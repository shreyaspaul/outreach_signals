# Archived docs — superseded, do not follow

These five documents were written on 16 Jun 2026, **before** the current outreach messaging system
existed. They are kept for history only. Every one of them describes an approach we have since
moved away from, so following them will produce the wrong work.

**Read instead:** `PROJECT_STATE.md` (what is true now) → `CLAUDE.md` (how the repo works) →
`specs/outreach-app-plan.md` (where it is going) → `.claude/skills/generate-outreach/SKILL.md`
(how messages are actually written).

| File | Why it is wrong now |
|---|---|
| `MESSAGE_TEMPLATES.md` | A library of fill-in-the-blank LinkedIn templates by segment. **Directly contradicts current practice** — messages are written per prospect, led by an inference drawn from that company's audit data. Templates are the thing we deliberately stopped doing. |
| `LINKEDIN_OUTREACH_STRATEGY.md` | Pain-point / problem-first messaging strategy. Current rule is positive, opportunity-framed only: never judge the site, never sell with fear or loss. |
| `OUTREACH_README.md` | Quick-start for the template-based flow. The flow is now `prep_bundles dump` → write → `assemble` → `qa_check` → `build_outreach_list`. |
| `OUTREACH_SUMMARY.md` | Executive summary of the same superseded strategy. |
| `IMPLEMENTATION_GUIDE.md` | End-to-end guide predating batching (`data/<batch>/`, `LEADS_BATCH`), the objective-signal graders, and the whole message-generation loop. |

Nothing here is imported or executed by any script.
