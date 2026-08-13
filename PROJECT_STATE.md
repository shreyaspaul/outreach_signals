# PROJECT STATE & NEXT STEPS
_Canonical handoff file. Read first each session; update whenever state changes. Survives compaction._
_Last updated: 2026-08-13_

## ⚠️ DIRECTION SET 2026-08-13 — productize the pipeline into a VA-operable web app

The project stops being a script pile. **Target: a deployed web app where a VA uploads a raw CSV and
downloads a send-ready outreach file, touching no terminal.** Nothing is built yet; this session
produced the plan only.

**Plan (read this before building anything):**
- `specs/outreach-app-plan.md` (canonical, editable)
- `specs/outreach-app-plan.html` (same doc, rendered)
- Published artifact: https://claude.ai/code/artifact/994a1223-3d6a-4829-8d7d-5c8677d24518

**Decisions locked this session (user):**
1. **Scope: the FULL pipeline in the app**, upload through send file (not messaging-only).
2. **Hosting: a deployed web app** (server-side jobs, keys on the server, VA logs in remotely).
   Not a local install, not a tunnel to Shreyas's machine.
3. **Send path: export CSV.** Sending stays in the existing LinkedIn tool. The app never drives
   LinkedIn directly (ToS risk), and this is deliberate, not a phase-1 shortcut.
4. **Message generation moves to the Claude API on Opus 5**, superseding both the retired Sonnet 5
   batch path AND the current in-session loop. See "Generation model decision" below.

**What this means for the paused v3 loop:** it is NOT cancelled, but it is now understood as the
manual version of Phase 2. Finishing the remaining 199 by hand is optional; the plan's Phase 2 proof
is generating exactly those 199 unattended through the new service. Decide which route before
resuming, so the work is not done twice.

### Generation model decision (2026-08-13) — Opus 5, and why cost is no longer the driver
- **Use `claude-opus-5`**, `output_config.effort: "high"`, `thinking: {type: "adaptive"}`,
  **structured outputs** (`output_config.format` json_schema over the 18-field result), master prompt
  as a **cached system prefix**, **Batch API** for bulk and realtime for single regenerations.
- **Measured cost from this repo's own files: ~$0.06/prospect, ~$48 per 800-lead batch, ~$24 on the
  Batch API.** Inputs: SKILL.md 44,587 chars, data dictionary 7,625 chars, median bundle 2,194 chars.
- **This supersedes the "Sonnet 5 is the chosen bulk model" finding in CLAUDE.md.** That test was run
  while the org was out of credits, so cost dominated. Against $10-20K deals $24-48 is noise, and the
  Sonnet v2 campaign (795 messages, 0 QA flags) was pulled for quality anyway, so the cheap path cost
  money rather than saving it. Keep Sonnet 5 configurable as a cheap "draft, human curates" mode only.
- **Batch API caveats to build around:** results return out of order (key on `custom_id`, never
  position), and the server-side `fallbacks` parameter is rejected on Batches, so handle
  `stop_reason == "refusal"` locally and requeue on the realtime path.

### The three findings that shape the build (do not lose these)
1. **A stateless per-prospect API call cannot see the batch.** That blindness is what produced 412 of
   594 identical closing lines and one case study carrying 52% of message 2s. The service therefore
   needs three explicit mechanisms: a **diversity budget** injected per request (saturated phrasings +
   case studies at quota, passed in the USER turn so the cached prefix stays intact), a **hard
   case-study quota** (~30% ceiling per batch, deterministic), and a **batch-level repetition lint**
   after generation that flags into the review queue.
2. **The review queue is load-bearing, not a nicety.** v2 was 795 messages at 0 QA flags and was still
   pulled. Regex QA proves absence of banned patterns; it cannot prove a message is good. Nothing
   exports without `status = approved`. Track approve/edit/reject rate per `prompt_version`: that is
   the quality signal for every future prompt change.
