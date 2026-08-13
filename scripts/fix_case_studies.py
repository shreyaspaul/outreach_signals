#!/usr/bin/env python3
"""
Re-select the case study for every prospect and rewrite message 2 to match it.

Why: message 1 pitches a signal (design / performance / content), and message 2 is supposed
to PROVE it. Across the batch the proof frequently didn't back the pitch (42 design pitches
cited Studio Artegra, whose only metric is +25% *performance*), and the copy had been reworded
to hide the gap. This pass fixes the pairing and rewrites message 2 honestly.

Message 1 and message 3 are NOT touched.

The model may only choose from studies whose real headline result can back that row's pitch
(scripts/case_studies.py :: proves). The URL is stamped from the registry, never from the model.

Usage:
  python scripts/fix_case_studies.py --limit 5                # smoke test, realtime
  python scripts/fix_case_studies.py --all --batch            # full run via Batch API (-50%)
  python scripts/fix_case_studies.py --apply                  # merge results -> results JSON + CSVs
"""
import argparse, json, os, re, subprocess, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from case_studies import CASE_STUDIES, url_for, eligible_for, registry_for_prompt
from generate_messages_api import backstop_case, load_env, extract_json

ROOT = Path(__file__).resolve().parent.parent
BATCH = os.environ.get("LEADS_BATCH", "batch_01")
DATA = ROOT / "data" / BATCH
RESULTS = DATA / "message_results.json"
ENRICHED = next(iter(sorted(DATA.glob("enriched_*.csv"))), DATA / "enriched_ALL_999.csv")
FIXES = DATA / "case_study_fixes.json"
MODEL = "claude-sonnet-5"
IN_RATE, OUT_RATE = 3e-6, 15e-6

SYSTEM = """You are rewriting the SECOND message of a 3-message cold LinkedIn outreach sequence
for a design and Webflow studio (Prismport).

Message 1 (already written, shown to you) makes an inference about the prospect's business and
raises ONE opportunity on their site. Message 2 is the follow-up sent if they don't reply: it
proves we can do that thing, using ONE case study.

THE RULE YOU EXIST TO ENFORCE: the case study must PROVE THE THING MESSAGE 1 PITCHED.
If message 1 talks about design and distinctiveness, the case study's headline result must be a
design outcome. Do not cite a performance win as proof of design work. Do not reword a case
study's story to make it sound like it was about something it wasn't. That is fabrication.

You are given ONLY the case studies that are allowed to back this prospect's pitch. Pick the ONE
that fits best, judging on:
  1. problem match  — does its story mirror the specific problem message 1 raised? (this dominates)
  2. industry/audience adjacency — enterprise vs consumer, technical vs mainstream, B2B vs eCommerce.
Do not default to the same study every time. If two fit equally, prefer the closer industry.

Then write message 2. Anatomy, in this exact shape:
  line 1: "Hey {first-name}, quick context, we're a design and Webflow studio."
  then:   one line naming the case study, its category, and that their problem was close to this
          prospect's — described ACCURATELY, per "what we actually did".
  then:   the URL on its own line.
  then:   one line quoting the EXACT result, and tying it to what THIS prospect would get.
  then:   a soft, forward close offering to show how we'd approach theirs.

HARD RULES
- Quote the result exactly as given. Never invent or inflate a number.
- {first-name} is the only name token. Never write a real first name.
- Proper capitalization and sentence case. No em dashes or en dashes.
- Warm, plain, lowercase-DM feel, but correctly capitalized. No buzzwords.
- Never judge or insult their site. Opportunity framing only. Never imply their visitors are
  judging them or that they're being evaluated.
- If message 1 carried a secondary point (a consent/GDPR or AI-crawler note), you may keep a
  short version of it as a final separate line, but do not add one that wasn't there.

Output ONLY a JSON object:
{"case_study_name": "<exact name from the allowed list>",
 "case_study_rationale": "<one line: why this study proves this pitch, for this company>",
 "second_message": "<the message>"}"""


