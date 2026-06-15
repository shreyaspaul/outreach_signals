#!/usr/bin/env python3
"""
Calibration + variance test harness for the website graders.

Runs the live content + design graders against a labeled set of URLs with known
expected outcomes, then reports where actual grades diverge from expectation.
Also runs a variance check (same URLs graded multiple times) to measure how
non-deterministic the LLM graders are.

PageSpeed is held constant per URL (we pass a known mobile score) so we isolate
the AI graders (content via Jina+Gemini, design via Gemini Vision) from PageSpeed
API variability.

Usage:
    python scripts/test_graders.py                 # calibration + variance
    python scripts/test_graders.py --no-variance   # calibration only
    python scripts/test_graders.py --variance-runs 5
"""
import os
import sys
import asyncio
import tempfile
import argparse
import statistics
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def load_env():
    """Minimal .env loader so we don't depend on python-dotenv."""
    env_path = Path(__file__).parent.parent / '.env'
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env()

from website_grader import capture_screenshot_and_content, grade_website  # noqa: E402


# Labeled set: (url, expected_band, known_pagespeed_mobile, note)
# Anchors are real sites pulled from the canonical enriched CSV so we can detect
# regressions against the grades they previously received.
LABELED = [
    ('https://www.veezoo.com',        'A',    86, 'anchor: was A / 91'),
    ('https://www.loopsai.com',       'A',    98, 'anchor: was A- / 87'),
    ('https://stripe.com',            'A',    90, 'external excellent anchor'),
    ('https://tesseral.com',          'B',    95, 'anchor: was B+ / 84'),
    ('https://www.kurtosis.com',      'B',    98, 'anchor: was B+ / 83'),
    ('https://www.leadbay.ai',        'F',    54, 'anchor: was F / 20'),
    ('https://www.swishrobotics.com', 'F',    57, 'anchor: was F / 21'),
    ('https://www.handsomeapp.com',   'F',    56, 'anchor: was F / 33'),
    ('https://www.enrich.ly',         'PARK', 50, 'domain-parking page; was wrongly D+ / 54'),
]

# URLs to run repeatedly for the variance check.
VARIANCE_URLS = [
    ('https://www.veezoo.com', 86),
    ('https://www.leadbay.ai', 54),
    ('https://www.enrich.ly',  50),
]


def evaluate(band, total, is_error):
    """Return (passed, expectation_text) for a result against its expected band."""
    if total is None:
        return False, '(no grade produced)'
    if band == 'A':
        return total >= 85, 'total >= 85'
    if band == 'B':
        return 75 <= total < 85, '75 <= total < 85'
    if band == 'F':
        return total < 40, 'total < 40'
    if band == 'PARK':
        # A parking/for-sale page should be caught as an error page OR score very
        # low. Today it slips through, so this assertion is expected to FAIL and
        # document the gap.
        return is_error or total < 40, 'flagged as error OR total < 40'
    return False, f'unknown band {band}'


def grade_one(url, pagespeed_mobile):
    """Capture + grade a single URL. Returns the grade_website result dict."""
    tmp = Path(tempfile.mkdtemp(prefix='gradertest_'))
    sem = asyncio.Semaphore(1)
    capture = asyncio.run(capture_screenshot_and_content(url, tmp, sem))
    result = grade_website(
        url=url,
        pagespeed_mobile=pagespeed_mobile,
        screenshot_dir=tmp,
        capture_result=capture,
        api_key=os.getenv('GEMINI_API_KEY'),
        jina_api_key=os.getenv('JINA_API_KEY'),
    )
    return result


def run_calibration():
    print('=' * 100)
    print('CALIBRATION  —  actual grade vs expected band')
    print('=' * 100)
    header = f"{'URL':<32}{'exp':<6}{'total':>6}{'grade':>7}{'cont':>6}{'desg':>6}{'err?':>6}  {'verdict':<6} note"
    print(header)
    print('-' * 100)

    passed = passed_total = 0
    for url, band, ps, note in LABELED:
        try:
            r = grade_one(url, ps)
        except Exception as e:
            print(f"{url:<32}{band:<6}  ERROR: {str(e)[:50]}")
            passed_total += 1
            continue

        total = r.get('total_grade_score')
        grade = r.get('letter_grade') or '-'
        cont = r.get('content_score')
        desg = r.get('design_score')
        is_err = bool(r.get('is_error_page'))
        ok, _ = evaluate(band, total, is_err)
        verdict = 'PASS' if ok else 'FAIL'
        passed += int(ok)
        passed_total += 1

        def fmt(x):
            return f"{x:.0f}" if isinstance(x, (int, float)) else '-'

        print(f"{url:<32}{band:<6}{fmt(total):>6}{grade:>7}{fmt(cont):>6}{fmt(desg):>6}"
              f"{('yes' if is_err else 'no'):>6}  {verdict:<6} {note}")
        if r.get('error'):
            print(f"{'':<32}   -> grader error: {r['error']}")

    print('-' * 100)
    print(f"PASSED {passed}/{passed_total}")
    print()
    return passed, passed_total


def run_variance(runs):
    print('=' * 100)
    print(f'VARIANCE  —  each URL graded {runs}x (measuring LLM non-determinism)')
    print('=' * 100)
    print(f"{'URL':<28}{'metric':<10}{'values':<28}{'min':>5}{'max':>5}{'spread':>8}{'stdev':>8}")
    print('-' * 100)

    for url, ps in VARIANCE_URLS:
        content_vals, design_vals, total_vals = [], [], []
        for _ in range(runs):
            try:
                r = grade_one(url, ps)
                if isinstance(r.get('content_score'), (int, float)):
                    content_vals.append(r['content_score'])
                if isinstance(r.get('design_score'), (int, float)):
                    design_vals.append(r['design_score'])
                if isinstance(r.get('total_grade_score'), (int, float)):
                    total_vals.append(r['total_grade_score'])
            except Exception as e:
                print(f"{url:<28} run error: {str(e)[:40]}")

        for metric, vals in (('content', content_vals), ('design', design_vals), ('total', total_vals)):
            if not vals:
                print(f"{url:<28}{metric:<10}(no data)")
                continue
            spread = max(vals) - min(vals)
            stdev = statistics.pstdev(vals) if len(vals) > 1 else 0.0
            vals_str = ','.join(f"{v:.0f}" for v in vals)
            print(f"{url:<28}{metric:<10}{vals_str:<28}{min(vals):>5.0f}{max(vals):>5.0f}"
                  f"{spread:>8.0f}{stdev:>8.1f}")
        print()


def main():
    ap = argparse.ArgumentParser(description='Test the website graders.')
    ap.add_argument('--no-variance', action='store_true', help='Skip the variance check')
    ap.add_argument('--variance-runs', type=int, default=3, help='Runs per URL in variance check')
    args = ap.parse_args()

    if not os.getenv('GEMINI_API_KEY'):
        print('ERROR: GEMINI_API_KEY not set (needed for content + design grading).')
        sys.exit(1)

    run_calibration()
    if not args.no_variance:
        run_variance(args.variance_runs)


if __name__ == '__main__':
    main()
