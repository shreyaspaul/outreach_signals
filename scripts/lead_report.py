#!/usr/bin/env python3
"""
Broken-down lead report for a batch: the numbers that matter, as a tidy CSV (+ printed table).

Reconciles the funnel from raw enriched sites -> worth-reaching -> contact-found, and breaks
the worth-reaching set down by signal and the found contacts down by role. Reusable per batch.

Usage:
  python scripts/lead_report.py                    # uses the current default files
  python scripts/lead_report.py <enriched.csv> <messages.csv> <outreach_ready.csv>
"""
import sys, re
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENRICHED = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "enriched_ALL_999.csv"
MESSAGES = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "data" / "messages_v2.csv"
OUTREACH = Path(sys.argv[3]) if len(sys.argv) > 3 else ROOT / "data" / "outreach_ready.csv"
OUT = ROOT / "data" / "lead_report.csv"


def role_cat(t):
    t = str(t).lower()
    if re.search(r"\bmarketing\b|\bcmo\b|brand|growth|demand", t):
        return "marketing/brand/growth"
    if re.search(r"digital|content|\bweb\b|website|\bseo\b|lifecycle|audience", t):
        return "digital/content/web"
    if re.search(r"communicat|public relation|\bpr\b|social media|\bpress\b|community", t):
        return "comms/PR/social"
    if re.search(r"found|\bceo\b|owner|president", t) and not re.search(r"office|associate|'s ", t):
        return "founder/CEO"
    if re.search(r"\bcto\b|engineer|technolog|developer|product|design", t):
        return "product/tech/design"
    return "other"


def main():
    enr = pd.read_csv(ENRICHED, low_memory=False)
    enr = enr[enr["Domain"].notna() & (enr["Domain"].astype(str).str.strip() != "")]
    g = enr["overall_grade"].astype(str) if "overall_grade" in enr.columns else pd.Series("", index=enr.index)
    invalid = g.str.upper().str.contains("INVALID").sum()
    ungraded = ((g.str.strip() == "") | (g.str.lower() == "nan")).sum()

    msg = pd.read_csv(MESSAGES)
    has_msg = msg["first_message"].notna() & (msg["first_message"].astype(str).str.strip() != "")
    skips = (msg["priority"].astype(str) == "skip").sum() if "priority" in msg.columns else 0
    sendable = int(has_msg.sum())

    out = pd.read_csv(OUTREACH)
    nc = ROOT / "data" / "messages_no_contact.csv"
    awaiting = len(pd.read_csv(nc)) if nc.exists() else (sendable - len(out))

    rows = [
        ("funnel", "total_enriched_sites", len(enr)),
        ("funnel", "invalid_parked_dead", int(invalid)),
        ("funnel", "ungraded_incomplete", int(ungraded)),
        ("funnel", "gradeable_rows", len(msg)),
        ("funnel", "skip_shutdown_no_message", int(skips)),
        ("funnel", "worth_reaching_out", sendable),  # rows with a real message (skips already excluded)
        ("funnel", "contact_found", len(out)),
        ("funnel", "awaiting_contact", int(awaiting)),
    ]
    if "signal_category" in msg.columns:
        for k, v in msg[has_msg]["signal_category"].fillna("(none)").value_counts().items():
            rows.append(("worth_reaching_by_signal", str(k), int(v)))
    for k, v in out["Title"].map(role_cat).value_counts().items():
        rows.append(("contacts_by_role", str(k), int(v)))

    rep = pd.DataFrame(rows, columns=["section", "metric", "count"])
    rep.to_csv(OUT, index=False)

    w = max(len(m) for _, m, _ in rows)
    last = None
    for sec, m, c in rows:
        if sec != last:
            print(f"\n[{sec}]")
            last = sec
        print(f"  {m:<{w}}  {c}")
    print(f"\n-> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
