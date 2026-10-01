# Plugin ecosystem design: third-party adapters (P-4)

**Status:** design doc, revised after review (red-team + Spec + Standards),
awaiting approval before implementation.
**Proposal:** P-4 of the 2026-10-01 decant audit (research notes held
outside this repo): third-party adapter plugin ecosystem, discovery
plus conformance kit plus sandbox.
**Supersedes on:** `docs/Adapter-Isolation.md` section "Adapter
packaging" (console-script packaging; see section 7 for why the
runner-owned shim replaces it). The protocol, handshake, and security
properties of `Adapter-Isolation.md` are otherwise adopted unchanged.

## 1. Goal

Give peira a third-party adapter story so the project is not limited
to adapters David authors:

1. **Discovery.** `pip install peira-adapter-foo` registers the
   adapter. No dotted-path hack, no vendoring into the peira repo.
2. **Conformance.** `peira adapter check` runs a contract test kit
   any adapter must pass before it is listed or trusted.
3. **Isolation.** Third-party adapters run out of the runner's
   process by default, in the subprocess/JSON mode designed in
   `docs/Adapter-Isolation.md`. In-process loading stays available
   only as an explicit, documented trust decision by the operator.
4. **Contribution flow.** A lightweight lane for community adapters
   (conformance green plus one maintainer review), not the full
   three-review gauntlet that in-repo adapters get.

## 2. Non-goals

- A security sandbox. The subprocess boundary is blast-radius
  containment and killability, not a sandbox. No seccomp, no network
  egress filtering, no UID change. Section 8 states exactly what is
  and is not stopped, and the red-team review of this doc attempted
  to break the isolation model before implementation.
- Install-time safety. `pip install peira-adapter-foo` already
  executes arbitrary code at install time (build backends, setup
  scripts). That is inherent to pip and out of scope. This design
  contains the adapter at *run time*; it does not make installing
  untrusted packages safe.
- Changing the adapter API. `decide(case_input, primitive, context)`
  is unchanged. Only discovery and transport change.
- Weakening any existing adapter gate. The conformance kit is
  additive. In-repo adapters keep every gate they have today.
- A plugin story for anything other than adapters (scorers, gates,
  metrics stay in-repo).

## 3. Terminology

- **Adapter spec.** The string the operator passes to `--adapter` or
  `peira adapter check`. One of: `mock`, a dotted path
  (`package.module` or `package.module:ClassName`), or a registry id.
- **Registry id.** The entry-point name under the `peira.adapters`
  group. The CLI id for a third-party adapter.
- **Shim.** The runner-owned child process
  (`python -m peira.adapters._shim <registry id>`) that imports the
  adapter inside the sandbox and speaks the stdio protocol.
- **Transport.** How `decide()` calls reach the adapter. `inprocess`
  or `subprocess`.
- **Conformance kit.** The contract test suite in
  `python/peira/adapters/conformance.py`, runnable as
  `peira adapter check`.
- **Capability report.** The machine-readable checklist the kit emits
  (observed primitives, `confidence_source`, retry posture, what the
  harness can and cannot observe).

## 4. Discovery via `entry_points`

### 4.1 Group and naming

Entry-point group: **`peira.adapters`**.

```toml
[project.entry-points."peira.adapters"]
my-adapter = "my_adapter_pkg.module:adapter"
```

- The entry-point **name** is the registry id
  (`peira run --adapter my-adapter`,
  `peira adapter check my-adapter`).
- Name rules, enforced at discovery time: `^[a-z0-9][a-z0-9_-]{1,63}$`
  (ASCII-only explicit ranges; no dots, which unambiguously mean
  dotted-path), not `mock` (reserved), not starting with `peira-`
  (reserved for first-party packaging; third-party distributions are
  encouraged to be named `peira-adapter-<slug>` on PyPI while the
  registry id itself drops the prefix).
- The entry-point **value** is a library reference in the same two
  forms the dotted-path loader accepts: `package.module`
  (module-level `adapter` object) or `package.module:ClassName`
  (instantiated with no arguments). No new syntax to learn.
- Peira registers its own first-party adapters under the same group,
  so `peira adapter list` shows one registry. Dotted-path loading
  keeps working unchanged for back-compat.

