# Claims

What peira claims, what it doesn't, and what's still unverified. This page
indexes the load-bearing claims; detail lives in the linked docs.

## We claim

- peira measures whether hostile input manipulations change typed decision
  outputs, with paired benign/attacked controls, across the documented
  attack families.
- Every public score will link to per-case drill-down receipts.
- Run artifacts are sealed with an analysis lock; `peira report` warns on
  lock mismatch.
- The attacked-arm decision curve carries an isotonic-recalibration
  upper-bound envelope (C-3). It is display-only, never a ranker, and
  slightly optimistic because the fit is in-sample.
- The private holdout's raw cases will never be published while they are
  holdout cases; aged-out cases enter the public set on the declared
  schedule (see `Holdout-OpSec.md`), and only aggregate metrics leave the
  maintainer's machine.
- The economic lottery index always reports the pair of robustness
  stability and economic stability. It never reports the economic index
  without the robustness index beside it (see `Methodology.md`).
- `peira dataset build-manifest` writes Croissant 1.0 metadata as
  `croissant.json` next to `manifest.json`, with per-file SHA-256 digests
  and a machine-readable recordSet for the paired-case schema. Croissant
  records ship for the v1, v2, trial, and safety-policy suites.
- Dataset-release tags are recorded in the immutable registry at
  `data/dataset-releases.json`, binding each tag to the manifest and
  croissant digests at the tag. Tags are never moved and entries are never
  edited. CI verifies the whole registry on every PR.
- Cases may carry optional PROV-style `provenance` fields
  (`generated_by`, `generated_at`, `was_derived_from`,
  `was_attributed_to`), validated identically by the Python and Rust
  backends.
- Leaderboard rows carry a `provenance` object with the full measurement
  tuple. It holds the adapter name, version, revision, and spec, plus the
  suite, dataset version, manifest digest, seed, pricing version and date,
  environment digest, and contract version.
- Every manifest build runs nine automated validation gates, G1 schema
  through G9 near-dedup, and refuses the seal while any gate reports
  an error. The v2 suite was sealed before this enforcement landed and
  carries 544 disclosed G9 near-duplicate flags in its
  verbosity_inflation family. See DATASHEET.md.
- Every headline number ships with a 95% confidence interval.
- No measured numbers are published from an adapter that has not
  passed its live smoke. The smoke procedure, and the publication
  block it lifts, is documented in `docs/live-verification.md`, which
  extends the D-33 precedent to the A6 adapters. D-33 itself covers
  the Tier 1 adapters and is recorded in `docs/Decisions.md`.
- Third-party adapters run isolated in a subprocess child by default
  (runner-owned shim, scrubbed environment, per-child resource
  limits, process-group kill on timeout). The boundary is
  blast-radius containment and killability, not a security sandbox.
- Blind-holdout integrity rests on the content-free adapter boundary
  (D-25), not on the sandbox: the adapter-visible surface is
  identical between public and holdout runs by construction, and no
  PR widens it without a holdout-integrity review.
- The conformance kit (`peira adapter check`) raises the cost of
  adapter cheating from zero to "must carry evasion code past
  review." It does not prove the absence of retry loops or metadata
  sniffing.
- Run artifacts seal `adapter_trust` and `adapter_transport` with
  the distribution name, version, and module SHA-256, so every
  leaderboard number is traceable to the exact bits that produced
  it.

## We don't claim

- That a good score certifies a model as safe. (Non-certification notice,
  README.)
- That the attack families cover every attack shape. They don't.
- That synthetic cases equal real incidents. They model attack shapes.
- That the subprocess boundary makes untrusted code safe to run. It
  does not filter syscalls or network egress, and it does not change
  UIDs. Only run adapters you trust.
- That a conformance pass endorses the package. A community table row
  states that a given set of bits passed the kit on a given date,
  nothing more.
- That the cryptographic_payload cases measure a live guardrail gap. They
  simulate the guard context (a BLOCKED notice) and the in-context decode
  instructions as a proxy for the proposed execution-context mechanism.
  Empirical demonstration with a guardrail in the loop is future work.
- That the frequency_salience cases measure real-world name-frequency
  effects. They simulate administrative filler repeating an entity as a
  proxy for the Laya name-frequency failure mode. Empirical demonstration
  in the original setting is future work.

## Unverified

- Calibration of the headline numbers against real-world deployment
  outcomes. That's future work, tracked in the issue tracker, not asserted
  here.
