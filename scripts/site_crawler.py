#!/usr/bin/env python3
"""
Site crawler / page discovery for the Deep Site Analysis vertical.

Given a single company URL, discover the high-signal pages worth analyzing and
return them PRIORITIZED (home/about/product/pricing/customers first), capped at
`max_pages`. No LLM involved — pure sitemap parsing + a single Playwright pass on
the homepage to harvest in-domain links (homepages are often the only place the
JS-rendered nav exists).

Used by `analyze_site.py`. Standalone CLI prints the prioritized list.

  python scripts/site_crawler.py https://example.com [--max-pages 25]
"""
import argparse
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urljoin, urlparse, urldefrag

import requests
import tldextract

USER_AGENT = (
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
)
SITEMAP_TIMEOUT = 15
DEFAULT_MAX_PAGES = 25
MAX_SITEMAP_URLS = 2000  # safety cap when expanding sitemap indexes


# ---------------------------------------------------------------------------
# Page categorization + priority. Lower priority number = analyzed first.
# Each (category, priority, [path keywords]). The homepage is always priority 0.
# ---------------------------------------------------------------------------
CATEGORY_RULES = [
    ('about',        2, ['about', 'company', 'our-story', 'who-we-are', 'mission']),
    ('product',      3, ['product', 'products', 'features', 'platform', 'how-it-works', 'capabilities']),
    ('pricing',      3, ['pricing', 'plans', 'price']),
    ('customers',    4, ['customer', 'customers', 'case-stud', 'case-study', 'casestudies', 'success', 'testimonial', 'stories']),
    ('solutions',    5, ['solution', 'solutions', 'use-case', 'use-cases', 'usecases', 'industries']),
    ('services',     5, ['services', 'service', 'what-we-do', 'offerings']),
    ('integrations', 6, ['integration', 'integrations', 'partners', 'marketplace']),
    ('changelog',    8, ['changelog', 'release-notes', 'whats-new', 'updates']),
    ('docs',         8, ['docs', 'documentation', 'developers', 'guide', 'guides']),
    ('blog',         8, ['blog', 'resources', 'insights', 'articles', 'news', 'learn']),
    ('careers',      9, ['careers', 'jobs', 'hiring']),
    ('contact',      9, ['contact', 'demo', 'get-started']),
]

# Paths we never want to analyze (legal/auth/utility/asset/transactional).
EXCLUDE_KEYWORDS = [
    'privacy', 'terms', 'tos', 'legal', 'cookie', 'gdpr', 'dpa', 'eula',
    'login', 'signin', 'sign-in', 'signup', 'sign-up', 'register', 'logout',
    'account', 'cart', 'checkout', 'basket', 'wishlist', 'password', 'reset',
    'sitemap', 'rss', 'feed', 'tag', 'tags', 'category', 'categories', 'author',
    'wp-admin', 'wp-login', 'wp-content', 'wp-json', 'admin',
    'unsubscribe', 'preferences', 'status', 'careers/apply',
]
EXCLUDE_EXTENSIONS = (
    '.pdf', '.zip', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.ico',
    '.css', '.js', '.json', '.xml', '.txt', '.mp4', '.mp3', '.woff', '.woff2',
    '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.dmg', '.exe',
)
# Categories where the inventory is huge (blog posts, docs pages). We keep only a
# couple so a content-heavy site doesn't blow the whole budget on blog articles.
CAPPED_CATEGORIES = {'blog': 2, 'docs': 2, 'changelog': 1, 'integrations': 3,
                     'customers': 4, 'solutions': 4, 'product': 5, 'other': 6}


def normalize_url(url: str) -> str:
    if not url:
        return url
    url = url.strip()
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    return url


def _registrable_domain(url: str) -> str:
    ext = tldextract.extract(url)
    return f"{ext.domain}.{ext.suffix}".lower()


# Subdomains worth crawling for marketing/business content. Utility subdomains
# (app, help, status, trust, api, account, ...) are NOT the marketing site and just
# pollute the page set, so we keep only the apex + an allowlist of content hosts.
ALLOWED_SUBDOMAINS = {'', 'www', 'blog', 'resources', 'learn', 'go', 'get', 'info', 'news', 'about'}


