#!/usr/bin/env python3
"""
AI-Readiness checker — objective, deterministic signals for whether bots & AI engines
(ChatGPT, Perplexity, Claude, Google AI) can DISCOVER and PARSE a site's content.

No LLM. Every check is a black-and-white fact. Produces one consolidated
`ai_readiness_score` (0-100) for ranking PLUS every sub-check as its own field so we
can cite the exact problem in outreach ("only 31% of your content is server-rendered",
"you block GPTBot", "no structured data", "no sitemap").

Sub-checks:
  1. Server- vs client-rendered ratio  — raw HTTP HTML text vs JS-rendered text.
     The single biggest signal: if content only appears after JavaScript runs, most AI
     crawlers (which often don't execute JS) see an empty page.
  2. robots.txt AI-bot policy           — does it block GPTBot/ClaudeBot/PerplexityBot/etc.?
  3. llms.txt presence                  — the emerging standard for AI-readable summaries.
  4. Structured data (Schema.org JSON-LD) — how AI/search extract facts cleanly.
  5. sitemap.xml                        — helps crawlers find all pages.
  6. Semantic HTML / metadata          — <title>, meta description, OpenGraph, single <h1>.

Checks 1, 4, 6 read the RAW HTML (what a non-JS crawler sees) on purpose — that is the
AI-readiness question. 2/3/5 are independent HTTP GETs.
"""

import json
import sys
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup

# A realistic browser UA so sites don't block the raw-HTML fetch outright.
BROWSER_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/124.0 Safari/537.36')
DEFAULT_TIMEOUT = 15

# Major AI / LLM crawlers we check robots.txt for.
AI_BOTS = ['GPTBot', 'ChatGPT-User', 'OAI-SearchBot', 'ClaudeBot', 'anthropic-ai',
           'Claude-Web', 'PerplexityBot', 'Google-Extended', 'CCBot', 'Bytespider',
           'Amazonbot', 'Applebot-Extended', 'Meta-ExternalAgent']

# Schema.org types that matter most for AI/search rich extraction.
HIGH_VALUE_SCHEMA_TYPES = {'organization', 'product', 'article', 'faqpage', 'website',
                           'breadcrumblist', 'localbusiness', 'softwareapplication',
                           'webpage', 'service', 'review', 'aggregaterating'}

# Below this server-rendered fraction, the page is "client-rendered" (AI-invisible risk).
SSR_CLIENT_THRESHOLD = 0.5

# Scoring weights (sum to 100 when SSR can be measured).
W_SSR = 30
W_ROBOTS_AI = 15
W_STRUCTURED = 20
W_SITEMAP = 10
W_SEMANTIC = 20   # title 5 + meta-desc 5 + OG 5 + single-h1 5
W_LLMS = 5
FULL_POSSIBLE = W_SSR + W_ROBOTS_AI + W_STRUCTURED + W_SITEMAP + W_SEMANTIC + W_LLMS  # 100


def _default_result():
    return {
        'ai_readiness_score': None,
        'ai_readiness_partial': None,
        'ai_readiness_issues': '',
        # SSR
        'ssr_raw_words': None,
        'ssr_rendered_words': None,
        'ssr_content_ratio': None,
        'ssr_client_rendered': None,
        # robots
        'robots_found': None,
        'robots_blocks_ai': None,
        'robots_ai_blocked_list': '',
        'robots_has_sitemap': None,
        # llms.txt
        'has_llms_txt': None,
        # structured data
        'jsonld_count': None,
        'jsonld_types': '',
        'has_schema_org': None,
        # sitemap
        'has_sitemap': None,
        'sitemap_url_count': None,
        # semantic / meta
        'has_title': None,
        'title_text': '',
        'has_meta_description': None,
        'meta_description_text': '',
        'has_og_tags': None,
        'h1_count': None,
        'ai_readiness_error': '',
    }


AI_READINESS_FIELDS = tuple(_default_result().keys())
# Text columns default to '' ; everything else to None.
_TEXT_FIELDS = {'ai_readiness_issues', 'robots_ai_blocked_list', 'jsonld_types',
                'title_text', 'meta_description_text', 'ai_readiness_error'}


