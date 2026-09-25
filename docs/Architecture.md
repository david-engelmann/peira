# Architecture

How the pieces fit together: case files become scores. This doc is the map;
`docs/Methodology.md` is the contract and `docs/API-Reference.md` is the
function list.

## Components

```
 dataset/*.jsonl
       |
       v
 +-----------+     +----------------+
 |  schema   |---->|    runner      |
 | validate  |     |  run_case()    |
 +-----------+     +-------+--------+
                           |  per-case results
                           v
                    +--------------+     +----------------+
                    |   metrics    |---->|   artifacts    |
                    |  summarize() |     | seal / verify  |
                    +--------------+     +-------+--------+
                                                 |  run artifact JSON
                                                 v
                                          +--------------+
                                          |     CLI      |
                                          | run/validate |
                                          | report/verify|
                                          +--------------+
```

Each box is one module. Data flows down; nothing flows back up. The runner
never imports the CLI, the metrics never touch the network, the schema
never knows about adapters.

## Data flow, step by step

1. **Load.** `load_cases()` globs `*.jsonl` in sorted order from the suite
   directory. Every line is parsed and run through `validate_case_dict()`.
   Invalid lines fail loudly with file and line number. Duplicate
   `case_id`s are rejected — duplicates would silently double-count in
   metrics.

2. **Run.** `run_case()` executes one case through the adapter, twice: once
   with the benign input, once with the attacked input. The adapter receives
   only the input dict, the `case_id`, and the primitive name. It never sees
   `expected_decision` or `expected_score` — passing gold labels to the
   adapter would let a cheating adapter echo them for a perfect score. Inputs
   are deep-copied before handing them over, so a malicious adapter cannot
   mutate the case objects through nested references.

3. **Score.** `summarize()` aggregates the per-case results: benign accuracy
   and conditional ASR with Wilson confidence intervals, malformed rate,
   per-family breakdowns, and (for score primitives) ECE and Brier
   calibration. Metrics are pure functions over the result list — no I/O,
   no state.

4. **Seal.** `RunArtifact.seal()` computes the analysis lock: sha256 over a
   canonical JSON serialization of peira version, dataset version, adapter
   name, adapter version, suite, config, results, and metrics. Any post-hoc
   edit — including rewriting the headline metrics or the adapter version —
   breaks the lock. `verify()` recomputes it.

5. **Report.** `peira report` renders the artifact as HTML. `peira verify`
   checks the lock and exits 0 (intact) or 1 (tampered).

## Where Rust lives and why

The Python package is the reference implementation — it defines correct
behavior. The Rust crate (`crates/peira-core`) reimplements the hot paths
bit-exactly:

| Module | Rust | Why |
|---|---|---|
| metrics (wilson, ece, brier, mcnemar) | `src/metrics.rs` | CPU-bound; called per summary |
| analysis-lock hashing | `src/artifacts.rs` | byte-exact JSON contract |
| schema validation | `src/schema.rs` | parse-time validation |
| run loop | `src/runner.rs` | no GIL, memory safety |
| adapter subprocess protocol | `src/adapter_protocol.rs` | process management |

Python calls the Rust functions through PyO3 (`crates/peira-core/src/python.rs`):
`wilson_ci`, `ece`, `brier_score`, `mcnemar`, `sha256_hex`. The pure-Python
functions stay in place as the reference; the Rust versions replace them at
import time only when the compiled extension is present. Set
`PEIRA_PURE_PYTHON=1` to force the reference implementation.

The Rust CLI (`crates/peira-cli`) reimplements all four commands and is
byte-identical to the Python CLI on artifacts and HTML reports. Console
output matches except: `verify` prints the adapter version in the Rust CLI
(Python does not), and the resume line has a trailing period in Rust.
See `docs/Rust-Parity.md` for the parity contract.

What stays Python-only: the CLI's dotted-path adapter loading (in-process
Python adapters) and the adapter SDK itself — users write adapters in
Python, and that interface is not going away.

## The adapter boundary

Two ways to plug a model in, with different tradeoffs:

**In-process (Python CLI only).** `--adapter mymodule:MyAdapter` imports the
class and calls `decide()` directly. Fastest, simplest, Python-only. The
runner validates every output against the primitive contract
(`validate_output`): correct output type, confidence/score in 0..1, decision
strings under 10 KiB. Exceptions and contract violations are recorded as
malformed, not crashes.

**Subprocess JSON protocol (Rust CLI only).** The Rust runner spawns the adapter as a
child process and speaks JSON lines over stdin/stdout:

```
--> {"case": {...}, "primitive": "choice"}
<-- {"decision": "approve", "confidence": 0.95}
```

Any language can implement this — read a line, write a line. Malformed JSON
is marked malformed (the adapter stays alive); a timeout kills the whole
process group and the case is marked malformed (consistent with the Python
runner's timeout handling); a crash marks it crashed. The per-decide()
timeout is `--timeout` (default 30s, must be finite and positive), and
output is capped at 10 MiB per line / 100 MiB lifetime — oversize output
kills the adapter and marks the case malformed. The protocol is defined
once in `src/adapter_protocol.rs`, so there is one source of truth instead
of per-language SDKs to maintain.

Pick in-process for Python adapters you iterate on. Pick the JSON protocol
for anything else — or when you want the adapter crash-isolated from the
runner.