def _allowed_host(url: str, base_domain: str) -> bool:
    """Same registrable domain AND an apex/www/content subdomain (not app/help/etc.)."""
    try:
        ext = tldextract.extract(url)
        if f"{ext.domain}.{ext.suffix}".lower() != base_domain:
            return False
        return ext.subdomain.lower() in ALLOWED_SUBDOMAINS
    except Exception:
        return False


def _clean_url(url: str) -> str:
    """Strip fragments and trailing slashes (so /about and /about/ dedupe)."""
    url, _ = urldefrag(url)
    if url.endswith('/') and len(urlparse(url).path) > 1:
        url = url.rstrip('/')
    return url


def _canon_key(url: str) -> str:
    """Dedupe key: host without leading 'www.' + path (so www/non-www collapse)."""
    p = urlparse(url)
    host = p.netloc.lower()
    if host.startswith('www.'):
        host = host[4:]
    return host + (p.path.rstrip('/') or '/')


def _kw_match(path: str, keyword: str) -> bool:
    """Boundary-aware keyword match: hyphens/slashes/dots act as token boundaries,
    so 'team' does NOT match 'teamplify' but does match '/team' or '/our-team'."""
    return re.search(r'(?<![a-z0-9])' + re.escape(keyword) + r'(?![a-z0-9])', path) is not None


def categorize(url: str):
    """Return (category, priority) for a URL. None if it should be excluded.

    Categorization keys on the FIRST path segment (the site section), not the deep
    slug — otherwise a blog post titled '.../how-we-think-about-customers' would be
    mis-filed as 'about'/'customers'. Deep slugs only affect dedupe/length ordering.
    """
    path = urlparse(url).path.lower()

    # Homepage
    if path in ('', '/'):
        return ('home', 0)

    # Excludes (checked against the whole path)
    if any(path.endswith(ext) for ext in EXCLUDE_EXTENSIONS):
        return None
    if any(kw in path for kw in EXCLUDE_KEYWORDS):
        return None

    segments = [p for p in path.split('/') if p]
    section = segments[0] if segments else ''

    for category, priority, keywords in CATEGORY_RULES:
        if any(_kw_match(section, kw) for kw in keywords):
            # A category landing page (e.g. /customers) ranks above its children
            # (e.g. /customers/acme) so the index is preferred when budget is tight.
            return (category, priority if len(segments) == 1 else priority + 1)

    # Unknown section. Shallow paths score better than deep ones.
    return ('other', 10 if len(segments) == 1 else 12)


# ---------------------------------------------------------------------------
# Sitemap discovery
# ---------------------------------------------------------------------------
def _fetch(url: str, timeout: int = SITEMAP_TIMEOUT):
    try:
        r = requests.get(url, headers={'User-Agent': USER_AGENT}, timeout=timeout,
                         allow_redirects=True)
        if r.status_code == 200:
            return r.text
    except requests.RequestException:
        pass
    return None


def _parse_sitemap(xml_text: str):
    """Return (page_urls, nested_sitemap_urls) from a sitemap or sitemap-index."""
    pages, nested = [], []
    try:
        # Strip namespaces for simpler tag matching.
        cleaned = re.sub(r'\sxmlns="[^"]+"', '', xml_text, count=1)
        root = ET.fromstring(cleaned)
    except ET.ParseError:
        return pages, nested
    tag = root.tag.lower()
    if tag.endswith('sitemapindex'):
        for sm in root.findall('.//sitemap/loc'):
            if sm.text:
                nested.append(sm.text.strip())
    else:  # urlset
        for loc in root.findall('.//url/loc'):
            if loc.text:
                pages.append(loc.text.strip())
    return pages, nested


def _sitemap_urls_from_robots(base: str):
    """Find Sitemap: lines in robots.txt."""
    txt = _fetch(urljoin(base, '/robots.txt'))
    if not txt:
        return []
    return re.findall(r'(?im)^\s*sitemap:\s*(\S+)', txt)


