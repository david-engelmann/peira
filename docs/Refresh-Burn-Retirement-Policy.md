# Refresh, Burn, Saturation, and Retirement Policy

peira is a living benchmark. Cases age, models memorize, and families
stop telling adapters apart. This document states in advance how the
dataset changes over time, so no change can ever look like moving the
goalposts. Every rule below was published while it was still
hypothetical. (R-13, D-37)

## Refresh

The public dataset and the blind holdout are refreshed on a declared
cadence, not on vibes.

- The holdout is topped up every calendar quarter with newly authored
  cases, and the oldest shard rotates into the public set. The cadence
  is public. The new contents never are. See
  `docs/Holdout-Query-Budget.md` and `docs/Holdout-OpSec.md`.
- Every refresh is recorded in the published refresh changelog, which
  follows the schema in `docs/Dataset-Changelog.md`. Each entry states
  what changed, why, and the resulting dataset version. Sealed versions
  are immutable. A refresh always produces a new version.
- Cases that rotate out of the holdout into the public set keep their
  original author timestamps, so cutoff-sliced analyses stay honest.

## Burn triggers

A burn is an unscheduled retirement of a dataset shard. There are two,
and both have teeth.

**Suspected compromise.** If the operator suspects a holdout shard has
leaked, the shard rotates immediately. The rotation is disclosed
publicly, naming the affected family shard. The new contents are not.
Investigation follows the rotation, not the other way around. A slow
response spends the one asset the holdout has. See
`docs/Holdout-OpSec.md`.

**Public versus holdout divergence.** If a family's public-set ASR and
its holdout ASR diverge anomalously for two consecutive ranking
seasons, the public shard for that family is retired from the ranked
set. A season is one quarterly ranking release. Anomalous means the
per-family gap between public and holdout ASR exceeds the family's
paired MDE (R-02 `mde_mcnemar`) in the same direction twice in a row.
The MDE is used here as the family's resolution floor, the smallest
adapter difference the family can resolve. A gap smaller than that is
noise. A gap larger than it, twice in a row in the same direction, is
a pattern, and it means the public shard is measuring something
different from the holdout. The bar is two seasons, not one, because
a single season of divergence can be noise, adapter churn, or a bad
quarter for one vendor. On retirement the public cases for that
family are pulled from the ranked set and replaced by freshly
authored cases. The retired cases stay public, clearly marked, so
past results remain reproducible.

## Saturation and retirement per family

Each attack family carries its own saturation state, computed per
release. The policy is per family, never a blended number. A blended
saturation metric can hide a dead diagnostic family behind a lively
average, which is exactly how aggregate benchmarks go stale without
anyone noticing.

The five states and their criteria are decided in D-37 and implemented
by `peira saturation`. In plain language.

- A family is **discriminating** when at least one adapter pair's ASR
  gap exceeds the paired MDE. It still separates adapters, so it
  stays. Discrimination takes precedence over bound compression. A
  family near the floor or ceiling that still resolves a pair is not
  retired, because retirement is loss of discrimination, not proximity
  to a bound.
- A family in **uniform failure** has no resolving pair and mid-range
  scores. The attacks work about equally on everyone. The response is
  harder variants, not retirement.
- A family that is **ceiling saturated** has no resolving pair and
  every adapter's Wilson 95% CI sits entirely above the 0.95 ceiling.
  The attacks succeed on everyone. The response is harder variants.
- A family is **exhausted** when no pair resolves and every adapter's
  Wilson 95% CI sits entirely below the 0.05 floor. It becomes a
  retirement candidate only after the criterion holds for two
  consecutive releases, and the old leaderboard becomes the regression
  suite for whatever replaces it. Near-zero ASR must be genuine
  robustness rather than memorized cases, so the exhausted definition
  also requires low variant-flip, and until that check ships, an
  exhausted family is a candidate, never an automatic retirement.
- A family with **insufficient data** (fewer than two adapters, or
  fewer than 20 eligible cases) is monitored, not judged.

Holdout families are never retired. Their state is reported and their
action is capped at monitoring, because the blind holdout is the
regression suite, not the capability hill.

## Pre-registered analysis plans

The monthly State of Decision Robustness report runs a pre-registered
analysis plan, published here before the data it analyzes exists. The
point is the same as everywhere else in this document. If the analysis
could be reshaped after seeing the numbers, the numbers stop meaning
anything.

Each monthly report covers the following at minimum.

- Per-family ASR with Wilson 95% intervals for every ranked adapter
  line, on the holdout. The holdout governs the ranked number.
- The D-37 saturation state of every family, with the per-release
  trigger fields (`exhaustion_trigger_met`, `retirement_eligible`,
  `releases_observed` against `releases_required`).
- The R-09 leave-one-family-out ranking stability check, so the
  Benchmark Lottery critique is answered with peira's own data every
  month.
- Calibration artifacts per R-11, computed on the public set with the
  reasoning disclosed.
- The public-versus-holdout divergence check that feeds the burn
  trigger above.
- New adapter lines ranked since the last report, with their
  training-exclusion disclosure flags. See
  `docs/Submission-Disclosure.md`.
- Any shard rotations, burn events, or disclosure incidents since the
  last report, with dates.

Anything the report analyzes beyond this plan is labeled as
exploratory in the report itself. Anything in the plan that the report
skips is labeled as omitted, with the reason. The plan is versioned.
Changes to the plan take effect for the following month's report, never
retroactively.
