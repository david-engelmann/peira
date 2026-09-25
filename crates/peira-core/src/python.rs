//! PyO3 bindings: peira-core hot paths callable from Python.
//!
//! Python (`python/peira/`) remains the reference implementation. These
//! bindings are bit-exact replacements for the pure-Python functions — the
//! underlying Rust is already covered by parity tests in `metrics.rs` and
//! `artifacts.rs`, and `tests/test_rust_parity.py` re-verifies the full
//! Python→Rust→Python round trip.
//!
//! Semantic notes (mirroring `python/peira/metrics.py`):
//! - `wilson_ci`, `mcnemar` match exactly, including `(0.0, 0.0)` / `0.0`
//!   edge cases.
//! - `ece` / `brier_score` raise `ValueError` on empty or length-mismatched
//!   input. The pure-Python reference raises `AssertionError` there (bare
//!   `assert`); `ValueError` is the deliberate, better-behaved equivalent
//!   for the compiled path.
//! - Integer arguments are `u64`: negative `hits`/`n` raise `OverflowError`
//!   instead of silently computing (Python would not reject them).

use pyo3::exceptions::{PyOverflowError, PyValueError};
use pyo3::prelude::*;
use sha2::{Digest, Sha256};

use crate::metrics;
use crate::metrics::FSumError;

fn map_fsum_error(e: FSumError) -> PyErr {
    match e {
        FSumError::IntermediateOverflow => {
            PyOverflowError::new_err("intermediate overflow in fsum")
        }
        FSumError::NegInfPlusInf => PyValueError::new_err("-inf + inf in fsum"),
    }
}

/// Wilson 95% confidence interval for a proportion.
///
/// Mirrors `peira.metrics.wilson_ci(hits, n, z=1.96)`.
#[pyfunction]
#[pyo3(signature = (hits, n, z = 1.96))]
fn wilson_ci(hits: u64, n: u64, z: f64) -> (f64, f64) {
    metrics::wilson_ci(hits, n, z)
}

/// McNemar chi-square for paired nominal data (no continuity correction).
///
/// Mirrors `peira.metrics.mcnemar(b, c)`.
#[pyfunction]
fn mcnemar(b: u64, c: u64) -> f64 {
    metrics::mcnemar(b, c)
}

/// Brier score: mean squared error between probabilities and labels.
///
/// Mirrors `peira.metrics.brier_score(probs, labels)`; raises `ValueError`
/// on empty or mismatched input (reference raises `AssertionError`).
/// The summation is correctly rounded, bit-exact with `math.fsum`.
#[pyfunction]
fn brier_score(probs: Vec<f64>, labels: Vec<u8>) -> PyResult<f64> {
    if probs.is_empty() || probs.len() != labels.len() {
        return Err(PyValueError::new_err(
            "probs and labels must be non-empty and the same length",
        ));
    }
    metrics::checked_brier_score(&probs, &labels).map_err(map_fsum_error)
}

/// Expected calibration error with equal-width bins.
///
/// Mirrors `peira.metrics.ece(probs, labels, bins=15)`; raises `ValueError`
/// on empty or mismatched input (reference raises `AssertionError`).
/// Binning and summation are bit-exact with the reference.
#[pyfunction]
#[pyo3(signature = (probs, labels, bins = 15))]
fn ece(probs: Vec<f64>, labels: Vec<u8>, bins: usize) -> PyResult<f64> {
    if probs.is_empty() || probs.len() != labels.len() {
        return Err(PyValueError::new_err(
            "probs and labels must be non-empty and the same length",
        ));
    }
    metrics::checked_ece(&probs, &labels, bins).map_err(map_fsum_error)
}

/// SHA-256 hex digest of raw bytes. Used for analysis locks
/// (`RunArtifact.compute_lock` hashes the canonical JSON payload).
#[pyfunction]
fn sha256_hex(data: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(data);
    format!("{:x}", hasher.finalize())
}

/// The compiled extension module, importable as `peira._peira_core`.
#[pymodule]
fn _peira_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(wilson_ci, m)?)?;
    m.add_function(wrap_pyfunction!(mcnemar, m)?)?;
    m.add_function(wrap_pyfunction!(brier_score, m)?)?;
    m.add_function(wrap_pyfunction!(ece, m)?)?;
    m.add_function(wrap_pyfunction!(sha256_hex, m)?)?;
    m.add("__version__", crate::VERSION)?;
    Ok(())
}
