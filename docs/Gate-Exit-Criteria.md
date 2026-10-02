# Evaluation Campaign Gates (A8 to A13)

This document turns the last six phases of the measurement-gate
campaign into an executable checklist. For each phase it states the
entry criteria, the exit criteria, the evidence that must exist, and
the decision rule that closes the phase. The phase definitions are
quoted from the program's campaign plan, not reworded.

The six phases are A8 "code freeze + official-run commit (immutable
dataset tag)", A9 "ledger entries with estimates", A10 "trial runs all
adapters", A11 "gate closure memo signed", A12 "official v1 run", and
A13 "blind holdout run".

## The boundary rule

No official evaluation runs until the perfection gate is met. This is
a hard rule, not a suggestion. Official runs require all three of
these. The thirteen gate items below must be resolved, the closure
memo must be signed, and the A8 code freeze must hold.

"Official" has a fixed meaning here. An official run is a run at the
frozen commit, against the immutable dataset tag, with a planned
ledger entry, a run-registry entry, and reproducibility under the
determinism contract.

## Preconditions from the perfection gate

A8 opens only when gate items 1 through 12 are resolved on merged
main. Item 13 is the closure memo itself, which is signed at A11.

1. Main green
2. The R-10 provenance package, which is croissant.json, immutable
   dataset tags, the manifest-SHA registry, and CI enforcement on main
3. Second independent case review of the integrated v1 set, plus
   assistant verification
4. The S-1 correction lanes landed
5. G8 near-dedup calibration complete
6. The public-to-holdout separation audit run at seal
7. Exhaustive row-by-row audit of the v1 public cases
8. Exhaustive row-by-row audit of the v2 drafts
9. Live adapter verification complete
10. The pytest migration landed
11. The signed disposition matrix covering all findings
12. Independent P0 and P1 re-verification on merged main
13. The closure memo signed (this is A11's exit, not an A8 entry)

Item 9 covers the live smoke verification of every adapter pin. A pin
that fails live smoke is dropped from the official run with a written
reason and backfilled later. It does not hold the gate.

## A8 - Code freeze and the official-run commit

The phase is "code freeze + official-run commit (immutable dataset
tag)".

**Entry**

- Gate items 1 through 12 above are resolved on merged main.
- Every adapter pin is either live-smoke-verified or dropped with a
  written reason.

**Exit**

- A two-week code freeze is declared with written start and end
  dates. In-flight pull requests either merge before the freeze or
  pause. During the freeze and the A12 and A13 runs, only a P0
  run-path fix may merge, and it restarts the affected window.
- The immutable dataset tag is cut, and the official run references
  the tag.
- The official-run commit is pinned and recorded.
- The pricing table is re-verified against live provider pages, so
  the A9 estimates rest on current prices.

**Evidence**

- The freeze declaration with dates, the pinned commit hash, the
  dataset tag, and the manifest-SHA registry entry for the tag.
- The re-verified pricing table.

**Decision rule**

Mechanical. The operator confirms items 1 through 12 are resolved,
cuts the tag, pins the commit, and records the freeze window. There
is no judgment call except confirming resolution.

## A9 - Cost-guard ledger entries with estimates

The phase is "ledger entries with estimates". Every planned run gets
a ledger entry carrying an up-front estimate before it may start. No
plan, no run.

**Entry**

- The A8 freeze is in force. The commit, the tag, and the pricing
  table are pinned.
- The adapter roster for the campaign is decided. This needs two
  maintainer decisions, both listed under open decisions below. The
  first is the adapter-gap decision, which covers which adapters run
  in v1 and which are backfilled later. The second is the Anthropic
  pin decision.
- The retry and degraded-adapter policy is written down before any
  run. Degraded adapters are excluded from ranking claims, and the
  run continues.

**Exit**

- A planned ledger entry with an up-front estimate exists for every
  planned run. That means the trial suite for each adapter (A10), the
  official public run (A12), the blind holdout run (A13), and the Jev
  re-run, which runs inside the v1 campaign with its own planned
  entry.
- The estimates fit the standing budget: a hard cap of $300 for the
  full run (2,000 public cases plus 500 holdout cases), and a $24 cap
  for the Jev re-run.
- Any estimate above the standing ask-first thresholds has the
  maintainer's written approval.

**Evidence**

- The ledger plan identifiers and the estimate table, planned versus
  the caps.
- The written retry and degraded-adapter policy.

**Decision rule**

Mechanical against the cost-guard policy, except for the roster
itself and any over-threshold estimate, which need the maintainer.

## A10 - Trial runs on all adapters

The phase is "trial runs all adapters". Trials validate the
pipeline end to end. They are not official runs, and trial results
stay off the public leaderboard (Decisions.md D-8).

**Entry**

- The A9 ledger plans exist for the trial suite.
- The freeze holds.

**Exit**

- The 100-case trial suite runs end to end on every rostered
  adapter.
- A run-registry entry exists for each trial run.
- The run artifacts validate against the artifact schema, and the
  analysis lock holds.
- Any adapter that fails the trial is dispositioned: fixed and
  re-run, or dropped from the official run with a written reason.

**Evidence**

- The trial run-registry entries and the validated artifacts.
- The written disposition of any dropped or re-run adapter.

**Decision rule**

Mechanical. A failed trial blocks A11 until the adapter is fixed or
dropped with a written reason. Nothing about a trial run may be
quoted as a result.

## A11 - Gate closure memo signed

The phase is "gate closure memo signed". The signed memo is the
single artifact that lifts the evaluation boundary for this
campaign.

**Entry**

- The A10 trials are green on all rostered adapters.
- Gate items 1 through 12 are resolved on merged main.

**Exit**

The closure memo is signed. All eight closure criteria below must
hold on evidence.

