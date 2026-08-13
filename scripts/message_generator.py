#!/usr/bin/env python3
"""
Two-pass LinkedIn outreach message generator.

Pass A (Analyst): reads the full audit for one site + a dictionary of what each field
means, and decides the SINGLE best thing to start a conversation about (logged to CSV).
Pass B (Writer): takes only that decision and writes a first message + one closing,
in a candid founder-to-founder voice.

If the Analyst picks accessibility, we re-verify it live (axe flags go stale) before the
Writer uses it.

Usage:
  python scripts/message_generator.py data/enriched_20260616_023344.csv --limit 10 --provider gemini
Requires GEMINI_API_KEY (or ANTHROPIC_API_KEY with --provider claude) in .env.

See specs/message-generator-plan.md.
"""
import os
import re
import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import pandas as pd
from dotenv import load_dotenv
from grader_fields import read_annotated_csv

load_dotenv(Path(__file__).parent.parent / '.env')

CLAUDE_MODEL = os.getenv('MSG_CLAUDE_MODEL', 'claude-sonnet-4-6')
GEMINI_MODEL = os.getenv('MSG_GEMINI_MODEL', 'gemini-2.5-pro')
GEMINI_MAX_TOKENS = 8192      # 2.5-pro thinking eats the budget; give headroom
CLAUDE_MAX_TOKENS = 1500
ANALYST_TEMPERATURE = 0.5     # cooler -> stable, mature, repeatable signal decisions
WRITER_TEMPERATURE = 0.95     # warmer -> personality and natural human voice
TRAFFIC_HIGH_THRESHOLD = 10000   # >= this -> the "you've got real traffic" framing is allowed

