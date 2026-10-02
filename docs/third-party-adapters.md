# Third-party adapters

Ship your own decision model in the peira benchmark without touching
this repo. This page is the contributor-facing guide; the normative
spec is `docs/Plugin-Ecosystem-Design.md`.

The shape of it:

1. You publish a package on PyPI and register one entry point.
2. You run `peira adapter check <your-id>` until the conformance kit
   is green.
3. You run `peira run --adapter <your-id>`. Your adapter executes in a
   subprocess child, never inside peira's process.
4. You open a docs PR to add one row to the community table in
   `docs/Adapters.md`. No code is vendored into peira.

## Packaging: one entry point

Add this to your distribution's packaging metadata:

```toml
[project.entry-points."peira.adapters"]
my-adapter = "my_package.module:MyAdapter"
```

Rules for the registry id (the entry-point name):

- Lowercase ASCII letters, digits, `_`, `-`. Two to 64 characters,
  enforced as `^[a-z0-9][a-z0-9_-]{1,63}$`. No dots: a spec with a
  dot is always read as a dotted path, so an id can never be
  ambiguous.
- `mock` is reserved for the built-in mock adapter. Ids starting
  with `peira-` are reserved for first-party packaging. Name your
  PyPI distribution `peira-adapter-<slug>` if you like; the registry
  id itself drops the prefix.
- The entry-point value takes the same two forms the dotted-path
  loader accepts. `package.module` for a module-level `adapter`
  object, or `package.module:ClassName` for a class instantiated
  with no arguments. Nothing new to learn.
- The id MUST equal your adapter class's `name` attribute. After
  loading, the runner asserts `adapter.name == <registry id>`, and
  the shim parent verifies the handshake's reported name before the
  first decide call. A package that registers one id but serves an
  adapter whose `name` differs fails closed with
  `adapter name mismatch: registry '<id>' served '<name>'`. This is
  deliberate. The registry id is the only name the benchmark ever
  displays, and a mismatch means the package claims an identity its
  code does not back.
- If two installed distributions claim the same id, both
  `peira adapter check` and `peira run` fail closed with
  `adapter name '<id>' claimed by multiple distributions: <a>, <b>`,
  naming every claimant. There is no winner by install order.
  Uninstall one claimant or pick a different id.

Discovery (`importlib.metadata`) never imports adapter code. Only
loading does, and loading of third-party adapters happens inside
the shim child, never in the runner's process. `peira adapter list`
shows every registered adapter with its owning distribution
(`my-adapter 0.2.0 from peira-adapter-foo 1.4.2`); `--verbose` adds
entry-point values, ambiguous names, and discovery issues.
Typosquatting remains possible, as with all of PyPI, and peira does
not endorse packages. It only reports that a given set of bits
passed conformance on a given date.

## The adapter contract

Implement the same `BaseAdapter` protocol first-party adapters use
(`python/peira/adapters/base.py`):

- `name`. Must equal your registry id (see above).
- `version`. The exact pinned model version, never an alias like
  `latest`.
- `supported_primitives`. The frozenset of primitives you implement
  (`choice`, `score`, `abstain`). Partial coverage is fine. It is
  reported honestly per primitive, not penalized.
- `confidence_source`. How your `confidence` is elicited. One of
  `verbalized` (the model states it), `token-logprob` (a model-output
  probability), `guardrail-score` (distance from a detector's
  decision boundary), or `none`. Cross-adapter calibration
  comparisons are only honest when the reader knows which kind each
  number is (M-2).
- `cache_namespace`. Include anything that changes your output for
  the same input (temperature, seed, top_p, max_tokens). Leave `""`
  when your adapter is not deterministic or caching is meaningless.
- `decide(case_input, primitive, context)`. Always returns the
  primitive's output object (`ChoiceOutput` / `ScoreOutput` /
  `AbstainOutput`), never a bare decision string. A refusal is an
  abstained output with a non-empty `refusal_reason`, never a raised
  exception and never silently dropped.
- Optional `close()`.
- Conversational adapters additionally implement
  `decide_turn(turn_input, primitive, context)`. The runner only
  drives conversational adapters on the conversational suite. It
  never silently flattens a conversation into one prompt, because
  that would measure a different thing while pretending it was
  multi-turn.

What your adapter sees. `case_input` is exactly the case's own input
dict: no case id, no family, no arm, no suite tag, no holdout flag
(D-25). `context` carries only a pseudonymous `call_id`,
deterministic per call so retries stay stable, opaque across runs.
There is no gold on your side of the boundary, so there is nothing
to echo.

Hard rules inside `decide`:

- Do not retry inside the adapter. The runner owns retries.
  Transient provider failures (408/409/429/5xx, timeouts) retry up
  to `--max-attempts`; permanent ones never do. Raise
  `ProviderError` with a status code when one exists so the runner
  can tell the two apart. The conformance kit requires a
  `retry_posture` self-attestation (below).
- No network calls during `decide` unless the adapter genuinely
  needs them (a hosted model does). If you call a provider, say so
  in your attestation.
