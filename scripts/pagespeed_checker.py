#!/usr/bin/env python3
"""
PageSpeed Checker
Gets mobile and desktop performance scores using Google PageSpeed Insights API.
"""

import pandas as pd
import requests
import time
import sys
import os
from pathlib import Path
from dotenv import load_dotenv


# Load environment variables from project root
project_root = Path(__file__).parent.parent
load_dotenv(project_root / '.env')

PAGESPEED_API_URL = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"

# All four Lighthouse categories come back in ONE call (no extra quota cost).
PAGESPEED_CATEGORIES = ['performance', 'seo', 'accessibility', 'best-practices']

# Retry policy for transient failures (429 rate-limit, 5xx, timeout, connection drop).
# At 999 sites these WILL happen; without retries we'd silently blank good data.
PAGESPEED_MAX_RETRIES = 3          # up to 3 extra attempts after the first
PAGESPEED_RETRY_BASE_DELAY = 2.0   # seconds; exponential backoff: 2, 4, 8
PAGESPEED_RETRY_MAX_DELAY = 60.0   # cap a single wait (e.g. a large Retry-After)

# Lighthouse audits are "passing" at score >= 0.9 (green). Anything below is an issue.
LIGHTHOUSE_PASS_THRESHOLD = 0.9
# Only these scoreDisplayModes carry a real pass/fail score. 'manual'/'informative'/
# 'notApplicable' are not failures and must never be reported as issues.
SCORABLE_DISPLAY_MODES = ('binary', 'numeric', 'metricSavings')

# Core Web Vitals field-data thresholds (Google, measured at p75 of real users).
# (good_max, poor_min): value <= good_max is "good"; > poor_min is "poor"; else "needs-improvement".
CWV_THRESHOLDS = {
    'lcp':  (2500.0, 4000.0),   # ms
    'inp':  (200.0, 500.0),     # ms
    'cls':  (0.10, 0.25),       # unitless
    'fcp':  (1800.0, 3000.0),   # ms
    'ttfb': (800.0, 1800.0),    # ms
}

# CrUX metric key -> our short name
_CRUX_METRIC_KEYS = {
    'LARGEST_CONTENTFUL_PAINT_MS': 'lcp',
    'INTERACTION_TO_NEXT_PAINT': 'inp',
    'CUMULATIVE_LAYOUT_SHIFT_SCORE': 'cls',
    'FIRST_CONTENTFUL_PAINT_MS': 'fcp',
    'EXPERIMENTAL_TIME_TO_FIRST_BYTE': 'ttfb',
}


def _rate_metric(name: str, value):
    """Return 'good' / 'needs-improvement' / 'poor' for a CWV value, or None."""
    if value is None or name not in CWV_THRESHOLDS:
        return None
    good_max, poor_min = CWV_THRESHOLDS[name]
    if value <= good_max:
        return 'good'
    if value > poor_min:
        return 'poor'
    return 'needs-improvement'


def _extract_failed_audits(category: dict, audits: dict) -> str:
    """Titles of scorable audits in a category that did NOT pass (score < 0.9).

    Returns a '; '-joined string of human-readable issue titles so we can cite the
    specific problems behind a category score (not just the rollup number).
    Score-driving failures lead: titles are sorted by the audit's weight (descending),
    so weight-0 "real but non-scoring" issues fall to the end rather than appearing first
    under a category that scored 100. Ties keep their original (Lighthouse) order.
    """
    scored = []  # (weight, order_index, title)
    for i, ref in enumerate(category.get('auditRefs', [])):
        audit = audits.get(ref.get('id'), {})
        score = audit.get('score')
        mode = audit.get('scoreDisplayMode')
        if score is None or mode not in SCORABLE_DISPLAY_MODES:
            continue
        if score < LIGHTHOUSE_PASS_THRESHOLD:
            title = (audit.get('title') or ref.get('id') or '').strip()
            if title:
                weight = ref.get('weight') or 0
                scored.append((weight, i, title))
    scored.sort(key=lambda t: (-t[0], t[1]))  # weight desc, stable on ties
    return '; '.join(t[2] for t in scored)


