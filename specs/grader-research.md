# Grader Research: Non-Genuine Page Detection & LLM Score Variance

Research conducted June 2026 for the cold outreach website grading pipeline.  
Scope: Part A (genuine/live site detection + content extraction) and Part B (LLM scoring determinism).

---

## Part A: Detecting Non-Genuine Pages & Extracting the Right Content

### A.1 The Problem Space

The current pipeline is fooled by at least five non-genuine page states:

| State | Example | Why current detection fails |
|---|---|---|
| Domain parking / for-sale | enrich.ly served by Atom/Squadhelp | Content is real HTML, scores fine on words and CTAs |
| Acquired/holding page | "XYZ acquired domain.com" thin page | No error keywords; may have normal word counts |
| Coming-soon / under-construction | WordPress holding page | Partially caught by current patterns |
| Login / bot-block | Cloudflare IUAM, captcha page | Playwright serves challenge page; Jina returns minimal content |
| Cross-domain redirect | company.com → acquirer.com | Content scored is acquirer, not the company you researched |

---

### A.2 Signal Layer 1: HTTP-Level Signals (Free, Implement First)

These can be checked with a plain `requests.get()` or via the existing Playwright session before any content analysis.

#### A.2.1 Final URL vs. Input URL

The single highest-value signal. If `final_url != input_url` after following redirects, something changed:

- **Same domain, different path** (e.g. `company.com` → `company.com/en/`) — normal, ignore.
- **Same domain, different subdomain** (e.g. → `www.company.com`) — normal, ignore.
- **Different domain entirely** (e.g. `company.com` → `acquirer.com`) — flag as `cross_domain_redirect`. Score should be attributed to `input_url`, not `final_url`.
- **Redirect to marketplace domain** (e.g. → `atom.com/domains/company`, `sedo.com/...`, `dan.com/...`, `afternic.com/...`) — definitive parking signal.

The current Jina integration does not expose the final URL. Firecrawl's scrape endpoint returns both `sourceURL` (original) and `url` (final after redirects) in its metadata object — this is a concrete advantage over Jina for this use case.

#### A.2.2 HTTP Status Codes

| Code | Meaning | Action |
|---|---|---|
| 200 | Normal | Continue to content analysis |
| 301/302 permanent redirect | Domain moved | Check final URL |
| 403 / 401 | Bot-block or login wall | Flag `access_denied`; skip scoring |
| 404 / 410 | Page gone | Already handled |
| 503 | Server unavailable / Cloudflare block | Flag `bot_blocked`; retry with stealth |
| Any non-200 from Jina | Extraction failure | Fall back to Playwright response code |

---

### A.3 Signal Layer 2: DNS / Nameserver Fingerprints

DNS checks are fast (< 50 ms, free) and can be done before any HTTP request using `dnspython`. APNIC research catalogued 82 parking services and their exact NS/IP indicators.

#### Confirmed Nameserver Fingerprints (per APNIC 2023 dataset, stable into 2026)

| Parking Service | Nameserver Pattern | Notes |
|---|---|---|
| GoDaddy Parking | NS `ns*.domaincontrol.com` OR A record `34.102.136.180` / `34.98.99.30` | Most common; GoDaddy-registered domains default here |
| Afternic (GoDaddy group) | NS `ns*.afternic.com` | Premium domain marketplace |
| Sedo | NS `ns*.sedoparking.com` or CNAME to `sedoparking.com` | 19.5% of all parked domains globally |
| Dan.com (GoDaddy acquired 2022) | NS `ns1.dan.com`, `ns2.dan.com` | Now integrated with Afternic |
| Bodis | NS `ns*.bodis.com` | Smaller parking provider |
| ParkingCrew | NS `ns*.parkingcrew.net` | Used by domain investors |
| Uniregistry (now part of GoDaddy) | NS `ns*.uniregistry.net` | Legacy; gradually migrating |
| Atom.com / Squadhelp | Pages served from `atom.com` subdomain; NS changed to `pendingdelete` before listing, then pointed to Atom infrastructure | HTML fingerprint more reliable (see A.4) |