3. **Contact sourcing, not writing, is the real bottleneck.** 132 of 594 written messages (22%) have
   nobody to send to, and the mix is 383 founders to 38 marketing because only ~20 marketing titles
   exist in the whole people dataset. More generation does not touch this. A people-enrichment step
   (Apollo/Clay) belongs around Phase 3.

### Session log — 2026-08-13 (planning only, no code changed)
Produced the productization plan. **No pipeline code, data, or message state was touched**, and the
Phase 0 hygiene items below were identified but **NOT done**.
1. Audited the whole pipeline back to first principles and wrote it up as **10 stages** (0 source
   acquisition, which has never existed in code, through 9 post-hoc verification), with each stage
   mapped to what it becomes as a queued job.
2. Named **4 structural blockers** to handoff, each tied to an incident that already happened here:
   the 219-column CSV acting as the database (no primary key, hence the overwrite incident, the 11
   `.bak` files, and the resurrected dead rows); env-var operations where forgetting one variable
   overwrites the live campaign; generation being a person in a terminal; and the master prompt being
   gitignored on one disk.
3. Specified the target architecture: FastAPI + Postgres + Redis worker, idempotent per-company tasks
   keyed `(batch_id, domain, stage)` so resume is free, a 9-table schema, per-provider rate limiters,
   and a 4-screen VA surface (Batches / Run / **Review queue** / Export).
4. Specified the generation service in detail (request shape, caching, diversity mechanisms, QA gate
   with one bounded regeneration then human review, cost model). See the decision block above.
5. Set the reuse boundary: **all grader modules, `case_studies.py`, `qa_check.check()` and
   `score_person()` move as libraries, unchanged.** `score_person()` specifically goes **verbatim with
   its tests**, because a scoring change once silently swapped 45 CEOs for CTOs.
   Rewritten: `orchestrator.py`, all CSV I/O, `prep_bundles.py`, the file-emitting half of
   `build_outreach_list.py`, `generate_messages_api.py`. Retired: `finish_batch.py`,
   `model_swap_test.py`, `build_comparison_csv.py`, `broaden_openers.py`, `fix_case_studies.py`, the
   Gemini path in `message_generator.py`, the `PILOT_*.md` files.
6. Wrote `specs/outreach-app-plan.md` and `specs/outreach-app-plan.html`, and published the artifact.

### Session log — 2026-08-13 (later) — Phase 0 DONE: everything committed, repo made hygienic

Two commits. The first is a verbatim backup (**nothing had been committed since 9 Jul**), so the
cleanup in the second cannot lose anything.

1. **Backup commit (now `db3600e` after the history rewrite below)** — all uncommitted work as-is: `scripts/outreach_loop/`, 14 new
   scripts, `Copy/`, `PROJECT_STATE.md`, `specs/outreach-app-plan.{md,html}`, and 9 modified scripts.
   **Force-added past the `data/` gitignore because it had no backup at all:**
   `message_results_v3.json` (the 594 hand-written messages), `messages_v3{,_complete}.csv`,
   `outreach_ready_v3.csv`, `not_contacted_v3.csv`, `messages_no_contact_v3.csv`,
   `skipped_shutdowns.json`, `signal_verdicts.json`, and the `PILOT_*`/`DESIGN_CHECK` review docs.
   Excluded `screenshots_recheck/` (380MB of regenerable PNGs) and added `screenshots_*/` to
   `.gitignore` — committing it would have bloated the repo permanently.
2. **`SKILL.md` was already tracked**, contrary to what CLAUDE.md and memory both claimed. It was
   force-added at some earlier point. It is in git and now committed. The "gitignored, unbacked on
   one disk" warning is **obsolete** — do not act on it.
