# Feature: Content Grader v2 — Page Validity Gate + Calibrated Quality Scoring

## Overview

### Problem

The current content grader scores whatever text Jina AI extracts as if it belongs to the company's website. It is trivially fooled by pages that are not a genuine, live company homepage. The canonical failure is `www.enrich.ly`: Atom.com (formerly Squadhelp) serves a domain-for-sale marketplace page at that domain. Jina extracts ~1,071 words of Atom's own content (pricing plans, testimonials, case studies, brand name "Atom"), the programmatic scorer rewards all of it (+10 for pricing, +10 for testimonials/case-studies, +10 for numbers/CTA, +20 for word count), and the LLM rates the text 7-9 on all four dimensions because the *extracted content itself* is high quality — it just belongs to the wrong company. Result: 91/100 content score, B overall grade, a worthless page ranked as a top prospect.

The existing `detect_error_page()` uses regex patterns against text. That approach is narrow by design and will always have blind spots for novel categories.

### Design Goal

Insert a **Page Validity Gate** before the quality scorer. The gate establishes two things independently:

1. **Page State**: Is this a live company site, or something else (parking, for-sale, redirect, coming-soon, bot-block, 404, login wall, acquired/holding)?
2. **Identity Match**: Is the extracted content actually about the company at this domain, or does it belong to a different brand/platform?

If either check fails the gate, the pipeline **abstains** — it records page state, skips scoring, and sets the grade to `INVALID` (not F, not 0 — a dedicated state that prevents the entry from being ranked). The grader must be either confidently-correct or it abstains; it must never confidently mis-score.

### Success Criteria

1. `www.enrich.ly` is caught as `PARKED_OR_FOR_SALE` and receives no content score or letter grade.
2. `www.leadbay.ai` (an F-anchor site) continues to score below 40 and produce a letter grade rather than abstaining.
3. The five labeled A/B/F anchors in `test_graders.py` continue to pass their band assertions.
4. Run-to-run variance for a given live site narrows relative to v1 (target: content score spread ≤ 10 points across 3 runs, vs the current 11–21 point spread).
5. The gate introduces at most one additional Gemini call per site (the vision call is already happening for design scoring and can be shared).

### Dependencies

- Existing: Playwright (screenshot + HTTP metadata), Jina AI (text extraction), Gemini 2.5 Flash (text + vision)
- New: `tldextract` (registrable-domain parsing) — already likely in the venv transitively; add explicitly to `requirements.txt` if absent
- No new external APIs required

---

## Technical Approach

### Recommended Solution: Two-Stage Gate with Shared Vision Call

The gate runs immediately after Jina extraction and Playwright capture, before any quality scoring. It uses four signals fused by a single Gemini call (text + vision) into a structured JSON decision. A secondary deterministic guard layer provides redundancy so a single missed LLM signal does not yield a wrong grade.

```
INPUT: url, jina_result, playwright_capture_result
         |
         v
[Stage 1: Deterministic Pre-Checks]          <- cheap, no LLM
  - HTTP status check (from Playwright final URL)
  - Final URL domain vs input domain         <- redirect-to-different-domain
  - Known platform fingerprints in content   <- Atom/Squadhelp/Sedo/GoDaddy/etc.
  - Page title heuristics                    <- "domain for sale", "coming soon"
  - Content length gate                      <- <50 words always suspicious
  - Registrable domain vs brand-in-title     <- fast tldextract check
         |
         | If any hard block fires -> ABSTAIN immediately (no LLM call)
         | Else -> continue
         v
[Stage 2: LLM Gate Call — Gemini text + vision]  <- 1 call, shared screenshot
  - Sends: extracted text (truncated), page title, final URL, screenshot image,
           input domain, company name (from CSV)
  - Returns: structured JSON with page_state + confidence + identity_match
         |
         v
[Gate Decision]
  - page_state in {LIVE_COMPANY_SITE} AND identity_match=true AND confidence >= 0.75
       -> PASS -> proceed to quality scoring
  - page_state in {LIVE_COMPANY_SITE} AND identity_match=true AND 0.50 <= confidence < 0.75
       -> BORDERLINE -> second opinion call (text-only, same prompt, no image)
         - If second call agrees: PASS
         - If disagrees: ABSTAIN with state=BORDERLINE_DISAGREEMENT
  - anything else -> ABSTAIN with page_state from gate
         |
         v
[Quality Scorer — only reached on PASS]
  - Improved programmatic scorer (see Section 5)
  - Improved LLM quality call with tighter rubric and self-consistency
         |
         v
OUTPUT: gate_result (page_state, confidence, identity_match, gate_reason)
        + quality scores (content_score, programmatic_score, llm_score, etc.)
        OR abstain record (no letter_grade, page_state recorded)
```

### Alternatives Considered

**Alternative A: Expand the regex-based `detect_error_page()` with parking-page patterns**

Rejected. This is exactly the narrow enumerative approach the user explicitly ruled out. Each new category of bad page (acquired holding, login wall, bot block) requires new patterns. Novel for-sale platforms (beyond Atom/Sedo) will always slip through until explicitly added. Does not address identity mismatch at all.

**Alternative B: Separate vision-only gate using the existing design screenshot**

A purely vision-based gate is attractive because "a for-sale page looks like one." However, it cannot verify identity match (vision alone cannot reliably compare domain to brand name in content), and it fails silently on bot-block pages that render a Cloudflare challenge behind a screenshot that looks like a partial page. The recommended approach uses vision as one signal within a fused call rather than the sole arbiter.

**Alternative C: Use HTTP HEAD request + Playwright `response.url` only**

Redirect detection is cheap and reliable, but many bad pages (parking, for-sale, acquired holding) serve HTTP 200 at the original domain. A redirect-only check would miss the canonical `enrich.ly` failure since Atom serves the page directly at that domain without a redirect.

