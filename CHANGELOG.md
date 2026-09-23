# Changelog

All notable changes to this project will be documented here. The format is
based on Keep a Changelog, and the project adheres to Semantic Versioning
(the package and the dataset are versioned independently — see
`docs/Compatibility.md`).

## [Unreleased]

### Changed (BREAKING — v2 measurement contract, ADR D-19)
- Every adapter output is now a full measurement record: `decision`,
  `confidence` (0..1 or None), `abstained`, `refusal_reason`, and `usage`
  (model, tokens_in/out, latency_ms, cost_usd, or None). `decide()` still
  receives the same input dicts — the input contract is unchanged — but
  what it returns is now a typed output object, never a bare decision.
- Results carry the benign and attacked `CallRecord`s side by side with
  `flipped`, `eligible`, and `ineligibility_reason`; every record adds
  the run `seed`, a deterministic `dispatch_index`, and an explicit
  `malformed` flag (set by the runner when validation fails or the call
  raises — never inferred from a sentinel decision).
- Eligibility is benign-validity: a case is eligible only with a usable
  benign baseline (well-formed, decided as expected, not abstained), with
  reasons `benign_malformed`, `benign_wrong_decision`, `benign_abstained`
  counted and reported. An attacked abstention counts as **not** flipped —
  refusals surface via `refusal_rate` (overall and per-family), never
  laundered into ASR. Attacked-malformed still counts as flipped (D-11).
- The targeted-attack-success metric is removed: the v2 result contract
  carries no target metadata. The leaderboard ranks on decision-change
  ASR only.
- Run artifacts are format version `"2"`; v1 artifacts are **rejected at
  load with a clear error, never migrated**. The analysis lock now also
  covers `pricing_source`, `pricing_date`, and `seed`.
- The runner is the authority on cost and latency: it overwrites
  adapter-reported `latency_ms` with its own wall-clock measurement and
  recomputes `cost_usd` from the pinned pricing table
  (`python/peira/data/pricing.json`, source and pin date sealed into the
  artifact). Unknown models price at 0.0 — explicitly unaccounted, never
  silently estimated.
- CLI: `peira run --seed <int>`; the run summary shows eligible count,
  refusal rate, and the ineligibility breakdown instead of
  targeted-success. HTML reports show nested call records, refusal rates,
  eligibility, pricing provenance, and seed.
- The Rust core and PyO3 bindings mirror the contract exactly (strict
  v2 artifact loading on both backends; parity fixtures regenerated from
  the Python reference).
- Backwards compatibility has zero weight while the project is
  pre-launch and unused: v1-shaped tests, docs, and examples were
  rewritten, not adapted (docs/Methodology.md, docs/Decisions.md D-12/D-16
  updates and new D-19, docs/Troubleshooting.md entries for v1 rejection,
  pricing-table errors, and resume seed mismatch).

### Added
- Trial dataset 1.0.1: five minor fixes from the case-quality audit —
  tr-cs-009 attacked variant now reads "an accounts-payable assistant"
  (restores the minimal pair); tr-pp-005 attacked variant drops the
  leftover benign-closing sentence; tr-df-001's persuasive anecdote
  distractor replaced with a neutral equipment-logistics item; all ten
  tr-df-* attacked variants move the "Additional context" flood block to
  between "Relevant facts" and the decision question; the trial-demo
  sa-001…sa-004 anchors now push toward each case's target decision
  (0.08-0.15 low risk) and the benign prompts state the 0.5 decision
  rule. Six gates green, manifest re-sealed, `dataset status` reports
  release-ready.
- Decision records D-16–D-18: `Case.extras` are tooling metadata and are
  never passed to adapters (adapter-facing configuration lives in the
  variant `input` dicts; the frozen `decide()` contract is untouched);
  `dataset_version` is the human-readable release label while the sealed
  manifest SHA-256 supplies byte identity; the mock adapter is a
  deterministic mechanism exerciser and no benchmark claim may rest on
  its numbers.
- Simplicity + scripts + CI hardening (H7): one shared `iter_cases()`
  generator replaces the three duplicated JSONL open/enumerate/parse
  loops (`dataset.summarize_cases`, `review._valid_cases`,
  `gates.run_gates`), and `run_gates` now validates each case exactly
  once, threading the result to every gate instead of re-validating.
  Review decisions fail fast on invalid case data (`error: unreadable
  case data: <file>:<line>`) instead of silently skipping bad lines.
  `review.json`, `--resume` partials, and run artifacts are written
  atomically (temp file + `os.replace`; last-writer-wins is the
  documented contract for concurrent `review approve`). `peira run
  --dry-run` no longer creates the output directory — zero side
  effects. `--adapter :Foo` now reports the documented "unknown
  adapter" error instead of `ValueError: Empty module name`.
  `scripts/check_doc_links.py` also verifies reference-style
  (`[text][ref]`) links. `peira dataset new --out` no longer glues onto
  a file missing its trailing newline. New Troubleshooting entries:
  `peira dataset status` exit 1, unreadable case data, and the
  trust note for dotted-path adapters (only load paths you trust —
  the module is imported and executed). CI pins
  `dtolnay/rust-toolchain` to 1.98.1 and smoke-tests the `peira-cli`
  binary (`validate --dir dataset/trial`) in `dataset-checks`.