3. **Hygiene commit** — see the repo layout note below. `next_bundles.py` now excludes
   `skipped_shutdowns.json`; verified: `WRITTEN: 594 | SKIPPED: 4 | REMAINING: 195`. Also defused 5
   fake sample credentials in `specs/cloud-deployment-spec.md` (`xoxb-1234…`, `AIzaSy…`) that were
   tripping GitHub push protection — they were always placeholders, nothing to rotate.
4. All live modules verified importable after the moves. (`finish_batch.py` cannot be imported, but
   that is pre-existing: it reads `sys.argv[1]` at module level.)

### Session log — 2026-08-14 — history rewritten to unblock the push; everything now on GitHub

GitHub push protection rejected the push over a **fake** Slack token
(`xoxb-1234567890-1234567890123-…`) in an "Appendix B: Sample Environment Variables" block in
`specs/cloud-deployment-spec.md`, present since commit `0a221be` (16 Jun). It was always a
placeholder sitting next to an equally fake `AIzaSyAaBbCc…` — **no credential was ever exposed and
nothing needed rotating.** The allow-secret link GitHub prints returned 404.

Resolved by rewriting history rather than bypassing the check. **This was safe because every
affected commit was unpushed** — `origin/main` (`f9e6e68`) is an ancestor of all 9, and no remote ref
contained any of them, so no collaborator held those SHAs and no force-push was needed.

- Took a verified full backup first: `../outreach_signals_backups/pre-rewrite-2026-08-14.bundle`
  (26MB, `git bundle verify` reports a complete history). **Same disk — it is a rollback, not an
  off-machine copy.** Safe to delete now that the push succeeded.
- `git filter-branch --tree-filter` over `--all ^f9e6e68` (11 commits), replacing 5 placeholder
  credentials with `<angle-bracket>` names. Then dropped `refs/original/`, expired the reflog and
  gc'd, so the old objects are gone rather than merely unreferenced.
- Verified after: zero of the 14 reachable commits contain the string; `origin/main` still an
  ancestor of HEAD (no divergence); `message_results_v3.json` (1,307,311 bytes), `messages_v3.csv`,
  `outreach_ready_v3.csv` and `SKILL.md` (44,587 bytes) all byte-intact in the rewritten backup commit.
- **All local SHAs changed.** Backup commit `3c7fcb8` → `db3600e`; hygiene `0319dec` → `2145c54`;
  `main` and `chore/cleanup-data-dirs` → `1d97e17`. Any SHA written in an older note is stale.
- Pushed `outreach-sonnet-batch-pipeline` to origin; local and remote tips match at `2145c54`, and
  the v3 message data, SKILL.md, RUN_LOOP.md and the plan are all confirmed present on the remote.
- **Not done:** `main` is still 3 commits ahead of `origin/main`. It is a clean fast-forward whenever
  you want it (`git push origin main`); left alone because those commits' content is already on the
  remote inside this branch, so nothing is at risk.

### Repo layout after the 2026-08-13 cleanup
- **Root holds 4 docs only**: `README.md`, `CLAUDE.md`, `PROJECT_STATE.md`, `SIGNALS.md`.
- **`docs/_archive/`** — 5 superseded outreach docs from 16 Jun (`MESSAGE_TEMPLATES.md`,
  `LINKEDIN_OUTREACH_STRATEGY.md`, `OUTREACH_README.md`, `OUTREACH_SUMMARY.md`,
  `IMPLEMENTATION_GUIDE.md`). **Do not follow them** — they describe segment templates and
  pain-point framing, both of which current practice explicitly reverses. `docs/_archive/README.md`
  says why, per file.
- **`scripts/_archive/`** — 11 one-off scripts, none imported by anything, with a README explaining
  each. `model_swap_test.py` and `build_comparison_csv.py` are in there because their conclusion
  (Sonnet 5) was reversed.
- **`generate_messages_api.py` stayed in `scripts/`** even though CLAUDE.md calls the path retired:
  `qa_check.py`, `finish_batch.py`, `fix_case_studies.py` and 2 others import `load_env`,
  `extract_json` and `backstop_case` from it. Moving it breaks QA. Do not "clean it up".
