#!/usr/bin/env python3
"""
Add an `outreach_priority` column (from tech_stack + grade) across the enriched files,
and print a combined tech-stack count + priority breakdown across all ~1000 sites.

Priority rule:
  na     -> not gradeable/reachable (INVALID or no grade) -> don't reach out
  skip   -> Framer (we won't reach out to them)
  high   -> Webflow / WordPress (incl. WooCommerce)
  medium -> everything else gradeable (next.js, custom, react, hubspot, shopify, ...)
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import pandas as pd
from grader_fields import read_annotated_csv, write_annotated_csv

FILES = ['data/enriched_ALL_999.csv']  # canonical consolidated file (source batches removed)
GRADES = set(list('ABCDF') + [g + s for g in 'ABCDF' for s in ('+', '-')])


def priority(tech, grade):
    g = str(grade).strip()
    if g not in GRADES:               # INVALID, '', errors -> not a live/reachable target
        return 'na'
    t = str(tech).strip().lower()
    if 'framer' in t:
        return 'skip'
    if 'webflow' in t or 'wordpress' in t or 'woocommerce' in t:
        return 'high'
    return 'medium'


def main():
    combined_tech = {}
    combined_prio = {}
    total = 0
    for f in FILES:
        if not Path(f).exists():
            print(f"(missing: {f})"); continue
        d = read_annotated_csv(f)
        d['outreach_priority'] = [priority(t, g) for t, g in zip(d['tech_stack'], d['letter_grade'])]
        write_annotated_csv(d, f)
        total += len(d)
        # tally tech (gradeable only, for outreach relevance) and priority (all)
        lg = d['letter_grade'].astype(str).str.strip()
        for t in d.loc[lg.isin(GRADES), 'tech_stack'].astype(str).str.strip().str.lower():
            combined_tech[t or '(none)'] = combined_tech.get(t or '(none)', 0) + 1
        for p in d['outreach_priority']:
            combined_prio[p] = combined_prio.get(p, 0) + 1
        print(f"flagged {f}  ({len(d)} rows)")

    print(f"\n================ ALL {total} SITES ================")
    print("\nOUTREACH PRIORITY breakdown:")
    for p in ('high', 'medium', 'skip', 'na'):
        if p in combined_prio:
            print(f"  {p:<7} {combined_prio[p]}")

    print("\nTECH STACK (gradeable/live sites only):")
    for t, c in sorted(combined_tech.items(), key=lambda x: -x[1]):
        print(f"  {t:<22} {c}")


if __name__ == '__main__':
    main()
