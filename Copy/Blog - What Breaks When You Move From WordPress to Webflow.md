# WordPress to Webflow Migration: What Actually Breaks (and How to Protect Your SEO)

*The honest version, written by someone who's done this enough times to know where the bodies are buried.*

---

A founder messaged me last year, two days after launching their shiny new Webflow site. Beautiful build. Fast. Their team finally loved updating it.

His message was just: **"Our organic traffic dropped 40% overnight. Did we just make a huge mistake?"**

They hadn't. The site was fine. The *migration* was the problem, or more precisely, the six small things nobody had flagged before they hit publish. We had it back to baseline in about ten days, and a couple of months later they were ahead of where they started.

But I think about that message a lot, because it captures the thing nobody tells you: **Webflow almost never breaks. The seams between your old site and your new one do.** And those seams are invisible until traffic falls off a cliff.

So let me walk you through where it actually goes wrong. Not the marketing-page version. The real one.

---

## First, the reframe: it's not Webflow's fault, and that matters

I want to get this out of the way because it changes how you approach the whole thing.

When people say "our migration broke our SEO," they almost never mean the new platform was worse. Webflow serves clean, fast, semantic markup, and Google likes it fine. What breaks is the **handoff**: the URLs, the redirects, the metadata, the little signals that took your old site years to earn and that don't come along automatically.

Think of it like moving house. The new house is great. But if you don't forward your mail, half your letters go to the old address and the postman gives up. That's a migration gone wrong. The house was never the issue.

Okay. Here's what actually goes missing.

---

## 1. Your URLs: the silent 404 massacre

This is the big one. It's the cause of that 40% drop, nine times out of ten.

WordPress and Webflow structure URLs differently. WordPress loves things like `/2021/08/your-post-title/` or `/?p=482`. Webflow gives you clean slugs like `/blog/your-post-title`. Looks better! But every single URL that changed and *doesn't* have a redirect pointing old to new is now a dead end.

Here's the part that stings: Google has spent years building up authority on those old URLs. Every backlink, every ranking, every bit of trust is attached to the *address*, not the content. Change the address with no forwarding instruction, and you hand all of that back. A visitor hits a 404. So does Googlebot. Do that across a few hundred blog posts and you've quietly deleted your best-performing pages from the internet.

**What this looks like done right:** before anything moves, you export every existing URL (pages, posts, tags, categories, the lot) and build a one-to-one redirect map of 301s to their new homes. Not a lazy "redirect everything to the homepage." That's almost worse; Google reads it as a soft 404 and ignores it. Each old URL points at its specific new equivalent.

If you take one thing from this whole post: **the redirect map is the migration.** Everything else is decoration.

---

## 2. The metadata a plugin was quietly writing for you

If you're on WordPress, there's a very good chance Yoast or RankMath has been doing a lot of invisible work for years: page titles, meta descriptions, Open Graph tags, canonical tags, your XML sitemap, your schema markup.

None of that lives in your content. It lives in the plugin. And plugins don't migrate.

So you rebuild in Webflow, it looks identical to a human, and meanwhile every page has lost its hand-tuned title tag and meta description and reverted to whatever the template spits out. Your social shares lose their preview images. Your structured data, the stuff that earns you rich results and gets you cited in AI answers, is just gone.

This one's sneaky because the site *looks* perfect. The damage is entirely in the parts only crawlers see.

**The fix is unglamorous:** audit and export the title, meta description, canonical, and schema for every meaningful page *before* you migrate, then rebuild them in Webflow's per-page SEO settings and embeds. Tedious. Non-negotiable.

---

## 3. Your CMS: fine in the demo, painful with real content

Webflow's CMS is genuinely great. But it's *structured* in a way WordPress isn't, and that structure is a decision you make up front, not something you can casually reshape later once you've got 300 posts in.

WordPress lets you be messy. Categories, tags, custom fields, a plugin someone installed in 2019 to add "reading time." It all just kind of accretes. Webflow asks you to decide, deliberately: what's a Collection, what's a reference field, what's a multi-reference, how do authors and categories relate to posts.

Where I see this bite people: they model the CMS around the *content they have today*, migrate everything, and then realise they can't filter blog posts by industry, or they need a second author on a post and the field only allows one, or their case studies and their blog are tangled into one Collection when they needed two. Now you're untangling live content instead of planning it.

**Spend the time on the content model before you import a single post.** Map how content actually relates, and how you'll want to *slice* it on the site (by category, by author, by use case), then build the Collections to match. This is an hour of thinking that saves a week of rework.

---

## 4. The plugins that were quietly load-bearing

Every WordPress site has a few plugins that turned out to be holding up the roof. You don't notice them until they're gone.