def ai_readiness_defaults():
    """Empty defaults for all AI-readiness fields (for result-dict initialization)."""
    return {f: ('' if f in _TEXT_FIELDS else None) for f in AI_READINESS_FIELDS}


def _normalize_url(url):
    url = (url or '').strip()
    if not url:
        return ''
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    return url


def _origin(url):
    """scheme://host for building /robots.txt etc."""
    p = urlparse(url)
    return f'{p.scheme}://{p.netloc}'


def _get(url, timeout=DEFAULT_TIMEOUT):
    return requests.get(url, headers={'User-Agent': BROWSER_UA},
                        timeout=timeout, allow_redirects=True)


def _visible_word_count(soup):
    """Word count of VISIBLE text, approximating a browser's innerText so it is
    comparable to the Playwright-rendered text we diff against.

    Drops scripts/styles/head AND elements hidden via the common mechanisms
    (hidden attribute, aria-hidden, display:none / visibility:hidden inline styles).
    We can't run the CSS cascade, so this is an approximation — but it removes the
    systematic upward bias of counting hidden/menu text the rendered side excludes.
    NOTE: mutates the soup; call AFTER other parsing (title/meta/jsonld/h1).
    """
    root = soup.body or soup
    for tag in root(['script', 'style', 'noscript', 'template', 'head']):
        tag.decompose()
    for tag in root.find_all(True):
        try:
            if tag.has_attr('hidden') or tag.get('aria-hidden') == 'true':
                tag.decompose()
                continue
            style = (tag.get('style') or '').replace(' ', '').lower()
            if 'display:none' in style or 'visibility:hidden' in style:
                tag.decompose()
        except Exception:
            continue  # tag already detached (parent removed) — skip
    return len(root.get_text(separator=' ').split())


def _collect_schema_types(node):
    """Recursively pull @type values out of a parsed JSON-LD node (handles
    dict, list, and @graph)."""
    out = []
    if isinstance(node, dict):
        t = node.get('@type')
        if isinstance(t, list):
            out.extend(str(x) for x in t)
        elif t is not None:
            out.append(str(t))
        graph = node.get('@graph')
        if isinstance(graph, list):
            for item in graph:
                out.extend(_collect_schema_types(item))
    elif isinstance(node, list):
        for item in node:
            out.extend(_collect_schema_types(item))
    return out


def _extract_jsonld(soup):
    """(count_of_valid_blocks, list_of_unique_types) from <script ld+json> tags."""
    count = 0
    types = []
    for tag in soup.find_all('script', attrs={'type': 'application/ld+json'}):
        raw = tag.string or tag.get_text() or ''
        # Strip CDATA / JS-comment wrappers some CMSs (WordPress/Drupal) emit, e.g.
        # //<![CDATA[ {...} //]]> — otherwise valid JSON-LD fails json.loads.
        raw = (raw.replace('//<![CDATA[', '').replace('<![CDATA[', '')
                  .replace('//]]>', '').replace(']]>', '').strip())
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            continue  # malformed JSON-LD — don't count it as valid
        count += 1
        types.extend(_collect_schema_types(data))
    # de-dupe preserving order
    seen = set()
    unique = []
    for t in types:
        key = t.lower()
        if key not in seen:
            seen.add(key)
            unique.append(t)
    return count, unique


def _parse_robots(text):
    """Parse robots.txt into {user_agent_lower: [(directive, value), ...]} plus a
    list of Sitemap: URLs. Approximation of the spec: handles consecutive
    User-agent lines sharing one rule block, comments, and blank lines."""
    groups = {}
    sitemaps = []
    current_uas = []
    last_was_ua = False
    for raw in text.splitlines():
        line = raw.split('#', 1)[0].strip()
        if not line or ':' not in line:
            last_was_ua = False if not line else last_was_ua
            continue
        field, _, value = line.partition(':')
        field = field.strip().lower()
        value = value.strip()
        if field == 'user-agent':
            ua = value.lower()
            if last_was_ua:
                current_uas.append(ua)
            else:
                current_uas = [ua]
            groups.setdefault(ua, [])
            last_was_ua = True
        elif field in ('disallow', 'allow'):
            for ua in current_uas:
                groups.setdefault(ua, []).append((field, value))
            last_was_ua = False
        elif field == 'sitemap':
            sitemaps.append(value)
            last_was_ua = False
        else:
            last_was_ua = False
    return groups, sitemaps


