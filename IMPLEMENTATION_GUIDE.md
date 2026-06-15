# Implementation Guide: From Data to Outreach
## How to Actually Use This System

---

## Quick Start (First 48 Hours)

### Day 1 Morning: Set Up Your Workflow

**1. Create Your Tracking Spreadsheet** (Google Sheets or Airtable)

Columns:
- Company Name
- Contact Name (find on LinkedIn)
- Title
- LinkedIn URL
- Email (if found)
- Segment (1, 2, 3, or 4)
- Traffic
- PageSpeed Mobile
- Design Score
- Content Score
- Tech Stack
- Funding Amount
- Connection Sent (date)
- Connection Accepted (date)
- Message 1 Sent (date)
- Reply? (Y/N)
- Meeting Booked (date)
- Notes

**2. Export Your Top Prospects from CSV**

Run this query on `/Users/shreyaspaul/code/outreach_signals/data/enriched_20260201_180319.csv`:

```python
# Segment 1: Performance Bleed (TOP PRIORITY)
segment1 = df[
    (df['monthly_visits'] >= 50000) &
    (df['pagespeed_mobile'] < 60) &
    (df['letter_grade'].notna())
].sort_values('monthly_visits', ascending=False)

# Export top 20
segment1.head(20).to_csv('segment1_prospects.csv')
```

**3. Find Decision Makers on LinkedIn**

For each company in your export:
1. Go to company LinkedIn page
2. Filter employees by keywords: "Marketing," "Growth," "CMO," "VP Marketing," "Head of Growth"
3. Avoid: "Manager" (too junior), "Founder/CEO" (unless <20 employees)
4. Best titles: VP Marketing, Head of Growth, CMO, Director of Marketing

---

### Day 1 Afternoon: Send First 10 Connections

**Step-by-step for each prospect**:

1. **Pull their data from CSV**:
   - Monthly visits: `271,846`
   - Mobile PageSpeed: `50`
   - Funding: `$33,99,999.00`
   - Weak areas: `performance`

2. **Choose template** (Segment 1, Variant 1C):
   ```
   You're getting 271K visits/month but mobile PageSpeed is 50. At that volume, slow load times cost you thousands in lost conversions monthly. Quick audit?
   ```

3. **Personalize** (takes 30 seconds):
   - Check their LinkedIn profile for recent post/activity
   - Check if they posted about funding, product launch, hiring
   - If yes, reference it: "Congrats on the Series A. You're getting 271K visits/month but..."

4. **Send connection** with note

5. **Log in tracking sheet**: Company name, contact name, LinkedIn URL, segment, date sent

**Target**: 10 connections Day 1

---

### Day 2: First Messages + More Connections

**Morning**: Check connection accepts from Day 1

