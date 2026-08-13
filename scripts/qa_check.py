#!/usr/bin/env python3
"""
QA checker/corrector for generated outreach messages — the batch safety net.

Sweeps every written message (data/<batch>/message_results.json) against the FULL rule set and
fixes what it can:
  MECHANICAL (fixed deterministically, no API):
    - casing (lowercase sentence starts, lowercased brands, stray lowercase "i")
    - em/en dashes, missing "Hey {first-name}," opener, uppercase in a case-study URL
  CONTENT (regenerated on the model, retry-until-clean):
    - tone (arrogant framing), negative "not cold" tail, niche opener, placeholder/0x stats,
      "even a small lift adds up" scale-math, piled proof (name + metric), forced product pun,
      negative-gap framing ("doesn't quite carry"), run-on/over-length, banned mechanism CTAs,
      a performance claim that isn't gated / has no number, a case-study whose URL is missing from msg2.

Report by default; --fix corrects. Runs on --all (default) or a --domains subset. Called
automatically at the end of a batch by generate_messages_api.py.

Usage:
  python scripts/qa_check.py                      # report, all written
  python scripts/qa_check.py --domains a.com,b.com
  python scripts/qa_check.py --fix                # correct all flagged
"""
import argparse, json, re, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from prep_bundles import tone_flag
from message_generator import sanitize, build_prospect
from grader_fields import read_annotated_csv
import generate_messages_api as gm

ROOT = gm.ROOT
RESULTS = gm.RESULTS

# ---- banned CONTENT patterns (regeneration) ----
NEG   = re.compile(r",?\s*not\s+(people finding you cold|cold search|from a cold|paid ads?|a sales team|"
                   r"cold sign|cold traffic|people finding you|them cold|cold\b)", re.I)
NICHE = re.compile(r"looking at[^.\n]*(whatsapp|multi-?agent|orchestration|eye-?tracking|ad[- ]attention|"
                   r"link-?in-?bio|conversational commerce|route optimi)", re.I)
PLACE = re.compile(r"\b0\s*x\b|\b0\s*%|\b0\+|placeholder", re.I)
SCALE = re.compile(r"even a (small|modest|tiny|little)|adds up to|small lift", re.I)
PILE  = re.compile(r"\bby over \d|\b\dx\b", re.I)
PUN   = re.compile(r"as instantly as|as sharply as|as fast as (your|the) (product|agent|tool)|"
                   r"as hard as the (tool|product)|keeps pace with|responds as .* as", re.I)
NEGGAP= re.compile(r"doesn'?t (quite |really )?(carry|feel|have|match)|isn'?t (quite |as )|"
                   r"not (quite |as )(polished|premium|sharp)", re.I)
BAD_CTA = re.compile(r"is (site )?speed something you'?re looking at|is performance on your radar|"
                     r"do you feel like the site does you justice|how are you thinking about the site|"
                     r"curious how you'?re approaching|what do you most want|"
                     # USER RULE 2026-08-08: the "worth a ..." close is banned outright (disliked).
                     # Use "Have you thought about ...?" / "Ever thought about ...?" /
                     # "Is ... on your radar?" instead. m1-only, so msg2's "worth a renew" is safe.
                     # only the QUESTION form is the CTA — "decides you're worth a look." is fine prose.
                     r"worth a (refresh|look|rebuild|redesign|revisit|change)\b[^?\n]{0,20}\?|"
                     r"worth thinking about a[^?\n]{0,20}\?", re.I)
SPEED = re.compile(r"\bspeed\b|\blag\b|\bslow\b|\bload(s|ed|ing)?\b|every tap|seconds to load|on desktop", re.I)
FUNDING = re.compile(r"\brais(ed|ing)\b[^.\n]{0,15}[\$£€]\d|[\$£€]\s?\d[\d.,]*\s?(m|million|bn|billion)\b"
                     r"[^.\n]{0,18}(behind you|in funding|raised|backing)", re.I)

LOWER_BRAND = re.compile(r"\b(webflow|wordpress|gdpr|chatgpt|seo|pagespeed|doubleclick|"
                         r"lighthouse|newscatcher|yourculture|linkedin)\b")
