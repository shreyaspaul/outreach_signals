#!/usr/bin/env python3
"""
Page Validity Gate
==================

Runs BEFORE content/design quality scoring and answers two questions
independently, with the right tool for each:

  1. "Is this a real, owned, operating website at all?"  -> INFRASTRUCTURE question.
     Answered by DNS (nameservers) + HTTP redirect signals. Robust, free, and
     invisible to an LLM (the model sees pixels and text, never the nameserver or
     the redirect chain). A live SaaS company never delegates its DNS to a domain
     marketplace, and its homepage does not redirect off-domain.

  2. "Does the content genuinely represent THIS company?"  -> SEMANTIC question.
     Answered by a vision-first LLM that does real reasoning. Generalizes to novel
     non-genuine pages (parked, for-sale, acquired holding, coming-soon, bot-block,
     login wall, content-about-a-different-entity) WITHOUT enumerating text patterns.

If either layer concludes the page is not a genuine, live company site, the gate
ABSTAINS: no score, letter_grade = "INVALID" (a distinct state, NOT an F, excluded
from ranking). The grader is confidently-correct or it abstains — it never
confidently mis-scores.

Design decisions (see specs/grader-v2-implementation.md):
  - NO content-string / "make an offer" / platform-name hard blocks. Those false-
    positive on legitimate SaaS sites that use such phrases as CTAs.
  - NO self-reported-confidence threshold as the gate trigger. LLM confidence is
    miscalibrated. The LLM decides categorically; confidence is recorded only as a
    diagnostic.
  - Thinking is ON for the gate (gemini-2.5-flash default on the legacy SDK), because
    this is a reasoning/classification task where a wrong call is expensive.
"""

import os
import re
import json
import time
from pathlib import Path
from datetime import datetime

import tldextract

# Reuse the rate-limit backoff helper from content_extractor for consistency.
try:
    from content_extractor import _retry_delay_from_error, _is_retryable_error
except Exception:  # pragma: no cover - fallback if imported in isolation
    def _retry_delay_from_error(err_str, attempt):
        m = re.search(r'retry in ([0-9.]+)s', err_str or '')
        if m:
            return float(m.group(1)) + 1.0
        return min((2 ** attempt) * 2.0, 30.0)

    def _is_retryable_error(err_str):
        s = (err_str or '').lower()
        return any(t in s for t in ('429', 'rate', 'quota', '500', '503', '504',
                                    'deadline', 'timeout', 'unavailable', 'internal error'))

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MAX_GATE_RETRIES = 4          # Gemini retries on rate-limit (429)
GATE_CONTENT_MAX_CHARS = 12500  # ~2500 words of context for the gate call
DNS_TIMEOUT = 4.0             # seconds per DNS query; best-effort, never blocks

# Known domain-parking / marketplace nameserver operators. Matched as a substring
# of the resolved NS hostname. These are infrastructure facts, NOT page content —
# a real operating company's DNS is never delegated here.
PARKING_NAMESERVERS = [
    # NOTE: 'domaincontrol.com' (GoDaddy's DEFAULT authoritative DNS) was removed —
    # it is used by millions of fully-operational sites registered at GoDaddy, NOT a
    # parking signal (false-positived magichour.ai, a live 1.9M-visit product). A
    # genuinely parked GoDaddy domain is still caught by PARKING_IPS + the content gate.
    'afternic.com',        # Afternic (GoDaddy group) marketplace
    'sedoparking.com',     # Sedo
    'dan.com',             # Dan.com (GoDaddy)
    'bodis.com',           # Bodis
    'parkingcrew.net',     # ParkingCrew
    'uniregistry.net',     # Uniregistry (GoDaddy)
    'above.com',           # Above.com / Trellian parking
    'atom.com',            # Atom.com (ex-Squadhelp) marketplace -> caught enrich.ly
    'squadhelp.com',
    'hugedomains.com',     # HugeDomains
]

