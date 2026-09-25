# peira-cli

The `peira` command-line binary, built in Rust on top of `peira-core`.

## Commands

Mirrors `python/peira/cli.py` command-for-command:

- `peira run --adapter <name> --suite <name> --out <dir> [--dry-run] [--json-progress] [--resume] [--adapter-version <ver>] [--timeout <secs>]`
- `peira validate --dataset <dir>`
- `peira report --run <artifact> --out <file>`
- `peira verify --run <artifact>`

`--adapter-version` pins the version of a subprocess adapter (required for
external adapters — the Rust CLI cannot infer it; the built-in `mock`
defaults to `0.1.0`). The version is covered by the analysis lock.

`--timeout` bounds one subprocess-adapter `decide()` (request write +
response read) in seconds; default 30. It must be finite and positive.
A variant that exceeds it is marked malformed and the run continues; the
adapter's whole process group is killed. Response lines are capped at
10 MiB and lifetime output at 100 MiB (see `peira-core/src/adapter_protocol.rs`).

## Compatibility

Artifacts, analysis locks, and HTML reports are byte-identical to the
Python CLI (verified by differential testing on `dataset/trial-demo`).
Artifacts are interchangeable: `peira verify` accepts artifacts from either
CLI. Console output matches except: `verify` prints the adapter version,
and the resume line ends with a period. Exit codes are 0/1/2/3, same as
Python.

## Adapters

- `mock` — built-in deterministic mock, bit-identical to Python's.
- Any other value is treated as a program (path or on `PATH`) speaking the
  JSON adapter protocol (see `peira-core/src/adapter_protocol.rs`): one JSON
  request per line on stdin, one JSON response per line on stdout.
- Python dotted paths (`mymodule:MyAdapter`) are **not** supported — they
  need the Python CLI. The error message says so.

## Known gaps vs the Python CLI

1. **Ctrl-C checkpoint is Unix-only.** Both CLIs write a partial artifact on
   interrupt and exit 2; the Rust handler is installed via `sigaction`, so
   Windows builds rely on the periodic (every 25 cases) checkpoint only.
2. **Suite dirs resolve from CWD.** Python resolves from the repo root;
   run the Rust binary from the repo root (or set the working directory
   so `dataset/<suite>` resolves).
3. **Artifact filenames sanitize `/` and `\` to `_`.** Python uses the raw
   `--adapter` string (which breaks for paths); the Rust CLI sanitizes.
4. **Traceback on corrupt JSONL.** Python prints a full traceback and exits
   2 on invalid JSON in `validate`; the Rust CLI prints a one-line error
   and exits 2.
5. **Rounding ties.** Metrics are rounded with ties-to-even on the scaled
   value, matching Python's `round(x, 4)` in all but pathological
   near-tie cases.

## Build

```
cargo build -p peira-cli          # binary at target/debug/peira
cargo build --release -p peira-cli
```
