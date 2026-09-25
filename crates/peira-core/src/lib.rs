//! peira-core: Rust core for the empirical trial for decision models.
//!
//! This crate implements the hot paths (metrics, schema validation,
//! artifact hashing) in Rust for performance and correctness. The Python
//! package (`python/peira/`) provides the adapter SDK, CLI, and
//! orchestration via PyO3 bindings.

pub mod adapter_protocol;
pub mod artifacts;
pub mod metrics;
pub mod runner;
pub mod schema;

/// PyO3 bindings exposing the hot paths to Python as `peira._peira_core`.
/// Always compiled (the `extension-module` feature keeps `cargo test`
/// working); the extension is only *used* when the cdylib is built and
/// placed on the Python path. See `python/peira/_rust.py`.
pub mod python;

/// Crate version, kept in sync with the Python package by CI.
pub const VERSION: &str = env!("CARGO_PKG_VERSION");

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn version_is_set() {
        assert!(!VERSION.is_empty());
    }
}
