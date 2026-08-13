# LinkedIn Outreach System - Quick Start Guide

## What This Is

A complete, data-driven LinkedIn outreach system for WordPress → Webflow migration services (or ANY web quality improvement), targeting funded SaaS/tech companies with $10-20K deal sizes.

Based on analysis of **316 fully-enriched prospects** with actual PageSpeed scores, traffic data, design scores, and content scores.

---

## The Core Insight

**Your original signal (Funded + WordPress) was too narrow.**

Only 27 WordPress companies exist in the dataset. The real opportunity is **198 funded companies with measurable website quality issues** - regardless of platform.

The signal isn't "they use WordPress." It's "their website is provably underperforming for their growth stage."

---

## The 4 Documents

### 1. OUTREACH_SUMMARY.md (START HERE)
**Read time: 5 minutes**

Executive summary of the entire strategy:
- The 4 segments (prioritized)
- Message framework
- First week action plan
- Key metrics

**→ Read this first to understand the approach.**

---

### 2. LINKEDIN_OUTREACH_STRATEGY.md
**Read time: 30 minutes**

Complete strategic framework:
- Deep dive into each segment
- Why each works (psychology + data)
- Multi-channel sequencing (LinkedIn + Email)
- Response handling
- A/B testing ideas
- Do's and don'ts

**→ Read this to understand the WHY behind every tactic.**

---

### 3. MESSAGE_TEMPLATES.md
**Read time: 15 minutes**

Ready-to-use copy for:
- Connection requests (by segment)
- First messages (by segment)
- Follow-ups (7-day, 14-day)
- Response handlers (objections)
- Break-up messages

**→ Use this when actually writing messages.**

---

### 4. IMPLEMENTATION_GUIDE.md
**Read time: 20 minutes**

Step-by-step execution:
- Day 1-5 action plan
- Data extraction scripts
- LinkedIn research process (5 min per prospect)
- Message customization workflow (60 sec per message)
- Weekly planning template
- Tools stack
- Success metrics

**→ Follow this to actually DO the outreach.**

---

## The 4 Segments (Priority Order)

### Segment 1: Performance Bleed ⚡️ (START HERE)
- **Volume**: 10 prospects
- **Signal**: 50K+ monthly visitors + mobile PageSpeed <60
- **Hook**: "Your site gets X visits/month but loads in Y seconds. That's costing you conversions daily."
- **Why it works**: Quantifiable pain, urgent, data-driven

**Best prospects**:
- Megaphone: 3.5M visits/mo, mobile 36
- Magic Hour: 2M visits/mo, mobile 43
- Design Arena: 1M visits/mo, mobile 28

---

### Segment 2: Investment Mismatch 💰
- **Volume**: 198 prospects
- **Signal**: Funded (Series A+) + 2+ quality issues (design <60, content <60, or performance <60)
- **Hook**: "You raised Series A but your website looks/performs like seed stage. That gap costs you enterprise credibility."
- **Why it works**: Ego/status, enterprise sales angle

**Sub-segments**:
- 2A: Thin Content (5 prospects, avg 263K traffic)
- 2B: Poor Design (12 prospects, avg 46K traffic)
- 2C: Multiple Issues (4 prospects, 20K+ traffic)

---

### Segment 3: WordPress Time Tax ⏱️
- **Volume**: 27 prospects
- **Signal**: WordPress + funded + marketing team
- **Hook**: "Every 'quick marketing change' that needs dev time costs you velocity. At your stage, speed matters more than stability."
- **Why it works**: Operational pain, growth blocker

---

### Segment 4: Webflow Underperformers 🔧
- **Volume**: 7 prospects
- **Signal**: Already on Webflow but performance/design/content <60
- **Hook**: "You're on Webflow but performance is 37. Either bad template or migration never got optimized."
- **Why it works**: No platform change friction, faster close

---

## How to Start (Next 2 Hours)

### Hour 1: Setup

**1. Export your first prospects** (5 min)
```bash
source venv/bin/activate
python scripts/export_prospects.py --segment 1 --limit 10
```

This creates `prospects_segment_1_[timestamp].csv` with:
- Company name
- Domain
- Traffic
- PageSpeed scores
- Design/content scores
- Funding amount

**2. Create tracking spreadsheet** (10 min)

Use Google Sheets or Airtable with columns:
- Company Name
- Contact Name
- Title
- LinkedIn URL
- Segment
- Traffic
- PageSpeed Mobile
- Connection Sent (date)
- Connection Accepted (date)
- Message 1 Sent (date)
- Reply? (Y/N)
- Notes

