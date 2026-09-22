# Changelog

All notable changes to this project will be documented here. The format is
based on Keep a Changelog, and the project adheres to Semantic Versioning
(the package and the dataset are versioned independently — see
`docs/Compatibility.md`).

## [Unreleased]

### Added
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
