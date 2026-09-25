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

**`error: adapter 'Y' has an invalid interface: ...`**
Cause: the adapter class is missing required interface members — a
callable `decide()`, a non-empty string `name`, a string `version`, or
`supported_primitives` contains unknown primitives. The interface is
validated at load time so a broken adapter fails fast instead of failing
mid-run. Fix: implement the missing members (see `docs/Adapter-Tutorial.md`).

**`warning: N timed-out adapter worker(s) still running ...`**
Cause: a previous `decide()` call timed out but its thread is still
running — Python threads can't be forcibly killed. The timed-out call was
already marked malformed; this warns you that the orphan is executing
concurrently against the same adapter, which is hazardous for adapters
with shared mutable state. Fix: make `decide()` respect the timeout, or
use the Rust subprocess adapter protocol for a hard-kill guarantee.

**`error: --timeout must be a finite positive number of seconds (got nan)`**
Cause: `--timeout` needs a finite positive number of seconds. NaN, inf,
zero, and negatives are all rejected — NaN slips past a naive `<= 0`
check, and inf would silently disable the timeout. Fix: pass a finite
positive value like `--timeout 30` (the default). Timed-out variants are
marked malformed, never silently dropped.

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
Cause (Python CLI): the suite directory is missing next to the installed
package — a deleted `dataset/`, a partial checkout, or a pip install
without data files. The path is derived from the package location, not
your working directory. Fix: re-clone the repo or point at a checkout.
Cause (Rust CLI): you ran from outside the repo checkout — the Rust CLI
resolves suite directories relative to the working directory. Fix: run
from the repo root.

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
smaller adapter; see `docs/Hardware.md` for per-tier requirements.

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

**`warning: could not read partial run (...); starting fresh.`**
Cause: the `--resume` checkpoint file is corrupt or unreadable. Fix: none
— peira starts the run from scratch. If the file matters, restore it from
a trusted copy.

**`warning: ignoring N duplicate case ID(s) in partial run.`**
Cause: the checkpoint contains the same case ID twice (hand-edited or
crashed mid-write). Fix: none — the first occurrence is kept.

**`error: invalid case data: ...`**
Cause: `load_cases` failed during `peira run` — a case file has a schema
violation. Fix: run `peira validate --dataset <dir>` for the exact
`file:line` and rule.

**`error: cannot parse artifact: ...`**
Cause: `peira verify` couldn't parse the artifact JSON. Fix: check the
file path; the file may be corrupt or not a peira artifact.

**`FAIL: <path> — analysis lock MISMATCH`**
Cause: `peira verify` recomputed the lock and it doesn't match — the
artifact was modified after sealing. The follow-up line ("artifact was
modified after sealing; metrics are not trustworthy") says it plainly.
Fix: don't edit artifacts; re-run. (Artifacts sealed before 2026-09-25
also fail — metrics and adapter_version are now lock-covered; re-run to
re-seal.)

**`interrupted — partial run saved; re-run with --resume.`**
Cause: you hit Ctrl-C during `peira run`. The checkpoint was written via
`finally`, so no completed cases are lost. Fix: re-run with `--resume`.
Exit code is 2.

**`skip: N 'choice' case(s) not scored (adapter declares ...)`**
Cause: not an error — your adapter's `supported_primitives` doesn't
include that primitive, so those cases were skipped (stderr notice).
Fix: none; the artifact's `n_skipped`/`primitive_coverage` describe the
gap. To score them, add the primitive to `supported_primitives`.

**`error: <dir> not found` / `error: <path> not found`**
Cause: `peira validate` got a missing dataset dir, or `peira report` /
`peira verify` got a missing artifact path. Fix: check the path.

## Rust CLI errors

The Rust CLI (`crates/peira-cli`) has its own messages. Python dotted-path
adapters (`mymodule:MyAdapter`) need the Python CLI — the Rust CLI only
runs `mock` and JSON-protocol subprocess adapters.

**`unknown adapter: 'x' (the Rust CLI runs 'mock' and JSON-protocol ...)`**
Cause: the adapter name isn't `mock` and isn't a program on PATH. Fix: use
`mock`, or pass a program name that speaks the JSON adapter protocol (see
`crates/peira-core/src/adapter_protocol.rs`).

**`unknown adapter: 'x' (looks like a Python dotted path, which needs ...)`**
Cause: you passed `mymodule:MyAdapter` or `mymodule.MyAdapter` to the Rust
CLI. Fix: use the Python CLI (`python -m peira.cli`) for dotted-path
adapters.

**`cannot spawn adapter 'x': ...`**
Cause: the subprocess adapter program couldn't be started (not on PATH,
not executable). Fix: check the program name and permissions.

**`error: cannot read <path>: ...`**
Cause: the Rust CLI couldn't read a dataset dir or artifact file. Fix:
check the path and permissions.

**`error: <path>:<lineno>: invalid JSON: ...`**
Cause: a case file line isn't valid JSON (Rust `validate`). Fix: check the
named line.

**`error: cannot create <path>: ...` / `error: cannot write <path>: ...` /
`error: cannot serialize artifact: ...`**
Cause: the Rust CLI couldn't write its output (permissions, disk full, or
an unserializable value). Fix: check the output path and disk space.

**`warning: could not read partial run (bad result shape); starting fresh.`**
Cause: the Rust `--resume` checkpoint has an unexpected shape. Fix: none —
the run starts fresh.
