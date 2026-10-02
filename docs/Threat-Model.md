# Threat model

## What peira measures

Whether a hostile manipulation of the input changes a decision model's
typed output (Choice / Score / Abstain), measured with paired benign/attacked
controls across the dataset's attack families (v1, 10 families × 200 cases).

## What peira does not measure

- Open-ended text generation safety (this is about *decisions*, not prose).
- Whether the model's reasoning is correct. Only whether the decision
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
Untrusted: third-party adapter code. How much of the machine an
adapter can reach depends on the transport it runs under.

Third-party adapters (registry ids from the `peira.adapters`
entry-point group that are not first-party) run in a subprocess
child by default: `python -m peira.adapters._shim <registry id>`,
spawned by the runner. Discovery never imports adapter code, and
loading happens inside the child, never in the runner's process.
Two paths still run adapter code in-process: dotted-path adapters
(`--adapter some.module`, trust `unverified` in the artifact) and
third-party registry ids with `--adapter-no-isolation` (an explicit
operator flag; the CLI prints a warning). Those paths carry the
old in-process threat model, documented below.

### What an isolated adapter can reach

The subprocess boundary is blast-radius containment and
killability, not a sandbox:

- **Environment.** The child gets a runner-built environment:
  sanitized `PATH`, `TMPDIR`/`TEMP`, `SYSTEMROOT` on Windows,
  `HOME` pointed at a fresh temp dir, plus explicit
  `--adapter-env KEY=VALUE` entries. Nothing is inherited
  wholesale. Denylisted names (`LD_PRELOAD`, `DYLD_*`,
  `PYTHONPATH`, `PYTHONSTARTUP`, `PYTHONHOME`) are refused, but
  only keys the operator chose to pass are visible, and any key
  given *can* be exfiltrated. Key scoping stays the operator's job.
- **Filesystem.** The child's working directory is an empty temp
  dir, but the UID's filesystem is still reachable by absolute
  path. Opportunistic relative-path damage is stopped; targeted
  reads are not.
- **Network.** No egress filtering. A malicious adapter can
  exfiltrate case text over its own network calls. Holdout bytes
  are protected by OpSec (never published, separate invocation),
  not by the sandbox.
- **CPU and memory.** Per-child Unix rlimits bound them;
  third-party children get a default 8192 MB address-space cap.
  CPU beyond the timeout kill and Windows builds remain
  operator-configured.
- **Killability.** Each child runs in its own process group.
  `--call-timeout` SIGKILLs the group immediately on expiry (no grace
  window for a hung child). Normal close (`aclose`) uses SIGTERM with
  a grace period, then SIGKILL. The old thread-zombie failure mode is
  structurally eliminated: a killed child frees its slot, and the
  retry goes to
  a fresh child.

A determined adapter author defeats any finite conformance probe
set, because the probes ship in the open. The conformance kit
raises the cost of cheating; it does not prove honesty.

### The in-process paths (dotted path, --adapter-no-isolation)

When adapter code runs inside the runner's process, it has the
runner's full ambient authority: environment variables including
API keys, the filesystem with the runner's permissions, the
network with no egress filtering, and unbounded CPU, memory, and
wall-clock time unless limits are set. Timeouts bound the runner's
wait, not the adapter: `--call-timeout` wraps each attempt in
`asyncio.wait_for`, but the adapter call runs on a worker thread,
and Python cannot kill threads. A hung adapter burns a thread; once
zombie threads exhaust the shared executor pool, the run's tail
becomes silently garbage results, not just slow ones.

Backstops that apply in-process: `--call-timeout` (default 300
seconds; a very large value effectively disables it),
`--rlimit-cpu-seconds`, `--rlimit-as-mb`, `--rlimit-fsize-mb`
(process-wide, Unix only, opt-in). Each attempt gets a deep copy
of the case input, so an adapter cannot poison the next attempt by
mutation. Import-time code executes with no backstop at all on the
in-process path.

### Holdout integrity does not depend on the sandbox

The blind holdout's integrity rests on the adapter-observable
surface being identical between public and holdout runs by
construction: `case_input` carries no case id, no family, no arm,
no suite tag, no holdout flag (D-25), and `context` carries only
the pseudonymous `call_id`. Holdout runs are unlinkable from
public runs, so an adapter cannot behave differently on them.
Residual risk, stated plainly: an adapter with network egress
*could* exfiltrate case text to a collaborator who checks it
against the public set ("not in public set" implies holdout), and
adapter fields recorded verbatim (`transcript`,
`provider_response_id`, `refusal_reason`) are a second exfil
channel needing no network. Holdout runs redact adapter-supplied
transcript payloads to fixed schema fields. No PR may widen the
adapter-visible surface (new `CallContext` fields, new protocol
params, new `case_input` metadata) without a holdout-integrity
review.

### Residual risks

- The subprocess boundary stops neither network exfiltration nor
  targeted filesystem reads as the operator's UID. Only run
  adapters you trust remains true; the subprocess mode narrows
  what "trust" has to cover.
- `--adapter-no-isolation` is an operator-risk flag. It is never
  something an adapter's install docs should instruct; never take
  CLI flags from an adapter's README.
- `pip install peira-adapter-foo` executes arbitrary code at
  install time (build backends, setup scripts). That is inherent
  to pip and out of scope: this design contains the adapter at
  *run time*, it does not make installing untrusted packages safe.
- Review listing PRs on a clean machine: a fresh VM or container
  holding no credentials. The conformance kit runs the adapter in
  the shim child regardless, but the reviewer's shell is their
  own responsibility.
