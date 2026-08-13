# Outreach Signals — Productization Plan

_From a pile of scripts to a handoff-ready web app a VA can run end to end._
_Written 2026-08-13. Target: VA uploads a raw CSV, downloads a send-ready outreach file._

---

## 0. The decision that shapes everything

**Scope:** full pipeline in the app — upload → enrich → grade → generate → QA → review → contact-match → export.
**Hosting:** deployed web app (server-side jobs, VA logs in from anywhere).
**Send path:** export CSV, sending happens in the existing LinkedIn tool.

---

## 1. What we actually built — the honest stage inventory

Reconstructed from the repo, not from memory. Nine stages, of which about six are production and three are archaeology.

### Stage 0 — Source acquisition (manual today)
Two independent inputs that must be joined later on domain:
- **Company list** — Crunchbase export (`crunchbase.csv`, 999 rows): `Domain`, `Name`, `Industry`, `Country`, `Description`, `Founder`, funding columns, and stale SimilarWeb traffic columns.
- **People list** — `Person_details_enriched0-1000_batch{1,2}.csv`: name, title, LinkedIn URL, work email, company website.

There is no step in the codebase that produces either. The VA will have both as files, so **two uploads on one screen** is the right shape.

### Stage 1 — Normalize
`scripts/column_utils.py` auto-detects the website/company/traffic columns across CSV shapes. Domain normalization (`norm_domain`) is reimplemented in three files (`build_outreach_list.py`, `prep_bundles.py`, `qa_check.py`). One canonical normalizer, one canonical domain key.

### Stage 2 — Enrichment fan-out (per company) — all the cost, all the flakiness
| Module | What it does | External dependency |
|---|---|---|
| `wordpress_detector.py` | tech stack (25+), marketing tools, ad pixels | HTTP fetch |
| `pagespeed_checker.py` | mobile + desktop lab scores **and CrUX field data** | Google PageSpeed API |
| `traffic_checker.py` / `apify_traffic_refresh.py` | fresh SimilarWeb → `apify_*` columns | Apify (paid) |
| `content_extractor.py` | Jina Reader → markdown → error-page detection → programmatic score (0–30) + LLM ratings (0–70) + `content_reasoning` | Jina + Gemini |
| `website_grader.py` | Playwright screenshot → Gemini Vision design score + `design_reasoning` | Playwright + Gemini |
| `ai_readiness.py` | SSR vs client-rendered, AI-crawler blocking | HTTP + render |
| `security_check.py` | SSL expiry, mixed content | HTTP/TLS |
| `page_signals.py` | ad/analytics cookies set before consent | render |
| `accessibility.py` | axe violations by severity | render |
| `page_gate.py`, `grader_fields.py` | gating + derived fields | — |
| `flag_checker.py` | 20+ data-quality flags per row | — |

`orchestrator.py` drives all of this **sequentially, one company at a time**, with a 1.5s delay, saving every 5 rows, and an interactive resume prompt. Running 999 rows took days and several hand-driven repair passes (`needs_reaudit.csv`, `recheck_performance.py`, `detect_site_changes.py`, `adjudicate_unsure.py`, `verify_signal_live.py`).

### Stage 3 — Grade and gate
`grader_fields` produces `overall_grade` (A+…F / INVALID). Result on batch_01: **999 rows → 795 graded, 155 INVALID, 49 dead → gradeable pool 793.** `add_priority_flag.py` adds `outreach_priority`. `generate_report.py` writes the batch overview; `lead_report.py` writes the funnel CSV.

### Stage 4 — Evidence bundles
`prep_bundles.py dump` → `message_bundles_all.json`: per-prospect audit bundle + a shared data dictionary + `first_name` (present for 631 of 793). Median bundle is 2,194 characters.

