# Grader v2 — Implementation & Build Log

Living record of the bulletproof grader rebuild. Tracks **decisions**, **what's built**,
and **calibration results**. Companion to the two research docs:
- `specs/content-grader-v2-spec.md` — original analyst architecture (superseded in parts; see Decisions)
- `specs/grader-research.md` — extraction + variance research with sources

Started 2026-06-12.

---

## The problem (recap)

The v1 grader scores whatever text Jina extracts as if it belongs to the company.
It is fooled by non-genuine pages — the canonical failure is `enrich.ly`, a domain
served by Atom.com's marketplace that scored a B. v1 also has run-to-run design-score
variance large enough to flip letter grades.

Two distinct problems, two different tools:

1. **Is this a real, owned, operating site?** → an *infrastructure* question. Answer with
   DNS + redirect signals (robust, free, LLM-invisible).
2. **Does the content genuinely represent THIS company?** → a *semantic/judgment* question.
   Answer with a vision-first LLM that does real reasoning (generalizes, no enumeration).

---

## Decisions (and where they overrule the original spec)

These were decided with the user after critiquing the spec + research. The verdict:

| # | Item | Decision | Rationale |
|---|---|---|---|
| 1 | Redirect / final-URL check | **BUILD** | Robust infra signal. Empirically caught `enrich.ly` (302 → atom.com). Free; from Playwright `page.url`. |
| 2 | DNS nameserver check | **BUILD** | Most robust signal. `enrich.ly` NS = `ns1.atom.com` — a real SaaS never delegates DNS to a marketplace. Near-zero false positive; LLM-invisible. |
| 3 | Vision-first LLM gate (thinking ON) | **BUILD** | The "real thinking" primary judge. Generalizes to novel non-genuine pages without pattern enumeration. |
| 4 | `INVALID` abstain state | **BUILD** | Distinct from F. Excluded from ranking/averages. `letter_grade="INVALID"`, `total_grade_score=None`. |
| 5 | Content-string / "make an offer" / platform fingerprints as **hard blocks** | **DROPPED** | User's objection is correct: legit SaaS sites use these as CTAs → false positives. Brittle first-level filter. Not built. |
| 6 | `confidence >= 0.75` threshold as gate trigger | **DROPPED** | LLM self-reported confidence is miscalibrated (clusters at 0.9). The gate decides categorically. Confidence still recorded as a *diagnostic only*. Second-opinion/disagreement path deferred until the manual-10 review shows it's needed. |
| 7 | `thinking_budget=0` | **DROPPED** | Legacy SDK (`google.generativeai` 0.8.6, used codebase-wide) cannot toggle thinking. Migrating the whole codebase to `google-genai` is out of scope. Evidence: `temperature=0` already produced deterministic output on an identical image (`[90,90,90]`) *with* thinking on — so thinking-on is not our variance source. Gate *wants* thinking on anyway (default). |
| 8 | `temperature=0` + `response_schema` on numeric scorers | **BUILD** | Free variance reduction; supported by legacy SDK. |
| 9 | Sub-dimension design scoring (5×0-20 anchored) | **BUILD** | Tighter + auditable. Replaces single holistic 0-100. |
| 10 | 5th content dimension "Depth" + tighter rubric | **BUILD** | Fixes v1 generosity (thin polished sites scoring ~56). |
| 11 | N-run design ensemble | **BUILD (calibration only)** | `DESIGN_ENSEMBLE_RUNS=2` for now. **Mean** of 2 (median needs 3), but **both runs + spread recorded** and large spread flagged — disagreement is the real diagnostic during manual review. Set to `1` for prod. |
| 12 | `gemini-2.5-pro` for design | **DEFERRED** | Escape hatch if free fixes leave design too wobbly. One-line swap later. |
| 13 | Firecrawl extractor swap | **DEFERRED** | Playwright already gives final-URL; only needed if bot-blocking is a real volume problem. |

**Net architecture:** `DNS + redirect (robust infra)` → `vision-first LLM judge (reasoning)` →
`PASS → score` or `ABSTAIN → INVALID`. Less code than the original spec, more robust.

---

## Environment

- SDK: `google.generativeai` 0.8.6 (legacy; deprecated upstream but functional). Supports
  `temperature`, `response_mime_type`, `response_schema`. Does **not** support `thinking_config`.
- New deps installed: `tldextract` 5.3.1, `dnspython` 2.8.0. Added to `requirements.txt`.
- Gemini account on Tier 1 (paid, funded). ~4 Gemini calls/site during calibration
  (gate + 2 design + 1 content); ~3/site in prod (gate + 1 design + 1 content).

---

## Components

