//! Automated dataset validation gates.
//!
//! Ports the pure checking logic of `python/peira/gates.py` (G2–G8).
//! G1 (schema validation) is already in `crate::schema`; the `run_gates`
//! orchestration (file I/O, `iter_case_lines`) stays in Python.
//!
//! Each gate takes a slice of `GateCase` (path name, line number, and
//! the case as `serde_json::Value`) and returns a `GateResult` with
//! `errors` and `warnings`. Findings are either errors (fail the suite)
//! or warnings (reported; the suite still passes).

use regex::Regex;
use serde_json::Value;
use std::collections::{BTreeMap, HashMap};
use std::sync::OnceLock;

/// One validated case for gate checking: the file name, line number,
/// and the case dict.
#[derive(Debug, Clone)]
pub struct GateCase {
    pub path_name: String,
    pub lineno: usize,
    pub case: Value,
}

/// The result of one gate: errors fail the suite, warnings do not.
#[derive(Debug, Clone)]
pub struct GateResult {
    pub gate_id: String,
    pub name: String,
    pub errors: Vec<String>,
    pub warnings: Vec<String>,
}

impl GateResult {
    fn new(gate_id: &str, name: &str) -> Self {
        GateResult {
            gate_id: gate_id.to_string(),
            name: name.to_string(),
            errors: Vec::new(),
            warnings: Vec::new(),
        }
    }

    /// Whether the gate passed (no errors).
    pub fn passed(&self) -> bool {
        self.errors.is_empty()
    }
}

/// Canonical JSON of a variant's input, for content comparison.
///
/// Mirrors `python/peira/gates.py::_canon_input` (which uses
/// `json.dumps(..., sort_keys=True)`).
fn canon_input(variant: &Value) -> String {
    let input = variant.get("input").unwrap_or(&Value::Null);
    crate::canonical::to_canonical(input)
}

/// G2: the attacked variant actually differs from its benign control.
///
/// An attacked variant identical to its benign control is a broken case:
/// there is no attack to measure.
/// Mirrors `python/peira/gates.py::gate_paired_variants`.
pub fn gate_paired_variants(cases: &[GateCase]) -> GateResult {
    let mut r = GateResult::new("G2", "paired-variants");
    for gc in cases {
        let benign = canon_input(&gc.case["benign"]);
        let attacked = canon_input(&gc.case["attacked"]);
        if benign == attacked {
            r.errors.push(format!(
                "{}:{}: attacked input is identical to benign input (no attack)",
                gc.path_name, gc.lineno
            ));
        }
    }
    r
}

/// G3: case ids are unique; no two cases share a content pair.
///
/// Mirrors `python/peira/gates.py::gate_dedup`.
pub fn gate_dedup(cases: &[GateCase]) -> GateResult {
    let mut r = GateResult::new("G3", "dedup");
    let mut seen_ids: HashMap<&str, String> = HashMap::new();
    let mut seen_pairs: HashMap<String, String> = HashMap::new();
    for gc in cases {
        let loc = format!("{}:{}", gc.path_name, gc.lineno);
        let cid = gc
            .case
            .get("case_id")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        if let Some(first) = seen_ids.get(cid) {
            r.errors.push(format!(
                "{loc}: duplicate case_id '{cid}' (first seen at {first})"
            ));
        } else {
            seen_ids.insert(cid, loc.clone());
        }
        let pair = format!(
            "{}\x00{}",
            canon_input(&gc.case["benign"]),
            canon_input(&gc.case["attacked"])
        );
        if let Some(first) = seen_pairs.get(&pair) {
            r.errors.push(format!(
                "{loc}: duplicate content pair (first seen at {first})"
            ));
        } else {
            seen_pairs.insert(pair, loc);
        }
    }
    r
}

