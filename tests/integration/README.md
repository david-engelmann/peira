# Integration suite

End-to-end coverage of the peira pipeline. Unit tests prove each
stage correct in isolation. This suite proves the stages agree with
each other, from dataset load through runner, metrics, artifact seal,
and report render.

## Files

| File | What it pins |
|---|---|
| `test_pipeline_end_to_end.py` | One cohesive run through every stage on a 20-case v1 sample |
| `test_family_coverage.py` | One case per shippable family (19/29) runs cleanly through runner + metrics |
| `test_mock_pipeline_behaviors.py` | flip_rate 0.0 -> ASR 0, 1.0 -> ASR 1, abstain -> refusal bucket |
| `test_pipeline_backend_parity.py` | Rust vs pure-Python backends, byte-identical sealed payloads |
| `test_artifact_roundtrip.py` | Seal -> JSON -> verify lossless; tampering breaks the seal; old versions rejected |
| `test_holdout_blindness.py` | Adapter boundary never sees case_id / arm / gold labels (D-25, D-28) |
| `test_pipeline_determinism.py` | Same seed -> same answers across concurrency levels |
| `test_compare_pipeline.py` | Two sealed runs pair up; mismatches are flagged |

## Running

```bash
.venv/bin/python -m pytest tests/integration -q
PEIRA_NO_RUST=1 .venv/bin/python -m pytest tests/integration -q
```

Budget: the whole suite must finish in well under 5 minutes (currently
~25s single-worker). Keep samples small and deterministic; the full
dataset belongs in evaluation runs, not in CI.

## Coverage audit

What existed before this suite, and what it adds.

Already covered elsewhere, not duplicated here:

- Function-level Rust/Python parity (`tests/test_*_rust_parity.py`,
  `tests/test_rust_execution_parity.py`): each dispatched function
  against its `_xxx_py` twin. This suite adds the pipeline level:
  byte-identical sealed payloads across backends.
- Runner unit behavior (`tests/test_runner.py`,
  `tests/test_adapter_runner_integration.py`): dispatch, retry,
  transcript, resume on the trial-demo fixture. This suite adds the
  dataset -> metrics -> artifact -> report chain on v1 samples.
- Determinism contract (`tests/test_determinism.py`): concurrency
  invariance on trial-demo. This suite extends it to the multi-family
  v1 sample.
- Artifact schema validation (`tests/test_artifacts.py`): field-level
  strictness. This suite adds the live seal -> write -> read ->
  verify path and tamper detection.
- Holdout separation at rest (`tests/test_holdout_separation_audit.py`,
  `tests/test_canary_separation.py`): repo-tree scans. This suite adds
  the runtime side: the adapter boundary never sees trial bookkeeping.

Known limitations, documented not hidden:

- 19 of 29 registered families have shippable case files; the other
  10 have registry entries but no cases yet, so no pipeline smoke
  can run for them. `test_family_coverage.py` lists the boundary.
- The holdout-blindness tests use synthetic holdout-style IDs. The
  real holdout is never touched (repo hard rule); the actual holdout
  execution path is therefore not exercised here.
- `test_compare_pipeline.py` covers the compare layer's pairing and
  compatibility checks as the downstream consumer of sealed
  artifacts. It was not in the original brief; it is kept because
  artifact version compatibility is only meaningful at a consumer.
- Under a fresh run nonce only headline metrics are pinned, not full
  sealed results: call IDs derive from the nonce by design, so they
  differ across nonces while the metrics reproduce.
