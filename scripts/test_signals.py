#!/usr/bin/env python3
"""
Regression tests for the objective-signal pipeline (Phase 1 PageSpeed extras + CrUX,
Phase 2 AI-readiness). Offline / deterministic — no network required.

Run: python scripts/test_signals.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import pagespeed_checker as ps
import ai_readiness as ar
import accessibility as a11y
import security_check as sc
import page_signals as pgs
import orchestrator as o


def check(name, cond):
    assert cond, f"FAILED: {name}"
    print(f"  ok: {name}")


def test_p0_mobile_branch_has_no_desktop_keys():
    """P0 regression: the orchestrator mobile-capture branch copies
    PAGESPEED_LAB_CATEGORY_FIELDS + PAGESPEED_CRUX_FIELDS from the mobile result.
    EVERY one of those keys MUST exist on a get_pagespeed_score result, and NO
    '*_desktop' key may — otherwise the per-entry loop KeyErrors and the run dies."""
    r = ps.get_pagespeed_score('')  # returns the fully-initialized result dict (empty URL)
    for k in o.PAGESPEED_LAB_CATEGORY_FIELDS + o.PAGESPEED_CRUX_FIELDS:
        check(f"mobile result has '{k}'", k in r)
    check("no '_desktop' keys on mobile result",
          not any(k.endswith('_desktop') for k in r))
    # the desktop suffixed set is exactly the mobile crux set + suffix
    check("desktop field set well-formed",
          set(o.PAGESPEED_CRUX_FIELDS_DESKTOP) == {f + '_desktop' for f in o.PAGESPEED_CRUX_FIELDS})


def test_field_units():
    fm = ar  # noqa (placeholder to keep import grouping)
    m = ps._parse_field_metrics({'metrics': {
        'LARGEST_CONTENTFUL_PAINT_MS': {'percentile': 2022},
        'INTERACTION_TO_NEXT_PAINT': {'percentile': 221},
        'CUMULATIVE_LAYOUT_SHIFT_SCORE': {'percentile': 12},
        'FIRST_CONTENTFUL_PAINT_MS': {'percentile': 1800},
        'EXPERIMENTAL_TIME_TO_FIRST_BYTE': {'percentile': 800}}})
    check("LCP in seconds", m['field_lcp'] == 2.02)
    check("FCP in seconds", m['field_fcp'] == 1.8)
    check("INP in ms", m['field_inp'] == 221)
    check("TTFB in ms", m['field_ttfb'] == 800)
    check("CLS unitless", m['field_cls'] == 0.12)
    check("INP rating from ms", m['field_inp_rating'] == 'needs-improvement')


def test_retry_after_date():
    from email.utils import format_datetime
    from datetime import datetime, timezone, timedelta

    class R:
        headers = {'Retry-After': '5'}
    check("Retry-After seconds honored", ps._retry_wait(R(), 0) == 5.0)

    class RD:
        headers = {'Retry-After': format_datetime(datetime.now(timezone.utc) + timedelta(seconds=20))}
    w = ps._retry_wait(RD(), 0)
    check("Retry-After HTTP-date honored (~20s)", 10 <= w <= 30)
    check("no Retry-After -> exp backoff", ps._retry_wait(None, 2) == 8.0)


def test_robots_blocking():
    g, sm = ar._parse_robots("User-agent: GPTBot\nDisallow: /\n\nUser-agent: *\nDisallow: /private\n")
    check("GPTBot blocked by Disallow:/", ar._bot_blocked(g, 'GPTBot'))
    check("Perplexity allowed (falls to *)", not ar._bot_blocked(g, 'PerplexityBot'))
    g2, _ = ar._parse_robots("User-agent: CCBot\nDisallow: /*\n")
    check("Disallow:/* treated as full block", ar._bot_blocked(g2, 'CCBot'))
    g3, _ = ar._parse_robots("User-agent: ClaudeBot\nDisallow: /\nAllow: /\n")
    check("Allow:/ overrides Disallow:/", not ar._bot_blocked(g3, 'ClaudeBot'))


def test_jsonld_cdata():
    from bs4 import BeautifulSoup
    html = ('<script type="application/ld+json">//<![CDATA[\n'
            '{"@type":"Organization"}\n//]]></script>')
    cnt, types = ar._extract_jsonld(BeautifulSoup(html, 'html.parser'))
    check("CDATA-wrapped JSON-LD parsed", cnt == 1 and 'Organization' in types)


def test_hidden_text_excluded():
    from bs4 import BeautifulSoup
    visible = '<body><p>one two three</p></body>'
    hidden = '<body><p>one two three</p><div style="display:none">a b c d e f</div></body>'
    wc_v = ar._visible_word_count(BeautifulSoup(visible, 'html.parser'))
    wc_h = ar._visible_word_count(BeautifulSoup(hidden, 'html.parser'))
    check("hidden text excluded from word count", wc_v == 3 and wc_h == 3)


def test_score_partial_flag():
    # full set measured -> not partial
    full = ar._default_result()
    full.update({'ssr_content_ratio': 0.2, 'robots_blocks_ai': False, 'has_schema_org': False,
                 'has_sitemap': False, 'has_title': True, 'has_meta_description': False,
                 'has_og_tags': False, 'h1_count': 1, 'has_llms_txt': False})
    score, possible = ar._compute_score(full)
    check("full score uses 100 possible", possible == ar.FULL_POSSIBLE)
    # SSR unmeasured -> possible drops -> caller flags partial
    part = dict(full); part['ssr_content_ratio'] = None
    s2, p2 = ar._compute_score(part)
    check("partial possible < full", p2 < ar.FULL_POSSIBLE)


def test_axe_lawsuit_flag_keys_off_rule():
    # null top-level impact on a litigated rule: impact falls back to node impact,
    # and the lawsuit flag still fires (keyed off the rule, not the impact bucket).
    r = a11y._parse_axe_results({'violations': [
        {'id': 'image-alt', 'impact': None, 'help': 'Images must have alternate text',
         'tags': ['wcag2a', 'wcag111'], 'nodes': [{'impact': 'critical'}, {'impact': 'critical'}]},
    ]})
    check("null impact -> derived from nodes (critical)", r['a11y_critical'] == 1 and r['a11y_minor'] == 0)
    check("lawsuit flag fires on litigated rule despite null impact", r['a11y_lawsuit_risk'] is True)
    # litigated rule with no impact anywhere -> minor bucket, but flag still fires
    r2 = a11y._parse_axe_results({'violations': [
        {'id': 'label', 'impact': None, 'help': 'Form fields need labels', 'tags': ['wcag2a'], 'nodes': [{}]}]})
    check("no-impact litigated rule still flags lawsuit", r2['a11y_lawsuit_risk'] is True)
    # non-litigated rule -> no lawsuit flag
    r3 = a11y._parse_axe_results({'violations': [
        {'id': 'region', 'impact': 'moderate', 'help': 'Use landmarks', 'tags': ['best-practice'], 'nodes': [{}]}]})
    check("non-litigated rule does not flag lawsuit", r3['a11y_lawsuit_risk'] is False)
    # clean page: measured zeros, no error, no risk
    r4 = a11y._parse_axe_results({'violations': []})
    check("clean page = 0 violations, no risk, no error",
          r4['a11y_violation_count'] == 0 and r4['a11y_lawsuit_risk'] is False and r4['a11y_error'] == '')


def test_security_header_grade_and_mixed_content():
    class FakeResp:
        def __init__(self, headers=None, text='', url='https://x.com'):
            self.headers = headers or {}
            self.text = text
            self.url = url
            self.status_code = 200
    # header grade: HSTS(25)+X-Frame(15)+X-CTO(15)=55 -> D, missing CSP listed
    r = sc.security_defaults()
    sc._check_headers(FakeResp({'Strict-Transport-Security': 'max-age=1',
                                'X-Frame-Options': 'DENY',
                                'X-Content-Type-Options': 'nosniff'}), r, [])
    check("header score 55 -> D", r['sec_header_score'] == 55 and r['sec_header_grade'] == 'D')
    check("missing CSP listed", 'Content-Security-Policy' in r['sec_headers_missing'])
    # mixed content: src + srcset + css url()
    r2 = sc.security_defaults()
    html = ('<img src="http://a.com/1.png"><img srcset="http://a.com/2.png 2x">'
            '<div style="background:url(http://a.com/bg.jpg)"></div><script src="https://ok/s.js"></script>')
    sc._check_mixed_content(FakeResp(text=html), 'https://x.com', r2, [])
    check("mixed content counts src+srcset+css", r2['mixed_content'] is True and r2['mixed_content_count'] == 3)
    # http page -> mixed content N/A
    r3 = sc.security_defaults()
    sc._check_mixed_content(FakeResp(text=html, url='http://x.com'), 'http://x.com', r3, [])
    check("mixed content N/A on http page", r3['mixed_content'] is None)


def test_ssl_error_classification():
    for msg, expect in [('certificate has expired', 'expired'),
                        ('self signed certificate', 'self-signed'),
                        ('self-signed certificate in certificate chain', 'authority'),
                        ("hostname 'x' doesn't match 'y'", 'match'),
                        ('unable to get local issuer', 'authority')]:
        r = sc.security_defaults()
        issues = []
        sc._classify_ssl_error(msg, r, issues)
        check(f"classify '{msg[:24]}'", expect in issues[0].lower())
    # expired sets the urgent flag and leaves exact days unknown
    r = sc.security_defaults()
    sc._classify_ssl_error('certificate has expired', r, [])
    check("expired -> expires_soon flag, days unknown",
          r['ssl_expires_soon'] is True and r['ssl_days_to_expiry'] is None)


def test_page_signals_dedupe_and_consent():
    # ranged video across 3 chunked 206s + duplicate image -> each counted ONCE at full size
    resp = [
        {'url': 'https://x.com/v.mp4', 'type': 'video/mp4', 'length': '1048576', 'range': 'bytes 0-1048575/23000000'},
        {'url': 'https://x.com/v.mp4', 'type': 'video/mp4', 'length': '1048576', 'range': 'bytes 1048576-2097151/23000000'},
        {'url': 'https://x.com/a.jpg', 'type': 'image/jpeg', 'length': '300000'},
        {'url': 'https://x.com/a.jpg', 'type': 'image/jpeg', 'length': '300000'},
        {'url': 'https://www.google-analytics.com/g.js', 'type': 'application/javascript', 'length': '40000'},
    ]
    r = pgs.parse_network_signals(resp, [{'name': '_ga'}], consent_present=True, base_url='https://x.com')
    check("deduped to 3 resources", r['request_count'] == 3)
    check("video counted once at full range size", r['page_weight_kb'] == round((23000000 + 300000 + 40000) / 1024))
    check("image counted once", r['image_count'] == 1 and r['large_image_count'] == 1)
    check("GA tracker detected", r['tracker_count'] == 1 and 'Google Analytics' in r['trackers_detected'])
    # the flag keys off a tracking COOKIE being set (here _ga) — fires even WITH a banner
    check("tracking before consent despite banner present", r['has_consent_banner'] is True and r['tracking_before_consent'] is True)
    # Consent Mode: GA request fires but sets NO tracking cookie -> tracker is detected
    # (informational) but the flag does NOT fire (cookieless ping is not the trigger).
    r3 = pgs.parse_network_signals(resp, [{'name': 'session'}], consent_present=True, base_url='https://x.com')
    check("tracker detected but cookieless -> not flagged",
          'Google Analytics' in r3['trackers_detected'] and r3['tracking_before_consent'] is False)
    # clean site: no trackers, no tracking cookies -> no violation; no images -> nextgen None
    r2 = pgs.parse_network_signals(
        [{'url': 'https://x.com/', 'type': 'text/html', 'length': '2000'}],
        [{'name': 'session'}], False, 'https://x.com')
    check("clean site no tracking-before-consent", r2['tracking_before_consent'] is False and r2['uses_next_gen_images'] is None)


def test_assess_sets_partial():
    # no rendered_text on an unreachable host -> partial flag set or None, never crash
    res = ar.assess_ai_readiness('nonexistent-xyz-123-abc.invalid', timeout=5)
    check("unreachable host never raises", isinstance(res, dict))
    check("partial flag present", 'ai_readiness_partial' in res)


if __name__ == '__main__':
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    print(f"Running {len(tests)} signal regression tests...\n")
    for t in tests:
        print(t.__name__)
        t()
    print(f"\nALL {len(tests)} TEST GROUPS PASSED")
