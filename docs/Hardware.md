# Hardware requirements

What runs today: the mock adapter and the Peira Trial demo fixture need
any laptop, offline, seconds.

Planned tiers — guidance for when the adapters land:

- **HF adapters, 3B class** (e.g. small guardrail models): ~8 GB RAM.
  Apple Silicon (MPS) or CUDA preferred; CPU fallback works.
- **HF adapters, 27B class**: 16 GB+ VRAM, or Apple Silicon unified memory;
  use the quantized path documented in the adapter's README.
- **Hosted adapters** (via LiteLLM): no local requirements beyond Python —
  you pay your provider per decision instead.
