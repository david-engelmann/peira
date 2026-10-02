# Tests

## Tiers

The suite has distinct tiers. Place new tests in the right tier.

**Unit tests** live as `test_*.py` in this directory. They pin behavior
of a single module. Examples are `test_metrics.py`, `test_gates.py`,
and `test_artifacts.py`. They must be xdist-safe with no shared mutable
state and no order dependence. Use `tmp_path` for file writes. Never
write to the repo tree.

**Rust-parity tests** live as `test_*_rust_parity.py`. They assert the
Rust core and the pure-Python reference produce identical outputs.
The contract requires both backends to be exercised. CI asserts
`RUST_AVAILABLE` before the Rust-active leg. Discrete values use
`assertEqual`. Floats use `assertAlmostEqual(places=12)` for the
documented ~1 ulp summation difference. Add a wiring assertion such as
`assertIs(mod._rust, _rust)` so the test fails if dispatch is not
actually reaching Rust.

**Repo self-checks** live as `test_check_*.py`. They are lint-as-tests.
They run the `scripts/check_*.py` scripts against the repo itself. If
you add a new check script then add a corresponding test here.

**Adapter tests** live as `test_*_adapter.py` plus `test_adapters.py`.
They use offline fakes by default. Live API tests are never in the
default suite. They run under the cost guard in dedicated lanes.

**Integration** lives in `tests/integration/`. These are end-to-end
pipeline tests covering dataset to runner to metrics to artifact to
report. See `tests/integration/README.md`. They run in their own CI job
named `test-integration` with its own timeout budget.

Note that `test_adapter_runner_integration.py` and
`test_adapter_subprocess.py` live in `tests/` not `tests/integration/`
for historical reasons. They test adapter machinery not the full
pipeline.

## Rules

**xdist-safe**. The command `pytest -n auto` runs workers in separate
processes. There is no shared mutable state across tests. If you mutate
process-global state such as cwd or env vars then restore it in
try/finally.

**Both backends**. New behavior tests must pass with and without
`PEIRA_NO_RUST=1`. Run both locally before pushing.

**No tautological tests**. Every test must be able to fail for a real
reason such as a bug in the code under test, not just a typo.

**Timeout**. The per-test timeout is 900s. If your test legitimately
needs more than about 60s then reconsider the fixture size.
