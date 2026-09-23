# leaderboard.json

Machine-readable leaderboard rows, emitted from sealed run artifacts.
This document is the data contract between the benchmark pipeline and
the static site: the site renders `leaderboard.json`; it never
recomputes metrics.

## Producing it

[`scripts/emit_leaderboard.py`](../scripts/emit_leaderboard.py) reads
one or more v2 run artifacts, verifies each artifact's analysis lock,
and projects each into one row:

```bash
python3 scripts/emit_leaderboard.py runs/a.json runs/b.json --out leaderboard.json
python3 scripts/emit_leaderboard.py --dir runs --out leaderboard.json
```

[`.github/workflows/leaderboard.yml`](../.github/workflows/leaderboard.yml)
runs the script in CI against the mock trial run and uploads the
result as a workflow artifact.

## Trust model

- An artifact whose analysis lock does not verify is **refused**: it is
  never silently included in the output.
- The lock is **unkeyed tamper evidence, not authenticity**. It binds
  the sealed metrics against accidental edits, but anyone who can run
  `seal()` can forge an artifact with a valid lock (re-sealing is a
  documented non-goal of `verify()` — see
  `python/peira/artifacts.py`). A public leaderboard MUST NOT treat a
  verified lock as proof of who produced the run: ingestion must
  re-score from the sealed transcripts or require signatures.
- `run_id` is the SHA-256 of the artifact file bytes — the row's
  content identity. Re-fetch the artifact bytes and re-hash to check
  any row independently. (It identifies the file bytes, not the
  abstract run: re-serializing identical content yields a different
  `run_id`.)
- `manifest_bound` tells whether the run sealed a dataset manifest
  digest. Empty means the run is explicitly unbound, not silently
  bound.
- The metric numbers are the runner's sealed summary, passed through
  unchanged. They are deterministic from the sealed results, which the
  verified lock binds.

## Trial suites stay off the public leaderboard

Per [D-8](Decisions.md#d-8-trial-suite-runs-stay-off-the-public-leaderboard):
runs against the trial suites are never published to the leaderboard;
the leaderboard starts with v1. The emitter enforces this
mechanically: `--exclude-suite` defaults to `trial,trial-demo`, and
excluded artifacts are counted in `n_excluded_suites`. The CI workflow
passes `--exclude-suite=` (empty) to opt out, because its smoke run
uses the trial suite only to exercise the emission pipeline.

**Any publisher of a public `leaderboard.json` MUST exclude rows whose
`suite` is a trial suite** (`trial`, `trial-demo`). The default flag
does this; a publisher that overrides `--exclude-suite` takes on the
obligation explicitly.

## Schema (version 1)

Top-level document:

| Field | Type | Meaning |
|---|---|---|
| `leaderboard_schema_version` | string | `"1"`. See Versioning below. |
| `generated_utc` | string | ISO-8601 UTC timestamp of emission. |
| `generator` | string | Always `"scripts/emit_leaderboard.py"`. |
| `emitter_peira_version` | string | `peira` version that ran the emitter. |
| `n_rows` | integer | Number of rows (equals `len(rows)`). |
| `n_excluded_suites` | integer | Artifacts skipped by `--exclude-suite` (D-8). |
| `rows` | array | One row per verified artifact, sorted by `run_id`. |

Each row:

| Field | Type | Meaning |
|---|---|---|
| `run_id` | string | SHA-256 hex of the artifact file bytes; the row's content identity (byte identity, not run identity). |
| `artifact_sha256` | string | Same digest, named for artifact-fetching consumers. |
| `adapter_name` / `adapter_version` | string | Who was measured, pinned version. |
| `suite` | string | Suite id, e.g. `v1`. Trial suites are never published (see above). |
| `dataset_version` | string | Dataset label the run claims. |
| `manifest_sha256` | string | Digest of the suite manifest bytes; empty when unbound. |
| `manifest_bound` | boolean | Whether `manifest_sha256` is non-empty. |
| `peira_version` | string | `peira` version that produced the artifact. |
| `pricing_source` / `pricing_date` | string | Pinned pricing table provenance sealed in the lock. |
| `seed` | integer | Run seed sealed in the lock. |
| `created_utc` | string | Artifact creation timestamp. |
| `analysis_lock` | string | The artifact's analysis-lock hash. |
| `lock_verified` | boolean | Always `true`; unverified artifacts are refused. |
| `n_cases` / `n_eligible` | integer | Case counts from the sealed summary. |
| `asr_conditional` | number | Attack success rate among eligible cases. |
| `asr_ci95` | `[lo, hi]` | Wilson 95% interval for `asr_conditional`. |
| `benign_accuracy` / `benign_accuracy_ci95` | number / `[lo, hi]` | Benign accuracy with Wilson 95% interval. |
| `refusal_rate` / `refusal_rate_ci95` | number / `[lo, hi]` | Attacked-variant refusal rate with Wilson 95% interval. |
| `malformed_rate` | number | Fraction of malformed adapter outputs. |
| `ranking_eligible` | boolean | Whether the run passed the ranking gates. |
| `eligibility_notes` | array of string | Gate failures; empty when eligible. |
| `ineligible_by_reason` | object | Ineligible-case counts by reason. |
| `per_family` | object | Per-family `{n, n_eligible, asr, asr_ci95, refusal_rate}`. |

`asr_ci95` and the other intervals are Wilson 95% intervals as defined
in [Methodology](Methodology.md).

## Versioning

`leaderboard_schema_version` is an integer-as-string, currently `"1"`.
Additive field additions keep the version. Any breaking change
(renamed/removed fields, changed semantics) bumps it, and consumers
MUST reject versions they do not understand.

## Out of scope for this slice

- **Per-case drill-down JSON** (case-level results for a case
  explorer): a follow-up slice; the sealed artifacts already carry the
  per-case records it would project.
- **Trust tiers** over rows (e.g. CI-verified vs self-reported): a
  follow-up slice. The raw fields tiers would be computed from —
  lock verification, manifest binding, pricing provenance — are all in
  every row.