### 4.2 Resolution order (unambiguous by construction)

1. `mock` gives the built-in mock (unchanged).
2. Spec contains `.` or `:` gives the dotted-path loader (unchanged
   behavior, unchanged trust warning).
3. Otherwise, `peira.adapters` entry-point lookup by exact name.

Because registry ids cannot contain dots, a spec can never match
both rule 2 and rule 3. Discovery (`importlib.metadata`) never
imports adapter code; only loading does, and loading of
third-party adapters happens inside the shim child (section 7),
never in the runner process.

### 4.3 Confusion defenses

- **Name-vs-attribute binding, enforced uniformly.** After loading,
  the runner asserts `adapter.name == <registry id>`. A package that
  registers the name `shieldstral` but serves a different adapter
  fails closed at load with an actionable error. In the subprocess
  flow the parent verifies the init handshake's reported `name`
  against the requested spec before the first decide call; a child
  that serves a different name is dropped.
- **Collision.** Two distributions registering the same name is an
  installation conflict, not a runtime tiebreak. Discovery reports
  every distribution that claims a name in `peira adapter list
  --verbose`. Both `peira adapter check <name>` and `peira run
  --adapter <name>` fail closed on ambiguity and tell the operator
  to uninstall one claimant. There is no "winner by metadata
  iteration order."
- **Provenance is visible.** `peira adapter list` always shows the
  owning distribution (`my-adapter 0.2.0 from peira-adapter-foo
  1.4.2`). Typosquatting remains possible, as with all of PyPI, and
  the docs say so plainly. Peira never endorses a package; it only
  reports that a given set of bits passed conformance on a given
  date (section 10).

## 5. `peira adapter` CLI

```text
peira adapter list [--verbose] [--json]
peira adapter check <spec> [--json] [--probes N] [--timeout S] [--verify]
```

- `list`: every registered adapter (name, version, primitives,
  owning distribution, first-party vs third-party, default
  transport). Exit 0 always; discovery errors are reported per row,
  never fatal.
- `check`: runs the conformance kit (section 6) against one adapter
  spec (registry id or dotted path). Exit 0 means all checks pass,
  1 means a check failed, 2 means usage or loading error. `--json`
  emits a machine-readable report for CI and listing PRs. `--verify`
  re-resolves an installed adapter and compares its bits against a
  recorded check report (section 10).
- New error strings, enumerated here so `docs/Troubleshooting.md`
  can pin each one:
  - `unknown adapter: '<spec>'` (existing wording, extended to
    mention the registry)
  - `adapter name mismatch: registry '<id>' served '<name>'`
  - `adapter name '<id>' claimed by multiple distributions: <a>, <b>`
  - `adapter protocol version mismatch: ...`
  - `adapter import timed out after 30s in the sandbox child`
  - `adapter did not exit within 5s of shutdown; killed`
  - `adapter failed conformance: <n> check(s) failed`
- `docs/CLI.md` gains the two commands with the signatures above
  and the exit-code contract.

## 6. Conformance kit

`python/peira/adapters/conformance.py`: a library
(`run_checks(...) -> Report`) plus the CLI. Checks run against
**synthetic probe cases authored by the kit**, never dataset cases,
never holdout bytes (the kit must be runnable by anyone, so it
cannot depend on anything non-public). Third-party adapters are
always exercised **through the shim child**, never in-process: the
kit tests what the runner will actually do, and untrusted
import-time code never executes in the checker's process
(red-team F1). First-party adapters may be checked in-process.

### 6.1 Contract checks (pass/fail)

1. **schema.** For each declared primitive, N probe decisions are
   validated with `validate_output()`. Zero errors required. A bare
   string return, a wrong output type, or an out-of-range confidence
   fails.
2. **abstention.** Refusal-shaped probes (refusal prefixes,
   provider block phrasing) must yield `abstained=True`,
   `decision=""`, non-empty `refusal_reason`. An adapter that raises
   on refusals, or returns a decision string for them, fails.
3. **determinism.** The same probe input twice (fresh contexts)
   yields identical `(decision, abstained)`. An adapter may declare
   a sampling posture instead; the kit then asserts the declared
   posture matches observed behavior (a self-declared deterministic
   adapter that wobbles fails; a declared sampler that is secretly
   deterministic gets a warning). Note: this softens P-4's
   "determinism" must-pass wording into posture-verification; see
   section 13.
