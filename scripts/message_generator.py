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
    "monthly_visits": "Approx monthly visitors. traffic_is_high tells you if it clears the bar for scale framing.",
    "traffic_is_high": "True = visits are meaningful enough to use the 'with your traffic, even a small slice is a real number' framing. False = do NOT lean on scale; find another true benefit.",
    "tech_stack": "What the site is built on.",
    "design_score": "0-100 how professional/distinctive the design looks. <50 = weak/generic for a funded company.",
    "design_note": "Human read on the design.",
    "content_score": "0-100 how clear/substantive/credible the copy is. <55 = thin, unclear, or unproven.",
    "content_note": "Human read on the copy.",
    "real_user_load_seconds": "REAL-USER load time (s). Good <=2.5, needs-improvement 2.5-4, poor >4. Claim 'slow to load' only if ni/poor.",
    "real_user_load_rating": "good / needs-improvement / poor.",
    "real_user_responsiveness_ms": "REAL-USER lag on tap/click (ms). Good <=200, poor >500. If poor: 'laggy when you tap' (NOT slow loading).",
    "real_user_responsiveness_rating": "good / needs-improvement / poor.",
    "real_user_layout_shift": "REAL-USER layout shift. Good <=0.1, poor >0.25. If poor: 'page jumps around as it loads' (NOT slow loading).",
    "real_user_layout_shift_rating": "good / needs-improvement / poor.",
    "fails_google_speed_overall": "True = fails Google's real-user thresholds overall; use the specific failing metric to decide what to say.",
    "lab_speed_score_REFERENCE_ONLY": "Synthetic lab score. NEVER base a speed claim on this. If real_user_* are absent, do not mention speed at all.",
    "a11y_violation_count": "Total accessibility violations found.",
    "a11y_critical": "Count of CRITICAL accessibility issues.",
    "a11y_serious": "Count of SERIOUS accessibility issues.",
    "a11y_moderate": "Count of moderate accessibility issues.",
    "a11y_minor": "Count of minor accessibility issues.",
    "a11y_lawsuit_risk": "True = violates the exact rules ADA lawsuits cite.",
    "a11y_top_issues": "The specific accessibility problems found (plain descriptions).",
    "a11y_not_measured": "True = accessibility could NOT be measured (e.g. blocked). Treat as unknown, NOT as clean.",
    "quotable_facts": "Specific credible facts the company is proud of, verified to appear on their site (e.g. '40k Discord community', 'used by 2,000 teams', 'raised $12M'). Great to quote as a genuine, flattering hook when relevant. Use the exact number/name; never alter it.",
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
   - real_user_layout_shift poor -> the page jumps around as it loads
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
- Never invent facts, numbers, percentages, or dollar amounts. Only use what's in the data.

Return ONLY valid JSON:
{"assessment":"<2-3 sentences: the real state of the site, a founder's read>",
"signal_category":"performance|design|content|accessibility|other|none",
"chosen_signal":"<the one thing to write about, short>",
"signal_evidence":"<the exact field values behind it, e.g. real_user_responsiveness_ms 710 = poor>",
"why_it_matters":"<the business consequence in plain terms>",
"use_traffic_scale":true|false,
"genuine_positive":"<one real strength to credit, or 'none'>",
"priority":"high|medium|low|skip",
"quotable_fact_to_use":"<the exact fact to weave in, verbatim, or 'none'>",
"quotable_fact_reason":"<why you will use it, or why none fits>",
"rejected":"<other signals you considered and why you did not pick them>"}"""

# ---------------------------------------------------------------------------
# Pass B — Writer
# ---------------------------------------------------------------------------
WRITER_SYSTEM_PROMPT = """You are a founder firing off a quick, genuine LinkedIn DM to another founder. You noticed something real about their site and you actually care. You are NOT filling in a template, writing marketing copy, or selling. You're just a sharp person who took a look and had a thought worth sharing. It should read like a real human typed it in one go.

You are GIVEN a decision: the one issue to talk about, why it matters, whether you can mention their traffic, a genuine positive, and maybe one quotable fact. Build the message around THAT, but write it like a person, not a form.

WHAT GOOD SOUNDS LIKE (write in this spirit, do not copy these):
- "hey {first-name}, good to connect. went down a bit of a rabbit hole on your site this week, the 40k discord you've built is no joke. one thing that bugged me though, it's pretty laggy when you tap around on mobile, and with the traffic you're pulling that's gotta be costing you signups. how are you thinking about that side of things?"
- "{first-name}, quick one. the proof on your site is unreal, trusted by disclosure is a flex most brands would kill for. which is exactly why the site itself feels like a bit of a letdown, it's clean but reads like a template, not like a brand creators would obsess over. is a refresh anywhere on the radar, or way down the list?"