1. A signed disposition matrix covers all findings plus the omission
   and meta findings, one row per finding. Each row is marked FIXED
   with its pull request and merged-main hash, STALE with evidence,
   REJECTED with reasoning, or ACCEPTED-RISK with a written rationale
   and an owner.
2. Every P0 and P1 is independently re-verified on merged main by
   reviewers who did not author the fixes, confirming each FIXED
   row.
3. Delegated findings are closed explicitly. Each has a named owner
   and a verification-on-merge step recorded in the matrix. No
   finding is closed because its lane exists.
4. Bulk changes are gated by pre-registered bars. Sweep protocols
   pass review before they execute, and the independent sample
   re-audit clears its bar before the sweep lands.
5. Per-PR new-issue guards hold. Each fix pull request is red-teamed
   for issues it introduces, not only reviewed for its intended
   diff.
6. Disputes are adjudicated in writing. Wherever a reviewer and a
   builder disagree on severity or scope, the decision and the
   reasoning are recorded in the matrix.
7. Final-head CI is green plus merged-main verification for each
   pull request.
8. The closure memo itself is signed, listing any accepted-risk
   rows.

**Evidence**

- The signed disposition matrix with evidence hashes.
- The independent re-verification report.
- The signed closure memo with the accepted-risk rows.

**Decision rule**

The operator signs the memo only when all eight criteria hold on
evidence. There is no closure by delegation. Nobody signs on behalf
of the gate owner, and a delegated finding is closed by explicit
verification, never by the existence of its lane.

## A12 - Official v1 run

The phase is "official v1 run". That means 2,000 public cases on
every eval-ready adapter.

**Entry**

- The A11 closure memo is signed.
- The A8 freeze still holds. Only a P0 run-path fix may merge, and
  it restarts the window.
- The campaign roster is decided. This needs three maintainer
  decisions, all listed under open decisions below. The first is the
  official eval target, v1 frozen now or wait for the v2 families.
  The second is the adapter-gap decision. The third is the Anthropic
  pin decision.
- The A9 ledger plans carry trial-calibrated estimates.
- The run is supervised automation through `peira run` with ledger
  entries.

**Exit**

- The run completes: 2,000 public cases on every rostered adapter.
- The run-registry entry exists.
- The ledger is reconciled to actuals, and planned versus actual
  spend is reported with the results.
- The artifacts are reproducible from the frozen commit plus the
  immutable dataset tag, under the determinism contract.
- The claims bar holds: 95% CIs on every number, no blended figures,
  no rank claims from partial runs, and mock runs never back claims.
- Spend stays within the caps: $300 for the full run, $24 for Jev.

**Evidence**

- The run-registry entry and the sealed run artifacts.
- The ledger reconciliation, planned versus actual.
- The reproducibility record tying the artifacts to the frozen
  commit and the tag.

**Decision rule**

Mechanical completion plus reconciliation. A partial run is
disclosed as partial and makes no rank claims.

## A12 and A13 merge window

Only a P0 run-path fix may merge during A12 and A13. A merge
restarts the affected window. This is the restarts window from the
freeze decision.

## A13 - Blind holdout run

The phase is "blind holdout run". That means 500 cases,
pseudonymized IDs, and aggregate-only publication.

**Entry**

- A12 is complete.
- The holdout protocol is decided: a full blind re-run of the
  roster, or a subset. This is a maintainer decision, listed under
  open decisions below.

**Exit**

- The run completes: 500 holdout cases on the decided roster, with
  pseudonymized IDs and no suite or arm labels observable by
  adapters, so adapters cannot detect holdout runs.
- Results are published as aggregates only. Public and holdout
  numbers are never blended. The holdout governs the ranked number.
- The holdout query budget and the query log are updated.
- The ledger is reconciled to actuals.

**Evidence**

- The run-registry entry and the sealed run artifacts.
- The updated query budget and query log.
- The ledger reconciliation, planned versus actual.

**Decision rule**

Mechanical, with the blind protocol enforced throughout. Any
protocol breach invalidates the run.

## What is still open (maintainer decisions)

These six decisions belong to the program roadmap's decision list
and are distinct from this repo's architecture decision records in
docs/Decisions.md. The recommendation shown is the program
planning recommendation. The maintainer may override any of them.

- **Eval target.** Evaluate the frozen v1 now (recommended), or wait
  for the v2 families. Blocks A12 and A13.
- **Adapter roster.** Run the roster as-is and backfill gaps later
  as versioned append-only runs (recommended), add the Mistral and
  Qwen baselines first, or close every gap before the official run.
  Blocks the A12 composition and the leaderboard list.
- **Anthropic pin.** Decided 2026-10-02. Latest only:
  `claude-sonnet-5-5`. Blocks the A12 composition.
- **Holdout protocol.** A full blind re-run of the roster
  (recommended), or a subset. Blocks A13.
- **v2 in the announcement.** Mention v2 as an in-progress roadmap
  (recommended), or stay silent. Blocks the announcement, not the
  campaign.
- **Announcement post.** The maintainer writes or approves it. The
  results table with headline numbers and CIs is prepared for the
  maintainer.
  Blocks the announcement, not the campaign.

One more authorization is pending outside this list. The paid run
authorization for the live adapter smoke verification (about $2
under the standing cost-guard rule) is a precondition for A8 entry.

## What is mechanical (no maintainer call needed)

Everything else on this page is mechanical. That covers confirming
the gate items are resolved, declaring the freeze, cutting the tag, pinning
the commit, re-verifying pricing, planning ledger entries against
the caps, validating trial runs, checking the eight closure
criteria against their evidence, reconciling the ledger to actuals,
and holding the claims bar. The maintainer is called only for the
decisions listed above and for any estimate above the ask-first
thresholds.
