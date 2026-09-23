# Contributing

## The mechanical checklist

Every PR must:

1. Keep `python -m unittest discover tests` green.
2. Keep `cargo test --workspace` green (once the Rust core has logic).
3. Keep `python scripts/check_public_surface.py` green — strategy language
   is never committed (see below).
4. If you added a user-facing error string, add it to
   `docs/Troubleshooting.md` in the same PR.
5. If you changed the dataset, bump the dataset version and add a
   CHANGELOG entry.
6. Sign off your commits (DCO): `git commit -s`.

## Public-content boundary

This repo is the product's public face. Never commit internal strategy
documents or planning language — in any file, issue, discussion post, or
commit message. The CI `public-surface` job enforces this mechanically.
When in doubt, leave it out and ask in Discussions.

## What happens after you open a PR

CI runs (tests, public-surface check, README quickstart on three OSes).
The maintainer reviews for correctness against `docs/Methodology.md`.
Adapter PRs will also run the Trial suite and post the score as a comment
— that's the whole review for a new adapter: green CI plus a posted score.

## Rust accelerator (optional)

The scoring hot paths (`peira.metrics`, `peira.schema`) can run on the
compiled Rust core via the `peira._core` PyO3 extension. It is purely an
accelerator: every function falls back to the pure-Python reference
implementation when the extension is absent, so `pip install peira` never
needs a Rust toolchain, and both backends produce the same values (up to
~1 ulp where the reference squares terms via `** 2` and the Rust core
uses exact multiplication; `paired_bootstrap_ci` always uses the
Python PRNG so reported intervals never depend on the backend).

To build it in a checkout:

    python scripts/build_core_ext.py

then confirm `python -c "from peira._rust import RUST_AVAILABLE;
print(RUST_AVAILABLE)"` prints `True`. Rebuild after changing anything
under `crates/`. The `test-python-rust` CI job builds the extension and
runs the full Python suite against both backends; backend parity is
pinned by `tests/test_rust_backend.py`. Set `PEIRA_NO_RUST=1` to force
the pure-Python backend locally.
