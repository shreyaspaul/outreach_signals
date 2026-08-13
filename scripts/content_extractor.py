#!/usr/bin/env python3
"""
Content Extractor using Jina AI Reader API
Extracts clean, LLM-ready text content from websites.

Scoring System:
- Programmatic Score (30 points max): Word count + key elements detection
- LLM Score (70 points max): Clarity, Substance, Credibility, Persuasiveness
- Final Score = Programmatic + LLM = 0-100
"""

import os
import re
import time
import requests
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

# Load .env from project root
project_root = Path(__file__).parent.parent
load_dotenv(project_root / '.env')

# Configuration
JINA_API_URL = "https://r.jina.ai"
DEFAULT_TIMEOUT = 30  # seconds
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds
MAX_LLM_RETRIES = 4  # retries for Gemini content calls on rate-limit (429)


def _retry_delay_from_error(err_str, attempt):
    """
    Pick how long to wait before retrying a rate-limited Gemini call.

    The Gemini free tier returns "Please retry in 19.02s" on 429s; honoring that
    is the only reliable way to recover (exponential backoff alone caps too low).
    Falls back to exponential backoff when no hint is present.
    """
    m = re.search(r'retry in ([0-9.]+)s', err_str)
    if m:
        return float(m.group(1)) + 1.0  # small buffer past the suggested wait
    return min((2 ** attempt) * 2.0, 30.0)


def _is_retryable_error(err_str):
    """True for transient Gemini errors worth retrying.

    Covers rate limits (429) AND transient server errors (500/503/504/deadline/
    timeout/unavailable) — the latter silently dropped real prospects (e.g. a 504
    on Acctual's design call left it ungraded).
    """
    s = (err_str or '').lower()
    return any(t in s for t in (
        '429', 'rate', 'quota',
        '500', '503', '504', 'deadline', 'timeout', 'unavailable', 'internal error',
    ))

# Scoring weights
PROGRAMMATIC_MAX = 30  # Max points from programmatic scoring
LLM_MAX = 70  # Max points from LLM scoring

# Error page detection patterns
# Note: Using flexible patterns that handle curly apostrophes and word gaps
ERROR_PAGE_PATTERNS = [
    # 404 patterns
    r'\b404\b',
    r'page\s+not\s+found',
    r'page.{0,30}not\s+found',  # "page ... not found" with up to 30 chars between
    r'page.{0,30}(doesn.t|does\s*not)\s+exist',  # handles curly apostrophes with .
    r'page.{0,30}(isn.t|is\s*not)\s+available',
    r'(couldn.t|can.t)\s+find.{0,20}page',
    r'page.{0,20}(moved|removed|deleted)',
    r'no\s+longer\s+(exists?|available)',
    r'(this\s+)?page\s+(isn.t|is\s*not)\s+available',
    # Other error patterns
    r'error\s*occurred',
    r'something\s*went\s*wrong',
    r'access\s*denied',
    r'\bforbidden\b',
    r'under\s*construction',
    r'coming\s*soon',
    r'site.{0,20}(under\s*)?maintenance',
    r'temporarily\s*unavailable',
    r'oops',  # Common error page indicator
    r'we\s*(couldn.t|can.t)\s+find',
]


def detect_error_page(content: str, word_count: int = None) -> dict:
    """
    Detect if content appears to be a 404/error page.

    Returns:
        dict with:
            - is_error_page: bool
            - error_type: str (e.g., '404', 'maintenance', 'coming_soon', None)
            - reason: str (the pattern matched or reason for detection)
    """
    if not content:
        return {'is_error_page': True, 'error_type': 'empty', 'reason': 'No content extracted'}

    content_lower = content.lower().strip()

    # Very short content is suspicious
    if word_count is not None and word_count < 30:
        # Check for error patterns in short content
        for pattern in ERROR_PAGE_PATTERNS:
            if re.search(pattern, content_lower):
                # Determine error type
                if '404' in content_lower or 'not found' in content_lower or "doesn't exist" in content_lower:
                    error_type = '404'
                elif 'coming soon' in content_lower or 'under construction' in content_lower:
                    error_type = 'coming_soon'
                elif 'maintenance' in content_lower:
                    error_type = 'maintenance'
                elif 'denied' in content_lower or 'forbidden' in content_lower:
                    error_type = 'access_denied'
                else:
                    error_type = 'error'

                return {
                    'is_error_page': True,
                    'error_type': error_type,
                    'reason': f"Pattern matched: '{pattern}' in short content ({word_count} words)"
                }

    # Check title-like patterns (first 500 chars often contain the main message)
    first_section = content_lower[:500]

    # Strong 404 indicators (flexible patterns)
    strong_404_patterns = [
        r'\b404\b',
        r'page\s+not\s+found',
        r'page.{0,30}(doesn.t|does\s*not)\s+exist',
        r'page.{0,30}(isn.t|is\s*not)\s+available',
        r'page.{0,30}(has\s+been\s+)?(moved|removed|deleted)',
    ]

    for pattern in strong_404_patterns:
        if re.search(pattern, first_section, re.MULTILINE):
            return {
                'is_error_page': True,
                'error_type': '404',
                'reason': f"Strong 404 pattern in header: '{pattern}'"
            }

    return {'is_error_page': False, 'error_type': None, 'reason': None}


