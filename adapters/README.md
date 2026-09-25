# Adapters

Community and built-in adapters live here. Each adapter is a small Python
module implementing the `BaseAdapter` protocol (`python/peira/adapters/base.py`).

- Start from `../examples/minimal_adapter.py` (~30 lines).
- Declare your `supported_primitives` honestly — partial coverage is
  reported, not punished.
- Open a PR: CI will run the Trial suite and post your score as a comment
  once the v1 dataset ships.

The deterministic `mock` adapter ships inside the package for offline
testing (`peira run --adapter mock`).

## Built-in adapters

| Adapter | Dotted path | Primitives | Notes |
|---|---|---|---|
| mock | `peira.adapters.mock:MockAdapter` | choice, score, abstain | Deterministic, offline, zero-dependency. |
| jev | `peira.adapters.jev:JevAdapter` | choice, score, abstain | TypeSafe System One API; needs `TYPESAFE_API_KEY`. Model pinned to `jev-1.13.0`. |
| laya | `peira.adapters.laya:LayaAdapter` | choice, score, abstain | Convai Innovations' open-source ModernBERT classifier (421M, Apache 2.0, `pip install laya`) — the open Jev alternative. Local, not gated. Three checkpoints via `checkpoint=`: `convaiinnovations/laya` (default, English 421M), `convaiinnovations/laya-multilingual` (322M), `convaiinnovations/laya-typed-decisions` (fine-tuned). Maps peira's `abstain` primitive to Laya's `noul` question type at the boundary.