- Do not read trial metadata, because there is none to read. Extra
  keys in `context` or `case_input` beyond the pinned set fail the
  conformance kit, and the metadata-invariance probes try to catch
  sniffing. The blind-holdout guarantee (below) depends on this.
- `decide` runs in the shim child, one call at a time per child. Do
  not depend on shared mutable state across calls; the runner may
  restart the child between them.

## The conformance kit

`peira adapter check <id>` runs the contract test kit from
`python/peira/adapters/conformance.py`. It exercises your adapter
through the same subprocess shim the runner uses, against synthetic
probe cases authored by the kit. Never dataset cases, never holdout
bytes: the kit must be runnable by anyone, so it cannot depend on
anything non-public. Exit 0 means all checks pass, 1 means a check
failed, 2 means a usage or loading error. `check` needs a registry
id; dotted paths are refused, because the shim and the name binding
need a registered id to hold onto.

The checks, numbered per design doc section 6.1:

1. **schema.** Per-primitive probe decisions validate with zero
   errors. A bare string return, a wrong output type, or an
   out-of-range confidence fails.
2. **abstention.** Refusal-shaped probes must not raise. Any
   abstention they produce must have the valid shape:
   `abstained=True`, empty decision, non-empty `refusal_reason`.
3. **determinism.** The same probe input twice (fresh contexts)
   yields identical `(decision, abstained)`. Or your declared
   sampling posture matches observed behavior: a self-declared
   deterministic adapter that wobbles fails; a declared sampler
   that is secretly deterministic gets a warning.
4. **metadata-invariance (holdout-integrity probe).** The kit calls
   `decide()` with extra plausible-looking context attributes and
   with junk keys injected into case inputs, and asserts your
   outputs do not change. The probes are randomized and shaped like
   production traffic, never obviously synthetic.
5. **retry-posture (must-attest).** The capability report must carry
   your self-attestation of retry behavior. A best-effort static
   scan looks for obvious retry machinery (tenacity/backoff
   decorators, retry loops around provider calls); scan findings are
   warnings with file and line, never verdicts, because "no nested
   retry loop" is not mechanically decidable in general.
6. **import-safety.** The shim child imports your entry point within
   30 seconds, does not call `sys.exit`/`os._exit`, and completes
   the hello handshake. Your import-time code never runs in the
   checker's process.
7. **protocol round-trip.** Init handshake, decide, error framing,
   and shutdown round-trip through the shim. Protocol version
   mismatch is a hard failure. One call is in flight per child at
   a time; response ids are matched strictly, and the child is
   dropped on any unsolicited or duplicate id.

Transport checks on top: the child must die on shutdown within 5
seconds, and stderr beyond 1 MB per call is truncated with a marker
while the call fails rather than OOMing the checker.

Reading the report. `--out` writes a sealed JSON check report
(default `<adapter>-check.json`); `--json` prints the
machine-readable capability table to stdout instead of the human
summary. The capability table holds per-primitive support as
observed (not just declared), `confidence_source`, the required
retry attestation, and what the harness can and cannot observe.
The report seals `dist_name`, `dist_version`, and the SHA-256 of
the adapter module file actually loaded. `peira adapter check
--verify REPORT` re-hashes the installed bits and compares them to
the sealed digest, fully offline: no imports, no subprocesses. A
conformance badge covers exact bits only. Ship a new version and
the old check no longer describes it.

What the kit cannot prove (candor section). It cannot prove the
absence of a nested retry loop or of covert metadata sniffing
beyond the probes it runs. The probes ship in the open, so a
determined author could defeat any finite probe set. The kit raises
the cost of cheating from zero to "must carry evasion code past
review." That is the honest bar for a conformance kit, not a proof.

## How your adapter runs: the shim

Third-party registry ids default to the subprocess transport. The
runner spawns `python -m peira.adapters._shim <registry id>`
(list-form `Popen`, never `shell=True`). The shim imports your
adapter inside the child and speaks a stdio JSONL protocol with four
ops: `hello`, `decide`, `decide_turn`, `close`. Adapter `print()`
output is redirected away from the protocol channel, so import-time
prints cannot corrupt framing.

What the isolation actually is, in plain words:

- Your code runs in its own process, in its own process group.
  Timeouts kill the whole group (SIGTERM, then SIGKILL), so a hung
  adapter cannot poison the run's tail with zombie threads. A killed
  child frees its slot; the retry goes to a fresh child.
- The child gets a runner-built environment: a sanitized `PATH`,
  `TMPDIR`/`TEMP`, `SYSTEMROOT` on Windows, `HOME` pointed at a
  fresh temp dir, and whatever you pass via `--adapter-env`. Your
  adapter's `os.environ` shows only what the runner gave it.
  `--adapter-env` names are checked against a denylist
  (`LD_PRELOAD`, `DYLD_*`, `PYTHONPATH`, `PYTHONSTARTUP`,
  `PYTHONHOME`, and friends); denied names fail with
  `--adapter-env may not set denylisted variable 'LD_PRELOAD'`,
  because an adapter's install docs could otherwise instruct the
  operator to re-arm exactly the channels the scrubbing removed.