> ⚠️ **Known defect, already diagnosed:** the bundle feeds grader *opinion* (`design_score`, `design_reasoning`) and drops the *evidence* — named customers and hard metrics that sit fully populated in `content_reasoning`. This is the recorded root cause of weak, repetitive messages. Fixing the bundle is probably worth more than any model choice.

### Stage 5 — Message generation — the stage with no automation story
- **v1** — Gemini two-pass. Abandoned on quality (kept as dead code in `message_generator.py`).
- **v2** — Sonnet 5 via the Message Batches API (`generate_messages_api.py`). All 795 generated, `qa_check` reported **0 flags** — and **the campaign was pulled for quality anyway.** Also shipped a silent batch-mode defect: ~135 of 359 messages dropped the msg-2 opener, and case-study URL slugs got capitalized into 404s.
- **v3** — Claude writing in the terminal session, 16 prospects per cycle (`scripts/outreach_loop/`). **594 of 793 written, paused since 2026-07-21.** Output: `message_results_v3.json` → `messages_v3.csv` → `outreach_ready_v3.csv` (462 rows).

### Stage 6 — QA
`qa_check.py` — roughly twelve regex rule families: niche openers, placeholder `0x/0%` stats, "even a small lift" scale framing, the banned `Worth a …?` CTA, speed words inside a non-performance message, funding amounts, brand casing, mechanics, `tone_flag`, case-study validity, the performance gate. Flags split into deterministic-fixable (`mech:*`, `case:*`) versus needs-regeneration. Standing rule: **never `--fix`** — that path calls the paid API.

### Stage 7 — Contact resolution
`build_outreach_list.py`: join the people CSVs on normalized domain → `score_person()` three-tier ranking (marketing/website-owner > founders > everyone else, with role affinity inside each tier) → one contact per company → substitute the real first name into all three messages → completeness gate. Outputs `outreach_ready`, `not_contacted`, `messages_no_contact`, `outreach_incomplete`.

### Stage 8 — Export
462 sendable rows of 594 written. **132 (22%) have no contact at all.**

### Stage 9 — Post-hoc verification
`verify_case_studies.py` (msg-2 metric traces to a real study), `verify_signal_live.py`, `detect_site_changes.py`.

### Parallel vertical (out of scope for v1)
`site_crawler.py` + `analyze_site.py` + the `analyze-site` skill: single-company deep business report. Shares the crawl/extract/grade primitives, so it can ride the same job infrastructure later.

---

## 2. Why this cannot be handed to a VA as-is

Four structural blockers. Each one already caused a real incident in this project.

**1. A 219-column CSV is the database.**
Every stage reads and rewrites the whole file. What that produced: `build_outreach_list.py` silently overwrote the live v2 campaign until it was parameterized; eleven `.bak` files in `data/batch_01/` are the versioning system; `assemble` doesn't enforce its 18-field schema, so 256 of 594 rows are missing review columns; deleting 4 dead rows made `next_bundles.py` resurrect them, because "already written" is derived from presence in a JSON file rather than from a state column. None of these are logic bugs — they're what happens without a primary key and a status field.

**2. Operations are environment variables, and getting them wrong is destructive.**
The working command today is
`LEADS_BATCH=batch_01 MESSAGES_FILE=messages_v3.csv OUT_SUFFIX=_v3 python scripts/build_outreach_list.py`
and the documented consequence of forgetting one variable is overwriting the live campaign. `qa_check.py --fix` spends money. That is not a surface you hand to someone else.

**3. The generation step is a person in a terminal.**
594 messages exist because Claude wrote them 16 at a time across two sessions, with the user correcting mid-run — the `Worth a …?` ban landed at message 412 and required a 420-instance string replacement afterwards. There is no unattended path to message 595.

**4. The prompt is not in version control.**
`.claude/skills/generate-outreach/SKILL.md` — 44.5 KB, and the actual product — is gitignored and lives on one disk. The same rules are partially restated in `RUN_LOOP.md` and re-encoded as regexes in `qa_check.py`. Three copies that can drift, one of them unbacked.

