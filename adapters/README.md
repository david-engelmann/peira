# Adapters

Day-one adapter matrix for the peira leaderboard. Each adapter is a small
Python module implementing the `BaseAdapter` protocol
(`python/peira/adapters/base.py`): `name`, `version` (pinned, never
"latest"), `supported_primitives`, and `decide(case_input, primitive)`.

All adapters are stdlib-only (urllib) — no third-party dependencies.

## The matrix

| Adapter | Module | Model | Access |
|---------|--------|-------|--------|
| Shieldstral 1.0 | `examples/shieldstral_adapter.py` | `mistralai/Shieldstral-1.0-3B` | Self-hosted (vLLM) |
| GPT-6 Luna | `examples/gpt6_adapter.py:Gpt6LunaAdapter` | `openai/gpt-6-luna` | OpenRouter |
| GPT-6 Sol | `examples/gpt6_adapter.py:Gpt6SolAdapter` | `openai/gpt-6-sol` | OpenRouter |
| Grok 4.7 | `examples/grok_adapter.py` | `x-ai/grok-4.7` | OpenRouter |
| DeepSeek V4.1 Flash | `examples/deepseek_adapter.py` | `deepseek/deepseek-v4.1-flash` | OpenRouter |
| Opus 5.5 | `examples/opus_adapter.py` | `claude-opus-5-5` | Anthropic API |
| Jev | `examples/jev_adapter.py` | `jev-1.13.0` | TypeSafe / OpenRouter |

The deterministic `mock` adapter ships inside the package for offline
testing (`peira run --adapter mock`).

## Quickstart

```bash
# Guardrail (self-hosted):
vllm serve mistralai/Shieldstral-1.0-3B --max-model-len 32768
peira run --adapter examples.shieldstral_adapter:ShieldstralAdapter \
    --suite trial-demo

# Cheapest LLM seat (OpenRouter):
export OPENROUTER_API_KEY="sk-or-..."
peira run --adapter examples.gpt6_adapter:Gpt6LunaAdapter --suite trial-demo

# Flagship (Anthropic):
export ANTHROPIC_API_KEY="sk-ant-..."
peira run --adapter examples.opus_adapter:OpusAdapter --suite trial-demo
```

## Design notes

- **Shieldstral** is a yes/no classifier (like Jev's Noul). Choice uses
  per-option argmax; Score uses P(yes | "Should the decision be
  '<options[0]>'?"); Noul maps directly. Yes-probabilities come from
  logprobs softmax, with text fallback.
- **LLM adapters** (GPT-6, Grok, DeepSeek, Opus) use structured outputs
  (JSON schema) at temperature 0.0. Score is authoritative: the adapter's
  threshold derives the decision, so a contradictory decision string from
  the model never causes silent threshold drift.
- **DeepSeek** disables thinking (`reasoning: {"effort": "none"}`) for
  fast, deterministic, cheap calls.
- **Opus 5.5** uses `output_config.format` (not forced tool_choice — that
  hard-400s) with thinking pinned to `low` effort (thinking is billed as
  output).
- **NaN** confidences/scores fail closed to 0.0, never silently 1.0.

## Cost (Sept 2026)

Per full 2,500-case run (~5,000 `decide()` calls):

| Adapter | Approx. cost |
|---------|--------------|
| Shieldstral (self-hosted) | GPU time only |
| GPT-6 Luna | ~$0.20–$0.30 |
| DeepSeek V4.1 Flash | ~$0.30–$0.60 (off-peak) |
| Jev | ~$0.06 |
| GPT-6 Sol | higher (reasoning tier) |
| Grok 4.7 | higher (~$2/$6 per 1M) |
| Opus 5.5 | highest (~$4/$20 per 1M) |

Use Luna for bulk runs; reserve Sol/Grok/Opus for the flagship
comparison seats. See `~/workspace/openrouter/COST_GUARD.md` — no paid run
without a planned ledger entry.

## Writing your own

- Start from `../examples/minimal_adapter.py` (~30 lines).
- Declare your `supported_primitives` honestly — partial coverage is
  reported, not punished.
- Shared OpenRouter plumbing lives in `../examples/_openrouter_base.py`
  (auth, retries, throttling, structured outputs).
- Open a PR: paste your `peira report` summary in the PR body.
