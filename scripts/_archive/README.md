# Archived scripts

One-off scripts that did their job and are kept only as a record. **Nothing here is on a live
path** — no file in `scripts/` imports any of them, and none is referenced by the pipeline
entry points. They were moved here on 13 Aug 2026 to make `scripts/` legible.

They are still in git, so `git mv` one back if you need it. Note that several import from
`scripts/` (e.g. `from generate_messages_api import load_env`), which no longer resolves from
this directory — move the file back rather than running it in place.

| Script | What it did | Why archived |
|---|---|---|
| `model_swap_test.py` | Ran identical bundles through Opus 4.8 / Sonnet 5 / Haiku 4.5 to pick a bulk model | Its conclusion ("Sonnet 5") was **reversed** on 13 Aug 2026 — the model is Opus 5. See `specs/outreach-app-plan.md` §4.6 |
| `build_comparison_csv.py` | Built the side-by-side CSV for the above | Companion to a superseded test |
| `broaden_openers.py` | One-off rewrite of repeated message openers | Batch-level repetition is now a designed mechanism, not a repair pass |
| `adjudicate_unsure.py` | One-off adjudication of borderline signal calls | Campaign-specific, done |
| `verify_signal_live.py` | One-off live re-verification of chosen signals | Campaign-specific, done |
| `recheck_performance.py` | One-off performance re-audit after the perf gate changed | Campaign-specific, done |
| `detect_site_changes.py` | One-off diff of sites that changed mid-campaign | Campaign-specific, done |
| `add_priority_flag.py` | Backfilled a `priority` column onto an enriched CSV | One-off column add |
| `extract_facts.py` | Backfilled `proud_facts` onto batch_01's enriched CSV | Backfill; `content_extractor.extract_proud_facts` runs inline now |
| `make_test_csv.py` | Built small test fixtures | Superseded by working on real batch slices |
| `export_prospects.py` | Early per-segment prospect export | Superseded by `build_outreach_list.py` |

## Deliberately NOT archived

`generate_messages_api.py` looks retired (CLAUDE.md says the runner path is), but it is still a
**live dependency** — `qa_check.py`, `finish_batch.py`, `fix_case_studies.py` and two others
import `load_env`, `extract_json` and `backstop_case` from it. Moving it breaks QA.