def normalize_url(url: str) -> str:
    """Ensure URL has proper scheme."""
    if not url:
        return url
    url = url.strip()
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    return url


def extract_content(url: str, api_key: str = None, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """
    Extract clean text content from a URL using Jina AI Reader.

    Args:
        url: Website URL to extract content from
        api_key: Jina AI API key (optional, but recommended for higher rate limits)
        timeout: Request timeout in seconds

    Returns:
        {
            'content': str,       # Clean markdown content
            'title': str,         # Page title
            'word_count': int,    # Word count of extracted content
            'char_count': int,    # Character count
            'error': str or None  # Error message if failed
        }
    """
    result = {
        'content': '',
        'title': '',
        'word_count': 0,
        'char_count': 0,
        'error': None
    }

    normalized_url = normalize_url(url)
    if not normalized_url:
        result['error'] = 'Invalid URL'
        return result

    # Build request
    jina_url = f"{JINA_API_URL}/{normalized_url}"
    headers = {
        'Accept': 'text/plain',  # Get clean markdown
        'User-Agent': 'OutreachSignals/1.0'
    }

    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'

    # Retry logic
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(jina_url, headers=headers, timeout=timeout)

            if response.status_code == 200:
                content = response.text.strip()

                # Parse title from markdown (usually first line)
                title = ''
                title_match = re.search(r'^Title:\s*(.+)$', content, re.MULTILINE)
                if title_match:
                    title = title_match.group(1).strip()

                # Extract just the markdown content (after "Markdown Content:")
                markdown_match = re.search(r'Markdown Content:\s*\n(.*)', content, re.DOTALL)
                if markdown_match:
                    content = markdown_match.group(1).strip()

                result['content'] = content
                result['title'] = title
                result['word_count'] = len(content.split())
                result['char_count'] = len(content)
                return result

            elif response.status_code == 429:
                # Rate limited - wait and retry
                wait_time = RETRY_DELAY * (attempt + 1)
                if attempt < MAX_RETRIES - 1:
                    time.sleep(wait_time)
                    continue
                last_error = 'Rate limited'

            elif response.status_code == 402:
                result['error'] = 'API quota exceeded'
                return result

            else:
                last_error = f'HTTP {response.status_code}'

        except requests.Timeout:
            last_error = 'Request timeout'
        except requests.RequestException as e:
            last_error = f'Request failed: {str(e)[:50]}'

        # Wait before retry
        if attempt < MAX_RETRIES - 1:
            time.sleep(RETRY_DELAY)

    result['error'] = last_error
    return result


def extract_multiple_pages(url: str, pages: list = None, api_key: str = None) -> dict:
    """
    Extract content from multiple pages of a website.

    Args:
        url: Base website URL
        pages: List of page paths to extract (default: ['/', '/about'])
        api_key: Jina AI API key

    Returns:
        {
            'pages': {
                '/': {'content': '...', 'title': '...', ...},
                '/about': {'content': '...', 'title': '...', ...}
            },
            'combined_content': str,  # All pages combined
            'total_word_count': int,
            'error': str or None
        }
    """
    if pages is None:
        pages = ['/', '/about']

    result = {
        'pages': {},
        'combined_content': '',
        'total_word_count': 0,
        'error': None
    }

    # Parse base URL
    parsed = urlparse(normalize_url(url))
    base_url = f"{parsed.scheme}://{parsed.netloc}"

    combined_parts = []
    errors = []

    for page_path in pages:
        # Build full URL for this page
        if page_path.startswith('http'):
            page_url = page_path
        elif page_path.startswith('/'):
            page_url = f"{base_url}{page_path}"
        else:
            page_url = f"{base_url}/{page_path}"

        # Extract content
        page_result = extract_content(page_url, api_key=api_key)
        result['pages'][page_path] = page_result

        if page_result['content']:
            combined_parts.append(f"## Page: {page_path}\n\n{page_result['content']}")
            result['total_word_count'] += page_result['word_count']

        if page_result['error']:
            errors.append(f"{page_path}: {page_result['error']}")

        # Small delay between requests
        time.sleep(0.5)

    result['combined_content'] = '\n\n---\n\n'.join(combined_parts)

    if errors and not result['combined_content']:
        result['error'] = '; '.join(errors)

    return result


def calculate_programmatic_score(content: str) -> dict:
    """
    Calculate programmatic content score based on objective metrics.

    Returns:
        {
            'word_count': int,
            'word_score': int (0-20),
            'key_elements': dict,
            'element_score': int (0-10),
            'programmatic_total': int (0-30)
        }
    """
    content_lower = content.lower()
    word_count = len(content.split())

    # Word count score (0-20 points)
    if word_count < 150:
        word_score = 0
    elif word_count < 300:
        word_score = 5
    elif word_count < 500:
        word_score = 10
    elif word_count < 800:
        word_score = 15
    else:
        word_score = 20

    # Key elements detection (0-10 points, +2 each)
    key_elements = {
        'has_pricing': False,
        'has_testimonials': False,
        'has_case_studies': False,
        'has_specific_numbers': False,
        'has_cta': False
    }

    # Pricing detection
    pricing_patterns = [
        r'\$\d+', r'pricing', r'price', r'cost', r'plans', r'/month', r'/year',
        r'free trial', r'free plan', r'starter', r'enterprise', r'per user'
    ]
    if any(re.search(p, content_lower) for p in pricing_patterns):
        key_elements['has_pricing'] = True

    # Testimonials detection
    # NOTE: patterns are word-bounded to avoid false positives:
    #   - bare 'review' matched 'preview'; bare 'stars?' matched 'start/started/starter'
    testimonial_patterns = [
        r'\btestimonials?\b', r'\breviews?\b', r'customer said', r'what .* say',
        r'\"[^\"]{20,}\"',  # Quoted text (likely testimonial)
        r'★', r'⭐', r'\b\d(?:\.\d)?\s*stars?\b'  # rating context, e.g. "5 stars", "4.5 stars"
    ]
    if any(re.search(p, content_lower) for p in testimonial_patterns):
        key_elements['has_testimonials'] = True

    # Case studies detection
    case_study_patterns = [
        r'case stud', r'success stor', r'customer stor', r'how .* helped',
        r'helped .* achieve', r'results for', r'worked with'
    ]
    if any(re.search(p, content_lower) for p in case_study_patterns):
        key_elements['has_case_studies'] = True

    # Specific numbers/stats detection
    number_patterns = [
        r'\d+\+?\s*(customers|clients|users|companies|businesses)',
        r'\d+%', r'\d+x', r'\$\d+[km]?', r'\d+\s*(million|billion|k\b)',
        r'increased .* by \d+', r'reduced .* by \d+', r'saved .* \d+'
    ]
    if any(re.search(p, content_lower) for p in number_patterns):
        key_elements['has_specific_numbers'] = True

    # CTA detection
    cta_patterns = [
        r'get started', r'sign up', r'start free', r'book a demo',
        r'schedule a call', r'contact us', r'request a quote', r'try free',
        r'start now', r'join now', r'subscribe', r'download'
    ]
    if any(re.search(p, content_lower) for p in cta_patterns):
        key_elements['has_cta'] = True

    # Calculate element score (+2 for each)
    element_score = sum(2 for v in key_elements.values() if v)

    return {
        'word_count': word_count,
        'word_score': word_score,
        'key_elements': key_elements,
        'element_score': element_score,
        'programmatic_total': word_score + element_score
    }


def get_llm_content_ratings(content: str, url: str = None, api_key: str = None, log_file: Path = None) -> dict:
    """
    Get LLM ratings for 4 content dimensions (1-10 each).

    Args:
        content: Extracted markdown content
        url: Website URL (for logging)
        api_key: Gemini API key
        log_file: Path to log file for request/response logging

    Returns:
        {
            'clarity': int (1-10),
            'substance': int (1-10),
            'credibility': int (1-10),
            'persuasiveness': int (1-10),
            'llm_raw_total': int (4-40),
            'llm_scaled_score': float (0-70),
            'analysis': str,
            'error': str or None
        }
    """
    import google.generativeai as genai
    import json
    from datetime import datetime

    result = {
        'clarity': None,
        'substance': None,
        'credibility': None,
        'persuasiveness': None,
        'llm_raw_total': None,
        'llm_scaled_score': None,
        'analysis': '',
        'error': None
    }

    api_key = api_key or os.getenv('GEMINI_API_KEY')
    if not api_key:
        result['error'] = 'Missing GEMINI_API_KEY'
        return result

    if not content or len(content) < 50:
        result['error'] = 'Insufficient content to analyze'
        return result

    # Truncate very long content
    max_chars = 15000
    truncated = False
    if len(content) > max_chars:
        content = content[:max_chars]
        truncated = True

    genai.configure(api_key=api_key)
    # temperature=0 for deterministic, repeatable content scoring.
    model = genai.GenerativeModel('gemini-2.5-flash', generation_config={'temperature': 0.0})

    word_count = len(content.split())

    prompt = f"""Rate this website content on 4 dimensions. Give a score from 1-10 for each.

CONTENT ({word_count} words):
{content}
{"[Content truncated...]" if truncated else ""}

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
{{"clarity": <1-10>, "substance": <1-10>, "credibility": <1-10>, "persuasiveness": <1-10>, "analysis": "<1 sentence summary>"}}"""

    # Log the request
    if log_file:
        try:
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(f"\n{'='*80}\n")
                f.write(f"CONTENT ANALYSIS REQUEST\n")
                f.write(f"TIMESTAMP: {datetime.now().isoformat()}\n")
                f.write(f"URL: {url or 'N/A'}\n")
                f.write(f"WORD COUNT: {word_count}\n")
                f.write(f"TRUNCATED: {truncated}\n")
                f.write(f"\n--- CONTENT SENT TO GEMINI ---\n")
                f.write(content[:2000])
                if len(content) > 2000:
                    f.write(f"\n... [{len(content) - 2000} more characters] ...\n")
                f.write(f"\n--- END CONTENT ---\n")
        except Exception as log_error:
            print(f"Warning: Could not write to log file: {log_error}")

    # Call Gemini with retry on rate-limit (429), honoring the API's suggested
    # wait. Without this the free-tier 20 RPM cap silently fails content scoring.
    response_text = None
    for attempt in range(MAX_LLM_RETRIES):
        try:
            response = model.generate_content(prompt)
            try:
                from _token_log import log_usage; log_usage('content', response)
            except Exception:
                pass
            response_text = response.text.strip()
            break
        except Exception as e:
            error_msg = str(e)
            is_rate = _is_retryable_error(error_msg)
            if is_rate and attempt < MAX_LLM_RETRIES - 1:
                time.sleep(_retry_delay_from_error(error_msg, attempt))
                continue
            if log_file:
                try:
                    with open(log_file, 'a', encoding='utf-8') as f:
                        f.write(f"\n--- ERROR (attempt {attempt + 1}) ---\n{error_msg}\n--- END ERROR ---\n")
                except Exception:
                    pass
            result['error'] = f'LLM analysis failed: {error_msg[:50]}'
            return result

    try:
        # Log the response
        if log_file:
            try:
                with open(log_file, 'a', encoding='utf-8') as f:
                    f.write(f"\n--- GEMINI RESPONSE ---\n")
                    f.write(response_text)
                    f.write(f"\n--- END RESPONSE ---\n")
            except Exception:
                pass

        # Extract JSON
        json_match = re.search(r'\{[^{}]*\}', response_text)
        if json_match:
            try:
                data = json.loads(json_match.group())

                # Extract and validate scores (clamp to 1-10)
                result['clarity'] = max(1, min(10, int(data.get('clarity', 5))))
                result['substance'] = max(1, min(10, int(data.get('substance', 5))))
                result['credibility'] = max(1, min(10, int(data.get('credibility', 5))))
                result['persuasiveness'] = max(1, min(10, int(data.get('persuasiveness', 5))))
                result['analysis'] = data.get('analysis', '')

                # Calculate totals
                llm_raw = result['clarity'] + result['substance'] + result['credibility'] + result['persuasiveness']
                result['llm_raw_total'] = llm_raw
                result['llm_scaled_score'] = (llm_raw / 40) * LLM_MAX  # Scale to 70 points max

            except (json.JSONDecodeError, ValueError, TypeError) as e:
                result['error'] = f'Could not parse LLM response: {str(e)[:30]}'
        else:
            result['error'] = 'Could not find JSON in LLM response'

    except Exception as e:
        error_msg = str(e)
        if log_file:
            try:
                with open(log_file, 'a', encoding='utf-8') as f:
                    f.write(f"\n--- ERROR ---\n{error_msg}\n--- END ERROR ---\n")
            except Exception:
                pass
        result['error'] = f'LLM analysis failed: {error_msg[:50]}'

    return result


# v2 content rubric: adds a 5th dimension (Depth) that explicitly penalizes thin
# sites, with tighter anchors so polished-but-shallow copy can't score highly.
# response_schema forces clean structured output; temperature=0 for repeatability.
CONTENT_V2_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "clarity_reason": {"type": "STRING"},
        "clarity": {"type": "INTEGER"},
        "substance_reason": {"type": "STRING"},
        "substance": {"type": "INTEGER"},
        "credibility_reason": {"type": "STRING"},
        "credibility": {"type": "INTEGER"},
        "persuasiveness_reason": {"type": "STRING"},
        "persuasiveness": {"type": "INTEGER"},
        "depth_reason": {"type": "STRING"},
        "depth": {"type": "INTEGER"},
        "analysis": {"type": "STRING"},
    },
    "required": ["clarity_reason", "clarity", "substance_reason", "substance",
                 "credibility_reason", "credibility", "persuasiveness_reason", "persuasiveness",
                 "depth_reason", "depth", "analysis"],
}


