#!/usr/bin/env python3
"""
QA checker/corrector for generated outreach messages.

Sweeps every written message (data/message_results.json) for:
  - tone   : arrogant/presumptuous framing (reuses prep_bundles.tone_flag)
  - cta    : vague / non-signal-matched closing question in message 1
  - casing : lowercase sentence starts, lowercased brand nouns, stray lowercase "i"
  - mech   : em/en dashes, missing {first-name}, uppercase in a case-study URL

Report by default; --fix corrects: casing/mech deterministically (no API), tone/cta by
regenerating that prospect via the API with a targeted steer. Runs on --all (default) or
a --domains subset. Called automatically at the end of a batch by generate_messages_api.py.

Usage:
  python scripts/qa_check.py                      # report, all written
  python scripts/qa_check.py --domains a.com,b.com
  python scripts/qa_check.py --fix                # correct all flagged
  python scripts/qa_check.py --domains ... --fix
"""
import argparse, json, os, re, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from prep_bundles import tone_flag
from message_generator import sanitize, build_prospect
from grader_fields import read_annotated_csv
import generate_messages_api as gm

ROOT = gm.ROOT
RESULTS = gm.RESULTS

VAGUE_CTA = ["how are you thinking", "what do you most", "curious how", "walk away",
             "take away", "the site's role", "how you're approaching", "how you think about the site",
             "what you most want"]
LOWER_BRAND = re.compile(r"\b(webflow|wordpress|gdpr|chatgpt|seo|pagespeed|doubleclick|"
                         r"lighthouse|newscatcher|yourculture|linkedin)\b")
LOWER_OK = ("scite", "tapouts", "simplyblock", "hoo.be", "a0", "your360", "http")

_bundles = None
_enriched = None


def get_bundle(dom):
    """Bundle for a domain — from the dumped file, else built from the enriched CSV."""
    global _bundles, _enriched
    if _bundles is None:
        _bundles = {p["domain"]: p["bundle"] for p in json.loads(gm.BUNDLES.read_text())["prospects"]}
    if dom in _bundles:
        return _bundles[dom]
    if _enriched is None:
        _enriched = read_annotated_csv(str(gm.ENRICHED))
    row = _enriched[_enriched["Domain"].astype(str) == dom]
    return build_prospect(row.iloc[0]) if len(row) else None


_INTERROG = re.compile(r"^(is|are|do|does|did|would|could|have|has|will|can|should|any)\b", re.I)


def cta_flag(first):
    """None = fine; 'vague' = genuinely open-ended (regenerate); 'no-qmark' = a real
    direct question written with a '.' instead of '?' (deterministically fixable)."""
    segs = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", str(first)) if s.strip()]
    last = segs[-1] if segs else ""
    if any(v in last.lower() for v in VAGUE_CTA):
        return "vague"
    if "?" in last:
        return None
    if _INTERROG.match(last.strip()):
        return "no-qmark"
    return "vague"


def casing_issues(text):
    # strip URLs first — case-study slugs are legitimately lowercase (…/newscatcher)
    t = re.sub(r"https?://\S+", "", str(text))
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


def check(r):
    msgs = [r.get("first_message"), r.get("second_message"), r.get("third_message")]
    flags = {}
    if str(r.get("priority", "")).lower() == "skip":
        return flags
    if tone_flag(*msgs) != "clean":
        flags["tone"] = tone_flag(*msgs)
    cf = cta_flag(r.get("first_message"))
    if cf:
        flags["cta"] = cf
    cas, mech = set(), set()
    for m in msgs:
        cas |= casing_issues(m)
        mech |= mech_issues(m)
    if cas:
        flags["casing"] = ",".join(sorted(cas))
    if mech:
        flags["mech"] = ",".join(sorted(mech))
    return flags


def wants_api(fl):
    """Only PROSE issues (tone, genuinely-vague CTA) need regeneration. Structural/mechanical
    issues (missing msg2 opener, capitalized URL, em-dash, a CTA just missing its '?') are fixed
    deterministically below."""
    return "tone" in fl or fl.get("cta") == "vague"


STUDIO_OPENER = "Hey {first-name}, quick context, we're a design and Webflow studio.\n\n"


def lower_urls(t):
    return re.sub(r"https?://\S+", lambda m: m.group(0).lower(), str(t))


