#!/usr/bin/env python3
"""Build a clean comparison CSV from the model-swap test outputs vs the in-session gold.

Reads data/model_swap/<domain>__<variant>.json for each of the 6 gold-reference prospects,
plus my in-session authored version (data/message_results.json) as the gold row, and writes
data/model_comparison.csv with per-(prospect x model) rows for side-by-side comparison.
"""
import json, re
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SWAP = ROOT / "data" / "model_swap"
DOMAINS = ["www.simplyblock.io", "nca.org/", "www.cirkledin.com/",
           "www.coreworks.ai/", "www.deeptrust.ai/", "www.bagel.com"]
# variant file-tag -> (label, thinking, est batch cost for all 380 $)
VARIANTS = [
    ("opus",       "Opus 4.8",          "off", 8.0),
    ("opus_think", "Opus 4.8 +thinking", "on", 16.4),
    ("sonnet",     "Sonnet 5",          "off", 4.9),
    ("haiku",      "Haiku 4.5",         "off", 1.3),
]

gold = {r["domain"]: r for r in json.load(open(ROOT / "data" / "message_results.json"))}
bundles = {p["domain"]: p for p in json.load(open(ROOT / "data" / "message_bundles_all.json"))["prospects"]}


def casing_clean(s):
    for seg in re.split(r"(?<=[.!?])\s+|\n+", str(s)):
        seg = seg.strip()
        if seg and seg[0].islower() and not seg.lower().startswith(("scite", "tapouts", "http")):
            return "NO"
    if re.search(r"(?<![A-Za-z])i(?![A-Za-z'])", str(s)) or re.search(r"(?<![A-Za-z])i'", str(s)):
        return "NO"
    return "yes"


def norm(x):
    return re.sub(r"[^a-z0-9]", "", str(x).lower())


def words(s):
    return len(str(s).split())


rows = []
for dom in DOMAINS:
    g = gold.get(dom, {})
    b = bundles.get(dom, {}).get("bundle", {})
    name = b.get("name", dom)
    hi = b.get("traffic_is_high")
    gold_cat = g.get("signal_category", "")
    gold_cs = g.get("case_study_name", "")

    # gold (my in-session) row first
    rows.append({
        "domain": dom, "name": name, "traffic_high": hi,
        "model": "MINE (in-session Opus)", "thinking": "in-session",
        "signal_category": gold_cat, "chosen_signal": g.get("chosen_signal", ""),
        "signal_cat_matches_gold": "-", "case_study": gold_cs, "cs_matches_gold": "-",
        "casing_clean": casing_clean(g.get("first_message")), "msg1_words": words(g.get("first_message")),
        "est_batch_cost_380_usd": "", "first_message": g.get("first_message", ""),
        "angle_rationale": g.get("angle_rationale", ""),
    })
    for tag, label, thinking, cost in VARIANTS:
        f = SWAP / (re.sub(r"[^\w]+", "_", dom).strip("_") + f"__{tag}.json")
        if not f.exists():
            continue
        try:
            o = json.loads(f.read_text())
        except Exception:
            o = {}
        rows.append({
            "domain": dom, "name": name, "traffic_high": hi,
            "model": label, "thinking": thinking,
            "signal_category": o.get("signal_category", ""),
            "chosen_signal": o.get("chosen_signal", ""),
            "signal_cat_matches_gold": "yes" if norm(o.get("signal_category")) == norm(gold_cat) and gold_cat else "no",
            "case_study": o.get("case_study_name", ""),
            "cs_matches_gold": "yes" if norm(o.get("case_study_name")) == norm(gold_cs) and gold_cs else "no",
            "casing_clean": casing_clean(o.get("first_message")),
            "msg1_words": words(o.get("first_message")),
            "est_batch_cost_380_usd": cost,
            "first_message": o.get("first_message", ""),
            "angle_rationale": o.get("angle_rationale", ""),
        })

df = pd.DataFrame(rows)
out = ROOT / "data" / "model_comparison.csv"
df.to_csv(out, index=False)

# quick summary to stdout
print(f"Wrote {out.relative_to(ROOT)}  ({len(df)} rows)\n")
comp = df[df["model"] != "MINE (in-session Opus)"]
print("SCORECARD (across 6 gold-reference prospects):")
for label in [v[1] for v in VARIANTS]:
    sub = comp[comp["model"] == label]
    if not len(sub):
        continue
    sig = (sub["signal_cat_matches_gold"] == "yes").sum()
    cs = (sub["cs_matches_gold"] == "yes").sum()
    cln = (sub["casing_clean"] == "yes").sum()
    print(f"  {label:20} signal-cat match {sig}/{len(sub)} | case-study match {cs}/{len(sub)} "
          f"| casing-clean {cln}/{len(sub)} | ~${VARIANTS[[v[1] for v in VARIANTS].index(label)][3]}/380")
