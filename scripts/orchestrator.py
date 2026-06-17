#!/usr/bin/env python3
"""
Orchestrator
Runs all enrichment scripts on a CSV and combines results.
Processes all phases per-entry for better API rate limit handling.
Supports resuming from a previous run.
"""

import pandas as pd
import sys
import os
import time
import asyncio
import glob
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# Load .env from project root
project_root = Path(__file__).parent.parent
load_dotenv(project_root / '.env')

# Import the checker functions
from wordpress_detector import detect_tech_stack, normalize_url
from pagespeed_checker import get_pagespeed_score
from traffic_checker import check_signal_2, clean_domain
from column_utils import (
    get_website_column, get_company_column, get_value,
    has_traffic_data, extract_existing_traffic_data, parse_traffic_value,
    print_detected_columns
)
from grader_fields import write_annotated_csv, read_annotated_csv
from ai_readiness import assess_ai_readiness, ai_readiness_defaults, AI_READINESS_FIELDS
from accessibility import accessibility_defaults, AXE_FIELDS
from security_check import assess_security, security_defaults, SECURITY_FIELDS
from page_signals import page_signals_defaults, PAGE_SIGNAL_FIELDS

# Save progress every N entries
SAVE_INTERVAL = 5

# Extra PageSpeed-derived fields (Lighthouse SEO/a11y/best-practices + CrUX field data).
# All come free from the same PageSpeed call. Listed once so the result schema, the
# save/load column lists, and the friendly-name map stay in sync.
#
# Two groups, captured differently:
#  - LAB category scores/issues are essentially form-factor-agnostic; we prefer the
#    mobile call but fall back to desktop if mobile errored (don't lose them silently).
#  - CrUX FIELD data is real-user data that DIFFERS by form factor; we only take the
#    mobile dataset (mobile-first) and leave it blank if the mobile call failed, rather
#    than mislabel desktop real-user data as mobile.
PAGESPEED_LAB_CATEGORY_FIELDS = (
    'seo_score', 'accessibility_score', 'best_practices_score',
    'seo_issues', 'accessibility_issues', 'best_practices_issues',
)
PAGESPEED_CRUX_FIELDS = (
    'crux_source', 'cwv_pass',
    'field_lcp', 'field_lcp_rating', 'field_inp', 'field_inp_rating',
    'field_cls', 'field_cls_rating', 'field_fcp', 'field_fcp_rating',
    'field_ttfb', 'field_ttfb_rating',
)
# Desktop CrUX field data lives in parallel '_desktop'-suffixed columns. The desktop
# PageSpeed call already runs; we just keep its (desktop-specific) real-user data so
# mobile-vs-desktop gaps are visible and desktop-search ranking risk is captured.
PAGESPEED_CRUX_FIELDS_DESKTOP = tuple(f + '_desktop' for f in PAGESPEED_CRUX_FIELDS)
PAGESPEED_EXTRA_FIELDS = (PAGESPEED_LAB_CATEGORY_FIELDS
                          + PAGESPEED_CRUX_FIELDS
                          + PAGESPEED_CRUX_FIELDS_DESKTOP)


def _pagespeed_extra_defaults():
    """Default (empty) values for the extra PageSpeed fields. Strings for the
    issue / crux_source / *_rating text columns, None for numeric/boolean columns."""
    issue_fields = {'seo_issues', 'accessibility_issues', 'best_practices_issues'}
    out = {}
    for f in PAGESPEED_EXTRA_FIELDS:
        is_text = f in issue_fields or 'crux_source' in f or '_rating' in f
        out[f] = '' if is_text else None
    return out


def flag_entry(result):
    """
    Check an entry for anomalies and data quality issues.
    Returns (flag_count, flag_reasons) tuple.

    Flags:
    - Zero scores (content=0 or design=0) when not an error page
    - Perfect 100 scores (suspicious)
    - Missing PageSpeed data (both mobile and desktop None)
    - Missing traffic data
    - Error pages (404, maintenance, etc.)
    - No valid URL
    - Any enrichment errors
    - Extreme LLM scores (all 1s or all 10s)
    - Missing grading data when expected
    """
    flags = []

    # Page validity gate abstained: not a gradeable page (parked/redirect/acquired/
    # blocked/mismatch/etc.). A single clean flag; the entry is excluded from
    # ranking and is NOT a grading failure, so skip the other checks.
    if result.get('letter_grade') == 'INVALID':
        state = (result.get('page_state') or 'unknown').lower()
        return 1, f"invalid_page:{state}"

    # Check for error page (flag but expected)
    if result.get('is_error_page'):
        error_type = result.get('error_type', 'unknown')
        flags.append(f"error_page:{error_type}")

    # Check for no valid URL
    if 'No valid URL' in str(result.get('enrichment_errors', '')):
        flags.append("no_url")

    # Check for enrichment errors (other than no URL)
    errors = result.get('enrichment_errors', '')
    if errors and 'No valid URL' not in errors:
        # Summarize error types
        if 'Tech:' in errors:
            flags.append("tech_error")
        if 'Mobile:' in errors:
            flags.append("pagespeed_mobile_error")
        if 'Desktop:' in errors:
            flags.append("pagespeed_desktop_error")
        if 'Grader:' in errors:
            flags.append("grader_error")

    # Check for missing PageSpeed data (both mobile AND desktop missing)
    mobile_ps = result.get('pagespeed_mobile')
    desktop_ps = result.get('pagespeed_desktop')
    if mobile_ps is None and desktop_ps is None:
        # Only flag if there's no error already explaining this
        if 'pagespeed_mobile_error' not in flags and 'pagespeed_desktop_error' not in flags:
            flags.append("missing_pagespeed")

    # Check for missing CrUX field data (real-user Core Web Vitals). This is NOT a fetch
    # error and is NOT retryable — the PageSpeed call succeeds (HTTP 200) but the origin
    # simply isn't in Google's CrUX dataset (too little qualifying Chrome traffic). It must
    # still be VISIBLE, not silently ignored: lab scores alone are a single synthetic load,
    # whereas field data is what Google actually ranks on. Only flag when lab data DID come
    # back (otherwise missing_pagespeed already covers a total fetch failure).
    def _is_empty(v):
        return v is None or (isinstance(v, float) and v != v) or str(v).strip() in ('', 'None', 'nan')
    have_lab = mobile_ps is not None or desktop_ps is not None
    if have_lab:
        field_mobile_missing = _is_empty(result.get('field_lcp'))
        field_desktop_missing = _is_empty(result.get('field_lcp_desktop'))
        if field_mobile_missing and field_desktop_missing:
            flags.append("no_crux_field_data")          # no real-user data at all (origin not in CrUX)
        elif field_mobile_missing:
            flags.append("no_crux_field_data_mobile")    # mobile is the ranking-relevant form factor

    # Check for missing traffic data
    if result.get('monthly_visits') is None:
        flags.append("missing_traffic")

    # Check for zero content score (when NOT an error page)
    content_score = result.get('content_score')
    if content_score is not None and content_score == 0 and not result.get('is_error_page'):
        flags.append("content_score_zero")

    # Check for zero design score (when NOT an error page)
    design_score = result.get('design_score')
    if design_score is not None and design_score == 0 and not result.get('is_error_page'):
        flags.append("design_score_zero")

    # Check for perfect 100 scores (suspicious - very rare legitimately)
    if content_score is not None and content_score == 100:
        flags.append("content_score_perfect")
    if design_score is not None and design_score == 100:
        flags.append("design_score_perfect")

    # Check for extreme LLM dimension scores (all 1s or all 10s)
    clarity = result.get('clarity')
    substance = result.get('substance')
    credibility = result.get('credibility')
    persuasiveness = result.get('persuasiveness')

    if all(s is not None for s in [clarity, substance, credibility, persuasiveness]):
        if all(s == 1 for s in [clarity, substance, credibility, persuasiveness]):
            flags.append("llm_all_ones")
        elif all(s == 10 for s in [clarity, substance, credibility, persuasiveness]):
            flags.append("llm_all_tens")

    # Check for missing grading data when we have a screenshot (partial grading failure)
    screenshot_path = result.get('screenshot_path', '')
    if screenshot_path and not result.get('is_error_page'):
        if content_score is None:
            flags.append("missing_content_score")
        if design_score is None:
            flags.append("missing_design_score")

    # Check for missing letter grade when we have scores
    if content_score is not None and design_score is not None:
        if not result.get('letter_grade'):
            flags.append("missing_letter_grade")

    # Calculate flag count and reasons string
    flag_count = len(flags)
    flag_reasons = '; '.join(flags) if flags else ''

    return flag_count, flag_reasons


