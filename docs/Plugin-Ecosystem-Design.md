# Plugin ecosystem design: third-party adapters (P-4)

**Status:** design doc for review — no implementation yet.
**Proposal:** P-4 from the decant audit
(`~/workspace/decant-audit/decant-audit-report.md` §P-4).
**Supersedes on:** `docs/Adapter-Isolation.md` §"Adapter packaging"
(console-script packaging; see §7 for why the runner-owned shim
replaces it). The protocol, handshake, and security properties of
`Adapter-Isolation.md` are otherwise adopted unchanged.

## 1. Goal

Give peira a third-party adapter story so the project is not limited
to adapters David authors:

1. **Discovery** — `pip install peira-adapter-foo` registers the
   adapter; no dotted-path hack, no vendoring into the peira repo.
2. **Conformance** — `peira adapter check` runs a contract test kit
   any adapter must pass before it is listed or trusted.
3. **Isolation** — third-party adapters run out of the runner's
   process by default, in the subprocess/JSON mode designed in
   `docs/Adapter-Isolation.md`. In-process loading stays available
   only as an explicit, documented trust decision by the operator.
4. **Contribution flow** — a lightweight lane for community adapters
   (conformance green + one maintainer review), not the full
   three-review gauntlet that in-repo adapters get.

## 2. Non-goals

- A security sandbox. The subprocess boundary is blast-radius
  containment and killability, not a sandbox: no seccomp, no network
  egress filtering, no UID change. §8 states exactly what is and is
  not stopped, and the red-team review of this doc is required to
  attempt to break the isolation model before implementation.
- Changing the adapter API. `decide(case_input, primitive, context)`
  is unchanged; only discovery and transport change.
- Weakening any existing adapter gate. The conformance kit is
  additive. In-repo adapters keep every gate they have today.
- A plugin story for anything other than adapters (scorers, gates,
  metrics stay in-repo).

## 3. Discovery via `entry_points`

### 3.1 Group and naming

Entry-point group: **`peira.adapters`**.

```toml
[project.entry-points."peira.adapters"]
my-adapter = "my_adapter_pkg.module:adapter"
```

- The entry-point **name** is the adapter's CLI id
  (`peira run --adapter my-adapter`, `peira adapter check my-adapter`).
- Name rules, enforced at discovery time: `^[a-z0-9][a-z0-9_-]{1,63}$`
  (no dots — dots unambiguously mean dotted-path), not `mock`
  (reserved), not starting with `peira-` (reserved for first-party
  packaging; third-party packages are encouraged to be named
  `peira-adapter-<slug>` on PyPI but the registry id itself drops the
  prefix).
- The entry-point **value** is a library reference in the same two
  forms the dotted-path loader accepts: `package.module` (module-level
  `adapter` object) or `package.module:ClassName` (instantiated with no
  arguments). No new syntax to learn.
- Peira registers its own first-party adapters under the same group,
  so `peira adapter list` shows one registry. Dotted-path loading
  keeps working unchanged for back-compat.

### 3.2 Resolution order (unambiguous by construction)

1. `mock` → the built-in mock (unchanged).
2. Spec contains `.` or `:` → dotted-path loader (unchanged behavior,
   unchanged trust warning).
3. Otherwise → `peira.adapters` entry-point lookup by exact name.

Because entry-point names cannot contain dots, a spec can never match
both rule 2 and rule 3.

### 3.3 Confusion defenses

- **Name-vs-attribute binding:** after loading, the runner asserts
  `adapter.name == <entry-point name>`. A package that registers the
  name `shieldstral` but serves a different adapter fails closed at
  load with an actionable error. (First-party entry points are
  exempt: their names are pinned in this repo.)
- **Collision:** two distributions registering the same name is an
  installation conflict, not a runtime tiebreak. Discovery reports
  every distribution that claims a name in `peira adapter list
  --verbose`; `peira adapter check <name>` fails closed on ambiguity
  and tells the operator to uninstall one claimant.
- **Provenance is visible:** `peira adapter list` always shows the
  owning distribution (`my-adapter 0.2.0 from peira-adapter-foo
  1.4.2`). Typosquatting remains possible — as with all of PyPI —
  and the docs say so plainly: peira never endorses a package, only
  reports that it passed conformance on a given date.

## 4. The adapter contract (unchanged, pinned for plugins)