4. **metadata-invariance (holdout-integrity probe).** The kit calls
   `decide()` with (a) contexts carrying extra plausible-looking
   attributes and (b) case inputs with injected plausible junk keys,
   and asserts outputs are invariant. The probes are randomized and
   shaped like production traffic, never obviously synthetic: a
   probe the adapter can trivially fingerprint is a probe that
   tests nothing (red-team F6). This is the executable half of the
   blind-holdout guarantee: a plugin that sniffs trial metadata
   fails here.
5. **retry-posture.** The capability report must contain the
   author's self-attestation of retry behavior (single-attempt
   configuration, or a description of the provider SDK's built-in
   behavior). Missing attestation fails. A best-effort static scan
   of the adapter's module (tenacity/backoff decorators,
   urllib3/httpx retry config, explicit retry loops around provider
   calls) checks the attestation is not obviously false; scan
   findings are warnings with file and line, not failures, because
   "no nested retry loop" is not mechanically decidable in general.
   Note: this downgrades P-4's `max_retries=0` must-pass test into
   must-attest plus advisory scan; see section 13.
6. **import-safety.** The shim child imports the entry point within
   30 seconds, does not call `sys.exit`/`os._exit`, and completes
   the protocol handshake. Import never runs in the checker's
   process for third-party adapters.
7. **protocol round-trip.** The stdio framing from
   `docs/Adapter-Isolation.md` (init handshake, decide, error,
   shutdown) round-trips through the shim. Protocol version
   mismatch is a hard failure. No pipelining: at most one call is
   in flight per child at a time (a child may serve many calls
   sequentially, but never concurrently); response ids are matched
   strictly, and the child is dropped on any unsolicited or
   duplicate id (red-team F2). A malformed framing line fails that
   call only; id spoofing cannot corrupt a sibling call because
   there are no concurrent sibling calls.

### 6.2 Transport check

Through the subprocess transport, the kit additionally asserts: the
child dies on `shutdown` within 5 seconds (SIGKILL otherwise, whole
process group, section 7); a deliberately slow probe is killed at
the kit's `--timeout` and the next check starts a fresh child (no
shared protocol state across checks); stderr beyond 1 MB per call
is truncated with a marker and the call is failed, not OOMed.

### 6.3 Capability report

`peira adapter check --json` emits the capability table in machine
form: per-primitive support *observed* (not just declared),
`confidence_source` with its M-2 meaning, the required retry
self-attestation, what the harness can and cannot observe
(confidence, usage, reasoning tokens), with "unavailable rather
than zero" accounting for anything unreported. The report seals
`dist_name`, `dist_version`, and the SHA-256 of the adapter module
file actually loaded, so `--verify` and listing PRs can bind the
badge to exact bits (red-team F7). The human-readable form is the
checklist a listing PR pastes.

### 6.4 What the kit cannot prove (candor section)

- It cannot prove the absence of a nested retry loop (section
  6.1.5) or of covert metadata sniffing beyond the probes it runs.
  The probes catch naive sniffing; a determined adapter author can
  defeat any finite probe set, because the probes ship in the open.
  The kit raises the cost of cheating from zero to "must carry
  evasion code past review," which is the honest bar for a
  conformance kit, not a proof.
- It cannot prove information-flow properties of the sandbox. The
  blind-holdout argument (section 9) rests on the adapter-visible
  surface being content-free *by construction*, verified by code
  inspection of the runner, not by testing the adapter.

## 7. Isolation: runner-owned subprocess shim

`docs/Adapter-Isolation.md` designed adapter-owned console scripts
(`my-adapter-peira` on stdin/stdout, launched via
`--adapter-subprocess`). This design **deliberately deviates** on
packaging only:

- **Runner-owned shim instead of author-owned servers.** The runner
  spawns `python -m peira.adapters._shim <registry id>` using
  `sys.executable`, list-form `Popen` (never `shell=True`). The shim
  imports the adapter *in the child* and runs the stdio protocol
  loop. The `serve()` helper from `Adapter-Isolation.md` becomes
  the loop implementation shared by the shim. It is an internal
  implementation detail in v1, not a supported author extension
  point.