/// G4: every case uses a canonical attack-family id.
///
/// `canonical_families` is the list of valid family ids (from
/// `peira.schema.CANONICAL_FAMILIES`).
/// Mirrors `python/peira/gates.py::gate_families`.
pub fn gate_families(cases: &[GateCase], canonical_families: &[String]) -> GateResult {
    let mut r = GateResult::new("G4", "families");
    for gc in cases {
        let family = gc.case.get("family").and_then(|v| v.as_str()).unwrap_or("");
        if !canonical_families.iter().any(|f| f == family) {
            r.errors.push(format!(
                "{}:{}: unknown family '{}' (see docs/Taxonomy.md)",
                gc.path_name, gc.lineno, family
            ));
        }
    }
    r
}

/// G5: a named target decision must differ from the benign expectation.
///
/// A targeted attack aiming at the decision the benign input already
/// produces is incoherent — there is nothing to steer toward.
/// Mirrors `python/peira/gates.py::gate_target_coherence`.
pub fn gate_target_coherence(cases: &[GateCase]) -> GateResult {
    let mut r = GateResult::new("G5", "target-coherence");
    for gc in cases {
        let target = gc.case["attacked"].get("target_decision");
        let expected = gc.case["benign"].get("expected_decision");
        if let (Some(t), Some(e)) = (target, expected) {
            if t == e && !t.is_null() {
                // Python formats with {target!r}: single quotes for strings.
                // target_decision is string|null per the schema and null is
                // excluded above, so t is always a string here.
                let t_str = t.as_str().unwrap_or("<non-string>");
                r.errors.push(format!(
                    "{}:{}: target_decision '{}' equals the benign expected decision",
                    gc.path_name, gc.lineno, t_str
                ));
            }
        }
    }
    r
}

fn pii_patterns() -> &'static Vec<(String, Regex)> {
    static PATTERNS: OnceLock<Vec<(String, Regex)>> = OnceLock::new();
    PATTERNS.get_or_init(|| {
        vec![
            (
                "email address".to_string(),
                Regex::new(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}").unwrap(),
            ),
            (
                "phone number".to_string(),
                Regex::new(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b").unwrap(),
            ),
            (
                "SSN".to_string(),
                Regex::new(r"\b\d{3}-\d{2}-\d{4}\b").unwrap(),
            ),
        ]
    })
}

/// G6: flag identifier-like strings in case inputs.
///
/// Warnings, not errors: attack payloads sometimes contain synthetic
/// identifiers by design. Every warning goes to the human review queue.
/// Mirrors `python/peira/gates.py::gate_pii_scan`.
pub fn gate_pii_scan(cases: &[GateCase]) -> GateResult {
    let mut r = GateResult::new("G6", "pii-scan");
    for gc in cases {
        for variant in ["benign", "attacked"] {
            let input = gc.case.get(variant).and_then(|v| v.get("input"));
            let text = crate::canonical::to_canonical(input.unwrap_or(&Value::Null));
            for (label, pattern) in pii_patterns() {
                if pattern.is_match(&text) {
                    r.warnings.push(format!(
                        "{}:{}: possible {label} in {variant} input",
                        gc.path_name, gc.lineno
                    ));
                    break;
                }
            }
        }
    }
    r
}

/// G7: score-primitive cases carry the author's reference score.
///
/// Score diagnostics measure adapter-vs-author agreement against
/// benign.expected_score; a score case without one cannot contribute.
/// Mirrors `python/peira/gates.py::gate_score_reference`.
pub fn gate_score_reference(cases: &[GateCase]) -> GateResult {
    let mut r = GateResult::new("G7", "score-reference");
    for gc in cases {
        let primitive = gc
            .case
            .get("primitive")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        if primitive == "score" {
            let expected = gc.case["benign"].get("expected_score");
            if expected.is_none() || expected == Some(&Value::Null) {
                r.errors.push(format!(
                    "{}:{}: score case missing benign expected_score (author reference)",
                    gc.path_name, gc.lineno
                ));
            }
        }
    }
    r
}

