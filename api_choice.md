# Traffic API Research Notes

> **Note:** This is a research document covering all APIs evaluated. See `final_api_choice.md` for the final decision and implementation details.

---

## Research Summary

**Goal:** Find an API to check if websites have 50K+ monthly visitors (Signal 2)

**Final Choice:** Apify SimilarWeb Scraper by curious_coder ($19/month rental, but ~10K domains FREE during 3-day trial)

---

## APIs Evaluated

### 1. SimilarWeb Official API
- **Link:** https://developers.similarweb.com/
- **Pricing:** Enterprise only, requires contacting sales
- **Verdict:** Not viable - no self-service option

### 2. DataForSEO Bulk Traffic Estimation
- **Link:** https://docs.dataforseo.com/v3/dataforseo_labs-google-bulk_traffic_estimation-live/
- **Pricing:** $50 minimum deposit + ~$0.01/request
- **What it measures:** SEO traffic only (Google rankings × search volume × CTR)
- **Limitation:** Misses direct traffic, social, email, referrals
- **Verdict:** Not ideal - we need total visitors, not just organic search

### 3. SEO Review Tools API
- **Link:** https://www.seoreviewtools.com/website-traffic-api/
- **Pricing:** $75/month minimum
- **Verdict:** Too expensive for our use case

### 4. SEMrush Trends API
- **Link:** https://www.semrush.com/kb/930-trends-api
- **Pricing:** $499+/month (requires Business plan)
- **Verdict:** Way too expensive

### 5. Ahrefs API
- **Link:** https://ahrefs.com/api/pricing
- **Pricing:** $399-1,499/month + per-request costs
- **Verdict:** Way too expensive

### 6. Apify SimilarWeb Quick Scraper
- **Link:** https://apify.com/mscraper/similarweb-quick-scraper
- **Pricing model:** Pay-per-result ($0.009/domain, platform costs included)
- **135 domains:** $1.21
- **Data quality:** Basic - traffic numbers only, limited additional data
- **Verdict:** Cheap but data quality not great

### 7. Apify SimilarWeb Scraper (curious_coder) ← CHOSEN
- **Link:** https://apify.com/curious_coder/similarweb-scraper
- **Pricing model:** Rental ($19/month) + platform usage (~$0.0005/domain)
- **Free trial:** 3 days (72 hours)
- **Data quality:** Rich - traffic, keywords, competitors, sources, geography
- **Verdict:** Best value during trial, rich data

---

## Apify Pricing Deep Dive

### How Apify Works
Apify is a marketplace for web scrapers ("Actors"). Two types of costs:

1. **Platform costs** - Apify's compute/server fees (~$0.0005/domain)
2. **Actor costs** - Developer's fee (varies by pricing model)

### Pricing Models on Apify

| Model | How It Works | Platform Costs |
|-------|--------------|----------------|
| **Pay Per Result** | Pay per scraped item (e.g., $0.009/domain) | Included in price |
| **Rental** | Monthly subscription to access actor | Extra (you pay both) |
| **Free** | No actor fee | You only pay platform |

### Free Tier
- Apify gives **$5/month free credits** for platform usage
- Credits don't roll over month-to-month

---

## Quick Scraper vs curious_coder Comparison

### Pricing Comparison

| Scraper | Model | 135 domains | 3,000 domains | 10,000 domains |
|---------|-------|-------------|---------------|----------------|
| **Quick Scraper** | Pay-per-result | $1.21 | $27.00 | $90.00 |
| **curious_coder (trial)** | Rental + platform | ~$0.07 | ~$1.50 | ~$5.00 |
| **curious_coder (after trial)** | Rental + platform | ~$19.07 | ~$20.50 | ~$24.00 |

### During Trial Math
- Rental fee: $0 (waived)
- Platform usage: ~$0.0005/domain
- Free credits: $5/month
- **Free capacity:** $5 ÷ $0.0005 = **10,000 domains FREE**

### Data Comparison

| Field | Quick Scraper | curious_coder |
|-------|---------------|---------------|
| Monthly visits | Yes | Yes |
| Historical traffic | Limited | Yes (monthly trends) |
| Traffic sources | Basic | Detailed breakdown |
| Top keywords + CPC | No | Yes |
| Competitors list | No | Yes |
| Geographic data | Basic | Detailed |

---

## Test Results

### Quick Scraper Test
- Ran 2-3 domains
- Data returned was basic
- Only traffic numbers were useful, other fields hit-or-miss

### curious_coder Scraper Test
- Ran 2 domains
- Cost: $0.001 (platform usage only, trial active)
- Data quality: Much richer, more useful for outreach

---

## Final Decision

**Chosen:** Apify SimilarWeb Scraper by curious_coder

**Why:**
1. **Free during trial** - Can run ~10,000 domains for $0 (using $5 free credits)
2. **Rich data** - Keywords, competitors, traffic sources useful for outreach personalization
3. **SimilarWeb source** - Most accurate traffic estimation available
4. **Trial strategy** - Run full list during 3-day trial, decide later if $19/month is worth it

**Action Plan:**
1. Run all domains during trial period (free)
2. If need ongoing access, $19/month is reasonable for unlimited runs
3. Can create new account for another trial if needed

---

## All Options Summary Table

| API | Cost | Traffic Type | Data Richness | Self-Service |
|-----|------|--------------|---------------|--------------|
| **curious_coder (trial)** | ~$0 | Full | Rich | Yes |
| **Quick Scraper** | $0.009/domain | Full | Basic | Yes |
| **DataForSEO** | $50 min | SEO only | Medium | Yes |
| **SEO Review Tools** | $75+/month | Full | Rich | Yes |
| **SimilarWeb Official** | Enterprise | Full | Rich | No |
| **SEMrush** | $499+/month | Full | Rich | Yes |
| **Ahrefs** | $399+/month | Full | Rich | Yes |

---

## Sources

- [Apify SimilarWeb Scraper (curious_coder)](https://apify.com/curious_coder/similarweb-scraper)
- [Apify SimilarWeb Quick Scraper](https://apify.com/mscraper/similarweb-quick-scraper)
- [Apify Pricing](https://apify.com/pricing)
- [Apify Pay Per Event Explained](https://help.apify.com/en/articles/10700066-what-is-pay-per-event)
- [DataForSEO Bulk Traffic Estimation API](https://docs.dataforseo.com/v3/dataforseo_labs-google-bulk_traffic_estimation-live/)
- [DataForSEO ETV Calculation](https://dataforseo.com/help-center/how-is-etv-calculated)
- [SimilarWeb Developers Portal](https://developers.similarweb.com/)
- [SEO Review Tools API](https://www.seoreviewtools.com/website-traffic-api/)
- [SEMrush Pricing](https://www.semrush.com/pricing/)
- [Ahrefs API Pricing](https://ahrefs.com/api/pricing)
