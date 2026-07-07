#!/usr/bin/env python3
"""
Data prep + assembly for CLAUDE-generated outreach messages.

We no longer call an LLM API to WRITE messages (no Gemini credits). Instead the
writing is done by Claude inside a terminal session, following the skill at
`.claude/skills/generate-outreach/SKILL.md`. This script is just the plumbing:

  1. `dump`     -> pull each gradeable prospect's full audit into a JSON bundle
                   that Claude reads.
  2. (Claude writes the messages -> a results JSON)
  3. `assemble` -> merge Claude's results JSON back into a messages CSV
                   (same schema as before, runs sanitize()).

Usage:
  python scripts/prep_bundles.py dump data/enriched_20260616_023344.csv --limit 10 \
      -o data/message_bundles.json
  python scripts/prep_bundles.py assemble data/enriched_20260616_023344.csv \
      data/message_results.json -o data/messages_v2.csv
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import pandas as pd
from grader_fields import read_annotated_csv
from message_generator import build_prospect, DATA_DICTIONARY, sanitize, _val, accurate_visits

# Extra context fields useful for the INFERENCE move, beyond what build_prospect carries.
EXTRA_DICT = {
    "industry": "Their industry / category.",
    "funding_total": "Total equity funding raised (signals stage & expectations).",
    "funding_last": "Most recent funding round amount.",
    "all_tech": "Everything detected in their stack (e.g. wordpress + old plugins).",
}


def _gradeable(input_path):
    df = read_annotated_csv(input_path)
    return df[~df['letter_grade'].astype(str).str.strip().isin(['INVALID', ''])]


def cmd_dump(args):
    gradeable = _gradeable(args.input)
    # Optionally restrict to the exact domains present in another CSV (e.g. an existing
    # messages sheet), so we can re-dump just those entries from a larger enriched file.
    if args.only_from:
        keep = set(pd.read_csv(args.only_from)['Domain'].astype(str))
        gradeable = gradeable[gradeable['Domain'].astype(str).isin(keep)]
    start = args.offset or 0
    if args.limit is not None:
        gradeable = gradeable.iloc[start:start + args.limit]
    elif start:
        gradeable = gradeable.iloc[start:]
    # Sort by tech stack so Webflow vs other stacks are grouped (drives msg-1 identity).
    if 'tech_stack' in gradeable.columns:
        gradeable = gradeable.sort_values(
            'tech_stack', key=lambda s: s.astype(str).str.lower(), kind='stable')

    prospects = []
    for _, row in gradeable.iterrows():
        bundle = build_prospect(row)
        for key, col in (("industry", "Industry"), ("funding_total", "Total Equity Funding Amount"),
                         ("funding_last", "Last Equity Funding Amount"), ("all_tech", "all_tech_detected")):
            v = _val(row, col)
            if v is not None:
                bundle[key] = v
        prospects.append({
            "domain": _val(row, 'Domain'),
            "name": _val(row, 'Name', 'there'),
            "bundle": bundle,
        })

    out = {"data_dictionary": {**DATA_DICTIONARY, **EXTRA_DICT}, "prospects": prospects}
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(out, indent=2, default=str))
    print(f"Wrote {len(prospects)} prospect bundles -> {args.output}")


# Every non-skip result MUST carry these, or the message sheet is silently incomplete.
# (case_study_name/url may be "none"/"" for relevance-gated skips; quotable_fact_to_use
# may be "none"; but the analyst metadata and all three messages are always required.)
REQUIRED_RESULT_FIELDS = [
    'priority', 'signal_category', 'chosen_signal', 'inference', 'why_it_matters',
    'genuine_positive', 'quotable_fact_to_use', 'case_study_name',
    'first_message', 'second_message', 'third_message',
]


def _validate_results(matched):
    """Return list of (domain, missing_field) for any non-skip result missing a required field."""
    problems = []
    for r in matched:
        if str(r.get('priority', '')).strip().lower() == 'skip':
            continue
        for f in REQUIRED_RESULT_FIELDS:
            v = r.get(f)
            if v is None or str(v).strip() == '':
                problems.append((r.get('domain', '?'), f))
    return problems


# QA aid: flag the genuinely arrogant/presumptuous framings (kept tight — the mild
# "deciding whether to trust <the process>" softie is intentionally NOT flagged).
_ARROGANT = ["evaluating you against", "sizing you up", "size you up", "judging you",
             "judge you", "before they read a word", "before you read a word",
             "read a word", "prove you're", "proving you're", "against your own promise",
             "against your promise", "scrutin"]


def tone_flag(*msgs):
    low = " ".join(str(m or "").lower() for m in msgs)
    hits = [p for p in _ARROGANT if p in low]
    return ("review: " + "; ".join(hits)) if hits else "clean"


def cmd_assemble(args):
    results = json.loads(Path(args.results).read_text())
    by_domain = {r.get('domain'): r for r in results}

    rows = []
    matched = []
    for _, row in _gradeable(args.input).iterrows():
        dom = _val(row, 'Domain')
        r = by_domain.get(dom)
        if not r:
            continue
        matched.append(r)
        rows.append({
            'Name': _val(row, 'Name'), 'Domain': dom,
            'tech_stack': _val(row, 'tech_stack'),
            'monthly_visits': accurate_visits(row),
            'letter_grade': _val(row, 'letter_grade'),
            'priority': r.get('priority'),
            'signal_category': r.get('signal_category'),
            'chosen_signal': r.get('chosen_signal'),
            'angle_rationale': r.get('angle_rationale', 'none'),
            'inference': r.get('inference'),
            'why_it_matters': r.get('why_it_matters'),
            'use_traffic_scale': r.get('use_traffic_scale'),
            'genuine_positive': r.get('genuine_positive'),
            'quotable_fact_to_use': r.get('quotable_fact_to_use'),
            'secondary_point': r.get('secondary_point', 'none'),
            'secondary_reasoning': r.get('secondary_reasoning', 'none'),
            'case_study_name': r.get('case_study_name'),
            'case_study_rationale': r.get('case_study_rationale', 'none'),
            'case_study_url': r.get('case_study_url'),
            'tone_flag': tone_flag(r.get('first_message'), r.get('second_message'),
                                   r.get('third_message')),
            'first_message': sanitize(r.get('first_message')),
            'second_message': sanitize(r.get('second_message')),
            'third_message': sanitize(r.get('third_message')),
        })

    # GUARD: refuse to write a silently-incomplete sheet (e.g. a builder that forgot
    # to populate inference/chosen_signal/etc). Lists exactly what's missing.
    problems = _validate_results(matched)
    if problems and not args.allow_incomplete:
        from collections import defaultdict
        by_field = defaultdict(list)
        for dom, f in problems:
            by_field[f].append(dom)
        print(f"ERROR: {len(problems)} missing required field(s) across "
              f"{len(set(d for d, _ in problems))} entries. NOT writing {args.output}.")
        for f, doms in sorted(by_field.items()):
            shown = ', '.join(doms[:8]) + (f" (+{len(doms)-8} more)" if len(doms) > 8 else '')
            print(f"  - {f}: {len(doms)} missing -> {shown}")
        print("Fix the results JSON (or pass --allow-incomplete to override).")
        sys.exit(1)

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    out_df = pd.DataFrame(rows)
    if 'tech_stack' in out_df.columns:  # sort entries by tech stack
        out_df = out_df.sort_values(
            'tech_stack', key=lambda s: s.astype(str).str.lower(), kind='stable')
    out_df.to_csv(args.output, index=False)
    if problems:
        print(f"  WARNING: wrote with {len(problems)} missing field(s) (--allow-incomplete).")
    missing = [d for d in by_domain if d not in {_val(row, 'Domain') for _, row in _gradeable(args.input).iterrows()}]
    print(f"Assembled {len(rows)} messages -> {args.output}")
    if missing:
        print(f"  WARNING: {len(missing)} result domains not matched to CSV: {missing}")


def main():
    ap = argparse.ArgumentParser(description="Prep/assemble for Claude-generated outreach")
    sub = ap.add_subparsers(dest='cmd', required=True)

    d = sub.add_parser('dump', help='extract prospect bundles to JSON')
    d.add_argument('input')
    d.add_argument('--limit', type=int)
    d.add_argument('--offset', type=int, default=0, help='skip the first N gradeable rows (CSV order)')
    d.add_argument('--only-from', help='restrict to domains present in this CSV (its Domain column)')
    d.add_argument('-o', '--output', default='data/message_bundles.json')
    d.set_defaults(func=cmd_dump)

    a = sub.add_parser('assemble', help='merge Claude results JSON into messages CSV')
    a.add_argument('input')
    a.add_argument('results')
    a.add_argument('-o', '--output', default='data/messages_v2.csv')
    a.add_argument('--allow-incomplete', action='store_true',
                   help='write even if some entries are missing required fields (default: refuse)')
    a.set_defaults(func=cmd_assemble)

    args = ap.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
