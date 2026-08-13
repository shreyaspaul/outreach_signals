#!/usr/bin/env python3
"""
Export top prospects by segment for LinkedIn outreach.

Usage:
    python scripts/export_prospects.py --segment 1 --limit 20
    python scripts/export_prospects.py --segment all
"""

import pandas as pd
import argparse
from datetime import datetime
from grader_fields import write_annotated_csv, read_annotated_csv

def export_segment_1(df, limit=None):
    """
    Segment 1: Performance Bleed
    High traffic (50K+) + slow mobile PageSpeed (<60)
    """
    segment = df[
        (df['monthly_visits'] >= 50000) &
        (df['pagespeed_mobile'] < 60) &
        (df['pagespeed_mobile'].notna()) &
        (df['letter_grade'].notna())
    ].sort_values('monthly_visits', ascending=False)

    if limit:
        segment = segment.head(limit)

    return segment[[
        'Name', 'Domain', 'monthly_visits', 'bounce_rate',
        'pagespeed_mobile', 'pagespeed_desktop',
        'tech_stack', 'Total Equity Funding Amount',
        'design_score', 'content_score', 'letter_grade',
        'weak_areas'
    ]]

def export_segment_2a(df, limit=None):
    """
    Segment 2A: Investment Mismatch - Thin Content
    Funded + content score <50 + decent traffic (10K+)
    """
    segment = df[
        (df['content_score'] < 50) &
        (df['content_score'].notna()) &
        (df['monthly_visits'] >= 10000) &
        (df['monthly_visits'].notna()) &
        (df['Total Equity Funding Amount'].notna()) &
        (df['letter_grade'].notna())
    ].sort_values('monthly_visits', ascending=False)

    if limit:
        segment = segment.head(limit)

    return segment[[
        'Name', 'Domain', 'monthly_visits',
        'content_score', 'content_word_count', 'content_analysis',
        'design_score', 'pagespeed_mobile',
        'Total Equity Funding Amount', 'tech_stack',
        'letter_grade'
    ]]

def export_segment_2b(df, limit=None):
    """
    Segment 2B: Investment Mismatch - Poor Design
    Funded + design score <60 + decent traffic (10K+)
    """
    segment = df[
        (df['design_score'] < 60) &
        (df['design_score'].notna()) &
        (df['monthly_visits'] >= 10000) &
        (df['monthly_visits'].notna()) &
        (df['Total Equity Funding Amount'].notna()) &
        (df['letter_grade'].notna())
    ].sort_values('monthly_visits', ascending=False)

    if limit:
        segment = segment.head(limit)

    return segment[[
        'Name', 'Domain', 'monthly_visits',
        'design_score', 'design_comment',
        'content_score', 'pagespeed_mobile',
        'Total Equity Funding Amount', 'tech_stack',
        'letter_grade'
    ]]

def export_segment_2c(df, limit=None):
    """
    Segment 2C: Investment Mismatch - Multiple Issues
    Funded + 2+ quality issues + decent traffic (20K+)
    """
    segment = df[
        (df['monthly_visits'] >= 20000) &
        (df['monthly_visits'].notna()) &
        (df['Total Equity Funding Amount'].notna()) &
        (df['letter_grade'].notna()) &
        (
            ((df['design_score'] < 60) & (df['content_score'] < 60)) |
            ((df['design_score'] < 60) & (df['pagespeed_mobile'].notna()) & (df['pagespeed_mobile'] < 60)) |
            ((df['content_score'] < 60) & (df['pagespeed_mobile'].notna()) & (df['pagespeed_mobile'] < 60))
        )
    ].sort_values('monthly_visits', ascending=False)

    if limit:
        segment = segment.head(limit)

    return segment[[
        'Name', 'Domain', 'monthly_visits', 'bounce_rate',
        'design_score', 'content_score', 'pagespeed_mobile',
        'Total Equity Funding Amount', 'tech_stack',
        'letter_grade', 'weak_areas'
    ]]

def export_segment_3(df, limit=None):
    """
    Segment 3: WordPress Time Tax
    WordPress + funded + some traffic (5K+)
    """
    segment = df[
        (df['is_wordpress'] == True) &
        (df['Total Equity Funding Amount'].notna()) &
        (df['letter_grade'].notna())
    ].copy()

    # Add traffic filter only if we have traffic data
    segment = segment[
        segment['monthly_visits'].isna() |
        (segment['monthly_visits'] >= 5000)
    ]

    segment = segment.sort_values('monthly_visits', ascending=False, na_position='last')

    if limit:
        segment = segment.head(limit)

    return segment[[
        'Name', 'Domain', 'monthly_visits',
        'pagespeed_mobile', 'all_tech_detected',
        'marketing_tools', 'has_premium_analytics',
        'Total Equity Funding Amount',
        'design_score', 'content_score', 'letter_grade'
    ]]