# Known parking A-record IPs (small, high-precision set).
PARKING_IPS = {
    '34.102.136.180',  # GoDaddy Free Parking
    '34.98.99.30',     # GoDaddy Free Parking
}

# Page-state taxonomy. The decision is binary (PASS vs ABSTAIN); the label is a
# diagnostic reason tag. Only LIVE_COMPANY_SITE passes.
LIVE = 'LIVE_COMPANY_SITE'
VALID_STATES = {
    LIVE,
    'PARKED_OR_FOR_SALE',
    'ACQUIRED_REDIRECT',
    'COMING_SOON_PLACEHOLDER',
    'BOT_BLOCKED',
    'ERROR_404_MAINTENANCE',
    'LOGIN_WALL',
    'CONTENT_MISMATCH',
    'INSUFFICIENT_CONTENT',
    'EXTRACTION_FAILED',
}

# Map a page_state to the flag tag stored in flag_reasons.
STATE_FLAG = {
    'PARKED_OR_FOR_SALE': 'invalid_page:parked',
    'ACQUIRED_REDIRECT': 'invalid_page:redirect',
    'COMING_SOON_PLACEHOLDER': 'invalid_page:coming_soon',
    'BOT_BLOCKED': 'invalid_page:bot_blocked',
    'ERROR_404_MAINTENANCE': 'invalid_page:error',
    'LOGIN_WALL': 'invalid_page:login_wall',
    'CONTENT_MISMATCH': 'invalid_page:mismatch',
    'INSUFFICIENT_CONTENT': 'invalid_page:insufficient',
    'EXTRACTION_FAILED': 'grader_error',
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_registrable_domain(url: str) -> str:
    """'www.enrich.ly' -> 'enrich.ly'; 'https://atom.com/name/X' -> 'atom.com'."""
    if not url:
        return ''
    try:
        ext = tldextract.extract(url)
        if ext.domain and ext.suffix:
            return f"{ext.domain}.{ext.suffix}".lower()
        # bare host with no suffix (localhost etc.)
        return (ext.domain or '').lower()
    except Exception:
        return ''


def _result(page_state, *, abstain, source, reason,
            identity_match=None, confidence=None,
            detected_platform=None, redirect_domain=None):
    """Build the standard gate_result dict."""
    return {
        'page_state': page_state,
        'identity_match': identity_match,
        'gate_confidence': confidence,
        'gate_passed': (not abstain),
        'gate_reason': reason,
        'abstain': abstain,
        'detected_platform': detected_platform,
        'redirect_domain': redirect_domain,
        'gate_source': source,
    }


def _check_redirect(input_url: str, final_url: str):
    """ACQUIRED_REDIRECT if the registrable domain changed after redirects.

    Ignores www/subdomain and scheme differences (tldextract handles those).
    Returns a gate_result (abstain) or None.
    """
    if not final_url:
        return None
    in_dom = _get_registrable_domain(input_url)
    fin_dom = _get_registrable_domain(final_url)
    if in_dom and fin_dom and in_dom != fin_dom:
        return _result(
            'ACQUIRED_REDIRECT', abstain=True, source='redirect',
            identity_match=False, confidence=1.0,
            redirect_domain=fin_dom,
            reason=f"Redirects off-domain: {in_dom} -> {fin_dom}. "
                   f"Content would belong to {fin_dom}, not the prospect.",
        )
    return None


def _check_dns_parking(domain: str):
    """PARKED_OR_FOR_SALE if NS/A records belong to a known parking operator.

    Best-effort: any DNS failure returns None (defer to later layers). Never raises.
    """
    reg = _get_registrable_domain(domain) or domain
    if not reg:
        return None
    try:
        import dns.resolver
        resolver = dns.resolver.Resolver()
        resolver.lifetime = DNS_TIMEOUT
        resolver.timeout = DNS_TIMEOUT

        # Nameservers
        try:
            ns_records = [str(r).lower().rstrip('.') for r in resolver.resolve(reg, 'NS')]
        except Exception:
            ns_records = []
        for ns in ns_records:
            for pat in PARKING_NAMESERVERS:
                if pat in ns:
                    return _result(
                        'PARKED_OR_FOR_SALE', abstain=True, source='dns',
                        identity_match=False, confidence=1.0,
                        detected_platform=pat,
                        reason=f"DNS delegated to parking/marketplace operator "
                               f"({ns}). Not a live company site.",
                    )

        # A records
        try:
            a_records = [str(r) for r in resolver.resolve(reg, 'A')]
        except Exception:
            a_records = []
        for ip in a_records:
            if ip in PARKING_IPS:
                return _result(
                    'PARKED_OR_FOR_SALE', abstain=True, source='dns',
                    identity_match=False, confidence=1.0,
                    detected_platform=f'ip:{ip}',
                    reason=f"Resolves to known parking IP {ip}. Not a live company site.",
                )
    except Exception:
        return None
    return None


# ---------------------------------------------------------------------------
# LLM gate (vision-first)
# ---------------------------------------------------------------------------

GATE_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "page_state": {
            "type": "STRING",
            "enum": [
                LIVE,
                "PARKED_OR_FOR_SALE",
                "ACQUIRED_REDIRECT",
                "COMING_SOON_PLACEHOLDER",
                "BOT_BLOCKED",
                "ERROR_404_MAINTENANCE",
                "LOGIN_WALL",
                "CONTENT_MISMATCH",
            ],
        },
        "identity_match": {"type": "BOOLEAN"},
        "confidence": {"type": "NUMBER"},
        "reason": {"type": "STRING"},
        "detected_platform": {"type": "STRING"},
    },
    "required": ["page_state", "identity_match", "confidence", "reason"],
}


