# Contributing

## The mechanical checklist

Every PR must:

1. Keep `.venv/bin/python -m pytest tests -n auto` green (install test deps first:
   `python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'`).
2. Keep `cargo test --workspace` green.
3. Keep `.venv/bin/python scripts/check_public_surface.py` green. Strategy language
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
test-rust, test-python-rust, test-integration, quickstart, readme-table, and
dataset-checks. The maintainer reviews for correctness against
`docs/Methodology.md`. Adapter PRs go through the same flow. The maintainer
additionally reviews the adapter for an honest `supported_primitives`
declaration. The `test-integration` job runs `tests/integration`
(the end-to-end pipeline suite: dataset -> runner -> metrics ->
artifact -> report) in both backends.

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

To build it in a checkout (maturin is the PEP 517 build backend, so a
normal editable install builds the extension with no separate script):

    python3 -m venv .venv
    .venv/bin/pip install -e '.[dev]'

then confirm `.venv/bin/python -c "from peira._rust import
RUST_AVAILABLE; print(RUST_AVAILABLE)"` prints `True`. After changing
anything under `crates/`, rebuild incrementally with `.venv/bin/maturin
develop` (debug, seconds); use `.venv/bin/maturin develop --release`
for performance work. Python-only edits take effect immediately under
the editable install with no rebuild needed.

IMPORTANT: always run tests through the venv (`.venv/bin/python -m
pytest tests -n auto`). `maturin develop` places the compiled `_core`
extension inside the `python/peira/` source tree as a
maturin-managed build artifact (gitignored, so never commit it); on a
fresh checkout that was never built, running pytest with a bare
`PYTHONPATH=<worktree>/python` will SILENTLY test the pure-Python
backend (`RUST_AVAILABLE=False`). The venv is the only supported way
to run the suite.

The `test-python-rust` CI job installs the extension in release profile
and runs the full Python suite against both backends; backend parity is
pinned by `tests/test_rust_backend.py`. Set `PEIRA_NO_RUST=1` to force
the pure-Python backend locally.

Distribution notes: `pip install peira` from PyPI installs prebuilt
abi3 wheels (one per platform, all supported Pythons) with no Rust
toolchain needed, unchanged UX. Installing from an sdist or a git URL
now requires a Rust toolchain, which is standard for maturin-based
projects.
