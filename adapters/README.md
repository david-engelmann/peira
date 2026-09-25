# Adapters

Community and built-in adapters live here. Each adapter is a small Python
module implementing the `BaseAdapter` protocol (`python/peira/adapters/base.py`).

- Start from `../examples/minimal_adapter.py` (~30 lines).
- Declare your `supported_primitives` honestly — partial coverage is
  reported, not punished.
- Open a PR: paste your `peira report` summary in the PR body (CI score-posting bot planned).

The deterministic `mock` adapter ships inside the package for offline
testing (`peira run --adapter mock`).