**Implementation:**
```python
import dns.resolver

PARKING_NAMESERVERS = [
    'domaincontrol.com',   # GoDaddy
    'afternic.com',
    'sedoparking.com',
    'dan.com',
    'bodis.com',
    'parkingcrew.net',
    'uniregistry.net',
]

PARKING_IPS = {
    '34.102.136.180',  # GoDaddy Free Parking
    '34.98.99.30',     # GoDaddy Free Parking
}

def check_dns_parking(domain: str) -> dict:
    try:
        ns_records = [str(r) for r in dns.resolver.resolve(domain, 'NS')]
        for ns in ns_records:
            for pattern in PARKING_NAMESERVERS:
                if pattern in ns.lower():
                    return {'is_parked': True, 'signal': f'ns:{ns}'}
        
        a_records = [str(r) for r in dns.resolver.resolve(domain, 'A')]
        for ip in a_records:
            if ip in PARKING_IPS:
                return {'is_parked': True, 'signal': f'ip:{ip}'}
    except Exception:
        pass
    return {'is_parked': False, 'signal': None}
```

---

### A.4 Signal Layer 3: HTML Content Fingerprints

After DNS and HTTP checks, these patterns in the extracted HTML/content reliably identify non-genuine states. Some are already in the current `ERROR_PAGE_PATTERNS` list; these are the missing ones.

#### A.4.1 Domain Parking / For-Sale Marketplace Markers

These are NOT currently detected by the codebase.

**Known HTML/text patterns:**
- `domain for sale` / `this domain is for sale` / `buy this domain`
- `make an offer` (common CTA on parking pages)
- `inquire about this domain`
- `domain is listed for sale`
- `purchase this domain`
- `brandable domain` / `premium domain`
- Meta tags: `<meta name="generator" content="Sedo">`
- `sedo.com`, `dan.com`, `afternic.com`, `atom.com`, `squadhelp.com` in page links or scripts
- Body class or data attributes: `class="parking-page"`, `id="parking"`
- Iframe pointing to a parking service domain

**Atom.com / Squadhelp specific:**
- Page title often: `[DomainName] - Premium Domain for Sale`
- Body contains phrases like `This domain is represented by Atom`
- Outbound links to `atom.com` or `squadhelp.com`
- No company-specific content; page is entirely about buying the domain

**Recommended additions to `ERROR_PAGE_PATTERNS`:**
```python
PARKING_PAGE_PATTERNS = [
    r'domain\s+(is\s+)?(for\s+sale|listed)',
    r'(buy|purchase|acquire)\s+this\s+domain',
    r'make\s+an\s+offer',
    r'inquire\s+about\s+this\s+domain',
    r'this\s+domain\s+is\s+represented\s+by',
    r'premium\s+domain\s+(for\s+sale|marketplace)',
    r'(sedo\.com|afternic\.com|dan\.com|atom\.com|squadhelp\.com)',  # in page body
    r'domain\s+parking',
]
```

#### A.4.2 Acquisition / Holding Page Markers

Not currently detected.

**Common patterns:**
- `[CompanyX] has been acquired by [CompanyY]`
- `we've joined [CompanyY]`
- `[Company] is now part of [Parent]`
- `this page is no longer active`
- `visit us at [new-url.com]`
- Very thin content (< 100 words) with a single external redirect link

**Recommended additions:**
```python
ACQUISITION_PAGE_PATTERNS = [
    r'(has been|have been)\s+acquired\s+by',
    r'we.{0,10}(joined|merged with|part of)',
    r'is now part of',
    r'this (page|site|company) is no longer',
    r'please visit us at',
    r'redirect(ing)? (you )?to our new',
]
```

#### A.4.3 Bot-Block / Login Wall Patterns (Cloudflare/CAPTCHA)

Partially detected via `access_denied` / `forbidden`, but Cloudflare IUAM pages need specific detection:

```python
BOT_BLOCK_PATTERNS = [
    r'checking\s+your\s+browser',        # Cloudflare IUAM
    r'please\s+(wait|stand\s+by)',        # Cloudflare IUAM
    r'enable\s+javascript\s+and\s+cookies',  # Cloudflare
    r'ddos\s+protection',
    r'verify\s+you\s+are\s+human',
    r'complete\s+the\s+captcha',
    r'cloudflare\s+ray\s+id',            # Cloudflare footer marker
    r'log\s*in\s+to\s+(continue|access)',  # Login wall
    r'sign\s+in\s+to\s+(view|continue)',
]
```

