#!/usr/bin/env python3
"""Fetch a COMPLETED message batch and finish the pipeline (merge -> tone-fix -> QA -> assemble
-> review). If the batch isn't 'ended' yet, print status and exit fast (no long polling — so it
can be re-run periodically without being killed).

Usage: python scripts/finish_batch.py msgbatch_XXXX
"""
import json, re, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_messages_api as gm
from prep_bundles import tone_flag

BATCH_ID = sys.argv[1]
gm.load_env()
import anthropic
client = anthropic.Anthropic()

b = client.messages.batches.retrieve(BATCH_ID)
rc = b.request_counts
if b.processing_status != "ended":
    print(f"NOT_DONE status={b.processing_status} done={rc.succeeded} proc={rc.processing} err={rc.errored}")
    sys.exit(0)

print(f"ENDED: succeeded={rc.succeeded} errored={rc.errored} expired={rc.expired} canceled={rc.canceled}")
system, prospects = gm.build_system()
cid = lambda d: re.sub(r"[^\w]+", "_", d).strip("_")[:60]
cid2dom = {cid(p["domain"]): p["domain"] for p in prospects}
bybundle = {p["domain"]: p["bundle"] for p in prospects}


def cost_of(u):
    return (u.input_tokens * gm.IN_RATE + (u.cache_read_input_tokens or 0) * 0.1 * gm.IN_RATE
            + (u.cache_creation_input_tokens or 0) * 1.25 * gm.IN_RATE + u.output_tokens * gm.OUT_RATE) * 0.5


results, cost, errs = [], 0.0, []
for res in client.messages.batches.results(BATCH_ID):
    if res.result.type != "succeeded":
        errs.append((res.custom_id, res.result.type))
        continue
    msg = res.result.message
    txt = next((x.text for x in msg.content if x.type == "text"), "")
    obj = gm.extract_json(txt)
    dom = cid2dom.get(res.custom_id)
    if obj and dom:
        results.append(gm.finalize(obj, dom))
    cost += cost_of(msg.usage)
print(f"parsed {len(results)} results ({len(errs)} errored) | fetch cost ${cost:.2f}")
if errs:
    print("  errored:", errs[:8])

# inline tone fix-pass (realtime) on any flagged result
fixed = 0
for i, r in enumerate(results):
    if tone_flag(r.get("first_message"), r.get("second_message"), r.get("third_message")) != "clean":
        try:
            resp = client.messages.create(model=gm.MODEL, max_tokens=2000, system=system,
                thinking={"type": "disabled"},
                messages=[{"role": "user", "content": gm.USER_INSTR + json.dumps(bybundle[r["domain"]], indent=2, default=str) + gm.STEER}])
            t = next((x.text for x in resp.content if x.type == "text"), "")
            o2 = gm.extract_json(t)
            if o2:
                results[i] = gm.finalize(o2, r["domain"])
                fixed += 1
        except Exception as e:
            print("  fix err", r["domain"], str(e)[:60])
if fixed:
    print(f"tone-corrected {fixed} inline")

# merge
master = json.loads(gm.RESULTS.read_text())
by = {r["domain"]: r for r in master}
for r in results:
    by[r["domain"]] = r
gm.RESULTS.write_text(json.dumps(list(by.values()), indent=2))
print(f"merged {len(results)} -> now {len(by)}/795")

# post-batch QA sweep (tone/cta/casing/mech) + fix, then assemble
doms = [r["domain"] for r in results]
subprocess.run([sys.executable, str(gm.ROOT / "scripts" / "qa_check.py"), "--domains", ",".join(doms), "--fix"], check=False)
subprocess.run([sys.executable, str(gm.ROOT / "scripts" / "prep_bundles.py"), "assemble",
                str(gm.ENRICHED), str(gm.RESULTS), "-o", str(gm.MESSAGES)], check=True)

# review CSV
import pandas as pd
n = gm.next_batch_num()
df = pd.read_csv(gm.MESSAGES)
sub = df[df["Domain"].isin(doms)].copy()
order = {d: i for i, d in enumerate(doms)}
sub["_o"] = sub["Domain"].map(order)
sub = sub.sort_values("_o").drop(columns="_o")
review = gm.ROOT / "data" / f"REVIEW_batch_{n:03d}.csv"
sub[[c for c in gm.REVIEW_COLS if c in sub.columns]].to_csv(review, index=False)
print(f"DONE_FINISHED wrote {review.name} ({len(sub)} rows) | total {len(by)}/795")
