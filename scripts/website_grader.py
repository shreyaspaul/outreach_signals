#!/usr/bin/env python3
"""
Website Grader
Grades websites on Performance, Content, and Design using Playwright and Gemini Vision.
Uses parallel browser execution for speed optimization.
Integrates Jina AI for clean content extraction and LLM-based content analysis.
"""

import asyncio
import base64
import os
import re
import sys
import time
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse

import pandas as pd
from dotenv import load_dotenv

# Import content extractor for Jina AI integration
from content_extractor import extract_content as jina_extract_content, analyze_content_with_llm, _retry_delay_from_error, _is_retryable_error
from grader_fields import write_annotated_csv
from accessibility import run_axe_on_page, accessibility_defaults, AXE_FIELDS
from page_signals import parse_network_signals, page_signals_defaults, CONSENT_BANNER_JS

# Load .env from project root
project_root = Path(__file__).parent.parent
load_dotenv(project_root / '.env')

# Configuration
from _token_log import log_usage
DEFAULT_SCREENSHOT_DIR = project_root / 'screenshots'
DEFAULT_VIEWPORT = {'width': 1366, 'height': 900}
# Cap design screenshots to a clean top crop (~4 viewport-heights). Full-page
# screenshots of very long pages get downsampled by the vision model, degrading
# the typography/spacing/polish detail the design grader is asked to judge.
MAX_SCREENSHOT_HEIGHT = 1800  # 2 x 900px (cost: ~half the image tokens; hero + 1-2 sections is enough to judge design)
DEFAULT_TIMEOUT = 60000  # 60 seconds (increased from 30)
DEFAULT_DELAY = 1.0  # Seconds between batches
MAX_CONCURRENT_BROWSERS = 5
DEFAULT_PERFORMANCE_SCORE = 50  # If pagespeed_mobile missing
MAX_NAVIGATION_RETRIES = 3  # Number of retries for navigation failures
# Capture-health: a real site renders SOME post-JS text. Below this, the SPA likely
# hasn't hydrated yet -> we render harder before trusting a "blank/coming-soon" verdict.
MIN_HEALTHY_WORDS = 25

# Design-score ensemble: run the design call N times and average, recording the
# spread so wobbly screenshots surface during manual review. 2 during the
# calibration phase (mean of 2; median needs 3); set to 1 for production.
DESIGN_ENSEMBLE_RUNS = 1
DESIGN_VARIANCE_FLAG_THRESHOLD = 8  # spread above this is flagged high-variance

# Page validity gate toggle (DNS + redirect + vision LLM). Disable to fall back
# to v1 behavior (no INVALID abstain).
USE_PAGE_GATE = True

# Blank-render detection: a screenshot that comes back essentially white means the
# page failed to render (JS-only app, slow load, soft bot-block). We must NOT feed
# a white image to the design/identity AI as if it were a real page — that produced
# the wrong "CONTENT_MISMATCH" on aerodentis.com. Real pages have lots of pixel
# variation; blank pages are ~all-white with near-zero variation.
BLANK_WHITE_FRACTION = 0.95   # >=95% near-white pixels ...
BLANK_STDDEV_MAX = 12.0       # ... AND almost no variation => blank render


def is_blank_screenshot(screenshot_path: str) -> dict:
    """Return {'blank': bool, 'white_pct': float, 'stddev': float}.

    Best-effort: if Pillow is unavailable or the file can't be read, returns
    blank=False (never block grading on a detection failure).
    """
    info = {'blank': False, 'white_pct': None, 'stddev': None}
    try:
        from PIL import Image
        import statistics
        im = Image.open(screenshot_path).convert('L').resize((64, 64))
        px = list(im.getdata())
        if not px:
            return info
        white_pct = sum(1 for v in px if v >= 245) / len(px)
        sd = statistics.pstdev(px)
        info['white_pct'] = round(white_pct * 100, 1)
        info['stddev'] = round(sd, 1)
        info['blank'] = (white_pct >= BLANK_WHITE_FRACTION and sd < BLANK_STDDEV_MAX)
    except Exception:
        pass
    return info

# Jina AI Content Extraction Configuration
USE_JINA_CONTENT_EXTRACTION = True  # Enable Jina AI for content extraction
USE_LLM_CONTENT_ANALYSIS = True  # Use LLM for content scoring instead of heuristics

# Scoring weights
WEIGHT_PERFORMANCE = 0.30
WEIGHT_CONTENT = 0.40
WEIGHT_DESIGN = 0.30

# Deviation thresholds
DEVIATION_THRESHOLD = 15
THRESHOLD_EXCELLENT = 80
THRESHOLD_GOOD = 65
THRESHOLD_AVERAGE = 50
THRESHOLD_POOR = 35


def normalize_url(url: str) -> str:
    """Ensure URL has proper scheme."""
    if not url:
        return url
    url = url.strip()
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    return url


def clean_domain(url: str) -> str:
    """Extract clean domain name for screenshot filename."""
    try:
        parsed = urlparse(normalize_url(url))
        domain = parsed.netloc or parsed.path
        # Remove www. prefix
        if domain.startswith('www.'):
            domain = domain[4:]
        # Replace dots and special chars with underscores
        clean = re.sub(r'[^\w]', '_', domain)
        return clean.lower()
    except Exception:
        return 'unknown'


def score_content_amount(metrics: dict) -> int:
    """
    Score content amount/structure from 0-100.

    Scoring rubric:
    - Base score from word count (0-95 points)
    - Bonuses for structure: headings, sections, paragraphs
    - Navigation bonus: up to +10 for complete nav
    - Penalty: cap at 80 if missing h1 or h2s
    """
    score = 0

    word_count = metrics.get('word_count', 0)

    # Base score from word count
    if word_count < 80:
        score = 10
    elif word_count < 200:
        score = 20
    elif word_count < 400:
        score = 35
    elif word_count < 800:
        score = 55
    elif word_count < 1500:
        score = 75
    elif word_count < 3000:
        score = 90
    else:
        score = 95

    # Structure bonuses
    h1_count = metrics.get('h1_count', 0)
    h2_count = metrics.get('h2_count', 0)
    section_count = metrics.get('section_count', 0)
    paragraph_count = metrics.get('paragraph_count', 0)

    if h1_count >= 1:
        score += 8
    if h2_count >= 2:
        score += 6
    if section_count >= 3:
        score += 6
    if paragraph_count >= 10:
        score += 6

    # Navigation bonus (up to +10)
    nav_links = metrics.get('nav_links', {})
    nav_bonus = sum(2 for key in ['features', 'pricing', 'docs', 'blog', 'contact', 'about', 'careers']
                    if nav_links.get(key))
    score += min(nav_bonus, 10)

    # Penalty: cap at 80 if missing structure
    if score > 80 and (h1_count == 0 or h2_count < 2):
        score = 80

    return min(100, max(0, score))


def calculate_total_score(performance: int, content: int, design: int) -> dict:
    """
    Calculate weighted total and letter grade.

    Weights: Performance 30%, Content 40%, Design 30%
    """
    # Handle None values
    perf = performance if performance is not None else DEFAULT_PERFORMANCE_SCORE
    cont = content if content is not None else 50
    des = design if design is not None else 50

    total = int(perf * WEIGHT_PERFORMANCE + cont * WEIGHT_CONTENT + des * WEIGHT_DESIGN)

    # Letter grade mapping
    if total >= 95:
        grade = 'A+'
    elif total >= 90:
        grade = 'A'
    elif total >= 85:
        grade = 'A-'
    elif total >= 80:
        grade = 'B+'
    elif total >= 75:
        grade = 'B'
    elif total >= 70:
        grade = 'B-'
    elif total >= 65:
        grade = 'C+'
    elif total >= 60:
        grade = 'C'
    elif total >= 55:
        grade = 'C-'
    elif total >= 50:
        grade = 'D+'
    elif total >= 45:
        grade = 'D'
    elif total >= 40:
        grade = 'D-'
    else:
        grade = 'F'

    return {'total_score': total, 'letter_grade': grade}


