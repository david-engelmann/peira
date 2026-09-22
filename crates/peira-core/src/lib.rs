//! peira-core: Rust core for the empirical trial for decision models.
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
pub mod dataset;
pub mod metrics;
pub mod schema;

pub mod canonical;

/// Crate version, kept in sync with the Python package by CI.
pub const VERSION: &str = env!("CARGO_PKG_VERSION");
