# Message Generator v2 — Two-Pass Plan

Goal: from the audit data, produce a LinkedIn first message + one closing message per
prospect that a founder would actually stop and reply to. We have ~10 seconds to win
attention. Founder-to-founder, candid, specific, real. Conversation-starter, not a pitch.

## 0. Audit-data correctness (prerequisite — DONE)
- `meta-viewport` / "zooming and scaling must not be disabled" rule disabled in
  `accessibility.py` (browsers ignore `user-scalable=no`; it false-positived moescape).
- Existing false zoom flags scrubbed from `a11y_top_issues` in the enriched CSV.
- Caveat to respect downstream: when `a11y_error` is set (e.g. CSP blocked axe injection),
  accessibility was NOT measured — never treat that as "clean / no issues."

## 1. Why two passes (two API calls)
A single call both decides and writes, so it defaults to the loudest/most-common flag
(accessibility fired on ~83% of sites) and writes shallow. Splitting forces a real
decision first, then focused writing.

- **Pass A — Analyst (decide).** Input: the full audit for one site + a dictionary of what
  each field means. Output: a structured judgment of the site's real state and the single
  best thing to open a conversation about. No prose message. Logged to the CSV.
- **Pass B — Writer (write).** Input: only Pass A's decision + the specific facts + the
  voice rules. Output: first message + closing. It does not re-decide; it just writes well.

If Pass A picks accessibility as the angle, run a live axe re-check on that one site before
Pass B uses it (a11y flags go stale — see moescape). If it no longer holds, fall back to
Pass A's second choice.

## 2. Pass A — Analyst: decision logic
Think only as a founder deciding "what's the one thing I'd mention to get a reply." Rank by
how much it would make THIS founder stop, weighing the site's audience/product, not by which
flag is loudest.

Signal priority (default order, override with judgment):
1. **Real-user performance that's genuinely bad** — field metrics only:
   - load slow (`field_lcp` needs-improvement/poor) → "slow to load"
   - laggy (`field_inp` poor) → "laggy when you tap, a beat before it responds"
   - jumpy (`field_cls` poor) → "page jumps around as it loads"
   - If there is NO field data, performance is OFF the table (never use the lab score).
2. **Design clearly weak for the stage/product** (`design_score` low + `design_comment`),
   especially for design-led/creative/visual products where a generic site contradicts the pitch.
3. **Content unclear / thin / low credibility** (`content_score` low + `content_analysis`) —
   visitors can't tell what they do, or claims lack proof.
4. **Accessibility — only when genuinely severe (Pass A's judgment).** Not a default and not a
   last resort. Pass A weighs the actual severity: many critical/serious violations, issues
   that truly block real users, and `a11y_lawsuit_risk` true. If it's genuinely bad, it can be
   THE chosen angle on its own merits; if it's minor, it isn't used. It must also survive the
   live re-check before Pass B writes it (flags go stale). Legal-risk framing only when
   `a11y_lawsuit_risk` is true after re-verification.

Honesty gate: if nothing is a genuinely real hook, mark `priority = skip` and say so.

Traffic-scale gate: only use the "with the traffic you're pulling, even a small slice is a
real number" framing when `monthly_visits` is genuinely meaningful (threshold: >= 10,000/mo,
tunable). Below that, do not lean on scale — find a different, true business benefit (e.g.
credibility with buyers, signups from the visitors they do have, standing out from
competitors). Never invent numbers/percentages/dollars.

Genuine positive: identify one real strength from the data to credit (strong copy, strong
social proof, clear niche, good design). If nothing is genuinely good, no praise.

