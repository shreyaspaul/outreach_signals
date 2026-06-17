#!/usr/bin/env python3
"""
Backfill quotable "proud facts" onto an existing enriched audit CSV.

For each gradeable row it re-fetches the page content (Jina) and runs the verified
proud-facts extractor, writing two columns WITHOUT touching anything else:
  - proud_facts          : the snippets joined by " | "  (0-3)
  - proud_facts_detail   : JSON list of {fact, type, evidence}

Idempotent: skips rows that already have proud_facts unless --force.

Usage:
  python scripts/extract_facts.py data/enriched_20260616_023344.csv --limit 12
  python scripts/extract_facts.py data/enriched_20260616_023344.csv --force
"""
import os
import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import pandas as pd
from dotenv import load_dotenv
from grader_fields import read_annotated_csv, write_annotated_csv
from content_extractor import extract_content, extract_proud_facts

load_dotenv(Path(__file__).parent.parent / '.env')


def _has(v):
    return pd.notna(v) and str(v).strip() not in ('', 'None', 'nan')


def main():
    ap = argparse.ArgumentParser(description="Backfill quotable proud facts onto an enriched CSV")
    ap.add_argument('input')
    ap.add_argument('-o', '--output', help='default: overwrite input')
    ap.add_argument('-l', '--limit', type=int, help='only process the first N gradeable rows')
    ap.add_argument('--force', action='store_true', help='re-extract even if proud_facts exists')
    args = ap.parse_args()

    if not os.getenv('GEMINI_API_KEY'):
        print("ERROR: GEMINI_API_KEY not set"); sys.exit(1)
    jina_key = os.getenv('JINA_API_KEY')

    df = read_annotated_csv(args.input)
    if 'proud_facts' not in df.columns:
        df['proud_facts'] = ''
    if 'proud_facts_detail' not in df.columns:
        df['proud_facts_detail'] = ''

    gradeable = ~df['letter_grade'].astype(str).str.strip().isin(['INVALID', ''])
    targets = df[gradeable]
    if args.limit:
        targets = targets.head(args.limit)

    done = 0
    for idx, row in targets.iterrows():
        if not args.force and _has(row.get('proud_facts')):
            continue
        url = row.get('Domain')
        if not _has(url):
            continue
        c = extract_content(str(url), api_key=jina_key)
        facts = extract_proud_facts(c.get('content', ''), url=str(url)) if not c.get('error') else []
        df.at[idx, 'proud_facts'] = ' | '.join(f['fact'] for f in facts)
        df.at[idx, 'proud_facts_detail'] = json.dumps(facts, ensure_ascii=False) if facts else ''
        done += 1
        tag = (' | '.join(f['fact'] for f in facts)) or '(none)'
        print(f"[{done}] {url}: {tag[:100]}")

    write_annotated_csv(df, args.output or args.input)
    print(f"\nBackfilled proud_facts on {done} rows -> {args.output or args.input}")


if __name__ == '__main__':
    main()