def get_llm_content_ratings_v2(content: str, url: str = None, api_key: str = None, log_file: Path = None) -> dict:
    """
    v2: Get LLM ratings for 5 content dimensions (1-10 each), incl. Depth.

    Scaling: (clarity+substance+credibility+persuasiveness+depth) / 50 * 70.
    Returns the same shape as get_llm_content_ratings plus 'depth'.
    """
    import google.generativeai as genai
    import json
    from datetime import datetime

    result = {
        'clarity': None, 'substance': None, 'credibility': None,
        'persuasiveness': None, 'depth': None,
        'llm_raw_total': None, 'llm_scaled_score': None,
        'analysis': '', 'content_reasoning': '', 'error': None
    }

    api_key = api_key or os.getenv('GEMINI_API_KEY')
    if not api_key:
        result['error'] = 'Missing GEMINI_API_KEY'
        return result
    if not content or len(content) < 50:
        result['error'] = 'Insufficient content to analyze'
        return result

    max_chars = 15000
    truncated = len(content) > max_chars
    if truncated:
        content = content[:max_chars]

    # THINKING OFF for content scoring (validated n=30: ~5pt scatter vs thinking-on,
    # no systematic bias; ~72% cheaper on this step). Uses the new google-genai SDK
    # because the legacy SDK can't disable thinking. Design + gate keep thinking ON.
    from google import genai as _genai_new
    from google.genai import types as _gtypes
    # Per-request timeout (ms) so a stalled connection can't hang the whole run forever
    # (a no-timeout call froze the 700-run for ~7h on one site). On timeout it raises ->
    # the retry loop below catches it (retryable) and fails fast instead of hanging.
    _client = _genai_new.Client(api_key=api_key,
                                http_options=_gtypes.HttpOptions(timeout=90000))
    _gen_config = _gtypes.GenerateContentConfig(
        temperature=0.0,
        response_mime_type='application/json',
        response_schema=CONTENT_V2_RESPONSE_SCHEMA,
        thinking_config=_gtypes.ThinkingConfig(thinking_budget=0),
    )

    word_count = len(content.split())

    prompt = f"""You are a BRUTALLY HONEST B2B content strategist evaluating a company's website copy.
The content already belongs to this company. Most startup copy is generic and forgettable — your
job is to SEPARATE genuinely strong content from the merely acceptable. DO NOT cluster scores high;
that is the #1 failure mode. Generic-but-clear copy is AVERAGE (5-6), not good.

For EACH dimension you MUST first write one sentence of SPECIFIC evidence quoting or pointing to
something in the actual content (the *_reason field), THEN give the 1-10 score. The score must
follow from the evidence — never score high without citing concrete specifics from the page.

CALIBRATION — use the FULL 1-10 range, be strict:
   1-2  absent / broken
   3-4  generic, vague, buzzwords, thin
   5-6  AVERAGE: clear-ish but unremarkable — typical startup copy lands HERE
   7-8  GOOD: specific, substantive, concrete detail or real proof
   9-10 EXCEPTIONAL: unusually clear, deep, proof-rich, compelling
Default to 5-6 unless your evidence sentence names concrete specifics that justify higher.

WORD COUNT: {word_count}
CONTENT:
{content}
{"[Content truncated...]" if truncated else ""}

---

DIMENSIONS (write evidence first, then score):

1. CLARITY: Can a first-time visitor instantly tell WHAT it does, FOR WHOM, and WHY it's different?
   Generic ("we help teams work smarter") = 3-5. Specific product + ICP + differentiation = 7-8.

2. SUBSTANCE: Real explanation (how it works, concrete features, specifics) vs marketing fluff?
   Headlines/taglines only = 3-4. Features merely named = 5. Features actually explained = 7-8.

3. CREDIBILITY: Verifiable, specific proof — NAMED customers, QUANTIFIED results, case studies?
   No proof / generic claims = 2-4. Logo wall or unnamed quotes = 4-5. Named + specific results = 7-9.

4. PERSUASIVENESS: Genuine differentiation + a strong, specific call to action?
   No real reason to choose them = 3-4. Clear value prop + decent CTA = 6-7. Compelling + urgent = 8-9.

5. DEPTH: Enough thorough information for a buyer's due diligence?
   This is heavily gated by substance and word count.

HARD RULES (these OVERRIDE the rubric):
- A page under ~400 words CANNOT score above 5 on DEPTH.
- No pricing, no named customers, AND no case studies => CREDIBILITY cannot exceed 4.
- "Clean / clear / professional writing" is NOT evidence for 7+. That is average (5-6).

Return JSON: for each dimension a one-sentence evidence reason then the integer score, plus a
one-sentence overall analysis."""

    if log_file:
        try:
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(f"\n{'='*80}\n")
                f.write("CONTENT ANALYSIS REQUEST (v2)\n")
                f.write(f"TIMESTAMP: {datetime.now().isoformat()}\n")
                f.write(f"URL: {url or 'N/A'}\n")
                f.write(f"WORD COUNT: {word_count}\n")
                f.write(f"TRUNCATED: {truncated}\n")
        except Exception as log_error:
            print(f"Warning: Could not write to log file: {log_error}")

    response_text = None
    for attempt in range(MAX_LLM_RETRIES):
        try:
            response = _client.models.generate_content(
                model='gemini-2.5-flash', contents=[prompt], config=_gen_config)
            try:
                from _token_log import log_usage; log_usage('content', response)
            except Exception:
                pass
            response_text = (response.text or '').strip()
            break
        except Exception as e:
            error_msg = str(e)
            is_rate = _is_retryable_error(error_msg)
            if is_rate and attempt < MAX_LLM_RETRIES - 1:
                time.sleep(_retry_delay_from_error(error_msg, attempt))
                continue
            if log_file:
                try:
                    with open(log_file, 'a', encoding='utf-8') as f:
                        f.write(f"\n--- ERROR (attempt {attempt + 1}) ---\n{error_msg}\n--- END ERROR ---\n")
                except Exception:
                    pass
            result['error'] = f'LLM analysis failed: {error_msg[:50]}'
            return result

    try:
        if log_file:
            try:
                with open(log_file, 'a', encoding='utf-8') as f:
                    f.write(f"\n--- GEMINI RESPONSE (v2) ---\n{response_text}\n--- END RESPONSE ---\n")
            except Exception:
                pass

        try:
            data = json.loads(response_text)
        except json.JSONDecodeError:
            m = re.search(r'\{.*\}', response_text, re.DOTALL)
            data = json.loads(m.group()) if m else None

        if not data:
            result['error'] = 'Could not find JSON in LLM response'
            return result

        for dim in ('clarity', 'substance', 'credibility', 'persuasiveness', 'depth'):
            result[dim] = max(1, min(10, int(data.get(dim, 5))))
        result['analysis'] = data.get('analysis', '')

        # Build an auditable, human-readable justification from the per-dimension
        # evidence the model wrote before each score.
        labels = [('clarity', 'Clarity'), ('substance', 'Substance'),
                  ('credibility', 'Credibility'), ('persuasiveness', 'Persuasiveness'),
                  ('depth', 'Depth')]
        lines = []
        for key, label in labels:
            reason = (data.get(f'{key}_reason') or '').strip()
            lines.append(f"{label} {result[key]}/10 — {reason}")
        result['content_reasoning'] = "\n".join(lines)

        llm_raw = (result['clarity'] + result['substance'] + result['credibility']
                   + result['persuasiveness'] + result['depth'])
        result['llm_raw_total'] = llm_raw
        result['llm_scaled_score'] = (llm_raw / 50) * LLM_MAX  # 5 dims x 10 = 50 raw max
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        result['error'] = f'Could not parse LLM response: {str(e)[:30]}'

    return result


