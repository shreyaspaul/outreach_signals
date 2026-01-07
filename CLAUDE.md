# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Cold outreach system for WordPress → Webflow migrations targeting SaaS/tech startups ($10-20K deals). The system enriches company data with signals and grades websites for prioritization.

## Three Signal Sets

1. **Signal 1: Funded + WordPress** - Series A/B companies ($3-30M) still on WordPress
2. **Signal 2: Traffic + Speed** - 50K+ monthly visitors with PageSpeed mobile score < 50 (PRIORITY)
3. **Signal 3: Modern Stack + Old Site** - Using premium analytics tools (Segment/Amplitude/Mixpanel) but still on WordPress

## Current Status

### Completed
- **Tech stack detector** (`scripts/wordpress_detector.py`) - Detects 25+ technologies including WordPress, Webflow, Wix, Squarespace, Shopify, React, Next.js, Vue, and more
- **Marketing stack detector** - Detects analytics tools (Segment, Amplitude, Mixpanel, HubSpot, etc.) and ad pixels (Google Ads, Facebook, LinkedIn, etc.)
- **PageSpeed checker** (`scripts/pagespeed_checker.py`) - Gets mobile + desktop scores via Google API, includes Core Web Vitals (FCP, LCP, CLS)
- **Traffic checker** (`scripts/traffic_checker.py`) - Gets monthly visits via SimilarWeb/Apify API
- **Website grader** (`scripts/website_grader.py`) - Parallel Playwright screenshots + Gemini Vision for design scoring, heuristic content scoring, deviation detection
- **Orchestrator** (`scripts/orchestrator.py`) - Runs all scripts on a CSV, outputs enriched data

### Not Yet Built
- **Improved content scoring** - Sitemap-based analysis for better accuracy
- **Message generator** - AI-powered personalization
- **Data combiner** - Merge multiple enrichment runs

### Known Limitations
- Content scoring is heuristic-based (word count, headings) - doesn't assess actual quality
- Traffic API requires paid Apify subscription after trial
- Some sites block Playwright (Cloudflare, bot detection)

## How to Run

```bash
# Setup (first time)
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium

# Run full enrichment
source venv/bin/activate
python scripts/orchestrator.py app.csv

# Run with limit (for testing)
python scripts/orchestrator.py app.csv --limit 5

# Skip expensive API calls
python scripts/orchestrator.py app.csv --skip-traffic   # Skip SimilarWeb
python scripts/orchestrator.py app.csv --skip-grader    # Skip Gemini Vision

# Run website grader standalone
python scripts/website_grader.py app.csv --limit 5

# Run individual scripts
python scripts/wordpress_detector.py app.csv
python scripts/pagespeed_checker.py app.csv
python scripts/traffic_checker.py app.csv
```

## Project Structure

```
app.csv                    # Input: 135 companies with Website column
.env                       # PAGESPEED_API_KEY, APIFY_TOKEN, GEMINI_API_KEY
requirements.txt           # pandas, requests, python-dotenv, apify-client, playwright, google-generativeai

/scripts
  orchestrator.py          # Main entry point - runs all checks
  wordpress_detector.py    # Tech stack + marketing detection
  pagespeed_checker.py     # PageSpeed scores (mobile + desktop)
  traffic_checker.py       # Traffic data via SimilarWeb/Apify
  website_grader.py        # Screenshots + Gemini Vision for grading

/data
  enriched_*.csv           # Full enrichment output files
  graded_*.csv             # Grading-only output files

/screenshots               # Website screenshots for design analysis
/logs                      # Gemini API request logs
/specs                     # Feature specifications
```

## Tech Stack Detection

Detects the following technologies:

- **CMS/Builders**: WordPress, Webflow, Wix, Squarespace, Shopify, Ghost, Drupal, Joomla, HubSpot, Framer, Contentful
- **JS Frameworks**: React, Next.js, Gatsby, Vue, Nuxt, Angular, Svelte
- **Static Generators**: Hugo, Jekyll, Eleventy
- **E-commerce**: Magento, BigCommerce, WooCommerce

## Output Columns Added

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
| performance_score | PageSpeed score used in grading |
| content_score | Heuristic content score (0-100) |
| design_score | AI design analysis score (0-100) |
| total_grade_score | Weighted: 30% perf, 40% content, 30% design |
| letter_grade | A+ to F |
| grade_analysis | e.g., "Excellent design, Good content, Poor performance" |
| weak_areas | Areas below threshold (e.g., "performance, content") |
| strong_areas | Areas above threshold (e.g., "design") |
| design_comment | AI comment on design quality |
| grader_error | Any errors during grading |

### Errors
| Column | Description |
|--------|-------------|
| enrichment_errors | Combined errors from all checks |

## Grading Logic

**Weights:** Performance 30%, Content 40%, Design 30%

**Grade Thresholds:**
- A+: 95+ | A: 90+ | A-: 85+
- B+: 80+ | B: 75+ | B-: 70+
- C+: 65+ | C: 60+ | C-: 55+
- D+: 50+ | D: 45+ | D-: 40+
- F: Below 40

**Important:** If any factor (performance, content, design) has an error, NO grade is assigned. The error is shown instead.

## API Keys Required

Store in `.env` file:
```
PAGESPEED_API_KEY=xxx    # Google Cloud Console
APIFY_TOKEN=xxx          # Apify Console
GEMINI_API_KEY=xxx       # Google AI Studio
```

## Next Steps

1. Improve content scoring with sitemap-based analysis
2. Build message generator for personalized outreach
3. Build data combiner for merging multiple enrichment runs
4. Add CRM export functionality