---

## Implementation Specification

### Data Flow

#### Input to Gate

```python
gate_input = {
    "url": str,                      # original input URL, e.g. "www.enrich.ly"
    "company_name": str,             # from CSV, e.g. "Enrich.ly"
    "jina_content": str,             # extracted markdown text
    "jina_title": str,               # page title from Jina response headers
    "playwright_final_url": str,     # URL after all redirects (from Playwright)
    "playwright_http_status": int,   # HTTP status of final navigation
    "screenshot_path": str,          # path to screenshot PNG (already captured)
    "content_word_count": int,
}
```

#### Gate Output Schema

```python
gate_result = {
    "page_state": str,               # see taxonomy below
    "identity_match": bool,          # content belongs to this domain's company
    "confidence": float,             # 0.0–1.0, LLM-reported
    "gate_passed": bool,             # True only if LIVE_COMPANY_SITE + identity_match + confidence >= threshold
    "gate_reason": str,              # human-readable explanation (1–2 sentences)
    "abstain": bool,                 # True means: do not score, do not grade
    "detected_platform": str | None, # e.g. "atom.com", "sedo.com" — if platform fingerprinted
    "redirect_domain": str | None,   # if final URL domain != input domain
}
```

### Page State Taxonomy

| State | Meaning | Primary Detection |
|---|---|---|
| `LIVE_COMPANY_SITE` | Genuine, live company website | LLM + all deterministic checks pass |
| `PARKED_OR_FOR_SALE` | Domain parking or domain marketplace | Platform fingerprint OR LLM vision + text |
| `ACQUIRED_REDIRECT` | Domain now redirects to acquiring company | Final URL domain != input domain |
| `COMING_SOON_PLACEHOLDER` | Under construction / launching soon | Title/content heuristic OR LLM |
| `BOT_BLOCKED` | Cloudflare, CAPTCHA, access denied | Content pattern + very low word count + screenshot |
| `ERROR_404_MAINTENANCE` | 404, maintenance mode, error page | Existing `detect_error_page()` patterns + LLM |
| `LOGIN_WALL` | Content is a login/signup gate, not homepage | LLM vision: form-dominated page + no company content |
| `CONTENT_MISMATCH` | Page loads but content is about a different entity | Identity match fails, not a known platform |
| `BORDERLINE_DISAGREEMENT` | Two LLM calls disagreed; cannot determine state | Second-opinion path |
| `INSUFFICIENT_CONTENT` | Word count too low to assess (<50 words after Jina) | Deterministic word-count check |
| `EXTRACTION_FAILED` | Jina and Playwright both failed to return usable content | Error state from extraction |

**Grading behavior per state:**

| State | Letter Grade | Content Score | Flag Added |
|---|---|---|---|
| `LIVE_COMPANY_SITE` + passed | Normal grade | Normal score | None |
| `PARKED_OR_FOR_SALE` | `INVALID` | None | `invalid_page:parked` |
| `ACQUIRED_REDIRECT` | `INVALID` | None | `invalid_page:redirect` |
| `COMING_SOON_PLACEHOLDER` | `INVALID` | None | `invalid_page:coming_soon` |
| `BOT_BLOCKED` | `INVALID` | None | `invalid_page:bot_blocked` |
| `ERROR_404_MAINTENANCE` | `INVALID` | None | `invalid_page:error` |
| `LOGIN_WALL` | `INVALID` | None | `invalid_page:login_wall` |
| `CONTENT_MISMATCH` | `INVALID` | None | `invalid_page:mismatch` |
| `BORDERLINE_DISAGREEMENT` | `INVALID` | None | `invalid_page:borderline` |
| `INSUFFICIENT_CONTENT` | `INVALID` | None | `invalid_page:insufficient` |
| `EXTRACTION_FAILED` | (existing error behavior, unchanged) | None | `grader_error` |

The key distinction: `INVALID` means "the page itself is not gradeable." It is not the same as a low grade. It should not appear in the grade distribution histogram or affect averages. In the CSV, `letter_grade` = `"INVALID"` and `total_grade_score` = `None`.

### Module Structure

#### New File: `scripts/page_gate.py`

This module is the entire gate. It has no side effects on scoring logic.

```python
# Key public function:
def assess_page_validity(
    url: str,
    company_name: str,
    jina_content: str,
    jina_title: str,
    playwright_final_url: str,
    playwright_http_status: int | None,
    screenshot_path: str,
    content_word_count: int,
    gemini_api_key: str,
    log_file: Path | None = None,
) -> dict:
    """
    Run the full page validity gate.
    Returns gate_result dict (schema above).
    Never raises — all exceptions are caught and returned as EXTRACTION_FAILED state.
    """
```

Internal functions (all private, `_` prefix):

```python
def _get_registrable_domain(url: str) -> str:
    """Extract registrable domain using tldextract. e.g. 'www.enrich.ly' -> 'enrich.ly'"""

def _check_redirect_domain(input_url: str, final_url: str) -> dict | None:
    """
    Returns a gate_result with ACQUIRED_REDIRECT if registrable domain changed, else None.
    Ignores www vs non-www and http vs https normalization.
    """

def _check_known_platforms(content: str, title: str) -> dict | None:
    """
    Returns a gate_result with PARKED_OR_FOR_SALE if a known parking/marketplace
    platform fingerprint is found in content or title, else None.
    This is the deterministic fast path for the canonical enrich.ly failure.
    """

def _check_content_length(word_count: int) -> dict | None:
    """Returns INSUFFICIENT_CONTENT gate_result if word_count < 50, else None."""

def _check_title_heuristics(title: str, content_first_300: str) -> dict | None:
    """
    Fast pattern match on title and first 300 chars for coming-soon,
    for-sale, login-wall indicators. Returns gate_result or None.
    """

def _run_llm_gate_call(
    url: str,
    company_name: str,
    content: str,
    title: str,
    screenshot_path: str,
    gemini_api_key: str,
    include_image: bool,
    log_file: Path | None,
) -> dict:
    """
    Single Gemini call returning raw parsed JSON gate assessment.
    temperature=0. Returns {'page_state': ..., 'identity_match': ...,
    'confidence': ..., 'reason': ..., 'detected_platform': ...}
    """

def _build_gate_prompt(
    url: str,
    company_name: str,
    content: str,
    title: str,
) -> str:
    """Build the gate prompt string (see Section 4 for exact text)."""
```