def analyze_content_with_llm(content: str, url: str = None, api_key: str = None, log_file: Path = None) -> dict:
    """
    Full content analysis combining programmatic + LLM scoring.

    Programmatic (30 points max): Word count + key elements
    LLM (70 points max): Clarity + Substance + Credibility + Persuasiveness

    Returns:
        {
            'content_score': int (0-100),
            'programmatic_score': int (0-30),
            'llm_score': float (0-70),
            'clarity': int (1-10),
            'substance': int (1-10),
            'credibility': int (1-10),
            'persuasiveness': int (1-10),
            'content_analysis': str,
            'word_count': int,
            'key_elements': dict,
            'is_error_page': bool,
            'error_type': str or None,
            'error': str or None
        }
    """
    result = {
        'content_score': None,
        'programmatic_score': None,
        'llm_score': None,
        'clarity': None,
        'substance': None,
        'credibility': None,
        'persuasiveness': None,
        'depth': None,
        'content_analysis': '',
        'content_reasoning': '',
        'word_count': 0,
        'key_elements': {},
        'is_error_page': False,
        'error_type': None,
        'error': None
    }

    if not content or len(content) < 50:
        result['error'] = 'Insufficient content to analyze'
        result['is_error_page'] = True
        result['error_type'] = 'empty'
        return result

    # Calculate word count first for error page detection
    word_count = len(content.split())

    # Step 0: Check if this is an error/404 page
    error_check = detect_error_page(content, word_count)
    if error_check['is_error_page']:
        result['is_error_page'] = True
        result['error_type'] = error_check['error_type']
        result['word_count'] = word_count
        result['content_score'] = 0
        result['programmatic_score'] = 0
        result['llm_score'] = 0
        result['content_analysis'] = f"Error page detected: {error_check['error_type']} - {error_check['reason']}"

        # Log the error page detection
        if log_file:
            try:
                from datetime import datetime
                with open(log_file, 'a', encoding='utf-8') as f:
                    f.write(f"\n{'='*80}\n")
                    f.write(f"ERROR PAGE DETECTED\n")
                    f.write(f"TIMESTAMP: {datetime.now().isoformat()}\n")
                    f.write(f"URL: {url}\n")
                    f.write(f"ERROR TYPE: {error_check['error_type']}\n")
                    f.write(f"REASON: {error_check['reason']}\n")
                    f.write(f"WORD COUNT: {word_count}\n")
                    f.write(f"CONTENT PREVIEW: {content[:200]}...\n")
                    f.write(f"{'='*80}\n")
            except Exception:
                pass

        return result

    # Step 1: Calculate programmatic score
    prog_result = calculate_programmatic_score(content)
    result['word_count'] = prog_result['word_count']
    result['key_elements'] = prog_result['key_elements']
    result['programmatic_score'] = prog_result['programmatic_total']

    # Step 2: Get LLM ratings (v2 — 5 dimensions incl. Depth)
    llm_result = get_llm_content_ratings_v2(content, url=url, api_key=api_key, log_file=log_file)

    if llm_result.get('error'):
        result['error'] = llm_result['error']
        # Still return programmatic score even if LLM fails
        result['content_score'] = prog_result['programmatic_total']  # Only programmatic portion
        result['content_analysis'] = f"LLM analysis failed. Programmatic score only ({prog_result['programmatic_total']}/30)"
        return result

    # Step 3: Combine scores
    result['clarity'] = llm_result['clarity']
    result['substance'] = llm_result['substance']
    result['credibility'] = llm_result['credibility']
    result['persuasiveness'] = llm_result['persuasiveness']
    result['depth'] = llm_result['depth']
    result['llm_score'] = llm_result['llm_scaled_score']
    result['content_analysis'] = llm_result['analysis']
    result['content_reasoning'] = llm_result.get('content_reasoning', '')

    # Final score = Programmatic (0-30) + LLM (0-70) = 0-100
    result['content_score'] = int(prog_result['programmatic_total'] + llm_result['llm_scaled_score'])

    # Log the final calculation
    if log_file:
        try:
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(f"\n--- SCORE CALCULATION ---\n")
                f.write(f"Programmatic: {prog_result['programmatic_total']}/30\n")
                f.write(f"  - Word count ({prog_result['word_count']}): {prog_result['word_score']}/20\n")
                f.write(f"  - Key elements: {prog_result['element_score']}/10\n")
                f.write(f"    {prog_result['key_elements']}\n")
                f.write(f"LLM: {llm_result['llm_scaled_score']:.1f}/70\n")
                f.write(f"  - Clarity: {llm_result['clarity']}/10\n")
                f.write(f"  - Substance: {llm_result['substance']}/10\n")
                f.write(f"  - Credibility: {llm_result['credibility']}/10\n")
                f.write(f"  - Persuasiveness: {llm_result['persuasiveness']}/10\n")
                f.write(f"  - Depth: {llm_result['depth']}/10\n")
                f.write(f"  - Raw total: {llm_result['llm_raw_total']}/50 -> scaled to {llm_result['llm_scaled_score']:.1f}/70\n")
                f.write(f"FINAL SCORE: {result['content_score']}/100\n")
                f.write(f"--- END CALCULATION ---\n")
        except Exception:
            pass

    return result