**3. Find decision makers** (30 min)

For each company in your export:
1. Go to company LinkedIn page
2. Find: VP Marketing, Head of Growth, CMO, Director of Marketing
3. Avoid: Managers (too junior), CEOs (unless <20 employees)
4. Add to tracking sheet

**4. Optimize your LinkedIn profile** (15 min)

Your profile should position you as:
- Expert in web performance/conversion optimization
- Work with funded SaaS companies
- Data-driven approach

Update:
- Headline: "Web Performance & Conversion Optimization | Helping Funded SaaS Companies Fix Sites That Slow Growth"
- About: 2-3 paragraphs on what you do, who you help, results you've driven
- Experience: List relevant projects, metrics, case studies

---

### Hour 2: First Outreach

**1. Customize connection requests** (30 min)

Use templates from `MESSAGE_TEMPLATES.md`, section "Segment 1: Performance Bleed"

**Template**:
```
Saw you hit 300K visits/month. Your mobile PageSpeed is 36 - at that traffic, every second costs you conversions. Worth a quick look?
```

**Personalized** (for Megaphone, 3.5M visits, mobile 36):
```
Saw you hit 3.5M visits/month on Megaphone. Mobile PageSpeed is 36 - at that traffic volume, every second of load time costs you thousands in conversions. Worth a quick look?
```

**Send 10 connection requests** (3 min each = 30 min total)

**2. Set calendar reminder** (2 min)

- Tomorrow 10am: Check connection accepts, send first messages
- Tomorrow 2pm: Research + send 10 more connections
- Friday 3pm: Review week's metrics

---

## Daily Workflow (30-45 min/day)

### Morning (15 min)
1. Check yesterday's connection accepts
2. Send first messages (use templates, personalize with their data)
3. Reply to any responses

### Midday (15 min)
4. Research 10 new prospects
5. Send 10 connection requests

### Afternoon (15 min)
6. Follow up with 7-day non-responders
7. Update tracking sheet

---

## Weekly Targets

| Week | Connections | Accepts | Messages | Replies | Meetings |
|------|-------------|---------|----------|---------|----------|
| 1 | 40 | 20 (50%) | 15 | 2-3 | 0-1 |
| 2 | 40 | 20 | 20 | 3-5 | 1-2 |
| 3 | 40 | 25 | 25 | 4-6 | 1-2 |
| 4 | 40 | 25 | 25 | 5-8 | 2-3 |

**Month 1**: 160 requests, 90 accepts (56%), 85 messages, 14-22 replies (16-26%), 5-9 meetings

---

## Message Framework

### Connection Request (300 char max)
```
[Specific data point] + [Why it matters] + [Soft question]
```

**Example**:
```
Saw you hit 271K visits/month. Mobile PageSpeed is 50 - at that volume, slow load costs you thousands in conversions monthly. Quick audit?
```

---

### First Message (after accept, 2-4 hours later)
```
[Their data] + [Business implication] + [Value offer] + [Soft CTA]
```

**Example**:
```
Your site's getting 1M+ visits/month but loads in 8 seconds on mobile. At that volume, every second of delay costs you 7-10% of conversions.

We've rebuilt sites for funded companies at your stage - typically see 20-40% conversion lifts just from speed improvements.

No pitch, but if you want to see what's slowing you down, I can send a breakdown. Worth 15 min?
```

---

## Key Principles

### DO:
✓ Use their EXACT data (271K visits, mobile 50, bounce 79%)
✓ Lead with business impact, not features
✓ Reference their funding/growth stage
✓ Sound like a peer, not a vendor
✓ Offer value before asking for time
✓ Keep messages under 100 words

### DON'T:
✗ Trash their platform ("WordPress sucks")
✗ Use buzzwords ("cutting-edge," "innovative")
✗ Send generic templates
✗ Ask for 60-min calls upfront
✗ Pitch Webflow features
✗ Sound desperate ("just checking in")

---

## Response Handling Cheat Sheet

### "Not a priority"
```
Totally get it. Just FYI: at 200K visits/month, a 1-second speed improvement = 7-10% conversion lift. For most SaaS that's 6-figure ARR impact annually.

When it becomes a priority, we move fast (4-6 weeks). I'll check back in Q2.
```

### "Send pricing"
```
Happy to, but varies based on scope. 30-min call to understand your setup and I can send fixed-price proposal same day. Usually $12-18K for companies at your stage.

[Calendar link] work?
```

