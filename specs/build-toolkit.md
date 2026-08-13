# Build toolkit — which Claude skills we use to build the outreach app

_Researched 2026-08-14. Companion to `specs/outreach-app-plan.md` — that plan says WHAT to build,
this says what we build it WITH._

Verified against the actual install on this machine: the official marketplace
(`~/.claude/plugins/marketplaces/claude-plugins-official/`) carries **287 plugins, 38 of them
Anthropic-authored**; the rest are vendor plugins distributed through an official channel, which is
not the same as Anthropic guidance. Every skill named below was confirmed present.

## The headline finding

**The skill ecosystem helps with two of our three concerns and barely touches the third.** Nothing
available anywhere — built-in, Anthropic, or vendor — addresses durable job state, idempotent task
design, or resumability. That is our top-stated concern and the reason `orchestrator.py` grew a
hand-rolled resume. It is the gap we fill ourselves (see "Custom skills to write").

Vendor plugins that sound like a direct hit are not. `redis-development` is eight datastore skills
(`redis-core`, `redis-search`, `redis-semantic-cache`, …) with **nothing on job-queue reliability** —
our Redis is a dumb broker. The Postgres plugins (`neon`, `supabase`, `cloud-sql-postgresql`) are
connection MCPs for a hosted product; none teach schema design or task keying.

## Shortlist — 5

### 1. `claude-api` — built-in, already active. Highest conviction.
Ships `shared/prompt-caching.md`, `shared/models.md`, `shared/token-counting.md`, and
`python/claude-api/batches.md`.

**Where:** Phase 2, the generation service — the cached system prefix (plan §4.2), Batch API costing
(§4.6), and both Batch caveats (out-of-order results keyed on `custom_id`; `fallbacks` rejected on
Batches).

**Why:** we have already been burned by API facts recalled from memory. `CLAUDE.md` records that
Opus pricing was first assumed at $15/$75 per MTok when it is **$5/$25** — a 3× error that shaped a
model decision. The plan now commits to `claude-opus-5`, `effort: high`, adaptive thinking and
$0.06/prospect: every one of those is a model-id, param or pricing claim, the exact category models
hallucinate. The skill's rule is "never answer from memory."

**Do first:** verify `claude-opus-5` is a real model id and that the §4.6 rate table is current,
*before* any generation code exists.

### 2. `skill-creator` — `skill-creator@claude-plugins-official`. Non-obvious, high value.
Not for authoring skills — for its **eval harness** (`eval-viewer/generate_review.py`, plus a
documented draft → test prompts → benchmark → rewrite loop).

**Where:** Phases 0–2, iterating on `generate-outreach/SKILL.md` before it moves into the `prompts`
table.

**Why:** this is the missing mechanism behind our worst incident. **795 messages, 0 QA flags,
campaign pulled.** Regex QA proves the absence of banned patterns; it cannot prove quality. The only
thing that catches that before a batch is spent is running the prompt on a held-out sample and
judging the output. We have no such loop today — the CTA ban landing at message 412 is what its
absence looks like.

**Caveat:** the tooling targets Claude Code *skills*; our prompt ends up in Postgres behind the API.
The methodology transfers, the scripts may not. Use it while SKILL.md is still a skill, expect to
port the harness in Phase 2.

### 3. `frontend-design` — `frontend-design@claude-plugins-official`. Recommended WITH steering.
**Where:** the review-queue card (Phase 2) and the VA shell (Phase 4).

**Why:** our stated goal is "feel like a real app, not a pile of CSVs stitched together." The default
LLM output for an admin UI is generic shadcn/Tailwind, which reads as exactly that pile. The review
queue is the screen a VA lives in all day.

**⚠️ The one entry that can actively hurt.** The skill's brief is expressive — "take one real
aesthetic risk," "the hero is a thesis." That is marketing-page framing and it is **wrong** for a
dense internal ops tool, where familiarity, information density and keyboard flow beat
distinctiveness. Always steer it: *"internal review tool, dense, keyboard-driven, hundreds of cards
per session, optimise for scan speed."* Un-steered it produces a beautiful landing page for a queue
nobody can work fast in.

### 4. `webapp-testing` — `anthropics/skills` (copy into `.claude/skills/`, not in the marketplace).
Playwright-driven E2E; ships `scripts/with_server.py` for multi-server lifecycle, called black-box so
it does not eat context.

**Where:** the end-to-end VA path (upload → progress → approve → export), and the Phase 1 migration
test: import `batch_01`, re-export, diff against `outreach_ready_v3.csv`, **zero rows changed**.

**Why:** multi-server handling matches our shape (FastAPI + RQ worker + Postgres), and Playwright is
already installed for `website_grader.py`, so it adds no dependency.

**Don't install day one:** the built-in `run` skill already covers "launch it and confirm the change
works," costs nothing, and is available now. Use `run` through Phases 1–2; `webapp-testing` earns its
place around Phase 4 when we want repeatable scripted E2E.

### 5. `checkpoint` — already installed at `~/.claude/skills/checkpoint/`. Free, and it fits.
**Where:** every phase.

**Why:** a 5-phase build across many sessions, and this project already runs on the pattern
(`PROJECT_STATE.md` is the canonical handoff). The failure mode is documented, not hypothetical: the
v3 loop has been **paused since 2026-07-21 at 594/793**, and before 2026-08-13 nothing had been
committed since 2026-07-09.

