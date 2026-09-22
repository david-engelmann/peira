# Version compatibility

`peira` (the package) and the dataset carry **independent semantic
versions**.

- `peira run` refuses a dataset whose major version it doesn't support,
  with an upgrade pointer. You never discover incompatibility by getting
  wrong numbers.
- `peira validate --dataset <dir>` checks compatibility offline.
- The leaderboard keeps one row per (adapter, dataset version) pair, so
  scores stay comparable within a dataset version.

| peira | dataset v1.x | dataset v2.x |
|---|---|---|
| 0.1.x | ✅ | ❌ (upgrade peira) |
| 1.x | ✅ | ✅ |

The matrix is checked in CI against the packaging metadata.
