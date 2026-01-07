# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Cold outreach system for WordPress → Webflow migrations targeting SaaS/tech startups ($10-20K deals). The system enriches company data with signals and generates personalized outreach messages.

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
- **Orchestrator** (`scripts/orchestrator.py`) - Runs all scripts on a CSV, outputs enriched data

### Not Yet Built
- **Message generator** - AI-powered personalization
- **Data combiner** - Merge multiple enrichment runs

### Tested
- 1 entry test: Passed
- 5 entry test: Passed
- 10 entry test: Passed (found 2 WordPress sites, 2 Signal 2 targets)

## How to Run

```bash
# Setup (first time)
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Run enrichment on full dataset
source venv/bin/activate
python scripts/orchestrator.py app.csv

# Run with limit (for testing)
python scripts/orchestrator.py app.csv --limit 5

# Skip traffic check (saves Apify credits)
python scripts/orchestrator.py app.csv --skip-traffic

# Run individual scripts
python scripts/wordpress_detector.py app.csv
python scripts/pagespeed_checker.py app.csv
python scripts/traffic_checker.py app.csv
```

## Project Structure

```
app.csv                    # Input: 135 companies with Website column
.env                       # PAGESPEED_API_KEY, APIFY_TOKEN
requirements.txt           # pandas, requests, python-dotenv, apify-client

/scripts
  orchestrator.py          # Main entry point - runs all checks
  wordpress_detector.py    # Tech stack + marketing detection
  pagespeed_checker.py     # PageSpeed scores (mobile + desktop)
  traffic_checker.py       # Traffic data via SimilarWeb/Apify

/data
  enriched_*.csv           # Output files with timestamps
```

## Tech Stack Detection

Detects the following technologies:

- **CMS/Builders**: WordPress, Webflow, Wix, Squarespace, Shopify, Ghost, Drupal, Joomla, HubSpot, Framer, Contentful
- **JS Frameworks**: React, Next.js, Gatsby, Vue, Nuxt, Angular, Svelte
- **Static Generators**: Hugo, Jekyll, Eleventy
- **E-commerce**: Magento, BigCommerce, WooCommerce

## Output Columns Added

| Column | Description |
|--------|-------------|
| tech_stack | Primary detected technology (e.g., wordpress, webflow, next.js) |
| all_tech_detected | All technologies found on the site |
| is_wordpress | Boolean - site uses WordPress |
| marketing_tools | Detected marketing/analytics tools |
| ad_pixels | Detected advertising pixels |
| has_premium_analytics | Uses premium analytics (Segment, Amplitude, etc.) |
| pagespeed_mobile | Mobile performance score (0-100) |
| pagespeed_desktop | Desktop performance score (0-100) |
| mobile_fcp | First Contentful Paint (seconds) |
| mobile_lcp | Largest Contentful Paint (seconds) |
| mobile_cls | Cumulative Layout Shift |
| desktop_fcp/lcp/cls | Same metrics for desktop |
| monthly_visits | Monthly visitors from SimilarWeb |
| global_rank | Global website ranking |
| bounce_rate | Visitor bounce rate |
| traffic_source_direct/search/social | Traffic sources breakdown |
| is_signal_2_traffic | Has 50K+ monthly visits |
| enrichment_errors | Any errors encountered |

## Next Steps

1. Run full enrichment on all 135 entries
2. Build message generator for personalized outreach
3. Build data combiner for merging multiple enrichment runs
