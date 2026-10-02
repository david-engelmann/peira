//! Combination-attack (combo) suite: ID helpers and validation.
//!
//! This module ports the validation/ID functions of
//! `python/peira/combo_schema.py` (`combo_pair_id`, `combo_case_id`,
//! `parse_combo_case_id`, `validate_combo_dict`). File IO
//! (`load_combo_cases`) and the `ComboCase` dataclass stay Python by
//! design (see `docs/rust-max-queue.md`).
//!
//! Parity notes:
//! - Case IDs are `combo-<a>-<b>-NNNN-<arm>`; parsing splits on the
//!   last two dashes (`rsplit("-", 2)`), so `<a>-<b>` may itself
//!   contain dashes. `rsplitn(3, '-')` reproduces this exactly.
//! - `combo_pair_id` sorts the two family ids with byte-wise ordering,
//!   which equals Python's codepoint ordering for valid UTF-8.
//! - `combo_case_id` formats the substrate index with `{:04}` —
//!   minimum width 4, no truncation — matching Python's `:04d`.
//! - The substrate-index parser mirrors Python's `int(s)` for the
//!   realistic domain: surrounding whitespace stripped, optional
//!   `+`/`-` sign, ASCII digits, i64 range. The trim matches CPython
//!   exactly (Unicode whitespace except U+001C..=U+001F, which
//!   CPython's `int()` does not strip; see `is_int_whitespace`).
//!   Documented divergences: Python also accepts underscores between
//!   digits (`"1_2"`) and non-ASCII decimal digits; those inputs are
//!   rejected by the Rust parser, and the Python wrapper falls back
//!   to the reference so they parse identically. Indices outside the
//!   i64 range likewise report malformed (and fall back).
//! - Error strings are byte-identical to the reference, including the
//!   `{!r}` interpolations, via [`crate::py_repr`]. Documented
//!   divergence classes, shared with the schema/dataset ports (all
//!   three affect only message text on already-invalid inputs —
//!   accept/reject outcomes, error counts, and exception types are
//!   identical): values containing non-printable non-ASCII outside C1
//!   (e.g. U+200B) render raw here where CPython's `repr()` would emit
//!   `\uNNNN`; dict values render with keys sorted (the JSON boundary
//!   is a `BTreeMap`, so insertion order is lost) where CPython's
//!   `repr()` preserves insertion order; tuples cross the PyO3 boundary
//!   as JSON arrays and render as `[...]` where the reference shows
//!   `(...)`.
//! - The arm-content rule compares benign/attacked inputs with
//!   Python `==` semantics for JSON values: `1 == 1.0` and
//!   `True == 1` hold (unlike `serde_json`'s structural equality).
//!   Non-finite floats cannot occur: the PyO3 boundary rejects them
//!   and the Python wrapper falls back to the reference.
//! - `(d["benign"] or {}).get("input")`: falsy values (`None`,
//!   `False`, `0`, `""`, `[]`, `{}`) behave as `{}`; a truthy
//!   non-dict raises `AttributeError` in the reference. The core
//!   reports those as [`StructuralError`] and the Python wrapper
//!   re-runs the reference so the natural exception surfaces.

use crate::py_repr;
use serde_json::{Map, Number, Value};

/// Required keys of a combo case dict, in the reference's check order.
const REQUIRED_KEYS: [&str; 10] = [
    "case_id",
    "family",
    "primitive",
    "severity",
    "benign",
    "attacked",
    "combo_arm",
    "combo_substrate",
    "combo_pair",
    "transform_order",
];

/// (pair_id, family_a, family_b); families stored alphabetically.
///
/// Mirrors `python/peira/combo_schema.py::COMBO_PAIRS`.
const COMBO_PAIRS: [(&str, &str, &str); 2] = [
    ("combo-dfl-ind", "distractor_flooding", "indirection"),
    ("combo-san-csp", "score_anchoring", "confidence_spoofing"),
];

/// Valid combo arms. Mirrors `COMBO_ARMS`.
const COMBO_ARMS: [&str; 4] = ["ctrl", "a", "b", "ab"];