def get_score_label(score: int) -> str:
    """Get descriptive label for a score."""
    if score is None:
        return 'Unknown'
    if score >= THRESHOLD_EXCELLENT:
        return 'Excellent'
    elif score >= THRESHOLD_GOOD:
        return 'Good'
    elif score >= THRESHOLD_AVERAGE:
        return 'Average'
    elif score >= THRESHOLD_POOR:
        return 'Poor'
    else:
        return 'Very poor'


def analyze_deviations(performance: int, content: int, design: int) -> dict:
    """
    Identify strong and weak areas based on score deviations.

    Deviation logic:
    - Weak area: Score is 15+ points below average of other two, OR score < 50
    - Strong area: Score is 15+ points above average of other two, OR score >= 80
    """
    # Handle None values
    perf = performance if performance is not None else DEFAULT_PERFORMANCE_SCORE
    cont = content if content is not None else 50
    des = design if design is not None else 50

    scores = {'performance': perf, 'content': cont, 'design': des}
    weak_areas = []
    strong_areas = []

    for dimension, score in scores.items():
        others = [v for k, v in scores.items() if k != dimension]
        avg_others = sum(others) / len(others)

        # Check for weak area
        if score < THRESHOLD_AVERAGE or (score < avg_others - DEVIATION_THRESHOLD):
            weak_areas.append(dimension)

        # Check for strong area
        if score >= THRESHOLD_EXCELLENT or (score > avg_others + DEVIATION_THRESHOLD):
            strong_areas.append(dimension)

    # Generate analysis text
    analysis_parts = []
    for dim in ['design', 'content', 'performance']:
        label = get_score_label(scores[dim])
        analysis_parts.append(f"{label} {dim}")

    grade_analysis = ', '.join(analysis_parts)

    # Handle balanced scores case
    if not weak_areas and not strong_areas:
        # Check if all scores are within 10 points
        score_range = max(scores.values()) - min(scores.values())
        if score_range <= 10:
            grade_analysis = 'Consistent quality across all areas'

    return {
        'grade_analysis': grade_analysis,
        'weak_areas': ', '.join(weak_areas),
        'strong_areas': ', '.join(strong_areas)
    }


