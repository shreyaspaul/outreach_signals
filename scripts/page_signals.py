#!/usr/bin/env python3
"""
Network-pass signals — derived from the resources a page loads, captured during the
Playwright capture pass we already run (no extra browser launch).

Two objective signal groups:
  1. Page weight + image bloat  — total bytes, image bytes, oversized/non-next-gen images.
     WordPress's signature weakness; a clean migration fixes it. ("8 MB homepage, 6 MB images.")
  2. Tracking COOKIES set before consent — since the capture never clicks "accept", any
     tracking cookie (an identifier like _ga/_fbp) found on load was stored WITHOUT consent.
     That cookie-write is the ePrivacy/GDPR trigger and the only thing the flag keys off — a
     tracker request firing on its own is NOT flagged (Google Consent Mode legitimately fires
     a cookieless ping when consent is denied). Trackers seen + whether a consent banner exists
     are recorded as context. ("Sets 4 tracking cookies (_ga, _fbp, …) before consent.")

`parse_network_signals` is a pure function (no browser) so it's unit-testable. The capture pass
feeds it: the list of responses seen, the cookies set, and whether a consent banner was detected.
"""

from urllib.parse import urlparse
import tldextract

# Trackers identified by their REGISTRABLE DOMAIN. These domains exist only to track,
# so a registrable-domain match is exact and safe (no substring false positives like
# "tiktok.com" matching "nottiktok.com"). Matched against tldextract's registered domain.
TRACKER_DOMAINS = {
    'google-analytics.com': 'Google Analytics',
    'googletagmanager.com': 'Google Tag Manager',
    'facebook.net': 'Meta Pixel',            # connect.facebook.net (the pixel loader)
    'licdn.com': 'LinkedIn Insight',         # snap.licdn.com (dedicated CDN)
    'hotjar.com': 'Hotjar',
    'hotjar.io': 'Hotjar',
    'segment.com': 'Segment',
    'segment.io': 'Segment',
    'clarity.ms': 'Microsoft Clarity',
    'doubleclick.net': 'Google Ads / DoubleClick',
    'googlesyndication.com': 'Google Ads',
    'googleadservices.com': 'Google Ads',
    'amplitude.com': 'Amplitude',
    'mxpnl.com': 'Mixpanel',
    'fullstory.com': 'FullStory',
    'mouseflow.com': 'Mouseflow',
    'hs-scripts.com': 'HubSpot',
    'hs-analytics.net': 'HubSpot',
    'hsadspixel.net': 'HubSpot',
    'pinimg.com': 'Pinterest Tag',           # s.pinimg.com/ct (Pinterest's dedicated CDN)
}

# Trackers hosted on BROAD consumer domains (facebook.com, tiktok.com, …) where the
# registrable domain alone is too broad. Matched on a specific host/path substring,
# which is precise enough to be safe.
TRACKER_HOST_PATH = {
    'bat.bing.com': 'Microsoft Ads',
    'analytics.tiktok.com': 'TikTok Pixel',
    'ads.linkedin.com': 'LinkedIn Ads',      # px.ads.linkedin.com
    'facebook.com/tr': 'Meta Pixel',
    'ct.pinterest.com': 'Pinterest Tag',
}

# Tracking cookies whose NAME is short/ambiguous -> require an EXACT match
# (e.g. DoubleClick's "IDE" must not match "IDENTITY"/"IDEA_session").
TRACKING_COOKIE_EXACT = frozenset({
    'IDE', 'personalization_id', 'hubspotutk', 'MUID', 'fr',
})

# Tracking-cookie NAME prefixes for the well-namespaced analytics/ad families.
TRACKING_COOKIE_PREFIXES = (
    '_ga', '_gid', '_gat', '_gcl', '_fbp', '_fbc', '_hj', 'ajs_', '_uet', 'mp_',
    'amplitude', '__hssc', '__hstc', '_clck', '_clsk', '_pin_unauth', '_pinterest',
)

_IMAGE_EXTS = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.avif', '.bmp', '.ico')

LARGE_IMAGE_BYTES = 200 * 1024     # a single image over 200 KB is "large"
HEAVY_PAGE_KB = 3 * 1024           # total page over 3 MB is "heavy"

