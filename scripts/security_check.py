#!/usr/bin/env python3
"""
Security & SSL signals — objective, deterministic, no browser.

Three checks, all black-and-white facts an outreach email can cite:
  1. Security-header hygiene  → an A-F grade (like Mozilla Observatory), plus exactly
     which headers are missing (HSTS, CSP, X-Frame-Options, …).
  2. SSL/TLS certificate      → valid? days until expiry? TLS version? ("cert expires in 9 days")
  3. Mixed content            → https page loading http:// assets (browser "Not Secure" warnings).

Pure `requests` + stdlib `ssl`/`socket` + BeautifulSoup (html.parser). Never raises.
"""

import re
import socket
import ssl
from datetime import datetime, timezone
from urllib.parse import urlparse
import requests
from requests.adapters import HTTPAdapter
from bs4 import BeautifulSoup

BROWSER_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/124.0 Safari/537.36')
DEFAULT_TIMEOUT = 15
CONNECT_TIMEOUT = 5            # cap the TCP connect leg specifically (read leg gets the rest)
SSL_TIMEOUT = 8                 # tighter — a pathological host shouldn't burn 15s on TLS

# Module-level session with retries DISABLED. By default urllib3 retries the connect
# against EACH resolved A/AAAA record, so a firewalled multi-IP host can stall for
# (timeout x IP count) ~= 45s+. max_retries=0 makes the per-attempt timeout the real
# wall-clock cap; paired with a (connect, read) tuple timeout below.
_SESSION = requests.Session()
_no_retry = HTTPAdapter(max_retries=0)
_SESSION.mount('http://', _no_retry)
_SESSION.mount('https://', _no_retry)
SSL_EXPIRES_SOON_DAYS = 30

# Header -> (points toward the 0-100 score, friendly name for the "missing" list).
# Weights echo the relative security value (HSTS/CSP matter most).
SECURITY_HEADERS = {
    'strict-transport-security': (25, 'HSTS'),
    'content-security-policy':   (25, 'Content-Security-Policy'),
    'x-frame-options':           (15, 'X-Frame-Options'),
    'x-content-type-options':    (15, 'X-Content-Type-Options'),
    'referrer-policy':           (10, 'Referrer-Policy'),
    'permissions-policy':        (10, 'Permissions-Policy'),
}

# Tags whose http:// src/href on an https page = mixed content (active/passive).
_MIXED_CONTENT_TAGS = {
    'script': 'src', 'link': 'href', 'iframe': 'src', 'img': 'src',
    'source': 'src', 'audio': 'src', 'video': 'src', 'embed': 'src', 'object': 'data',
}

SECURITY_FIELDS = (
    'sec_header_score',        # 0-100
    'sec_header_grade',        # A+ .. F
    'has_hsts',
    'has_csp',
    'has_x_frame_options',
    'has_x_content_type_options',
    'has_referrer_policy',
    'has_permissions_policy',
    'sec_headers_missing',     # citable list of missing headers
    'ssl_valid',               # cert chain verifies (not expired/self-signed/mismatch)
    'ssl_days_to_expiry',
    'ssl_expires_soon',        # bool: < 30 days
    'tls_version',             # e.g. TLSv1.3
    'mixed_content',           # bool
    'mixed_content_count',
    'mixed_content_examples',
    'security_issues',         # combined citable summary
    'security_error',
)
_SEC_TEXT_FIELDS = {'sec_header_grade', 'sec_headers_missing', 'tls_version',
                    'mixed_content_examples', 'security_issues', 'security_error'}


def security_defaults():
    return {f: ('' if f in _SEC_TEXT_FIELDS else None) for f in SECURITY_FIELDS}


def _normalize_url(url):
    url = (url or '').strip()
    if not url:
        return ''
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    return url


def _grade_from_score(score):
    if score >= 95:
        return 'A+'
    if score >= 85:
        return 'A'
    if score >= 75:
        return 'B'
    if score >= 65:
        return 'C'
    if score >= 50:
        return 'D'
    return 'F'


