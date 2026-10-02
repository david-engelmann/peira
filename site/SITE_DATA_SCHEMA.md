# Site data schema (v2)

The contract between the ingestion pipeline (`site/scripts/ingest.py`)
and the Astro site (`site/src`). Both sides must honor this file. Bump
`schema_version` and document the change here if the shape ever changes.

## Changelog

- v2: runs carry the v3 extension blocks (`run.v3`): threat model,
  attack provenance, adjudication identity, exposure attestation, and
  the other agent-consumer fields from
  `research_notes/peira-run-artifact-research-20260928.md`. The blocks
  ride sealed inside the artifact's `config.v3` until the real v3
  schema lands in `peira.artifacts` (which will move them to top-level
  fields and update the ingest reader). Ingest now enforces the
  run_status gate: a v3-bearing artifact whose `run_status` is not
  `"success"` is rejected (the Inspect rule, which says never analyze a
  non-successful run). Pure-v2 artifacts without v3 blocks
  ingest exactly as in v1 (no `v3` key on the run object).
- v1: initial sealed-artifact ingestion.

## Top level

```json
{
  "schema_version": "2",
  "generated_utc": "2026-09-29T18:00:00+00:00",
  "mock_data": true,
  "peira_version": "0.1.0",
  "dataset": {
    "name": "peira-v1",
    "version": "1.1.1",
    "manifest_sha256": "abc123..."
  },
  "runs": [ <run> ]
}
```

- `mock_data` is true when every run came from synthetic artifacts. The
  site renders a banner on every page while this is true. Never ship a
  build with `mock_data: true` as if it were real.
- `dataset` is taken from the artifacts' `dataset_version` fields (all
  runs in one build must agree, else ingest fails). `manifest_sha256`
  is the artifacts' `manifest_sha256` (empty string when unbound).

## Run object

