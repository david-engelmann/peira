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
- CG4 substrate freshness vs v1/v2 corpus (3,455 prompts at pilot time): PASS (0 errors)
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

## Pilot limitations (follow-up items)

The pilot implements the 2x2 arm structure and the paired interaction
machinery. Three design elements are documented here as deferred, not
as resolved.

- **Length control (design 6c).** Attacked arms are longer than the
  control arm (the anchor/spoof lines add tokens). If longer prompts
  flip more often regardless of content, part of any measured
  interaction could be a length effect rather than a combination
  effect. Follow-up: length-matched control arms that add inert text
  of equal token count, so the interaction contrast isolates content
  from length.
- **Order control (design 6c).** The ab arm always applies
  score_anchoring before confidence_spoofing (or distraction before
  misdirection). Order effects are not measured. Follow-up: a ba arm
  with the application order reversed, at least on a subsample, to
  check that the interaction is not order-dependent.
- **`unresolved` floor (design 6d).** `paired_interaction()` in
  `python/peira/combo_metrics.py` classifies a pair as unresolved when
  MDE80 exceeds a fixed 0.20 floor. The design doc's convention is a
  per-combo MDE floor calibrated to the pair's stakes, not one fixed
  threshold. Follow-up: replace the fixed floor with the per-combo
  convention before the first full-scale combo run.

## Design compliance

Implements phase-0 of `research_notes/family-intersections-20260928.md` sections 4a/6a/6b. The re-review's required deliverable (paired variance estimator derived by pilot builder) is implemented in `combo_metrics.py:paired_interaction()` — variance estimated from the sample variance of per-substrate contrasts d_i, not from independent-arms sum-of-variances.

## Copy bar

Zero em dashes (U+2014) in case files (codepoint scan verified).