## Rejected, with reasons

| Skill | Why not |
|---|---|
| `code-modernization` | Closest near-miss — its extract-rules → transform arc is literally scripts→app. But it targets legacy code with *undocumented* business rules. Ours are documented: plan §3.4 already lists reuse/rewrite/retire per module. We have done the extract-rules phase; the rest is ceremony. |
| `feature-dev` | Explore → architect → review. We already have `outreach-app-plan.md`, more specific than its architect would produce, plus a project `analyst` subagent. Duplication. |
| `redis-development` | Eight *datastore* skills, nothing on queue reliability. Our Redis is a dumb broker. |
| `neon` / `supabase` / `prisma` / `cloud-sql-postgresql` / `aiven` | Vendor connection MCPs. None teach schema design or idempotent task keying, and we have not picked a host. Install the one we choose, after we choose it. |
| `railway` | Deploy plugin; host undecided (Render/Fly/Railway). Revisit Phase 4. |
| `logfire` | FastAPI/asyncpg/httpx auto-instrumentation, genuinely relevant to "where did the run fail" — but adds a vendor before we have an app. Revisit Phase 3–4 alongside the cost meter. |
| `playwright` (MCP) | We already drive Playwright from Python. Duplicates it and burns context. |
| `mcp-builder` | We are building a web app, not an MCP server. |
| `web-artifacts-builder`, `theme-factory`, `artifact-design`, `dataviz` | Target claude.ai artifacts/charts. Our progress board is counts and statuses. |
| `doc-coauthoring` | The spec is written. |
| `hookify` | Tempting as a guard against `qa_check.py --fix` (the money-spending footgun) — but the app *deletes* that footgun. Don't solve what you're removing. |
| `security-guidance` / `claude-security` | Real, but Phase 4, once there is deployed auth and server-side keys. Built-in `security-review` likely suffices. |

**One partial pull:** `pr-review-toolkit` ships a `silent-failure-hunter` agent. Every incident in
plan §2 is a silent failure — `build_outreach_list.py` overwriting the live campaign, `assemble` not
enforcing its 18-field schema so 256/594 rows lost review columns, batch mode dropping the msg-2
opener in ~135/359 messages. Unusually exact match to our history. Default to the built-in
`code-review`; add this one agent on the Phase 1 and Phase 3 diffs.

## Custom skills to write (the real gap)

Written with `skill-creator`. The repo already has this pattern working twice: `generate-outreach`
and `analyze-site`.

1. **`stage-task` — the task contract. Highest value.** Encodes how an enrichment stage is written:
   idempotent, keyed `(batch_id, domain, stage)`, own status row, terminal-vs-retryable states (plan
   §6 needs a terminal "couldn't grade" for Cloudflare-blocked sites, not infinite retry), cost
   recording, per-provider rate limiters, and the **wrap-don't-rewrite** rule for the ~12 modules
   §3.4 moves verbatim. Carries the Phase 3 proof obligation: re-enrich a 50-row slice and match
   existing column values. Write it once and stage 11 comes out the same shape as stage 1 — which is
   what "robustness as a property of the system" actually means.
2. **`message-rules` — one source of truth.** Plan §6 names the risk: rules live in SKILL.md prose,
   `RUN_LOOP.md`, and `qa_check.py` regexes — three copies that drift. A project skill holding the
   canonical list, from which prompt body and QA regexes are generated or cross-checked. Natural home
   for the `outreach-message-dont-list` and `outreach-reasoning-spine` knowledge currently in memory
   files only.
3. **`batch-lint` — reading the whole batch.** Plan §4.3c. The one capability in-session Claude had
   that a stateless API call structurally cannot: n-gram frequency across openers and closers,
   case-study distribution against the 30% ceiling, signal-category distribution. The counting is
   code; the judgement ("is this repetitive enough to flag?") is the skill. This caught 412 identical
   closers and NewsCatcher at 52% of msg-2s, and currently has **no owner** in the target architecture.

## Install order

```bash
# now — Phases 0/2
/plugin install skill-creator@claude-plugins-official
# claude-api, code-review, run, checkpoint: already available, nothing to install

# when the review-queue UI starts — Phase 2
/plugin install frontend-design@claude-plugins-official

# when repeatable E2E on the VA path is wanted — Phase 4
#   webapp-testing: github.com/anthropics/skills/tree/main/skills/webapp-testing
#   (copy into .claude/skills/ — not in the plugin marketplace)

# optional, on the Phase 1 and 3 diffs
/plugin install pr-review-toolkit@claude-plugins-official   # for silent-failure-hunter
```

## Sources
- `github.com/anthropics/skills` (17 skills)
- Official marketplace `anthropics/claude-plugins-official`, read from
  `~/.claude/plugins/marketplaces/claude-plugins-official/.claude-plugin/marketplace.json`
  (287 plugins, 38 Anthropic-authored) — count and every shortlisted name verified on disk 2026-08-14
- Redis plugin scope: `api.github.com/repos/redis/agent-skills/contents/plugins/redis-development/skills`
- Local: `~/.claude/skills/`, `.claude/skills/`