- **`data/batch_01/_archive/`** — the 10 `.bak` intermediates, moved off the working path but kept
  on disk (still gitignored, so they are NOT in git; that is deliberate, they are 17MB of duplicates).

## ⚠️ CURRENT WORK (now = Phase 2 of the plan) — v3 messages, loop PAUSED at 594/793

The first campaign was pulled for quality. We rebuilt the whole messaging system (rules below) and
are regenerating every gradeable prospect fresh. **The Anthropic API is OUT OF CREDITS** (org went
to ~-$28.58; the earlier Opus Batch job `msgbatch_016…` is dead/uncollectable — do NOT rely on it or
on `generate_messages_api.py`). So generation now happens **in-session: Claude writes each 3-message
sequence directly, no API call.**

### Where we are (2026-08-08)
- **594 of 793 gradeable prospects written and QA-clean (0 flags). 199 remaining.**
  (The loop ran to 598 on 2026-07-21; on 2026-08-08 we removed the 4 dead entries — see below — so
  the written count is now 594 real sequences with no placeholder rows.)
- Output (live `_v2` campaign files untouched, verified by checksum):
  - `data/batch_01/message_results_v3.json` — all 3 messages + reasoning per prospect (the loop's store)
  - `data/batch_01/messages_v3.csv` — 594-row, 23-col review CSV
  - `data/batch_01/messages_v3_complete.csv` — 594-row lean message text, **review/QA only, not sendable**
  - **`data/batch_01/outreach_ready_v3.csv` — 462 rows, THE SEND FILE** (contact + LinkedIn + real
    names filled in). Regenerate it after each loop cycle; see the session log for the command.
- The run was **paused** by the user 2026-07-21 ~07:22; it resumes cleanly at the next unwritten
  prospect (currently `maesn.com`).
- Composition so far: priority 402 high / 191 medium / 1 low. Signal lead: `other` 341, design 148,
  content 80, performance 29 — i.e. **~57% rest on business-inference rather than a hard signal**
  (the decision order working as designed, but worth a human eye).
- Case-study concentration: **NewsCatcherAPI 311 (52%)** + Webless AI 174 = 81% of all msg-2s.
  Defensible on a dev-tool/SaaS-heavy list, but Flatable (17) / Wondersimple (9) / Studio Artegra (7)
  are barely used. **Review before sending in tight industry clusters.**

### Session log — 2026-08-08 (cleanup + first export)
1. **Removed the 4 dead entries** from `message_results_v3.json` (598 → 594). Three had blank
   messages (`www.kovadx.com`, `www.huxe.com`, `skarbe.com` — shut down / winding down); the fourth,
   **`ftx.com`, had the literal string `"SKIP"` in all three fields** (now a bankruptcy claims portal),
   which a blanks-only check misses and which would have shipped as a message reading "SKIP".
   - Backup: `message_results_v3.json.pre-skipremoval.bak`
   - Removed entries + their skip reasoning quarantined in **`data/batch_01/skipped_shutdowns.json`**
2. Re-ran `assemble` (594 rows) and `qa_check.py` report-only → **0 flags**.
3. **New: `scripts/outreach_loop/export_complete.py`** — re-runnable lean export of the MESSAGE TEXT
   for prospects with a COMPLETE 3-message sequence (non-blank, not `"SKIP"`) → `messages_v3_complete.csv`.
   Verified all 594 carry the `{first-name}` token. **This is a review/QA artifact, not a send file**
   (domain-keyed, no person attached).
   ```bash
   LEADS_BATCH=batch_01 MESSAGES_FILE=messages_v3.csv python scripts/outreach_loop/export_complete.py
   ```
4. **Fixed `build_outreach_list.py` + built the real v3 send list.** The script is now parameterized
   (`MESSAGES_FILE` input, `OUT_SUFFIX` on all three outputs); defaults unchanged so a bare run still
   reproduces v2. Ran it for v3 and **confirmed by checksum that the v2 files were untouched**:
   ```bash
   LEADS_BATCH=batch_01 MESSAGES_FILE=messages_v3.csv OUT_SUFFIX=_v3 python scripts/build_outreach_list.py
   ```
   - **`data/batch_01/outreach_ready_v3.csv` — 462 companies. THIS IS THE SEND FILE.** One best contact
     each, with `Full Name` / `first_name` / `last_name` / `Title` / `Person LinkedIn` / `Work Email` /
     company fields, and the real name substituted into all three messages (0 rows still holding the
     `{first-name}` token). Coverage: LinkedIn 462/462, first name 462/462, last name 459/462 (3
     mononyms), work email 427/462 (35 rows carry the literal `"No email"` from the source data —
     filter those if emailing; LinkedIn DM is unaffected). Priority: 318 high / 143 medium / 1 low.
   - **Contact mix is founder-heavy: 38 marketing / 383 founder / 41 other.** The marketing-first rule
     barely fires because the people data holds only ~20 marketing/growth/brand titles across the whole
     list — a sourcing gap, not a scoring bug. Fine for founder-led companies; worth knowing for tone.
5. **Revised the contact ranking to the user's rule + hard completeness gate** (`build_outreach_list.py`):
   - **Three strict tiers, no interleaving:** (1) marketing/website owner — core marketing/brand/growth
     > digital/content/web/SEO — at any seniority; (2) founders; (3) the rest — product/design > sales
     > comms/PR/social > tech. **Comms/PR/social moved from tier 1 to tier 3.** A comms title still
     counts as tier 1 only if it carries a real marketing/brand remit ("Head of Brand & Communications").
   - ⚠️ **Trap found while doing this:** flattening tier 2 to `200 + seniority` made every founder tie,
     and the alphabetical tie-break silently swapped **45 CEOs for CTOs** — the worst reader for a
     website pitch. Fixed by keeping the role-affinity term inside tier 2, so CEO (240) > CTO (232) and
     a product-founder (252) > CEO. **Verified 0 pick churn vs the previous ranking.** If you touch
     `score_person()`, diff the chosen contacts before/after — the score alone won't show this.
   - **A LinkedIn URL is now required** to be eligible at all (it's the outreach channel; also stops
     `drop_duplicates` collapsing blank-LinkedIn people, since pandas treats NaNs as equal).
     **Work email is NOT required** — outreach is LinkedIn DM. 427/462 have one; 35 carry the literal
     `"No email"` from source, which is fine and no longer filtered on.
   - **Final completeness gate:** every send row must have a name, first name, LinkedIn, all three
     messages, and no unfilled `{first-name}`. Failures go to `outreach_incomplete_v3.csv` — currently
     **0 rows dropped**, and the send file shares **0 domains** with `messages_no_contact_v3.csv`.
   - `not_contacted_v3.csv` — 509 runner-up contacts at those same companies (manual-override pool).
   - **`messages_no_contact_v3.csv` — 132 written messages with NO contact in the people data.**
     That's 132 of 594 (22%) currently unsendable; they need contact sourcing, not rewriting.

6. **Banned the "Worth a ...?" CTA close and swapped all 420 instances** (user rule — they dislike it).
   Deterministic string replacement, no LLM/API. Was **412 of 594 first messages (69%) closing with the
   identical line** "Worth a refresh to match?", so this fixed a major repetition problem too.
   - Rotated 4 house phrasings instead of one, all already present in our own messages:
     "Have you thought about giving it a refresh to match?" (151) / "Ever thought about a refresh to
     match?" (111) / "Have you thought about a refresh to match?" (103) / "Is a refresh to match on your
     radar?" (103). To make it a single phrase, edit the rotation and re-run.
   - **Enforced in `qa_check.py` `BAD_CTA`** so the remaining 199 can't reintroduce it. The rule only
     fires on the QUESTION form — "decides you're worth a look." as prose is legitimate and not flagged.
   - The QA gate then caught **13 more** the closing-line swap alone missed: 2 over the 82-word cap
     (`blacktag.com` 85, `geosimple.ai` 83 — the new CTA is longer; gave them the shorter
     "Is a refresh on your radar?"), 6 using "Would that be worth a look?" mid-message, and 1 false
     positive that led to tightening the regex. All hand-fixed — **never `qa_check --fix`** (paid API).
   - Verified after: **0 QA flags**, 0 message bodies altered above the CTA line, 0 second/third
     messages touched, 462 send rows with 0 "Worth a" remaining.

### ⚠️ OPEN ISSUES found 2026-08-08 (none blocking, all unfixed)
- **`next_bundles.py` will re-serve the 4 removed domains.** It derives "already written" purely from
  domains present in the results file, so REMAINING went 195 → 199 and the loop will hand you FTX +
  3 dead startups to write. **Fix before resuming:** have it also exclude domains in
  `skipped_shutdowns.json`. (Reasoning is preserved there, nothing lost.)
- ~~**`build_outreach_list.py` hardcodes `messages_v2.csv`**~~ **FIXED 2026-08-08** — see the session
  log below. It now reads `MESSAGES_FILE` and names its outputs with `OUT_SUFFIX`. **The defaults still
  point at v2 and overwrite the live v2 files, so always pass `OUT_SUFFIX=_v3`.**
- **`assemble` does NOT enforce the 18-field schema** (RUN_LOOP.md claims it "refuses otherwise").
  256 of 594 entries are missing one or more of `secondary_point` / `secondary_reasoning` /
  `case_study_rationale`. No message text is affected — all three messages are intact on every row —
  but those review columns are unreliable.
- **Nothing has been committed since 2026-07-09** (`23f138d`). ~17 modified files (incl. a heavily
  reworked `qa_check.py`, a 366-line SKILL.md diff) + all of `scripts/outreach_loop/`, `PROJECT_STATE.md`,
  `case_studies.py`, `analyze_site.py`, `site_crawler.py` untracked. **The SKILL.md is gitignored, so
  the master prompt exists only on this disk — force-add it.**

### How to RESUME (the only supported path — no API)
Everything lives in **`scripts/outreach_loop/`** (permanent — but **still untracked**, see OPEN ISSUES):
- `RUN_LOOP.md` — the operating playbook: per-cycle procedure + the fast signal/case-study/secondary
  heuristics converged on during the run. **Read it before writing any messages.**
- `next_bundles.py N` — prints the next N *unwritten* prospect bundles (reads results file to know
  what's done; hands only what's left, so no dupes/gaps). **See OPEN ISSUES — needs the
  `skipped_shutdowns.json` exclusion before resuming.**
- `merge_results.py chunk.json` — merges a chunk Claude wrote into `message_results_v3.json`.
- `export_complete.py` — lean send-ready export of complete sequences only → `messages_v3_complete.csv`.
  Re-run after each cycle to refresh what the outreach tool imports.

Per cycle: `next_bundles.py 16` → Claude writes a `chunk.json` (schema in RUN_LOOP.md, following
SKILL.md rules) → `merge_results.py chunk.json` → `prep_bundles.py assemble … -o messages_v3.csv` →
`qa_check.py` (**report only — NEVER `--fix`, its regen path calls the paid API**). Hand-fix any flag,
re-assemble, re-check. Can be driven manually chunk-by-chunk or via `/loop`.

### NEXT STEPS (rewritten 2026-08-13 for the productization direction)

**PHASE 0 — ✅ DONE AND PUSHED (2026-08-14).** Everything is committed and **on GitHub** at
`origin/outreach-sonnet-batch-pipeline` (tip `2145c54`). SKILL.md confirmed tracked and pushed,
`next_bundles.py` now excludes the 4 shut-down domains. See the session logs and the repo layout note
above. Nothing here is outstanding.

**Build toolkit decided (2026-08-14):** which Claude skills we build this with is recorded in
**`specs/build-toolkit.md`** — 5 shortlisted (`claude-api`, `skill-creator`, `frontend-design`,
`webapp-testing`, `checkpoint`), the rejected ones with reasons, and 3 custom skills we must write
ourselves (`stage-task`, `message-rules`, `batch-lint`). Key finding: **no existing skill anywhere
covers durable job state / idempotent tasks / resumability**, which is the top robustness concern.

**⚠️ Stage 4 root cause was MISDIAGNOSED — corrected 2026-08-14.** Both the plan (§Stage 4) and the
[[outreach-bundle-evidence-gap]] memory say the bundle drops evidence that sits in `content_reasoning`.
Measured against the real data, that is wrong: `content_reasoning` is filled 793/793 but is **grader
opinion**, carrying a hard number in only **2 of 793**. The evidence is in `proof_from_site`, which is
**already in the bundle** (782/793, median 429 chars, with real quotes). The defect is its *shape* —
it reads as commentary about the webpage ("The content moves beyond mere naming by providing … like
'Collectors using Aktos touch 3.5x the accounts per day'"), so the fact's grammatical subject is "the
content", not the company. The data dictionary even instructs the model to "ignore any scoring or
opinion framing", i.e. **we pushed an extraction job into the writing prompt** and re-ran it 793
times. Meanwhile `proud_facts`, the clean atomic extractor that outputs exactly what we want ("trusted
by Google, Adobe, Microsoft, Amazon, Notion, and Facebook"), ran on **13 of 1000 rows** and was never
backfilled. **Fix:** evidence extraction becomes its own stage with typed rows
(`{type, value, exact_quote, source_url}`) before generation. `scripts/_archive/extract_facts.py` is
the existing backfill and needs to come back out of the archive.

**THEN, decide the fork before doing more writing:**
1. **Either** finish the remaining **195** by hand through the existing loop (see RESUME below),
   **or** build Phase 1 + 2 of the plan and let the service generate those 195 as its proof. Do not
   do both. Recommendation in the plan: build, because the 195 are the natural acceptance test.
2. **Phase 1: schema, import, export.** Proof of correctness is a diff, not a demo: import the
   existing `batch_01` files, re-export, and confirm **zero rows differ** from `outreach_ready_v3.csv`.
3. **Phase 2: generation service, QA, review queue.** Includes **bundle v2** (carry the customer names
   and hard metrics from `content_reasoning`, not just grader opinion). See
   [[outreach-bundle-evidence-gap]].
4. **Phase 3: enrichment as jobs.** Blocked in practice until the **Gemini account is on paid
   billing** (free tier is 20 req/day, roughly 10 sites/day). Add people-enrichment here to close the
   22% no-contact gap.
5. **Phase 4: the VA shell** (auth, dashboard, progress board, error surfacing), then deploy.

**Still true regardless of route:** the 462 rows in `outreach_ready_v3.csv` are sendable now, and the
case-study concentration (NewsCatcher at 52%) still wants a human eye before any of it goes out.

**Sending mid-run is fine** — `outreach_ready_v3.csv` is regenerated from whatever is written so far,
so the 462 currently sendable can go out while the loop finishes the rest.

### The messaging system (source of truth = `.claude/skills/generate-outreach/SKILL.md` + `qa_check.py`)
The SKILL prompt sits under the gitignored `.claude/` but is **force-added and tracked** (verified and
committed 2026-08-13). `scripts/outreach_loop/RUN_LOOP.md` mirrors the operational rules. In brief:
- **Reasoning spine** (the anatomy): `fact → so I'd guess → which means (the room to improve) → so a
  short forward CTA`. Each beat ONE short line, ~45-70 words, effortless. [[outreach-reasoning-spine]]
- **Signal decision order:** (1) SKIP shutdowns; (2) genuinely-lacking design (read reasoning, not the
  score — design_score is noise, 78% pile ~50); (3) genuinely-thin content (esp. content/education
  businesses); (4) **genuinely** poor speed = real-user load ≥4s / tap ≥600ms / desktop ≤50 **with no
  good real-user load** (if field load is fine, do NOT lead speed — you'll get caught); (5) WordPress
  rebuild; (6) strong precinct (named customers / a hard metric) → business inference; (7) last-resort
  soft refresh. See [[outreach-signal-decision-order]], [[outreach-performance-gate]].
- **Case study (msg 2) must PROVE msg 1's pitch** — match on the problem, quote the real metric exactly.
  8-study registry in `scripts/case_studies.py`. **Never cite Two Dots, Lowr, Qmin AI, your360 AI.**
  See [[case-study-selection-rule]], [[excluded-case-studies]].
- **Hard bans** (SKILL + qa_check): funding amounts, "…not cold search" tails, niche openers, placeholder
  0x/0% stats, "even a small lift adds up", piled proof (name+metric), forced product puns, negative-gap
  framing, **the "Worth a ...?" / "Would that be worth a look?" CTA close (2026-08-08 — use the
  "Have you thought about ...?" family and rotate the phrasing)**. Plus QA-tripping tokens to avoid even when innocent: "judge you / size up / scrutin* /
  skeptical / proving you're", buzzwords "seamless/frictionless", "slow/load" in a non-perf message,
  and "Nx" metrics (write a percentage or "fivefold"). [[outreach-message-dont-list]]
- Message opens `Hey {first-name},` (literal token, substituted downstream — never hard-write the name).

### qa_check.py — the standing safety net
`python scripts/qa_check.py` (report; `--all` default or `--domains a.com,b.com`). Flags every banned
pattern + the perf-gate + casing/mechanics. **Only run without `--fix`** now (no API). Fix this session:
the SPEED regex is `\b`-anchored so it no longer false-flags "download"/"downloading".

---

## ENRICHMENT / GRADING STATE (stable — the dataset the messages are built on)
All ~999 Crunchbase rows enriched + graded + flagged. **`data/batch_01/enriched_ALL_999.csv`** is THE
consolidated file (999 rows, ~219 cols, fresh `apify_*` traffic, `outreach_priority`). Real grades
**795** | INVALID **155** | dead **49**. Gradeable outreach pool ≈ **793** (what we're messaging).
- `prep_bundles.py dump` builds `data/batch_01/message_bundles_all.json` (per-prospect audit + flags +
  reasoning + `first_name`, 631/793 have a name) — the input the loop reads. **Re-dump after any
  `build_prospect`/`prep_bundles` change** (it's a cached artifact).
- Grading pivoted to objective signals (ai_readiness, security/SSL, page_signals, a11y, page_gate).
  content_score is reliable (spreads); design_score is NOT (read `design_reasoning`).
- `report_ALL_999.md` = batch overview. `invalid_entries.csv` = no-grade rows. Convention: after any
  full-list grading, run `scripts/generate_report.py <enriched.csv> -o data/report_<stem>.md`.

## GOTCHAS
- The `/generate-outreach` SKILL.md is gitignored → not in version control; back it up / force-add.
- Message-2 case-study metrics must be real (registry in `scripts/case_studies.py`); `verify_case_studies.py` audits.
- Graders use Gemini (needs prepaid balance); message generation now uses NO API (Claude in-session).
- Read/write enriched CSVs via `grader_fields.read_annotated_csv`/`write_annotated_csv` (they carry a legend row).
- `scripts/_token_log.py` is a real dependency (website_grader/page_gate/content_extractor import it).
