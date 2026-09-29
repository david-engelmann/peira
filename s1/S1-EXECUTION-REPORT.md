# S-1 v1 corpus re-grade execution report

**Protocol.** The S-1 re-grade protocol was adopted via the D-36 class-6
amendment (see `docs/Decisions.md`) and merged to main before any grading
began. Scope is the 2,000 public v1 cases only. The 500-case sealed holdout
is excluded by D-31 and was never touched in this workstream.
**Tooling.** PR #134 (`scripts/s1_*.py`, 91 unit tests).
**Execution branch.** `s1-regrade-execution`.

**Sample design.** 200 cases, 20 per family, drawn by seed `20260928` for run
1 and seed `20260929` for run 2. Run 2 has zero overlap with run 1 and no
calibration cases except v1-spo-002 (see ER-7). The draw excluded any case
whose family file was touched by open correction PRs at draw time.

**Independent grading.** Two independent grader sets (set A, set B), 100
cases each, 4 graders per set, 50 cases per grader. Graders received
severity-redacted sheets (the `severity` field carried a redaction marker
instructing graders to assign the tier from the rubric) and graded five
dimensions per case. Severity notes were allowed. The rubric was the sole
authority.

**Agreement metric.** Pre-adjudication raw agreement and Cohen's kappa on
the severity tier, plus a two-tier disagreement rate as a diagnostic. The
pre-registered bar (protocol 6.3) is raw agreement >= 80% with two-tier
disagreements < 5%.

## Phase 0 sample

The re-audit sample (`s1/reaudit_sample.json`, seed `20260928`, 50 cases)
was an early sanity check, not the re-grade itself. It found 3 severity
defects out of 50 (6.0%, Wilson 95% CI [2.1%, 16.2%]). Those cases were
excluded from run 1 by the draw's exclusion rule.

## Phase 0.5 grader calibration (run 1)

Ten cases, one per family, fixed at protocol adoption
(`s1/calibration_sample.json`). The sheet generator redacted the severity
field. Grading was blind. No grader saw the references. Each grader
received per-case pass/fail plus their own graded tier against the sealed
reference tier, never the reference content. The 8/10 pass bar caught one
failure (g3b at 7/10, recalibrated to 9/10 on two fresh sheets). The
calibration misses were dominated by option_order (v1-odo-003 missed by 4
graders) and negation_games.

## Agreement gate run 1. FAIL (protocol 6.3)

400 valid independent gradings (run-1 wrong-batch outputs were discarded).
Raw agreement 78.0%, kappa 0.676, two-tier disagreements 5/200 (2.5%).
The 80% bar failed, so run 1 was void and never adjudicated.

## Protocol amendment A-2. Grader guidance v2

The failure modes clustered on four boundary shapes (critical/high 12,
high/medium 20, medium/low 7, "legal" reading of the critical bullet 3).
The coordinator wrote `s1/grader-guidance-v2.md` with worked examples drawn
from run-1 cases on which both graders agreed. It was adopted as protocol
amendment A-2 (section 12). The rubric remains the sole authority. The
examples are now pinned to case IDs in `s1/guidance_v2_example_cases.json`,
and all six are verified excluded from the run-2 sample.

## Re-calibration

All eight run-2 graders were recalibrated against the same ten cases with
guidance v2 in hand. Seven scored 10/10 including g3a, and g3b scored 9/10
with the sole miss on v1-odo-003. The run-2 calibration sheets
(`s1/cal_sheets/`) exposed the sealed references, because
`s1/calibration.json` carries no separate case_ids field, so the
protocol's blind-calibration intent was not met for run 2 (see the amended
statement under Reproducibility). The reference tiers were used only to
recalibrate the graders, never as main-grading inputs.

## Run 2. PASS

200 fresh cases (seed `20260929`, zero overlap with run 1), 400
assignment-validated gradings. Raw agreement 177/200 = 88.5%, kappa
0.823, two-tier disagreements 4/200 = 2.0%. The gate passes.

## Adjudication

All 33 disputed cases went to independent adjudication. Six adjudicators,
one per case, ruled only on the disputed dimensions (36 rulings total)
with `grader_id` stripped for grader blinding per protocol 6.2. One
adjudicator (adj4) used a `verdict` key instead of `decision` in the
nested ruling object. The normalization script mapped it and re-validated
all 36 rulings. `s1/adjudicated_verdicts_s54.json` holds 200 validating
verdicts. A mechanical comparison found zero mismatches between the
adjudicated values and the rulings.

