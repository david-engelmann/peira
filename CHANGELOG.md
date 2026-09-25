# Changelog

All notable changes to this project will be documented here. The format is
based on Keep a Changelog, and the project adheres to Semantic Versioning
(the package and the dataset are versioned independently — see
`docs/Compatibility.md`).

## [Unreleased]

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

### Changed (2026-09-25)
- Analysis lock now covers **8 fields** (added `metrics` and
  `adapter_version`); artifacts sealed before 2026-09-25 fail `verify()`.
- `supported_primitives` filtering is now enforced: unsupported primitives
  are skipped (not malformed), with `n_scored`/`n_skipped`/
  `primitive_coverage` coverage metadata.
- `validate_output()` rejects booleans for Choice confidence and Score.
- Resume now verifies the partial's analysis lock and refuses (exit 1) on
  tampered or mismatched adapter/suite/dataset/version; foreign and
  duplicate case IDs are warned and ignored.
- Rust canonical JSON now byte-exact with Python (float formatting,
  string escapes); cross-implementation `verify` works.
- `peira verify` CLI command added (Python and Rust).
- Rust CLI: `--adapter-version` flag (required for external subprocess
  adapters).
- Jev adapter with multi-option Noul (per-option yes/no + argmax); 23
  mocked tests, zero live API calls.
- Docs: Adapter-Tutorial, API-Reference, Architecture, Abstain-Explainer,
  Score-Guide, Rust-Parity; README import paths corrected.
- **Adapter protocol v2 (breaking):** `decide()` now takes a single frozen
  `CaseContext` instead of `(case_input: dict, primitive: str)`. The
  context carries case id, primitive, variant input, and the
  attacked/benign flag — gold labels are structurally absent (the type
  system enforces the no-gold-leak invariant). `CaseContext` validates
  the primitive/variant and their agreement at construction.
  `ctx.to_wire()` reproduces the pre-v2 subprocess JSON shape, so the
  Rust side is untouched.
- `summarize()` now returns a frozen typed `RunSummary`
  (`PrimitiveCoverage` / `PerFamilySummary` / `ScoreCalibration`
  nested); `RunSummary.to_dict()` reproduces the artifact metrics JSON
  byte-for-byte — sealed artifact format unchanged.
- `run_suite()` is keyword-only after `(adapter, cases)`.
- Artifact filenames are Windows-safe: the CLI sanitizes the
  `--adapter` value (`my_adapter:MyGuardrail` →
  `my_adapter_MyGuardrail-….json`) for both final and `.partial.json`
  artifacts; path traversal is structurally impossible.
- README quickstart rewritten: timed install → run → verify → report
  steps with expected output, the "plumbing check, not a benchmark"
  warning, and next steps.