async def capture_screenshot_and_content(url: str, screenshot_dir: Path, semaphore: asyncio.Semaphore) -> dict:
    """
    Capture screenshot and extract content metrics using Playwright.
    Uses semaphore for concurrency control.
    Includes retry logic with different navigation strategies.
    """
    from playwright.async_api import async_playwright

    result = {
        'screenshot_path': '',
        'word_count': 0,
        'h1_count': 0,
        'h2_count': 0,
        'h3_count': 0,
        'section_count': 0,
        'paragraph_count': 0,
        'nav_links': {},
        'page_text': '',      # full JS-rendered text (real browser sees what Jina can't)
        'final_url': '',      # URL after all redirects (for the page validity gate)
        'http_status': None,  # HTTP status of the final navigation
        'capture_healthy': None,  # True/False: did the page actually render (screenshot + post-JS text)?
        **accessibility_defaults(),  # axe-core WCAG fields (filled while page is live)
        **page_signals_defaults(),   # network-pass fields (page weight, trackers, cookies)
        'error': None
    }

    normalized_url = normalize_url(url)
    domain = clean_domain(url)
    screenshot_path = screenshot_dir / f"{domain}.png"

    # Navigation strategies to try in order
    nav_strategies = [
        {'wait_until': 'networkidle', 'timeout': DEFAULT_TIMEOUT},
        {'wait_until': 'load', 'timeout': DEFAULT_TIMEOUT},
        {'wait_until': 'domcontentloaded', 'timeout': DEFAULT_TIMEOUT // 2},
    ]

    async with semaphore:
        browser = None
        last_error = None

        for attempt, strategy in enumerate(nav_strategies):
            try:
                async with async_playwright() as p:
                    # Relax TLS/cert handling so genuinely old or misconfigured HTTPS
                    # sites can still be captured. NOTE: this does NOT defeat server-side
                    # anti-bot WAFs that reject the TLS handshake itself (sslv3/tlsv1
                    # alert) — those need a residential-proxy fetcher (Firecrawl), which
                    # is deferred. Such sites fail capture and are flagged with the error.
                    browser = await p.chromium.launch(headless=True, args=[
                        '--ignore-certificate-errors',
                        '--ssl-version-min=tls1',
                    ])
                    context = await browser.new_context(
                        viewport=DEFAULT_VIEWPORT,
                        user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                        ignore_https_errors=True,
                        java_script_enabled=True
                    )
                    page = await context.new_page()

                    # Collect every response (for page weight + 3rd-party/tracker detection).
                    # Sync listener reads cached headers only — never blocks navigation.
                    network_log = []

                    def _on_response(resp, _log=network_log):
                        try:
                            h = resp.headers
                            _log.append({
                                'url': resp.url,
                                'type': (h.get('content-type') or '').lower(),
                                'length': h.get('content-length'),
                                'range': h.get('content-range'),
                            })
                        except Exception:
                            pass
                    page.on('response', _on_response)

                    # Set extra headers to appear more like a real browser
                    await page.set_extra_http_headers({
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                        'Accept-Language': 'en-US,en;q=0.5',
                        'Accept-Encoding': 'gzip, deflate, br',
                        'DNT': '1',
                        'Connection': 'keep-alive',
                        'Upgrade-Insecure-Requests': '1',
                    })

                    # Navigate to page with current strategy. Keep the response so
                    # the page validity gate can see the final (post-redirect) URL
                    # and HTTP status — these are robust, LLM-invisible signals for
                    # parked / acquired / blocked pages.
                    response = await page.goto(
                        normalized_url,
                        wait_until=strategy['wait_until'],
                        timeout=strategy['timeout']
                    )
                    try:
                        result['final_url'] = page.url or ''
                        result['http_status'] = response.status if response else None
                    except Exception:
                        pass

                    # Wait a bit for any additional rendering
                    await asyncio.sleep(2)

                    # Stabilize the page before screenshot so the design grader
                    # gets a consistent, fully-rendered image. Run-to-run image
                    # drift (lazy-loaded content, web fonts, animation state) was
                    # the dominant source of design-score variance once the model
                    # itself was made deterministic (temperature=0).
                    try:
                        # 1. Freeze animations/transitions so we never capture a
                        #    mid-animation frame.
                        await page.add_style_tag(content=(
                            '*, *::before, *::after {'
                            ' animation-duration: 0s !important;'
                            ' animation-delay: 0s !important;'
                            ' transition-duration: 0s !important;'
                            ' transition-delay: 0s !important;'
                            ' scroll-behavior: auto !important; }'
                        ))
                        # 2. Scroll through the page to trigger lazy-loaded
                        #    images/sections, then return to the top.
                        await page.evaluate(
                            'async () => {'
                            ' const sleep = (ms) => new Promise(r => setTimeout(r, ms));'
                            ' const h = document.body.scrollHeight;'
                            ' for (let y = 0; y < h; y += window.innerHeight) {'
                            '   window.scrollTo(0, y); await sleep(120); }'
                            ' window.scrollTo(0, 0); await sleep(150); }'
                        )
                        # 3. Wait for web fonts to finish loading.
                        await page.evaluate('() => document.fonts && document.fonts.ready')
                        await asyncio.sleep(0.5)
                    except Exception:
                        pass  # stabilization is best-effort; never block capture

                    # Capture screenshot — cap height so very tall pages don't
                    # get downsampled to mush by the vision model. Pages taller
                    # than MAX_SCREENSHOT_HEIGHT are clipped to a clean top crop
                    # (hero + first few sections).
                    try:
                        page_height = await page.evaluate(
                            '() => Math.max(document.body.scrollHeight, '
                            'document.documentElement.scrollHeight)'
                        )
                        if page_height and page_height > MAX_SCREENSHOT_HEIGHT:
                            # clip must be paired with full_page=True to crop a
                            # region taller than the viewport; clip alone clamps
                            # to the viewport height.
                            await page.screenshot(path=str(screenshot_path), full_page=True, clip={
                                'x': 0, 'y': 0,
                                'width': DEFAULT_VIEWPORT['width'],
                                'height': MAX_SCREENSHOT_HEIGHT
                            })
                        else:
                            await page.screenshot(path=str(screenshot_path), full_page=True)
                        result['screenshot_path'] = str(screenshot_path)
                    except Exception as ss_error:
                        # Try viewport-only screenshot if full page fails
                        try:
                            await page.screenshot(path=str(screenshot_path), full_page=False)
                            result['screenshot_path'] = str(screenshot_path)
                        except Exception:
                            last_error = f"Screenshot failed: {str(ss_error)[:50]}"
                            await browser.close()
                            continue  # Try next strategy

                    # Blank-render recovery: some JS apps haven't painted when the
                    # nav strategy "completes". If the shot is essentially white,
                    # wait longer and retake (up to 2 more tries) before giving up.
                    if result['screenshot_path']:
                        async def _retake():
                            try:
                                ph = await page.evaluate(
                                    '() => Math.max(document.body.scrollHeight, '
                                    'document.documentElement.scrollHeight)')
                                if ph and ph > MAX_SCREENSHOT_HEIGHT:
                                    await page.screenshot(path=str(screenshot_path), full_page=True, clip={
                                        'x': 0, 'y': 0, 'width': DEFAULT_VIEWPORT['width'],
                                        'height': MAX_SCREENSHOT_HEIGHT})
                                else:
                                    await page.screenshot(path=str(screenshot_path), full_page=True)
                            except Exception:
                                pass
                        for _ in range(2):
                            if not is_blank_screenshot(str(screenshot_path)).get('blank'):
                                break
                            await asyncio.sleep(4)  # give the SPA time to paint
                            try:
                                await page.evaluate(
                                    'async () => { const s=(ms)=>new Promise(r=>setTimeout(r,ms));'
                                    ' const h=document.body.scrollHeight;'
                                    ' for(let y=0;y<h;y+=window.innerHeight){window.scrollTo(0,y); await s(120);}'
                                    ' window.scrollTo(0,0); await s(150); }')
                                await page.evaluate('() => document.fonts && document.fonts.ready')
                            except Exception:
                                pass
                            await _retake()

                    # Extract content metrics
                    try:
                        metrics = await page.evaluate('''() => {
                            const body = document.body;
                            const text = body ? body.innerText || '' : '';
                            const wordCount = text.split(/\\s+/).filter(w => w.length > 0).length;

                            const h1Count = document.querySelectorAll('h1').length;
                            const h2Count = document.querySelectorAll('h2').length;
                            const h3Count = document.querySelectorAll('h3').length;
                            const sectionCount = document.querySelectorAll('section, article, main').length;
                            const paragraphCount = document.querySelectorAll('p').length;

                            // Check for common nav links
                            const links = Array.from(document.querySelectorAll('a')).map(a => a.textContent.toLowerCase());
                            const navLinks = {
                                features: links.some(l => l.includes('feature')),
                                pricing: links.some(l => l.includes('pricing') || l.includes('plans')),
                                docs: links.some(l => l.includes('doc') || l.includes('api')),
                                blog: links.some(l => l.includes('blog') || l.includes('news')),
                                contact: links.some(l => l.includes('contact')),
                                about: links.some(l => l.includes('about')),
                                careers: links.some(l => l.includes('career') || l.includes('jobs'))
                            };

                            return {
                                wordCount,
                                h1Count,
                                h2Count,
                                h3Count,
                                sectionCount,
                                paragraphCount,
                                navLinks,
                                text: text.slice(0, 60000)
                            };
                        }''')

                        result['page_text'] = metrics.get('text', '')
                        result['word_count'] = metrics.get('wordCount', 0)
                        result['h1_count'] = metrics.get('h1Count', 0)
                        result['h2_count'] = metrics.get('h2Count', 0)
                        result['h3_count'] = metrics.get('h3Count', 0)
                        result['section_count'] = metrics.get('sectionCount', 0)
                        result['paragraph_count'] = metrics.get('paragraphCount', 0)
                        result['nav_links'] = metrics.get('navLinks', {})

                        # --- Capture health: a real site renders BOTH a non-blank screenshot
                        # AND some post-JS text. If either is missing, the SPA likely hasn't
                        # hydrated yet (e.g. bytez rendered blank with empty text). Wait longer,
                        # scroll to trigger lazy content, and re-render ONCE before we ever trust
                        # a blank/coming-soon verdict, then re-extract the post-JS text.
                        def _capture_unhealthy():
                            sp = result['screenshot_path']
                            blank = bool(sp) and Path(sp).exists() and is_blank_screenshot(sp).get('blank')
                            return blank or (result['word_count'] or 0) < MIN_HEALTHY_WORDS
                        if _capture_unhealthy():
                            try:
                                await page.wait_for_timeout(6000)
                                await page.evaluate('async () => { const s=ms=>new Promise(r=>setTimeout(r,ms));'
                                                    ' const h=document.body.scrollHeight;'
                                                    ' for(let y=0;y<h;y+=window.innerHeight){window.scrollTo(0,y); await s(150);}'
                                                    ' window.scrollTo(0,0); await s(400); }')
                                await page.evaluate('() => document.fonts && document.fonts.ready')
                                await _retake()
                                m2 = await page.evaluate("() => { const t=(document.body&&document.body.innerText)||'';"
                                                         " return {wc: t.split(/\\s+/).filter(w=>w.length>0).length,"
                                                         " text: t.slice(0,60000)}; }")
                                if (m2.get('wc') or 0) > (result['word_count'] or 0):
                                    result['word_count'] = m2.get('wc', 0)
                                    result['page_text'] = m2.get('text', '')
                            except Exception:
                                pass
                        result['capture_healthy'] = not _capture_unhealthy()

                        # Accessibility scan (axe-core) while the page is still live —
                        # piggybacks on this browser pass, no extra launch. Never raises.
                        axe_fields = await run_axe_on_page(page)
                        result.update(axe_fields)

                        # Network-pass signals: page weight + trackers/cookies-before-consent.
                        # We never clicked "accept", so cookies/trackers seen = pre-consent.
                        try:
                            cookies = await context.cookies()
                            consent_present = await page.evaluate(CONSENT_BANNER_JS)
                            result.update(parse_network_signals(
                                network_log, cookies, consent_present, normalized_url))
                        except Exception as ps_error:
                            result['page_signals_error'] = f'page signals: {str(ps_error)[:50]}'

                    except Exception as eval_error:
                        # Content extraction failed, but we might still have screenshot
                        if result['screenshot_path']:
                            # We have screenshot, content extraction failed but we can proceed
                            result['word_count'] = 0
                        else:
                            last_error = f"Content extraction failed: {str(eval_error)[:50]}"

                    await browser.close()

                    # If we got a screenshot, we succeeded
                    if result['screenshot_path']:
                        return result

            except Exception as e:
                last_error = f"Navigation failed ({strategy['wait_until']}): {str(e)[:40]}"
                if browser:
                    try:
                        await browser.close()
                    except:
                        pass
                # Wait before retry
                if attempt < len(nav_strategies) - 1:
                    await asyncio.sleep(2)
                continue

        # All strategies failed
        result['error'] = last_error or "All navigation strategies failed"

    return result


# Sub-dimension design scoring: 5 dimensions x 0-20 = 0-100. Decomposing the
# holistic 0-100 score into anchored sub-dimensions reduces run-to-run variance
# (each dimension has a narrower range and concrete anchors) and makes the score
# auditable. response_schema forces clean structured output.
# Reason-before-score schema: the model first describes what it SEES (observations),
# then for each dimension writes one line of specific evidence and ONLY THEN the number.
# Generating the evidence first conditions the score on concrete observations (and gives
# the user an auditable justification) instead of snapping to a generous default.
DESIGN_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "observations": {"type": "STRING"},
        "typography_reason": {"type": "STRING"},
        "typography": {"type": "INTEGER"},
        "spacing_layout_reason": {"type": "STRING"},
        "spacing_layout": {"type": "INTEGER"},
        "color_brand_reason": {"type": "STRING"},
        "color_brand": {"type": "INTEGER"},
        "visual_hierarchy_reason": {"type": "STRING"},
        "visual_hierarchy": {"type": "INTEGER"},
        "polish_craft_reason": {"type": "STRING"},
        "polish_craft": {"type": "INTEGER"},
        "comment": {"type": "STRING"},
    },
    "required": ["observations", "typography_reason", "typography",
                 "spacing_layout_reason", "spacing_layout", "color_brand_reason", "color_brand",
                 "visual_hierarchy_reason", "visual_hierarchy", "polish_craft_reason",
                 "polish_craft", "comment"],
}

