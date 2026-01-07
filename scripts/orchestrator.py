#!/usr/bin/env python3
"""
Orchestrator
Runs all enrichment scripts on a CSV and combines results.
"""

import pandas as pd
import sys
import os
import time
import asyncio
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# Load .env from project root
project_root = Path(__file__).parent.parent
load_dotenv(project_root / '.env')

# Import the checker functions
from wordpress_detector import detect_tech_stack, normalize_url
from pagespeed_checker import get_pagespeed_score
from traffic_checker import get_traffic_data, extract_traffic_metrics, check_signal_2, clean_domain
from website_grader import process_csv_async as grade_websites_async


def run_enrichment(input_path: str, output_path: str = None, limit: int = None, delay: float = 1.5, skip_traffic: bool = False, skip_grader: bool = False):
    """
    Run all enrichment checks on a CSV.

    Args:
        input_path: Path to input CSV with 'Website' column
        output_path: Path for output CSV
        limit: Optional limit on number of rows to process (for testing)
        delay: Seconds to wait between requests
        skip_traffic: Skip traffic check (uses Apify API credits)
        skip_grader: Skip website grading (uses Gemini API credits)
    """
    # Read input CSV
    df = pd.read_csv(input_path)

    if 'Website' not in df.columns:
        print("Error: CSV must have a 'Website' column")
        sys.exit(1)

    # Apply limit if specified
    if limit:
        df = df.head(limit)
        print(f"Limited to first {limit} entries for testing")

    # Set default output path
    if not output_path:
        input_file = Path(input_path)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = input_file.parent / "data" / f"enriched_{timestamp}.csv"
        # Create data directory if needed
        output_path.parent.mkdir(exist_ok=True)

    total = len(df)
    print(f"\n{'='*60}")
    print(f"ENRICHMENT RUN - {total} websites")
    print(f"{'='*60}\n")

    # Initialize result columns
    tech_results = []
    mobile_results = []
    desktop_results = []

    for idx, row in df.iterrows():
        url = row['Website']
        company = row.get('Company Name', 'Unknown')

        print(f"[{idx + 1}/{total}] {company}")
        print(f"         URL: {url}")

        # 1. Tech Stack Detection
        print(f"         Tech: ", end='', flush=True)
        tech_result = detect_tech_stack(url)
        tech_results.append(tech_result)

        if tech_result['error']:
            print(f"Error - {tech_result['error']}")
        else:
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
        mobile_results.append(mobile)

        if mobile['error']:
            print(f"Error - {mobile['error']}")
        else:
            print(f"{mobile['score']}/100 (LCP: {mobile['lcp']}s)")

        time.sleep(delay)

        # 3. PageSpeed - Desktop
        print(f"         Desktop:   ", end='', flush=True)
        desktop = get_pagespeed_score(url, strategy='desktop')
        desktop_results.append(desktop)

        if desktop['error']:
            print(f"Error - {desktop['error']}")
        else:
            print(f"{desktop['score']}/100 (LCP: {desktop['lcp']}s)")

        print()  # Blank line between entries

        # Rate limiting between sites
        if idx < total - 1:
            time.sleep(delay)

    # 4. Traffic Check (batch API call)
    traffic_results = []
    if not skip_traffic:
        print(f"\n{'='*60}")
        print("TRAFFIC DATA (SimilarWeb via Apify)")
        print(f"{'='*60}\n")

        domains = df['Website'].tolist()
        try:
            raw_traffic = get_traffic_data(domains)

            # Create domain -> result mapping
            traffic_map = {}
            for item in raw_traffic:
                domain = item.get('domain', '').lower()
                if domain:
                    traffic_map[domain] = extract_traffic_metrics(item)

            # Match results back to original rows
            for idx, row in df.iterrows():
                url = row['Website']
                domain = clean_domain(url).lower()
                company = row.get('Company Name', 'Unknown')

                if domain in traffic_map:
                    result = traffic_map[domain]
                    visits = result.get('monthly_visits')
                    if visits is not None:
                        try:
                            visits_int = int(visits)
                            signal_2 = check_signal_2(visits_int)
                            marker = " [SIGNAL 2]" if signal_2 else ""
                            print(f"  {company}: {visits_int:,} visits/month{marker}")
                        except (ValueError, TypeError):
                            print(f"  {company}: Invalid traffic data ({visits})")
                    else:
                        print(f"  {company}: No traffic data")
                else:
                    result = {
                        'domain': domain,
                        'monthly_visits': None,
                        'global_rank': None,
                        'error': 'No data returned'
                    }
                    print(f"  {company}: No data")

                traffic_results.append(result)

        except Exception as e:
            print(f"Error fetching traffic data: {e}")
            # Fill with empty results
            traffic_results = [{'domain': '', 'monthly_visits': None, 'error': str(e)} for _ in range(total)]
    else:
        print("\nSkipping traffic check (--skip-traffic flag set)")
        traffic_results = [{'domain': '', 'monthly_visits': None, 'error': 'Skipped'} for _ in range(total)]

    # 5. Website Grading (parallel screenshot capture + Gemini Vision)
    grader_results = []
    if not skip_grader:
        print(f"\n{'='*60}")
        print("WEBSITE GRADING (Parallel Screenshots + Gemini Vision)")
        print(f"{'='*60}\n")

        from website_grader import (
            capture_screenshot_and_content,
            grade_website,
            analyze_design_with_gemini,
            score_content_amount,
            DEFAULT_SCREENSHOT_DIR,
            MAX_CONCURRENT_BROWSERS
        )

        screenshot_dir = project_root / 'screenshots'
        screenshot_dir.mkdir(exist_ok=True)
        api_key = os.getenv('GEMINI_API_KEY')

        if not api_key:
            print("Warning: GEMINI_API_KEY not found. Design scoring will be skipped.")

        # Phase 1: Capture screenshots in parallel
        print(f"Phase 1: Capturing screenshots ({MAX_CONCURRENT_BROWSERS} concurrent)...")
        import time as time_module
        start_time = time_module.time()

        async def capture_all():
            semaphore = asyncio.Semaphore(MAX_CONCURRENT_BROWSERS)
            tasks = [capture_screenshot_and_content(url, screenshot_dir, semaphore) for url in df['Website'].tolist()]
            return await asyncio.gather(*tasks)

        capture_results = asyncio.run(capture_all())

        screenshot_time = time_module.time() - start_time
        success_count = sum(1 for r in capture_results if r.get('screenshot_path'))
        print(f"  Captured {success_count}/{total} screenshots in {screenshot_time:.1f}s")

        # Phase 2: Analyze designs with Gemini
        print(f"\nPhase 2: Analyzing designs with Gemini...")
        start_time = time_module.time()

        for idx, row in df.iterrows():
            url = row['Website']
            company = row.get('Company Name', 'Unknown')
            pagespeed_mobile = mobile_results[idx]['score']
            capture_result = capture_results[idx]

            print(f"  [{idx + 1}/{total}] {company}...", end='', flush=True)

            result = grade_website(
                url=url,
                pagespeed_mobile=pagespeed_mobile,
                screenshot_dir=screenshot_dir,
                api_key=api_key,
                capture_result=capture_result
            )
            grader_results.append(result)

            if result['error']:
                print(f" Error: {result['error'][:30]}")
            else:
                print(f" {result['letter_grade']} ({result['total_grade_score']}/100)")

            time.sleep(delay * 0.5)  # Shorter delay for API calls

        design_time = time_module.time() - start_time
        print(f"\n  Design analysis completed in {design_time:.1f}s")

    else:
        print("\nSkipping website grading (--skip-grader flag set)")
        grader_results = [{
            'content_score': None,
            'design_score': None,
            'total_grade_score': None,
            'letter_grade': '',
            'grade_analysis': '',
            'weak_areas': '',
            'strong_areas': '',
            'screenshot_path': '',
            'design_comment': '',
            'error': 'Skipped'
        } for _ in range(total)]

    # Add all results to dataframe
    df['tech_stack'] = [r['primary_tech'] for r in tech_results]
    df['all_tech_detected'] = [', '.join(r['detected_tech']) if r['detected_tech'] else '' for r in tech_results]
    df['is_wordpress'] = [r['is_wordpress'] for r in tech_results]

    # Marketing & Ads columns
    df['marketing_tools'] = [', '.join(r['marketing_tools']) if r['marketing_tools'] else '' for r in tech_results]
    df['ad_pixels'] = [', '.join(r['ad_pixels']) if r['ad_pixels'] else '' for r in tech_results]
    df['has_premium_analytics'] = [r['has_premium_analytics'] for r in tech_results]

    df['pagespeed_mobile'] = [r['score'] for r in mobile_results]
    df['pagespeed_desktop'] = [r['score'] for r in desktop_results]

    df['mobile_fcp'] = [r['fcp'] for r in mobile_results]
    df['mobile_lcp'] = [r['lcp'] for r in mobile_results]
    df['mobile_cls'] = [r['cls'] for r in mobile_results]

    df['desktop_fcp'] = [r['fcp'] for r in desktop_results]
    df['desktop_lcp'] = [r['lcp'] for r in desktop_results]
    df['desktop_cls'] = [r['cls'] for r in desktop_results]

    # Traffic columns
    df['monthly_visits'] = [r.get('monthly_visits') for r in traffic_results]
    df['global_rank'] = [r.get('global_rank') for r in traffic_results]
    df['bounce_rate'] = [r.get('bounce_rate') for r in traffic_results]
    df['pages_per_visit'] = [r.get('pages_per_visit') for r in traffic_results]
    df['traffic_source_direct'] = [r.get('traffic_source_direct') for r in traffic_results]
    df['traffic_source_search'] = [r.get('traffic_source_search') for r in traffic_results]
    df['traffic_source_social'] = [r.get('traffic_source_social') for r in traffic_results]
    df['top_country'] = [r.get('top_country') for r in traffic_results]

    # Signal 2 flag (50K+ visits + poor mobile score)
    df['is_signal_2_traffic'] = [check_signal_2(r.get('monthly_visits')) for r in traffic_results]

    # Grading columns
    df['content_score'] = [r.get('content_score') for r in grader_results]
    df['design_score'] = [r.get('design_score') for r in grader_results]
    df['total_grade_score'] = [r.get('total_grade_score') for r in grader_results]
    df['letter_grade'] = [r.get('letter_grade', '') for r in grader_results]
    df['grade_analysis'] = [r.get('grade_analysis', '') for r in grader_results]
    df['weak_areas'] = [r.get('weak_areas', '') for r in grader_results]
    df['strong_areas'] = [r.get('strong_areas', '') for r in grader_results]
    df['screenshot_path'] = [r.get('screenshot_path', '') for r in grader_results]
    df['design_comment'] = [r.get('design_comment', '') for r in grader_results]

    # Error column (any errors from any check)
    df['enrichment_errors'] = [
        '; '.join(filter(None, [
            f"Tech: {tech_results[i]['error']}" if tech_results[i]['error'] else '',
            f"Mobile: {mobile_results[i]['error']}" if mobile_results[i]['error'] else '',
            f"Desktop: {desktop_results[i]['error']}" if desktop_results[i]['error'] else '',
            f"Traffic: {traffic_results[i].get('error')}" if traffic_results[i].get('error') else '',
            f"Grader: {grader_results[i].get('error')}" if grader_results[i].get('error') and grader_results[i].get('error') != 'Skipped' else ''
        ])) or ''
        for i in range(len(df))
    ]

    # Save output
    df.to_csv(output_path, index=False)

    # Print summary
    print(f"{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"Output saved to: {output_path}")
    print()

    # Tech stack breakdown
    tech_counts = {}
    for r in tech_results:
        if not r['error']:
            tech = r['primary_tech']
            tech_counts[tech] = tech_counts.get(tech, 0) + 1

    print("Tech Stack Breakdown:")
    for tech, count in sorted(tech_counts.items(), key=lambda x: -x[1]):
        print(f"  {tech}: {count}")
    print()

    wp_count = sum(1 for r in tech_results if r['is_wordpress'])
    print(f"WordPress sites: {wp_count}/{total}")

    # Marketing summary
    premium_count = sum(1 for r in tech_results if r.get('has_premium_analytics'))
    has_ads_count = sum(1 for r in tech_results if r.get('ad_pixels'))
    has_marketing_count = sum(1 for r in tech_results if r.get('marketing_tools'))
    print(f"Sites with marketing tools: {has_marketing_count}/{total}")
    print(f"Sites with premium analytics (Signal 3): {premium_count}/{total}")
    print(f"Sites running ads: {has_ads_count}/{total}")
    print()

    mobile_scores = [r['score'] for r in mobile_results if r['score'] is not None]
    desktop_scores = [r['score'] for r in desktop_results if r['score'] is not None]

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
    if not skip_traffic:
        # Convert visits to integers for calculations
        visits_data = []
        for r in traffic_results:
            v = r.get('monthly_visits')
            if v is not None:
                try:
                    visits_data.append(int(v))
                except (ValueError, TypeError):
                    pass
        signal_2_traffic = sum(1 for r in traffic_results if check_signal_2(r.get('monthly_visits')))
        print(f"With traffic data: {len(visits_data)}/{total}")
        print(f"50K+ monthly visits: {signal_2_traffic}/{total}")
        if visits_data:
            avg_visits = sum(visits_data) / len(visits_data)
            print(f"Average monthly visits: {avg_visits:,.0f}")

        # Full Signal 2 (WordPress + poor mobile + high traffic)
        full_signal_2 = sum(
            1 for i in range(len(df))
            if tech_results[i]['is_wordpress']
            and mobile_results[i]['score'] is not None
            and mobile_results[i]['score'] < 50
            and check_signal_2(traffic_results[i].get('monthly_visits'))
        )
        print(f"\n*** FULL SIGNAL 2 (WP + Mobile<50 + 50K+ visits): {full_signal_2}/{total} ***")
    print()

    # Grading summary
    if not skip_grader:
        grades = [r['letter_grade'] for r in grader_results if r.get('letter_grade')]
        if grades:
            grade_counts = {}
            for g in grades:
                grade_counts[g] = grade_counts.get(g, 0) + 1
            print("Grade Distribution:")
            for grade in ['A+', 'A', 'A-', 'B+', 'B', 'B-', 'C+', 'C', 'C-', 'D+', 'D', 'D-', 'F']:
                if grade in grade_counts:
                    print(f"  {grade}: {grade_counts[grade]}")
            print()

        content_scores = [r['content_score'] for r in grader_results if r.get('content_score') is not None]
        design_scores = [r['design_score'] for r in grader_results if r.get('design_score') is not None]
        total_scores = [r['total_grade_score'] for r in grader_results if r.get('total_grade_score') is not None]

        if content_scores:
            print(f"Avg content score: {sum(content_scores)/len(content_scores):.1f}/100")
        if design_scores:
            print(f"Avg design score: {sum(design_scores)/len(design_scores):.1f}/100")
        if total_scores:
            print(f"Avg total score: {sum(total_scores)/len(total_scores):.1f}/100")
        print()

        # Common weak areas
        all_weak = []
        for r in grader_results:
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

    error_count = sum(1 for i in range(len(df)) if df['enrichment_errors'].iloc[i])
    print(f"Entries with errors: {error_count}/{total}")

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

    args = parser.parse_args()

    run_enrichment(args.input, args.output, args.limit, args.delay, args.skip_traffic, args.skip_grader)
