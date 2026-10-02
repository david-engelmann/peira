# Test Suite Audit — peira (agentic-dev-audit, fc289590)

Read-only audit. Method: static scans of all 121 `tests/test_*.py` + 8
`tests/integration/` files; `pytest --collect-only` (3346 tests collected);
timed samples (test_artifacts 6.6s, tests/integration 15s, test_metrics.py
254s); order-dependence sample (gates+artifacts in both orders, both green);
targeted reads of 15 recently-added files for tautology review. Tests were
run in a scratch venv in /tmp with PYTHONPATH=python (pure-Python backend,
PEIRA_NO_RUST=1); the checkout itself was not modified.

## Ranked findings

### P1 — Silent Rust-fallback hides Rust bugs from parity tests

Every Rust dispatch site follows this shape (example:
`python/peira/artifacts.py:806-808`, `RunArtifact.compute_lock`):

```python
if _rust is not None:
    try:
        return _rust.artifact_lock_payload(...)
    except (TypeError, ValueError, OverflowError):
        pass
return self._compute_lock_py()
```

There are **24 dispatch sites** across artifacts, combo_metrics, compare,
concurrency, dataset, economics, env_fingerprint, gates, hardness, metrics,
pricing, runner, schema, and others. If the Rust implementation raises
`TypeError`/`ValueError`/`OverflowError` on real inputs — a genuine bug in
the ported code — the dispatched function silently returns the Python result.
The parity test then compares the dispatched function against the
`_xxx_py` twin, i.e. **Python against Python, and passes**. The Rust bug is
completely invisible to the test suite.

This is not hypothetical design nitpicking: the whole rust-max program
rests on parity tests catching divergence, and the fallback converts an
entire bug class (Rust-side exceptions) into silent passes.

Evidence:
- `python/peira/artifacts.py:753-808` — 50-argument dispatch wrapped in
  try/except-fallback.
- Same pattern at 24 sites (`grep -A3 "if _rust is not None:" python/peira`
  | 24 `try:` follow-ups).

Recommendation: add a strict dispatch mode (e.g. `PEIRA_STRICT_RUST=1`
re-raises instead of falling back) and run the Rust-active CI leg
(`test-python-rust`, `.github/workflows/ci.yml:340`) with it. The
`economics.py` pre-validation gate (`_require_economics_rust_input`,
`python/peira/economics.py:71`, asserted in
`tests/test_economics_rust_parity.py:43-117`) is the model pattern:
validate inputs first, then dispatch without a catch-all.

### P2 — test_metrics.py is the suite's long tail: 254s, single tests 31-131s

Slowest durations measured (`-n auto`, pure-Python backend):

| test | time |
|---|---|
| `TestSummarize::test_summarize_without_required` | 130.8s |
| `TestSummarize::test_per_family_eligible_counts` | 80.1s |
| `TestMetricsSummarize::test_score_section_unavailable_without_references` | 36.2s |
| `TestMetricsSummarize::test_no_composite_no_bradley_terry` | 35.4s |
| `TestS9ConfidenceIntervalCoverage::test_compression_index_unavailable_branch_shape` | 31.5s |

Root cause: 21 of 34 `summarize()` calls in `tests/test_metrics.py` use
the default `n_boot=10000` bootstrap (`python/peira/metrics.py:6413`).
Tests that pin summary *wiring* (per-family counts, branch shapes,
unavailable-section branches) do not need 10k bootstrap draws; `n_boot=100`
pins the same behavior ~100x cheaper. Under xdist each worker is serial, so
a 131s single test gates the suite's tail latency directly.

Fix: pass a small `n_boot` in wiring-shape tests; keep one test at the
default to pin bootstrap behavior. Expected saving: ~200s off this file.

### P2 — test_rust_lane4_parity.py parity tests can't prove they touched Rust

`tests/test_rust_lane4_parity.py` (1725 lines) covers the lane-4 ports
(artifacts lock, runner record helpers, dataset, concurrency, pricing,
env_fingerprint) as dispatcher-vs-`_xxx_py` parity. Its own docstring
(lines 21-24) admits: "The parity tests pass whether or not
`peira._core` is built." Nothing in the file asserts the dispatch actually
used Rust for any of its six modules — no per-module wiring assertion
(`assertIs(mod._rust, _rust)`), which 7 of the other 10 parity files do
have (e.g. `tests/test_combo_metrics_rust_parity.py:37`,
`tests/test_combo_schema_rust_parity.py:58-63`). Only the
`RustBoundaryTypes` class at line 1506 is gated on `RUST_AVAILABLE`.

Combined with the P1 silent fallback: a Rust regression (or an un-wired
dispatch) in any lane-4 module is invisible in the Rust-active leg. The
file's saving grace is its independently-computed known vectors (e.g.
`test_known_vector_independent`, line 186: lock digest recomputed with
hashlib/json from a literal payload — genuinely behavioral), which still
pin the reference. The *parity* half, though, is toothless without a
wiring assert.

### P2 — No test taxonomy for agents; the real tiers are undocumented

`tests/integration/README.md` is excellent (file table, coverage audit,
known limitations). But there is **no `tests/README.md`** and
`docs/Contributing.md` mentions tests only as "keep pytest green" plus a
one-liner about `test-integration`. The actual taxonomy an agent must
reverse-engineer from filenames:

- unit tests (`test_metrics.py`, `test_gates.py`, `test_artifacts.py`, ...)
- Rust-parity tests (10 `test_*_rust_parity.py` + `test_rust_backend.py`,
  `test_rust_execution_parity.py`, `test_rust_lane4_parity.py`)
- repo self-checks (`test_check_doc_links.py`, `test_check_families.py`,
  `test_check_trial_version_pins.py`) — lint-as-tests, a distinct tier
- pin tests (`test_api_pins.py`, `*_adapter.py` model pins)
- adapter tests (21 files, offline fakes + HF contract tests)
- integration (`tests/integration/`, 8 files)
- `tests/test_adapter_runner_integration.py` — named "integration" but
  lives in `tests/`, not `tests/integration/`, blurring the boundary the
  README draws. Same for `test_adapter_subprocess.py`.

121 files in one flat directory. An agent adding a test has no documented
answer to "where does this belong, and what tier conventions apply
(xdist-safety rules, tmp_path discipline, backend-both-modes requirement)?"
Recommend a `tests/README.md` (or a Contributing section) naming the tiers,
the placement rule, and the parity-file contract (both modes, wiring
assert, known vectors preferred).

### P3 — Weak/self-referential assertions in parity files

- `tests/test_economics_rust_parity.py:281-286` (`DrummondHolteParity`):
  compares `drummond_holte_curves(...)[1]` (pure-Python crossover
  statements) against a *second call of the same function*. Can only fail
  on nondeterminism — a determinism self-check masquerading as a parity
  assertion.
- `BackendUnderTest` classes (`test_economics_rust_parity.py:43`,
  `test_combo_metrics_rust_parity.py:36`) `print()` which backend ran but
  don't fail when Rust is absent-but-expected. CI covers this
  (`.github/workflows/ci.yml` asserts `RUST_AVAILABLE` before the
  Rust-active leg), but a local dev who never built the extension gets
  trivially-passing parity tests with only a print hint. Consider
  `PEIRA_REQUIRE_RUST=1` support in the parity helpers for local runs.

### P3 — process-global cwd mutation in test_doctor.py

`tests/test_doctor.py:525-533` does `os.chdir(tmp_path)` / restore with
try/finally. Correct as written and xdist-safe (workers are separate
processes), but it is process-global mutable state: any future test in the
same worker that assumes cwd is a latent order-dependence bug. Prefer
passing the path explicitly (the function under test already takes it).

### P3 — 900s per-test timeout is generous for a 3346-test suite

`pyproject.toml` `[tool.pytest.ini_options]`: `timeout = 900`,
`timeout_method = "thread"`. A genuinely hung test blocks an xdist worker
for 15 minutes before the suite reports. With legit tests now taking
130s (P2), the headroom between "slow" and "hung" is thin. Consider
per-file timeout markers (e.g. the integration suite already budgets
"well under 5 minutes" in its README; encode it).

## What the audit verified as healthy (no action)

- **xdist safety is genuinely good.** `tests/adapter_test_plugin.py`
  installs a fake dist into site-packages but serializes across workers
  with an atomic-mkdir file lock (`_install_lock`, lines 215-244) and
  cleans up when not under xdist. All file writes found go to
  `tmp_path`/`TemporaryDirectory` (test_canary_separation, test_s1_verify,
  test_author_benign_twins). Env mutations are subprocess-scoped
  (`test_rust_backend.py:587`) or try/finally-restored
  (`test_kev_adapter.py:56-61`, `test_doctor.py` chdir). No unseeded
  `random`/`numpy.random` use in tests. Order-dependence sample
  (test_gates.py + test_artifacts.py) passes in both orders.
- **Hot paths are pinned behaviorally, not just importably.**
  `metrics.summarize` has hand-computed assertions
  (`test_metrics.py:2403+`, Wilson intervals computed independently in the
  test). The artifact lock (canonicalization) has a literal
  independently-computed known vector
  (`test_rust_lane4_parity.py:186`). Gates have per-gate rejection tests
  (`test_gates.py:65-353`). Ingest has fail-closed gate tests against the
  real artifact code path (`test_site_ingest.py`).
- **No outright tautological tests found** in the 15 sampled files
  (economics/combo parity, all 8 integration files, site_ingest,
  api_pins, mock). Parity files honestly document their trivial-pass mode
  (`test_combo_schema_rust_parity.py:14-17`); pin tests assert literals
  (`test_api_pins.py:48-61`); integration tests assert cross-layer
  semantics with explanatory docstrings
  (`test_mock_pipeline_behaviors.py`).
- **CI runs both backends** and asserts `RUST_AVAILABLE` before the
  Rust-active leg (`.github/workflows/ci.yml:340-364`, `:375-395`); the
  HF contract lane even greps for zero skips. Collection is clean: 3346
  tests, 0 collection errors (with dev deps installed).
- **Property tests exist** (`test_invariant_properties.py`, hypothesis).

## Suggested fix order for the parent

1. P1 silent-fallback: strict-dispatch mode + CI leg (kills a whole hidden
   bug class; prerequisite for trusting the rust-max parity story).
2. P2 n_boot: mechanical, ~200s suite saving, safe.
3. P2 lane-4 wiring asserts: small, mirrors the existing pattern in 7
   sibling files.
4. P2 tests/README.md: cheap, high agent-leverage.
5. P3s as drive-bys.