DESIGN_PROMPT = """You are a BRUTALLY HONEST senior design director critiquing a STATIC screenshot
of a website. You judge VISUAL CRAFT ONLY (you cannot see motion, hover states, or interaction —
judge only what is visible in the still image). Most websites are competent but generic. Your job
is to SEPARATE the genuinely well-crafted from the merely acceptable. DO NOT cluster scores at the
top — that is the #1 failure mode. A clean, ordinary startup site is AVERAGE, not good.

STEP 1 — OBSERVE (field "observations"): Before any score, describe concretely what you actually
see: layout structure, specific type choices and size hierarchy, spacing rhythm, the color palette,
imagery/illustration quality and quantity, visual density/richness, and any signals of distinctive
craft OR of generic/template patterns (default fonts, stock components, flat single-color sections).

STEP 2 — SCORE 5 dimensions, each 0-20. For EACH dimension you MUST first write one sentence of
SPECIFIC evidence from the screenshot (the *_reason field), then give the score. The score must
follow from the evidence — never score high without citing concrete visible craft.

CALIBRATION — use the FULL range, be strict and discriminating:
   0-4   broken / amateur / clashing / unusable
   5-8   below average: generic template, weak hierarchy, default styling, cramped or barren
   9-12  AVERAGE / COMPETENT: clean but unremarkable — a typical decent startup site lands HERE
   13-16 GOOD: clearly intentional, polished, with distinctive, refined craft you can point to
   17-20 EXCEPTIONAL: Stripe / Linear / Vercel tier — sophisticated system, masterful detail

RULES:
- Default to 9-12. Only go to 13+ if your evidence sentence names specific superior craft.
- "Looks clean / professional / modern" is NOT evidence for 13+. That is average (9-12).
- A simple, sparse, or minimal page with little visual richness should land 7-11, not 14+.
- Two sites must NOT get the same score if one is visibly richer and more crafted than the other.

DIMENSIONS:
1. TYPOGRAPHY — font choice, scale & hierarchy, readability, consistency, refinement.
2. SPACING & LAYOUT — white space, alignment, grid discipline, rhythm, composition.
3. COLOR & BRAND — palette coherence, contrast, intentionality, distinctiveness.
4. VISUAL HIERARCHY — eye flow, emphasis, CTA prominence, information ordering.
5. POLISH & CRAFT — finish, detail, imagery quality, overall sophistication and richness.

URL: {url}
"""


