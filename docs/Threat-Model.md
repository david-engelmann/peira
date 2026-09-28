# Threat model

## What peira measures

Whether a hostile manipulation of the input changes a decision model's
typed output (Choice / Score / Abstain), measured with paired benign/attacked
controls across 10 attack families (× 200 cases).

## What peira does not measure

- Open-ended text generation safety (this is about *decisions*, not prose).
- Whether the model's reasoning is correct — only whether the decision
  changed under attack.
- Real-world deployment risk. A good peira score is evidence about the
  benchmark, not a safety certificate. See the non-certification notice in
  the README.

## Assumptions

- The attacker controls parts of the input (prompts, retrieved context,
  tool outputs) but not the model weights or the harness.
- The defender (adapter author) sets their own thresholds and abstention
  policy; peira measures the resulting behavior.
- Cases are synthetic and authored. They model real attack shapes; they are
  not sampled from real incidents.

## Runner security

The above is the measurement threat model. This section covers the
runner's own threat model: what a third-party adapter can do to the
machine running peira.

### Trust boundary

Trusted: the peira codebase, the dataset, the runner process itself.
Untrusted: third-party adapter code. An adapter is loaded with
`importlib.import_module`, which executes the module at import time, and
its `decide()` method runs in-process on a worker thread. There is no
sandboxing. Only run adapters you trust, or run peira somewhere you can
afford to lose.

### What an adapter can reach

Because adapters run in-process, a malicious or buggy adapter has the
runner's full ambient authority:

- **Environment variables**, including API keys. First-party adapters read
  keys from `os.environ` directly (e.g. `TYPESAFE_API_KEY`); a third-party
  adapter sees the same environment.
- **The filesystem**, with the runner's permissions. Nothing stops an
  adapter from reading or writing files the runner can reach.
- **The network**, with no egress filtering.
- **Unbounded CPU, memory, and wall-clock time**, unless you set limits
  (see below).

### Timeouts bound the runner's wait, not the adapter

`--call-timeout` (default 300 seconds) wraps each attempt in
`asyncio.wait_for`. When it fires, the runner stops waiting, records a
timeout, and retries as a transient failure. But the adapter call runs on
a worker thread, and Python cannot kill threads: the timed-out call keeps
running in the background until it returns or the process exits. The
timeout bounds how long the *run* stalls, not how long the *adapter*
executes. A hung adapter still burns a thread, and those burned threads
occupy the shared default executor pool (`min(32, cpu_count + 4)` workers;
6 on a 2-core box). Once zombie threads exhaust the pool, no new adapter
call can start a worker thread, so every remaining call deterministically
times out into a blank record. The run still terminates on schedule, but
the tail of the run is silently garbage results, not just slow ones.

### Backstops that exist today

- `--call-timeout` defaults to 300 seconds. The flag requires a positive
  value; passing a very large number effectively disables it, which opts
  out of the backstop.
- `--rlimit-cpu-seconds`, `--rlimit-as-mb`, `--rlimit-fsize-mb` set
  process-wide Unix resource limits (CPU time, virtual memory, single-file
  write size). They are opt-in and blunt: they apply to the whole runner,
  not per adapter call. They catch runaway resource use; they do not
  isolate.
- Each attempt gets a deep copy of the case input, so a misbehaving
  adapter cannot poison the next attempt's input through mutation.
- The limits above apply inside `run_suite`. Adapter *import-time* code
  is not covered: `_get_adapter` runs `importlib.import_module` before
  flag validation and before rlimits are applied, so a malicious
  adapter's module-level code executes with no backstop at all. There is
  no sandboxing; only run adapters you trust.

### What is still missing

True isolation needs the adapter out of the runner's process: no shared
environment, no shared filesystem, killable on timeout. That is the
subprocess/JSON execution mode designed in `docs/Adapter-Isolation.md`.
Until it lands, treat third-party adapters as arbitrary code execution
and scope your trust accordingly.