PAGE_SIGNAL_FIELDS = (
    'page_weight_kb',          # transferred KB from Content-Length headers — a FLOOR (undercounts)
    'page_weight_partial',     # True = many resources reported no size -> weight is an unreliable floor
    'image_weight_kb',
    'image_count',
    'large_image_count',       # images > 200 KB
    'uses_next_gen_images',    # any webp/avif served
    'request_count',
    'third_party_domains',     # distinct off-site registrable domains
    'trackers_detected',       # citable list of named trackers
    'tracker_count',
    'cookies_set',             # total cookies after load (pre-consent)
    'tracking_cookies',        # of those, how many are tracking cookies
    'has_consent_banner',      # a cookie/consent banner was present
    'tracking_before_consent', # tracking fired BEFORE any consent (the observable privacy fact)
    'page_signals_issues',     # combined citable summary
    'page_signals_error',
)
_PS_TEXT_FIELDS = {'trackers_detected', 'page_signals_issues', 'page_signals_error'}


def page_signals_defaults():
    return {f: ('' if f in _PS_TEXT_FIELDS else None) for f in PAGE_SIGNAL_FIELDS}


def _reg_domain(url_or_host):
    try:
        ext = tldextract.extract(url_or_host)
        if ext.suffix:
            return f"{ext.domain}.{ext.suffix}".lower()
        return (ext.domain or '').lower()
    except Exception:
        return ''


def _match_tracker(url, reg_domain):
    """Return a friendly tracker name for a resource, or None.
    Prefers an exact registrable-domain match; falls back to a precise host/path needle
    for trackers that live on broad consumer domains."""
    name = TRACKER_DOMAINS.get(reg_domain)
    if name:
        return name
    low = url.lower()
    for needle, nm in TRACKER_HOST_PATH.items():
        if needle in low:
            return nm
    return None


def _is_tracking_cookie(name):
    return name in TRACKING_COOKIE_EXACT or name.startswith(TRACKING_COOKIE_PREFIXES)


def _is_image(content_type, url):
    if content_type and content_type.startswith('image/'):
        return True
    path = urlparse(url).path.lower()
    return path.endswith(_IMAGE_EXTS)


def _to_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _resource_size(r):
    """Bytes for one response. For ranged media (HTTP 206) the Content-Range total
    ('bytes 0-1023/146515') is the real file size; otherwise use Content-Length."""
    n = _to_int(r.get('length'))
    rng = r.get('range') or ''
    if '/' in rng:
        total = rng.rsplit('/', 1)[-1].strip()
        if total.isdigit():
            n = max(n, int(total))
    return n


