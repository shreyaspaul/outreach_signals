#!/usr/bin/env python3
"""
Tech Stack & Marketing Detector
Detects website technology stacks, marketing tools, and ad pixels.
"""

import pandas as pd
import requests
from urllib.parse import urlparse
import time
import re
import sys
from pathlib import Path


# Marketing & Analytics detection patterns
# premium: True ONLY for tools with NO free tier (must be paying to use)
MARKETING_PATTERNS = {
    # Analytics - most have free tiers, so not premium
    'segment': {
        'patterns': ['cdn.segment.com', 'cdn.segment.io', 'api.segment.io'],
        'premium': True,  # Exception: uncommon, indicates data sophistication
    },
    'amplitude': {
        'patterns': ['cdn.amplitude.com', 'api.amplitude.com', 'amplitude.min.js'],
        'premium': True,  # Exception: uncommon, indicates data sophistication
    },
    'mixpanel': {
        'patterns': ['cdn.mxpnl.com', 'mixpanel.com/track', 'mixpanel.min.js', 'api.mixpanel.com'],
        'premium': False,  # Has free tier (20M events/mo)
    },
    'heap': {
        'patterns': ['heap.io', 'heapanalytics.com', 'heap-'],
        'premium': False,  # Has free tier (10K sessions/mo)
    },
    'fullstory': {
        'patterns': ['fullstory.com', 'fs.js', 'edge.fullstory.com'],
        'premium': False,  # Has free tier (1,000 sessions/mo)
    },
    'hotjar': {
        'patterns': ['hotjar.com', 'static.hotjar.com', 'hj.js'],
        'premium': False,  # Has free tier
    },
    'posthog': {
        'patterns': ['posthog.com', 'app.posthog.com', 'posthog.js'],
        'premium': False,  # Has generous free tier
    },
    'google_analytics': {
        'patterns': ['google-analytics.com', 'googletagmanager.com/gtag', 'ga.js', 'gtag.js', 'G-', 'UA-'],
        'premium': False,  # Free
    },
    'plausible': {
        'patterns': ['plausible.io'],
        'premium': False,  # Has free self-hosted
    },

    # Marketing Automation - these are truly paid
    'hubspot_marketing': {
        'patterns': ['js.hs-scripts.com', 'js.hubspot.com', 'hs-analytics', 'hubspot.com/analytics', 'hbspt.forms'],
        'premium': False,  # Has free CRM, can't distinguish paid marketing hub
    },
    'marketo': {
        'patterns': ['marketo.com', 'munchkin.js', 'mktoresp.com', 'marketo.net'],
        'premium': True,  # NO free tier - enterprise only ($$$)
    },
    'pardot': {
        'patterns': ['pardot.com', 'pi.pardot.com', 'pd.js'],
        'premium': True,  # NO free tier - Salesforce product ($1,250+/mo)
    },
    'customer_io': {
        'patterns': ['customer.io', 'customerioforms', 'track.customer.io'],
        'premium': True,  # NO free tier - paid only ($100+/mo)
    },
    'activecampaign': {
        'patterns': ['activehosted.com', 'activecampaign.com', 'trackcmp.net'],
        'premium': True,  # NO free tier - paid only ($29+/mo)
    },
    'klaviyo': {
        'patterns': ['klaviyo.com', 'static.klaviyo.com', 'a.klaviyo.com'],
        'premium': False,  # Has free tier (250 contacts)
    },
    'mailchimp': {
        'patterns': ['mailchimp.com', 'list-manage.com', 'chimpstatic.com'],
        'premium': False,  # Has free tier
    },
    'convertkit': {
        'patterns': ['convertkit.com', 'convertkit-mail'],
        'premium': False,  # Has free tier (1,000 subscribers)
    },

    # Chat & Support
    'intercom': {
        'patterns': ['intercom.io', 'js.intercomcdn.com', 'widget.intercom.io', 'intercom-'],
        'premium': True,  # NO free tier anymore - paid only ($74+/mo)
    },
    'drift': {
        'patterns': ['drift.com', 'js.driftt.com', 'drift-'],
        'premium': False,  # Has free tier (limited)
    },
    'zendesk': {
        'patterns': ['zendesk.com', 'zdassets.com', 'zopim.com'],
        'premium': False,  # Has free tier for startups
    },
    'crisp': {
        'patterns': ['crisp.chat', 'client.crisp.chat'],
        'premium': False,  # Has free tier
    },
    'livechat': {
        'patterns': ['livechat.com', 'livechatinc.com', 'cdn.livechatinc.com'],
        'premium': False,  # Has free trial, then paid - but can't confirm
    },
    'freshdesk': {
        'patterns': ['freshdesk.com', 'freshworks.com', 'freshchat'],
        'premium': False,  # Has free tier
    },

    # A/B Testing
    'optimizely': {
        'patterns': ['optimizely.com', 'cdn.optimizely.com', 'optimizely.min.js'],
        'premium': True,  # NO free tier - enterprise only ($$$)
    },
    'vwo': {
        'patterns': ['visualwebsiteoptimizer.com', 'vwo.com', 'wingify.com', 'dev.visualwebsiteoptimizer'],
        'premium': False,  # Has free tier (limited testing)
    },
    'launchdarkly': {
        'patterns': ['launchdarkly.com', 'ld.js'],
        'premium': False,  # Has free tier (up to 1,000 MAU)
    },
    'split_io': {
        'patterns': ['split.io', 'cdn.split.io'],
        'premium': False,  # Has free tier
    },

    # Tag Managers
    'google_tag_manager': {
        'patterns': ['googletagmanager.com/gtm.js', 'GTM-'],
        'premium': False,  # Free
    },
    'tealium': {
        'patterns': ['tealium.com', 'tealiumiq.com', 'tags.tiqcdn.com'],
        'premium': True,  # NO free tier - enterprise only ($$$)
    },
}