/// Valid primary outcomes. Mirrors `COMBO_PRIMARY_OUTCOMES`.
const COMBO_PRIMARY_OUTCOMES: [&str; 3] = ["flip", "abstain", "joint"];

/// Valid primitives for combo cases.
const COMBO_PRIMITIVES: [&str; 3] = ["choice", "score", "abstain"];

/// Valid severities for combo cases.
const COMBO_SEVERITIES: [&str; 4] = ["critical", "high", "medium", "low"];

/// Error from the combo ID/validation functions.
///
/// `is_key_error` selects the Python exception type the PyO3 binding
/// raises: `KeyError` (unknown pair lookups) vs `ValueError`
/// (everything else). `message` is byte-identical to the reference.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ComboError {
    is_key_error: bool,
    message: String,
}

impl ComboError {
    /// True when the reference raises `KeyError` for this error.
    pub fn is_key_error(&self) -> bool {
        self.is_key_error
    }

    /// The exact message the Python reference raises.
    pub fn message(&self) -> &str {
        &self.message
    }

    fn key(message: String) -> Self {
        ComboError {
            is_key_error: true,
            message,
        }
    }

    fn value(message: String) -> Self {
        ComboError {
            is_key_error: false,
            message,
        }
    }
}

impl std::fmt::Display for ComboError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.message)
    }
}

/// Marker: the input violates the structural contract the Rust port
/// handles (non-string `case_id`, truthy non-dict `benign`/`attacked`).
/// The Python wrapper catches this and re-runs the pure-Python
/// reference, which raises the natural Python exception
/// (`AttributeError`).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct StructuralError;

fn pair_families(pair_id: &str) -> Option<(&'static str, &'static str)> {
    COMBO_PAIRS
        .iter()
        .find(|(pid, _, _)| *pid == pair_id)
        .map(|(_, a, b)| (*a, *b))
}

/// Return the canonical combo pair id for two family ids.
///
/// Families are ordered alphabetically so (A, B) and (B, A) map to
/// the same pair. Mirrors
/// `python/peira/combo_schema.py::combo_pair_id`; unknown pairs raise
/// `KeyError` with the families in their original order.
pub fn combo_pair_id(family_a: &str, family_b: &str) -> Result<String, ComboError> {
    let (a, b) = if family_a <= family_b {
        (family_a, family_b)
    } else {
        (family_b, family_a)
    };
    for (pair_id, fa, fb) in COMBO_PAIRS {
        if fa == a && fb == b {
            return Ok(pair_id.to_owned());
        }
    }
    Err(ComboError::key(format!(
        "unknown combo pair: {family_a} x {family_b}"
    )))
}

/// Build the canonical case id for one arm of a substrate.
///
/// Mirrors `python/peira/combo_schema.py::combo_case_id`.
pub fn combo_case_id(pair_id: &str, substrate_idx: i64, arm: &str) -> Result<String, ComboError> {
    if pair_families(pair_id).is_none() {
        return Err(ComboError::key(format!("unknown combo pair id: {pair_id}")));
    }
    if !COMBO_ARMS.contains(&arm) {
        return Err(ComboError::value(format!("unknown combo arm: {arm}")));
    }
    Ok(format!("{pair_id}-{substrate_idx:04}-{arm}"))
}

/// True when a substrate-index string is rejected by [`parse_py_int`]
/// but accepted by CPython's `int()`: underscores between digits or
/// non-ASCII decimal digits. Over-approximates (any non-ASCII char
/// triggers it); a spurious fallback just re-runs the reference,
/// which always gives the right answer.
fn index_needs_reference_fallback(s: &str) -> bool {
    s.chars().any(|c| c == '_' || !c.is_ascii())
}

/// Whitespace as stripped by CPython's `int()`: Unicode whitespace
/// except U+001C..=U+001F (the C0 separators), which CPython does not
/// strip even though Rust's `char::is_whitespace` reports them.
fn is_int_whitespace(c: char) -> bool {
    c.is_whitespace() && !('\u{1c}'..='\u{1f}').contains(&c)
}

