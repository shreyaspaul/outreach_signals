#!/usr/bin/env python3
"""
Deep Site Analysis — bundle builder (deterministic, no LLM *writing*).

Crawls one company's website, extracts the high-signal pages, runs our existing
design + content graders on the key pages, and writes everything into a single
`bundle.json` that Claude (in-session, via the /analyze-site skill) then reads to
WRITE the business-analyst report. Mirrors the prep_bundles.py -> Claude pattern.

  python scripts/analyze_site.py https://example.com [--max-pages 25] [--skip-grader]

Output: data/analysis/<slug>/bundle.json  (+ screenshots/<slug>__<category>.png)
"""
import argparse
import asyncio
import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv(project_root / '.env')

import os

from site_crawler import discover_pages, normalize_url
from content_extractor import extract_content, detect_error_page, analyze_content_with_llm, extract_proud_facts
from website_grader import capture_screenshot_and_content, analyze_design_with_gemini, clean_domain
from wordpress_detector import detect_tech_stack

# Per-page extracted markdown is capped so the bundle stays a reasonable size for
# the writer to read. 12k chars (~2k words) is plenty to understand any one page.
MAX_PAGE_CHARS = 12000
JINA_DELAY = 0.5            # politeness between Jina fetches
MAX_GRADED_PAGES = 3        # homepage + up to 2 key pages get the full design/content audit

DATA_DICTIONARY = {
    "domain": "Registrable domain analyzed.",
    "url": "The homepage URL given.",
    "tech_stack.primary_tech": "Best-guess CMS/builder/framework powering the site.",
    "tech_stack.detected_tech": "All technologies detected on the homepage.",
    "tech_stack.marketing_tools": "Analytics/marketing tools detected (Segment, HubSpot, etc.).",
    "tech_stack.has_premium_analytics": "True if premium analytics (Segment/Amplitude/Mixpanel) detected.",
    "proud_facts": "Verified, quotable traction facts pulled from the site copy (named customers, "
                   "metrics, funding). Each has the exact supporting evidence substring. Quote EXACTLY; "
                   "never invent or extrapolate beyond these.",
    "pages": "Every analyzed page: url, category (home/about/product/pricing/customers/...), title, "
             "word_count, and the full extracted markdown content. is_error_page flags 404/placeholder "
             "pages (ignore their content).",
    "graded_pages": "The key pages (homepage + product/pricing) run through our graders. "
                    "design_score is 0-100 (sum of 5 sub-dimensions, each 0-20); design_reasoning is the "
                    "model's per-dimension evidence. content_score is 0-100 (programmatic 0-30 + LLM 0-70); "
                    "clarity/substance/credibility/persuasiveness/depth are 1-10; content_reasoning is the "
                    "per-dimension evidence. screenshot_path is a local PNG of the rendered page.",
    "errors": "Any pages or steps that failed (for transparency; don't treat as findings).",
}


def _truncate(text: str):
    if text and len(text) > MAX_PAGE_CHARS:
        return text[:MAX_PAGE_CHARS] + "\n\n[...truncated...]"
    return text


def extract_pages(pages, jina_key, errors):
    """Jina-extract each discovered page into a content record."""
    records = []
    for i, p in enumerate(pages, 1):
        url, cat = p['url'], p['category']
        print(f"  [{i}/{len(pages)}] extracting [{cat}] {url} ...", end='', flush=True)
        rec = {'url': url, 'category': cat, 'title': '', 'word_count': 0,
               'content': '', 'is_error_page': False, 'error': None}
        try:
            res = extract_content(url, api_key=jina_key)
            if res.get('error'):
                rec['error'] = res['error']
                errors.append(f"extract {url}: {res['error']}")
                print(f" ERR ({res['error'][:30]})")
            else:
                content = res.get('content', '') or ''
                wc = res.get('word_count', 0)
                err = detect_error_page(content, wc)
                rec['title'] = res.get('title', '')
                rec['word_count'] = wc
                rec['is_error_page'] = err['is_error_page']
                rec['content'] = '' if err['is_error_page'] else _truncate(content)
                print(f" {wc}w" + (" [error-page]" if err['is_error_page'] else ""))
        except Exception as e:
            rec['error'] = str(e)[:120]
            errors.append(f"extract {url}: {e}")
            print(f" EXC ({str(e)[:30]})")
        records.append(rec)
        time.sleep(JINA_DELAY)
    return records


def pick_graded_pages(page_records):
    """Homepage + first product/pricing page (most design/messaging-relevant), max 3."""
    chosen, seen_cat = [], set()
    home = next((p for p in page_records if p['category'] == 'home'), None)
    if home:
        chosen.append(home)
    for want in ('product', 'pricing', 'solutions', 'about'):
        if len(chosen) >= MAX_GRADED_PAGES:
            break
        if want in seen_cat:
            continue
        match = next((p for p in page_records
                      if p['category'] == want and not p['is_error_page']), None)
        if match and match not in chosen:
            chosen.append(match)
            seen_cat.add(want)
    return chosen[:MAX_GRADED_PAGES]


