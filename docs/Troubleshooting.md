# Troubleshooting

An error catalog: exact error → cause → fix. New user-facing errors get an
entry here in the same PR that introduces them.

**`error: unknown adapter: 'x'`**
Cause: the adapter name isn't `mock` and isn't a valid dotted path. Fix: use
`mock`, or pass a dotted path like `--adapter mymodule:MyAdapter` or
`--adapter mymodule.MyAdapter` (see `examples/minimal_adapter.py`). The class
must take no constructor arguments and implement `decide()`.

**`error: cannot import adapter module 'x'`**
Cause: the module in your `--adapter` dotted path isn't on `PYTHONPATH`.
Fix: `pip install` your adapter package, or set `PYTHONPATH` to include its
directory.

**`error: module 'x' has no class 'Y'`**
Cause: typo in the class name after the `:` or `.` in `--adapter`. Fix: check
the class name matches exactly (case-sensitive).

**`error: cannot instantiate 'Y': ...`**
Cause: the adapter class constructor raised an exception. Fix: ensure the
class takes no required arguments and its `__init__` doesn't fail.

**`error: --timeout must be positive (got 0.0)`**
Cause: `--timeout` needs a positive number of seconds. Fix: pass a positive
value like `--timeout 30` (the default). Timed-out variants are marked
malformed, never silently dropped.

**`timeout: adapter.decide() exceeded 30s on case <id> (<variant> variant) — marked malformed`**
Cause: your adapter took longer than `--timeout` on that variant. This is a
warning, not a fatal error — the case is marked malformed and the run
continues. Fix: make `decide()` faster, or raise `--timeout`. Note: the
timeout can't interrupt a thread stuck in a C extension; for a hard-kill
guarantee, use the Rust subprocess adapter protocol instead.

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

**`peira run` exits with code 3**
Cause: none — the run completed. Exit 3 means ranking-ineligible (one of
the Methodology eligibility floors failed; the notes are printed with the
results). Fix: none needed for a demo; for a real submission, clear the
named gate. Exit codes: 0 clean, 1 user error, 2 infrastructure error,
3 completed but unranked.

**`error: partial run ... failed analysis-lock verification`**
Cause: the `--resume` checkpoint was modified or corrupted after it was
written — its analysis lock no longer matches its contents. Fix: delete the
`.partial.json` file and re-run without `--resume`, or restore it from a
trusted copy. Peira refuses to resume rather than risk laundering forged
results into a sealed artifact.

**`error: partial run ... belongs to a different run (...); refusing to resume.`**
Cause: the `.partial.json` file was written by a different adapter, suite,
or dataset version than the current `--resume` invocation. Fix: check that
`--adapter` and `--suite` match the original run, or delete the partial and
start fresh.

**`error: external adapter 'x' needs --adapter-version`**
Cause: the Rust CLI cannot infer the version of a subprocess adapter, and
an unpinned version makes the run irreproducible (the version is covered
by the analysis lock). Fix: pass `--adapter-version 1.2.3` with the exact
pinned version. The built-in `mock` defaults to `0.1.0`.

**`warning: ignoring N foreign case ID(s) in partial run`**
Cause: the partial contains results for case IDs not in the current suite
(stale or hand-edited file). Fix: none — peira drops them and resumes only
the suite's own cases. If you see this unexpectedly, delete the partial and
re-run.