/// Parse a Python-`int()`-shaped decimal string to i64.
///
/// Mirrors `int(s)` for the realistic domain: surrounding whitespace
/// stripped, one optional sign, ASCII digits, i64 range. Returns
/// `None` otherwise.
///
/// The trim matches CPython exactly: it strips Unicode whitespace
/// *except* U+001C..=U+001F, which CPython's `int()` does not strip
/// (Rust's `char::is_whitespace` includes them).
fn parse_py_int(s: &str) -> Option<i64> {
    let t = s.trim_matches(is_int_whitespace);
    let (sign, digits) = match t.strip_prefix('+') {
        Some(rest) => (1i128, rest),
        None => match t.strip_prefix('-') {
            Some(rest) => (-1i128, rest),
            None => (1i128, t),
        },
    };
    if digits.is_empty() || !digits.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    let mut acc: i128 = 0;
    for b in digits.bytes() {
        acc = acc * 10 + (b - b'0') as i128;
    }
    i64::try_from(sign * acc).ok()
}

/// Split a combo case id into (pair_id, substrate_idx, arm).
///
/// Mirrors `python/peira/combo_schema.py::parse_combo_case_id`.
pub fn parse_combo_case_id(case_id: &str) -> Result<(String, i64, String), ComboError> {
    let mut parts = case_id.rsplitn(3, '-');
    let (Some(arm), Some(idx_s), Some(pair_id)) = (parts.next(), parts.next(), parts.next()) else {
        return Err(ComboError::value(format!(
            "malformed combo case id: {case_id}"
        )));
    };
    if pair_families(pair_id).is_none() {
        return Err(ComboError::value(format!(
            "unknown combo pair in case id: {case_id}"
        )));
    }
    if !COMBO_ARMS.contains(&arm) {
        return Err(ComboError::value(format!(
            "unknown combo arm in case id: {case_id}"
        )));
    }
    let idx = parse_py_int(idx_s).ok_or_else(|| {
        ComboError::value(format!("malformed substrate index in case id: {case_id}"))
    })?;
    Ok((pair_id.to_owned(), idx, arm.to_owned()))
}

/// Python truthiness for JSON values.
fn py_truthy(v: &Value) -> bool {
    match v {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                i != 0
            } else if let Some(u) = n.as_u64() {
                u != 0
            } else {
                n.as_f64().is_some_and(|f| f != 0.0)
            }
        }
        Value::String(s) => !s.is_empty(),
        Value::Array(a) => !a.is_empty(),
        Value::Object(m) => !m.is_empty(),
    }
}

fn num_as_i128(n: &Number) -> Option<i128> {
    n.as_i64()
        .map(|v| v as i128)
        .or_else(|| n.as_u64().map(|v| v as i128))
}

/// Exact Python `int == float` for an i128 against an f64.
///
/// True iff the float is integral and equals the integer exactly;
/// `i as f64` rounding is detected via the round-trip check, so
/// `2**53 + 1 == 2**53` is false, matching Python.
fn int_eq_float(i: i128, f: f64) -> bool {
    if !f.is_finite() || f.fract() != 0.0 {
        return false;
    }
    let fi = i as f64;
    if fi != f || !fi.is_finite() {
        return false;
    }
    // `fi as i128` saturates on overflow; a saturated cast can never
    // equal the in-range `i`, so this is exact.
    fi as i128 == i
}

/// Python numeric `==` for two JSON numbers.
fn py_num_eq(a: &Number, b: &Number) -> bool {
    match (num_as_i128(a), num_as_i128(b)) {
        (Some(x), Some(y)) => x == y,
        // At least one side is a float (non-finite impossible here:
        // the PyO3 boundary rejects them).
        (Some(i), None) => int_eq_float(i, b.as_f64().unwrap_or(f64::NAN)),
        (None, Some(i)) => int_eq_float(i, a.as_f64().unwrap_or(f64::NAN)),
        (None, None) => a.as_f64() == b.as_f64(),
    }
}