```json
{
  "adapter_name": "shieldstral-1.0",
  "adapter_version": "2026-09-01",
  "model_class": "guardrail",
  "division": "guardrail",
  "suite": "public",
  "dataset_version": "1.1.1",
  "created_utc": "2026-09-29T17:00:00+00:00",
  "analysis_lock": "sha256...",
  "ranking_eligible": true,
  "eligibility_notes": [],
  "metrics": { "...": "verbatim peira.metrics.summarize() output" },
  "v3": { "...": "verbatim v3 extension block (see below); absent on pure-v2 artifacts" },
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
- `metrics` is the verbatim `summarize()` dict. The views read the
  fields below.
  - The leaderboard reads `asr_conditional`, `asr_ci95`,
    `benign_accuracy`, `benign_accuracy_ci95`, `n_eligible`,
    `ranking_eligible`
  - The families view reads `per_family` (each entry carries `n`,
    `n_eligible`, `asr`, `asr_ci95`, `refusal_rate`,
    `flip_direction_counts`)
  - The calibration view reads `calibration.reliability_bins.benign`,
    `calibration.reliability_bins.attacked`, `calibration.benign.ece`,
    `calibration.attacked.ece`, `calibration.delta_brier`
  - The frontier view reads `asr_conditional` against
    `cost.total_cost_usd` (or `cost_per_1k_decisions`) and
    `latency_ms.overall.p99`
  - The compare view joins two runs' `cases` on `case_id` and shows
    per-case flip agreement plus the headline delta with CIs
  - The cases view reads the `cases` array (search and filter run
    client-side)
- `cases` decisions are strings, while `flipped` and `eligible` are booleans.
  Withheld metric values are `null` (never NaN).

## v3 block

`run.v3` is the verbatim v3 extension block from the sealed artifact
(`config.v3` until the real v3 schema lands). Every key below comes from
`research_notes/peira-run-artifact-research-20260928.md`; the mock
generator (`site/scripts/gen_mock.py`) exercises all of them.

```json
"v3": {
  "run_id": "01J...",
  "parent_run_id": null,
  "supersedes": [],
  "run_status": "success",
  "metrics_version": "peira-metrics-0.1.0-contract-1",
  "adjudication_policy_version": "peira-adjudication-1",
  "threat_model": {
    "attacker_access": "black_box_api",
    "attacker_knowledge": "adapter_identity_only",
    "query_budget_per_case": 1,
    "adaptive": false
  },
  "attack_provenance": {
    "attacker_model": "mock-attacker",
    "attacker_model_version": "mock-1",
    "attack_budget": { "variants_per_case": 1, "restarts_per_case": 1 },
    "attack_method": "static_template"
  },
  "exclusion_log": [
    { "case_id": "v1-spo-001", "arm": "benign", "reason_code": "benign_malformed" }
  ],
  "determinism_check": { "passed": true, "mismatches": 0, "sample_n": 50 },
  "exposure_attestation": {
    "case_subset": "public",
    "blindness_protocol_id": "mock-blind-1",
    "prior_exposure_attestation": "...",
    "holdout_access_log_ref": null
  },
  "adapter_pinning": {
    "provider_snapshot": null,
    "hf_revision": null,
    "code_sha": "mock",
    "code_dirty": false
  },
  "schema_ref": "https://peiratrial.dev/schemas/run-artifact/v3.json",
  "license": "CC-BY-4.0",
  "access_tier": "public",
  "retention_policy": "indefinite",
  "reference_baseline": {
    "undefended_asr": 0.97,
    "clean_task_retention": 0.99,
    "baseline_adapter": "mock-always-approve"
  },
  "run_group_id": "mock-group-7",
  "repetition_index": 0,
  "planned_repetitions": 1,
  "uncertainty": {
    "ci_method": "bootstrap",
    "ci_level": 0.95,
    "ci_unit": "per_case_bootstrap",
    "multiple_comparison": "none",
    "familywise_alpha": 0.05
  },
  "hardware": { "cpu": "mock", "gpu": null, "ram_gb": 16, "cuda": null },
  "wall_clock": { "started_utc": "...", "ended_utc": "..." },
  "retry_policy": {
    "per_call_timeout_s": 30,
    "max_retries": 0,
    "total_retries": 0,
    "rate_limit_hits": 0
  },
  "cache_policy": {
    "cache_enabled": false,
    "cache_key_scheme": null,
    "cache_hits": 0
  },
  "per_family": [
    { "family": "state_poisoning", "n": 24, "n_eligible": 24,
      "asr": 0.5, "ci_lo": 0.31, "ci_hi": 0.69 }
  ],
  "submitter_provenance": {
    "submitted_by": "mock-generator",
    "submission_channel": "internal_ci",
    "verification_level": "self_reported"
  },
  "dependency_lock": { "lockfile_sha256": null, "container_digest": null },
  "threshold_policy_version": null,
  "sampling_plan": null
}
```

Closed vocabularies (ingest rejects anything outside these):
`run_status` in {started, success, cancelled, error, partial};
`threat_model.attacker_access` in {black_box_api, gray_box, white_box};
`attack_provenance.attack_method` in {static_template, adaptive_search};
`exposure_attestation.case_subset` in {public, private, blind};
`access_tier` in {public, internal, confidential};
`submitter_provenance.submission_channel` in
{internal_ci, vendor_self_report, third_party};
`submitter_provenance.verification_level` in
{self_reported, independently_reproduced};
`uncertainty.ci_method` in {bootstrap, wilson, binomial};
`uncertainty.multiple_comparison` in {holm, bonferroni, none};
`exclusion_log[].reason_code` in {timeout, rate_limit, api_error,
parse_failure, refused_to_format, benign_abstained, benign_malformed,
benign_wrong_decision, attacked_malformed};
`exclusion_log[].arm` in {benign, attacked}.

## Ingest rules (enforced by `ingest.py`, not by convention)

1. Every artifact must parse via `RunArtifact.from_json` and `verify()`
   must pass. A broken lock fails the build loudly.
2. `artifact_version` must be `"2"`.
3. Mock discipline stays mechanical. `--mock` ingests only artifacts
   whose `config.mock` is true. Without `--mock` any mock artifact is
   rejected. Real and mock never mix in one build.
4. All runs in one build must share `dataset_version` and `manifest_sha256`.
5. `suite` must be `public` or `holdout`.
6. `config.mock` must be a real boolean.
7. Every artifact must carry a non-empty `metrics` mapping.
8. No two artifacts may share one `adapter_name`, `adapter_version`,
   `suite` identity. The dashboard keys runs by that triple, so a
   duplicate would silently shadow its twin.
9. Sealed payloads must contain no NaN or Infinity. Withheld values are
   null, never NaN, and the emitted JSON is written with `allow_nan`
   off so a non-finite value fails the build instead of shipping
   nonstandard JSON.
10. v3 extension blocks (`config.v3`) are optional on v2 artifacts. When
    present they must be well-formed: all required keys present, every
    enum value inside its closed vocabulary (see "v3 block" above), and
    the exclusion log typed. A malformed block fails the build.
11. The run_status gate: a v3-bearing artifact whose `run_status` is not
    `"success"` is rejected. Only successful runs feed the site data;
    partial/cancelled/error runs are analyzable by hand but must never
    flow into the leaderboard pipeline silently.
12. v3 blocks are carried into the site data verbatim as `run.v3` so the
    views can read threat model, attack provenance, adjudication
    identity, exposure attestation, and the other agent-consumer fields
    without recomputing them. Pure-v2 artifacts have no `v3` key.
