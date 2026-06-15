#!/usr/bin/env python3
"""
Unit tests for the deterministic layers of the page validity gate.

These cover the parts that must be bulletproof and need no LLM/API key:
  - registrable-domain parsing
  - off-domain redirect detection (with www/scheme normalization)
  - HTTP-status short-circuits in assess_page_validity
  - DNS parking detection (network; the canonical enrich.ly -> atom.com case)

Run:  PYTHONPATH=scripts python scripts/test_page_gate.py
Exits non-zero on first failure.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import page_gate as pg

passed = 0


def check(name, cond):
    global passed
    if cond:
        passed += 1
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}")
        sys.exit(1)


print("registrable domain")
check("www stripped", pg._get_registrable_domain("www.enrich.ly") == "enrich.ly")
check("path ignored", pg._get_registrable_domain("https://atom.com/name/Enrich.ly") == "atom.com")
check("scheme + case", pg._get_registrable_domain("http://www.Stripe.com/payments") == "stripe.com")
check("subdomain stripped", pg._get_registrable_domain("https://app.veezoo.com") == "veezoo.com")

print("redirect detection")
check("www vs non-www is NOT a redirect",
      pg._check_redirect("http://company.com", "https://www.company.com/en") is None)
check("same domain different path is NOT a redirect",
      pg._check_redirect("https://x.com", "https://x.com/home") is None)
r = pg._check_redirect("company.com", "https://acquirer.com/company")
check("off-domain IS a redirect", r is not None and r["page_state"] == "ACQUIRED_REDIRECT")
check("redirect records target domain", r and r["redirect_domain"] == "acquirer.com")
check("redirect abstains", r and r["abstain"] is True)
check("empty final_url -> no redirect", pg._check_redirect("company.com", "") is None)

print("HTTP status short-circuits (no API key needed; DNS clean domain)")
# example.com has no parking NS, so assess_page_validity reaches the HTTP-status check.
r404 = pg.assess_page_validity(
    url="https://example.com", company_name="Example",
    jina_content="", jina_title="", playwright_final_url="https://example.com",
    playwright_http_status=404, screenshot_path="", content_word_count=0,
    gemini_api_key="DUMMY")
check("404 -> abstain ERROR_404_MAINTENANCE",
      r404["abstain"] and r404["page_state"] == "ERROR_404_MAINTENANCE")
r403 = pg.assess_page_validity(
    url="https://example.com", company_name="Example",
    jina_content="", jina_title="", playwright_final_url="https://example.com",
    playwright_http_status=403, screenshot_path="", content_word_count=0,
    gemini_api_key="DUMMY")
check("403 -> abstain BOT_BLOCKED",
      r403["abstain"] and r403["page_state"] == "BOT_BLOCKED")

print("DNS parking (network)")
dns_hit = pg._check_dns_parking("www.enrich.ly")
check("enrich.ly NS -> PARKED_OR_FOR_SALE",
      dns_hit is not None and dns_hit["page_state"] == "PARKED_OR_FOR_SALE")
check("enrich.ly detected_platform is atom.com",
      dns_hit and dns_hit["detected_platform"] == "atom.com")
check("stripe.com NS -> clean", pg._check_dns_parking("stripe.com") is None)

# enrich.ly should also abstain via assess_page_validity at the DNS layer, with a
# dummy API key, because DNS fires before any LLM call.
r_enrich = pg.assess_page_validity(
    url="https://www.enrich.ly", company_name="Enrich.ly",
    jina_content="", jina_title="", playwright_final_url="https://www.enrich.ly",
    playwright_http_status=200, screenshot_path="", content_word_count=0,
    gemini_api_key="DUMMY")
check("enrich.ly abstains at DNS layer (no LLM needed)",
      r_enrich["abstain"] and r_enrich["gate_source"] == "dns")

print(f"\nAll {passed} checks passed.")
