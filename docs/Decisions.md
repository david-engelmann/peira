# Decisions

Architecture Decision Records. New decisions get an entry here; the
reasoning stays with the repo.

## D-1: Rust core + Python SDK via PyO3

The hot paths (scoring, metrics, validation) will live in Rust; the adapter SDK,
CLI, and dataset tooling are Python. Rationale: contributors write adapters
in Python (zero friction), while the harness stays fast enough for
2,500-case runs on a laptop. Status: accepted; the Python reference
implementation freezes the interfaces first (Phase 0).
Update 2026-09-22: PyO3 wiring landed — `crates/peira-python` builds the
optional `peira._core` accelerator (`scripts/build_core_ext.py`);
`peira.metrics` / `peira.schema` dispatch to it with a pure-Python
fallback, and `tests/test_rust_backend.py` pins backend parity.

## D-2: No human baseline in v1

Human baselines are credible only with independent raters, which needs
contributors the project doesn't have yet. v1 ships without one rather
than with a biased single-rater number. Status: accepted, deferred to
post-v1.

## D-3: CC-BY-4.0 for the dataset, MIT for code

Code needs maximum reuse (MIT); the dataset needs attribution and a
non-training request (CC-BY-4.0). Status: accepted.
