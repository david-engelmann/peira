# Troubleshooting

An error catalog: exact error → cause → fix. New user-facing errors get an
entry here in the same PR that introduces them.

**`error: unknown adapter: 'x'`**
Cause: the adapter name isn't registered. Fix: use `mock`, or point
`--adapter` at your adapter module (see `examples/minimal_adapter.py`).

**`error: unknown suite 'x'`**
Cause: typo in `--suite`. Fix: `trial-demo` (demo fixture, offline) or
`trial` (the real 100-case Trial suite, ships with dataset v1).

**`error: suite directory ... not found`**
Cause: you ran `peira` from outside the repo checkout. Fix: run from the
repo root, or `pip install peira` and let it use the installed dataset.

**`...: bad primitive: 'xyz'` / `bad severity` / `missing required key`**
Cause: a case file fails schema validation. Fix: run
`peira validate --dataset <dir>` — it prints file, line, and rule.

**`confidence 1.4 outside 0..1` (or similar contract errors)**
Cause: your adapter returned a value outside its primitive contract.
Fix: normalize outputs in your adapter (Choice confidence and Score must
be 0..1). Malformed outputs count against your ASR, so fix this before
benchmarking seriously.

**Hugging Face auth / rate-limit errors**
Cause: `peira[hf]` adapters download models from HF Hub. Fix: `huggingface-cli
login`, or set `HF_TOKEN`. Model weights are cached after the first download.

**Out-of-memory on local models**
Cause: the model doesn't fit in RAM/VRAM. Fix: use a quantized variant or a
smaller adapter; see `docs/Hardware.md` for per-tier requirements. `peira run`
prints an estimate before starting — don't ignore it.

**`peira report` prints "analysis lock mismatch"**
Cause: the run artifact was edited after sealing. Fix: don't edit artifacts;
re-run. If you need different config, that's a new run with a new lock.

**`error: no cases found in ...`**
Cause: the suite directory has no `.jsonl` files. Fix: check the path;
`dataset/trial-demo/cases.jsonl` ships with the repo.
