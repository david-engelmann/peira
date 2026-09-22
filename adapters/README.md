# Adapters

Community and built-in adapters live here. Each adapter is a small Python
module implementing the `BaseAdapter` protocol (`python/peira/adapters/base.py`).

- Start from `../examples/minimal_adapter.py` (~30 lines).
- Declare your `supported_primitives` honestly — partial coverage is
  reported, not punished.
- Open a PR: CI runs the Trial suite and posts your score as a comment.

The deterministic `mock` adapter ships inside the package for offline
testing (`peira run --adapter mock`).
