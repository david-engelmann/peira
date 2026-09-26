# Artifact Version Policy

**Status:** Policy — effective 2026-09-25
**Applies to:** `RunArtifact` (`python/peira/artifacts.py`, `crates/peira-core/src/artifact.rs`)

## The Two Principles

1. **Blank-canvas:** Peira has no users. We can break anything — formats,
   schemas, versions — to reach the best end state.

2. **Sealed measurements are sacred:** Once an official measurement is sealed
   (analysis lock computed, artifact published), it must remain verifiable
   forever. "Verifiable" means `peira validate` can confirm the seal and
   recompute the metrics. It does NOT mean the artifact must load in the
   latest peira — a migration tool is acceptable.

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
   - (b) Provide a `peira migrate-artifact` tool that converts old → new,
         with the migration itself being tested and the converted artifact's
         lock recomputed transparently.

2. **The analysis lock is version-scoped.** A v2 artifact's lock is computed
   over v2 fields. If v3 adds a field, the v3 lock covers it. An old artifact
   verified under v2 semantics remains valid — its lock doesn't change.

3. **Metrics recomputation must be version-aware.** `peira validate` recomputes
   metrics from results. If the metrics logic changes between versions, the
   validator must use the logic that matches the artifact's version, OR
   clearly label the recomputed metrics as "current-logic" vs "sealed-logic".

4. **Breaking changes require a changelog entry.** `docs/CHANGELOG.md` (or
   the artifact version history below) must document:
   - What changed
   - Why it was necessary
   - How to verify old artifacts under the new version

## Version History

| Version | Date | Changes | Verifies older? |
|---------|------|---------|-----------------|
| 1 | pre-2026-09-25 | Initial format | N/A (superseded) |
| 2 | 2026-09-25 | Metrics included in lock (P0-1). Pre-v2 artifacts fail `verify()`. | No — rejected with clear error. Acceptable: no sealed measurements exist. |

## What "Verifiable Forever" Means in Practice

A researcher in 2028 should be able to:

```bash
# Download a 2026 artifact
curl -O https://peiratrial.dev/artifacts/kev-4b-v2.1.0-v1.0.0.json

# Verify it (using a 2028 peira, or a pinned 2026 peira)
peira validate kev-4b-v2.1.0-v1.0.0.json
# → ✓ Analysis lock verified (artifact v2, verified under v2 semantics)
# → ✓ Metrics recomputed and match sealed values
```

If the 2028 peira can't do this natively, it must point to the migration tool
or a pinned historical version. "Just re-run it" is not an answer — the
model version may no longer exist.

## Implementation Notes

- The Rust core (`crates/peira-core/src/artifact.rs`) must implement the same
  version policy. Currently `suite` is `#[serde(default)]`, which yields `""`
  (an empty/unbound suite name) — the `"trial-demo"` string appears only in
  the test `sample()` fixture (`artifact.rs:282`), not in any default path.
  This should be reviewed for v1 compatibility.
- `peira validate` should report the artifact version in its output.
- Consider a `--artifact-version` flag on `peira run` for testing migrations.