---

### A.5 Signal Layer 4: Domain-Company Identity Verification

This answers: "Is the content on this URL actually the company we're researching, or something else?"

**Lightweight approach (recommended):**
1. Extract the company name from your CSV (the `Name` column).
2. Extract the domain from the URL (strip `www.`, TLD).
3. Check if any of these match in the page content:
   - Company name appears in page title or H1
   - Page title does NOT contain "for sale", "domain", "parking"
   - Domain stem appears in the company name or vice versa
4. If none match AND content is thin (< 200 words), flag as `identity_mismatch`.

**For cross-domain redirects:**
- If `final_url` domain differs from `input_url` domain, check whether the company name appears in the final page. If not → `cross_domain_redirect_mismatch`.

**LLM-based approach (heavier, use as a second pass on flagged entries only):**
Ask Gemini (with the page title + first 500 chars of content + company name): "Is this page the website of [Company Name], or is it a different entity?" — binary answer. Only costs ~100 tokens per call.

---

### A.6 Content Extraction Tool Comparison

#### A.6.1 Jina AI Reader (Current)

**How it works:** Proxy-based HTTP fetch (not a real browser) → strips HTML → returns clean markdown.

| Dimension | Assessment |
|---|---|
| Anti-bot handling | Poor. Uses HTTP fetching, not a real browser. Cloudflare IUAM, bot-detection JS, and login walls produce challenge pages or empty content. |
| Final URL exposure | Partially. Documentation states it uses "final URL as base" for relative links, but the `text/plain` response does not include the final URL as a structured field. With `Accept: application/json`, a URL field is returned, but this is not always the true final URL after all JS-driven redirects. |
| Parking page detection | None. Returns the parking page content as-is, scoring it normally. |
| Structured metadata | Title only (when using text/plain). JSON mode returns title + URL + content. |
| Rate limits | 500 RPM with free key; 5000 RPM on Premium. |
| Pricing (2026) | Free tier: 10M tokens included. Paid: token-based top-up. Effectively ~$0.00 for a 999-site run at current usage. |
| Extraction quality | Good for standard marketing sites. Misses JS-rendered content (SPAs). |
| Best for | Fast, cheap extraction of standard HTML sites where bot-blocking is not an issue. |

**Key gap:** Jina does not return `final_url` or `status_code` in a reliable, structured way. This is the primary reason parking pages and cross-domain redirects go undetected.

#### A.6.2 Firecrawl

**How it works:** Real Playwright browser in the cloud → follows all JS redirects → returns markdown + metadata.

| Dimension | Assessment |
|---|---|
| Anti-bot handling | Good on standard Cloudflare. Standard tier uses datacenter IPs. Stealth Mode (5 credits/page vs 1 credit/page) uses residential proxies for enterprise bot protection. |
| Final URL exposure | Excellent. Returns both `sourceURL` (input) and `url` (final after all redirects) plus `statusCode` in every response. This directly solves the redirect-mismatch problem. |
| Parking page detection | Not built-in, but you get the final URL and full content to run your own pattern matching. If `final_url` is `atom.com/domains/...`, detection is trivial. |
| Structured metadata | Title, description, language, keywords, statusCode, contentType, sourceURL, url. |
| Rate limits | 50 concurrent requests on Standard plan. |
| Pricing (2026) | Free: 1,000 credits/month. Hobby: $16/month (5,000 credits). Standard: $83/month (100,000 credits). 1 credit = 1 page (standard). 5 credits/page for Stealth Mode. For 999 sites: ~1,000 credits = free tier or ~$0.80 on Hobby. |
| Extraction quality | Excellent. Real browser means JS-rendered content is captured. Comparable to or better than Jina for SPA sites. |
| Best for | Any workflow where redirect detection, final URL, and bot-blocking are concerns. The direct replacement for Jina when these signals matter. |

**Concrete advantage over Jina:** The `url` (final) vs `sourceURL` (original) field pair means every cross-domain redirect is automatically caught. A one-line check `if result['url'] != result['sourceURL']` flags the issue.

