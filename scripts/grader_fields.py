#!/usr/bin/env python3
"""
Friendly CSV field names + a human-readable description header row.

WHY THIS EXISTS
---------------
The code uses terse internal column names (letter_grade, programmatic_score,
llm_score, clarity, ...). Those are confusing to read in a spreadsheet. Rather than
rename them everywhere in the code (risky, touches all the scoring/flagging logic),
we translate ONLY at the CSV boundary:

  - on WRITE: rename internal -> friendly, and insert a second row of plain-English
    descriptions right under the header.
  - on READ:  drop that description row, rename friendly -> internal, and re-coerce
    numbers (the text description row forces object dtypes on read).

So the file you open is self-explanatory; the code keeps working unchanged.

A generated CSV looks like:

    overall_grade, overall_score, speed_score, content_score, ...
    "A+..F; INVALID=not a real page", "0-100 overall", "site speed 0-100", ...   <- description row
    A-, 88, 47, 81, ...                                                          <- data
    C,  64, 50, 74, ...
"""

import pandas as pd

# internal_name -> (friendly_name, description)
FIELD_MAP = {
    # ---- THE HEADLINE VERDICTS ----
    'letter_grade':       ('overall_grade',  'FINAL grade A+ to F. INVALID = not a real/usable page (parked/blank/blocked).'),
    'total_grade_score':  ('overall_score',  'FINAL overall 0-100 = 30% speed + 40% content + 30% design.'),
    'performance_score':  ('speed_score',    'FINAL speed verdict 0-100 (mobile PageSpeed). Higher = faster.'),
    'content_score':      ('content_score',  'FINAL content verdict 0-100 = elements (0-30) + AI quality (0-70).'),
    'design_score':       ('design_score',   'FINAL design verdict 0-100 = sum of the 5 design_* parts below.'),

    # ---- CONTENT BREAKDOWN ----
    'programmatic_score': ('content_elements_score', 'Auto-checklist 0-30: enough text + has pricing/testimonials/case-studies/numbers/CTA.'),
    'llm_score':          ('content_quality_score',  "AI's content quality 0-70 (scaled from the 5 ratings below)."),
    'clarity':            ('content_clarity',        '1-10: can a visitor instantly tell what the company does?'),
    'substance':          ('content_substance',      '1-10: real information vs empty marketing fluff.'),
    'credibility':        ('content_credibility',    '1-10: trust/proof (named customers, real results).'),
    'persuasiveness':     ('content_persuasiveness', '1-10: compelling reason to take action.'),
    'depth':              ('content_depth',          '1-10: thorough enough for a buyer to evaluate.'),
    'content_analysis':   ('content_summary',        "AI's one-sentence summary of the content."),
    'content_reasoning':  ('content_reasoning',      'Per-dimension EVIDENCE and justification behind each content score.'),
    'content_source':     ('content_source',        'Which extractor was scored: jina (HTTP) or playwright (real browser, JS-rendered).'),
    'content_word_count': ('content_word_count',     'Number of words of text scored (from the chosen source).'),
    'proud_facts':        ('proud_facts',           'Specific quotable facts the company is proud of (community size, customers, funding, etc.), verified present in their content. Joined by " | ".'),
    'proud_facts_detail': ('proud_facts_detail',    'JSON of the quotable facts with type + the exact source evidence for each.'),

    # ---- DESIGN BREAKDOWN (each 0-20) ----
    'design_typography':  ('design_typography',  '0-20: fonts, size hierarchy, readability.'),
    'design_spacing':     ('design_spacing',     '0-20: white space, alignment, layout grid.'),
    'design_color':       ('design_color',       '0-20: palette, contrast, brand coherence.'),
    'design_hierarchy':   ('design_hierarchy',   '0-20: eye flow, CTA prominence, information priority.'),
    'design_polish':      ('design_polish',      '0-20: overall finish and attention to detail.'),
    'design_comment':     ('design_summary',     "AI's one-sentence summary of the design."),
    'design_reasoning':   ('design_reasoning',   'Observations + per-dimension EVIDENCE and justification behind each design score.'),
    'design_score_runs':  ('design_score_runs',  'Diagnostic: the 2 ensemble runs (e.g. "66,68").'),
    'design_score_spread':('design_score_spread','Diagnostic: gap between the 2 runs; large gap = AI unsure.'),

    # ---- OVERALL EXPLANATION ----
    'grade_analysis':     ('grade_summary',  'Plain-language strengths/weaknesses.'),
    'weak_areas':         ('weak_areas',     'Categories scoring below threshold.'),
    'strong_areas':       ('strong_areas',   'Categories scoring above threshold.'),

    # ---- IS IT EVEN A REAL SITE? (the gate) ----
    'page_state':         ('site_status',          'LIVE_COMPANY_SITE = gradeable. Else parked/blank/blocked/redirect/mismatch.'),
    'gate_reason':        ('site_status_reason',   'Why the site got this status.'),
    'gate_confidence':    ('site_status_confidence','Diagnostic: AI confidence in the status (0-1).'),
    'gate_source':        ('site_status_source',   'Which check decided: dns / redirect / http / screenshot / llm.'),
    'detected_platform':  ('detected_platform',    'Parking/marketplace platform if detected (e.g. atom.com).'),

    # ---- LAB CORE WEB VITALS (one synthetic test; compare against field_* below) ----
    'mobile_fcp':  ('mobile_fcp_s',  'LAB FCP (seconds), one synthetic mobile test. Compare vs field_fcp_s (real users).'),
    'mobile_lcp':  ('mobile_lcp_s',  'LAB LCP (seconds), one synthetic mobile test. Compare vs field_lcp_s (real users).'),
    'mobile_cls':  ('mobile_cls',    'LAB CLS (unitless), one synthetic mobile test. Compare vs field_cls (real users).'),
    'desktop_fcp': ('desktop_fcp_s', 'LAB desktop FCP (seconds), one synthetic test.'),
    'desktop_lcp': ('desktop_lcp_s', 'LAB desktop LCP (seconds), one synthetic test.'),
    'desktop_cls': ('desktop_cls',   'LAB desktop CLS (unitless), one synthetic test.'),

    # ---- LIGHTHOUSE EXTRA CATEGORIES (free, from the PageSpeed call) ----
    'seo_score':              ('seo_score',           'Lighthouse SEO score 0-100 (lab).'),
    'accessibility_score':    ('accessibility_score', 'Lighthouse Accessibility score 0-100. Low = ADA/WCAG legal-risk signal.'),
    'best_practices_score':   ('best_practices_score','Lighthouse Best-Practices score 0-100 (security/console/deprecations).'),
    'seo_issues':             ('seo_issues',          'Specific SEO audits the page FAILED — citable facts behind the SEO score.'),
    'accessibility_issues':   ('accessibility_issues','Specific accessibility audits FAILED — citable WCAG-related facts.'),
    'best_practices_issues':  ('best_practices_issues','Specific best-practices audits FAILED — citable facts.'),

    # ---- CORE WEB VITALS: REAL-USER FIELD DATA (CrUX = Google ranking input) ----
    # MOBILE real-user field data (primary — mobile-first indexing + main traffic).
    'crux_source':            ('crux_source',     'MOBILE field-data source: page (this URL) / origin (whole domain) / empty (no real-user data).'),
    'cwv_pass':               ('cwv_pass',        'MOBILE Core Web Vitals assessment from REAL users (LCP+INP+CLS all good). True/False/empty.'),
    'field_lcp':              ('field_lcp_s',     'MOBILE real-user LCP at p75 (seconds). Good <=2.5, poor >4. Compare vs lab mobile_lcp_s.'),
    'field_lcp_rating':       ('field_lcp_rating','good / needs-improvement / poor for mobile real-user LCP.'),
    'field_inp':              ('field_inp_ms',    'MOBILE real-user INP at p75 (ms). Good <=200, poor >500. (No lab equivalent — field only.)'),
    'field_inp_rating':       ('field_inp_rating','good / needs-improvement / poor for mobile real-user INP.'),
    'field_cls':              ('field_cls',       'MOBILE real-user CLS at p75 (unitless). Good <=0.10, poor >0.25. Compare vs lab mobile_cls.'),
    'field_cls_rating':       ('field_cls_rating','good / needs-improvement / poor for mobile real-user CLS.'),
    'field_fcp':              ('field_fcp_s',     'MOBILE real-user FCP at p75 (seconds). Good <=1.8, poor >3. Compare vs lab mobile_fcp_s.'),
    'field_fcp_rating':       ('field_fcp_rating','good / needs-improvement / poor for mobile real-user FCP.'),
    'field_ttfb':             ('field_ttfb_ms',   'MOBILE real-user TTFB at p75 (ms). Good <=800, poor >1800. (No lab equivalent — field only.)'),
    'field_ttfb_rating':      ('field_ttfb_rating','good / needs-improvement / poor for mobile real-user TTFB.'),

    # DESKTOP real-user field data (parallel; desktop CWV drives desktop-search ranking).
    'crux_source_desktop':       ('crux_source_desktop',     'DESKTOP field-data source: page / origin / empty.'),
    'cwv_pass_desktop':          ('cwv_pass_desktop',        'DESKTOP Core Web Vitals assessment from REAL users. True/False/empty.'),
    'field_lcp_desktop':         ('field_lcp_desktop_s',     'DESKTOP real-user LCP at p75 (seconds). Compare vs field_lcp_s (mobile).'),
    'field_lcp_rating_desktop':  ('field_lcp_rating_desktop','good / needs-improvement / poor for desktop real-user LCP.'),
    'field_inp_desktop':         ('field_inp_desktop_ms',    'DESKTOP real-user INP at p75 (ms).'),
    'field_inp_rating_desktop':  ('field_inp_rating_desktop','good / needs-improvement / poor for desktop real-user INP.'),
    'field_cls_desktop':         ('field_cls_desktop',       'DESKTOP real-user CLS at p75 (unitless).'),
    'field_cls_rating_desktop':  ('field_cls_rating_desktop','good / needs-improvement / poor for desktop real-user CLS.'),
    'field_fcp_desktop':         ('field_fcp_desktop_s',     'DESKTOP real-user FCP at p75 (seconds).'),
    'field_fcp_rating_desktop':  ('field_fcp_rating_desktop','good / needs-improvement / poor for desktop real-user FCP.'),
    'field_ttfb_desktop':        ('field_ttfb_desktop_ms',   'DESKTOP real-user TTFB at p75 (ms).'),
    'field_ttfb_rating_desktop': ('field_ttfb_rating_desktop','good / needs-improvement / poor for desktop real-user TTFB.'),

    # ---- AI-READINESS (deterministic discoverability signals; no LLM) ----
    'ai_readiness_score':    ('ai_readiness_score',  'Can bots & AI find/parse this site? 0-100 rollup of the sub-checks below.'),
    'ai_readiness_partial':  ('ai_readiness_partial','True = score is partial (some checks unmeasurable, usually SSR) — not directly comparable to a full score.'),
    'ai_readiness_issues':   ('ai_readiness_issues', 'Specific AI-discoverability problems found (citable facts).'),
    'ssr_raw_words':         ('ssr_raw_words',       'Words in the RAW HTML (what a non-JS crawler/AI sees).'),
    'ssr_rendered_words':    ('ssr_rendered_words',  'Words after JavaScript runs (what a real browser sees).'),
    'ssr_content_ratio':     ('ssr_content_ratio',   'raw / rendered words. ~1 = server-rendered (AI-friendly); low = needs JS (AI-invisible).'),
    'ssr_client_rendered':   ('ssr_client_rendered', 'True if <50% of content is server-rendered — AI crawlers likely miss most of it.'),
    'robots_found':          ('robots_found',        'True if /robots.txt exists.'),
    'robots_blocks_ai':      ('robots_blocks_ai',    'True if robots.txt disallows major AI crawlers (GPTBot/ClaudeBot/PerplexityBot/etc.).'),
    'robots_ai_blocked_list':('robots_ai_blocked_list','Which AI bots are blocked.'),
    'robots_has_sitemap':    ('robots_has_sitemap',  'True if robots.txt declares a Sitemap:.'),
    'has_llms_txt':          ('has_llms_txt',        'True if /llms.txt exists (emerging AI-readable summary standard).'),
    'jsonld_count':          ('jsonld_count',        'Number of valid Schema.org JSON-LD blocks in the raw HTML.'),
    'jsonld_types':          ('jsonld_types',        'Schema.org types found (Organization, Product, FAQPage, ...).'),
    'has_schema_org':        ('has_schema_org',      'True if any structured data (JSON-LD) is present.'),
    'has_sitemap':           ('has_sitemap',         'True if a sitemap.xml exists (direct or via robots.txt).'),
    'sitemap_url_count':     ('sitemap_url_count',   'URL count in sitemap.xml (when directly readable).'),
    'has_title':             ('has_title',           'True if the page has a <title>.'),
    'title_text':            ('title_text',          'The page <title> text.'),
    'has_meta_description':  ('has_meta_description','True if a meta description is present.'),
    'meta_description_text': ('meta_description_text','The meta description text.'),
    'has_og_tags':           ('has_og_tags',         'True if OpenGraph tags exist (social/link-preview readiness).'),
    'h1_count':              ('h1_count',            'Number of <h1> headings (1 is ideal).'),
    'ai_readiness_error':    ('ai_readiness_error',  'Error from the AI-readiness check, if any.'),

    # ---- ACCESSIBILITY (axe-core WCAG scan of the HOMEPAGE; ADA/legal-risk signal) ----
    # Scope is the homepage only; counts are a conservative FLOOR (axe excludes
    # "incomplete"/undecidable checks). An empty a11y_error + non-null count = measured;
    # a set a11y_error or null counts = NOT measured (e.g. CSP blocked the scan) != clean.
    'a11y_violation_count': ('a11y_violation_count', 'Homepage: distinct WCAG rules failed (axe-core, WCAG A/AA). Conservative floor.'),
    'a11y_node_count':      ('a11y_node_count',      'Homepage: total failing elements across all violations.'),
    'a11y_critical':        ('a11y_critical',        'Homepage: number of CRITICAL-impact rule violations.'),
    'a11y_serious':         ('a11y_serious',         'Homepage: number of SERIOUS-impact rule violations.'),
    'a11y_moderate':        ('a11y_moderate',        'Homepage: number of MODERATE-impact rule violations.'),
    'a11y_minor':           ('a11y_minor',           'Homepage: number of MINOR-impact rule violations.'),
    'a11y_lawsuit_risk':    ('a11y_lawsuit_risk',    'Homepage has a violation in a commonly-litigated WCAG rule (alt text, form labels, contrast, link/button names).'),
    'a11y_top_issues':      ('a11y_top_issues',      'Homepage: specific WCAG failures + element counts — citable facts (e.g. "Images must have alternate text (12 elements)").'),
    'a11y_wcag_tags':       ('a11y_wcag_tags',       'Homepage: WCAG success criteria touched (e.g. wcag111, wcag143).'),
    'a11y_error':           ('a11y_error',           'Error from the accessibility scan (e.g. CSP blocked it). Non-empty = NOT measured, not "clean".'),

    # ---- PAGE WEIGHT + PRIVACY (network-pass, from the capture browser) ----
    'page_weight_kb':        ('page_weight_kb',       'Transferred KB from Content-Length headers — a FLOOR (undercounts gzipped/cached). Blank = no sizes seen.'),
    'page_weight_partial':   ('page_weight_partial',  'True = many resources reported no size, so page_weight_kb is an unreliable floor; do not cite it.'),
    'image_weight_kb':       ('image_weight_kb',      'KB of images loaded.'),
    'image_count':           ('image_count',          'Number of images loaded.'),
    'large_image_count':     ('large_image_count',    'Images over 200 KB each (optimization targets).'),
    'uses_next_gen_images':  ('uses_next_gen_images', 'True if any WebP/AVIF served; False = legacy JPEG/PNG only.'),
    'request_count':         ('request_count',        'Total network requests on load.'),
    'third_party_domains':   ('third_party_domains',  'Distinct off-site domains the page calls (tag/privacy surface).'),
    'trackers_detected':     ('trackers_detected',    'Named trackers firing on load (GA, Meta Pixel, …) — informational (their marketing stack); does NOT by itself imply a consent issue.'),
    'tracker_count':         ('tracker_count',        'Number of distinct trackers detected.'),
    'cookies_set':           ('cookies_set',          'Total cookies set on load (before any consent).'),
    'tracking_cookies':      ('tracking_cookies',     'Of those, how many are tracking cookies (_ga/_fbp/…).'),
    'has_consent_banner':    ('has_consent_banner',   'A cookie/consent banner or CMP was detected.'),
    'tracking_before_consent': ('tracking_before_consent', 'True if a tracking COOKIE (identifier, e.g. _ga/_fbp) was set on load BEFORE any consent — the ePrivacy/GDPR trigger. Cookieless tracker pings (Consent Mode) do NOT count.'),
    'page_signals_issues':   ('page_signals_issues',  'Combined page-weight + privacy problems (citable summary).'),
    'page_signals_error':    ('page_signals_error',   'Error from the network-pass signals, if any.'),

    # ---- SECURITY & SSL (deterministic; no browser) ----
    'sec_header_score':        ('sec_header_score',        'Security-header score 0-100 (HSTS/CSP/X-Frame/X-CTO/Referrer/Permissions, weighted).'),
    'sec_header_grade':        ('sec_header_grade',        'Security-header grade A+ to F (like Mozilla Observatory).'),
    'has_hsts':                ('has_hsts',                'True if Strict-Transport-Security header present.'),
    'has_csp':                 ('has_csp',                 'True if Content-Security-Policy header present.'),
    'has_x_frame_options':     ('has_x_frame_options',     'True if X-Frame-Options header present (clickjacking protection).'),
    'has_x_content_type_options':('has_x_content_type_options','True if X-Content-Type-Options header present.'),
    'has_referrer_policy':     ('has_referrer_policy',     'True if Referrer-Policy header present.'),
    'has_permissions_policy':  ('has_permissions_policy',  'True if Permissions-Policy header present.'),
    'sec_headers_missing':     ('sec_headers_missing',     'Which security headers are missing (citable facts).'),
    'ssl_valid':               ('ssl_valid',               'True if the TLS cert chain verifies (not expired/self-signed/wrong host).'),
    'ssl_days_to_expiry':      ('ssl_days_to_expiry',      'Days until the SSL certificate expires (negative = already expired).'),
    'ssl_expires_soon':        ('ssl_expires_soon',        'True if the cert expires in under 30 days.'),
    'tls_version':             ('tls_version',             'Negotiated TLS version (TLSv1.2 / TLSv1.3; older = outdated).'),
    'mixed_content':           ('mixed_content',           'True if the HTTPS page loads insecure http:// assets (browser warnings). None = not an HTTPS page.'),
    'mixed_content_count':     ('mixed_content_count',     'Number of insecure http:// assets found.'),
    'mixed_content_examples':  ('mixed_content_examples',  'Example insecure asset URLs.'),
    'security_issues':         ('security_issues',         'Combined security problems found (citable summary).'),
    'security_error':          ('security_error',          'Error from the security check, if any.'),

    # ---- DATA QUALITY / ERRORS ----
    'is_error_page':      ('is_error_page',  'True if 404 / parked / blank / blocked / etc.'),
    'error_type':         ('error_type',     'Type of non-gradeable page.'),
    'screenshot_path':    ('screenshot_path','Saved screenshot file used for design scoring.'),
    'grader_error':       ('grader_error',   'Error from the grading step (e.g. capture failed).'),
    'enrichment_errors':  ('enrichment_errors','Combined errors across all enrichment steps.'),
    'flag_count':         ('flag_count',     'Number of data-quality issues detected.'),
    'flag_reasons':       ('flag_reasons',   'Codes explaining the data-quality issues.'),
}