Third-party adapters implement `BaseAdapter`
(`python/peira/adapters/base.py`) exactly as first-party adapters do:
`name`, `version` (exact pinned model version, never an alias),
`supported_primitives`, `confidence_source` (M-2 vocabulary),
`cache_namespace`, and `decide(case_input, primitive, context)`
returning the primitive's output object. The retry-layering rule
(runner owns retries; adapters configure provider SDKs to a single
attempt) applies to plugins with no exception.

Two plugin-specific obligations, both enforced by the conformance kit:

- **No adapter-visible metadata dependency.** `case_input` is exactly
  the case's input dict; `context` carries only the pseudonymous
  `call_id`. A plugin must not branch on anything else, because
  nothing else is there — and the kit probes that the adapter does
  not *reach* for more (see §6.4).
- **Self-declared determinism posture.** The capability report states
  whether the adapter is deterministic for a fixed input; the kit
  verifies the claim on probes.

## 5. `peira adapter` CLI

```
peira adapter list [--verbose] [--json]
peira adapter check <spec> [--json] [--probes N] [--timeout S]
```

- `list`: every registered adapter — name, version, primitives,
  owning distribution, first-party vs third-party, default transport.
  Exit 0 always (discovery errors are reported per-row, never fatal).
- `check`: runs the conformance kit (§6) against one adapter spec
  (entry-point name or dotted path). Exit 0 = all checks pass,
  1 = any check fails, 2 = usage/loading error. `--json` emits a
  machine-readable report for CI and listing PRs.
- Every error string the new commands can emit is added to
  `docs/Troubleshooting.md` (repo convention). `docs/CLI.md` gains
  the new commands.

## 6. Conformance kit

`python/peira/adapters/conformance.py`: a library (`run_checks(adapter,
...) -> Report`) plus the CLI. Checks run against **synthetic probe
cases authored by the kit** — never dataset cases, never holdout bytes
(the kit must be runnable by anyone, so it cannot depend on anything
non-public).

### 6.1 Contract checks (pass/fail)

1. **schema** — for each declared primitive, N probe decisions are
   validated with `validate_output()`; zero errors required. A bare
   string return, a wrong output type, or an out-of-range confidence
   fails.
2. **abstention** — refusal-shaped probes (refusal prefixes, provider
   block phrasing) must yield `abstained=True`, `decision=""`,
   non-empty `refusal_reason`. An adapter that raises on refusals, or
   returns a decision string for them, fails.
3. **determinism** — the same probe input twice (fresh contexts)
   yields identical `(decision, abstained)`. If the adapter declares
   nondeterminism, the kit instead asserts the *declared posture
   matches observed behavior* (a self-declared deterministic adapter
   that wobbles fails; a declared sampler that is secretly
   deterministic gets a warning, not a failure).
4. **metadata-invariance (holdout-integrity probe)** — the kit calls
   `decide()` with (a) contexts carrying extra unexpected attributes
   and (b) case inputs with injected junk keys, and asserts outputs
   are invariant. This is the executable half of the blind-holdout
   guarantee: a plugin that sniffs trial metadata fails here.
5. **retry-posture (advisory)** — a best-effort static scan of the
   adapter's module for nested retry machinery (tenacity/backoff
   decorators, urllib3/httpx retry config, explicit retry loops
   around provider calls). Findings are warnings with file/line, not
   failures: "no nested retry loop" is not mechanically decidable in
   general, and the doc says so. The capability report (§6.3) carries
   the author's self-attestation; the scan checks the attestation is
   not *obviously* false.
6. **import-safety** — loading the entry point completes within 30 s,
   does not call `sys.exit`, and leaves no `os._exit` behind. (Import
   runs in the kit's process for library adapters; see §7 for why
   run-time isolation is a separate layer.)
7. **protocol round-trip** — the stdio framing from
   `docs/Adapter-Isolation.md` (init handshake, decide, error,
   shutdown) round-trips against the adapter through the shim.
   Protocol version mismatch is a hard failure.

### 6.2 Transport check

When the adapter is exercised through the subprocess transport, the
kit additionally asserts: the child dies on `shutdown` within 5 s
(SIGKILL otherwise); a deliberately slow probe is killed at the
kit's `--timeout` with the protocol left in a clean state for the
next call (fresh child per check — no shared protocol state across
checks).