The usual suspects:
- **Forms:** your contact and demo-request forms were probably a plugin (Gravity Forms, Contact Form 7) wired to your CRM. That wiring doesn't come with you.
- **Gated content / memberships:** anything behind a login needs a real replacement (Memberstack, usually), not a checkbox.
- **Search:** WordPress had search built in. On a content-heavy Webflow site you'll want to plan for it.
- **Multilingual:** if you ran WPML, that's a whole architecture decision, not a setting.
- **Integrations:** the HubSpot tracking, the Intercom widget, the analytics events your marketing team depends on.

The trap isn't that these are hard to rebuild, most are straightforward. It's that they're *invisible in a visual comparison*. The site looks done. Then a week after launch someone notices the demo form has been silently dropping leads into the void.

**Make a plain-English inventory of every plugin and ask one question of each: "what does this actually *do* for the business, and what replaces it?"** Half of them you'll happily delete. The other half are load-bearing, and you want to find that out now, not from an angry sales team.

---

## 5. Internal links and everything pointing at the old addresses

Even with perfect redirects, you've got a pile of links inside your *own* content pointing at old URLs: blog posts linking to other blog posts, "read more" links, CTAs.

Redirects will catch them, so it's not a disaster. But every redirect is a tiny extra hop, and a chain of them (old URL, to a redirect, to another redirect, to the page) genuinely slows things down and dilutes the signal. On a clean migration you update the important internal links to point *directly* at the new URLs, and let redirects be the safety net for the long tail and external backlinks you don't control.

Small thing. But "clean" is the whole game here, and this is part of clean.

---

## 6. The "just copy it exactly" trap

Here's a conversation I have on nearly every migration. The founder says: "Can you just rebuild it exactly as it is, pixel for pixel?"

You can. Sometimes you should. But usually, the reason the site needs migrating is the same reason it shouldn't be copied: it's a few years old, the product has moved on, and the design is carrying baggage from a theme someone bought in 2020.

I'll always give the honest read here, because it's a real fork:
- If your current design genuinely still represents the product well, lift-and-shift is faster and cheaper. Do that.
- If the backend is structurally a mess (nested page builders, conflicting plugins, no naming logic), rebuilding is often *cheaper and faster* than untangling it, on top of giving you a better site.

There's no universal right answer. But "copy it exactly" should be a decision you make on purpose, not a default you reach for because rethinking feels like more work. Often the migration is the best excuse you'll get to fix the things that have been quietly annoying you for two years.

---

## The dip nobody warns you about (and why not to panic)

Last thing, because it'll save you a stressful week.

Even on a flawless migration, there's often a short wobble. Google has to re-crawl your new structure, re-process the redirects, and re-rank everything. For a couple of weeks, your numbers might bounce around. Rankings dip, then recover, sometimes overshooting where they started.

This is normal. It is not the thing going wrong. The thing going wrong looks like a *cliff*, a sharp, sustained drop that doesn't recover, and that's almost always a redirect problem from section one, not a re-crawl wobble.

Know the difference and you won't make the mistake I've watched a few founders make: panicking at week two and frantically "fixing" things that were fine, which actually does cause damage. Hold your nerve. Watch Search Console. Give it a beat.

---

## What I'd actually do, in order

If you're staring down a migration, here's the sequence I'd run, and yes, the boring steps come first on purpose:

1. **Crawl and export every URL** on the current site. This is your source of truth.
2. **Audit metadata and schema** for every page that matters: titles, descriptions, canonicals, structured data.
3. **Inventory plugins** and decide what each one is replaced by (or deleted).
4. **Design the CMS content model** around how you'll actually slice and grow the content, before importing anything.
5. **Build the redirect map**, one old URL to one new URL. Treat this as the heart of the project.
6. **Rebuild** the pages, CMS, forms, integrations, metadata, and internal links pointing at real new URLs.
7. **QA against the export:** every old URL resolves, every form fires, every key page keeps its SEO data.
8. **Launch, submit the new sitemap**, and then *watch and wait* through the re-crawl without flinching.

None of this is exotic. It's just disciplined. A migration goes smoothly almost entirely in proportion to how seriously you took the unglamorous prep, which is exactly why most of the horror stories come from people who rushed straight to the fun part.

---

## The honest bottom line

Moving from WordPress to Webflow is, in my experience, one of the highest-leverage things a growing team can do: a faster site, a CMS your marketers will actually use, and the end of the "can a developer please change this one word" bottleneck. Done with care, teams usually land at equal or better SEO within a few weeks, and a much nicer site to run.

But "done with care" is load-bearing. The platform won't let you down. The seams will, if you let them. So plan the boring parts like they're the whole project, because honestly, they are.

If you'd rather not learn all of this the way that founder did, that's largely what we do; we've built a checklist over the years that catches these before they catch you. Happy to look at your setup and tell you, straight, where the risk actually is.

---

*Written by Shreyas Paul, COO & Co-Founder at Prismport. We're a small Webflow studio that migrates SaaS, AI, and tech teams off WordPress without the traffic horror stories. [Book a 15-minute migration assessment →]*