def _bot_blocked(groups, bot):
    """True if robots.txt blocks `bot` from the site root. Uses the bot-specific
    group if present, else the '*' group. 'Blocked' = Disallow: / not overridden by
    an explicit Allow: /."""
    rules = groups.get(bot.lower())
    if rules is None:
        rules = groups.get('*')
    if not rules:
        return False
    # '/' and '/*' both block the whole site.
    disallow_root = any(d == 'disallow' and v in ('/', '/*') for d, v in rules)
    allow_root = any(d == 'allow' and v in ('/', '/*') for d, v in rules)
    return disallow_root and not allow_root


_SOFT_404_PHRASES = ('not found', '404', 'page not found', 'does not exist',
                     'no such file', 'error')


def _looks_like_file(resp, min_len=1, reject_soft_404=False):
    """A 200 that is actually the requested TEXT file, not a soft-404 HTML page.

    Guards llms.txt: many sites return 200 + an HTML (or plain-text) error page for
    missing files. Reject HTML, empty/too-short bodies, and obvious 404 text.
    """
    if resp.status_code != 200:
        return False
    body = (resp.text or '').strip()
    if len(body) < min_len:
        return False
    ctype = resp.headers.get('Content-Type', '').lower()
    if 'html' in ctype or body[:200].lstrip().lower().startswith(('<!doctype html', '<html')):
        return False
    if reject_soft_404 and any(p in body[:120].lower() for p in _SOFT_404_PHRASES):
        return False
    return True


def _is_xml_sitemap(resp):
    """A 200 that is actually an XML sitemap. Accepts by XML markers EVEN if the
    server mislabels the Content-Type as text/html (common misconfiguration)."""
    if resp.status_code != 200:
        return False
    body = (resp.text or '').strip()
    low = body[:500].lower()
    return low.startswith('<?xml') or '<urlset' in body.lower() or '<sitemapindex' in body.lower()


