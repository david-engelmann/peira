# Compare and report: interpretation guide

This guide explains how to read `peira compare` and `peira report`
output. It covers what each number means, what the confidence intervals
tell you, and when a difference is real.

## The headline numbers

Every peira report starts with the same core metrics:

- **ASR (attack success rate).** The fraction of eligible cases where
  the attacked-arm decision differs from the benign-arm decision. Higher
  means the adapter is more vulnerable. Always reported with a Wilson
  95% confidence interval.
- **Benign accuracy.** The fraction of benign-arm decisions matching the
  gold label. This is the "does it work at all" check. An adapter with
  low benign accuracy is broken, not robust.
- **Eligible cases.** Cases that passed the eligibility gates (benign
  decision correct, benign arm well-formed, no abstention). Ineligible
  cases are excluded from ASR, never silently counted as passes.

## Reading confidence intervals

A report might show:

```
ASR: 0.3333 95% CI 0.1381-0.6094
```

This means: the point estimate is 33%, but the true ASR could plausibly
be anywhere from 14% to 61%. With only 12 cases, the interval is wide.
With 400 cases per family, it tightens considerably.

**Overlapping intervals are not ties.** If adapter A has ASR 0.30
(CI 0.25-0.35) and adapter B has 0.35 (CI 0.30-0.40), the intervals
overlap but A is still probably better. Peira reports "ahead in X% of
resamples" for this reason. See `docs/Methodology.md` for the bootstrap
procedure.

## The "not resolvable at this n" convention

Before reading any leaderboard as containing wins, check the per-family
minimum detectable effect (MDE) table. If the MDE for a family is 8pp
and two adapters differ by 3pp, that difference is not resolvable at
this sample size. The report flags this. Do not claim a win the data
cannot support.

## Compare view

`peira compare` takes two or more run artifacts and produces:

- **Paired McNemar test.** For each pair of adapters on the same cases,
  tests whether their flip rates differ. Paired means the same cases,
  so case difficulty cancels out.
- **Bradley-Terry strengths.** A latent strength per adapter from all
  pairwise comparisons. Compare view only, never a ranker, never on the
  leaderboard.
- **Per-family win/tie/loss.** Which adapter flipped less, family by
  family. Ties are reported as ties with the data shown.

## Calibration section

If the adapters report confidence scores, the report includes:

- **Reliability diagrams.** Predicted confidence vs observed accuracy,
  per arm (benign and attacked separately).
- **ECE (expected calibration error).** Lower is better. Reported
  per arm because attack can destroy calibration even when accuracy
  looks fine.
- **All confidence labels are "self-reported."** Peira does not verify
  that a confidence score means what the adapter claims. The label is
  honest about this limitation.

## What not to do

- Do not average ASRs across families into a single number. Families
  measure different attacks. Report per family.
- Do not blend public and holdout numbers. The holdout governs the
  ranked result. The public set is for development.
- Do not claim a leaderboard win without checking the MDE table.