#### Modifications to `scripts/content_extractor.py`

- The existing `detect_error_page()` function is **retained as-is** for backward compatibility and as a cheap pre-filter that can catch obvious cases before the LLM gate fires.
- `analyze_content_with_llm()` signature is unchanged; the gate result is passed in by the caller (`grade_website`), not handled inside this function.
- Add a new function `get_llm_content_ratings_v2()` implementing the improved quality rubric (Section 5). The old function stays for backward compatibility; `grade_website` will call v2 when the gate passes.

#### Modifications to `scripts/website_grader.py`

In `grade_website()`, insert the gate call between Jina extraction and quality scoring:

```python
# EXISTING (around line 641-668):
#   jina_result = jina_extract_content(url, ...)
#   content_analysis_result = analyze_content_with_llm(...)

# NEW (to be inserted after jina extraction, before content scoring):
from page_gate import assess_page_validity

gate_result = assess_page_validity(
    url=url,
    company_name=company_name,          # new parameter added to grade_website()
    jina_content=jina_result.get('content', ''),
    jina_title=jina_result.get('title', ''),
    playwright_final_url=capture_result.get('final_url', ''),   # see below
    playwright_http_status=capture_result.get('http_status'),   # see below
    screenshot_path=screenshot_path,
    content_word_count=jina_result.get('word_count', 0),
    gemini_api_key=api_key,
    log_file=log_file,
)

# Store gate fields in result
result['page_state'] = gate_result['page_state']
result['gate_confidence'] = gate_result['confidence']
result['gate_reason'] = gate_result['gate_reason']
result['detected_platform'] = gate_result.get('detected_platform')

if gate_result['abstain']:
    result['letter_grade'] = 'INVALID'
    result['is_error_page'] = True
    result['error_type'] = gate_result['page_state'].lower()
    # content_score, design_score, total_grade_score remain None
    return result

# ... proceed to quality scoring as before, using get_llm_content_ratings_v2()
```

The `grade_website()` function needs two new parameters: `company_name: str = ''` (passed from orchestrator/process_csv) and those are already available in the calling contexts. Also add `company_name` as a parameter to `process_csv_async()` row loop since it already reads `companies[idx]`.

#### Capture `final_url` and `http_status` in Playwright

In `capture_screenshot_and_content()`, capture the final URL after navigation and HTTP status:

```python
# After successful page.goto():
result['final_url'] = page.url          # Playwright exposes post-redirect URL
result['http_status'] = response.status if response else None
# (page.goto() returns the response object; assign it to a variable)
```

This is a minimal, non-breaking addition to the existing function return dict.

#### New Output Columns (additions to existing schema)

| Column | Type | Description |
|---|---|---|
| `page_state` | str | Gate classification (e.g. `LIVE_COMPANY_SITE`, `PARKED_OR_FOR_SALE`) |
| `gate_confidence` | float | LLM confidence in gate decision (0.0–1.0) |
| `gate_reason` | str | 1–2 sentence explanation of gate decision |
| `detected_platform` | str | Platform fingerprinted if applicable (e.g. `atom.com`) |

The existing `letter_grade` column gains a new possible value: `"INVALID"`. Downstream filtering (e.g. `export_prospects.py`) should already exclude non-letter-grade values; add `!= "INVALID"` filter to be explicit.

Also add to `load_existing_results()` in `orchestrator.py`:
```python
'page_state': row.get('page_state', '') if pd.notna(row.get('page_state')) else '',
'gate_confidence': row.get('gate_confidence') if pd.notna(row.get('gate_confidence')) else None,
'gate_reason': row.get('gate_reason', '') if pd.notna(row.get('gate_reason')) else '',
'detected_platform': row.get('detected_platform', '') if pd.notna(row.get('detected_platform')) else '',
```

---

## Stage 1: Deterministic Pre-Checks (Detail)

### Redirect Domain Check

```python
import tldextract

def _get_registrable_domain(url: str) -> str:
    ext = tldextract.extract(url)
    return f"{ext.domain}.{ext.suffix}".lower()

# Example:
# "www.enrich.ly"  -> "enrich.ly"
# "atom.com/enrich.ly" -> "atom.com"
```

If `_get_registrable_domain(playwright_final_url) != _get_registrable_domain(input_url)`, return `ACQUIRED_REDIRECT` immediately. This catches acquisitions like "company.com now redirects to acquirer.com/company" without any LLM call.

Edge cases:
- `www.` normalization: handled by tldextract (strips subdomain)
- `http` vs `https`: tldextract ignores scheme
- CDN/proxy URLs (e.g. Cloudflare always redirects to the same domain): not affected, the registrable domain stays the same

### Known Platform Fingerprints

The canonical failure (Atom/Squadhelp) and the most common domain parking platforms have distinctive textual fingerprints. This check is fast and cheap.

