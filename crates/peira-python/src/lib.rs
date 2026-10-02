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
//! - Float aggregates can differ from the reference by a few ulp:
//!   on Python 3.12+ the reference sums with the builtin `sum()`
//!   (Neumaier compensated summation) while the Rust core accumulates
//!   naively left-to-right, and the reference computes `** 2` through
//!   CPython's C `pow()` where the Rust core uses `.powi(2)` (exact
//!   multiplication). On Python 3.10/3.11 the builtin `sum()` is
//!   itself naive left-to-right. A few ulp is ~1e-15 relative,
//!   immaterial to every reported number.
//! - Values that have no JSON representation (non-finite floats, integers
//!   wider than u64, non-string dict keys) raise `TypeError`/`ValueError`;
//!   the Python wrappers catch those and fall back to pure Python.

use peira_core::{
    artifact, calibration, canonical, combo, combo_metrics, compare, dataset, economics, env,
    execution, gates, hardness, invariance, labels, lottery, metrics, pricing, records, schema,
    stability,
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
    price_table_ref: Option<String>,
    finish_reason: Option<String>,
    cached_tokens_in: Option<i64>,
    provider_response_id: Option<String>,
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
            finish_reason: u.finish_reason,
            cached_tokens_in: u.cached_tokens_in,
            provider_response_id: u.provider_response_id,
        }
    }
}

/// The record fields the Rust core computes on, extracted from any
/// Python object carrying those attributes. This is deliberately NOT
/// a field-for-field mirror of the Python `CallRecord`: Python owns
/// measurement sidecars the Rust core never computes on (`timing_ms`
/// decomposition, `timeout_kind` typing) and overlays them after the
/// Rust call returns (see `_record_from_transcript_entry` in
/// runner.py). Adding a field here is only warranted when the Rust
/// core needs it for a calculation.
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
            // v3 sidecars: the Rust core never computes on them (see
            // the struct doc above); they ride the artifact JSON, not
            // the PyO3 mirror.
            timeout_kind: None,
            timing_ms: None,
            error_code: String::new(),
            retry_count: 0,
            sampling_config: None,
            prompt_hash: String::new(),
            completion_hash: String::new(),
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
            conversational_turns: None,
            // The PyO3 path serves single-shot metrics; the
            // conversational runner is Python-only, so the EB-15
            // budget flag is always false here.
            attack_budget_exhausted: false,
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

/// Direction of a case's flip in the M-1 taxonomy.
#[pyfunction]
fn flip_direction(result: PyPerCaseResult) -> String {
    metrics::flip_direction(&metrics::PerCaseResult::from(result)).to_string()
}

/// Count of eligible cases per flip direction (M-1), every direction
/// present as a key.
#[pyfunction]
fn flip_direction_counts(results: Vec<PyPerCaseResult>) -> BTreeMap<String, usize> {
    metrics::flip_direction_counts(&to_core_results(results))
}

/// Net benefit at a single operating threshold (Vickers & Elkin 2006).
/// The Python wrapper validates before dispatching; the Rust core
/// asserts per the D-11 caller-bug convention.
#[pyfunction]
fn net_benefit_at_threshold(risks: Vec<f64>, labels: Vec<i64>, pt: f64) -> f64 {
    metrics::net_benefit_at_threshold(&risks, &labels, pt)
}

// ---------------------------------------------------------------------------
// economics: M-3 / C-4 numeric core (rust-max slice 4).
//
// The Rust core returns plain structs; these bindings hand the fields
// back as dicts the Python wrapper uses to construct its dataclasses
// (the slice-3 pattern). Scenario prices arrive as plain parameters;
// the Python wrapper owns the CostScenario dataclass and validation.
// ---------------------------------------------------------------------------

/// Build a ScenarioPrices from wrapper-supplied fields.
fn scenario_prices(
    flip_cost_usd: BTreeMap<String, f64>,
    flips_per_incident: f64,
    scenario_id: String,
) -> economics::ScenarioPrices {
    economics::ScenarioPrices {
        flip_cost_usd,
        flips_per_incident,
        scenario_id,
    }
}

fn dict_attack_cost_estimate(
    py: Python<'_>,
    e: &economics::AttackCostEstimate,
) -> PyResult<Py<PyDict>> {
    let out = PyDict::new(py);
    out.set_item("e_attacked", e.e_attacked)?;
    out.set_item("per_flip", e.per_flip)?;
    out.set_item("per_incident", e.per_incident)?;
    out.set_item("direction_counts", &e.direction_counts)?;
    out.set_item("n", e.n)?;
    out.set_item("scenario_id", &e.scenario_id)?;
    Ok(out.into())
}

/// economics.e_attacked: expected attack cost per decision.
#[pyfunction]
#[pyo3(signature = (results, flip_cost_usd, flips_per_incident, attack_rate, scenario_id))]
fn economics_e_attacked(
    py: Python<'_>,
    results: Vec<PyPerCaseResult>,
    flip_cost_usd: BTreeMap<String, f64>,
    flips_per_incident: f64,
    attack_rate: f64,
    scenario_id: String,
) -> PyResult<Py<PyDict>> {
    let prices = scenario_prices(flip_cost_usd, flips_per_incident, scenario_id);
    let e = economics::e_attacked(&to_core_results(results), &prices, attack_rate);
    dict_attack_cost_estimate(py, &e)
}

/// economics._mean_cost_per_decision: mean inference cost per eligible decision.
#[pyfunction]
fn economics_mean_cost_per_decision(results: Vec<PyPerCaseResult>) -> f64 {
    economics::mean_cost_per_decision(&to_core_results(results))
}

fn dict_frontier_point(py: Python<'_>, p: &economics::FrontierPoint) -> PyResult<Py<PyDict>> {
    let out = PyDict::new(py);
    out.set_item("adapter", &p.adapter)?;
    out.set_item("cost_per_decision_usd", p.cost_per_decision_usd)?;
    out.set_item("asr", p.asr)?;
    out.set_item("asr_ci95", (p.asr_ci95.0, p.asr_ci95.1))?;
    out.set_item("n", p.n)?;
    out.set_item("price_date", &p.price_date)?;
    out.set_item("on_frontier", p.on_frontier)?;
    Ok(out.into())
}

/// economics.pareto_frontier: (cost, ASR) Pareto frontier.
///
/// Adapters arrive as an order-preserving list of (name, results);
/// the returned points keep that order.
#[pyfunction]
fn economics_pareto_frontier(
    py: Python<'_>,
    adapters: Vec<(String, Vec<PyPerCaseResult>)>,
    price_date: &str,
) -> PyResult<Vec<Py<PyDict>>> {
    let core: Vec<(String, Vec<metrics::PerCaseResult>)> = adapters
        .into_iter()
        .map(|(name, rs)| (name, to_core_results(rs)))
        .collect();
    economics::pareto_frontier(&core, price_date)
        .iter()
        .map(|p| dict_frontier_point(py, p))
        .collect()
}