---

## 3. Target architecture

### 3.1 What the VA sees — four screens

1. **Batches** — list of campaigns, status, counts, cost to date. "New batch."
2. **Run** — upload company CSV + people CSV; a stage-by-stage progress board (Normalize → Enrich → Grade → Generate → QA → Contacts → Export) with live counts, failures, and a running cost meter.
3. **Review queue** — *the screen that matters.* One card per prospect: evidence bundle on the left, the three messages on the right, QA flags inline, buttons: **Approve / Edit / Regenerate / Skip**. Filters by QA flag, signal category, priority.
4. **Export** — download the send file plus the exclusion lists, with a one-screen summary (sendable / no-contact / rejected / skipped).

### 3.2 What runs behind it

- **FastAPI + Postgres + Redis/RQ worker.** Deployed (Render, Fly, or Railway). Keys live in server env, never on the VA's machine.
- **Every stage is an idempotent per-company task**, keyed `(batch_id, domain, stage)` with its own status row. Resume becomes a property of the system rather than a hand-written feature; `orchestrator.py`'s resume logic gets deleted.
- **Per-provider rate limiters** (token buckets in the worker): Gemini, Jina, PageSpeed, Apify, plus a bounded Playwright browser pool (3–5).

### 3.3 Data model

```
batches      (id, name, created_at, status)
companies    (id, batch_id, domain, name, source_row jsonb)      -- UNIQUE(batch_id, domain)
enrichment   (company_id, stage, status, payload jsonb, error, cost_cents, updated_at)
people       (id, batch_id, domain, full_name, title, linkedin, email, raw jsonb)
messages     (id, company_id, version, m1, m2, m3, signal_category, chosen_signal,
              reasoning jsonb, model, prompt_version, status, qa_flags jsonb)
contacts     (company_id, person_id, rank_score, chosen bool)
prompts      (id, name, version, body, created_at)
exports      (id, batch_id, created_at, row_count, file_path)
```

`messages.status ∈ draft | flagged | approved | rejected`. **Nothing exports without `approved`.**
The 219 columns become ~25 typed columns (everything any downstream code actually reads) plus jsonb for the rest.

### 3.4 What gets reused vs. rewritten

**Reused as libraries, unchanged:** `content_extractor`, `website_grader`, `wordpress_detector`, `pagespeed_checker`, `ai_readiness`, `security_check`, `page_signals`, `accessibility`, `page_gate`, `grader_fields`, `case_studies`, `qa_check.check()`, and `build_outreach_list.score_person()` **verbatim** — that function has a documented trap where a scoring change silently swapped 45 CEOs for CTAs, so it moves as-is with its tests.

**Rewritten:** `orchestrator.py` (replaced by the queue), all CSV I/O, `prep_bundles.py` (becomes a DB query), the file-emitting half of `build_outreach_list.py`, and `generate_messages_api.py` (replaced by the generation service below).

**Retired:** `finish_batch.py`, `model_swap_test.py`, `build_comparison_csv.py`, `broaden_openers.py`, `fix_case_studies.py`, the Gemini path in `message_generator.py`, the `PILOT_*.md` files.

---

## 4. The generation service — the crux

### 4.1 What actually made in-session generation good

It was not only the model. Four things, and each needs an explicit mechanism in the service or the app regresses straight back to v2 — which was QA-clean and still got pulled.

| What worked in-session | Mechanism in the service |
|---|---|
| Deep per-prospect reasoning through the signal decision order | Opus 5, adaptive thinking, `effort: high` |
| Rich evidence input | **Bundle v2** — carry the customer names and hard metrics from `content_reasoning`, not just grader opinion |
| Seeing the *whole batch* — that 412 of 594 messages closed identically, that NewsCatcher carried 52% of msg-2s | **Diversity budget + batch lint** (§4.3). This is the thing a stateless API call cannot do, and exactly what v2 got wrong |
| Mid-run correction (the CTA ban at message 412) | **Versioned prompts** + regenerate-affected-subset |