### "We just redesigned"
```
Design looks solid. But design and performance are different problems.

Your visual scores well but mobile PageSpeed is 36. We can keep 90% of your design and just rebuild the technical layer for speed.

Want to see what that looks like?
```

---

## Tools Required

**Essential** ($99/mo):
- LinkedIn Sales Navigator - Better search, more InMails

**Recommended** (~$50/mo):
- Apollo.io or Hunter.io - Email finding
- Calendly - Booking

**Optional**:
- Loom - Video messages
- TextExpander - Template shortcuts

---

## Quick Command Reference

### Export prospects by segment:
```bash
# Segment 1 (Performance Bleed) - TOP PRIORITY
python scripts/export_prospects.py --segment 1 --limit 20

# Segment 2A (Thin Content)
python scripts/export_prospects.py --segment 2a --limit 20

# Segment 2B (Poor Design)
python scripts/export_prospects.py --segment 2b --limit 20

# Segment 3 (WordPress)
python scripts/export_prospects.py --segment 3 --limit 20

# All segments
python scripts/export_prospects.py --segment all
```

### View enriched data:
```bash
# Open in Excel/Numbers/Google Sheets
open data/enriched_20260201_180319.csv
```

---

## Success Metrics

**Week 1 Target**:
- 40 connection requests sent
- 20 accepts (50% rate)
- 15 first messages sent
- 2-3 replies
- 0-1 meetings booked

**Month 1 Target**:
- 160 connection requests
- 90 accepts (56%)
- 85 first messages
- 14-22 replies (16-26%)
- 5-9 meetings
- 2-4 proposals sent
- 0-1 deals closed

**Month 2-3 Target**:
- 10-15 meetings/month
- 4-6 proposals/month
- 1-2 deals closed/month
- $20-40K revenue from outbound

---

## Troubleshooting

### Low accept rate (<30%)?
- Connection request too salesy
- Profile not credible (update headline/about)
- Targeting wrong people (go higher - VPs not Managers)

### Low reply rate (<10%)?
- Not specific enough (use MORE of their data)
- Too long (cut 30%)
- Value prop unclear (focus on their pain, not your solution)

### Low meeting rate (<5%)?
- Ask too big (try "worth a look?" vs. "book a call")
- Not enough value offered first
- Wrong person (try one level up)

---

## What to Expect

### Week 1
You'll feel like you're bothering people. You're not. If you're using their data and showing real insights, you're providing value.

### Week 2
First replies will come in. Some will be polite "not interested," some will be "tell me more." Both are wins - you're learning.

### Week 3
First meeting booked. You'll realize the messaging works when you're specific and data-driven.

### Week 4
Pipeline building. You'll have 5-10 active conversations, 2-3 meetings, 1-2 proposals in progress.

### Month 2
Systems and rhythm established. You know which messages work, which segments respond best, how to handle objections.

### Month 3
First deals closing. Proof of concept complete. Ready to scale.

---

## Files in This System

```
OUTREACH_README.md                      ← You are here
OUTREACH_SUMMARY.md                     ← Executive summary (read first)
LINKEDIN_OUTREACH_STRATEGY.md           ← Full strategy (30 min read)
MESSAGE_TEMPLATES.md                    ← Ready-to-use templates
IMPLEMENTATION_GUIDE.md                 ← Step-by-step execution

scripts/export_prospects.py             ← Export prospects by segment
data/enriched_20260201_180319.csv       ← Your prospect data
```

---

## Next Steps

1. **Read OUTREACH_SUMMARY.md** (5 min)
2. **Export Segment 1 prospects** (1 min)
   ```bash
   python scripts/export_prospects.py --segment 1 --limit 10
   ```
3. **Find 10 decision makers on LinkedIn** (30 min)
4. **Send 10 personalized connection requests** (30 min)
5. **Set reminder for tomorrow to check accepts**

Then repeat daily for 30 days.

The system works if you work the system.

---

## Questions?

All the answers are in the 4 strategy documents. Use Ctrl+F to search:
- "How do I handle [objection]" → MESSAGE_TEMPLATES.md
- "What do I say when [situation]" → MESSAGE_TEMPLATES.md
- "Why does [segment/tactic] work" → LINKEDIN_OUTREACH_STRATEGY.md
- "How do I [execute task]" → IMPLEMENTATION_GUIDE.md

Everything is documented. Just execute.
