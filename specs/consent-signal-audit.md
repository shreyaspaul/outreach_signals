# Consent Signal (`tracking_before_consent`) — Data Integrity Audit

**Date:** 2026-07-02
**Scope:** the `tracking_before_consent` signal (`scripts/page_signals.py`), its message-level
narrowing to advertising cookies (`scripts/message_generator.py:build_secondary_signals`), and the
40 outbound messages in `data/messages_v2.csv` that cite it ("...cookies are set before consent, so
that part just needs to be GDPR compliant").

---

## VERDICT: YES — WITH CAVEATS

The **technical core of the signal is accurate and defensible**: the cookies we cite are real
cross-site advertising identifiers, Google/Meta Consent Mode genuinely withholds them when consent is
denied (so their *presence* is meaningful), the capture never clicks "accept," and live re-capture
reproduces the cited first-party cookies reliably. **The weakness is not the cookie observation — it
is the leap to "you'll have EU visitors, so it just needs to be GDPR compliant."** That EU-traffic
claim is an *unverified assumption* the pipeline never measures, and our capture runs from a US IP so
it cannot detect geo-gating. The cookie fact is bulletproof; the *GDPR jurisdiction* framing is the
soft spot. Two secondary fixes (Microsoft `_uet*` placeholder nuance, third-party-cookie flakiness)
are minor because first-party `_gcl_au`/`_fbp` carry almost every message.

---

## Check 1 — Classification correctness (false positives / negatives)

**Advertising cookies actually cited across the 40 messages** (parsed from `page_signals_issues`):

| Cookie | Count | Party | Product | Defensible as a cross-site ad identifier? |
|---|---|---|---|---|
| `_gcl_au` | 28 | **first-party** | Google Ads (Conversion Linker) | YES — 90-day ad-click identifier, requires consent under GDPR/ePrivacy (Google's own docs). |
| `_fbp` | 26 | **first-party** | Meta Pixel | YES — pseudonymous browser identifier, "personal data under GDPR," set the moment the pixel script runs. |
| `MUID` | 9 | 3rd (also seen 1st) | Microsoft | YES — Microsoft User ID, synced across bing/msn/live for ad targeting. |
| `IDE` | 4 | **third-party** | DoubleClick | YES — the canonical DoubleClick retargeting cookie. |
| `personalization_id` | 3 | third-party | X/Twitter | YES — X ad personalization identifier. |
| `_uetsid` / `_uetvid` | 3 | first-party | Microsoft Ads (UET) | MOSTLY — see the placeholder caveat in Check 2. |

**No false positives found among cited cookies.** Every name that reaches a message maps to a genuine
advertising/retargeting product. The message layer (`_AD_COOKIE_EXACT` / `_AD_COOKIE_PREFIX`,
`message_generator.py:252-259`) is *deliberately narrower* than the raw signal — it excludes analytics
(`_ga`, `_clck`/Clarity, `__hstc`/HubSpot, `mp_`/Mixpanel), which is the correct and defensible move.

**Prefix false-positive risk in the RAW signal** (`TRACKING_COOKIE_PREFIXES`, `page_signals.py:67`):
`mp_` could in principle match a non-Mixpanel cookie, and `_gcl` matches `_gcl_dc`/`_gcl_gs` variants.
But these never reach a message because analytics prefixes are dropped at the message layer. The
message-level `_AD_COOKIE_*` prefixes (`_fbp`,`_fbc`,`_gcl`,`_uet`,`_pin`) are all well-namespaced ad
families — low collision risk. `MUID` / `IDE` / `fr` / `personalization_id` are EXACT-match only, so
no "IDENTITY"/"frame" substring risk. **Classification is clean.**

---

## Check 2 — Does the Consent-Mode logic actually hold?

**YES, this is the strongest part of the signal.** Under Google Consent Mode v2 with the default set to
denied, Google's tags **do not write** `_ga`, `_gid`, `_gat`, or `_gcl_au`; they instead fire a
*cookieless* ping carrying only consent-denied flags (no identifier stored). Meta's pixel behaves
analogously. Therefore **the physical presence of `_gcl_au`/`_fbp` in the browser after a no-interaction
load genuinely means an advertising identifier was stored without consent** — either Consent Mode is not
implemented, or its default is (wrongly) set to granted. The module's decision to key the flag off the
*cookie* and NOT the *tracker request* (docstring lines 9-14, code lines 249-252) is exactly right and
avoids the cookieless-ping false positive. `test_page_signals_dedupe_and_consent` encodes this.

**One caveat — Microsoft UET (`_uetsid`/`_uetvid`):** Microsoft's docs note these can be *initialized with
placeholder values before consent* that "do not contain personal identifiers and are not used for tracking
until the user provides consent." So a bare `_uetsid` is a *weaker* proof of a stored identifier than
`_gcl_au`/`_fbp`. Only **3 of 40** messages lean on `_uet*`, so impact is small, but the claim is softer
there.

---

## Check 3 — GEO / IP dependence (HIGHEST-RISK HOLE)

**This is the real weakness, and it lands on the message framing, not the cookie fact.**

- Our capture runs from this machine's IP (US) and the context sets **no EU locale, timezone, geolocation,
  or proxy** (`website_grader.py:355-360` — only viewport, a US-ish UA, `ignore_https_errors`,
  `java_script_enabled`; `Accept-Language: en-US`, line 383). So every observation is a **US-visitor
  observation**.
- Setting ad cookies for a genuine US visitor with no banner is **legal** (US has no ePrivacy consent-gate).
  A cookie-before-consent seen from a US IP therefore does **not by itself prove** the site mistreats EU
  visitors — a compliant site can geo-gate: serve the CMP + Consent-Mode-deny to EU/EEA IPs only.
- **The messages assert exactly the unproven link:** *"you'll have eu visitors at your traffic, so that part
  just needs to be gdpr compliant"* (second_message, all 40). The pipeline **never measures EU traffic** —
  it stores only `apify_top_country` + `apify_top_country_share`, no EU/EEA percentage. For the flagged
  sites the top country is **US in 28 of 40**, mean US share ~50%, with the remaining ~50% unattributed
  (could be EU, could be IN/ID/BR/etc.). So "you'll have EU visitors" is a **plausible-but-unverified
  inference**, not a fact.

**Partial mitigation from Check 4:** the EU-locale re-capture (below) showed the flagged sites set the
*same* cookies regardless of locale — i.e. these particular sites are **not locale-gating**. That means the
underlying behavior (cookies fire unconditionally client-side) is real; but locale ≠ IP, so it does not
prove they aren't *IP*-gating. Net: the cookie behavior is real and mostly unconditional, but the specific
"you have EU visitors" sentence is the least-defensible clause in the message and should be softened.

---

## Check 4 — Live empirical reproduction (7 domains, 3 context variants each)

Throwaway script `/tmp/consent_repro.py` (mirrors the grader's launch/context args). Each domain captured
under: **US-default**, **EU-like** (`locale=en-GB`, `timezone_id=Europe/Berlin`, `Accept-Language: en-GB`),
and **US + third-party cookies force-enabled** (`--disable-features=ImprovedCookieControls`). No "accept"
click. Results:

| Domain | Banner | Ad cookies observed (US-default) | EU-like differs? | Negative control |
|---|---|---|---|---|
| acctual.com | none | `_gcl_au` | no diff | |
| floot.com | none | `_fbp` | no diff | |
| neurosity.co | none | `_fbp`, `_gcl_au` | no diff | |
| poised.com | none | `_gcl_au`, `_fbp`, **IDE** (3rd-party) | no diff | |
| jabali.ai | **present** | `_gcl_au`, `_fbp`, **IDE** | no diff | banner present, cookies still set |
| elitehrv.com | **present** | `_fbp` | no diff | banner present, cookies still set |
| **simplex.chat** | none | **none — 0 cookies total** | — | ✅ correct negative |

**Findings:**
- The cited ad cookies are **actually set on load**, confirmed live for every tested domain.
- **EU-like locale/timezone changed nothing** — cookies identical. These sites do not locale-gate. (IP not
  testable here; documented limitation.)
- **Negative control (simplex.chat, not flagged) set zero cookies** — the signal does not fire spuriously.
- **Banner-present sites (jabali, elitehrv) still set ad cookies before any click** — confirms a visible
  banner ≠ compliance; `tracking_before_consent` correctly fires despite `has_consent_banner=True`. This is
  a genuinely strong talking point.

---

## Check 5 — Reproducibility vs stored `enriched_ALL_999.csv`

| Domain | Stored (page_signals_issues) | Live re-capture | Match? |
|---|---|---|---|
| acctual.com | `_ga,_ga_*,_gcl_au` | identical | ✅ exact |
| floot.com | `_fbp,_ga,_ga_*` | identical | ✅ exact |
| poised.com | `IDE,_fbp,_ga,_ga_*,_gcl_au` | identical | ✅ exact |
| jabali.ai | `_fbp,_ga_*,_gcl_au,mp_*` | `IDE,_fbp,_ga_*,_gcl_au` (mp_ gone, IDE new) | ~ drift |
| neurosity.co | `IDE,_fbp,_ga,_ga_*,_gcl_au` | `_fbp,_gcl_au` (IDE + _ga gone) | ~ drift |
| elitehrv.com | `IDE,_fbp,_ga,_ga_*,_gid` | `_fbp,_ga,_ga_*,_gid` (IDE gone) | ~ drift |

**The drift is entirely in the third-party cookies** (`IDE` appears/disappears run-to-run; the third-party
`_ga` state on neurosity varied). **First-party ad cookies (`_gcl_au`, `_fbp`) reproduced 100%** across
every domain that claimed them. Since the messages lean overwhelmingly on `_gcl_au` (28) and `_fbp` (26),
the signal is **stable enough to cite** — but any message resting *solely* on `IDE`/`personalization_id`
is on shakier, flakier ground.

---

## Check 6 — Third-party cookie capture reliability

**Hypothesis (third-party cookies structurally never captured) is DISPROVEN.** `IDE` (a doubleclick.net
third-party cookie) appeared in `context.cookies()` on poised.com and jabali.ai **even without** the
`--disable-features=ImprovedCookieControls` flag. So Playwright Chromium as launched here (line 351: only
`--ignore-certificate-errors`, `--ssl-version-min=tls1`) *does* store and surface third-party cookies.

BUT their appearance is **non-deterministic** (Check 5 drift). And per the message breakdown:
- **57 first-party** ad-cookie citations (`_gcl_au`,`_fbp`,`_uet*`) vs **16 third-party** (`IDE`,`MUID`,
  `personalization_id`).
- **Only 2 of 40** messages rely *exclusively* on third-party ad cookies. 38 are anchored by a stable
  first-party cookie.

So the third-party flakiness is a real but **contained** risk. It does not structurally sink the signal.

---

## Prioritized fixes

1. **[HIGH — framing] Soften the "you'll have EU visitors, so it just needs to be GDPR compliant" clause.**
   This is the single least-defensible sentence. The pipeline never measures EU traffic, and we observe
   from a US IP so we can't rule out legal US-visitor cookie-setting or EU-only geo-gating. Reword to make
   the *cookie fact* the claim and EU applicability a soft conditional, e.g. "these ad cookies fire before
   any consent step — if you get EU/UK traffic that's worth gating." Don't assert EU traffic as fact.

2. **[MEDIUM — data] Capture/store an EU-traffic percentage** (or at least stop implying one). If we want
   to keep the GDPR angle strong, add an EU/EEA share from the traffic source and only make the compliance
   claim when it's meaningfully > 0. Right now only single-top-country is stored.

3. **[MEDIUM — optional rigor] Add an EU-IP (or at least document the US-IP limitation) before scaling.**
   Locale/timezone made no difference here, but that does not test IP-based geo-gating, which is the real
   compliance discriminator. A one-off EU-proxy re-capture on a sample would let us claim "we checked as an
   EU visitor."

4. **[LOW — precision] Demote `_uetsid`/`_uetvid` as sole evidence.** Microsoft may set these as pre-consent
   *placeholders* without a real identifier. Only 3 messages use them; prefer `_gcl_au`/`_fbp` as the anchor
   when both are present, and avoid resting a message on `_uet*` alone.

5. **[LOW — precision] Flag/deprioritize messages resting solely on third-party cookies** (`IDE`,
   `personalization_id`): only 2 today, but they are the flaky ones (Check 5). Prefer a first-party anchor.

**No code changes were made** (verification-only task). Existing `scripts/test_signals.py` passes (12/12).
Throwaway repro script left at `/tmp/consent_repro.py`.
