#!/usr/bin/env python3
"""
Generate a report.md overview for a graded batch.

Run this after every full-list grading so we always have an at-a-glance overview
(counts, outreach-priority split, tech-stack breakdown, grade distribution).

Usage:
  python scripts/generate_report.py data/enriched_ALL_999.csv
  python scripts/generate_report.py data/enriched_ALL_999.csv -o data/report_ALL_999.md
If -o is omitted, writes <input_dir>/report_<input_stem>.md
"""
import sys
import argparse
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from grader_fields import read_annotated_csv

GRADES = set(list('ABCDF') + [g + s for g in 'ABCDF' for s in ('+', '-')])
GRADE_ORDER = ['A+', 'A', 'A-', 'B+', 'B', 'B-', 'C+', 'C', 'C-', 'D+', 'D', 'D-', 'F']
PRIORITY_LABEL = {'high': '🟢 high', 'medium': 'medium', 'skip': '⛔ skip', 'na': 'na'}


def priority_for(tech, grade):
    if str(grade).strip() not in GRADES:
        return 'na'
    t = str(tech).strip().lower()
    if 'framer' in t:
        return 'skip'
    if 'webflow' in t or 'wordpress' in t or 'woocommerce' in t:
        return 'high'
    return 'medium'


def tnorm(t):
    t = str(t).strip().lower()
    return t if t and t != 'nan' else '(none/unknown)'


def main():
    ap = argparse.ArgumentParser(description='Generate a batch overview report.md')
    ap.add_argument('input', help='Enriched CSV path')
    ap.add_argument('-o', '--output', help='Output markdown path')
    args = ap.parse_args()

    in_path = Path(args.input)
    df = read_annotated_csv(str(in_path))
    out_path = Path(args.output) if args.output else in_path.parent / f"report_{in_path.stem}.md"

    lg = df['letter_grade'].astype(str).str.strip().replace('nan', '')
    gradeable = df[lg.isin(GRADES)].copy()
    total = len(df)
    n_grade = len(gradeable)
    n_invalid = int((lg == 'INVALID').sum())
    n_other = total - n_grade - n_invalid

    # priority (recompute so the report is self-consistent regardless of stored col)
    if 'outreach_priority' in df.columns:
        prio = df['outreach_priority'].astype(str).str.strip()
    else:
        prio = df.apply(lambda r: priority_for(r.get('tech_stack'), r.get('letter_grade')), axis=1)
    prio_counts = {p: int((prio == p).sum()) for p in ('high', 'medium', 'skip', 'na')}
    reachable = prio_counts['high'] + prio_counts['medium']

    # tech (gradeable only)
    gradeable['_t'] = gradeable['tech_stack'].apply(tnorm)
    gradeable['_p'] = [priority_for(t, g) for t, g in zip(gradeable['tech_stack'], gradeable['letter_grade'])]
    tech_counts = gradeable['_t'].value_counts()

    # grade distribution
    grade_counts = gradeable['letter_grade'].astype(str).str.strip().value_counts()

    L = []
    L.append(f"# Batch Report — {in_path.name}")
    L.append("")
    L.append(f"_Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}_")
    L.append("")
    L.append("## Summary")
    L.append("")
    L.append("| Metric | Count |")
    L.append("|---|---:|")
    L.append(f"| Total rows | {total} |")
    L.append(f"| Real grades (live sites) | {n_grade} |")
    L.append(f"| INVALID | {n_invalid} |")
    L.append(f"| Unprocessed / dead | {n_other} |")
    L.append(f"| **Outreach pool (high+medium)** | **{reachable}** |")
    L.append("")
    L.append("## Outreach priority")
    L.append("")
    L.append("| Priority | Count | % of total |")
    L.append("|---|---:|---:|")
    for p in ('high', 'medium', 'skip', 'na'):
        c = prio_counts[p]
        L.append(f"| {PRIORITY_LABEL[p]} | {c} | {c/total*100:.1f}% |")
    L.append("")
    L.append(f"## Tech stack (gradeable/live sites only — {n_grade})")
    L.append("")
    L.append("| Tech | Count | % | Priority |")
    L.append("|---|---:|---:|---|")
    for t, c in tech_counts.items():
        p = priority_for(t, 'A')  # grade placeholder; priority by tech only here
        L.append(f"| {t} | {c} | {c/n_grade*100:.1f}% | {PRIORITY_LABEL[p]} |")
    L.append("")
    L.append("## Grade distribution (gradeable sites)")
    L.append("")
    L.append("| Grade | Count |")
    L.append("|---|---:|")
    for g in GRADE_ORDER:
        if g in grade_counts:
            L.append(f"| {g} | {int(grade_counts[g])} |")
    L.append("")

    out_path.write_text("\n".join(L), encoding='utf-8')
    print(f"Wrote {out_path}")
    print(f"  {total} rows | {n_grade} graded | reachable pool {reachable}")


if __name__ == '__main__':
    main()