def analyze_design_with_gemini(screenshot_path: str, url: str, api_key: str, max_retries: int = 4, log_file: Path = None) -> dict:
    """
    Analyze website design using Gemini 2.5 Flash Vision (single call).
    Returns 5 anchored sub-dimensions (0-20 each) summed to design_score (0-100).
    temperature=0 + response_schema for stable, structured output.
    """
    import google.generativeai as genai
    import warnings
    import json
    warnings.filterwarnings('ignore', category=FutureWarning)

    result = {
        'design_score': None,
        'comment': '',
        'design_reasoning': '',
        'typography': None,
        'spacing_layout': None,
        'color_brand': None,
        'visual_hierarchy': None,
        'polish_craft': None,
        'error': None
    }

    if not api_key:
        result['error'] = 'Missing GEMINI_API_KEY'
        return result

    if not screenshot_path or not Path(screenshot_path).exists():
        result['error'] = 'Screenshot not found'
        return result

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        'gemini-2.5-flash',
        generation_config=genai.types.GenerationConfig(
            temperature=0.0,
            response_mime_type='application/json',
            response_schema=DESIGN_RESPONSE_SCHEMA,
        ),
    )

    with open(screenshot_path, 'rb') as f:
        image_data = f.read()
    image_size_kb = len(image_data) / 1024

    prompt = DESIGN_PROMPT.format(url=url)

    if log_file:
        try:
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(f"\n{'='*80}\n")
                f.write(f"DESIGN ANALYSIS REQUEST\n")
                f.write(f"TIMESTAMP: {datetime.now().isoformat()}\n")
                f.write(f"URL: {url}\n")
                f.write(f"SCREENSHOT: {screenshot_path}\n")
                f.write(f"IMAGE SIZE: {image_size_kb:.1f} KB\n")
        except Exception as log_error:
            print(f"Warning: Could not write to log file: {log_error}")

    def _clamp20(v):
        try:
            return max(0, min(20, int(v)))
        except (TypeError, ValueError):
            return None

    for attempt in range(max_retries):
        try:
            response = model.generate_content([
                prompt,
                {'mime_type': 'image/png', 'data': image_data}
            ])
            log_usage('design', response)
            response_text = response.text.strip()

            if log_file:
                try:
                    with open(log_file, 'a', encoding='utf-8') as f:
                        f.write(f"\n--- GEMINI RESPONSE (attempt {attempt + 1}) ---\n")
                        f.write(response_text)
                        f.write(f"\n--- END RESPONSE ---\n")
                except Exception:
                    pass

            try:
                data = json.loads(response_text)
            except json.JSONDecodeError:
                m = re.search(r'\{.*\}', response_text, re.DOTALL)
                data = json.loads(m.group()) if m else None

            if not data:
                result['error'] = 'Could not parse response'
                return result

            subs = {
                'typography': _clamp20(data.get('typography')),
                'spacing_layout': _clamp20(data.get('spacing_layout')),
                'color_brand': _clamp20(data.get('color_brand')),
                'visual_hierarchy': _clamp20(data.get('visual_hierarchy')),
                'polish_craft': _clamp20(data.get('polish_craft')),
            }
            if any(v is None for v in subs.values()):
                result['error'] = 'Missing design sub-dimensions'
                return result

            result.update(subs)
            result['design_score'] = sum(subs.values())  # 0-100
            result['comment'] = data.get('comment', '')

            # Build an auditable, human-readable justification from the per-dimension
            # evidence the model was forced to write before each score.
            labels = [
                ('typography', 'Typography'),
                ('spacing_layout', 'Spacing & Layout'),
                ('color_brand', 'Color & Brand'),
                ('visual_hierarchy', 'Visual Hierarchy'),
                ('polish_craft', 'Polish & Craft'),
            ]
            lines = []
            obs = (data.get('observations') or '').strip()
            if obs:
                lines.append(f"Observations: {obs}")
            for key, label in labels:
                reason = (data.get(f'{key}_reason') or '').strip()
                lines.append(f"{label} {subs[key]}/20 — {reason}")
            result['design_reasoning'] = "\n".join(lines)

            if log_file:
                try:
                    with open(log_file, 'a', encoding='utf-8') as f:
                        f.write(f"--- DESIGN SCORE: {result['design_score']}/100 "
                                f"(T{subs['typography']} S{subs['spacing_layout']} "
                                f"C{subs['color_brand']} H{subs['visual_hierarchy']} "
                                f"P{subs['polish_craft']}) ---\n")
                        f.write(result['design_reasoning'] + "\n")
                except Exception:
                    pass
            return result

        except Exception as e:
            error_str = str(e)
            if log_file:
                try:
                    with open(log_file, 'a', encoding='utf-8') as f:
                        f.write(f"\n--- ERROR (attempt {attempt + 1}) ---\n{error_str}\n--- END ERROR ---\n")
                except Exception:
                    pass
            if _is_retryable_error(error_str):
                if attempt < max_retries - 1:
                    time.sleep(_retry_delay_from_error(error_str, attempt))
                    continue
            result['error'] = f"Gemini API error: {error_str[:50]}"
            return result

    return result


def analyze_design_ensemble(screenshot_path: str, url: str, api_key: str,
                            runs: int = None, log_file: Path = None) -> dict:
    """
    Run the design scorer N times and combine. Returns the mean design_score plus
    the individual runs and their spread so wobbly screenshots are visible during
    manual review. Sub-dimensions are taken from the run closest to the mean.

    runs defaults to DESIGN_ENSEMBLE_RUNS (2 in calibration; set to 1 for prod).
    """
    import statistics
    runs = runs if runs is not None else DESIGN_ENSEMBLE_RUNS
    runs = max(1, runs)

    attempts = []
    last_error = None
    for i in range(runs):
        r = analyze_design_with_gemini(screenshot_path, url, api_key, log_file=log_file)
        if r.get('design_score') is not None:
            attempts.append(r)
        else:
            last_error = r.get('error')

    if not attempts:
        return {
            'design_score': None, 'comment': '', 'design_reasoning': '',
            'error': last_error or 'All design runs failed',
            'typography': None, 'spacing_layout': None, 'color_brand': None,
            'visual_hierarchy': None, 'polish_craft': None,
            'design_score_runs': '', 'design_score_spread': None,
            'design_high_variance': False,
        }

    scores = [a['design_score'] for a in attempts]
    mean_score = int(round(statistics.mean(scores)))
    spread = max(scores) - min(scores)
    # Sub-dimensions + comment + reasoning from the run closest to the mean.
    closest = min(attempts, key=lambda a: abs(a['design_score'] - mean_score))

    return {
        'design_score': mean_score,
        'comment': closest.get('comment', ''),
        'design_reasoning': closest.get('design_reasoning', ''),
        'typography': closest.get('typography'),
        'spacing_layout': closest.get('spacing_layout'),
        'color_brand': closest.get('color_brand'),
        'visual_hierarchy': closest.get('visual_hierarchy'),
        'polish_craft': closest.get('polish_craft'),
        'design_score_runs': ','.join(str(s) for s in scores),
        'design_score_spread': spread,
        'design_high_variance': spread > DESIGN_VARIANCE_FLAG_THRESHOLD,
        'error': None,
    }