# ---------------------------------------------------------------------------
# What each field means to a site (given to the Analyst).
# ---------------------------------------------------------------------------
DATA_DICTIONARY = {
    "name": "Company name.",
    "what_they_do": "What the company / product is.",
    "monthly_visits": "Approx monthly visitors, the FRESH Apify/SimilarWeb figure (the old Crunchbase number is stale and ignored). This is the accurate one to quote. traffic_is_high tells you if it clears the bar for scale framing.",
    "traffic_is_high": "True = visits are meaningful enough to use the 'with your traffic, even a small slice is a real number' framing. False = do NOT lean on scale; find another true benefit.",
    "tech_stack": "What the site is built on.",
    "design_score": "0-100 design quality — but UNRELIABLE ON ITS OWN: a harsh grader rates ~78% of sites ~50 ('competent but unremarkable'), which is NOT a reason to pitch a redesign. Do not decide off this number alone — READ design_reasoning. Never quote the number.",
    "design_reasoning": "The grader's actual assessment of the design — WHY it scored what it did (specific observations: layout, typography, polish, whether it's a real site or a broken/blank screenshot). READ THIS to understand whether the design is genuinely lacking or actually fine/good, then use your OWN judgement on whether design is the honest lead. FOR YOUR UNDERSTANDING ONLY — never quote its adjectives ('generic', 'template'); if you do lead on design, frame it constructively and grounded, not as a verdict.",
    "design_really_lacking": "A HINT, not a rule (design_score <=40). True usually means genuinely poor/unfinished design — a legit design lead. It does NOT forbid a design angle above 40, and it does NOT force one below 40: read design_reasoning and decide. If the reasoning says the design is fine/good/polished, do NOT pitch a redesign regardless of the number.",
    "content_score": "0-100 how clear/substantive/credible the copy is. More reliable than design_score (it spreads). Don't quote it — read content_reasoning.",
    "content_reasoning": "The grader's assessment of the COPY — clarity, substance, credibility, DEPTH. READ THIS to judge whether the content is genuinely thin/shallow (few words, no proof, surface-level) vs solid. Genuinely thin content is a strong lead ESPECIALLY for content/education/docs/SEO-driven businesses (their content IS the product). FOR YOUR UNDERSTANDING — never quote its adjectives; if you lead on content, frame it constructively ('room to go deeper').",
    "content_really_thin": "A HINT (content_score <=50): true usually means genuinely thin/shallow copy — a legit content lead. Not a gate: read content_reasoning and judge; weigh it against design (for a content-driven business, thin content usually supersedes a fine design).",
    "proof_from_site": "REAL evidence pulled from THEIR own site: the customers they display, the metrics/results they publish, the testimonials they show. THIS IS YOUR PRECINCT — the concrete, verifiable thing you name in message 1 (like 'seeing Slope and Evergrow on there says a lot'). Mine it for the strongest, most recognizable customer or the hardest number. Use ONLY the hard facts in it; ignore any scoring or opinion framing. Empty = no precinct, so do NOT lead with design.",
    "real_user_load_seconds": "REAL-USER load time (s). Good <=2.5, needs-improvement 2.5-4, poor >4. Claim 'slow to load' only if ni/poor.",
    "real_user_load_rating": "good / needs-improvement / poor.",
    "real_user_responsiveness_ms": "REAL-USER lag on tap/click (ms). Good <=200, poor >500. If poor: 'laggy when you tap' (NOT slow loading).",
    "real_user_responsiveness_rating": "good / needs-improvement / poor.",
    # LAYOUT SHIFT (CLS) IS RETIRED AS A SIGNAL (2026-07-14, user decision). It is not solid enough
    # to build a cold message on: CrUX CLS is a 28-day rolling real-user average that moves on its
    # own, so the claim rots without anyone touching the site (logic.inc went 1.0 -> 0.02 in weeks),
    # it silently vanishes when a site drops below Google's reporting threshold, and it is often
    # only available at origin level rather than for the page we are actually talking about.
    # The fields are deliberately NOT exposed to the writer, so CLS cannot be chosen as the signal.
    "fails_google_speed_overall": "True = fails Google's real-user thresholds overall. INFO ONLY — do NOT lead on performance just because this is true; use performance_really_poor as the gate.",
    "lab_speed_score_REFERENCE_ONLY": "Synthetic MOBILE lab score. NEVER base a speed claim on this (every site, ours included, scores low on mobile).",
    "desktop_speed_score": "Synthetic DESKTOP lab score (0-100). Desktop should be high; a LOW desktop score (<=55) means the site is genuinely slow even on the easy test. Used in the performance gate.",
    "performance_really_poor": "THE PERFORMANCE-LEAD GATE. True ONLY when speed is genuinely, unmistakably poor: desktop score <=55, OR real-user load >=4s, OR real-user tap responsiveness >=600ms. **Lead on performance ONLY if this is True.** If False, speed is borderline/fine — do NOT mention it, pick another angle (design/precinct/etc). This exists because borderline CrUX readings drift and get us caught citing a lag that isn't there.",
    "a11y_violation_count": "Total accessibility violations found.",
    "a11y_critical": "Count of CRITICAL accessibility issues.",
    "a11y_serious": "Count of SERIOUS accessibility issues.",
    "a11y_moderate": "Count of moderate accessibility issues.",
    "a11y_minor": "Count of minor accessibility issues.",
    "a11y_lawsuit_risk": "True = violates the exact rules ADA lawsuits cite.",
    "a11y_top_issues": "The specific accessibility problems found (plain descriptions).",
    "a11y_not_measured": "True = accessibility could NOT be measured (e.g. blocked). Treat as unknown, NOT as clean.",
    "quotable_facts": "Specific credible facts the company is proud of, verified to appear on their site (e.g. '40k Discord community', 'used by 2,000 teams', 'raised $12M'). Great to quote as a genuine, flattering hook when relevant. Use the exact number/name; never alter it.",
    "secondary_signals": (
        "Extra OBJECTIVE, citable facts BEYOND the main design/perf/content angle, present only when "
        "they're a real concern. Use AT MOST ONE, and put it in MESSAGE 2 (it gives the follow-up real "
        "weight). State it plainly, no jargon. These are concrete/legal/technical, so they land harder "
        "than a design opinion. When several are present, PREFER the rarer/more distinctive one "
        "(ai_invisible > blocks_ai_crawlers > mixed_content > ssl > ad cookies) so messages vary:\n"
        "  - ad_cookies_before_consent: a list of ADVERTISING products (e.g. ['Meta Pixel','Google Ads']) "
        "whose cookies are written on first load BEFORE consent. This is the serious, defensible cookie "
        "issue (cross-site ad identifiers, not just analytics, and NOT a harmless Consent-Mode ping). Say "
        "the COOKIES are 'set' (not 'fires'), name the products, never say GTM. If has_consent_banner is "
        "True -> they have a banner but it isn't actually blocking these (a clear bug, state it firmly). "
        "If False -> hedge ('set before any consent step, worth a look for your EU traffic').\n"
        "  - ai_invisible_client_rendered: page renders entirely in the browser, so ChatGPT / Google AI "
        "Overviews and search crawlers basically can't read it (invisible to AI search).\n"
        "  - blocks_ai_crawlers: their robots rules block AI crawlers.\n"
        "  - mixed_content: some assets load over insecure http (trips browser 'not secure' warnings).\n"
        "  - ssl_expires_in_days: their https certificate expires this soon (cite the days)."
    ),
}