# ---------------------------------------------------------------------------
# Quotable "proud facts" extraction (for outreach hooks). See specs/proud-facts-plan.md
# ---------------------------------------------------------------------------
PROUD_FACTS_PROMPT = """You extract specific, credible, QUOTABLE facts a founder would be proud of, from their website content, for use in a personalized outreach message.

ONLY extract concrete, verifiable facts that are explicitly stated in the content. Good facts (examples):
- community size ("40,000-member Discord", "100k newsletter subscribers")
- customers/users ("used by 2,000 teams", "500,000 users")
- funding/backers ("raised $12M Series A", "backed by Y Combinator")
- volume/scale ("processed $1B in payments", "1M videos generated")
- ratings/reviews ("4.9 stars from 3,000 reviews")
- notable customers ("trusted by Netflix and Spotify")
- growth/milestones ("grew 300% last year", "founded 2019")
- awards.

Do NOT include vague marketing claims ("best-in-class", "trusted by many", "industry leading", "the #1 platform") — those are not quotable facts.
Quote the exact number/name as written. Do not round, infer, or combine. If unsure a fact is really in the text, leave it out.

Return ONLY a JSON list (max 3, strongest first). Each item:
{"fact":"<short natural phrasing of the fact>","type":"community|customers|funding|volume|rating|backers|notable_customer|growth|award|other","evidence":"<the exact substring from the content that states it>"}
If there are no concrete quotable facts, return []."""