def find_latest_enrichment(data_dir):
    """
    Find the most recent enriched_*.csv file in the data directory.
    Returns (filepath, timestamp) or (None, None) if not found.
    """
    pattern = str(data_dir / 'enriched_*.csv')
    files = glob.glob(pattern)
    if not files:
        return None, None

    # Sort by modification time, most recent first
    latest = max(files, key=os.path.getmtime)
    mtime = datetime.fromtimestamp(os.path.getmtime(latest))
    return latest, mtime


def load_existing_results(enriched_path):
    """
    Load existing results from a previously saved enriched CSV.
    Returns a list of result dicts and the count of fully processed entries.
    """
    df = read_annotated_csv(enriched_path)
    results = []
    last_processed_idx = -1

    for idx, row in df.iterrows():
        # Check if this row has grading data (letter_grade is not empty)
        has_grade = pd.notna(row.get('letter_grade')) and str(row.get('letter_grade', '')).strip() != ''

        result = {
            'tech_stack': row.get('tech_stack', '') if pd.notna(row.get('tech_stack')) else '',
            'all_tech_detected': row.get('all_tech_detected', '') if pd.notna(row.get('all_tech_detected')) else '',
            'is_wordpress': bool(row.get('is_wordpress', False)),
            'marketing_tools': row.get('marketing_tools', '') if pd.notna(row.get('marketing_tools')) else '',
            'ad_pixels': row.get('ad_pixels', '') if pd.notna(row.get('ad_pixels')) else '',
            'has_premium_analytics': bool(row.get('has_premium_analytics', False)),
            'pagespeed_mobile': row.get('pagespeed_mobile') if pd.notna(row.get('pagespeed_mobile')) else None,
            'pagespeed_desktop': row.get('pagespeed_desktop') if pd.notna(row.get('pagespeed_desktop')) else None,
            'mobile_fcp': row.get('mobile_fcp') if pd.notna(row.get('mobile_fcp')) else None,
            'mobile_lcp': row.get('mobile_lcp') if pd.notna(row.get('mobile_lcp')) else None,
            'mobile_cls': row.get('mobile_cls') if pd.notna(row.get('mobile_cls')) else None,
            'desktop_fcp': row.get('desktop_fcp') if pd.notna(row.get('desktop_fcp')) else None,
            'desktop_lcp': row.get('desktop_lcp') if pd.notna(row.get('desktop_lcp')) else None,
            'desktop_cls': row.get('desktop_cls') if pd.notna(row.get('desktop_cls')) else None,
            **{f: (row.get(f) if pd.notna(row.get(f)) else _pagespeed_extra_defaults()[f])
               for f in PAGESPEED_EXTRA_FIELDS},
            **{f: (row.get(f) if pd.notna(row.get(f)) else ai_readiness_defaults()[f])
               for f in AI_READINESS_FIELDS},
            **{f: (row.get(f) if pd.notna(row.get(f)) else accessibility_defaults()[f])
               for f in AXE_FIELDS},
            **{f: (row.get(f) if pd.notna(row.get(f)) else page_signals_defaults()[f])
               for f in PAGE_SIGNAL_FIELDS},
            **{f: (row.get(f) if pd.notna(row.get(f)) else security_defaults()[f])
               for f in SECURITY_FIELDS},
            'monthly_visits': row.get('monthly_visits') if pd.notna(row.get('monthly_visits')) else None,
            'global_rank': row.get('global_rank') if pd.notna(row.get('global_rank')) else None,
            'bounce_rate': row.get('bounce_rate') if pd.notna(row.get('bounce_rate')) else None,
            'pages_per_visit': row.get('pages_per_visit') if pd.notna(row.get('pages_per_visit')) else None,
            'traffic_source_direct': row.get('traffic_source_direct') if pd.notna(row.get('traffic_source_direct')) else None,
            'traffic_source_search': row.get('traffic_source_search') if pd.notna(row.get('traffic_source_search')) else None,
            'traffic_source_social': row.get('traffic_source_social') if pd.notna(row.get('traffic_source_social')) else None,
            'top_country': row.get('top_country') if pd.notna(row.get('top_country')) else None,
            'is_signal_2_traffic': bool(row.get('is_signal_2_traffic', False)),
            'content_score': row.get('content_score') if pd.notna(row.get('content_score')) else None,
            'design_score': row.get('design_score') if pd.notna(row.get('design_score')) else None,
            'total_grade_score': row.get('total_grade_score') if pd.notna(row.get('total_grade_score')) else None,
            'letter_grade': row.get('letter_grade', '') if pd.notna(row.get('letter_grade')) else '',
            'grade_analysis': row.get('grade_analysis', '') if pd.notna(row.get('grade_analysis')) else '',
            'weak_areas': row.get('weak_areas', '') if pd.notna(row.get('weak_areas')) else '',
            'strong_areas': row.get('strong_areas', '') if pd.notna(row.get('strong_areas')) else '',
            'screenshot_path': row.get('screenshot_path', '') if pd.notna(row.get('screenshot_path')) else '',
            'design_comment': row.get('design_comment', '') if pd.notna(row.get('design_comment')) else '',
            'content_analysis': row.get('content_analysis', '') if pd.notna(row.get('content_analysis')) else '',
            'programmatic_score': row.get('programmatic_score') if pd.notna(row.get('programmatic_score')) else None,
            'llm_score': row.get('llm_score') if pd.notna(row.get('llm_score')) else None,
            'clarity': row.get('clarity') if pd.notna(row.get('clarity')) else None,
            'substance': row.get('substance') if pd.notna(row.get('substance')) else None,
            'credibility': row.get('credibility') if pd.notna(row.get('credibility')) else None,
            'persuasiveness': row.get('persuasiveness') if pd.notna(row.get('persuasiveness')) else None,
            'depth': row.get('depth') if pd.notna(row.get('depth')) else None,
            'content_reasoning': row.get('content_reasoning', '') if pd.notna(row.get('content_reasoning')) else '',
            'content_source': row.get('content_source', '') if pd.notna(row.get('content_source')) else '',
            'content_word_count': row.get('content_word_count') if pd.notna(row.get('content_word_count')) else None,
            # Design sub-dimensions + ensemble diagnostics
            'design_reasoning': row.get('design_reasoning', '') if pd.notna(row.get('design_reasoning')) else '',
            'design_typography': row.get('design_typography') if pd.notna(row.get('design_typography')) else None,
            'design_spacing': row.get('design_spacing') if pd.notna(row.get('design_spacing')) else None,
            'design_color': row.get('design_color') if pd.notna(row.get('design_color')) else None,
            'design_hierarchy': row.get('design_hierarchy') if pd.notna(row.get('design_hierarchy')) else None,
            'design_polish': row.get('design_polish') if pd.notna(row.get('design_polish')) else None,
            'design_score_runs': row.get('design_score_runs', '') if pd.notna(row.get('design_score_runs')) else '',
            'design_score_spread': row.get('design_score_spread') if pd.notna(row.get('design_score_spread')) else None,
            # Page validity gate
            'page_state': row.get('page_state', '') if pd.notna(row.get('page_state')) else '',
            'gate_confidence': row.get('gate_confidence') if pd.notna(row.get('gate_confidence')) else None,
            'gate_reason': row.get('gate_reason', '') if pd.notna(row.get('gate_reason')) else '',
            'detected_platform': row.get('detected_platform', '') if pd.notna(row.get('detected_platform')) else '',
            'gate_source': row.get('gate_source', '') if pd.notna(row.get('gate_source')) else '',
            'is_error_page': bool(row.get('is_error_page', False)),
            'error_type': row.get('error_type', '') if pd.notna(row.get('error_type')) else '',
            'enrichment_errors': row.get('enrichment_errors', '') if pd.notna(row.get('enrichment_errors')) else ''
        }
        results.append(result)

        if has_grade:
            last_processed_idx = idx

    return results, last_processed_idx