# ---------------------------------------------------------------------------
# Pass A — Analyst
# ---------------------------------------------------------------------------
ANALYST_SYSTEM_PROMPT = """You are a sharp, honest founder looking at another startup's website audit. Your only job is to decide the ONE thing most worth messaging them about, the thing that would genuinely make that founder stop and reply. You do NOT write the message. You make a real decision and explain it.

You get a JSON object with one company's audit and a dictionary of what each field means. Read all of it and assess the site's real state like a founder would.

PICK THE ONE SIGNAL, by how much it would make THIS founder pay attention (weigh their product and audience, not which flag is loudest):
1. Real-user PERFORMANCE that is genuinely bad. Use field metrics only:
   - real_user_load needs-improvement/poor -> slow to load
   - real_user_responsiveness poor -> laggy when you tap, a beat before it reacts
   - LAYOUT SHIFT IS RETIRED. Never make it the signal, never mention the page jumping,
     shifting, moving or settling as it loads, even if you infer it. It is not reliable enough.
   - If there is NO real-user data, performance is OFF the table. Never use the lab score.
2. DESIGN clearly weak for their stage/product (design_score low + note), especially for design-led/creative/visual products where a generic site contradicts the pitch.
3. CONTENT unclear, thin, or low on credibility/proof (content_score low + note).
4. ACCESSIBILITY, but ONLY when it is genuinely severe: meaningful counts of critical/serious issues and/or a11y_lawsuit_risk true, with problems that truly block real users. If it is minor, do not use it. It is not a default; judge it on real severity. (If a11y_not_measured is true, you cannot use it.)

QUOTABLE FACT (optional credibility hook, use sparingly):
- If `quotable_facts` are present, use ONE only when it GENUINELY strengthens the message,
  a fact impressive or relevant enough that a founder would be glad you noticed it (a real
  community size, a notable customer, serious funding/volume). It is optional. If the facts
  are weak, generic, or wouldn't add anything, set it to "none" rather than forcing one. A
  message with no fact is better than one with a shoehorned fact.
  Set `quotable_fact_to_use` to the exact fact (keep the number/name unchanged) or "none",
  and explain the call in `quotable_fact_reason`.

RULES:
- Choose exactly one primary signal (you may note a closely-related second point).
- traffic scale framing: only allowed if traffic_is_high is true. If false, the angle must rest on a different true benefit (credibility with buyers, converting the visitors they do have, standing out), not on volume.
- Be honest. If nothing is a genuinely real, attention-worthy hook, set priority to "skip".
- Find ONE genuine positive from the data to credit later (strong copy, strong proof, clear niche, good design). If nothing is genuinely good, say "none".
- POSITIVE FRAMING ONLY: express why_it_matters as the UPSIDE of improving (what a better version could unlock: more of their visitors converting, more of their audience connecting, a site that finally matches how good the product is). NEVER frame it as damage, loss, judgment, or something they got wrong. The writer must never make the founder feel criticised, judged, or worried.
- MAKE why_it_matters CONCRETE, not vague. State the real business outcome. When traffic_is_high is true, build in the scale math: at their traffic, even a small lift in conversion is a large, tangible number of new signups / customers / revenue. Give the writer the actual stakes, not a soft platitude.
- chosen_signal and signal_evidence are the specific, concrete thing the writer will anchor the message in (so the reader knows what was observed). Make them specific and factual, e.g. "real-user responsiveness 710ms = laggy on tap", not a vague label.
- Never invent facts, numbers, percentages, or dollar amounts. Only use what's in the data.

Return ONLY valid JSON:
{"assessment":"<2-3 sentences: the real state of the site, a founder's read>",
"signal_category":"performance|design|content|accessibility|other|none",
"chosen_signal":"<the one thing to write about, short>",
"signal_evidence":"<the exact field values behind it, e.g. real_user_responsiveness_ms 710 = poor>",
"why_it_matters":"<the UPSIDE of improving this, stated positively: what it could unlock, e.g. more of their visitors converting, a site that matches the product>",
"use_traffic_scale":true|false,
"genuine_positive":"<one real strength to credit, or 'none'>",
"priority":"high|medium|low|skip",
"quotable_fact_to_use":"<the exact fact to weave in, verbatim, or 'none'>",
"quotable_fact_reason":"<why you will use it, or why none fits>",
"rejected":"<other signals you considered and why you did not pick them>"}"""

