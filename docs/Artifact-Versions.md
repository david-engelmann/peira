# Artifact Version Policy

**Status:** Policy (effective 2026-09-25)
**Applies to:** `RunArtifact` (`python/peira/artifacts.py`, `crates/peira-core/src/artifact.rs`)

## The Two Principles

1. **Blank-canvas:** Peira has no users. We can break anything (formats,
   schemas, versions) to reach the best end state.

2. **Sealed measurements are sacred:** Once an official measurement is sealed
   (analysis lock computed, artifact published), it must remain verifiable
   forever. "Verifiable" means `peira runs verify` can confirm the seal
   against the artifact's own version semantics. It does NOT mean the
   artifact must load in the latest peira; a migration tool is acceptable.

These principles are in tension. This policy resolves the tension.

## Current State (2026-09-25)

- `ARTIFACT_VERSION = "2"`.
- `from_json()` **rejects** v1 artifacts with a clear error message.
- This is correct: there are no sealed v1 measurements yet. Nothing to preserve.

## The Policy

### Before the first sealed measurement

Break freely. Bump `ARTIFACT_VERSION`, reject old versions, no migration tool.
This is where we are now.

### After the first sealed measurement

The moment the first official artifact is sealed (the first `peira run --suite v1`
whose results are published), the following rules take effect:

1. **Never silently break verification.** If `ARTIFACT_VERSION` is bumped,
   `from_json()` must either:
   - (a) Still verify old versions (preferred for minor changes), OR
   - (b) Provide a migration path (a dedicated command or a pinned
         historical peira release) that converts old → new,
         with the migration itself being tested and the converted artifact's
         lock recomputed transparently.

2. **The analysis lock is version-scoped.** A v2 artifact's lock is computed
   over v2 fields. If v3 adds a field, the v3 lock covers it. An old artifact
   verified under v2 semantics remains valid; its lock doesn't change.

3. **Metrics recomputation must be version-aware.** Recomputing metrics from
   a sealed artifact's per-case results must use the logic that matches the
   artifact's version, OR clearly label the recomputed metrics as
   "current-logic" vs "sealed-logic". (`peira runs verify` confirms the
   seal; it does not recompute metrics. `peira validate` is dataset-only.)

4. **Breaking changes require a changelog entry.** `docs/CHANGELOG.md` (or
   the artifact version history below) must document:
   - What changed
   - Why it was necessary
   - How to verify old artifacts under the new version

## Version History

| Version | Date | Changes | Verifies older? |
|---------|------|---------|-----------------|
| 1 | pre-2026-09-25 | Initial format | N/A (superseded) |
| 2 | 2026-09-25 | Metrics included in lock (P0-1). Pre-v2 artifacts fail `verify()`. | No; rejected with clear error. Acceptable: no sealed measurements exist. |
| 2 | 2026-09-27 | Environment fingerprint added: `env` (dict) and `env_sha256` (str) fields. The `env_sha256` is part of the analysis lock. Pre-2026-09-27 v2 artifacts fail `verify()` (the lock payload changed); acceptable per blank-canvas, no sealed measurements exist. | No; old v2 artifacts fail verification (lock mismatch). |

## Environment Fingerprint (2026-09-27)

Every artifact now records the environment it ran in:

- `env`: Full environment dict (Python version, peira version, torch/transformers/numpy versions, CUDA availability, OS, architecture, Rust backend availability)
- `env_sha256`: SHA-256 of the canonical JSON encoding of `env`

The `env_sha256` is part of the analysis lock. Two runs with different
`env_sha256` values are *explained* (the environment differed), not
mysterious. Use `peira runs list` to see the 8-character env fingerprint
prefix for each run,
and `peira runs compare` (future) to diff environments between runs.

The fingerprint is computed by `python/peira/env_fingerprint.py` at run start
and sealed into the artifact. See the module docstring for the full field list.

## Report Artifacts (2026-10-01)

`peira report --json-out report.json` writes a versioned report
artifact alongside the HTML. The HTML alone is not reproducible.
Buyer-cost parameters change the rendering, so the report artifact
seals the source artifact's provenance (path, artifact version,
analysis lock, env fingerprint, manifest digest, adapter, suite,
dataset version, seed), the report parameters, and the metric
payload under its own analysis lock.

- `artifact_kind`: `"report"`
- `report_schema_version`: `"1"`
- The loader is strict like the run artifact's. Unknown fields are
  rejected and non-`"1"` schema versions are refused.
- `verify()` detects any post-hoc edit to the sealed content.

## What "Verifiable Forever" Means in Practice

A researcher in 2028 should be able to:

```bash
# Download a 2026 artifact
curl -O https://peiratrial.dev/artifacts/kev-4b-v2.1.0-v1.0.0.json

# Verify it (using a 2028 peira, or a pinned 2026 peira)
peira runs verify kev-4b-v2.1.0-v1.0.0.json
# → ✓ Analysis lock verified (artifact v2, verified under v2 semantics)
```

If the 2028 peira can't do this natively, it must point to the migration tool
or a pinned historical version. "Just re-run it" is not an answer; the
model version may no longer exist.

## Implementation Notes

- The Rust core (`crates/peira-core/src/artifact.rs`) must implement the same
  version policy. Currently `suite` is `#[serde(default)]`, which yields `""`
  (an empty/unbound suite name). The `"trial-demo"` string appears only in
  the test `sample()` fixture (`artifact.rs:282`), not in any default path.
  This should be reviewed for v1 compatibility.
- `peira runs verify` should report the artifact version in its output.
- Consider a `--artifact-version` flag on `peira run` for testing migrations.
