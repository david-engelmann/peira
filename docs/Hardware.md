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

## Latency comparability (R-17)

Latency numbers are only comparable within one run on one machine.
A governor switch from `powersave` to `performance`, a boost toggle,
a taskset change, or SMT on vs off can move p99 by tens of percent
with no change to the adapter or the attack. So every run records a
`perf_state` block in the environment fingerprint: CPU governor,
boost state, process affinity, SMT state, and an observed frequency
sample.

The rule is simple. **Compare latency arms within a run, never
across runs on different machines.** The R-16 latency-inflation ratio is deliberately
intra-run for this reason (p99 attacked vs the benign control of the
same family in the same run). If you must compare across runs, check
that `perf_state` matches first; if it does not, the comparison is
invalid and the report should say so, not silently print both
numbers.

Sources that are unreadable (containers without sysfs, macOS, WSL)
are recorded as `None` with a warning at collection time. `None`
means "unknown", not "default": an unknown governor is not a
performance governor.
