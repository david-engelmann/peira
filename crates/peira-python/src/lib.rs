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
//! - Float aggregates can differ from the reference by ~1 ulp: the
//!   reference sums with Python's compensated `sum()` (Neumaier, same as
//!   `math.fsum`) while the Rust core accumulates naively left-to-right,
//!   and the reference computes `** 2` through CPython's C `pow()` where
//!   the Rust core uses `.powi(2)` (exact multiplication). Immaterial
//!   after the 4-decimal rounding applied before anything is reported.
//! - Values that have no JSON representation (non-finite floats, integers
//!   wider than u64, non-string dict keys) raise `TypeError`/`ValueError`;
//!   the Python wrappers catch those and fall back to pure Python.

use peira_core::{canonical, compare, gates, metrics, schema};
use pyo3::exceptions::{PyTypeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyBool, PyDict, PyFloat, PyInt, PyList, PyString, PyTuple};
use serde_json::{Number, Value};
use std::collections::BTreeMap;

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

/// Mirror of the Python `CallUsage` dataclass, field-for-field.
#[derive(FromPyObject)]
struct PyCallUsage {
    model: String,
    tokens_in: i64,
    tokens_out: i64,
    latency_ms: f64,
    cost_usd: f64,
}

impl From<PyCallUsage> for metrics::CallUsage {
    fn from(u: PyCallUsage) -> Self {
        metrics::CallUsage {
            model: u.model,
            tokens_in: u.tokens_in,
            tokens_out: u.tokens_out,
            latency_ms: u.latency_ms,
            cost_usd: u.cost_usd,
        }
    }
}

/// Mirror of the Python `CallRecord` dataclass, field-for-field.
/// Extracted from any Python object carrying those attributes.
#[derive(FromPyObject)]
struct PyCallRecord {
    decision: String,
    confidence: Option<f64>,
    abstained: bool,
    refusal_reason: String,
    usage: Option<PyCallUsage>,
    seed: i64,
    dispatch_index: i64,
    malformed: bool,
    dispatch_limit: i64,
    score: Option<f64>,
}

impl From<PyCallRecord> for metrics::CallRecord {
    fn from(r: PyCallRecord) -> Self {
        metrics::CallRecord {
            decision: r.decision,
            confidence: r.confidence,
            abstained: r.abstained,
            refusal_reason: r.refusal_reason,
            usage: r.usage.map(metrics::CallUsage::from),
            seed: r.seed,
            dispatch_index: r.dispatch_index,
            malformed: r.malformed,
            dispatch_limit: r.dispatch_limit,
            score: r.score,
        }
    }
}

/// Mirror of the Python `PerCaseResult` dataclass, field-for-field.
#[derive(FromPyObject)]
struct PyPerCaseResult {
    case_id: String,
    family: String,
    severity: String,
    primitive: String,
    benign: PyCallRecord,
    attacked: PyCallRecord,
    flipped: bool,
    eligible: bool,
    ineligibility_reason: String,
}