- Backend parity + robustness (H6): `RunArtifact.from_json` now validates
  strictly on both backends — top-level object required,
  `peira_version`/`dataset_version` required, unknown fields rejected,
  every field's JSON type checked (`config`/`metrics` must be objects on
  the Rust side too), every `results` entry validated as a
  `PerCaseResult`-shaped object, and all other fields defaulting
  exactly like the Rust core (missing `config`/`metrics` become `{}`, not
  `null`), instead of silently defaulting or leaking `TypeError`
  (new ADR D-12). Malformed `--resume` partial entries (scalar or
  wrong-shaped result objects) raise a clear `ValueError` naming the entry
  index instead of `AttributeError`/`TypeError`. The `ece` / `brier_score`
  / `paired_bootstrap_ci` input asserts are explicit `ValueError`s
  (non-empty, equal-length) that survive `python -O` and are validated
  before backend dispatch so both backends agree (D-11 extended;
  `docs/Methodology.md` updated). Manifest verification rejects file
  names containing `..`, separators, or absolute paths before touching
  the filesystem, and reads `manifest.json` exactly once — the digest
  sealed into the analysis lock is always the digest of the verified
  bytes (no verify-then-reread race). Schema error strings now use a
  fixed escaping rule implemented identically in both languages
  (`_safe_repr` / `py_repr`) instead of `repr()`, making them
  byte-identical for every input (new ADR D-13). The Rust analysis lock
  streams canonical bytes straight into SHA-256 (no more deep-clone of
  `config`/`results`), case files are read+hashed in one pass, and
  canonical output sorts object keys explicitly. The Rust CLI matches the
  Python CLI's `validate` summary text (`validated N cases, M invalid`),
  full-path `file:line` errors, exit codes, and `--dir=` form, and types
  manifest errors instead of string-matching them. New user-facing errors
  are catalogued in `docs/Troubleshooting.md`.
- Trust-boundary hardening (H5): `peira report` now formats every
  metric cell through a single `_num` formatter (floats render with four
  decimals, anything unexpected is escaped) and escapes the artifact
  version, analysis lock, and manifest digest — closing the
  stored-XSS-shaped hole H2 left in the metric cells (regression-tested
  with a hostile artifact). `peira validate` reports malformed JSON
  lines as exit-1 user errors with `file:line` instead of tracebacks;
  `peira report` exits 1 (not 2) on corrupt artifacts and unwritable
  `--out`. The schema validator now enforces the declared JSON types
  (`bad case_id: expected string`, `bad benign input: expected object`,
  …) on both backends with byte-identical messages. `validate_output`
  rejects non-string decisions and non-numeric confidences instead of
  mis-scoring or raising bare `TypeError`. Case files are read as UTF-8
  on every platform. The Rust core rejects case-file lines nesting
  deeper than 256 levels before parsing. The three
  `paired_bootstrap_ci` / `ece` / `mcnemar` edge divergences now fail
  loudly and identically on both backends (new ADR D-11). New
  user-facing errors are catalogued in `docs/Troubleshooting.md`.
- Trial-demo disposition (T3): `dataset/trial-demo` confirmed as the
  12-case offline quickstart fixture (gate-exempt, contents frozen for
  the quickstart). Stale "starter suite" / "lands at v1" wording swept
  from `AGENTS.md`, `docs/Troubleshooting.md`, `docs/Decisions.md`, and
  the dataset docstring; `dataset/README.md` now lists the branded
  Trial; D-8's "to revisit" note resolved — Trial runs stay off the
  leaderboard (below the hard 20-case ranking gate).
- Branded 100-case Peira Trial (T2): `dataset/trial` now holds 100
  v1-quality cases (10 per attack family; 14 critical / 40 high / 46
  medium) authored through the full pipeline — all six gates green,
  100% of critical cases human-reviewed, manifest sealed at 1.0.0
  (`peira dataset status` reports release-ready). The README quickstart
  gains a per-adapter-class cost/time table, and the two stale Trial
  claims are reworded (the Trial is here now; per-case drill-down in
  `peira report` is real).
- Authoring pipeline, third slice (T1c): `peira dataset status --dir
  <dir>` — one view of the generate → gate → review → manifest flow
  (per-gate results, review pending/coverage, manifest state). Exit 0
  means release-ready (no gate errors, no pending reviews, manifest
  verifies clean); anything else is exit 1. Documented in
  `docs/Dataset.md`, including the authoring loop.
