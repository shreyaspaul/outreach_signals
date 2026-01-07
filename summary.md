Cold Outreach System - Technical Spec
Project Goal
Build a data extraction and outreach system for selling WordPress → Webflow migrations to SaaS/tech startups. Deal size: $10-20K. Start with LinkedIn outreach, validate signals, then automate.

Target Signals (Pick Best Performing)
Signal Set 1: Funded + WordPress

Raised $3M-30M (Series A/B) in last 12-18 months
Currently using WordPress
Why: Have budget, WordPress looks cheap post-funding

Signal Set 2: Traffic + Speed Problem

50K+ monthly visitors
PageSpeed score < 50 (mobile)
Why: Clear ROI - can calculate lost revenue from slow site

Signal Set 3: Modern Stack + Old Site

Using Segment/Amplitude/Mixpanel/HubSpot Premium
Site still on WordPress
Why: Budget proven (expensive tools), site is contradiction

Target: 100-200 leads per signal set for testing (300-600 total)

Data Structure
Company Data Needed
- company_name
- website_url
- industry
- employee_count (target: 20-500)
- funding_amount
- funding_date
- funding_stage (Series A/B/C)
- cms_technology (WordPress yes/no)
- monthly_traffic (for Signal 2)
- pagespeed_score_mobile (for Signal 2)
- modern_tools_used (for Signal 3)
- signal_set (1, 2, or 3)
People Data Needed
- person_name
- person_title (CMO, VP Marketing, Head of Growth, CEO if <50 employees)
- company
- linkedin_url
- email (optional - can add later)
Tracking Fields
- custom_message (AI-generated)
- date_contacted
- response_status (yes/no)
- meeting_booked (yes/no)
- notes

Data Sources (All Free)
For Company Data
Crunchbase (funding data)

Free trial: 7 days
Get: Companies, funding amount/date/stage, employee count, website
Export: CSV up to 1,000 companies
Filters: Series A/B, $3M-50M, last 12-18 months, SaaS/Software

Wappalyzer (WordPress detection)

Chrome extension (free)
Detects: CMS technology on any website
Alternative: Manual check - view source, search "wp-content"

SimilarWeb (traffic data - for Signal 2)

Chrome extension (free)
Shows: Monthly traffic estimates
Alternative: Ahrefs 7-day trial

PageSpeed Insights (speed scores - for Signal 2)

Website: pagespeed.web.dev (free, unlimited)
API available: 25,000 requests/day free
Get: Mobile performance score

BuiltWith (tech stack - for Signal 3)

Free tier: 50 lookups/month
Detects: Analytics/marketing tools (Segment, Amplitude, etc.)

For People Data
LinkedIn Sales Navigator

Free trial: 30 days
Search by: Job titles, company, seniority
Extract via: Phantombuster (free tier) or Instant Data Scraper (free extension)

Email Finding (optional)

Hunter.io: 25 free/month
Apollo.io: 50 free/month
Snov.io: 50 free trial
Total: 125 emails/month free


Automation Needs
Phase 1: Data Collection Scripts
Script 1: Crunchbase Export Processor

Input: Crunchbase CSV export
Process: Clean data, filter by geography, remove duplicates
Output: Google Sheet with company data

Script 2: WordPress Checker

Input: List of website URLs
Process:

Option A: Use Wappalyzer API (if available)
Option B: Scrape page source, search for "wp-content" or "wordpress"


Output: Add "is_wordpress: true/false" column

Script 3: PageSpeed Checker

Input: List of website URLs
Process: Call PageSpeed Insights API
Get: Mobile performance score
Output: Add "pagespeed_mobile" column
Note: Rate limit - batch in groups, add delays

Script 4: Traffic Checker

Input: List of website URLs
Process: Use SimilarWeb API (if available) or manual
Output: Add "monthly_traffic" column

Script 5: LinkedIn Data Scraper Setup

Tool: Phantombuster or custom scraper
Input: LinkedIn Sales Navigator search URL
Output: CSV with name, title, company, linkedin_url

Phase 2: Message Personalization
Script 6: Message Generator

Input: Company data + person data
Process: Use AI (Claude API or OpenAI) to generate personalized intro
Templates by signal set:
Signal 1 template variables: company_name, funding_amount, funding_date, person_name
Signal 2 template variables: company_name, monthly_traffic, pagespeed_score, person_name
Signal 3 template variables: company_name, modern_tools, person_name
Output: Add "custom_message" column

Phase 3: Tracking System
Script 7: Outreach Tracker

Google Sheet with formula columns for:

Days since contacted
Response rate by signal
Meeting booking rate
Next follow-up date (calculated)




Message Templates
Signal 1: Funded + WordPress
{person_name}, congrats on the {funding_stage} raise—${funding_amount}M is a great milestone.

