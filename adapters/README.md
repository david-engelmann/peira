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
| kev | `peira.adapters.kev:KevAdapter` | choice, score, abstain | Jared Palmer's open decision model (Apache 2.0) — a LoRA + pointer-head on Qwen, served locally via `python -m kev.serve` with a TypeSafe-compatible `POST /v1/systemone` API. No API key; `api_url=` points at the local server (default `http://127.0.0.1:8008/v1/systemone`). Model pinned to `jaredpalmer/kev-4b` (Qwen3-4B-Base); `0.5b`/`0.6b`/`8b` sizes selectable via `model=`. Self-hosted, $0.
| semif | `peira.adapters.semif:SemifAdapter` | choice, score, abstain | TheoLeeCJ's SemIf (MIT, formerly OpenJev) — typed option logits read from a frozen open model in one forward pass. Subprocess adapter: spawns the `semif-score` CLI per call (`--mode direct --model Qwen/Qwen3.5-4B --revision 851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a`, both pinned). No API key; needs the CLI on PATH (`pip install -e '.[test]'` from github.com/theoleecj/semif). Peira's `abstain` primitive is a yes/no question — SemIf has no `noul` wire type. Self-hosted, $0.
| openjev-sglang | `peira.adapters.openjev_sglang:OpenJevSglangAdapter` | choice, score, abstain | ekzhang's Jev-compatible API server: open models + prefill-only inference on SGLang. Same wire shape as Jev/Kev. No API key; `api_url=` points at the deployment (default `http://localhost:8000/v1/systemone`). Model pinned to `Qwen/Qwen3.6-35B-A3B` (baked into the deployment — the adapter rejects other ids). Self-hosted, $0.
| moonshot | `peira.adapters.llm:MoonshotAdapter` | choice, score, abstain | Moonshot's Kimi K3 (2.8T open-weight flagship) via its OpenAI-compatible API (`https://api.moonshot.ai/v1`); needs `MOONSHOT_API_KEY` and the `peira[openai]` extra. Default model `kimi-k3`, $3/$15 per 1M in the pinned pricing table. |
