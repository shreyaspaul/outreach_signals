# Final API Choice: Traffic Data

## Selected API: Apify SimilarWeb Scraper (curious_coder)

**Link:** https://apify.com/curious_coder/similarweb-scraper

**Actor ID:** `curious_coder/similarweb-scraper`

---

## Why This Choice

| Factor | Details |
|--------|---------|
| Data source | SimilarWeb (most accurate traffic estimation) |
| Data richness | Traffic + keywords + competitors + sources |
| Cost during trial | ~$0.0005/domain (covered by $5 free credits) |
| Cost after trial | $19/month + ~$0.0005/domain platform usage |
| Free capacity | ~10,000 domains free during 3-day trial |

---

## Pricing Breakdown

### During Trial (3 days)
| Item | Cost |
|------|------|
| Rental fee | $0 (waived) |
| Platform usage | ~$0.0005/domain |
| Free credits | $5/month |
| **10,000 domains** | **$0 (covered by free credits)** |

### After Trial
| Item | Cost |
|------|------|
| Rental fee | $19/month |
| Platform usage | ~$0.0005/domain |
| **135 domains/month** | ~$19.07/month |

---

## Data Fields Returned

### Core Traffic Metrics (Signal 2)
| Field | Type | Description | Use Case |
|-------|------|-------------|----------|
| `visits` | number | Total estimated visits | Primary Signal 2 check (50K+) |
| `estimatedMonthlyVisits` | object | Historical monthly visits | Trend analysis |
| `bounceRate` | number | % single-page sessions | Site quality indicator |
| `pagesPerVisit` | number | Avg pages per session | Engagement metric |
| `timeOnSite` | number | Avg session duration (seconds) | Engagement metric |

### Rankings
| Field | Type | Description |
|-------|------|-------------|
| `globalRank` | number | Worldwide ranking position |
| `countryRank` | object | Country-specific rank + country code |
| `categoryRank` | object | Industry/category ranking |

### Traffic Sources
| Field | Type | Description |
|-------|------|-------------|
| `trafficSources.direct` | number | % direct traffic |
| `trafficSources.search` | number | % from search engines |
| `trafficSources.social` | number | % from social media |
| `trafficSources.referrals` | number | % from referral links |
| `trafficSources.paid` | number | % from paid ads |
| `trafficSources.mail` | number | % from email campaigns |

### Geography
| Field | Type | Description |
|-------|------|-------------|
| `topCountryShares` | array | Top countries with % share |

### SEO Data
| Field | Type | Description |
|-------|------|-------------|
| `topKeywords` | array | Top ranking keywords |
| `topKeywords[].keyword` | string | The keyword |
| `topKeywords[].estimatedValue` | number | Traffic value |
| `topKeywords[].cpc` | number | Cost per click |

### Competitive Intelligence
| Field | Type | Description |
|-------|------|-------------|
| `competitors` | array | List of competing domains |

### Metadata
| Field | Type | Description |
|-------|------|-------------|
| `domain` | string | Domain analyzed |
| `title` | string | Website title |
| `description` | string | Meta description |
| `category` | string | Industry classification |
| `screenshot` | string | Thumbnail URL |
| `snapshotDate` | string | Data collection date |
| `isDataFromGA` | boolean | Google Analytics source flag |

---

## Example Output

```json
{
  "domain": "example.com",
  "globalRank": 15234,
  "countryRank": {"country": "US", "rank": 8921},
  "categoryRank": {"category": "Technology", "rank": 342},
  "visits": 125000,
  "estimatedMonthlyVisits": {
    "2025-10-01": 118000,
    "2025-11-01": 122000,
    "2025-12-01": 125000
  },
  "bounceRate": 0.45,
  "pagesPerVisit": 3.2,
  "timeOnSite": 185,
  "trafficSources": {
    "direct": 0.35,
    "search": 0.42,
    "social": 0.12,
    "referrals": 0.08,
    "paid": 0.02,
    "mail": 0.01
  },
  "topCountryShares": [
    {"country": "US", "share": 0.45},
    {"country": "UK", "share": 0.15},
    {"country": "CA", "share": 0.10}
  ],
  "topKeywords": [
    {"keyword": "example tool", "estimatedValue": 5200, "cpc": 2.50},
    {"keyword": "example software", "estimatedValue": 3100, "cpc": 1.80}
  ],
  "competitors": ["competitor1.com", "competitor2.com"],
  "title": "Example - The Best Tool",
  "description": "Example helps you do things better.",
  "category": "Technology/Software",
  "screenshot": "https://...",
  "snapshotDate": "2025-12-26",
  "isDataFromGA": false
}
```

