# peira governance

How peira is run, who decides, and what happens when something goes wrong. Short on purpose.

## Project lead

David Engelmann is the project lead. He has final authority on admission disputes, methodology changes, and releases. If a rule here is silent or two rules conflict, his call is the decision.

## Admission and submission rules

The rules for getting on the leaderboard are published at [docs/Admission-Rules.md](docs/Admission-Rules.md). They exist before the leaderboard opens, and the leaderboard does not open before they do.

## Public dispute process

Every leaderboard row ships with a provenance bundle. It names the pinned adapter revision SHA, the dataset version, and the seed. Anyone can re-run that row from the bundle.

If your re-run lands outside the reported confidence interval, that is a material discrepancy. File it as a GitHub issue with the `dispute` label. The maintainer re-validates the row, and the whole thing happens in public. The issue stays open until the row is corrected, withdrawn, or confirmed.

## Succession and maintenance mode

If the project lead becomes unavailable, maintainership passes to a named successor or the repo enters maintenance mode.

Maintenance mode is defined. No new leaderboard rows are published. Existing data stays published. The docs stay up. Security fixes to the repo itself continue. Nothing else moves.

This is stated here so there is no ambiguity about what happens next.