#### A.6.3 ScrapingBee

| Dimension | Assessment |
|---|---|
| Anti-bot handling | Good. 84.47% success rate on protected targets (Proxyway 2025 benchmark). Browser-based with premium proxy option. |
| Final URL | Returns response metadata including redirect information. Less structured than Firecrawl's explicit sourceURL/url split. |
| Parking detection | Not built-in. Same as Firecrawl — you post-process the content. |
| Pricing (2026) | Starts at $49/month. HTTP requests: 1 credit. Browser: 5 credits. Premium proxy: 10-25 credits. More expensive per page than Firecrawl for this use case. |
| Best for | When you need maximum anti-bot success rate and are willing to pay more per page. Not the best fit here given cost vs. Firecrawl. |

#### A.6.4 Zyte API (formerly Scrapy Cloud)

| Dimension | Assessment |
|---|---|
| Anti-bot handling | Highest success rate — consistently >90% in Proxyway 2025 benchmark, top overall. |
| Final URL | Yes, via automatic extraction metadata. |
| Structured output | Best-in-class. Returns structured entities (article, product, job listing) not just markdown. Overkill for this use case. |
| Pricing (2026) | ~$1.01/1,000 requests for easy targets. Scales significantly for protected sites. More complex pricing model. |
| Best for | Enterprise pipelines needing maximum anti-bot success + structured entity extraction. Overkill for a 999-site enrichment run. |

#### A.6.5 Diffbot

| Dimension | Assessment |
|---|---|
| Anti-bot handling | Moderate. Uses ML-based extraction. |
| Final URL | Yes. |
| Structured output | Strongest of all options. Returns typed entities: Article, Product, Organization — including company name, description, industry. Highly relevant for domain-company identity matching. |
| Pricing (2026) | Startup: $299/month. Plus: $899/month. Very expensive for batch enrichment. |
| Best for | When you need automatic company entity extraction to verify domain↔company identity. Not cost-effective at this scale. |

#### A.6.6 Recommendation: Hybrid Approach

Given the cost constraints (~free for 999 sites) and the specific failure modes:

**Recommended architecture:**

1. **Keep Jina AI Reader as primary extractor** for standard sites (cheap, fast, good quality).
2. **Add pre-extraction DNS check** (free, catches GoDaddy/Sedo/Afternic/Dan parking before any HTTP call).
3. **Add `requests.get()` with `allow_redirects=True`** before Jina to capture `response.url` (final URL) and `response.status_code`. This adds ~1 second per site but catches all redirect-based parking.
4. **Add HTML pattern detection** for parking/acquisition/bot-block markers (extend current `ERROR_PAGE_PATTERNS`).
5. **Use Firecrawl selectively** (not as default) for sites where Jina returns thin content or triggers bot-block patterns. At 1 credit/page, the free tier (1,000 credits/month) is sufficient for re-trying flagged sites from a 999-site batch.

**Cost estimate for hybrid approach:**
- DNS lookups: free
- `requests.get()` preflight: free (network cost only)
- Jina AI: free (within token limits)
- Firecrawl fallback for ~10-15% of sites: ~100-150 credits/run → free tier

---

### A.7 Detecting Specific Non-Genuine Patterns: Decision Tree

```
Input URL
    │
    ├─► DNS check: NS/IP matches known parking service?
    │       YES → flag 'dns_parking', skip enrichment
    │       NO  → continue
    │
    ├─► requests.get() preflight:
    │       status 4xx/5xx → flag 'http_error'
    │       final_url.domain != input_url.domain?
    │           final_url is marketplace domain (atom.com, sedo.com, etc.)
    │               → flag 'redirect_to_marketplace'
    │           final_url is unrelated company domain
    │               → flag 'cross_domain_redirect', note both URLs
    │       continue with Jina extraction
    │
    ├─► Jina extraction:
    │       content < 50 words → flag 'empty_content'
    │       matches BOT_BLOCK_PATTERNS → flag 'bot_blocked', retry with Firecrawl
    │       matches PARKING_PAGE_PATTERNS → flag 'parked_domain'
    │       matches ACQUISITION_PAGE_PATTERNS → flag 'acquisition_holding_page'
    │       continue to scoring
    │
    └─► Identity check (lightweight):
            Company name NOT in title + NOT in first 300 chars + content < 200 words
                → flag 'identity_mismatch'
```

