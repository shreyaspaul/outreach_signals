#!/usr/bin/env python3
"""
Generate outreach messages via the Claude API (Sonnet 5) using the generate-outreach
SKILL.md as a cached system prompt. Picks the next N unwritten gradeable prospects from
data/message_bundles_all.json, authors each, applies a deterministic brand-casing backstop,
merges into data/message_results.json, runs `assemble`, and writes a full-column
REVIEW_batch_XXX.csv (same columns as prior review batches, plus the tone_flag column).

Usage:
  python scripts/generate_messages_api.py --limit 18                # next 18, realtime
  python scripts/generate_messages_api.py --limit 380 --batch       # all remaining via Batch API (-50%)
"""
import argparse, json, os, re, subprocess, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from prep_bundles import tone_flag  # reuse the exact arrogant-phrase check

ROOT = Path(__file__).resolve().parent.parent

# appended to the user message when a first draft trips the tone check, to force a rewrite
STEER = ("\n\nIMPORTANT REWRITE NOTE: your previous draft used a BANNED arrogant phrase "
         "(e.g. 'sizing you up', 'evaluating you', 'judging you', 'before they read a word'). "
         "The reader is NOT scrutinizing or judging you. Rewrite every message so no framing "
         "casts their visitors as skeptics/evaluators. Keep it warm and credit-giving.")
# Each batch of leads lives in its own folder: data/<batch>/ (default batch_01).
# Switch batches with the LEADS_BATCH env var, e.g. `LEADS_BATCH=batch_02 python scripts/...`.
BATCH = os.environ.get("LEADS_BATCH", "batch_01")
DATA = ROOT / "data" / BATCH
BUNDLES = DATA / "message_bundles_all.json"
SKILL = ROOT / ".claude" / "skills" / "generate-outreach" / "SKILL.md"
RESULTS = DATA / "message_results.json"
ENRICHED = next(iter(sorted(DATA.glob("enriched_*.csv"))), DATA / "enriched_ALL_999.csv")
MESSAGES = DATA / "messages_v2.csv"
MODEL = "claude-sonnet-5"
IN_RATE, OUT_RATE = 3e-6, 15e-6  # Sonnet 5 standard $/token

REQUIRED = ["priority", "signal_category", "chosen_signal", "inference", "why_it_matters",
            "genuine_positive", "quotable_fact_to_use", "case_study_name",
            "first_message", "second_message", "third_message"]
REVIEW_COLS = ["Name", "Domain", "tech_stack", "monthly_visits", "letter_grade", "priority",
               "signal_category", "chosen_signal", "angle_rationale", "inference",
               "why_it_matters", "use_traffic_scale", "genuine_positive", "quotable_fact_to_use",
               "secondary_point", "secondary_reasoning", "case_study_name", "case_study_rationale",
               "case_study_url", "tone_flag", "first_message", "second_message", "third_message"]

USER_INSTR = (
    "You are given ONE prospect bundle below (JSON). Ignore any procedure in the system "
    "prompt about dump/assemble scripts or writing files. Author the 3-message outreach "
    "for THIS ONE prospect following every rule in the system prompt, and output ONLY a "
    "single JSON object matching the OUTPUT SCHEMA (all fields, including angle_rationale, "
    "case_study_rationale, second_message, third_message). No prose, no markdown.\n\nBUNDLE:\n"
)

# ---- deterministic brand-casing backstop (models occasionally lowercase brand nouns) ----
_MULTI = [("google ads", "Google Ads"), ("microsoft ads", "Microsoft Ads"), ("meta pixel", "Meta Pixel"),
          ("google analytics", "Google Analytics"), ("google's", "Google's"), ("ai overviews", "AI overviews")]
_CASE_STUDIES = {"webless": "Webless", "flatable": "Flatable", "qmin": "Qmin", "newscatcher": "NewsCatcher",
                 "wondersimple": "Wondersimple", "amalia": "Amalia", "yourculture": "YourCulture"}
_BRAND = {"webflow": "Webflow", "wordpress": "WordPress", "google": "Google", "adobe": "Adobe",
          "microsoft": "Microsoft", "apple": "Apple", "meta": "Meta", "slack": "Slack", "github": "GitHub",
          "whatsapp": "WhatsApp", "twitter": "Twitter", "ethereum": "Ethereum", "bitcoin": "Bitcoin",
          "chatgpt": "ChatGPT", "pagespeed": "PageSpeed", "doubleclick": "DoubleClick", "lighthouse": "Lighthouse",
          "klarna": "Klarna", "afterpay": "Afterpay", "discord": "Discord", "gdpr": "GDPR", "seo": "SEO",
          "api": "API", "saas": "SaaS", "sms": "SMS", "ssl": "SSL", "b2b": "B2B", "hrv": "HRV", "eu": "EU",
          "ui": "UI", "ai": "AI", "web3": "Web3"}
