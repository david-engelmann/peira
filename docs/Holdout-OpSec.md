# Holdout OpSec

The private holdout is peira's ranking backstop: 500 cases across the ten
attack families, mirroring the public set's severity mix, that are never
published. Public cases are assumed exposed — training corpora,
write-ups, paraphrase. The holdout is the clean re-test.

This document states the operating *policy*, never the *contents*.
Assume the adversary reads it: every control below holds when known.
The secrecy of the contents is the only secret.

## What it is

- 500 cases: the ten full families × 50, the public set's severity
  mix, so public-vs-holdout divergence is interpretable per family.
  (Whether the private holdout draws from the eleventh family,
  safety_policy, is an open holdout-design question —
  `dataset/v1/safety_policy_SPEC.md` §8.3.)
- The anti-memorization control for the public set, and the tiebreaker
  for every gaming dispute (see `Holdout-Ranking-Design.md`).

## What it is not

- Not purchasable, not requestable. No contributor, vendor, or researcher
  access — ever. There is no form to fill out.

## Access

Two parties, no more:

1. The maintainer.
2. The CI system, for the duration of a holdout re-execution run.

"Just for debugging" is not access grounds — debugging uses the public
set. Access is never broadened temporarily; temporary access is how
holdouts die.

## Storage and transfer

- Encrypted at rest, maintainer-held keys. The public repo never sees the
  key, a key fragment, or anything that identifies the key.
- Transferred only over authenticated channels to the CI runner executing
  the holdout run — never to shared, ephemeral, or personal machines.
- Once canary pilots land (a later slice — see `Holdout-Ranking-Design.md`
  §Non-goals; no v1 canaries until the packaging phase), every copy will
  carry a unique per-copy canary GUID, so a leak is attributable to the
  copy it came from. The canary is a tripwire, not a fence: a hit
  triggers investigation, never automatic punishment.

## The contamination rule

Holdout bytes never appear in:

- the public repo, including git history — one accidental push ends the
  holdout's useful life;
- CI logs, artifacts, or caches of any public job;
- error messages, transcripts, or published run artifacts;
- the dataset manifests shipped in this repo;
- any prompt, completion, or tuning payload sent to a third party.

Public runs and holdout runs are separate invocations. The public CI
configuration cannot address holdout storage, and holdout jobs never
upload their working directories.

## Freshness and rotation

- The holdout is a living pool, not a fixed set. The refresh cadence is
  declared in advance (standing: quarterly top-up with newly authored
  cases). The cadence is public; the contents never are.
- Every case carries an author timestamp. Ranked rows may be computed on
  post-cutoff slices — only cases authored after a model's knowledge
  cutoff count for that model. Cutoff dates are vendor-claimed and
  treated as such: the slice is a control against accidental
  contamination, and the holdout's secrecy is the backstop against the
  adversarial case.
- Suspected compromise rotates the affected shard immediately. The
  rotation is disclosed publicly — that it happened and which family
  shard was affected. The new contents are not.
- Cases age out of the holdout into the public set on a declared
  schedule. A holdout that never refreshes becomes the thing it was built
  to prevent: a static, memorizable set.

## On a suspected leak

Treat the holdout as compromised first and investigate second: rotate the
affected shard, disclose the rotation, then determine what happened. The
order matters — a slow response spends the one asset the holdout has.