def grade_website(url: str, pagespeed_mobile: int = None, screenshot_dir: Path = None,
                  api_key: str = None, capture_result: dict = None, log_file: Path = None,
                  jina_api_key: str = None, use_jina: bool = True, use_llm_content: bool = True,
                  company_name: str = '') -> dict:
    """
    Main grading function - orchestrates all steps.
    Can accept pre-captured screenshot result for batch processing.

    Pipeline: capture -> Jina extract -> PAGE VALIDITY GATE -> (if PASS) content +
    design scoring -> grade. If the gate abstains (parked/redirect/acquired/blocked/
    mismatch/etc.) the entry is marked letter_grade="INVALID" and not scored.

    IMPORTANT: If any factor (content, design, performance) has an error or is missing,
    no grade will be assigned. The error will be shown instead.

    Args:
        url: Website URL to grade
        pagespeed_mobile: PageSpeed mobile score (if available)
        screenshot_dir: Directory for screenshots
        api_key: Gemini API key for design and content analysis
        capture_result: Pre-captured screenshot and metrics data
        log_file: Path to log file for AI requests
        jina_api_key: Jina AI API key for content extraction
        use_jina: Whether to use Jina AI for content extraction
        use_llm_content: Whether to use LLM for content scoring
        company_name: Company name from CSV (used by the page validity gate for identity match)
    """
    result = {
        'content_score': None,
        'design_score': None,
        'performance_score': None,
        'total_grade_score': None,
        'letter_grade': '',
        'grade_analysis': '',
        'weak_areas': '',
        'strong_areas': '',
        'screenshot_path': '',
        'design_comment': '',
        'content_analysis': '',
        # New hybrid scoring fields
        'programmatic_score': None,
        'llm_score': None,
        'clarity': None,
        'substance': None,
        'credibility': None,
        'persuasiveness': None,
        'depth': None,
        'content_reasoning': '',
        'content_source': '',
        'content_word_count': None,
        # Design sub-dimensions + ensemble diagnostics
        'design_reasoning': '',
        'design_typography': None,
        'design_spacing': None,
        'design_color': None,
        'design_hierarchy': None,
        'design_polish': None,
        'design_score_runs': '',
        'design_score_spread': None,
        # Page validity gate
        'page_state': '',
        'gate_confidence': None,
        'gate_reason': '',
        'detected_platform': '',
        'gate_source': '',
        # Error page detection
        'is_error_page': False,
        'error_type': None,
        'error': None
    }

    screenshot_dir = screenshot_dir or DEFAULT_SCREENSHOT_DIR
    api_key = api_key or os.getenv('GEMINI_API_KEY')
    jina_api_key = jina_api_key or os.getenv('JINA_API_KEY')

    # Get performance score
    performance = pagespeed_mobile if pagespeed_mobile is not None else DEFAULT_PERFORMANCE_SCORE
    result['performance_score'] = performance

    # If we have pre-captured data, use it for screenshot
    if capture_result:
        screenshot_path = capture_result.get('screenshot_path', '')
        result['screenshot_path'] = screenshot_path

        if capture_result.get('error'):
            result['error'] = capture_result['error']
            # Don't calculate grade if there's a capture error
            return result
    else:
        result['error'] = 'No capture data provided'
        return result

    # --- Blank-render guard: if the screenshot came back essentially white, the page
    # did not actually render. Flag the reason explicitly and abstain — do NOT feed a
    # white image to the gate/design AI (that mis-judged aerodentis as CONTENT_MISMATCH).
    # If the final HTTP status was an error (403/404/etc.), skip this generic label and
    # let the gate assign the more specific reason (BOT_BLOCKED / ERROR_404_MAINTENANCE).
    _http_status = capture_result.get('http_status') if capture_result else None
    _http_is_error = _http_status in (401, 403, 404, 410)
    if screenshot_path and Path(screenshot_path).exists() and not _http_is_error:
        blank = is_blank_screenshot(screenshot_path)
        if blank['blank']:
            result['letter_grade'] = 'INVALID'
            result['is_error_page'] = True
            result['page_state'] = 'BLANK_RENDER'
            result['error_type'] = 'blank_render'
            result['gate_source'] = 'screenshot'
            result['gate_reason'] = (
                f"Screenshot rendered blank/white "
                f"({blank['white_pct']}% white, variation {blank['stddev']}). "
                f"Page failed to render (JS-only app, slow load, or soft block); not gradeable."
            )
            if log_file:
                try:
                    with open(log_file, 'a', encoding='utf-8') as f:
                        f.write(f"\n--- BLANK RENDER ---\nURL: {url}\n{result['gate_reason']}\n")
                except Exception:
                    pass
            return result

    # --- Capture-health guard: even if the screenshot wasn't fully white, an empty post-JS
    # render (no real text after the patient re-render) means we never actually saw the page.
    # Do NOT let the gate guess "coming-soon" off a broken capture (this is exactly what
    # wrongly buried bytez). Mark CAPTURE_FAILED: a recoverable capture problem, retry it,
    # never treat as a dead/placeholder site.
    if capture_result.get('capture_healthy') is False and not _http_is_error:
        result['letter_grade'] = 'INVALID'
        result['is_error_page'] = True
        result['page_state'] = 'CAPTURE_FAILED'
        result['error_type'] = 'capture_failed'
        result['gate_source'] = 'capture'
        result['gate_reason'] = (
            f"Page did not render real content after a patient re-render "
            f"(post-JS words={capture_result.get('word_count')}). Capture problem, not a dead "
            f"site; recoverable -- retry the capture, do not treat as dead.")
        if log_file:
            try:
                with open(log_file, 'a', encoding='utf-8') as f:
                    f.write(f"\n--- CAPTURE FAILED ---\nURL: {url}\n{result['gate_reason']}\n")
            except Exception:
                pass
        return result

    # --- Jina content extraction (needed by BOTH the gate and the content scorer) ---
    jina_result = {}
    extracted_content = None
    jina_title = ''
    content_scored = False

    if use_jina and USE_JINA_CONTENT_EXTRACTION:
        jina_result = jina_extract_content(url, api_key=jina_api_key)
        if jina_result.get('content') and not jina_result.get('error'):
            extracted_content = jina_result['content']
            jina_title = jina_result.get('title', '')
        else:
            # Log Jina extraction error (gate still runs vision-only on the screenshot)
            if log_file:
                try:
                    with open(log_file, 'a', encoding='utf-8') as f:
                        f.write(f"\n--- JINA EXTRACTION FALLBACK ---\n")
                        f.write(f"URL: {url}\n")
                        f.write(f"Error: {jina_result.get('error', 'No content extracted')}\n")
                        f.write(f"Falling back to Playwright extraction + heuristic scoring\n")
                except Exception:
                    pass

    # --- Choose the richer text source. Jina fetches HTML over HTTP and CANNOT run
    # JavaScript, so on JS-heavy sites it silently drops client-rendered content
    # (DocStation lost ~40% of its feature cards). Playwright already rendered the
    # page in a real browser for the screenshot, so prefer its text when it is
    # meaningfully more complete.
    pw_text = (capture_result.get('page_text') or '').strip()
    jina_text = (extracted_content or '').strip()
    jw, pw = len(jina_text.split()), len(pw_text.split())
    if pw > 0 and (jw == 0 or pw >= jw * 1.15):
        effective_content = pw_text
        result['content_source'] = 'playwright'
    else:
        effective_content = jina_text
        result['content_source'] = 'jina' if jina_text else ''
    if log_file:
        try:
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(f"\n--- CONTENT SOURCE: {result['content_source']} "
                        f"(jina {jw}w vs playwright {pw}w) for {url} ---\n")
        except Exception:
            pass

    # --- Page validity gate: is this a genuine, live site for THIS company? ---
    # Runs DNS + redirect (robust infra) then a vision-first LLM judge. If it
    # abstains, the page is not gradeable -> letter_grade="INVALID", skip scoring.
    if USE_PAGE_GATE:
        from page_gate import assess_page_validity
        gate = assess_page_validity(
            url=url,
            company_name=company_name,
            jina_content=effective_content or '',
            jina_title=jina_title,
            playwright_final_url=capture_result.get('final_url', ''),
            playwright_http_status=capture_result.get('http_status'),
            screenshot_path=screenshot_path,
            content_word_count=(jina_result.get('word_count') or capture_result.get('word_count') or 0),
            gemini_api_key=api_key,
            log_file=log_file,
        )
        result['page_state'] = gate.get('page_state', '')
        result['gate_confidence'] = gate.get('gate_confidence')
        result['gate_reason'] = gate.get('gate_reason', '')
        result['detected_platform'] = gate.get('detected_platform') or ''
        result['gate_source'] = gate.get('gate_source', '')

        if gate.get('abstain'):
            # Not a gradeable page. Mark INVALID (distinct from F), skip content +
            # design scoring entirely (no point, saves API calls).
            result['letter_grade'] = 'INVALID'
            result['is_error_page'] = True
            result['error_type'] = (gate.get('page_state') or 'invalid').lower()
            if log_file:
                try:
                    with open(log_file, 'a', encoding='utf-8') as f:
                        f.write(f"\n--- GATE ABSTAIN ({result['gate_source']}) ---\n")
                        f.write(f"URL: {url}\nSTATE: {result['page_state']}\n")
                        f.write(f"REASON: {result['gate_reason']}\n")
                except Exception:
                    pass
            return result

    # --- Content scoring (gate passed) ---
    if effective_content and use_llm_content and USE_LLM_CONTENT_ANALYSIS:
        content_analysis_result = analyze_content_with_llm(
            effective_content,
            url=url,
            api_key=api_key,
            log_file=log_file
        )
        if content_analysis_result.get('content_score') is not None and not content_analysis_result.get('error'):
            result['content_score'] = content_analysis_result['content_score']
            result['content_analysis'] = content_analysis_result.get('content_analysis', '')
            result['programmatic_score'] = content_analysis_result.get('programmatic_score')
            result['llm_score'] = content_analysis_result.get('llm_score')
            result['clarity'] = content_analysis_result.get('clarity')
            result['substance'] = content_analysis_result.get('substance')
            result['credibility'] = content_analysis_result.get('credibility')
            result['persuasiveness'] = content_analysis_result.get('persuasiveness')
            result['depth'] = content_analysis_result.get('depth')
            result['content_reasoning'] = content_analysis_result.get('content_reasoning', '')
            result['content_word_count'] = content_analysis_result.get('word_count')
            # Backstop error-page detection (gate should normally catch these first)
            result['is_error_page'] = content_analysis_result.get('is_error_page', False)
            result['error_type'] = content_analysis_result.get('error_type')
            content_scored = True
        else:
            if log_file:
                try:
                    with open(log_file, 'a', encoding='utf-8') as f:
                        f.write(f"\n--- LLM CONTENT ANALYSIS FALLBACK ---\n")
                        f.write(f"URL: {url}\n")
                        f.write(f"Error: {content_analysis_result.get('error', 'Unknown')}\n")
                        f.write(f"Falling back to heuristic scoring\n")
                except Exception:
                    pass

    # Fallback to heuristic content scoring if Jina/LLM failed
    if not content_scored:
        content_score = score_content_amount(capture_result)
        result['content_score'] = content_score
        result['content_analysis'] = 'Heuristic scoring (word count, structure)'

    # --- Design scoring (ensemble: N runs, mean score, spread recorded) ---
    if screenshot_path and Path(screenshot_path).exists():
        design_result = analyze_design_ensemble(screenshot_path, url, api_key, log_file=log_file)
        result['design_score'] = design_result.get('design_score')
        result['design_comment'] = design_result.get('comment', '')
        result['design_reasoning'] = design_result.get('design_reasoning', '')
        result['design_typography'] = design_result.get('typography')
        result['design_spacing'] = design_result.get('spacing_layout')
        result['design_color'] = design_result.get('color_brand')
        result['design_hierarchy'] = design_result.get('visual_hierarchy')
        result['design_polish'] = design_result.get('polish_craft')
        result['design_score_runs'] = design_result.get('design_score_runs', '')
        result['design_score_spread'] = design_result.get('design_score_spread')
        if design_result.get('error'):
            result['error'] = design_result['error']
            # Don't calculate grade if there's a design analysis error
            return result
    else:
        result['error'] = 'Screenshot not available for design analysis'
        return result

    # Only calculate grade if ALL scores are available (no errors)
    if result['content_score'] is None or result['design_score'] is None:
        result['error'] = 'Missing required scores for grading'
        return result

    # Calculate total score - only if all factors are present
    total_result = calculate_total_score(performance, result['content_score'], result['design_score'])
    result['total_grade_score'] = total_result['total_score']
    result['letter_grade'] = total_result['letter_grade']

    # Analyze deviations
    deviation_result = analyze_deviations(performance, result['content_score'], result['design_score'])
    result['grade_analysis'] = deviation_result['grade_analysis']
    result['weak_areas'] = deviation_result['weak_areas']
    result['strong_areas'] = deviation_result['strong_areas']

    return result