```python
KNOWN_PARKING_PLATFORMS = [
    # (search_string, platform_name) — checked against content.lower() + title.lower()
    ("squadhelp.com",    "squadhelp.com"),
    ("atom.com",         "atom.com"),          # Atom is rebranded Squadhelp
    ("sedo.com",         "sedo.com"),
    ("dan.com",          "dan.com"),
    ("afternic.com",     "afternic.com"),
    ("godaddy.com/domainsearch", "godaddy.com"),
    ("hugedomains.com",  "hugedomains.com"),
    ("undeveloped.com",  "undeveloped.com"),
    ("epik.com",         "epik.com"),
    ("brandbucket.com",  "brandbucket.com"),
    ("brandpa.com",      "brandpa.com"),
    ("namerific.com",    "namerific.com"),
    # Generic parking phrases (check title first 200 chars only to reduce false positives)
    ("this domain is for sale",    "generic_parking"),
    ("buy this domain",            "generic_parking"),
    ("domain for sale",            "generic_parking"),
    ("make an offer",              "generic_parking"),    # title-only check
]
```

Implementation: check `platform_name` in `content[:3000].lower()` OR in `title.lower()`. Platform URLs in content are high-confidence because they appear as links or "powered by" attributions (e.g., Atom's page footer contains "atom.com" links).

**False positive risk:** A company legitimately mentioning Sedo or GoDaddy in a blog post. Mitigation: only flag if the platform string appears in the first 3,000 characters of content (above-the-fold content, not a blog article) OR in the page title. An additional guard: if `word_count > 2000` AND the platform fingerprint only appears once, reduce confidence rather than hard-blocking (pass to LLM gate instead).

### Title and First-300 Heuristics

```python
TITLE_PARKING_PATTERNS = [
    r'domain\s+(is\s+)?(for\s+sale|available)',
    r'buy\s+this\s+domain',
    r'make\s+an\s+offer',
]

TITLE_CONSTRUCTION_PATTERNS = [
    r'coming\s+soon',
    r'under\s+construction',
    r'launching\s+soon',
    r'site\s+under\s+construction',
]

TITLE_LOGIN_PATTERNS = [
    r'^(log\s*in|sign\s*in|login)\s*[\|–—-]',  # "Login | CompanyName"
    r'^(log\s*in|sign\s*in)\s*$',
]
```

These are checked against `title` (case-insensitive). If matched, return the corresponding state immediately without an LLM call. These are high-precision patterns on a short string — false positive risk is low.

---

## Stage 2: LLM Gate Call (Detail)

### Gate Prompt

The gate prompt is sent as a multimodal request: text prompt + screenshot image. `temperature=0`.

```
You are evaluating whether a URL points to a genuine, live company website.

DOMAIN: {registrable_domain}
COMPANY NAME (from database): {company_name}
PAGE TITLE: {title}
FINAL URL AFTER REDIRECTS: {final_url}
WORD COUNT: {word_count}

EXTRACTED TEXT (first 2500 words):
{content_truncated}

[SCREENSHOT IS ATTACHED]

---

TASK: Determine the page state and whether the content belongs to the company at this domain.

PAGE STATE — choose exactly one:
- LIVE_COMPANY_SITE: A real, live company website with content about its own products/services
- PARKED_OR_FOR_SALE: Domain parking page or domain marketplace (e.g. GoDaddy, Sedo, Atom/Squadhelp, Afternic, Dan.com, HugeDomains)
- ACQUIRED_REDIRECT: Domain acquired or redirected; content is about the acquiring company, not the original
- COMING_SOON_PLACEHOLDER: Under construction, coming soon, or blank placeholder
- BOT_BLOCKED: Cloudflare challenge, CAPTCHA, or access denied page
- ERROR_404_MAINTENANCE: 404, page not found, maintenance mode, or error page
- LOGIN_WALL: The page is a login or sign-up form with no company homepage content visible
- CONTENT_MISMATCH: Page loads real content but belongs to a completely different entity than the domain company

IDENTITY MATCH: Does the content and visual design represent the company at domain "{registrable_domain}"?
Answer true only if the content is clearly about this company's own products/services.
Answer false if the content belongs to a marketplace, platform, different company, or generic page.

CONFIDENCE: Your confidence in this assessment (0.0 to 1.0).
Be honest: use 0.5–0.7 for borderline cases, 0.8–1.0 for clear cases.

DETECTED PLATFORM: If this is a parking/marketplace page, name the platform (e.g. "atom.com", "sedo.com"). Otherwise null.

Return ONLY valid JSON (no markdown):
{
  "page_state": "<state from list above>",
  "identity_match": <true|false>,
  "confidence": <0.0-1.0>,
  "reason": "<1–2 sentences explaining your decision>",
  "detected_platform": "<platform or null>"
}
```

**Key design decisions in this prompt:**

1. The screenshot is included because visual design is a strong signal — a for-sale page is visually unmistakable even when content analysis is ambiguous.
2. The domain, title, final URL, and company name are all explicit context so the LLM does not need to infer them from content.
3. The state list is exhaustive and exclusive, forcing a single classification rather than free-text.
4. The confidence instruction explicitly defines what a borderline score looks like, calibrating the model's self-assessment.
5. Content is truncated to 2,500 words rather than the current 15,000-character (≈2,200-word) limit. For gate purposes, the above-the-fold content is the most signal-rich section. Full content is still passed to the quality scorer after the gate.

### Second-Opinion Path

When `page_state == LIVE_COMPANY_SITE` but `0.50 <= confidence < 0.75`:

A second call is made with the same prompt but **without the screenshot** (`include_image=False`). This tests whether the text alone supports the same conclusion. Using text-only for the second opinion provides a different evidence base.

Decision rules:
- Both calls say `LIVE_COMPANY_SITE` with `identity_match=true`: PASS (use higher of the two confidence values)
- First says LIVE, second says anything else: ABSTAIN as `BORDERLINE_DISAGREEMENT`
- The second call costs one additional Gemini text request (no image), which at Tier 1 is negligible

### Confidence Threshold Rationale

- `>= 0.75` required for single-call PASS. This is deliberately conservative. A live company site should consistently score 0.85+. The 0.75 threshold is chosen to catch uncertain cases while not over-blocking obvious sites.
- `0.50–0.75` triggers second opinion. Below 0.50 on a first call for a live site is very unusual and should abstain directly.
- If the LLM returns a malformed JSON or an error, treat as confidence=0.0 and abstain.

---

## Stage 3: Domain / Brand Identity Verification

Identity verification is partially handled in the LLM gate call (`identity_match` field). This section describes the additional deterministic check that runs in parallel.

### Registrable Domain vs Brand Name in Title

```python
def _check_domain_brand_match(
    registrable_domain: str,    # e.g. "enrich.ly"
    company_name: str,          # e.g. "Enrich.ly" (from CSV)
    page_title: str,            # e.g. "Domain for Sale | Atom"
    content_first_500: str,
) -> float:
    """
    Returns a domain-brand concordance score 0.0–1.0.
    High score = content is likely about this company.
    Low score = content may be about a different entity.
    """
```

Logic:
1. Extract the domain stem: `tldextract.extract("enrich.ly").domain` = `"enrich"`.
2. Extract the company name stem: strip common suffixes (`.ai`, `.io`, `.com`, `.ly`, `Inc`, `LLC`, `Corp`) and lowercase.
3. Check if the domain stem appears in `page_title` (case-insensitive). If the company owns the domain, their name almost always appears in their page title.
4. If `company_name` is available from the CSV (non-empty), also fuzzy-match it against the title using a simple token overlap (not a full Levenshtein to keep it cheap).

**This score is an input to the LLM gate call** (passed as context) and also used as a hard block:
- If domain stem does NOT appear in title and title does NOT contain company_name tokens AND content_word_count > 200: pass this signal to LLM as context, do not block deterministically (could be a legitimate company with a generic title).
- If the title contains another company's name (like "Atom" when domain is "enrich.ly") AND that other name appears to be a known platform: this reinforces the platform fingerprint check.

---

## Improved Quality Scoring (Pages That Pass the Gate)

### Problem with Current Scorer

Two issues:

1. **Generosity bias in the LLM rubric.** The current 1–10 scale gives too much scoring leverage to content that is clear and well-written, even if it is thin. A company with 300 words of polished copy scores 6–7 on all dimensions, yielding 42–49 raw LLM points → 73–86 scaled → 85–98 total content score. That is too high for a thin site.

2. **Noise from non-zero temperature.** The current code calls `genai.GenerativeModel('gemini-2.5-flash')` and passes `prompt` to `generate_content()` without specifying `generation_config`. Gemini's default temperature is 1.0. This is the primary source of the 11–21 point run-to-run spread observed in variance testing. Setting `temperature=0` eliminates almost all run-to-run variance.

### Fix 1: temperature=0 for ALL Gemini calls

In both `get_llm_content_ratings_v2()` and `_run_llm_gate_call()`:

```python
import google.generativeai as genai

model = genai.GenerativeModel(
    'gemini-2.5-flash',
    generation_config=genai.GenerationConfig(temperature=0),
)
```

This single change is the highest-leverage variance fix and should be applied to both the gate call and the quality scoring call.

### Fix 2: Revised LLM Quality Rubric

The new `get_llm_content_ratings_v2()` function uses a tighter rubric that is harder to score highly on thin content. Key changes:

- Add a **fifth dimension: Depth** (1–10), replacing the current implicit weighting that over-rewards any credibility signal. Depth specifically penalizes thin sites.
- Adjust anchor descriptions to be explicitly anchored to word-count tiers so the LLM calibrates against realistic websites.
- Keep the 1–10 scale per dimension but change the scaling formula: `LLM Score = (raw / 50) * 70` (5 dimensions × 10 max = 50 raw max). This is a minor adjustment but keeps the 70-point ceiling.
- Add explicit instruction: "Be critical. A B2B SaaS homepage with fewer than 400 words, no pricing, no case studies, and no named customers should score no higher than 5 on Credibility and no higher than 5 on Depth regardless of how polished the writing is."

#### Revised Prompt for `get_llm_content_ratings_v2()`

```
You are a senior B2B marketing consultant evaluating a SaaS company's website content.
This content has ALREADY been confirmed to belong to the company at this domain.
Be critical. Most real startup sites are mediocre. Reserve 8–10 for genuinely strong content.

COMPANY DOMAIN: {domain}
WORD COUNT: {word_count}
CONTENT:
{content_truncated}
{"[Content truncated...]" if truncated else ""}

---

RATE EACH DIMENSION (1–10). Use the full scale.

1. CLARITY (1–10): Can a first-time visitor immediately understand what this company does and who it serves?
   - 1–3: No clear explanation; buzzwords only ("We empower teams with AI-driven solutions")
   - 4–5: Vague but some specifics; unclear ICP or use case
   - 6–7: Clear product category, unclear differentiation or ICP
   - 8–9: Clear product, clear ICP, clear differentiation
   - 10: Instantly crystal-clear: what, who, why, how much, how to start

2. SUBSTANCE (1–10): Does the content go beyond headlines and marketing copy to provide real information?
   - 1–3: All headlines and CTAs, no explanatory content at all
   - 4–5: Some feature names listed but no explanation of how they work or why they matter
   - 6–7: Several features explained; missing pricing/process/technical details
   - 8–9: Comprehensive: features explained with context, pricing discussed, integration details
   - 10: Exhaustive: documentation-level detail, FAQs, technical specs, full pricing

3. CREDIBILITY (1–10): Does it build trust with verifiable, specific proof?
   - 1–3: No proof; only generic claims ("thousands of customers", "industry-leading")
   - 4–5: Logo wall only, or unnamed testimonials, or a single round number
   - 6–7: Named customers OR specific result statistics, but not both
   - 8–9: Named customers with specific results, or multiple verified case studies
   - 10: Multiple named customers + specific quantified results + verifiable external references

4. PERSUASIVENESS (1–10): Is there a compelling reason to take the next step?
   - 1–3: No differentiation; no reason to choose this over a competitor
   - 4–5: Some benefits listed but generic; weak or absent CTA
   - 6–7: Clear value proposition; decent CTA; some differentiation
   - 8–9: Compelling story; strong unique positioning; urgent, specific CTA
   - 10: Irresistible offer; pricing transparency; multiple conversion paths; strong social proof

5. DEPTH (1–10): How thorough and complete is the information for a buyer doing due diligence?
   - 1–3: Fewer than 200 words; no actionable information for a buyer
   - 4–5: 200–500 words; enough to know what it does but not enough to evaluate it
   - 6–7: 500–1000 words OR pricing available; reasonably complete for a first evaluation
   - 8–9: 1000–2000 words with pricing, feature details, integrations, or use cases
   - 10: 2000+ words; comprehensive for a buyer to make a shortlist decision

IMPORTANT: A polished 300-word homepage CANNOT score above 5 on Depth or 4 on Credibility, regardless of writing quality.

---

Return ONLY valid JSON (no markdown):
{"clarity": <1-10>, "substance": <1-10>, "credibility": <1-10>, "persuasiveness": <1-10>, "depth": <1-10>, "analysis": "<1 sentence summary>"}
```

#### Revised Scaling Formula

```
LLM Score = (clarity + substance + credibility + persuasiveness + depth) / 50 * 70
```

Range: minimum 5/50 * 70 = 7.0 points; maximum 50/50 * 70 = 70 points (unchanged ceiling).

A polished thin site (e.g., 300 words, clear copy, no pricing, no case studies) that scored 7+7+6+7 = 27 raw → 47 scaled under v1 would now score approximately 7+5+4+7+4 = 27 raw → 37.8 scaled under v2, a 9-point reduction. Combined with programmatic score (5/30 for 300 words), total ≈ 43 vs. the current ≈ 52.

### Fix 3: Programmatic Score — no change

The existing programmatic score (word count tiers + key element regexes) is well-calibrated and should be retained. The key elements detection correctly rewards pricing, testimonials, case studies, specific numbers, and CTAs. However, these signals should be validated against the page content AFTER the gate confirms identity — if the gate passes, the programmatic scorer's output is trustworthy. No changes needed.

---

## Error Handling

### Gate Failure Modes

| Failure | Behavior |
|---|---|
| Jina returns empty content | `EXTRACTION_FAILED` state; existing error behavior preserved |
| Playwright navigation failed | `EXTRACTION_FAILED` state; `final_url` defaults to input URL (redirect check skipped) |
| Screenshot file missing | LLM gate call is made text-only (`include_image=False`); no hard failure |
| Gemini API error (non-rate-limit) | Catch exception; if deterministic checks produced a state, use that; else `EXTRACTION_FAILED` |
| Gemini API rate limit (429) | Use existing `_retry_delay_from_error()` with up to 4 retries |
| Gemini returns malformed JSON | Retry once with a simpler prompt (see below); if still malformed, treat confidence=0 → abstain |
| `tldextract` failure | Catch exception; skip redirect check; log warning; proceed to LLM gate |
| Second-opinion call fails | Treat as disagreement → `BORDERLINE_DISAGREEMENT` |

#### Fallback Prompt for Malformed JSON

If the primary gate call returns non-parseable JSON, one retry with a simpler prompt:

```
Look at the screenshot and this text. Is this a genuine company website?
TEXT START: {content[:500]}
Answer with JSON only: {"is_live_site": true/false, "reason": "one sentence"}
```

If this also fails or returns `is_live_site: false`, set page_state=EXTRACTION_FAILED and abstain. If `is_live_site: true`, set page_state=LIVE_COMPANY_SITE with confidence=0.6 and proceed to second-opinion check.

### Gate Never Blocks a Valid Site (Anti-False-Positive Principle)

The gate is calibrated to prefer abstaining over incorrectly blocking a real site. If the LLM is uncertain (confidence < 0.75) about a `LIVE_COMPANY_SITE` classification, the second-opinion path is taken. A site only gets blocked if:
- A deterministic check fires (hard block — high precision), OR
- The LLM assigns a non-`LIVE_COMPANY_SITE` state with confidence >= 0.5

A live site that the LLM rates `LIVE_COMPANY_SITE` with confidence 0.6 gets a second chance via the second-opinion path.

---

## Configuration

### No New Environment Variables Required

The gate uses the existing `GEMINI_API_KEY`. No additional API keys are needed.

### Constants in `page_gate.py`

```python
GATE_CONFIDENCE_THRESHOLD = 0.75     # minimum confidence to pass on single call
GATE_BORDERLINE_LOW = 0.50           # below this -> abstain without second opinion
GATE_CONTENT_MAX_CHARS = 12500       # ~2500 words for gate call (vs 15000 for quality scorer)
GATE_PLATFORM_CONTENT_WINDOW = 3000  # chars to check for platform fingerprints
MIN_WORD_COUNT_FOR_GATE = 50         # below this -> INSUFFICIENT_CONTENT without LLM call
```

These can be tuned without code changes.

---

## Edge Cases and Considerations

### Edge Case 1: Legitimate company that mentions a parking platform

A company blog post that discusses domain brokerage might mention "Sedo" or "Afternic." Mitigation: the platform fingerprint check is limited to the first 3,000 characters of content. Blog posts appear later. Additionally, platform strings appearing only once with high word count (>2,000 words) are downgraded to a signal for the LLM rather than a hard block.

### Edge Case 2: Coming-soon page with a domain that matches the company

`company_name = "LaunchCo"`, domain = `launchco.com`, title = "Coming Soon | LaunchCo". The title heuristic fires on "Coming Soon" and returns `COMING_SOON_PLACEHOLDER`. This is correct — a coming-soon page should abstain. The company is not gradeable yet.

### Edge Case 3: Login wall that partially shows the product

Some SaaS sites (especially older ones or those requiring account creation) serve a login page at the root. The LLM vision call can see the screenshot — a page dominated by a login form with no product content visible scores as `LOGIN_WALL`. Identity match may be `true` (the company's logo is present) but the page is still not gradeable for content.

### Edge Case 4: Cloudflare challenge page screenshot

Cloudflare challenge pages have a distinctive visual appearance (orange/yellow brand, spinning wheel or checkbox). They also have very low word count in Jina extraction (~30–60 words: "Checking your browser..."). The `MIN_WORD_COUNT_FOR_GATE` check triggers first, but if word count is 50–100 words, the LLM gate fires with the screenshot. The vision model reliably identifies Cloudflare challenge pages.

### Edge Case 5: Domain acquired; new owner has legitimate content

Suppose `oldcompany.com` was acquired and now runs `newcompany.com`'s product. Playwright final URL is still `oldcompany.com` (no redirect). Content is about New Company. The redirect domain check does not fire. The LLM gate sees company_name="OldCompany" from CSV, content is about "NewCompany," and should return `CONTENT_MISMATCH` with identity_match=false. This is correct — the page is not about the prospect we were given.

### Edge Case 6: Apify/proxy URLs in final_url

Some testing environments or Apify actors may navigate through proxy domains. The redirect check uses tldextract; if the Playwright final URL is a proxy with a different domain, it will incorrectly flag ACQUIRED_REDIRECT. Mitigation: in `capture_screenshot_and_content()`, only record `final_url` if the page navigation fully completed; if it timed out on a proxy, `final_url` is None and the redirect check is skipped.

### Edge Case 7: Jina extracts the same company's About or 404 page when homepage fails

Jina may occasionally return content from a different path than `/`. If it returns a 404 page for a live site, `detect_error_page()` catches it before the gate. If it returns an `/about` page, the LLM gate correctly identifies it as a live company site (identity match is true regardless of subpath).

### Performance Considerations

- Deterministic checks add < 5ms per site.
- LLM gate call adds one Gemini request per site. At Tier 1 (~$0.001/request), this is ~$1 for 1,000 sites, per the user's cost estimate.
- The screenshot is already being captured for the design scorer. The gate reuses the same PNG file. No additional Playwright navigation is needed.
- The second-opinion path is only triggered for borderline cases (estimated 5–10% of sites). At most 100 additional calls for a 1,000-site run.

### Rate Limiting

The gate call is added sequentially in the design analysis loop (Phase 2 of `process_csv_async()`), not in the parallel Phase 1. This means it respects the existing `await asyncio.sleep(delay)` between sites. No additional rate limiting logic is required.

---

## Testing Plan

### Extension to `scripts/test_graders.py`

#### 1. Expand the Labeled Set

Add the following entries to `LABELED`:

```python
# Known parking/for-sale pages
('https://www.enrich.ly',           'PARK',      50, 'atom.com domain-for-sale; was wrongly B'),
('https://leadsbay.com',            'PARK',      50, 'if available: generic parking page'),

# Known redirect/acquired
# (add a real example from your CSV if available)

# Known coming-soon
# (add a real example from your CSV if available)

# Known bot-blocked
# (add a real example from your CSV if available)

# Login wall
('https://app.salesforce.com',      'LOGIN_WALL', 80, 'login wall; should abstain'),
```

#### 2. Update the `evaluate()` Function

```python
if band == 'PARK':
    # Gate must fire: either is_error_page=True OR letter_grade='INVALID' OR total < 40
    is_invalid = r.get('letter_grade') == 'INVALID'
    is_gated = r.get('page_state') not in (None, '', 'LIVE_COMPANY_SITE')
    return (is_invalid or is_error or total is None or (total is not None and total < 40),
            'letter_grade=INVALID or page_state!=LIVE or is_error or total<40')

if band == 'LOGIN_WALL':
    is_invalid = r.get('letter_grade') == 'INVALID'
    return is_invalid, 'letter_grade=INVALID'
```

#### 3. Add Gate-Specific Assertions to Calibration Output

Print the `page_state` and `gate_confidence` columns for every labeled entry so regressions are immediately visible:

```
URL                              exp    total  grade  cont   desg   state              conf  verdict  note
www.enrich.ly                    PARK      -      -      -      -   PARKED_OR_FOR_SALE  0.97  PASS
stripe.com                       A        91     A      96     72   LIVE_COMPANY_SITE   0.99  PASS
```

#### 4. Variance Test — Add Gate Stability Check

In `run_variance()`, also collect `page_state` and `gate_confidence` across runs. For a live site, both should be identical across all runs (deterministic at temperature=0). Any run where a live site changes state is an immediate regression.

#### Unit Test Scenarios (manual, without live network)

These should be implemented as a standalone `test_page_gate_unit.py` with mocked inputs:

| Scenario | Input | Expected gate_result |
|---|---|---|
| Atom platform fingerprint in content | content contains "atom.com" in first 2000 chars | PARKED_OR_FOR_SALE, abstain=True |
| Redirect to different domain | final_url="newco.com/old", input="oldco.com" | ACQUIRED_REDIRECT, abstain=True |
| Normal live site | stripe.com content, title "Stripe: Online Payment Processing" | LIVE_COMPANY_SITE, abstain=False |
| Empty content | word_count=0 | INSUFFICIENT_CONTENT, abstain=True |
| Title "Coming Soon \| LaunchCo" | title matches TITLE_CONSTRUCTION_PATTERNS | COMING_SOON_PLACEHOLDER, abstain=True |
| Short word count (30 words) | word_count=30 | INSUFFICIENT_CONTENT, abstain=True |
| Identity mismatch (LLM) | company_name="OldCo", content about "NewCo" | CONTENT_MISMATCH, abstain=True |
| Malformed JSON from LLM | LLM returns "Sorry I cannot..." | fallback path fires, abstain=True |

#### Manual Verification Steps

1. Run `python scripts/test_graders.py --no-variance` against the expanded labeled set. All PARK entries must show `INVALID` grade and a non-`LIVE_COMPANY_SITE` page_state.
2. Run `python scripts/test_graders.py --variance-runs 3` for `www.veezoo.com` and `www.leadbay.ai`. Verify content score spread is ≤ 10 points (down from 11–21 in v1).
3. Manually run `python scripts/content_extractor.py https://www.enrich.ly --analyze` (after backporting temperature=0 only) and verify score drops relative to v1 even before the gate.
4. Run the orchestrator with `--limit 5` on `crunchbase.csv` and verify the new columns (`page_state`, `gate_confidence`, `gate_reason`, `detected_platform`) appear in the output CSV.

---

## Implementation Checklist

In dependency order:

- [ ] **1. Add `tldextract` to `requirements.txt`** (simple — check if already present first)
- [ ] **2. Create `scripts/page_gate.py`** with all functions listed in Module Structure section (complex)
  - [ ] 2a. `_get_registrable_domain()` using tldextract
  - [ ] 2b. `_check_redirect_domain()` using 2a
  - [ ] 2c. `KNOWN_PARKING_PLATFORMS` list and `_check_known_platforms()`
  - [ ] 2d. `_check_content_length()`
  - [ ] 2e. `_check_title_heuristics()` with the three pattern lists
  - [ ] 2f. `_build_gate_prompt()` with exact prompt text from Section 4
  - [ ] 2g. `_run_llm_gate_call()` with temperature=0, image support, retry logic
  - [ ] 2h. `assess_page_validity()` orchestrating all checks and second-opinion path
- [ ] **3. Fix temperature in existing Gemini calls** (simple — add `generation_config` to both `get_llm_content_ratings()` and `analyze_design_with_gemini()`)
- [ ] **4. Add `get_llm_content_ratings_v2()` to `content_extractor.py`** (medium — new function, does not modify existing one)
  - [ ] 4a. 5-dimension prompt with revised rubric
  - [ ] 4b. New scaling formula `/ 50 * 70`
  - [ ] 4c. Add `depth` field to return dict
- [ ] **5. Capture `final_url` and `http_status` in `capture_screenshot_and_content()`** (simple — assign `page.goto()` return value, add two fields to result dict)
- [ ] **6. Integrate gate into `grade_website()`** (medium — insert gate call, handle abstain return path, pass company_name)
  - [ ] 6a. Add `company_name: str = ''` parameter to `grade_website()`
  - [ ] 6b. Add gate call after Jina extraction, before quality scoring
  - [ ] 6c. Add `page_state`, `gate_confidence`, `gate_reason`, `detected_platform` to result dict initialization
  - [ ] 6d. Add early return on `gate_result['abstain']` setting `letter_grade='INVALID'`
  - [ ] 6e. Replace `get_llm_content_ratings()` call with `get_llm_content_ratings_v2()` in the happy path
- [ ] **7. Pass `company_name` through `process_csv_async()`** (simple — `companies[idx]` already exists in the loop, add to `grade_website()` call)
- [ ] **8. Add new output columns to `process_csv_async()` DataFrame assignment** (simple)
- [ ] **9. Update `load_existing_results()` in `orchestrator.py`** to include the four new gate columns (simple)
- [ ] **10. Update `flag_entry()` in `orchestrator.py`** to recognize `letter_grade='INVALID'` as a valid non-error state (simple — add `'INVALID'` to the existing `missing_letter_grade` check exclusion)
- [ ] **11. Update `test_graders.py`** with expanded LABELED set, updated `evaluate()`, gate column display (medium)
- [ ] **12. Write `scripts/test_page_gate_unit.py`** with mocked inputs for the eight unit scenarios (medium)

---

## Future Enhancements

- **Cached gate results**: For a resume run, if a site was already gated as `LIVE_COMPANY_SITE` in a previous run, skip the gate call on resume (the gate decision is stored in the CSV). This would save ~30% of gate API calls on large resume runs.
- **Async gate calls**: The gate call is currently sequential (in Phase 2). A future optimization could batch gate calls in Phase 1 alongside screenshot captures, using a separate async queue, further reducing total wall-clock time.
- **Domain-level gate cache**: Within a single run, if multiple rows share the same registrable domain (e.g. two contacts at the same company), the gate result can be reused. This is a 1-line dict lookup.
- **Human review queue**: Rather than silently setting `INVALID`, expose a `--review-borderline` flag that exports borderline-disagreement entries to a separate CSV for manual inspection.
- **Widen the platform fingerprint list**: As new domain parking platforms emerge, they can be added to `KNOWN_PARKING_PLATFORMS` without any other code change.
- **Apply gate to design scoring**: Currently the design grader always runs if a screenshot is captured. After v2, if the gate abstains, the design call should also be skipped (screenshot is still taken as evidence, but Gemini vision is not called). This was not specified as in-scope but is a natural follow-on that saves one Gemini call per invalid site.
