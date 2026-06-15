# SIGNALS — what the tool scans on every site

A living catalog of every signal the enrichment pipeline collects per website. Use this to
know, at a glance, *everything that's happening* on a scan. Grouped by category. "Type" tells you
how trustworthy a signal is:

- **objective** = black-and-white fact, stable across runs (the good outreach hooks).
- **lab** = one synthetic measurement; steady but can drift a few points run-to-run.
- **field** = real-user data (Google CrUX); stable, and what Google actually ranks on.
- **parked** = subjective content/design grading — still produced, accuracy work paused (see
  `specs/grader-v2-implementation.md`).

Last updated: 2026-06-15.

---

## 1. Tech & marketing stack  ·  `scripts/wordpress_detector.py`  ·  *objective*

| Signal | Column(s) | What it checks |
|---|---|---|
| Primary tech | `tech_stack`, `all_tech_detected` | CMS/framework: WordPress, Webflow, Wix, Shopify, React, Next.js, … |
| WordPress flag | `is_wordpress` | True if the site runs WordPress (core migration target) |
| Marketing tools | `marketing_tools` | Analytics/marketing: GA, Segment, Amplitude, Mixpanel, HubSpot, … |
| Ad pixels | `ad_pixels` | Google/Facebook/LinkedIn ad pixels present |
| Premium analytics | `has_premium_analytics` | Uses Segment/Amplitude/Mixpanel etc. (Signal 3) |

## 2. Performance — LAB (one synthetic test)  ·  `scripts/pagespeed_checker.py`  ·  *lab*

| Signal | Column(s) | What it checks |
|---|---|---|
| Performance score | `pagespeed_mobile`, `pagespeed_desktop` | Lighthouse speed score 0-100 |
| Lab Core Web Vitals | `mobile_lcp_s`/`mobile_fcp_s`/`mobile_cls` (+ desktop) | LCP/FCP (seconds), CLS (unitless) from the synthetic test |

## 3. Performance — FIELD / real users (Google CrUX)  ·  `pagespeed_checker.py`  ·  *field*

The truth — what real visitors experience, and Google's actual ranking input. Captured for **mobile
and desktop** separately (`*_desktop` columns).

| Signal | Column(s) | What it checks |
|---|---|---|
| CWV pass/fail | `cwv_pass`, `cwv_pass_desktop` | Real users pass Core Web Vitals? (True / False / blank = no field data) |
| Field LCP | `field_lcp_s` (+ `_desktop`), `field_lcp_rating` | Real-user Largest Contentful Paint, p75 (seconds) |
| Field INP | `field_inp_ms` (+ `_desktop`), `field_inp_rating` | Real-user Interaction to Next Paint, p75 (ms) — field-only |
| Field CLS | `field_cls` (+ `_desktop`), `field_cls_rating` | Real-user layout shift, p75 (unitless) |
| Field FCP / TTFB | `field_fcp_s`, `field_ttfb_ms` (+ `_desktop`, + ratings) | First paint / server response time, p75 |
| Data source | `crux_source` (+ `_desktop`) | page / origin / blank (whether real-user data exists) |

## 4. SEO / Accessibility / Best-practices (Lighthouse extras)  ·  `pagespeed_checker.py`  ·  *lab*

Free from the same PageSpeed call. **Cite the `*_issues` lists in outreach, not the rollup score**
(the issues are stable binary facts; the rollup drifts).

| Signal | Column(s) | What it checks |
|---|---|---|
| SEO | `seo_score`, `seo_issues` | Technical SEO setup + the specific audits failed |
| Accessibility | `accessibility_score`, `accessibility_issues` | WCAG-related issues (contrast, labels, alt text) — legal-risk hook |
| Best practices | `best_practices_score`, `best_practices_issues` | Security/console/deprecation issues |

## 4b. Accessibility — deep WCAG scan (axe-core)  ·  `scripts/accessibility.py`  ·  *objective*

Runs Deque's **axe-core** (the engine ADA lawsuits are based on) inside the existing capture
browser pass. The ADA/legal-risk hook. Reports **factual counts + the specific violations** — no
invented score (the Lighthouse `accessibility_score` is the rollup if a number is wanted).