/// economics.drummond_holte_curves (points half): normalized expected
/// cost vs cost ratio. Crossover statements stay Python.
#[pyfunction]
fn economics_drummond_holte_points(
    py: Python<'_>,
    adapters: Vec<(String, Vec<PyPerCaseResult>)>,
    cost_ratios: Vec<f64>,
) -> PyResult<Vec<Py<PyDict>>> {
    let core: Vec<(String, Vec<metrics::PerCaseResult>)> = adapters
        .into_iter()
        .map(|(name, rs)| (name, to_core_results(rs)))
        .collect();
    economics::drummond_holte_points(&core, &cost_ratios)
        .iter()
        .map(|p| {
            let out = PyDict::new(py);
            out.set_item("adapter", &p.adapter)?;
            out.set_item("cost_ratio", p.cost_ratio)?;
            out.set_item("normalized_cost", p.normalized_cost)?;
            Ok(out.into())
        })
        .collect()
}

/// economics.attacker_cost_multiplier: 1 / P(flip in direction).
/// Returns None when the direction never flips.
#[pyfunction]
fn economics_attacker_cost_multiplier(
    results: Vec<PyPerCaseResult>,
    direction: &str,
) -> Option<f64> {
    economics::attacker_cost_multiplier(&to_core_results(results), direction)
}

fn dict_gordon_loeb(py: Python<'_>, r: &economics::GordonLoebResult) -> PyResult<Py<PyDict>> {
    let out = PyDict::new(py);
    out.set_item("tripped", r.tripped)?;
    out.set_item("annualized_extra_cost", r.annualized_extra_cost)?;
    out.set_item("expected_loss_reduction", r.expected_loss_reduction)?;
    out.set_item("ratio", r.ratio)?;
    Ok(out.into())
}

/// economics.gordon_loeb_tripwire: 37% over-investment tripwire.
#[pyfunction]
#[allow(clippy::too_many_arguments)]
#[pyo3(signature = (baseline_results, candidate_results, flip_cost_usd, flips_per_incident, scenario_id, decisions_per_year, attack_rate))]
fn economics_gordon_loeb_tripwire(
    py: Python<'_>,
    baseline_results: Vec<PyPerCaseResult>,
    candidate_results: Vec<PyPerCaseResult>,
    flip_cost_usd: BTreeMap<String, f64>,
    flips_per_incident: f64,
    scenario_id: String,
    decisions_per_year: f64,
    attack_rate: f64,
) -> PyResult<Py<PyDict>> {
    let prices = scenario_prices(flip_cost_usd, flips_per_incident, scenario_id);
    let r = economics::gordon_loeb_tripwire(
        &to_core_results(baseline_results),
        &to_core_results(candidate_results),
        &prices,
        decisions_per_year,
        attack_rate,
    );
    dict_gordon_loeb(py, &r)
}

fn dict_defense_point(py: Python<'_>, p: &economics::DefensePoint) -> PyResult<Py<PyDict>> {
    let out = PyDict::new(py);
    out.set_item("pt", p.pt)?;
    out.set_item("n_reviewed", p.n_reviewed)?;
    out.set_item("review_rate", p.review_rate)?;
    out.set_item("residual_e_attacked", p.residual_e_attacked)?;
    out.set_item("review_spend_per_decision", p.review_spend_per_decision)?;
    out.set_item(
        "total_defender_cost_per_decision",
        p.total_defender_cost_per_decision,
    )?;
    out.set_item("net_benefit", p.net_benefit)?;
    Ok(out.into())
}

fn dict_defense_curve(py: Python<'_>, c: &economics::DefenseCurve) -> PyResult<Py<PyDict>> {
    let out = PyDict::new(py);
    let points: Vec<Py<PyDict>> = c
        .points
        .iter()
        .map(|p| dict_defense_point(py, p))
        .collect::<PyResult<_>>()?;
    out.set_item("points", points)?;
    out.set_item("n_eligible", c.n_eligible)?;
    out.set_item("n_analyzed", c.n_analyzed)?;
    out.set_item("n_always_review", c.n_always_review)?;
    out.set_item("e_attacked_undefended", c.e_attacked_undefended)?;
    out.set_item("scenario_id", &c.scenario_id)?;
    out.set_item("review_cost_usd", c.review_cost_usd)?;
    out.set_item("attack_rate", c.attack_rate)?;
    Ok(out.into())
}

/// economics.defense_curve: C-4 threshold sweep.
///
/// The wrapper validates review_cost_usd, attack_rate, and the
/// threshold grid (exact ValueErrors); the core assumes valid inputs.
/// Errors when no eligible cases exist.
#[pyfunction]
#[allow(clippy::too_many_arguments)]
#[pyo3(signature = (results, flip_cost_usd, flips_per_incident, scenario_id, review_cost_usd, attack_rate, thresholds))]
fn economics_defense_curve(
    py: Python<'_>,
    results: Vec<PyPerCaseResult>,
    flip_cost_usd: BTreeMap<String, f64>,
    flips_per_incident: f64,
    scenario_id: String,
    review_cost_usd: f64,
    attack_rate: f64,
    thresholds: Vec<f64>,
) -> PyResult<Py<PyDict>> {
    let prices = scenario_prices(flip_cost_usd, flips_per_incident, scenario_id);
    let c = economics::defense_curve(
        &to_core_results(results),
        &prices,
        review_cost_usd,
        attack_rate,
        &thresholds,
    )
    .map_err(PyValueError::new_err)?;
    dict_defense_curve(py, &c)
}

/// economics.risk_coverage_curve: (review_rate, residual) sorted.
#[pyfunction]
fn economics_risk_coverage_curve(
    py: Python<'_>,
    curve: &Bound<'_, PyDict>,
) -> PyResult<Vec<(f64, f64)>> {
    let _ = py;
    let points: Vec<(f64, f64)> = curve
        .get_item("points")?
        .ok_or_else(|| PyValueError::new_err("curve dict missing 'points'"))?
        .extract::<Vec<Py<PyDict>>>()?
        .iter()
        .map(|p| {
            let p = p.bind(py);
            Ok((
                p.get_item("review_rate")?
                    .ok_or_else(|| PyValueError::new_err("point missing 'review_rate'"))?
                    .extract::<f64>()?,
                p.get_item("residual_e_attacked")?
                    .ok_or_else(|| PyValueError::new_err("point missing 'residual_e_attacked'"))?
                    .extract::<f64>()?,
            ))
        })
        .collect::<PyResult<_>>()?;
    let mut pts = points;
    pts.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    Ok(pts)
}

fn dict_defense_optimum(py: Python<'_>, o: &economics::DefenseOptimum) -> PyResult<Py<PyDict>> {
    let out = PyDict::new(py);
    out.set_item("pt", o.pt)?;
    out.set_item("review_rate", o.review_rate)?;
    out.set_item("residual_e_attacked", o.residual_e_attacked)?;
    out.set_item("review_spend_per_decision", o.review_spend_per_decision)?;
    out.set_item(
        "total_defender_cost_per_decision",
        o.total_defender_cost_per_decision,
    )?;
    out.set_item(
        "prevention_value_per_review_dollar",
        o.prevention_value_per_review_dollar,
    )?;
    Ok(out.into())
}