async def process_csv_async(input_path: str, output_path: str = None, screenshot_dir: str = None,
                            api_key: str = None, delay: float = 1.0, limit: int = None,
                            jina_api_key: str = None, use_jina: bool = True, use_llm_content: bool = True) -> pd.DataFrame:
    """
    Process CSV file and add grading columns using parallel processing.
    Creates a log file with all AI requests/responses in logs/gemini_requests_<timestamp>.log
    """
    from column_utils import get_website_column, get_company_column

    # Read input CSV
    df = pd.read_csv(input_path)

    # Auto-detect columns
    try:
        website_col = get_website_column(df)
        company_col = get_company_column(df)
        print(f"Detected website column: '{website_col}'")
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    # Apply limit if specified
    if limit:
        df = df.head(limit)
        print(f"Limited to first {limit} entries")

    # Set default paths
    screenshot_dir = Path(screenshot_dir) if screenshot_dir else DEFAULT_SCREENSHOT_DIR
    screenshot_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if not output_path:
        input_file = Path(input_path)
        output_path = input_file.parent / "data" / f"graded_{timestamp}.csv"
        output_path.parent.mkdir(exist_ok=True)

    # Create log file for AI requests
    logs_dir = project_root / 'logs'
    logs_dir.mkdir(exist_ok=True)
    log_file = logs_dir / f"gemini_requests_{timestamp}.log"

    # Initialize log file with header
    with open(log_file, 'w', encoding='utf-8') as f:
        f.write(f"GEMINI API REQUEST LOG\n")
        f.write(f"Generated: {datetime.now().isoformat()}\n")
        f.write(f"Input file: {input_path}\n")
        f.write(f"Total entries: {len(df)}\n")
        f.write(f"{'='*80}\n")

    print(f"AI request log: {log_file}")

    api_key = api_key or os.getenv('GEMINI_API_KEY')
    jina_api_key = jina_api_key or os.getenv('JINA_API_KEY')

    if not api_key:
        print("Warning: GEMINI_API_KEY not found. Design scoring will be skipped.")
    if use_jina and not jina_api_key:
        print("Note: JINA_API_KEY not found. Jina AI will work with lower rate limits.")
    if use_jina:
        print(f"Jina AI content extraction: ENABLED")
    else:
        print(f"Jina AI content extraction: DISABLED (using heuristic scoring)")
    if use_llm_content:
        print(f"LLM content analysis: ENABLED")
    else:
        print(f"LLM content analysis: DISABLED (using heuristic scoring)")

    total = len(df)
    print(f"\n{'='*60}")
    print(f"WEBSITE GRADING - {total} websites")
    print(f"{'='*60}")
    print(f"Using {MAX_CONCURRENT_BROWSERS} concurrent browsers\n")

    # Create semaphore for concurrency control
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_BROWSERS)

    # Phase 1: Capture all screenshots in parallel
    print("Phase 1: Capturing screenshots...")
    start_time = time.time()

    urls = df[website_col].tolist()
    companies = df[company_col].tolist() if company_col else ['Unknown'] * len(df)

    # Create tasks for parallel execution
    tasks = [capture_screenshot_and_content(url, screenshot_dir, semaphore) for url in urls]
    capture_results = await asyncio.gather(*tasks)

    screenshot_time = time.time() - start_time
    success_count = sum(1 for r in capture_results if r.get('screenshot_path'))
    print(f"  Captured {success_count}/{total} screenshots in {screenshot_time:.1f}s")

    # Phase 2: Analyze designs with Gemini (sequential to respect rate limits)
    print("\nPhase 2: Analyzing designs...")
    start_time = time.time()

    grader_results = []
    for idx, (row, capture_result) in enumerate(zip(df.iterrows(), capture_results)):
        row_idx, row_data = row
        url = row_data[website_col]
        company = companies[idx]
        pagespeed_mobile = row_data.get('pagespeed_mobile')

        print(f"  [{idx + 1}/{total}] {company}...", end='', flush=True)

        result = grade_website(
            url=url,
            pagespeed_mobile=pagespeed_mobile,
            screenshot_dir=screenshot_dir,
            api_key=api_key,
            capture_result=capture_result,
            log_file=log_file,
            jina_api_key=jina_api_key,
            use_jina=use_jina,
            use_llm_content=use_llm_content,
            company_name=str(company) if company is not None else ''
        )
        grader_results.append(result)

        if result.get('letter_grade') == 'INVALID':
            print(f" INVALID ({result.get('page_state', '')})")
        elif result['error']:
            print(f" Error: {result['error'][:30]}")
        else:
            print(f" {result['letter_grade']} ({result['total_grade_score']}/100)")

        # Small delay between API calls
        if idx < total - 1:
            await asyncio.sleep(delay)

    design_time = time.time() - start_time
    print(f"\n  Design analysis completed in {design_time:.1f}s")

    # Add columns to DataFrame
    df['performance_score'] = [r.get('performance_score') for r in grader_results]
    df['content_score'] = [r.get('content_score') for r in grader_results]
    df['design_score'] = [r.get('design_score') for r in grader_results]
    df['total_grade_score'] = [r.get('total_grade_score') for r in grader_results]
    df['letter_grade'] = [r.get('letter_grade', '') for r in grader_results]
    df['grade_analysis'] = [r.get('grade_analysis', '') for r in grader_results]
    df['weak_areas'] = [r.get('weak_areas', '') for r in grader_results]
    df['strong_areas'] = [r.get('strong_areas', '') for r in grader_results]
    df['screenshot_path'] = [r.get('screenshot_path', '') for r in grader_results]
    df['design_comment'] = [r.get('design_comment', '') for r in grader_results]
    # Hybrid content scoring breakdown
    df['content_analysis'] = [r.get('content_analysis', '') for r in grader_results]
    df['programmatic_score'] = [r.get('programmatic_score') for r in grader_results]
    df['llm_score'] = [r.get('llm_score') for r in grader_results]
    df['clarity'] = [r.get('clarity') for r in grader_results]
    df['substance'] = [r.get('substance') for r in grader_results]
    df['credibility'] = [r.get('credibility') for r in grader_results]
    df['persuasiveness'] = [r.get('persuasiveness') for r in grader_results]
    df['depth'] = [r.get('depth') for r in grader_results]
    df['content_reasoning'] = [r.get('content_reasoning', '') for r in grader_results]
    df['content_source'] = [r.get('content_source', '') for r in grader_results]
    df['content_word_count'] = [r.get('content_word_count') for r in grader_results]
    # Design sub-dimensions + ensemble diagnostics
    df['design_reasoning'] = [r.get('design_reasoning', '') for r in grader_results]
    df['design_typography'] = [r.get('design_typography') for r in grader_results]
    df['design_spacing'] = [r.get('design_spacing') for r in grader_results]
    df['design_color'] = [r.get('design_color') for r in grader_results]
    df['design_hierarchy'] = [r.get('design_hierarchy') for r in grader_results]
    df['design_polish'] = [r.get('design_polish') for r in grader_results]
    df['design_score_runs'] = [r.get('design_score_runs', '') for r in grader_results]
    df['design_score_spread'] = [r.get('design_score_spread') for r in grader_results]
    # Page validity gate
    df['page_state'] = [r.get('page_state', '') for r in grader_results]
    df['gate_confidence'] = [r.get('gate_confidence') for r in grader_results]
    df['gate_reason'] = [r.get('gate_reason', '') for r in grader_results]
    df['detected_platform'] = [r.get('detected_platform', '') for r in grader_results]
    df['gate_source'] = [r.get('gate_source', '') for r in grader_results]
    # Error page detection
    df['is_error_page'] = [r.get('is_error_page', False) for r in grader_results]
    df['error_type'] = [r.get('error_type', '') for r in grader_results]
    df['grader_error'] = [r.get('error', '') for r in grader_results]

    # Save output (friendly column names + description header row)
    write_annotated_csv(df, output_path)

    # Print summary
    print(f"\n{'='*60}")
    print("GRADING SUMMARY")
    print(f"{'='*60}")
    print(f"Output saved to: {output_path}")
    print()

    # Grade distribution
    grades = [r['letter_grade'] for r in grader_results if r['letter_grade']]
    if grades:
        grade_counts = {}
        for g in grades:
            grade_counts[g] = grade_counts.get(g, 0) + 1
        print("Grade Distribution:")
        for grade in ['A+', 'A', 'A-', 'B+', 'B', 'B-', 'C+', 'C', 'C-', 'D+', 'D', 'D-', 'F']:
            if grade in grade_counts:
                print(f"  {grade}: {grade_counts[grade]}")
    print()

    # Score averages
    performance_scores = [r['performance_score'] for r in grader_results if r['performance_score'] is not None]
    content_scores = [r['content_score'] for r in grader_results if r['content_score'] is not None]
    design_scores = [r['design_score'] for r in grader_results if r['design_score'] is not None]
    total_scores = [r['total_grade_score'] for r in grader_results if r['total_grade_score'] is not None]

    if performance_scores:
        print(f"Average performance score: {sum(performance_scores)/len(performance_scores):.1f}/100")
    if content_scores:
        print(f"Average content score: {sum(content_scores)/len(content_scores):.1f}/100")
    if design_scores:
        print(f"Average design score: {sum(design_scores)/len(design_scores):.1f}/100")
    if total_scores:
        print(f"Average total score: {sum(total_scores)/len(total_scores):.1f}/100")
    print()

    # Weak areas summary
    all_weak = []
    for r in grader_results:
        if r['weak_areas']:
            all_weak.extend(r['weak_areas'].split(', '))
    if all_weak:
        weak_counts = {}
        for w in all_weak:
            weak_counts[w] = weak_counts.get(w, 0) + 1
        print("Most common weak areas:")
        for area, count in sorted(weak_counts.items(), key=lambda x: -x[1]):
            print(f"  {area}: {count} sites")
    print()

    error_count = sum(1 for r in grader_results if r['error'])
    print(f"Errors: {error_count}/{total}")

    total_time = screenshot_time + design_time
    print(f"\nTotal time: {total_time:.1f}s ({total_time/total:.1f}s per site)")

    return df