def _parse_field_metrics(experience: dict) -> dict:
    """Parse a CrUX loadingExperience block into flat metric values + ratings.

    Returns {} if the block has no metrics. Values: ms for time metrics, raw for CLS.
    """
    metrics = (experience or {}).get('metrics', {})
    if not metrics:
        return {}
    out = {}
    for crux_key, short in _CRUX_METRIC_KEYS.items():
        m = metrics.get(crux_key)
        if not m or m.get('percentile') is None:
            continue
        pct = m['percentile']
        if short == 'cls':
            # CrUX reports CLS as an integer = CLS * 100; convert back to the real value.
            value = round(pct / 100.0, 3)
            rating = _rate_metric('cls', value)  # thresholds are unitless
        else:
            ms = int(pct)
            rating = _rate_metric(short, ms)     # thresholds are in ms
            # Store LCP/FCP in SECONDS to line up with our lab columns (mobile_lcp etc.)
            # for direct field-vs-lab comparison; keep INP/TTFB in ms (their convention).
            value = round(ms / 1000.0, 2) if short in ('lcp', 'fcp') else ms
        out[f'field_{short}'] = value
        out[f'field_{short}_rating'] = rating
    return out


def normalize_url(url: str) -> str:
    """Ensure URL has proper scheme."""
    if not url:
        return ""
    url = url.strip()
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    return url


def _retry_wait(response, attempt: int) -> float:
    """Backoff for the next retry: honor a 429 Retry-After header if present,
    otherwise exponential backoff (2, 4, 8 ...), capped. Retry-After may be either
    an integer number of seconds OR an HTTP-date (RFC 7231)."""
    base = PAGESPEED_RETRY_BASE_DELAY * (2 ** attempt)
    if response is not None:
        retry_after = response.headers.get('Retry-After')
        if retry_after:
            wait = None
            try:
                wait = float(retry_after)
            except (TypeError, ValueError):
                try:
                    from email.utils import parsedate_to_datetime
                    from datetime import datetime, timezone
                    dt = parsedate_to_datetime(retry_after)
                    if dt is not None:
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        wait = (dt - datetime.now(timezone.utc)).total_seconds()
                except Exception:
                    wait = None
            if wait is not None and wait > 0:
                return min(max(wait, base), PAGESPEED_RETRY_MAX_DELAY)
    return min(base, PAGESPEED_RETRY_MAX_DELAY)


def _fetch_pagespeed(params: dict, timeout: int) -> tuple:
    """GET the PageSpeed API with retries on TRANSIENT failures only.

    Retries: 429 (rate limit), 5xx, request timeout, connection error.
    Does NOT retry other 4xx (e.g. 400 bad URL, 404) — those won't fix themselves.
    Returns (data_dict, None) on success or (None, error_str) after exhausting retries.
    """
    last_error = None
    for attempt in range(PAGESPEED_MAX_RETRIES + 1):
        transient_response = None
        try:
            response = requests.get(PAGESPEED_API_URL, params=params, timeout=timeout)
            code = response.status_code
            if code == 200:
                return response.json(), None
            if code == 429 or 500 <= code < 600:
                last_error = 'Rate limited' if code == 429 else f'HTTP {code}'
                transient_response = response  # retryable
            else:
                return None, f'HTTP {code}'   # non-retryable 4xx
        except requests.exceptions.Timeout:
            last_error = 'Timeout'
        except requests.exceptions.ConnectionError:
            last_error = 'Connection Error'
        except ValueError:
            return None, 'Invalid JSON'       # 200 but unparseable; don't hammer it
        except Exception as e:
            return None, str(e)[:50]

        # Reached here => transient failure. Retry if attempts remain.
        if attempt < PAGESPEED_MAX_RETRIES:
            time.sleep(_retry_wait(transient_response, attempt))
            continue
        return None, last_error
    return None, last_error


