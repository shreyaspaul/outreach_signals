# Quotable "proud facts" extraction — plan

Goal: pull specific, credible, QUOTABLE facts a founder is proud of from their site
("40,000-member Discord", "used by 2,000 teams", "raised $12M", "processed $1B",
"4.9 stars from 3,000 reviews", "backed by Y Combinator", "trusted by Netflix"), and make
them available to the message writer to use as a genuine, flattering hook when relevant.

## Bulletproofing (no hallucinated facts — this is the whole point)
A wrong number in outreach is worse than no number. So:
1. The LLM extracts facts ONLY from the page's own extracted content (the same text the
   content grader already analyzes), and must return the exact `evidence` substring.
2. Post-extraction VERIFICATION (code, not LLM): every fact is kept only if its evidence
   phrase is actually present in the source content (whitespace-normalized, casefolded), OR
   the fact's headline number/entity appears verbatim in the content. Unverified facts are
   dropped. This guarantees nothing reaches a message that isn't in the source.
3. Vague marketing claims ("best-in-class", "trusted by many", "industry leading") are
   explicitly excluded — only concrete, specific, numeric/named facts qualify.

## Where it runs
- New function `extract_proud_facts(content, url, api_key)` in `content_extractor.py`
  (focused Gemini 2.5 Flash call, temperature 0, same retry pattern as content grading).
- It naturally belongs alongside content grading (same content, LLM already involved). For
  FUTURE audits it can be called in the content step. For the EXISTING 100-site data we
  backfill without disturbing any existing column.

## Columns added
- `proud_facts` — the quotable snippets, joined by " | " (0, 1, 2, or 3 facts).
- `proud_facts_detail` — JSON: list of {fact, type, evidence} for transparency/review.

## Backfill (existing data)
- `scripts/extract_facts.py`: for each gradeable row, re-fetch content via Jina
  (`extract_content`), run `extract_proud_facts`, write the two columns back. Idempotent
  (skips rows that already have it unless `--force`); never touches other columns.

## Message generator wiring (so I can SEE what/why)
- `build_prospect` passes `quotable_facts` (from `proud_facts`).
- Pass A (Analyst) decides whether a fact is worth using and which one, adding to its output:
  - `quotable_fact_to_use` — the exact fact to weave in, or "none".
  - `quotable_fact_reason` — why it picked/skipped it.
- Pass B (Writer) weaves the chosen fact in naturally, often as the genuine positive or a
  credibility nod, quoting the number/name EXACTLY, never altering it. If "none", ignores it.
- Output CSV shows: `proud_facts` (what was available), `quotable_fact_to_use` (what it used),
  `quotable_fact_reason` (why) — so you can see if it's coming through smoothly and judge it.

## Review loop
Run backfill on the first ~12 sites, regenerate the 10 messages, and check: are the facts
real (verified), are they being used naturally and only when relevant, and is the reasoning
visible in the columns.
