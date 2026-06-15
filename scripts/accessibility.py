#!/usr/bin/env python3
"""
Accessibility scan via axe-core (Deque) — the industry-standard WCAG engine, the SAME
rules ADA web-accessibility lawsuits are based on.

Runs inside the Playwright page we already open during capture (no extra browser launch).
Produces FACTUAL, citable columns — counts by severity + the specific violations
("Images must have alternative text (12 elements)") + a lawsuit-risk flag for the
high-litigation rule categories. No invented 0-100 score (axe doesn't provide one; the
Lighthouse accessibility_score already gives a rollup if a number is wanted).

Why this matters: research found 5,000+ ADA web lawsuits in 2025, settlements $5-75K, and
36% targeting companies >$25M revenue (the ICP). The most-litigated issues — missing alt
text, missing form labels, insufficient contrast, unnamed links/buttons — are exactly what
axe detects automatically.
"""

from pathlib import Path

# axe-core is vendored locally (MPL-2.0) so there's no runtime CDN dependency.
_AXE_PATH = Path(__file__).parent / 'vendor' / 'axe.min.js'
_AXE_JS_CACHE = None

# axe rule IDs that map to the most commonly-litigated WCAG failures. A serious/critical
# violation in any of these sets the lawsuit-risk flag.
HIGH_LITIGATION_RULES = {
    'image-alt', 'input-image-alt', 'area-alt', 'role-img-alt',     # missing alt text
    'label', 'select-name', 'form-field-multiple-labels',           # unlabeled form fields
    'color-contrast',                                               # insufficient contrast
    'link-name', 'button-name',                                     # unnamed links/buttons
    'document-title', 'html-has-lang', 'frame-title',               # page-level basics
    'aria-input-field-name', 'aria-command-name',                   # unnamed ARIA controls
}

# WCAG A / AA tags — the legally relevant conformance levels.
AXE_RUN_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']

AXE_FIELDS = (
    'a11y_violation_count',   # distinct rules failed
    'a11y_node_count',        # total failing elements (instances)
    'a11y_critical',          # rules failed at each impact level
    'a11y_serious',
    'a11y_moderate',
    'a11y_minor',
    'a11y_lawsuit_risk',      # bool: serious/critical violation in a high-litigation rule
    'a11y_top_issues',        # citable: "Images must have alternate text (12 elements); ..."
    'a11y_wcag_tags',         # WCAG criteria touched (e.g. wcag111, wcag143)
    'a11y_error',
)
_AXE_TEXT_FIELDS = {'a11y_top_issues', 'a11y_wcag_tags', 'a11y_error'}


def accessibility_defaults():
    """Empty (not-measured) defaults for all axe fields."""
    return {f: ('' if f in _AXE_TEXT_FIELDS else None) for f in AXE_FIELDS}


def _load_axe_js():
    global _AXE_JS_CACHE
    if _AXE_JS_CACHE is None:
        _AXE_JS_CACHE = _AXE_PATH.read_text(encoding='utf-8')
    return _AXE_JS_CACHE


