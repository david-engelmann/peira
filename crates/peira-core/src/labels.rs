//! Shared decision-label helpers for adapters (B2).
//!
//! This module ports `python/peira/adapters/_labels.py`: adapters that
//! need a per-call candidate label set (constrained LLM enums,
//! Jev-family choice criteria) build it from the case input's explicit
//! `options` list. Two labels are always available beyond the case's
//! own options: `"other"` (the model can answer outside the listed
//! vocabulary) and `"abstain"` (abstain primitive only).
//!
//! Parity notes:
//! - `options` must be a JSON array; non-string or empty entries are
//!   ignored, exactly like the reference's `isinstance(option, str) and
//!   option` filter. A missing or non-array `options` contributes
//!   nothing (the reference's `isinstance(options, list)` guard).
//! - The result is sorted and deduplicated. Rust's byte-wise `str`
//!   ordering equals Python's codepoint ordering for valid UTF-8, so
//!   `sorted()` and `sort()` agree.

use serde_json::Value;

/// Placeholder decision for abstain-primitive adapters whose model
/// answered "should I abstain?" with no.
///
/// Mirrors `python/peira/adapters/_labels.py::NON_ABSTAIN_PLACEHOLDER`.
pub const NON_ABSTAIN_PLACEHOLDER: &str = "other";

/// Sorted, deduplicated candidate labels from the input's options.
///
/// Mirrors `python/peira/adapters/_labels.py::candidate_labels`:
/// `case_input` is the case input object, `primitive` the decision
/// primitive. Non-array `options` (or a missing key) contributes
/// nothing; `"abstain"` is added only for the abstain primitive;
/// `"other"` is always present.
pub fn candidate_labels(case_input: &Value, primitive: &str) -> Vec<String> {
    let mut labels: Vec<String> = Vec::new();
    if let Some(options) = case_input.get("options").and_then(Value::as_array) {
        for option in options {
            if let Some(s) = option.as_str() {
                if !s.is_empty() {
                    labels.push(s.to_owned());
                }
            }
        }
    }
    if primitive == "abstain" {
        labels.push("abstain".to_owned());
    }
    labels.push(NON_ABSTAIN_PLACEHOLDER.to_owned());
    labels.sort();
    labels.dedup();
    labels
}

/// The decision placeholder when an abstain-primitive call does not
/// abstain.
///
/// Mirrors `python/peira/adapters/_labels.py::non_abstain_placeholder`.
pub fn non_abstain_placeholder() -> &'static str {
    NON_ABSTAIN_PLACEHOLDER
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn labels_of(input: &Value, primitive: &str) -> Vec<String> {
        candidate_labels(input, primitive)
    }

    #[test]
    fn basic_options_sorted_deduped() {
        let input = json!({"options": ["deny", "approve", "deny"]});
        assert_eq!(labels_of(&input, "choice"), vec!["approve", "deny", "other"]);
    }

    #[test]
    fn abstain_primitive_adds_abstain() {
        let input = json!({"options": ["approve"]});
        assert_eq!(
            labels_of(&input, "abstain"),
            vec!["abstain", "approve", "other"]
        );
    }

    #[test]
    fn missing_options_yields_placeholders_only() {
        let input = json!({"input": "decide"});
        assert_eq!(labels_of(&input, "choice"), vec!["other"]);
        assert_eq!(labels_of(&input, "abstain"), vec!["abstain", "other"]);
    }

    #[test]
    fn non_array_options_ignored() {
        for options in [json!("approve"), json!(5), json!(null), json!({"a": 1})] {
            let input = json!({"options": options});
            assert_eq!(labels_of(&input, "choice"), vec!["other"]);
        }
    }

    #[test]
    fn non_string_and_empty_options_ignored() {
        let input = json!({"options": ["approve", "", 5, null, true, ["x"], {"y": 1}]});
        assert_eq!(labels_of(&input, "choice"), vec!["approve", "other"]);
    }

    #[test]
    fn placeholder_strings_participate_in_dedupe() {
        // "other"/"abstain" appearing in options must not duplicate.
        let input = json!({"options": ["other", "approve"]});
        assert_eq!(labels_of(&input, "choice"), vec!["approve", "other"]);
        let input = json!({"options": ["abstain", "approve"]});
        assert_eq!(
            labels_of(&input, "abstain"),
            vec!["abstain", "approve", "other"]
        );
    }

    #[test]
    fn sort_is_codepoint_order() {
        // Byte-wise Rust ordering == Python codepoint ordering.
        let input = json!({"options": ["éclair", "zebra", "Äpfel", "apple"]});
        let got = labels_of(&input, "choice");
        let mut expected = vec!["éclair", "zebra", "Äpfel", "apple", "other"];
        expected.sort();
        assert_eq!(got, expected);
    }

    #[test]
    fn non_object_input_has_no_options() {
        for input in [json!([1, 2]), json!("x"), json!(null), json!(5)] {
            assert_eq!(labels_of(&input, "choice"), vec!["other"]);
        }
    }

    #[test]
    fn placeholder_fn_returns_other() {
        assert_eq!(non_abstain_placeholder(), "other");
        assert_eq!(non_abstain_placeholder(), NON_ABSTAIN_PLACEHOLDER);
    }
}
