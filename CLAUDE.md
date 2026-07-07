# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **CURRENT STATE & NEXT STEPS → see `PROJECT_STATE.md`** (canonical handoff; read it first each session).

## Last Session Context (2026-06-23)

### What Was Done This Session — Outreach Messaging Overhaul
Reworked how outreach messages are written and who writes them. Full detail in the new
**"Outreach Messaging System"** section below; in brief:
- **Generation moved off the Gemini API to Claude in-session** via a new `/generate-outreach`
  skill (out of Gemini credits + Claude writes better). `scripts/prep_bundles.py` is the
  data-prep/assembly plumbing.
- **New writing philosophy: lead with an inference about the prospect's business, not flattery**
  (modeled on a cold email the user admired). Understanding > praise. Positive/opportunity
  framing only, grounded in the audit, with traffic-scale math. Guardrails live in the master
  prompt, not a keyword blocklist.
- **3-message sequence**: inference DM → case-study follow-up → short soft close.
- **Case-study library + selection rules** built into the skill (12 studies from `Copy/`,
  URLs `https://prismport.co/case-studies/<slug>` — slugs still need verifying, esp. Wonder
  Phone ↔ Wondersimple).
- **Traffic source-of-truth fix**: messages must use `apify_monthly_visits`, never the stale
  Crunchbase `monthly_visits` (enforced by `accurate_visits()`).
- Latest output: `data/messages_v2.csv` (first/second/third messages + case-study columns).

### Prior Session (2026-06-18) — Apify Traffic Refresh
The prefilled traffic data (copied from Crunchbase into `monthly_visits`) was found to be
stale/wrong for many rows. Refreshed it with live SimilarWeb data via Apify.

1. **New script `scripts/apify_traffic_refresh.py`** — fetches fresh SimilarWeb data via the
   `curious_coder/similarweb-scraper` Apify actor and writes it back into an enriched CSV as
   **new `apify_`-prefixed columns** (originals left untouched, side-by-side for diffing).
   Writes a `.bak` backup first; idempotent (drops/re-adds `apify_` cols on re-run).
   - Usage: `python scripts/apify_traffic_refresh.py data/enriched_<ts>.csv`
   - Built against the **current** actor schema — note `trafficSources` changed: `Search`/`Social`
     are now split into `SearchOrganic`/`SearchPaid`/`SocialOrganic`/`SocialPaid`, `Paid Referrals`
     is gone, and there are new sources incl. `GenAi`, `DisplayAds`, `Affiliate`. The old
     `traffic_checker.extract_traffic_metrics()` mapping is stale for search/social — do not reuse it.
2. **Ran it on `data/enriched_20260616_023344.csv`** (latest fully-enriched file, 100 real rows).
   - 100/100 domains returned data, 0 failures. Added 27 `apify_` columns (now 216 cols total).
   - Confirmed Crunchbase figures were badly off (e.g. megaphone.xyz: 3.47M → 24K actual).
3. **Wrote descriptions into the legend row** for all 27 new columns (see grader_fields note below).

### Apify gotchas (for next time)
- The actor needs a **one-time permission approval** in the Apify Console before the API will run it
  (`?approvePermissions=true` link), separate from "renting" it. A new account must do both.
- The orchestrator does **not** call Apify per-entry; it only ever reads traffic from the CSV. Only
  `traffic_checker.py` / `apify_traffic_refresh.py` actually hit the API. So to refresh, run the
  script first, then enrichment.
- `apify_error` column logs per-row fetch failures (`no_url` / `no_data_returned`); blank = success.
- `apify_country_rank` / `apify_country_rank_country` come back empty in batch mode (actor limitation).

### Recent Work From Prior Sessions (was undocumented here)
The grading pivoted from subjective content/design scoring toward **objective, deterministic
signals** (black-and-white facts an outreach email can cite). Major additions:
- **`scripts/ai_readiness.py`** — bot/AI-engine readiness signals (robots/llms.txt, JSON-LD schema,
  SSR vs client-rendered content ratio, sitemaps). No LLM; every check is a verifiable fact.
- **`scripts/security_check.py`** — security-header score, HSTS/CSP/etc., SSL validity/expiry,
  TLS version, mixed content. Pure `requests` + stdlib `ssl`/`socket`.
- **`scripts/page_signals.py`** — network-pass signals (page/image weight, request count, trackers,
  cookies, consent banner, tracking-before-consent) derived from the existing Playwright capture.
- **`scripts/accessibility.py`** — axe-core a11y violations (critical/serious/moderate/minor,
  WCAG tags, lawsuit-risk flag).
- **`scripts/page_gate.py`** — validity gate that runs BEFORE quality scoring to weed out
  parked/blank/blocked pages (`site_status`, `detected_platform`).
- **`scripts/grader_fields.py`** — **this is what creates the legend/description row** (row 0, just
  under the header) mapping terse internal names to human-readable descriptions. When adding new
  columns, add their descriptions to this row.
- **`scripts/message_generator.py`** — two-pass LinkedIn message generator (Analyst picks the angle
  from the audit, Writer drafts; re-verifies stale a11y flags live before citing).
- **`scripts/extract_facts.py`** — backfills quotable "proud facts" onto an enriched CSV.
- **`scripts/export_prospects.py`** — exports top prospects by segment for outreach.
- These added many columns to the enriched CSV (seo/accessibility/best_practices scores, CrUX Core
  Web Vitals fields, `ai_readiness_*`, `a11y_*`, `sec_header_*`/`ssl_*`, `page_weight_*`,
  `proud_facts*`, etc.). Specs in `specs/grader-v2-implementation.md`, `specs/proud-facts-plan.md`,
  `specs/message-generator-plan.md`.

