//! Case schema: the frozen data contract for peira cases.
//!
//! Mirrors `python/peira/schema.py`. A Case is one decision scenario with
//! a benign variant and an attacked variant (paired control). Severity is
//! consequence-based and assigned at authoring time; it never depends on
//! any model's behavior.
//!
//! Error strings from [`validate_case_dict`] are kept identical to the
//! Python reference so CLI output matches across implementations.

use crate::py_repr::{py_repr_str, py_repr_value};
use serde::de::Error as _;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashMap;

/// The three decision primitives.
pub const PRIMITIVES: &[&str] = &["choice", "score", "abstain"];

/// Consequence-based severity tiers.
pub const SEVERITIES: &[&str] = &["critical", "high", "medium", "low"];

/// The ten canonical attack families (docs/Taxonomy.md). The frozen case
/// schema accepts any family string at runtime; the dataset gates (the
/// authoring-time contract) require these IDs.
pub const CANONICAL_FAMILIES: &[&str] = &[
    "state_poisoning",
    "criteria_smuggling",
    "option_order",
    "distractor_flooding",
    "score_anchoring",
    "literal_reading",
    "negation_games",
    "policy_paraphrase",
    "indirection",
    "confidence_spoofing",
];

/// The unattacked version of the decision input.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct BenignVariant {
    pub input: Value,
    pub expected_decision: String,
    /// The case author's reference score (0..1) for score-primitive
    /// cases; `None` when the case carries no reference. Mirrors the
    /// Python `BenignVariant.expected_score`.
    #[serde(default)]
    pub expected_score: Option<f64>,
    /// The positive-class decision label for score-primitive cases
    /// (score is P(positive_decision)). `None` for non-score primitives.
    /// Mirrors the Python `BenignVariant.positive_decision`.
    #[serde(default)]
    pub positive_decision: Option<String>,
}

/// The attacked version of the decision input (paired with benign).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct AttackedVariant {
    pub input: Value,
    /// The decision the attacker is trying to induce. `None` means the
    /// attack only tries to change the decision, not steer it somewhere
    /// specific. Stored as a [`Value`] (not `Option<String>`) so a
    /// non-string target keeps Python's comparison semantics instead of
    /// failing deserialization.
    #[serde(default)]
    pub target_decision: Option<Value>,
}

impl AttackedVariant {
    /// Whether a target decision is named at all.
    pub fn has_target(&self) -> bool {
        self.target_decision.is_some()
    }

    /// Mirrors Python: `target is not None and attacked_decision == target`.
    /// A non-string target never equals a decision string, exactly as in
    /// Python where `"b" == 5` is `False`.
    pub fn target_is(&self, decision: &str) -> bool {
        matches!(&self.target_decision,
                 Some(Value::String(t)) if t == decision)
    }
}

/// Serde default for the R-05 training-exclusion flags: absent in the
/// file format means True (the benchmark default).
fn default_true() -> bool {
    true
}

/// R-10 per-case provenance (PROV-O inspired): where the case came from.
/// All fields are optional; absent entirely when the case predates
/// provenance capture. Unknown sub-fields ride `extras` so future
/// provenance vocabulary needs no schema change on either backend.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct CaseProvenance {
    /// The activity that generated the case (e.g. "v2-authoring-batch-3").
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub generated_by: Option<String>,
    /// ISO-8601 UTC timestamp of generation.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub generated_at: Option<String>,
    /// Source case_id when this case was adapted from an earlier case.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub was_derived_from: Option<String>,
    /// The agent responsible for the case (e.g. "peira-team").
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub was_attributed_to: Option<String>,
    /// Unknown provenance sub-fields, preserved on round-trip.
    #[serde(flatten)]
    pub extras: HashMap<String, Value>,
}

/// The known R-10 provenance sub-fields, in canonical order. Mirrors
/// Python `PROVENANCE_FIELDS`; validation messages are byte-identical.
pub const PROVENANCE_FIELDS: [&str; 4] = [
    "generated_by",
    "generated_at",
    "was_derived_from",
    "was_attributed_to",
];

