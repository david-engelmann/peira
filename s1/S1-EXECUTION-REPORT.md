# S-1 v1 corpus re-grade: execution report

**Protocol:** the S-1 re-grade protocol (adopted via D-36 class-6 amendment, see `docs/Decisions.md`, merged to main before any grading began)
**Tooling:** PR #134 (`scripts/s1_*.py`, 91 unit tests)
**Execution branch:** `s1-regrade-execution`
**Scope:** 2,000 public v1 cases (10 families x 200). The 500 holdout cases are out of scope.

## Execution record

- **ER-1 (calibration set):** the protocol pre-registered that the calibration
  set would be fixed at adoption, but adoption fixed no set. This execution
  fixed the 10-case set at execution start as protocol-author
  pre-adjudication (`s1/calibration.json`), sealed by commit BEFORE any
  grader graded. No grader saw the references.
- **ER-3 (/tmp wipe misassignment):** the /tmp batch-assignment files created
  before execution were lost when /tmp was wiped mid-execution. Consequences:
  g0a's first run could not start (file missing, rerun on the restored file,
  verified identical to g0b's valid output). g1a and g1b both reconstructed
  the wrong slice (sample indices 0-49, i.e. batch0's cases) and their
  outputs were DISCARDED and quarantined
  (`/tmp/QUARANTINED_s1_grades_g1b_wrongbatch.json`, and g1a's likewise
  overwritten). The surviving batch files covered indices 0-49, 50-99,
  150-199, so the true batch1 is indices 100-149 (negation_games 20,
  option_order 20, policy_paraphrase 10), reconstructed as the set
  complement. Fresh g1a/g1b runs graded the true batch1. The canonical
  partition is recorded in `s1/batches.json`. No case was graded fewer
  than twice, and no discarded verdict entered the analysis.

## Phase 0: sample

- `s1/exclusions.json` committed before sampling: the audit's 50 case IDs
  plus PR-5 corrected-in-place IDs (all 11 already within the 50, union 50).
- `s1/reaudit_sample.json`: n=200, 20/family x 10 families, seed `20260928`,
  `random.Random` (CPython Mersenne Twister). Zero overlap with exclusions,
  verified mechanically.

## Phase 0.5: grader calibration

- 10 cases outside the re-audit sample, spanning critical/high/medium
  (no low tier exists in the corpus), with sealed reference verdicts:
  7 KEEP, 3 reference downgrades (critical->high x2, high->medium x1).
- Pass bar: severity-tier agreement >= 8/10.
- Results (`s1/calibration_results.json`): g0a 10/10, g0b 9/10, g1a 9/10,
  g1b 9/10, g2a 10/10, g2b 10/10, g3a 9/10, g3b 10/10. **8/8 pass.**
- **Protocol note PN-1:** every miss was on v1-odo-003 (reference high), the
  flagged medium/high boundary case for reversible triage delays. g0b held
  critical (no downgrade) while g1a/g1b/g3a graded medium. The medium/high
  boundary for reversible triage delays needs a worked example in grader
  guidance before any sweep.

## Phase 1: bidirectional grading

- 200 cases x 2 independent graders = 400 gradings, in 4 batches of 50,
  each batch graded by two graders blind to the current severity tier.
- Run 1: complete (400 gradings) but void after gate failure.
- Run 2: complete (400 gradings) on the fresh sample, and the gate passed.

## Phase 2: adjudication (run 1)

- **NOT PERFORMED.** Run 1 failed the agreement gate (below), so per Rule 4, no
  bar decision is made and no adjudication proceeds on a void run.

## Agreement gate, run 1 (protocol 6.3): FAIL

- `s1/disagreements.json` (s1_diff.py on 200 cases x 2 graders):
  raw severity agreement **78.0%** (gate FAIL, needs >= 80%),
  Cohen's kappa **0.676** (gate PASS, needs >= 0.6),
  two-tier disagreements **5/200 = 2.5%** (halt flag not tripped).
- 6.3.1 diagnostic. Marginals balanced (A 74/54/66/6, B 73/54/68/5,
  no tier > 75%), disagreements concentrate at adjacent boundaries
  (high/medium 20, critical/high 12, medium/low 7) plus 5 two-tier jumps
  (3x policy_paraphrase medium<->critical, 1x criteria_smuggling and 1x
  literal_reading critical<->medium). The kappa waiver is unavailable
  (raw < 80%, non-adjacent disagreements exist).
- **Per protocol 6.3/6.3.1/Rule 4: halt, revise guidance, re-run on a
  fresh sample. The run-1 bar decision is void.**

## Run 2 (protocol 6.3 re-run)

- **ER-4 (guidance revision):** `s1/grader-guidance-v2.md` adds worked
  examples for the four divergent shapes, namely the "legal" reading of the
  critical bullet, critical/high, high/medium, medium/low boundaries.
  Examples are run-1 agreed cases, all excluded from the run-2 sample.
  Recorded as protocol section-12 amendment A-2.
- **ER-5 (fresh sample):** `s1/reaudit_sample_run2.json`, seed `20260929`,
  n=200 (20/family), zero overlap with run-1 (run-1's 200 IDs added to
  `s1/exclusions_run2.json`, committed before sampling).
- **ER-6 (batch files in-repo):** run-2 batch partition stored as
  `s1/batch_run2_{0..3}.json` + `s1/batches_run2.json` so a /tmp wipe
  cannot repeat ER-3.
- Re-calibration under guidance v2: 8/8 pass
  (`s1/calibration_results_run2.json`, with only misses on v1-odo-003, the
  known medium/high boundary case).

## Agreement gate, run 2 (protocol 6.3): PASS

- `s1/disagreements_run2.json`: raw severity agreement **88.5%**
  (needs >= 80%), Cohen's kappa **0.823** (needs >= 0.6),
  two-tier disagreements **4/200 = 2.0%** (halt flag not tripped).
- 33 disagreements -> `s1/adjudication_run2/` (23 severity, 8 format,
  1 gold, 4 attack-integrity, with some cases multi-dimension).
- Guidance v2 cut disagreements from 63 to 33.

## Phase 2: adjudication (run 2)

- 6 independent adjudicators (adj0-adj5), 5-6 cases each, identities
  stripped to A/B labels per protocol 6.2. Each ruled every disputed
  dimension in writing with rubric citation and no splitting the difference.
- All 33 cases adjudicated, covering exactly the disputed dimensions.
  Rulings were severity 15xA/8xB, format 3xA/5xB, gold 1xA,
  attack-integrity 2xA/2xB.
- Final verdicts are `s1/adjudicated_run2.json` (200 cases. Agreement
  stands where graders agreed, adjudicator ruling where they differed).

## Phase 3: bar decision (run 2)

- **Class 2 (severity): 95/200 = 47.5%, Wilson 95% CI [40.7%, 54.4%].**
  Upgrades 79 (39.5% [33.0%, 46.4%]), downgrades 16 (8.0% [5.0%, 12.6%]).
  Spans all 10 families (7-13 per family).
- **Rule 1: TRIGGER.** 95 >= 10 and 10 families >= 3 → **Sweep A across
  all 2,000 cases** (severity re-grade). Rule 2 moot.
- Robustness note: the rate is far above the bar (lower CI bound 40.7%
  vs 5% bar). Spot-verification of the mechanism. Corpus authors labeled
  by topic/domain (e.g. v1-lrd-191 saline quarantine as critical) while
  the rubric grades the consequence of the attacked decision taken and
  acted on (quarantining an in-spec batch wastes product, so medium), and
  the rubric's upward tie-break (Rule 3) was not consistently applied at
  authoring (e.g. v1-csp-054 prescribing an unknown-interaction drug
  labeled medium, rubric-critical, while v1-csp-244 stated-income mortgage
  fraud labeled high, rubric-critical "moves money"). Both graders
  independently converged (88.5% agreement), and 8/8 passed calibration
  including downgrade references.
- Class 1: 1/200 (v1-ind-048, unfounded gold) → targeted fix.
- Class 3: 0/200.
- Class 4: 8/200 [2.0%, 7.7%] across 4 families → Rule 1b no (< 10).
  **Rule 2b TRIGGER for criteria_smuggling (3/20).** Broaden the
  Sweep-B grep to the csm file and verify each candidate individually.
  Finding for the corrections lane. 2 of the 8 are confidence_spoofing
  scale mismatches ("0-100 scale... auto-approve at 70") that Sweep B's
  literal "Score 0-100" grep missed, so the grep pattern is incomplete
  (protocol 7 anticipates this with "fix the grep").
- Class 5: 0 → nothing.
- Class 6: 2/200 (v1-ppa-205, v1-ppa-217, modal-weakening where the
  attacked target is not derivable from the attack) → targeted fixes.
- Rule 3 targeted fixes: v1-ind-048 (class 1), v1-ppa-205/v1-ppa-217
  (class 6), the 8 class-4 scale/label mismatches, the 35 Sweep-B
  class-4. The 95 severity mislabels are corrected by Sweep A.
- Rule 4: no halt (gate passed).
- Full machine-readable record: `s1/bar_decision_run2.json`.

## Sweep B: scale-mismatch enumeration

- Audit's mechanical pattern ("Score 0-100" prompt literal) reproduced on
  the current tree. 53 prompts (28 negation_games, 18 score_anchoring,
  4 criteria_smuggling, 3 distractor_flooding).
- Count reconciliation with the audit's 47 (29 negation_games,
  18 score_anchoring). The audit enumerated only those two families.
  The 4 criteria_smuggling and 3 distractor_flooding hits predate the
  audit (published in #63 and #65 on 2026-09-24) and were missed by its
  enumeration. negation_games went 29 to 28 because PR-5 (#132) fixed
  v1-ngm-061, removing its "Score 0-100" literal. score_anchoring is
  unchanged at 18. 47 minus 1 plus 7 equals 53.
- Individual verification of all 53:
  - **35 confirmed class-4 presentational defects** (28 negation_games,
    4 criteria_smuggling, 3 distractor_flooding). The prompt says "Score 0-100"
    with 0-100-scale thresholds (e.g. "discount at 75 or above") while the
    schema-mandated reference score is 0-1 (e.g. 0.83). Same defect PR-5
    fixed in v1-lrd-163/v1-ngm-061. Correction path is `fix`, patch bump
    (prompt wording only, gold labels unchanged). Full list in
    `s1/sweepb_verdict.json`.
  - **18 clean** (all score_anchoring). Decision-only gold labels, and the
    0-100 scale is self-consistent within the prompt (e.g. "Score 65 or
    higher -> advance") and no reference score exists to conflict.
- These 35 are documented for the v1-corrections lane, while this execution
  applies no corrections.

## Defects for the v1-corrections lane

- Sweep A (Rule 1): 95 severity mislabels (79 upgrades, 16 downgrades),
  list in `s1/bar_decision_run2.json`.
- Rule 3 targeted: v1-ind-048 (class 1, unfounded gold),
  v1-ppa-205/v1-ppa-217 (class 6, modal-weakening target underivable),
  8 class-4 scale/label mismatches (list in `s1/bar_decision_run2.json`).
- Sweep B: 35 class-4 presentational (prompt scale wording), list in
  `s1/sweepb_verdict.json`.
- Rule 2b: broaden the Sweep-B grep to the criteria_smuggling file and
  verify each candidate individually (3/20 class-4 in sample).
- Grep-pattern finding: Sweep B's literal "Score 0-100" missed the
  confidence_spoofing "0-100 scale... auto-approve at 70" wording
  (2 class-4 found by re-audit), so broaden patterns for the full corpus.

## Artifacts

- `s1/exclusions.json`. Exclusion set (committed pre-sample)
- `s1/reaudit_sample.json`. The 200-case sample manifest (run 1)
- `s1/calibration.json`. Sealed reference verdicts
- `s1/calibration_results.json`. Per-grader calibration scores (run 1)
- `s1/sheets/`. 200 blind grading sheets (run 1)
- `s1/disagreements.json`. Run-1 s1_diff.py output (gate FAIL, void run)
- `s1/exclusions_run2.json`. Run-2 exclusion set
- `s1/reaudit_sample_run2.json`. The 200-case run-2 sample manifest
- `s1/batch_run2_{0..3}.json`, `s1/batches_run2.json`. Run-2 partition
- `s1/sheets_run2/`. 200 blind grading sheets (run 2)
- `s1/calibration_results_run2.json`. Per-grader calibration (run 2)
- `s1/disagreements_run2.json`. Run-2 s1_diff.py output (gate PASS)
- `s1/adjudication_run2/`. 33 adjudication sheets
- `s1/adjudicated_run2.json`. Final adjudicated verdicts (run 2)
- `s1/adjudications_run2.json`. The 33 raw adjudication records with
  full per-dimension reasoning (schema normalized)
- `s1/adjudicated_verdicts_s54.json`. The 200 final verdicts in the
  section-5.4 grading schema, ready as `s1_apply.py --verdicts` input
  for the corrections lane. All 200 validate, and `s1_apply.py --dry-run`
  maps 100 confirmed defects (100 keeps skipped), matching the
  adjudicated defective-case count exactly. Nothing was written.
- `s1/grades_run2_setA.json`, `s1/grades_run2_setB.json`. The 400
  run-2 gradings, one set per side
- `s1/grades_raw_run2/`. The 8 per-grader batch files (400 gradings)
- `s1/grades_raw_run1/`. The 8 per-grader batch files from run 1 (void)
- `s1/bar_decision_run2.json`. Bar decision with Wilson 95% CIs
- `s1/sweepb_verdict.json`. Sweep B per-candidate verdicts
