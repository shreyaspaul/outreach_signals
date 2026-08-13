"""Build a HeyReach test CSV with the exact same columns/format as outreach_ready.csv.

The messages are obvious "this is a test" copy, but every column, quoting rule and
newline convention matches the real send file so HeyReach maps them identically.

Edit TEST_CONTACTS with the accounts you can actually send to, then:
    python scripts/make_test_csv.py
"""
import csv
import os
from pathlib import Path

BATCH = os.getenv("LEADS_BATCH", "batch_01")
DATA = Path(__file__).resolve().parent.parent / "data" / BATCH
REAL = DATA / "outreach_ready.csv"
OUT = DATA / "heyreach_test.csv"

# --- EDIT ME: the accounts you can send a test message to -------------------
# Person LinkedIn is the only field HeyReach truly needs to reach someone.
TEST_CONTACTS = [
    {
        "domain": "prismport.co",
        "first_name": "Pratik",
        "last_name": "Hetamsaria",
        "Title": "CEO",
        "Person LinkedIn": "https://www.linkedin.com/in/pratik-hetamsaria-0277ba1b/",
        "Work Email": "pratik@prismport.co",
        "Company Name": "Prismport",
        "Company Headcount": "42",
        "Location": "New York, New York",
        "Company LinkedIn": "https://www.linkedin.com/company/prismport/",
        "signal_category": "performance",
        "chosen_signal": "slow mobile load",
        "case_study_name": "NewsCatcherAPI",
        "case_study_url": "https://prismport.co/case-studies/newscatcher",
    },
    {
        "domain": "prismport.co",
        "first_name": "Amjad",
        "last_name": "Rathod",
        "Title": "Dev",
        "Person LinkedIn": "https://www.linkedin.com/in/amjad-rathod/",
        "Work Email": "amjad@prismport.co",
        "Company Name": "Prismport",
        "Company Headcount": "17",
        "Location": "Berlin, Germany",
        "Company LinkedIn": "https://www.linkedin.com/company/prismport/",
        "signal_category": "design",
        "chosen_signal": "generic visual design",
        "case_study_name": "Studio Artegra",
        "case_study_url": "https://prismport.co/case-studies/studio-artegra",
    },
]
# ---------------------------------------------------------------------------


def messages(first: str, company: str, case_name: str, case_url: str):
    first_message = (
        f"Hey {first}, ignore this one, it's an automated message and there's no need to reply. "
        f"I'm testing out a new campaign tool and needed a live send to check everything lands "
        f"the way it should. This is the first of a three message sequence, so expect a second "
        f"message shortly that tests the follow-up step, and a third one after that to close it "
        f"out. No pitch attached, the {company} name is only here as test data."
    )
    second_message = (
        f"Hey {first}, quick context, this is still the test sequence, message two of three. "
        f"Checking that follow-ups fire and that a link on its own line renders properly:\n"
        f"{case_url}\n"
        f"That's the {case_name} page, used here purely as a link to click. Nothing to action."
    )
    third_message = (
        f"Hey {first}, last one, this closes out the test sequence. "
        f"Thanks for being the guinea pig, back to your day."
    )
    return first_message, second_message, third_message


def main():
    with REAL.open() as f:
        header = next(csv.reader(f))
    # same columns as the real send file, plus last_name for HeyReach personalization
    header.insert(header.index("first_name") + 1, "last_name")

    rows = []
    for c in TEST_CONTACTS:
        first = c["first_name"]
        m1, m2, m3 = messages(first, c["Company Name"], c["case_study_name"], c["case_study_url"])
        rows.append({
            "domain": c["domain"],
            "message_Domain": f"{c['domain']}/",
            "person_Website": f"https://{c['domain']}/",
            "Full Name": f"{c['first_name']} {c['last_name']}",
            "first_name": c["first_name"],
            "last_name": c["last_name"],
            "Title": c["Title"],
            "Person LinkedIn": c["Person LinkedIn"],
            "Work Email": c["Work Email"],
            "Company Name": c["Company Name"],
            "Company Headcount": c["Company Headcount"],
            "Location": c["Location"],
            "Company LinkedIn": c["Company LinkedIn"],
            "selection_score": "65",
            "contacts_at_company": "1",
            "dropped_contacts": "",
            "priority": "medium",
            "signal_category": c["signal_category"],
            "chosen_signal": c["chosen_signal"],
            "case_study_name": c["case_study_name"],
            "case_study_url": c["case_study_url"],
            "tone_flag": "clean",
            "first_message": m1,
            "second_message": m2,
            "third_message": m3,
        })

    with OUT.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        w.writerows(rows)

    print(f"Wrote {len(rows)} test rows -> {OUT}")


if __name__ == "__main__":
    main()