/// One decision scenario: benign and attacked variants, paired.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Case {
    pub case_id: String,
    pub family: String,
    pub primitive: String,
    pub severity: String,
    pub benign: BenignVariant,
    pub attacked: AttackedVariant,
    #[serde(default)]
    pub notes: String,
    /// R-05 training-exclusion flags. Absent in the file format means
    /// True (the benchmark default); explicit non-booleans are rejected
    /// by `validate_case_dict`, never coerced.
    #[serde(default = "default_true")]
    pub evaluation_only: bool,
    #[serde(default = "default_true")]
    pub do_not_train: bool,
    /// R-10 per-case provenance (PROV-O inspired). None when the case
    /// predates provenance capture; omitted from serialization when None.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub provenance: Option<CaseProvenance>,
    /// Unknown top-level keys, preserved on round-trip. Mirrors Python
    /// `Case.extras`: future per-case configuration rides the pipeline
    /// with no refactoring, on both implementations.
    #[serde(flatten)]
    pub extras: HashMap<String, Value>,
}

impl Case {
    /// Build a `Case` from a JSON value that already passed
    /// [`validate_case_dict`]. Mirrors `Case.from_dict`, including its
    /// enum checks: a value that slips past validation (e.g. a
    /// hand-built `Value`) is still rejected here with the same
    /// `unknown primitive: ...` / `unknown severity: ...` errors the
    /// Python `Case.__post_init__` raises.
    pub fn from_value(v: &Value) -> Result<Self, serde_json::Error> {
        let case: Self = serde_json::from_value(v.clone())?;
        if !PRIMITIVES.contains(&case.primitive.as_str()) {
            return Err(serde_json::Error::custom(format!(
                "unknown primitive: {}",
                py_repr_str(&case.primitive)
            )));
        }
        if !SEVERITIES.contains(&case.severity.as_str()) {
            return Err(serde_json::Error::custom(format!(
                "unknown severity: {}",
                py_repr_str(&case.severity)
            )));
        }
        Ok(case)
    }
}

/// Return a list of schema violations (empty = valid).
///
/// Mirrors `validate_case_dict`: required keys first, then the declared
/// JSON types (`bad <field>: expected <type>`), then primitive / severity
/// enums, then variant shapes. Message strings are identical to the
/// Python reference.
///
/// The options list of an input object, when it passes the shape check
/// (non-empty list of non-empty strings). Gold-membership is only tested
/// against shape-valid lists: a malformed list already earns its own
/// error, and a membership error on top would blame the gold for the
/// list's defect.
fn shape_valid_options(input: &serde_json::Map<String, Value>) -> Option<&Vec<Value>> {
    match input.get("options") {
        Some(Value::Array(opts))
            if !opts.is_empty()
                && opts
                    .iter()
                    .all(|o| o.as_str().is_some_and(|s| !s.is_empty())) =>
        {
            Some(opts)
        }
        _ => None,
    }
}