def build_user(row, ctx):
    sig = row.get("signal_category", "design")
    registry = ("\n".join(f"- {n} ({CASE_STUDIES[n]['category']})\n    exact result (quote this, do not embellish): {CASE_STUDIES[n]['metric']}\n    what we actually did: {CASE_STUDIES[n]['story']}\n    use when: {CASE_STUDIES[n]['use_when']}\n    url: {url_for(n)}"
                          for n in allowed_for(row)))
    return (
        f"PROSPECT\n"
        f"  company: {ctx.get('name')}\n"
        f"  domain: {row['domain']}\n"
        f"  what they do / industry: {ctx.get('industry')}\n"
        f"  tech stack: {ctx.get('tech')}\n"
        f"  monthly visits: {ctx.get('visits')}\n\n"
        f"THE PITCH IN MESSAGE 1\n"
        f"  signal category: {sig}\n"
        f"  the specific thing raised: {row.get('chosen_signal')}\n"
        f"  why it matters: {row.get('why_it_matters')}\n\n"
        f"MESSAGE 1 (already sent, do not rewrite):\n{row.get('first_message')}\n\n"
        f"CURRENT MESSAGE 2 (being replaced because its case study does not prove the pitch):\n"
        f"{row.get('second_message')}\n\n"
        f"ALLOWED CASE STUDIES (only these can prove a '{sig}' pitch):\n{registry}\n\n"
        f"Pick the best one and write message 2." + (STEER if os.environ.get("STEER_TONE") else "")
    )


# appended when a draft tripped the tone check (same banned phrases the pipeline already enforces)
STEER = (
    "\n\nIMPORTANT: your previous draft used a BANNED arrogant framing ('sizing you up', "
    "'scrutinizing', 'skeptics', 'evaluating you', 'judging'). Never cast their visitors as "
    "skeptics or evaluators sitting in judgment of them. Describe the reader as someone forming "
    "an impression or getting up to speed, warmly and with credit. Rewrite with that removed."
)


def load_context():
    """Company context from the enriched CSV, keyed by domain."""
    import csv
    ctx = {}
    with ENRICHED.open() as f:
        for r in csv.DictReader(f):
            dom = (r.get("Domain") or r.get("domain") or "").strip()
            if not dom:
                continue
            ctx[dom] = {
                "name": r.get("Name") or r.get("Company Name"),
                "industry": (r.get("Industries") or r.get("content_analysis") or "")[:300],
                "tech": r.get("tech_stack"),
                "visits": r.get("apify_monthly_visits") or r.get("monthly_visits"),
            }
    return ctx


OPENER = "Hey {first-name}, quick context, we're a design and Webflow studio."


def canon(name, allowed):
    """Model often echoes 'YourCulture (Media & Entertainment)' or 'TwoDots'. Map to the real key."""
    n = re.sub(r"\s*\(.*$", "", (name or "").strip()).strip()
    if n in allowed:
        return n
    squash = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
    for a in allowed:
        if squash(a) == squash(n):
            return a
    return None


def allowed_for(row):
    sig = row.get("signal_category", "design")
    if sig not in ("design", "performance", "content"):   # 'other' -> any site-quality study
        return sorted({n for s in ("design", "performance", "content") for n in eligible_for(s)})
    return eligible_for(sig)