---

## Part B: Reducing LLM Scoring Variance

### B.1 The Problem: Why Gemini 2.5 Flash Scores 72→88 on Identical Input

The observed 16-point swing on identical design screenshots is not a bug. It is a documented, fundamental property of all large transformer models running as SaaS.

**Root causes (confirmed in literature and Google developer forums as of 2025-2026):**

1. **Floating-point non-determinism:** Even at `temperature=0`, billions of arithmetic operations accumulate rounding errors. A single bit difference in an intermediate activation can flip the top-1 token when two candidates are nearly tied.

2. **MoE batch routing:** Gemini 2.5 Flash uses Mixture-of-Experts layers. Token routing depends on what else is in the inference batch at that moment — outside your control in a shared SaaS deployment.

3. **Thinking budget adds variance:** When `thinking_budget > 0` (the default for Gemini 2.5 Flash), the model's internal reasoning path is sampled from a distribution. Different reasoning chains reach different conclusions. This is especially impactful for subjective tasks like design scoring.

4. **Google has confirmed** (Google AI Developers Forum, 2025) that `gemini-2.5-pro` produces different outputs for identical requests even with fixed `seed` and `temperature`, calling this behavior reproducible and outside their current service contract for determinism.

**Measured magnitude:** Research (QAnswer 2025) shows Gemini 2.5 Flash achieves only 40-70% exact-match consistency at temperature=0 depending on prompt length. For a continuous 0-100 scoring task, variation of ±8-10 points on a single call is expected.

---

### B.2 What Does NOT Work (and Why)

| Technique | Why it fails for this use case |
|---|---|
| `temperature=0` alone | Reduces but does not eliminate variance. Confirmed by Google devs. The 72→88 swing can still occur. |
| `seed` parameter | Gemini API does not honor `seed` as a determinism guarantee (confirmed in GitHub issues). GPT-4 honors it approximately but Gemini does not. |
| Caching responses | Works for exact repeat calls but doesn't help with first-time scoring of new sites. |
| `top_p=1, top_k=1` | Same issue as temperature=0: floating-point nondeterminism persists at the hardware level. |

---

### B.3 What Actually Works: Ranked Recommendations

#### B.3.1 HIGHEST IMPACT: Disable Thinking + Temperature 0 + Structured Output Schema

Three parameters together, applied to the existing `analyze_design_with_gemini()` call.

**Disable thinking:**
```python
from google.generativeai.types import GenerationConfig

config = GenerationConfig(
    temperature=0.0,
    thinking_config={"thinking_budget": 0},  # Disables thinking entirely
    response_mime_type="application/json",
    response_schema={
        "type": "OBJECT",
        "properties": {
            "design_score": {"type": "INTEGER"},
            "comment": {"type": "STRING"}
        },
        "required": ["design_score", "comment"]
    }
)
response = model.generate_content([prompt, image_part], generation_config=config)
```

**Why `thinking_budget=0` helps:** With thinking enabled, the model's internal scratchpad is sampled stochastically, producing different reasoning chains and different final scores. Disabling thinking removes this primary source of variance for a structured scoring task. The model goes straight to output rather than reasoning its way there differently each time.

**Why `response_schema` helps:** Constraining the output to a strict JSON schema with `design_score` as an INTEGER forces the decoding path through constrained decoding. The model cannot emit freeform text that it then rounds — it must emit a specific integer. This eliminates the "parse a number from prose" step which itself introduces variance.

**Combined effect:** Based on research patterns for similar structured scoring tasks, this combination is expected to reduce the swing from ~±10 points to ~±3-5 points. Full determinism is not achievable in SaaS deployment.

**Note on new SDK:** The current code uses `google.generativeai` (the legacy SDK). Google's newer `google-genai` SDK uses slightly different syntax:
```python
from google import genai
from google.genai.types import GenerateContentConfig, ThinkingConfig

config = GenerateContentConfig(
    temperature=0.0,
    thinking_config=ThinkingConfig(thinking_budget=0),
    response_mime_type="application/json",
    response_schema={"type": "OBJECT", ...}
)
```
Both SDKs work; prefer the new `google-genai` SDK for new development.