### Current State
- Latest fully-enriched file: **`data/enriched_20260616_023344.csv`** (100 rows + legend row, 216
  cols incl. fresh `apify_` traffic). Backup: `.bak` alongside it.
- Note: grading uses `overall_grade` (A+–F / INVALID), not the older `letter_grade`.

### Next Steps (User's Priority)
1. Apply fresh `apify_` traffic to a larger prospect set when ready (`apify_traffic_refresh.py`).
2. Continue outreach via the `/generate-outreach` skill (see "Outreach Messaging System") and `export_prospects.py`. Verify case-study slugs before sending.
3. Cloud Deployment — Railway.app + Slack (spec in `specs/cloud-deployment-spec.md`, still pending).

## Outreach Messaging System (How We Write Messages)

This is the canonical record of our outreach-message technique. The **operational source
of truth is the skill** at `.claude/skills/generate-outreach/SKILL.md` (the master prompt +
procedure + case-study library). This section explains the why and the shape so it stays saved.

### 2026-07 UPDATE — bulk generation moved to the Claude API (Sonnet 5)
After hand-authoring/subagent runs got expensive (drained API/usage credits) and couldn't run
unattended reliably, we ran a **model-swap quality/cost test** (`scripts/model_swap_test.py`) on
gold-reference prospects across Opus 4.8, Opus 4.8+thinking, Sonnet 5, Haiku 4.5. Findings:
Opus 4.8+thinking best-matched in-session quality (~$16/380) but **Sonnet 5 matched the hard
rubric calls at ~$5/380 with clean output**, so **Sonnet 5 is the chosen bulk model**. (Correct
Opus pricing is $5/$25 per 1M, not the $15/$75 first assumed — older Opus is the same price, so
"lower Opus" saves nothing; only Sonnet/Haiku are cheaper.) Prompt-caching + Batch API drive cost.
- **Runner: `scripts/generate_messages_api.py`** — picks the next N unwritten gradeable prospects
  from `data/message_bundles_all.json`, sends each with SKILL.md+data-dictionary as a **cached
  system prompt** to Sonnet 5 (thinking disabled), applies a **deterministic brand-casing
  backstop** (`webflow`→`Webflow`, `gdpr`→`GDPR`, sentence-case, `I`), merges into
  `message_results.json`, runs `assemble`, writes a full-column `REVIEW_batch_XXX.csv`.
  `--batch` uses the Message Batches API (-50%); default is realtime. Needs `ANTHROPIC_API_KEY` in `.env`.