### 6.3 Capability report

`peira adapter check --json` emits the P-3 capability table in
machine form: per-primitive support *observed* (not just declared),
`confidence_source` with its M-2 meaning, what the harness can and
cannot observe (confidence? usage? reasoning tokens?), and
"unavailable rather than zero" accounting for anything unreported.
The human-readable form is the checklist a listing PR pastes.

### 6.4 What the kit cannot prove (candor section)

- It cannot prove the absence of a nested retry loop (§6.1.5) or of
  covert metadata sniffing beyond the probes it runs. It raises the
  cost of cheating from zero to "must defeat the probes," which is
  the honest bar for a conformance kit.
- It cannot prove information-flow properties of the sandbox. The
  blind-holdout argument (§9) rests on the adapter-visible surface
  being content-free *by construction*, verified by code inspection
  of the runner, not by testing the adapter.

## 7. Isolation: runner-owned subprocess shim

`docs/Adapter-Isolation.md` designed adapter-owned console scripts
(`my-adapter-peira` on stdin/stdout, launched via
`--adapter-subprocess`). This design **deliberately deviates** on
packaging only:

- **Runner-owned shim instead of author-owned servers.** The runner
  spawns `python -m peira.adapters._shim <spec>`; the shim imports
  the adapter *in the child* and runs the stdio protocol loop. The
  `serve()` helper from `Adapter-Isolation.md` becomes the loop
  implementation shared by the shim (and remains available for
  authors who want a standalone server, but nothing requires it).

Rationale: (a) zero author ceremony — any `BaseAdapter`
implementation gets isolation without writing a server; (b) uniform
env scrubbing — an author-owned script could re-inherit the
operator's environment, silently voiding the "minimal environment"
property; (c) one framing implementation to audit instead of N.

### 7.1 Transport policy

- **Entry-point (third-party) adapters default to subprocess
  transport.** No flag, no opt-out at the adapter's request.
- **In-process for a third-party adapter requires an explicit
  operator flag** (`--adapter-in-process-allowlist my-adapter`) that
  documents the trust decision in the run artifact (`adapter_trust:
  in-process-allowlisted`). The R-03 rule stands: in-process means no
  isolation by design.
- **First-party adapters keep the in-process path** as the reference
  implementation; `--adapter-subprocess` (existing design) opts any
  adapter into the shim for debugging.

### 7.2 Child environment (what the sandbox is)

- Empty temp working directory; stdio is the protocol (stderr is a
  log stream, captured per call, never parsed).
- Minimal environment built by the runner: a sanitized `PATH`,
  `TMPDIR`/`TEMP`, `SYSTEMROOT` on Windows, `HOME` pointed at a fresh
  temp dir, and nothing else inherited. API keys and adapter config
  pass explicitly via `--adapter-env KEY=VALUE` (repeatable); the
  runner never inherits its own environment wholesale into the
  child. An adapter that dumps `os.environ` sees only what the
  runner gave it.
- Unix rlimits (`--rlimit-cpu-seconds`, `--rlimit-as-mb`,
  `--rlimit-fsize-mb`) apply to the child, per adapter, instead of
  process-wide — the bluntness R-03 complains about is fixed by the
  move.
