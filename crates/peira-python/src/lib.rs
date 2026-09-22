//! PyO3 bindings: peira-core as the Python extension module `peira._core`.
//!
//! This crate is a thin translation layer — no scoring logic lives here.
//! Every function delegates to `peira-core`, which is also the reference
//! the Rust CLI uses, so the Python and Rust paths cannot drift apart.
//!
//! The extension is optional: `python/peira/_rust.py` imports it when
//! present and every hot path falls back to the pure-Python reference
//! implementation otherwise. Two deliberate non-goals:
//!
//! - `paired_bootstrap_ci` is exposed but the Python side does not
//!   auto-dispatch to it: the Rust core uses SplitMix64 where the Python
//!   reference uses Mersenne Twister, so draws are not bit-identical.
//! - Float aggregates (`brier_score`, in principle `ece`) can differ from
//!   the reference by ~1 ulp: the reference sums with Python's compensated
//!   builtin `sum()`, the Rust core sums naively. Immaterial after the
//!   4-decimal rounding applied before anything is reported.
//! - Values that have no JSON representation (non-finite floats, integers
//!   wider than u64, non-string dict keys) raise `TypeError`/`ValueError`;
//!   the Python wrappers catch those and fall back to pure Python.

use peira_core::{canonical, metrics, schema};
use pyo3::exceptions::{PyTypeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyBool, PyDict, PyFloat, PyInt, PyList, PyString, PyTuple};
use serde_json::{Number, Value};

/// Convert an arbitrary Python object to `serde_json::Value`.
///
/// Only JSON-shaped values are accepted: None, bool, int, float, str,
/// list, tuple, and dicts with string keys. `bool` is checked before
/// `int` because Python's `bool` subclasses `int`.
fn value_from_py(obj: &Bound<'_, PyAny>) -> PyResult<Value> {
    if obj.is_none() {
        Ok(Value::Null)
    } else if let Ok(dict) = obj.cast::<PyDict>() {
        let mut map = serde_json::Map::with_capacity(dict.len());
        for (k, v) in dict.iter() {
            let key: String = k.extract().map_err(|_| {
                PyTypeError::new_err("dict keys must be strings for JSON conversion")
            })?;
            map.insert(key, value_from_py(&v)?);
        }
        Ok(Value::Object(map))
    } else if let Ok(list) = obj.cast::<PyList>() {
        list.iter()
            .map(|item| value_from_py(&item))
            .collect::<PyResult<Vec<_>>>()
            .map(Value::Array)
    } else if let Ok(tuple) = obj.cast::<PyTuple>() {
        tuple
            .iter()
            .map(|item| value_from_py(&item))
            .collect::<PyResult<Vec<_>>>()
            .map(Value::Array)
    } else if let Ok(s) = obj.cast::<PyString>() {
        Ok(Value::String(s.extract::<String>()?))
    } else if obj.cast::<PyBool>().is_ok() {
        Ok(Value::Bool(obj.extract::<bool>()?))
    } else if obj.cast::<PyInt>().is_ok() {
        if let Ok(i) = obj.extract::<i64>() {
            Ok(Value::Number(i.into()))
        } else if let Ok(u) = obj.extract::<u64>() {
            Ok(Value::Number(u.into()))
        } else {
            Err(PyValueError::new_err(
                "integer too large to represent in JSON",
            ))
        }
    } else if obj.cast::<PyFloat>().is_ok() {
        let f = obj.extract::<f64>()?;
        Number::from_f64(f)
            .map(Value::Number)
            .ok_or_else(|| PyValueError::new_err("non-finite floats have no JSON representation"))
    } else {
        let tname = obj
            .get_type()
            .name()
            .map(|n| n.to_string())
            .unwrap_or_else(|_| "<unknown type>".to_string());
        Err(PyTypeError::new_err(format!(
            "cannot convert {tname} to JSON"
        )))
    }
}

/// Mirror of the Python `PerCaseResult` dataclass, field-for-field.
/// Extracted from any Python object carrying those attributes.
#[derive(FromPyObject)]
struct PyPerCaseResult {
    case_id: String,
    family: String,
    primitive: String,
    benign_correct: bool,
    attacked_flipped: bool,
    attacked_targeted: bool,
    malformed: bool,
    confidence: Option<f64>,
    benign_malformed: bool,
    has_target: bool,
}

impl From<PyPerCaseResult> for metrics::PerCaseResult {
    fn from(r: PyPerCaseResult) -> Self {
        metrics::PerCaseResult {
            case_id: r.case_id,
            family: r.family,
            primitive: r.primitive,
            benign_correct: r.benign_correct,
            attacked_flipped: r.attacked_flipped,
            attacked_targeted: r.attacked_targeted,
            malformed: r.malformed,
            confidence: r.confidence,
            benign_malformed: r.benign_malformed,
            has_target: r.has_target,
        }
    }
}

fn to_core_results(results: Vec<PyPerCaseResult>) -> Vec<metrics::PerCaseResult> {
    results
        .into_iter()
        .map(metrics::PerCaseResult::from)
        .collect()
}

#[pyfunction]
#[pyo3(name = "version")]
fn version() -> &'static str {
    peira_core::VERSION
}

/// Validate a case dict; returns the list of violations (empty = valid).
///
/// Raises `TypeError`/`ValueError` for values with no JSON representation;
/// the Python wrapper falls back to the reference implementation then.
#[pyfunction]
fn validate_case_dict(d: &Bound<'_, PyDict>) -> PyResult<Vec<String>> {
    let v = value_from_py(d.as_any())?;
    Ok(schema::validate_case_dict(&v))
}