For each accept:
1. Wait 2-4 hours (don't message immediately)
2. Pull their data again
3. Send first message using template
4. Log in tracking sheet

**Example**:

**Company**: Remento
**Data**: 271K visits/mo, mobile 50, desktop 72, Webflow, B grade
**Contact**: Sarah Chen, VP Marketing
**Template**: Segment 1, Variant 1C (mobile-specific)

**Customized Message**:
```
Sarah - your site's getting 271K visits/month (impressive for a memory platform).

But your mobile PageSpeed is 50 while desktop is 72. That gap means the site wasn't built mobile-first, and with 60%+ of traffic on mobile, you're running two different conversion rates.

We've fixed this exact issue for 6 companies this year - usually 4 weeks, 30-40% mobile conversion lift. Want to see what's causing the drag?
```

**Afternoon**: Send 10 more connections (Segment 1 or 2)

**Target**: 10 first messages sent, 10 new connections

---

### Days 3-5: Build Pipeline

**Daily rhythm**:
- **Morning**: Send first messages to yesterday's accepts (5-8/day)
- **Midday**: Research + send 10 new connection requests
- **Afternoon**: Follow up with 7-day non-responders

**By end of Week 1**:
- 40 connection requests sent
- 20-25 connections accepted (50% rate)
- 15-20 first messages sent
- 2-4 replies expected

---

## Segment Selection Guide

### Which segment to start with?

**Week 1-2: Segment 1 Only** (Performance Bleed)
- Easiest to message (data is clear-cut)
- Highest urgency (bleeding money now)
- Best response rates (quantifiable pain)
- Build confidence with wins

**Week 3-4: Add Segment 2** (Investment Mismatch)
- More volume (198 prospects vs. 10)
- Requires more research (need to check competitors)
- Longer sales cycle (less urgent)
- Higher deal sizes (more comprehensive rebuilds)

**Week 5+: Layer in Segment 3** (WordPress Time Tax)
- Good for variety
- Operational pain angle (different from performance)
- Works well with marketing/growth hires

**As Needed: Segment 4** (Webflow Underperformers)
- Smaller deals ($5-10K vs. $15-20K)
- Faster close (optimization vs. migration)
- Fill pipeline gaps

---

## Data Extraction Cheat Sheet

### SQL-like Queries for Your CSV

**Segment 1: Top 20 Performance Bleed Prospects**
```python
import pandas as pd
df = pd.read_csv('data/enriched_20260201_180319.csv')

segment1 = df[
    (df['monthly_visits'] >= 50000) &
    (df['pagespeed_mobile'] < 60) &
    (df['letter_grade'].notna())
][['Name', 'Domain', 'monthly_visits', 'pagespeed_mobile',
   'pagespeed_desktop', 'bounce_rate', 'tech_stack',
   'Total Equity Funding Amount', 'design_score', 'content_score']]

print(segment1.sort_values('monthly_visits', ascending=False).head(20))
```

**Segment 2A: Funded Companies with Thin Content**
```python
segment2a = df[
    (df['content_score'] < 50) &
    (df['monthly_visits'] >= 10000) &
    (df['Total Equity Funding Amount'].notna()) &
    (df['letter_grade'].notna())
][['Name', 'Domain', 'content_score', 'content_word_count',
   'monthly_visits', 'Total Equity Funding Amount']]

print(segment2a.sort_values('monthly_visits', ascending=False))
```

**Segment 2B: Funded Companies with Poor Design**
```python
segment2b = df[
    (df['design_score'] < 60) &
    (df['monthly_visits'] >= 10000) &
    (df['Total Equity Funding Amount'].notna()) &
    (df['letter_grade'].notna())
][['Name', 'Domain', 'design_score', 'monthly_visits',
   'Total Equity Funding Amount', 'design_comment']]

print(segment2b.sort_values('monthly_visits', ascending=False))
```

**Segment 3: WordPress Companies (Funded)**
```python
segment3 = df[
    (df['is_wordpress'] == True) &
    (df['Total Equity Funding Amount'].notna()) &
    (df['letter_grade'].notna())
][['Name', 'Domain', 'monthly_visits', 'pagespeed_mobile',
   'all_tech_detected', 'marketing_tools', 'Total Equity Funding Amount']]

print(segment3.sort_values('monthly_visits', ascending=False))
```

---

## LinkedIn Research Process

### For Each Prospect (5 minutes max)

**Step 1: Company Page** (1 min)
- Recent posts (funding, product launches, hiring)
- Employee count (influences who to target)
- Headquarters location (timezone for follow-ups)

**Step 2: Find Decision Maker** (2 min)
- Search: `site:linkedin.com/in/ "VP Marketing" OR "CMO" OR "Head of Growth" [company name]`
- Or use LinkedIn's "People" filter on company page
- Look for: 1-3 years tenure (not brand new, not leaving soon)

**Step 3: Profile Scan** (2 min)
- Recent posts (anything about website, performance, growth?)
- Shared connections (mutual intro possible?)
- Background (came from similar company?)
- Activity level (active = higher response rate)

**Decision Tree**:
- If <50 employees → Target Head of Marketing or Director
- If 50-200 employees → Target VP Marketing or CMO
- If 200+ employees → Target VP Growth or Head of Digital
- If no marketing hire → Target CEO/Founder (only if <30 employees)

---

## Message Customization Workflow

### Base Template → Personalized Message (60 seconds)

**Template** (Segment 1):
```
Your site's getting [X] visits/month but loads in [Y] seconds on mobile. At that volume, every second costs you [Z]% of conversions.

We've rebuilt sites for funded companies at your stage - typically see 20-40% conversion lifts from speed alone.

No pitch, but if you want to see what's slowing you down, I can send a breakdown. Worth 15 min?
```

**Step 1: Fill in data** (15 sec)
```
Your site's getting 271K visits/month but loads in 8.2 seconds on mobile. At that volume, every second costs you 7-10% of conversions.
```

**Step 2: Add context** (20 sec)
Check their LinkedIn/website for:
- Recent funding? Add: "Congrats on the Series A."
- Hiring for growth? Add: "Saw you're hiring a Growth Lead - they'll want this fixed."
- Recent press? Add: "Saw your TechCrunch feature."
- None of the above? Use template as-is.

**Step 3: Adjust tone** (15 sec)
- If they're super formal (enterprise SaaS) → Keep it professional
- If they're casual (consumer product) → More conversational
- If they're technical founder → Add more technical details

**Step 4: Proof** (10 sec)
- Read out loud (does it sound human?)
- Spell check
- Verify their name is correct

**Total time**: 60 seconds per message

---

## Follow-Up Cadence

### The 7-14-21 Rule

**Day 0**: Connection request sent
**Day 0-2**: Connection accepted
**Day 0 (+2-4 hours)**: First message sent

**Day 7**: Follow-up #1 (if no reply)
- Different angle or new data point
- Example: "Forgot to mention - your desktop score is fine (83) but mobile is 36. The gap suggests mobile wasn't prioritized. Worth fixing?"

**Day 14**: Follow-up #2 (if no reply)
- Break-up or value offer
- Example: "No worries if timing's off. Ran the full diagnostic anyway - attached. Shows you're losing ~$30K/year from mobile performance. No obligation to reply."

**Day 21**: Final touch (optional)
- Pure value, no ask
- Example: "Leaving this here: [link to case study]. Similar company, similar traffic, we cut their load time from 8s to 2s in 4 weeks. Converted 40% better. That's it - figured you'd find it interesting."

**After Day 21**: Move to "nurture" list
- Q2 check-in (3 months later)
- Trigger-based (if they get funding, press, etc.)

---

## Email + LinkedIn Strategy

### When to Add Email

**Trigger**: After LinkedIn message #1 with no reply after 3 days

**Why**: Different channel, can be longer/more detailed, includes attachments

**Email Timing**:
- Day 3 after first LinkedIn message
- Don't reference LinkedIn message (feels desperate)
- New angle or deeper dive

**Example Flow**:

**Day 0**: LinkedIn connection + message (performance angle)
**Day 3**: Email (competitive angle)
**Day 7**: LinkedIn follow-up (break-up)
**Day 14**: Email with attachment (diagnostic)

### Finding Emails

**Tools**:
1. Hunter.io (find company email pattern)
2. Apollo.io (verified emails)
3. Manual: firstname@company.com or first.last@company.com
4. LinkedIn profile (some list emails)

**Verification**:
- Use NeverBounce or ZeroBounce
- Don't send to unverified emails (hurts deliverability)

---

## Response Rate Optimization

### What to Track

**Weekly metrics**:
- Connection requests sent
- Accept rate (target: 40-50%)
- First message reply rate (target: 15-25%)
- Meeting booked rate (target: 8-12% of replies)

**Monthly metrics**:
- Proposals sent
- Close rate
- Average deal size
- Time to close

### When to Iterate

**If accept rate <30%**:
- Connection request too salesy
- Profile not credible (update your headline, about section)
- Targeting too broad (narrow to better fit)

**If reply rate <10%**:
- Message not specific enough (add more of their data)
- Value prop unclear (focus on pain, not solution)
- Too long (cut 30%)

**If meeting rate <5%**:
- Ask too big (try softer CTA: "worth a look?" vs. "book a call")
- Not enough value offered first (send audit/breakdown first)
- Wrong person (targeting too junior/senior)

---

## Objection Handling Scripts

### "We just redesigned"

**What they mean**: We don't want to redo work we just paid for

**Your response**:
```
I saw that - design looks solid. But design and performance are different problems.

Your visual layer scores well (72/100) but mobile PageSpeed is 36. That means the design is good but technical implementation is killing conversions.

We can keep 90% of your current design and just rebuild the technical layer for speed. 4-week project, keeps your brand intact.

Want to see what that looks like?
```

---

### "We're working with another agency"

**What they mean**: We have a vendor relationship already

**Your response**:
```
Fair enough. Out of curiosity, are they addressing the mobile performance issue? (Your mobile score is 36 - that's costing you 30-40% of conversions.)

If they're on it, great. If not, we can jump in for just that piece and leave everything else to them.

Worth a 10-min call to see if it makes sense?
```

---

### "We don't have budget right now"

**What they mean**: Not convinced it's worth the investment OR wrong timing

**Your response**:
```
Totally understand. Quick math to put on your radar:

Your site gets 200K visits/month. Your mobile conversion rate is probably 2-3% (industry avg). If we improve mobile PageSpeed from 36 to 70, you'd likely see 30-40% lift in mobile conversions.

That's ~150-200 additional conversions/month. If your LTV is $500+, that's $75-100K/year in recovered revenue.

Project cost is $15K. Pays for itself in 2-3 months, then it's pure upside.

When budget opens up, let's revisit. Sound fair?
```

---

### "Just send me a proposal"

**What they mean**: I want to evaluate without talking (OR brush-off)

**Your response**:
```
Happy to, but I'd be sending you a generic proposal that probably doesn't fit your exact needs.

Proposals vary widely based on:
- Number of pages (10 vs. 50)
- Integrations (CRM, analytics, ad pixels)
- Custom functionality (forms, calculators, etc.)

10-min call and I can send a fixed-price proposal same day that actually matches your scope. Usually lands $12-18K for companies at your stage.

[Calendar link] - worth it to get accurate pricing?
```

---

## Weekly Planning Template

### Monday

**Research (30 min)**:
- Export 10 Segment 1 prospects from CSV
- Find decision makers on LinkedIn
- Log in tracking sheet

**Outreach (20 min)**:
- Send 10 connection requests
- Personalize each with their data

**Follow-ups (15 min)**:
- Reply to weekend responses
- Send first messages to connections from last Friday

---

### Tuesday

**Research (30 min)**:
- Export 10 Segment 2 prospects
- Find decision makers

**Outreach (20 min)**:
- Send 10 connection requests
- First messages to Monday's accepts

**Follow-ups (15 min)**:
- 7-day follow-ups (prospects from last Tuesday)

---

### Wednesday

**Research (30 min)**:
- Export 10 Segment 1 or 2 prospects
- Deeper dive (check competitors, recent press)

**Outreach (20 min)**:
- Send 10 connection requests
- First messages to Tuesday's accepts

**Follow-ups (15 min)**:
- Reply to new responses
- Email touch for 3-day non-responders

---

### Thursday

**Outreach (30 min)**:
- First messages to Wednesday's accepts
- Send 5-10 more connection requests

**Follow-ups (30 min)**:
- 14-day break-ups (prospects from 2 weeks ago)
- Reply to conversations in progress

---

### Friday

**Analytics (30 min)**:
- Update tracking sheet
- Calculate week's metrics:
  - Accept rate
  - Reply rate
  - Meetings booked
- Identify what worked/what didn't

**Planning (30 min)**:
- Plan next week's targets
- Adjust messaging if needed
- Export next batch of prospects

---

## Tools Stack

### Required
- **LinkedIn Sales Navigator** ($99/mo) - Advanced search, more InMails
- **Google Sheets** - Tracking (free)
- **Calendar booking tool** - Calendly ($10/mo) or Cal.com (free)

### Recommended
- **Apollo.io** ($49/mo) - Email finding + verification
- **Hunter.io** ($49/mo) - Email finding
- **Loom** ($8/mo) - Video messages for follow-ups
- **TextExpander** ($3/mo) - Template shortcuts

### Optional
- **Phantombuster** ($30/mo) - LinkedIn automation (use carefully)
- **Clay** ($150/mo) - Data enrichment at scale
- **Airtable** ($20/mo) - Better tracking than Sheets

---

## Red Flags to Avoid

**Don't message if**:
- Company has <10 employees (too small for $15K project)
- Company has >500 employees (procurement hell, 6+ month sales cycle)
- Site was updated in last 30 days (check Wayback Machine)
- They're hiring a marketing agency (they'll bundle web work)
- They're in obvious decline (traffic down 50%+ in 6 months)

