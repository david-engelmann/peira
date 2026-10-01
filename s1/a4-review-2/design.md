# A4 second-review lane — design (2026-10-01)

Branch `a4-second-review-2`, base `73327c3f` (post #280 Sweep A, post #283 EB-44/EB-53).
Mission: gate item 3 — the second independent case review + assistant verification
on the integrated v1 set (dataset v1 1.4.0, 2,000 cases), independent re-derivation
of the first A4 review's conclusions.

## Legs (executed sequentially, then verdict)

1. **Mechanical.** `peira dataset gates` exit code + 9/9; manifest 1.4.0 SHA-256
   recomputation (family files vs aggregate); 2,000-case count; ID
   uniqueness; retired-ID handling per CHANGELOG; Python codepoint scan
   for raw U+2014 in changed content.
2. **Sweep-A fidelity.** Diff `2cca2ee1^..2cca2ee1` categorized:
   severity-only edits vs notes-only vs class-4 prompt fixes vs
   retire+add; confirm zero gold/structural field changes; reconcile the
   852-planned / 848-applied counts; cross-check a sample of applied
   severity tiers against `s1/sweep_a_severity_corrections.json` verdicts.
3. **Case-level second review (fresh sample, seed 20261001 — NOT the
   first review's 20260929 seed).** Stratified: (a) cases corrected by
   #280 (upgrades, downgrades, class-4 prompt fixes) graded against
   `docs/Severity-Rubric.md`; (b) non-corrected cases, deliberately
   weighted toward the F-3 safety/medical substrate pool #280 did NOT
   touch, to test whether the F-3 residual-under-tiering risk persists
   after Sweep A. Judge independently; do not copy first-review verdicts.
4. **Statistics.** Recompute from committed artifacts: severity
   distribution before/after Sweep A, critical count, disagreement rate
   from grades_sweep_a_*, agreement/kappa if derivable, all quoted
   numbers in S1-EXECUTION-REPORT / sweep report re-derived.

## Verdict criteria
Gate item 3 is clean iff: mandated Sweep-A corrections landed completely
and correctly, applied tiers match verdicts, no genuine residual defects
in the case-level sample, statistics re-derive exactly.

## Non-goals
- No tree modifications, no fix PRs (findings go to the report;
  repair lanes handle fixes).
- No live API calls; no full pytest suites (review lane scope).
- #283 (EB-44/EB-53) only checked for absence of dataset-side effects.