def prompt_resume_or_fresh(enriched_path, last_processed, total):
    """
    Ask user whether to resume from previous run or start fresh.
    Returns: 'resume', 'fresh', or 'quit'
    """
    print(f"\n{'='*60}")
    print("PREVIOUS RUN DETECTED")
    print(f"{'='*60}")
    print(f"  File: {enriched_path}")
    print(f"  Progress: {last_processed + 1}/{total} entries completed")
    print(f"  Remaining: {total - last_processed - 1} entries")
    print()

    while True:
        print("Options:")
        print("  [R] Resume from where we left off")
        print("  [F] Start fresh (overwrite previous progress)")
        print("  [Q] Quit")
        print()
        choice = input("Your choice (R/F/Q): ").strip().upper()

        if choice == 'R':
            return 'resume'
        elif choice == 'F':
            confirm = input("Are you sure? This will overwrite previous progress. (y/n): ").strip().lower()
            if confirm == 'y':
                return 'fresh'
        elif choice == 'Q':
            return 'quit'
        else:
            print("Invalid choice. Please enter R, F, or Q.\n")


def save_progress(df, output_path, results, processed_count):
    """
    Save intermediate results to CSV.
    """
    total = len(df)
    df_copy = df.copy()

    # Helper to get value from results or default
    def get_result_value(key, default=None):
        values = []
        for i in range(total):
            if i < len(results):
                values.append(results[i].get(key, default))
            else:
                values.append(default)
        return values

    # Build ALL enrichment columns into one dict and attach in a single assign().
    # (Assigning ~80 columns one-by-one fragments the DataFrame and spams
    # PerformanceWarning on every save — painful on the 999-row run.)
    new_cols = {}

    # Tech results
    new_cols['tech_stack'] = get_result_value('tech_stack', '')
    new_cols['all_tech_detected'] = get_result_value('all_tech_detected', '')
    new_cols['is_wordpress'] = get_result_value('is_wordpress', False)
    new_cols['marketing_tools'] = get_result_value('marketing_tools', '')
    new_cols['ad_pixels'] = get_result_value('ad_pixels', '')
    new_cols['has_premium_analytics'] = get_result_value('has_premium_analytics', False)

    # PageSpeed results
    new_cols['pagespeed_mobile'] = get_result_value('pagespeed_mobile')
    new_cols['pagespeed_desktop'] = get_result_value('pagespeed_desktop')
    new_cols['mobile_fcp'] = get_result_value('mobile_fcp')
    new_cols['mobile_lcp'] = get_result_value('mobile_lcp')
    new_cols['mobile_cls'] = get_result_value('mobile_cls')
    new_cols['desktop_fcp'] = get_result_value('desktop_fcp')
    new_cols['desktop_lcp'] = get_result_value('desktop_lcp')
    new_cols['desktop_cls'] = get_result_value('desktop_cls')

    # Extra Lighthouse categories + CrUX field data (from the same PageSpeed call)
    _extra_defaults = _pagespeed_extra_defaults()
    for f in PAGESPEED_EXTRA_FIELDS:
        new_cols[f] = get_result_value(f, _extra_defaults[f])

    # AI-Readiness signals
    _ai_defaults = ai_readiness_defaults()
    for f in AI_READINESS_FIELDS:
        new_cols[f] = get_result_value(f, _ai_defaults[f])

    # Accessibility (axe-core) signals
    _axe_defaults = accessibility_defaults()
    for f in AXE_FIELDS:
        new_cols[f] = get_result_value(f, _axe_defaults[f])

    # Network-pass signals (page weight, trackers, cookies-before-consent)
    _ps_defaults = page_signals_defaults()
    for f in PAGE_SIGNAL_FIELDS:
        new_cols[f] = get_result_value(f, _ps_defaults[f])

    # Security & SSL signals
    _sec_defaults = security_defaults()
    for f in SECURITY_FIELDS:
        new_cols[f] = get_result_value(f, _sec_defaults[f])

    # Traffic results
    new_cols['monthly_visits'] = get_result_value('monthly_visits')
    new_cols['global_rank'] = get_result_value('global_rank')
    new_cols['bounce_rate'] = get_result_value('bounce_rate')
    new_cols['pages_per_visit'] = get_result_value('pages_per_visit')
    new_cols['traffic_source_direct'] = get_result_value('traffic_source_direct')
    new_cols['traffic_source_search'] = get_result_value('traffic_source_search')
    new_cols['traffic_source_social'] = get_result_value('traffic_source_social')
    new_cols['top_country'] = get_result_value('top_country')
    new_cols['is_signal_2_traffic'] = get_result_value('is_signal_2_traffic', False)

    # Grading results
    new_cols['content_score'] = get_result_value('content_score')
    new_cols['design_score'] = get_result_value('design_score')
    new_cols['total_grade_score'] = get_result_value('total_grade_score')
    new_cols['letter_grade'] = get_result_value('letter_grade', '')
    new_cols['grade_analysis'] = get_result_value('grade_analysis', '')
    new_cols['weak_areas'] = get_result_value('weak_areas', '')
    new_cols['strong_areas'] = get_result_value('strong_areas', '')
    new_cols['screenshot_path'] = get_result_value('screenshot_path', '')
    new_cols['design_comment'] = get_result_value('design_comment', '')
    new_cols['content_analysis'] = get_result_value('content_analysis', '')
    new_cols['programmatic_score'] = get_result_value('programmatic_score')
    new_cols['llm_score'] = get_result_value('llm_score')
    new_cols['clarity'] = get_result_value('clarity')
    new_cols['substance'] = get_result_value('substance')
    new_cols['credibility'] = get_result_value('credibility')
    new_cols['persuasiveness'] = get_result_value('persuasiveness')
    new_cols['depth'] = get_result_value('depth')
    new_cols['content_reasoning'] = get_result_value('content_reasoning', '')
    new_cols['content_source'] = get_result_value('content_source', '')
    new_cols['content_word_count'] = get_result_value('content_word_count')
    # Design sub-dimensions + ensemble diagnostics
    new_cols['design_reasoning'] = get_result_value('design_reasoning', '')
    new_cols['design_typography'] = get_result_value('design_typography')
    new_cols['design_spacing'] = get_result_value('design_spacing')
    new_cols['design_color'] = get_result_value('design_color')
    new_cols['design_hierarchy'] = get_result_value('design_hierarchy')
    new_cols['design_polish'] = get_result_value('design_polish')
    new_cols['design_score_runs'] = get_result_value('design_score_runs', '')
    new_cols['design_score_spread'] = get_result_value('design_score_spread')
    # Page validity gate
    new_cols['page_state'] = get_result_value('page_state', '')
    new_cols['gate_confidence'] = get_result_value('gate_confidence')
    new_cols['gate_reason'] = get_result_value('gate_reason', '')
    new_cols['detected_platform'] = get_result_value('detected_platform', '')
    new_cols['gate_source'] = get_result_value('gate_source', '')
    new_cols['is_error_page'] = get_result_value('is_error_page', False)
    new_cols['error_type'] = get_result_value('error_type', '')
    new_cols['enrichment_errors'] = get_result_value('enrichment_errors', '')

    # Flagging columns - computed from results
    flag_counts = []
    flag_reasons_list = []
    for i in range(total):
        if i < len(results):
            count, reasons = flag_entry(results[i])
            flag_counts.append(count)
            flag_reasons_list.append(reasons)
        else:
            flag_counts.append(0)
            flag_reasons_list.append('')

    new_cols['flag_count'] = flag_counts
    new_cols['flag_reasons'] = flag_reasons_list

    # Build all enrichment columns as ONE block and concat once -> no fragmentation.
    # (df.assign / repeated df[col]= both insert column-by-column and warn.)
    enrich_df = pd.DataFrame(new_cols, index=df_copy.index)
    overlap = [c for c in enrich_df.columns if c in df_copy.columns]
    if overlap:
        df_copy = df_copy.drop(columns=overlap)
    df_copy = pd.concat([df_copy, enrich_df], axis=1)

    # Save (friendly column names + description header row)
    write_annotated_csv(df_copy, output_path)
    print(f"\n  [SAVED] Progress: {processed_count}/{total} entries → {output_path}\n")