# Ad Pixels (indicates active ad spend)
AD_PIXEL_PATTERNS = {
    'google_ads': {
        'patterns': ['googleadservices.com', 'googlesyndication.com', 'googleads.g.doubleclick', 'conversion.js', 'AW-'],
    },
    'facebook_pixel': {
        'patterns': ['connect.facebook.net', 'facebook.com/tr', 'fbevents.js', 'fbq('],
    },
    'linkedin_insight': {
        'patterns': ['snap.licdn.com', 'linkedin.com/insight', 'linkedin.com/px'],
    },
    'twitter_pixel': {
        'patterns': ['static.ads-twitter.com', 'analytics.twitter.com', 't.co/i/adsct'],
    },
    'tiktok_pixel': {
        'patterns': ['analytics.tiktok.com', 'tiktok.com/i18n'],
    },
    'pinterest_tag': {
        'patterns': ['pintrk', 'ct.pinterest.com', 'pinterest.com/ct'],
    },
    'reddit_pixel': {
        'patterns': ['redditmedia.com', 'reddit.com/pixel'],
    },
    'snapchat_pixel': {
        'patterns': ['sc-static.net', 'tr.snapchat.com'],
    },
    'bing_ads': {
        'patterns': ['bat.bing.com', 'clarity.ms', 'bing.com/bat'],
    },
    'quora_pixel': {
        'patterns': ['quora.com/_/ad'],
    },
    'taboola': {
        'patterns': ['taboola.com', 'trc.taboola.com'],
    },
    'outbrain': {
        'patterns': ['outbrain.com', 'widgets.outbrain.com'],
    },
    'criteo': {
        'patterns': ['criteo.com', 'criteo.net', 'static.criteo.net'],
    },
    'adroll': {
        'patterns': ['adroll.com', 'd.adroll.com'],
    },
}