def _norm(s):
    return re.sub(r'\s+', ' ', (s or '')).strip().lower()


def _verify_fact(fact_obj, content):
    """A fact is trusted only if it's substantiated by the source text: the evidence
    phrase appears in the content, OR every numeric token in the fact appears in it."""
    low = _norm(content)
    ev = _norm(fact_obj.get('evidence'))
    if ev and len(ev) >= 4 and ev in low:
        return True
    nums = re.findall(r'\d[\d,\.]*\s*(?:k|m|b|%|\+)?|\b(?:million|billion|thousand)\b',
                      _norm(fact_obj.get('fact')))
    nums = [n.strip() for n in nums if n.strip()]
    return bool(nums) and all(n in low for n in nums)


def extract_proud_facts(content: str, url: str = None, api_key: str = None, log_file: Path = None) -> list:
    """Return a list of verified {fact, type, evidence} dicts. Never raises; [] on any failure."""
    if not content or len((content or '').split()) < 20:
        return []
    import google.generativeai as genai
    import json
    api_key = api_key or os.getenv('GEMINI_API_KEY')
    if not api_key:
        return []
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-2.5-flash',
                                  generation_config={'temperature': 0.0,
                                                     'response_mime_type': 'application/json'})
    snippet = content[:8000]
    prompt = PROUD_FACTS_PROMPT + "\n\nCONTENT:\n" + snippet
    raw = None
    for attempt in range(MAX_RETRIES):
        try:
            raw = model.generate_content(prompt).text
            break
        except Exception as e:
            if attempt < MAX_RETRIES - 1 and _is_retryable_error(str(e)):
                time.sleep(_retry_delay_from_error(str(e), attempt)); continue
            return []
    try:
        facts = json.loads((raw or '[]').strip())
        if not isinstance(facts, list):
            return []
    except (json.JSONDecodeError, ValueError, TypeError):
        return []
    # Bulletproofing: keep only facts substantiated by the source content.
    verified = []
    for f in facts:
        if isinstance(f, dict) and f.get('fact') and _verify_fact(f, content):
            verified.append({'fact': str(f['fact']).strip(),
                             'type': str(f.get('type', 'other')).strip(),
                             'evidence': str(f.get('evidence', '')).strip()[:200]})
    if log_file:
        try:
            with open(log_file, 'a', encoding='utf-8') as fh:
                fh.write(f"\n--- PROUD FACTS ({url}) ---\nraw: {raw}\nverified: {verified}\n")
        except Exception:
            pass
    return verified[:3]


