#!/usr/bin/env python3
"""
Apify Traffic Refresh
=====================
Fetches fresh SimilarWeb traffic data via Apify and writes it back into an
existing enriched CSV as NEW columns prefixed `apify_` (originals untouched).

Adds an `apify_error` column logging any domain whose call failed / returned no
data, so failures are auditable.

Built against the current `curious_coder/similarweb-scraper` response schema
(trafficSources split into SearchOrganic/SearchPaid/SocialOrganic/SocialPaid,
plus GenAi/DisplayAds/Affiliate; estimatedMonthlyVisits is a 3-month dict).

Usage:
    python scripts/apify_traffic_refresh.py data/enriched_20260616_023344.csv
"""

import argparse
import json
import os
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

# Reuse the existing Apify call + domain cleaner
from traffic_checker import get_traffic_data, clean_domain
from column_utils import get_website_column

project_root = Path(__file__).parent.parent
load_dotenv(project_root / ".env")


def _pct(val):
    """Decimal fraction -> percentage rounded to 1dp (0.711 -> 71.1)."""
    if val is None:
        return None
    try:
        return round(float(val) * 100, 1)
    except (ValueError, TypeError):
        return None


def _num(val):
    if val is None:
        return None
    try:
        f = float(val)
        return int(f) if f.is_integer() else round(f, 2)
    except (ValueError, TypeError):
        return None


def build_apify_row(data: dict) -> dict:
    """Flatten one raw Apify SimilarWeb record into apify_-prefixed fields."""
    sources = data.get("trafficSources") or {}
    countries = data.get("topCountryShares") or []
    top = countries[0] if countries else {}
    country_rank = data.get("countryRank") or {}
    keywords = data.get("topKeywords") or []

    row = {
        "apify_domain": data.get("domain"),
        "apify_snapshot_date": data.get("snapshotDate"),
        "apify_monthly_visits": _num(data.get("visits")),
        "apify_visits_trend": json.dumps(data.get("estimatedMonthlyVisits"))
        if data.get("estimatedMonthlyVisits") else None,
        "apify_global_rank": _num(data.get("globalRank")),
        "apify_country_rank": _num(country_rank.get("rank")),
        "apify_country_rank_country": country_rank.get("countryCode")
        or country_rank.get("country"),
        "apify_category": data.get("category"),
        "apify_category_rank": _num(data.get("categoryRank")),
        "apify_bounce_rate": _pct(data.get("bounceRate")),
        "apify_pages_per_visit": _num(data.get("pagesPerVisit")),
        "apify_avg_visit_duration_s": _num(data.get("timeOnSite")),
        "apify_is_data_from_ga": data.get("isDataFromGA"),
        # Traffic sources (current schema)
        "apify_traffic_direct": _pct(sources.get("Direct")),
        "apify_traffic_search_organic": _pct(sources.get("SearchOrganic")),
        "apify_traffic_search_paid": _pct(sources.get("SearchPaid")),
        "apify_traffic_social_organic": _pct(sources.get("SocialOrganic")),
        "apify_traffic_social_paid": _pct(sources.get("SocialPaid")),
        "apify_traffic_referrals": _pct(sources.get("Referrals")),
        "apify_traffic_mail": _pct(sources.get("Mail")),
        "apify_traffic_genai": _pct(sources.get("GenAi")),
        "apify_traffic_display_ads": _pct(sources.get("DisplayAds")),
        "apify_traffic_affiliate": _pct(sources.get("Affiliate")),
        # Top country
        "apify_top_country": top.get("CountryCode"),
        "apify_top_country_share": _pct(top.get("Value")),
        # Keywords (compact, top 10)
        "apify_top_keywords": ", ".join(
            str(k.get("name") or k.get("keyword") or k)
            for k in keywords[:10]
        ) if keywords else None,
        "apify_error": None,
    }
    return row


# The full set of apify_ columns, so rows with no data still get every column
APIFY_COLUMNS = list(build_apify_row({}).keys())


def main():
    parser = argparse.ArgumentParser(description="Refresh traffic data via Apify into an enriched CSV")
    parser.add_argument("input", help="Path to enriched CSV to augment in place")
    parser.add_argument("--limit", type=int, help="Only process first N rows (testing)")
    parser.add_argument("--no-backup", action="store_true", help="Skip writing a .bak backup")
    args = parser.parse_args()

    in_path = Path(args.input)
    if not in_path.exists():
        print(f"ERROR: {in_path} not found")
        sys.exit(1)

    df = pd.read_csv(in_path)
    website_col = get_website_column(df)
    print(f"Loaded {len(df)} rows. Website column: '{website_col}'")

    if args.limit:
        df = df.head(args.limit).copy()
        print(f"Limited to first {len(df)} rows")

    # Unique cleaned domains for the batch call
    cleaned = df[website_col].apply(lambda d: clean_domain(d).lower() if pd.notna(d) else "")
    domains = sorted({d for d in cleaned if d})
    print(f"Fetching {len(domains)} unique domains via Apify...")

    raw = get_traffic_data(domains)
    result_map = {}
    for item in raw:
        dom = (item.get("domain") or "").lower()
        if dom:
            result_map[dom] = build_apify_row(item)

    print(f"Apify returned data for {len(result_map)}/{len(domains)} domains")

    # Assemble apify_ columns row-by-row, matched by cleaned domain
    rows = []
    missing = 0
    for dom in cleaned:
        if dom and dom in result_map:
            rows.append(result_map[dom])
        else:
            blank = {c: None for c in APIFY_COLUMNS}
            blank["apify_error"] = "no_data_returned" if dom else "no_url"
            missing += 1
            rows.append(blank)

    apify_df = pd.DataFrame(rows, index=df.index, columns=APIFY_COLUMNS)

    # Drop any pre-existing apify_ columns (idempotent re-run), then attach
    df = df.drop(columns=[c for c in df.columns if c in APIFY_COLUMNS], errors="ignore")
    out = pd.concat([df, apify_df], axis=1)

    if not args.no_backup:
        bak = in_path.with_suffix(in_path.suffix + ".bak")
        pd.read_csv(in_path).to_csv(bak, index=False)
        print(f"Backup written: {bak}")

    out.to_csv(in_path, index=False)

    got = out["apify_monthly_visits"].notna().sum()
    failed = out["apify_error"].notna().sum()
    print("-" * 50)
    print(f"Wrote {len(APIFY_COLUMNS)} apify_ columns into {in_path}")
    print(f"  With fresh visits: {got}/{len(out)}")
    print(f"  Failed / no data:  {failed}/{len(out)} (see apify_error)")


if __name__ == "__main__":
    main()