# Descriptions for columns we DON'T rename (kept as-is, but still annotated).
EXTRA_DESCRIPTIONS = {
    'pagespeed_mobile':   'Mobile speed 0-100 (Google PageSpeed). Below 50 = Signal 2 target.',
    'pagespeed_desktop':  'Desktop speed 0-100 (Google PageSpeed).',
    'monthly_visits':     'Monthly visitors (from the source CSV / SimilarWeb).',
    'global_rank':        'Global website traffic rank.',
    'bounce_rate':        'Visitor bounce rate (%).',
    'tech_stack':         'Primary detected technology (wordpress, webflow, next.js, ...).',
    'all_tech_detected':  'All technologies detected on the site.',
    'is_wordpress':       'True if the site runs on WordPress.',
    'marketing_tools':    'Detected analytics/marketing tools.',
    'has_premium_analytics':'Uses premium analytics (Segment/Amplitude/Mixpanel, ...) = Signal 3.',
    'is_signal_2_traffic':'True if 50K+ monthly visits.',
}

# Derived lookups
_INTERNAL_TO_FRIENDLY = {k: v[0] for k, v in FIELD_MAP.items()}
_FRIENDLY_TO_INTERNAL = {v[0]: k for k, v in FIELD_MAP.items()}
# description keyed by the friendly name (what appears in the written file)
_FRIENDLY_DESC = {v[0]: v[1] for k, v in FIELD_MAP.items()}
_FRIENDLY_DESC.update(EXTRA_DESCRIPTIONS)