### 4.2 Request shape

```
system = [
  { SKILL.md body,           cache_control: ephemeral, ttl "1h" },   # ~11k tokens
  { data dictionary,         cache_control: ephemeral            },   # ~2k tokens
  { case-study registry      },                                       # ~1.5k tokens
]
messages = [
  { role: "user", content: prospect bundle JSON + diversity constraints }   # ~700 tokens
]
model = "claude-opus-5"
thinking = { type: "adaptive" }
output_config = { effort: "high", format: json_schema(<18-field result schema>) }
```

Three things this buys us:
- **Structured outputs** replace the "return only valid JSON" prose and the parse-retry loop — killing a whole class of v2 failures at the source.
- **The cached prefix stays byte-identical** across the batch, so every call after the first reads it at 0.1× price. Opus 5's minimum cacheable prefix is 512 tokens; ours is ~14.5k, so it caches comfortably. Volatile content (bundle, diversity constraints) goes *after* the last breakpoint — never interpolate a batch ID or timestamp into the system prompt. Verify with `usage.cache_read_input_tokens`; if it's zero across calls, something is invalidating the prefix.
- **`prompt_version` is recorded on every message row**, so "the rule changed, regenerate everything written under v3" becomes a query instead of a string replacement.

### 4.3 Solving statelessness — three mechanisms

**a. Diversity budget, injected per request.** Before each call the service computes, from the batch so far: which CTA phrasings have been used and how often, which case studies are at or over quota, which opener categories are saturated. It passes a short constraint block in the *user* turn — "phrasings already used ≥40 times: […]; case studies at quota: [NewsCatcherAPI]; prefer: […]". Cheap, leaves the cache intact, and aims directly at the observed failure.

**b. Case-study quota as a hard post-check.** Eight studies in the registry. Enforce a ceiling (no study above ~30% of a batch) and re-roll anything over. Deterministic; doesn't need the model.

**c. Batch-level lint after generation.** Over the whole batch, not per message: n-gram frequency on closing lines and openers, case-study distribution, signal-category distribution. Anything above threshold gets a `repetition` flag into the review queue. This is what a human reading 594 messages does, and it automates cleanly.

### 4.4 Post-processing and the QA gate (deterministic, free)

Per result: `sanitize()` (em-dash strip, `{first-name}` enforcement) → brand-casing backstop → lowercase all URLs → restore the msg-2 opener → `qa_check.check()`.

- `mech:*` / `case:*` flags → **auto-fixed**, no API call.
- Anything else → **one bounded regeneration** with the failed rule appended as a steer (reuse the existing `STEER` string), capped at 2 attempts.
- Still flagged → **review queue. Never auto-shipped.**

### 4.5 The review queue is not optional

The v2 lesson is precise: **795 messages, 0 QA flags, campaign pulled.** Regex QA proves the absence of banned patterns; it cannot prove a message is good. So nothing exports without `status = approved`. Give the VA an "approve all visible" for clean pages, but flagged messages get handled one at a time. Track approve / edit / reject rates per `prompt_version` — that becomes the quality signal for every future prompt change.

### 4.6 Model choice and cost — with real numbers

Measured from this repo: SKILL.md 44,587 chars, data dictionary 7,625 chars, registry ~5.9 KB, median bundle 2,194 chars.

| Component | Tokens | Opus 5 rate | Cost/prospect |
|---|---|---|---|
| Cached system prefix | ~14,500 | $0.50 / MTok (cache read) | $0.007 |
| Fresh input (bundle + constraints) | ~700 | $5 / MTok | $0.004 |
| Output + adaptive thinking | ~2,000 | $25 / MTok | $0.050 |
| **Total** | | | **≈ $0.06** |

**≈ $48 for an 800-lead batch. ≈ $24 via the Batch API (−50%).** Cache writes add roughly $0.09 once per hour of runtime.