def get_pagespeed_score(url: str, strategy: str = 'mobile', api_key: str = None, timeout: int = 60) -> dict:
    """
    Get PageSpeed score for a URL.

    Args:
        url: Website URL to test
        strategy: 'mobile' or 'desktop'
        api_key: Optional Google API key (higher quota)
        timeout: Request timeout in seconds

    Returns dict with (all from a SINGLE API call):
        Lab metrics:
        - score: Performance score (0-100) or None
        - fcp / lcp / cls: lab Core Web Vitals (FCP/LCP in seconds, CLS unitless)
        Extra Lighthouse categories (0-100) + their failed-audit issue lists:
        - seo_score / accessibility_score / best_practices_score
        - seo_issues / accessibility_issues / best_practices_issues ('; '-joined titles)
        CrUX field data (real-user, p75 — what Google actually ranks on):
        - crux_source: 'page' | 'origin' | None (which dataset was available)
        - field_lcp / field_inp / field_cls / field_fcp / field_ttfb (+ _rating each)
        - cwv_pass: True/False if LCP+INP+CLS all measured; None if not enough field data
        - error: str if request failed
    """
    result = {
        'score': None,
        'fcp': None,
        'lcp': None,
        'cls': None,
        # extra Lighthouse categories
        'seo_score': None,
        'accessibility_score': None,
        'best_practices_score': None,
        'seo_issues': '',
        'accessibility_issues': '',
        'best_practices_issues': '',
        # CrUX field data
        'crux_source': None,
        'field_lcp': None, 'field_lcp_rating': None,
        'field_inp': None, 'field_inp_rating': None,
        'field_cls': None, 'field_cls_rating': None,
        'field_fcp': None, 'field_fcp_rating': None,
        'field_ttfb': None, 'field_ttfb_rating': None,
        'cwv_pass': None,
        'error': None
    }

    if not url:
        result['error'] = 'Empty URL'
        return result

    url = normalize_url(url)

    # Fall back to env variable if no API key provided
    if not api_key:
        api_key = os.getenv('PAGESPEED_API_KEY')

    params = {
        'url': url,
        'strategy': strategy,
        # Request all four categories in one call — same quota cost as one.
        'category': PAGESPEED_CATEGORIES,
    }

    if api_key:
        params['key'] = api_key

    data, fetch_error = _fetch_pagespeed(params, timeout)
    if fetch_error:
        result['error'] = fetch_error
        return result

    try:
        # ---- Lighthouse LAB results (categories + audits) ----
        lighthouse = data.get('lighthouseResult', {})
        categories = lighthouse.get('categories', {})
        audits = lighthouse.get('audits', {})

        # Performance score
        score = categories.get('performance', {}).get('score')
        if score is not None:
            result['score'] = int(round(score * 100))  # Convert 0-1 to 0-100

        # Extra category scores (0-100). score can legitimately be None (Lighthouse
        # couldn't compute it) — keep None rather than guessing.
        for cat_key, out_key in (('seo', 'seo_score'),
                                 ('accessibility', 'accessibility_score'),
                                 ('best-practices', 'best_practices_score')):
            cat = categories.get(cat_key, {})
            cscore = cat.get('score')
            if cscore is not None:
                result[out_key] = int(round(cscore * 100))

        # Per-category failed audits → citable issue lists
        result['seo_issues'] = _extract_failed_audits(categories.get('seo', {}), audits)
        result['accessibility_issues'] = _extract_failed_audits(categories.get('accessibility', {}), audits)
        result['best_practices_issues'] = _extract_failed_audits(categories.get('best-practices', {}), audits)

        # Lab Core Web Vitals
        fcp = audits.get('first-contentful-paint', {})
        if fcp.get('numericValue') is not None:
            result['fcp'] = round(fcp['numericValue'] / 1000, 2)  # ms -> s

        lcp = audits.get('largest-contentful-paint', {})
        if lcp.get('numericValue') is not None:
            result['lcp'] = round(lcp['numericValue'] / 1000, 2)

        cls = audits.get('cumulative-layout-shift', {})
        if cls.get('numericValue') is not None:
            result['cls'] = round(cls['numericValue'], 3)

        # ---- CrUX FIELD data (real users, p75 — Google's ranking input) ----
        # Prefer the source that has the full Core Web Vitals triad (LCP+INP+CLS), so
        # cwv_pass can actually be computed. A page result with only TTFB must NOT block
        # the origin fallback when origin has the full triad. If neither has the triad,
        # use whatever partial data exists (page preferred) — missing is fine, wrong isn't.
        def _has_triad(f):
            return all(f.get(f'field_{m}') is not None for m in ('lcp', 'inp', 'cls'))

        page_field = _parse_field_metrics(data.get('loadingExperience', {}))
        origin_field = _parse_field_metrics(data.get('originLoadingExperience', {}))

        if _has_triad(page_field):
            field, crux_source = page_field, 'page'
        elif _has_triad(origin_field):
            field, crux_source = origin_field, 'origin'
        elif page_field:
            field, crux_source = page_field, 'page'
        elif origin_field:
            field, crux_source = origin_field, 'origin'
        else:
            field, crux_source = {}, None

        result['crux_source'] = crux_source
        for k, v in field.items():
            result[k] = v

        # Core Web Vitals assessment: pass iff LCP, INP, CLS are all measured AND good.
        core_ratings = [result.get('field_lcp_rating'),
                        result.get('field_inp_rating'),
                        result.get('field_cls_rating')]
        if all(r is not None for r in core_ratings):
            result['cwv_pass'] = all(r == 'good' for r in core_ratings)

    except Exception as e:
        # Network/transient errors are handled in _fetch_pagespeed; this only catches
        # an unexpected shape in an otherwise-valid 200 response.
        result['error'] = f'Parse error: {str(e)[:40]}'

    return result