/// Python `==` for JSON-shaped values.
///
/// Numbers compare numerically across int/float (`1 == 1.0`), and
/// bools compare against numbers (`True == 1`); containers recurse;
/// mismatched types are unequal.
fn py_json_eq(a: &Value, b: &Value) -> bool {
    match (a, b) {
        (Value::Null, Value::Null) => true,
        (Value::Bool(x), Value::Bool(y)) => x == y,
        (Value::String(x), Value::String(y)) => x == y,
        (Value::Array(x), Value::Array(y)) => {
            x.len() == y.len() && x.iter().zip(y.iter()).all(|(u, v)| py_json_eq(u, v))
        }
        (Value::Object(x), Value::Object(y)) => {
            x.len() == y.len()
                && x.iter()
                    .all(|(k, u)| y.get(k).is_some_and(|v| py_json_eq(u, v)))
        }
        (Value::Number(x), Value::Number(y)) => py_num_eq(x, y),
        (Value::Bool(b), Value::Number(n)) => py_num_eq(&Number::from(*b as i64), n),
        (Value::Number(n), Value::Bool(b)) => py_num_eq(n, &Number::from(*b as i64)),
        _ => false,
    }
}

fn py_json_eq_opt(a: Option<&Value>, b: Option<&Value>) -> bool {
    match (a, b) {
        (None, None) => true,
        (Some(x), Some(y)) => py_json_eq(x, y),
        _ => false,
    }
}

/// Mirror `(d[key] or {}).get("input")`.
///
/// Falsy values behave as `{}` (missing input → `None`); a truthy
/// non-dict is a [`StructuralError`] (the reference raises
/// `AttributeError` calling `.get` on it).
fn side_input<'a>(
    d: &'a Map<String, Value>,
    key: &str,
) -> Result<Option<&'a Value>, StructuralError> {
    let v = &d[key];
    if !py_truthy(v) {
        return Ok(None);
    }
    match v.as_object() {
        Some(map) => Ok(map.get("input")),
        None => Err(StructuralError),
    }
}

/// Error from [`validate_combo_dict`].
///
/// The reference raises two different exceptions out of
/// `validate_combo_dict` depending on the input: `AttributeError` for
/// inputs that violate the structural contract (non-string case_id,
/// truthy non-dict benign/attacked — `.get`/`.rsplit` on a non-dict),
/// and `KeyError` when `primary_outcome` is absent (it is not in the
/// required-keys list, so `d["primary_outcome"]` raises). The PyO3
/// binding maps `Structural` to an internal `AttributeError` the
/// Python wrapper catches to fall back to the reference, and `Key` to
/// the reference's `KeyError`. `Structural` is also used when the
/// case-id substrate index is one the reference accepts but the Rust
/// parser rejects (underscores, non-ASCII digits): the reference
/// validator calls the public `parse_combo_case_id`, which falls back
/// to Python's `int()`, so the whole validation must defer to it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ValidateError {
    Structural,
    Key(ComboError),
}

