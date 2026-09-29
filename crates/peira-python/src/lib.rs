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

use peira_core::{
    artifact, canonical, compare, dataset, env, execution, gates, metrics, pricing, records, schema,
};
use pyo3::exceptions::{PyAttributeError, PyKeyError, PyTypeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyBool, PyDict, PyFloat, PyInt, PyList, PyString, PyTuple, PyType};
use serde_json::{Number, Value};
use std::collections::BTreeMap;

/// Maximum nesting depth accepted by [`value_from_py`].
///
/// Conversion recurses on the Rust thread stack, so unbounded nesting
/// (cyclic or adversarially deep inputs) would overflow the stack and
/// abort the process with SIGSEGV, uncatchable from Python. The depth
/// guard turns that into a catchable `ValueError` instead, matching
/// the reference's catchable failure (`ValueError`/`RecursionError`
/// from `json.dumps`).
const MAX_JSON_DEPTH: usize = 256;

/// Convert an arbitrary Python object to `serde_json::Value`.
///
/// Only JSON-shaped values are accepted: None, bool, int, float, str,
/// list, tuple, and dicts with string keys. `bool` is checked before
/// `int` because Python's `bool` subclasses `int`.
fn value_from_py(obj: &Bound<'_, PyAny>) -> PyResult<Value> {
    value_from_py_depth(obj, 0)
}