/// economics.optimal_threshold: attacker-cost-aware operating point.
/// Takes the defense-curve dict produced by economics_defense_curve.
#[pyfunction]
fn economics_optimal_threshold(py: Python<'_>, curve: &Bound<'_, PyDict>) -> PyResult<Py<PyDict>> {
    let get_f = |d: &Bound<'_, PyDict>, k: &str| -> PyResult<f64> {
        d.get_item(k)?
            .ok_or_else(|| PyValueError::new_err(format!("curve missing {k:?}")))?
            .extract::<f64>()
    };
    let get_usize = |d: &Bound<'_, PyDict>, k: &str| -> PyResult<usize> {
        d.get_item(k)?
            .ok_or_else(|| PyValueError::new_err(format!("curve missing {k:?}")))?
            .extract::<usize>()
    };
    let points: Vec<economics::DefensePoint> = curve
        .get_item("points")?
        .ok_or_else(|| PyValueError::new_err("curve dict missing 'points'"))?
        .extract::<Vec<Py<PyDict>>>()?
        .iter()
        .map(|p| {
            let p = p.bind(py);
            Ok(economics::DefensePoint {
                pt: get_f(p, "pt")?,
                n_reviewed: get_usize(p, "n_reviewed")?,
                review_rate: get_f(p, "review_rate")?,
                residual_e_attacked: get_f(p, "residual_e_attacked")?,
                review_spend_per_decision: get_f(p, "review_spend_per_decision")?,
                total_defender_cost_per_decision: get_f(p, "total_defender_cost_per_decision")?,
                net_benefit: get_f(p, "net_benefit")?,
            })
        })
        .collect::<PyResult<_>>()?;
    let c = economics::DefenseCurve {
        points,
        n_eligible: get_usize(curve, "n_eligible")?,
        n_analyzed: get_usize(curve, "n_analyzed")?,
        n_always_review: get_usize(curve, "n_always_review")?,
        e_attacked_undefended: get_f(curve, "e_attacked_undefended")?,
        scenario_id: curve
            .get_item("scenario_id")?
            .ok_or_else(|| PyValueError::new_err("curve missing 'scenario_id'"))?
            .extract::<String>()?,
        review_cost_usd: get_f(curve, "review_cost_usd")?,
        attack_rate: get_f(curve, "attack_rate")?,
    };
    let o = economics::optimal_threshold(&c);
    dict_defense_optimum(py, &o)
}

// ---------------------------------------------------------------------------
// stability: M-7 numeric core (rust-max slice 5).
//
// The Rust core returns plain structs; these bindings hand the fields
// back as dicts the Python wrapper uses to construct its dataclasses
// (the slice-4 pattern). The dataclasses, summary_text, and
// StabilityArtifact sealing stay Python.
// ---------------------------------------------------------------------------

/// Fields of `stability::StabilitySummary` as a dict.
fn dict_stability_summary(py: Python<'_>, s: &stability::StabilitySummary) -> PyResult<Py<PyDict>> {
    let out = PyDict::new(py);
    out.set_item("k", s.k)?;
    out.set_item("n_cases", s.n_cases)?;
    out.set_item("n_cases_total", s.n_cases_total)?;
    out.set_item("per_seed_asr", &s.per_seed_asr)?;
    out.set_item("pooled_asr", s.pooled_asr)?;
    out.set_item("pass_k", s.pass_k)?;
    out.set_item("n_agree", s.n_agree)?;
    let rates = PyDict::new(py);
    for (cid, rate) in &s.per_case_flip_rate {
        rates.set_item(cid, *rate)?;
    }
    out.set_item("per_case_flip_rate", rates)?;
    out.set_item("wilson_ci", (s.wilson_ci.0, s.wilson_ci.1))?;
    out.set_item("run_sd", s.run_sd)?;
    out.set_item("item_variance", s.item_variance)?;
    out.set_item("n_churn", s.n_churn)?;
    Ok(out.into())
}

/// stability.flip_agreement: k-seed stability numeric core.
///
/// Returns the raw fields as a dict; the wrapper constructs the
/// `StabilityResult` dataclass (seeds/excluded_seeds filled by the
/// caller). Alignment failures raise `ValueError`, matching the
/// reference.
#[pyfunction]
fn stability_flip_agreement(
    py: Python<'_>,
    results_by_seed: Vec<Vec<PyPerCaseResult>>,
) -> PyResult<Py<PyDict>> {
    let input: Vec<Vec<metrics::PerCaseResult>> =
        results_by_seed.into_iter().map(to_core_results).collect();
    let s = stability::flip_agreement(&input).map_err(|e| PyValueError::new_err(e.to_string()))?;
    dict_stability_summary(py, &s)
}

/// Fields of `stability::FamilyDriftSummary` as a dict.
fn dict_family_drift_summary(
    py: Python<'_>,
    f: &stability::FamilyDriftSummary,
) -> PyResult<Py<PyDict>> {
    let out = PyDict::new(py);
    out.set_item("family", &f.family)?;
    out.set_item("n_paired", f.n_paired)?;
    out.set_item("asr_old", f.asr_old)?;
    out.set_item("asr_new", f.asr_new)?;
    out.set_item("delta", f.delta)?;
    out.set_item("n_newly_flipping", f.n_newly_flipping)?;
    out.set_item("n_newly_fixed", f.n_newly_fixed)?;
    out.set_item("mcnemar_p", f.mcnemar_p)?;
    out.set_item("degraded", f.degraded)?;
    Ok(out.into())
}

/// stability.drift_watch: longitudinal drift numeric core.
///
/// Returns the raw fields as a dict; the wrapper constructs the
/// `DriftResult` dataclass (run ids filled by the caller).
#[pyfunction]
fn stability_drift_watch(
    py: Python<'_>,
    old_results: Vec<PyPerCaseResult>,
    new_results: Vec<PyPerCaseResult>,
) -> PyResult<Py<PyDict>> {
    let d = stability::drift_watch(&to_core_results(old_results), &to_core_results(new_results));
    let out = PyDict::new(py);
    let fams = PyList::new(
        py,
        d.families
            .iter()
            .map(|f| dict_family_drift_summary(py, f))
            .collect::<PyResult<Vec<_>>>()?,
    )?;
    out.set_item("families", fams)?;
    out.set_item("newly_flipping", &d.newly_flipping)?;
    out.set_item("newly_fixed", &d.newly_fixed)?;
    Ok(out.into())
}

// ---------------------------------------------------------------------------
// calibration: R-11 SVG diagrams (rust-max slice 7).
//
// The Python wrappers gate inputs to JSON-native shapes before dispatch;
// these bindings extract the gated values into the core's `Scalar`
// model. Anything the gate missed (non-JSON scalars, out-of-range ints)
// raises TypeError/ValueError, which the wrappers catch and fall back
// to the pure-Python twins.
// ---------------------------------------------------------------------------

/// Extract a JSON-native scalar for the calibration core.
///
/// `bool` is checked before `int` because Python's `bool` subclasses
/// `int`. Huge ints fail the i64 extraction and raise, as do non-scalar
/// types; the wrapper falls back to Python on both.
fn calibration_scalar(obj: &Bound<'_, PyAny>) -> PyResult<calibration::Scalar> {
    if obj.is_none() {
        return Ok(calibration::Scalar::None);
    }
    if let Ok(b) = obj.cast::<PyBool>() {
        return Ok(calibration::Scalar::Bool(b.is_true()));
    }
    if let Ok(i) = obj.cast::<PyInt>() {
        let v: i64 = i
            .extract()
            .map_err(|_| PyValueError::new_err("calibration: int out of i64 range"))?;
        return Ok(calibration::Scalar::Int(v));
    }
    if let Ok(f) = obj.cast::<PyFloat>() {
        return Ok(calibration::Scalar::Float(f.value()));
    }
    Err(PyTypeError::new_err(
        "calibration: expected a JSON scalar (None/bool/int/float)",
    ))
}