### `scripts/page_gate.py` (NEW)
- `_get_registrable_domain(url)` — tldextract.
- `_check_redirect(input_url, final_url)` — registrable-domain change → `ACQUIRED_REDIRECT`.
- `_check_dns_parking(domain)` — NS/A records vs known parking operators → `PARKED_OR_FOR_SALE`.
- `_run_llm_gate(...)` — single Gemini vision call, temp=0, response_schema; returns
  page_state + identity_match + reason + confidence (diagnostic).
- `assess_page_validity(...)` — orchestrates DNS → redirect → LLM. Never raises.
  Returns `{page_state, identity_match, gate_confidence, gate_passed, gate_reason,
  abstain, detected_platform, redirect_domain, gate_source}`.

Decision order: DNS parking → redirect-off-domain → LLM gate. PASS iff
`LIVE_COMPANY_SITE` + `identity_match`. Everything else abstains.

### `scripts/website_grader.py`
- `capture_screenshot_and_content` — adds `final_url`, `http_status`.
- `analyze_design_with_gemini` — sub-dimension schema (typography, spacing_layout,
  color_brand, visual_hierarchy, polish_craft; each 0-20; sum = 0-100), temp=0, anchored.
- `analyze_design_ensemble` — runs the above N times; mean score, records runs + spread.
- `grade_website` — new `company_name` param; runs gate after Jina; INVALID abstain path;
  adds gate + design-ensemble + depth fields.
- `process_csv_async` — passes company_name; new output columns.

### `scripts/content_extractor.py`
- `get_llm_content_ratings_v2` — 5 dims incl Depth, response_schema, temp=0, scale `/50*70`.
- `analyze_content_with_llm` — calls v2; threads `depth`.

### `scripts/orchestrator.py`
- `run_enrichment` — passes company_name; captures gate fields into entry_result.
- `load_existing_results` — loads new gate columns (resume support).
- `flag_entry` — treats `INVALID` as a valid non-error state.

### New output columns
`page_state`, `gate_confidence`, `gate_reason`, `detected_platform`, `gate_source`,
`design_typography`, `design_spacing`, `design_color`, `design_hierarchy`, `design_polish`,
`design_score_runs`, `design_score_spread`, `depth`.
`letter_grade` gains value `"INVALID"`.

---

## Status

- [x] Decisions locked, deps installed, tracking doc (this file)
- [x] page_gate.py
- [x] Playwright final_url/http_status
- [x] Design scorer rewrite + ensemble
- [x] Content v2 (Depth)
- [x] Integration (grade_website + orchestrator + flag_entry + process_csv_async)
- [x] Unit tests (deterministic gate layers) — `scripts/test_page_gate.py`, 16/16 pass
- [x] First-10 run for manual review — `data/graded_v2_test.csv`
- [ ] User manual review feedback → calibration iteration

---

## Run 2 — first 15 sites (`data/graded_v2_15.csv`, 2026-06-12)

Friendly names + description row + full breakdowns now in the output. Results:
- **Graded (LIVE):** Axle B(75), Soldera/Sweetspot/Refraction/DocStation/QA.tech all C+ (65-67).
- **INVALID (correct):** Dror=BLANK_RENDER (fix confirmed), Industrial Data Labs=BOT_BLOCKED(403),
  Composabl=ACQUIRED_REDIRECT->amesa.com, Materia=ACQUIRED_REDIRECT->thomsonreuters.com (real acquisition).
- **Capture fail (flagged):** Terrain Bio + Coherence (server-side SSL/WAF), TENYX + Diagon (DNS) — Firecrawl territory.

**Fix applied:** transient Gemini errors (500/503/504/deadline/timeout) are now retried
(`_is_retryable_error` in content_extractor, used by design + content + gate). Acctual was
dropped by a 504 on its design call; after the fix it grades C-(55), LIVE. Verified.

**Known issues / next:**
- **Content-score variance from Jina extraction.** Axle content 80->99, Acctual 80->55 across runs.
  The LLM is deterministic (temp=0); the swing comes from Jina returning different amounts of text
  per fetch. Design variance is solved (LLM); content variance is an EXTRACTION problem, not yet
  addressed. Candidate fixes: cache/normalize extraction, or average content over 2 fetches.
