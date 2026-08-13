#!/usr/bin/env python3
"""
Broaden the opener pretext in message 1.

Problem: every message claimed a hyper-specific browsing reason, e.g.
  "came across Nexcade while looking at freight-automation tools"
  "came across X while looking at Device-as-a-Service providers"
  "came across X while looking at Bitcoin treasury companies"
Nobody browses those categories. It reads invented, which undermines the inference that follows.

Fix: keep the pretext but widen it to something a design studio founder plausibly looks at
(AI tools, B2B SaaS sites, dev tools, fintech products, ...), derived from the Crunchbase
`Industry` tags. Deterministic: no LLM, so nothing else in the message can drift.

  python scripts/broaden_openers.py            # dry run, prints coverage + samples
  python scripts/broaden_openers.py --apply    # rewrite results JSON + rebuild CSVs
"""
import argparse, csv, json, os, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BATCH = os.environ.get("LEADS_BATCH", "batch_01")
DATA = ROOT / "data" / BATCH
RESULTS = DATA / "message_results.json"
ENRICHED = next(iter(sorted(DATA.glob("enriched_*.csv"))))

# Industry tag -> the broad thing a design studio would plausibly be browsing.
# Order matters: first match wins, so put the more specific verticals above the generic ones.
BUCKETS = [
    (("bitcoin", "blockchain", "cryptocurrency", "crypto", "web3", "nft", "defi", "ethereum"),
     "crypto and web3 products"),
    (("health care", "healthcare", "biotechnology", "medical", "mental health", "wellness",
      "life science", "pharmaceutical", "health diagnostics", "therapeutics", "clinical"),
     "health tech sites"),
    (("clean energy", "sustainability", "climate", "solar", "renewable", "greentech", "carbon",
      "environmental", "energy", "agriculture", "agtech"),
     "climate and energy tech sites"),
    (("fintech", "financial services", "banking", "payments", "accounting", "insurance",
      "lending", "credit", "wealth", "investing", "finance"),
     "fintech products"),
    (("e-commerce", "ecommerce", "retail", "marketplace", "consumer goods", "fashion", "food",
      "beverage", "shopping"),
     "eCommerce brands"),
    (("developer", "devops", "open source", "api", "cloud computing", "infrastructure",
      "cyber security", "cybersecurity", "security", "database", "programming"),
     "dev tools"),
    (("artificial intelligence", "generative ai", "agentic ai", "ai infrastructure",
      "machine learning", "natural language processing", "computer vision", "ai"),
     "AI tools"),
    (("saas", "enterprise software", "b2b", "analytics", "big data", "software",
      "information technology", "productivity", "crm", "sales", "marketing"),
     "B2B SaaS sites"),
]
# Consumer products must never be called "B2B SaaS" — that was the first version's bug
# (Pickleheads, a consumer pickleball community, got labelled a B2B SaaS site).
CONSUMER = ("consumer", "social network", "community", "sports", "fitness", "music", "art",
            "gaming", "games", "game", "video game", "creator", "dating", "travel", "food and beverage",
            "e-learning", "education", "edtech", "messaging", "photo", "entertainment",
            "media", "link-in-bio", "gift", "gifting", "gaming")
# Truthful of every company on the list. Used when we cannot confidently place them, because
# asserting a wrong category is exactly the failure we are fixing.
DEFAULT_BUCKET = "tech sites"

# "came across Nexcade while looking at freight-automation tools." and the no-"while" variant,
# plus "looking into" / "digging into" / "going through". Only the reason clause is replaced.
OPENER = re.compile(
    r"(came across\s+.+?)\s+(?:while\s+)?(?:looking|digging|poking around|going through|browsing)"
    r"\s+(?:at|into|through)\s+[^.!?\n]+",
    re.IGNORECASE,
)


def _has(text: str, key: str) -> bool:
    """Whole-word match. Substring matching is a trap here: 'art' hits inside 'Artificial
    Intelligence' and 'ai' hits inside 'domain', which mis-bucketed hundreds of rows."""
    return re.search(r"(?<![a-z0-9])" + re.escape(key) + r"(?![a-z0-9])", text) is not None


def bucket_for(industry: str, niche: str = "") -> str:
    """The original niche phrase ('AI music tools', 'link-in-bio tools') is descriptive, so it's
    a better signal than the Crunchbase tags alone. Consider both."""
    ind = (industry or "").lower()
    both = f"{ind} {(niche or '').lower()}"
    # a specific vertical (fintech, health, crypto...) outranks the generic consumer read
    for keys, label in BUCKETS:
        if any(_has(both, k) for k in keys):
            if label in ("AI tools", "B2B SaaS sites") and any(_has(both, c) for c in CONSUMER) \
                    and not _has(ind, "b2b"):
                return "consumer apps"     # a consumer AI app is still consumer
            return label
    if any(_has(both, c) for c in CONSUMER):
        return "consumer apps"
    return DEFAULT_BUCKET


def niche_of(msg: str) -> str:
    """The hyper-specific phrase currently in the opener, e.g. 'AI music tools'."""
    m = OPENER.search(msg or "")
    if not m:
        return ""
    tail = msg[m.start():m.end()]
    m2 = re.search(r"(?:at|into|through)\s+([^.!?\n]+)$", tail)
    return m2.group(1) if m2 else ""


def load_industries():
    out = {}
    with ENRICHED.open() as f:
        for r in csv.DictReader(f):
            dom = (r.get("Domain") or "").strip()
            if dom:
                out[dom] = r.get("Industry") or ""
    return out


def rewrite(msg: str, bucket: str):
    """Replace only the pretext clause. Returns (new_msg, matched)."""
    if not msg:
        return msg, False
    new, n = OPENER.subn(lambda m: f"{m.group(1)} while looking at {bucket}", msg, count=1)
    return new, bool(n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    results = json.loads(RESULTS.read_text())
    industries = load_industries()

    matched, unmatched, samples = 0, [], []
    for r in results:
        m1 = r.get("first_message") or ""
        if not m1.strip():
            continue
        b = bucket_for(industries.get(r["domain"], ""), niche_of(m1))
        new, ok = rewrite(m1, b)
        if ok:
            matched += 1
            if len(samples) < 10:
                samples.append((m1.split("\n")[0][:78], new.split("\n")[0][:78]))
            if args.apply:
                r["first_message"] = new
        else:
            unmatched.append((r["domain"], m1.split("\n")[0][:70]))

    print(f"opener pretext rewritten in {matched} messages; {len(unmatched)} had no pretext to change\n")
    for old, new in samples:
        print(f"  - {old}\n  + {new}\n")
    if unmatched:
        print(f"no pretext found (left untouched), first 8:")
        for d, o in unmatched[:8]:
            print(f"    {d:<24} {o}")

    if not args.apply:
        print("\nDry run. Re-run with --apply to write.")
        return

    bak = RESULTS.with_suffix(".json.pre_openers")
    if not bak.exists():
        bak.write_text(json.dumps(json.loads(RESULTS.read_text()), indent=1))
    RESULTS.write_text(json.dumps(results, indent=1))
    subprocess.run([sys.executable, "scripts/prep_bundles.py", "assemble", str(ENRICHED),
                    str(RESULTS), "-o", str(DATA / "messages_v2.csv")], cwd=ROOT, check=True)
    subprocess.run([sys.executable, "scripts/build_outreach_list.py"], cwd=ROOT, check=True)
    print(f"\nApplied. Rebuilt messages_v2.csv + outreach_ready.csv")


if __name__ == "__main__":
    main()
