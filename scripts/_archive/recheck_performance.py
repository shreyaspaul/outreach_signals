#!/usr/bin/env python3
"""
Re-check the PERFORMANCE claims live.

A screenshot cannot show load speed, so the vision adjudicator returns UNSURE for every
performance row. Those get settled here against live PageSpeed instead of being guessed at:
if a site got faster since the June audit, we must not send it a message calling it slow.

A performance claim HOLDS only if the site is still genuinely slow on mobile.
Threshold: mobile score < 50 is the project's "slow" line (same one the signal was built on).

Usage: python scripts/recheck_performance.py
"""
import concurrent.futures as cf
import csv, json, os, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pagespeed_checker import get_pagespeed_score

ROOT = Path(__file__).resolve().parent.parent
BATCH = os.environ.get("LEADS_BATCH", "batch_01")
DATA = ROOT / "data" / BATCH
VERDICTS = DATA / "signal_verdicts.json"
SLOW = 50


def load_key():
    envf = ROOT / ".env"
    if envf.exists():
        for line in envf.read_text().splitlines():
            if line.strip().startswith("PAGESPEED_API_KEY") and "=" in line:
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get("PAGESPEED_API_KEY")


def main():
    verdicts = json.loads(VERDICTS.read_text())
    changes = {r["domain"]: r for r in csv.DictReader(open(DATA / "site_changes.csv"))}
    ready = {r["domain"]: r for r in csv.DictReader(open(DATA / "outreach_ready.csv"))}

    todo = [d for d, v in verdicts.items()
            if v["verdict"] == "UNSURE" and changes.get(d, {}).get("signal_category") == "performance"]
    print(f"Re-checking live mobile PageSpeed for {len(todo)} performance claims...")
    key = load_key()

    def one(dom):
        url = ready[dom].get("person_Website") or f"https://{dom}"
        try:
            res = get_pagespeed_score(url, strategy="mobile", api_key=key)
            return dom, res.get("score"), res.get("error")
        except Exception as e:
            return dom, None, str(e)[:60]

    out = []
    with cf.ThreadPoolExecutor(max_workers=5) as ex:
        for i, (dom, score, err) in enumerate(ex.map(one, todo), 1):
            if err or score is None:
                verdict, note = "UNSURE", f"pagespeed failed: {err}"
            elif score < SLOW:
                verdict, note = "HOLDS", f"still slow on mobile ({score})"
            else:
                verdict, note = "BROKEN", f"no longer slow: mobile is now {score}"
            verdicts[dom]["verdict"] = verdict
            verdicts[dom]["reason"] = note
            verdicts[dom]["mobile_now"] = score
            out.append((dom, verdict, note))
            print(f"  [{i}/{len(todo)}] {dom:<28} {verdict:<7} {note}")

    VERDICTS.write_text(json.dumps(verdicts, indent=1))
    import collections
    print("\n" + str(dict(collections.Counter(v for _, v, _ in out))))


if __name__ == "__main__":
    main()
