# NO-API OUTREACH GENERATION LOOP — operating playbook

Write a 3-message outreach sequence for every gradeable prospect **in-session (Claude writes them,
NOT the Anthropic API — the account is out of credits)**. Full writing rules live in
`.claude/skills/generate-outreach/SKILL.md`; this file is the operational procedure + the fast
heuristics converged on during the 2026-07-20/21 run.

Batch dir: `data/<LEADS_BATCH>/` (default `batch_01`). Output: `message_results_v3.json` +
`messages_v3.csv` (the live `_v2` campaign files are untouched), plus `messages_v3_complete.csv`
(the lean send-ready export, refreshed by `export_complete.py`).

## PER-CYCLE PROCEDURE (repeat until REMAINING == 0)
1. `cd <repo> && source venv/bin/activate`
2. `python scripts/outreach_loop/next_bundles.py 16`  → prints WRITTEN / REMAINING + next 16 bundles.
   If REMAINING == 0 → FINALIZE.
3. Write a `chunk.json` (array of result objects, schema below) for those bundles — every word yours,
   against the spine + decision order. Skip shutdown/wind-down sites (`priority: "skip"`, empty messages).
   **Skips are pruned later:** dead entries get removed from the results file and quarantined in
   `skipped_shutdowns.json` (done 2026-08-08 for kovadx / huxe / skarbe / ftx). Never write the literal
   string `"SKIP"` into a message field — leave it empty; `"SKIP"` reads as real text downstream.