**Don't send connection if**:
- Profile has <100 connections (inactive or fake)
- Profile has no photo (low engagement likelihood)
- Person just joined company <1 month ago (not settled yet)
- Person is leaving company (job hunting, won't prioritize)

---

## Success Metrics (First 30 Days)

### Week 1
- 40 connection requests sent
- 20 accepts (50% rate)
- 15 first messages
- 2-3 replies
- 0-1 meetings booked

### Week 2
- 40 connection requests
- 20 accepts
- 20 first messages
- 3-5 replies
- 1-2 meetings booked

### Week 3
- 40 connection requests
- 25 accepts (improving targeting)
- 25 first messages
- 4-6 replies
- 1-2 meetings booked
- 0-1 proposals sent

### Week 4
- 40 connection requests
- 25 accepts
- 25 first messages
- 5-8 replies
- 2-3 meetings booked
- 1-2 proposals sent

### Month 1 Totals
- 160 connection requests
- 90 accepts (56% rate)
- 85 first messages
- 14-22 replies (16-26% reply rate)
- 5-9 meetings (23-40% meeting rate)
- 2-4 proposals sent
- 0-1 deals closed (if lucky)

---

## Month 2+ Scaling

Once you've validated messaging (15%+ reply rate), scale:

**Volume increase**:
- Week 5-8: 60 connection requests/week (from 40)
- Month 3+: 80-100 connection requests/week

**Add channels**:
- Email cold outreach (100/week)
- Twitter/X (for prospects who are active there)
- Video messages (Loom for warm follow-ups)

**Optimize**:
- Build case studies from first clients
- A/B test messaging variants
- Segment by industry (fintech vs. healthtech messaging)

**Expected Month 2-3**:
- 10-15 meetings/month
- 4-6 proposals/month
- 1-2 deals closed/month
- $20-40K MRR from outbound

---

## Final Checklist Before You Start

- [ ] CSV data exported and organized
- [ ] Tracking spreadsheet created
- [ ] LinkedIn profile optimized (headline, about, experience)
- [ ] Calendar booking link set up
- [ ] Email signature updated
- [ ] Templates saved (TextExpander or doc)
- [ ] First 10 prospects researched
- [ ] Connection requests drafted and ready
- [ ] 2 hours blocked daily for outreach (next 30 days)

**Now send the first 10 connections and don't stop until you hit your weekly targets.**

The system works if you work the system.