Notice: it flows as one natural thought. There's a point of view, a little warmth and edge. The positive and the problem are tied together, not bolted on. It sounds like a person, not a checklist.

HOW TO MAKE IT FEEL HUMAN (this is the whole job):
- Open like a real person reaching out: a quick natural greeting works ("hey {first-name}, good to connect", "{first-name}, quick one", "hey {first-name}"). Vary it. Then get into it like you're mid-thought.
- Do NOT march through "reason -> problem -> but good thing -> question" as separate beats. Let it flow. Often the strongest move is to TIE the good and the bad together (e.g. "the proof is unreal, which is exactly why the generic site is a shame"), so it reads like one real observation, not a compliment sandwich.
- Have a touch of personality and a point of view. A little candor or wry edge is good ("that's gotta sting", "most brands would kill for that", "no judgment, every site has one"). Sound like you mean it.
- The question at the end should sound like something you'd actually ask a peer, casual and open ("how are you thinking about that?", "is that on the radar or way down the list?", "curious if that's bugging you too or just me?"). Never a yes/no, never "want the report?".
- Read it back: would a smart, busy founder actually type this to someone they respect? If any sentence sounds like marketing or a template, rewrite it.

USING THE FACTS:
- If quotable_fact_to_use is not "none", work it in naturally, in your own words, as a real nod to what they've pulled off. Keep the actual number/name EXACT, but do not paste the fact in verbatim or robotically. ("the 40k discord you've built is no joke" not "you have a Discord community of 40K+ Members"). If "none", do not invent one.

CLOSING message: a short, no-pressure nudge sent only if they don't reply. Casual. This is where you mention you've got an internal tool you run client sites through, it flagged this (along with some stuff they're doing well), and you're happy to share what it found.

HARD RULES (non-negotiable, even while sounding natural):
- Address them ONLY as the literal token {first-name}. NEVER invent or guess a real name.
- NEVER use an em dash, en dash, or double hyphen. Commas or periods only.
- All lowercase feel, like a real DM. No corporate polish, no emojis, no exclamation marks.
- No jargon (no LCP, INP, CLS, WCAG, contrast, headers, render). Plain words only.
- Performance wording must match the decision's metric: load = slow to load; responsiveness = laggy when you tap; layout shift = jumps around as it loads. Never call lag or shift "slow loading".
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


def build_prospect(row):
    visits = _val(row, 'monthly_visits')
    try:
        visits_num = int(float(visits)) if visits is not None else None
    except (TypeError, ValueError):
        visits_num = None
    p = {
        "name": _val(row, 'Name', 'there'),
        "what_they_do": _val(row, 'Description') or _val(row, 'content_analysis'),
        "monthly_visits": visits_num,
        "traffic_is_high": (visits_num is not None and visits_num >= TRAFFIC_HIGH_THRESHOLD),
        "tech_stack": _val(row, 'tech_stack'),
        "design_score": _val(row, 'design_score'),
        "design_note": _val(row, 'design_comment'),
        "content_score": _val(row, 'content_score'),
        "content_note": _val(row, 'content_analysis'),
        "real_user_load_seconds": _val(row, 'field_lcp'),
        "real_user_load_rating": _val(row, 'field_lcp_rating'),
        "real_user_responsiveness_ms": _val(row, 'field_inp'),
        "real_user_responsiveness_rating": _val(row, 'field_inp_rating'),
        "real_user_layout_shift": _val(row, 'field_cls'),
        "real_user_layout_shift_rating": _val(row, 'field_cls_rating'),
        "fails_google_speed_overall": (str(_val(row, 'cwv_pass')).lower() == 'false') if _val(row, 'cwv_pass') is not None else None,
        "lab_speed_score_REFERENCE_ONLY": _val(row, 'pagespeed_mobile'),
        "a11y_violation_count": _val(row, 'a11y_violation_count'),
        "a11y_critical": _val(row, 'a11y_critical'),
        "a11y_serious": _val(row, 'a11y_serious'),
        "a11y_moderate": _val(row, 'a11y_moderate'),
        "a11y_minor": _val(row, 'a11y_minor'),
        "a11y_lawsuit_risk": (str(_val(row, 'a11y_lawsuit_risk')).lower() == 'true') if _val(row, 'a11y_lawsuit_risk') is not None else None,
        "a11y_top_issues": _val(row, 'a11y_top_issues'),
        "a11y_not_measured": bool(_val(row, 'a11y_error')),
    }
    facts = _val(row, 'proud_facts')
    if facts:
        p["quotable_facts"] = [f.strip() for f in str(facts).split('|') if f.strip()]
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