def _check_headers(resp, result, issues):
    headers = {k.lower(): v for k, v in resp.headers.items()}
    score = 0
    missing = []
    flag_map = {
        'strict-transport-security': 'has_hsts',
        'content-security-policy': 'has_csp',
        'x-frame-options': 'has_x_frame_options',
        'x-content-type-options': 'has_x_content_type_options',
        'referrer-policy': 'has_referrer_policy',
        'permissions-policy': 'has_permissions_policy',
    }
    for hdr, (pts, friendly) in SECURITY_HEADERS.items():
        present = hdr in headers and bool((headers[hdr] or '').strip())
        result[flag_map[hdr]] = present
        if present:
            score += pts
        else:
            missing.append(friendly)
    result['sec_header_score'] = score
    result['sec_header_grade'] = _grade_from_score(score)
    result['sec_headers_missing'] = ', '.join(missing)
    if missing:
        issues.append('Missing security headers: ' + ', '.join(missing))


def _classify_ssl_error(err_msg, result, issues):
    """Turn a TLS verification error string into a specific, citable fact —
    no extra library needed (the handshake error itself tells us what's wrong)."""
    msg = (err_msg or '').lower()
    self_signed = 'self-signed' in msg or 'self signed' in msg
    if 'expired' in msg:
        issues.append('SSL certificate has EXPIRED')
        result['ssl_expires_soon'] = True   # expired = maximally urgent
        result['ssl_days_to_expiry'] = None  # exact day count not readable on a bad cert
    elif 'unable to get local issuer' in msg or 'unable to get issuer' in msg or (self_signed and 'chain' in msg):
        # untrusted root / private CA — the chain can't be built to a trusted authority
        # (openssl: "self-signed certificate in certificate chain" / "unable to get local issuer").
        issues.append('SSL certificate is not issued by a trusted authority (chain does not validate)')
    elif self_signed:
        issues.append('SSL certificate is self-signed (browsers will not trust it)')
    elif "doesn't match" in msg or 'hostname mismatch' in msg or 'host name' in msg or 'match either' in msg:
        issues.append('SSL certificate does not match the domain name')
    else:
        issues.append('SSL certificate does not validate')


def _check_ssl(host, result, issues, known_valid, ssl_error_msg):
    """Read cert details (expiry for valid certs + TLS version) via ONE socket.

    `known_valid` comes from whether the verified HTTPS page fetch already succeeded:
      True  -> verified handshake worked; read the cert dict (has the expiry date).
      False -> the fetch hit a cert error; we already know it's invalid, so just read
               the TLS version over an unverified socket and classify the error string.
      None  -> unknown (e.g. fetch failed for a non-cert reason); try a verified read.
    """
    if not host:
        return

    if known_valid is False:
        # Invalid cert: we can't get the parsed cert dict, but we can still get the
        # TLS version and classify WHY it's invalid from the fetch error message.
        result['ssl_valid'] = False
        _classify_ssl_error(ssl_error_msg, result, issues)
        try:
            uctx = ssl._create_unverified_context()
            with socket.create_connection((host, 443), timeout=SSL_TIMEOUT) as sock:
                with uctx.wrap_socket(sock, server_hostname=host) as ssock:
                    result['tls_version'] = ssock.version()
        except Exception:
            pass
        return

    # known_valid True or None -> attempt a verified read to get the cert dict.
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, 443), timeout=SSL_TIMEOUT) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                cert = ssock.getpeercert()
                result['ssl_valid'] = True
                result['tls_version'] = ssock.version()
                if ssock.version() in ('TLSv1', 'TLSv1.1', 'SSLv3'):
                    issues.append(f'Outdated TLS version ({ssock.version()})')
                if cert and cert.get('notAfter'):
                    try:
                        expires = datetime.strptime(
                            cert['notAfter'], '%b %d %H:%M:%S %Y %Z').replace(tzinfo=timezone.utc)
                        days = (expires - datetime.now(timezone.utc)).days
                        result['ssl_days_to_expiry'] = days
                        result['ssl_expires_soon'] = days < SSL_EXPIRES_SOON_DAYS
                        if days < 0:
                            issues.append('SSL certificate has EXPIRED')
                        elif days < SSL_EXPIRES_SOON_DAYS:
                            issues.append(f'SSL certificate expires in {days} days')
                    except (ValueError, KeyError):
                        pass
    except ssl.SSLCertVerificationError as e:
        result['ssl_valid'] = False
        _classify_ssl_error(str(e), result, issues)
    except (socket.timeout, socket.gaierror, ConnectionRefusedError, OSError, ssl.SSLError):
        # couldn't establish TLS at all — leave ssl_* as None (not measured)
        pass


