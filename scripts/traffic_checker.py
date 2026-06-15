#!/usr/bin/env python3
"""
Traffic Checker
Gets website traffic data using SimilarWeb via Apify.
"""

import pandas as pd
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlparse
from dotenv import load_dotenv
from apify_client import ApifyClient

# Load environment variables from project root
project_root = Path(__file__).parent.parent
load_dotenv(project_root / '.env')

ACTOR_ID = "curious_coder/similarweb-scraper"


def clean_domain(url: str) -> str:
    """
    Extract clean domain from URL.

    Examples:
        https://example.com/path -> example.com
        http://www.example.com/ -> www.example.com
        example.com -> example.com
    """
    if not url:
        return ""

    url = url.strip()

    # Add scheme if missing for proper parsing
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    parsed = urlparse(url)
    domain = parsed.netloc or parsed.path

    # Remove trailing slashes and paths
    domain = domain.split('/')[0]

    return domain


def get_traffic_data(domains: list, timeout_minutes: int = 30) -> list:
    """
    Fetch traffic data for a list of domains using SimilarWeb via Apify.

    Args:
        domains: List of domains to check (e.g., ["example.com", "test.com"])
        timeout_minutes: Max time to wait for results

    Returns:
        List of dicts with traffic data for each domain
    """
    token = os.getenv("APIFY_TOKEN")
    if not token:
        raise ValueError("APIFY_TOKEN not found in environment variables")

    client = ApifyClient(token)

    # Clean domains
    clean_domains = [clean_domain(d) for d in domains if d]
    clean_domains = [d for d in clean_domains if d]  # Remove empty

    print(f"Fetching traffic data for {len(clean_domains)} domains...")

    # Start the actor run
    run = client.actor(ACTOR_ID).call(
        run_input={"domains": clean_domains},
        timeout_secs=timeout_minutes * 60
    )

    # Collect results
    results = []
    for item in client.dataset(run["defaultDatasetId"]).iterate_items():
        results.append(item)

    return results


def extract_traffic_metrics(data: dict) -> dict:
    """
    Extract key traffic metrics from SimilarWeb response.

    Returns dict with standardized fields.
    """
    # Format bounce rate as percentage (0.45 → 45.0)
    bounce_rate = data.get('bounceRate')
    if bounce_rate is not None:
        try:
            bounce_rate = round(float(bounce_rate) * 100, 1)
        except (ValueError, TypeError):
            bounce_rate = None

    # Limit pages per visit to 2 decimal places
    pages_per_visit = data.get('pagesPerVisit')
    if pages_per_visit is not None:
        try:
            pages_per_visit = round(float(pages_per_visit), 2)
        except (ValueError, TypeError):
            pages_per_visit = None

    result = {
        'domain': data.get('domain', ''),
        'monthly_visits': data.get('visits'),
        'global_rank': data.get('globalRank'),
        'country_rank': None,
        'country_rank_country': None,
        'bounce_rate': bounce_rate,
        'pages_per_visit': pages_per_visit,
        'avg_visit_duration': data.get('timeOnSite'),
        'traffic_source_direct': None,
        'traffic_source_search': None,
        'traffic_source_social': None,
        'traffic_source_referrals': None,
        'traffic_source_paid': None,
        'traffic_source_mail': None,
        'top_country': None,
        'top_country_share': None,
        'category': data.get('category'),
        'error': None
    }

    # Extract country rank
    country_rank = data.get('countryRank', {})
    if country_rank:
        result['country_rank'] = country_rank.get('rank')
        result['country_rank_country'] = country_rank.get('country')

    # Extract traffic sources (API uses capitalized keys)
    traffic_sources = data.get('trafficSources', {})
    if traffic_sources:
        # Convert to percentages and round to 1 decimal
        def format_pct(val):
            if val is not None:
                try:
                    return round(float(val) * 100, 1)
                except (ValueError, TypeError):
                    return None
            return None

        result['traffic_source_direct'] = format_pct(traffic_sources.get('Direct'))
        result['traffic_source_search'] = format_pct(traffic_sources.get('Search'))
        result['traffic_source_social'] = format_pct(traffic_sources.get('Social'))
        result['traffic_source_referrals'] = format_pct(traffic_sources.get('Referrals'))
        result['traffic_source_paid'] = format_pct(traffic_sources.get('Paid Referrals'))
        result['traffic_source_mail'] = format_pct(traffic_sources.get('Mail'))

    # Extract top country (API uses 'CountryCode' and 'Value')
    top_countries = data.get('topCountryShares', [])
    if top_countries and len(top_countries) > 0:
        result['top_country'] = top_countries[0].get('CountryCode')
        top_share = top_countries[0].get('Value')
        if top_share is not None:
            try:
                result['top_country_share'] = round(float(top_share) * 100, 1)
            except (ValueError, TypeError):
                result['top_country_share'] = None

    return result


