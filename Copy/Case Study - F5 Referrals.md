# **F5 Hiring Solutions — Turning a simple idea into a system that runs on its own**

# When Joel reached out about this project, we were pretty excited. We’d worked with him before, and he has a way of describing ideas that makes the core instantly clear. “I want people to be able to refer good companies and actually get rewarded for it,” he said on our first call. “But I don’t want to build a whole app from scratch. I want it inside the F5 ecosystem. I want it simple. And it has to look like us.”

# At that point, the “F5 referral program” existed only as a rough document and a direction. The business logic was there, but the flow wasn’t fully shaped. He wanted users to log in, submit companies, see their referral status, and get credit when something moved forward. He also wanted the team to be able to manage everything without technical oversight. It all sounded reasonable until we got into the details, and that’s where things started to get interesting.

### **The moment the project took shape**

# On the discovery call, we opened a FigJam board and walked through the idea step by step. Joel listed everything he expected the system to do. We added the things the system would need to avoid. We mapped what happens when a referral is submitted, when it needs enrichment, when it needs verification, and when someone on the F5 side has to approve or decline it.

# Halfway through the session, Joel paused and said, “This is why I reached out again. I didn’t even think about half these cases. Now it’s actually making sense.”  That moment is when the project became real. We could see exactly what needed to be built.

### **Designing something that looked like it always belonged to F5**

# F5 already had a strong visual presence, but the original site never came with a formal design system. That meant we had to reverse-engineer one before designing anything new. It’s one thing to create a fresh brand; it’s a different challenge to extend an existing one so seamlessly that no one can see the line where the old ends and the new begins.

# We studied the existing layouts, typography, spacing, icon style, and rhythm of the product pages, then rebuilt those foundations inside Figma. Once the system felt right, we started shaping the screens that would form the referral platform: the landing page, the login and signup flow, the dashboard, empty states, review screens, and the small utilities that make the whole experience feel intentional.

# The design leaned more toward product thinking than typical marketing web pages. It had to feel like software, not a website pretending to be one. And throughout the process, Joel would send short messages like “This feels exactly like F5” or “This is the direction I was hoping for,” which helped keep the momentum steady.

### **When the build finally clicked**

# Development began once the full interface was signed off. Webflow carried the UI because it gave Joel’s team the easiest way to manage the visual layer. Memberstack took care of authentication. Airtable became the source of truth because it matched the way the F5 team already worked. Make handled everything in between: domain checks, dedupe prevention, logo pulling, status syncing, and updating both sides of the system when something changed.

# There was a moment during implementation when it all clicked. We updated a record in Airtable and watched the status change instantly inside the dashboard. That’s when the entire mechanism felt complete: a system that looked like F5, behaved like an internal tool, and didn’t require ongoing engineering.

### **What it meant for Joel and his team**

# After launch, Joel told us, “This looks beautiful, exactly like what I’d wanted”. The referral flow became a new revenue channel for F5 without adding engineering overhead. Users understood the process immediately. Admins had a predictable way to review submissions. The visuals blended perfectly with the main site. And the entire setup could be run by the F5 team using nothing more than Webflow, Airtable, and a few Make scenarios.

# Everything about the system is stable, clear, and simple to operate. It sits quietly in the background, doing its job, which is what good tools are supposed to do.

## **Testimonial**

“Prismport was fantastic to work with\! Very professional, responsive, and delivered exactly what we needed for the F5 Hiring Solutions referral website. Highly recommended\!”  
 — **Joel Deutsch**, Co-Founder & CEO, F5 Hiring Solutions