def assess_ai_readiness(url, rendered_text=None, timeout=DEFAULT_TIMEOUT):
    """Run all AI-readiness checks for `url`.

    Args:
        url: site URL.
        rendered_text: the JS-rendered visible text (e.g. from the Playwright capture).
            Needed to compute the server-vs-client render ratio. If None, the SSR check
            is skipped and the score is scaled over the remaining checks.
        timeout: per-request timeout.

    Returns a flat dict of all AI_READINESS_FIELDS. Never raises.
    """
    result = _default_result()
    url = _normalize_url(url)
    if not url:
        result['ai_readiness_error'] = 'Empty URL'
        return result

    origin = _origin(url)
    issues = []

    # ---- 1/4/6: fetch RAW HTML and parse (what a non-JS crawler sees) ----
    raw_words = None
    try:
        resp = _get(url, timeout)
        if resp.status_code == 200 and resp.text:
            if resp.encoding is None:
                resp.encoding = resp.apparent_encoding
            soup = BeautifulSoup(resp.text, 'html.parser')

            # Semantic / metadata
            title = soup.title.string if soup.title and soup.title.string else ''
            title = (title or '').strip()
            result['has_title'] = bool(title)
            result['title_text'] = title[:300]
            if not title:
                issues.append('Missing <title>')

            md = soup.find('meta', attrs={'name': lambda v: v and v.lower() == 'description'})
            md_content = (md.get('content') or '').strip() if md else ''
            result['has_meta_description'] = bool(md_content)
            result['meta_description_text'] = md_content[:300]
            if not md_content:
                issues.append('Missing meta description')

            og = soup.find('meta', attrs={'property': lambda v: v and v.lower().startswith('og:')})
            result['has_og_tags'] = bool(og)
            if not og:
                issues.append('No OpenGraph tags (broken social/link previews)')

            h1s = soup.find_all('h1')
            result['h1_count'] = len(h1s)
            if len(h1s) == 0:
                issues.append('No <h1> heading')
            elif len(h1s) > 1:
                issues.append(f'{len(h1s)} <h1> headings (should be exactly 1)')

            # Structured data
            jsonld_count, jsonld_types = _extract_jsonld(soup)
            result['jsonld_count'] = jsonld_count
            result['jsonld_types'] = ', '.join(jsonld_types)
            result['has_schema_org'] = jsonld_count > 0
            if jsonld_count == 0:
                issues.append('No structured data (Schema.org JSON-LD)')

            # Raw (server-rendered) word count for the SSR ratio
            raw_words = _visible_word_count(soup)
            result['ssr_raw_words'] = raw_words
        else:
            result['ai_readiness_error'] = f'Raw HTML HTTP {resp.status_code}'
    except requests.exceptions.Timeout:
        result['ai_readiness_error'] = 'Raw HTML timeout'
    except requests.exceptions.RequestException as e:
        result['ai_readiness_error'] = f'Raw HTML: {str(e)[:50]}'
    except Exception as e:
        result['ai_readiness_error'] = f'Parse: {str(e)[:50]}'

    # ---- 1: server- vs client-rendered ratio (needs rendered_text) ----
    if rendered_text is not None and raw_words is not None:
        rendered_words = len(rendered_text.split())
        result['ssr_rendered_words'] = rendered_words
        if rendered_words > 0:
            ratio = round(raw_words / rendered_words, 2)
            result['ssr_content_ratio'] = ratio
            result['ssr_client_rendered'] = ratio < SSR_CLIENT_THRESHOLD
            if ratio < SSR_CLIENT_THRESHOLD:
                # Coarse band, not a precise % — the raw/rendered measurement is an
                # approximation. Exact word counts live in the ssr_* columns.
                issues.append('Content is mostly client-rendered (JavaScript-dependent) '
                              '— AI crawlers and bots may not see most of it')

    # ---- 2: robots.txt AI-bot policy ----
    try:
        r = _get(origin + '/robots.txt', timeout)
        if r.status_code == 200 and not ('html' in r.headers.get('Content-Type', '').lower()):
            result['robots_found'] = True
            groups, sitemaps = _parse_robots(r.text or '')
            blocked = [bot for bot in AI_BOTS if _bot_blocked(groups, bot)]
            result['robots_blocks_ai'] = len(blocked) > 0
            result['robots_ai_blocked_list'] = ', '.join(blocked)
            result['robots_has_sitemap'] = len(sitemaps) > 0
            if blocked:
                issues.append('robots.txt blocks AI crawlers: ' + ', '.join(blocked))
        else:
            result['robots_found'] = False
            result['robots_blocks_ai'] = False
            result['robots_has_sitemap'] = False
    except requests.exceptions.RequestException:
        pass  # leave robots_* as None (couldn't determine)

    # ---- 3: llms.txt presence ----
    try:
        r = _get(origin + '/llms.txt', timeout)
        result['has_llms_txt'] = _looks_like_file(r, min_len=20, reject_soft_404=True)
        if not result['has_llms_txt']:
            issues.append('No llms.txt (AI-readable site summary)')
    except requests.exceptions.RequestException:
        pass

    # ---- 5: sitemap.xml ----
    try:
        r = _get(origin + '/sitemap.xml', timeout)
        xml_ok = _is_xml_sitemap(r)
        # also accept a sitemap declared in robots.txt
        has_sitemap = bool(xml_ok) or bool(result.get('robots_has_sitemap'))
        result['has_sitemap'] = has_sitemap
        if xml_ok:
            result['sitemap_url_count'] = (r.text or '').lower().count('<loc>')
        if not has_sitemap:
            issues.append('No sitemap.xml')
    except requests.exceptions.RequestException:
        if result.get('robots_has_sitemap'):
            result['has_sitemap'] = True

    result['ai_readiness_issues'] = '; '.join(issues)
    score, possible = _compute_score(result)
    result['ai_readiness_score'] = score
    # Partial = some checks couldn't be measured (usually SSR, when capture failed).
    # The score is then scaled over fewer checks and is NOT directly comparable to a
    # full score — surface that so ranking can treat partials separately.
    result['ai_readiness_partial'] = (possible < FULL_POSSIBLE) if possible > 0 else None
    return result