def _build_gate_prompt(registrable_domain, company_name, content, title, final_url, word_count):
    company_line = f'COMPANY NAME (from database): {company_name}\n' if company_name else ''
    body = (content or '')[:GATE_CONTENT_MAX_CHARS]
    return f"""You are verifying whether a URL is a GENUINE, LIVE company website that
belongs to the company at this domain. Look at the SCREENSHOT first — a for-sale page,
parking page, "coming soon" placeholder, bot/CAPTCHA challenge, or login wall is usually
visually unmistakable. Then corroborate with the text.

DOMAIN: {registrable_domain}
{company_line}PAGE TITLE: {title or '(none)'}
FINAL URL AFTER REDIRECTS: {final_url or registrable_domain}
WORD COUNT: {word_count}

EXTRACTED TEXT (truncated):
{body}

---

Choose exactly one PAGE STATE:
- LIVE_COMPANY_SITE: a real, live company website with content about its OWN products/services.
- PARKED_OR_FOR_SALE: domain parking or a domain marketplace listing (the page's purpose is to
  sell/advertise the domain, not run a business).
- ACQUIRED_REDIRECT: the content is about an ACQUIRING/different company, not the one at this domain.
- COMING_SOON_PLACEHOLDER: under construction / launching soon / blank placeholder.
- BOT_BLOCKED: Cloudflare challenge, CAPTCHA, "checking your browser", or access denied.
- ERROR_404_MAINTENANCE: 404, page not found, or maintenance/error page.
- LOGIN_WALL: the page is only a login/sign-up form with no company homepage content.
- CONTENT_MISMATCH: real content, but about a COMPLETELY DIFFERENT, UNRELATED business than this
  domain's company (e.g. the domain is a software startup but the page is a personal blog or an
  unrelated local shop).

Be careful and do real reasoning:
- A normal company homepage may legitimately say "pricing", "get a quote", "contact us", or even
  "make an offer" as a CTA. Those words ALONE do NOT make it a parking/for-sale page. Judge the
  PURPOSE of the page, not isolated phrases.
- DEFAULT TO LIVE_COMPANY_SITE. Only use a non-LIVE state when you are clearly confident.

IDENTITY MATCH: Companies VERY OFTEN operate their website under a PRODUCT or BRAND name that
differs from the registered/database company name (e.g. the company "Dror Ortho-Design" ships a
product site branded "Aerodentis"/"ZSmile"; a parent company markets only its product brand).
A different name is NOT a mismatch by itself.
- Set identity_match=true whenever this is a genuine company's OWN product/marketing site — even if
  the exact database name "{company_name}" never appears, as long as the business is plausibly the
  same entity (related product, same industry, owns this domain).
- Set identity_match=false ONLY for a clearly DIFFERENT/UNRELATED entity, a domain marketplace, or a
  page that is not this company's own site at all.
- If unsure, prefer identity_match=true (we would rather grade a real prospect than wrongly drop it).

CONFIDENCE: 0.0-1.0, your honest certainty (diagnostic only).

DETECTED PLATFORM: if parked/for-sale/marketplace, name it (e.g. "atom.com", "sedo.com"); else "".
"""


