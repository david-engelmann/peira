# AGENTS.md

Operating notes for agents working in this repo. See CLAUDE.md for build
commands, architecture map, and the hard rules.

- The Python package is the reference implementation. Port to Rust only
  after the Phase 0 interfaces (case schema, `BaseAdapter`, run-artifact
  format, metrics signatures) are frozen.
- Metrics live in `python/peira/metrics.py` with unit tests in
  `tests/test_metrics.py`. New metrics need tests and a Methodology doc
  update in the same PR.
- Every user-facing error string the CLI can emit must appear in
  `docs/Troubleshooting.md` - CI-adjacent convention, enforced in review.
- README code blocks must run verbatim: CI executes the quickstart on
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

- A metric or statistic: `docs/Methodology.md` (the contract) and
  `docs/Analytics-Methodology.md` (the reader's guide).
- An adapter: `docs/Adapters.md` entry plus the capability report
  table from `docs/adding-an-adapter.md` in the PR description.
- Case schema or dataset format: the dataset spec, `DATASHEET.md`,
  and `docs/Dataset-Changelog.md`.
- Install or packaging: the install docs and the root `README.md`,
  which is also the PyPI package page. The PyPI README drifts
  silently because no symlink can prevent content drift, so this
  mapping is enforced by review, not by tooling.
- A CLI surface change: `docs/CLI.md` and the generated CLI
  reference.
- A leaderboard or API change: the Program B docs and
  `docs/Analytics-Methodology.md` if a reported number changed
  meaning.
- Dataset lifecycle events (refresh, burn, retirement):
  `docs/Refresh-Burn-Retirement-Policy.md` and the dataset
  changelog.