One thing jumped out when I checked out {company_name}: you're still on WordPress. I'm guessing that's on the list to upgrade now that you're scaling up, especially with [enterprise customers/speed/dev team bandwidth].

We just migrated [Similar Company] from WordPress to Webflow in 4 weeks—cut their load time from 5.8s to 1.2s. Their demo requests increased 34% in the first month.

Worth a quick chat? No pitch, just curious what your roadmap looks like for the site.
Signal 2: Traffic + Speed
{person_name}, pulled up {company_name}'s site—you're doing serious traffic ({monthly_traffic}K/month from what I can see), but the PageSpeed score is rough ({pagespeed_score}).

Quick math: at your traffic level, a 4-second load time is costing you ~30-40% of mobile visitors before they even see your product. That's {calculated_lost_visitors} lost visitors/month.

We specialize in fixing exactly this for high-traffic sites. [Similar Company] went from 4.8s to 1.1s, saw demo requests jump 35%.

Open to a quick call this week?
Signal 3: Modern Stack + Old Site
{person_name}, noticed {company_name} is running {modern_tools}—that's a serious stack for a company your size.

But the site's still on WordPress. That's like having a Ferrari engine in a '98 Civic—your data infrastructure is modern, but the site it's tracking is outdated.

We just moved [Similar Company] from WordPress to Webflow. Cut load time 70%, and now their site actually matches the sophistication of their analytics.

Worth a conversation?

Week 1 Workflow (Manual Process to Validate)
Day 1-2: Get Company Data

Crunchbase trial → Export 500-1,000 funded SaaS companies
Run WordPress checker script on all URLs
Filter: Keep only WordPress = true
Expected output: 100-200 companies

Day 3: Get People Data

LinkedIn Sales Navigator trial
Search CMO/VP Marketing at target companies
Scrape via Phantombuster → Export CSV
Expected output: 100-200 decision makers

Day 4: Personalization

Run message generator script
Review first 10 messages manually (quality check)
Generate for all 100-200 leads

Day 5: Start Outreach

LinkedIn: View profiles (Day 1)
LinkedIn: Send connection requests (Day 2)
LinkedIn: Send personalized messages (Day 4)

Week 2-3: Repeat for Signal Set 2 and 3

Success Metrics
Track weekly:

Leads contacted
Response rate (target: 10-20%)
Meeting booking rate (target: 40-50% of responses)
Best performing signal set

Do not track:

Profile views (vanity metric)
Connection acceptance alone

After 3 weeks: Identify winning signal, build automation for that one only

Technical Requirements for Scripts
Language: Python preferred (for API calls, data processing)
Libraries needed:

pandas - data manipulation
requests - API calls (PageSpeed, etc.)
beautifulsoup4 - web scraping (WordPress detection)
gspread or openpyxl - Google Sheets integration
openai or anthropic - AI message generation

APIs to integrate:

Google PageSpeed Insights API (free)
Wappalyzer API (optional, 50 free/month)
Claude API or OpenAI API (for message generation)
Google Sheets API (for database)

Output format: Google Sheets (cloud-based, easy to track/update)

Immediate Build Priority
Build in this order:

Crunchbase data cleaner - Takes CSV export, cleans/filters it
WordPress detector - Checks if site uses WordPress (bulk processing)
PageSpeed checker - Gets performance scores (bulk with rate limiting)
Data combiner - Merges all data sources into master sheet
Message generator - AI-powered personalization using templates
Tracking sheet setup - Formulas for metrics, follow-up dates

Skip for now:

Email infrastructure (not needed yet - doing LinkedIn first)
Full automation (validate manually first)
Attribution tracking (too early)


File Structure
/cold-outreach-system
  /scripts
    crunchbase_cleaner.py
    wordpress_detector.py
    pagespeed_checker.py
    linkedin_scraper.py (Phantombuster config)
    message_generator.py
    data_combiner.py
  /data
    crunchbase_export.csv (raw export)
    companies_cleaned.csv (processed)
    master_leads.csv (final output)
  /config
    api_keys.env (PageSpeed API, Claude API, etc.)
    signal_filters.json (filter criteria for each signal)
  /templates
    message_templates.json (by signal set)
  README.md (setup instructions)

Environment Setup
bash# .env file
PAGESPEED_API_KEY=your_key_here
ANTHROPIC_API_KEY=your_key_here
GOOGLE_SHEETS_CREDENTIALS=path/to/credentials.json

Notes for Implementation

Start with Signal Set 1 only (validate before building all 3)
Build scripts to handle 100-200 leads at a time (not thousands)
Add rate limiting to API calls (especially PageSpeed)
Log all API responses for debugging
Manual QA on first 10 generated messages
Google Sheets is the source of truth (easy to edit/track manually)