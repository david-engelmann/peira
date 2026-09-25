# Hardware requirements

- **Mock / Peira Trial demo fixture**: any laptop, offline, seconds.
- **HF adapters, 3B class** (e.g. small guardrail models): ~8 GB RAM.
  Apple Silicon (MPS) or CUDA preferred; CPU fallback works and the runner
  prints expected runtimes before starting.
- **HF adapters, 27B class**: 16 GB+ VRAM, or Apple Silicon unified memory;
  use the quantized path documented in the adapter's README.
- **Hosted adapters** (LiteLLM): no local requirements beyond Python —
  you pay your provider per decision instead.