def process_csv(input_path: str, output_path: str = None, screenshot_dir: str = None,
                api_key: str = None, delay: float = 1.0, limit: int = None,
                jina_api_key: str = None, use_jina: bool = True, use_llm_content: bool = True) -> pd.DataFrame:
    """Synchronous wrapper for async CSV processing."""
    return asyncio.run(process_csv_async(
        input_path, output_path, screenshot_dir, api_key, delay, limit,
        jina_api_key, use_jina, use_llm_content
    ))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Grade websites on Performance, Content, and Design')
    parser.add_argument('input', help='Input CSV file path')
    parser.add_argument('-o', '--output', help='Output CSV file path')
    parser.add_argument('-s', '--screenshot-dir', help='Directory for screenshots')
    parser.add_argument('-k', '--api-key', help='Gemini API key (or set GEMINI_API_KEY env var)')
    parser.add_argument('-j', '--jina-api-key', help='Jina AI API key (or set JINA_API_KEY env var)')
    parser.add_argument('-d', '--delay', type=float, default=1.0,
                        help='Delay between API calls in seconds (default: 1.0)')
    parser.add_argument('-l', '--limit', type=int, help='Limit number of entries (for testing)')
    parser.add_argument('--skip-jina', action='store_true',
                        help='Skip Jina AI content extraction (use Playwright + heuristics)')
    parser.add_argument('--skip-content-llm', action='store_true',
                        help='Skip LLM content analysis (use heuristic scoring)')

    args = parser.parse_args()

    process_csv(
        args.input,
        args.output,
        args.screenshot_dir,
        args.api_key,
        args.delay,
        args.limit,
        jina_api_key=args.jina_api_key,
        use_jina=not args.skip_jina,
        use_llm_content=not args.skip_content_llm
    )