4. `python scripts/outreach_loop/merge_results.py chunk.json`
5. `LEADS_BATCH=batch_01 python scripts/prep_bundles.py assemble data/batch_01/enriched_ALL_999.csv data/batch_01/message_results_v3.json -o data/batch_01/messages_v3.csv`
6. `RESULTS_FILE=message_results_v3.json MESSAGES_FILE=messages_v3.csv LEADS_BATCH=batch_01 python scripts/qa_check.py`
   0 flags = good. If flagged: HAND-FIX (edit the message in message_results_v3.json, re-assemble, re-run).
   **Never run `qa_check.py --fix`** — its content-regen path calls the API (costs money we don't have).

## SIGNAL DECISION ORDER (take the FIRST that genuinely applies)
1. Shutdown / wind-down (content_reasoning mentions closure/winding down) → SKIP.
2. design_really_lacking AND reasoning shows amateur/unfinished/broken (not just "competent but generic") → DESIGN lead.
3. content_really_thin AND (genuinely shallow OR content/education/docs/SEO-driven business) → CONTENT lead (CTA = "building the site out").
4. GENUINELY poor speed → SPEED lead, cite the number. GENUINELY poor =
   real_user_load ≥4s OR responsiveness ≥600ms OR desktop ≤50 **with no good real-user load**.
   If real-user load is fine (e.g. desktop 15 but field 1.8s), do NOT lead speed — they'll check and find it fine.
5. WordPress / dated stack → rebuild/migration lead.
6. Strong precinct (recognizable named customers / a hard metric in proof_from_site) → business-inference lead on ONE precinct.
7. Else → LAST-RESORT soft design/refresh (never claim design is lacking; investment-framed).

## MESSAGE 1 SPINE (each beat ONE short line, blank line between; ~45-70 words, proper capitalization)
- Opener: "Hey {first-name}, came across <Company> while looking at <BROAD category>." (AI tools / fintech tools / dev tools / creator tools / health tools / consumer apps ...). NEVER a narrow niche (not "WhatsApp commerce tools").
- Premise → guess: state the FACT (one precinct: names OR a number, never both) then "so I'd guess ...". End the guess POSITIVE (no "not X" tail).
- Which means → opportunity: TWO short lines — why the site carries weight + "and there's room for it to ..." (constructive, never "doesn't quite carry"). Perf lead cites the number here.
- CTA: short, names the action. **Always the "Have you thought about ...?" family — the "Worth a ...?"
  / "Would that be worth a look?" close is BANNED (user rule 2026-08-08; `qa_check.py` BAD_CTA
  enforces it).** Approved openings, rotate them so 400 messages don't close identically:
  "Have you thought about ...?" / "Ever thought about ...?" / "Is ... on your radar?".
  perf→"a rebuild to speed it up?"; content→"building the site out?"; design/precinct→"a refresh to match?".

## CASE STUDY (msg 2) — pick by problem then industry; quote the metric EXACTLY; slug on its own line
- AI / AI-search product → Webless AI (bounce down 20%, animation load down 70%, time on page up 32%) — webless-ai
- Technical / API / developer / infra / enterprise → NewsCatcherAPI (engagement up 3,600%, 20s to 3+ min sessions) — newscatcher
- Two-sided / marketplace / proptech / location → Flatable (95 on PageSpeed, two clear journeys) — flatable
- Creator / artist / media / community / fan / showcase → YourCulture (motion-rich site scoring 97 on Lighthouse) — your-culture
- Premium physical / consumer / ecommerce / Shopify → Wondersimple (sales up over 50% after launch) — wondersimple
- Design-led but slow/fragile OR a clean speed-fix → Studio Artegra (performance up over 25%) — studio-artegra
- Regulated / health / life-sciences / enterprise depth → Amalia (25 of 44 pages built by the client team) — amalia-tech
- Referral / revenue-system / no-dev workflow → F5 Hiring Solutions (a revenue channel on zero engineering overhead) — f5-hiring-solutions
- NEVER use: Lowr, TwoDots, Qmin AI, your360 AI.
- No strong fit → msg 2 WITHOUT a case study (name/url "none"): studio intro + genuine build-on note + soft offer.
- URL base: https://prismport.co/case-studies/<slug>  (lowercase).

## STUDIO INTRO
- tech_stack == webflow → msg 1 says "Webflow certified partner"; msg 2 does NOT reintroduce.
- every other stack (framer/next.js/gatsby/hubspot/custom...) → msg 1 no studio mention; msg 2 opens
  "Hey {first-name}, quick context, we're a design and Webflow studio."
Every message (1,2,3) starts with "Hey {first-name},".

## SECONDARY (msg 2 only, ONE, prefer rarer): ai_invisible_client_rendered > blocks_ai_crawlers > mixed_content > ssl_expires_in_days > ad_cookies_before_consent.
- ad cookies: name the ad PRODUCTS, cookies are "set/loading" (never "fires"/"GTM"), mention GDPR, EU as an EXPLICIT ASSUMPTION ("I'm assuming you'll have EU visitors"), end "quick to sort". Banner true = "banner shows but the X cookies are already set before anyone clicks accept". Banner false = "X cookies loading the second someone lands, before any consent". SKIP for clearly non-EU-market companies (India-only, US-gov, US-dental, LATAM, etc.).
- ai_invisible: "the site renders entirely in the browser, so ChatGPT and Google's AI overviews basically can't read it right now, which only matters more for getting found."
- blocks_ai_crawlers: "your robots setup is currently blocking the AI crawlers, so tools like ChatGPT can't see the site."
- ssl: "your SSL certificate looks set to expire in about <n> days, worth a renew before it lapses."

## THIRD MESSAGE — rotate these 4 ONLY:
A "Hey {first-name}, I'll leave this with you for now. Whenever it feels like the right time, I'd be glad to talk through how we'd approach it."
B "Hey {first-name}, no rush on this at all. If it ever moves up your list, I'm happy to jump on a quick call and show you what we'd do."
C "Hey {first-name}, I'll stop here so I'm not crowding your inbox. Whenever the timing's right for a quick chat, I'm around and happy to help."
D "Hey {first-name}, totally understand if this isn't top of mind right now. It'll keep, so reach out whenever you'd like to dig into it."

## HARD RULES (qa_check.py enforces; must be 0 flags before moving on)
Proper capitalization always ("I", Webflow/GDPR/SEO/ChatGPT/AI/SSL; intentionally-lowercase brands like simplyblock/scite/tapouts/hoo.be/a0/your360 stay lowercase). Only the literal {first-name} token. NEVER invent numbers/customers/funding. NEVER cite a funding amount. No judgment/surprise/fear, no loss framing ("costing/losing"), always gain-framed. No em/en dash. No emojis/exclamations. No jargon (LCP/INP/CLS/WCAG). One precinct only (no name+metric pile). No niche opener. No forced product-verb pun. No "even a small lift adds up". Traffic-scale framing only if traffic_is_high.
**Banned CTA close:** never "Worth a refresh/look/rebuild?" or "Would that be worth a look?" — use the
"Have you thought about ...?" family (see MESSAGE 1 SPINE). Note "you're worth a look" as ordinary prose
mid-message is fine; only the question form is banned.
**Tokens that trip the QA tone/pile checks even when innocent — avoid them:** "judge you", "size up", "scrutin*", "skeptical" (as a visitor), "proving you're", the buzzwords "seamless"/"frictionless", the product words "slow"/"load" inside a NON-performance message (use "quick"/"waiting"), and any "Nx" metric like "5x" (write "fivefold" or a percentage). Also never cite grader placeholder "0x / 0%" stats.

## OUTPUT SCHEMA (each object) — write ALL fields for non-skip.
**Correction (2026-08-08): `assemble` does NOT actually enforce this** — 256 of 594 existing entries
are missing `secondary_point` / `secondary_reasoning` / `case_study_rationale` and assembled fine.
Messages are unaffected, but those review columns are unreliable, so fill them by hand, not by trust.
domain, priority(high|medium|low|skip), signal_category(performance|design|content|accessibility|other),
chosen_signal, angle_rationale, inference, why_it_matters, use_traffic_scale(bool), genuine_positive,
quotable_fact_to_use, secondary_point, secondary_reasoning, case_study_name, case_study_rationale,
case_study_url, first_message, second_message, third_message.  ("none" where truly N/A.)

## FINALIZE (when REMAINING == 0)
1. assemble (step 5) one last time.
2. `LEADS_BATCH=batch_01 MESSAGES_FILE=messages_v3.csv python scripts/outreach_loop/export_complete.py`
   → `messages_v3_complete.csv` (complete sequences only, lean columns). **Review/QA artifact — NOT
   sendable** (domain-keyed, `{first-name}` still literal, no person attached).
3. **The send file:**
   `LEADS_BATCH=batch_01 MESSAGES_FILE=messages_v3.csv OUT_SUFFIX=_v3 python scripts/build_outreach_list.py`
   → `outreach_ready_v3.csv` (one best contact/company + LinkedIn/email, real {first-name} filled in;
   every row passes a completeness gate — name + LinkedIn + all 3 messages, no unfilled token),
   `not_contacted_v3.csv`, `messages_no_contact_v3.csv`, and `outreach_incomplete_v3.csv` if any row
   fails the gate. Contact ranking: marketing > founders > product/sales/comms/tech (see CLAUDE.md).
   ⚠️ **Always pass `OUT_SUFFIX=_v3`** — the bare defaults read `messages_v2.csv` and OVERWRITE the
   live v2 campaign files. Safe to run mid-run; it just uses whatever is written so far.
4. `LEADS_BATCH=batch_01 python scripts/lead_report.py`
5. Report totals + skips + anything worth a human eye (start with case-study concentration).
DONE = every gradeable prospect has a QA-clean 3-message sequence in messages_v3.csv.
