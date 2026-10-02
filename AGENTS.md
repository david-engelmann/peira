# AGENTS.md

Operating notes for agents working in this repo. `CLAUDE.md` is a
symlink to this file, for agents configured to look for that name.

## Build / test / lint

```bash
pip install -e .                    # install the Python package
pip install -e .[dev]               # pytest, pytest-xdist, pytest-timeout
python -m pytest tests -n auto      # Python tests - must stay green
cargo test --workspace              # Rust tests - must stay green
python scripts/check_public_surface.py   # strategy-language check - must stay green
peira run --adapter mock --suite trial-demo --dry-run   # CLI smoke
```

## Architecture map

- `python/peira/` - reference implementation and SDK. `schema.py` (case
  contract), `adapters/base.py` (adapter protocol), `adapters/mock.py`
  (deterministic offline adapter), `runner.py`, `metrics.py`, `artifacts.py`
  (sealed run records), `cli.py`.
- `crates/peira-core/` - Rust core. Ports the hot paths once the Python
  interfaces freeze (Phase 0). The Python package is the reference until then.
- `dataset/` - `trial-demo/` is the offline demo fixture; `trial/` is the
  branded Trial; `v1/` is the real 2,000-case dataset.
- `docs/` - the product's public face. `docs/Methodology.md` is the
  measurement contract; update docs when behavior changes, in the same PR.

## Contribution workflow

Mechanical checklist in `docs/Contributing.md`. Green local gates,
then merge. CI is a backstop, not a gate.

## Hard rules

1. **Never edit scored artifacts post-hoc.** New config means a new run
   and a new analysis lock. The lock is the trust model.
2. **Never read or decrypt the private holdout** unless the human
   explicitly asks. It doesn't exist yet; when it does, this rule is
   absolute.
3. **Never commit strategy.** No dominance intent, speed language, vendor
   plays, or internal memos - in any file, issue, or commit message.
   `scripts/check_public_surface.py` enforces it; keep it green.

## Repo conventions

- The Python package is the reference implementation. Port to Rust only
  after the Phase 0 interfaces (case schema, `BaseAdapter`, run-artifact
  format, metrics signatures) are frozen.
- Metrics live in `python/peira/metrics.py` with unit tests in
  `tests/test_metrics.py`. New metrics need tests and a Methodology doc
  update in the same PR.
- Every user-facing error string the CLI can emit must appear in
  `docs/Troubleshooting.md` - CI-adjacent convention, enforced in review.
- README code blocks must run verbatim. CI executes the quickstart on
  Ubuntu, macOS, and Windows.
- Keep files small and dependency-free in the core path. `peira` (base
  tier) has zero third-party runtime dependencies - protect that.
- The demo fixture (`dataset/trial-demo/`) is scaffolding, clearly labeled.
  The branded 100-case Trial lives in `dataset/trial/`; don't build features
  that depend on either fixture's exact contents.

## Documentation map

CI checks that docs exist and links resolve. It cannot check that docs
are current. Only review culture can. When your change touches one of
the areas below, update the mapped docs in the same PR. Reviewers
check the map, not just the code.

- A metric or statistic. Update `docs/Methodology.md` (the contract)
  and `docs/Analytics-Methodology.md` (the reader's guide).
- An adapter. Add a `docs/Adapters.md` entry, and put the capability
  report table from `docs/adding-an-adapter.md` in the PR description.
- Case schema or dataset format. Update the dataset spec,
  `DATASHEET.md`, and `docs/Dataset-Changelog.md`.
- Install or packaging. Update the install docs and the root
  `README.md`, which is also the PyPI package page. The PyPI README
  drifts silently because no symlink can prevent content drift, so
  this mapping is enforced by review, not by tooling.
- A CLI surface change. Update `docs/CLI.md` and the generated CLI
  reference.
- A leaderboard or API change. Update the Program B docs, and
  `docs/Analytics-Methodology.md` if a reported number changed
  meaning.
- Dataset lifecycle events (refresh, burn, retirement). Update
  `docs/Refresh-Burn-Retirement-Policy.md` and the dataset
  changelog.
