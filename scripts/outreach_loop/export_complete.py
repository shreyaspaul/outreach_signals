#!/usr/bin/env python3
"""Export the MESSAGE TEXT for prospects with a COMPLETE 3-message sequence, as a lean CSV.

⚠️ This is NOT the file you import into the outreach tool — it is keyed by company domain and
still contains the literal {first-name} token, with no person attached. To actually send, run
`scripts/build_outreach_list.py` (MESSAGES_FILE=messages_v3.csv OUT_SUFFIX=_v3), which picks one
best contact per company, attaches their name/title/LinkedIn/email and fills in {first-name}
-> outreach_ready_v3.csv. Use this script for reviewing/QA-ing the words themselves.

Complete = all three messages present, non-blank, and not the literal "SKIP" placeholder.
Re-runnable: run it again after each loop cycle to refresh the export.

Usage:  python scripts/outreach_loop/export_complete.py [-o OUT]
Resolves data/<LEADS_BATCH>/ (default batch_01); reads MESSAGES_FILE (default messages_v3.csv).
"""
import argparse, csv, os, sys
from pathlib import Path

csv.field_size_limit(10**9)

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / os.environ.get("LEADS_BATCH", "batch_01")
SRC = DATA / os.environ.get("MESSAGES_FILE", "messages_v3.csv")

MSG = ("first_message", "second_message", "third_message")
# lean set: identity + the words. Reasoning columns stay in messages_v3.csv for review.
COLS = ("Name", "Domain", "priority", "signal_category", "chosen_signal",
        "case_study_name", "case_study_url") + MSG

ap = argparse.ArgumentParser()
ap.add_argument("-o", "--out", default=str(DATA / "messages_v3_complete.csv"))
args = ap.parse_args()

with SRC.open(newline="") as fh:
    rows = list(csv.DictReader(fh))

complete, dropped = [], []
for r in rows:
    vals = [(r.get(m) or "").strip() for m in MSG]
    if all(v and v.upper() != "SKIP" for v in vals):
        complete.append(r)
    else:
        dropped.append(r.get("Domain", "?"))

out = Path(args.out)
with out.open("w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=COLS, extrasaction="ignore")
    w.writeheader()
    w.writerows(complete)

print(f"source: {SRC.name}  rows: {len(rows)}")
print(f"complete: {len(complete)}  dropped: {len(dropped)}")
if dropped:
    print("  dropped:", ", ".join(dropped[:20]))
# sanity: the merge token must survive into every message
missing_tok = [r["Domain"] for r in complete
               if not all("{first-name}" in (r.get(m) or "") for m in MSG)]
print(f"rows missing the {{first-name}} token: {len(missing_tok)}"
      + (f" -> {missing_tok[:10]}" if missing_tok else ""))
print(f"wrote -> {out}")
