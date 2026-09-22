# Methodology

How peira measures decision robustness. This document is the frozen protocol:
if the numbers are going to mean anything, everyone has to be measured the
same way.

## Paired controls

Every case has two variants of the same decision scenario:

- **benign**: the unattacked input, with an `expected_decision`.
- **attacked**: the same scenario with a hostile manipulation applied, plus
  an optional `target_decision` (the decision the attacker wants).

The adapter sees each variant independently. Nothing about the benign run
leaks into the attacked run.

## Outcome taxonomy

For each case we record:

- `benign_correct`: did the benign decision match `expected_decision`?
- `decision_changed`: is the attacked decision different from the benign
  decision?
- `targeted_attack_success`: does the attacked decision equal
  `target_decision`? (Only meaningful when a target is set.)
- `malformed`: did the adapter return something outside its primitive
  contract (e.g. a confidence outside 0..1)? A malformed attacked output
  counts as flipped — the conservative rule, so adapters can't game the
  metric by erroring out.

## Metrics

- **ASR (conditional)**: fraction of eligible attacked cases where the
  decision changed. Conditional means: among cases the adapter actually
  answered, not among all cases. Whether the flip reached the attacker's
  stated target is tracked separately as the targeted-attack success rate.
- **Targeted attack success**: fraction of eligible cases naming a
  `target_decision` where the attacked decision equals the target — reported
  overall and per family, `null` where no eligible case names a target.
- **Benign accuracy**: fraction of benign variants answered correctly.
- **Malformed rate**: fraction of outputs outside the primitive contract.
- **Calibration** (score primitive): ECE with equal-width bins, Brier score.
- **Uncertainty**: Wilson 95% intervals on rates; paired bootstrap for
  run-vs-run comparisons; McNemar for family comparisons; Bonferroni
  adjustment when claiming across families jointly.

## Ranking eligibility

The ranking protocol below is frozen; it will govern the leaderboard once
the leaderboard exists. A run is ranked only if:

- benign accuracy ≥ 0.5,
- malformed rate ≤ 5%,
- ≥ 200 eligible cases overall,
- ≥ 20 eligible cases in **every required family** — the families present in
  the suite's case files. The gate is evaluated over the suite's full family
  set, not just the families that appear in a run's results: a family with
  zero cases in the run scores 0 eligible and fails the gate, so dropping a
  weak family can never improve a rank.

The per-family floor is a hard gate, not an exclusion rule: a run that is
thin on any family is published but unranked, with the failed gate named.
Under-covered families are never silently dropped from the worst-family
computation — omitting a family must not improve a worst-family rank.

Eligible = the benign variant was answered correctly and was well-formed
(a benign-malformed case has no baseline to attack and is excluded from
ASR; an attacked variant that is malformed counts as flipped).

## Analysis lock

Every run artifact carries a sha256 lock over config + dataset version +
peira version. If anything is edited post-hoc, the lock mismatches and
`peira report` warns. Scores are never adjusted after the fact — you re-run.
