# Outreach Signals

A cold outreach enrichment system for WordPress → Webflow migrations, targeting SaaS/tech startups ($10-20K deals). The system enriches company data with multiple signals and grades websites on performance, content, and design.

## What This Project Does

Given a CSV of company websites, this system:

1. **Detects tech stack** - Identifies WordPress, Webflow, React, Next.js, and 25+ other technologies
2. **Checks performance** - Gets Google PageSpeed scores (mobile + desktop) with Core Web Vitals
3. **Fetches traffic data** - Monthly visits, bounce rate, traffic sources via SimilarWeb
4. **Grades websites** - AI-powered design analysis + content scoring with deviation detection

### Signal Detection

The system identifies three types of high-value prospects:

| Signal | Description | Why It Matters |
|--------|-------------|----------------|
| Signal 1 | Funded (Series A/B) + WordPress | Have budget, need modern site |
| Signal 2 | 50K+ traffic + Mobile score < 50 | High traffic, poor experience |
| Signal 3 | Premium analytics + WordPress | Tech-savvy but outdated site |

## Quick Start

```bash
# Clone the repo
git clone https://github.com/shreyaspaul/outreach_signals.git
cd outreach_signals

# Setup environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium

# Create .env file with your API keys
cat > .env << EOF
PAGESPEED_API_KEY=your_google_api_key
APIFY_TOKEN=your_apify_token
GEMINI_API_KEY=your_gemini_api_key
EOF

# Run enrichment on sample data
python scripts/orchestrator.py app.csv --limit 5
```

## Project Structure

```
outreach_signals/
├── app.csv                 # Input: companies with Website column
├── .env                    # API keys (not in git)
├── requirements.txt        # Python dependencies
├── CLAUDE.md              # Instructions for Claude Code
│
├── scripts/
│   ├── orchestrator.py     # Main entry - runs all checks
│   ├── wordpress_detector.py   # Tech stack detection
│   ├── pagespeed_checker.py    # Google PageSpeed API
│   ├── traffic_checker.py      # SimilarWeb via Apify
│   └── website_grader.py       # Screenshots + Gemini Vision
│
├── data/                   # Output CSVs (timestamped)
│   ├── enriched_*.csv      # Full enrichment results
│   └── graded_*.csv        # Grading-only results
│
├── screenshots/            # Website screenshots for grading
├── logs/                   # Gemini API request logs
└── specs/                  # Feature specifications
```

## Usage

### Full Enrichment Pipeline

```bash
# Run all checks (tech, PageSpeed, traffic, grading)
python scripts/orchestrator.py app.csv

# Limit entries for testing
python scripts/orchestrator.py app.csv --limit 10

# Skip expensive API calls
python scripts/orchestrator.py app.csv --skip-traffic    # Skip SimilarWeb
python scripts/orchestrator.py app.csv --skip-grader     # Skip Gemini Vision
```

### Individual Scripts

```bash
# Tech stack detection only
python scripts/wordpress_detector.py app.csv

# PageSpeed scores only
python scripts/pagespeed_checker.py app.csv

# Traffic data only
python scripts/traffic_checker.py app.csv

# Website grading only (screenshots + AI)
python scripts/website_grader.py app.csv --limit 5
```

## Output Columns

### Tech Detection
| Column | Description |
|--------|-------------|
| tech_stack | Primary technology (wordpress, webflow, next.js, etc.) |
| all_tech_detected | All technologies found |
| is_wordpress | Boolean flag |
| marketing_tools | Analytics tools (GA, Segment, Mixpanel, etc.) |
| ad_pixels | Ad pixels (Facebook, Google Ads, LinkedIn, etc.) |
| has_premium_analytics | Uses Segment/Amplitude/Mixpanel |