- **Three prompt fixes locked in (in SKILL.md HARD RULES / anatomy):** (1) **proper capitalization is
  mandatory** (overrides the casual feel; models otherwise slip to lowercase); (2) **signal-matched
  direct CTA** (perf→"is site speed something you're looking at?", design→"is a refresh on your
  radar?", content→"is building out the site something you're thinking about?"); banned the vague
  "how are you thinking about the site" openers; (3) **anti-arrogance tone guardrail** (banned
  "evaluating you against your promise", "sizing you up", "judging you", "before they read a word").
- **`tone_flag` column** added to `assemble` output (and review CSVs) — flags the egregious
  arrogant framings for QA (the mild "deciding whether to trust <the process>" softie is left unflagged).
- Model-comparison artifacts: `data/model_comparison.csv`, `data/sonnet_v2_comparison.csv`,
  `scripts/build_comparison_csv.py`, outputs in `data/model_swap/`.

#### ✅ RUN COMPLETE (2026-07-08) — all 795 gradeable prospects generated & QA-clean
The full set is DONE. Every gradeable prospect (795; the ~204 INVALID sites are not messaged)
has a 3-message sequence in **`data/messages_v2.csv`** (full reasoning columns + `tone_flag`).
`python scripts/qa_check.py` (report mode, all 795) returns **0 flags** — tone, CTA, casing,
mechanics all clean.
- **How it ran:** the remaining 359 went through the **Batch API** (`generate_messages_api.py
  --batch`, one `msgbatch_…` job, -50%). The local poll got killed by the runtime cap twice, but
  the batch is cloud-side and survives — re-attach with **`scripts/finish_batch.py <batch_id>`**
  (fetches an ENDED batch, no long poll, so it can't be killed).
- **Batch-output quirk found & fixed deterministically (no mass regen):** Sonnet in batch mode
  frequently (~135/359) dropped the msg2 opener ("Hey {first-name}, quick context, we're a design
  and Webflow studio.") and sometimes capitalized case-study URL slugs (`/NewsCatcher` → a 404).
  `qa_check.det_fix()` now restores the opener, forces every message to contain `{first-name}`,
  lowercases all URLs, and fixes a CTA written with `.` instead of `?`. Only genuinely-vague CTAs
  / arrogant tone get an API regen (`wants_api()`); everything structural/mechanical is free.
- **`qa_check.py` is the standing QA tool** — `qa_check.py` (report) / `--fix` (correct), `--all`
  or `--domains`, and it auto-runs after every batch inside the runner. Reuse it before any send.
- **Note:** the SKILL prompt at `.claude/skills/generate-outreach/SKILL.md` is gitignored (under
  `.claude/`), so prompt changes are NOT in version control unless force-added.

### Who writes the messages (architecture)
- **Claude writes them, in the terminal session — NOT an LLM API.** We ran out of Gemini
  credits, and Claude's writing is better. Generation happens by invoking the
  **`/generate-outreach` skill**, which Claude executes directly.
- **`scripts/prep_bundles.py`** is the deterministic plumbing (no API):
  - `dump <enriched.csv> --limit N -o data/message_bundles.json` — pulls each gradeable
    prospect's full audit + a data dictionary into JSON for Claude to read.
  - `assemble <enriched.csv> data/message_results.json -o data/messages_v2.csv` — merges
    Claude's authored results back into a CSV and runs `sanitize()` (em-dash strip,
    `{first-name}` enforcement).
- **Flow:** `dump` → Claude reads bundles and writes `data/message_results.json` (the words
  are Claude's; JSON is just serialization) → `assemble` → `data/messages_v2.csv`.
- `scripts/message_generator.py` still holds the reused helpers `build_prospect`,
  `DATA_DICTIONARY`, `sanitize`, `_val`, `accurate_visits`, plus the **legacy** Gemini
  two-pass path (kept but not used).

### Writing philosophy (hard-won from user feedback)
1. **Lead with an INFERENCE about the prospect's business, not flattery.** The standout move
   — modeled on a cold email the user loved ("no big sales team → growth is probably referrals").
   Use the audit data to say something true and specific about how they grow / where the site
   stands, as a humble hypothesis ("i'd guess most of your signups arrive warm..."). The reader
   should think "huh, yeah." **Understanding outranks praise.**
2. **Positive / opportunity framing only.** Never judge their site, never pivot on surprise or
   disappointment, never sell with fear/loss. Frame every point as upside ("a faster site could
   convert more" not "your site is slow and losing you signups"). Always end forward.
3. **Grounded + concrete.** Positive does NOT mean vague. Name the ONE real thing from the audit
   (kindly, factually) and tie it to a concrete business outcome. When traffic is high, do the
   math out loud: at their scale, even a small conversion lift is a large, tangible number.
4. **Guardrails live in the master prompt, not a code blocklist.** A keyword-blocklist filter was
   tried and explicitly rejected by the user as "not prompt engineering." The skill's prompt
   carries the rules.

### Traffic = source of truth
Messages must quote **`apify_monthly_visits`** (fresh SimilarWeb), never the stale Crunchbase
`monthly_visits`. `accurate_visits(row)` (in `message_generator.py`) enforces this and is used by
`build_prospect` and `prep_bundles`. Don't use scale framing for genuinely low traffic even if it
trips the 10k `traffic_is_high` threshold (e.g. megaphone.xyz is really ~24k, not 3M).

### The 3-message sequence
1. **first_message** — the inference-led DM. Anatomy: a light human opener → the inference →
   the grounded observation + concrete outcome (with scale math) → a soft, forward CTA.
2. **second_message** — case-study follow-up (sent if no reply). Soft intro → case-study link on
   its own line → one line on the result that maps to THEIR problem → relevance tie-back → soft
   CTA. Modeled on a follow-up email the user liked.
3. **third_message** — a very short, low-key soft close (sent if still no reply). "looks like this
   isn't a priority right now, totally fair, reach out whenever it's back on your radar." This is
   the one place light no-pressure language is welcome.

### Case-study library + selection
- Source copy lives in `Copy/` (all 12 case studies; the concise registry is `Copy/Case Study
  Cards.md` — company, category, problem, exact headline metric).
- The skill embeds a **registry table** (company | category | "use when" | exact result | slug)
  and the rule: **match on the problem/signal pitched in message 1 first, then industry
  adjacency.** Always quote the case study's real metric exactly.
- URLs are `https://prismport.co/case-studies/<slug>`. **Slugs are derived from names and need
  human verification** — especially Wonder Phone (file is "Wondersimple").

### Hard rules (enforced by the skill prompt; `sanitize()` backstops two of them)
`{first-name}` is the only name token; never invent numbers/funding/customers; no judgment,
surprise, or fear framing; no buzzwords (world-class, seamless, etc.); no em/en dashes; lowercase
DM feel; performance wording must match the metric (load vs tap-responsiveness vs layout-shift);
only use traffic-scale framing if `traffic_is_high`; always end positive.

### Files
| Path | Role |
|------|------|
| `.claude/skills/generate-outreach/SKILL.md` | **Master prompt + procedure + case-study library** (source of truth for HOW we write) |
| `scripts/prep_bundles.py` | `dump` / `assemble` plumbing (no API) |
| `scripts/message_generator.py` | reused helpers (`build_prospect`, `accurate_visits`, `sanitize`, ...) + legacy Gemini path |
| `Copy/` | website copy incl. all case studies (`Case Study Cards.md` = the registry source) |
| `data/message_bundles.json` | dumped audit bundles (intermediate) |
| `data/message_results.json` | Claude's authored messages (intermediate) |
| `data/messages_v2.csv` | latest output: first/second/third messages + `case_study_name`/`case_study_url` |

### How to run
Say "generate outreach" (or `/generate-outreach`). Claude will `dump` → write the messages →
`assemble`. Point it at any enriched CSV with `--limit N`. Always verify case-study slugs resolve.

## Site Analysis Vertical (Deep Client Understanding)

A separate use case from the bulk outreach pipeline. Given a SINGLE company URL, it
produces an in-depth **business-analyst report** — what the business does, who it
serves, how it makes money, how it grows, its proof points — plus a site-improvement
audit. Used to understand a prospective client's business in depth before we engage.

### Architecture (mirrors `/generate-outreach`)
Deterministic plumbing builds a bundle; **Claude (in-session) writes the report.** No
LLM API is used for the report writing itself (the graders still use Gemini).
- **`scripts/site_crawler.py`** — page discovery + prioritization. Sitemap.xml (+ robots
  + index recursion) and a single rendered-homepage Playwright link harvest; categorizes
  by first path segment (home/about/product/pricing/customers/...), caps noisy categories
  (blog/docs/customers), returns ~20–30 prioritized pages. No LLM.
- **`scripts/analyze_site.py`** — orchestrator. Crawl → Jina-extract each page →
  grade key pages (homepage + product/pricing) with the existing `capture_screenshot_and_content`
  + `analyze_design_with_gemini` + `analyze_content_with_llm` → `detect_tech_stack` →
  `extract_proud_facts`. Writes `data/analysis/<slug>/bundle.json` (+ per-page screenshots).
  Resilient per-page; re-run overwrites.
- **`.claude/skills/analyze-site/SKILL.md`** — the analyst master prompt: persona,
  report structure (14 sections — business analysis 1–8, site audit 9, then the sales plan:
  improvement opportunities/pitch, engagement opportunity, discovery questions, and an
  **always-included Webflow-migration cost estimate** §13), PRICING GUIDANCE bands, and hard
  rules (cite evidence, label inferences, quote proud_facts exactly, opportunity-framed audit,
  **write with explanatory depth — not terse bullets**). Source of truth for HOW.

### How to run
```bash
python scripts/site_crawler.py https://example.com           # preview the page list
python scripts/analyze_site.py https://example.com --max-pages 25
python scripts/analyze_site.py https://example.com --skip-grader   # fast, text-only
```
Then say `/analyze-site <url>` (or "analyze this site") → Claude builds the bundle,
reads it, and writes `data/analysis/<slug>/report.md`.

### Reused (do not fork)
`extract_content`/`detect_error_page`/`analyze_content_with_llm`/`extract_proud_facts`
(`content_extractor.py`); `capture_screenshot_and_content`/`analyze_design_with_gemini`/
`clean_domain` (`website_grader.py`); `detect_tech_stack` (`wordpress_detector.py`).

### Later (web app phase)
The skill prompt is the seam: a future `scripts/analyze_writer.py` would send the SKILL
prompt (as system) + `bundle.json` (as payload) to the **Claude API** to produce the
report with no other change. Needs `ANTHROPIC_API_KEY` + `anthropic` added then. Not built yet.

## Project Overview

Cold outreach system for WordPress → Webflow migrations targeting SaaS/tech startups ($10-20K deals). The system enriches company data with signals and grades websites for prioritization.

## Three Signal Sets

1. **Signal 1: Funded + WordPress** - Series A/B companies ($3-30M) still on WordPress
2. **Signal 2: Traffic + Speed** - 50K+ monthly visitors with PageSpeed mobile score < 50 (PRIORITY)
3. **Signal 3: Modern Stack + Old Site** - Using premium analytics tools (Segment/Amplitude/Mixpanel) but still on WordPress

## Current Status

### Completed
- **Column utilities** (`scripts/column_utils.py`) - Auto-detects column names (Website/Domain, Company Name/Name, traffic columns) for flexible CSV input
- **Tech stack detector** (`scripts/wordpress_detector.py`) - Detects 25+ technologies including WordPress, Webflow, Wix, Squarespace, Shopify, React, Next.js, Vue, and more
- **Marketing stack detector** - Detects analytics tools (Segment, Amplitude, Mixpanel, HubSpot, etc.) and ad pixels (Google Ads, Facebook, LinkedIn, etc.)
- **PageSpeed checker** (`scripts/pagespeed_checker.py`) - Gets mobile + desktop scores via Google API, includes Core Web Vitals (FCP, LCP, CLS)
- **Traffic checker** (`scripts/traffic_checker.py`) - Gets monthly visits via SimilarWeb/Apify API OR uses existing CSV data
- **Website grader** (`scripts/website_grader.py`) - Parallel Playwright screenshots + Gemini Vision for design scoring, hybrid content scoring (programmatic + LLM), deviation detection
- **Content extractor** (`scripts/content_extractor.py`) - Jina AI Reader API for clean markdown content extraction + hybrid scoring system
- **Orchestrator** (`scripts/orchestrator.py`) - Runs all scripts on a CSV, outputs enriched data, supports resume from interrupted runs

### Not Yet Built
- **Data combiner** - Merge multiple enrichment runs

> Note: the **Message generator is built** — now Claude-written via the `/generate-outreach`
> skill. See the "Outreach Messaging System" section above.

### Known Limitations
- Traffic API requires paid Apify subscription after trial (not needed if CSV already has traffic data)
- Some sites block Playwright (Cloudflare, bot detection)
- Jina AI has rate limits (20 req/min without API key, 200 req/min with free API key)
- Gemini API has rate limits - may get 429 errors when processing many sites quickly

## How to Run

```bash
# Setup (first time)
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium

# Run full enrichment (auto-detects column names)
source venv/bin/activate
python scripts/orchestrator.py crunchbase.csv      # Uses Domain column
python scripts/orchestrator.py app.csv             # Uses Website column

# Resume a previous run (prompts: Resume/Fresh/Quit)
python scripts/orchestrator.py crunchbase.csv      # Detects previous run automatically

# Auto-resume without prompting
python scripts/orchestrator.py crunchbase.csv --resume

# Run with limit (for testing)
python scripts/orchestrator.py crunchbase.csv --limit 5

# Skip expensive API calls
python scripts/orchestrator.py crunchbase.csv --skip-traffic   # Skip SimilarWeb (ignored if CSV has traffic)
python scripts/orchestrator.py crunchbase.csv --skip-grader    # Skip Gemini Vision

# Run website grader standalone
python scripts/website_grader.py crunchbase.csv --limit 5

# Skip Jina AI content extraction (use Playwright + heuristics)
python scripts/website_grader.py crunchbase.csv --skip-jina

# Skip LLM content analysis (use heuristic scoring)
python scripts/website_grader.py crunchbase.csv --skip-content-llm

# Test content extractor standalone
python scripts/content_extractor.py https://example.com
python scripts/content_extractor.py https://example.com --analyze  # With hybrid scoring

# Run individual scripts
python scripts/wordpress_detector.py crunchbase.csv
python scripts/pagespeed_checker.py crunchbase.csv
python scripts/traffic_checker.py crunchbase.csv

# Run flag checker on existing enriched files
python scripts/flag_checker.py                                    # Flags most recent enriched file
python scripts/flag_checker.py data/enriched_20260201_180319.csv  # Flags specific file
python scripts/flag_checker.py data/enriched_*.csv --in-place     # Overwrites original file
python scripts/flag_checker.py --list                              # List available enriched files
```

## Project Structure

```
crunchbase.csv             # Input: Companies with Domain column + traffic data
app.csv                    # Input: Older format with Website column
.env                       # PAGESPEED_API_KEY, APIFY_TOKEN, GEMINI_API_KEY, JINA_API_KEY

/scripts
  orchestrator.py          # Main entry point - runs all checks
  column_utils.py          # Column auto-detection utilities
  wordpress_detector.py    # Tech stack + marketing detection
  pagespeed_checker.py     # PageSpeed scores (mobile + desktop)
  traffic_checker.py       # Traffic data via SimilarWeb/Apify (or from CSV)
  website_grader.py        # Screenshots + Gemini Vision + hybrid content scoring
  content_extractor.py     # Jina AI extraction + hybrid scoring (programmatic + LLM)
  flag_checker.py          # Data quality flagging for existing enriched CSVs

/data
  enriched_*.csv           # Full enrichment output files
  graded_*.csv             # Grading-only output files

/screenshots               # Website screenshots for design analysis
/logs                      # AI request logs (content + design analysis with score calculations)
```

## Resume Feature

The orchestrator supports resuming interrupted runs. Progress is saved every 5 entries, so you never lose more than 5 entries of work if stopped.

### How It Works

1. **Auto-detection**: When you run the orchestrator, it checks for existing `data/enriched_*.csv` files
2. **Progress check**: Loads the latest file and counts entries with `letter_grade` (fully processed)
3. **User prompt**: Asks what to do:
   ```
   ============================================================
   PREVIOUS RUN DETECTED
   ============================================================
     File: data/enriched_20260201_180319.csv
     Progress: 115/999 entries completed
     Remaining: 884 entries

   Options:
     [R] Resume from where we left off
     [F] Start fresh (overwrite previous progress)
     [Q] Quit
   ```
4. **Resume**: Loads existing results and continues from the next unprocessed entry
5. **Saves to same file**: Continues updating the same CSV file

### Usage

```bash
# Interactive mode - prompts you to choose
python scripts/orchestrator.py crunchbase.csv

# Auto-resume without prompting
python scripts/orchestrator.py crunchbase.csv --resume
```

### Incremental Saving

- Progress is saved every **5 entries** (configurable via `SAVE_INTERVAL`)
- Saves happen during processing, not just at the end
- If interrupted, resume picks up from the last saved entry

## Flexible Column Detection

All scripts auto-detect column names, supporting multiple CSV formats:

| Internal Name | Recognized Column Names |
|---------------|------------------------|
| website | Domain, Website, URL, Site, Homepage |
| company_name | Name, Company Name, Organization, Company |
| monthly_visits | Monthly Visits, Visits, Monthly Traffic |
| bounce_rate | Bounce Rate |
| global_rank | Global Traffic Rank, Global Rank, Rank |

**Auto-detection in action:**
```
$ python scripts/orchestrator.py crunchbase.csv --limit 2
Detected website column: 'Domain'
Detected company column: 'Name'
CSV already contains traffic data - will use existing data instead of Apify
```

**Traffic data handling:**
- If CSV has `Monthly Visits` (or similar) column, it uses that data directly
- If no traffic data in CSV, it fetches from SimilarWeb via Apify (requires APIFY_TOKEN)
- The `--skip-traffic` flag only applies when fetching from Apify

## Error Page Detection

The system automatically detects 404 pages, error pages, and placeholder pages before sending content to the AI for analysis. This saves API costs and properly flags broken/unavailable sites.

### Detection Logic

1. **Content is extracted** via Jina AI
2. **Pattern matching** checks for error indicators:
   - 404 / Page not found
   - "Page doesn't exist" / "has been moved"
   - Under construction / Coming soon
   - Site maintenance
   - Access denied / Forbidden
3. **If error detected:**
   - `is_error_page` = True
   - `error_type` = 404, maintenance, coming_soon, access_denied, empty, or error
   - `content_score` = 0
   - AI content analysis is **skipped** (saves API cost)

### Patterns Detected

```python
ERROR_PAGE_PATTERNS = [
    r'\b404\b',                                    # Literal "404"
    r'page\s+not\s+found',                         # "page not found"
    r'page.{0,30}(doesn.t|does\s*not)\s+exist',   # "page ... doesn't exist"
    r'page.{0,30}(moved|removed|deleted)',         # "page has been moved"
    r'under\s*construction',                       # "under construction"
    r'coming\s*soon',                              # "coming soon"
    r'site.{0,20}maintenance',                     # "site maintenance"
    # ... more patterns
]
```

### Example Log Entry
```
ERROR PAGE DETECTED
TIMESTAMP: 2026-01-31T15:21:07.735983
URL: www.terrainbiosciences.com
ERROR TYPE: 404
REASON: Pattern matched: 'page.{0,30}(doesn.t|does\s*not)\s+exist' in short content (12 words)
WORD COUNT: 12
CONTENT PREVIEW: The page you are looking for doesn't exist or has been moved....
```

## Content Scoring System (Hybrid)

The content scoring uses a **hybrid approach** combining programmatic detection with LLM evaluation. This ensures thin content is automatically penalized while quality assessment is done by the LLM.

### Final Score Formula
```
Content Score = Programmatic (0-30) + LLM (0-70) = 0-100
```

### Programmatic Score (30 points max)

Calculated in `content_extractor.py:calculate_programmatic_score()`. Objective metrics with no LLM involvement:

**Word Count Score (0-20 points):**
| Word Count | Points |
|------------|--------|
| < 150      | 0      |
| 150-299    | 5      |
| 300-499    | 10     |
| 500-799    | 15     |
| 800+       | 20     |

**Key Elements Score (0-10 points, +2 each):**

| Element | Detection Patterns |
|---------|-------------------|
| Pricing | `$`, `pricing`, `price`, `cost`, `plans`, `/month`, `/year`, `free trial`, `free plan`, `starter`, `enterprise`, `per user` |
| Testimonials | `testimonial`, `review`, `customer said`, quoted text 20+ chars, `★`, `⭐`, `stars` |
| Case Studies | `case stud`, `success stor`, `customer stor`, `how * helped`, `helped * achieve`, `results for`, `worked with` |
| Specific Numbers | `X+ customers/clients/users`, `X%`, `Xx`, `$Xk/m`, `X million/billion`, `increased/reduced by X` |
| CTA | `get started`, `sign up`, `start free`, `book a demo`, `schedule a call`, `contact us`, `request a quote`, `try free`, `start now`, `join now`, `subscribe`, `download` |

### LLM Score (70 points max)

The LLM rates 4 dimensions on a 1-10 scale. Raw total (4-40) is scaled to 0-70.

**Formula:** `LLM Score = (clarity + substance + credibility + persuasiveness) / 40 * 70`

**The exact prompt sent to Gemini (in `content_extractor.py:get_llm_content_ratings()`):**

```
Rate this website content on 4 dimensions. Give a score from 1-10 for each.

CONTENT ({word_count} words):
{content}

---

RATE EACH DIMENSION (1-10):

1. CLARITY: Can a visitor immediately understand what this company does and offers?
   - 1-2: Completely unclear, only vague buzzwords ("We provide innovative solutions for digital transformation")
   - 3-4: Very unclear, generic statements without specifics
   - 5-6: Somewhat clear but still generic ("We build websites for businesses")
   - 7-8: Clear offering with some specifics ("We build e-commerce websites for retail brands")
   - 9-10: Crystal clear and specific ("We build Shopify stores for DTC brands, $5-15K, 4-week delivery")

2. SUBSTANCE: Does it provide real, useful information beyond marketing fluff?
   - 1-2: Empty marketing speak only, no real information at all
   - 3-4: Mostly buzzwords with minimal substance
   - 5-6: Some information but surface-level, missing key details
   - 7-8: Good amount of useful info - features, process, or use cases explained
   - 9-10: Comprehensive - detailed features, how it works, pricing, documentation, examples

3. CREDIBILITY: Does it build trust with proof and specifics?
   - 1-2: No proof at all, generic claims ("We're the best", "Industry leading")
   - 3-4: Only partner logos or vague claims
   - 5-6: Some social proof but weak (unnamed testimonials, generic stats)
   - 7-8: Good proof - named clients, specific testimonials, some results
   - 9-10: Strong proof - specific results ("Helped Acme increase revenue 40%"), detailed case studies, named customers

4. PERSUASIVENESS: Is it compelling? Does it motivate action?
   - 1-2: No reason to choose them, no differentiation, no urgency
   - 3-4: Weak value proposition, unclear why to act
   - 5-6: Some benefits listed but not compelling
   - 7-8: Clear value proposition, good differentiation, decent CTA
   - 9-10: Compelling story, strong differentiation, urgent CTA, clear next steps

---

Return ONLY valid JSON (no markdown, no explanation):
{"clarity": <1-10>, "substance": <1-10>, "credibility": <1-10>, "persuasiveness": <1-10>, "analysis": "<1 sentence summary>"}
```

### Example Score Calculation

**shiftavenue.com (thin content site):**
```
Word count: 167 → 5 points (150-299 range)
Key elements: 0/5 detected → 0 points
Programmatic total: 5/30

LLM ratings: Clarity 7, Substance 5, Credibility 6, Persuasiveness 7
LLM raw: 25/40 → scaled to (25/40) * 70 = 43.75/70

FINAL: 5 + 43.75 = 48/100
```

**stripe.com (comprehensive content):**
```
Word count: 3195 → 20 points (800+)
Key elements: 5/5 detected → 10 points
Programmatic total: 30/30

LLM ratings: Clarity 10, Substance 10, Credibility 9, Persuasiveness 9
LLM raw: 38/40 → scaled to (38/40) * 70 = 66.5/70

FINAL: 30 + 66.5 = 96/100
```

## Design Scoring System

Design scoring uses Gemini Vision to analyze screenshots. The prompt in `website_grader.py:analyze_design_with_gemini()`:

```
You are a senior design director at a top-tier design studio.
Evaluate ONLY visual design professionalism from this website screenshot.
Ignore content quantity.
Be critical.

Score 0-100 for professional polish, sophistication, hierarchy, typography, spacing, visual clarity, and brand craft.

Consider: sophistication, intentionality, polish, hierarchy, typography, spacing, visual clarity, brand craft.
Be critical: simple/minimal does NOT automatically mean professional.

URL: {url}

Return ONLY valid JSON in this exact format:
{"design_score": <0-100>, "comment": "<one detailed sentence about the design>"}
```

## Overall Grading Logic

**Total Grade Formula:**
```
Total = Performance (30%) + Content (40%) + Design (30%)
```

**Grade Thresholds:**
- A+: 95+ | A: 90+ | A-: 85+
- B+: 80+ | B: 75+ | B-: 70+
- C+: 65+ | C: 60+ | C-: 55+
- D+: 50+ | D: 45+ | D-: 40+
- F: Below 40

**Important:** If any factor (performance, content, design) has an error, NO grade is assigned. The error is shown instead.

## Output Columns

### Tech & Marketing
| Column | Description |
|--------|-------------|
| tech_stack | Primary detected technology (e.g., wordpress, webflow, next.js) |
| all_tech_detected | All technologies found on the site |
| is_wordpress | Boolean - site uses WordPress |
| marketing_tools | Detected marketing/analytics tools |
| ad_pixels | Detected advertising pixels |
| has_premium_analytics | Uses premium analytics (Segment, Amplitude, etc.) |

### Performance
| Column | Description |
|--------|-------------|
| pagespeed_mobile | Mobile performance score (0-100) |
| pagespeed_desktop | Desktop performance score (0-100) |
| mobile_fcp | First Contentful Paint (seconds) |
| mobile_lcp | Largest Contentful Paint (seconds) |
| mobile_cls | Cumulative Layout Shift |
| desktop_fcp/lcp/cls | Same metrics for desktop |

### Traffic
| Column | Description |
|--------|-------------|
| monthly_visits | Monthly visitors from SimilarWeb |
| global_rank | Global website ranking |
| bounce_rate | Visitor bounce rate (%) |
| pages_per_visit | Average pages per visit |
| traffic_source_direct/search/social | Traffic sources breakdown (%) |
| top_country | Top traffic country |
| is_signal_2_traffic | Has 50K+ monthly visits |

### Grading
| Column | Description |
|--------|-------------|
| performance_score | PageSpeed score used in grading (defaults to 50 if not available) |
| content_score | Hybrid content score (0-100) = Programmatic + LLM |
| design_score | AI design analysis score (0-100) via Gemini Vision |
| total_grade_score | Weighted: 30% perf, 40% content, 30% design |
| letter_grade | A+ to F |
| grade_analysis | e.g., "Excellent design, Good content, Poor performance" |
| weak_areas | Areas below threshold (e.g., "performance, content") |
| strong_areas | Areas above threshold (e.g., "design") |
| design_comment | AI comment on design quality |

### Content Scoring Breakdown
| Column | Description |
|--------|-------------|
| content_analysis | 1-sentence AI summary of content quality |
| programmatic_score | Programmatic portion (0-30): word count + key elements |
| llm_score | LLM portion (0-70): scaled from 4 dimension ratings |
| clarity | LLM rating (1-10): Can visitors understand what you do? |
| substance | LLM rating (1-10): Real info vs marketing fluff? |
| credibility | LLM rating (1-10): Trust signals and proof? |
| persuasiveness | LLM rating (1-10): Compelling and actionable? |
| content_word_count | Word count of extracted content |

### Error Page Detection
| Column | Description |
|--------|-------------|
| is_error_page | Boolean - True if 404/error/placeholder page detected |
| error_type | Type of error: 404, maintenance, coming_soon, access_denied, empty |

### Errors
| Column | Description |
|--------|-------------|
| enrichment_errors | Combined errors from all checks |

### Data Quality Flags
| Column | Description |
|--------|-------------|
| flag_count | Number of data quality issues detected for this entry |
| flag_reasons | Semicolon-separated list of flag codes explaining issues |

**Available Flags:**
| Flag Code | Description |
|-----------|-------------|
| `error_page:404` | 404 page / page not found |
| `error_page:maintenance` | Site under maintenance |
| `error_page:coming_soon` | Coming soon page |
| `error_page:access_denied` | Access denied / blocked |
| `error_page:empty` | Empty or minimal content |
| `error_page:error` | Generic error page |
| `no_url` | No valid URL provided |
| `tech_error` | Failed to detect tech stack |
| `pagespeed_mobile_error` | PageSpeed mobile API error |
| `pagespeed_desktop_error` | PageSpeed desktop API error |
| `grader_error` | Website grading failed |
| `missing_pagespeed` | No PageSpeed data (both mobile & desktop) |
| `missing_traffic` | No traffic data available |
| `content_score_zero` | Content score is 0 (not error page) - suspicious |
| `design_score_zero` | Design score is 0 (not error page) - suspicious |
| `content_score_perfect` | Content score is 100 - suspicious |
| `design_score_perfect` | Design score is 100 - suspicious |
| `llm_all_ones` | LLM gave all 1s (lowest scores) - suspicious |
| `llm_all_tens` | LLM gave all 10s (highest scores) - suspicious |
| `missing_content_score` | Content score missing despite screenshot |
| `missing_design_score` | Design score missing despite screenshot |
| `missing_letter_grade` | Letter grade missing despite scores |

**Filtering Flagged Entries:**
```python
import pandas as pd
df = pd.read_csv('data/enriched_*.csv')

# Find all flagged entries
flagged = df[df['flag_count'] > 0]

# Find entries with specific issues
zero_scores = df[df['flag_reasons'].str.contains('score_zero', na=False)]
error_pages = df[df['flag_reasons'].str.contains('error_page', na=False)]
missing_data = df[df['flag_reasons'].str.contains('missing_', na=False)]

# Find clean entries (no flags)
clean = df[df['flag_count'] == 0]
```

## Tech Stack Detection

Detects the following technologies:

- **CMS/Builders**: WordPress, Webflow, Wix, Squarespace, Shopify, Ghost, Drupal, Joomla, HubSpot, Framer, Contentful
- **JS Frameworks**: React, Next.js, Gatsby, Vue, Nuxt, Angular, Svelte
- **Static Generators**: Hugo, Jekyll, Eleventy
- **E-commerce**: Magento, BigCommerce, WooCommerce

## AI Services Used

| Service | Purpose | API |
|---------|---------|-----|
| **Google Gemini 2.5 Flash** | Design scoring (vision) + Content scoring (text) | `google-generativeai` Python SDK |
| **Jina AI Reader** | Extracts clean text from websites | REST API (`r.jina.ai`) |

**Per-website API calls:**
- 1x Jina AI (content extraction)
- 1x Gemini (content analysis) - skipped if error page detected
- 1x Gemini (design analysis from screenshot)

**No OpenAI/ChatGPT** - the tool uses Gemini only for all AI tasks.

## API Keys Required

Store in `.env` file:
```
PAGESPEED_API_KEY=xxx    # Google Cloud Console (optional, increases rate limit)
APIFY_TOKEN=xxx          # Apify Console (only needed if CSV lacks traffic data)
GEMINI_API_KEY=xxx       # Google AI Studio (required for grading)
JINA_API_KEY=xxx         # Jina AI (optional, increases rate limits from 20 to 200 req/min)
```

## Log Files

All AI requests are logged to `logs/ai_requests_<timestamp>.log` including:
- Content sent to Gemini for analysis
- Design analysis prompts and screenshots
- LLM responses
- Score calculation breakdowns (programmatic + LLM)
- Error page detections
- Errors

**Content Analysis Log Example:**
```
CONTENT ANALYSIS REQUEST
TIMESTAMP: 2026-01-31T15:23:06
URL: www.soldera.org/
WORD COUNT: 1004

--- CONTENT SENT TO GEMINI ---
[Full extracted content...]
--- END CONTENT ---

--- GEMINI RESPONSE ---
{"clarity": 9, "substance": 9, "credibility": 9, "persuasiveness": 9, "analysis": "..."}
--- END RESPONSE ---

--- SCORE CALCULATION ---
Programmatic: 28/30
  - Word count (1004): 20/20
  - Key elements: 8/10
LLM: 63.0/70
  - Clarity: 9/10, Substance: 9/10, Credibility: 9/10, Persuasiveness: 9/10
FINAL SCORE: 91/100
--- END CALCULATION ---
```

**Design Analysis Log Example:**
```
TIMESTAMP: 2026-01-31T15:23:17
URL: www.soldera.org/
SCREENSHOT: /path/to/screenshots/soldera_org.png
IMAGE SIZE: 852.7 KB

--- PROMPT SENT TO GEMINI ---
[Design analysis prompt...]
--- END PROMPT ---

--- GEMINI RESPONSE ---
{"design_score": 65, "comment": "..."}
--- END RESPONSE ---
```

**Error Page Detection Log Example:**
```
ERROR PAGE DETECTED
TIMESTAMP: 2026-01-31T15:21:07
URL: www.terrainbiosciences.com
ERROR TYPE: 404
REASON: Pattern matched in short content (12 words)
CONTENT PREVIEW: The page you are looking for doesn't exist...
```

## Key Files Explained

### `scripts/column_utils.py`
- `get_website_column(df)` - Auto-detect website/domain column
- `get_company_column(df)` - Auto-detect company name column
- `has_traffic_data(df)` - Check if CSV already has traffic data
- `extract_existing_traffic_data(row, df)` - Parse traffic data from CSV columns

### `scripts/content_extractor.py`
- `extract_content(url)` - Calls Jina AI Reader API to get clean markdown
- `detect_error_page(content, word_count)` - Detects 404/error pages via pattern matching
- `calculate_programmatic_score(content)` - Calculates word count + key elements (0-30)
- `get_llm_content_ratings(content)` - Gets 4 LLM dimension scores (1-10 each)
- `analyze_content_with_llm(content)` - Combines error detection + programmatic + LLM into final score

### `scripts/website_grader.py`
- `capture_screenshot_and_content(url)` - Playwright screenshot capture with retry logic
- `analyze_design_with_gemini(screenshot)` - Gemini Vision design analysis
- `grade_website(url)` - Orchestrates content + design scoring
- `process_csv_async(input)` - Processes CSV with parallel browser execution

### `scripts/orchestrator.py`
- `run_enrichment(input_path)` - Main entry point, runs all checks per-entry
- `find_latest_enrichment(data_dir)` - Finds most recent enriched CSV for resume
- `load_existing_results(enriched_path)` - Loads previous results and determines last processed entry
- `prompt_resume_or_fresh()` - Interactive prompt for resume/fresh/quit
- `save_progress()` - Saves intermediate results every 5 entries
- `flag_entry(result)` - Analyzes entry for data quality issues, returns (flag_count, flag_reasons)
- Creates log file for all AI requests
- Handles flexible column detection and traffic data from CSV
- Supports `--resume` flag for auto-resume without prompting

### `scripts/flag_checker.py`
- `check_flags(input_path)` - Run flagging on existing enriched CSV files
- `list_enriched_files()` - List available enriched CSVs in data directory
- Standalone script to flag existing data without re-running enrichment
- Uses same `flag_entry()` logic as orchestrator for consistency
- Options: `--in-place` to overwrite, `-o` for custom output, `--list` to show files

## Next Steps

1. Build message generator for personalized outreach (using extracted content)
2. Build data combiner for merging multiple enrichment runs
3. Add CRM export functionality
