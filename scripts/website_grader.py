#!/usr/bin/env python3
"""
Website Grader
Grades websites on Performance, Content, and Design using Playwright and Gemini Vision.
Uses parallel browser execution for speed optimization.
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

# Load .env from project root
project_root = Path(__file__).parent.parent
load_dotenv(project_root / '.env')

# Configuration
DEFAULT_SCREENSHOT_DIR = project_root / 'screenshots'
DEFAULT_VIEWPORT = {'width': 1366, 'height': 900}
DEFAULT_TIMEOUT = 60000  # 60 seconds (increased from 30)
DEFAULT_DELAY = 1.0  # Seconds between batches
MAX_CONCURRENT_BROWSERS = 5
MAX_SCREENSHOT_HEIGHT = 10000  # Limit screenshot height to prevent memory issues
DEFAULT_PERFORMANCE_SCORE = 50  # If pagespeed_mobile missing
MAX_NAVIGATION_RETRIES = 3  # Number of retries for navigation failures

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
                    browser = await p.chromium.launch(headless=True)
                    context = await browser.new_context(
                        viewport=DEFAULT_VIEWPORT,
                        user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                        ignore_https_errors=True,
                        java_script_enabled=True
                    )
                    page = await context.new_page()

                    # Set extra headers to appear more like a real browser
                    await page.set_extra_http_headers({
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                        'Accept-Language': 'en-US,en;q=0.5',
                        'Accept-Encoding': 'gzip, deflate, br',
                        'DNT': '1',
                        'Connection': 'keep-alive',
                        'Upgrade-Insecure-Requests': '1',
                    })

                    # Navigate to page with current strategy
                    await page.goto(
                        normalized_url,
                        wait_until=strategy['wait_until'],
                        timeout=strategy['timeout']
                    )

                    # Wait a bit for any additional rendering
                    await asyncio.sleep(2)

                    # Capture screenshot
                    try:
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
                                navLinks
                            };
                        }''')

                        result['word_count'] = metrics.get('wordCount', 0)
                        result['h1_count'] = metrics.get('h1Count', 0)
                        result['h2_count'] = metrics.get('h2Count', 0)
                        result['h3_count'] = metrics.get('h3Count', 0)
                        result['section_count'] = metrics.get('sectionCount', 0)
                        result['paragraph_count'] = metrics.get('paragraphCount', 0)
                        result['nav_links'] = metrics.get('navLinks', {})

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


def analyze_design_with_gemini(screenshot_path: str, url: str, api_key: str, max_retries: int = 3, log_file: Path = None) -> dict:
    """
    Analyze website design using Gemini 2.5 Flash Vision.
    Includes retry logic with exponential backoff for rate limits.
    Logs all requests and responses to log_file if provided.
    """
    import google.generativeai as genai
    import warnings
    import json
    warnings.filterwarnings('ignore', category=FutureWarning)

    result = {
        'design_score': None,
        'comment': '',
        'error': None
    }

    if not api_key:
        result['error'] = 'Missing GEMINI_API_KEY'
        return result

    if not screenshot_path or not Path(screenshot_path).exists():
        result['error'] = 'Screenshot not found'
        return result

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-2.5-flash')

    # Read and encode the image
    with open(screenshot_path, 'rb') as f:
        image_data = f.read()

    # Get image size for logging
    image_size_kb = len(image_data) / 1024

    # Create the prompt
    prompt = f"""You are a senior design director at a top-tier design studio.
Evaluate ONLY visual design professionalism from this website screenshot.
Ignore content quantity.
Be critical.

Score 0-100 for professional polish, sophistication, hierarchy, typography, spacing, visual clarity, and brand craft.

Consider: sophistication, intentionality, polish, hierarchy, typography, spacing, visual clarity, brand craft.
Be critical: simple/minimal does NOT automatically mean professional.

URL: {url}