- `--call-timeout` SIGTERMs the child on expiry, SIGKILLs after a
  grace period. The thread-zombie failure mode in R-03 (hung adapter
  burns executor threads; the run's tail goes silently garbage) is
  structurally eliminated: a killed child frees its slot, and the
  retry is dispatched to a fresh child.

### 7.3 What the sandbox is not (§8 has the attack catalog)

No seccomp/syscall filtering, no network egress filtering, no UID
separation, no filesystem virtualization beyond cwd+env discipline.
A malicious adapter can still do anything its UID can do — the
boundary contains blast radius and guarantees killability; it does
not make untrusted code safe to run. **Only run adapters you trust
remains true; the subprocess mode changes what "trust" has to cover
from "everything about my machine" to "what my UID can reach over
the network and filesystem."** The docs state this in plain words;
any copy that implies more is a defect.

## 8. Attack catalog: what the isolation model stops and does not

The red-team review of this doc must attempt each of these and
report which the design actually defeats. (This section is the
review's checklist, not a claim of victory.)

| # | Attack | Stopped? | Mechanism / residual |
|---|--------|----------|----------------------|
| A1 | Adapter reads `TYPESAFE_API_KEY` from inherited env | **Yes** | Child env is runner-built; nothing inherited wholesale |
| A2 | Adapter reads/writes arbitrary files as the runner's UID | **Partial** | cwd is an empty temp dir, but the UID's filesystem is still reachable by absolute path. Stops opportunistic `open("...")` relative-path damage; does not stop targeted reads |
| A3 | Adapter hangs forever; zombie threads poison the run tail (R-03) | **Yes** | SIGTERM/SIGKILL the child; fresh child per retry |
| A4 | Adapter burns unbounded CPU/RAM | **Partial** | Per-child rlimits bound it (opt-in flags, same as today but per-adapter). Default-off remains a footgun: document the recommended defaults |
| A5 | Malicious import-time code (runs before flags/rlimits today, R-03) | **Yes** | Import happens in the child, after the runner applied rlimits and built the env |
| A6 | Adapter exfiltrates case text over the network | **No** | No egress filtering (explicit non-goal). Holdout bytes are still protected by OpSec (never published, separate invocation) — see §9 |
| A7 | Adapter detects holdout runs and behaves differently | **No by sandbox; yes by construction** | Nothing adapter-observable differs between public and holdout runs (§9). The sandbox is irrelevant to this; the content-free boundary is the defense |
| A8 | Adapter poisons the next attempt via shared mutable state | **Yes** | No shared memory; deep-copy guarantee becomes structural |
| A9 | Adapter desyncs the stdio protocol to confuse scoring | **Yes** | Framing is length-agnostic JSON-per-line with request ids; a malformed line fails that call only; fresh child per retry |
| A10 | Adapter slow-loris: responds just under the timeout every call | **Partial** | Each call still bounded by `--call-timeout`; run-level wall-clock budget (existing `--max-wallclock`) bounds the run. Slow-loris wastes budget but cannot corrupt results |
| A11 | Confused deputy: adapter A registered under adapter B's name | **Yes** | §3.3 name-vs-attribute binding fails the load closed |
| A12 | Adapter phones home with the operator's API keys | **Partial** | Keys are passed explicitly, so only keys the operator chose to give are visible — but any key given *can* be exfiltrated (no egress filter). Key scoping stays the operator's job, stated in the docs |

Any reviewer who finds an attack not on this list adds it; the list
is append-only.

## 9. Blind-holdout integrity (non-negotiable)

The holdout's integrity does **not** depend on the sandbox. It
depends on the adapter-observable surface being identical between
public and holdout runs *by construction*:

1. **Content-free boundary (D-25, amended 2026-09-25).** `case_input`
   is exactly the case's input dict — no case id, no family, no arm,
   no suite tag, no holdout flag. `context` carries only the
   pseudonymous `call_id`, deterministic in `(seed,
   dispatch_index)`: stable across retries of the same call, opaque
   across runs. There is no gold anywhere on the adapter's side of
   the boundary, so there is nothing to echo.
2. **Protocol key-set pinning.** The subprocess protocol's decide
   params are exactly `{case_input, primitive, context}` — the
   conformance kit asserts the key set, so a future "helpful"
   addition like `run_name` or `suite_tag` fails conformance until a
   design review explicitly approves widening the boundary.
3. **Separate invocations.** Public runs and holdout runs are
   separate invocations under `Holdout-OpSec.md` (maintainer + CI
   only, encrypted at rest, contamination rule). A third-party
   adapter author never receives holdout bytes through peira tooling.
4. **No timing oracle.** Holdout cases mirror the public set's shape
   and severity mix; runner concurrency, timeouts, and retry policy
   are identical. Nothing in the call's timing reveals which set it
   came from.
5. **Probe (§6.1.4).** The conformance kit actively tries to catch
   metadata-sniffing adapters with junk-keyed inputs and
   attribute-laden contexts.

Residual, stated plainly: an adapter with network egress *could*
exfiltrate case text to a collaborator who checks it against the
public set ("not in public set" ⇒ holdout). The sandbox does not
stop this (§8 A6); the OpSec controls do (holdout bytes never reach
the adapter author's hands through any peira channel, and the
contamination rule forbids holdout bytes in anything sent to a third
party). This is the same residual every blind benchmark carries;
the design's contribution is making the *in-band* channel
content-free, which is mechanically verifiable.

**Invariant for all future work:** no PR widens the adapter-visible
surface (new `CallContext` fields, new protocol params, new
`case_input` metadata) without a holdout-integrity review. The
Spec-fidelity review axis owns this check.

## 10. Contribution flow (lightweight lane)

P-4 requires a lane that does not demand the full three-review
gauntlet for community adapters. The lane:

1. Author implements `BaseAdapter`, publishes
   `peira-adapter-<slug>` to PyPI, registers the
   `peira.adapters` entry point.
2. Author runs `peira adapter check <name>`; the JSON report is
   attached to the listing request.
3. Listing request = a PR adding one row to the community table in
   `docs/Adapters.md` (name, version, capability summary, check
   date, link). No code is vendored into peira.
4. Maintainer re-runs `peira adapter check` on a clean machine,
   reads the capability table, does **one** review pass focused on
   the adapter's measurement honesty (confidence_source plausibility,
   usage-reporting honesty). Green kit + sane review = merge the
   docs row.
5. The row is a link, not an endorsement: "passed conformance
   <date>" is a fact about a test run, not a recommendation. No
   vendor marks inside any data artifact (N-1 from the decant
   audit); the leaderboard never carries sponsor placement.

Delisting: a community row is removed (docs PR, same lightweight
lane) if a later `peira adapter check` fails against a newer peira,
or if measurement dishonesty is found. Removal is from the docs
table only — peira never had the code.

## 11. Sequencing (implementation order)

1. `peira.adapters.discovery` — entry-point registry, resolution,
   name rules, confusion defenses (§3). No runner behavior change
   yet: `peira adapter list` works, `run` still takes dotted paths.
2. `peira.adapters.conformance` + `peira adapter check` (§5–§6).
   Synthetic probes only.
3. `peira.adapters.subprocess` — protocol framing, `serve()` loop,
   runner-owned shim `python -m peira.adapters._shim`, child env
   builder, timeout kill, rlimit move (§7).
4. Runner wiring: entry-point adapters default to subprocess
   transport; `--adapter-in-process-allowlist`; artifact records
   `adapter_trust` and `adapter_transport`.
5. Docs: `docs/third-party-adapters.md` (the contribution flow),
   `docs/Adapters.md` community table, `docs/Threat-Model.md`
   runner-security update, `docs/Adapter-Isolation.md` marked
   implemented-with-deviation (§7), `docs/Troubleshooting.md` new
   errors, `docs/CLI.md` new commands, `docs/Methodology.md` only
   if the adapter boundary changes (it does not).

Each step ships as its own commit; steps 1–2 can land before 3–4.

## 12. Open questions for reviewers

1. Should `peira adapter check` refuse to run a library adapter
   in-process at all (always via the shim), or is in-process check
   acceptable for the kit's synthetic probes? (Lean: always via the
   shim — the kit should test what the runner will actually do.)