### Performance
| Column | Description |
|--------|-------------|
| pagespeed_mobile | Mobile score (0-100) |
| pagespeed_desktop | Desktop score (0-100) |
| mobile_fcp/lcp/cls | Core Web Vitals (mobile) |
| desktop_fcp/lcp/cls | Core Web Vitals (desktop) |

### Traffic
| Column | Description |
|--------|-------------|
| monthly_visits | Monthly visitors |
| global_rank | Global website ranking |
| bounce_rate | Bounce rate (%) |
| traffic_source_direct/search/social | Traffic breakdown |
| is_signal_2_traffic | Has 50K+ monthly visits |

### Grading
| Column | Description |
|--------|-------------|
| performance_score | PageSpeed mobile score used in grading |
| content_score | Content structure score (0-100) |
| design_score | AI design analysis score (0-100) |
| total_grade_score | Weighted total (30% perf, 40% content, 30% design) |
| letter_grade | A+ to F |
| grade_analysis | e.g., "Excellent design, Good content, Poor performance" |
| weak_areas | Areas scoring below threshold |
| strong_areas | Areas scoring above threshold |

## API Keys Required

| API | Purpose | Get Key |
|-----|---------|---------|
| Google PageSpeed | Performance scores | [Google Cloud Console](https://console.cloud.google.com/) |
| Apify | SimilarWeb traffic data | [Apify Console](https://console.apify.com/) |
| Gemini | AI design analysis | [Google AI Studio](https://aistudio.google.com/) |

---

## Development Workflow with Claude Code

This project was built collaboratively with [Claude Code](https://claude.ai/code). Here's how we work together:

### How We Develop Features

1. **Describe the requirement** - Explain what you want to build in plain English
2. **Claude researches** - Uses the `analyst` agent to explore the codebase and plan implementation
3. **Review the plan** - Claude presents a spec, you provide feedback
4. **Implementation** - Claude writes the code, you test it
5. **Iteration** - Fix issues, refine, test again

### Agents Available

Claude Code has specialized agents for different tasks:

| Agent | When to Use | What It Does |
|-------|-------------|--------------|
| `analyst` | Planning new features | Explores codebase, creates specs, considers trade-offs |
| `Explore` | Understanding code | Searches files, finds patterns, answers "how does X work?" |
| `api-researcher` | Choosing APIs | Compares options, pricing, rate limits for a use case |

### Example Workflow

```
You: "I want to add a website grader that scores design and content"

Claude: *Uses analyst agent to create a spec*
        *Presents plan with scoring weights, output columns, etc.*

You: "Looks good, but I don't want to spend too much on AI"

Claude: *Researches cheaper options*
        *Recommends Gemini Flash instead of GPT-4o (87% cheaper)*

You: "Let's do it"

Claude: *Implements website_grader.py*
        *Integrates with orchestrator*
        *Tests with sample data*

You: "Run it on 10 entries"

Claude: *Runs test, shows results*
        *Identifies and fixes any issues*
```

### Tips for Working with Claude Code

1. **Be specific** - "Add a column for bounce rate" is better than "improve traffic data"
2. **Test incrementally** - Start with `--limit 5` before running on full dataset
3. **Review outputs** - Check the CSV results to catch issues early
4. **Iterate** - It's normal to refine 2-3 times before getting it right

### Useful Commands

```bash
# Check what Claude remembers about the project
cat CLAUDE.md

# See recent outputs
ls -la data/

# Check API logs
cat logs/gemini_requests_*.log

# Run quick test
python scripts/orchestrator.py app.csv --limit 3 --skip-traffic
```

---

## Current Limitations

- **Content scoring** is heuristic-based (word count, headings) - may not reflect actual content quality
- **Traffic data** requires paid Apify subscription after free trial
- **Some sites block screenshots** - Cloudflare/bot detection can cause failures

## Next Steps

- [ ] Improve content scoring with sitemap analysis
- [ ] Build message generator for personalized outreach
- [ ] Add data combiner for merging multiple runs
- [ ] Export to CRM format

## License

MIT