---

## Integration

### Requirements
```bash
pip install apify-client
```

### Environment Variable
Add to `.env`:
```
APIFY_TOKEN=your_token_here
```

### Python Integration
```python
import os
from apify_client import ApifyClient
from dotenv import load_dotenv

load_dotenv()

def get_traffic_data(domains: list[str]) -> list[dict]:
    """
    Fetch traffic data for a list of domains using SimilarWeb via Apify.

    Args:
        domains: List of domains to check (e.g., ["example.com", "test.com"])

    Returns:
        List of dicts with traffic data for each domain
    """
    client = ApifyClient(os.getenv("APIFY_TOKEN"))

    run = client.actor("curious_coder/similarweb-scraper").call(
        run_input={"domains": domains}
    )

    results = []
    for item in client.dataset(run["defaultDatasetId"]).iterate_items():
        results.append(item)

    return results


def check_signal_2(traffic_data: dict, min_visits: int = 50000) -> bool:
    """
    Check if a domain qualifies for Signal 2 (high traffic).

    Args:
        traffic_data: Dict from get_traffic_data()
        min_visits: Minimum monthly visits threshold (default 50K)

    Returns:
        True if domain has >= min_visits
    """
    visits = traffic_data.get("visits", 0)
    return visits >= min_visits if visits else False
```

### Usage Example
```python
# Single domain test
results = get_traffic_data(["stripe.com"])
for r in results:
    print(f"{r['domain']}: {r.get('visits', 'N/A')} visits/month")
    print(f"  Signal 2 candidate: {check_signal_2(r)}")

# Batch processing from CSV
import pandas as pd

df = pd.read_csv("app.csv")
domains = df["Website"].dropna().tolist()

# Clean domains (remove https://, trailing slashes, etc.)
domains = [d.replace("https://", "").replace("http://", "").rstrip("/") for d in domains]

results = get_traffic_data(domains)
```

---

## Integration with Orchestrator

The traffic checker will be added to `scripts/orchestrator.py` to run after:
1. WordPress detection (`wordpress_detector.py`)
2. PageSpeed check (`pagespeed_checker.py`)
3. **Traffic check** (`traffic_checker.py`) ← NEW

### Output Columns to Add
| Column | Source Field | Description |
|--------|--------------|-------------|
| `monthly_visits` | `visits` | Estimated monthly visitors |
| `global_rank` | `globalRank` | Worldwide ranking |
| `bounce_rate` | `bounceRate` | Bounce rate % |
| `traffic_source_search` | `trafficSources.search` | % from search |
| `traffic_source_direct` | `trafficSources.direct` | % direct traffic |
| `traffic_source_social` | `trafficSources.social` | % from social |
| `top_country` | `topCountryShares[0].country` | Primary audience country |
| `is_signal_2` | computed | True if visits >= 50K |

---

## Signal 2 Qualification

A company qualifies for **Signal 2** when:
1. `monthly_visits` >= 50,000
2. `pagespeed_mobile` < 50 (from PageSpeed checker)
3. `is_wordpress` = True (from WordPress detector)

All three conditions = **High-priority outreach target**

---

## Rate Limits & Best Practices

1. **Batch size**: Can process hundreds of domains per run
2. **Retry handling**: Built-in smart retry for failed URLs
3. **Resume support**: Can resume interrupted runs
4. **Recommended**: Process in batches of 100-200 for reliability

---

## Setup Checklist

- [ ] Create Apify account at https://apify.com
- [ ] Get API token from Settings → Integrations
- [ ] Add `APIFY_TOKEN` to `.env`
- [ ] Install `apify-client` (`pip install apify-client`)
- [ ] Test with 2-3 domains
- [ ] Run full batch during trial period

---

## Files

| File | Purpose |
|------|---------|
| `api_choice.md` | Research notes on all APIs evaluated |
| `final_api_choice.md` | This file - final decision + implementation |
| `scripts/traffic_checker.py` | Traffic checker script (to be created) |
| `.env` | Contains `APIFY_TOKEN` |

---

## Sources

- [Apify SimilarWeb Scraper](https://apify.com/curious_coder/similarweb-scraper)
- [Python API Documentation](https://apify.com/curious_coder/similarweb-scraper/api/python)
- [Apify Pricing](https://apify.com/pricing)
