# peira-cli

The `peira` command-line binary, built in Rust on top of `peira-core`.

## Commands

Mirrors `python/peira/cli.py` command-for-command:

- `peira run --adapter <name> --suite <name> --out <dir> [--dry-run] [--json-progress] [--resume]`
- `peira validate --dataset <dir>`
- `peira report --run <artifact> --out <file>`
- `peira verify --run <artifact>`

## Compatibility

Console output, exit codes (0/1/2/3), artifact JSON, analysis locks, and
HTML reports are byte-identical to the Python CLI (verified by differential
testing on `dataset/trial-demo`). Artifacts are interchangeable: `peira
verify` accepts artifacts from either CLI.

## Adapters

- `mock` — built-in deterministic mock, bit-identical to Python's.
- Any other value is treated as a program (path or on `PATH`) speaking the
  JSON adapter protocol (see `peira-core/src/adapter_protocol.rs`): one JSON
  request per line on stdin, one JSON response per line on stdout.
- Python dotted paths (`mymodule:MyAdapter`) are **not** supported — they
  need the Python CLI. The error message says so.

## Known gaps vs the Python CLI

1. **No Ctrl-C checkpoint.** Python's runner writes a partial artifact on
   `KeyboardInterrupt`; the Rust CLI relies on the periodic (every 25 cases)
   checkpoint only. An interrupt between checkpoints loses that work.
2. **Suite dirs resolve from CWD.** Python resolves from the repo root;
   run the Rust binary from the repo root (or set the working directory
   so `dataset/<suite>` resolves).
3. **Artifact filenames sanitize `/` and `\` to `_`.** Python uses the raw
   `--adapter` string (which breaks for paths); the Rust CLI sanitizes.
4. **No adapter timeout flag.** Subprocess adapters get a fixed 30s
   per-response timeout (Python has no timeout at all).
5. **Traceback on corrupt JSONL.** Python prints a full traceback and exits
   2 on invalid JSON in `validate`; the Rust CLI prints a one-line error
   and exits 2.
6. **Rounding ties.** Metrics are rounded with ties-to-even on the scaled
   value, matching Python's `round(x, 4)` in all but pathological
   near-tie cases. The analysis lock does not cover metrics.

## Build

```
cargo build -p peira-cli          # binary at target/debug/peira
cargo build --release -p peira-cli
```