#### B.3.2 HIGH IMPACT: Score Decomposition (Sub-Dimensions Instead of Holistic)

The current design prompt asks for a single holistic `design_score: 0-100`. This is the highest-variance form of scoring — the model must simultaneously weigh typography, spacing, hierarchy, color, brand, and then collapse to one number. Different internal reasoning paths weight these differently.

**Replace with sub-dimension scoring:**
```
Rate this website screenshot on 5 dimensions, each 0-20:

1. TYPOGRAPHY (0-20): Font choice, size hierarchy, readability, consistent type scale
   0-5: No hierarchy, illegible fonts, clashing sizes
   6-10: Basic hierarchy, readable, some inconsistency
   11-15: Clear hierarchy, professional fonts, consistent scale
   16-20: Exceptional typography, intentional scale, high craft

2. SPACING & LAYOUT (0-20): White space use, alignment, grid consistency
   [anchored rubric...]

3. COLOR & BRAND (0-20): Palette coherence, contrast, brand intentionality
   [anchored rubric...]

4. VISUAL HIERARCHY (0-20): Eye flow, information priority, CTA prominence
   [anchored rubric...]

5. POLISH & CRAFT (0-20): Overall finish, attention to detail, professional execution
   [anchored rubric...]

Return ONLY valid JSON:
{"typography": <0-20>, "spacing_layout": <0-20>, "color_brand": <0-20>, 
 "visual_hierarchy": <0-20>, "polish_craft": <0-20>, "comment": "<one sentence>"}
```

**Final score:** `design_score = typography + spacing_layout + color_brand + visual_hierarchy + polish_craft`

**Why this helps:**
- Each dimension has a narrower range (0-20 vs 0-100), reducing the absolute variance per dimension.
- Anchored behavioral rubrics with concrete score examples (like the content scoring currently does) ground the model's judgment.
- Sub-dimension scores are logged, enabling post-hoc analysis of which dimension is driving variance.
- Research (2025, EMNLP findings) consistently shows sub-dimension scoring with rubric anchors reduces LLM judge variance by 30-50% compared to holistic scoring.

This mirrors the approach already working well for content scoring (clarity/substance/credibility/persuasiveness), which observes much less variance than the design score.

#### B.3.3 HIGH IMPACT: 3-Run Median (Self-Consistency Ensemble)

The most robust variance reduction technique: call the model 3 times on the same input and take the median score.

```python
def analyze_design_with_gemini_ensemble(screenshot_path, url, api_key, runs=3, log_file=None):
    scores = []
    comments = []
    for i in range(runs):
        result = analyze_design_with_gemini(screenshot_path, url, api_key, log_file=log_file)
        if result.get('design_score') is not None:
            scores.append(result['design_score'])
            comments.append(result.get('comment', ''))
    
    if not scores:
        return {'design_score': None, 'comment': '', 'error': 'All runs failed'}
    
    import statistics
    median_score = int(statistics.median(scores))
    # Pick the comment from the run closest to median
    closest_idx = min(range(len(scores)), key=lambda i: abs(scores[i] - median_score))
    
    return {
        'design_score': median_score,
        'comment': comments[closest_idx],
        'score_runs': scores,  # For logging/debugging
        'score_std': statistics.stdev(scores) if len(scores) > 1 else 0
    }
```

**Cost:** 3x Gemini API calls per site. At Tier 1 pricing for `gemini-2.5-flash`, design scoring with vision tokens is approximately $0.0015-0.003 per call (image input tokens + output tokens). 3 runs = ~$0.005-0.009 per site. For 999 sites: ~$5-9 additional cost. Acceptable.

**Why median over mean:** The median is more robust to outlier runs (the 88 when two runs give 72 is cancelled). Mean would pull toward the outlier; median eliminates it entirely with 3 samples.

**Expected outcome:** Reduces effective variance from ±10 points to ±3-5 points across re-runs. Prevents single-run outliers from flipping letter grades.

