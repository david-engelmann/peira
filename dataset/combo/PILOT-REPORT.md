# Family-Combination Pilot Report

**Date:** 2026-09-30
**Branch:** `family-combination-pilot` (based at `c26e432`)
**Status:** Infrastructure complete, cases gated, machinery validated. Interaction measurement pending authorized adapter runs.

## What was built

**Cases:** 800 (100 substrates x 4 arms x 2 pairs)
- `combo-dfl-ind`: distractor_flooding x indirection (hypothesis: super-additive)
- `combo-san-csp`: score_anchoring x confidence_spoofing (hypothesis: sub-additive, negative control)

**Gates (all pass):**
- CG1 schema validity: PASS (0 errors)
- CG2 2x2 arm completeness: PASS (0 errors)
- CG3 pair separation + id uniqueness: PASS (0 errors)
- CG4 substrate freshness vs v1/v2 corpus (3,455 prompts): PASS (0 errors)
- CG5 substrate near-dedup (Jaccard < 0.85): PASS (0 errors)

**Infrastructure:**
- `python/peira/combo_schema.py`: case schema, validation, id format
- `python/peira/combo_gates.py`: CG1-CG5 gate implementations
- `python/peira/combo_metrics.py`: paired interaction contrast with 95% CI and MDE
- `python/peira/combo.py`: public re-exports
- `scripts/combo_analyze.py`: CLI for interaction analysis from run results
- `scripts/combo_run.py`: pilot runner (adapter-agnostic)
- `tests/test_combo.py`: 14 unit tests (all pass)
- `dataset/combo/cases/manifest.json`: sealed manifest (800 cases)

**Methodology:** Documented in `docs/Methodology.md` ("Combo interaction contrast").

## Machinery validation

The full analysis pipeline was validated with synthetic outcomes simulating
known interaction effects:

- **Synthetic super-additive** (dfl-ind pattern): interaction=+0.240, 95% CI [+0.087, +0.393], MDE80=0.218 -> UNRESOLVED (MDE floor not met at n=100; conservative by design)
- **Synthetic sub-additive** (san-csp pattern): interaction=-0.170, 95% CI [-0.309, -0.031], MDE80=0.199 -> SUB-ADDITIVE, hypothesis CONFIRMED

The pipeline correctly classifies known effects and honestly reports
"unresolved" when the MDE floor is not met.

## Interaction measurement: PENDING

**Real interaction numbers require authorized adapter runs.** The pilot
delivers gated cases and validated measurement machinery. The interaction
classification for each pair awaits execution against a real adapter.

**Pre-registered hypotheses:**
- `combo-dfl-ind`: super-additive (distraction + misdirection compound)
- `combo-san-csp`: sub-additive (redundant persuasion; negative control)

**To run:** `python3 scripts/combo_run.py --adapter <name> --out runs/<id>/results.jsonl`, then `python3 scripts/combo_analyze.py runs/<id>/results.jsonl`.

## Design compliance

Implements phase-0 of `research_notes/family-intersections-20260928.md` sections 4a/6a/6b. The re-review's required deliverable (paired variance estimator derived by pilot builder) is implemented in `combo_metrics.py:paired_interaction()` — variance estimated from the sample variance of per-substrate contrasts d_i, not from independent-arms sum-of-variances.

## Copy bar

Zero em dashes (U+2014) in case files (codepoint scan verified).