impl From<PyPerCaseResult> for metrics::PerCaseResult {
    fn from(r: PyPerCaseResult) -> Self {
        metrics::PerCaseResult {
            case_id: r.case_id,
            family: r.family,
            severity: r.severity,
            primitive: r.primitive,
            benign: metrics::CallRecord::from(r.benign),
            attacked: metrics::CallRecord::from(r.attacked),
            flipped: r.flipped,
            eligible: r.eligible,
            ineligibility_reason: r.ineligibility_reason,
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

/// Conditional ASR: flips among eligible attacked cases, with Wilson CI.
#[pyfunction]
fn asr_conditional(results: Vec<PyPerCaseResult>) -> (f64, (f64, f64)) {
    metrics::asr_conditional(&to_core_results(results))
}

/// Benign accuracy with Wilson CI.
#[pyfunction]
fn benign_accuracy(results: Vec<PyPerCaseResult>) -> (f64, (f64, f64)) {
    metrics::benign_accuracy(&to_core_results(results))
}

/// Attacked-variant refusal rate with Wilson 95% CI.
#[pyfunction]
fn refusal_rate(results: Vec<PyPerCaseResult>) -> (f64, (f64, f64)) {
    metrics::refusal_rate(&to_core_results(results))
}

/// Attacked-variant refusal rate per family, as a dict.
#[pyfunction]
fn refusal_rate_by_family(results: Vec<PyPerCaseResult>) -> BTreeMap<String, f64> {
    metrics::refusal_rate_by_family(&to_core_results(results))
}

/// Ineligible-case counts by reason, as a dict.
#[pyfunction]
fn ineligible_by_reason(results: Vec<PyPerCaseResult>) -> BTreeMap<String, u64> {
    metrics::ineligible_by_reason(&to_core_results(results))
}

/// Fraction of cases malformed on either variant.
#[pyfunction]
fn malformed_rate(results: Vec<PyPerCaseResult>) -> f64 {
    metrics::malformed_rate(&to_core_results(results))
}

/// Expected calibration error with equal-mass bins.
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

/// Mean absolute error between point scores and author references:
/// the degenerate CRPS for deterministic forecasts.
#[pyfunction]
fn crps_point(scores: Vec<f64>, refs: Vec<f64>) -> f64 {
    metrics::crps_point(&scores, &refs)
}

/// How much of the 0..1 scale the scores use: 1 - 12*Var, clipped.
#[pyfunction]
fn score_compression_index(scores: Vec<f64>) -> f64 {
    metrics::score_compression_index(&scores)
}

/// McNemar's chi-square statistic for paired disagreements (b, c).
#[pyfunction]
fn mcnemar(b: u64, c: u64) -> f64 {
    metrics::mcnemar(b, c)
}

/// Davidson Bradley-Terry strengths: monotone MM fit over aggregated
/// pair counts.
///
/// `pairs` holds `(i, j, w_ij, w_ji, t_ij)` with `i < j`; returns
/// `(centered log-strengths, nu)`. Compare-view only, display-only —
/// never a ranker. Panics (the Python side raises `ValueError` before
/// dispatch) on empty input, bad indices, non-positive or non-finite
/// `max_iter`/`tol`, when an item never won-or-tied or never
/// lost-or-tied (per-item backstop), and when a group won every
/// cross-group comparison outright (exact Ford strong-connectivity
/// check — asserted in both backends, D-11).
#[pyfunction]
#[pyo3(signature = (n_items, pairs, max_iter=1000, tol=1e-10))]
fn bradley_terry_fit(
    n_items: usize,
    pairs: Vec<(usize, usize, u64, u64, u64)>,
    max_iter: usize,
    tol: f64,
) -> (Vec<f64>, f64) {
    metrics::bradley_terry_fit(n_items, &pairs, max_iter, tol)
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
) -> BTreeMap<String, usize> {
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

/// Holm step-down adjusted p-values, in the input order.
///
/// Panics (D-11) on empty input, out-of-[0, 1] values, or bad alpha —
/// the Python side validates before dispatch and raises ValueError.
#[pyfunction]
#[pyo3(signature = (p_values, alpha=0.05))]
fn holm_adjust(p_values: Vec<f64>, alpha: f64) -> Vec<f64> {
    metrics::holm_adjust(&p_values, alpha)
}

/// Bonferroni adjusted p-values (min(1, m*p)), in the input order.
#[pyfunction]
fn bonferroni_adjust(p_values: Vec<f64>) -> Vec<f64> {
    metrics::bonferroni_adjust(&p_values)
}

/// Indices of adjusted p-values rejected at level alpha.
#[pyfunction]
#[pyo3(signature = (adjusted, alpha=0.05))]
fn reject_at(adjusted: Vec<f64>, alpha: f64) -> Vec<usize> {
    metrics::reject_at(&adjusted, alpha)
}

/// Selective-classification risk-coverage curve: Vec of (coverage, risk).
#[pyfunction]
fn risk_coverage_curve(probs: Vec<f64>, labels: Vec<i64>) -> Vec<(f64, f64)> {
    metrics::risk_coverage_curve(&probs, &labels)
}

/// Selective risk at one fixed coverage in (0, 1].
#[pyfunction]
fn selective_risk_at_coverage(probs: Vec<f64>, labels: Vec<i64>, coverage: f64) -> f64 {
    metrics::selective_risk_at_coverage(&probs, &labels, coverage)
}

/// Area Under the Generalized Risk Coverage curve.
#[pyfunction]
fn augrc(probs: Vec<f64>, labels: Vec<i64>) -> f64 {
    metrics::augrc(&probs, &labels)
}

/// Murphy decomposition: (reliability, resolution, uncertainty, residual).
#[pyfunction]
#[pyo3(signature = (probs, labels, bins=15))]
fn murphy_decomposition(probs: Vec<f64>, labels: Vec<i64>, bins: usize) -> (f64, f64, f64, f64) {
    metrics::murphy_decomposition(&probs, &labels, bins)
}

/// Benign-variant refusal rate with Wilson 95% CI.
#[pyfunction]
fn benign_refusal_rate(results: Vec<PyPerCaseResult>) -> (f64, (f64, f64)) {
    metrics::benign_refusal_rate(&to_core_results(results))
}

/// Per-arm outcome census: (benign, attacked), each as
/// (n, approve, deny, other, refused, abstained, malformed).
#[pyfunction]
fn outcome_accounting(results: Vec<PyPerCaseResult>) -> (ArmCensus, ArmCensus) {
    let (b, a) = metrics::outcome_accounting(&to_core_results(results));
    let pack = |o: metrics::ArmOutcomes| {
        (
            o.n,
            o.approve,
            o.deny,
            o.other,
            o.refused,
            o.abstained,
            o.malformed,
        )
    };
    (pack(b), pack(a))
}

/// (confidences, correctness labels) for calibration over eligible cases.
#[pyfunction]
fn eligible_confidence_pairs(results: Vec<PyPerCaseResult>) -> (Vec<f64>, Vec<i64>) {
    metrics::eligible_confidence_pairs(&to_core_results(results))
}

/// (confidences, correctness labels) for attacked-arm calibration.
#[pyfunction]
fn attacked_confidence_pairs(results: Vec<PyPerCaseResult>) -> (Vec<f64>, Vec<i64>) {
    metrics::attacked_confidence_pairs(&to_core_results(results))
}

/// Fraction of cases with a reported confidence: (benign, attacked).
#[pyfunction]
fn confidence_coverage(results: Vec<PyPerCaseResult>) -> (f64, f64) {
    metrics::confidence_coverage(&to_core_results(results))
}

/// Severity-weighted attack success rate over eligible cases.
#[pyfunction]
fn severity_weighted_asr(results: Vec<PyPerCaseResult>) -> f64 {
    metrics::severity_weighted_asr(&to_core_results(results))
}

/// Per-arm outcome census, packed as (n, approve, deny, other, refused, abstained, malformed).
type ArmCensus = (usize, u64, u64, u64, u64, u64, u64);

/// McNemar test result, packed as (b, c, n_pairs, statistic, p_value, winner).
type McNemarPacked = (u64, u64, usize, f64, f64, Option<String>);

/// Mirror of the Python `PairedCase` dataclass in `peira.compare`.
#[derive(FromPyObject)]
struct PyPairedCase {
    case_id: String,
    family: String,
    primitive: String,
    a: PyPerCaseResult,
    b: PyPerCaseResult,
}

impl From<PyPairedCase> for compare::PairedCase {
    fn from(p: PyPairedCase) -> Self {
        compare::PairedCase {
            case_id: p.case_id,
            family: p.family,
            primitive: p.primitive,
            a: metrics::PerCaseResult::from(p.a),
            b: metrics::PerCaseResult::from(p.b),
        }
    }
}

fn to_core_pairs(pairs: Vec<PyPairedCase>) -> Vec<compare::PairedCase> {
    pairs.into_iter().map(compare::PairedCase::from).collect()
}

/// Whether the adapter handled this case correctly (eligible and not flipped).
#[pyfunction]
fn compare_case_ok(r: PyPerCaseResult) -> bool {
    compare::case_ok(&metrics::PerCaseResult::from(r))
}

/// Survival function of chi-square with 1 degree of freedom.
#[pyfunction]
fn compare_chi2_sf_1df(stat: f64) -> f64 {
    compare::chi2_sf_1df(stat)
}

/// Fourfold head-to-head counts: (n, both_right, a_only, b_only, both_wrong).
#[pyfunction]
fn compare_head_to_head(pairs: Vec<PyPairedCase>) -> (usize, u64, u64, u64, u64) {
    let h = compare::head_to_head(&to_core_pairs(pairs));
    (h.n, h.both_right, h.a_only, h.b_only, h.both_wrong)
}

/// Per-family head-to-head counts as a dict of (n, both_right, a_only, b_only, both_wrong).
#[pyfunction]
fn compare_per_family(pairs: Vec<PyPairedCase>) -> BTreeMap<String, (usize, u64, u64, u64, u64)> {
    compare::per_family(&to_core_pairs(pairs))
        .into_iter()
        .map(|(fam, h)| (fam, (h.n, h.both_right, h.a_only, h.b_only, h.both_wrong)))
        .collect()
}

/// McNemar's test over paired choice-primitive cases.
///
/// Returns (result, note) where result is None when there are no
/// choice-primitive pairs, else (b, c, n_pairs, statistic, p_value, winner).
#[pyfunction]
fn compare_mcnemar_test(pairs: Vec<PyPairedCase>) -> (Option<McNemarPacked>, String) {
    let (res, note) = compare::mcnemar_test(&to_core_pairs(pairs));
    let packed = res.map(|m| (m.b, m.c, m.n_pairs, m.statistic, m.p_value, m.winner));
    (packed, note)
}

/// Total measured cost for one case (both arms), or None if unpriced.
#[pyfunction]
fn compare_per_case_cost(r: PyPerCaseResult) -> Option<f64> {
    compare::per_case_cost(&metrics::PerCaseResult::from(r))
}

/// Total measured latency for one case (both arms), or None if missing.
#[pyfunction]
fn compare_per_case_latency(r: PyPerCaseResult) -> Option<f64> {
    compare::per_case_latency(&metrics::PerCaseResult::from(r))
}

/// Mirror of the Python `GateCase` tuple: (path_name, lineno, case_dict).
/// Accepts a Python tuple of (str, int, dict).
#[derive(FromPyObject)]
struct PyGateCase<'a>(String, usize, Bound<'a, PyAny>);

impl<'a> PyGateCase<'a> {
    fn to_core(&self) -> PyResult<gates::GateCase> {
        // D-11: fail loudly on non-dict cases. Python raises TypeError;
        // the dispatch except falls back to Python, which raises loudly.
        if self.2.cast::<PyDict>().is_err() {
            return Err(PyTypeError::new_err(
                "gate case must be a dict",
            ));
        }
        Ok(gates::GateCase {
            path_name: self.0.clone(),
            lineno: self.1,
            case: value_from_py(&self.2)?,
        })
    }
}

fn to_core_gate_cases(cases: Vec<PyGateCase>) -> PyResult<Vec<gates::GateCase>> {
    cases.iter().map(|c| c.to_core()).collect()
}

/// Gate result, packed as (gate_id, name, errors, warnings).
type GatePacked = (String, String, Vec<String>, Vec<String>);

fn pack_gate_result(r: gates::GateResult) -> GatePacked {
    (r.gate_id, r.name, r.errors, r.warnings)
}

/// G2: the attacked variant actually differs from its benign control.
#[pyfunction]
fn gates_paired_variants(cases: Vec<PyGateCase>) -> PyResult<GatePacked> {
    Ok(pack_gate_result(gates::gate_paired_variants(
        &to_core_gate_cases(cases)?,
    )))
}

/// G3: case ids are unique; no two cases share a content pair.
#[pyfunction]
fn gates_dedup(cases: Vec<PyGateCase>) -> PyResult<GatePacked> {
    Ok(pack_gate_result(gates::gate_dedup(&to_core_gate_cases(
        cases,
    )?)))
}

/// G4: every case uses a canonical attack-family id.
#[pyfunction]
fn gates_families(cases: Vec<PyGateCase>, canonical_families: Vec<String>) -> PyResult<GatePacked> {
    Ok(pack_gate_result(gates::gate_families(
        &to_core_gate_cases(cases)?,
        &canonical_families,
    )))
}

/// G5: a named target decision must differ from the benign expectation.
#[pyfunction]
fn gates_target_coherence(cases: Vec<PyGateCase>) -> PyResult<GatePacked> {
    Ok(pack_gate_result(gates::gate_target_coherence(
        &to_core_gate_cases(cases)?,
    )))
}

/// G6: flag identifier-like strings in case inputs (warnings, not errors).
#[pyfunction]
fn gates_pii_scan(cases: Vec<PyGateCase>) -> PyResult<GatePacked> {
    Ok(pack_gate_result(gates::gate_pii_scan(&to_core_gate_cases(
        cases,
    )?)))
}

/// G7: score-primitive cases carry the author's reference score.
#[pyfunction]
fn gates_score_reference(cases: Vec<PyGateCase>) -> PyResult<GatePacked> {
    Ok(pack_gate_result(gates::gate_score_reference(
        &to_core_gate_cases(cases)?,
    )))
}

/// G8: options lists are canonical across both variants.
#[pyfunction]
fn gates_options_coherence(cases: Vec<PyGateCase>) -> PyResult<GatePacked> {
    Ok(pack_gate_result(gates::gate_options_coherence(
        &to_core_gate_cases(cases)?,
    )))
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
    m.add_function(wrap_pyfunction!(refusal_rate, m)?)?;
    m.add_function(wrap_pyfunction!(refusal_rate_by_family, m)?)?;
    m.add_function(wrap_pyfunction!(ineligible_by_reason, m)?)?;
    m.add_function(wrap_pyfunction!(malformed_rate, m)?)?;
    m.add_function(wrap_pyfunction!(ece, m)?)?;
    m.add_function(wrap_pyfunction!(brier_score, m)?)?;
    m.add_function(wrap_pyfunction!(crps_point, m)?)?;
    m.add_function(wrap_pyfunction!(score_compression_index, m)?)?;
    m.add_function(wrap_pyfunction!(mcnemar, m)?)?;
    m.add_function(wrap_pyfunction!(bradley_terry_fit, m)?)?;
    m.add_function(wrap_pyfunction!(paired_bootstrap_ci, m)?)?;
    m.add_function(wrap_pyfunction!(n_eligible_by_family, m)?)?;
    m.add_function(wrap_pyfunction!(check_eligibility, m)?)?;
    m.add_function(wrap_pyfunction!(holm_adjust, m)?)?;
    m.add_function(wrap_pyfunction!(bonferroni_adjust, m)?)?;
    m.add_function(wrap_pyfunction!(reject_at, m)?)?;
    m.add_function(wrap_pyfunction!(risk_coverage_curve, m)?)?;
    m.add_function(wrap_pyfunction!(selective_risk_at_coverage, m)?)?;
    m.add_function(wrap_pyfunction!(augrc, m)?)?;
    m.add_function(wrap_pyfunction!(murphy_decomposition, m)?)?;
    m.add_function(wrap_pyfunction!(benign_refusal_rate, m)?)?;
    m.add_function(wrap_pyfunction!(outcome_accounting, m)?)?;
    m.add_function(wrap_pyfunction!(eligible_confidence_pairs, m)?)?;
    m.add_function(wrap_pyfunction!(attacked_confidence_pairs, m)?)?;
    m.add_function(wrap_pyfunction!(confidence_coverage, m)?)?;
    m.add_function(wrap_pyfunction!(severity_weighted_asr, m)?)?;
    m.add_function(wrap_pyfunction!(compare_case_ok, m)?)?;
    m.add_function(wrap_pyfunction!(compare_chi2_sf_1df, m)?)?;
    m.add_function(wrap_pyfunction!(compare_head_to_head, m)?)?;
    m.add_function(wrap_pyfunction!(compare_per_family, m)?)?;
    m.add_function(wrap_pyfunction!(compare_mcnemar_test, m)?)?;
    m.add_function(wrap_pyfunction!(compare_per_case_cost, m)?)?;
    m.add_function(wrap_pyfunction!(compare_per_case_latency, m)?)?;
    m.add_function(wrap_pyfunction!(gates_paired_variants, m)?)?;
    m.add_function(wrap_pyfunction!(gates_dedup, m)?)?;
    m.add_function(wrap_pyfunction!(gates_families, m)?)?;
    m.add_function(wrap_pyfunction!(gates_target_coherence, m)?)?;
    m.add_function(wrap_pyfunction!(gates_pii_scan, m)?)?;
    m.add_function(wrap_pyfunction!(gates_score_reference, m)?)?;
    m.add_function(wrap_pyfunction!(gates_options_coherence, m)?)?;
    m.add_function(wrap_pyfunction!(canonical_json, m)?)?;
    m.add_function(wrap_pyfunction!(canonical_pretty, m)?)?;
    Ok(())
}
