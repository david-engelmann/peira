# Execution Contract

This document states exactly what peira guarantees about run-to-run
reproducibility, and what it does not. It describes the code as it is:
where a field is timing-dependent, the document says so instead of
pretending otherwise. The executable form of this contract is
`peira/repro.py` (normalization and comparison primitives),
exercised by `tests/test_repro.py` and applied by
`scripts/check_determinism.py` in CI. `tests/test_determinism.py`
tests the runner directly with its own normalization helpers.

## The precise claim

Two runs with identical (env, dataset, adapter, seed, config)
fingerprints produce identical `results` arrays, except for the
documented timing and telemetry fields on each call record.
`usage.latency_ms`, `latency_ms_total`, and the `timing_ms`
decomposition are wall-clock measurements, and `dispatch_limit` is
the concurrency the AIMD controller had in effect when the call was
dispatched.

Note the scope: the claim is about the `results` arrays, not the whole
artifact file. The artifact envelope also carries per-run values (a
fresh nonce, timestamps), so two runs never produce byte-identical
artifact files. `call_id` does not appear in the `results` arrays at
all; it lives only in the transcript.

## Deterministic

- **Case order in the artifact.** Results are sealed in suite order
  (`_sort_results`), never completion order. Concurrent runs finish
  cases out of order; the artifact does not record that order.
- **`dispatch_index` values.** Derived from the case's suite position:
  benign is `2i`, attacked is `2i+1` for the case at index `i`.
  Resumed runs re-derive the same indices, so a resume records
  identical indices to an uninterrupted run.
- **Retry jitter sequence.** The backoff for a retry is drawn from
  `random.Random(retry_jitter_seed(seed, dispatch_index, attempt))`,
  a pure function of the run seed, the call's dispatch index, and the
  attempt number. The same seed always yields the same jitter sequence
  for the same call, independent of completion order.
- **Decisions, confidences, scores, flips, eligibility.** Pure
  functions of the adapter's outputs and the case gold. (Determinism
  of the harness is conditional on determinism of the adapter; see
  below.)
- **Metric values, except the latency sidecar.** Every rate,
  confidence interval, and calibration number is a pure function of
  the results plus the run seed: bootstrap PRNGs are seeded, so the
  same seed and results always produce the same summary. The one
  exception is `metrics["latency_ms"]`, which summarizes wall-clock
  measurements.
- **Cost accounting.** `usage.cost_usd` is recomputed from the pinned
  pricing table, never taken from the adapter. Same tokens, same
  table, same cost.
- **The analysis lock, as an integrity seal.** `verify()` recomputes
  the lock deterministically: an unmodified artifact always verifies,
  a modified one never does. The lock is not a cross-run equality
  check (see below).

## Not deterministic

- **Wall-clock timing.** `usage.latency_ms` is measured with
  `perf_counter` around each call. It varies with machine load,
  provider latency, and concurrency. The `metrics["latency_ms"]`
  percentiles vary with it. The same holds for `latency_ms_total`
  and the R-12 `timing_ms` decomposition on each call record, and
  for the `metrics["timing_ms"]` rollup. All are wall-clock
  measurements and all are excluded from rerun comparison.
- **Completion order.** Tasks finish in whatever order the event loop
  and the provider dictate. Nothing in the sealed results records
  this order.
- **`dispatch_limit`.** Each call record carries the AIMD
  controller's live limit at the moment the call was dispatched. The
  controller slow-starts from 1 and doubles on every success, so the
  recorded value depends on how many calls had completed before this
  one was dispatched, which is timing-dependent. At
  `max_concurrency=1` it is always 1; at higher caps it is a mix that
  is stable in practice but not contractual. Treat it as operational
  telemetry, not measurement. This is why the precise claim excludes
  it alongside timing.
- **Call IDs.** Each run mints a fresh nonce (`secrets.token_hex(16)`),
  and every call ID is derived from `(nonce, seed, dispatch_index)`.
  The same `(seed, dispatch_index)` yields a different ID in every
  run, by design: adapters cannot correlate calls across runs or
  detect holdout runs by ID. Call IDs appear in the transcript, not in
  the results arrays.
- **Whether a timeout fires, and therefore attempt counts.** A
  `call_timeout` that expires on a loaded machine might not on an
  idle one. A timeout produces a terminal `<error>` record, so a run
  near the timeout edge can legitimately differ from an identical run
  on faster hardware.
- **API-model outputs at temperature > 0.** The runner cannot make a
  sampling model deterministic. If the adapter is nondeterministic,
  the results are nondeterministic, and no harness setting changes
  that.
- **The artifact envelope across runs.** `config.run_nonce` is fresh
  per run, `created_utc` differs, and the analysis lock covers both
  plus the timing-dependent fields above. Two runs never produce
  byte-identical artifact files, even when their results arrays match
  modulo the documented fields.

## Comparing two runs

To check that a rerun reproduced a run: normalize the documented
non-deterministic fields (`usage.latency_ms` and `dispatch_limit` on
each benign/attacked record) and compare the `results` arrays for
equality, then compare `metrics` with the `latency_ms` block
normalized. `peira.repro.normalize_artifact` and
`peira.repro.compare_artifacts` do exactly this; `tests/test_repro.py`
covers them as unit tests, and `scripts/check_determinism.py` applies
them to real CLI reruns in CI.

## Out of scope

- The opt-in response cache is keyed deterministically (adapter,
  version, namespace, primitive, variant, case, input, manifest). A
  warm cache changes timing, which is excluded above; it does not
  change decisions.
- This contract covers one uninterrupted `run_suite` execution.
  Resume replays prior results verbatim from the sealed partial; the
  resumed suffix follows the same contract under the new run's nonce.