## 3. Column dictionary the Analyst receives (what each means to a site)
- `Name`, `Description` / `content_analysis` — who they are, what they do.
- `monthly_visits` — audience size; gates the scale framing.
- `tech_stack` — what the site is built on.
- `design_score` (0-100) + `design_comment` — how professional/distinctive it looks; <50 weak.
- `content_score` (0-100) + `content_analysis` — clarity/substance/credibility of the copy; <55 thin.
- `field_lcp` + `field_lcp_rating` — REAL-USER load seconds (good <=2.5, ni 2.5-4, poor >4).
- `field_inp` + `field_inp_rating` — REAL-USER tap responsiveness ms (good <=200, poor >500).
- `field_cls` + `field_cls_rating` — REAL-USER layout shift (good <=0.1, poor >0.25).
- `cwv_pass` — overall real-user pass/fail; decide the WORD from the specific failing metric.
- `pagespeed_mobile` — LAB score, REFERENCE ONLY, never the basis of a claim.
- `a11y_violation_count`, `a11y_critical`, `a11y_serious`, `a11y_moderate`, `a11y_minor` —
  accessibility severity (Pass A judges how bad it really is from these counts).
- `a11y_lawsuit_risk`, `a11y_top_issues` — litigated-rule flag + the specific issues; use only
  when genuinely severe, and re-verify live before writing (flags go stale).
- `a11y_error` — if set, a11y NOT measured (do not treat as clean).
- `tracking_before_consent`, `trackers_detected` — privacy; almost never an opener.
- `letter_grade`, `total_grade_score` — overall snapshot (context only).

## 4. Pass A output (logged to CSV)
- `assessment` — 2-3 sentences: the real state of the site, founder's read.
- `chosen_signal` — the one thing to write about.
- `signal_evidence` — the exact values behind it (e.g. "field_inp 710 = poor").
- `why_it_matters` — the business consequence, in plain terms.
- `use_traffic_scale` — true/false + the visits number.
- `genuine_positive` — what to credit (or "none").
- `priority` — high / medium / low / skip.
- `rejected` — what else was considered and why not (keeps it honest, aids review).

## 5. Pass B — Writer: voice + hard guardrails
Structure: natural reason you were on the site -> the issue + why it costs them (bad news
first) -> the one genuine positive ("that said, X is genuinely good") -> open-ended question
that invites a reply. Closing (msg 2) = soft nudge that mentions the internal tool/report and
offers to share what it found.

Hard rules (enforced in prompt AND post-processing where possible):
- **Name token:** always write the literal `{first-name}`. NEVER invent or vary a name
  (no "Jordan"/"Martin"). Post-process: replace any opener name with `{first-name}`.
- **No em/en dashes or `--`** anywhere (sanitizer strips them).
- **Lowercase, handwritten feel.** No corporate polish, no emojis, no exclamation marks.
- **No jargon.** Translate everything (LCP/INP/CLS/WCAG/etc. -> plain words).
- **Performance claims = field data only**, and the right word per metric (load/lag/shift).
  No field data -> no performance claim.
- **Scale framing only if `use_traffic_scale` is true.**
- **No invented numbers / %, / $.**
- **Accessibility** only if Pass A chose it and it passed the live re-check.
- **Two messages only.** First 60-95 words; closing 25-45.
- **No defensive hedging** ("no agenda/pressure/pitch"). Open question is the close of msg 1;
  the tool/report offer lives only in msg 2.

## 6. CSV output schema (one row per prospect)
`Name, Domain, monthly_visits, letter_grade,` then Pass A fields (`assessment,
chosen_signal, signal_evidence, why_it_matters, use_traffic_scale, genuine_positive,
priority, rejected`), then Pass B fields (`first_message, closing_message`).

## 7. Model / cost
- Gemini 2.5 Pro (good prose; needs `max_output_tokens` headroom ~8k because thinking eats
  the budget) or Claude if a key is added. Two calls x 10 rows = trivial cost.
- Temperature ~0.7-0.85 for natural variety.

## 8. Rollout
1. Build the two-pass function with the above.
2. Run first 10, log decisions + messages.
3. Review the DECISIONS first (is it picking the right signal, varied, honest?), then the prose.
4. Tune prompts, re-run, then scale.
