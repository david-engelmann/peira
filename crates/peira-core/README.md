# peira-core

Rust core for peira: the hot paths (metrics, schema validation, artifact
hashing) implemented in Rust for safety, performance, and maintainability.
The Python package (`python/peira/`) remains the **reference
implementation**; this crate must produce bit-identical outputs.

## Layout

- `src/metrics.rs` — Wilson CI, McNemar, Brier score, ECE, ASR/accuracy
  aggregation. Includes `accurate_sum`, a correctly-rounded summation
  bit-exact with Python's `math.fsum` (port of CPython's `math_fsum`).
- `src/adapter_protocol.rs` — language-agnostic adapter protocol: run any
  adapter as a subprocess speaking JSON lines over stdin/stdout.
- `src/artifacts.rs` — SHA-256 / artifact sealing helpers.
- `src/schema.rs` — case schema validation.
- `src/python.rs` — PyO3 bindings exposing the hot paths to Python as the
  optional `peira._peira_core` extension module.

## Building

```bash
cargo test -p peira-core      # Rust unit tests — must stay green
cargo build --release -p peira-core
```

The PyO3 extension is an **optional accelerator**. The pure-Python package
works without it (`peira._rust.available` is `False`) and keeps zero
third-party runtime dependencies. To use the compiled extension in a dev
checkout, build the release cdylib and place it where `peira._rust`
expects it:

```bash
cargo build --release -p peira-core
cp target/release/libpeira_core.so \
   python/peira/_peira_core.cpython-312-x86_64-linux-gnu.so
```

(Adjust the filename suffix for your Python version/platform; e.g.
`.cpython-311-x86_64-linux-gnu.so`, `_peira_core.cp311-win_amd64.pyd` on
Windows, `libpeira_core.dylib` renamed appropriately on macOS.)

Then verify bit-exact parity with the reference implementation:

```bash
PYTHONPATH=python python -m pytest tests/test_rust_parity.py -q
```

The parity claim is strict: randomized comparisons assert `==`, not
approximate equality. If they fail, the Rust code is wrong — never weaken
the tests without a deliberate contract decision.

> **Packaging note (not yet done):** there is no maturin/setuptools-rust
> integration yet; the `.so` copy above is a dev-only step. The intended
> direction is a maturin mixed Rust/Python build producing
> `peira._peira_core` wheels, keeping the pure-Python install
> dependency-free.

## Correctness notes

- **Summation is correctly rounded.** Python's builtin `sum()` is only
  correctly rounded on some interpreter builds; peira pins `math.fsum`
  in `python/peira/metrics.py` and `accurate_sum` here, so published
  numbers are identical on every interpreter and platform.
- **ECE binning** compares against the actual edge doubles (`b / bins`),
  exactly like the reference — no `ceil` shortcut — so probabilities on an
  edge land in the lower bin.
- **Error mapping:** the bindings raise `ValueError`/`OverflowError`
  where the reference raises `AssertionError`/overflows; documented in
  `python/peira/_rust.py`.

## Phase 2 plan (Rust migration)

Per the project direction — move as much into Rust as possible; Python
keeps the CLI, the adapter SDK, and thin wrappers:

1. **Schema validation** — complete `schema.rs`, make it authoritative
   behind thin Python wrappers. (Blocked on freezing the Phase 0 case
   schema per repo `AGENTS.md`.)
2. **Artifact sealing/verification** — port fully to Rust (`artifacts.rs`).
3. **Runner core** — port case iteration, the adapter-call orchestration
   boundary, result aggregation, and resume/checkpoint invariants to Rust.
   `adapter_protocol.rs` in this crate is the subprocess side of that
   boundary: any language can implement an adapter with zero SDK
   maintenance.
4. **Keep in Python:** `cli.py`, user adapters + SDK (`adapters/`),
   `__init__.py` thin exports.

`BaseAdapter` (Python, in-process) and `SubprocessAdapter` (Rust,
JSON-lines subprocess) are the two supported adapter shapes; the PyO3
bindings serve the former at native speed.