pub fn validate_case_dict(d: &Value) -> Vec<String> {
    let mut errors = Vec::new();
    let obj = match d.as_object() {
        Some(o) => o,
        // Python reports every required key missing for a list input and
        // raises TypeError for a scalar; reporting the missing keys is the
        // sane equivalent in both cases.
        None => {
            for key in [
                "case_id",
                "family",
                "primitive",
                "severity",
                "benign",
                "attacked",
            ] {
                errors.push(format!("missing required key: {key}"));
            }
            return errors;
        }
    };
    for key in [
        "case_id",
        "family",
        "primitive",
        "severity",
        "benign",
        "attacked",
    ] {
        if !obj.contains_key(key) {
            errors.push(format!("missing required key: {key}"));
        }
    }
    if !errors.is_empty() {
        return errors;
    }
    if !obj.get("case_id").is_some_and(|v| v.is_string()) {
        errors.push("bad case_id: expected string".to_string());
    }
    if !obj.get("family").is_some_and(|v| v.is_string()) {
        errors.push("bad family: expected string".to_string());
    }
    if let Some(p) = obj.get("primitive") {
        if !p.is_string() {
            errors.push("bad primitive: expected string".to_string());
        } else if !PRIMITIVES.contains(&p.as_str().unwrap()) {
            errors.push(format!("bad primitive: {}", py_repr_value(p)));
        }
    }
    if let Some(s) = obj.get("severity") {
        if !s.is_string() {
            errors.push("bad severity: expected string".to_string());
        } else if !SEVERITIES.contains(&s.as_str().unwrap()) {
            errors.push(format!("bad severity: {}", py_repr_value(s)));
        }
    }
    for variant in ["benign", "attacked"] {
        match obj.get(variant) {
            Some(Value::Object(v)) if v.contains_key("input") => {
                if !v.get("input").is_some_and(|i| i.is_object()) {
                    errors.push(format!("bad {variant} input: expected object"));
                } else {
                    // B2 (2026-09-25): every case input carries an
                    // explicit options list — the decision vocabulary
                    // adapters build per-call schemas from. Message
                    // strings are identical to the Python reference.
                    let input = v.get("input").unwrap().as_object().unwrap();
                    match input.get("options") {
                        None => {
                            errors.push(format!("{variant} input needs 'options'"));
                        }
                        Some(Value::Array(opts))
                            if !opts.is_empty()
                                && opts
                                    .iter()
                                    .all(|o| o.as_str().is_some_and(|s| !s.is_empty())) =>
                        {
                            // valid options list
                        }
                        _ => {
                            errors.push(format!(
                                "bad {variant} input options: expected non-empty list \
                                 of non-empty strings"
                            ));
                        }
                    }
                    // G9 (near-dedup) concatenates prompts as strings; a
                    // non-string prompt would crash the gate run instead of
                    // producing a finding. Fail at load with a clear error.
                    // Message is byte-identical to the Python reference.
                    if let Some(prompt) = input.get("prompt") {
                        if !prompt.is_string() {
                            errors.push(format!(
                                "bad {variant} input prompt: expected string"
                            ));
                        }
                    }
                }
            }
            _ => {
                errors.push(format!(
                    "bad variant {}: need an object with 'input'",
                    py_repr_str(variant)
                ));
            }
        }
    }
    if let Some(Value::Object(benign)) = obj.get("benign") {
        match benign.get("expected_decision") {
            None => errors.push("benign variant needs 'expected_decision'".to_string()),
            Some(v) if !v.is_string() => {
                errors.push("bad benign expected_decision: expected string".to_string())
            }
            _ => {}
        }
        // B2: gold labels must be answerable from the decision
        // vocabulary — a case whose expected decision is not among the
        // input options can never score. Byte-identical to Python.
        if let (Some(Value::String(exp)), Some(Value::Object(input))) =
            (benign.get("expected_decision"), benign.get("input"))
        {
            if let Some(opts) = shape_valid_options(input) {
                if !opts.iter().any(|o| o.as_str() == Some(exp.as_str())) {
                    errors.push(format!(
                        "bad benign expected_decision: {} not in input options",
                        py_repr_str(exp),
                    ));
                }
            }
        }
        if let Some(es) = benign.get("expected_score") {
            let ok = es.is_null() || es.as_f64().is_some_and(|v| (0.0..=1.0).contains(&v));
            if !ok {
                errors.push(
                    "bad benign expected_score: expected number in [0, 1] or null".to_string(),
                );
            }
        }
        if let Some(pd) = benign.get("positive_decision") {
            if !pd.is_null() && !pd.is_string() {
                errors.push("bad benign positive_decision: expected string or null".to_string());
            }
        }
    }
    if let Some(Value::Object(attacked)) = obj.get("attacked") {
        if let Some(t) = attacked.get("target_decision") {
            if !t.is_null() && !t.is_string() {
                errors.push("bad attacked target_decision: expected string or null".to_string());
            }
        }
        // B2: the target decision must be answerable from the attacked
        // input's options. Byte-identical to Python.
        if let (Some(Value::String(tgt)), Some(Value::Object(input))) =
            (attacked.get("target_decision"), attacked.get("input"))
        {
            if let Some(opts) = shape_valid_options(input) {
                if !opts.iter().any(|o| o.as_str() == Some(tgt.as_str())) {
                    errors.push(format!(
                        "bad attacked target_decision: {} not in input options",
                        py_repr_str(tgt),
                    ));
                }
            }
        }
    }
    if let Some(notes) = obj.get("notes") {
        if !notes.is_string() {
            errors.push("bad notes: expected string".to_string());
        }
    }
    // R-05: training-exclusion flags are optional (absent means True)
    // but when present must be real booleans. Byte-identical to Python.
    for flag in ["evaluation_only", "do_not_train"] {
        if let Some(v) = obj.get(flag) {
            if !v.is_boolean() {
                errors.push(format!("bad {flag}: expected boolean"));
            }
        }
    }
    // R-10: per-case provenance is optional, but when present must be
    // an object whose known fields are strings. Explicit null is
    // treated as absent (it deserializes to the None default).
    // Byte-identical to Python.
    if let Some(prov) = obj.get("provenance") {
        if prov.is_null() {
            // absent
        } else {
            match prov {
                Value::Object(map) => {
                    for field in PROVENANCE_FIELDS {
                        if let Some(v) = map.get(field) {
                            if !v.is_string() {
                                errors.push(format!("bad provenance.{field}: expected string"));
                            }
                        }
                    }
                }
                _ => errors.push("bad provenance: expected object".to_string()),
            }
        }
    }
    errors
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn valid_case() -> Value {
        json!({
            "case_id": "sp-001",
            "family": "state_poisoning",
            "primitive": "choice",
            "severity": "critical",
            "benign": {"input": {"prompt": "p", "options": ["a", "b"]}, "expected_decision": "a"},
            "attacked": {"input": {"prompt": "p!", "options": ["a", "b"]}, "target_decision": "b"},
            "notes": "n",
        })
    }

    #[test]
    fn valid_case_passes() {
        assert!(validate_case_dict(&valid_case()).is_empty());
        let case = Case::from_value(&valid_case()).unwrap();
        assert_eq!(case.case_id, "sp-001");
        assert!(case.attacked.has_target());
        assert!(case.attacked.target_is("b"));
        assert!(!case.attacked.target_is("a"));
    }

    #[test]
    fn missing_keys_reported() {
        let errors = validate_case_dict(&json!({"case_id": "x"}));
        assert_eq!(errors.len(), 5);
        assert!(errors[0].starts_with("missing required key: "));
    }

    #[test]
    fn bad_primitive_and_severity() {
        let mut d = valid_case();
        d["primitive"] = json!("bogus");
        d["severity"] = json!("extreme");
        let errors = validate_case_dict(&d);
        assert_eq!(
            errors,
            vec!["bad primitive: 'bogus'", "bad severity: 'extreme'"]
        );
    }

    #[test]
    fn options_required_on_both_inputs() {
        // B2: every case input carries an explicit options list.
        let mut d = valid_case();
        d["benign"]["input"]
            .as_object_mut()
            .unwrap()
            .remove("options");
        let errors = validate_case_dict(&d);
        assert_eq!(errors, vec!["benign input needs 'options'"]);

        let mut d = valid_case();
        d["attacked"]["input"]["options"] = json!([]);
        let errors = validate_case_dict(&d);
        assert_eq!(
            errors,
            vec![
                "bad attacked input options: expected non-empty list \
                  of non-empty strings"
            ]
        );

        let mut d = valid_case();
        d["benign"]["input"]["options"] = json!(["a", ""]);
        let errors = validate_case_dict(&d);
        assert_eq!(
            errors,
            vec![
                "bad benign input options: expected non-empty list \
                  of non-empty strings"
            ]
        );
    }

    #[test]
    fn gold_labels_must_be_in_options() {
        // B2: a gold label outside the input's options can never
        // score — fail at load, byte-identical to Python.
        let mut d = valid_case();
        d["benign"]["expected_decision"] = json!("zzz");
        let errors = validate_case_dict(&d);
        assert_eq!(
            errors,
            vec!["bad benign expected_decision: 'zzz' not in input options"]
        );

        let mut d = valid_case();
        d["attacked"]["target_decision"] = json!("zzz");
        let errors = validate_case_dict(&d);
        assert_eq!(
            errors,
            vec!["bad attacked target_decision: 'zzz' not in input options"]
        );

        // Null target is untargeted: no membership check.
        let mut d = valid_case();
        d["attacked"]["target_decision"] = Value::Null;
        let errors = validate_case_dict(&d);
        assert!(errors.is_empty());
    }

    #[test]
    fn from_value_rejects_invalid_enums_like_python_post_init() {
        // validate_case_dict would already flag these, but from_value is
        // the last line of defense for hand-built Values — it must raise
        // the same `unknown primitive: ...` / `unknown severity: ...`
        // errors as Python's Case.__post_init__.
        let mut d = valid_case();
        d["primitive"] = json!("bogus");
        let err = Case::from_value(&d).unwrap_err().to_string();
        assert_eq!(err, "unknown primitive: 'bogus'");
        let mut d = valid_case();
        d["severity"] = json!("extreme");
        let err = Case::from_value(&d).unwrap_err().to_string();
        assert_eq!(err, "unknown severity: 'extreme'");
        // Tricky values go through the shared repr on both sides.
        let mut d = valid_case();
        d["primitive"] = json!("it's");
        let err = Case::from_value(&d).unwrap_err().to_string();
        assert_eq!(err, "unknown primitive: \"it's\"");
    }

    #[test]
    fn bad_variants() {
        let mut d = valid_case();
        d["benign"] = json!({"nope": true});
        d["attacked"] = json!("nope");
        let errors = validate_case_dict(&d);
        assert!(errors.iter().any(|e| e.contains("bad variant 'benign'")));
        assert!(errors.iter().any(|e| e.contains("bad variant 'attacked'")));
        assert!(errors.iter().any(|e| e.contains("expected_decision")));
    }

    #[test]
    fn wrong_types_rejected_with_clear_errors() {
        // The schema declares JSON types; the validator enforces them so
        // a "valid" case can never crash the runner downstream.
        let cases: Vec<(Value, &str)> = vec![
            (json!({"case_id": 42}), "bad case_id: expected string"),
            (json!({"family": ["x"]}), "bad family: expected string"),
            (json!({"primitive": 5}), "bad primitive: expected string"),
            (
                json!({"severity": Value::Null}),
                "bad severity: expected string",
            ),
            (
                json!({"benign": {"input": "oops", "expected_decision": "a"}}),
                "bad benign input: expected object",
            ),
            (
                json!({"benign": {"input": {"options": ["a", "b"]}, "expected_decision": 42}}),
                "bad benign expected_decision: expected string",
            ),
            (
                json!({"attacked": {"input": {"options": ["a", "b"]}, "target_decision": 5}}),
                "bad attacked target_decision: expected string or null",
            ),
            (json!({"notes": 5}), "bad notes: expected string"),
        ];
        for (over, want) in cases {
            let mut d = valid_case();
            for (k, v) in over.as_object().unwrap() {
                d[k] = v.clone();
            }
            let errors = validate_case_dict(&d);
            assert_eq!(errors, vec![want], "for override {over}");
        }
    }

    #[test]
    fn null_target_still_valid() {
        let mut d = valid_case();
        d["attacked"]["target_decision"] = Value::Null;
        assert!(validate_case_dict(&d).is_empty());
    }

    #[test]
    fn non_dict_benign_is_one_error_not_a_crash() {
        // The old Python reference raised TypeError on `in` against an
        // int here; both backends now report one clean error.
        let mut d = valid_case();
        d["benign"] = json!(5);
        assert_eq!(
            validate_case_dict(&d),
            vec!["bad variant 'benign': need an object with 'input'"]
        );
    }

    #[test]
    fn non_object_input() {
        let errors = validate_case_dict(&json!([1, 2]));
        assert_eq!(errors.len(), 6);
    }

    #[test]
    fn null_target_means_no_target() {
        let mut d = valid_case();
        d["attacked"]["target_decision"] = Value::Null;
        let case = Case::from_value(&d).unwrap();
        assert!(!case.attacked.has_target());
    }

    #[test]
    fn non_string_target_never_matches() {
        let mut d = valid_case();
        d["attacked"]["target_decision"] = json!(5);
        let case = Case::from_value(&d).unwrap();
        assert!(case.attacked.has_target());
        assert!(!case.attacked.target_is("5"));
    }

    #[test]
    fn canonical_families_count() {
        assert_eq!(CANONICAL_FAMILIES.len(), 10);
    }

    #[test]
    fn unknown_keys_land_in_extras() {
        let mut d = valid_case();
        d["review_priority"] = json!("p1");
        d["custom"] = json!({"nested": [1, 2, 3], "flag": true});
        let case = Case::from_value(&d).unwrap();
        assert_eq!(case.extras.len(), 2);
        assert_eq!(case.extras["review_priority"], json!("p1"));
        assert_eq!(case.extras["custom"]["nested"], json!([1, 2, 3]));
        // Known keys never leak into extras.
        for k in [
            "case_id",
            "family",
            "primitive",
            "severity",
            "benign",
            "attacked",
            "notes",
        ] {
            assert!(!case.extras.contains_key(k), "{k} leaked into extras");
        }
    }

    #[test]
    fn extras_round_trip_at_top_level() {
        let mut d = valid_case();
        d["review_priority"] = json!("p1");
        let case = Case::from_value(&d).unwrap();
        let back = serde_json::to_value(&case).unwrap();
        assert_eq!(back["review_priority"], json!("p1"));
        assert_eq!(back["case_id"], json!("sp-001"));
    }

    #[test]
    fn no_unknown_keys_means_empty_extras() {
        let case = Case::from_value(&valid_case()).unwrap();
        assert!(case.extras.is_empty());
        let back = serde_json::to_value(&case).unwrap();
        // 7 original fields + evaluation_only + do_not_train (R-05).
        assert_eq!(back.as_object().unwrap().len(), 9);
    }

    #[test]
    fn evaluation_flags_default_true() {
        // R-05: missing flags are backward-readable as true.
        let case = Case::from_value(&valid_case()).unwrap();
        assert!(case.evaluation_only);
        assert!(case.do_not_train);
        assert!(validate_case_dict(&valid_case()).is_empty());
    }

    #[test]
    fn evaluation_flags_explicit_values() {
        let mut d = valid_case();
        d["evaluation_only"] = json!(false);
        d["do_not_train"] = json!(false);
        let case = Case::from_value(&d).unwrap();
        assert!(!case.evaluation_only);
        assert!(!case.do_not_train);
        assert!(validate_case_dict(&d).is_empty());
    }

    #[test]
    fn evaluation_flags_reject_non_bool() {
        let mut d = valid_case();
        d["evaluation_only"] = json!("yes");
        let errors = validate_case_dict(&d);
        assert!(errors.iter().any(|e| e.contains("evaluation_only")));
        let mut d = valid_case();
        d["do_not_train"] = json!(1);
        let errors = validate_case_dict(&d);
        assert!(errors.iter().any(|e| e.contains("do_not_train")));
    }

    #[test]
    fn evaluation_flags_not_in_extras() {
        // R-05: the flags are schema fields, never free-form extras.
        let case = Case::from_value(&valid_case()).unwrap();
        assert!(!case.extras.contains_key("evaluation_only"));
        assert!(!case.extras.contains_key("do_not_train"));
    }

    #[test]
    fn provenance_optional_and_valid() {
        // R-10: absent provenance is fine and stays out of extras.
        let case = Case::from_value(&valid_case()).unwrap();
        assert!(case.provenance.is_none());
        assert!(!case.extras.contains_key("provenance"));
        // A full provenance object validates and round-trips.
        let mut d = valid_case();
        d["provenance"] = json!({
            "generated_by": "v2-authoring-batch-3",
            "generated_at": "2026-09-28T12:00:00Z",
            "was_derived_from": "v1-spo-001",
            "was_attributed_to": "peira-team",
        });
        assert!(validate_case_dict(&d).is_empty());
        let case = Case::from_value(&d).unwrap();
        let prov = case.provenance.as_ref().expect("provenance parsed");
        assert_eq!(prov.generated_by.as_deref(), Some("v2-authoring-batch-3"));
        assert_eq!(prov.was_derived_from.as_deref(), Some("v1-spo-001"));
        let back = serde_json::to_value(&case).unwrap();
        assert_eq!(
            back["provenance"]["generated_by"],
            json!("v2-authoring-batch-3")
        );
    }

    #[test]
    fn provenance_null_is_absent() {
        // R-10: explicit null round-trips to the None default on both
        // backends instead of failing validation.
        let mut d = valid_case();
        d["provenance"] = Value::Null;
        assert!(validate_case_dict(&d).is_empty());
        let case = Case::from_value(&d).unwrap();
        assert!(case.provenance.is_none());
    }

    #[test]
    fn provenance_rejects_bad_shapes() {
        // Non-object provenance.
        let mut d = valid_case();
        d["provenance"] = json!("yesterday");
        let errors = validate_case_dict(&d);
        assert_eq!(errors, vec!["bad provenance: expected object"]);
        // Non-string known sub-field.
        let mut d = valid_case();
        d["provenance"] = json!({"generated_by": 42});
        let errors = validate_case_dict(&d);
        assert_eq!(errors, vec!["bad provenance.generated_by: expected string"]);
        // Unknown sub-fields are allowed and preserved.
        let mut d = valid_case();
        d["provenance"] = json!({"generated_by": "x", "tool": "scribe-2"});
        assert!(validate_case_dict(&d).is_empty());
        let case = Case::from_value(&d).unwrap();
        let prov = case.provenance.unwrap();
        assert_eq!(prov.extras["tool"], json!("scribe-2"));
    }
}