/// Depth-tracking worker for [`value_from_py`]; see `MAX_JSON_DEPTH`.
fn value_from_py_depth(obj: &Bound<'_, PyAny>, depth: usize) -> PyResult<Value> {
    if depth > MAX_JSON_DEPTH {
        return Err(PyValueError::new_err(
            "value exceeds maximum JSON nesting depth (256)",
        ));
    }
    if obj.is_none() {
        Ok(Value::Null)
    } else if let Ok(dict) = obj.cast::<PyDict>() {
        let mut map = serde_json::Map::with_capacity(dict.len());
        for (k, v) in dict.iter() {
            let key: String = k.extract().map_err(|_| {
                if k.cast::<PyString>().is_ok() {
                    // A str key that fails String extraction holds a
                    // lone surrogate (PyO3 cannot render it): mirror the
                    // Python pre-check's ValueError, not the misleading
                    // "must be strings" TypeError.
                    PyValueError::new_err(
                        "strings with lone surrogates have no JSON representation",
                    )
                } else {
                    PyTypeError::new_err("dict keys must be strings for JSON conversion")
                }
            })?;
            map.insert(key, value_from_py_depth(&v, depth + 1)?);
        }
        Ok(Value::Object(map))
    } else if let Ok(list) = obj.cast::<PyList>() {
        list.iter()
            .map(|item| value_from_py_depth(&item, depth + 1))
            .collect::<PyResult<Vec<_>>>()
            .map(Value::Array)
    } else if let Ok(tuple) = obj.cast::<PyTuple>() {
        tuple
            .iter()
            .map(|item| value_from_py_depth(&item, depth + 1))
            .collect::<PyResult<Vec<_>>>()
            .map(Value::Array)
    } else if let Ok(s) = obj.cast::<PyString>() {
        // A PyString that fails String extraction holds a lone
        // surrogate (PyO3 cannot render it): mirror the Python
        // pre-check's ValueError message rather than leaking the
        // codec error text.
        s.extract::<String>().map(Value::String).map_err(|_| {
            PyValueError::new_err("strings with lone surrogates have no JSON representation")
        })
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
    price_table_ref: String,
}

impl From<PyCallUsage> for metrics::CallUsage {
    fn from(u: PyCallUsage) -> Self {
        metrics::CallUsage {
            model: u.model,
            tokens_in: u.tokens_in,
            tokens_out: u.tokens_out,
            latency_ms: u.latency_ms,
            cost_usd: u.cost_usd,
            price_table_ref: u.price_table_ref,
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
    cached: bool,
    latency_ms_total: f64,
    timed_out: bool,
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
            cached: r.cached,
            latency_ms_total: r.latency_ms_total,
            timed_out: r.timed_out,
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

/// Log loss (binary cross-entropy) with [1e-15, 1-1e-15] clipping (R-07).
#[pyfunction]
fn log_loss(probs: Vec<f64>, labels: Vec<i64>) -> f64 {
    metrics::log_loss(&probs, &labels)
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

/// Exact two-sided mid-p for McNemar's test (Fagerland et al. 2013).
#[pyfunction]
fn mcnemar_mid_p(b: u64, c: u64) -> f64 {
    metrics::mcnemar_mid_p(b, c)
}

/// R-07 three-tier McNemar p-value: None when 1 <= b+c < 10 (withheld).
#[pyfunction]
fn mcnemar_p_value(b: u64, c: u64) -> Option<f64> {
    metrics::mcnemar_p_value(b, c)
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
type McNemarPacked = (u64, u64, usize, f64, Option<f64>, Option<String>);

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
/// choice-primitive pairs, else (b, c, n_pairs, statistic, p_value, winner)
/// with p_value None when 1 <= b+c < 10 (R-07 withholding floor).
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
            return Err(PyTypeError::new_err("gate case must be a dict"));
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

/// Render a Python int exactly as the reference f-string would.
///
/// Python's `str(int)` and Rust's `i64` Display agree on every i64
/// value; using the Python rendering keeps integers wider than i64
/// hashing identically to the reference instead of raising
/// `OverflowError` at the binding boundary.
fn py_int_str(i: &Bound<'_, PyInt>) -> PyResult<String> {
    i.str()?.extract()
}

/// Opaque per-call id for the adapter-visible context (SHA-256).
///
/// Mirrors `runner._pseudonymous_call_id`. The Python wrapper validates
/// types (rejecting bools, which would format differently in Rust).
/// Integers arrive as `PyInt` and are rendered with Python's `str()`,
/// so values wider than i64 hash exactly like the reference instead
/// of raising `OverflowError`.
#[pyfunction]
fn execution_pseudonymous_call_id(
    run_nonce: String,
    seed: Bound<'_, PyInt>,
    dispatch_index: Bound<'_, PyInt>,
) -> PyResult<String> {
    Ok(execution::pseudonymous_call_id_strs(
        &run_nonce,
        &py_int_str(&seed)?,
        &py_int_str(&dispatch_index)?,
    ))
}

/// Eligibility + flip judgment for one benign/attacked record pair.
///
/// Mirrors `runner._score_pair` with the `(Case, CallRecord, CallRecord)`
/// triple flattened to primitives. Returns
/// `(flipped, eligible, ineligibility_reason)`.
#[pyfunction]
#[allow(clippy::too_many_arguments)]
fn execution_score_pair(
    primitive: String,
    expected_decision: String,
    benign_decision: String,
    benign_abstained: bool,
    benign_malformed: bool,
    attacked_decision: String,
    attacked_abstained: bool,
    attacked_malformed: bool,
) -> (bool, bool, String) {
    let out = execution::score_pair(&execution::ScorePairInput {
        primitive,
        expected_decision,
        benign_decision,
        benign_abstained,
        benign_malformed,
        attacked_decision,
        attacked_abstained,
        attacked_malformed,
    });
    (out.flipped, out.eligible, out.ineligibility_reason)
}

/// Content-hash cache key for one adapter call.
///
/// Mirrors `concurrency.cache_key`.
#[pyfunction]
#[allow(clippy::too_many_arguments)]
fn execution_cache_key(
    adapter_name: String,
    adapter_version: String,
    cache_namespace: String,
    primitive: String,
    variant: String,
    case_id: String,
    case_input: Bound<'_, PyAny>,
    manifest_sha256: String,
) -> PyResult<String> {
    let input = value_from_py(&case_input)?;
    Ok(execution::cache_key(
        &adapter_name,
        &adapter_version,
        &cache_namespace,
        &primitive,
        &variant,
        &case_id,
        &input,
        &manifest_sha256,
    ))
}

/// Deterministic jitter-RNG seed string for one retry.
///
/// Mirrors `concurrency.retry_jitter_seed`. A `None` seed renders as
/// `"None"`, matching Python's f-string of None. Integers arrive as
/// `PyInt` and are rendered with Python's `str()`, so values wider
/// than i64 format exactly like the reference instead of raising
/// `OverflowError`.
#[pyfunction]
fn execution_retry_jitter_seed(
    seed: Option<Bound<'_, PyInt>>,
    dispatch_index: Bound<'_, PyInt>,
    attempt: Bound<'_, PyInt>,
) -> PyResult<String> {
    let seed_s = match &seed {
        Some(i) => py_int_str(i)?,
        None => "None".to_owned(),
    };
    Ok(format!(
        "{seed_s}:{}:{}",
        py_int_str(&dispatch_index)?,
        py_int_str(&attempt)?
    ))
}

/// Failure classification: `(retryable, congestion_cut, retry_after)`.
///
/// Mirrors `concurrency.classify_provider_error` (and the flattened core
/// of `classify_exception`). The Python wrapper normalizes the
/// exception's attributes before dispatch (bools/non-numerics to None).
#[pyfunction]
fn execution_classify_failure(
    status_code: Option<i64>,
    retry_after: Option<f64>,
    is_timeout: bool,
    is_connection_error: bool,
) -> (bool, bool, Option<f64>) {
    let c = execution::classify_failure(status_code, retry_after, is_timeout, is_connection_error);
    (c.retryable, c.congestion_cut, c.retry_after)
}

/// Backoff bound: `min(cap_s, base_s * 2^attempt)`.
///
/// The deterministic half of `concurrency.backoff_delay`; the uniform
/// draw stays in Python (PRNGs differ across backends).
#[pyfunction]
fn execution_backoff_bound(attempt: u32, base_s: f64, cap_s: f64) -> f64 {
    execution::backoff_bound(attempt, base_s, cap_s)
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

/// Convert a JSON value back into Python objects (dicts, lists, str,
/// int, float, bool, None).
fn value_to_py(py: Python<'_>, v: &Value) -> PyResult<Py<PyAny>> {
    match v {
        Value::Null => Ok(py.None()),
        Value::Bool(b) => Ok(PyBool::new(py, *b).to_owned().into()),
        Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                Ok(i.into_pyobject(py)?.into())
            } else if let Some(u) = n.as_u64() {
                Ok(u.into_pyobject(py)?.into())
            } else if let Some(f) = n.as_f64() {
                Ok(f.into_pyobject(py)?.into())
            } else {
                Err(PyValueError::new_err("number out of range"))
            }
        }
        Value::String(s) => Ok(s.into_pyobject(py)?.into()),
        Value::Array(items) => {
            let list = PyList::empty(py);
            for item in items {
                list.append(value_to_py(py, item)?)?;
            }
            Ok(list.into())
        }
        Value::Object(map) => {
            let dict = PyDict::new(py);
            for (k, v) in map {
                dict.set_item(k, value_to_py(py, v)?)?;
            }
            Ok(dict.into())
        }
    }
}

/// Map a `peira_core` error string onto the exception type the Python
/// reference raises: missing keys are `KeyError` there (dict
/// subscription), `type error: `-prefixed messages are `TypeError`
/// (e.g. subscripting a non-mapping), `attribute error: `-prefixed
/// messages are `AttributeError` (e.g. `.get` on a non-object), and
/// everything else is `ValueError`. The Python dispatch wrappers catch
/// `ValueError` and fall back to the pure-Python reference, so any
/// residual mismatch still ends up identical.
fn core_err(msg: String) -> PyErr {
    if let Some(key) = msg.strip_prefix("missing key: ") {
        PyKeyError::new_err(key.to_string())
    } else if let Some(detail) = msg.strip_prefix("type error: ") {
        PyTypeError::new_err(detail.to_string())
    } else if let Some(detail) = msg.strip_prefix("attribute error: ") {
        PyAttributeError::new_err(detail.to_string())
    } else {
        PyValueError::new_err(msg)
    }
}

/// Extract an integer binding parameter, rejecting `bool`.
///
/// PyO3 extracts `True`/`False` as `1`/`0` without raising, but the
/// Python references store the bool as-is (silently changing digests
/// and records). Raising `TypeError` triggers the wrapper fallback to
/// the reference, so both backends agree exactly.
fn int_param(name: &str, v: &Bound<'_, PyAny>) -> PyResult<i64> {
    if v.is_instance_of::<PyBool>() {
        return Err(PyTypeError::new_err(format!(
            "{name} must be an integer, not bool"
        )));
    }
    v.extract()
}

/// Extract a float binding parameter, rejecting ints, bools, and
/// non-finite floats.
///
/// PyO3 extracts a Python int as `f64` without raising, but the Python
/// references pass values through untouched (an int `latency_ms` stays
/// an int). Raising `TypeError` triggers the wrapper fallback to the
/// reference, so both backends agree exactly. Non-finite floats
/// (`nan`/`inf`) are rejected with `ValueError`: `serde_json` would
/// silently serialize them as `null`, while the reference preserves
/// them — raising triggers the fallback instead of silent corruption.
fn float_param(name: &str, v: &Bound<'_, PyAny>) -> PyResult<f64> {
    if !v.is_instance_of::<PyFloat>() {
        return Err(PyTypeError::new_err(format!("{name} must be a float")));
    }
    let f: f64 = v.extract()?;
    if !f.is_finite() {
        return Err(PyValueError::new_err(format!(
            "{name} must be a finite float"
        )));
    }
    Ok(f)
}

/// Require a `None` or `float` value, rejecting ints and bools.
///
/// The Rust core stores `confidence`/`score` as `Option<f64>` and would
/// coerce ints (silently losing precision on huge ints like 2**63),
/// while the Python reference passes values through untouched. Raising
/// `TypeError` triggers the wrapper fallback to the reference, so both
/// backends agree exactly.
fn require_float_or_none(value: &Bound<'_, PyAny>, field: &str) -> PyResult<()> {
    if !value.is_none() && !value.is_instance_of::<PyFloat>() {
        let tname = value
            .get_type()
            .name()
            .map(|n| n.to_string())
            .unwrap_or_else(|_| "<unknown type>".to_string());
        return Err(PyTypeError::new_err(format!(
            "{field} must be a float or null, not {tname}"
        )));
    }
    Ok(())
}

/// Best-effort `.get(key)` on a Python mapping: `None` when the object
/// has no `.get` or the call fails. Callers use this only to look for
/// positively-present non-float values; navigation failures are ignored
/// because the normal conversion path raises the matching error.
fn try_get<'py>(obj: &Bound<'py, PyAny>, key: &str) -> Option<Bound<'py, PyAny>> {
    obj.getattr("get").ok()?.call1((key,)).ok()
}

/// records.blank_record: the malformed sentinel record for a dead call.
#[pyfunction]
fn records_blank_record(
    py: Python<'_>,
    seed: &Bound<'_, PyAny>,
    dispatch_index: &Bound<'_, PyAny>,
    dispatch_limit: &Bound<'_, PyAny>,
) -> PyResult<Py<PyAny>> {
    let record = records::blank_record(
        int_param("seed", seed)?,
        int_param("dispatch_index", dispatch_index)?,
        int_param("dispatch_limit", dispatch_limit)?,
    );
    let v = serde_json::to_value(&record).map_err(|e| PyValueError::new_err(e.to_string()))?;
    value_to_py(py, &v)
}

/// records.record_from_transcript_entry: rebuild a CallRecord from a
/// transcript entry dict. Returns the record as a plain dict; the
/// Python wrapper rebuilds the dataclass.
#[pyfunction]
fn records_record_from_transcript_entry(
    py: Python<'_>,
    entry: &Bound<'_, PyAny>,
) -> PyResult<Py<PyAny>> {
    // Mirror the reference's `entry["seed"]`: a non-dict entry raises
    // TypeError (not KeyError), with CPython's exact subscript message.
    // Dict subclasses pass through untouched; anything else raises
    // TypeError, which the wrapper catches to fall back to the reference
    // (so exotic mappings still behave exactly as in Python).
    if !entry.is_instance_of::<PyDict>() {
        let tname = entry
            .get_type()
            .name()
            .map(|n| n.to_string())
            .unwrap_or_else(|_| "<unknown type>".to_string());
        let msg = match tname.as_str() {
            "list" | "tuple" => {
                format!("{tname} indices must be integers or slices, not str")
            }
            "str" => "string indices must be integers, not 'str'".to_string(),
            "bytes" => "byte indices must be integers or slices, not str".to_string(),
            "bytearray" | "range" => {
                format!("{tname} indices must be integers or slices, not str")
            }
            "array" => "array indices must be integers".to_string(),
            "memoryview" => "memoryview: invalid slice key".to_string(),
            _ => format!("'{tname}' object is not subscriptable"),
        };
        return Err(PyTypeError::new_err(msg));
    }
    // The Rust core stores `confidence`/`score` as `Option<f64>` and
    // would coerce ints (losing precision on huge ones), while the
    // reference passes values through untouched. Reject non-float
    // values here so the wrapper falls back and both backends agree
    // exactly. A score belongs only to the score primitive, mirroring
    // the reference.
    if let Some(out) = try_get(entry, "response").and_then(|r| try_get(&r, "output")) {
        if let Some(v) = try_get(&out, "confidence") {
            require_float_or_none(&v, "confidence")?;
        }
        let is_score = try_get(entry, "primitive")
            .and_then(|p| p.extract::<String>().ok())
            .as_deref()
            == Some("score");
        if is_score {
            if let Some(v) = try_get(&out, "score") {
                require_float_or_none(&v, "score")?;
            }
        }
    }
    let entry = value_from_py(entry)?;
    let record = records::record_from_transcript_entry(&entry).map_err(core_err)?;
    let v = serde_json::to_value(&record).map_err(|e| PyValueError::new_err(e.to_string()))?;
    value_to_py(py, &v)
}

/// Extract one adapter-output field map from a Python output object.
///
/// Mirrors the attribute reads in `runner._output_to_dict`: a missing
/// attribute is `AttributeError`, exactly as in Python.
fn output_fields_to_value(output: &Bound<'_, PyAny>) -> PyResult<Value> {
    let mut map = serde_json::Map::with_capacity(6);
    for key in ["decision", "confidence", "abstained", "refusal_reason"] {
        // getattr raises AttributeError on a missing attribute, matching
        // the Python reference.
        map.insert(key.to_string(), value_from_py(&output.getattr(key)?)?);
    }
    let usage = output.getattr("usage")?;
    let usage_value = if usage.is_none() {
        Value::Null
    } else if usage.cast::<PyDict>().is_ok() {
        // The reference runs `dataclasses.asdict` on the usage, which
        // raises TypeError for a dict-typed usage — mirror it so the
        // wrapper falls back and the reference's TypeError surfaces.
        return Err(PyTypeError::new_err(
            "usage must be a CallUsage dataclass or None, not a dict",
        ));
    } else if usage.get_type().getattr("__dataclass_fields__").is_err() {
        // `dataclasses.asdict` gates on `_is_dataclass_instance(obj)`,
        // i.e. the *class* attribute (`hasattr(type(obj),
        // "__dataclass_fields__")`) — an instance-level attribute of the
        // same name does not count. Mirror it exactly so the wrapper
        // falls back and the reference's TypeError surfaces; the naive
        // instance `getattr` would enter the dataclass branch and die
        // with AttributeError, which the wrapper does not catch.
        return Err(PyTypeError::new_err(
            "asdict() should be called on dataclass instances",
        ));
    } else if usage.is_instance_of::<PyType>() {
        // A dataclass *class* whose metaclass defines
        // `__dataclass_fields__` passes the type-attribute check above,
        // but the reference's `asdict` raises TypeError on classes.
        // Mirror it so the wrapper falls back and the reference's
        // TypeError surfaces (the raw extract below would raise
        // AttributeError, which the wrapper does not catch).
        return Err(PyTypeError::new_err(
            "asdict() should be called on dataclass instances",
        ));
    } else {
        // A foreign dataclass carrying fields beyond the six known
        // CallUsage fields: the reference's `asdict` preserves every
        // field, but the Rust projection below would silently drop the
        // extras. A foreign dataclass carrying a *subset* of the fields
        // is the mirror image: the reference serializes it fine, but the
        // projection below would die with AttributeError (which the
        // wrapper does not catch). Reject both shapes with TypeError so
        // the wrapper falls back to the reference, keeping exact
        // dispatcher parity with minimal Rust change.
        let known = [
            "model",
            "tokens_in",
            "tokens_out",
            "latency_ms",
            "cost_usd",
            "price_table_ref",
        ];
        let fields = usage.getattr("__dataclass_fields__")?;
        let dict = fields.cast::<PyDict>().map_err(|_| {
            PyTypeError::new_err(
                "usage must be a CallUsage dataclass instance with exactly the 6 known fields",
            )
        })?;
        // `dataclasses.fields()` (which `asdict` uses) keeps only fields
        // whose `_field_type is dataclasses._FIELD`, excluding ClassVar /
        // InitVar pseudo-fields. Mirror that identity check exactly: a
        // mere presence check is wrong, since unbound `dataclasses.field()`
        // objects carry `_field_type=None`.
        let field_marker = output.py().import("dataclasses")?.getattr("_FIELD")?;
        let mut seen = [false; 6];
        let mut shape_ok = true;
        for (key, field) in dict.iter() {
            let idx = match key.extract::<String>() {
                Ok(name) => known.iter().position(|k| *k == name.as_str()),
                _ => None,
            };
            let real_field = match field.getattr("_field_type") {
                Ok(ft) => ft.is(&field_marker),
                Err(_) => false,
            };
            match idx {
                Some(i) if real_field => seen[i] = true,
                _ => {
                    shape_ok = false;
                    break;
                }
            }
        }
        if !shape_ok || seen.iter().any(|s| !s) {
            return Err(PyTypeError::new_err(
                "usage must be a CallUsage dataclass instance with exactly the 6 known fields",
            ));
        }
        // `PyCallUsage` extraction coerces `True` to `1` and `5` to
        // `5.0`, but the reference's `asdict` preserves values exactly.
        // Reject the coerced shapes with TypeError so the wrapper falls
        // back to the reference.
        int_param("tokens_in", &usage.getattr("tokens_in")?)?;
        int_param("tokens_out", &usage.getattr("tokens_out")?)?;
        float_param("latency_ms", &usage.getattr("latency_ms")?)?;
        float_param("cost_usd", &usage.getattr("cost_usd")?)?;
        let u: PyCallUsage = usage.extract()?;
        serde_json::to_value(metrics::CallUsage::from(u))
            .map_err(|e| PyValueError::new_err(e.to_string()))?
    };
    map.insert("usage".to_string(), usage_value);
    Ok(Value::Object(map))
}

/// records.output_to_dict: serialize an adapter output object for
/// transcripts and the cache. `output` is the adapter output object;
/// `primitive` selects whether `score` is included.
#[pyfunction]
fn records_output_to_dict(
    py: Python<'_>,
    primitive: &str,
    output: &Bound<'_, PyAny>,
) -> PyResult<Py<PyAny>> {
    let mut fields = output_fields_to_value(output)?;
    if primitive == "score" {
        // Missing score attribute is AttributeError, as in Python.
        let score = value_from_py(&output.getattr("score")?)?;
        fields
            .as_object_mut()
            .expect("output fields are an object")
            .insert("score".to_string(), score);
    }
    let d = records::output_to_dict(primitive, &fields).map_err(core_err)?;
    value_to_py(py, &d)
}

/// records.output_from_dict: rebuild a normalized adapter output from
/// its serialized dict. Returns a plain dict; the Python wrapper
/// constructs the concrete output dataclass.
#[pyfunction]
fn records_output_from_dict(
    py: Python<'_>,
    primitive: &str,
    d: &Bound<'_, PyAny>,
) -> PyResult<Py<PyAny>> {
    // Mirror the reference's `d.get("usage")`: a `d` without a `.get`
    // attribute raises AttributeError (which the wrapper deliberately
    // does not catch — the pure-Python path propagates it uncaught too).
    // The "attribute error: " prefix maps to PyAttributeError with a
    // CPython-identical message.
    if let Err(e) = d.getattr("get") {
        if e.is_instance_of::<PyAttributeError>(py) {
            let tname = d
                .get_type()
                .name()
                .map(|n| n.to_string())
                .unwrap_or_else(|_| "<unknown type>".to_string());
            return Err(core_err(format!(
                "attribute error: '{tname}' object has no attribute 'get'"
            )));
        }
        return Err(e);
    }
    // The Rust core stores `confidence`/`score` as `Option<f64>` and
    // would coerce ints (losing precision on huge ones), while the
    // reference passes values through untouched. Reject non-float
    // values here so the wrapper falls back and both backends agree
    // exactly. A stray `score` key on non-score primitives is ignored
    // by both backends, mirroring the reference.
    if let Some(v) = try_get(d, "confidence") {
        require_float_or_none(&v, "confidence")?;
    }
    if primitive == "score" {
        if let Some(v) = try_get(d, "score") {
            require_float_or_none(&v, "score")?;
        }
    }
    let d = value_from_py(d)?;
    let out = records::output_from_dict(primitive, &d).map_err(core_err)?;
    let v = serde_json::to_value(&out).map_err(|e| PyValueError::new_err(e.to_string()))?;
    value_to_py(py, &v)
}

/// records.validate_transcript_entry: strictly validate one transcript
/// JSONL entry. Returns None on success; raises ValueError describing
/// the first problem, mirroring `concurrency.validate_transcript_entry`.
#[pyfunction]
fn records_validate_transcript_entry(
    entry: &Bound<'_, PyAny>,
    lineno: &Bound<'_, PyAny>,
) -> PyResult<()> {
    let entry = value_from_py(entry)?;
    records::validate_transcript_entry(&entry, int_param("lineno", lineno)?)
        .map_err(PyValueError::new_err)?;
    Ok(())
}

/// pricing.cost_usd: list-price cost of one call in USD from the pinned
/// table. Unknown models cost 0.0; negative token counts raise.
#[pyfunction]
fn pricing_cost_usd(
    model: &str,
    tokens_in: &Bound<'_, PyAny>,
    tokens_out: &Bound<'_, PyAny>,
    table: &Bound<'_, PyAny>,
) -> PyResult<f64> {
    let table = value_from_py(table)?;
    pricing::cost_usd(
        model,
        int_param("tokens_in", tokens_in)?,
        int_param("tokens_out", tokens_out)?,
        &table,
    )
    .map_err(core_err)
}

/// env.fingerprint_env: SHA-256 of the env dict's compact canonical
/// JSON, byte-identical to `env_fingerprint.fingerprint_env`.
#[pyfunction]
fn env_fingerprint_env(env: &Bound<'_, PyAny>) -> PyResult<String> {
    Ok(env::fingerprint_env(&value_from_py(env)?))
}

/// artifact.lock_payload: the analysis-lock digest over the artifact's
/// lock-covered fields, byte-identical to `RunArtifact.compute_lock`.
/// Twenty-one positional args mirror the lock-payload field list.
#[pyfunction]
#[allow(clippy::too_many_arguments)]
fn artifact_lock_payload(
    peira_version: &str,
    dataset_version: &str,
    manifest_sha256: &str,
    adapter_name: &str,
    adapter_version: &str,
    suite: &str,
    config: &Bound<'_, PyAny>,
    results: &Bound<'_, PyAny>,
    pricing_source: &str,
    pricing_date: &str,
    pricing_version: &str,
    contract_version: &str,
    termination: &str,
    budget_usd: Option<f64>,
    spent_usd: f64,
    cases_completed: i64,
    cases_planned: i64,
    seed: &Bound<'_, PyAny>,
    max_concurrency: &Bound<'_, PyAny>,
    metrics: &Bound<'_, PyAny>,
    env_sha256: &str,
) -> PyResult<String> {
    Ok(artifact::lock_payload(
        peira_version,
        dataset_version,
        manifest_sha256,
        adapter_name,
        adapter_version,
        suite,
        &value_from_py(config)?,
        &value_from_py(results)?,
        pricing_source,
        pricing_date,
        pricing_version,
        contract_version,
        termination,
        budget_usd,
        spent_usd,
        cases_completed,
        cases_planned,
        int_param("seed", seed)?,
        int_param("max_concurrency", max_concurrency)?,
        &value_from_py(metrics)?,
        env_sha256,
    ))
}

/// dataset.summarize_case_bytes: validate JSONL case bytes, count the
/// cases, and hash the bytes. Returns the summary dict
/// (`kind`/`sha256`/`n_cases`/`n_by_*`, maps in sorted key order),
/// mirroring `dataset._summarize_bytes`. Aggregated per-line problems
/// raise ValueError; the Python wrapper falls back to the reference so
/// the exact message wording is always Python's.
#[pyfunction]
fn dataset_summarize_case_bytes(
    py: Python<'_>,
    name: &str,
    data: &Bound<'_, PyAny>,
) -> PyResult<Py<PyAny>> {
    let bytes: Vec<u8> = data
        .extract()
        .map_err(|_| PyTypeError::new_err("data must be bytes"))?;
    let (summary, digest) =
        dataset::summarize_case_bytes(name, &bytes).map_err(PyValueError::new_err)?;
    let mut map = serde_json::Map::with_capacity(6);
    map.insert("kind".to_string(), Value::String("cases".to_string()));
    map.insert("sha256".to_string(), Value::String(digest));
    map.insert("n_cases".to_string(), Value::Number(summary.n_cases.into()));
    for (key, counts) in [
        ("n_by_family", &summary.n_by_family),
        ("n_by_severity", &summary.n_by_severity),
        ("n_by_primitive", &summary.n_by_primitive),
    ] {
        // BTreeMap iterates in sorted key order, matching the Python
        // `dict(sorted(...))`.
        let inner: serde_json::Map<String, Value> = counts
            .iter()
            .map(|(k, v)| (k.clone(), Value::Number((*v).into())))
            .collect();
        map.insert(key.to_string(), Value::Object(inner));
    }
    value_to_py(py, &Value::Object(map))
}

/// peira._core: the compiled Rust core (PyO3). Optional accelerator,
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
    m.add_function(wrap_pyfunction!(log_loss, m)?)?;
    m.add_function(wrap_pyfunction!(crps_point, m)?)?;
    m.add_function(wrap_pyfunction!(score_compression_index, m)?)?;
    m.add_function(wrap_pyfunction!(mcnemar, m)?)?;
    m.add_function(wrap_pyfunction!(mcnemar_mid_p, m)?)?;
    m.add_function(wrap_pyfunction!(mcnemar_p_value, m)?)?;
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
    m.add_function(wrap_pyfunction!(execution_pseudonymous_call_id, m)?)?;
    m.add_function(wrap_pyfunction!(execution_score_pair, m)?)?;
    m.add_function(wrap_pyfunction!(execution_cache_key, m)?)?;
    m.add_function(wrap_pyfunction!(execution_retry_jitter_seed, m)?)?;
    m.add_function(wrap_pyfunction!(execution_classify_failure, m)?)?;
    m.add_function(wrap_pyfunction!(execution_backoff_bound, m)?)?;
    m.add_function(wrap_pyfunction!(canonical_json, m)?)?;
    m.add_function(wrap_pyfunction!(canonical_pretty, m)?)?;
    m.add_function(wrap_pyfunction!(records_blank_record, m)?)?;
    m.add_function(wrap_pyfunction!(records_record_from_transcript_entry, m)?)?;
    m.add_function(wrap_pyfunction!(records_output_to_dict, m)?)?;
    m.add_function(wrap_pyfunction!(records_output_from_dict, m)?)?;
    m.add_function(wrap_pyfunction!(records_validate_transcript_entry, m)?)?;
    m.add_function(wrap_pyfunction!(pricing_cost_usd, m)?)?;
    m.add_function(wrap_pyfunction!(env_fingerprint_env, m)?)?;
    m.add_function(wrap_pyfunction!(artifact_lock_payload, m)?)?;
    m.add_function(wrap_pyfunction!(dataset_summarize_case_bytes, m)?)?;
    Ok(())
}