def process_csv(input_path: str, output_path: str = None, api_key: str = None, delay: float = 2.0):
    """
    Process a CSV file and add PageSpeed scores.

    Args:
        input_path: Path to input CSV with website/domain column
        output_path: Path for output CSV
        api_key: Optional Google API key
        delay: Seconds to wait between requests
    """
    from column_utils import get_website_column, get_company_column

    # Try to get API key from environment if not provided
    if not api_key:
        api_key = os.getenv('PAGESPEED_API_KEY')

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

    # Set default output path
    if not output_path:
        input_file = Path(input_path)
        output_path = input_file.parent / f"{input_file.stem}_pagespeed.csv"

    total = len(df)
    print(f"Processing {total} websites...")
    print(f"API Key: {'Configured' if api_key else 'Not set (using free tier)'}")
    print("-" * 60)

    # Process each website
    mobile_results = []
    desktop_results = []

    for idx, row in df.iterrows():
        url = row[website_col]
        company = row[company_col] if company_col else 'Unknown'

        print(f"[{idx + 1}/{total}] {company}: {url}")

        # Get mobile score
        print(f"         Mobile:  ", end='', flush=True)
        mobile = get_pagespeed_score(url, strategy='mobile', api_key=api_key)
        mobile_results.append(mobile)

        if mobile['error']:
            print(f"Error - {mobile['error']}")
        else:
            print(f"{mobile['score']}/100 (FCP: {mobile['fcp']}s, LCP: {mobile['lcp']}s)")

        time.sleep(delay)  # Rate limit between mobile and desktop

        # Get desktop score
        print(f"         Desktop: ", end='', flush=True)
        desktop = get_pagespeed_score(url, strategy='desktop', api_key=api_key)
        desktop_results.append(desktop)

        if desktop['error']:
            print(f"Error - {desktop['error']}")
        else:
            print(f"{desktop['score']}/100 (FCP: {desktop['fcp']}s, LCP: {desktop['lcp']}s)")

        # Rate limiting between sites
        if idx < total - 1:
            time.sleep(delay)

    # Add results to dataframe
    df['pagespeed_mobile'] = [r['score'] for r in mobile_results]
    df['pagespeed_desktop'] = [r['score'] for r in desktop_results]
    df['mobile_fcp'] = [r['fcp'] for r in mobile_results]
    df['mobile_lcp'] = [r['lcp'] for r in mobile_results]
    df['mobile_cls'] = [r['cls'] for r in mobile_results]
    df['desktop_fcp'] = [r['fcp'] for r in desktop_results]
    df['desktop_lcp'] = [r['lcp'] for r in desktop_results]
    df['desktop_cls'] = [r['cls'] for r in desktop_results]

    # Extra Lighthouse categories + CrUX field data (from the mobile call: mobile-first).
    df['seo_score'] = [r['seo_score'] for r in mobile_results]
    df['accessibility_score'] = [r['accessibility_score'] for r in mobile_results]
    df['best_practices_score'] = [r['best_practices_score'] for r in mobile_results]
    df['seo_issues'] = [r['seo_issues'] for r in mobile_results]
    df['accessibility_issues'] = [r['accessibility_issues'] for r in mobile_results]
    df['best_practices_issues'] = [r['best_practices_issues'] for r in mobile_results]
    df['crux_source'] = [r['crux_source'] for r in mobile_results]
    df['cwv_pass'] = [r['cwv_pass'] for r in mobile_results]
    for short in ('lcp', 'inp', 'cls', 'fcp', 'ttfb'):
        df[f'field_{short}'] = [r[f'field_{short}'] for r in mobile_results]
        df[f'field_{short}_rating'] = [r[f'field_{short}_rating'] for r in mobile_results]
    # Desktop CrUX field data (parallel columns, from the desktop call)
    df['crux_source_desktop'] = [r['crux_source'] for r in desktop_results]
    df['cwv_pass_desktop'] = [r['cwv_pass'] for r in desktop_results]
    for short in ('lcp', 'inp', 'cls', 'fcp', 'ttfb'):
        df[f'field_{short}_desktop'] = [r[f'field_{short}'] for r in desktop_results]
        df[f'field_{short}_rating_desktop'] = [r[f'field_{short}_rating'] for r in desktop_results]

    df['pagespeed_error'] = [
        mobile_results[i]['error'] or desktop_results[i]['error'] or ''
        for i in range(len(mobile_results))
    ]

    # Save output
    df.to_csv(output_path, index=False)
    print("-" * 60)
    print(f"Results saved to: {output_path}")

    # Summary
    mobile_scores = [r['score'] for r in mobile_results if r['score'] is not None]
    desktop_scores = [r['score'] for r in desktop_results if r['score'] is not None]
    error_count = sum(1 for r in mobile_results if r['error']) + sum(1 for r in desktop_results if r['error'])

    print(f"\nSummary:")
    if mobile_scores:
        print(f"  Mobile avg:  {sum(mobile_scores) / len(mobile_scores):.1f}/100")
    if desktop_scores:
        print(f"  Desktop avg: {sum(desktop_scores) / len(desktop_scores):.1f}/100")
    print(f"  Errors: {error_count}")

    # Sites with poor mobile score (Signal 2 targets)
    poor_mobile = sum(1 for s in mobile_scores if s < 50)
    print(f"  Mobile score < 50: {poor_mobile}/{len(mobile_scores)}")

    return df


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Get PageSpeed scores from a CSV')
    parser.add_argument('input', help='Input CSV file path')
    parser.add_argument('-o', '--output', help='Output CSV file path')
    parser.add_argument('-k', '--api-key', help='Google PageSpeed API key')
    parser.add_argument('-d', '--delay', type=float, default=2.0,
                        help='Delay between requests in seconds (default: 2.0)')

    args = parser.parse_args()

    process_csv(args.input, args.output, args.api_key, args.delay)