def parse_network_signals(responses, cookies, consent_present, base_url):
    """Compute page-weight + privacy signals.

    Args:
        responses: list of dicts {url, type (content-type, lowercased), length (content-length)}.
        cookies:   list of cookie dicts (name/domain/...), e.g. from context.cookies().
        consent_present: bool — a consent/cookie banner or CMP was detected.
        base_url:  the site URL (to tell first-party from third-party).
    Returns all PAGE_SIGNAL_FIELDS. Never raises.
    """
    result = page_signals_defaults()
    try:
        site_reg = _reg_domain(base_url)

        # Dedupe by URL — the SAME resource can produce many responses (e.g. a video
        # range-requested as multiple 206 chunks). Keep one entry per URL with its
        # largest known size, so weight isn't multiply-counted.
        by_url = {}
        for r in responses or []:
            url = r.get('url', '') or ''
            # Skip inline/non-network resources — data: and blob: URLs aren't real
            # requests and shouldn't inflate request_count or weight.
            if not url or url[:5].lower() in ('data:', 'blob:'):
                continue
            size = _resource_size(r)
            ctype = (r.get('type') or '').lower()
            if url in by_url:
                prev_ctype, prev_size = by_url[url]
                by_url[url] = (prev_ctype or ctype, max(prev_size, size))
            else:
                by_url[url] = (ctype, size)

        total_bytes = 0
        image_bytes = 0
        image_count = 0
        large_images = 0
        next_gen = False
        third_parties = set()
        trackers = set()
        sized_count = 0          # how many resources reported a usable byte size

        for url, (ctype, n) in by_url.items():
            total_bytes += n
            if n > 0:
                sized_count += 1

            if _is_image(ctype, url):
                image_count += 1
                image_bytes += n
                if n > LARGE_IMAGE_BYTES:
                    large_images += 1
                if 'webp' in ctype or 'avif' in ctype or url.lower().rsplit('?', 1)[0].endswith(('.webp', '.avif')):
                    next_gen = True

            rd = _reg_domain(url)
            if rd and site_reg and rd != site_reg:
                third_parties.add(rd)

            name = _match_tracker(url, rd)
            if name:
                trackers.add(name)

        # cookies (all set on load = pre-consent, since capture never clicks accept)
        total_cookies = len(cookies or [])
        tracking_cookie_names = [(c.get('name') or '') for c in (cookies or [])
                                 if _is_tracking_cookie(c.get('name') or '')]
        tracking_cookies = len(tracking_cookie_names)

        # Page weight is a FLOOR built from Content-Length headers; many responses (gzipped
        # HTML/JS, 204s, cached) report no size. If coverage is poor, don't cite the number
        # as a fact — flag it partial and never emit a "heavy page" claim off it.
        n_resources = len(by_url)
        coverage = (sized_count / n_resources) if n_resources else 0
        weight_partial = n_resources > 0 and (sized_count == 0 or coverage < 0.5)
        if sized_count == 0:
            result['page_weight_kb'] = None
            result['image_weight_kb'] = None
        else:
            result['page_weight_kb'] = round(total_bytes / 1024)
            result['image_weight_kb'] = round(image_bytes / 1024)
        result['page_weight_partial'] = weight_partial if n_resources else None
        result['image_count'] = image_count
        result['large_image_count'] = large_images
        result['uses_next_gen_images'] = next_gen if image_count else None
        result['request_count'] = n_resources  # distinct resources (deduped)
        result['third_party_domains'] = len(third_parties)
        result['trackers_detected'] = ', '.join(sorted(trackers))
        result['tracker_count'] = len(trackers)
        result['cookies_set'] = total_cookies
        result['tracking_cookies'] = tracking_cookies
        result['has_consent_banner'] = bool(consent_present)
        # The signal that MATTERS (and is defensible): a tracking cookie — an identifier —
        # was written to the device BEFORE consent. That's the ePrivacy/GDPR trigger.
        # A tracker request firing on its own is NOT counted: under Google Consent Mode a
        # denied default fires a cookieless ping (e.g. GA page_view) that stores nothing,
        # which is legitimate. `trackers_detected` stays as informational context only.
        result['tracking_before_consent'] = tracking_cookies > 0
        result['page_signals_error'] = ''

        issues = []
        if result['tracking_before_consent']:
            named = ', '.join(sorted(set(tracking_cookie_names))[:6])
            issues.append(f'{tracking_cookies} tracking cookie(s) set before consent: {named}')
        # Only cite weight when coverage is good enough to trust the floor.
        if not weight_partial and result['page_weight_kb'] and result['page_weight_kb'] > HEAVY_PAGE_KB:
            issues.append(f"Heavy page (≥{result['page_weight_kb'] / 1024:.1f} MB transferred)")
        if large_images:
            issues.append(f'{large_images} oversized image(s) (>200 KB)')
        if image_count and not next_gen:
            issues.append('No next-gen image formats (WebP/AVIF)')
        result['page_signals_issues'] = '; '.join(issues)
    except Exception as e:
        result['page_signals_error'] = f'parse: {str(e)[:50]}'
    return result


# JS that detects a consent/cookie banner or CMP on the live page. Used by the capture
# pass: `consent = await page.evaluate(CONSENT_BANNER_JS)`.
CONSENT_BANNER_JS = r"""
() => {
  try {
    if (window.__tcfapi || window.__cmp || window.OneTrust || window.Cookiebot ||
        window.Osano || window.cookieconsent || window.Cookiehub || window.Didomi ||
        window.klaro || window.UC_UI) return true;
    const sel = '[id*="cookie" i],[class*="cookie" i],[id*="consent" i],' +
                '[class*="consent" i],[id*="gdpr" i],[class*="gdpr" i],[aria-label*="cookie" i]';
    const els = document.querySelectorAll(sel);
    for (const el of els) {
      const r = el.getBoundingClientRect();
      if (r.width > 0 && r.height > 0) {
        const t = (el.innerText || '').toLowerCase();
        if (t.includes('cookie') || t.includes('consent') ||
            t.includes('accept') || t.includes('privacy')) return true;
      }
    }
    return false;
  } catch (e) { return false; }
}
"""