2. Is the name-vs-attribute binding (§3.3) too strict for adapters
   whose PyPI slug differs from their display name? (It binds the
   *entry-point name* to `adapter.name`, not the PyPI name — the
   author chooses both.)
3. Per-child rlimits default-off (§8 A4): keep opt-in for back-compat,
   or make the subprocess transport apply sane defaults? (Lean:
   sane defaults for third-party children, documented; in-process
   keeps today's opt-in semantics.)
4. Should the conformance report be sealed into run artifacts when a
   checked adapter is used (`adapter_check: {date, peira_version,
   passed}`)? (Lean: yes — cheap provenance, M-7 spirit.)

## 13. Review-readiness

- Spec: P-4 from the decant audit report (§P-4 quoted in §1–§2
  above); R-03 threat model (`docs/Threat-Model.md`); D-25
  content-free boundary; `docs/Adapter-Isolation.md` protocol.
- Verified: this is a design doc; verification is the review itself.
  No code, no tests, no behavior change in this commit.
- Known deviations: §7 packaging deviates from
  `Adapter-Isolation.md` (runner-owned shim vs author-owned console
  scripts), with rationale. Flagged for explicit reviewer approval.
- Reviews required before implementation: red-team re-audit with an
  explicit attempt to break the isolation model (§8 is the
  checklist), plus the two-axis Spec/Standards review.
