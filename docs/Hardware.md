# Hardware requirements

What runs today: the mock adapter and the trial-demo fixture need
any laptop, offline, seconds.

The local HF adapters are grouped below by model size, in descending order.
How much memory a model actually needs depends on the backend and
dtype you run it under (CUDA, MPS, or CPU; fp16 vs fp32), so treat
these as size classes, not RAM guarantees. Peira has no built-in
quantization path; if you need one, quantize outside peira and load
the result through the standard HF adapter.

- **8B class**: Granite Guardian 4.1 8B (`ibm-granite/granite-guardian-4.1-8b`),
  the biggest model peira ships an adapter for.
- **7B class**: WildGuard (`allenai/wildguard`).
- **3B-4B class**: Shieldstral 3B (`mistralai/Shieldstral-1.0-3B`),
  Qwen3Guard-Gen 4B (`Qwen/Qwen3Guard-Gen-4B`).
- **2B class**: ShieldGemma 2B (`google/shieldgemma-2b`).
- **Sub-1B class**: ProtectAI (`protectai/deberta-v3-base-prompt-injection-v2`,
  DeBERTa-v3-base), Llama Prompt Guard 2 86M
  (`meta-llama/Llama-Prompt-Guard-2-86M`; gated, accept the license and
  run `huggingface-cli login` before first use).

- **Hosted adapters** (LLM baselines, TypeSafe Jev): no local
  requirements beyond Python. You pay your provider per decision
  instead.
- **Self-hosted adapters** (Laya, Kev, SemIf, openjev-sglang): you
  provide the machine. See `docs/Adapters.md` for each model's size
  and the serving setup it expects.