_LOWER_BRANDS = ("scite", "tapouts", "hoo.be", "a0", "your360", "simplyblock")


def _word(t, k, v):
    return re.sub(r"(?<![\w])" + re.escape(k) + r"(?![\w])", v, t, flags=re.I)


def backstop_case(text):
    if not text:
        return text
    out = []
    for line in str(text).split("\n"):
        if line.strip().lower().startswith("http"):
            out.append(line)
            continue
        t = line
        for k, v in _MULTI:
            t = _word(t, k, v)
        t = _word(t, "studio artegra", "Studio Artegra")
        for k, v in _CASE_STUDIES.items():
            t = _word(t, k, v)
        for k, v in _BRAND.items():
            t = _word(t, k, v)
        low = t.lstrip().lower()
        if not any(low.startswith(b) for b in _LOWER_BRANDS):
            t = re.sub(r"^(\s*)([a-z])", lambda m: m.group(1) + m.group(2).upper(), t)
        t = re.sub(r"([.!?]\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), t)
        t = re.sub(r"\bi\b", "I", t)
        out.append(t)
    # force any URL fully lowercase — case-study slugs are lowercase, and casing must never
    # touch them (a capitalized slug like /NewsCatcher is a broken 404 link).
    return re.sub(r"https?://\S+", lambda m: m.group(0).lower(), "\n".join(out))


def load_env():
    if os.environ.get("ANTHROPIC_API_KEY"):
        return
    envf = ROOT / ".env"
    if envf.exists():
        for line in envf.read_text().splitlines():
            if line.strip().startswith("ANTHROPIC_API_KEY") and "=" in line:
                os.environ["ANTHROPIC_API_KEY"] = line.split("=", 1)[1].strip().strip('"').strip("'")


def build_system():
    data = json.loads(BUNDLES.read_text())
    text = SKILL.read_text() + "\n\n## DATA DICTIONARY (field meanings for the bundle)\n" + json.dumps(data["data_dictionary"], indent=2)
    return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}], data["prospects"]


def extract_json(text):
    text = str(text).strip()
    if text.startswith("```"):
        text = re.sub(r"^```(json)?", "", text).rsplit("```", 1)[0].strip()
    for cand in (text, (re.search(r"\{.*\}", text, re.DOTALL) or type("", (), {"group": lambda *_: None})).group(0)):
        if cand:
            try:
                return json.loads(cand, strict=False)
            except Exception:
                continue
    return None


def finalize(obj, dom):
    obj["domain"] = dom
    for f in REQUIRED:
        obj.setdefault(f, "none")
    for f in ("angle_rationale", "case_study_rationale", "secondary_point", "secondary_reasoning",
              "case_study_url", "use_traffic_scale"):
        obj.setdefault(f, "none")
    for f in ("first_message", "second_message", "third_message"):
        obj[f] = backstop_case(obj.get(f))
    return obj