def _compute_score(r):
    """Weighted rollup. Returns (score, possible_weight). `score` is 0-100 scaled over
    whichever checks could be performed (SSR is skipped when no rendered_text was
    supplied), or None if nothing could be measured. `possible_weight` lets the caller
    flag a partial (non-comparable) score."""
    earned = 0.0
    possible = 0.0

    # SSR (only if measured)
    if r.get('ssr_content_ratio') is not None:
        earned += W_SSR * min(r['ssr_content_ratio'], 1.0)
        possible += W_SSR

    # robots AI policy (only if robots could be fetched/determined)
    if r.get('robots_blocks_ai') is not None:
        earned += 0 if r['robots_blocks_ai'] else W_ROBOTS_AI
        possible += W_ROBOTS_AI

    # structured data
    if r.get('has_schema_org') is not None:
        if r['has_schema_org']:
            types = {t.strip().lower() for t in (r.get('jsonld_types') or '').split(',') if t.strip()}
            high_value = bool(types & HIGH_VALUE_SCHEMA_TYPES)
            earned += W_STRUCTURED if high_value else W_STRUCTURED * 0.6
        possible += W_STRUCTURED

    # sitemap
    if r.get('has_sitemap') is not None:
        earned += W_SITEMAP if r['has_sitemap'] else 0
        possible += W_SITEMAP

    # semantic / meta (only if raw HTML parsed -> has_title is not None)
    if r.get('has_title') is not None:
        sem = 0
        sem += 5 if r.get('has_title') else 0
        sem += 5 if r.get('has_meta_description') else 0
        sem += 5 if r.get('has_og_tags') else 0
        sem += 5 if r.get('h1_count') == 1 else 0
        earned += sem
        possible += W_SEMANTIC

    # llms.txt
    if r.get('has_llms_txt') is not None:
        earned += W_LLMS if r['has_llms_txt'] else 0
        possible += W_LLMS

    if possible == 0:
        return None, 0
    return int(round(earned / possible * 100)), possible


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Check a URL for AI-readiness signals')
    parser.add_argument('url', help='Site URL')
    parser.add_argument('--rendered-from', help='Optional: file with JS-rendered text for the SSR ratio')
    args = parser.parse_args()

    rendered = None
    if args.rendered_from:
        with open(args.rendered_from) as f:
            rendered = f.read()

    res = assess_ai_readiness(args.url, rendered_text=rendered)
    print(f"\nAI-Readiness for {args.url}")
    print("=" * 60)
    print(f"  SCORE: {res['ai_readiness_score']}/100")
    if res['ai_readiness_error']:
        print(f"  ERROR: {res['ai_readiness_error']}")
    print(f"\n  Server-rendered ratio: {res['ssr_content_ratio']} "
          f"(raw {res['ssr_raw_words']} / rendered {res['ssr_rendered_words']} words)")
    print(f"  robots.txt found: {res['robots_found']} | blocks AI: {res['robots_blocks_ai']} "
          f"({res['robots_ai_blocked_list'] or 'none'})")
    print(f"  llms.txt: {res['has_llms_txt']}")
    print(f"  JSON-LD: {res['jsonld_count']} blocks | types: {res['jsonld_types'] or 'none'}")
    print(f"  sitemap.xml: {res['has_sitemap']} ({res['sitemap_url_count']} urls)")
    print(f"  title: {res['has_title']} | meta-desc: {res['has_meta_description']} | "
          f"OG: {res['has_og_tags']} | h1 count: {res['h1_count']}")
    print(f"\n  ISSUES: {res['ai_readiness_issues'] or '(none)'}")
