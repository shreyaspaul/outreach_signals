#!/usr/bin/env python3
"""
Detect prospects whose site changed since we audited it.

Why: the audit ran 2026-06-19..23. Every message 1 cites a specific observation from that
audit ("leans on stock imagery", "slow first load", "thin content"). If the site was redesigned
since, the message describes a site that no longer exists — nexcade.ai is the known case. Sending
that is worse than not sending.

This pass re-captures each site NOW and compares it to the stored audit screenshot + word count.
No LLM, no API cost. It only FLAGS; it does not rewrite anything.

  visual_diff: mean absolute pixel difference (0..1) of the two captures, downscaled to a
               grayscale thumbnail. Layout/imagery changes move this a lot; minor content
               edits barely move it.
  word_delta:  relative change in rendered word count vs the audit.

Usage:
  python scripts/detect_site_changes.py                    # all send-list domains
  python scripts/detect_site_changes.py --limit 20
"""
import argparse, asyncio, csv, os, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from website_grader import capture_screenshot_and_content, clean_domain

ROOT = Path(__file__).resolve().parent.parent
BATCH = os.environ.get("LEADS_BATCH", "batch_01")
DATA = ROOT / "data" / BATCH
OLD_SHOTS = ROOT / "screenshots"
NEW_SHOTS = ROOT / "screenshots_recheck"
OUT = DATA / "site_changes.csv"

# Calibrated against known cases (2026-07-14):
#   nexcade.ai  (full rebrand)      visual_diff 0.353  -> must flag
#   withaccend  (visually identical) visual_diff 0.00007, yet word_count moved 1721->1042
# So the VISUAL diff is the trustworthy signal; rendered word count swings on lazy-loaded and
# dynamic content and produces false positives. Word delta is recorded for context but only
# TRIGGERS at an extreme value, where the page genuinely lost/gained most of its content.
VISUAL_THRESHOLD = 0.10
WORD_THRESHOLD = 0.60


def thumb(path, size=(160, 160)):
    from PIL import Image
    with Image.open(path) as im:
        return im.convert("L").resize(size, Image.BILINEAR)


def visual_diff(old_path, new_path):
    """Mean absolute pixel difference of the two captures, 0..1. None if either is missing."""
    if not (old_path.exists() and new_path.exists()):
        return None
    try:
        a, b = thumb(old_path), thumb(new_path)
        pa, pb = a.getdata(), b.getdata()
        return sum(abs(x - y) for x, y in zip(pa, pb)) / (len(pa) * 255.0)
    except Exception:
        return None


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--concurrency", type=int, default=6)
    args = ap.parse_args()

    NEW_SHOTS.mkdir(exist_ok=True)
    rows = list(csv.DictReader(open(DATA / "outreach_ready.csv")))
    # word counts from the audit, keyed by domain
    enriched = next(iter(sorted(DATA.glob("enriched_*.csv"))))
    old_words = {}
    with enriched.open() as f:
        for r in csv.DictReader(f):
            d = (r.get("Domain") or "").strip()
            try:
                old_words[d] = int(float(r.get("content_word_count") or 0))
            except ValueError:
                old_words[d] = 0

    targets = rows[: args.limit] if args.limit else rows
    print(f"Re-capturing {len(targets)} sites (concurrency {args.concurrency})...")
    sem = asyncio.Semaphore(args.concurrency)

    async def one(r):
        dom = r["domain"]
        url = r["person_Website"] or f"https://{dom}"
        res = await capture_screenshot_and_content(url, NEW_SHOTS, sem)
        return r, res

    done = 0
    out = []
    for fut in asyncio.as_completed([one(r) for r in targets]):
        r, res = await fut
        done += 1
        dom = r["domain"]
        md = r.get("message_Domain") or dom
        stem = clean_domain(md) or clean_domain(dom)
        old_p = OLD_SHOTS / f"{stem}.png"
        new_p = Path(res.get("screenshot_path")) if res.get("screenshot_path") else Path("/nonexistent")
        vd = visual_diff(old_p, new_p)
        ow = old_words.get(r.get("message_Domain"), 0) or old_words.get(dom, 0)
        nw = res.get("word_count") or 0
        wd = abs(nw - ow) / ow if ow else None
        # unknown (capture failed, or we have no audit-era screenshot to compare against) is NOT
        # the same as unchanged: we cannot vouch for the claim, so it must not go out blind.
        unknown = res.get("error") or not old_p.exists() or vd is None
        changed = (vd is not None and vd >= VISUAL_THRESHOLD) or (wd is not None and wd >= WORD_THRESHOLD)
        out.append({
            "domain": dom, "signal_category": r["signal_category"], "chosen_signal": r["chosen_signal"],
            "visual_diff": "" if vd is None else f"{vd:.3f}",
            "old_words": ow, "new_words": nw,
            "word_delta": "" if wd is None else f"{wd:.2f}",
            "capture_error": res.get("error") or "",
            "old_shot_missing": "yes" if not old_p.exists() else "",
            "changed": "CHANGED" if changed else ("UNKNOWN" if unknown else ""),
        })
        if done % 25 == 0:
            print(f"  {done}/{len(targets)}")

    with OUT.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader(); w.writerows(out)

    ch = [o for o in out if o["changed"]]
    err = [o for o in out if o["capture_error"]]
    print(f"\n{len(ch)}/{len(out)} sites CHANGED since the audit -> {OUT}")
    print(f"{len(err)} could not be re-captured (treat as unknown, do not send blind)")
    for o in sorted(ch, key=lambda x: -float(x["visual_diff"] or 0))[:15]:
        print(f"  {o['domain']:<30} visual_diff={o['visual_diff']:<6} words {o['old_words']}->{o['new_words']}"
              f"  [{o['signal_category']}: {o['chosen_signal'][:40]}]")


if __name__ == "__main__":
    asyncio.run(main())