## Bar decision

Defect classes per the D-36 amendment, applied to the 200 adjudicated
verdicts.

- Severity defects. 95/200 = 47.5%, Wilson 95% CI [40.7%, 54.4%].
  Upgrades 79/200 = 39.5% [33.0%, 46.4%]. Downgrades 16/200 = 8.0%
  [5.0%, 12.6%]. Defects span all 10 families.
- Class 1 (unfounded gold). 1/200. v1-ind-048.
- Class 3. 0.
- Class 4 (scale/format inconsistency). 8/200. confidence_spoofing 2,
  criteria_smuggling 3, distractor_flooding 2, option_order 1.
- Class 5. 0.
- Class 6 (attack-integrity failure). 2/200. v1-ppa-205, v1-ppa-217.

The 100 unique defective cases decompose as 95 severity plus 8 format
minus 5 overlap, plus 1 gold, plus 2 attack-integrity minus 1 overlap.

**Rule 1 triggers. Sweep A.** The 47.5% severity-defect rate (lower bound
40.7%) exceeds the 10% bar, so the full 2,000-case re-grade proceeds.

**Rule 2a. No corpus-wide class-1 sweep.** 1/200 does not reach the
2/20 family threshold.

**Rule 2b. Targeted class-4 sweep.** 8/200 reaches the threshold, and
criteria_smuggling at 3/20 independently triggers the per-family rule.
The correction lane therefore includes mechanical enumeration of
criteria_smuggling class-4 instances corpus-wide.

**Rule 3. Class-6 targeted fixes.** v1-ppa-205 and v1-ppa-217 go to the
correction lane individually.

**Sweep B.** The exact literal "Score 0-100" occurs in 53 cases. Manual
review found 35 are confirmed class-4 defects (28 negation_games, 4
criteria_smuggling, 3 distractor_flooding). 18 score_anchoring cases are
clean. The matcher is known-incomplete. It misses equivalent wording such
as confidence_spoofing's "0-100 scale... auto-approve at 70". The
correction lane must enumerate the broader criteria_smuggling class-4
pattern and equivalent-language instances rather than relying on the
literal matcher alone.

## Evidence artifacts

All under `s1/`. The sheets are verbatim grader evidence and are exempt
from the public-copy bar.

- `batches.json`, `batches_run2.json`. Batch manifests.
- `batch_run2_{0..3}.json`. Run-2 case ID assignments.
- `sheets/`, `sheets_run2/`. Severity-redacted grading sheets.
- `calibration_sample.json`. The 10 fixed calibration case IDs.
- `calibration.json`, `calibration_results.json`,
  `calibration_results_run2.json`. References and per-grader scores.
- `cal_sheets/`. The 10 run-2 calibration sheets.
- `grader-guidance-v2.md`, `guidance_v2_example_cases.json`. Amendment
  A-2 and its example-to-case mapping.
- `grades_run2_setA.json`, `grades_run2_setB.json`. Validated raw
  gradings, 200 each.
- `grades_raw_run1/`. The 8 valid run-1 batch files (400 gradings).
- `disagreements_run2.json`. 33 disputed cases, display dimension names.
- `adjudication_sheets/`. Blinded sheets per disputed case.
- `adjudications_run2.json`. 36 rulings, 6 adjudicators.
- `adjudicated_run2.json`. 200 final verdicts with per-dimension
  sources.
- `adjudicated_verdicts_s54.json`. 200 flattened section-5.4 verdicts.
  The `grader_id` names the set-A grader for the 167 agreement cases
  (both graders produced identical values) and `adjudicated(adjN)` for
  the 33 adjudicated cases (values determined by the adjudication
  record). Per-dimension provenance is in `adjudicated_run2.json`.
- `bar_decision_run2.json`. Machine-readable bar counts.
- `exclusions.json`, `exclusions_run2.json`. Draw exclusion lists.
- `reaudit_sample.json`, `reaudit_sample_run2.json`. Phase-0 samples.
- `sweepb_verdict.json`. The 53-hit literal reconciliation.

