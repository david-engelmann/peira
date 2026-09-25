//! Schema: Rust implementation of peira's case data contract.
//!
//! This is a port of `python/peira/schema.py`. The case schema is the
//! frozen data contract — the same validation rules must apply in Rust,
//! Python, and future TypeScript SDKs.

use std::collections::HashMap;
use thiserror::Error;

pub const PRIMITIVES: &[&str] = &["choice", "score", "noul"];
pub const SEVERITIES: &[&str] = &["critical", "high", "medium", "low"];

#[derive(Debug, Error)]
pub enum SchemaError {
    #[error("unknown primitive: {0}")]
    UnknownPrimitive(String),
    #[error("unknown severity: {0}")]
    UnknownSeverity(String),
    #[error("score case {case_id}: benign.expected_score is required")]
    MissingExpectedScore { case_id: String },
    #[error("score case {case_id}: expected_score must be a number")]
    InvalidExpectedScoreType { case_id: String },
    #[error("score case {case_id}: expected_score {score} outside 0..1")]
    ExpectedScoreOutOfRange { case_id: String, score: f64 },
    #[error("missing required field: {0}")]
    MissingField(String),
    #[error("invalid field: {0}")]
    InvalidField(String),
}

/// The unattacked version of a decision input.
#[derive(Debug, Clone)]
pub struct BenignVariant {
    pub input: HashMap<String, serde_json::Value>,
    pub expected_decision: String,
    /// For score primitives: the gold-standard score in 0..1.
    /// None for choice/noul primitives.
    pub expected_score: Option<f64>,
}

/// The attacked version of a decision input.
#[derive(Debug, Clone)]
pub struct AttackedVariant {
    pub input: HashMap<String, serde_json::Value>,
    /// The decision the attacker is trying to induce.
    /// None means the attack only tries to change the decision.
    pub target_decision: Option<String>,
}

/// A single decision scenario with benign and attacked variants.
#[derive(Debug, Clone)]
pub struct Case {
    pub case_id: String,
    pub family: String,
    pub primitive: String,
    pub severity: String,
    pub benign: BenignVariant,
    pub attacked: AttackedVariant,
    pub notes: String,
}