/// `dict.get(key)` as a calibration scalar; missing keys become
/// `Scalar::None` (the twin's `KeyError` path withholds the block).
fn calibration_get(dict: &Bound<'_, PyDict>, key: &str) -> PyResult<calibration::Scalar> {
    match dict.get_item(key)? {
        Some(v) => calibration_scalar(&v),
        None => Ok(calibration::Scalar::None),
    }
}

/// calibration.reliability_diagram_svg: R-11 reliability diagram.
///
/// `block` is a gated dict (`reliability_bins` block); `title` is a
/// plain string. Returns the SVG (or the withheld placeholder) as a
/// string, byte-identical to the Python twin.
#[pyfunction]
fn calibration_reliability_diagram_svg(block: &Bound<'_, PyDict>, title: &str) -> PyResult<String> {
    let n = calibration_get(block, "n")?.to_int().unwrap_or(0);
    let sufficient = block
        .get_item("sufficient")?
        .map(|v| v.is_truthy())
        .transpose()?
        .unwrap_or(false);
    let bins = match block.get_item("bins")? {
        None => None,
        Some(v) => {
            if v.is_none() {
                None
            } else {
                let list = v
                    .cast::<PyList>()
                    .map_err(|_| PyTypeError::new_err("calibration: 'bins' is not a list"))?;
                let mut out = Vec::with_capacity(list.len());
                for item in list.iter() {
                    let d = item
                        .cast::<PyDict>()
                        .map_err(|_| PyTypeError::new_err("calibration: bin is not a dict"))?;
                    out.push(calibration::RawRelBin {
                        mean_forecast: calibration_get(d, "mean_forecast")?,
                        mean_outcome: calibration_get(d, "mean_outcome")?,
                        n: calibration_get(d, "n")?,
                    });
                }
                Some(out)
            }
        }
    };
    Ok(calibration::reliability_diagram_svg(
        &calibration::ReliabilityBlock {
            n,
            sufficient,
            bins,
        },
        title,
    ))
}

/// calibration.risk_coverage_diagram_svg: R-11 selective-risk curve.
///
/// `sp` is a gated dict (`selective_prediction` block). Returns the SVG
/// (or the withheld placeholder), byte-identical to the Python twin.
#[pyfunction]
fn calibration_risk_coverage_diagram_svg(sp: &Bound<'_, PyDict>, title: &str) -> PyResult<String> {
    let n = calibration_get(sp, "n")?.to_int().unwrap_or(0);
    let sufficient = sp
        .get_item("sufficient")?
        .map(|v| v.is_truthy())
        .transpose()?
        .unwrap_or(false);
    let curve = match sp.get_item("risk_coverage_curve")? {
        None => None,
        Some(v) => {
            if v.is_none() {
                None
            } else {
                let list = v.cast::<PyList>().map_err(|_| {
                    PyTypeError::new_err("calibration: 'risk_coverage_curve' is not a list")
                })?;
                let mut out = Vec::with_capacity(list.len());
                for item in list.iter() {
                    let pair = item.cast::<PyList>().map_err(|_| {
                        PyTypeError::new_err("calibration: curve point is not a list")
                    })?;
                    if pair.len() != 2 {
                        return Err(PyValueError::new_err(
                            "calibration: curve point does not have 2 elements",
                        ));
                    }
                    let c = calibration_scalar(&pair.get_item(0)?)?;
                    let r = calibration_scalar(&pair.get_item(1)?)?;
                    out.push((c, r));
                }
                Some(out)
            }
        }
    };
    Ok(calibration::risk_coverage_diagram_svg(
        &calibration::RiskCoverageBlock {
            n,
            sufficient,
            curve,
        },
        title,
    ))
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
        // A foreign dataclass carrying fields beyond the nine known
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
            "finish_reason",
            "cached_tokens_in",
            "provider_response_id",
        ];
        let fields = usage.getattr("__dataclass_fields__")?;
        let dict = fields.cast::<PyDict>().map_err(|_| {
            PyTypeError::new_err(
                "usage must be a CallUsage dataclass instance with exactly the 9 known fields",
            )
        })?;
        // `dataclasses.fields()` (which `asdict` uses) keeps only fields
        // whose `_field_type is dataclasses._FIELD`, excluding ClassVar /
        // InitVar pseudo-fields. Mirror that identity check exactly: a
        // mere presence check is wrong, since unbound `dataclasses.field()`
        // objects carry `_field_type=None`.
        let field_marker = output.py().import("dataclasses")?.getattr("_FIELD")?;
        let mut seen = [false; 9];
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
                "usage must be a CallUsage dataclass instance with exactly the 9 known fields",
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
    max_tokens_per_call: Option<i64>,
    metrics: &Bound<'_, PyAny>,
    env: &Bound<'_, PyAny>,
    env_sha256: &str,
    model_class: &str,
    confidence_source: &str,
    checkpoint_hash: &str,
    api_version: &str,
    call_date: &str,
    decode_params: &str,
    template_hash: &str,
    case_set_tag: &str,
    cost_scenario_version: &str,
    run_id: &str,
    parent_run_id: &str,
    run_status: &str,
    schema_ref: &str,
    metrics_version: &str,
    threat_model: &Bound<'_, PyAny>,
    attack_provenance: &Bound<'_, PyAny>,
    adjudication_policy: &Bound<'_, PyAny>,
    exposure_attestation: &Bound<'_, PyAny>,
    adapter_pins: &Bound<'_, PyAny>,
    license: &str,
    access_tier: &str,
    per_family_stats: &Bound<'_, PyAny>,
    uncertainty: &Bound<'_, PyAny>,
    retry_policy: &Bound<'_, PyAny>,
    cache_policy: &Bound<'_, PyAny>,
    determinism_check: &Bound<'_, PyAny>,
    error_log: &Bound<'_, PyAny>,
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
        max_tokens_per_call,
        &value_from_py(metrics)?,
        &value_from_py(env)?,
        env_sha256,
        model_class,
        confidence_source,
        checkpoint_hash,
        api_version,
        call_date,
        decode_params,
        template_hash,
        case_set_tag,
        cost_scenario_version,
        run_id,
        parent_run_id,
        run_status,
        schema_ref,
        metrics_version,
        &value_from_py(threat_model)?,
        &value_from_py(attack_provenance)?,
        &value_from_py(adjudication_policy)?,
        &value_from_py(exposure_attestation)?,
        &value_from_py(adapter_pins)?,
        license,
        access_tier,
        &value_from_py(per_family_stats)?,
        &value_from_py(uncertainty)?,
        &value_from_py(retry_policy)?,
        &value_from_py(cache_policy)?,
        &value_from_py(determinism_check)?,
        &value_from_py(error_log)?,
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

/// Banker's rounding to 4 decimals, mirroring Python's `round(v, 4)`.
///
/// Exposed so the backend-parity suite can pin it directly against the
/// Python reference on a boundary battery (negatives, x.xxx5 values).
/// The lottery bindings apply it internally; this entry point is the
/// test hook for the rounding rule itself.
#[pyfunction]
fn lottery_round4(v: f64) -> f64 {
    lottery::round4(v)
}