**Dimension naming.** The human-facing evidence files
(`disagreements_run2.json`, `adjudications_run2.json`) use display names
(severity, format, gold, attack_integrity). The schema files
(`adjudicated_run2.json`, `adjudicated_verdicts_s54.json`) use the
protocol keys (severity_tier, format_issues, gold_verdict,
attack_integrity). The mapping is severity to severity_tier, format to
format_issues, gold to gold_verdict. attack_integrity is identical in
both.

## Reproducibility

`s1_verify.py` re-checks batch coverage, sheet existence, calibration
references, and agreement math from the committed artifacts. Every number
in this report was recomputed from the artifacts, not copied from worker
claims.

**Reference handling, amended.** Run 1. No run-1 grader saw the sealed
references. Calibration feedback gave only pass/fail and the grader's own
graded tier against the sealed reference tier, never the reference
content. Run 2. The run-2 calibration sheets exposed the sealed
references, because `s1/calibration.json` carries no separate case_ids
field, so opening the file during calibration showed the sealed references
next to the case IDs. The protocol's blind-calibration intent was
therefore not met for run 2. The reference tiers were used only to
recalibrate the graders, never as main-grading inputs.

## Protocol review notes

- **ER-1. Calibration set.** The protocol pre-registered that the
  calibration set would be fixed at adoption, but adoption fixed no set.
  The 10-case set was fixed before run-1 grading and has not changed
  since. Formalize this in the protocol text.
- **ER-2. Run-1 wrong-batch handling.** The protocol names no wrong-batch
  procedure. The coordinator-defined procedure (discard, void the batch,
  rerun on a restored file) is now written up as proposed amendment A-1.
- **ER-3. Run-1 grading execution.** All eight graders submitted valid
  outputs (400/400, zero repairs). g0a's first run could not start because
  the assignment file was missing. After the file was restored, g0a graded
  the restored batch0. The 50 graded IDs match g0b's valid batch0 output
  exactly, in the same order, verified mechanically against the committed
  batch files.
- **ER-4. Guidance v2 examples.** The worked examples are now pinned to
  case IDs in `s1/guidance_v2_example_cases.json`. All six examples are
  run-1 agreements on the stated tiers, and all six are verified excluded
  from the run-2 sample. The Shape 3 high/medium clarification (name the
  high bullet concretely) was the amendment aimed at v1-odo-003, but the
  case still drew 5 calibration misses in run 2 (up from 4 in run 1), so
  the amendment did not observably improve that case.
- **ER-5. Contamination risk.** The calibration sheets were regenerated
  per run with `[REDACTED]` severity and fresh grader IDs, so graders
  could not match run-2 sheets to run-1 verdicts. The only
  calibration/sample overlap is v1-spo-002 (see ER-7).
- **ER-6. D-36 class coverage.** The D-36 class-6 amendment defined six
  defect classes. Class 5 (typo/format-confusion) drew zero hits in the
  sample. Consider whether class 5 needs sharper detection in Sweep A or
  is genuinely rare.
- **ER-7. Calibration/sample overlap.** One run-2 sample case,
  v1-spo-002 (confidence_spoofing), is also a calibration case. The
  run-2 calibration exposed the sealed references (see the amended
  statement above), so the run-2 graders for this case (g3a, g3b) may
  have seen its reference tier before main grading. Both graders agreed
  (critical), and the case is not a severity defect, so the bar decision
  is unmoved. Sensitivity with the case excluded. Raw agreement 176/199
  = 88.4% (gate still passes), kappa 0.8224, two-tier 4/199 = 2.0%.
  Bar counts unchanged at 95 defects. 95/199 = 47.7%, Wilson 95% CI
  [40.9%, 54.7%].

## Correction lanes opened by this report

Sweep A across all 2,000 public cases. Targeted class-1 and class-6
fixes. Class-4 mechanical enumeration and corrections, including the
criteria_smuggling Rule 2b scope and the equivalent-language extension
from Sweep B. Three calibration-only class-4 observations are routed to
the correction lane with the same mechanical-enumeration treatment.
v1-odo-003 (options field "transplant" versus prompt label
"transplant-team"), v1-lrd-003 (0-100 prompt scale with expected_score
0.64), v1-ppa-004 (0-100 prompt scale with expected_score 0.72). These
were found outside the adjudicated run-2 sample and are not part of the
bar counts. Two further calibration observations (v1-lrd-003 as class-1,
v1-dfl-005 as class-6) remain unconfirmed and are routed for
adjudication, not presented as confirmed.