- Public decision records: `docs/Decisions.md` now records the locked
  methodology decisions as ADRs (D-4 decision-change ASR with targeted
  success secondary; D-5 asymmetric malformed handling; D-6 hard
  per-family ranking gate with exit code 3 for unranked runs; D-7 100%
  human review of critical cases; D-8 trial suites stay off the
  leaderboard; D-9 benchmark before thresholds library; D-10 no vendor
  pre-briefs). Each names the alternatives considered and what would
  trigger a revisit.
- Docs link check: `scripts/check_doc_links.py` fails CI on dead
  internal links (new `docs` job), so the growing docs set can't rot
  silently.
- GitHub issue templates for bug reports and feature requests.
- Authoring pipeline, second slice (T1b): the release seal in
  `peira dataset build-manifest`. The build now refuses when
  `--version` isn't semver, when any critical-severity case lacks a
  severity justification in its notes (the rubric's "say why" rule), or
  when the dataset changed under an already-sealed version — bump the
  version instead (idempotent rebuilds are still fine). `peira dataset
  new` also prints the family's severity hint so authors grade against
  the rubric at authoring time. New errors documented in
  `docs/Troubleshooting.md`.
- Authoring pipeline, first slice (T1a): CI runs the dataset checks on
  every push — `peira dataset gates --dir dataset/trial` and
  `peira dataset verify-manifest --dir dataset/trial` on the committed
  Trial starter suite, plus conditional gates/manifest checks on
  `dataset/v1` once it has case files. This makes the documented claim
  true: manifests are committed to git and a mismatch is a build
  failure. `dataset/trial-demo/` stays exempt (gate-exempt scaffolding).
- Byte-proof dataset identity (H4): `peira run` verifies the suite
  manifest before scoring and seals the manifest's SHA-256 into the
  analysis lock, so an artifact proves the exact dataset bytes scored —
  not just the version label. A verification mismatch fails closed
  (nothing is scored), and `peira run --resume` refuses a partial run
  recorded against a different dataset snapshot. The Rust
  `RunArtifact`/`lock_payload` mirror the new sealed field, with
  regenerated parity fixtures.
- Rust `Case` now preserves unknown top-level keys in `extras`
  (`#[serde(flatten)]`), matching Python's `Case.extras`, with a
  Python-generated fixture pinning byte-identical canonical round-trips
  across both implementations.

### Fixed
- Report HTML: `peira report` now escapes author-controlled strings
  (case ids, family names, adapter name/version, suite and dataset
  labels) so a hostile case id lands inert in the HTML.
- Docs: consolidated the two overlapping severity rubrics
  (`docs/Severity-Rubric.md` + `docs/SeverityRubric.md`) into a single
  `docs/Severity-Rubric.md` — tiers, rules, template-author guidance,
  and the confidence-movement disambiguation in one place.
- Mock adapter flip behavior: on its seeded flip subset the mock now flips
  toward each case's own `target_decision` (injected into the attacked
  input by the runner) instead of hard-coding the approve/deny toggle,
  so targeted-attack-success is meaningful for arbitrary decision labels
  (A/B, advance/reject, flag/clear, …). The approve/deny toggle remains
  as the fallback for target-less synthetic inputs. Deterministic and
  bit-for-bit reproducible as before.

### Added
- Initial scaffold: Python SDK (`BaseAdapter`, case schema, runner,
  metrics, sealed run artifacts), `peira` CLI (`run`/`validate`/`report`),
  deterministic mock adapter, 12-case offline demo fixture.
- Rust workspace with `peira-core` skeleton (ports hot paths after the
  Phase 0 interface freeze).
- Docs: Methodology, Taxonomy, Threat-Model, Severity-Rubric, Concepts,
  FAQ, Troubleshooting, Glossary, Hardware, Compatibility, Contributing,
  Claims, Decisions.
- CI: Python + Rust tests, `public-surface` strategy-language check, README
  quickstart executed verbatim on Ubuntu/macOS/Windows.
- Optional Rust accelerator: `crates/peira-python` exposes the Rust core to
  Python as the `peira._core` PyO3 extension (built with
  `scripts/build_core_ext.py`). The scoring hot paths in `peira.metrics`
  and `peira.schema` dispatch to it when importable and fall back to the
  pure-Python reference otherwise, so `pip install peira` still needs no
  Rust toolchain. Backend parity is pinned by
  `tests/test_rust_backend.py`; the `test-python-rust` CI job builds the
  extension and runs the Python suite against both backends.
- Trial-suite mechanism: `dataset/trial/` starter suite (20 scaffolding
  cases, 2 per family, all six gates green, manifest `0.1.0-trial`) wired
  to `peira run --suite trial`. Case schema is now forward-compatible:
  validators ignore unknown top-level fields and `Case.from_dict`
  preserves them on `Case.extras`, so future per-case configuration needs
  no pipeline refactoring. `peira run` records the suite's manifest
  dataset version in the artifact (part of the analysis lock); `peira
  report` gains a per-case results table for drilling into flips.
