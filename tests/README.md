# Tests

## Tiers

The suite has distinct tiers. Place new tests in the right tier:

- **Unit tests** (`test_*.py` in this directory): Pin behavior of a single
  module. Examples: `test_metrics.py`, `test_gates.py`, `test_artifacts.py`.
  Must be xdist-safe (no shared mutable state, no order dependence).
  Use `tmp_path` for file writes, never the repo tree.

- **Rust-parity tests** (`test_*_rust_parity.py`): Assert the Rust core
  and the pure-Python reference produce identical outputs. Contract:
  both backends must be exercised (CI asserts `RUST_AVAILABLE` before
  the Rust-active leg); discrete values use `assertEqual`, floats use
  `assertAlmostEqual(places=12)` for the documented ~1 ulp summation
  difference; add a wiring assertion (`assertIs(mod._rust, _rust)`)
  so the test fails if dispatch is not actually reaching Rust.

- **Repo self-checks** (`test_check_*.py`): Lint-as-tests. They run the
  `scripts/check_*.py` scripts against the repo itself. If you add a
  new check script, add a corresponding test here.

- **Adapter tests** (`test_*_adapter.py`, `test_adapters.py`): Offline
  fakes by default. Live API tests are never in the default suite;
  they run under the cost guard in dedicated lanes.

- **Integration** (`tests/integration/`): End-to-end pipeline tests
  (dataset -> runner -> metrics -> artifact -> report). See
  `tests/integration/README.md`. These run in their own CI job
  (`test-integration`) with its own timeout budget.

Note: `test_adapter_runner_integration.py` and
`test_adapter_subprocess.py` live in `tests/` (not `tests/integration/`)
for historical reasons; they test adapter machinery, not the full
pipeline.

## Rules

- **xdist-safe**: `pytest -n auto` runs workers in separate processes.
  No shared mutable state across tests. If you mutate process-global
  state (cwd, env vars), restore it in try/finally.
- **Both backends**: New behavior tests must pass with and without
  `PEIRA_NO_RUST=1`. Run both locally before pushing.
- **No tautological tests**: Every test must be able to fail for a
  real reason (a bug in the code under test), not just a typo.
- **Timeout**: The per-test timeout is 900s. If your test legitimately
  needs more than ~60s, reconsider the fixture size.