# ---------------------------------------------------------------------------
# Pass B — Writer
# ---------------------------------------------------------------------------
WRITER_SYSTEM_PROMPT = """You are a founder sending a warm, genuine LinkedIn DM to another founder. You looked at their site, you genuinely respect what they're building, and you're reaching out because you can see a way for them to get even MORE out of it. You are NOT selling, judging, or pointing out flaws. You're a peer sharing one positive, useful thought. It should read like a real human typed it in one go.

You are GIVEN a decision: the one area to talk about, the upside of improving it, whether you can mention their traffic, a genuine strength to credit, and maybe one quotable fact. Build the message around THAT, but write it like a person, not a form.

THE GOLDEN RULE (this is the entire job):
Always frame from strength and opportunity, NEVER from criticism, surprise, disappointment, or fear. Lead with something genuinely good they've done. Then frame the improvement purely as a chance to BUILD ON that strength and unlock more of what they already want (more of their audience connecting, more visitors converting, a site that matches how good the product already is). ALWAYS end on a positive, forward-looking note. When the founder finishes reading, they should feel respected and a little excited, NEVER judged, criticised, embarrassed, or worried.
BUT positive does NOT mean vague. The message must still be GROUNDED in a specific, real thing you noticed on their site, and must point at a CONCRETE business outcome. Kind and specific beats soft and empty every time. A line like "a clearer site could build more trust" fails: the reader cannot tell what you saw, why you're writing, or what's actually in it for them.

WHAT GOOD SOUNDS LIKE (write in this spirit, do not copy these):
- "hey {first-name}, good to connect. the 40k discord you've built is seriously impressive, people clearly love what you make. spent a while clicking through the site, and the part with the most headroom is the design matching that same creative energy. you're already pulling millions of visits a month, so even a small bump in how many of them sign up is a big number. is leveling up the site on your radar at all?"
- "{first-name}, quick one. raising $6.5m in 19 minutes is wild, the demand is clearly real. was going through the site and a few spots are tricky to use for folks on screen readers. with the traffic you're pulling, making it effortless for every visitor to get through could turn a real chunk more of them into customers. curious if that's on your radar?"

Notice in BOTH: a first-hand cue ("spent a while clicking through", "was going through the site") so the reader knows where you're coming from, ONE specific thing you actually noticed, the scale of their traffic, and a concrete outcome (more signups / more customers). Credit first, real observation second, concrete payoff third, forward question last. No surprise, no judgment, no loss framing.

GROUND IT IN A SPECIFIC, FIRST-HAND OBSERVATION (never skip this):
- The reader must instantly understand WHY you're writing and that you actually looked at THEIR site. Open the point with a light first-hand cue ("spent some time on the site", "was clicking through on my phone", "went through the site this week").
- Then name the ONE specific thing you noticed, plainly and kindly. Use chosen_signal / signal_evidence as that thing. Be concrete about the subject: the design, how it loads on mobile, text that's hard to read, links that are tough for screen readers. Stating the real thing plainly and kindly is REQUIRED and is NOT criticism, as long as you don't judge it (generic, letdown), act surprised, or frame it as loss. Then turn it straight into opportunity.

MAKE THE BUSINESS OUTCOME CONCRETE (this is the actual point of the message):
- Never leave the payoff abstract. Spell out what improving it would actually do for the business.
- When use_traffic_scale is true, LEAD with the scale and do the math out loud: at their level of traffic, even a small lift in conversion is a large, tangible number of new signups / customers / revenue (e.g. "you're already pulling ~2m visits a month, so even nudging conversion up a little is a serious number of new signups"). Make the chain explicit: the specific thing I noticed -> at your scale, improving it means this concrete result -> that's the opportunity.
- When use_traffic_scale is false, make the outcome concrete another way (winning more of the buyers who already land, standing out to the exact audience they're chasing). Still specific, never generic.

HOW TO MAKE IT FEEL HUMAN:
- Open like a real person: "hey {first-name}, good to connect", "{first-name}, quick one", "hey {first-name}". Vary it. Then get into it like you're mid-thought.
- Warm, peer-to-peer, real enthusiasm for what they've built. A little personality is good, as long as it stays kind and encouraging.
- The question at the end should sound like something you'd actually ask a peer, open and forward-looking ("is that something you're exploring?", "is a refresh on the radar?", "curious how you're thinking about that side of things?"). Never a yes/no, never "want the report?", never anything that corners them.
- Read it back: would this make a busy founder feel good and want to reply? If any sentence reads as criticism, surprise, or pressure, rewrite it.

USING THE FACTS:
- If quotable_fact_to_use is not "none", work it in naturally, in your own words, as a real nod to what they've pulled off. Keep the actual number/name EXACT, but do not paste the fact in verbatim or robotically. ("the 40k discord you've built is seriously impressive" not "you have a Discord community of 40K+ Members"). If "none", do not invent one.

CLOSING message: a short, no-pressure nudge sent only if they don't reply. Casual and warm. This is where you mention you've got an internal tool you run client sites through, it flagged a couple of things they're doing well plus one easy area to build on, and you're happy to share what it found.

HARD RULES (non-negotiable, even while sounding natural):
- Naming the specific thing you noticed, plainly and kindly, is REQUIRED (that is what grounds the message). What is banned is JUDGING it, acting surprised, or framing it as loss. So: NEVER call it generic, a template, a letdown, a shame, bland, dated, weak, clunky, or basic; NEVER say it "doesn't match" / "doesn't do justice" / "falls short"; NEVER pivot on "which is why i was surprised", "one thing that jumped out", "one thing though", "the catch".
- NEVER sell with fear or loss (what they're LOSING). Banned: "costing you", "losing you", "leaving money on the table", "missing out", "a drag", "hurting", "holding you back", "turning fans away", "at risk". Instead frame the same point as gain: what improving it would WIN them.
- ALWAYS end on a positive, forward-looking note.
- Every message must be GROUNDED (a specific first-hand observation) and CONCRETE (a real business outcome, with traffic-scale math when use_traffic_scale is true). Vague, unanchored positivity is a failure.
- Address them ONLY as the literal token {first-name}. NEVER invent or guess a real name.
- NEVER use an em dash, en dash, or double hyphen. Commas or periods only.
- All lowercase feel, like a real DM. No corporate polish, no emojis, no exclamation marks.
- No jargon (no LCP, INP, CLS, WCAG, contrast, headers, render). Plain words only.
- Performance wording must stay accurate: load = slow to load / a faster-loading site; responsiveness = laggy when you tap / responds the instant they tap. Never call lag "slow loading", and never dwell on or pile onto the problem. Layout shift is retired: never say the page jumps, shifts, moves or settles as it loads.
- Only mention their traffic/scale if use_traffic_scale is true.
- No invented numbers, percentages, or dollars. No buzzwords (cutting-edge, best-in-class, innovative, seamless, world-class, leverage, game-changing).
- No defensive hedging ("no agenda", "no pressure", "no pitch", "just trying to help", "sorry to bother").
- Two messages only. First 50-85 words, tight and real. Closing 25-45 words.

Return ONLY valid JSON:
{"first_message":"<the message>","closing_message":"<the follow-up>"}"""