# Probe columns used to detect whether row 0 is the description row: columns that are
# numeric in real data but hold descriptive TEXT in the description row. Includes both
# the subjective-grader headline scores AND objective-signal columns, so the description
# row is still detected on CSVs that carry only the objective signals (no grade columns).
_NUMERIC_PROBES = ('overall_score', 'content_score', 'design_score',
                   'total_grade_score', 'speed_score',
                   'seo_score', 'accessibility_score', 'best_practices_score',
                   'field_lcp_s', 'field_cls', 'pagespeed_mobile')


def _is_number(v):
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def _has_description_row(df: pd.DataFrame) -> bool:
    """A description row has TEXT in a column that is otherwise numeric."""
    if len(df) == 0:
        return False
    first = df.iloc[0]
    for col in _NUMERIC_PROBES:
        if col in df.columns:
            v = first[col]
            if isinstance(v, str) and v.strip() and not _is_number(v):
                return True
    return False


def write_annotated_csv(df: pd.DataFrame, path) -> None:
    """Write df with friendly column names + a plain-English description row."""
    rename = {c: _INTERNAL_TO_FRIENDLY[c] for c in df.columns if c in _INTERNAL_TO_FRIENDLY}
    out = df.rename(columns=rename)
    desc = {col: _FRIENDLY_DESC.get(col, '') for col in out.columns}
    annotated = pd.concat([pd.DataFrame([desc], columns=out.columns), out], ignore_index=True)
    annotated.to_csv(path, index=False)


