"""Canonical case-study registry.

NOT CITED (client instruction, 2026-07-14): Two Dots, Lowr, your360 AI, F5 Hiring Solutions.
NOT CITED (client instruction, 2026-07-18): Qmin AI — the case study doesn't present well enough.
They are removed from this registry entirely, so they cannot be selected or pass verification.

Rebuilt from Copy/Case Study Cards.md (the source copy) after the generate-outreach
SKILL.md was lost. Every slug here was verified live against prismport.co (HTTP 200).

THE SELECTION RULE THAT MATTERS: a case study may only be cited as proof of the thing
message 1 actually pitches. The headline metric IS the proof. Citing Studio Artegra
(a +25% *performance* win) to back a *design* pitch is a non-sequitur, and rewording
its story to sound design-y is fabrication. `proves` encodes that constraint.
"""

CASE_STUDIES = {
    "Flatable": {
        "slug": "flatable",
        "category": "PropTech",
        "metric": "95 on PageSpeed, on both desktop and mobile",
        "story": ("Flatable matches people, not just properties, but the site made that invisible. We "
                  "rebuilt it around two distinct user journeys and kept it fast."),
        "use_when": "two-sided marketplace / two audiences, or a site that must be both rich and fast",
        "proves": {"performance", "design"},
    },
    "Webless AI": {
        "slug": "webless-ai",
        "category": "AI",
        "metric": "bounce rate dropped 20% and time on page grew 32%",
        "story": ("Webless builds generative AI search. The technology was impressive, the website gave "
                  "no one a way in. We rebuilt the brand from scratch, restructured the narrative around "
                  "real use cases, and produced nearly 40 animation frames to make an abstract product tangible."),
        "use_when": "a technical/abstract product whose design doesn't do it justice; design -> measurable result",
        "proves": {"design", "content"},
    },
    "NewsCatcherAPI": {
        "slug": "newscatcher",
        "category": "Enterprise / API",
        "metric": "session time went from around 20 seconds to over 3 minutes, 3,600% more engagement",
        "story": ("NewsCatcher's APIs power enterprise news intelligence for Samsung and major financial "
                  "institutions, but a single-page site wasn't keeping pace. We restructured around real "
                  "use cases and built interactive animations to explain complex workflows."),
        "use_when": "developer/API/enterprise product on a thin or single-page site",
        "proves": {"content", "design"},
    },
    "YourCulture": {
        "slug": "your-culture",
        "category": "Media & Entertainment",
        "metric": "97 on Lighthouse, with perfect accessibility and SEO",
        "story": ("YourCulture activates fan communities for artists and labels. Their site was a single "
                  "page that said almost nothing. We built two full journeys with expressive typography "
                  "and GSAP motion, and still scored 97 on Lighthouse."),
        "use_when": "consumer/media/culture brand that needs expressive, bold, motion-rich design",
        "proves": {"design"},
    },
    "Wonder Phone": {
        "slug": "wondersimple",
        "category": "Consumer Hardware / eCommerce",
        "metric": "sales increased by over 50% after launch",
        "story": ("Wonder Phone is a premium kosher flip phone. The product was exceptional, the website "
                  "wasn't. We designed a scroll-driven 3D experience around the phone's hinge and "
                  "integrated Shopify without losing visual control."),
        "use_when": "eCommerce / physical or consumer product where presentation drives sales",
        "proves": {"design"},
    },
    "Studio Artegra": {
        "slug": "studio-artegra",
        "category": "Creative Agency",
        "metric": "performance improved by over 25% across the site",
        "story": ("Studio Artegra's site had strong visual direction but under the surface it was slow, "
                  "inconsistent across devices, and fragile to update. We went page by page: rebuilt the "
                  "hero animation, fixed responsiveness, repaired a broken filter, cleaned the structure."),
        "use_when": "THE performance study: a site that already looks good but is slow/janky/fragile",
        "proves": {"performance"},
    },
    "Amalia": {
        "slug": "amalia-tech",
        "category": "Life Sciences",
        "metric": "around 25 of the 44 pages were built by their own non-technical team",
        "story": ("Amalia guides pharma manufacturers through dense, regulated work. We built the site as "
                  "a component system with deliberate open and closed slots, so the design could never "
                  "drift no matter who touched it, and their own team built most of the sub-service pages."),
        "use_when": "enterprise/regulated/technical authority, or a large site a lean team must maintain",
        "proves": {"design", "content"},
    },
}

BASE_URL = "https://prismport.co/case-studies/"


def url_for(name: str) -> str:
    return BASE_URL + CASE_STUDIES[name]["slug"]


def eligible_for(signal: str):
    """Studies whose headline result can genuinely back a pitch on `signal`."""
    return [n for n, cs in CASE_STUDIES.items() if signal in cs["proves"]]


def registry_for_prompt(signal: str) -> str:
    lines = []
    for name in eligible_for(signal):
        cs = CASE_STUDIES[name]
        lines.append(
            f"- {name} ({cs['category']})\n"
            f"    exact result (quote this, do not embellish): {cs['metric']}\n"
            f"    what we actually did: {cs['story']}\n"
            f"    use when: {cs['use_when']}\n"
            f"    url: {url_for(name)}"
        )
    return "\n".join(lines)
