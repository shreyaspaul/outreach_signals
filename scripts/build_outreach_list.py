#!/usr/bin/env python3
"""
Build the send-ready outreach list: pick ONE best contact per company and attach the
correct message strictly by domain.

Inputs:
  - Person_details_enriched0-1000_batch1.csv + batch2.csv  (people: name/title/LinkedIn/Website)
  - the messages CSV, keyed by Domain (MESSAGES_FILE env, default messages_v2.csv)

Rules:
  1. Dedup people by company (normalized domain): keep the single contact most likely to reply
     to AND care about a website/Webflow-design pitch (see score_person()).
  2. Attach the message for that person's domain ONLY — matched on normalized domain, so we never
     pitch someone about a site they don't own. Fill {first-name} with the person's first name.

Outputs (nothing deleted; new files only) — `<name><OUT_SUFFIX>.csv`:
  - data/<batch>/outreach_ready.csv       one row per company: chosen person + their message
  - data/<batch>/not_contacted.csv        runner-up contacts at those same companies
  - data/<batch>/messages_no_contact.csv  message domains that have NO contact yet (can't send)

Env:
  LEADS_BATCH   batch folder under data/            (default batch_01)
  MESSAGES_FILE messages CSV inside that folder     (default messages_v2.csv)
  OUT_SUFFIX    suffix for the three output files   (default "")

  The defaults reproduce the original v2 run and OVERWRITE the live v2 campaign files.
  For the v3 campaign always pass a suffix, e.g.:
    LEADS_BATCH=batch_01 MESSAGES_FILE=messages_v3.csv OUT_SUFFIX=_v3 \
        python scripts/build_outreach_list.py
"""
import os
import re
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# per-batch data folder: data/<batch>/ (switch with LEADS_BATCH env var)
DATA = ROOT / "data" / os.environ.get("LEADS_BATCH", "batch_01")
PEOPLE = sorted(DATA.glob("Person_details*.csv"))
MESSAGES = DATA / os.environ.get("MESSAGES_FILE", "messages_v2.csv")
SUFFIX = os.environ.get("OUT_SUFFIX", "")


def norm_domain(x):
    x = str(x).strip().lower()
    x = re.sub(r"^https?://", "", x)
    x = re.sub(r"^www\.", "", x)
    return x.split("/")[0].strip()


def first_name(full):
    tok = str(full).strip().split()
    if not tok:
        return ""
    n = re.sub(r"[^A-Za-z'\-]", "", tok[0])
    return n[:1].upper() + n[1:] if n else ""


def last_name(full):
    """Everything after the first token. Blank for mononyms (some rows are just 'Johannes')."""
    tok = str(full).strip().split()
    if len(tok) < 2:
        return ""
    n = re.sub(r"[^A-Za-z'\-\s]", "", " ".join(tok[1:])).strip()
    return n[:1].upper() + n[1:] if n else ""


def score_person(row):
    """Higher = more likely to reply to AND care about a website/design/Webflow pitch.

    USER RULE (2026-08-08) — strict tier order, tiers cannot interleave via seniority:
        1. MARKETING / website owner  (400+)  — at ANY seniority, ahead of the founder
        2. FOUNDER / owner / CEO      (200+)
        3. everyone else              (<100)  — product/design > sales > comms/PR/social > tech

    Note comms/PR/social is TIER 3, not marketing: it owns external messaging, not the website.
    """
    t = str(row.get("Title", "")).lower()
    # "founder's office" / "ceo's office" / "founder associate" / "chief of staff" work FOR a
    # founder but are not one — don't award the founder bonus to them.
    is_founder = (bool(re.search(r"found|owner|\bceo\b|president|proprietor", t))
                  and not re.search(r"office|associate|assistant|chief of staff|'s ", t))
    is_comms = bool(re.search(r"communicat|public relation|\bpr\b|social media|\bpress\b|community", t))
    # marketing = owns the brand/website. comms-only titles are explicitly excluded (tier 3).
    is_mktg = bool(re.search(r"market|growth|brand|demand|content|\bseo\b|"
                             r"digital|\bcmo\b|audience|lifecycle", t))
    is_prod = bool(re.search(r"product|design|\bux\b|\bui\b|creative", t))
    is_sales = bool(re.search(r"sales|business development|\bbd\b|partnership|account|commercial", t))
    is_tech = bool(re.search(r"engineer|\bcto\b|technolog|developer|\bdev\b|\bdata\b|scien|"
                             r"security|infrastructure|devops|architect|machine learning|platform", t))
    if re.search(r"\bchief\b|\bc[emorpt]o\b|found|owner|president", t):
        sen = 20
    elif re.search(r"\bvp\b|vice president|\bhead\b|\bsvp\b|\bevp\b", t):
        sen = 16
    elif re.search(r"director", t):
        sen = 10
    elif re.search(r"lead|principal|manager", t):
        sen = 5
    else:
        sen = 3
    # TIER 1 — marketing / website owner. A comms-flavoured title only counts here if it ALSO
    # carries a real marketing/brand/web remit (e.g. "Head of Brand & Communications").
    if is_mktg:
        # Within marketing: core marketing/brand/growth > digital/content/web/SEO.
        sub = 0
        if re.search(r"\bmarketing\b|\bcmo\b|marketing officer|brand|growth|demand", t):
            sub += 35   # core marketing/brand/growth — owns brand, website, design decisions
        elif re.search(r"digital|\bweb\b|website|content|\bseo\b|lifecycle|audience", t):
            sub += 22   # digital / content / web — site-adjacent owner
        if is_comms:
            sub -= 15   # part-comms remit — still tier 1, just ranked last within it
        return 400 + sub + sen + (15 if is_founder else 0)
    # role affinity for a WEBSITE pitch, used to order within tier 2 and to rank tier 3:
    #   product/design (site-adjacent) > generalist/CEO > sales > comms/PR/social > tech.
    # Keep this term in tier 2 as well, or every founder ties on seniority alone and the
    # tie-break picks alphabetically — which silently swaps CEOs for CTOs.
    role = 32 if is_prod else 22 if is_sales else 16 if is_comms else 12 if is_tech else 20
    # TIER 2 — founders. Decision power + reply rate, but below anyone who owns the site.
    if is_founder:
        return 200 + sen + role
    # TIER 3 — the rest.
    return role + sen


