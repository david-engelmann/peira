# Third-party adapters

Ship your own decision model in the peira benchmark without touching
this repo. This page is the contributor-facing guide; the normative
spec is `docs/Plugin-Ecosystem-Design.md`.

> Status: discovery and the registry listing are implemented
> (`peira adapter list`). The conformance kit (`peira adapter check`),
> the subprocess isolation transport, and runner wiring land in the
> following steps of the plugin-ecosystem build. Until then,
> third-party adapters load the same way first-party ones do: by
> dotted path.

## Registering your adapter

Add an entry point to your distribution's packaging metadata:

```toml
[project.entry-points."peira.adapters"]
my-adapter = "my_package.module:MyAdapter"
```

Rules for the registry id (the entry-point name):

- Lowercase ASCII letters, digits, `_`, `-`; 2 to 64 characters; no
  dots (dots unambiguously mean a dotted path).
- `mock` is reserved for the built-in mock adapter; names starting
  with `peira-` are reserved for the project.
- The id MUST equal your adapter class's `name` attribute. A package
  that registers one id but serves an adapter whose `name` differs
  fails closed at load time: the confusion deputy cannot borrow a
  trusted name.
- If two distributions claim the same id, the spec fails closed with
  a name-collision error that names every claimant. Coordinate with
  the other author or pick a different id.

## Your adapter class

Implement the same `BaseAdapter` contract first-party adapters use
(`python/peira/adapters/base.py`): `name`, `version`,
`supported_primitives`, `decide(case_input, primitive, context)`,
`optional: close()`. The conformance kit (`peira adapter check`,
landing next) exercises your adapter against these before you
publish:

- protocol key-set pinning (the exact `CallContext` fields; extra
  keys are rejected, not warned),
- a holdout-integrity suite (no suite/arm label detection,
  metadata-invariance probes, no timing oracle),
- deterministic replay,
- the must-attest list (`max_retries=0`, no network calls during
  `decide`, no extra metadata), plus an advisory scanner whose
  findings you triage by hand.

## How your adapter runs

Third-party adapters run in a subprocess (`python -m
peira.adapters._shim <registry id>`), never inside peira's process:
your module is imported only in the child, on a stdio JSONL
protocol, with a scrubbed environment, a dedicated process group,
and memory/CPU limits. First-party adapters keep the in-process
path; anything else defaults to the subprocess. Pass
`--adapter-no-isolation` only when you explicitly accept running
untrusted code in-process (the CLI prints a warning; never take CLI
flags from an adapter's README).

## Provenance in every run

Run artifacts seal `adapter_trust` (first-party / third-party /
unverified-dotted-path) and `adapter_transport` (inprocess /
subprocess), plus the distribution name, version, and SHA-256 of
the loaded module. A leaderboard row appears only after a measured
run with name + version + date, same as first-party adapters.

## Open questions (being resolved)

See `docs/Plugin-Ecosystem-Design.md` section 1. If you are writing
an adapter today, the safest posture: pass the conformance kit,
declare `model_paths` for any model files your adapter loads, and
keep `decide` free of network calls.