def _val(row, key, default=None):
    v = row.get(key, default)
    if v is None:
        return default
    if isinstance(v, float) and v != v:
        return default
    s = str(v).strip()
    if s in ('', 'None', 'nan'):
        return default
    return v


def sanitize(text):
    """Strip em/en dashes; enforce {first-name} as the only name token."""
    if not text:
        return text
    t = str(text)
    for d in ('—', '–', '―'):
        t = t.replace(' ' + d + ' ', ', ').replace(d, ', ')
    t = t.replace('--', ', ')
    while ', ,' in t:
        t = t.replace(', ,', ',')
    # never out them as a sales target
    t = t.replace('prospect sites', 'client sites').replace('Prospect sites', 'Client sites')
    # normalize any stray placeholder variants to the canonical token
    for variant in ('[first-name]', '[First Name]', '[Name]', '[name]', '[Founder Name]',
                    '{Name}', '{name}', '{{first_name}}', '{first_name}'):
        t = t.replace(variant, '{first-name}')
    return t.strip()


def accurate_visits(row):
    """Source-of-truth monthly visits: the fresh Apify/SimilarWeb figure.
    The pre-filled `monthly_visits` (from Crunchbase) is stale/compromised and must
    NOT be used. Fall back to it only if there is no Apify value at all."""
    visits = _val(row, 'apify_monthly_visits')
    if visits is None:
        visits = _val(row, 'monthly_visits')
    try:
        return int(float(visits)) if visits is not None else None
    except (TypeError, ValueError):
        return None


def _flag(row, col):
    """Return True/False/None for a 'True'/'False'-ish cell."""
    v = _val(row, col)
    if v is None:
        return None
    return str(v).strip().lower() == 'true'


# Cookie NAME -> friendly ADVERTISING product. These are cross-site / retargeting
# identifiers (the serious, consent-required category). Analytics-only cookies (_ga, Clarity)
# are deliberately NOT here: too mild to call out, and a Google Consent-Mode cookieless ping
# is already excluded upstream (it stores nothing). We cite the AD product, never "GTM".
_AD_COOKIE_EXACT = {
    'IDE': 'DoubleClick ads', 'fr': 'Meta ads', 'MUID': 'Microsoft Ads',
    'personalization_id': 'X/Twitter ads',
}
_AD_COOKIE_PREFIX = (
    ('_fbp', 'Meta Pixel'), ('_fbc', 'Meta Pixel'), ('_gcl', 'Google Ads'),
    ('_uet', 'Microsoft Ads'), ('_pin', 'Pinterest ads'),
)


def _ad_cookie_product(name):
    if name in _AD_COOKIE_EXACT:
        return _AD_COOKIE_EXACT[name]
    for pfx, prod in _AD_COOKIE_PREFIX:
        if name.startswith(pfx):
            return prod
    return None


def _cookies_before_consent(row):
    """The actual tracking-cookie NAMES the grader recorded set before consent
    (parsed from page_signals_issues)."""
    issues = str(_val(row, 'page_signals_issues') or '')
    m = re.search(r'tracking cookie\(s\) set before consent:\s*([^;]+)', issues)
    return [c.strip() for c in m.group(1).split(',') if c.strip()] if m else []


