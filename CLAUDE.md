# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Last Session Context (2026-02-03)

### What Was Done
1. **Created Cloud Deployment Spec** (`specs/cloud-deployment-spec.md`)
   - Researched cheapest cloud options for running Python + Playwright
   - Recommended Railway.app (~$10-12/month) with Slack Bot integration
   - Full implementation plan with Dockerfile, Slack bot code, architecture diagram
   - Includes `/enrich` and `/status` slash commands, progress updates every 50 entries

2. **Added Data Quality Flagging System**
   - Added `flag_entry()` function to `orchestrator.py` that detects anomalies
   - New output columns: `flag_count` (number of issues) and `flag_reasons` (semicolon-separated codes)
   - Flags: error pages, missing data, zero scores, perfect 100 scores, API errors, extreme LLM scores
   - Prints flag summary at end of enrichment run

3. **Created Standalone Flag Checker** (`scripts/flag_checker.py`)
   - Runs flagging on existing enriched CSV files without re-running enrichment
   - Usage: `python scripts/flag_checker.py` (flags most recent file)
   - Options: `--in-place` to overwrite, `-o` for custom output, `--list` to show files
   - Tested on 999-entry file: found 783 flagged (78.4%), 216 clean (21.6%)

### Current State
- User has an ongoing enrichment run: `data/enriched_20260201_180319.csv` with ~340/999 entries completed
- Flagged version created at: `data/enriched_20260201_180319_flagged.csv`
- Most flags are `missing_traffic` and `missing_pagespeed` (entries not yet processed)

### Next Steps (User's Priority)
1. **Cloud Deployment** - Deploy to Railway.app with Slack integration (spec is ready)
2. Continue enrichment run to completion
3. Build message generator for personalized outreach
4. Build data combiner for merging multiple enrichment runs

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
- **Message generator** - AI-powered personalization using extracted content
- **Data combiner** - Merge multiple enrichment runs

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
