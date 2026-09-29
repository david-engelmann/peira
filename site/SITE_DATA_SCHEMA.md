# Site data schema (v1)

The contract between the ingestion pipeline (`site/scripts/ingest.py`)
and the Astro site (`site/src`). Both sides must honor this file. Bump
`schema_version` and document the change here if the shape ever changes.

## Top level

```json
{
  "schema_version": "1",
  "generated_utc": "2026-09-29T18:00:00+00:00",
  "mock_data": true,
  "peira_version": "0.9.0",
  "dataset": {
    "name": "peira-v1",
    "version": "1.1.1",
    "manifest_sha256": "abc123..."
  },
  "runs": [ <run> ]
}
```

- `mock_data`: true when every run came from synthetic artifacts. The
  site renders a banner on every page while this is true. Never ship a
  build with `mock_data: true` as if it were real.
- `dataset`: taken from the artifacts' `dataset_version` fields (all
  runs in one build must agree, else ingest fails). `manifest_sha256`
  is the artifacts' `manifest_sha256` (empty string when unbound).

## Run object

```json
{
  "adapter_name": "shieldstral-1.0",
  "adapter_version": "2026-09-01",
  "model_class": "guardrail",
  "suite": "public",
  "dataset_version": "1.1.1",
  "created_utc": "2026-09-29T17:00:00+00:00",
  "analysis_lock": "sha256...",
  "ranking_eligible": true,
  "eligibility_notes": [],
  "metrics": { "...": "verbatim peira.metrics.summarize() output" },
  "cases": [
    {
      "case_id": "v1-spo-001",
      "family": "state_poisoning",
      "severity": "critical",
      "primitive": "choice",
      "benign_decision": "deny",
      "attacked_decision": "approve",
      "flipped": true,
      "eligible": true
    }
  ]
}
```

- `suite` is `"public"` or `"holdout"`. The toggle switches between them.
- `metrics` is the verbatim `summarize()` dict. Views read:
  - Leaderboard: `asr_conditional`, `asr_ci95`, `benign_accuracy`,
    `benign_accuracy_ci95`, `n_eligible`, `ranking_eligible`
  - Families: `per_family` (each: `n`, `n_eligible`, `asr`,
    `asr_ci95`, `refusal_rate`, `flip_direction_counts`)
  - Calibration: `calibration.reliability_bins.benign`,
    `calibration.reliability_bins.attacked`, `calibration.benign.ece`,
    `calibration.attacked.ece`, `calibration.delta_brier`
  - Frontier: `asr_conditional` vs `cost.total_cost_usd` (or
    `cost_per_1k_decisions`) vs `latency_ms.overall.p99`
  - Compare: two runs' `cases` joined on `case_id`; per-case flip
    agreement plus headline delta with CIs
  - Cases: the `cases` array (search/filter client-side)
- `cases` decisions are strings; `flipped`/`eligible` are booleans.
  Withheld metric values are `null` (never NaN).

## Ingest rules (enforced by `ingest.py`, not by convention)

1. Every artifact must parse via `RunArtifact.from_json` and `verify()`
   must pass. A broken lock fails the build loudly.
2. `artifact_version` must be `"2"`.
3. Mock discipline: `--mock` ingests only artifacts whose
   `config.mock is true`; without `--mock` any mock artifact is
   rejected. Real and mock never mix in one build.
4. All runs in one build must share `dataset_version`.
5. `suite` must be `public` or `holdout`.