# Tech stack detection patterns
TECH_PATTERNS = {
    # CMS / Page Builders
    'wordpress': {
        'html': ['wp-content', 'wp-includes', 'wp-json', 'wp-admin', 'wp-login.php'],
        'meta_generator': ['wordpress'],
        'headers': {'x-powered-by': 'wordpress', 'link': 'wp-json'},
    },
    'webflow': {
        'html': ['webflow.com', 'w-webflow', 'wf-page', 'data-wf-site', 'data-wf-page'],
        'meta_generator': ['webflow'],
        'headers': {'x-powered-by': 'webflow'},
    },
    'wix': {
        'html': ['wix.com', 'wixstatic.com', 'wix-code', '_wix_browser_sess', 'x-wix'],
        'meta_generator': ['wix.com'],
        'headers': {'x-wix': ''},
    },
    'squarespace': {
        'html': ['squarespace.com', 'static.squarespace', 'sqsp', 'squarespace-cdn'],
        'meta_generator': ['squarespace'],
        'headers': {'x-servedby': 'squarespace'},
    },
    'shopify': {
        'html': ['shopify.com', 'cdn.shopify', 'shopify-section', 'myshopify.com'],
        'meta_generator': ['shopify'],
        'headers': {'x-shopid': '', 'x-shopify': ''},
    },
    'ghost': {
        'html': ['ghost.io', 'ghost-portal', 'data-ghost'],
        'meta_generator': ['ghost'],
        'headers': {'x-ghost': ''},
    },
    'drupal': {
        'html': ['drupal.org', '/sites/default/files', 'drupal.js', 'drupal-'],
        'meta_generator': ['drupal'],
        'headers': {'x-drupal': '', 'x-generator': 'drupal'},
    },
    'joomla': {
        'html': ['/media/jui/', '/media/system/', 'joomla'],
        'meta_generator': ['joomla'],
        'headers': {},
    },
    'hubspot': {
        'html': ['hubspot.com', 'hs-scripts.com', 'hubspot-wrapper', 'hs-banner'],
        'meta_generator': ['hubspot'],
        'headers': {'x-hs': ''},
    },
    'contentful': {
        'html': ['contentful.com', 'ctfassets.net'],
        'meta_generator': ['contentful'],
        'headers': {},
    },
    'framer': {
        'html': ['framer.com', 'framerusercontent.com', 'data-framer'],
        'meta_generator': ['framer'],
        'headers': {},
    },

    # JavaScript Frameworks
    'react': {
        'html': ['react', 'data-reactroot', 'data-reactid', '__NEXT_DATA__', '_next/'],
        'meta_generator': [],
        'headers': {},
    },
    'next.js': {
        'html': ['__NEXT_DATA__', '_next/', 'next/head', 'nextjs'],
        'meta_generator': ['next.js'],
        'headers': {'x-nextjs': '', 'x-powered-by': 'next.js'},
    },
    'gatsby': {
        'html': ['gatsby', '___gatsby', 'gatsby-image', 'gatsby-resp-image'],
        'meta_generator': ['gatsby'],
        'headers': {'x-gatsby': ''},
    },
    'vue': {
        'html': ['vue.js', 'vuejs', 'data-v-', '__vue__', 'vue-router'],
        'meta_generator': [],
        'headers': {},
    },
    'nuxt': {
        'html': ['__NUXT__', '_nuxt/', 'nuxt.js', 'nuxtjs'],
        'meta_generator': ['nuxt'],
        'headers': {},
    },
    'angular': {
        'html': ['ng-version', 'ng-app', 'angular.js', 'angular.min.js', 'ng-controller'],
        'meta_generator': [],
        'headers': {},
    },
    'svelte': {
        'html': ['svelte', '__svelte', 'sveltekit'],
        'meta_generator': ['sveltekit', 'svelte'],
        'headers': {},
    },

    # Static Site Generators
    'hugo': {
        'html': ['hugo', 'gohugo.io'],
        'meta_generator': ['hugo'],
        'headers': {},
    },
    'jekyll': {
        'html': ['jekyll'],
        'meta_generator': ['jekyll'],
        'headers': {},
    },
    'eleventy': {
        'html': ['11ty', 'eleventy'],
        'meta_generator': ['eleventy'],
        'headers': {},
    },

    # E-commerce
    'magento': {
        'html': ['/mage/', '/skin/frontend/', 'varien', 'magento-init', 'mage/cookies'],
        'meta_generator': ['magento'],
        'headers': {'x-magento': ''},
    },
    'bigcommerce': {
        'html': ['bigcommerce', 'cdn.bcapp'],
        'meta_generator': ['bigcommerce'],
        'headers': {},
    },
    'woocommerce': {
        'html': ['woocommerce', 'wc-', 'add_to_cart'],
        'meta_generator': ['woocommerce'],
        'headers': {},
    },
}


