#!/usr/bin/env python3
"""Merge a chunk JSON (a list of result objects Claude just wrote) into the batch's
message_results file, dedup by domain. Part of the no-API generation loop — see
scripts/outreach_loop/RUN_LOOP.md.

Usage:  python scripts/outreach_loop/merge_results.py <chunk.json>
Writes data/<LEADS_BATCH>/<RESULTS_FILE> (defaults: batch_01 / message_results_v3.json).
"""
import json, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BATCH = os.environ.get("LEADS_BATCH", "batch_01")
R = ROOT / "data" / BATCH / os.environ.get("RESULTS_FILE", "message_results_v3.json")

chunk = json.loads(Path(sys.argv[1]).read_text())
existing = json.loads(R.read_text()) if R.exists() else []
by = {r["domain"]: r for r in existing}
for r in chunk:
    by[r["domain"]] = r
R.write_text(json.dumps(list(by.values()), indent=2))
print(f"Merged {len(chunk)} -> total {len(by)} in {R.name}")
