# Contributing

## The mechanical checklist

Every PR must:

1. Keep `python -m pytest tests -n auto` green (install test deps first:
   `pip install -e .[dev]`).
2. Keep `cargo test --workspace` green.
3. Keep `python scripts/check_public_surface.py` green. Strategy language
   is never committed (see below).
4. If you added a user-facing error string, add it to
   `docs/Troubleshooting.md` in the same PR.
5. If you changed the dataset, bump the dataset version and add a
   CHANGELOG entry.
6. Sign off your commits (DCO): `git commit -s`.

## Public-content boundary

This repo is the product's public face. Never commit internal strategy
documents or planning language in any file, issue, discussion post, or
commit message. The CI `public-surface` job enforces this mechanically.
When in doubt, leave it out and ask in Discussions.

## What happens after you open a PR

CodeRabbit reviews every PR automatically. It is advisory only. Read its
comments and fix the valid ones before requesting human review. It never
blocks a merge.

Each PR then goes through three reviews. An independent red-team audit of
the finished state. An independent line-by-line review of the diff. The
maintainer's own verification pass with independent re-checks of the key
claims. Fix everything the reviews find.

During the build phase, the maintainer merges on green local gates plus
the three reviews. CI is a backstop, not a gate. It is never waited on.
A red main does not hold up merges. The fix-forward lane repairs it in
parallel while perfect, fully verified work keeps landing. Before every
merge the branch is rebased onto the current origin/main head and passes
the rebase survival check, which confirms every hunk of the lane's work
is still present and behaving. Once the project has downstream users or
contributors, the bar tightens and CI must be green on the final head
before merge. The required checks are check_runner, coderabbit-config, public-surface,
docs, dco, dataset-version, lint-rust, test-python, test-hf-tokenizers,
test-rust, test-python-rust, quickstart, readme-table, and
dataset-checks. The maintainer reviews for correctness against
`docs/Methodology.md`. Adapter PRs go through the same flow. The maintainer
additionally reviews the adapter for an honest `supported_primitives`
declaration.

## Rust core

The deterministic logic (metrics, gates, canonicalization, dataset
validation, artifacts) is implemented in the Rust core and exposed to
Python through PyO3. The direction is Rust-maximal (2026-09-30).
Deterministic logic moves to Rust in parity-tested slices while
adapters stay Python and the PyO3 surfaces stay intact. Every Rust
function keeps a pure-Python reference implementation, so
`pip install peira` never needs a Rust toolchain. The two backends
produce the same values (up to ~1 ulp where the reference squares
terms via `** 2` and the Rust core uses exact multiplication).
`paired_bootstrap_ci` always uses the Python PRNG so reported
intervals never depend on the backend.

To build it in a checkout:

    python scripts/build_core_ext.py

then confirm `python -c "from peira._rust import RUST_AVAILABLE;
print(RUST_AVAILABLE)"` prints `True`. Rebuild after changing anything
under `crates/`. The `test-python-rust` CI job builds the extension and
runs the full Python suite against both backends; backend parity is
pinned by `tests/test_rust_backend.py`. Set `PEIRA_NO_RUST=1` to force
the pure-Python backend locally.
