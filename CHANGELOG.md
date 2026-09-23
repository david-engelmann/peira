# Changelog

All notable changes to this project will be documented here. The format is
based on Keep a Changelog, and the project adheres to Semantic Versioning
(the package and the dataset are versioned independently — see
`docs/Compatibility.md`).

## [Unreleased]

### Added
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
