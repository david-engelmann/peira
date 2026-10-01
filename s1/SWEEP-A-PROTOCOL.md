# Sweep A Protocol: Full 2,000-Case Severity Re-grade

**Authority.** S-1 execution report bar decision, Rule 1: the 47.5%
severity-defect rate (Wilson 95% CI lower bound 40.7%) exceeds the 10%
bar, so the full 2,000-case re-grade proceeds. D-36 governs corrections.

**Scope.** All 2,000 public v1 cases. The 200 run-2 sample cases already
carry adjudicated verdicts applied via #215; Sweep A grades the remaining
1,800. The 200 sample cases are excluded from the Sweep A draw
(`s1/sweep_a_sample.json` records the exclusion).

**Grading method.** Identical to run-2 (S-1 protocol sections 5-6):

1. Severity-redacted sheets per case (severity field + notes-tier hints
   redacted per the ER-8 fix in `scripts/s1_sheet.py`).
2. Two independent grader sets (A, B) per case. Graders see only the
   sheet and `docs/Severity-Rubric.md` + `s1/grader-guidance-v2.md`.
   The rubric is the sole authority.
3. Bidirectional: graders assign the tier the rubric requires, up or
   down, quoting the bullet. Downgrades carry the same weight as
   upgrades.
4. Disputes (any dimension) go to independent adjudication per
   protocol 6.2 (grader identities blinded, adjudicator cites the
   rubric bullet or D-36 clause, no splitting the difference).
5. Severity changes ship as `annotate` per D-36 (patch bump; severity
   does not change decision/score labels). New criticals enter the
   D-7 human-review queue before the manifest re-seals.

**Defect classes in scope for Sweep A graders.** All six D-36 classes
(severity, class 1, 3, 4, 5, 6) are graded per the sheet's five
dimensions, but Sweep A's primary mandate is severity. Class-1/6
findings are routed to the targeted-fix lanes for adjudication, not
applied directly, unless the grader evidence is unambiguous and the
red-team confirms.

**Execution gate (already cleared).** The run-2 independent re-audit
passed the agreement gate (88.5% raw, kappa 0.823). Rule 1 triggered.
No second gate is required before Sweep A execution.

**Verification.** `scripts/s1_verify.py` (protocol sections 9-10) runs
after application: manifest integrity, schema, ID uniqueness,
retired-ID handling, defect coverage, changelog form, version-bump
consistency. All nine dataset gates must pass with 0 errors.

**Records.** `s1/sweep_a_sample.json` (draw), `s1/sheets_sweep_a/`
(sheets), `s1/grades_sweep_a_*.json` (raw gradings),
`s1/disagreements_sweep_a.json`, `s1/adjudications_sweep_a.json`,
`s1/sweep_a_report.md` (final counts).