**Research backing:** Liu et al. (2023) and subsequent work shows majority-vote/median across 3 LLM judge samples gives higher balanced accuracy than single-run with temperature=0. The key insight: T=0 gives you the modal path; median of 3 gives you the central tendency of the distribution.

#### B.3.4 MEDIUM IMPACT: Rubric Anchoring with Few-Shot Examples

The current design prompt lacks concrete anchor examples in the score range. Compare:

**Current (high variance):**
> "Score 0-100 for professional polish, sophistication, hierarchy, typography, spacing, visual clarity, and brand craft."

**Improved (lower variance):**
> ```
> SCORING ANCHORS:
> 90-100: Stripe.com, Linear.app, Vercel.com level — pixel-perfect spacing, strong brand system, 
>         intentional motion, exceptional type scale
> 70-89: Professional SaaS site — clear hierarchy, consistent components, good but not distinctive
> 50-69: Decent but generic — readable, functional, could belong to any company
> 30-49: Dated or inconsistent — clashing colors/fonts, poor spacing, template-level quality
> 0-29: Broken layout, unreadable text, obvious amateur design
> ```

Named reference points give the model calibration anchors. Without them, "70" and "80" are subjective labels. With named examples, the model is comparing against a consistent standard.

**Limitation:** Over time, as these example sites update their design, anchors may drift. Review anchors quarterly.

#### B.3.5 MEDIUM IMPACT: Gemini 2.5 Pro for Final Scoring

As an alternative to ensembling with Flash:

- Gemini 2.5 Pro achieves Cohen's Kappa of **0.925** vs Flash's **0.475** as an LLM judge (research 2025).
- Pro is far more consistent as an evaluator due to larger model capacity for nuanced judgments.
- Cost tradeoff: Pro is ~8-10x more expensive per token than Flash at Tier 1.
- For a 999-site run at current usage (~$1 total), switching design scoring to Pro would cost ~$5-8 total. Acceptable given cost is not a constraint.

**Recommendation:** If implementing only one change, switching to `gemini-2.5-pro` for the design scoring call (not content scoring) gives the biggest single-step improvement in consistency. Then add the response_schema and thinking_budget=0 changes on top.

#### B.3.6 LOW IMPACT: Pointwise vs. Pairwise Scoring

Pairwise scoring (show model two screenshots and ask "which is better?") has higher human-preference alignment than pointwise for the same model. However, it doesn't produce a cardinal score directly — you'd need a tournament or Elo system across your site corpus.

For a batch enrichment workflow scoring 999 independent sites, the overhead of pairwise comparison is impractical. Stick with pointwise but improve it via the techniques above.

---

### B.4 Implementation Priority for Part B

| Priority | Change | Expected Variance Reduction | Cost Impact | Effort |
|---|---|---|---|---|
| 1 | `thinking_budget=0` + `temperature=0` + `response_schema` (INTEGER type) | ~40% reduction | None | Low (3 lines) |
| 2 | Sub-dimension scoring (5 x 0-20 rubric) | ~35% reduction | None | Medium (rewrite prompt + sum logic) |
| 3 | 3-run median ensemble | ~50% reduction, orthogonal to above | +$5-9 per 999-site run | Medium (wrapper function) |
| 4 | Switch design call to `gemini-2.5-pro` | ~40% reduction (consistency, not just variance) | +$5-8 per 999-site run | Low (1 line change) |
| 5 | Rubric anchoring with named examples | ~20% reduction | None | Low |

**Recommended combined approach:** Priority 1 + Priority 2 + Priority 5 give roughly 60-70% variance reduction with zero cost increase and moderate implementation effort. Priority 3 adds more robustness at minimal cost.

---

### B.5 Monitoring Variance in Production

Add these fields to every design scoring call:

```python
result['design_score_run1'] = scores[0]   # if ensembling
result['design_score_run2'] = scores[1]
result['design_score_run3'] = scores[2]
result['design_score_std'] = statistics.stdev(scores)
```

Flag entries where `design_score_std > 5` as `high_variance_design` for manual review. This provides ongoing signal about which sites the model is uncertain on.

---

## Summary Table

### Part A: Non-Genuine Page Detection