Rationale: (a) zero author ceremony, any `BaseAdapter`
implementation gets isolation without writing a server; (b)
uniform env scrubbing, an author-owned script could re-inherit the
operator's environment and silently void the "minimal environment"
property; (c) one framing implementation to audit instead of N.

### 7.1 Transport policy

- **Third-party (entry-point, non-first-party) adapters default to
  subprocess transport.** No flag, no opt-out at the adapter's
  request. The rule keys off provenance, stated explicitly: a
  first-party adapter registered in the same entry-point group
  still defaults to in-process as the reference implementation.
- **In-process for a third-party adapter requires an explicit
  operator flag** `--adapter-no-isolation <registry id>`. The name
  is meant to sound dangerous, because it is. The runner prints an
  explicit warning naming the consequences (the adapter gets the
  operator's full environment, filesystem, and network as the
  operator's UID), records `adapter_trust: no-isolation-opt-out` in
  the run artifact, and the docs say: never take CLI flags from an
  adapter's README (red-team F10). The R-03 rule stands: in-process
  means no isolation by design.
- `--adapter-subprocess` (existing design) opts any adapter into
  the shim for debugging.

### 7.2 Child environment (what the sandbox is)

- Empty temp working directory. Stdio is the protocol; stderr is a
  log stream, captured per call up to 1 MB (then truncated with a
  marker and the call failed), control sequences stripped or
  escaped before display, never parsed.
- Minimal environment built by the runner: a sanitized `PATH`,
  `TMPDIR`/`TEMP`, `SYSTEMROOT` on Windows, `HOME` pointed at a
  fresh temp dir, and nothing else inherited. Package visibility
  comes from the interpreter's own site-packages
  (`sys.executable` already has peira and the adapter installed);
  no `PYTHONPATH` is set. API keys and adapter config pass
  explicitly via `--adapter-env KEY=VALUE` (repeatable). Variable
  names are checked against a denylist
  (`LD_PRELOAD`, `DYLD_*`, `PYTHONPATH`, `PYTHONSTARTUP`,
  `PYTHONHOME`, and friends): denied names are refused with an
  actionable error, because an adapter's install docs could
  otherwise instruct the operator to re-arm exactly the channels
  the scrubbing removed (red-team F5). An adapter that dumps
  `os.environ` sees only what the runner gave it.
- Unix rlimits (`--rlimit-cpu-seconds`, `--rlimit-as-mb`,
  `--rlimit-fsize-mb`) apply to the child, per adapter, instead of
  process-wide. They are Unix-only (no-op with a warning on
  Windows). Third-party children get a default `--rlimit-as-mb`
  of 8192 unless the operator overrides it; CPU time stays bounded
  by the timeout kill. The default-off footgun R-03 names is
  closed for the memory dimension on the third-party path;
  in-process keeps today's opt-in semantics.
- Each child runs in its own process group (`start_new_session`
  on Unix); the timeout kill terminates the whole group, so a
  child that double-forks in the grace window cannot leave
  orphaned grandchildren behind (red-team F4). `--call-timeout`
  SIGTERMs the group on expiry, SIGKILLs after a grace period.
  The R-03 thread-zombie failure mode (hung adapter burns executor
  threads; the run's tail goes silently garbage) is structurally
  eliminated: a killed child frees its slot, and the retry is
  dispatched to a fresh child.
- No shared memory: the deep-copy-per-attempt guarantee becomes
  structural. The adapter cannot reach the runner's objects at all.
- Adapters that need local model files declare them up front via
  an optional `model_paths` attribute (list of absolute paths);
  the runner logs the declarations into the run artifact and
  passes them to the child through the handshake. The runner
  bind-mounts nothing and grants nothing by default (spec F2,
  restoring the Adapter-Isolation.md mechanism this section
  dropped).

### 7.3 What the sandbox is not (section 8 has the attack catalog)

No seccomp/syscall filtering, no network egress filtering, no UID
separation, no filesystem virtualization beyond cwd plus env
discipline. A malicious adapter can still do anything its UID can
do. The boundary contains blast radius and guarantees killability;
it does not make untrusted code safe to run. **Only run adapters
you trust remains true. The subprocess mode changes what "trust"
has to cover, from "everything about my machine, including
ambient credentials and the runner's memory" to "what my UID can
reach over the network and filesystem."** The docs state this in
plain words. Any copy that implies more is a defect.

### 7.4 Runner integration

The runner side uses `asyncio.create_subprocess_exec` and speaks
the protocol from the event loop; the `decide()` call signature
seen by the rest of the runner is unchanged (a proxy object
implements `decide(case_input, primitive, context)`), so scoring,
retries, concurrency control, and transcript writing are untouched.

## 8. Attack catalog: what the isolation model stops and does not

The red-team review of this doc attempted each of these. This
section is the review's checklist, not a claim of victory, and it
is append-only: any reviewer who finds an attack not on the list
adds it.

| # | Attack | Stopped? | Mechanism / residual |
|---|--------|----------|----------------------|
| A1 | Adapter reads `TYPESAFE_API_KEY` from inherited env | **Yes** | Child env is runner-built; nothing inherited wholesale; `--adapter-env` names are denylisted (A16) |
| A2 | Adapter reads/writes arbitrary files as the runner's UID | **Partial** | cwd is an empty temp dir, but the UID's filesystem is still reachable by absolute path. Stops opportunistic relative-path damage; does not stop targeted reads |
| A3 | Adapter hangs forever; zombie threads poison the run tail (R-03) | **Yes** | SIGTERM/SIGKILL the process group; fresh child per retry |
| A4 | Adapter burns unbounded CPU/RAM | **Partial** | Per-child rlimits bound it; third-party children get a default 8192 MB address-space cap (Unix-only). CPU beyond the timeout kill and Windows builds remain operator-configured |
| A5 | Malicious import-time code (runs before flags/rlimits today, R-03) | **Yes, on the run path** | Import happens in the child, after the runner applied rlimits and built the env. Scoped: true only when rlimits are actually set (they are by default for third-party children, section 7.2); the old in-process import hazard is unchanged for allowlisted adapters, by explicit operator choice |
| A6 | Adapter exfiltrates case text over the network | **No** | No egress filtering (explicit non-goal). Holdout bytes are still protected by OpSec (never published, separate invocation). See section 9 |
| A7 | Adapter detects holdout runs and behaves differently | **No by sandbox; yes by construction** | Nothing adapter-observable differs between public and holdout runs (section 9). The sandbox is irrelevant to this; the content-free boundary is the defense |
| A8 | Adapter poisons the next attempt via shared mutable state | **Yes** | No shared memory; deep-copy guarantee becomes structural |
| A9 | Adapter desyncs the stdio protocol to confuse scoring | **Yes, per call** | No concurrent pipelining (sequential reuse allowed); response ids matched strictly; the child is dropped on unsolicited or duplicate ids. A malformed line fails that call only. A Byzantine child can still lie in its own responses; scoring integrity assumes a non-Byzantine adapter |
| A10 | Adapter slow-loris: responds just under the timeout every call | **Partial** | Each call still bounded by `--call-timeout`; the run-level wall-clock budget bounds the run. Slow-loris wastes budget but cannot corrupt results |
| A11 | Confused deputy: adapter A registered under adapter B's name | **Yes** | Name-vs-attribute binding fails the load closed; the parent verifies the handshake `name` against the requested spec; duplicate-name claims fail closed at both `check` and `run` (no iteration-order winner) |
| A12 | Adapter phones home with the operator's API keys | **Partial** | Keys are passed explicitly, so only keys the operator chose to give are visible, but any key given *can* be exfiltrated (no egress filter). Key scoping stays the operator's job, stated in the docs |
| A13 | Maintainer runs `peira adapter check` on a malicious adapter; import-time code executes in the checker's process | **Yes** | `check` exercises third-party adapters through the shim child, never in-process (red-team F1). "Clean machine" for listing review means a fresh VM or container holding no credentials |
| A14 | Malicious child spoofs response ids to corrupt sibling calls' scoring | **Yes** | No pipelining: one in-flight call per child, strict id matching, drop on violation (red-team F2) |
| A15 | Child double-forks in the SIGTERM grace window; grandchildren survive the kill | **Yes** | Own process group per child; the kill terminates the group (red-team F4). The grace window still permits network exfiltration (A6 residual) |
| A16 | Adapter's install docs instruct `--adapter-env LD_PRELOAD=...`, re-arming scrubbed channels | **Yes** | Denylist on `--adapter-env` variable names, refused with an actionable error (red-team F5) |
| A17 | Attacker passes `check` on benign bits, then ships malicious code under a newer version while the listing advertises the old pass | **Yes, when verified** | The check report seals `dist_name`, `dist_version`, and the SHA-256 of the loaded module file; `check --verify` compares installed bits; the badge covers exact bits only (red-team F7). Unverified installs get no badge claim |
| A18 | Adapter smuggles holdout case text out through `transcript`, `usage.provider_response_id`, or `refusal_reason` (recorded verbatim, no egress needed) | **Partial** | Named in the section 9 residual. Holdout runs redact adapter-supplied transcript payloads to fixed schema fields (decision-relevant metadata only); the redaction is part of the holdout runner, not the adapter contract |

## 9. Blind-holdout integrity (non-negotiable)

The holdout's integrity does **not** depend on the sandbox. It
depends on the adapter-observable surface being identical between
public and holdout runs *by construction*:

1. **Content-free boundary (D-25, amended 2026-09-25).**
   `case_input` is exactly the case's input dict: no case id, no
   family, no arm, no suite tag, no holdout flag. `context` carries
   only the pseudonymous `call_id`, deterministic in `(seed,
   dispatch_index)`: stable across retries of the same call,
   opaque across runs. There is no gold anywhere on the adapter's
   side of the boundary, so there is nothing to echo.
2. **Protocol key-set pinning.** The subprocess protocol's decide
   params are exactly `{case_input, primitive, context}`. The
   conformance kit asserts the key set, so a future "helpful"
   addition like `run_name` or `suite_tag` fails conformance until
   a design review explicitly approves widening the boundary.
3. **Separate invocations.** Public runs and holdout runs are
   separate invocations under `Holdout-OpSec.md` (maintainer plus
   CI only, encrypted at rest, contamination rule). A third-party
   adapter author never receives holdout bytes through peira
   tooling. This argument assumes the holdout is executed by the
   trusted benchmark operator; delegating holdout execution to a
   third party would void the in-band guarantee, and the docs say
   so.
4. **No timing oracle.** This is a requirement on the holdout
   pipeline (private repo), recorded here because the design
   depends on it: holdout cases must mirror the public set's
   shape and severity mix behind a distribution-comparison gate,
   and holdout seeds must come from the same CSPRNG stream as
   public seeds. Runner concurrency, timeouts, and retry policy
   are identical. Nothing in a call's timing reveals which set it
   came from.
5. **Probe (section 6.1.4).** The conformance kit actively tries
   to catch metadata-sniffing adapters with randomized,
   production-shaped inputs.

Residual, stated plainly: an adapter with network egress *could*
exfiltrate case text to a collaborator who checks it against the
public set ("not in public set" implies holdout), and adapter
fields recorded verbatim (`transcript`, `provider_response_id`,
`refusal_reason`) are a second exfil channel needing no network
(red-team F8). The sandbox stops neither (section 8, A6 and A18).
The defenses are OpSec (holdout bytes never reach the adapter
author's hands through any peira channel; the contamination rule
forbids holdout bytes in anything sent to a third party) plus
transcript redaction on holdout runs (A18). This is the same
residual every blind benchmark carries. The design's contribution
is making the *in-band* channel content-free, which is
mechanically verifiable by inspecting the runner.

**Invariant for all future work:** no PR widens the
adapter-visible surface (new `CallContext` fields, new protocol
params, new `case_input` metadata) without a holdout-integrity
review. The Spec-fidelity review axis owns this check.

## 10. Contribution flow (lightweight lane)

P-4 requires a lane that does not demand the full three-review
gauntlet for community adapters. The lane:

1. Author implements `BaseAdapter`, publishes
   `peira-adapter-<slug>` to PyPI, registers the
   `peira.adapters` entry point.
2. Author runs `peira adapter check <name>`. The JSON report is
   attached to the listing request.
3. Listing request: a PR adding one row to the community table in
   `docs/Adapters.md` (name, version, capability summary, check
   date, sealed bits hash, link). No code is vendored into peira.
4. Maintainer re-runs `peira adapter check` on a clean machine
   (fresh VM or container, no credentials; the check itself runs
   the adapter in the shim child regardless), reads the
   capability table, does **one** review pass focused on the
   adapter's measurement honesty (`confidence_source`
   plausibility, usage-reporting honesty). Green kit plus sane
   review merges the docs row.
5. The row is a link, not an endorsement: "passed conformance on
   <date> for exactly these bits (sha256:…)" is a fact about a
   test run, not a recommendation. The badge never follows the
   package to a new version without a new check (A17). No vendor
   marks inside any data artifact (N-1 from the decant audit);
   the leaderboard never carries sponsor placement.

Delisting: a community row is removed (docs PR, same lightweight
lane) if a later `peira adapter check` fails against a newer
peira, or if measurement dishonesty is found. Removal is from the
docs table only. Peira never had the code.

## 11. Sequencing (implementation order)

1. `peira.adapters.discovery`: entry-point registry, resolution,
   name rules, confusion defenses (section 4). No runner behavior
   change yet. `peira adapter list` works; `run` still takes
   dotted paths.
2. `peira.adapters.conformance` plus `peira adapter check`
   (sections 5 and 6). Synthetic probes only.
3. `peira.adapters.subprocess`: protocol framing, `serve()` loop,
   runner-owned shim `python -m peira.adapters._shim`, child env
   builder, process-group timeout kill, rlimit move (section 7).
4. Runner wiring: entry-point third-party adapters default to
   subprocess transport; `--adapter-no-isolation`; artifact
   records `adapter_trust` and `adapter_transport`.
5. Docs: `docs/third-party-adapters.md` (the contribution flow),
   `docs/Adapters.md` community table,
   `docs/Threat-Model.md` runner-security update,
   `docs/Adapter-Isolation.md` marked implemented-with-deviation
   (section 7), `docs/Troubleshooting.md` new error strings (all
   enumerated in section 5), `docs/CLI.md` new commands,
   `docs/Glossary.md` new terms (shim, transport, conformance kit,
   capability report, registry id, adapter spec),
   `docs/FAQ.md` new failure modes, `docs/Claims.md` referencing
   the isolation claims. `docs/Methodology.md` only if the
   adapter boundary changes (it does not).

Each step ships as its own commit. Steps 1 and 2 can land before
3 and 4.

## 12. Open questions for reviewers

1. Is the name-vs-attribute binding (section 4.3) too strict for
   adapters whose PyPI slug differs from their display name? (It
   binds the *entry-point name* to `adapter.name`, not the PyPI
   name. The author chooses both.)
2. Should the conformance report be sealed into run artifacts when
   a checked adapter is used (`adapter_check: {date,
   peira_version, passed, bits_sha256}`)? (Lean: yes. Cheap
   provenance, M-7 spirit.)

## 13. Review-readiness

- Spec: P-4 of the decant audit (section 1); R-03 threat model
  (`docs/Threat-Model.md`); D-25 content-free boundary;
  `docs/Adapter-Isolation.md` protocol.
- Verified: this is a design doc; verification is the review
  itself. Red-team re-audit (explicit isolation-model attack),
  Spec axis, Standards axis, and the author's own line-by-line
  pass are recorded in the lane's gate report. No code, no tests,
  no behavior change in the design commits.
- Known deviations from the cited specs:
  - Section 7 packaging deviates from `docs/Adapter-Isolation.md`
    (runner-owned shim vs author-owned console scripts), with
    rationale, flagged for explicit reviewer approval.
  - Section 6.1.5 downgrades P-4's `max_retries=0` must-pass
    contract test to must-attest plus advisory static scan, with
    the undecidability rationale. P-4's other three named tests
    (schema, abstention, determinism) are must-pass, except the
    determinism posture-verification softening noted below.
  - Section 6.1.3 softens P-4's determinism test into
    declared-posture verification (a declared sampler is not
    failed for sampling).
- Reviews required before implementation: red-team re-audit with
  an explicit attempt to break the isolation model (section 8 is
  the checklist), plus the two-axis Spec/Standards review.
  All three returned APPROVE-WITH-CHANGES; every finding was
  adjudicated in this revision.