/// Finite f64 as a JSON number. Lottery outputs are ratios of small
/// integers in [-1, 1]; non-finite cannot occur.
fn json_num(v: f64) -> Value {
    Value::Number(Number::from_f64(v).expect("lottery outputs are finite"))
}

fn json_opt_num(v: Option<f64>) -> Value {
    v.map_or(Value::Null, json_num)
}

fn json_strs(items: Vec<String>) -> Value {
    Value::Array(items.into_iter().map(Value::String).collect())
}

/// Convert `(run_id, results)` pairs to core results; shared by the
/// two lottery entry points that take runs.
fn to_core_runs(
    runs: Vec<(String, Vec<PyPerCaseResult>)>,
) -> Vec<(String, Vec<metrics::PerCaseResult>)> {
    runs.into_iter()
        .map(|(run_id, results)| (run_id, to_core_results(results)))
        .collect()
}

/// RankedRun as a named-field object, mirroring
/// `python/peira/lottery.py::RankedRun`. `asr` is the RAW conditional
/// ASR (null when ineligible); the Python wrapper rounds it for
/// display, exactly like the reference.
fn ranked_run_to_value(r: lottery::RankedRun) -> Value {
    let mut m = serde_json::Map::new();
    m.insert("run_id".to_string(), Value::String(r.run_id));
    m.insert("asr".to_string(), json_opt_num(r.asr));
    m.insert("eligible".to_string(), Value::Bool(r.eligible));
    m.insert("reasons".to_string(), json_strs(r.reasons));
    Value::Object(m)
}

/// lottery.rank_runs: rank runs by conditional ASR (ascending) over
/// `families`.
///
/// `runs` holds (run_id, results) in mapping order. Returns a list of
/// named-field RankedRun objects: eligible first by (raw asr, run_id),
/// then ineligible by run_id. The Python wrapper validates (non-empty
/// families, non-empty string run ids) before dispatch and raises the
/// reference's ValueErrors itself.
#[pyfunction]
fn lottery_rank_runs(
    py: Python<'_>,
    runs: Vec<(String, Vec<PyPerCaseResult>)>,
    families: Vec<String>,
) -> PyResult<Py<PyAny>> {
    let arr = Value::Array(
        lottery::rank_runs(&to_core_runs(runs), &families)
            .into_iter()
            .map(ranked_run_to_value)
            .collect(),
    );
    value_to_py(py, &arr)
}

/// lottery.kendall_tau: Kendall's tau between two best-first run-id
/// lists, or None when fewer than two runs are common to both.
#[pyfunction]
fn lottery_kendall_tau(rank_a: Vec<String>, rank_b: Vec<String>) -> Option<f64> {
    lottery::kendall_tau(&rank_a, &rank_b)
}

/// lottery.pairwise_swap_fraction: fraction of common pairs whose
/// relative order differs, or None when fewer than two runs are
/// common to both.
#[pyfunction]
fn lottery_pairwise_swap_fraction(rank_a: Vec<String>, rank_b: Vec<String>) -> Option<f64> {
    lottery::pairwise_swap_fraction(&rank_a, &rank_b)
}

/// lottery.stability_verdict: one-word verdict for a lottery index.
/// Bands the value it is given; `lottery_analysis` passes the ROUNDED
/// index, mirroring the reference.
#[pyfunction]
fn lottery_stability_verdict(lottery_index: Option<f64>) -> String {
    lottery::stability_verdict(lottery_index)
}

/// Per-family leave-one-out detail as a named-field object.
/// `tau`/`swap_fraction` arrive [`lottery::round4`]-rounded; the Python
/// wrapper places them into the report dict untouched.
fn family_detail_to_value(family: &str, d: lottery::FamilyDetail) -> Value {
    let mut m = serde_json::Map::new();
    m.insert("family".to_string(), Value::String(family.to_string()));
    m.insert("tau".to_string(), json_opt_num(d.tau));
    m.insert("swap_fraction".to_string(), json_opt_num(d.swap_fraction));
    m.insert(
        "n_common".to_string(),
        Value::Number(Number::from(d.n_common as u64)),
    );
    m.insert(
        "max_rank_displacement".to_string(),
        d.max_rank_displacement
            .map_or(Value::Null, |n| Value::Number(Number::from(n as u64))),
    );
    m.insert("ranking".to_string(), json_strs(d.ranking));
    m.insert("dropped_runs".to_string(), json_strs(d.dropped_runs));
    Value::Object(m)
}

/// lottery.lottery_analysis: leave-one-family-out ranking stability.
///
/// Returns the report as a named-field object; `per_family` is an
/// array of family-detail objects in the input `families` order, so
/// the Python wrapper preserves dict insertion order.
///
/// Raises ValueError with the reference's exact message when
/// `families` is empty, or when a leave-one-out step would rank on no
/// families (the single-family case).
#[pyfunction]
fn lottery_analysis(
    py: Python<'_>,
    runs: Vec<(String, Vec<PyPerCaseResult>)>,
    families: Vec<String>,
) -> PyResult<Py<PyAny>> {
    let a =
        lottery::lottery_analysis(&to_core_runs(runs), &families).map_err(PyValueError::new_err)?;
    let mut m = serde_json::Map::new();
    m.insert("families".to_string(), json_strs(a.families));
    m.insert(
        "n_runs".to_string(),
        Value::Number(Number::from(a.n_runs as u64)),
    );
    m.insert(
        "n_ranked".to_string(),
        Value::Number(Number::from(a.n_ranked as u64)),
    );
    m.insert("full_ranking".to_string(), json_strs(a.full_ranking));
    m.insert(
        "full_ranking_detail".to_string(),
        Value::Array(
            a.full_ranking_detail
                .into_iter()
                .map(ranked_run_to_value)
                .collect(),
        ),
    );
    m.insert("lottery_index".to_string(), json_opt_num(a.lottery_index));
    m.insert("verdict".to_string(), Value::String(a.verdict));
    m.insert("min_tau".to_string(), json_opt_num(a.min_tau));
    m.insert(
        "most_influential_family".to_string(),
        a.most_influential_family.map_or(Value::Null, Value::String),
    );
    m.insert(
        "per_family".to_string(),
        Value::Array(
            a.per_family
                .into_iter()
                .map(|(fam, d)| family_detail_to_value(&fam, d))
                .collect(),
        ),
    );
    value_to_py(py, &Value::Object(m))
}

/// _labels.candidate_labels: sorted, deduplicated candidate labels
/// from the case input's options.
///
/// The Python wrapper validates that `case_input` is a dict before
/// dispatch (a non-dict raises the reference's AttributeError); the
/// core handles every JSON-shaped dict, and values that have no JSON
/// representation raise TypeError/ValueError from the conversion, in
/// which case the wrapper falls back to the pure-Python reference.
#[pyfunction]
fn labels_candidate_labels(
    case_input: &Bound<'_, PyDict>,
    primitive: &str,
) -> PyResult<Vec<String>> {
    let v = value_from_py(case_input.as_any())?;
    Ok(labels::candidate_labels(&v, primitive))
}

/// _labels.non_abstain_placeholder: the "other" placeholder.
#[pyfunction]
fn labels_non_abstain_placeholder() -> String {
    labels::non_abstain_placeholder().to_owned()
}