LOWER_OK = ("scite", "tapouts", "simplyblock", "hoo.be", "a0", "your360", "http")

_bundles = None
_enriched = None


def get_bundle(dom):
    """Bundle for a domain — from the dumped file (carries the flags), else built from the CSV."""
    global _bundles, _enriched
    if _bundles is None:
        _bundles = {p["domain"]: p["bundle"] for p in json.loads(gm.BUNDLES.read_text())["prospects"]}
    if dom in _bundles:
        return _bundles[dom]
    if _enriched is None:
        _enriched = read_annotated_csv(str(gm.ENRICHED))
    row = _enriched[_enriched["Domain"].astype(str) == dom]
    return build_prospect(row.iloc[0]) if len(row) else None


def casing_issues(text):
    t = re.sub(r"https?://\S+", "", str(text))  # slugs are legitimately lowercase
    probs = set()
    for line in t.split("\n"):
        for seg in re.split(r"(?<=[.!?])\s+", line):
            seg = seg.strip()
            if seg and seg[0].islower() and not seg.lower().startswith(LOWER_OK):
                probs.add("lc-start")
    if LOWER_BRAND.search(t):
        probs.add("lc-brand")
    if re.search(r"(?<![A-Za-z])i(?![A-Za-z'])", t):
        probs.add("lc-i")
    return probs


def mech_issues(text):
    p = set()
    if any(d in str(text) for d in ("—", "–", "―")):
        p.add("em-dash")
    if "{first-name}" not in str(text):
        p.add("no-firstname")
    for u in re.findall(r"https?://\S+", str(text)):
        if any(c.isupper() for c in u):
            p.add("url-caps")
    return p


def check(r, bundle=None):
    """Return a set of flags. 'mech:*' / 'case:*' are deterministic; everything else needs a regen."""
    if str(r.get("priority", "")).lower() == "skip":
        return set()
    m1 = str(r.get("first_message") or "")
    m2 = str(r.get("second_message") or "")
    m3 = str(r.get("third_message") or "")
    allm = " ".join((m1, m2, m3))
    f = set()
    # CONTENT (regen)
    if tone_flag(m1, m2, m3) != "clean": f.add("tone")
    if NEG.search(allm): f.add("neg-tail")
    if PLACE.search(allm): f.add("placeholder")
    if SCALE.search(allm): f.add("scale")
    if PILE.search(m1): f.add("pile")
    if PUN.search(allm): f.add("pun")
    if NEGGAP.search(allm): f.add("neg-gap")
    if FUNDING.search(allm): f.add("funding")
    if NICHE.search(m1.split("\n")[0]): f.add("niche")
    if BAD_CTA.search(m1): f.add("bad-cta")
    if len(m1.split()) > 82: f.add("long")
    if bundle is not None and SPEED.search(m1):
        if not bundle.get("performance_really_poor"): f.add("perf-ungated")
        elif not re.search(r"\d", m1): f.add("perf-nonum")
    csu = str(r.get("case_study_url") or "").strip().lower()
    if csu and csu != "none" and "prismport.co/case-studies/" not in m2:
        f.add("nourl")
    # MECHANICAL (deterministic)
    for m in (m1, m2, m3):
        f |= {"mech:" + x for x in mech_issues(m)}
        f |= {"case:" + x for x in casing_issues(m)}
    return f


def needs_regen(flags):
    return any(not (x.startswith("mech:") or x.startswith("case:")) for x in flags)


def lower_urls(t):
    return re.sub(r"https?://\S+", lambda m: m.group(0).lower(), str(t))


def det_fix(r):
    """Deterministic mechanical repair (no API): guarantee 'Hey {first-name},' in every message,
    force URLs lowercase, strip dashes, fix casing via the backstop."""
    for f in ("first_message", "second_message", "third_message"):
        m = str(r.get(f) or "")
        if m.strip() and "{first-name}" not in m:
            r[f] = "Hey {first-name}, " + m.lstrip()
    if r.get("case_study_url"):
        r["case_study_url"] = lower_urls(r["case_study_url"])
    for f in ("first_message", "second_message", "third_message"):
        if r.get(f) is not None:
            r[f] = sanitize(gm.backstop_case(lower_urls(r.get(f))))


