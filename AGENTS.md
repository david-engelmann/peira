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
  `docs/Troubleshooting.md` — CI-adjacent convention, enforced in review.
- README code blocks must run verbatim: CI executes the quickstart on
  Ubuntu, macOS, and Windows.
- Keep files small and dependency-free in the core path. `peira` (base
  tier) has zero third-party runtime dependencies — protect that.
- The demo fixture (`dataset/trial-demo/`) is scaffolding, clearly labeled.
  The real Trial suite lands at dataset v1; don't build features that
  depend on the fixture's exact contents.