/// invariance.invariance_report: flip-rate summary for one case's
/// variant set, as a named-field object.
///
/// The Python wrapper validates non-empty `variant_decisions` before
/// dispatch (D-11); the core also returns the error, mapped here to
/// PyValueError with the reference's exact message, as a backstop.
#[pyfunction]
fn invariance_report(
    py: Python<'_>,
    baseline_decision: &str,
    variant_decisions: Vec<String>,
) -> PyResult<Py<PyAny>> {
    let r = invariance::invariance_report(baseline_decision, &variant_decisions)
        .map_err(|e| PyValueError::new_err(e.message().to_owned()))?;
    let mut m = serde_json::Map::new();
    m.insert("baseline".to_string(), Value::String(r.baseline));
    m.insert(
        "n_variants".to_string(),
        Value::Number(Number::from(r.n_variants as u64)),
    );
    m.insert(
        "n_flips".to_string(),
        Value::Number(Number::from(r.n_flips as u64)),
    );
    m.insert(
        "flip_rate".to_string(),
        Value::Number(
            Number::from_f64(r.flip_rate)
                .ok_or_else(|| PyValueError::new_err("flip_rate is not finite"))?,
        ),
    );
    m.insert(
        "flipped_indices".to_string(),
        Value::Array(
            r.flipped_indices
                .into_iter()
                .map(|i| Value::Number(Number::from(i as u64)))
                .collect(),
        ),
    );
    value_to_py(py, &Value::Object(m))
}

/// Map a [`combo::ComboError`] to the Python exception type the
/// reference raises: KeyError for unknown-pair lookups, ValueError
/// otherwise, with the identical message.
fn combo_py_err(e: combo::ComboError) -> PyErr {
    if e.is_key_error() {
        PyKeyError::new_err(e.message().to_owned())
    } else {
        PyValueError::new_err(e.message().to_owned())
    }
}

/// combo_schema.combo_pair_id: canonical pair id for two family ids.
#[pyfunction]
fn combo_pair_id(family_a: &str, family_b: &str) -> PyResult<String> {
    combo::combo_pair_id(family_a, family_b).map_err(combo_py_err)
}

/// combo_schema.combo_case_id: canonical case id for one arm.
#[pyfunction]
fn combo_case_id(pair_id: &str, substrate_idx: i64, arm: &str) -> PyResult<String> {
    combo::combo_case_id(pair_id, substrate_idx, arm).map_err(combo_py_err)
}

/// combo_schema.parse_combo_case_id: split into (pair_id, idx, arm).
#[pyfunction]
fn combo_parse_case_id(case_id: &str) -> PyResult<(String, i64, String)> {
    combo::parse_combo_case_id(case_id).map_err(combo_py_err)
}

/// combo_schema.validate_combo_dict: list of error strings.
///
/// Inputs that violate the structural contract (non-string case_id,
/// truthy non-dict benign/attacked) surface here as an internal
/// AttributeError; the Python wrapper catches it and re-runs the
/// pure-Python reference, which raises the natural exception. A
/// missing `primary_outcome` propagates as KeyError, exactly like the
/// reference. Non-JSON-shaped values raise TypeError/ValueError from
/// the conversion with the same fallback.
#[pyfunction]
fn combo_validate_dict(d: &Bound<'_, PyDict>) -> PyResult<Vec<String>> {
    let v = value_from_py(d.as_any())?;
    let map = v
        .as_object()
        .ok_or_else(|| PyValueError::new_err("internal: dict did not convert to a JSON object"))?;
    combo::validate_combo_dict(map).map_err(|e| match e {
        combo::ValidateError::Structural => PyAttributeError::new_err(
            "internal: input violates the combo validation structural contract",
        ),
        combo::ValidateError::Key(ke) => combo_py_err(ke),
    })
}

/// combo_metrics.paired_interaction: paired interaction contrast.
///
/// Returns the result fields as a dict; the Python wrapper constructs
/// the `InteractionResult` dataclass from it. Empty outcomes raise
/// `ValueError("no substrates")`, matching the reference. Non-integer
/// outcomes fail `Vec<(i64, i64, i64, i64)>` extraction with
/// `TypeError`; the wrapper falls back to the reference.
#[pyfunction]
fn combo_metrics_paired_interaction(
    py: Python<'_>,
    outcomes: Vec<(i64, i64, i64, i64)>,
    pair_id: &str,
    hypothesis: &str,
) -> PyResult<Py<PyDict>> {
    let r = combo_metrics::paired_interaction(&outcomes, pair_id, hypothesis)
        .map_err(|e| PyValueError::new_err(e.to_string()))?;
    let d = PyDict::new(py);
    d.set_item("pair_id", r.pair_id)?;
    d.set_item("n_substrates", r.n_substrates)?;
    d.set_item("rate_ctrl", r.rate_ctrl)?;
    d.set_item("rate_a", r.rate_a)?;
    d.set_item("rate_b", r.rate_b)?;
    d.set_item("rate_ab", r.rate_ab)?;
    d.set_item("interaction", r.interaction)?;
    d.set_item("se", r.se)?;
    d.set_item("ci_lo", r.ci_lo)?;
    d.set_item("ci_hi", r.ci_hi)?;
    d.set_item("mde_80", r.mde_80)?;
    d.set_item("classification", r.classification)?;
    d.set_item("hypothesis", r.hypothesis)?;
    d.set_item("hypothesis_confirmed", r.hypothesis_confirmed)?;
    Ok(d.into())
}

/// Extract an `InteractionResult` from the wrapper-built dict.
///
/// Field extraction failures raise `TypeError`; the Python wrapper
/// catches it and re-runs the reference, which raises the natural
/// exception (or formats the unusual value) itself.
fn interaction_from_dict(d: &Bound<'_, PyDict>) -> PyResult<combo_metrics::InteractionResult> {
    let get_str = |k: &str| -> PyResult<String> {
        d.get_item(k)?
            .ok_or_else(|| PyTypeError::new_err(format!("internal: missing field {k}")))?
            .extract()
            .map_err(|_| PyTypeError::new_err(format!("internal: field {k} is not a str")))
    };
    let get_f64 = |k: &str| -> PyResult<f64> {
        d.get_item(k)?
            .ok_or_else(|| PyTypeError::new_err(format!("internal: missing field {k}")))?
            .extract()
            .map_err(|_| PyTypeError::new_err(format!("internal: field {k} is not a float")))
    };
    Ok(combo_metrics::InteractionResult {
        pair_id: get_str("pair_id")?,
        n_substrates: d
            .get_item("n_substrates")?
            .ok_or_else(|| PyTypeError::new_err("internal: missing field n_substrates"))?
            .extract()
            .map_err(|_| PyTypeError::new_err("internal: field n_substrates is not an int"))?,
        rate_ctrl: get_f64("rate_ctrl")?,
        rate_a: get_f64("rate_a")?,
        rate_b: get_f64("rate_b")?,
        rate_ab: get_f64("rate_ab")?,
        interaction: get_f64("interaction")?,
        se: get_f64("se")?,
        ci_lo: get_f64("ci_lo")?,
        ci_hi: get_f64("ci_hi")?,
        mde_80: get_f64("mde_80")?,
        classification: get_str("classification")?,
        hypothesis: get_str("hypothesis")?,
        hypothesis_confirmed: d
            .get_item("hypothesis_confirmed")?
            .ok_or_else(|| PyTypeError::new_err("internal: missing field hypothesis_confirmed"))?
            .extract()
            .map_err(|_| {
                PyTypeError::new_err("internal: field hypothesis_confirmed is not a bool-or-None")
            })?,
    })
}