# comprehensive steer appended when regenerating a flagged message
STEER = ("\n\nGUARDRAILS (a previous draft broke one). Rewrite all three messages clean: short "
         "(~45-70 words, one idea per sentence, no run-ons); broad opener category (never a niche like "
         "'WhatsApp'/'multi-agent'); the guess ends positive (never '...not cold search'); frame the gap "
         "as 'there's room for the site to...' never 'it doesn't quite carry'; NO forced product pun "
         "('as fast as your agents'); NO 'even a small lift adds up' scale-math; name ONE precinct only "
         "(never a customer name PLUS their metric); NO '0x/0%/placeholder' stats; short CTA that names the "
         "action (never a mechanism question like 'is site speed something you're looking at'). NEVER "
         "cite a funding amount ('you've raised $5M' is banned). If "
         "performance leads it must cite a concrete number AND only when the site is genuinely slow. "
         "Message 2 must put the case-study URL on its OWN line. Always the literal {first-name} token.")


def regen_clean(dom, client, system, tries=4):
    """Regenerate a prospect on the model until the CONTENT checks pass (mechanical fixed after)."""
    b = get_bundle(dom)
    if b is None:
        return None
    best = None
    for _ in range(tries):
        resp = client.messages.create(
            model=gm.MODEL, max_tokens=12000, system=system,
            thinking={"type": "adaptive"}, output_config={"effort": "high"},
            messages=[{"role": "user", "content": gm.USER_INSTR + json.dumps(b, indent=2, default=str) + STEER}])
        obj = gm.extract_json(next((x.text for x in resp.content if x.type == "text"), ""))
        if not obj:
            continue
        best = gm.finalize(obj, dom)
        if not needs_regen(check(best, b)):
            return best
    return best  # best effort; det_fix + report will still run


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--domains", help="comma-separated subset; default = all written")
    ap.add_argument("--fix", action="store_true")
    ap.add_argument("-o", "--report", default=None, help="report path (default: <batch>/qa_report.csv)")
    args = ap.parse_args()
    report_path = Path(args.report) if args.report else gm.DATA / "qa_report.csv"

    master = json.loads(RESULTS.read_text())
    by = {r["domain"]: r for r in master}
    scope = [d.strip() for d in args.domains.split(",")] if args.domains else list(by.keys())

    report = []
    for dom in scope:
        r = by.get(dom)
        if not r:
            continue
        flags = check(r, get_bundle(dom))
        if flags:
            report.append({"domain": dom, "flags": ",".join(sorted(flags)), "regen": needs_regen(flags)})

    import pandas as pd
    pd.DataFrame(report).to_csv(report_path, index=False)
    from collections import Counter
    tally = Counter(fl for row in report for fl in row["flags"].split(","))
    print(f"Scanned {len(scope)} | flagged {len(report)} -> {report_path}")
    if report:
        print("  by type:", dict(tally.most_common()))

    if not args.fix or not report:
        if report and not args.fix:
            print("  (run with --fix to correct these)")
        return

    gm.load_env()
    import anthropic
    client = anthropic.Anthropic()
    system, _ = gm.build_system()
    fixed_api = fixed_det = 0

    for row in report:
        dom = row["domain"]
        if row["regen"]:
            new = regen_clean(dom, client, system)
            if new is not None:
                by[dom] = new
                fixed_api += 1
        det_fix(by[dom])  # always apply mechanical repair (also after a regen)
        fixed_det += 1

    RESULTS.write_text(json.dumps(list(by.values()), indent=2))
    print(f"Fixed: {fixed_api} regenerated on {gm.MODEL}, {fixed_det} mechanically cleaned")
    subprocess.run([sys.executable, str(ROOT / "scripts" / "prep_bundles.py"), "assemble",
                    str(gm.ENRICHED), str(RESULTS), "-o", str(gm.MESSAGES)], check=True)
    post = {r["domain"]: check(r, get_bundle(r["domain"]))
            for r in json.loads(RESULTS.read_text()) if r["domain"] in scope}
    still = {d: sorted(f) for d, f in post.items() if f}
    print(f"Post-fix residual flags: {len(still)}" + (f" -> {list(still.items())[:5]}" if still else " (all clean)"))


if __name__ == "__main__":
    main()