def tie_key(row):
    """When scores tie: prefer reachable, then smaller (founder-led) co.

    LinkedIn is REQUIRED upstream (it's the outreach channel), so that term is always 0 here.
    A work email is a nice-to-have only — outreach is LinkedIn DM, so it never gates selection.
    """
    hc = row.get("Company Headcount")
    try:
        hc = float(hc)
    except (TypeError, ValueError):
        hc = 1e9
    return (
        0 if pd.notna(row.get("Work Email")) and str(row.get("Work Email")).strip() else 1,
        0 if pd.notna(row.get("Person LinkedIn")) and str(row.get("Person LinkedIn")).strip() else 1,
        hc,
        str(row.get("Full Name", "")),
    )


def main():
    ppl = pd.concat([pd.read_csv(f) for f in PEOPLE], ignore_index=True)
    # LinkedIn is the outreach channel -> a contact without one is not sendable, so they are not
    # eligible to be picked at all. (Also avoids drop_duplicates() collapsing every blank-LinkedIn
    # person into a single row, since pandas treats NaNs as equal.)
    li = ppl["Person LinkedIn"].astype(str).str.strip()
    no_li = (li == "") | (li.str.lower() == "nan")
    if no_li.any():
        print(f"excluded {int(no_li.sum())} people with no LinkedIn URL (not reachable)")
    ppl = ppl[~no_li].copy()
    ppl = ppl.drop_duplicates(subset=["Person LinkedIn"]).copy()
    ppl["domain"] = ppl["Website"].map(norm_domain)
    ppl["_score"] = ppl.apply(score_person, axis=1)
    ppl["_tie"] = ppl.apply(tie_key, axis=1)

    msg = pd.read_csv(MESSAGES)
    msg["domain"] = msg["Domain"].map(norm_domain)
    # only domains with an actual message to send
    msg = msg[msg["first_message"].notna() & (msg["first_message"].astype(str).str.strip() != "")]
    msg_by_dom = {r["domain"]: r for _, r in msg.iterrows()}

    rows, dropped, chosen_domains = [], [], set()
    for dom, grp in ppl.groupby("domain"):
        if dom not in msg_by_dom:
            continue  # person exists but no message for their site -> never pitch it
        grp = grp.sort_values(by=["_score", "_tie"], ascending=[False, True])
        best = grp.iloc[0]
        others = grp.iloc[1:]
        m = msg_by_dom[dom]
        fn = first_name(best["Full Name"])
        for rank, (_, p) in enumerate(others.iterrows(), start=2):
            dropped.append({
                "domain": dom, "Company Name": p.get("Company Name"),
                "Full Name": p["Full Name"], "Title": p["Title"],
                "Person LinkedIn": p["Person LinkedIn"], "Work Email": p.get("Work Email"),
                "Company Headcount": p.get("Company Headcount"), "Location": p.get("Location"),
                "selection_score": int(p["_score"]), "rank_at_company": rank,
                "chosen_instead": f"{best['Full Name']} ({best['Title']})",
            })

        def fill(x):
            return str(x).replace("{first-name}", fn) if fn else str(x)

        rows.append({
            "domain": dom, "message_Domain": m["Domain"], "person_Website": best["Website"],
            "Full Name": best["Full Name"], "first_name": fn,
            "last_name": last_name(best["Full Name"]), "Title": best["Title"],
            "Person LinkedIn": best["Person LinkedIn"], "Work Email": best.get("Work Email"),
            "Company Name": best.get("Company Name"), "Company Headcount": best.get("Company Headcount"),
            "Location": best.get("Location"), "Company LinkedIn": best.get("Company LinkedIn"),
            "selection_score": int(best["_score"]),
            "contacts_at_company": len(grp),
            "dropped_contacts": " ; ".join(f"{r['Full Name']} ({r['Title']})" for _, r in others.iterrows()),
            "priority": m.get("priority"), "signal_category": m.get("signal_category"),
            "chosen_signal": m.get("chosen_signal"), "case_study_name": m.get("case_study_name"),
            "case_study_url": m.get("case_study_url"), "tone_flag": m.get("tone_flag"),
            "first_message": fill(m["first_message"]),
            "second_message": fill(m["second_message"]),
            "third_message": fill(m["third_message"]),
        })
        chosen_domains.add(dom)

    out = pd.DataFrame(rows).sort_values("Company Name")

    # FINAL COMPLETENESS GATE — the send file must be sendable on every row, no exceptions.
    # Required: a person, a first name, a LinkedIn URL, all three messages, and no leftover
    # {first-name} token. Work email is NOT required (outreach is LinkedIn DM).
    def _has(v):
        s = str(v).strip()
        return bool(s) and s.lower() != "nan"

    def incomplete_reason(r):
        why = []
        if not _has(r["Full Name"]):
            why.append("no_name")
        if not _has(r["first_name"]):
            why.append("no_first_name")
        if not _has(r["Person LinkedIn"]):
            why.append("no_linkedin")
        for m in ("first_message", "second_message", "third_message"):
            if not _has(r[m]):
                why.append(f"empty_{m}")
            elif "{first-name}" in str(r[m]):
                why.append(f"unfilled_token_{m}")
        return ";".join(why)

    out["_incomplete"] = out.apply(incomplete_reason, axis=1)
    bad = out[out["_incomplete"] != ""].copy()
    out = out[out["_incomplete"] == ""].drop(columns=["_incomplete"])
    if len(bad):
        bad.rename(columns={"_incomplete": "incomplete_reason"}).to_csv(
            DATA / f"outreach_incomplete{SUFFIX}.csv", index=False)

    out.to_csv(DATA / f"outreach_ready{SUFFIX}.csv", index=False)

    # runner-up contacts at the SAME companies we ARE reaching out to — the people we
    # deliberately chose NOT to message (kept for reference / manual override).
    drop_df = pd.DataFrame(dropped).sort_values(["Company Name", "rank_at_company"])
    drop_df.to_csv(DATA / f"not_contacted{SUFFIX}.csv", index=False)

    # message domains with no contact at all
    no_contact = msg[~msg["domain"].isin(ppl["domain"])]
    nc = no_contact[["Domain", "Name", "signal_category", "chosen_signal",
                     "first_message", "second_message", "third_message"]]
    nc.to_csv(DATA / f"messages_no_contact{SUFFIX}.csv", index=False)

    rel = DATA.relative_to(ROOT)
    print(f"messages source: {rel}/{MESSAGES.name}  ({len(msg)} written rows)")
    print(f"people (deduped, LinkedIn required): {len(ppl)} across {ppl['domain'].nunique()} domains")
    print(f"OUTREACH-READY: {len(out)} companies (one best contact + message each, all sendable)")
    print(f"  -> {rel}/outreach_ready{SUFFIX}.csv")
    if len(bad):
        print(f"  DROPPED as incomplete: {len(bad)} -> {rel}/outreach_incomplete{SUFFIX}.csv")
        print("   ", bad["_incomplete"].value_counts().to_dict())
    tiers = {"1 marketing": (out["selection_score"] >= 400).sum(),
             "2 founder": ((out["selection_score"] >= 200) & (out["selection_score"] < 400)).sum(),
             "3 other": (out["selection_score"] < 200).sum()}
    print(f"  contact tiers: {tiers}")
    print(f"NOT-CONTACTED runner-ups at those companies: {len(drop_df)} -> {rel}/not_contacted{SUFFIX}.csv")
    print(f"messages with NO contact yet: {len(nc)} -> {rel}/messages_no_contact{SUFFIX}.csv")
    print(f"people on domains with no message (excluded): "
          f"{ppl[~ppl['domain'].isin(set(msg['domain']))]['domain'].nunique()}")


if __name__ == "__main__":
    main()