def _check_mixed_content(resp, final_url, result, issues):
    """Only meaningful on an https page. Finds http:// asset references in the HTML."""
    if not final_url.startswith('https://'):
        result['mixed_content'] = None  # not applicable on an http page
        return
    try:
        soup = BeautifulSoup(resp.text or '', 'html.parser')
    except Exception:
        return
    # Dedupe by URL: the SAME asset can appear as a tag attr AND in a CSS url(), so
    # count distinct insecure URLs, not raw reference occurrences.
    seen = set()

    def _add(u):
        u = (u or '').strip()
        if u.lower().startswith('http://'):
            seen.add(u)

    for tag_name, attr in _MIXED_CONTENT_TAGS.items():
        for tag in soup.find_all(tag_name):
            _add(tag.get(attr))
            # responsive images: srcset can carry multiple http:// candidates
            for m in re.findall(r'http://[^\s,]+', (tag.get('srcset') or ''), flags=re.I):
                _add(m)
    # CSS backgrounds: url(http://...) in <style> blocks and inline style attrs
    for m in re.findall(r'url\(\s*[\'\"]?(http://[^\)\'\"]+)', resp.text or '', flags=re.I):
        _add(m)

    count = len(seen)
    examples = [u[:120] for u in list(seen)[:5]]
    result['mixed_content'] = count > 0
    result['mixed_content_count'] = count
    result['mixed_content_examples'] = '; '.join(examples)
    if count:
        issues.append(f'{count} insecure (http://) asset(s) on an HTTPS page (browser security warnings)')


def assess_security(url, timeout=DEFAULT_TIMEOUT):
    """Run header + SSL + mixed-content checks. Returns all SECURITY_FIELDS. Never raises."""
    result = security_defaults()
    url = _normalize_url(url)
    if not url:
        result['security_error'] = 'Empty URL'
        return result
    issues = []

    # One verified GET serves headers + mixed-content, AND tells us if the cert is valid
    # (requests verifies the TLS chain by default; an SSLError = a real cert problem).
    final_url = url
    known_valid = None          # True / False (cert error) / None (no/other error)
    ssl_error_msg = ''
    try:
        resp = _SESSION.get(url, headers={'User-Agent': BROWSER_UA},
                            timeout=(CONNECT_TIMEOUT, timeout), allow_redirects=True)
        final_url = resp.url or url
        # Headers are real on ANY status (403 challenge pages still carry HSTS/CSP/...).
        _check_headers(resp, result, issues)
        # Mixed content only makes sense on a real HTML body.
        if resp.status_code < 400:
            _check_mixed_content(resp, final_url, result, issues)
        else:
            result['security_error'] = f'HTTP {resp.status_code}'
        known_valid = True if final_url.startswith('https://') else None
    except requests.exceptions.SSLError as e:
        known_valid = False     # the verified handshake failed => cert is invalid
        ssl_error_msg = str(e)
        result['security_error'] = f'SSL: {str(e)[:50]}'
    except requests.exceptions.RequestException as e:
        result['security_error'] = f'fetch: {str(e)[:50]}'

    # SSL cert details: probe the FINAL (post-redirect) host, and only if it's HTTPS.
    ssl_host = urlparse(final_url).netloc.split(':')[0] if final_url.startswith('https://') else ''
    if ssl_host:
        _check_ssl(ssl_host, result, issues, known_valid, ssl_error_msg)

    result['security_issues'] = '; '.join(issues)
    return result


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Security & SSL signals for a URL')
    parser.add_argument('url')
    args = parser.parse_args()
    r = assess_security(args.url)
    print(f"\nSecurity & SSL — {args.url}")
    print("=" * 60)
    if r['security_error']:
        print("  ERROR:", r['security_error'])
    print(f"  Header grade: {r['sec_header_grade']} ({r['sec_header_score']}/100)")
    print(f"    HSTS {r['has_hsts']} | CSP {r['has_csp']} | X-Frame {r['has_x_frame_options']} "
          f"| X-CTO {r['has_x_content_type_options']} | Referrer {r['has_referrer_policy']} "
          f"| Permissions {r['has_permissions_policy']}")
    print(f"    Missing: {r['sec_headers_missing'] or '(none)'}")
    print(f"  SSL: valid={r['ssl_valid']} | expires in {r['ssl_days_to_expiry']} days "
          f"(soon={r['ssl_expires_soon']}) | {r['tls_version']}")
    print(f"  Mixed content: {r['mixed_content']} ({r['mixed_content_count']})")
    if r['mixed_content_examples']:
        print(f"    e.g. {r['mixed_content_examples'][:120]}")
    print(f"\n  Issues: {r['security_issues'] or '(none)'}")