def check_signal_2(monthly_visits, min_visits: int = 50000) -> bool:
    """
    Check if a domain qualifies for Signal 2 (high traffic).

    Args:
        monthly_visits: Monthly visitor count (int or str)
        min_visits: Minimum threshold (default 50K)

    Returns:
        True if visits >= min_visits
    """
    if monthly_visits is None:
        return False
    try:
        visits = int(monthly_visits)
        return visits >= min_visits
    except (ValueError, TypeError):
        return False


def process_csv(input_path: str, output_path: str = None):
    """
    Process a CSV file and add traffic data columns.

    Args:
        input_path: Path to input CSV with website/domain column
        output_path: Path for output CSV
    """
    from column_utils import get_website_column, get_company_column

    # Read input CSV
    df = pd.read_csv(input_path)

    # Auto-detect columns
    try:
        website_col = get_website_column(df)
        company_col = get_company_column(df)
        print(f"Detected website column: '{website_col}'")
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    # Set default output path
    if not output_path:
        input_file = Path(input_path)
        output_path = input_file.parent / f"{input_file.stem}_traffic.csv"

    total = len(df)
    print(f"Processing {total} websites...")
    print("-" * 50)

    # Extract domains from website column
    domains = df[website_col].tolist()

    # Fetch traffic data in batch
    try:
        raw_results = get_traffic_data(domains)
    except Exception as e:
        print(f"Error fetching traffic data: {e}")
        sys.exit(1)

    # Create domain -> result mapping
    result_map = {}
    for item in raw_results:
        domain = item.get('domain', '').lower()
        if domain:
            result_map[domain] = extract_traffic_metrics(item)

    # Match results back to original rows
    results = []
    for idx, row in df.iterrows():
        url = row[website_col]
        domain = clean_domain(url).lower()
        company = row[company_col] if company_col else 'Unknown'

        if domain in result_map:
            result = result_map[domain]
            visits = result.get('monthly_visits')
            print(f"[{idx + 1}/{total}] {company}: {visits:,} visits/month" if visits else f"[{idx + 1}/{total}] {company}: No data")
        else:
            result = {
                'domain': domain,
                'monthly_visits': None,
                'global_rank': None,
                'country_rank': None,
                'bounce_rate': None,
                'error': 'No data returned'
            }
            print(f"[{idx + 1}/{total}] {company}: No data")

        results.append(result)

    # Add results to dataframe
    df['monthly_visits'] = [r.get('monthly_visits') for r in results]
    df['global_rank'] = [r.get('global_rank') for r in results]
    df['country_rank'] = [r.get('country_rank') for r in results]
    df['bounce_rate'] = [r.get('bounce_rate') for r in results]
    df['pages_per_visit'] = [r.get('pages_per_visit') for r in results]
    df['avg_visit_duration'] = [r.get('avg_visit_duration') for r in results]
    df['traffic_source_direct'] = [r.get('traffic_source_direct') for r in results]
    df['traffic_source_search'] = [r.get('traffic_source_search') for r in results]
    df['traffic_source_social'] = [r.get('traffic_source_social') for r in results]
    df['traffic_source_paid'] = [r.get('traffic_source_paid') for r in results]
    df['top_country'] = [r.get('top_country') for r in results]
    df['is_signal_2_traffic'] = [check_signal_2(r.get('monthly_visits')) for r in results]
    df['traffic_error'] = [r.get('error', '') for r in results]

    # Save output
    df.to_csv(output_path, index=False)
    print("-" * 50)
    print(f"Results saved to: {output_path}")

    # Summary
    visits_data = [r.get('monthly_visits') for r in results if r.get('monthly_visits')]
    signal_2_count = sum(1 for r in results if check_signal_2(r.get('monthly_visits')))
    no_data_count = sum(1 for r in results if r.get('error'))

    print(f"\nSummary:")
    print(f"  Total: {total}")
    print(f"  With traffic data: {len(visits_data)}/{total}")
    print(f"  Signal 2 (50K+ visits): {signal_2_count}/{total}")
    print(f"  No data: {no_data_count}/{total}")

    if visits_data:
        avg_visits = sum(visits_data) / len(visits_data)
        print(f"  Average visits: {avg_visits:,.0f}/month")

    return df


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Get traffic data from a CSV of websites')
    parser.add_argument('input', help='Input CSV file path')
    parser.add_argument('-o', '--output', help='Output CSV file path')

    args = parser.parse_args()

    process_csv(args.input, args.output)