def normalize_url(url: str) -> str:
    """Ensure URL has proper scheme."""
    if not url:
        return ""
    url = url.strip()
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    return url


def detect_tech_stack(url: str, timeout: int = 10) -> dict:
    """
    Detect website technology stack, marketing tools, and ad pixels.

    Returns dict with:
        - detected_tech: list of detected technologies
        - primary_tech: most likely primary CMS/builder (or 'custom' if none detected)
        - is_wordpress: bool (for backwards compatibility)
        - indicators: dict of tech -> indicators found
        - marketing_tools: list of detected marketing/analytics tools
        - ad_pixels: list of detected advertising pixels
        - has_premium_analytics: bool (Signal 3 indicator)
        - error: str if request failed
    """
    result = {
        'detected_tech': [],
        'primary_tech': 'unknown',
        'is_wordpress': False,
        'indicators': {},
        'marketing_tools': [],
        'ad_pixels': [],
        'has_premium_analytics': False,
        'error': None
    }

    if not url:
        result['error'] = 'Empty URL'
        return result

    url = normalize_url(url)

    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        html = response.text.lower()
        html_original = response.text  # Keep original case for some patterns
        response_headers = {k.lower(): v.lower() for k, v in response.headers.items()}

        # Extract generator meta tag
        generator_match = re.search(r'<meta[^>]*name=["\']generator["\'][^>]*content=["\']([^"\']+)["\']', html)
        if not generator_match:
            generator_match = re.search(r'<meta[^>]*content=["\']([^"\']+)["\'][^>]*name=["\']generator["\']', html)
        generator = generator_match.group(1).lower() if generator_match else ''

        detected = {}

        # Check each tech pattern
        for tech, patterns in TECH_PATTERNS.items():
            indicators = []

            # Check HTML patterns
            for pattern in patterns.get('html', []):
                if pattern in html:
                    indicators.append(f'html:{pattern}')

            # Check generator meta tag
            for gen_pattern in patterns.get('meta_generator', []):
                if gen_pattern in generator:
                    indicators.append(f'generator:{gen_pattern}')

            # Check headers
            for header_name, header_value in patterns.get('headers', {}).items():
                if header_name in response_headers:
                    if not header_value or header_value in response_headers[header_name]:
                        indicators.append(f'header:{header_name}')

            if indicators:
                detected[tech] = indicators

        result['detected_tech'] = list(detected.keys())
        result['indicators'] = detected
        result['is_wordpress'] = 'wordpress' in detected

        # Determine primary tech (priority: CMS/builders over frameworks)
        cms_priority = ['wordpress', 'webflow', 'wix', 'squarespace', 'shopify',
                       'ghost', 'drupal', 'joomla', 'hubspot', 'framer', 'contentful']
        framework_priority = ['next.js', 'gatsby', 'nuxt', 'react', 'vue', 'angular', 'svelte']
        static_priority = ['hugo', 'jekyll', 'eleventy']

        for tech in cms_priority:
            if tech in detected:
                result['primary_tech'] = tech
                break
        else:
            for tech in framework_priority:
                if tech in detected:
                    result['primary_tech'] = tech
                    break
            else:
                for tech in static_priority:
                    if tech in detected:
                        result['primary_tech'] = tech
                        break
                else:
                    if detected:
                        result['primary_tech'] = list(detected.keys())[0]
                    else:
                        result['primary_tech'] = 'custom/static'

        # Detect marketing tools
        marketing_detected = []
        premium_tools = []
        for tool, config in MARKETING_PATTERNS.items():
            for pattern in config['patterns']:
                # Check both lowercase and original case for patterns like GTM-, G-, UA-
                if pattern in html or pattern in html_original:
                    marketing_detected.append(tool)
                    if config.get('premium', False):
                        premium_tools.append(tool)
                    break

        result['marketing_tools'] = marketing_detected
        result['has_premium_analytics'] = len(premium_tools) > 0

        # Detect ad pixels
        ad_detected = []
        for pixel, config in AD_PIXEL_PATTERNS.items():
            for pattern in config['patterns']:
                if pattern in html or pattern in html_original:
                    ad_detected.append(pixel)
                    break

        result['ad_pixels'] = ad_detected

    except requests.exceptions.Timeout:
        result['error'] = 'Timeout'
    except requests.exceptions.SSLError:
        result['error'] = 'SSL Error'
    except requests.exceptions.ConnectionError:
        result['error'] = 'Connection Error'
    except Exception as e:
        result['error'] = str(e)[:50]

    return result


