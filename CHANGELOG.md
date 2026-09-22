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
- Optional Rust accelerator: `crates/peira-python` exposes the Rust core to
  Python as the `peira._core` PyO3 extension (built with
  `scripts/build_core_ext.py`). The scoring hot paths in `peira.metrics`
  and `peira.schema` dispatch to it when importable and fall back to the
  pure-Python reference otherwise, so `pip install peira` still needs no
  Rust toolchain. Backend parity is pinned by
  `tests/test_rust_backend.py`; the `test-python-rust` CI job builds the
  extension and runs the Python suite against both backends.