def det_fix(r):
    """Deterministic structural + mechanical repair (no API): restore the msg2 opener when
    dropped, guarantee {first-name} in every message, force URLs lowercase, strip dashes."""
    m2 = str(r.get("second_message") or "")
    if m2.strip() and "{first-name}" not in m2:
        r["second_message"] = STUDIO_OPENER + m2.lstrip()
    for f in ("first_message", "third_message"):
        m = str(r.get(f) or "")
        if m.strip() and "{first-name}" not in m:
            r[f] = "Hey {first-name}, " + m.lstrip()
    if r.get("case_study_url"):
        r["case_study_url"] = lower_urls(r["case_study_url"])
    # CTA punctuation: a trailing direct question written with '.' -> '?'
    fm = str(r.get("first_message") or "")
    r["first_message"] = re.sub(
        r"((?:Is|Are|Do|Does|Did|Would|Could|Have|Has|Will|Can|Should|Any)\b[^.?!\n]*)\.(\s*)$",
        r"\1?\2", fm, flags=re.I)
    for f in ("first_message", "second_message", "third_message"):
        if r.get(f) is not None:
            r[f] = sanitize(gm.backstop_case(lower_urls(r.get(f))))


def steer_for(flags):
    s = ""
    if "tone" in flags:
        s += gm.STEER
    if "cta" in flags:
        s += ("\n\nIMPORTANT CTA NOTE: the previous draft's closing question was vague or "
              "open-ended. Rewrite the final CTA as a SHORT, DIRECT question about the SAME thing "
              "you pitched (performance -> 'is site speed something you're looking at?'; design -> "
              "'is a refresh on your radar?'; content -> 'is building out the site something you're "
              "thinking about?'). No vague 'how are you thinking about the site' style openers.")
    if "mech" in flags:
        s += ("\n\nIMPORTANT STRUCTURE NOTE: EVERY one of the three messages must begin with "
              "'Hey {first-name},' using the literal token {first-name}; use no em/en dashes; and "
              "put any case-study URL on its OWN line.")
    return s


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

    report, need_api = [], []
    for dom in scope:
        r = by.get(dom)
        if not r:
            continue
        flags = check(r)
        if flags:
            report.append({"domain": dom, **flags})
            if wants_api(flags):
                need_api.append(dom)

    import pandas as pd
    pd.DataFrame(report).to_csv(report_path, index=False)
    print(f"Scanned {len(scope)} | flagged {len(report)} -> {report_path}")
    if report:
        from collections import Counter
        c = Counter(k for row in report for k in row if k != "domain")
        print("  by type:", dict(c))

    if not args.fix or not report:
        if report and not args.fix:
            print("  (run with --fix to correct these)")
        return

    gm.load_env()
    import anthropic
    client = anthropic.Anthropic()
    system, _ = gm.build_system()
    fixed_det = fixed_api = 0

    for row in report:
        dom = row["domain"]
        if wants_api(row):  # tone/cta -> regenerate via API
            b = get_bundle(dom)
            if b is not None:
                steer = steer_for(row)
                resp = client.messages.create(
                    model=gm.MODEL, max_tokens=2000, system=system, thinking={"type": "disabled"},
                    messages=[{"role": "user", "content": gm.USER_INSTR + json.dumps(b, indent=2, default=str) + steer}])
                txt = next((x.text for x in resp.content if x.type == "text"), "")
                obj = gm.extract_json(txt)
                if obj:
                    by[dom] = gm.finalize(obj, dom)
                    fixed_api += 1
            else:
                print(f"  !! no bundle for {dom}, deterministic-only")
        det_fix(by[dom])  # ALWAYS apply structural/mechanical repair (also after a regen)
        fixed_det += 1

    RESULTS.write_text(json.dumps(list(by.values()), indent=2))
    print(f"Fixed: {fixed_api} via API (tone/cta), {fixed_det} deterministically (casing/mech)")
    subprocess.run([sys.executable, str(ROOT / "scripts" / "prep_bundles.py"), "assemble",
                    str(gm.ENRICHED), str(RESULTS), "-o", str(gm.MESSAGES)], check=True)
    # verify
    post = {r["domain"]: check(r) for r in json.loads(RESULTS.read_text()) if r["domain"] in scope}
    still = {d: f for d, f in post.items() if f}
    print(f"Post-fix residual flags: {len(still)}" + (f" -> {list(still)[:6]}" if still else " (all clean)"))


if __name__ == "__main__":
    main()