def enforce(obj, row):
    """Deterministic guards. The model picks; the code stamps the facts."""
    allowed = allowed_for(row)
    name = canon(obj.get("case_study_name"), allowed)
    if not name:
        return None, f"picked disallowed study {obj.get('case_study_name')!r} for {row.get('signal_category')}"
    msg = backstop_case(obj.get("second_message") or "")
    msg = msg.replace("—", ", ").replace("–", ", ")
    # the URL is OURS, never the model's: strip any it wrote, stamp the verified one
    real = url_for(name)
    msg = re.sub(r"https?://\S+", real, msg)
    if real not in msg:
        # model forgot the link. It's our URL, not theirs to author: place it on its own line
        # after the line that introduces the study (the anatomy), rather than dropping the row.
        lines = [l for l in msg.split("\n")]
        at = next((i for i, l in enumerate(lines) if name.split()[0] in l), 0)
        lines.insert(at + 1, real)
        msg = "\n".join(lines)
    if not msg.lstrip().startswith("Hey {first-name}"):
        msg = OPENER + "\n\n" + msg.lstrip()
    if "{first-name}" not in msg:
        return None, "lost {first-name}"
    obj["case_study_name"] = name
    obj["case_study_url"] = real
    obj["second_message"] = msg
    return obj, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--batch", action="store_true", help="Message Batches API (-50%)")
    ap.add_argument("--apply", action="store_true", help="merge fixes into results JSON + rebuild CSVs")
    ap.add_argument("--collect", metavar="BATCH_ID", help="re-attach to an ENDED batch (no long poll)")
    ap.add_argument("--domains", help="comma-separated domains to (re)run")
    ap.add_argument("--merge", action="store_true", help="merge into existing fixes file instead of overwriting")
    args = ap.parse_args()

    results = json.loads(RESULTS.read_text())
    if args.apply:
        return apply_fixes(results)
    if args.collect:
        load_env()
        import anthropic
        return collect(anthropic.Anthropic(), args.collect, results)

    load_env()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("No ANTHROPIC_API_KEY (checked env and .env).")
    import anthropic
    client = anthropic.Anthropic()
    ctx = load_context()

    # rows with a real pitch. 'other' rows that still cite a study are site-quality pitches with a
    # miscategorised signal, so they get re-picked too; rows with no message at all are left alone.
    todo = [r for r in results
            if r.get("signal_category") in ("design", "performance", "content")
            or (r.get("second_message") or "").strip()]
    if args.domains:
        want = set(args.domains.split(","))
        todo = [r for r in todo if r["domain"] in want]
    elif not args.all:
        todo = todo[: args.limit]
    print(f"Re-selecting case studies for {len(todo)} prospects via {MODEL} "
          f"({'BATCH' if args.batch else 'realtime'})...")

    def params(row):
        return dict(model=MODEL, max_tokens=1200, thinking={"type": "disabled"},
                    system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
                    messages=[{"role": "user", "content": build_user(row, ctx.get(row["domain"], {}))}])

    def cost_of(u, batched=False):
        # The Batch API bills at 50%. Omitting this made every batched run report ~2x its real
        # cost, which is worse than reporting nothing: it silently overstates spend.
        mult = 0.5 if batched else 1.0
        return mult * (u.input_tokens * IN_RATE + (u.cache_read_input_tokens or 0) * 0.1 * IN_RATE
                       + (u.cache_creation_input_tokens or 0) * 1.25 * IN_RATE + u.output_tokens * OUT_RATE)

    fixes, cost, bad = {}, 0.0, []
    if args.batch:
        from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
        from anthropic.types.messages.batch_create_params import Request
        cid = lambda d: re.sub(r"[^\w]+", "_", d).strip("_")[:60]
        reqs = [Request(custom_id=cid(r["domain"]), params=MessageCreateParamsNonStreaming(**params(r)))
                for r in todo]
        c2d = {cid(r["domain"]): r["domain"] for r in todo}
        by_dom = {r["domain"]: r for r in todo}
        mb = client.messages.batches.create(requests=reqs)
        print(f"  batch {mb.id} submitted. Poll with: python scripts/fix_case_studies.py --collect {mb.id}")
        (DATA / "case_study_batch_id.txt").write_text(mb.id)
        while True:
            b = client.messages.batches.retrieve(mb.id)
            if b.processing_status == "ended":
                break
            time.sleep(20)
        for res in client.messages.batches.results(mb.id):
            dom = c2d.get(res.custom_id)
            if res.result.type != "succeeded":
                bad.append((dom, "api failed")); continue
            txt = next((b.text for b in res.result.message.content if b.type == "text"), "")
            obj = extract_json(txt)
            cost += cost_of(res.result.message.usage, batched=True)
            obj, err = enforce(obj, by_dom[dom]) if obj else (None, "no json")
            (fixes.setdefault(dom, obj) if obj else bad.append((dom, err)))
    else:
        for i, row in enumerate(todo, 1):
            resp = client.messages.create(**params(row))
            txt = next((b.text for b in resp.content if b.type == "text"), "")
            cost += cost_of(resp.usage)
            obj = extract_json(txt)
            obj, err = enforce(obj, row) if obj else (None, "no json")
            if obj:
                fixes[row["domain"]] = obj
                print(f"  [{i}/{len(todo)}] {row['domain']}: {row['case_study_name']} -> {obj['case_study_name']}")
            else:
                bad.append((row["domain"], err))
                print(f"  [{i}/{len(todo)}] {row['domain']}: FAILED ({err})")

    if args.merge and FIXES.exists():
        prev = json.loads(FIXES.read_text()); prev.update(fixes); fixes = prev
    FIXES.write_text(json.dumps(fixes, indent=1))
    print(f"\nWrote {len(fixes)} fixes -> {FIXES}   (cost ~${cost:.2f})")
    if bad:
        print(f"{len(bad)} failed:")
        for d, e in bad[:20]:
            print(f"  {d}: {e}")
    print("\nReview, then merge with:  python scripts/fix_case_studies.py --apply")


