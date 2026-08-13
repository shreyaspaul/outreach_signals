#!/usr/bin/env python3
"""
Adjudicate whether the claim we make in message 1 is STILL TRUE of the site as it exists today.

Pixel-diff alone can't decide this: tella.com scored 0.167 purely because a hero carousel was on
a different tab at capture time (no redesign at all), while nexcade.ai fully rebranded. So we take
every site the detector flagged, show a vision model the CURRENT screenshot, and ask the only
question that matters: does our specific criticism still hold?

Verdicts:
  HOLDS   - claim is still accurate; the message is safe to send
  BROKEN  - the site changed and the claim is now false (nexcade: "stock imagery" -> rebranded)
  UNSURE  - cannot tell from the screenshot; treated as unsafe

Usage:
  python scripts/verify_signal_live.py --limit 5
  python scripts/verify_signal_live.py --all --batch
"""
import argparse, base64, csv, json, os, re, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_messages_api import load_env, extract_json
from website_grader import clean_domain

ROOT = Path(__file__).resolve().parent.parent
BATCH = os.environ.get("LEADS_BATCH", "batch_01")
DATA = ROOT / "data" / BATCH
NEW_SHOTS = ROOT / "screenshots_recheck"
CHANGES = DATA / "site_changes.csv"
OUT = DATA / "signal_verdicts.json"
MODEL = "claude-sonnet-5"
IN_RATE, OUT_RATE = 3e-6, 15e-6

SYSTEM = """You are auditing a cold-outreach message before it is sent, to make sure it does not
insult a company for a problem they have already fixed.

You get a screenshot of the company's website AS IT IS TODAY, plus the specific criticism our
message makes about their site. The site may have been redesigned since we audited it.

Answer one question: is that criticism STILL TRUE of the site in this screenshot?

Be strict and literal about the claim:
- "leans on stock imagery" is BROKEN if the site now uses custom/branded visuals or none.
- "generic / safe / undistinctive design" is BROKEN if the site now has a strong, deliberate,
  distinctive visual identity.
- "thin content / no proof / no customer logos" is BROKEN if the page now shows real proof,
  named customers, testimonials or metrics.
- "near-empty / placeholder hero" is BROKEN if the hero is now full and finished.
If the site plainly still has the problem, the claim HOLDS.
If you cannot judge it from this screenshot, say UNSURE.

Note: performance/speed claims (slow load, layout shift) cannot be judged from a screenshot.
For those, answer UNSURE unless the page is visibly broken or clearly rebuilt.

Output ONLY JSON:
{"verdict": "HOLDS" | "BROKEN" | "UNSURE", "reason": "<one short sentence citing what you see>"}"""


def img_block(path: Path):
    data = base64.standard_b64encode(path.read_bytes()).decode()
    return {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--batch", action="store_true")
    ap.add_argument("--min-diff", type=float, default=0.10,
                    help="only adjudicate rows at/above this visual diff (plus unknowns)")
    args = ap.parse_args()

    load_env()
    import anthropic
    client = anthropic.Anthropic()

    changes = {r["domain"]: r for r in csv.DictReader(open(CHANGES))}
    msgs = {r["domain"]: r for r in csv.DictReader(open(DATA / "outreach_ready.csv"))}

    todo = []
    for dom, c in changes.items():
        vd = c["visual_diff"]
        flagged = (vd and float(vd) >= args.min_diff) or c["changed"] == "UNKNOWN" or not vd
        if not flagged or dom not in msgs:
            continue
        shot = NEW_SHOTS / f"{clean_domain(msgs[dom].get('message_Domain') or dom)}.png"
        if not shot.exists():
            continue
        todo.append((dom, c, shot))

    if not args.all:
        todo = todo[: args.limit]
    print(f"Adjudicating {len(todo)} flagged sites against their CURRENT screenshot "
          f"({'BATCH' if args.batch else 'realtime'})...")

    def params(dom, c, shot):
        m = msgs[dom]
        user = [
            img_block(shot),
            {"type": "text", "text":
                f"Company: {m['Company Name']} ({dom})\n"
                f"The criticism our message makes: \"{c['chosen_signal']}\" "
                f"(category: {c['signal_category']})\n\n"
                f"Is that criticism still true of the site in this screenshot?"},
        ]
        return dict(model=MODEL, max_tokens=300, thinking={"type": "disabled"},
                    system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
                    messages=[{"role": "user", "content": user}])

    def cost_of(u, batched=False):
        # The Batch API bills at 50%. Omitting this made every batched run report ~2x its real
        # cost, which is worse than reporting nothing: it silently overstates spend.
        mult = 0.5 if batched else 1.0
        return mult * (u.input_tokens * IN_RATE + (u.cache_read_input_tokens or 0) * 0.1 * IN_RATE
                       + (u.cache_creation_input_tokens or 0) * 1.25 * IN_RATE + u.output_tokens * OUT_RATE)

    verdicts, cost = {}, 0.0
    if args.batch:
        from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
        from anthropic.types.messages.batch_create_params import Request
        cid = lambda d: re.sub(r"[^\w]+", "_", d).strip("_")[:60]
        reqs = [Request(custom_id=cid(d), params=MessageCreateParamsNonStreaming(**params(d, c, s)))
                for d, c, s in todo]
        c2d = {cid(d): d for d, _, _ in todo}
        mb = client.messages.batches.create(requests=reqs)
        print(f"  batch {mb.id} submitted, polling...")
        while True:
            b = client.messages.batches.retrieve(mb.id)
            if b.processing_status == "ended":
                break
            time.sleep(20)
        for res in client.messages.batches.results(mb.id):
            dom = c2d.get(res.custom_id)
            if res.result.type != "succeeded":
                verdicts[dom] = {"verdict": "UNSURE", "reason": "api failed"}
                continue
            txt = next((x.text for x in res.result.message.content if x.type == "text"), "")
            cost += cost_of(res.result.message.usage, batched=True)
            verdicts[dom] = extract_json(txt) or {"verdict": "UNSURE", "reason": "unparseable"}
    else:
        for i, (dom, c, shot) in enumerate(todo, 1):
            resp = client.messages.create(**params(dom, c, shot))
            txt = next((x.text for x in resp.content if x.type == "text"), "")
            cost += cost_of(resp.usage)
            v = extract_json(txt) or {"verdict": "UNSURE", "reason": "unparseable"}
            verdicts[dom] = v
            print(f"  [{i}/{len(todo)}] {dom:<26} {v['verdict']:<7} {v.get('reason','')[:60]}")

    for d, v in verdicts.items():
        v["visual_diff"] = changes[d]["visual_diff"]
        v["chosen_signal"] = changes[d]["chosen_signal"]
    OUT.write_text(json.dumps(verdicts, indent=1))
    import collections
    tally = collections.Counter(v["verdict"] for v in verdicts.values())
    print(f"\n{dict(tally)}  -> {OUT}   (cost ~${cost:.2f})")


if __name__ == "__main__":
    main()