| Signal | Implementation | Catches | Cost |
|---|---|---|---|
| DNS NS/IP check | `dnspython` + known NS list | GoDaddy, Sedo, Afternic, Dan, Bodis, ParkingCrew parking | Free |
| HTTP preflight `requests.get()` | Check `response.url` vs input | All cross-domain redirects, marketplace redirects | Free |
| Extend `ERROR_PAGE_PATTERNS` | Add parking + acquisition + bot-block regex | For-sale pages, acquisition pages, Cloudflare IUAM | Free |
| Firecrawl fallback | Use for bot-blocked sites only | Cloudflare, JS-heavy sites, login walls | ~Free (within free tier) |
| Identity check | Company name in title/H1 + thin content | Mismatch between company and page content | Free |

### Part B: LLM Variance Reduction

| Change | Variance Reduction | Priority |
|---|---|---|
| `thinking_budget=0` + `response_schema` + `temperature=0` | ~40% | Implement first |
| Sub-dimension scoring (5 x 0-20) | ~35% | Implement second |
| 3-run median ensemble | ~50% | Implement third |
| Switch to `gemini-2.5-pro` for design call | High consistency gain | Optional, ~$8/run |
| Rubric anchoring with named site examples | ~20% | Low effort, do it |

---

## Sources

- [The prevalence of domain parking — APNIC Blog](https://blog.apnic.net/2023/11/08/the-prevalence-of-domain-parking/)
- [Domain Parking: Gateway to Attackers — Palo Alto Unit 42](https://unit42.paloaltonetworks.com/domain-parking/)
- [Firecrawl Scrape API Reference](https://docs.firecrawl.dev/api-reference/endpoint/scrape)
- [Firecrawl Pricing 2026](https://www.firecrawl.dev/pricing)
- [Jina Reader API](https://jina.ai/reader/)
- [Gemini Structured Output — Google AI Docs](https://ai.google.dev/gemini-api/docs/structured-output)
- [Gemini Thinking — Google AI Docs](https://ai.google.dev/gemini-api/docs/thinking)
- [Is a Zero Temperature Deterministic? — Google Cloud Blog](https://medium.com/google-cloud/is-a-zero-temperature-deterministic-c4a7faef4d20)
- [Gemini 2.5 Pro Non-Determinism Issue — Google AI Developers Forum](https://discuss.ai.google.dev/t/the-gemini-api-is-exhibiting-non-deterministic-behavior-for-the-gemini-2-5-pro-model-it-is-producing-different-outputs-for-identical-requests-even-when-a-fixed-seed-is-provided-along-with-a-constant-temperature-this-behavior-has-been-reliably-rep/101331)
- [LLM Non-Determinism at Temperature 0 — QAnswer](https://www.qanswer.ai/blog/llm-non-determinism-temperature-zero)
- [Rating Roulette: Self-Inconsistency in LLM-As-A-Judge — EMNLP 2025](https://aclanthology.org/2025.findings-emnlp.1361.pdf)
- [Rubric-Based Evaluations & LLM-as-a-Judge — Medium/Apr 2026](https://medium.com/@adnanmasood/rubric-based-evals-llm-as-a-judge-methodologies-and-empirical-validation-in-domain-context-71936b989e80)
- [LLM-as-a-Judge Complete Guide — Evidently AI](https://www.evidentlyai.com/llm-guide/llm-as-a-judge)
- [Gemini 2.5 Flash vs Pro Comparison — LLM Stats](https://llm-stats.com/models/compare/gemini-2.5-flash-vs-gemini-2.5-pro)
- [Firecrawl Pricing Breakdown 2026 — ScrapeGraphAI](https://scrapegraphai.com/blog/firecrawl-pricing)
- [Best Web Scraping APIs 2026 — Zyte](https://www.zyte.com/blog/best-web-scraping-apis-2026/)
- [Playwright Cloudflare Bypass 2026 — BrowserStack](https://www.browserstack.com/guide/playwright-cloudflare)
- [How to Bulk Check for Parked Domains — Datablist](https://www.datablist.com/how-to/bulk-parked-domains-checker)
- [Parking Sensors: Analyzing and Detecting Parked Domains — NDSS 2015](https://www.ndss-symposium.org/wp-content/uploads/2017/09/01_2_2.pdf)