/// combo_metrics.format_interaction: one-paragraph human summary.
///
/// Takes the wrapper-built field dict (see [`interaction_from_dict`]).
/// An unknown classification raises `KeyError`, matching the reference.
#[pyfunction]
fn combo_metrics_format_interaction(d: &Bound<'_, PyDict>) -> PyResult<String> {
    let r = interaction_from_dict(d)?;
    combo_metrics::format_interaction(&r).map_err(PyKeyError::new_err)
}

/// Convert the Python `dict[str, list[PerCaseResult]]` to the core input.
///
/// `BTreeMap` extraction sorts adapter names byte-wise, matching the
/// reference's `sorted()`. Non-string keys or non-PerCaseResult values
/// fail extraction with `TypeError`; the wrapper falls back.
fn hardness_input(results: BTreeMap<String, Vec<PyPerCaseResult>>) -> hardness::ResultsByAdapter {
    results
        .into_iter()
        .map(|(k, v)| (k, v.into_iter().map(metrics::PerCaseResult::from).collect()))
        .collect()
}

fn hardness_dict_flip_distribution(
    py: Python<'_>,
    d: &hardness::FlipDistribution,
) -> PyResult<Py<PyDict>> {
    let out = PyDict::new(py);
    out.set_item("adapters", &d.adapters)?;
    out.set_item("n_cases", d.n_cases)?;
    out.set_item("counts", &d.counts)?;
    Ok(out.into())
}

fn hardness_dict_hardest_decile(
    py: Python<'_>,
    h: &hardness::HardestDecileSurvival,
) -> PyResult<Py<PyDict>> {
    let out = PyDict::new(py);
    out.set_item("adapters", &h.adapters)?;
    out.set_item("n_cases", h.n_cases)?;
    out.set_item("decile_size", h.decile_size)?;
    out.set_item("decile_case_ids", &h.decile_case_ids)?;
    out.set_item("survived", &h.survived)?;
    Ok(out.into())
}

fn hardness_dict_transfer_matrix(
    py: Python<'_>,
    t: &hardness::TransferMatrix,
) -> PyResult<Py<PyDict>> {
    let out = PyDict::new(py);
    out.set_item("adapters", &t.adapters)?;
    out.set_item("family", &t.family)?;
    out.set_item("n_cases", t.n_cases)?;
    out.set_item("flipped_by_source", &t.flipped_by_source)?;
    // Rates cross as (src, dst, rate-or-None) triples; the wrapper
    // rebuilds the {(src, dst): rate} dict.
    let rates: Vec<(String, String, Option<f64>)> = t
        .rates
        .iter()
        .map(|((s, d), v)| (s.clone(), d.clone(), *v))
        .collect();
    out.set_item("rates", rates)?;
    Ok(out.into())
}

/// hardness.flip_distribution: flip-count histogram.
///
/// Returns the raw fields as a dict; the wrapper constructs the
/// `FlipDistribution` dataclass.
#[pyfunction]
fn hardness_flip_distribution(
    py: Python<'_>,
    results: BTreeMap<String, Vec<PyPerCaseResult>>,
) -> PyResult<Py<PyDict>> {
    let input = hardness_input(results);
    let d = hardness::flip_distribution(&input);
    hardness_dict_flip_distribution(py, &d)
}

/// hardness.hardest_decile_survival: per-adapter survival on the decile.
///
/// `decile` is pre-validated by the wrapper (D-11); the core assumes
/// `0 < decile <= 1`.
#[pyfunction]
fn hardness_hardest_decile_survival(
    py: Python<'_>,
    results: BTreeMap<String, Vec<PyPerCaseResult>>,
    decile: f64,
) -> PyResult<Py<PyDict>> {
    let input = hardness_input(results);
    let h = hardness::hardest_decile_survival(&input, decile);
    hardness_dict_hardest_decile(py, &h)
}

/// hardness.transfer_matrix: cross-adapter transfer ASR.
#[pyfunction]
fn hardness_transfer_matrix(
    py: Python<'_>,
    results: BTreeMap<String, Vec<PyPerCaseResult>>,
    family: Option<String>,
) -> PyResult<Py<PyDict>> {
    let input = hardness_input(results);
    let t = hardness::transfer_matrix(&input, family.as_deref());
    hardness_dict_transfer_matrix(py, &t)
}

/// hardness.analyze_runs: the full M-4 diagnostic report.
#[pyfunction]
fn hardness_analyze_runs(
    py: Python<'_>,
    results: BTreeMap<String, Vec<PyPerCaseResult>>,
    decile: f64,
) -> PyResult<Py<PyDict>> {
    let input = hardness_input(results);
    let r = hardness::analyze_runs(&input, decile);
    let out = PyDict::new(py);
    out.set_item("adapters", &r.adapters)?;
    out.set_item("n_cases", r.n_cases)?;
    out.set_item(
        "flip_distribution",
        hardness_dict_flip_distribution(py, &r.flip_distribution)?,
    )?;
    out.set_item(
        "hardest_decile",
        hardness_dict_hardest_decile(py, &r.hardest_decile)?,
    )?;
    out.set_item(
        "transfer_overall",
        hardness_dict_transfer_matrix(py, &r.transfer_overall)?,
    )?;
    let by_family = PyDict::new(py);
    for (fam, m) in &r.transfer_by_family {
        by_family.set_item(fam, hardness_dict_transfer_matrix(py, m)?)?;
    }
    out.set_item("transfer_by_family", by_family)?;
    Ok(out.into())
}

/// Get a required key from a dict, raising `TypeError` when missing
/// (the wrapper falls back to the reference on `TypeError`).
fn dict_get<'a>(dd: &'a Bound<'_, PyDict>, k: &str) -> PyResult<Bound<'a, PyAny>> {
    dd.get_item(k)?
        .ok_or_else(|| PyTypeError::new_err(format!("internal: missing key {k}")))
}

