#!/usr/bin/env python3
"""
Flag Checker
Runs data quality flagging on existing enriched CSV files.
Can be run independently without re-running the full enrichment.
"""

import pandas as pd
import sys
import argparse
from pathlib import Path
from datetime import datetime

# Import the flag_entry function from orchestrator to keep logic consistent
from orchestrator import flag_entry
from grader_fields import write_annotated_csv, read_annotated_csv


def check_flags(input_path: str, output_path: str = None, in_place: bool = False):
    """
    Run flagging on an existing enriched CSV file.

    Args:
        input_path: Path to enriched CSV file
        output_path: Optional output path (default: adds _flagged suffix)
        in_place: If True, overwrites the input file
    """
    # Read the CSV (handles the friendly-name + description-row format)
    print(f"Loading: {input_path}")
    df = read_annotated_csv(input_path)
    total = len(df)
    print(f"Found {total} entries")

    # Check if this looks like an enriched file
    required_cols = ['letter_grade', 'content_score', 'design_score']
    missing_cols = [c for c in required_cols if c not in df.columns]
    if missing_cols:
        print(f"Warning: Missing expected columns: {missing_cols}")
        print("This may not be an enriched CSV file.")

    # Process each row
    print(f"\nAnalyzing data quality...")
    flag_counts = []
    flag_reasons_list = []
    all_flags = {}

    for idx, row in df.iterrows():
        # Convert row to dict format expected by flag_entry
        result = {
            'is_error_page': bool(row.get('is_error_page', False)) if pd.notna(row.get('is_error_page')) else False,
            'error_type': str(row.get('error_type', '')) if pd.notna(row.get('error_type')) else '',
            'enrichment_errors': str(row.get('enrichment_errors', '')) if pd.notna(row.get('enrichment_errors')) else '',
            'pagespeed_mobile': row.get('pagespeed_mobile') if pd.notna(row.get('pagespeed_mobile')) else None,
            'pagespeed_desktop': row.get('pagespeed_desktop') if pd.notna(row.get('pagespeed_desktop')) else None,
            'field_lcp': row.get('field_lcp') if pd.notna(row.get('field_lcp')) else None,
            'field_lcp_desktop': row.get('field_lcp_desktop') if pd.notna(row.get('field_lcp_desktop')) else None,
            'monthly_visits': row.get('monthly_visits') if pd.notna(row.get('monthly_visits')) else None,
            'content_score': row.get('content_score') if pd.notna(row.get('content_score')) else None,
            'design_score': row.get('design_score') if pd.notna(row.get('design_score')) else None,
            'clarity': row.get('clarity') if pd.notna(row.get('clarity')) else None,
            'substance': row.get('substance') if pd.notna(row.get('substance')) else None,
            'credibility': row.get('credibility') if pd.notna(row.get('credibility')) else None,
            'persuasiveness': row.get('persuasiveness') if pd.notna(row.get('persuasiveness')) else None,
            'screenshot_path': str(row.get('screenshot_path', '')) if pd.notna(row.get('screenshot_path')) else '',
            'letter_grade': str(row.get('letter_grade', '')) if pd.notna(row.get('letter_grade')) else '',
            'page_state': str(row.get('page_state', '')) if pd.notna(row.get('page_state')) else '',
            'depth': row.get('depth') if pd.notna(row.get('depth')) else None,
        }

        # Run flagging
        count, reasons = flag_entry(result)
        flag_counts.append(count)
        flag_reasons_list.append(reasons)

        # Collect flag statistics
        if count > 0:
            for flag in reasons.split('; '):
                if flag:
                    all_flags[flag] = all_flags.get(flag, 0) + 1

    # Add/update flag columns
    df['flag_count'] = flag_counts
    df['flag_reasons'] = flag_reasons_list

    # Determine output path
    if in_place:
        output_path = input_path
    elif not output_path:
        input_file = Path(input_path)
        output_path = input_file.parent / f"{input_file.stem}_flagged{input_file.suffix}"

    # Save (friendly column names + description header row)
    write_annotated_csv(df, output_path)

    # Print summary
    flagged_count = sum(1 for c in flag_counts if c > 0)

    print(f"\n{'='*60}")
    print("DATA QUALITY FLAGS SUMMARY")
    print(f"{'='*60}")
    print(f"Total entries: {total}")
    print(f"Flagged entries: {flagged_count} ({flagged_count/total*100:.1f}%)")
    print(f"Clean entries: {total - flagged_count} ({(total-flagged_count)/total*100:.1f}%)")

    if all_flags:
        print(f"\nFlag breakdown:")
        for flag, count in sorted(all_flags.items(), key=lambda x: -x[1]):
            pct = count / total * 100
            print(f"  {flag}: {count} ({pct:.1f}%)")

        print(f"\nFlag legend:")
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
            if flag.startswith('error_page:'):
                desc = flag_descriptions.get(flag, 'Error page detected')
            else:
                desc = flag_descriptions.get(flag, flag)
            print(f"  - {flag}: {desc}")
    else:
        print(f"\nNo data quality issues detected!")

    print(f"\n{'='*60}")
    print(f"Output saved to: {output_path}")
    print(f"{'='*60}\n")

    return df, flagged_count, all_flags