def next_batch_num():
    nums = [int(m.group(1)) for f in DATA.glob("REVIEW_batch_*.csv")
            if (m := re.search(r"REVIEW_batch_(\d+)\.csv", f.name))]
    return (max(nums) + 1) if nums else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=18)
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--batch", action="store_true", help="use Message Batches API (-50%)")
    args = ap.parse_args()

    load_env()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("No ANTHROPIC_API_KEY (checked env and .env).")
    import anthropic
    client = anthropic.Anthropic()
    system, prospects = build_system()

    done = {r["domain"] for r in json.loads(RESULTS.read_text())}
    todo = [p for p in prospects if p["domain"] not in done]
    picks = todo[args.offset:args.offset + args.limit]
    if not picks:
        sys.exit("Nothing to do — all gradeable prospects already written.")
    print(f"Generating {len(picks)} prospects via {MODEL} ({'BATCH' if args.batch else 'realtime'})...")

    def params(dom, bundle, steer=""):
        return dict(model=MODEL, max_tokens=2000, system=system, thinking={"type": "disabled"},
                    messages=[{"role": "user", "content": USER_INSTR + json.dumps(bundle, indent=2, default=str) + steer}])

    def cost_of(u):
        return (u.input_tokens * IN_RATE + (u.cache_read_input_tokens or 0) * 0.1 * IN_RATE
                + (u.cache_creation_input_tokens or 0) * 1.25 * IN_RATE + u.output_tokens * OUT_RATE)

    def call(dom, bundle, steer=""):
        resp = client.messages.create(**params(dom, bundle, steer))
        txt = next((b.text for b in resp.content if b.type == "text"), "")
        return extract_json(txt), cost_of(resp.usage)

    def is_arrogant(o):
        return tone_flag(o.get("first_message"), o.get("second_message"), o.get("third_message")) != "clean"

    results, cost = [], 0.0
    if args.batch:
        from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
        from anthropic.types.messages.batch_create_params import Request
        reqs = [Request(custom_id=re.sub(r"[^\w]+", "_", p["domain"]).strip("_")[:60],
                        params=MessageCreateParamsNonStreaming(**params(p["domain"], p["bundle"]))) for p in picks]
        cid2dom = {re.sub(r"[^\w]+", "_", p["domain"]).strip("_")[:60]: p["domain"] for p in picks}
        mb = client.messages.batches.create(requests=reqs)
        print(f"  batch {mb.id} submitted, polling...")
        while True:
            b = client.messages.batches.retrieve(mb.id)
            if b.processing_status == "ended":
                break
            time.sleep(20)
        for res in client.messages.batches.results(mb.id):
            if res.result.type != "succeeded":
                print(f"  !! {res.custom_id}: {res.result.type}")
                continue
            msg = res.result.message
            txt = next((b.text for b in msg.content if b.type == "text"), "")
            obj = extract_json(txt)
            if obj:
                results.append(finalize(obj, cid2dom[res.custom_id]))
            u = msg.usage
            cost += (u.input_tokens * IN_RATE + (u.cache_read_input_tokens or 0) * 0.1 * IN_RATE
                     + (u.cache_creation_input_tokens or 0) * 1.25 * IN_RATE + u.output_tokens * OUT_RATE) * 0.5
        # tone fix-pass (realtime) on any batch result that tripped the arrogant-phrase check
        bybundle = {p["domain"]: p["bundle"] for p in picks}
        fixed = 0
        for i, r in enumerate(results):
            if is_arrogant(r):
                obj2, c2 = call(r["domain"], bybundle[r["domain"]], STEER)
                cost += c2
                if obj2:
                    results[i] = finalize(obj2, r["domain"])
                    fixed += 1
        if fixed:
            print(f"  tone-corrected {fixed} flagged message(s) via realtime fix-pass")
    else:
        for p in picks:
            dom = p["domain"]
            for attempt in (1, 2):
                try:
                    obj, c = call(dom, p["bundle"])
                    cost += c
                    if obj:
                        obj = finalize(obj, dom)
                        note = ""
                        if is_arrogant(obj):  # self-correct arrogant tone once
                            obj2, c2 = call(dom, p["bundle"], STEER)
                            cost += c2
                            if obj2:
                                obj = finalize(obj2, dom)
                            note = "  [tone-corrected]" + ("" if not is_arrogant(obj) else " STILL-FLAGGED")
                        results.append(obj)
                        print(f"  ok  {dom}{note}")
                        break
                    print(f"  parse-fail (try {attempt}) {dom}")
                except Exception as e:
                    print(f"  ERROR (try {attempt}) {dom}: {str(e)[:80]}")
                    time.sleep(2)

    # merge into master results
    master = json.loads(RESULTS.read_text())
    by = {r["domain"]: r for r in master}
    for r in results:
        by[r["domain"]] = r
    RESULTS.write_text(json.dumps(list(by.values()), indent=2))
    print(f"\nMerged {len(results)} -> message_results.json (now {len(by)})")

    # AUTO POST-BATCH QA SWEEP: flag + fix tone/cta/casing/mech across this batch
    # (belt-and-suspenders on top of the inline tone-correction). It re-assembles if it fixes.
    batch_doms = [r["domain"] for r in results]
    print("Running post-batch QA sweep...")
    subprocess.run([sys.executable, str(ROOT / "scripts" / "qa_check.py"),
                    "--domains", ",".join(batch_doms), "--fix"], check=False)

    # assemble (ensures messages_v2 reflects the final, corrected batch)
    subprocess.run([sys.executable, str(ROOT / "scripts" / "prep_bundles.py"), "assemble",
                    str(ENRICHED), str(RESULTS), "-o", str(MESSAGES)], check=True)

    # review CSV for this batch
    import pandas as pd
    n = next_batch_num()
    df = pd.read_csv(MESSAGES)
    doms = [r["domain"] for r in results]
    sub = df[df["Domain"].isin(doms)].copy()
    order = {d: i for i, d in enumerate(doms)}
    sub["_o"] = sub["Domain"].map(order)
    sub = sub.sort_values("_o").drop(columns="_o")
    review = DATA / f"REVIEW_batch_{n:03d}.csv"
    sub[[c for c in REVIEW_COLS if c in sub.columns]].to_csv(review, index=False)
    print(f"Wrote {review.relative_to(ROOT)} ({len(sub)} rows)")
    print(f"Batch cost: ${cost:.2f}   |   written total: {len(by)}/795")


if __name__ == "__main__":
    main()