/// Extract a `HardnessReport` from the wrapper-built plain dict.
///
/// The dict mirrors the dataclass fields with transfer rates as
/// `(src, dst, rate-or-None)` triples. Extraction failures raise
/// `TypeError`; the wrapper falls back to the reference.
fn hardness_report_from_dict(d: &Bound<'_, PyDict>) -> PyResult<hardness::HardnessReport> {
    let adapters: Vec<String> = dict_get(d, "adapters")?
        .extract()
        .map_err(|_| PyTypeError::new_err("internal: adapters is not a list of str"))?;
    let n_cases: usize = dict_get(d, "n_cases")?
        .extract()
        .map_err(|_| PyTypeError::new_err("internal: n_cases is not an int"))?;
    let fd: Bound<'_, PyDict> = dict_get(d, "flip_distribution")?
        .extract()
        .map_err(|_| PyTypeError::new_err("internal: flip_distribution is not a dict"))?;
    let hd: Bound<'_, PyDict> = dict_get(d, "hardest_decile")?
        .extract()
        .map_err(|_| PyTypeError::new_err("internal: hardest_decile is not a dict"))?;
    let flip_distribution = hardness::FlipDistribution {
        adapters: dict_get(&fd, "adapters")?
            .extract()
            .map_err(|_| PyTypeError::new_err("internal: bad flip_distribution.adapters"))?,
        n_cases: dict_get(&fd, "n_cases")?
            .extract()
            .map_err(|_| PyTypeError::new_err("internal: bad flip_distribution.n_cases"))?,
        counts: dict_get(&fd, "counts")?
            .extract()
            .map_err(|_| PyTypeError::new_err("internal: bad flip_distribution.counts"))?,
    };
    let transfer = |dd: &Bound<'_, PyDict>| -> PyResult<hardness::TransferMatrix> {
        let rates_in: Vec<(String, String, Option<f64>)> = dict_get(dd, "rates")?
            .extract()
            .map_err(|_| PyTypeError::new_err("internal: bad transfer.rates"))?;
        Ok(hardness::TransferMatrix {
            adapters: dict_get(dd, "adapters")?
                .extract()
                .map_err(|_| PyTypeError::new_err("internal: bad transfer.adapters"))?,
            family: dict_get(dd, "family")?
                .extract()
                .map_err(|_| PyTypeError::new_err("internal: bad transfer.family"))?,
            n_cases: dict_get(dd, "n_cases")?
                .extract()
                .map_err(|_| PyTypeError::new_err("internal: bad transfer.n_cases"))?,
            flipped_by_source: dict_get(dd, "flipped_by_source")?
                .extract()
                .map_err(|_| PyTypeError::new_err("internal: bad transfer.flipped_by_source"))?,
            rates: rates_in
                .into_iter()
                .map(|(s, dst, v)| ((s, dst), v))
                .collect(),
        })
    };
    let t_overall: Bound<'_, PyDict> = dict_get(d, "transfer_overall")?
        .extract()
        .map_err(|_| PyTypeError::new_err("internal: transfer_overall is not a dict"))?;
    let by_family_in: Bound<'_, PyDict> = dict_get(d, "transfer_by_family")?
        .extract()
        .map_err(|_| PyTypeError::new_err("internal: transfer_by_family is not a dict"))?;
    // Preserve the dict's insertion order (the reference iterates
    // transfer_by_family.items() in insertion order).
    let mut transfer_by_family: Vec<(String, hardness::TransferMatrix)> = Vec::new();
    for (fam, m) in by_family_in.iter() {
        let fam: String = fam
            .extract()
            .map_err(|_| PyTypeError::new_err("internal: transfer_by_family key is not str"))?;
        let m: Bound<'_, PyDict> = m.extract().map_err(|_| {
            PyTypeError::new_err("internal: transfer_by_family value is not a dict")
        })?;
        transfer_by_family.push((fam, transfer(&m)?));
    }
    let report = hardness::HardnessReport {
        adapters,
        n_cases,
        flip_distribution,
        hardest_decile: hardness::HardestDecileSurvival {
            adapters: dict_get(&hd, "adapters")?
                .extract()
                .map_err(|_| PyTypeError::new_err("internal: bad hardest_decile.adapters"))?,
            n_cases: dict_get(&hd, "n_cases")?
                .extract()
                .map_err(|_| PyTypeError::new_err("internal: bad hardest_decile.n_cases"))?,
            decile_size: dict_get(&hd, "decile_size")?
                .extract()
                .map_err(|_| PyTypeError::new_err("internal: bad hardest_decile.decile_size"))?,
            decile_case_ids: dict_get(&hd, "decile_case_ids")?.extract().map_err(|_| {
                PyTypeError::new_err("internal: bad hardest_decile.decile_case_ids")
            })?,
            survived: dict_get(&hd, "survived")?
                .extract()
                .map_err(|_| PyTypeError::new_err("internal: bad hardest_decile.survived"))?,
        },
        transfer_overall: transfer(&t_overall)?,
        transfer_by_family,
    };
    Ok(report)
}

/// hardness.report_text: human-readable M-4 diagnostic tables.
///
/// Takes the wrapper-built plain report dict (see
/// [`hardness_report_from_dict`]).
#[pyfunction]
fn hardness_report_text(d: &Bound<'_, PyDict>) -> PyResult<String> {
    let r = hardness_report_from_dict(d)?;
    hardness::report_text(&r).map_err(|e| PyKeyError::new_err(e.0))
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
    m.add_function(wrap_pyfunction!(flip_direction, m)?)?;
    m.add_function(wrap_pyfunction!(flip_direction_counts, m)?)?;
    m.add_function(wrap_pyfunction!(net_benefit_at_threshold, m)?)?;
    m.add_function(wrap_pyfunction!(economics_e_attacked, m)?)?;
    m.add_function(wrap_pyfunction!(economics_mean_cost_per_decision, m)?)?;
    m.add_function(wrap_pyfunction!(economics_pareto_frontier, m)?)?;
    m.add_function(wrap_pyfunction!(economics_drummond_holte_points, m)?)?;
    m.add_function(wrap_pyfunction!(economics_attacker_cost_multiplier, m)?)?;
    m.add_function(wrap_pyfunction!(economics_gordon_loeb_tripwire, m)?)?;
    m.add_function(wrap_pyfunction!(economics_defense_curve, m)?)?;
    m.add_function(wrap_pyfunction!(economics_risk_coverage_curve, m)?)?;
    m.add_function(wrap_pyfunction!(economics_optimal_threshold, m)?)?;
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
    m.add_function(wrap_pyfunction!(lottery_round4, m)?)?;
    m.add_function(wrap_pyfunction!(lottery_rank_runs, m)?)?;
    m.add_function(wrap_pyfunction!(lottery_kendall_tau, m)?)?;
    m.add_function(wrap_pyfunction!(lottery_pairwise_swap_fraction, m)?)?;
    m.add_function(wrap_pyfunction!(lottery_stability_verdict, m)?)?;
    m.add_function(wrap_pyfunction!(lottery_analysis, m)?)?;
    m.add_function(wrap_pyfunction!(labels_candidate_labels, m)?)?;
    m.add_function(wrap_pyfunction!(labels_non_abstain_placeholder, m)?)?;
    m.add_function(wrap_pyfunction!(invariance_report, m)?)?;
    m.add_function(wrap_pyfunction!(combo_pair_id, m)?)?;
    m.add_function(wrap_pyfunction!(combo_case_id, m)?)?;
    m.add_function(wrap_pyfunction!(combo_parse_case_id, m)?)?;
    m.add_function(wrap_pyfunction!(combo_validate_dict, m)?)?;
    m.add_function(wrap_pyfunction!(combo_metrics_paired_interaction, m)?)?;
    m.add_function(wrap_pyfunction!(combo_metrics_format_interaction, m)?)?;
    m.add_function(wrap_pyfunction!(hardness_flip_distribution, m)?)?;
    m.add_function(wrap_pyfunction!(hardness_hardest_decile_survival, m)?)?;
    m.add_function(wrap_pyfunction!(hardness_transfer_matrix, m)?)?;
    m.add_function(wrap_pyfunction!(hardness_analyze_runs, m)?)?;
    m.add_function(wrap_pyfunction!(hardness_report_text, m)?)?;
    m.add_function(wrap_pyfunction!(stability_flip_agreement, m)?)?;
    m.add_function(wrap_pyfunction!(stability_drift_watch, m)?)?;
    m.add_function(wrap_pyfunction!(calibration_reliability_diagram_svg, m)?)?;
    m.add_function(wrap_pyfunction!(calibration_risk_coverage_diagram_svg, m)?)?;
    Ok(())
}