def build_secondary_signals(row):
    """Genuinely 'pointable' OBJECTIVE facts beyond the main design/perf/content angle
    (cookie-consent, security, AI-invisibility). Includes a signal ONLY when it's actually a
    concern, so the bundle stays focused on what can truthfully be raised. {} = nothing."""
    sec = {}

    # COOKIE CONSENT: only flag when ACTUAL advertising cookies (cross-site/retargeting
    # identifiers like Meta Pixel / Google Ads) are written before consent. We surface the
    # real product names (not the request-tracker list, which includes exempt things like GTM).
    if _flag(row, 'tracking_before_consent'):
        ad_products = []
        for ck in _cookies_before_consent(row):
            prod = _ad_cookie_product(ck)
            if prod and prod not in ad_products:
                ad_products.append(prod)
        if ad_products:
            sec['ad_cookies_before_consent'] = ad_products
            banner = _flag(row, 'has_consent_banner')
            if banner is not None:
                sec['has_consent_banner'] = banner

    # SSL about to expire (concrete, time-sensitive).
    if _flag(row, 'ssl_expires_soon'):
        days = _val(row, 'ssl_days_to_expiry')
        if days is not None:
            sec['ssl_expires_in_days'] = days

    # Mixed content: insecure http assets can trip browser 'not secure' warnings.
    if _flag(row, 'mixed_content'):
        sec['mixed_content'] = True

    # AI / search invisibility: fully client-rendered => AI engines & crawlers can't
    # read the page; robots blocking AI does the same on purpose.
    if _flag(row, 'ssr_client_rendered'):
        sec['ai_invisible_client_rendered'] = True
    if _flag(row, 'robots_blocks_ai'):
        sec['blocks_ai_crawlers'] = True

    return sec


def extract_proof_from_reasoning(reasoning):
    """Pull the evidence-bearing sentences (Substance + Credibility) out of the grader's
    content_reasoning, stripping the 'Substance N/10 -' scoring prefix. Those two lines quote
    the real customers, metrics, and testimonials shown on the prospect's site — the precinct
    for message 1. We deliberately DROP design_reasoning and the Clarity/Persuasiveness/Depth
    lines: those are opinion/adjectives, and opinion is exactly what must never reach the writer.
    Returns a short list of clean fact sentences, or None.

    We ALSO strip the grader's negative judgment that rides inside these sentences — clauses
    about "placeholder" / "0x" / "0%" / "0+" stats and "undermines / glaring / lacks / generic".
    Those are (a) the grader's opinion, not clean evidence, and (b) usually a count-up animation
    captured at rest (numbers that animate from 0 on scroll), NOT real placeholders — citing them
    tells a founder their site has a problem it may not have (the OmniAI/Monumint lesson). Only the
    positive evidence (named customers, real metrics, backers) should reach the writer."""
    if not reasoning:
        return None
    # a clause is dropped if it carries the grader's negative/placeholder judgment
    NEG = re.compile(r"\b0\s*x\b|\b0\s*%|\b0\+|placeholder|undermin|glaring|\blacks?\b|"
                     r"generic|without any|no named|not explained|merely named|rather than", re.I)
    out = []
    for label in ('Substance', 'Credibility'):
        m = re.search(label + r'\s+\d+/10\s*[—\-:]\s*(.+?)(?=\n[A-Z][a-z]+\s+\d+/10|$)',
                      str(reasoning), re.DOTALL)
        if not m:
            continue
        sentence = ' '.join(m.group(1).split())
        # keep only the clauses that carry no negative-judgment flag
        clauses = re.split(r"(?:,\s*(?:but|though|although|however|despite|severely|while)\b|;|\bbut this is\b)", sentence)
        clean = [c.strip(" ,;.") for c in clauses if c.strip() and not NEG.search(c)]
        kept = ". ".join(clean).strip()
        if len(kept) >= 25:  # drop items that collapse to almost nothing after stripping
            out.append(kept)
    return out or None


