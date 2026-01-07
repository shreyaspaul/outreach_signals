#!/usr/bin/env python3
"""
PageSpeed Checker
Gets mobile and desktop performance scores using Google PageSpeed Insights API.
"""

import pandas as pd
import requests
import time
import sys
import os
from pathlib import Path
from dotenv import load_dotenv


# Load environment variables from project root
project_root = Path(__file__).parent.parent
load_dotenv(project_root / '.env')

PAGESPEED_API_URL = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"


def normalize_url(url: str) -> str:
    """Ensure URL has proper scheme."""
    if not url:
        return ""
    url = url.strip()
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    return url


def get_pagespeed_score(url: str, strategy: str = 'mobile', api_key: str = None, timeout: int = 60) -> dict:
    """
    Get PageSpeed score for a URL.

    Args:
        url: Website URL to test
        strategy: 'mobile' or 'desktop'
        api_key: Optional Google API key (higher quota)
        timeout: Request timeout in seconds

    Returns dict with:
        - score: Performance score (0-100) or None
        - fcp: First Contentful Paint (seconds)
        - lcp: Largest Contentful Paint (seconds)
        - cls: Cumulative Layout Shift
        - error: str if request failed
    """
    result = {
        'score': None,
        'fcp': None,
        'lcp': None,
        'cls': None,
        'error': None
    }

    if not url:
        result['error'] = 'Empty URL'
        return result

    url = normalize_url(url)

    # Fall back to env variable if no API key provided
    if not api_key:
        api_key = os.getenv('PAGESPEED_API_KEY')

    params = {
        'url': url,
        'strategy': strategy,
        'category': 'performance'
    }

    if api_key:
        params['key'] = api_key

    try:
        response = requests.get(PAGESPEED_API_URL, params=params, timeout=timeout)

        if response.status_code == 429:
            result['error'] = 'Rate limited'
            return result

        if response.status_code != 200:
            result['error'] = f'HTTP {response.status_code}'
            return result

        data = response.json()

        # Extract performance score
        lighthouse = data.get('lighthouseResult', {})
        categories = lighthouse.get('categories', {})
        performance = categories.get('performance', {})

        score = performance.get('score')
        if score is not None:
            result['score'] = int(score * 100)  # Convert 0-1 to 0-100

        # Extract Core Web Vitals
        audits = lighthouse.get('audits', {})

        # First Contentful Paint
        fcp = audits.get('first-contentful-paint', {})
        if fcp.get('numericValue'):
            result['fcp'] = round(fcp['numericValue'] / 1000, 2)  # Convert ms to seconds

        # Largest Contentful Paint
        lcp = audits.get('largest-contentful-paint', {})
        if lcp.get('numericValue'):
            result['lcp'] = round(lcp['numericValue'] / 1000, 2)

        # Cumulative Layout Shift
        cls = audits.get('cumulative-layout-shift', {})
        if cls.get('numericValue') is not None:
            result['cls'] = round(cls['numericValue'], 3)

    except requests.exceptions.Timeout:
        result['error'] = 'Timeout'
    except requests.exceptions.ConnectionError:
        result['error'] = 'Connection Error'
    except Exception as e:
        result['error'] = str(e)[:50]

    return result


def process_csv(input_path: str, output_path: str = None, api_key: str = None, delay: float = 2.0):
    """
    Process a CSV file and add PageSpeed scores.

    Args:
        input_path: Path to input CSV with 'Website' column
        output_path: Path for output CSV
        api_key: Optional Google API key
        delay: Seconds to wait between requests
    """
    # Try to get API key from environment if not provided
    if not api_key:
        api_key = os.getenv('PAGESPEED_API_KEY')

    # Read input CSV
    df = pd.read_csv(input_path)

    if 'Website' not in df.columns:
        print("Error: CSV must have a 'Website' column")
        sys.exit(1)

    # Set default output path
    if not output_path:
        input_file = Path(input_path)
        output_path = input_file.parent / f"{input_file.stem}_pagespeed.csv"

    total = len(df)
    print(f"Processing {total} websites...")
    print(f"API Key: {'Configured' if api_key else 'Not set (using free tier)'}")
    print("-" * 60)

    # Process each website
    mobile_results = []
    desktop_results = []

    for idx, row in df.iterrows():
        url = row['Website']
        company = row.get('Company Name', 'Unknown')

        print(f"[{idx + 1}/{total}] {company}: {url}")

        # Get mobile score
        print(f"         Mobile:  ", end='', flush=True)
        mobile = get_pagespeed_score(url, strategy='mobile', api_key=api_key)
        mobile_results.append(mobile)

        if mobile['error']:
            print(f"Error - {mobile['error']}")
        else:
            print(f"{mobile['score']}/100 (FCP: {mobile['fcp']}s, LCP: {mobile['lcp']}s)")

        time.sleep(delay)  # Rate limit between mobile and desktop

        # Get desktop score
        print(f"         Desktop: ", end='', flush=True)
        desktop = get_pagespeed_score(url, strategy='desktop', api_key=api_key)
        desktop_results.append(desktop)

        if desktop['error']:
            print(f"Error - {desktop['error']}")
        else:
            print(f"{desktop['score']}/100 (FCP: {desktop['fcp']}s, LCP: {desktop['lcp']}s)")

        # Rate limiting between sites
        if idx < total - 1:
            time.sleep(delay)

    # Add results to dataframe
    df['pagespeed_mobile'] = [r['score'] for r in mobile_results]
    df['pagespeed_desktop'] = [r['score'] for r in desktop_results]
    df['mobile_fcp'] = [r['fcp'] for r in mobile_results]
    df['mobile_lcp'] = [r['lcp'] for r in mobile_results]
    df['mobile_cls'] = [r['cls'] for r in mobile_results]
    df['desktop_fcp'] = [r['fcp'] for r in desktop_results]
    df['desktop_lcp'] = [r['lcp'] for r in desktop_results]
    df['desktop_cls'] = [r['cls'] for r in desktop_results]
    df['pagespeed_error'] = [
        mobile_results[i]['error'] or desktop_results[i]['error'] or ''
        for i in range(len(mobile_results))
    ]

    # Save output
    df.to_csv(output_path, index=False)
    print("-" * 60)
    print(f"Results saved to: {output_path}")

    # Summary
    mobile_scores = [r['score'] for r in mobile_results if r['score'] is not None]
    desktop_scores = [r['score'] for r in desktop_results if r['score'] is not None]
    error_count = sum(1 for r in mobile_results if r['error']) + sum(1 for r in desktop_results if r['error'])

    print(f"\nSummary:")
    if mobile_scores:
        print(f"  Mobile avg:  {sum(mobile_scores) / len(mobile_scores):.1f}/100")
    if desktop_scores:
        print(f"  Desktop avg: {sum(desktop_scores) / len(desktop_scores):.1f}/100")
    print(f"  Errors: {error_count}")

    # Sites with poor mobile score (Signal 2 targets)
    poor_mobile = sum(1 for s in mobile_scores if s < 50)
    print(f"  Mobile score < 50: {poor_mobile}/{len(mobile_scores)}")

    return df


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Get PageSpeed scores from a CSV')
    parser.add_argument('input', help='Input CSV file path')
    parser.add_argument('-o', '--output', help='Output CSV file path')
    parser.add_argument('-k', '--api-key', help='Google PageSpeed API key')
    parser.add_argument('-d', '--delay', type=float, default=2.0,
                        help='Delay between requests in seconds (default: 2.0)')

    args = parser.parse_args()

    process_csv(args.input, args.output, args.api_key, args.delay)