/// Validate one combo case dict; returns the list of error strings.
///
/// Mirrors `python/peira/combo_schema.py::validate_combo_dict`
/// exactly, including error order and early returns: missing keys
/// return immediately; a case-id parse failure returns immediately;
/// everything else accumulates.
pub fn validate_combo_dict(d: &Map<String, Value>) -> Result<Vec<String>, ValidateError> {
    let mut errors: Vec<String> = Vec::new();
    for key in REQUIRED_KEYS {
        if !d.contains_key(key) {
            errors.push(format!("missing required key: {key}"));
        }
    }
    if !errors.is_empty() {
        return Ok(errors);
    }

    let case_id = d["case_id"].as_str().ok_or(ValidateError::Structural)?;
    let (pair_id, idx, arm) = match parse_combo_case_id(case_id) {
        Ok(parsed) => parsed,
        Err(e) => {
            // The reference validator calls the public `parse_combo_case_id`,
            // which falls back to Python's `int()` for indices the Rust
            // parser rejects (underscores, non-ASCII digits). If this input
            // is one the reference accepts, defer to it via a Structural
            // fallback instead of reporting a malformed index the reference
            // would not report.
            if e.message()
                .starts_with("malformed substrate index in case id: ")
                && case_id
                    .rsplit('-')
                    .nth(1)
                    .is_some_and(index_needs_reference_fallback)
            {
                return Err(ValidateError::Structural);
            }
            return Ok(vec![e.message().to_owned()]);
        }
    };

    if !matches!(&d["family"], Value::String(s) if s == &pair_id) {
        errors.push(format!(
            "family {} does not match case-id pair {}",
            py_repr::py_repr_value(&d["family"]),
            py_repr::py_repr_str(&pair_id),
        ));
    }
    if !matches!(&d["combo_arm"], Value::String(s) if s == &arm) {
        errors.push(format!(
            "combo_arm {} does not match case-id arm {}",
            py_repr::py_repr_value(&d["combo_arm"]),
            py_repr::py_repr_str(&arm),
        ));
    }
    let expected_substrate = format!("{pair_id}-{idx:04}");
    if !matches!(&d["combo_substrate"], Value::String(s) if s == &expected_substrate) {
        errors.push(format!(
            "combo_substrate {} does not match expected {}",
            py_repr::py_repr_value(&d["combo_substrate"]),
            py_repr::py_repr_str(&expected_substrate),
        ));
    }

    if !matches!(&d["primitive"], Value::String(s) if COMBO_PRIMITIVES.contains(&s.as_str())) {
        errors.push(format!(
            "bad primitive: {}",
            py_repr::py_repr_value(&d["primitive"])
        ));
    }
    if !matches!(&d["severity"], Value::String(s) if COMBO_SEVERITIES.contains(&s.as_str())) {
        errors.push(format!(
            "bad severity: {}",
            py_repr::py_repr_value(&d["severity"])
        ));
    }
    // `primary_outcome` is not in the required-keys list: when it is
    // absent the reference's `d["primary_outcome"]` raises
    // KeyError("primary_outcome"), which propagates to the caller (not
    // into the error list). The message is the bare key: `str()` of the
    // raised KeyError adds the quotes, like the reference.
    let primary_outcome = d
        .get("primary_outcome")
        .ok_or_else(|| ValidateError::Key(ComboError::key("primary_outcome".to_owned())))?;
    if !matches!(primary_outcome, Value::String(s) if COMBO_PRIMARY_OUTCOMES.contains(&s.as_str()))
    {
        errors.push(format!(
            "bad primary_outcome: {}",
            py_repr::py_repr_value(primary_outcome)
        ));
    }

    // Arm-content rules (design 6b.3).
    let benign_input = side_input(d, "benign").map_err(|_| ValidateError::Structural)?;
    let attacked_input = side_input(d, "attacked").map_err(|_| ValidateError::Structural)?;
    if arm == "ctrl" && !py_json_eq_opt(benign_input, attacked_input) {
        errors.push("control arm attacked input must equal benign input".to_owned());
    }
    if arm != "ctrl" && py_json_eq_opt(benign_input, attacked_input) {
        errors.push(format!(
            "arm {} attacked input identical to benign input",
            py_repr::py_repr_str(&arm),
        ));
    }

    for side in ["benign", "attacked"] {
        // `d.get(side) or {}`: falsy → empty map; truthy non-dict is a
        // structural error (reference raises AttributeError).
        let empty = Map::new();
        let s: &Map<String, Value> = if !py_truthy(&d[side]) {
            &empty
        } else if let Value::Object(m) = &d[side] {
            m
        } else {
            return Err(ValidateError::Structural);
        };
        if !matches!(s.get("input"), Some(Value::Object(_))) {
            errors.push(format!("{side} missing input dict"));
        }
        if side == "benign" && !s.contains_key("expected_decision") {
            errors.push("benign missing expected_decision".to_owned());
        }
        if side == "attacked" && !s.contains_key("target_decision") {
            errors.push("attacked missing target_decision".to_owned());
        }
    }

    Ok(errors)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn valid_case() -> Map<String, Value> {
        json!({
            "case_id": "combo-dfl-ind-0001-a",
            "family": "combo-dfl-ind",
            "primitive": "choice",
            "severity": "high",
            "benign": {"input": {"text": "x"}, "expected_decision": "approve"},
            "attacked": {"input": {"text": "y"}, "target_decision": "deny"},
            "combo_arm": "a",
            "combo_substrate": "combo-dfl-ind-0001",
            "combo_pair": "distractor_flooding x indirection",
            "transform_order": "distractor_flooding then indirection",
            "primary_outcome": "flip",
        })
        .as_object()
        .unwrap()
        .clone()
    }

    #[test]
    fn pair_id_orders_alphabetically() {
        assert_eq!(
            combo_pair_id("distractor_flooding", "indirection").unwrap(),
            "combo-dfl-ind"
        );
        assert_eq!(
            combo_pair_id("indirection", "distractor_flooding").unwrap(),
            "combo-dfl-ind"
        );
    }

    #[test]
    fn pair_id_san_csp_quirk_matches_reference() {
        // The reference table stores ("score_anchoring",
        // "confidence_spoofing") but looks up the SORTED pair
        // ("confidence_spoofing", "score_anchoring"), so combo-san-csp
        // never resolves. Verified against the Python reference: it
        // raises the same KeyError. Parity, not a fix.
        let err = combo_pair_id("score_anchoring", "confidence_spoofing").unwrap_err();
        assert!(err.is_key_error());
        assert_eq!(
            err.message(),
            "unknown combo pair: score_anchoring x confidence_spoofing"
        );
    }

    #[test]
    fn pair_id_unknown_is_key_error_original_order() {
        let err = combo_pair_id("zzz", "aaa").unwrap_err();
        assert!(err.is_key_error());
        assert_eq!(err.message(), "unknown combo pair: zzz x aaa");
    }

    #[test]
    fn case_id_format_zero_padded() {
        assert_eq!(
            combo_case_id("combo-dfl-ind", 1, "a").unwrap(),
            "combo-dfl-ind-0001-a"
        );
        assert_eq!(
            combo_case_id("combo-san-csp", 12345, "ab").unwrap(),
            "combo-san-csp-12345-ab"
        );
    }

    #[test]
    fn case_id_unknown_pair_is_key_error() {
        let err = combo_case_id("combo-nope", 1, "a").unwrap_err();
        assert!(err.is_key_error());
        assert_eq!(err.message(), "unknown combo pair id: combo-nope");
    }

    #[test]
    fn case_id_unknown_arm_is_value_error() {
        let err = combo_case_id("combo-dfl-ind", 1, "c").unwrap_err();
        assert!(!err.is_key_error());
        assert_eq!(err.message(), "unknown combo arm: c");
    }

    #[test]
    fn parse_round_trip() {
        assert_eq!(
            parse_combo_case_id("combo-dfl-ind-0001-a").unwrap(),
            ("combo-dfl-ind".to_owned(), 1, "a".to_owned())
        );
        assert_eq!(
            parse_combo_case_id("combo-san-csp-0042-ctrl").unwrap(),
            ("combo-san-csp".to_owned(), 42, "ctrl".to_owned())
        );
    }

    #[test]
    fn parse_malformed_variants() {
        for bad in ["", "a-b"] {
            let err = parse_combo_case_id(bad).unwrap_err();
            assert_eq!(err.message(), &format!("malformed combo case id: {bad}"));
        }
        // These split into 3 parts via rsplit("-", 2), so they are not
        // "malformed": they fail the pair lookup instead.
        for bad in ["combo-dfl-ind", "combo-dfl-ind-0001"] {
            let err = parse_combo_case_id(bad).unwrap_err();
            assert_eq!(
                err.message(),
                &format!("unknown combo pair in case id: {bad}")
            );
        }
    }

    #[test]
    fn parse_unknown_pair_and_arm() {
        let err = parse_combo_case_id("combo-zzz-0001-a").unwrap_err();
        assert_eq!(
            err.message(),
            "unknown combo pair in case id: combo-zzz-0001-a"
        );
        let err = parse_combo_case_id("combo-dfl-ind-0001-c").unwrap_err();
        assert_eq!(
            err.message(),
            "unknown combo arm in case id: combo-dfl-ind-0001-c"
        );
    }

    #[test]
    fn parse_bad_index() {
        for bad_idx in ["abcd", "", "1.5", "0x10"] {
            let id = format!("combo-dfl-ind-{bad_idx}-a");
            let err = parse_combo_case_id(&id).unwrap_err();
            assert_eq!(
                err.message(),
                &format!("malformed substrate index in case id: {id}")
            );
        }
    }

    #[test]
    fn parse_index_whitespace_and_sign() {
        // Mirrors Python int(): surrounding whitespace and +/- signs.
        assert_eq!(parse_combo_case_id("combo-dfl-ind- 12 -a").unwrap().1, 12);
        assert_eq!(parse_combo_case_id("combo-dfl-ind-+0007-a").unwrap().1, 7);
    }

    #[test]
    fn parse_index_whitespace_matches_cpython_exactly() {
        // CPython int() strips U+00A0 (and other Unicode whitespace)
        // but NOT U+001C..=U+001F. The trim must match exactly:
        // accepting "\x1c1" would diverge from the reference.
        assert_eq!(parse_combo_case_id("combo-dfl-ind-\u{a0}1-a").unwrap().1, 1);
        assert!(parse_combo_case_id("combo-dfl-ind-\u{1c}1-a").is_err());
        assert!(parse_combo_case_id("combo-dfl-ind-\u{1f}1-a").is_err());
    }

    #[test]
    fn validate_ok_case() {
        assert!(validate_combo_dict(&valid_case()).unwrap().is_empty());
    }

    #[test]
    fn validate_underscore_index_defers_to_reference() {
        // Python int("1_2") == 12, so the reference validator accepts
        // this case id. The Rust validator cannot reproduce that, so it
        // reports Structural and the Python wrapper re-runs the reference.
        let mut d = valid_case();
        d["case_id"] = json!("combo-dfl-ind-1_2-a");
        d["combo_substrate"] = json!("combo-dfl-ind-0012");
        assert_eq!(validate_combo_dict(&d), Err(ValidateError::Structural));
    }

    #[test]
    fn validate_missing_keys_early_return() {
        let d = Map::new();
        let errors = validate_combo_dict(&d).unwrap();
        assert_eq!(errors.len(), 10);
        assert_eq!(errors[0], "missing required key: case_id");
        assert_eq!(errors[9], "missing required key: transform_order");
    }

    #[test]
    fn validate_bad_case_id_early_return() {
        let mut d = valid_case();
        d["case_id"] = json!("nope");
        let errors = validate_combo_dict(&d).unwrap();
        assert_eq!(errors, vec!["malformed combo case id: nope"]);
    }

    #[test]
    fn validate_mismatch_messages() {
        let mut d = valid_case();
        d["family"] = json!("combo-san-csp");
        d["combo_arm"] = json!("b");
        d["combo_substrate"] = json!("combo-dfl-ind-0002");
        let errors = validate_combo_dict(&d).unwrap();
        assert_eq!(
            errors,
            vec![
                "family 'combo-san-csp' does not match case-id pair 'combo-dfl-ind'",
                "combo_arm 'b' does not match case-id arm 'a'",
                "combo_substrate 'combo-dfl-ind-0002' does not match expected 'combo-dfl-ind-0001'",
            ]
        );
    }

    #[test]
    fn validate_bad_vocab() {
        let mut d = valid_case();
        d["primitive"] = json!("vote");
        d["severity"] = json!("extreme");
        d["primary_outcome"] = json!("vibes");
        let errors = validate_combo_dict(&d).unwrap();
        assert_eq!(
            errors,
            vec![
                "bad primitive: 'vote'",
                "bad severity: 'extreme'",
                "bad primary_outcome: 'vibes'",
            ]
        );
    }

    #[test]
    fn validate_control_arm_inputs_must_match() {
        let mut d = valid_case();
        d["case_id"] = json!("combo-dfl-ind-0001-ctrl");
        d["combo_arm"] = json!("ctrl");
        // attacked input differs from benign -> error.
        let errors = validate_combo_dict(&d).unwrap();
        assert_eq!(
            errors,
            vec!["control arm attacked input must equal benign input"]
        );
        // Equal inputs -> clean.
        d["attacked"] = json!({"input": {"text": "x"}, "target_decision": "deny"});
        assert!(validate_combo_dict(&d).unwrap().is_empty());
    }

    #[test]
    fn validate_non_control_arm_inputs_must_differ() {
        let mut d = valid_case();
        d["attacked"] = json!({"input": {"text": "x"}, "target_decision": "deny"});
        let errors = validate_combo_dict(&d).unwrap();
        assert_eq!(
            errors,
            vec!["arm 'a' attacked input identical to benign input"]
        );
    }

    #[test]
    fn validate_json_eq_numeric_tower() {
        // Python == semantics: 1 == 1.0, True == 1.
        assert!(py_json_eq(&json!(1), &json!(1.0)));
        assert!(py_json_eq(&json!(true), &json!(1)));
        assert!(py_json_eq(&json!(true), &json!(1.0)));
        assert!(!py_json_eq(&json!(1), &json!(1.5)));
        assert!(py_json_eq(&json!(0), &json!(false)));
        // Precision: 2**53+1 != 2**53 as f64.
        assert!(!py_json_eq(
            &json!(9007199254740993i64),
            &json!(9007199254740992.0)
        ));
        assert!(py_json_eq(
            &json!({"a": [1, {"b": 2.0}]}),
            &json!({"a": [1.0, {"b": 2}]})
        ));
    }

    #[test]
    fn validate_missing_input_dicts_and_decisions() {
        // Both sides lack "input": inputs compare None == None, so the
        // arm-content rule fires, then the per-side checks.
        let mut d = valid_case();
        d["benign"] = json!({"expected_decision": "approve"});
        d["attacked"] = json!({"target_decision": "deny"});
        let errors = validate_combo_dict(&d).unwrap();
        assert_eq!(
            errors,
            vec![
                "arm 'a' attacked input identical to benign input",
                "benign missing input dict",
                "attacked missing input dict",
            ]
        );
    }

    #[test]
    fn structural_non_string_case_id() {
        let mut d = valid_case();
        d["case_id"] = json!(5);
        assert_eq!(
            validate_combo_dict(&d).unwrap_err(),
            ValidateError::Structural
        );
    }

    #[test]
    fn structural_truthy_non_dict_side() {
        let mut d = valid_case();
        d["benign"] = json!("x");
        assert_eq!(
            validate_combo_dict(&d).unwrap_err(),
            ValidateError::Structural
        );
    }

    #[test]
    fn missing_primary_outcome_is_key_error() {
        // primary_outcome is not a required key: the reference's
        // d["primary_outcome"] raises KeyError, which propagates.
        let mut d = valid_case();
        d.remove("primary_outcome");
        let err = validate_combo_dict(&d).unwrap_err();
        match err {
            ValidateError::Key(e) => {
                assert!(e.is_key_error());
                assert_eq!(e.message(), "primary_outcome");
            }
            other => panic!("expected Key error, got {other:?}"),
        }
    }

    #[test]
    fn ab_arm_is_valid_non_control() {
        assert_eq!(
            combo_case_id("combo-san-csp", 3, "ab").unwrap(),
            "combo-san-csp-0003-ab"
        );
        let mut d = valid_case();
        d["case_id"] = json!("combo-dfl-ind-0001-ab");
        d["combo_arm"] = json!("ab");
        // ab is a non-control arm: identical inputs are an error.
        d["attacked"] = json!({"input": {"text": "x"}, "target_decision": "deny"});
        let errors = validate_combo_dict(&d).unwrap();
        assert_eq!(
            errors,
            vec!["arm 'ab' attacked input identical to benign input"]
        );
    }
}
