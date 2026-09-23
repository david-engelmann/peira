# Version compatibility

`peira` (the package) and the dataset carry **independent semantic
versions**.

What works today:

- Every run artifact records the suite's `dataset_version` in its
  analysis lock, and `peira run` verifies the suite manifest before
  scoring — a tampered dataset fails closed.
- `peira validate --dataset <dir>` checks a dataset directory's case
  files against the schema.

Planned (design intent, not implemented):

- `peira run` will refuse a dataset whose major version it doesn't
  support, with an upgrade pointer. You never discover incompatibility by
  getting wrong numbers.
- The leaderboard will keep one row per (adapter, dataset version)
  pair, so scores stay comparable within a dataset version.

Planned compatibility matrix:

| peira | dataset v1.x | dataset v2.x |
|---|---|---|
| 0.1.x | ✅ | ❌ (upgrade peira) |
| 1.x | ✅ | ✅ |

The matrix will be checked in CI against the packaging metadata.
