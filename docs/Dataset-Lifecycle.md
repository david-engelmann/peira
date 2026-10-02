# Dataset Lifecycle

This document says what happens to dataset material over time.
What redaction is done and not done. How deletion and retirement
actually work, mechanically. What the threat model covers and what
it does not. Read it before asking for a case to be removed.

## What redaction is not done

peira does not redact the dataset to protect adapter vendors.
Cases are published as authored, including cases that embarrass
specific models. A case is never softened because a vendor asked,
and never withheld because a result would be inconvenient.

Redaction that IS done is narrower.

- Real user data. Fixtures derived from real interactions are
  redacted before entering the repo. The redaction is noted on the
  fixture. See `docs/adding-an-adapter.md`.
- Credentials and secrets in authored cases. An author who
  pastes a real key into a case gets the key revoked and the case
  rewritten, not a quiet edit.

## Deletion and retirement mechanics

Deletion and retirement are different operations with different
guarantees. They are not interchangeable.

**Retirement** removes a case or shard from the ranked set. The
files stay in the repo. The case keeps its id. The dataset changelog
records the retirement, the reason, and the version it took effect
in. Retired cases are excluded from leaderboards once the exclusion
mechanism lands. Today no retired-list is consumed by the runner,
so treat retirement as a changelog-level operation with leaderboard
exclusion planned, not yet enforced. See
`docs/Refresh-Burn-Retirement-Policy.md`.

**Deletion** removes the bytes. There are two levels, described
below.

- **Manifest tombstone.** The case id is marked deleted in the
  dataset manifest, and the case body is removed from the published
  JSONL. The id is never reused. Downstream copies that already
  hold the bytes are unaffected. peira cannot reach into someone
  else's disk. The tombstone exists so re-published versions stay
  consistent and nobody silently re-adds the id.
- **Full removal.** Tombstone plus removal from the git history of
  the dataset repo, where the law or a safety incident requires it.
  This rewrites history. It is done rarely, loudly, and with a
  public note saying it happened. It does not delete copies other
  people made.

Git tags on sealed dataset versions are immutable. A sealed tag is
never rewritten, even for a deletion. Deletion produces a new
version with the tombstone. The old tag keeps pointing at the old
bytes. Immutability of sealed versions is the trust model. If you
need the bytes gone from a sealed tag, you are asking for the
trust model to be broken, and the answer is no.

## Threat model

The lifecycle policy defends against specific threats. They are
listed below.

- **Training-data contamination.** Cases leaking into vendor
  training sets. Defended by the holdout rotation, the burn
  triggers, and the prohibition on publishing holdout contents.
  See `docs/Contamination-Policy.md`.
- **Goalpost-moving.** Dataset changes that flatter a vendor.
  Defended by publishing every rule while it is still
  hypothetical, by the changelog schema, and by tag immutability.
- **Silent case surgery.** Quiet edits to scored cases. Defended
  by the post-hoc edit prohibition in AGENTS.md and the sealed
  artifact lock.

## Out of scope

- peira does not police what vendors do with public cases. Once
  published, a case can be trained on, quoted, or memed. The
  holdout exists because the public set is assumed compromised
  from birth.
- peira does not offer embargoed pre-briefs to vendors. No vendor
  sees cases before publication. See the no-pre-briefs commitment
  in the project record.
- peira does not delete leaderboard history. A retired adapter or
  a retired case keeps its historical rows. History is the product.
- peira does not guarantee that a deleted case is gone from the
  internet. It guarantees the tombstone, the changelog entry, and
  the new version. Copies are out of its hands.

## Requesting a removal

Open an issue naming the case id and the reason. Security or
privacy reasons go through the private security channel in
SECURITY.md, not the public tracker. The operator decides between
retirement, tombstone, or full removal, and records the decision in
the dataset changelog. The default answer to a removal request is
retirement, not deletion.