def export_segment_4(df, limit=None):
    """
    Segment 4: Webflow Underperformers
    Already on Webflow but still has quality issues
    """
    segment = df[
        (df['tech_stack'] == 'webflow') &
        (df['letter_grade'].notna()) &
        (
            ((df['design_score'].notna()) & (df['design_score'] < 60)) |
            ((df['content_score'].notna()) & (df['content_score'] < 60)) |
            ((df['pagespeed_mobile'].notna()) & (df['pagespeed_mobile'] < 60))
        )
    ].sort_values('monthly_visits', ascending=False, na_position='last')

    if limit:
        segment = segment.head(limit)

    return segment[[
        'Name', 'Domain', 'monthly_visits',
        'pagespeed_mobile', 'pagespeed_desktop',
        'design_score', 'content_score',
        'Total Equity Funding Amount',
        'letter_grade', 'weak_areas'
    ]]

def main():
    parser = argparse.ArgumentParser(description='Export prospects by segment for outreach')
    parser.add_argument('--segment', type=str, required=True,
                       choices=['1', '2a', '2b', '2c', '3', '4', 'all'],
                       help='Segment to export (1, 2a, 2b, 2c, 3, 4, or all)')
    parser.add_argument('--limit', type=int, default=None,
                       help='Limit number of results (default: all)')
    parser.add_argument('--input', type=str,
                       default='data/enriched_20260201_180319.csv',
                       help='Input CSV file')

    args = parser.parse_args()

    # Read data (handles the friendly-name + description-row format)
    print(f"Reading data from {args.input}...")
    df = read_annotated_csv(args.input)
    print(f"Total entries: {len(df)}")
    print(f"Graded entries: {df['letter_grade'].notna().sum()}\n")

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    # Export segments
    segments_to_export = []

    if args.segment == 'all':
        segments_to_export = [
            ('1', 'Performance Bleed', export_segment_1),
            ('2a', 'Investment Mismatch - Thin Content', export_segment_2a),
            ('2b', 'Investment Mismatch - Poor Design', export_segment_2b),
            ('2c', 'Investment Mismatch - Multiple Issues', export_segment_2c),
            ('3', 'WordPress Time Tax', export_segment_3),
            ('4', 'Webflow Underperformers', export_segment_4)
        ]
    else:
        segment_map = {
            '1': ('1', 'Performance Bleed', export_segment_1),
            '2a': ('2a', 'Investment Mismatch - Thin Content', export_segment_2a),
            '2b': ('2b', 'Investment Mismatch - Poor Design', export_segment_2b),
            '2c': ('2c', 'Investment Mismatch - Multiple Issues', export_segment_2c),
            '3': ('3', 'WordPress Time Tax', export_segment_3),
            '4': ('4', 'Webflow Underperformers', export_segment_4)
        }
        segments_to_export = [segment_map[args.segment]]

    # Process each segment
    for seg_id, seg_name, seg_func in segments_to_export:
        print(f"{'='*80}")
        print(f"SEGMENT {seg_id}: {seg_name}")
        print(f"{'='*80}")

        segment_df = seg_func(df, args.limit)

        if len(segment_df) == 0:
            print(f"No prospects found for this segment.\n")
            continue

        # Display summary
        print(f"\nFound {len(segment_df)} prospects:")
        print(f"\nTop 5 by traffic:")
        print(segment_df.head(5).to_string(index=False))

        # Save to CSV (friendly column names + description header row)
        filename = f"prospects_segment_{seg_id}_{timestamp}.csv"
        write_annotated_csv(segment_df, filename)
        print(f"\n✓ Exported to: {filename}")

        # Print stats
        if 'monthly_visits' in segment_df.columns:
            avg_traffic = segment_df['monthly_visits'].mean()
            if pd.notna(avg_traffic):
                print(f"  Average traffic: {avg_traffic:,.0f}/month")

        if 'pagespeed_mobile' in segment_df.columns:
            avg_mobile = segment_df['pagespeed_mobile'].mean()
            if pd.notna(avg_mobile):
                print(f"  Average mobile PageSpeed: {avg_mobile:.0f}")

        if 'design_score' in segment_df.columns:
            avg_design = segment_df['design_score'].mean()
            if pd.notna(avg_design):
                print(f"  Average design score: {avg_design:.0f}")

        print()

    print(f"{'='*80}")
    print(f"EXPORT COMPLETE")
    print(f"{'='*80}")
    print(f"\nNext steps:")
    print(f"1. Open the exported CSV(s)")
    print(f"2. Find decision makers on LinkedIn (VP Marketing, Head of Growth)")
    print(f"3. Use templates from MESSAGE_TEMPLATES.md")
    print(f"4. Personalize with their specific data")
    print(f"5. Track in your outreach spreadsheet")
    print(f"\nTarget: 40 connection requests/week, 15-20 first messages/week")

if __name__ == '__main__':
    main()