def _parse_axe_results(raw):
    """Parse the dict returned by axe.run() into our flat factual fields.

    Pure function (no browser) so it's unit-testable against captured axe output.
    """
    result = accessibility_defaults()
    if not isinstance(raw, dict):
        result['a11y_error'] = 'axe returned no result'
        return result

    violations = raw.get('violations') or []
    impacts = {'critical': 0, 'serious': 0, 'moderate': 0, 'minor': 0}
    node_total = 0
    wcag_tags = set()
    lawsuit_risk = False
    ranked = []  # (severity_rank, node_count, label)

    severity_rank = {'critical': 4, 'serious': 3, 'moderate': 2, 'minor': 1}

    for v in violations:
        nodes = v.get('nodes') or []
        n = len(nodes)
        node_total += n

        # Impact: prefer the violation's top-level impact; axe allows it to be null,
        # so fall back to the WORST impact among its failing nodes (never silently
        # downgrade a real issue to 'minor').
        impact = (v.get('impact') or '').lower()
        if impact not in impacts:
            node_impacts = [(nd.get('impact') or '').lower() for nd in nodes]
            impact = next((lvl for lvl in ('critical', 'serious', 'moderate', 'minor')
                           if lvl in node_impacts), 'minor')
        impacts[impact] += 1

        for tag in (v.get('tags') or []):
            if tag.startswith('wcag') and any(c.isdigit() for c in tag):
                wcag_tags.add(tag)

        rule_id = v.get('id', '')
        # Lawsuit-risk keys off the RULE identity (alt text / labels / contrast /
        # link & button names / …), independent of the impact bucket — these rules are
        # litigation-relevant whenever they fire, and keying off the rule avoids a
        # null/odd impact value silently clearing the flag.
        if rule_id in HIGH_LITIGATION_RULES:
            lawsuit_risk = True

        # Human-readable citable label
        label = (v.get('help') or v.get('description') or rule_id or 'issue').strip()
        ranked.append((severity_rank.get(impact, 1), n, f"{label} ({n} element{'s' if n != 1 else ''})"))

    # Top issues: worst impact first, then most instances
    ranked.sort(key=lambda t: (-t[0], -t[1]))
    top_issues = '; '.join(label for _, _, label in ranked[:6])

    result['a11y_violation_count'] = len(violations)
    result['a11y_node_count'] = node_total
    result['a11y_critical'] = impacts['critical']
    result['a11y_serious'] = impacts['serious']
    result['a11y_moderate'] = impacts['moderate']
    result['a11y_minor'] = impacts['minor']
    result['a11y_lawsuit_risk'] = lawsuit_risk
    result['a11y_top_issues'] = top_issues
    result['a11y_wcag_tags'] = ', '.join(sorted(wcag_tags))
    result['a11y_error'] = ''
    return result


async def run_axe_on_page(page):
    """Inject axe-core into an open Playwright page and run a WCAG A/AA scan.

    Returns the parsed factual fields. Never raises — on any failure returns
    not-measured defaults with a11y_error set.
    """
    try:
        await page.add_script_tag(content=_load_axe_js())
        raw = await page.evaluate(
            """async (tags) => {
                try {
                    const res = await axe.run(document, {
                        runOnly: { type: 'tag', values: tags },
                        resultTypes: ['violations']
                    });
                    return { violations: res.violations };
                } catch (e) {
                    return { __error: String(e) };
                }
            }""",
            AXE_RUN_TAGS,
        )
        if isinstance(raw, dict) and raw.get('__error'):
            out = accessibility_defaults()
            out['a11y_error'] = f"axe.run: {str(raw['__error'])[:60]}"
            return out
        return _parse_axe_results(raw)
    except Exception as e:
        out = accessibility_defaults()
        out['a11y_error'] = f"axe inject/run: {str(e)[:60]}"
        return out


if __name__ == '__main__':
    # Standalone: run axe on a URL via a fresh Playwright page.
    import argparse
    import asyncio
    parser = argparse.ArgumentParser(description='Run an axe-core WCAG scan on a URL')
    parser.add_argument('url')
    args = parser.parse_args()

    async def _main():
        from playwright.async_api import async_playwright
        url = args.url if args.url.startswith(('http://', 'https://')) else 'https://' + args.url
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(url, wait_until='load', timeout=45000)
            res = await run_axe_on_page(page)
            await browser.close()
        print(f"\naxe-core WCAG A/AA scan — {url}")
        print("=" * 60)
        if res['a11y_error']:
            print("  ERROR:", res['a11y_error'])
        print(f"  Violations: {res['a11y_violation_count']} rules / {res['a11y_node_count']} elements")
        print(f"  By impact: critical {res['a11y_critical']} | serious {res['a11y_serious']} "
              f"| moderate {res['a11y_moderate']} | minor {res['a11y_minor']}")
        print(f"  Lawsuit-risk (serious/critical in litigated rules): {res['a11y_lawsuit_risk']}")
        print(f"  WCAG tags: {res['a11y_wcag_tags'] or '(none)'}")
        print(f"\n  Top issues:\n    " + (res['a11y_top_issues'].replace('; ', '\n    ') or '(none)'))

    asyncio.run(_main())
