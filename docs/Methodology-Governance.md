# Methodology governance

How the leaderboard stays honest after the methodology is frozen. This page is about process. The measurement contract itself lives in [Methodology.md](Methodology.md).

## Verified rows

A submission is a run bundle, not a claim. Nobody gets verified status on their word alone.

Before a row earns the verified badge, maintainers re-run a random subset of its cases with the bundle's pinned adapter revision, dataset version, and seed. If the re-run matches within the reported confidence interval, the row is verified.

Rows that have not been through this process must be labeled "peira-derived, unverified". They appear on the site. They never appear in the headline ranking.

## Saturation and successor policy

Benchmarks die by saturation. The policy for peira's death is written before it is needed.

The trigger is quantitative. If the median top-5 adapter ASR falls below 5% for two consecutive releases, the current version is declared saturated.

A saturated version is not patched into relevance. A successor version ships with harder families, and the leaderboard moves to the successor. GLUE to SuperGLUE is the pattern. Old versions stay published for comparison, and their rows are not backfilled.

## Adaptive attacks welcome

Static cases are a starting point, not the whole story. External adaptive evaluations are explicitly invited.

For every adapter, the leaderboard will track the best known ASR across all attack suites, not just the static v1 cases. If your adaptive suite breaks an adapter harder than v1 does, that number counts and it is attributed to your suite. The leaderboard is a record of the strongest known attacks, not a monument to the shipped ones.

## Uncertainty discipline

Confidence intervals on the leaderboard are marginal. Two intervals that overlap are not a tie. They are two uncertain estimates whose relationship is not settled.

Separation must be tested on the difference within resamples. The leaderboard reports the share of resamples in which one adapter is ahead of the other, for example "ahead in 97% of resamples". When resamples show no separation, the leaderboard reports a tie. A tie is a legitimate outcome of the analysis, not a failure to decide.

Thin slices must be dropped. A low-n cell is not shown with false precision. It is shown as insufficient data or not shown at all.

## Contamination assumption

Public cases are assumed contaminated from day one. Any model could have seen them in training, and the leaderboard does not argue about whether it did.

The sealed 500-case holdout is the scoring authority. It is never published, not even as IDs. Headline rankings rest on the holdout. Public cases are for development and transparency.
