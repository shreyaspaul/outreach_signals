#!/usr/bin/env python3
"""Print the next N unwritten prospect bundles (all decision-relevant fields), for Claude to
write outreach messages from IN-SESSION (no API). Part of the no-API generation loop — see
scripts/outreach_loop/RUN_LOOP.md.

Usage:  python scripts/outreach_loop/next_bundles.py [N]
Resolves data/<LEADS_BATCH>/ (default batch_01); reads RESULTS_FILE (default message_results_v3.json)
to know what's already written, so it only ever shows unwritten prospects.
"""
import json, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BATCH = os.environ.get("LEADS_BATCH", "batch_01")
DATA = ROOT / "data" / BATCH
B = DATA / "message_bundles_all.json"
R = DATA / os.environ.get("RESULTS_FILE", "message_results_v3.json")

N = int(sys.argv[1]) if len(sys.argv) > 1 else 15
prospects = json.loads(B.read_text())["prospects"]
done = {r["domain"] for r in json.loads(R.read_text())} if R.exists() else set()
todo = [p for p in prospects if p["domain"] not in done]

print(f"WRITTEN: {len(done)} | REMAINING: {len(todo)} | showing next {min(N, len(todo))}")
FIELDS = ("name", "what_they_do", "tech_stack", "monthly_visits", "traffic_is_high", "industry",
          "funding", "design_score", "design_really_lacking", "content_score", "content_really_thin",
          "performance_really_poor", "desktop_speed_score", "real_user_load_seconds",
          "real_user_responsiveness_ms")
for p in todo[:N]:
    b = p["bundle"]
    print("=" * 72)
    print(f"DOMAIN: {p['domain']} | first_name: {b.get('first_name')}")
    for k in FIELDS:
        print(f"  {k}: {b.get(k)}")
    print(f"  proof_from_site: {b.get('proof_from_site')}")
    print(f"  quotable_facts: {b.get('quotable_facts')}")
    print(f"  design_reasoning: {(b.get('design_reasoning') or '')[:260]}")
    print(f"  content_reasoning: {(b.get('content_reasoning') or '')[:260]}")
    sec = b.get("secondary_signals")
    print(f"  secondary_signals: {json.dumps(sec) if sec else None}")