/// Wilson 95% confidence interval for a proportion (z = 1.96).
#[pyfunction]
fn wilson_ci(hits: u64, n: u64) -> (f64, f64) {
    metrics::wilson_ci(hits, n)
}

/// Conditional ASR: flips among ASR-eligible attacked cases, with Wilson CI.
#[pyfunction]
fn asr_conditional(results: Vec<PyPerCaseResult>) -> (f64, (f64, f64)) {
    metrics::asr_conditional(&to_core_results(results))
}

/// Benign accuracy with Wilson CI.
#[pyfunction]
fn benign_accuracy(results: Vec<PyPerCaseResult>) -> (f64, (f64, f64)) {
    metrics::benign_accuracy(&to_core_results(results))
}

/// Targeted attack success: (rate or None, number of targeted cases).
#[pyfunction]
fn targeted_attack_success(results: Vec<PyPerCaseResult>) -> (Option<f64>, usize) {
    metrics::targeted_attack_success(&to_core_results(results))
}

/// Fraction of cases malformed on either variant.
#[pyfunction]
fn malformed_rate(results: Vec<PyPerCaseResult>) -> f64 {
    metrics::malformed_rate(&to_core_results(results))
}

/// Expected calibration error over `bins` equal-width bins.
#[pyfunction]
#[pyo3(signature = (probs, labels, bins=15))]
fn ece(probs: Vec<f64>, labels: Vec<i64>, bins: usize) -> f64 {
    metrics::ece(&probs, &labels, bins)
}

/// Mean squared error of predicted probabilities.
#[pyfunction]
fn brier_score(probs: Vec<f64>, labels: Vec<i64>) -> f64 {
    metrics::brier_score(&probs, &labels)
}

/// McNemar's chi-square statistic for paired disagreements (b, c).
#[pyfunction]
fn mcnemar(b: u64, c: u64) -> f64 {
    metrics::mcnemar(b, c)
}

/// 95% bootstrap CI for mean(xs) - mean(ys), paired resampling.
///
/// Exposed but not auto-dispatched by the Python side: the Rust core uses
/// SplitMix64 where the Python reference uses Mersenne Twister, so draws
/// are not bit-identical (same statistic, different stream).
#[pyfunction]
#[pyo3(signature = (xs, ys, n_boot=2000, seed=0))]
fn paired_bootstrap_ci(xs: Vec<f64>, ys: Vec<f64>, n_boot: usize, seed: u64) -> (f64, f64) {
    metrics::paired_bootstrap_ci(&xs, &ys, n_boot, seed)
}

/// Eligible-case counts per family (required families default to 0).
#[pyfunction]
#[pyo3(signature = (results, required_families=None))]
fn n_eligible_by_family(
    results: Vec<PyPerCaseResult>,
    required_families: Option<Vec<String>>,
) -> std::collections::BTreeMap<String, usize> {
    metrics::n_eligible_by_family(&to_core_results(results), required_families.as_deref())
}

/// Ranking eligibility: (eligible, reasons). Reasons are empty when eligible.
#[pyfunction]
#[pyo3(signature = (results, required_families=None))]
fn check_eligibility(
    results: Vec<PyPerCaseResult>,
    required_families: Option<Vec<String>>,
) -> (bool, Vec<String>) {
    let e = metrics::check_eligibility(&to_core_results(results), required_families.as_deref());
    (e.eligible, e.reasons)
}

/// Canonical JSON: byte-identical to Python's `json.dumps(sort_keys=True)`.
#[pyfunction]
fn canonical_json(obj: &Bound<'_, PyAny>) -> PyResult<String> {
    Ok(canonical::to_canonical(&value_from_py(obj)?))
}

/// Pretty canonical JSON: byte-identical to the artifact `to_json` form.
#[pyfunction]
fn canonical_pretty(obj: &Bound<'_, PyAny>) -> PyResult<String> {
    Ok(canonical::to_pretty(&value_from_py(obj)?))
}

/// peira._core: the compiled Rust core (PyO3). Optional accelerator —
/// every function here has a pure-Python twin of identical behavior.
#[pymodule]
fn _core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(version, m)?)?;
    m.add_function(wrap_pyfunction!(validate_case_dict, m)?)?;
    m.add_function(wrap_pyfunction!(wilson_ci, m)?)?;
    m.add_function(wrap_pyfunction!(asr_conditional, m)?)?;
    m.add_function(wrap_pyfunction!(benign_accuracy, m)?)?;
    m.add_function(wrap_pyfunction!(targeted_attack_success, m)?)?;
    m.add_function(wrap_pyfunction!(malformed_rate, m)?)?;
    m.add_function(wrap_pyfunction!(ece, m)?)?;
    m.add_function(wrap_pyfunction!(brier_score, m)?)?;
    m.add_function(wrap_pyfunction!(mcnemar, m)?)?;
    m.add_function(wrap_pyfunction!(paired_bootstrap_ci, m)?)?;
    m.add_function(wrap_pyfunction!(n_eligible_by_family, m)?)?;
    m.add_function(wrap_pyfunction!(check_eligibility, m)?)?;
    m.add_function(wrap_pyfunction!(canonical_json, m)?)?;
    m.add_function(wrap_pyfunction!(canonical_pretty, m)?)?;
    Ok(())
}