- Unix rlimits apply to the child. Third-party children get a
  default 8192 MB address-space cap unless the operator overrides
  `--rlimit-as-mb`. Unix-only; a warning on Windows.
- The child's working directory is an empty temp dir. Adapters that
  need local model files declare them up front via the optional
  `model_paths` attribute (a list of absolute paths). The runner
  logs the declarations into the run artifact and passes them to
  the child through the handshake.
- The decide protocol params are exactly
  `{case_input, primitive, context}`, with `context` carrying only
  the pinned keys (`call_id`). Key-set pinning is enforced by the
  conformance kit, so no future "helpful" addition can silently
  widen what the adapter sees.
- One call in flight per child at a time (no pipelining). A child
  that sends an unsolicited or duplicate response id is dropped.

What the isolation is not. No seccomp, no syscall filtering, no
network egress filtering, no UID separation, no filesystem
virtualization beyond cwd plus env discipline. A malicious adapter
can still do anything its UID can do, including reaching the
network. The boundary contains blast radius and guarantees
killability; it does not make untrusted code safe. Only run
adapters you trust. The subprocess mode narrows what "trust" has to
cover, from "everything about my machine, including ambient
credentials and the runner's memory" to "what my UID can reach over
the network and filesystem." Any copy that implies more is a
defect.

Never take CLI flags from an adapter's README.
`--adapter-no-isolation` exists for debugging and for adapters you
wrote yourself and trust completely. It imports third-party code
into peira's process with peira's full environment, and the CLI
prints a warning saying exactly that. It is an operator decision,
never something a package's install docs should instruct.

## --adapter-env

For API keys and other config your adapter needs in the child:

```bash
peira run --adapter my-adapter \
  --adapter-env TYPESAFE_API_KEY=sk-... \
  --adapter-env MY_ADAPTER_TIMEOUT=30
```

Repeatable, `KEY=VALUE` form, applied on top of the runner-built
environment. A missing `=` fails closed with
`error: --adapter-env needs KEY=VALUE, got 'MY_ADAPTER_TIMEOUT'`.
Keys the operator passes can be exfiltrated by a malicious adapter
(there is no egress filter), so scope them narrowly: give the child
only what the adapter needs, never ambient credentials. The same
flag exists on `peira adapter check` for the isolated check child.

## Blind-holdout integrity

Holdout runs and public runs are separate invocations under
`Holdout-OpSec.md`. What matters for you as an adapter author: the
adapter-visible surface is identical between public and holdout
runs by construction. `case_input` carries no case id, no family, no
arm, no suite tag, no holdout flag. `context` carries only the
pseudonymous `call_id`. There is no suite or arm label anywhere your
code can observe, so holdout runs are unlinkable: a run you cannot
identify as holdout is a run you cannot game. Holdout bytes never
reach adapter authors through any peira channel, and the
conformance kit's metadata-invariance probes exist to catch
adapters that sniff for trial metadata. The sandbox is irrelevant
to this property. The content-free boundary is the defense.

## Contribution flow: getting listed

1. Implement `BaseAdapter`, publish `peira-adapter-<slug>` to PyPI,
   register the `peira.adapters` entry point.
2. Run `peira adapter check <your-id>` until it is green. Keep the
   sealed JSON report.
3. Open a PR adding one row to the community table in
   `docs/Adapters.md`: registry id, adapter, capability summary,
   check date, dist name and version, module SHA-256, package link.
   No code is vendored into peira.
4. A maintainer re-runs the check on a clean machine (a fresh VM or
   container holding no credentials; the check itself runs the
   adapter in the shim child regardless), reads the capability
   table, and does one review pass focused on measurement honesty
   (`confidence_source` plausibility, usage-reporting honesty).
   Green kit plus a sane review merges the row.
5. The row is a link, not an endorsement. It states "passed
   conformance on <date> for exactly these bits (sha256:...)", a
   fact about a test run, not a recommendation. The badge never
   follows the package to a new version without a new check.

Delisting. A row is removed by docs PR if a later check fails
against a newer peira, or if measurement dishonesty is found.
Removal is from the docs table only. Peira never had the code.

## Provenance in every run

Run artifacts seal `adapter_trust` (`first-party`,
`third-party`, or `unverified` for dotted-path adapters) and
`adapter_transport` (`inprocess` or `subprocess`), plus the
distribution name, version, and SHA-256 of the loaded module. A
leaderboard row appears only after a measured run with name +
version + date, same as first-party adapters. No vendor marks
appear inside data artifacts (N-1); the leaderboard never carries
sponsor placement.

## When something goes wrong

Every CLI error string has a cause and fix in
`docs/Troubleshooting.md` under "Third-party adapter (plugin)
errors." Start there when `check` or `run` refuses your adapter.