impl Case {
    /// Validate a case against the schema rules.
    /// Mirrors Python's `Case.__post_init__` and `validate_case_dict`.
    pub fn validate(&self) -> Result<(), SchemaError> {
        if !PRIMITIVES.contains(&self.primitive.as_str()) {
            return Err(SchemaError::UnknownPrimitive(self.primitive.clone()));
        }
        if !SEVERITIES.contains(&self.severity.as_str()) {
            return Err(SchemaError::UnknownSeverity(self.severity.clone()));
        }
        // Score invariant (audit M2): score primitives must have
        // expected_score in 0..1.
        if self.primitive == "score" {
            match self.benign.expected_score {
                None => {
                    return Err(SchemaError::MissingExpectedScore {
                        case_id: self.case_id.clone(),
                    })
                }
                Some(s) => {
                    if !(0.0..=1.0).contains(&s) {
                        return Err(SchemaError::ExpectedScoreOutOfRange {
                            case_id: self.case_id.clone(),
                            score: s,
                        });
                    }
                    // Reject NaN and infinities (Python's comparison
                    // returns False for NaN, so it would fail the range check)
                    if !s.is_finite() {
                        return Err(SchemaError::ExpectedScoreOutOfRange {
                            case_id: self.case_id.clone(),
                            score: s,
                        });
                    }
                }
            }
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_benign(score: Option<f64>) -> BenignVariant {
        BenignVariant {
            input: HashMap::new(),
            expected_decision: "approve".to_string(),
            expected_score: score,
        }
    }

    fn make_attacked() -> AttackedVariant {
        AttackedVariant {
            input: HashMap::new(),
            target_decision: Some("deny".to_string()),
        }
    }

    #[test]
    fn score_case_requires_expected_score() {
        let case = Case {
            case_id: "test-001".to_string(),
            family: "score_anchoring".to_string(),
            primitive: "score".to_string(),
            severity: "critical".to_string(),
            benign: make_benign(None),
            attacked: make_attacked(),
            notes: String::new(),
        };
        assert!(matches!(
            case.validate(),
            Err(SchemaError::MissingExpectedScore { .. })
        ));
    }

    #[test]
    fn score_case_rejects_out_of_range() {
        let case = Case {
            case_id: "test-002".to_string(),
            family: "score_anchoring".to_string(),
            primitive: "score".to_string(),
            severity: "critical".to_string(),
            benign: make_benign(Some(1.5)),
            attacked: make_attacked(),
            notes: String::new(),
        };
        assert!(matches!(
            case.validate(),
            Err(SchemaError::ExpectedScoreOutOfRange { .. })
        ));
    }

    #[test]
    fn score_case_accepts_valid() {
        let case = Case {
            case_id: "test-003".to_string(),
            family: "score_anchoring".to_string(),
            primitive: "score".to_string(),
            severity: "critical".to_string(),
            benign: make_benign(Some(0.75)),
            attacked: make_attacked(),
            notes: String::new(),
        };
        assert!(case.validate().is_ok());
    }

    #[test]
    fn choice_case_no_score_needed() {
        let case = Case {
            case_id: "test-004".to_string(),
            family: "state_poisoning".to_string(),
            primitive: "choice".to_string(),
            severity: "critical".to_string(),
            benign: make_benign(None),
            attacked: make_attacked(),
            notes: String::new(),
        };
        assert!(case.validate().is_ok());
    }
}

/// Python-`repr`-style formatting for a scalar JSON value, used to mirror
/// `validate_case_dict`'s exact error strings (e.g. `bad primitive: 'xyz'`).
fn py_repr_scalar(v: &serde_json::Value) -> String {
    match v {
        serde_json::Value::String(s) => format!("'{s}'"),
        serde_json::Value::Number(n) => n.to_string(),
        serde_json::Value::Bool(b) => {
            if *b {
                "True".to_string()
            } else {
                "False".to_string()
            }
        }
        serde_json::Value::Null => "None".to_string(),
        _ => "<complex>".to_string(),
    }
}

/// Canonical score predicate, mirroring Python's `_is_valid_score`:
/// a JSON number in 0..1, not a bool. (JSON `true`/`false` parse as
/// `Value::Bool`, so they are excluded by matching only `Number`.)
fn is_valid_score(v: &serde_json::Value) -> bool {
    match v {
        serde_json::Value::Number(n) => {
            if let Some(f) = n.as_f64() {
                (0.0..=1.0).contains(&f)
            } else {
                false
            }
        }
        _ => false,
    }
}

/// Validate a raw case dict, returning the list of violations.
/// Mirrors Python's `validate_case_dict` exactly, including error strings,
/// so `peira validate` output is identical across implementations.
pub fn validate_case_dict(d: &serde_json::Value) -> Vec<String> {
    let mut errors: Vec<String> = Vec::new();
    let obj = match d.as_object() {
        Some(o) => o,
        None => {
            errors.push("case must be a JSON object".to_string());
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
    if let Some(p) = obj.get("primitive") {
        if p.as_str().map(|s| !PRIMITIVES.contains(&s)).unwrap_or(true) {
            errors.push(format!("bad primitive: {}", py_repr_scalar(p)));
        }
    }
    if let Some(s) = obj.get("severity") {
        if s.as_str().map(|s| !SEVERITIES.contains(&s)).unwrap_or(true) {
            errors.push(format!("bad severity: {}", py_repr_scalar(s)));
        }
    }
    for variant in ["benign", "attacked"] {
        let ok = obj
            .get(variant)
            .and_then(|v| v.as_object())
            .map(|o| o.contains_key("input"))
            .unwrap_or(false);
        if !ok {
            errors.push(format!(
                "bad variant '{variant}': need an object with 'input'"
            ));
        }
    }
    let benign_has_expected = obj
        .get("benign")
        .and_then(|v| v.as_object())
        .map(|o| o.contains_key("expected_decision"))
        .unwrap_or(false);
    if !benign_has_expected {
        errors.push("benign variant needs 'expected_decision'".to_string());
    }
    if obj.get("primitive").and_then(|v| v.as_str()) == Some("score") {
        let score = obj
            .get("benign")
            .and_then(|v| v.as_object())
            .and_then(|o| o.get("expected_score"));
        match score {
            None => errors.push("score primitive needs benign 'expected_score'".to_string()),
            Some(s) if !is_valid_score(s) => errors.push(format!(
                "expected_score {} must be a number in 0..1 (not bool)",
                py_repr_scalar(s)
            )),
            _ => {}
        }
    }
    errors
}

fn get_str<'a>(
    o: &'a serde_json::Map<String, serde_json::Value>,
    k: &str,
) -> Result<&'a str, SchemaError> {
    o.get(k)
        .and_then(|v| v.as_str())
        .ok_or_else(|| SchemaError::MissingField(k.to_string()))
}

impl Case {
    /// Build a `Case` from a raw JSON value. Callers should run
    /// [`validate_case_dict`] first; this returns an error instead of
    /// panicking if the shape is unexpected.
    pub fn from_value(v: &serde_json::Value) -> Result<Self, SchemaError> {
        let o = v
            .as_object()
            .ok_or_else(|| SchemaError::InvalidField("case must be an object".to_string()))?;
        let benign = o
            .get("benign")
            .and_then(|v| v.as_object())
            .ok_or_else(|| SchemaError::MissingField("benign".to_string()))?;
        let attacked = o
            .get("attacked")
            .and_then(|v| v.as_object())
            .ok_or_else(|| SchemaError::MissingField("attacked".to_string()))?;
        let benign_input = benign
            .get("input")
            .and_then(|v| v.as_object())
            .ok_or_else(|| SchemaError::MissingField("benign.input".to_string()))?;
        let attacked_input = attacked
            .get("input")
            .and_then(|v| v.as_object())
            .ok_or_else(|| SchemaError::MissingField("attacked.input".to_string()))?;

        let expected_score = match benign.get("expected_score") {
            None | Some(serde_json::Value::Null) => None,
            Some(serde_json::Value::Number(n)) => n.as_f64(),
            Some(other) => {
                return Err(SchemaError::InvalidExpectedScoreType {
                    case_id: get_str(o, "case_id").unwrap_or("?").to_string(),
                }
                .into_with_value(other));
            }
        };
        let target_decision = match attacked.get("target_decision") {
            None | Some(serde_json::Value::Null) => None,
            Some(serde_json::Value::String(s)) => Some(s.clone()),
            _ => None,
        };

        let case = Case {
            case_id: get_str(o, "case_id")?.to_string(),
            family: get_str(o, "family")?.to_string(),
            primitive: get_str(o, "primitive")?.to_string(),
            severity: get_str(o, "severity")?.to_string(),
            benign: BenignVariant {
                input: benign_input
                    .iter()
                    .map(|(k, v)| (k.clone(), v.clone()))
                    .collect(),
                expected_decision: get_str(benign, "expected_decision")?.to_string(),
                expected_score,
            },
            attacked: AttackedVariant {
                input: attacked_input
                    .iter()
                    .map(|(k, v)| (k.clone(), v.clone()))
                    .collect(),
                target_decision,
            },
            notes: o
                .get("notes")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string(),
        };
        case.validate()?;
        Ok(case)
    }
}

impl SchemaError {
    fn into_with_value(self, _v: &serde_json::Value) -> Self {
        self
    }
}

#[cfg(test)]
mod dict_tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn validate_ok_case() {
        let v = json!({
            "case_id": "x-1", "family": "f", "primitive": "choice", "severity": "low",
            "benign": {"input": {}, "expected_decision": "approve"},
            "attacked": {"input": {}, "target_decision": "deny"},
        });
        assert!(validate_case_dict(&v).is_empty());
        assert!(Case::from_value(&v).is_ok());
    }

    #[test]
    fn validate_error_strings_match_python() {
        // missing keys
        let v = json!({"case_id": "x"});
        let e = validate_case_dict(&v);
        assert_eq!(e[0], "missing required key: family");
        // bad primitive / severity use Python repr quoting
        let v = json!({
            "case_id": "x", "family": "f", "primitive": "bogus", "severity": "dire",
            "benign": {"input": {}, "expected_decision": "a"},
            "attacked": {"input": {}},
        });
        let e = validate_case_dict(&v);
        assert!(e.contains(&"bad primitive: 'bogus'".to_string()), "{e:?}");
        assert!(e.contains(&"bad severity: 'dire'".to_string()), "{e:?}");
        // bool score rejected like Python
        let v = json!({
            "case_id": "x", "family": "f", "primitive": "score", "severity": "low",
            "benign": {"input": {}, "expected_decision": "a", "expected_score": true},
            "attacked": {"input": {}},
        });
        let e = validate_case_dict(&v);
        assert_eq!(
            e,
            vec!["expected_score True must be a number in 0..1 (not bool)".to_string()]
        );
    }
}
