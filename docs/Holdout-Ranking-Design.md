# Holdout ranking & CI re-execution — design

Status: design. Not implemented yet. This document is the build target for
the submission-pipeline slice; it changes nothing until that slice lands.

## Goals

1. Ranked leaderboard rows rest on holdout numbers, not on
   submitter-reported public numbers alone.
2. Every ranked submission publishes public-vs-holdout divergence per
   family, in the open.
3. Gaming evidence triggers a deterministic, pre-declared policy — the
   same response every time, not judgment calls under pressure.

## Submission pipeline

1. A submission is a PR adding a run artifact (public set) plus an
   adapter pin: adapter name, version, and configuration hash.
2. Public CI validates the artifact — schema, analysis lock, ranking
   gates — without touching the holdout.
3. A private CI context then *re-executes* the pinned adapter against the
   holdout: same adapter version, same runner flags, fresh seed.
   Re-execution, not trust: artifacts can be forged, so the holdout run
   is the verifier, not the submission.
4. The holdout manifest SHA is computed inside the private context and
   bound into the public leaderboard record. The SHA binds the run to an
   exact holdout snapshot without revealing a byte of it.

## What leaves the private context

Aggregates only: per-family ASR, benign accuracy, refusal rate, eligible
counts, and the divergence table. Never case text, never per-case
outcomes, never the holdout manifest content. Per-case holdout outcomes
stay private — published per-case results would let an adversary probe
which public cases have holdout twins.

## Divergence

Per family: `divergence = holdout_ASR − public_ASR` (and likewise for
benign accuracy). The leaderboard row shows public ASR, holdout ASR, and
Δ per family.

- Small, uniform Δ: healthy. The public set and the holdout agree; the
  adapter generalizes.
- Large positive ASR Δ concentrated in one or two families: investigate.
  That is the signature of public-set memorization — the adapter resists
  the public attacks it has seen (low public ASR) but not the holdout's
  (high holdout ASR). A uniform Δ points at a distribution shift, not at
  memorization; the family-local shape is what makes the signal
  interpretable.
- On disagreement, the holdout governs: the ranked number is the holdout
  number.

## Blind mode (decided: blind, 2026-09-23)

Holdout runs are blind: the adapter's trial context carries a run-scoped
pseudonym instead of the case id, and no arm flag — the runner knows
benign from attacked internally for scoring, but the adapter is not told.
Rationale: an adapter that can detect the attacked arm (or recognize a
case id) can behave differently under test than in the wild;
comparability of *scores* does not require identical *inputs*.

This needs a small runner change (a blind context mode), so it lands with
the implementation slice. Maintainer decision 2026-09-23: blind.

## Gaming policy

Evidence: sustained per-family divergence beyond the published
threshold — or, once canary pilots land (a later slice), a canary hit
corroborated by surrounding case text.

Response, in order:

1. Investigate. A canary can surface via a quoted blog post; divergence
   can have innocent causes. Evidence first, verdicts after.
2. While under investigation, the submission's public numbers are marked
   suspect and its ranked row falls back to holdout-only figures — dual
   reporting: both numbers visible, holdout authoritative.
3. Confirmed deliberate gaming: zero/unranked, with a public note stating
   what was found. No silent delisting: the policy is the deterrent, and
   deterrents work in the open.

The numeric divergence threshold is set from the first seasons of holdout
data and published *before* it is ever enforced. Declaring a cutoff
without data would be arbitrary; the threshold is a measurement, not a
guess.

## Non-goals (this slice)

- Slot-substitution invariance reporting on submissions (the generator
  exists — see `peira.probes` — wiring it into the pipeline is a later
  slice).
- Canary/watermark pilots, Sybil controls, paraphrase-controlled
  rankings: later slices.
- Statistical membership inference as a verdict: never. Weak signals are
  tripwires for investigation, not evidence for punishment.