| Signal | Column(s) | What it checks |
|---|---|---|
| Violations | `a11y_violation_count`, `a11y_node_count` | Distinct WCAG rules failed + total failing elements |
| By severity | `a11y_critical` / `a11y_serious` / `a11y_moderate` / `a11y_minor` | Rule counts per impact level |
| Lawsuit risk | `a11y_lawsuit_risk` | A violation in a commonly-litigated rule (alt text, form labels, contrast, link/button names) |
| Specific issues | `a11y_top_issues` | Citable facts, e.g. "Images must have alternate text (12 elements)" |
| WCAG criteria | `a11y_wcag_tags` | e.g. wcag111, wcag143 |
| Scan status | `a11y_error` | Set if the scan couldn't run (e.g. strict CSP blocked it) |

**Honesty caveats (read before citing in outreach):**
- **Homepage-only.** axe scans the one captured page. Say "your homepage," never "your site."
- **Conservative floor.** Counts exclude axe's `incomplete`/undecidable checks, and automated scans
  catch only ~30-40% of WCAG criteria — the real number is higher, never lower.
- **Not-measured ≠ clean.** A non-empty `a11y_error` or null counts means the scan didn't run (often
  a strict Content-Security-Policy blocking script injection) — NOT that the site is accessible. Only
  trust a row where `a11y_error` is empty AND `a11y_violation_count` is not null.

## 5. Traffic  ·  `scripts/traffic_checker.py` / from input CSV  ·  *objective*

| Signal | Column(s) | What it checks |
|---|---|---|
| Volume | `monthly_visits`, `global_rank` | Monthly visitors + global rank (SimilarWeb / CSV) |
| Engagement | `bounce_rate`, `pages_per_visit` | Visitor engagement |
| Sources / geo | `traffic_source_*`, `top_country` | Direct/search/social split, top country |
| Signal 2 flag | `is_signal_2_traffic` | True if 50K+ monthly visits |

## 6. AI-Readiness — can bots & AI find/parse the site?  ·  `scripts/ai_readiness.py`  ·  *objective*

Consolidated `ai_readiness_score` (0-100) + `ai_readiness_partial` flag + `ai_readiness_issues`
(citable problems). Every sub-check is its own column.

| Sub-check | Column(s) | What it checks |
|---|---|---|
| **SSR ratio** (server vs client render) | `ssr_content_ratio`, `ssr_raw_words`, `ssr_rendered_words`, `ssr_client_rendered` | Words in raw HTML (what a non-JS crawler sees) ÷ words after JS. Low = content needs JavaScript → invisible to most AI crawlers |
| robots.txt AI policy | `robots_blocks_ai`, `robots_ai_blocked_list`, `robots_found`, `robots_has_sitemap` | Does robots.txt block GPTBot/ClaudeBot/PerplexityBot/Google-Extended/CCBot/Bytespider/… |
| llms.txt | `has_llms_txt` | Presence of the emerging AI-readable site-summary file |
| Structured data | `has_schema_org`, `jsonld_count`, `jsonld_types` | Schema.org JSON-LD blocks + types (Organization/Product/FAQ…) — how AI extracts facts |
| Sitemap | `has_sitemap`, `sitemap_url_count` | sitemap.xml present (direct or via robots) + URL count |
| Semantic / meta | `has_title`+`title_text`, `has_meta_description`+`meta_description_text`, `has_og_tags`, `h1_count` | Title, meta description, OpenGraph, single `<h1>` — basic parseability |

## 6c. Page weight + privacy (network-pass)  ·  `scripts/page_signals.py`  ·  *objective*

Derived from the resources the page loads, captured during the existing browser pass.