# Backwards compatibility alias
def check_wordpress(url: str, timeout: int = 10) -> dict:
    """
    Check if a website is running WordPress.
    (Backwards compatible wrapper around detect_tech_stack)
    """
    result = detect_tech_stack(url, timeout)
    return {
        'is_wordpress': result['is_wordpress'],
        'indicators': result['indicators'].get('wordpress', []),
        'error': result['error']
    }


def process_csv(input_path: str, output_path: str = None, delay: float = 1.0):
    """
    Process a CSV file and add tech stack detection columns.

    Args:
        input_path: Path to input CSV with 'Website' column
        output_path: Path for output CSV (default: input_techstack.csv)
        delay: Seconds to wait between requests (be polite)
    """
    # Read input CSV
    df = pd.read_csv(input_path)

    if 'Website' not in df.columns:
        print("Error: CSV must have a 'Website' column")
        sys.exit(1)

    # Set default output path
    if not output_path:
        input_file = Path(input_path)
        output_path = input_file.parent / f"{input_file.stem}_techstack.csv"

    total = len(df)
    print(f"Processing {total} websites...")
    print("-" * 50)

    # Process each website
    results = []
    tech_counts = {}

    for idx, row in df.iterrows():
        url = row['Website']
        company = row.get('Company Name', 'Unknown')

        print(f"[{idx + 1}/{total}] {company}: {url}")

        result = detect_tech_stack(url)
        results.append(result)

        if result['error']:
            print(f"         Error: {result['error']}")
        else:
            print(f"         Tech: {result['primary_tech']}", end='')
            if len(result['detected_tech']) > 1:
                others = [t for t in result['detected_tech'] if t != result['primary_tech']]
                print(f" (also: {', '.join(others)})")
            else:
                print()

            # Count tech
            tech_counts[result['primary_tech']] = tech_counts.get(result['primary_tech'], 0) + 1

        # Rate limiting
        if idx < total - 1:
            time.sleep(delay)

    # Add results to dataframe
    df['tech_stack'] = [r['primary_tech'] for r in results]
    df['all_tech_detected'] = [', '.join(r['detected_tech']) if r['detected_tech'] else '' for r in results]
    df['is_wordpress'] = [r['is_wordpress'] for r in results]
    df['tech_indicators'] = [str(r['indicators']) if r['indicators'] else '' for r in results]
    df['tech_check_error'] = [r['error'] if r['error'] else '' for r in results]

    # Save output
    df.to_csv(output_path, index=False)
    print("-" * 50)
    print(f"Results saved to: {output_path}")

    # Summary
    error_count = sum(1 for r in results if r['error'])
    print(f"\nSummary:")
    print(f"  Total: {total}")
    print(f"  Errors: {error_count}")
    print(f"\nTech breakdown:")
    for tech, count in sorted(tech_counts.items(), key=lambda x: -x[1]):
        print(f"  {tech}: {count}")

    return df


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Detect tech stack from a CSV of websites')
    parser.add_argument('input', help='Input CSV file path')
    parser.add_argument('-o', '--output', help='Output CSV file path')
    parser.add_argument('-d', '--delay', type=float, default=1.0,
                        help='Delay between requests in seconds (default: 1.0)')

    args = parser.parse_args()

    process_csv(args.input, args.output, args.delay)