def collect(client, batch_id, results):
    """Re-attach to a batch that already ENDED (the long poll can get killed; the job survives)."""
    b = client.messages.batches.retrieve(batch_id)
    if b.processing_status != "ended":
        sys.exit(f"batch {batch_id} is {b.processing_status}, not ended yet. Try again shortly.")
    by_dom = {r["domain"]: r for r in results}
    cid = lambda d: re.sub(r"[^\w]+", "_", d).strip("_")[:60]
    c2d = {cid(d): d for d in by_dom}
    fixes, bad = {}, []
    for res in client.messages.batches.results(batch_id):
        dom = c2d.get(res.custom_id)
        if res.result.type != "succeeded":
            bad.append((dom, "api failed")); continue
        txt = next((x.text for x in res.result.message.content if x.type == "text"), "")
        obj = extract_json(txt)
        obj, err = enforce(obj, by_dom[dom]) if obj else (None, "no json")
        (fixes.setdefault(dom, obj) if obj else bad.append((dom, err)))
    FIXES.write_text(json.dumps(fixes, indent=1))
    print(f"Collected {len(fixes)} fixes -> {FIXES}")
    if bad:
        print(f"{len(bad)} failed: {bad[:10]}")
    print("Merge with:  python scripts/fix_case_studies.py --apply")


def apply_fixes(results):
    fixes = json.loads(FIXES.read_text())
    changed = 0
    for r in results:
        f = fixes.get(r["domain"])
        if not f:
            continue
        if r.get("case_study_name") != f["case_study_name"] or r.get("second_message") != f["second_message"]:
            changed += 1
        r["case_study_name"] = f["case_study_name"]
        r["case_study_url"] = f["case_study_url"]
        r["case_study_rationale"] = f.get("case_study_rationale", "")
        r["second_message"] = f["second_message"]
    bak = RESULTS.with_suffix(".json.bak")
    if not bak.exists():
        bak.write_text(RESULTS.read_text())
        print(f"backup -> {bak}")
    RESULTS.write_text(json.dumps(results, indent=1))
    print(f"Applied {len(fixes)} fixes ({changed} rows changed) -> {RESULTS}")
    subprocess.run([sys.executable, "scripts/prep_bundles.py", "assemble", str(ENRICHED),
                    str(RESULTS), "-o", str(DATA / "messages_v2.csv")], cwd=ROOT, check=True)
    subprocess.run([sys.executable, "scripts/build_outreach_list.py"], cwd=ROOT, check=True)
    print("Rebuilt messages_v2.csv + outreach_ready.csv")


if __name__ == "__main__":
    main()
