//! peira-core: Rust core for peira, benchmarking decision models under attack.
//!
//! This crate ports the frozen Python reference implementation
//! (`python/peira/`) to Rust: case schema types and validation, dataset
//! loading, metrics, run artifacts with analysis locks, and the canonical
//! JSON serialization that keeps locks byte-identical across languages.
//!
//! [`canonical`] is the load-bearing piece: it replicates Python's
//! `json.dumps(sort_keys=True)` byte-for-byte (separators, `ensure_ascii`
//! escaping, float formatting), so a lock sealed by Python verifies in
//! Rust and vice versa. See the module docs for the exact rules.

pub mod artifact;
pub mod canonical;
pub mod compare;
pub mod dataset;
pub mod env;
pub mod execution;
pub mod gates;
pub mod metrics;
pub mod pricing;
pub mod py_repr;
pub mod records;
pub mod schema;

/// Crate version, kept in sync with the Python package by CI.
pub const VERSION: &str = env!("CARGO_PKG_VERSION");