def grade_pages(graded, page_records, slug, screenshot_dir, gemini_key, errors):
    """Run screenshot + design score + content score on the key pages."""
    results = []
    content_by_url = {p['url']: p for p in page_records}
    for gp in graded:
        url, cat = gp['url'], gp['category']
        print(f"  grading [{cat}] {url} ...", end='', flush=True)
        out = {'url': url, 'category': cat, 'screenshot_path': '',
               'design_score': None, 'design_reasoning': '', 'design_comment': '',
               'design_sub_dimensions': {}, 'content_score': None,
               'content_reasoning': '', 'content_analysis': '',
               'clarity': None, 'substance': None, 'credibility': None,
               'persuasiveness': None, 'depth': None, 'error': None}
        try:
            sem = asyncio.Semaphore(1)
            cap = asyncio.run(capture_screenshot_and_content(url, screenshot_dir, sem))
            src = cap.get('screenshot_path')
            if src and Path(src).exists():
                # Per-page filename (capture names all pages of a domain the same).
                dest = screenshot_dir / f"{slug}__{cat}.png"
                try:
                    shutil.move(src, dest)
                except Exception:
                    dest = Path(src)
                out['screenshot_path'] = str(dest)
                # Design score
                d = analyze_design_with_gemini(str(dest), url, gemini_key)
                out['design_score'] = d.get('design_score')
                out['design_reasoning'] = d.get('design_reasoning', '')
                out['design_comment'] = d.get('comment', '')
                out['design_sub_dimensions'] = {
                    'typography': d.get('typography'),
                    'spacing_layout': d.get('spacing_layout'),
                    'color_brand': d.get('color_brand'),
                    'visual_hierarchy': d.get('visual_hierarchy'),
                    'polish_craft': d.get('polish_craft'),
                }
                if d.get('error'):
                    errors.append(f"design {url}: {d['error']}")
            else:
                out['error'] = cap.get('error') or 'no screenshot'
                errors.append(f"capture {url}: {out['error']}")
            # Content score — prefer Jina content; fall back to rendered page text.
            page_content = (content_by_url.get(url, {}).get('content')
                            or cap.get('page_text') or '')
            if page_content:
                c = analyze_content_with_llm(page_content, url=url, api_key=gemini_key)
                if not c.get('error'):
                    out['content_score'] = c.get('content_score')
                    out['content_reasoning'] = c.get('content_reasoning', '')
                    out['content_analysis'] = c.get('content_analysis', '')
                    for k in ('clarity', 'substance', 'credibility', 'persuasiveness', 'depth'):
                        out[k] = c.get(k)
                else:
                    errors.append(f"content {url}: {c['error']}")
            print(f" design={out['design_score']} content={out['content_score']}")
        except Exception as e:
            out['error'] = str(e)[:120]
            errors.append(f"grade {url}: {e}")
            print(f" EXC ({str(e)[:40]})")
        results.append(out)
    return results


def analyze_site(url, max_pages=25, skip_grader=False):
    gemini_key = os.getenv('GEMINI_API_KEY')
    jina_key = os.getenv('JINA_API_KEY')
    url = normalize_url(url)
    slug = clean_domain(url)
    domain = urlparse(url).netloc

    out_dir = project_root / 'data' / 'analysis' / slug
    screenshot_dir = out_dir / 'screenshots'
    out_dir.mkdir(parents=True, exist_ok=True)
    screenshot_dir.mkdir(parents=True, exist_ok=True)

    errors = []
    print(f"\n{'='*60}\nDEEP SITE ANALYSIS: {url}\n{'='*60}")

    # 1. Discover + prioritize pages
    print("\nDiscovering pages...")
    pages = discover_pages(url, max_pages=max_pages)
    print(f"  {len(pages)} pages selected.")

    # 2. Extract content for each
    print("\nExtracting content...")
    page_records = extract_pages(pages, jina_key, errors)

    # 3. Tech stack (homepage)
    print("\nDetecting tech stack...")
    tech = detect_tech_stack(url)
    tech_summary = {
        'primary_tech': tech.get('primary_tech'),
        'detected_tech': tech.get('detected_tech', []),
        'marketing_tools': tech.get('marketing_tools', []),
        'ad_pixels': tech.get('ad_pixels', []),
        'has_premium_analytics': tech.get('has_premium_analytics', False),
    }
    print(f"  primary: {tech_summary['primary_tech']}")

    # 4. Proud facts (from combined corpus)
    print("\nExtracting proud facts...")
    corpus = "\n\n".join(r['content'] for r in page_records if r['content'])[:30000]
    proud_facts = []
    try:
        proud_facts = extract_proud_facts(corpus, url=url, api_key=gemini_key)
    except Exception as e:
        errors.append(f"proud_facts: {e}")
    print(f"  {len(proud_facts)} facts.")

    # 5. Grade key pages
    graded_results = []
    if not skip_grader:
        print("\nGrading key pages (screenshot + design + content)...")
        graded = pick_graded_pages(page_records)
        graded_results = grade_pages(graded, page_records, slug, screenshot_dir,
                                     gemini_key, errors)

    # 6. Assemble bundle
    bundle = {
        'domain': domain,
        'url': url,
        'company_slug': slug,
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'page_count': len(page_records),
        'tech_stack': tech_summary,
        'proud_facts': proud_facts,
        'pages': page_records,
        'graded_pages': graded_results,
        'errors': errors,
        'data_dictionary': DATA_DICTIONARY,
    }
    bundle_path = out_dir / 'bundle.json'
    with open(bundle_path, 'w', encoding='utf-8') as f:
        json.dump(bundle, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*60}\nBundle written: {bundle_path}")
    print(f"  pages: {len(page_records)} | graded: {len(graded_results)} | "
          f"proud_facts: {len(proud_facts)} | errors: {len(errors)}")
    print(f"  report goes to: {out_dir / 'report.md'}")
    print(f"{'='*60}\n")
    return bundle_path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Build a deep-site-analysis bundle for one company')
    parser.add_argument('url', help='Company website URL')
    parser.add_argument('--max-pages', type=int, default=25)
    parser.add_argument('--skip-grader', action='store_true',
                        help='Skip screenshot + design/content grading (faster, text-only)')
    args = parser.parse_args()
    analyze_site(args.url, max_pages=args.max_pages, skip_grader=args.skip_grader)