/// G8: options lists are canonical across both variants.
///
/// Every case's benign and attacked inputs must carry the identical
/// options list (order-sensitive), and each list must be sorted with
/// unique labels.
/// Mirrors `python/peira/gates.py::gate_options_coherence`.
pub fn gate_options_coherence(cases: &[GateCase]) -> GateResult {
    let mut r = GateResult::new("G8", "options-coherence");
    for gc in cases {
        let loc = format!("{}:{}", gc.path_name, gc.lineno);
        let mut opts: BTreeMap<&str, Vec<String>> = BTreeMap::new();
        for variant in ["benign", "attacked"] {
            let o = gc
                .case
                .get(variant)
                .and_then(|v| v.get("input"))
                .and_then(|v| v.get("options"));
            // G1 rejects non-list options; the gate only checks
            // canonical form on lists.
            if let Some(Value::Array(arr)) = o {
                let labels: Vec<String> = arr
                    .iter()
                    .filter_map(|v| v.as_str().map(|s| s.to_string()))
                    .collect();
                // Only check if all elements were strings (else G1 already failed).
                if labels.len() == arr.len() {
                    let unique: std::collections::HashSet<&String> = labels.iter().collect();
                    if unique.len() != labels.len() {
                        r.errors.push(format!(
                            "{loc}: {variant} input options contain duplicate labels"
                        ));
                    }
                    let mut sorted = labels.clone();
                    sorted.sort();
                    if labels != sorted {
                        r.errors.push(format!(
                            "{loc}: {variant} input options are not in sorted order"
                        ));
                    }
                    opts.insert(variant, labels);
                }
            }
        }
        if let (Some(b), Some(a)) = (opts.get("benign"), opts.get("attacked")) {
            if b != a {
                r.errors.push(format!(
                    "{loc}: benign and attacked input options differ — \
                     the decision vocabulary must be identical across arms"
                ));
            }
        }
    }
    r
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn case(id: &str, benign_input: Value, attacked_input: Value) -> GateCase {
        GateCase {
            path_name: "test.jsonl".to_string(),
            lineno: 1,
            case: json!({
                "case_id": id,
                "family": "prompt_injection",
                "primitive": "choice",
                "benign": {"input": benign_input, "expected_decision": "approve"},
                "attacked": {"input": attacked_input},
            }),
        }
    }

    fn simple_input(prompt: &str) -> Value {
        json!({"prompt": prompt, "options": ["approve", "deny"]})
    }

    #[test]
    fn g2_passes_when_variants_differ() {
        let cases = vec![case("c1", simple_input("hello"), simple_input("hello!"))];
        let r = gate_paired_variants(&cases);
        assert!(r.passed());
    }

    #[test]
    fn g2_fails_when_identical() {
        let cases = vec![case("c1", simple_input("same"), simple_input("same"))];
        let r = gate_paired_variants(&cases);
        assert!(!r.passed());
        assert_eq!(r.errors.len(), 1);
        assert!(r.errors[0].contains("identical to benign input"));
    }

    #[test]
    fn g3_passes_unique() {
        let cases = vec![
            case("c1", simple_input("a"), simple_input("a!")),
            case("c2", simple_input("b"), simple_input("b!")),
        ];
        let r = gate_dedup(&cases);
        assert!(r.passed());
    }

    #[test]
    fn g3_fails_duplicate_id() {
        let cases = vec![
            case("c1", simple_input("a"), simple_input("a!")),
            case("c1", simple_input("b"), simple_input("b!")),
        ];
        let r = gate_dedup(&cases);
        assert!(!r.passed());
        assert!(r.errors[0].contains("duplicate case_id"));
    }

    #[test]
    fn g3_fails_duplicate_content() {
        let cases = vec![
            case("c1", simple_input("a"), simple_input("a!")),
            case("c2", simple_input("a"), simple_input("a!")),
        ];
        let r = gate_dedup(&cases);
        assert!(!r.passed());
        assert!(r.errors[0].contains("duplicate content pair"));
    }

    #[test]
    fn g4_passes_canonical_family() {
        let cases = vec![case("c1", simple_input("a"), simple_input("a!"))];
        let fams = vec!["prompt_injection".to_string()];
        let r = gate_families(&cases, &fams);
        assert!(r.passed());
    }

    #[test]
    fn g4_fails_unknown_family() {
        let cases = vec![case("c1", simple_input("a"), simple_input("a!"))];
        let fams = vec!["other".to_string()];
        let r = gate_families(&cases, &fams);
        assert!(!r.passed());
        assert!(r.errors[0].contains("unknown family"));
    }

    #[test]
    fn g5_fails_when_target_equals_expected() {
        let mut gc = case("c1", simple_input("a"), simple_input("a!"));
        gc.case["attacked"]["target_decision"] = json!("approve");
        let r = gate_target_coherence(&[gc]);
        assert!(!r.passed());
        assert!(r.errors[0].contains("target_decision"));
        // Python formats with {target!r}: single quotes for strings.
        assert!(r.errors[0].contains("target_decision 'approve'"),
                "G5 message was: {}", r.errors[0]);
    }

    #[test]
    fn g5_passes_when_untargeted() {
        let cases = vec![case("c1", simple_input("a"), simple_input("a!"))];
        let r = gate_target_coherence(&cases);
        assert!(r.passed());
    }

    #[test]
    fn g6_warns_on_email() {
        let cases = vec![case(
            "c1",
            simple_input("contact ops@company.example"),
            simple_input("x"),
        )];
        let r = gate_pii_scan(&cases);
        assert!(r.passed()); // warnings, not errors
        assert_eq!(r.warnings.len(), 1);
        assert!(r.warnings[0].contains("email address"));
    }

    #[test]
    fn g6_no_warning_on_clean() {
        let cases = vec![case("c1", simple_input("hello"), simple_input("hi"))];
        let r = gate_pii_scan(&cases);
        assert!(r.warnings.is_empty());
    }

    #[test]
    fn g7_fails_score_without_reference() {
        let mut gc = case("c1", simple_input("a"), simple_input("a!"));
        gc.case["primitive"] = json!("score");
        let r = gate_score_reference(&[gc]);
        assert!(!r.passed());
        assert!(r.errors[0].contains("expected_score"));
    }

    #[test]
    fn g7_passes_score_with_reference() {
        let mut gc = case("c1", simple_input("a"), simple_input("a!"));
        gc.case["primitive"] = json!("score");
        gc.case["benign"]["expected_score"] = json!(0.8);
        let r = gate_score_reference(&[gc]);
        assert!(r.passed());
    }

    #[test]
    fn g7_ignores_choice() {
        let cases = vec![case("c1", simple_input("a"), simple_input("a!"))];
        let r = gate_score_reference(&cases);
        assert!(r.passed());
    }

    #[test]
    fn g8_passes_identical_sorted_options() {
        let cases = vec![case("c1", simple_input("a"), simple_input("a!"))];
        let r = gate_options_coherence(&cases);
        assert!(r.passed());
    }

    #[test]
    fn g8_fails_differing_options() {
        let cases = vec![case(
            "c1",
            json!({"prompt": "a", "options": ["approve", "deny"]}),
            json!({"prompt": "a!", "options": ["deny", "approve"]}),
        )];
        // Note: ["deny", "approve"] is not sorted, so we get two errors:
        // not sorted + differ. Use sorted-but-different instead.
        let r = gate_options_coherence(&cases);
        assert!(!r.passed());
    }

    #[test]
    fn g8_fails_unsorted_options() {
        let cases = vec![case(
            "c1",
            json!({"prompt": "a", "options": ["deny", "approve"]}),
            json!({"prompt": "a!", "options": ["deny", "approve"]}),
        )];
        let r = gate_options_coherence(&cases);
        assert!(!r.passed());
        assert!(r.errors.iter().any(|e| e.contains("sorted order")));
    }

    #[test]
    fn g8_fails_duplicate_options() {
        let cases = vec![case(
            "c1",
            json!({"prompt": "a", "options": ["approve", "approve", "deny"]}),
            json!({"prompt": "a!", "options": ["approve", "approve", "deny"]}),
        )];
        let r = gate_options_coherence(&cases);
        assert!(!r.passed());
        assert!(r.errors.iter().any(|e| e.contains("duplicate labels")));
    }
}
