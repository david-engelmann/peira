//! peira-core: Rust core for the empirical trial for decision models.
//!
//! Phase 0 status: the interface freeze lives in the Python reference
//! implementation (`python/peira/`). This crate will port the hot paths
//! (metrics, artifact hashing, case validation) once the Python interfaces
//! are frozen. The Python package remains the reference.

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