- **Throughput: 138 min for 15 sites (~552s/site)** — untenable for 999 (see task #17). Capture
  retries on failing sites + 2x design ensemble + the 504 hang dominate. Correctness is fine.
- All `speed_score`=50 in these isolated grader runs (no PageSpeed data); the full orchestrator
  fetches real speed, which will move overall grades.

## ⏸️ PARKED (2026-06-13): subjective content/design grading accuracy

Decision: stop polishing the subjective graders for now — getting content/design scores
*accurately* and *stably* is genuinely hard and has diminishing returns. What's built works
and fails safe; revisit later. Open threads to pick up when we return:
- **Design score is only as stable as the screenshot crop.** Same site scored design 63 then 55
  across runs because a fresh capture framed different sections. Need consistent capture (fixed
  crop / full-page tiling / element-aware) before the design number is trustworthy.
- **Content completeness is solved (Playwright text) but score calibration is unsettled** — two
  genuinely-substantive sites both land ~81; unclear if anchors should be harsher.
- **Content extraction variance** (Jina non-determinism) — mitigated by preferring Playwright text.
- Possible future: drop Jina entirely (Playwright text is strictly more complete), median design
  ensemble, or `gemini-2.5-pro` for design.

## 🔭 NEW DIRECTION (2026-06-13): objective "black-and-white" signals — BUILD PLAN

Pivot from subjective grading toward concrete, deterministic signals (performance is the model:
it's the truth, no arguing). These are stable across runs, mostly LLM-free (fast → fixes the
throughput blocker), and each one is a defensible, fact-based outreach hook.

**HARD REQUIREMENT (user, 2026-06-13):** every consolidated score must carry its **broken-down
sub-metrics as their own columns**. We never just say "AI-readiness 42/100" — we cite the exact
fact ("blocks GPTBot", "no llms.txt", "only 38% of content is server-rendered", "0 JSON-LD blocks").
The consolidated score is for ranking; the sub-metrics are for the outreach copy. Do not drop them.

We are building ALL of the below. Sequenced by payoff/effort.

### Phase 1 — Lighthouse extra scores (nearly free; data already fetched)
The PageSpeed API call we already make returns four Lighthouse categories; we only read
Performance. Parse the other three from the SAME response (zero extra API calls):
- `seo_score` (0-100), `accessibility_score` (0-100), `best_practices_score` (0-100)
- Also surface the individual audit failures behind each (e.g. which a11y audits failed) so we can
  cite specifics, not just the rollup. Store as `*_issues` (list of failed-audit ids/titles).
- File: `scripts/pagespeed_checker.py` (extend existing parse). Add columns + descriptions in
  `grader_fields.py`.

### Phase 2 — AI-Readiness module (deterministic, no LLM)
New module `scripts/ai_readiness.py`. One consolidated `ai_readiness_score` (0-100) PLUS every
sub-metric as its own column. Sub-checks:
| Sub-metric | Column(s) | Source |
|---|---|---|
| Server- vs client-rendered ratio | `ssr_content_ratio` (raw HTTP text ÷ Playwright rendered text), `ssr_raw_words`, `ssr_rendered_words` | **already captured** (`jina_text`/raw vs `pw_text`) — just compute |
| robots.txt AI-bot policy | `robots_blocks_ai` (bool), `robots_ai_blocked_list` (which of GPTBot/ClaudeBot/PerplexityBot/Google-Extended/CCBot/Bytespider), `robots_has_sitemap` | GET /robots.txt |
| llms.txt presence | `has_llms_txt` (bool) | GET /llms.txt |
| Structured data | `jsonld_count`, `jsonld_types` (Organization/Product/FAQ/…), `has_schema_org` | parse rendered HTML |
| Sitemap | `has_sitemap` (bool), `sitemap_url_count` | GET /sitemap.xml (+ robots Sitemap:) |
| Semantic HTML / metadata | `has_title`, `title_text`, `has_meta_description`, `meta_description_text`, `has_og_tags`, `h1_count`, `heading_outline_ok` | parse rendered HTML |

`ai_readiness_score` = weighted roll-up of the above; weights TBD after the research agent reports.
Each contributing fact stays addressable for outreach.

### Phase 3 — Security / SSL + headers hygiene (deterministic)
New module `scripts/security_check.py`. Consolidated `security_score` + sub-metrics:
- `ssl_valid`, `ssl_days_to_expiry`, `tls_version`
- `has_hsts`, `has_csp`, `has_x_frame_options`, `has_x_content_type_options`, `has_referrer_policy`
- `mixed_content` (http resources on an https page), `mixed_content_urls`
- (stretch) outdated-CMS / known-CVE detection from version fingerprints.

### Phase 4 — Core Web Vitals pass/fail + mobile-friendliness
- Turn raw FCP/LCP/CLS (already collected) into Google's hard pass/fail badges
  (`lcp_pass`, `cls_pass`, `fcp_pass`, `cwv_all_pass`) using published thresholds.
- `has_viewport_meta`, `is_responsive` (no fixed-width layout), `tap_targets_ok`.

### Phase 5 — Technical staleness / hygiene
- `copyright_year`, `copyright_is_stale` (footer year < current)
- broken internal links (`broken_link_count`), `oversized_images_count`, `has_favicon`.

### Phase 6 — Research-driven signals (catalog in hand, 2026-06-14)
Research agent returned a full, cited catalog of what serious CRO/SEO/accessibility/security
firms audit. **Top 10 highest-value to build (revenue/legal × ease × fit):**
1. **CrUX field data** — ✅ done in Phase 1 (Google's real ranking input).
2. **axe-core WCAG violations** — runs in our existing Playwright; ties to 5,000+ ADA suits/yr,
   $5–75K settlements, 36% of suits hit >$25M-rev companies (our ICP). Strongest legal hook.
3. **Speed→$ loss estimate** — PageSpeed score × SimilarWeb traffic (we have both) × 7%/sec.
4. **Cookies/trackers firing before consent** — GDPR top-tier fines (Amazon €35M, Shein €150M);
   Playwright network capture pre-interaction.
5. **Security-header grade (A+–F, Observatory-style)** — single request; avg site scores 58/100.
6. **Form friction** (field count + high-friction inputs) — DOM parse; 11→4 fields = +120% conv.
7. **Page weight + unoptimized images** — WordPress's signature weakness; fixable by migration.
8. **Outdated CMS / known-CVE exposure** — indicts WordPress itself (perfect WP→Webflow wedge).
9. **Missing trust-signal markup + rich-result schema gaps** — testimonials/logos/G2 + FAQ/Product JSON-LD.
10. **SSL expiry + mixed content** — cert countdown + http-asset-on-https; trivial, browser-warning risk.

Strategic note from research: signals #2/#4/#7/#8 indict **WordPress as a platform** (plugin CVEs,
image bloat, accessibility debt in themes, tracker sprawl) → "migrate off WP" is the natural
conclusion, not "patch this page." Lead legal-risk prospects with accessibility+privacy; lead
traffic-rich prospects with CWV field data + dollarized speed loss. Several of these merge into the
existing phases (security headers/SSL → Phase 3; page weight/images → reframed Phase 5; CWV field →
done). axe-core accessibility (#2) and cookies-before-consent (#4) are net-new modules.

### ⚠️ OUTREACH FRAMING RULE (critic finding, 2026-06-14) — applies to ALL phases
Not every signal is equally "black and white." **Lab** Lighthouse scores (seo/accessibility/
best_practices) are far steadier than the perf score but still recomputed per run and can drift
±a few points. Only **CrUX field data** (`field_*`, `cwv_pass`) and **specific failed-audit facts**
(`*_issues`, e.g. "buttons have no accessible name") are truly run-stable. **Outreach copy must
cite the stable facts — the `*_issues` items and field data — NOT the volatile rollup score.**
Friendly descriptions tag lab scores "(lab)". Keep this distinction as we add more signals.

### ✅ Phase 1 — BUILT & critic-reviewed (2026-06-14)
Extracts from the SINGLE PageSpeed call we already make (zero extra quota):
- Lab category scores: `seo_score`, `accessibility_score`, `best_practices_score` (0-100).
- Citable failed-audit lists per category: `seo_issues`, `accessibility_issues`,
  `best_practices_issues` (sorted by audit weight so score-driving issues lead).
- CrUX **field** data (real users, p75 — Google's ranking input): `field_{lcp,inp,cls,fcp,ttfb}`
  + per-metric `_rating` (good/needs-improvement/poor), `crux_source` (page→origin fallback keyed
  on the LCP+INP+CLS triad), and `cwv_pass` (tri-state: True/False/None where None = insufficient
  field data, kept distinct from False).
- Wired through: `pagespeed_checker.get_pagespeed_score` (+ standalone `process_csv`),
  `orchestrator` (PAGESPEED_LAB_CATEGORY_FIELDS / PAGESPEED_CRUX_FIELDS / `_pagespeed_extra_defaults`,
  capture + save + load), `grader_fields` friendly names+descriptions.
- **Critic verdict: SHIP WITH FIXES** — data correctness verified against live responses. Applied:
  (1) desktop fallback for lab category scores when the mobile call errors (CrUX stays mobile-only);
  (2) CrUX page→origin fallback keyed on the core triad, not "any metric"; (3) issues sorted by
  weight; (4) hardened `_NUMERIC_PROBES` for the description-row detector. Framing rule recorded above.
- Verified: helper unit checks, live calls (stripe/wordpress.org), annotated-CSV round-trip,
  orchestrator import + field-group invariants, py_compile of all 3 files.

### ✅ Phase 1 follow-ups — BUILT (2026-06-14)
- **PageSpeed retries** (`_fetch_pagespeed` + `_retry_wait`): 3 attempts, exp backoff 2/4/8,
  honors `Retry-After` (seconds OR HTTP-date), retries only transient (429/5xx/timeout/connection),
  never other 4xx. Without this a flaky mobile call silently blanked good data at 999-site scale.
- **Desktop CrUX field data**: parallel `*_desktop` columns (desktop CWV ranks desktop search;
  research-confirmed mobile-first indexing + per-form-factor CWV). Mobile remains primary.
- **Comparable units**: field LCP/FCP now in SECONDS (match lab `mobile_lcp_s` etc.), INP/TTFB in ms,
  CLS unitless — so field-vs-lab gap is readable directly. Lab CWV columns gained units + "compare vs
  field" descriptions. (bbc.com showed why: lab LCP 4.39s but real-user 1.06s → cwv_pass True.)
- **Boolean round-trip fix** (`read_annotated_csv`): bool columns (cwv_pass, is_wordpress,
  ssr_client_rendered, ...) now restore as real bools — fixed a latent `bool('False')==True` resume bug.

### ✅ Phase 2 — AI-Readiness BUILT & critic-reviewed (2026-06-14)
`scripts/ai_readiness.py` — deterministic, no-LLM discoverability signals. One `ai_readiness_score`
(0-100) + `ai_readiness_partial` flag + every sub-check as its own column (the hard requirement):
- **Server-vs-client render ratio** (`ssr_*`) — raw HTTP word count vs Playwright rendered text;
  flags client-rendered (<50% SSR). Raw side strips hidden elements to match `innerText` semantics.
- **robots.txt AI-bot policy** — custom parser; blocks-AI detection for GPTBot/ClaudeBot/Perplexity/
  Google-Extended/CCBot/Bytespider/etc. Handles `*` fallback, `Allow:/` override, `Disallow:/*`.
- **llms.txt** (soft-404-guarded), **JSON-LD** (handles @graph/array/CDATA/malformed),
  **sitemap.xml** (direct or via robots; accepts XML even if mislabeled text/html),
  **semantic/meta** (title/description/OG/single-h1).
- Wired into orchestrator (step 6, uses Playwright `page_text` for the ratio), save/load, friendly names.
- **Critic verdict: DO NOT SHIP → fixed.** Caught a P0 (desktop-field loop KeyError that would crash
  the run on site #1) + 2 P1 (SSR not apples-to-apples; partial scores not comparable) + 4 P2
  (Disallow:/*, CDATA JSON-LD, llms.txt false-accept, XML sitemap mislabel, Retry-After date). ALL
  applied. Regression suite added: `scripts/test_signals.py` (8 groups incl. the P0 guard) — all pass.
- Real-site validation: Stripe/Vercel 93, TechCrunch 64 (correctly flags it blocks 9 AI crawlers).

### ✅ Orchestrator end-to-end — critic-reviewed + LIVE-validated (2026-06-14)
- Critic verdict on the full `run_enrichment` path + save/load/resume: **SHIP** (schema consistency,
  resume of renamed cols, partial-run defaults, step-6 robustness, bool handling — all verified).
- Live 2-site run (`crunchbase.csv --limit 2 -o data/test_signals_run.csv`, existing 999-run untouched):
  Soldera (live) populated everything correctly — SEO 100 / A11y 91 (+citable contrast issue) / BP 77,
  mobile CWV pass (LCP 2.06s, INP 196ms) + desktop CWV (LCP 0.6s, shows mobile↔desktop gap), lab
  mobile_lcp 1.82 vs field 2.06 (field>lab gap visible), AI-readiness 100 (SSR 1.1, llms.txt, 11 JSON-LD,
  sitemap). Terrain Bio (anti-bot/SSL) failed SAFE — all fields null, errors flagged, no crash; its
  PageSpeed 400 correctly NOT retried (transient-only).
- **Fixed the P2 fragmentation warning**: `save_progress` now builds all enrichment columns into one
  block and `pd.concat(axis=1)` once (df.assign / repeated df[col]= both insert column-by-column and
  still warn). Verified: no PerformanceWarning, no duplicate columns, round-trip intact.
- Pipeline is correct and ready for a larger run.

### ✅ Phase 6a — axe-core accessibility BUILT & critic-reviewed (2026-06-15)
`scripts/accessibility.py` — runs Deque axe-core 4.10.2 (vendored at `scripts/vendor/axe.min.js`,
MPL-2.0) inside the EXISTING capture browser pass (no extra launch). The ADA/legal-risk hook.
Factual columns only (no invented score; Lighthouse `accessibility_score` is the rollup):
`a11y_violation_count`, `a11y_node_count`, `a11y_{critical,serious,moderate,minor}`,
`a11y_lawsuit_risk`, `a11y_top_issues` (citable, e.g. "Images must have alternate text (12 elements)"),
`a11y_wcag_tags`, `a11y_error`. Runs WCAG A/AA tags only.
- Wired: website_grader capture (spreads defaults + runs axe while page live), orchestrator
  (init/capture-copy/save/load), grader_fields friendly names, SIGNALS.md §4b.
- **Critic verdict: SHIP WITH FIXES — all applied:** (P1) lawsuit flag keys off the RULE identity
  (not impact bucket) + impact derived from node-level data when top-level null, so a null-impact
  alt-text violation can't silently clear the flag; (P1) "Homepage:" scope stated in all column
  descriptions + SIGNALS.md honesty notes (homepage-only, conservative floor, not-measured≠clean);
  (P2) empty text round-trips as '' not nan (text columns with data only — numeric untouched).
- Confirmed solid by critic: fails SAFE under strict CSP (GitHub/Stripe block script injection →
  a11y_error set, screenshot/text/all other fields intact), deterministic run-to-run, parsing
  matches axe raw output, schema plumbing consistent, bool round-trip works, 30s timeout bounds it.
- Regression: `test_signals.py` now 9 groups (added axe lawsuit-flag/null-impact guards) — all pass.
- Live: soldera.org → 3 serious WCAG violations / 28 elements (contrast ×25, link-name ×2, ARIA ×1),
  lawsuit_risk=True (cross-checks the Lighthouse contrast finding).
- **Scope note:** Speed→$ DROPPED (no credible per-company $ without assuming conversion rate/value).
  CMS CVEs = free version-fingerprint only (no paid WPScan).

### ✅ Phase 6b — Security & SSL BUILT & critic-reviewed (2026-06-15)
`scripts/security_check.py` — pure HTTP + stdlib `ssl`/`socket` + bs4, no browser, no new deps.
Header grade A+–F (HSTS/CSP/X-Frame/X-CTO/Referrer/Permissions) + per-header bools + missing list;
SSL cert validity + days-to-expiry + expires-soon + TLS version; mixed content (http:// assets on
https, incl. srcset + CSS url()); combined `security_issues`. Wired into orchestrator step 7 +
save/load + grader_fields + SIGNALS.md §6b. Live: GitHub A(90), Soldera F(0).
- **Critic verdict: SHIP WITH FIXES — all applied (NO new dependency; user declined `cryptography`):**
  - cert validity now derived from whether the verified HTTPS fetch succeeded; cert details read via
    ONE socket (was 1 requests + up to 2 sockets). Final (post-redirect) host used; SSL only probed
    on HTTPS final URLs (fixes neverssl-style cert fabrication on http-only sites).
  - Broken-cert facts WITHOUT cryptography: `_classify_ssl_error` reads the handshake error →
    EXPIRED / self-signed / hostname-mismatch (expired sets `ssl_expires_soon`; exact day count is
    None on a bad cert — valid certs still get the precise date from the cert dict).
  - Headers now read off ANY response (403 Cloudflare challenge pages still carry HSTS/CSP).
  - Mixed content also catches `srcset` + CSS `url(http://…)`. SSL timeout tightened to 8s.
  - Verified live on badssl.com expired/self-signed/wrong-host + neverssl + github.
- Regression: `test_signals.py` → 11 groups (added header-grade/mixed-content + SSL-classification). Pass.
- **Re-review (2026-06-16) — SHIP WITH FIXES, applied:** all six prior fixes re-confirmed correct on
  live badssl/Cloudflare/redirect/http-only sites. (P1) throughput: `requests` `timeout` is
  per-connection-attempt, so a firewalled multi-IP host could stall ~46s — now uses a module-level
  `requests.Session` with `HTTPAdapter(max_retries=0)` + split `timeout=(CONNECT_TIMEOUT=5, read)`,
  making the per-attempt timeout the real wall-clock cap. (P2) `mixed_content_count` now dedupes by
  URL (an asset referenced as both a tag attr and CSS `url()` counts once). Classification: untrusted
  root / unverifiable chain ("self-signed in certificate chain" / "unable to get local issuer") now
  reads as "not issued by a trusted authority", distinct from a genuinely self-signed leaf.

### ✅ Phase 6c — Network-pass signals BUILT & critic-reviewed (2026-06-16)
`scripts/page_signals.py` — pure `parse_network_signals(responses, cookies, consent_present, base_url)`
fed by the existing capture browser pass (a `page.on('response')` listener in `website_grader.py`; no
extra launch). Two objective groups: (1) page weight + image bloat — `page_weight_kb` (Content-Length
FLOOR), `page_weight_partial`, `image_weight_kb`/`image_count`/`large_image_count`,
`uses_next_gen_images`, `request_count`, `third_party_domains`; (2) privacy — `trackers_detected`/
`tracker_count`, `cookies_set`/`tracking_cookies`, `has_consent_banner`, `tracking_before_consent`.
Dedupes responses by URL (max size); ranged-media (206) weight from Content-Range total. Wired into
grader result init + save/load + grader_fields + SIGNALS.md §6c. Live: Soldera ~24MB, 4 trackers
before consent.
- **Critic verdict: SHIP WITH FIXES — all applied:**
  - Tracker match: url-substring → **registrable domain** (`TRACKER_DOMAINS`) + precise host/path needles
    (`TRACKER_HOST_PATH`) for broad consumer domains. Kills false positives ("tiktok.com" ⊂ "nottiktok.com").
  - Tracking cookies: anchored — short/ambiguous names (`IDE`, `personalization_id`, …) require EXACT
    match; namespaced families keep prefix match. (Bare `IDE` no longer matches `IDENTITY`.)
  - Fixed the dead Pinterest pattern (`pinimg.com` / `ct.pinterest.com` instead of `pinterest.com/ct`).
  - Page weight guard: when too few resources report a size (`page_weight_partial`), `page_weight_kb` is
    blanked/not cited; framed as a transferred-bytes FLOOR, never "0 MB".
  - `consent_violation` → `tracking_before_consent` (observable fact, not a legal verdict); SIGNALS.md
    softened (no "GDPR violation" claim — cite the cookies/trackers that fired).
  - P2: `data:`/`blob:` URLs excluded from `request_count`/weight.
- Regression: `test_signals.py` → 12 groups. Pass.

### Cross-cutting
- All new columns get friendly names + descriptions in `scripts/grader_fields.py`.
- These run independent of the (parked) subjective graders; an `INVALID`-gated site still gets
  objective signals where they make sense (a parked domain has no AI-readiness, but a live-but-
  ugly site does).
- Most are pure HTTP/parse → fast. This directly helps the 999-site throughput problem (task #17).

## CSV field naming + description row (`scripts/grader_fields.py`)

Decision: rename fields for human readability at the **CSV boundary only** — internal
code keeps its names (renaming everywhere would touch all scoring/flag/export logic and
is risky). `grader_fields.py` owns one `FIELD_MAP` (internal -> friendly + description):

- **on write** (`write_annotated_csv`): rename internal -> friendly, insert a second row
  of plain-English descriptions under the header.
- **on read** (`read_annotated_csv`): drop the description row, rename friendly -> internal
  so code is unchanged, re-coerce numeric columns (the text desc row forces object dtype).

Wired into every generated-CSV IO point: `orchestrator.save_progress` / `load_existing_results`,
`website_grader.process_csv_async`, `flag_checker`, `export_prospects`. Raw INPUT files
(crunchbase.csv) are still read with plain `pd.read_csv` (no desc row, backward compatible).

The headline verdict fields (what to actually read):
| Friendly name | Meaning |
|---|---|
| `site_status` | LIVE_COMPANY_SITE = gradeable; else parked/blank/blocked/redirect/mismatch |
| `overall_grade` | A+..F, or INVALID |
| `overall_score` | 0-100 = 30% speed + 40% content + 30% design |
| `speed_score` | site speed 0-100 (mobile PageSpeed) |
| `content_score` | 0-100 (= `content_elements_score` 0-30 + `content_quality_score` 0-70) |
| `design_score` | 0-100 (= sum of `design_typography/spacing/color/hierarchy/polish`, each 0-20) |

Full breakdowns are in the CSV: content (clarity/substance/credibility/persuasiveness/depth,
elements, quality, summary) and design (5 sub-scores + summary + ensemble runs/spread).

## Calibration phase plan

1. Unit-test the deterministic gate layers offline (registrable domain, redirect, DNS on
   `enrich.ly` → expect parked).
2. Run orchestrator `--limit 10` on `crunchbase.csv`. User manually reviews each scan.
3. Log findings below; iterate. Keep 2-run design ensemble until prod release, then drop to 1.

### First-10 run — `data/graded_v2_test.csv` (2026-06-12)

7/10 captured; 3 capture failures (not gate-related: SSL/DNS). Gate abstained on 2.
Design ensemble spread: 6 of 7 graded sites had spread 0-1; one (DocStation) spread 4.
Variance is effectively solved by temp=0 + stabilization + sub-dimensions.

| # | Company | Domain | page_state | src | grade | design runs(spread) | content | Auto-verdict | Manual |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Soldera | soldera.org | LIVE | llm | C (64) | 66,66 (0) | 74 | OK | ? |
| 2 | Terrain Bio | terrainbiosciences.com | — | — | capture-fail | — | — | SSL error | ? |
| 3 | DocStation | docstation.co | LIVE | llm | C+ (66) | 82,78 (4) | 68 | OK | ? |
| 4 | TENYX | tenyx.com | — | — | capture-fail | — | — | DNS not resolved | ? |
| 5 | Coherence | withcoherence.com | — | — | capture-fail | — | — | SSL error | ? |
| 6 | Dror Ortho-Design | aerodentis.com | CONTENT_MISMATCH | llm | INVALID | — | — | **possible FALSE POSITIVE** — site is their product "ZSmile/Aerodentis"; DB name differs | ? |
| 7 | Refraction | shoprefraction.com | LIVE | llm | C+ (66) | 67,68 (1) | 77 | OK | ? |
| 8 | QA.tech | qa.tech | LIVE | llm | C (63) | 66,66 (0) | 72 | OK | ? |
| 9 | Axle Labs | axle.insure | LIVE | llm | C+ (67) | 69,69 (0) | 80 | OK | ? |
| 10 | Industrial Data Labs | industrialdatalabs.com | BOT_BLOCKED | http | INVALID | — | — | correct (403 Cloudflare; can't grade what we can't see) | ? |

**Calibration fixes applied (2026-06-12, after run 1):**
- **Blank-render guard** (`website_grader.is_blank_screenshot` + guard in `grade_website`):
  a screenshot that comes back essentially white (>=95% near-white AND pixel variation <12)
  means the page never rendered. We now flag it `page_state=BLANK_RENDER`, `letter_grade=INVALID`
  with an explicit reason, and abstain BEFORE the gate/design AI run (no wasted API calls). This
  fixes the aerodentis mislabel — the 8KB white screenshot was being fed to the AI as if real.
  An HTTP error status (403/404) keeps its more specific gate label instead of the generic blank one.
  Verified: aerodentis -> INVALID/BLANK_RENDER, real sites unaffected (axle 79.8% white but var 20.8 -> gradeable).
- **Softened identity check** (`page_gate._build_gate_prompt`): companies often run their site under a
  product/brand name different from the DB/legal name (Dror Ortho-Design -> Aerodentis/ZSmile).
  `identity_match` is now true whenever it's plausibly the same business; CONTENT_MISMATCH only fires
  for a clearly DIFFERENT/UNRELATED entity or marketplace. Default-to-LIVE, prefer grading over dropping.
- Added `Pillow` to requirements (blank detection).

**Findings to resolve with user:**
1. **Dror Ortho-Design = likely false positive.** Identity check is too strict when a
   company's DB/legal name differs from its product/site brand (Dror Ortho-Design ships
   "Aerodentis"/"ZSmile" at aerodentis.com). Proposed fix: soften the gate's identity rule
   so CONTENT_MISMATCH only fires for a clearly *unrelated/different* company or a
   marketplace — not a brand/product-name difference. Pending user confirmation.
2. **3/10 capture failures + 1 blank render = 4 hard anti-bot targets.** Root causes
   confirmed via curl (which is rejected identically):
   - terrainbiosciences.com, withcoherence.com: `sslv3 alert handshake failure` — the
     SERVER rejects the TLS handshake (WAF fingerprinting the client). Not a weak-cipher
     issue on our side.
   - tenyx.com: `www.` subdomain doesn't resolve; apex gives `tlsv1 alert internal error`.
   - aerodentis.com: returns 200 but serves a BLANK page to headless browsers (bot detection).
   **Conclusion:** client-side retries/TLS flags cannot fix server-side anti-bot rejection.
   These are the Firecrawl (residential proxy) use case — deferred. Capture improvements
   added (relaxed TLS, blank-recapture, multi-strategy retry) still help slow SPAs /
   misconfigured certs / transient DNS in the broader set; they just can't beat these 4.
   All four now fail safe with a recorded reason (BLANK_RENDER or grader_error).
3. **Design variance solved**: max spread 4, mostly 0. 2-run ensemble can likely drop to 1
   for prod once user confirms.

| # | Domain | page_state | gate_source | grade | design (runs/spread) | content | Manual verdict | Notes |
|---|---|---|---|---|---|---|---|---|