def _run_llm_gate(url, company_name, content, title, screenshot_path, final_url,
                  word_count, api_key, log_file=None):
    """Single Gemini multimodal call. Returns parsed dict or {'error': ...}.

    Thinking is left ON (legacy SDK default for gemini-2.5-flash) — this is a
    reasoning task. temperature=0 + response_schema for stable, structured output.
    """
    import google.generativeai as genai
    import warnings
    warnings.filterwarnings('ignore', category=FutureWarning)

    if not api_key:
        return {'error': 'Missing GEMINI_API_KEY'}

    reg = _get_registrable_domain(url)
    prompt = _build_gate_prompt(reg, company_name, content, title, final_url, word_count)

    parts = [prompt]
    has_image = bool(screenshot_path and Path(screenshot_path).exists())
    if has_image:
        with open(screenshot_path, 'rb') as f:
            parts.append({'mime_type': 'image/png', 'data': f.read()})

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        'gemini-2.5-flash',
        generation_config=genai.types.GenerationConfig(
            temperature=0.0,
            response_mime_type='application/json',
            response_schema=GATE_RESPONSE_SCHEMA,
        ),
    )

    if log_file:
        try:
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(f"\n{'='*80}\n")
                f.write("PAGE GATE REQUEST\n")
                f.write(f"TIMESTAMP: {datetime.now().isoformat()}\n")
                f.write(f"URL: {url}\n")
                f.write(f"COMPANY: {company_name}\n")
                f.write(f"FINAL URL: {final_url}\n")
                f.write(f"IMAGE: {'yes' if has_image else 'no'}\n")
        except Exception:
            pass

    response_text = None
    for attempt in range(MAX_GATE_RETRIES):
        try:
            response = model.generate_content(parts)
            response_text = response.text.strip()
            break
        except Exception as e:
            err = str(e)
            is_rate = _is_retryable_error(err)
            if is_rate and attempt < MAX_GATE_RETRIES - 1:
                time.sleep(_retry_delay_from_error(err, attempt))
                continue
            if log_file:
                try:
                    with open(log_file, 'a', encoding='utf-8') as f:
                        f.write(f"\n--- GATE ERROR (attempt {attempt + 1}) ---\n{err}\n")
                except Exception:
                    pass
            return {'error': f'Gate LLM error: {err[:80]}'}

    if log_file:
        try:
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(f"\n--- GATE RESPONSE ---\n{response_text}\n--- END ---\n")
        except Exception:
            pass

    # With response_schema the output is clean JSON, but parse defensively.
    try:
        data = json.loads(response_text)
    except Exception:
        m = re.search(r'\{.*\}', response_text or '', re.DOTALL)
        if not m:
            return {'error': 'Gate returned unparseable output'}
        try:
            data = json.loads(m.group())
        except Exception:
            return {'error': 'Gate returned unparseable output'}

    state = data.get('page_state')
    if state not in VALID_STATES:
        state = 'CONTENT_MISMATCH'  # unknown label -> treat as not-live, abstain
    return {
        'page_state': state,
        'identity_match': bool(data.get('identity_match', False)),
        'confidence': data.get('confidence'),
        'reason': (data.get('reason') or '')[:300],
        'detected_platform': (data.get('detected_platform') or '') or None,
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def assess_page_validity(url, company_name, jina_content, jina_title,
                         playwright_final_url, playwright_http_status,
                         screenshot_path, content_word_count,
                         gemini_api_key=None, log_file=None):
    """Run the full page validity gate. Never raises.

    Order (cheap/robust -> semantic):
      1. DNS parking nameservers  (infrastructure, free, LLM-invisible)
      2. Off-domain redirect      (infrastructure, free)
      3. Vision-first LLM gate    (reasoning, generalizes)

    Returns a gate_result dict (see _result). `abstain=True` means: do not score,
    set letter_grade="INVALID".
    """
    gemini_api_key = gemini_api_key or os.getenv('GEMINI_API_KEY')

    try:
        # 1. DNS — highest-precision infrastructure signal.
        dns_hit = _check_dns_parking(url)
        if dns_hit:
            return dns_hit

        # 2. Redirect off-domain — content would belong to a different company.
        redir = _check_redirect(url, playwright_final_url)
        if redir:
            return redir

        # 2b. Hard HTTP errors from the final navigation.
        if playwright_http_status is not None:
            if playwright_http_status in (404, 410):
                return _result('ERROR_404_MAINTENANCE', abstain=True, source='http',
                               identity_match=False, confidence=1.0,
                               reason=f"HTTP {playwright_http_status} on final navigation.")
            if playwright_http_status in (401, 403):
                return _result('BOT_BLOCKED', abstain=True, source='http',
                               identity_match=False, confidence=1.0,
                               reason=f"HTTP {playwright_http_status} (blocked/forbidden).")

        # 3. LLM vision gate — the generalizing semantic judge.
        llm = _run_llm_gate(
            url=url, company_name=company_name,
            content=jina_content, title=jina_title,
            screenshot_path=screenshot_path,
            final_url=playwright_final_url,
            word_count=content_word_count,
            api_key=gemini_api_key, log_file=log_file,
        )
        if llm.get('error'):
            # Gate could not run. Fail SAFE toward grading: a transient LLM/API
            # error should not silently drop a real prospect. Mark the source so
            # it is visible, but do not abstain on infra-clean sites.
            return _result(LIVE, abstain=False, source='llm_error',
                           identity_match=None, confidence=None,
                           reason=f"Gate LLM unavailable ({llm['error']}); "
                                  f"passed by default (infra checks clean).")

        state = llm['page_state']
        identity = llm['identity_match']
        passed = (state == LIVE and identity)
        return _result(
            state, abstain=(not passed), source='llm',
            identity_match=identity, confidence=llm.get('confidence'),
            detected_platform=llm.get('detected_platform'),
            reason=llm.get('reason', ''),
        )
    except Exception as e:
        # Never let the gate crash the pipeline. Fail safe toward grading.
        return _result(LIVE, abstain=False, source='exception',
                       identity_match=None, confidence=None,
                       reason=f"Gate crashed ({str(e)[:80]}); passed by default.")


# ---------------------------------------------------------------------------
# CLI / quick manual test
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Test the page validity gate on a URL.')
    parser.add_argument('url')
    parser.add_argument('--company', default='')
    parser.add_argument('--dns-only', action='store_true',
                        help='Only run the deterministic DNS + registrable-domain checks')
    args = parser.parse_args()

    print(f"registrable domain: {_get_registrable_domain(args.url)}")
    dns_hit = _check_dns_parking(args.url)
    print(f"DNS parking check : {dns_hit['page_state'] + ' / ' + (dns_hit['detected_platform'] or '') if dns_hit else 'clean (no parking NS/IP)'}")
    if dns_hit:
        print(f"  reason: {dns_hit['gate_reason']}")
    if args.dns_only:
        raise SystemExit(0)
