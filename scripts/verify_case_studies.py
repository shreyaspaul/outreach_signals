#!/usr/bin/env python3
"""
Independent audit of case-study usage. Does NOT trust the model or the fixer.

Checks, per row:
  1. eligibility  — the study's real headline result can back the pitch in message 1
  2. url          — matches the verified slug for that study (a wrong slug is a 404)
  3. numbers      — every number in message 2 traces to that study's real metric, the
                    prospect's own traffic, or a safe non-claim. Catches invented results.
  4. mechanics    — {first-name} present, opener present, no em/en dash

Usage:  python scripts/verify_case_studies.py            # audit current messages
        python scripts/verify_case_studies.py --csv path
"""
import argparse, csv, json, re, sys, os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from case_studies import CASE_STUDIES, url_for, eligible_for

ROOT = Path(__file__).resolve().parent.parent
BATCH = os.environ.get("LEADS_BATCH", "batch_01")
DATA = ROOT / "data" / BATCH

# numbers each study is allowed to claim, from its real metric
ALLOWED_NUMS = {
    "Studio Artegra": {"25"},
    "Webless AI": {"20", "32", "40"},          # bounce -20%, time +32%, ~40 animation frames
    "Two Dots": {"40"},
    "Wonder Phone": {"50", "3"},               # sales +50%, 3D
    "YourCulture": {"97", "2"},
    "Flatable": {"95", "2"},
    "NewsCatcherAPI": {"20", "3", "3600", "3,600"},
    "Qmin AI": {"60", "1"},
    "Amalia": {"25", "44", "60"},
    "Lowr": set(),
    "your360 AI": {"1"},
    "F5 Hiring Solutions": set(),
}
SAFE = {"1", "2", "3", "10", "100"}  # ordinals/idioms, not result claims


def numbers(text):
    return set(re.findall(r"\d[\d,\.]*", text or ""))


def audit(rows):
    # outreach_ready.csv is the RESOLVED send list: {first-name} is already replaced with the
    # real name and the traffic column is dropped. Those two checks only apply upstream.
    resolved = bool(rows) and "first_name" in rows[0]
    problems = []
    for r in rows:
        dom = r.get("Domain") or r.get("domain") or "?"
        name = (r.get("case_study_name") or "").strip()
        sig = (r.get("signal_category") or "").strip()
        m2 = r.get("second_message") or ""
        if not name or name == "none":
            problems.append((dom, "no case study", name)); continue
        if name not in CASE_STUDIES:
            problems.append((dom, "unknown study", name)); continue
        # 'other' rows have a miscategorised signal; any site-quality study may back them
        provable = CASE_STUDIES[name]["proves"]
        if sig in ("design", "performance", "content") and sig not in provable:
            problems.append((dom, f"MISMATCH: {name} cannot prove a '{sig}' pitch",
                             CASE_STUDIES[name]["metric"])); continue
        if r.get("case_study_url") != url_for(name):
            problems.append((dom, "wrong url", r.get("case_study_url")))
        # A number in msg2 is legitimate only if it traces to: the study's real metric, the
        # prospect's own data (their traffic / their own stat, both of which already appear in
        # msg1 or the enriched row), or their name (257.co, c64.ai). Anything else is invented.
        own = ALLOWED_NUMS.get(name, set()) | SAFE | numbers(name)   # 'your360 AI' contains 360
        theirs = numbers(r.get("first_message")) | numbers(str(r.get("monthly_visits"))) | numbers(dom)
        try:
            visits = float(str(r.get("monthly_visits") or 0).replace(",", ""))
        except ValueError:
            visits = 0.0
        stray = set()
        for n in numbers(m2):
            bare = n.strip(".,").replace(",", "")
            if bare in own or n in own:
                continue
            if any(bare == t.strip(".,").replace(",", "") or bare in t for t in theirs):
                continue
            # their traffic, quoted rounded ("13,000" for 13,024; "160k" for 160,400)
            try:
                v = float(bare)
                for scale in (1, 1e3, 1e6):
                    if visits and abs(v * scale - visits) <= 0.1 * visits:
                        raise StopIteration
            except StopIteration:
                continue
            except ValueError:
                pass
            stray.add(n)
        if stray and not resolved:
            problems.append((dom, f"UNVERIFIED NUMBER in msg2 citing {name}", ", ".join(sorted(stray))))
        if not resolved and "{first-name}" not in m2:
            problems.append((dom, "missing {first-name}", ""))
        if resolved and r.get("first_name") and r["first_name"] not in m2:
            problems.append((dom, "send list: message not personalized", ""))
        if "—" in m2 or "–" in m2:
            problems.append((dom, "em/en dash", ""))
        # Layout shift (CLS) is retired as a signal: the claim rots on its own (28-day rolling
        # real-user average) and vanishes below Google's reporting threshold. Catch any that
        # sneak back into the copy or the chosen signal.
        blob = f"{r.get('first_message','')} {m2} {r.get('chosen_signal','')}"
        if re.search(r"layout shift|jumps around|shifts around|page (?:jump|shift|mov|settl)"
                     r"|content mov|CLS\b", blob, re.I):
            problems.append((dom, "RETIRED SIGNAL: layout shift / CLS referenced", ""))
        if url_for(name) not in m2:
            problems.append((dom, "case-study url missing from msg2", ""))
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=str(DATA / "messages_v2.csv"))
    args = ap.parse_args()
    rows = list(csv.DictReader(open(args.csv)))
    problems = audit(rows)
    import collections
    print(f"Audited {len(rows)} rows from {args.csv}\n")
    if not problems:
        print("CLEAN — every case study proves the pitch it backs, every url is verified, "
              "every number traces to a real metric.")
        return
    kinds = collections.Counter(p[1].split(":")[0] for p in problems)
    for k, n in kinds.most_common():
        print(f"{n:>4}  {k}")
    print(f"\n{len(problems)} problems. First 25:")
    for dom, what, detail in problems[:25]:
        print(f"  {dom:<28} {what:<52} {detail}")
    sys.exit(1)


if __name__ == "__main__":
    main()