def run_enrichment(input_path: str, output_path: str = None, limit: int = None, delay: float = 1.5, skip_traffic: bool = False, skip_grader: bool = False, auto_resume: bool = False):
    """
    Run all enrichment checks on a CSV.
    Processes all phases per-entry for better API rate limiting.

    Args:
        input_path: Path to input CSV with website/domain column
        output_path: Path for output CSV
        limit: Optional limit on number of rows to process (for testing)
        delay: Seconds to wait between requests
        skip_traffic: Skip traffic check (uses Apify API credits) - ignored if CSV has traffic data
        skip_grader: Skip website grading (uses Gemini API credits)
        auto_resume: If True, automatically resume without prompting
    """
    # Read input CSV
    df = pd.read_csv(input_path)

    # Auto-detect columns
    try:
        website_col = get_website_column(df)
        company_col = get_company_column(df)
        print(f"Detected website column: '{website_col}'")
        print(f"Detected company column: '{company_col}'" if company_col else "Company column: not found (using 'Unknown')")
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    # Check if CSV already has traffic data
    csv_has_traffic = has_traffic_data(df)
    if csv_has_traffic:
        print("CSV already contains traffic data - will use existing data instead of Apify")

    # Apply limit if specified
    if limit:
        df = df.head(limit)
        print(f"Limited to first {limit} entries for testing")

    total = len(df)

    # Check for existing enrichment to resume
    data_dir = project_root / 'data'
    data_dir.mkdir(exist_ok=True)

    existing_path, existing_mtime = find_latest_enrichment(data_dir)
    results = []
    start_idx = 0
    resume_mode = False

    if existing_path and not output_path:
        # Load existing results to check progress
        existing_results, last_processed = load_existing_results(existing_path)

        # Only offer resume if there's actual progress and not all entries are done
        if last_processed >= 0 and last_processed < total - 1:
            if auto_resume:
                choice = 'resume'
                print(f"\nAuto-resuming from entry {last_processed + 2}/{total}...")
            else:
                choice = prompt_resume_or_fresh(existing_path, last_processed, total)

            if choice == 'quit':
                print("Exiting.")
                sys.exit(0)
            elif choice == 'resume':
                results = existing_results
                start_idx = last_processed + 1
                output_path = existing_path  # Continue saving to same file
                resume_mode = True
                print(f"\nResuming from entry {start_idx + 1}/{total}...")
            else:
                # Fresh start
                pass
        elif last_processed >= total - 1:
            print(f"\nPrevious run is complete ({last_processed + 1}/{total} entries).")
            choice = input("Start a fresh run? (y/n): ").strip().lower()
            if choice != 'y':
                print("Exiting.")
                sys.exit(0)

    # Set default output path if not resuming
    if not output_path:
        input_file = Path(input_path)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = data_dir / f"enriched_{timestamp}.csv"

    print(f"\n{'='*60}")
    if resume_mode:
        print(f"RESUMING ENRICHMENT - {total - start_idx} remaining of {total} websites")
    else:
        print(f"ENRICHMENT RUN - {total} websites")
    print(f"{'='*60}\n")

    # Import grading functions if needed
    if not skip_grader:
        from website_grader import (
            capture_screenshot_and_content,
            grade_website,
        )

        screenshot_dir = project_root / 'screenshots'
        screenshot_dir.mkdir(exist_ok=True)
        api_key = os.getenv('GEMINI_API_KEY')
        jina_api_key = os.getenv('JINA_API_KEY')

        # Create log file for AI requests
        logs_dir = project_root / 'logs'
        logs_dir.mkdir(exist_ok=True)
        timestamp_log = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = logs_dir / f"ai_requests_{timestamp_log}.log"

        # Initialize log file
        with open(log_file, 'w', encoding='utf-8') as f:
            f.write(f"AI REQUEST LOG\n")
            f.write(f"Generated: {datetime.now().isoformat()}\n")
            f.write(f"Input file: {input_path}\n")
            f.write(f"Total entries: {total}\n")
            if resume_mode:
                f.write(f"Resuming from entry: {start_idx + 1}\n")
            f.write(f"{'='*80}\n")

        print(f"AI request log: {log_file}")

        if not api_key:
            print("Warning: GEMINI_API_KEY not found. Design scoring will be skipped.")

    # Process entries
    for idx, row in df.iterrows():
        # Skip already processed entries when resuming
        if idx < start_idx:
            continue

        url = row[website_col]
        company = row[company_col] if company_col else 'Unknown'

        print(f"[{idx + 1}/{total}] {company}")
        print(f"         URL: {url}")

        # Check for invalid/missing URL
        if pd.isna(url) or not url or str(url).strip() == '':
            print(f"         SKIPPED - No valid URL")
            skipped_result = {
                'tech_stack': '',
                'all_tech_detected': '',
                'is_wordpress': False,
                'marketing_tools': '',
                'ad_pixels': '',
                'has_premium_analytics': False,
                'pagespeed_mobile': None,
                'pagespeed_desktop': None,
                'mobile_fcp': None,
                'mobile_lcp': None,
                'mobile_cls': None,
                'desktop_fcp': None,
                'desktop_lcp': None,
                'desktop_cls': None,
                **_pagespeed_extra_defaults(),
                'monthly_visits': None,
                'global_rank': None,
                'bounce_rate': None,
                'pages_per_visit': None,
                'traffic_source_direct': None,
                'traffic_source_search': None,
                'traffic_source_social': None,
                'top_country': None,
                'is_signal_2_traffic': False,
                'content_score': None,
                'design_score': None,
                'total_grade_score': None,
                'letter_grade': '',
                'grade_analysis': '',
                'weak_areas': '',
                'strong_areas': '',
                'screenshot_path': '',
                'design_comment': '',
                'content_analysis': '',
                'programmatic_score': None,
                'llm_score': None,
                'clarity': None,
                'substance': None,
                'credibility': None,
                'persuasiveness': None,
                'content_word_count': None,
                'is_error_page': False,
                'error_type': '',
                **ai_readiness_defaults(),
                **accessibility_defaults(),
                **page_signals_defaults(),
                **security_defaults(),
                'enrichment_errors': 'No valid URL'
            }
            # Add/update at correct index
            if idx < len(results):
                results[idx] = skipped_result
            else:
                results.append(skipped_result)
            print()
            # Still check for save interval
            if (idx + 1) % SAVE_INTERVAL == 0:
                save_progress(df, output_path, results, idx + 1)
            continue

        # Initialize result dict for this entry
        entry_result = {
            'tech_stack': '',
            'all_tech_detected': '',
            'is_wordpress': False,
            'marketing_tools': '',
            'ad_pixels': '',
            'has_premium_analytics': False,
            'pagespeed_mobile': None,
            'pagespeed_desktop': None,
            'mobile_fcp': None,
            'mobile_lcp': None,
            'mobile_cls': None,
            'desktop_fcp': None,
            'desktop_lcp': None,
            'desktop_cls': None,
            **_pagespeed_extra_defaults(),
            'monthly_visits': None,
            'global_rank': None,
            'bounce_rate': None,
            'pages_per_visit': None,
            'traffic_source_direct': None,
            'traffic_source_search': None,
            'traffic_source_social': None,
            'top_country': None,
            'is_signal_2_traffic': False,
            'content_score': None,
            'design_score': None,
            'total_grade_score': None,
            'letter_grade': '',
            'grade_analysis': '',
            'weak_areas': '',
            'strong_areas': '',
            'screenshot_path': '',
            'design_comment': '',
            'content_analysis': '',
            'programmatic_score': None,
            'llm_score': None,
            'clarity': None,
            'substance': None,
            'credibility': None,
            'persuasiveness': None,
            'content_word_count': None,
            'is_error_page': False,
            'error_type': '',
            **ai_readiness_defaults(),
            **accessibility_defaults(),
            **page_signals_defaults(),
            **security_defaults(),
            'enrichment_errors': ''
        }

        errors = []

        # 1. Tech Stack Detection
        print(f"         Tech: ", end='', flush=True)
        tech_result = detect_tech_stack(url)

        if tech_result['error']:
            print(f"Error - {tech_result['error']}")
            errors.append(f"Tech: {tech_result['error']}")
        else:
            entry_result['tech_stack'] = tech_result['primary_tech']
            entry_result['all_tech_detected'] = ', '.join(tech_result['detected_tech']) if tech_result['detected_tech'] else ''
            entry_result['is_wordpress'] = tech_result['is_wordpress']
            entry_result['marketing_tools'] = ', '.join(tech_result['marketing_tools']) if tech_result['marketing_tools'] else ''
            entry_result['ad_pixels'] = ', '.join(tech_result['ad_pixels']) if tech_result['ad_pixels'] else ''
            entry_result['has_premium_analytics'] = tech_result['has_premium_analytics']

            print(f"{tech_result['primary_tech']}", end='')
            if len(tech_result['detected_tech']) > 1:
                others = [t for t in tech_result['detected_tech'] if t != tech_result['primary_tech']]
                print(f" (also: {', '.join(others)})")
            else:
                print()

            # Print marketing tools if found
            if tech_result['marketing_tools']:
                premium_marker = " [PREMIUM]" if tech_result['has_premium_analytics'] else ""
                print(f"         Marketing: {', '.join(tech_result['marketing_tools'])}{premium_marker}")

            # Print ad pixels if found
            if tech_result['ad_pixels']:
                print(f"         Ads: {', '.join(tech_result['ad_pixels'])}")

        time.sleep(delay)

        # 2. PageSpeed - Mobile
        print(f"         Mobile:    ", end='', flush=True)
        mobile = get_pagespeed_score(url, strategy='mobile')

        if mobile['error']:
            print(f"Error - {mobile['error']}")
            errors.append(f"Mobile: {mobile['error']}")
        else:
            entry_result['pagespeed_mobile'] = mobile['score']
            entry_result['mobile_fcp'] = mobile['fcp']
            entry_result['mobile_lcp'] = mobile['lcp']
            entry_result['mobile_cls'] = mobile['cls']
            # Extra Lighthouse categories + MOBILE CrUX field data (free from the same call).
            # Only mobile-present keys here — the *_desktop keys come from the desktop
            # call below and do NOT exist on the mobile result dict.
            for k in PAGESPEED_LAB_CATEGORY_FIELDS + PAGESPEED_CRUX_FIELDS:
                entry_result[k] = mobile[k]
            print(f"{mobile['score']}/100 (LCP: {mobile['lcp']}s)")
            extra = []
            if mobile['seo_score'] is not None:
                extra.append(f"SEO {mobile['seo_score']}")
            if mobile['accessibility_score'] is not None:
                extra.append(f"A11y {mobile['accessibility_score']}")
            if mobile['best_practices_score'] is not None:
                extra.append(f"BP {mobile['best_practices_score']}")
            if mobile['cwv_pass'] is not None:
                extra.append("CWV " + ("pass" if mobile['cwv_pass'] else "FAIL")
                             + f" [{mobile['crux_source']}]")
            if extra:
                print(f"                    {' | '.join(extra)}")

        time.sleep(delay)

        # 3. PageSpeed - Desktop
        print(f"         Desktop:   ", end='', flush=True)
        desktop = get_pagespeed_score(url, strategy='desktop')

        if desktop['error']:
            print(f"Error - {desktop['error']}")
            errors.append(f"Desktop: {desktop['error']}")
        else:
            entry_result['pagespeed_desktop'] = desktop['score']
            entry_result['desktop_fcp'] = desktop['fcp']
            entry_result['desktop_lcp'] = desktop['lcp']
            entry_result['desktop_cls'] = desktop['cls']
            print(f"{desktop['score']}/100 (LCP: {desktop['lcp']}s)")
            # Desktop CrUX field data -> parallel '_desktop' columns (desktop real users).
            for f in PAGESPEED_CRUX_FIELDS:
                entry_result[f + '_desktop'] = desktop[f]
            # Fallback: if the mobile call failed, don't lose the (form-factor-agnostic)
            # Lighthouse category scores/issues — take them from the desktop response.
            # Mobile CrUX field data is intentionally NOT backfilled (it's mobile-specific).
            if mobile['error']:
                for k in PAGESPEED_LAB_CATEGORY_FIELDS:
                    entry_result[k] = desktop[k]

        # 4. Traffic Data (from CSV or skip)
        if csv_has_traffic:
            traffic_data = extract_existing_traffic_data(row, df)
            entry_result['monthly_visits'] = traffic_data.get('monthly_visits')
            entry_result['global_rank'] = traffic_data.get('global_rank')
            entry_result['bounce_rate'] = traffic_data.get('bounce_rate')
            entry_result['pages_per_visit'] = traffic_data.get('pages_per_visit')
            entry_result['traffic_source_direct'] = traffic_data.get('traffic_source_direct')
            entry_result['traffic_source_search'] = traffic_data.get('traffic_source_search')
            entry_result['traffic_source_social'] = traffic_data.get('traffic_source_social')
            entry_result['top_country'] = traffic_data.get('top_country')
            entry_result['is_signal_2_traffic'] = check_signal_2(traffic_data.get('monthly_visits'))

            visits = traffic_data.get('monthly_visits')
            if visits is not None:
                signal_marker = " [SIGNAL 2]" if entry_result['is_signal_2_traffic'] else ""
                print(f"         Traffic:   {visits:,} visits/month{signal_marker}")
            else:
                print(f"         Traffic:   No data in CSV")

        # 5. Website Grading (screenshot + content + design analysis)
        capture_result = None
        if not skip_grader:
            print(f"         Grading:   ", end='', flush=True)

            # Capture screenshot
            semaphore = asyncio.Semaphore(1)  # Single capture
            capture_result = asyncio.run(capture_screenshot_and_content(url, screenshot_dir, semaphore))

            # Accessibility (axe-core) + network-pass signals are produced during capture.
            for f in AXE_FIELDS:
                if f in capture_result:
                    entry_result[f] = capture_result[f]
            for f in PAGE_SIGNAL_FIELDS:
                if f in capture_result:
                    entry_result[f] = capture_result[f]

            # Grade website
            grader_result = grade_website(
                url=url,
                pagespeed_mobile=entry_result['pagespeed_mobile'],
                screenshot_dir=screenshot_dir,
                api_key=api_key,
                capture_result=capture_result,
                log_file=log_file,
                jina_api_key=jina_api_key,
                company_name=str(company) if company is not None else ''
            )

            if grader_result.get('error'):
                print(f"Error - {grader_result['error'][:40]}")
                errors.append(f"Grader: {grader_result['error']}")
            else:
                entry_result['content_score'] = grader_result.get('content_score')
                entry_result['design_score'] = grader_result.get('design_score')
                entry_result['total_grade_score'] = grader_result.get('total_grade_score')
                entry_result['letter_grade'] = grader_result.get('letter_grade', '')
                entry_result['grade_analysis'] = grader_result.get('grade_analysis', '')
                entry_result['weak_areas'] = grader_result.get('weak_areas', '')
                entry_result['strong_areas'] = grader_result.get('strong_areas', '')
                entry_result['screenshot_path'] = grader_result.get('screenshot_path', '')
                entry_result['design_comment'] = grader_result.get('design_comment', '')
                entry_result['content_analysis'] = grader_result.get('content_analysis', '')
                entry_result['programmatic_score'] = grader_result.get('programmatic_score')
                entry_result['llm_score'] = grader_result.get('llm_score')
                entry_result['clarity'] = grader_result.get('clarity')
                entry_result['substance'] = grader_result.get('substance')
                entry_result['credibility'] = grader_result.get('credibility')
                entry_result['persuasiveness'] = grader_result.get('persuasiveness')
                entry_result['depth'] = grader_result.get('depth')
                entry_result['content_reasoning'] = grader_result.get('content_reasoning', '')
                entry_result['content_source'] = grader_result.get('content_source', '')
                entry_result['content_word_count'] = grader_result.get('content_word_count')
                # Design sub-dimensions + ensemble diagnostics
                entry_result['design_reasoning'] = grader_result.get('design_reasoning', '')
                entry_result['design_typography'] = grader_result.get('design_typography')
                entry_result['design_spacing'] = grader_result.get('design_spacing')
                entry_result['design_color'] = grader_result.get('design_color')
                entry_result['design_hierarchy'] = grader_result.get('design_hierarchy')
                entry_result['design_polish'] = grader_result.get('design_polish')
                entry_result['design_score_runs'] = grader_result.get('design_score_runs', '')
                entry_result['design_score_spread'] = grader_result.get('design_score_spread')
                # Page validity gate
                entry_result['page_state'] = grader_result.get('page_state', '')
                entry_result['gate_confidence'] = grader_result.get('gate_confidence')
                entry_result['gate_reason'] = grader_result.get('gate_reason', '')
                entry_result['detected_platform'] = grader_result.get('detected_platform', '')
                entry_result['gate_source'] = grader_result.get('gate_source', '')
                entry_result['is_error_page'] = grader_result.get('is_error_page', False)
                entry_result['error_type'] = grader_result.get('error_type', '')

                grade = entry_result['letter_grade']
                score = entry_result['total_grade_score']
                if grade == 'INVALID':
                    print(f"INVALID ({grader_result.get('page_state', '')} via {grader_result.get('gate_source', '')})")
                else:
                    error_flag = " [ERROR PAGE]" if entry_result['is_error_page'] else ""
                    print(f"{grade} ({score}/100){error_flag}")

            time.sleep(delay)

        # 6. AI-Readiness (deterministic discoverability signals; no LLM)
        print(f"         AI-ready:  ", end='', flush=True)
        rendered_text = capture_result.get('page_text') if capture_result else None
        ar_result = assess_ai_readiness(url, rendered_text=rendered_text)
        for f in AI_READINESS_FIELDS:
            entry_result[f] = ar_result[f]
        if ar_result['ai_readiness_error'] and ar_result['ai_readiness_score'] is None:
            print(f"Error - {ar_result['ai_readiness_error'][:40]}")
            errors.append(f"AI-readiness: {ar_result['ai_readiness_error']}")
        else:
            ssr = ar_result['ssr_content_ratio']
            ssr_str = f" | {round(ssr*100)}% SSR" if ssr is not None else ""
            blocked = " | BLOCKS AI" if ar_result['robots_blocks_ai'] else ""
            print(f"{ar_result['ai_readiness_score']}/100{ssr_str}{blocked}")

        # 7. Security & SSL (deterministic; no browser)
        print(f"         Security:  ", end='', flush=True)
        sec_result = assess_security(url)
        for f in SECURITY_FIELDS:
            entry_result[f] = sec_result[f]
        if sec_result['security_error'] and sec_result['sec_header_grade'] == '':
            print(f"Error - {sec_result['security_error'][:40]}")
            errors.append(f"Security: {sec_result['security_error']}")
        else:
            exp = sec_result['ssl_days_to_expiry']
            exp_str = f" | cert {exp}d" if exp is not None else ""
            mc = " | MIXED CONTENT" if sec_result['mixed_content'] else ""
            print(f"headers {sec_result['sec_header_grade']}{exp_str}{mc}")

        # Collect errors
        entry_result['enrichment_errors'] = '; '.join(errors) if errors else ''

        # Add/update results at the correct index
        if idx < len(results):
            # Resume mode: update existing entry
            results[idx] = entry_result
        else:
            # Fresh mode: append new entry
            results.append(entry_result)

        print()  # Blank line between entries

        # Save progress every SAVE_INTERVAL entries
        if (idx + 1) % SAVE_INTERVAL == 0:
            save_progress(df, output_path, results, idx + 1)

    # Final save
    print(f"\n  [FINAL] Saving all results...")
    save_progress(df, output_path, results, total)

    # Print summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"Output saved to: {output_path}")
    print()

    # Tech stack breakdown
    tech_counts = {}
    for r in results:
        tech = r.get('tech_stack')
        if tech:
            tech_counts[tech] = tech_counts.get(tech, 0) + 1

    print("Tech Stack Breakdown:")
    for tech, count in sorted(tech_counts.items(), key=lambda x: -x[1]):
        print(f"  {tech}: {count}")
    print()

    wp_count = sum(1 for r in results if r.get('is_wordpress'))
    print(f"WordPress sites: {wp_count}/{total}")

    # Marketing summary
    premium_count = sum(1 for r in results if r.get('has_premium_analytics'))
    has_ads_count = sum(1 for r in results if r.get('ad_pixels'))
    has_marketing_count = sum(1 for r in results if r.get('marketing_tools'))
    print(f"Sites with marketing tools: {has_marketing_count}/{total}")
    print(f"Sites with premium analytics (Signal 3): {premium_count}/{total}")
    print(f"Sites running ads: {has_ads_count}/{total}")
    print()

    mobile_scores = [r['pagespeed_mobile'] for r in results if r.get('pagespeed_mobile') is not None]
    desktop_scores = [r['pagespeed_desktop'] for r in results if r.get('pagespeed_desktop') is not None]

    if mobile_scores:
        avg_mobile = sum(mobile_scores) / len(mobile_scores)
        poor_mobile = sum(1 for s in mobile_scores if s < 50)
        print(f"Mobile avg: {avg_mobile:.1f}/100")
        print(f"Mobile < 50 (Signal 2 targets): {poor_mobile}/{len(mobile_scores)}")

    if desktop_scores:
        avg_desktop = sum(desktop_scores) / len(desktop_scores)
        print(f"Desktop avg: {avg_desktop:.1f}/100")
    print()

    # Traffic summary
    visits_data = []
    for r in results:
        v = r.get('monthly_visits')
        if v is not None:
            try:
                visits_data.append(int(v))
            except (ValueError, TypeError):
                pass
    signal_2_traffic = sum(1 for r in results if r.get('is_signal_2_traffic'))
    print(f"With traffic data: {len(visits_data)}/{total}")
    print(f"50K+ monthly visits: {signal_2_traffic}/{total}")
    if visits_data:
        avg_visits = sum(visits_data) / len(visits_data)
        print(f"Average monthly visits: {avg_visits:,.0f}")

    # Full Signal 2 (WordPress + poor mobile + high traffic)
    full_signal_2 = sum(
        1 for r in results
        if r.get('is_wordpress')
        and r.get('pagespeed_mobile') is not None
        and r.get('pagespeed_mobile') < 50
        and r.get('is_signal_2_traffic')
    )
    print(f"\n*** FULL SIGNAL 2 (WP + Mobile<50 + 50K+ visits): {full_signal_2}/{total} ***")
    print()

    # Grading summary
    if not skip_grader:
        grades = [r['letter_grade'] for r in results if r.get('letter_grade')]
        if grades:
            grade_counts = {}
            for g in grades:
                grade_counts[g] = grade_counts.get(g, 0) + 1
            print("Grade Distribution:")
            for grade in ['A+', 'A', 'A-', 'B+', 'B', 'B-', 'C+', 'C', 'C-', 'D+', 'D', 'D-', 'F']:
                if grade in grade_counts:
                    print(f"  {grade}: {grade_counts[grade]}")
            print()

        content_scores = [r['content_score'] for r in results if r.get('content_score') is not None]
        design_scores = [r['design_score'] for r in results if r.get('design_score') is not None]
        total_scores = [r['total_grade_score'] for r in results if r.get('total_grade_score') is not None]

        if content_scores:
            print(f"Avg content score: {sum(content_scores)/len(content_scores):.1f}/100")
        if design_scores:
            print(f"Avg design score: {sum(design_scores)/len(design_scores):.1f}/100")
        if total_scores:
            print(f"Avg total score: {sum(total_scores)/len(total_scores):.1f}/100")
        print()

        # Common weak areas
        all_weak = []
        for r in results:
            if r.get('weak_areas'):
                all_weak.extend(r['weak_areas'].split(', '))
        if all_weak:
            weak_counts = {}
            for w in all_weak:
                if w:
                    weak_counts[w] = weak_counts.get(w, 0) + 1
            print("Most common weak areas:")
            for area, count in sorted(weak_counts.items(), key=lambda x: -x[1]):
                print(f"  {area}: {count} sites")
            print()

        # Error page count
        error_page_count = sum(1 for r in results if r.get('is_error_page'))
        if error_page_count:
            print(f"Error pages detected (404, maintenance, etc.): {error_page_count}/{total}")

    error_count = sum(1 for r in results if r.get('enrichment_errors'))
    print(f"Entries with errors: {error_count}/{total}")

    # Flagging summary
    print(f"\n{'='*60}")
    print("DATA QUALITY FLAGS")
    print(f"{'='*60}")

    # Compute flags for all results
    all_flags = {}
    flagged_count = 0
    for r in results:
        count, reasons = flag_entry(r)
        if count > 0:
            flagged_count += 1
            for flag in reasons.split('; '):
                if flag:
                    all_flags[flag] = all_flags.get(flag, 0) + 1

    print(f"Total flagged entries: {flagged_count}/{total}")

    if all_flags:
        print("\nFlag breakdown:")
        # Sort by count descending
        for flag, count in sorted(all_flags.items(), key=lambda x: -x[1]):
            print(f"  {flag}: {count}")

        print("\nFlag legend:")
        flag_descriptions = {
            'error_page:404': '404 page / page not found',
            'error_page:maintenance': 'Site under maintenance',
            'error_page:coming_soon': 'Coming soon page',
            'error_page:access_denied': 'Access denied / blocked',
            'error_page:empty': 'Empty or minimal content',
            'error_page:error': 'Generic error page',
            'no_url': 'No valid URL provided',
            'tech_error': 'Failed to detect tech stack',
            'pagespeed_mobile_error': 'PageSpeed mobile API error',
            'pagespeed_desktop_error': 'PageSpeed desktop API error',
            'grader_error': 'Website grading failed',
            'missing_pagespeed': 'No PageSpeed data (both mobile & desktop)',
            'missing_traffic': 'No traffic data available',
            'content_score_zero': 'Content score is 0 (not error page)',
            'design_score_zero': 'Design score is 0 (not error page)',
            'content_score_perfect': 'Content score is 100 (suspicious)',
            'design_score_perfect': 'Design score is 100 (suspicious)',
            'llm_all_ones': 'LLM gave all 1s (lowest scores)',
            'llm_all_tens': 'LLM gave all 10s (highest scores)',
            'missing_content_score': 'Content score missing despite screenshot',
            'missing_design_score': 'Design score missing despite screenshot',
            'missing_letter_grade': 'Letter grade missing despite scores',
        }
        for flag in all_flags.keys():
            # Handle error_page:* flags
            if flag.startswith('error_page:'):
                desc = flag_descriptions.get(flag, 'Error page detected')
            else:
                desc = flag_descriptions.get(flag, flag)
            print(f"  - {flag}: {desc}")
    else:
        print("\nNo data quality issues detected!")

    print()

    return df


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Run all enrichment checks on a CSV')
    parser.add_argument('input', help='Input CSV file path')
    parser.add_argument('-o', '--output', help='Output CSV file path')
    parser.add_argument('-l', '--limit', type=int, help='Limit number of entries (for testing)')
    parser.add_argument('-d', '--delay', type=float, default=1.5,
                        help='Delay between requests in seconds (default: 1.5)')
    parser.add_argument('--skip-traffic', action='store_true',
                        help='Skip traffic check (saves Apify API credits)')
    parser.add_argument('--skip-grader', action='store_true',
                        help='Skip website grading (saves Gemini API credits)')
    parser.add_argument('--resume', action='store_true',
                        help='Automatically resume from last run without prompting')

    args = parser.parse_args()

    run_enrichment(args.input, args.output, args.limit, args.delay, args.skip_traffic, args.skip_grader, args.resume)
