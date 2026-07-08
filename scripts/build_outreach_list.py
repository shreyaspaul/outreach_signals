#!/usr/bin/env python3
"""
Build the send-ready outreach list: pick ONE best contact per company and attach the
correct message strictly by domain.

Inputs:
  - Person_details_enriched0-1000_batch1.csv + batch2.csv  (people: name/title/LinkedIn/Website)
  - data/messages_v2.csv                                    (messages, keyed by Domain)

Rules:
  1. Dedup people by company (normalized domain): keep the single contact most likely to reply
     to AND care about a website/Webflow-design pitch (see score_person()).
  2. Attach the message for that person's domain ONLY — matched on normalized domain, so we never
     pitch someone about a site they don't own. Fill {first-name} with the person's first name.

Outputs (nothing deleted; new files only):
  - data/outreach_ready.csv       one row per company: chosen person + their message
  - data/messages_no_contact.csv  message domains that have NO contact yet (can't send)
"""
import re
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PEOPLE = [ROOT / "Person_details_enriched0-1000_batch1.csv",
          ROOT / "Person_details_enriched0-1000_batch2.csv"]
MESSAGES = ROOT / "data" / "messages_v2.csv"


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


def score_person(row):
    """Higher = more likely to reply to AND care about a website/design/Webflow pitch."""
    t = str(row.get("Title", "")).lower()
    # "founder's office" / "ceo's office" / "founder associate" / "chief of staff" work FOR a
    # founder but are not one — don't award the founder bonus to them.
    is_founder = (bool(re.search(r"found|owner|\bceo\b|president|proprietor", t))
                  and not re.search(r"office|associate|assistant|chief of staff|'s ", t))
    is_mktg = bool(re.search(r"market|growth|brand|demand|content|comms|communicat|\bseo\b|"
                             r"digital|social media|\bcmo\b|audience|lifecycle", t))
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
    # USER RULE: pick the marketing / website owner FIRST, at ANY seniority, over the founder.
    if is_mktg:
        # Within marketing, rank by who actually owns website/brand/design decisions:
        #   core marketing/brand/growth  >  digital/content/web/SEO  >  comms/PR/social/press.
        sub = 0
        if re.search(r"\bmarketing\b|\bcmo\b|marketing officer|brand|growth|demand", t):
            sub += 35   # core marketing/brand/growth — owns brand, website, design decisions
        elif re.search(r"digital|\bweb\b|website|content|\bseo\b|lifecycle|audience", t):
            sub += 22   # digital / content / web — site-adjacent owner
        if re.search(r"communicat|public relation|\bpr\b|social media|\bpress\b|community", t):
            sub -= 15   # external messaging, not the website itself
        return 400 + sub + sen + (15 if is_founder else 0)
    # among the non-marketing rest, founders are preferred (reply rate + decision power).
    base = 32 if is_prod else 22 if is_sales else 12 if is_tech else 20
    return base + sen + (25 if is_founder else 0)


def tie_key(row):
    """When scores tie: prefer reachable (email, then LinkedIn), then smaller (founder-led) co."""
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
            "Full Name": best["Full Name"], "first_name": fn, "Title": best["Title"],
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
    out.to_csv(ROOT / "data" / "outreach_ready.csv", index=False)

    # runner-up contacts at the SAME companies we ARE reaching out to — the people we
    # deliberately chose NOT to message (kept for reference / manual override).
    drop_df = pd.DataFrame(dropped).sort_values(["Company Name", "rank_at_company"])
    drop_df.to_csv(ROOT / "data" / "not_contacted.csv", index=False)

    # message domains with no contact at all
    no_contact = msg[~msg["domain"].isin(ppl["domain"])]
    nc = no_contact[["Domain", "Name", "signal_category", "chosen_signal",
                     "first_message", "second_message", "third_message"]]
    nc.to_csv(ROOT / "data" / "messages_no_contact.csv", index=False)

    print(f"people (deduped): {len(ppl)} across {ppl['domain'].nunique()} domains")
    print(f"OUTREACH-READY: {len(out)} companies (one best contact + message each)")
    print(f"  -> data/outreach_ready.csv")
    print(f"NOT-CONTACTED runner-ups at those companies: {len(drop_df)} -> data/not_contacted.csv")
    print(f"messages with NO contact yet: {len(nc)} -> data/messages_no_contact.csv")
    print(f"people on domains with no message (excluded): "
          f"{ppl[~ppl['domain'].isin(set(msg['domain']))]['domain'].nunique()}")


if __name__ == "__main__":
    main()