| Signal | Column(s) | What it checks |
|---|---|---|
| Page weight | `page_weight_kb`, `page_weight_partial`, `image_weight_kb`, `image_count`, `large_image_count`, `uses_next_gen_images`, `request_count` | Transferred bytes + image bloat (WordPress's weakness; migration fixes it). Weight is a Content-Length **floor** (undercounts gzipped/cached); `page_weight_partial=True` → too few sizes seen to cite |
| 3rd-party surface | `third_party_domains` | Distinct off-site domains called (tag/privacy/perf surface) |
| Trackers (context) | `trackers_detected`, `tracker_count` | Named trackers (GA/Meta Pixel/…) firing on load — *informational* (their marketing stack); a cookieless ping is not a consent issue |
| Cookies before consent | `cookies_set`, `tracking_cookies` | Cookies set on load (capture never clicks "accept" → all pre-consent) |
| Consent | `has_consent_banner`, `tracking_before_consent` | Banner present? + the signal that matters: a **tracking cookie (identifier) was set before consent** — the ePrivacy/GDPR trigger. Cookieless Consent-Mode pings are excluded |
| Summary | `page_signals_issues` | Combined citable list |

## 6b. Security & SSL  ·  `scripts/security_check.py`  ·  *objective*

Pure HTTP + TLS inspection (no browser). All deterministic facts.

| Signal | Column(s) | What it checks |
|---|---|---|
| Header grade | `sec_header_grade` (A+–F), `sec_header_score`, `sec_headers_missing` + per-header bools (`has_hsts`/`has_csp`/…) | Security headers present vs missing (Observatory-style) |
| SSL cert | `ssl_valid`, `ssl_days_to_expiry`, `ssl_expires_soon`, `tls_version` | Cert validates? days to expiry? TLS version (old = outdated) |
| Mixed content | `mixed_content`, `mixed_content_count`, `mixed_content_examples` | HTTPS page loading insecure http:// assets (browser "Not Secure"). None = page isn't HTTPS |
| Summary | `security_issues` | Combined citable list |

## 7. Page validity gate — is it a real, gradeable site?  ·  `scripts/page_gate.py`  ·  *objective*

| Signal | Column(s) | What it checks |
|---|---|---|
| Status | `page_state`, `gate_reason`, `gate_source` | LIVE_COMPANY_SITE vs parked / blank / bot-blocked / redirected / mismatch |
| Platform | `detected_platform` | Parking/marketplace platform if detected (atom.com, etc.) |
| Error page | `is_error_page`, `error_type` | 404 / maintenance / coming-soon / access-denied / empty |

## 8. Content & design grading  ·  `scripts/website_grader.py` + `content_extractor.py`  ·  *parked*

Still produced, but accuracy work is paused (subjective). Use with caution.

| Signal | Column(s) | What it checks |
|---|---|---|
| Content score | `content_score` = `programmatic_score` + `llm_score`; `clarity`/`substance`/`credibility`/`persuasiveness`/`depth`; `content_*` | Content quality (programmatic checklist + LLM ratings) |
| Design score | `design_score` + `design_typography/spacing/color/hierarchy/polish`; `design_comment`, `design_reasoning` | Visual design via Gemini Vision on a screenshot |
| Overall grade | `total_grade_score`, `letter_grade`, `grade_analysis`, `weak_areas`, `strong_areas` | 30% speed + 40% content + 30% design; A+…F or INVALID |

## 9. Data quality  ·  `scripts/orchestrator.py` (`flag_entry`)  ·  *meta*

| Signal | Column(s) | What it checks |
|---|---|---|
| Flags | `flag_count`, `flag_reasons` | Anomalies: error pages, missing data, zero/perfect scores, invalid page, API errors |
| Errors | `enrichment_errors` | Combined per-step errors |

---

## Roadmap — signals not yet built

See `specs/grader-v2-implementation.md` for the full plan. Status as of 2026-06-15:

| Phase | Signals | Status |
|---|---|---|
| 1 | Lighthouse SEO/A11y/BP + CrUX field data (mobile + desktop) | ✅ done |
| 2 | AI-Readiness (SSR ratio, robots/llms.txt, JSON-LD, sitemap, semantic) | ✅ done |
| 3 | Security / SSL: cert validity + expiry, TLS version, HSTS/CSP/headers, mixed content | ⬜ planned |
| 4 | Core Web Vitals pass/fail badges + mobile-friendliness (viewport/responsive/tap targets) | ⬜ planned |
| 5 | Technical staleness: stale copyright year, broken links, unoptimized images, favicon | ⬜ planned |
| 6a | **axe-core accessibility** (deep WCAG scan, legal hook) — see section 4b | ✅ done |
| 6b | **Security & SSL** (header grade, cert expiry, TLS, mixed content) — see section 6b | ✅ done |
| 6c | **Network-pass**: cookies-before-consent (GDPR), page weight, image bloat — see section 6c | ✅ done |
| 6d | DOM-pass: form friction, trust-signal/schema gaps | ⬜ planned |
| — | CMS CVEs **dropped** (not worth paid WPScan); Speed→$ **dropped** (not credibly computable per company) | ✂️ |
