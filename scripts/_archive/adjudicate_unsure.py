#!/usr/bin/env python3
"""
Second pass for the UNSURE rows: show the BEFORE and AFTER screenshots together.

A single screenshot can't settle claims like "design blends in" (subjective) or "the testimonial
has an error" (section not visible). But we don't actually need to re-derive the claim from
scratch: the June audit already established it was true THEN. The only question is whether the
site changed in a way that makes it false NOW. That is answerable from the pair.

  SAME   - site is materially unchanged in the respect the claim is about -> claim still holds
  FIXED  - the site changed and the claim no longer applies -> do not send
  UNSURE - still cannot tell -> treated as unsafe

Usage: python scripts/adjudicate_unsure.py [--batch]
"""
import argparse, base64, csv, json, os, re, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_messages_api import load_env, extract_json
from website_grader import clean_domain

ROOT = Path(__file__).resolve().parent.parent
BATCH = os.environ.get("LEADS_BATCH", "batch_01")
DATA = ROOT / "data" / BATCH
OLD, NEW = ROOT / "screenshots", ROOT / "screenshots_recheck"
VERDICTS = DATA / "signal_verdicts.json"
MODEL = "claude-sonnet-5"
IN_RATE, OUT_RATE = 3e-6, 15e-6

SYSTEM = """You are checking a cold-outreach message before it is sent, so we never criticise a
company for something they have already fixed.

You get TWO screenshots of the same website:
  IMAGE 1 = BEFORE, when we audited it (a few weeks ago)
  IMAGE 2 = NOW
Plus the specific criticism our message makes. That criticism was accurate at BEFORE.

Decide whether the site has changed in a way that makes the criticism no longer true.

  SAME  - the site is materially the same in the respect the criticism is about (it may differ in
          minor ways: a rotated carousel, a new banner, reworded copy). The criticism still holds.
  FIXED - the site changed in a way that defeats the criticism. Examples: it was generic and is now
          a distinctive branded design; it leaned on stock imagery and now uses custom visuals; it
          lacked proof and now shows named customers, metrics or testimonials; the placeholder hero
          is now finished.
  UNSURE - you genuinely cannot tell from these two images.

Be honest. A false SAME means we insult someone for a problem they fixed. A false FIXED only costs
us one prospect. When truly torn, choose UNSURE.

Output ONLY JSON: {"verdict": "SAME" | "FIXED" | "UNSURE", "reason": "<one short sentence>"}"""


def img(path: Path):
    return {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                        "data": base64.standard_b64encode(path.read_bytes()).decode()}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", action="store_true")
    ap.add_argument("--verdicts", default="UNSURE",
                    help="comma-separated verdicts to re-adjudicate with BEFORE+AFTER pairs")
    args = ap.parse_args()
    want = set(args.verdicts.upper().split(","))

    load_env()
    import anthropic
    client = anthropic.Anthropic()

    verdicts = json.loads(VERDICTS.read_text())
    ready = {r["domain"]: r for r in csv.DictReader(open(DATA / "outreach_ready.csv"))}

    todo = []
    for dom, v in verdicts.items():
        if v["verdict"] not in want or dom not in ready:
            continue
        stem = clean_domain(ready[dom].get("message_Domain") or dom)
        o, n = OLD / f"{stem}.png", NEW / f"{stem}.png"
        if o.exists() and n.exists():
            todo.append((dom, v, o, n))
    print(f"Re-adjudicating {len(todo)} UNSURE rows with BEFORE+AFTER pairs...")

    def params(dom, v, o, n):
        return dict(model=MODEL, max_tokens=300, thinking={"type": "disabled"},
                    system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
                    messages=[{"role": "user", "content": [
                        {"type": "text", "text": "IMAGE 1 = BEFORE (when we audited):"}, img(o),
                        {"type": "text", "text": "IMAGE 2 = NOW:"}, img(n),
                        {"type": "text", "text":
                            f"Company: {ready[dom]['Company Name']} ({dom})\n"
                            f"Our criticism: \"{v['chosen_signal']}\"\n\n"
                            f"Has the site changed so that this criticism is no longer true?"}]}])

    def cost_of(u, batched=False):
        # The Batch API bills at 50%. Omitting this made every batched run report ~2x its real
        # cost, which is worse than reporting nothing: it silently overstates spend.
        mult = 0.5 if batched else 1.0
        return mult * (u.input_tokens * IN_RATE + (u.cache_read_input_tokens or 0) * 0.1 * IN_RATE
                       + (u.cache_creation_input_tokens or 0) * 1.25 * IN_RATE + u.output_tokens * OUT_RATE)

    cost = 0.0
    if args.batch:
        from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
        from anthropic.types.messages.batch_create_params import Request
        cid = lambda d: re.sub(r"[^\w]+", "_", d).strip("_")[:60]
        reqs = [Request(custom_id=cid(d), params=MessageCreateParamsNonStreaming(**params(d, v, o, n)))
                for d, v, o, n in todo]
        c2d = {cid(d): d for d, _, _, _ in todo}
        mb = client.messages.batches.create(requests=reqs)
        print(f"  batch {mb.id}, polling...")
        while True:
            b = client.messages.batches.retrieve(mb.id)
            if b.processing_status == "ended":
                break
            time.sleep(20)
        for res in client.messages.batches.results(mb.id):
            dom = c2d.get(res.custom_id)
            if res.result.type != "succeeded":
                continue
            cost += cost_of(res.result.message.usage, batched=True)
            txt = next((x.text for x in res.result.message.content if x.type == "text"), "")
            o = extract_json(txt) or {}
            apply_verdict(verdicts, dom, o)
    else:
        for i, (dom, v, o, n) in enumerate(todo, 1):
            resp = client.messages.create(**params(dom, v, o, n))
            cost += cost_of(resp.usage)
            txt = next((x.text for x in resp.content if x.type == "text"), "")
            obj = extract_json(txt) or {}
            apply_verdict(verdicts, dom, obj)
            print(f"  [{i}/{len(todo)}] {dom:<26} {verdicts[dom]['verdict']:<7} {obj.get('reason','')[:55]}")

    VERDICTS.write_text(json.dumps(verdicts, indent=1))
    import collections
    print("\nfinal:", dict(collections.Counter(v["verdict"] for v in verdicts.values())), f"(cost ~${cost:.2f})")


def apply_verdict(verdicts, dom, obj):
    v = (obj.get("verdict") or "UNSURE").upper()
    verdicts[dom]["verdict"] = {"SAME": "HOLDS", "FIXED": "BROKEN"}.get(v, "UNSURE")
    verdicts[dom]["reason"] = obj.get("reason", "")


if __name__ == "__main__":
    main()
