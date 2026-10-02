# Adapter isolation: subprocess/JSON execution mode

> **Status: implemented with deviation.** The subprocess/JSON execution
> mode is implemented in `python/peira/adapters/` (`discovery.py`,
> `conformance.py`, `subprocess.py`, `_shim.py`) and wired through the
> runner (third-party registry ids default to the subprocess
> transport). Deliberate deviation from this doc's packaging section:
> the runner spawns a **runner-owned shim**
> (`python -m peira.adapters._shim <registry id>`) instead of
> launching author-owned console scripts via `--adapter-subprocess`.
> Rationale and details are in `docs/Plugin-Ecosystem-Design.md`
> section 7 (zero author ceremony, uniform env scrubbing, one framing
> implementation to audit). The protocol, handshake, and security
> properties below are otherwise adopted as designed, with two
> further deviations: no pipelining (one in-flight call per child;
> the runner never sends concurrent calls), and the protocol params
> are key-set-pinned (`{case_input, primitive, context}`,
> `context` carrying only `call_id`). The `serve()` helper became
> the shim's internal loop, not a supported author extension point.

Design for running third-party adapters out of the runner's process.
This is a design doc; the implementation is a separate build. For why
this is needed, see the runner security section of `docs/Threat-Model.md`.

## Goal

A third-party adapter runs as a child process speaking JSON over stdio.
The runner keeps full control: it can kill a hung adapter, it decides
which environment variables the adapter sees, and per-adapter resource
limits apply to the child instead of the whole runner.

## What moves out of process

Only the adapter's `decide()` call. Everything else stays in-process:
case loading, concurrency control, retries, scoring, metrics, transcript
writing, artifact sealing. The runner remains the reference
implementation; the subprocess is a containment boundary, not a rewrite.

## Protocol

JSON objects, one per line, over stdin (runner to adapter) and stdout
(adapter to runner). Stderr is the adapter's log stream; the runner
captures it per call for diagnostics and never parses it.

Handshake on startup (runner sends first):

```json
{"protocol": "peira-adapter/1", "method": "init", "params": {"adapter": "my-adapter"}}
```

The adapter responds:

```json
{"protocol": "peira-adapter/1", "result": {"name": "my-adapter", "version": "0.1.0", "primitives": ["choice"]}}
```

Version mismatch on `protocol` is a hard error: the runner refuses to
proceed rather than guessing at compatibility.

Decide call:

```json
{"id": 7, "method": "decide", "params": {
  "case_input": {"prompt": "...", "options": [...]},
  "primitive": "choice",
  "context": {"call_id": "abc123"}
}}
```

Success response:

```json
{"id": 7, "result": {"decision": "approve", "confidence": 0.92, "abstained": false}}
```

Error response:

```json
{"id": 7, "error": {"type": "ValueError", "message": "bad options"}}
```

`id` correlates requests and responses; the runner may pipeline multiple
in-flight calls. An `error` is treated like an in-process exception:
transient types retry, the rest fail the call.

Shutdown is a `{"method": "shutdown"}` message; the adapter exits 0.
If it does not exit within 5 seconds, the runner SIGKILLs it.

## Security properties

- **Environment**: the child starts with a minimal environment built by
  the runner. API keys are passed explicitly per adapter, never inherited
  wholesale. An adapter that dumps `os.environ` sees only what the runner
  gave it.
- **Timeouts kill**: `--call-timeout` SIGTERMs the child on expiry, then
  SIGKILLs after a grace period. No more abandoned threads.
- **Resource limits are per-adapter**: the rlimits that are process-wide
  today (`--rlimit-cpu-seconds`, `--rlimit-as-mb`, `--rlimit-fsize-mb`)
  move onto the child process, where they bound the adapter without
  risking the runner.
- **Filesystem**: the child's working directory is an empty temp dir.
  Adapters that need model files declare paths up front; the runner
  bind-mounts nothing by default (no containers in v1, just cwd and env
  discipline).
- **No shared memory**: the deep-copy-per-attempt guarantee becomes
  structural. The adapter cannot reach the runner's objects at all.

## Adapter packaging

A third-party adapter ships a console entry point (e.g.
`my-adapter-peira`) that reads the handshake on stdin and speaks the
protocol. The runner launches it with `peira run --adapter-subprocess
my-adapter-peira`. First-party adapters keep the in-process path; the
flag opts into isolation per run.

The adapter SDK gains a small `peira.adapters.subprocess.serve(adapter)`
helper that wraps any existing `BaseAdapter` in the stdio loop, so
authors do not hand-roll framing.

## What this does not do

- It does not sandbox syscalls (no seccomp in v1). A malicious adapter
  can still do anything its UID can do. The boundary is about blast
  radius and killability, not a security sandbox.
- It does not filter network egress. An adapter with a key can still
  exfiltrate through its own network calls. Key scoping stays the
  operator's job.
- It does not change the adapter API. `decide(case_input, primitive,
  context)` is the same function; only the transport changes.

## Sequencing

1. `serve()` helper and the protocol framing (no runner changes).
2. Runner `--adapter-subprocess` flag with spawn, handshake, decide
   dispatch, timeout kill, and shutdown.
3. Move rlimits onto the child; document the new defaults.
4. Third-party adapter docs point at the subprocess path as the default.