def build_prospect(row):
    visits_num = accurate_visits(row)
    p = {
        "name": _val(row, 'Name', 'there'),
        "what_they_do": _val(row, 'Description') or _val(row, 'content_analysis'),
        "monthly_visits": visits_num,
        "traffic_is_high": (visits_num is not None and visits_num >= TRAFFIC_HIGH_THRESHOLD),
        "tech_stack": _val(row, 'tech_stack'),
        "design_score": _val(row, 'design_score'),
        "design_reasoning": _val(row, 'design_comment') or _val(row, 'design_summary'),
        "content_score": _val(row, 'content_score'),
        "content_reasoning": _val(row, 'content_summary') or _val(row, 'content_analysis'),
        "real_user_load_seconds": _val(row, 'field_lcp'),
        "real_user_load_rating": _val(row, 'field_lcp_rating'),
        "real_user_responsiveness_ms": _val(row, 'field_inp'),
        "real_user_responsiveness_rating": _val(row, 'field_inp_rating'),
        # field_cls / field_cls_rating intentionally omitted: layout shift is retired as a signal.
        "fails_google_speed_overall": (str(_val(row, 'cwv_pass')).lower() == 'false') if _val(row, 'cwv_pass') is not None else None,
        "lab_speed_score_REFERENCE_ONLY": _val(row, 'pagespeed_mobile'),
        "desktop_speed_score": _val(row, 'pagespeed_desktop'),
        "a11y_violation_count": _val(row, 'a11y_violation_count'),
        "a11y_critical": _val(row, 'a11y_critical'),
        "a11y_serious": _val(row, 'a11y_serious'),
        "a11y_moderate": _val(row, 'a11y_moderate'),
        "a11y_minor": _val(row, 'a11y_minor'),
        "a11y_lawsuit_risk": (str(_val(row, 'a11y_lawsuit_risk')).lower() == 'true') if _val(row, 'a11y_lawsuit_risk') is not None else None,
        "a11y_top_issues": _val(row, 'a11y_top_issues'),
        "a11y_not_measured": bool(_val(row, 'a11y_error')),
    }
    # PERFORMANCE-LEAD GATE (2026-07-19): only lead on speed when it's GENUINELY, unmistakably poor,
    # with margin so a borderline reading (that drifts) never gets cited. Otherwise pick another angle.
    # Thresholds: desktop lab <= 55 (slow even on the easy test), OR real-user load >= 4.0s, OR
    # real-user tap responsiveness >= 600ms (well past Google's 500ms "poor" line). "needs-improvement"
    # / borderline-poor (e.g. INP 550, desktop 66 like heylua) does NOT qualify.
    def _n(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    _desk, _load, _inp = _n(p.get("desktop_speed_score")), _n(p.get("real_user_load_seconds")), _n(p.get("real_user_responsiveness_ms"))
    p["performance_really_poor"] = bool(
        (_desk is not None and _desk <= 55)
        or (_load is not None and _load >= 4.0)
        or (_inp is not None and _inp >= 600))
    # DESIGN HINT (2026-07-19): design_score alone is unreliable — a harsh grader rates ~78% of sites
    # ~50 ("competent but unremarkable"), which is NOT a reason to pitch a redesign. This flag is an
    # ADVISORY hint, not a hard gate: <=40 usually means genuinely lacking (unfinished/unpolished). The
    # writer reads design_reasoning + this hint and makes its own call. (Very low scores <25 can be
    # broken/blank screenshots, not real assessments — the reasoning says so.)
    _dsc = _n(p.get("design_score"))
    p["design_really_lacking"] = bool(_dsc is not None and _dsc <= 40)
    # CONTENT HINT: content_score is more reliable than design_score (it spreads: mean ~67). <=50 usually
    # means genuinely thin/shallow copy — a real lead, ESPECIALLY for content/education/docs-driven
    # businesses. Advisory, not a gate: read content_reasoning and judge.
    _csc = _n(p.get("content_score"))
    p["content_really_thin"] = bool(_csc is not None and _csc <= 50)
    facts = _val(row, 'proud_facts')
    if facts:
        p["quotable_facts"] = [f.strip() for f in str(facts).split('|') if f.strip()]
    proof = extract_proof_from_reasoning(_val(row, 'content_reasoning'))
    if proof:
        p["proof_from_site"] = proof
    sec = build_secondary_signals(row)
    if sec:
        p["secondary_signals"] = sec
    return {k: v for k, v in p.items() if v is not None}


def _parse_json(text):
    text = (text or '').strip()
    if text.startswith('```'):
        text = text.split('```', 2)[1].lstrip('json').strip()
    return json.loads(text)


def _call(handle, system, user, temperature):
    provider, obj = handle
    if provider == 'claude':
        resp = obj.messages.create(model=CLAUDE_MODEL, max_tokens=CLAUDE_MAX_TOKENS,
                                   temperature=temperature, system=system,
                                   messages=[{"role": "user", "content": user}])
        return _parse_json(resp.content[0].text)
    else:
        import google.generativeai as genai
        model = genai.GenerativeModel(
            GEMINI_MODEL, system_instruction=system,
            generation_config=genai.types.GenerationConfig(
                temperature=temperature, max_output_tokens=GEMINI_MAX_TOKENS,
                response_mime_type="application/json"))
        return _parse_json(model.generate_content(user).text)


def run_analyst(handle, prospect, exclude_accessibility=False):
    extra = "\n\nNOTE: accessibility was re-checked live and no longer holds. Do NOT choose accessibility; pick the next best real signal." if exclude_accessibility else ""
    user = ("Field meanings:\n" + json.dumps(DATA_DICTIONARY, indent=2) +
            "\n\nThe company:\n" + json.dumps(prospect, indent=2, default=str) + extra +
            "\n\nMake your decision now. Return ONLY the JSON object.")
    try:
        return _call(handle, ANALYST_SYSTEM_PROMPT, user, ANALYST_TEMPERATURE)
    except Exception as e:
        return {"priority": "error", "signal_category": "none", "assessment": f"ERROR: {str(e)[:160]}",
                "chosen_signal": "", "signal_evidence": "", "why_it_matters": "",
                "use_traffic_scale": False, "genuine_positive": "", "rejected": ""}


def run_writer(handle, prospect, decision):
    user = ("The company (facts you may use):\n" + json.dumps(prospect, indent=2, default=str) +
            "\n\nThe decision (write about THIS only):\n" + json.dumps(decision, indent=2, default=str) +
            "\n\nWrite the two messages now. Return ONLY the JSON object.")
    try:
        out = _call(handle, WRITER_SYSTEM_PROMPT, user, WRITER_TEMPERATURE)
        return {"first_message": sanitize(out.get('first_message')),
                "closing_message": sanitize(out.get('closing_message'))}
    except Exception as e:
        return {"first_message": "", "closing_message": f"ERROR: {str(e)[:160]}"}


def reverify_a11y(site_url):
    """Live re-check: re-run axe on the site. Returns ('confirmed'|'not_confirmed'|'unchecked', detail)."""
    try:
        import asyncio
        from accessibility import run_axe_on_page

        async def _run():
            from playwright.async_api import async_playwright
            url = site_url if site_url.startswith(('http://', 'https://')) else 'https://' + site_url
            async with async_playwright() as p:
                b = await p.chromium.launch()
                pg = await b.new_page()
                try:
                    await pg.goto(url, wait_until='domcontentloaded', timeout=40000)
                    await pg.wait_for_timeout(3000)
                    res = await run_axe_on_page(pg)
                finally:
                    await b.close()
                return res

        res = asyncio.run(_run())
        if res.get('a11y_error'):
            return 'unchecked', res['a11y_error']
        crit = (res.get('a11y_critical') or 0)
        serious = (res.get('a11y_serious') or 0)
        risk = res.get('a11y_lawsuit_risk')
        if (crit + serious) > 0 or risk:
            return 'confirmed', res.get('a11y_top_issues', '')
        return 'not_confirmed', 'no critical/serious issues on live re-check'
    except Exception as e:
        return 'unchecked', str(e)[:120]


def main():
    ap = argparse.ArgumentParser(description="Two-pass LinkedIn message generator")
    ap.add_argument('input')
    ap.add_argument('-o', '--output')
    ap.add_argument('-l', '--limit', type=int, default=10)
    ap.add_argument('--provider', choices=['claude', 'gemini'], default=None)
    ap.add_argument('--no-reverify', action='store_true', help='skip live accessibility re-check')
    args = ap.parse_args()

    provider = args.provider or ('claude' if os.getenv('ANTHROPIC_API_KEY') else 'gemini')
    if provider == 'claude':
        import anthropic
        handle = ('claude', anthropic.Anthropic()); model_name = CLAUDE_MODEL
    else:
        if not os.getenv('GEMINI_API_KEY'):
            print("ERROR: GEMINI_API_KEY not set"); sys.exit(1)
        import google.generativeai as genai
        genai.configure(api_key=os.getenv('GEMINI_API_KEY'))
        handle = ('gemini', None); model_name = GEMINI_MODEL

    df = read_annotated_csv(args.input)
    gradeable = df[~df['letter_grade'].astype(str).str.strip().isin(['INVALID', ''])].head(args.limit)
    print(f"Two-pass generation for {len(gradeable)} prospects with {model_name}...\n")

    rows = []
    for i, (_, row) in enumerate(gradeable.iterrows(), 1):
        prospect = build_prospect(row)
        domain = _val(row, 'Domain')
        decision = run_analyst(handle, prospect)
        reverify_status = ''

        # Live re-verify accessibility before trusting it
        if (not args.no_reverify and decision.get('signal_category') == 'accessibility'
                and decision.get('priority') in ('high', 'medium') and domain):
            reverify_status, detail = reverify_a11y(domain)
            if reverify_status == 'not_confirmed':
                decision = run_analyst(handle, prospect, exclude_accessibility=True)
            decision['_a11y_reverify_detail'] = detail

        if decision.get('priority') == 'skip':
            msg = {"first_message": "", "closing_message": ""}
        else:
            msg = run_writer(handle, prospect, decision)

        rows.append({
            'Name': prospect.get('name'), 'Domain': domain,
            'monthly_visits': _val(row, 'monthly_visits'), 'letter_grade': _val(row, 'letter_grade'),
            'priority': decision.get('priority'), 'signal_category': decision.get('signal_category'),
            'chosen_signal': decision.get('chosen_signal'), 'signal_evidence': decision.get('signal_evidence'),
            'why_it_matters': decision.get('why_it_matters'), 'use_traffic_scale': decision.get('use_traffic_scale'),
            'genuine_positive': decision.get('genuine_positive'), 'assessment': decision.get('assessment'),
            'proud_facts': _val(row, 'proud_facts'),
            'quotable_fact_to_use': decision.get('quotable_fact_to_use'),
            'quotable_fact_reason': decision.get('quotable_fact_reason'),
            'rejected': decision.get('rejected'), 'a11y_reverify': reverify_status,
            'first_message': msg.get('first_message'), 'closing_message': msg.get('closing_message'),
        })
        print(f"[{i}/{len(gradeable)}] {prospect.get('name')} -> {decision.get('priority')} / "
              f"{decision.get('signal_category')}: {decision.get('chosen_signal')}"
              + (f"  [a11y reverify: {reverify_status}]" if reverify_status else ""))

    out_path = args.output or str(Path(args.input).parent / 'messages_preview.csv')
    pd.DataFrame(rows).to_csv(out_path, index=False)
    print(f"\nSaved {len(rows)} -> {out_path}")


if __name__ == '__main__':
    main()
