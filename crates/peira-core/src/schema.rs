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
pub const PRIMITIVES: &[&str] = &["choice", "score", "noul"];

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
    }
    if let Some(Value::Object(attacked)) = obj.get("attacked") {
        if let Some(t) = attacked.get("target_decision") {
            if !t.is_null() && !t.is_string() {
                errors.push("bad attacked target_decision: expected string or null".to_string());
            }
        }
    }
    if let Some(notes) = obj.get("notes") {
        if !notes.is_string() {
            errors.push("bad notes: expected string".to_string());
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
            "benign": {"input": {"prompt": "p"}, "expected_decision": "a"},
            "attacked": {"input": {"prompt": "p!"}, "target_decision": "b"},
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
                json!({"benign": {"input": {}, "expected_decision": 42}}),
                "bad benign expected_decision: expected string",
            ),
            (
                json!({"attacked": {"input": {}, "target_decision": 5}}),
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
        assert_eq!(back.as_object().unwrap().len(), 7);
    }
}