def list_enriched_files():
    """List available enriched CSV files in the data directory."""
    data_dir = Path(__file__).parent.parent / 'data'
    files = sorted(data_dir.glob('enriched_*.csv'), key=lambda x: x.stat().st_mtime, reverse=True)

    if not files:
        print("No enriched CSV files found in data/")
        return []

    print(f"\nAvailable enriched files:")
    print(f"-" * 60)
    for i, f in enumerate(files, 1):
        size = f.stat().st_size / 1024  # KB
        mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime('%Y-%m-%d %H:%M')

        # Quick check for row count
        try:
            df = pd.read_csv(f, usecols=[0])
            rows = len(df)
        except:
            rows = '?'

        print(f"  [{i}] {f.name}")
        print(f"      {rows} rows, {size:.1f} KB, modified {mtime}")
    print()

    return files


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Run data quality flagging on existing enriched CSV files',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Flag the most recent enriched file
  python flag_checker.py

  # Flag a specific file (creates new file with _flagged suffix)
  python flag_checker.py data/enriched_20260201_180319.csv

  # Flag and overwrite the original file
  python flag_checker.py data/enriched_20260201_180319.csv --in-place

  # Flag and save to a specific output file
  python flag_checker.py data/enriched_20260201_180319.csv -o data/checked.csv

  # List available enriched files
  python flag_checker.py --list
"""
    )
    parser.add_argument('input', nargs='?', help='Input enriched CSV file (default: most recent)')
    parser.add_argument('-o', '--output', help='Output CSV file path')
    parser.add_argument('--in-place', action='store_true',
                        help='Overwrite the input file instead of creating a new one')
    parser.add_argument('--list', action='store_true',
                        help='List available enriched CSV files')

    args = parser.parse_args()

    # List mode
    if args.list:
        list_enriched_files()
        sys.exit(0)

    # Determine input file
    if args.input:
        input_path = args.input
    else:
        # Find most recent enriched file
        data_dir = Path(__file__).parent.parent / 'data'
        files = sorted(data_dir.glob('enriched_*.csv'), key=lambda x: x.stat().st_mtime, reverse=True)

        if not files:
            print("Error: No enriched CSV files found in data/")
            print("Run the orchestrator first or specify a file path.")
            sys.exit(1)

        input_path = str(files[0])
        print(f"Using most recent file: {input_path}")

    # Check file exists
    if not Path(input_path).exists():
        print(f"Error: File not found: {input_path}")
        sys.exit(1)

    # Run flagging
    check_flags(input_path, args.output, args.in_place)