# CLI for standalone testing
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Extract website content using Jina AI')
    parser.add_argument('url', help='Website URL to extract')
    parser.add_argument('-k', '--api-key', help='Jina AI API key')
    parser.add_argument('-a', '--analyze', action='store_true', help='Also run LLM content analysis')
    parser.add_argument('-m', '--multi-page', action='store_true', help='Extract multiple pages')

    args = parser.parse_args()

    api_key = args.api_key or os.getenv('JINA_API_KEY')

    if args.multi_page:
        result = extract_multiple_pages(args.url, api_key=api_key)
        print(f"Total word count: {result['total_word_count']}")
        print(f"Pages extracted: {list(result['pages'].keys())}")
        if result['error']:
            print(f"Error: {result['error']}")
        print("\n" + "="*60 + "\n")
        print(result['combined_content'][:2000])
        if len(result['combined_content']) > 2000:
            print(f"\n... [{len(result['combined_content']) - 2000} more characters]")
    else:
        result = extract_content(args.url, api_key=api_key)
        print(f"Title: {result['title']}")
        print(f"Word count: {result['word_count']}")
        print(f"Error: {result['error']}")
        print("\n" + "="*60 + "\n")
        print(result['content'][:2000])
        if len(result['content']) > 2000:
            print(f"\n... [{len(result['content']) - 2000} more characters]")

    if args.analyze:
        content = result.get('combined_content') or result.get('content')
        if content:
            print("\n" + "="*60)
            print("CONTENT ANALYSIS (Hybrid Scoring)")
            print("="*60 + "\n")
            analysis = analyze_content_with_llm(content, url=args.url)

            print(f"FINAL SCORE: {analysis['content_score']}/100\n")

            print("PROGRAMMATIC SCORE ({}/30):".format(analysis.get('programmatic_score', 'N/A')))
            print(f"  Word count ({analysis.get('word_count', 0)})")
            key_elements = analysis.get('key_elements', {})
            for k, v in key_elements.items():
                status = "+" if v else "-"
                print(f"  [{status}] {k}")

            print(f"\nLLM SCORE ({analysis.get('llm_score', 'N/A'):.1f}/70):")
            print(f"  Clarity:       {analysis.get('clarity', 'N/A')}/10")
            print(f"  Substance:     {analysis.get('substance', 'N/A')}/10")
            print(f"  Credibility:   {analysis.get('credibility', 'N/A')}/10")
            print(f"  Persuasiveness:{analysis.get('persuasiveness', 'N/A')}/10")

            print(f"\nAnalysis: {analysis.get('content_analysis', 'N/A')}")

            if analysis.get('error'):
                print(f"\nError: {analysis['error']}")
        else:
            print("\nNo content available for analysis")