def discover_from_sitemap(base_url: str) -> list:
    """Collect candidate page URLs from sitemap.xml / robots.txt (with index recursion)."""
    base = normalize_url(base_url)
    candidates = []
    seen_sitemaps = set()
    queue = _sitemap_urls_from_robots(base) + [
        urljoin(base, '/sitemap.xml'), urljoin(base, '/sitemap_index.xml'),
    ]
    while queue and len(candidates) < MAX_SITEMAP_URLS:
        sm_url = queue.pop(0)
        if sm_url in seen_sitemaps:
            continue
        seen_sitemaps.add(sm_url)
        xml_text = _fetch(sm_url)
        if not xml_text:
            continue
        pages, nested = _parse_sitemap(xml_text)
        candidates.extend(pages)
        for n in nested:
            if n not in seen_sitemaps and len(seen_sitemaps) < 50:
                queue.append(n)
    return candidates


# ---------------------------------------------------------------------------
# Homepage link harvest (Playwright) — catches JS-rendered nav the sitemap misses
# ---------------------------------------------------------------------------
async def _homepage_links_async(url: str) -> list:
    from playwright.async_api import async_playwright
    links = []
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=[
                '--ignore-certificate-errors', '--ssl-version-min=tls1'])
            context = await browser.new_context(user_agent=USER_AGENT,
                                                 ignore_https_errors=True)
            page = await context.new_page()
            await page.goto(normalize_url(url), wait_until='domcontentloaded', timeout=45000)
            await page.wait_for_timeout(2500)
            hrefs = await page.evaluate(
                "() => Array.from(document.querySelectorAll('a[href]'))"
                ".map(a => a.href)")
            links = hrefs or []
            await browser.close()
    except Exception:
        pass
    return links


def discover_from_homepage(url: str) -> list:
    """Best-effort harvest of all anchor hrefs on the rendered homepage."""
    import asyncio
    try:
        return asyncio.run(_homepage_links_async(url))
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------
def discover_pages(base_url: str, max_pages: int = DEFAULT_MAX_PAGES,
                   use_playwright: bool = True) -> list:
    """
    Discover + prioritize pages for analysis.

    Returns an ordered list of {'url', 'category', 'priority'}, homepage first,
    capped at max_pages. Combines sitemap.xml with a rendered-homepage link harvest.
    """
    base = normalize_url(base_url)
    base_domain = _registrable_domain(base)
    home = _clean_url(base)

    raw = [home]
    raw.extend(discover_from_sitemap(base))
    if use_playwright:
        raw.extend(discover_from_homepage(base))

    # Normalize, keep same-site, dedupe (www/non-www collapse), categorize.
    by_url = {}
    for u in raw:
        if not u or not u.startswith('http'):
            continue
        if not _allowed_host(u, base_domain):
            continue
        cu = _clean_url(u)
        cat = categorize(cu)
        if cat is None:
            continue
        category, priority = cat
        key = _canon_key(cu)
        # Keep the best (lowest priority) categorization if seen twice.
        if key not in by_url or priority < by_url[key]['priority']:
            by_url[key] = {'url': cu, 'category': category, 'priority': priority}

    # Always ensure homepage is present and first.
    by_url[_canon_key(home)] = {'url': home, 'category': 'home', 'priority': 0}

    # Apply per-category caps (blog/docs) before the global cap.
    pages = sorted(by_url.values(), key=lambda d: (d['priority'], len(d['url']), d['url']))
    capped, counts = [], {}
    for p in pages:
        cap = CAPPED_CATEGORIES.get(p['category'])
        if cap is not None:
            counts[p['category']] = counts.get(p['category'], 0) + 1
            if counts[p['category']] > cap:
                continue
        capped.append(p)
        if len(capped) >= max_pages:
            break
    return capped


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Discover + prioritize pages for site analysis')
    parser.add_argument('url', help='Company website URL')
    parser.add_argument('--max-pages', type=int, default=DEFAULT_MAX_PAGES)
    parser.add_argument('--no-playwright', action='store_true',
                        help='Skip the rendered-homepage link harvest (sitemap only)')
    args = parser.parse_args()

    pages = discover_pages(args.url, max_pages=args.max_pages,
                           use_playwright=not args.no_playwright)
    print(f"\nDiscovered {len(pages)} pages (prioritized):\n")
    for i, p in enumerate(pages, 1):
        print(f"  {i:2d}. [{p['category']:<11}] {p['url']}")