**Recommendation: Opus 5, `effort: high`, adaptive thinking, structured outputs. Batch API for the bulk pass, realtime for single regenerations from the review queue.**

Not Sonnet. The earlier Sonnet-vs-Opus comparison was run while the org was out of credits and cost dominated the decision; at $24–48 per campaign against $10–20K deals, cost is not a real constraint — and the pulled v2 campaign is direct evidence that the cheaper path lost money rather than saving it. Keep Sonnet 5 configurable as a "draft everything cheaply, human curates hard" mode if that's ever wanted.

Two Batch API caveats to build around: results come back **out of order** (key on `custom_id`, never position), and the `fallbacks` parameter is **rejected on Batches** — so handle `stop_reason == "refusal"` yourself and requeue those on the realtime path.

### 4.7 The prompt becomes a first-class object

SKILL.md moves into the `prompts` table and gets force-added to git **today**, before any app code. Every message records the version that wrote it. Changing the prompt creates a new version, and the app can then offer: "412 messages were written under v3; the rule changed; regenerate them" — the operation we did by hand with string replacement.

---

## 5. Build order

### Phase 0 — This week, independent of the app
1. `git add -f .claude/skills/generate-outreach/SKILL.md` — 44.5 KB of product on one disk, unbacked.
2. Commit the ~17 modified files plus all of `scripts/outreach_loop/` — nothing has been committed since 2026-07-09.
3. Patch `next_bundles.py` to exclude domains in `skipped_shutdowns.json`, or the loop re-serves FTX and three shut-down companies.

### Phase 1 — Schema, import, export (the spine)
Postgres schema; CSV importers for both file types; `score_person` ported verbatim; export endpoint.
**Proof of correctness:** import the existing batch_01 files, re-export, and diff against the current `outreach_ready_v3.csv` — **zero rows changed.** That diff is the migration test.

### Phase 2 — Generation service, QA, review queue
Bundle v2 (add the evidence fields); Anthropic client with cached prefix and structured outputs; diversity budget; deterministic post-processing; `qa_check` as a library; the review UI.
**Proof:** generate the remaining 199 prospects unattended, user reviews, approve rate matches or beats the hand-written run.

### Phase 3 — Enrichment as jobs
Wrap the existing grader modules as tasks; per-provider rate limiters; retries with terminal states; cost meter; free resume.
**Proof:** re-enrich a 50-row slice and match the existing column values.

### Phase 4 — The VA shell
Auth, batch dashboard, progress board, run history, legible error surfacing. Deploy.

### Phase 5 — Optional
Reply/status ingestion (turns it into a light CRM); the `analyze-site` vertical behind the same UI.

---

## 6. Risks and open items

- **Contact sourcing is the real bottleneck, not messaging.** 132 of 594 written messages (22%) can't be sent because the people file has nobody at that domain, and the contact mix is 383 founders to 38 marketing because only ~20 marketing titles exist in the entire people dataset. More writing does not fix this. The app should surface it per batch, but the actual fix is a people-enrichment step (Apollo/Clay) — worth slotting around Phase 3.
- **Gemini free tier is 20 requests/day**, which throttles grading to ~10 sites/day. Enrichment cannot be a self-serve button until that account is on paid billing.
- **Some sites never grade** (Cloudflare, bot detection). Needs a terminal "couldn't grade" state, not an infinite retry.
- **Signal freshness.** A site audited in June may have relaunched by August — `detect_site_changes.py` exists precisely because this bit us. Every message should carry `audited_at`, and export should warn when the evidence is stale.
- **LinkedIn ToS.** Export-only is the correct call. Keep it that way.
- **Rules live in three places** (SKILL.md prose, `RUN_LOOP.md`, `qa_check.py` regexes). Phase 2 should make SKILL.md the single source and generate or at least cross-check the QA rules against it.