Return ONLY valid JSON in this exact format:
{{"design_score": <0-100>, "comment": "<one detailed sentence about the design>"}}"""

    # Log the request being sent to AI
    if log_file:
        try:
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(f"\n{'='*80}\n")
                f.write(f"TIMESTAMP: {datetime.now().isoformat()}\n")
                f.write(f"URL: {url}\n")
                f.write(f"SCREENSHOT: {screenshot_path}\n")
                f.write(f"IMAGE SIZE: {image_size_kb:.1f} KB\n")
                f.write(f"\n--- PROMPT SENT TO GEMINI ---\n")
                f.write(prompt)
                f.write(f"\n--- END PROMPT ---\n")
        except Exception as log_error:
            print(f"Warning: Could not write to log file: {log_error}")

    # Retry logic with exponential backoff
    response_text = None
    for attempt in range(max_retries):
        try:
            # Send to Gemini with image
            response = model.generate_content([
                prompt,
                {'mime_type': 'image/png', 'data': image_data}
            ])

            # Parse response
            response_text = response.text.strip()

            # Log the response
            if log_file:
                try:
                    with open(log_file, 'a', encoding='utf-8') as f:
                        f.write(f"\n--- GEMINI RESPONSE (attempt {attempt + 1}) ---\n")
                        f.write(response_text)
                        f.write(f"\n--- END RESPONSE ---\n")
                except Exception:
                    pass

            # Try to extract JSON from response
            json_match = re.search(r'\{[^}]+\}', response_text)
            if json_match:
                try:
                    data = json.loads(json_match.group())
                    score = data.get('design_score')
                    if isinstance(score, (int, float)) and 0 <= score <= 100:
                        result['design_score'] = int(score)
                        result['comment'] = data.get('comment', '')
                        return result  # Success!
                    else:
                        result['error'] = 'Invalid score range'
                except json.JSONDecodeError:
                    result['error'] = 'JSON parse error'
            else:
                # Try to extract just a number as fallback
                numbers = re.findall(r'\b(\d{1,3})\b', response_text)
                for num in numbers:
                    n = int(num)
                    if 0 <= n <= 100:
                        result['design_score'] = n
                        result['comment'] = 'Score extracted from response'
                        return result  # Success!
                result['error'] = 'Could not parse response'

            return result  # Got a response but couldn't parse properly

        except Exception as e:
            error_str = str(e)

            # Log the error
            if log_file:
                try:
                    with open(log_file, 'a', encoding='utf-8') as f:
                        f.write(f"\n--- ERROR (attempt {attempt + 1}) ---\n")
                        f.write(f"{error_str}\n")
                        f.write(f"--- END ERROR ---\n")
                except Exception:
                    pass

            if '429' in error_str or 'rate' in error_str.lower() or 'quota' in error_str.lower():
                # Rate limit - wait and retry
                wait_time = (2 ** attempt) * 2  # 2, 4, 8 seconds
                if attempt < max_retries - 1:
                    time.sleep(wait_time)
                    continue
            result['error'] = f"Gemini API error: {error_str[:50]}"
            return result

    return result


def grade_website(url: str, pagespeed_mobile: int = None, screenshot_dir: Path = None,
                  api_key: str = None, capture_result: dict = None, log_file: Path = None) -> dict:
    """
    Main grading function - orchestrates all steps.
    Can accept pre-captured screenshot result for batch processing.

    IMPORTANT: If any factor (content, design, performance) has an error or is missing,
    no grade will be assigned. The error will be shown instead.
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
        'error': None
    }

    screenshot_dir = screenshot_dir or DEFAULT_SCREENSHOT_DIR
    api_key = api_key or os.getenv('GEMINI_API_KEY')

    # Get performance score
    performance = pagespeed_mobile if pagespeed_mobile is not None else DEFAULT_PERFORMANCE_SCORE
    result['performance_score'] = performance

    # If we have pre-captured data, use it
    if capture_result:
        screenshot_path = capture_result.get('screenshot_path', '')
        result['screenshot_path'] = screenshot_path

        if capture_result.get('error'):
            result['error'] = capture_result['error']
            # Don't calculate grade if there's a capture error
            return result

        # Score content
        content_score = score_content_amount(capture_result)
        result['content_score'] = content_score
    else:
        result['error'] = 'No capture data provided'
        return result

    # Analyze design with Gemini if we have a screenshot
    if screenshot_path and Path(screenshot_path).exists():
        design_result = analyze_design_with_gemini(screenshot_path, url, api_key, log_file=log_file)
        result['design_score'] = design_result.get('design_score')
        result['design_comment'] = design_result.get('comment', '')
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
                            api_key: str = None, delay: float = 1.0, limit: int = None) -> pd.DataFrame:
    """
    Process CSV file and add grading columns using parallel processing.
    Creates a log file with all AI requests/responses in logs/gemini_requests_<timestamp>.log
    """
    # Read input CSV
    df = pd.read_csv(input_path)

    if 'Website' not in df.columns:
        print("Error: CSV must have a 'Website' column")
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
    if not api_key:
        print("Warning: GEMINI_API_KEY not found. Design scoring will be skipped.")

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

    urls = df['Website'].tolist()
    companies = df.get('Company Name', pd.Series(['Unknown'] * len(df))).tolist()

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
        url = row_data['Website']
        company = companies[idx]
        pagespeed_mobile = row_data.get('pagespeed_mobile')

        print(f"  [{idx + 1}/{total}] {company}...", end='', flush=True)

        result = grade_website(
            url=url,
            pagespeed_mobile=pagespeed_mobile,
            screenshot_dir=screenshot_dir,
            api_key=api_key,
            capture_result=capture_result,
            log_file=log_file
        )
        grader_results.append(result)

        if result['error']:
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
    df['grader_error'] = [r.get('error', '') for r in grader_results]

    # Save output
    df.to_csv(output_path, index=False)

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
                api_key: str = None, delay: float = 1.0, limit: int = None) -> pd.DataFrame:
    """Synchronous wrapper for async CSV processing."""
    return asyncio.run(process_csv_async(input_path, output_path, screenshot_dir, api_key, delay, limit))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Grade websites on Performance, Content, and Design')
    parser.add_argument('input', help='Input CSV file path')
    parser.add_argument('-o', '--output', help='Output CSV file path')
    parser.add_argument('-s', '--screenshot-dir', help='Directory for screenshots')
    parser.add_argument('-k', '--api-key', help='Gemini API key (or set GEMINI_API_KEY env var)')
    parser.add_argument('-d', '--delay', type=float, default=1.0,
                        help='Delay between API calls in seconds (default: 1.0)')
    parser.add_argument('-l', '--limit', type=int, help='Limit number of entries (for testing)')

    args = parser.parse_args()

    process_csv(args.input, args.output, args.screenshot_dir, args.api_key, args.delay, args.limit)