def read_annotated_csv(path, **kwargs) -> pd.DataFrame:
    """Read a CSV written by write_annotated_csv (or a plain one).

    Drops the description row if present, renames friendly -> internal so the rest
    of the code sees the names it expects, and re-coerces numeric columns.
    """
    df = pd.read_csv(path, **kwargs)
    if _has_description_row(df):
        df = df.iloc[1:].reset_index(drop=True)
    rename = {c: _FRIENDLY_TO_INTERNAL[c] for c in df.columns if c in _FRIENDLY_TO_INTERNAL}
    df = df.rename(columns=rename)
    # The text description row forces object dtype; coerce real values back.
    for c in df.columns:
        if df[c].dtype != object:
            continue
        non_null = df[c].dropna()
        if len(non_null) == 0:
            continue
        # Boolean columns (cwv_pass, is_wordpress, ...) survive a CSV round-trip as the
        # STRINGS 'True'/'False'. Coerce them back to real bools — otherwise downstream
        # bool('False') == True silently flips them. Check before numeric coercion.
        vals = set(str(v).strip() for v in non_null.unique())
        if vals <= {'True', 'False'}:
            df[c] = df[c].map(lambda v: True if str(v).strip() == 'True'
                              else (False if str(v).strip() == 'False' else None))
            continue
        coerced = pd.to_numeric(df[c], errors='coerce')
        # only adopt if it didn't blow away real (non-empty) string data
        if coerced.notna().sum() == df[c].notna().sum():
            df[c] = coerced

    # Text columns: a CSV empty cell reads back as NaN. For columns that remain text
    # AND actually contain string data, restore '' so equality filters like
    # df['a11y_error'] == '' behave. Skip all-empty columns (could be an empty NUMERIC
    # column left as object by the description row — don't stringify those) and any
    # numeric/bool columns (already coerced, not object).
    for c in df.columns:
        if df[c].dtype == object and df[c].notna().any():
            df[c] = df[c].where(df[c].notna(), '')
    return df
