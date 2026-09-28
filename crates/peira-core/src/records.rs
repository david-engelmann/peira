//! Transcript and adapter-output record assembly.
//!
//! Mirrors the pure record-building helpers in `python/peira/runner.py`
//! (`_blank_record`, `_record_from_transcript_entry`, `_output_to_dict`,
//! `_output_from_dict`) and `python/peira/concurrency.py`
//! (`validate_transcript_entry`). These are the serialization seams of
//! the run pipeline: adapter outputs become transcript/cache dicts, and
//! transcript entries become [`CallRecord`]s on replay. No I/O, no
//! randomness — dict in, record out.
//!
//! All functions take [`serde_json::Value`] so the PyO3 layer stays a
//! thin translation shim. Error strings mirror the Python reference
//! messages; the bindings map them onto the same exception types the
//! Python side raises (`KeyError` for missing keys, `ValueError` for
//! failed validation, `TypeError` for wrong-shaped values, and
//! `AttributeError` where the reference would raise one).

use serde::Serialize;
use serde_json::Value;

use crate::metrics::{CallRecord, CallUsage};

/// The ten required transcript-entry fields, in the order
/// `python/peira/concurrency.py::TRANSCRIPT_REQUIRED` lists them.
pub const TRANSCRIPT_REQUIRED: [&str; 10] = [
    "dispatch_index",
    "case_id",
    "variant",
    "primitive",
    "request",
    "response",
    "provider",
    "seed",
    "dispatch_limit",
    "max_concurrency",
];

/// One normalized adapter output, as `_output_from_dict` rebuilds it.
///
/// The Python reference returns a different dataclass per primitive
/// (`ChoiceOutput` / `ScoreOutput` / `AbstainOutput`); they share every
/// field, so one struct with the primitive name and an optional `score`
/// captures the same information. The Python dispatch wrapper constructs
/// the concrete dataclass from this.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct AdapterOutput {
    pub primitive: String,
    pub decision: String,
    pub confidence: Option<f64>,
    /// Missing key vs explicit null, mirroring `d.get("abstained", False)`:
    /// `None` = key missing (the caller's default applies), `Some(None)` =
    /// explicit null (passes through as null), `Some(Some(b))` = a value.
    /// Serialized with the key absent when missing, so the Python wrapper's
    /// `.get("abstained", False)` default still applies.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub abstained: Option<Option<bool>>,
    /// Same missing-vs-null distinction as `abstained`, mirroring
    /// `d.get("refusal_reason", "")`.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub refusal_reason: Option<Option<String>>,
    pub usage: Option<CallUsage>,
    /// Only `Some` for the score primitive (mirrors `ScoreOutput`).
    pub score: Option<f64>,
}

/// The record for a call that produced nothing usable.
///
/// Mirrors `runner._blank_record`: the decision is the `"<error>"`
/// sentinel (never a real decision label), confidence is unknown, and
/// the malformed flag carries the signal.
pub fn blank_record(seed: i64, dispatch_index: i64, dispatch_limit: i64) -> CallRecord {
    CallRecord {
        decision: "<error>".to_string(),
        confidence: None,
        abstained: false,
        refusal_reason: String::new(),
        usage: None,
        seed,
        dispatch_index,
        malformed: true,
        dispatch_limit,
        score: None,
    }
}

fn get<'a>(v: &'a Value, key: &str) -> Result<&'a Value, String> {
    // "missing key: <name>" — the PyO3 layer maps this prefix to KeyError,
    // matching the Python reference's `entry["seed"]` subscription errors.
    v.get(key).ok_or_else(|| format!("missing key: {key}"))
}

fn as_i64(v: &Value, what: &str) -> Result<i64, String> {
    if let Some(i) = v.as_i64() {
        Ok(i)
    } else if let Some(u) = v.as_u64() {
        i64::try_from(u).map_err(|_| format!("{what} out of range: {u}"))
    } else {
        Err(format!("{what} must be an integer"))
    }
}

fn parse_usage(v: &Value, where_: &str) -> Result<CallUsage, String> {
    serde_json::from_value(v.clone())
        .map_err(|e| format!("{where_} field 'usage' is malformed: {e}"))
}

/// The Python type name of a JSON value, for CPython-faithful error
/// messages on shape mismatches.
fn json_type_name(v: &Value) -> &'static str {
    match v {
        Value::Null => "NoneType",
        Value::Bool(_) => "bool",
        Value::Number(n) => {
            if n.is_i64() || n.is_u64() {
                "int"
            } else {
                "float"
            }
        }
        Value::String(_) => "str",
        Value::Array(_) => "list",
        Value::Object(_) => "dict",
    }
}

/// Rebuild the original [`CallRecord`] from a transcript entry.
///
/// Mirrors `runner._record_from_transcript_entry`: no measurement is
/// re-taken — decision, confidence, score, abstention, usage, seed,
/// dispatch index, and dispatch limit all come from the recorded entry.
/// An error-kind entry rebuilds the malformed blank record the original
/// run sealed.
///
/// A score belongs only to the score primitive: `_output_to_dict`
/// writes it for score outputs only, so a score on any other
/// primitive's entry is foreign data (a hand-edited transcript) and
/// must not leak into the rebuilt record.
pub fn record_from_transcript_entry(entry: &Value) -> Result<CallRecord, String> {
    let seed = as_i64(get(entry, "seed")?, "seed")?;
    let dispatch_index = as_i64(get(entry, "dispatch_index")?, "dispatch_index")?;
    let dispatch_limit = as_i64(get(entry, "dispatch_limit")?, "dispatch_limit")?;
    let response = get(entry, "response")?;
    // The reference subscripts `response["kind"]`: a non-mapping
    // response raises TypeError there (not KeyError), so the Rust side
    // must raise TypeError too. The "type error: " prefix is mapped to
    // PyTypeError by the bindings.
    if !response.is_object() {
        return Err(format!(
            "type error: response is not a mapping (got '{}')",
            json_type_name(response)
        ));
    }
    let kind = get(response, "kind")?
        .as_str()
        .ok_or_else(|| "response kind must be a string".to_string())?;
    if kind != "output" {
        return Ok(blank_record(seed, dispatch_index, dispatch_limit));
    }
    let out = get(response, "output")?;
    // The reference calls `out.get("usage")`: a non-object output
    // raises AttributeError there (not KeyError), so the Rust side
    // must raise AttributeError too. The "attribute error: " prefix is
    // mapped to PyAttributeError by the bindings, with a CPython-exact
    // message.
    if !out.is_object() {
        return Err(format!(
            "attribute error: '{}' object has no attribute 'get'",
            json_type_name(out)
        ));
    }
    let usage_value = out.get("usage").unwrap_or(&Value::Null);
    let usage = if usage_value.is_null() {
        None
    } else {
        Some(parse_usage(usage_value, "output")?)
    };
    // Score only survives on score-primitive entries (see docstring).
    // It is passed through unvalidated like the Python reference — but
    // only numbers fit the typed record, so a non-numeric score errors
    // here and the Python wrapper falls back to the reference, which
    // passes it through untouched.
    let primitive = entry.get("primitive").and_then(|v| v.as_str());
    let score = if primitive == Some("score") {
        match out.get("score") {
            None | Some(Value::Null) => None,
            Some(v) => Some(
                v.as_f64()
                    .ok_or_else(|| "output field 'score' must be a number or null".to_string())?,
            ),
        }
    } else {
        None
    };
    let decision = get(out, "decision")?
        .as_str()
        .ok_or_else(|| "output field 'decision' must be a string".to_string())?
        .to_string();
    let confidence = match out.get("confidence") {
        None | Some(Value::Null) => None,
        Some(v) => Some(
            v.as_f64()
                .ok_or_else(|| "output field 'confidence' must be a number or null".to_string())?,
        ),
    };
    let abstained = match out.get("abstained") {
        None | Some(Value::Null) => false,
        Some(Value::Bool(b)) => *b,
        Some(_) => {
            return Err("output field 'abstained' must be a boolean".to_string());
        }
    };
    let refusal_reason = match out.get("refusal_reason") {
        None | Some(Value::Null) => String::new(),
        Some(Value::String(s)) => s.clone(),
        Some(_) => {
            return Err("output field 'refusal_reason' must be a string".to_string());
        }
    };
    Ok(CallRecord {
        decision,
        confidence,
        abstained,
        refusal_reason,
        usage,
        seed,
        dispatch_index,
        malformed: false,
        dispatch_limit,
        score,
    })
}

/// Serialize an adapter output for transcripts and the cache.
///
/// Mirrors `runner._output_to_dict`: the dict carries exactly the known
/// keys (decision, confidence, abstained, refusal_reason, usage) plus
/// `score` for the score primitive. `output` is the output's field map
/// (decision/confidence/abstained/refusal_reason/usage-as-dict, plus
/// `score` for score outputs); `usage` is already a plain dict or null,
/// as `dataclasses.asdict` would produce.
pub fn output_to_dict(primitive: &str, output: &Value) -> Result<Value, String> {
    let mut map = serde_json::Map::with_capacity(6);
    for key in [
        "decision",
        "confidence",
        "abstained",
        "refusal_reason",
        "usage",
    ] {
        map.insert(key.to_string(), get(output, key)?.clone());
    }
    if primitive == "score" {
        map.insert("score".to_string(), get(output, "score")?.clone());
    }
    Ok(Value::Object(map))
}

/// Rebuild a normalized adapter output from its serialized form.
///
/// Mirrors `runner._output_from_dict`: raises on wrong-shaped dicts
/// (callers treat that as a cache miss — never trust a corrupt entry)
/// and on unknown primitives. `usage`, when present, must carry the
/// five `CallUsage` fields.
pub fn output_from_dict(primitive: &str, d: &Value) -> Result<AdapterOutput, String> {
    let usage_value = d.get("usage").unwrap_or(&Value::Null);
    let usage = if usage_value.is_null() {
        None
    } else {
        Some(parse_usage(usage_value, "output")?)
    };
    let decision = get(d, "decision")?
        .as_str()
        .ok_or_else(|| "output field 'decision' must be a string".to_string())?
        .to_string();
    let confidence = match d.get("confidence") {
        None | Some(Value::Null) => None,
        Some(v) => Some(
            v.as_f64()
                .ok_or_else(|| "output field 'confidence' must be a number or null".to_string())?,
        ),
    };
    // Missing vs explicit-null, exactly like `d.get("abstained", False)`:
    // a missing key leaves the field absent (the caller defaults it to
    // False), an explicit null serializes as null (the caller passes
    // None through), any other non-bool is an error.
    let abstained = match d.get("abstained") {
        None => None,
        Some(Value::Null) => Some(None),
        Some(Value::Bool(b)) => Some(Some(*b)),
        Some(_) => {
            return Err("output field 'abstained' must be a boolean".to_string());
        }
    };
    let refusal_reason = match d.get("refusal_reason") {
        None => None,
        Some(Value::Null) => Some(None),
        Some(Value::String(s)) => Some(Some(s.clone())),
        Some(_) => {
            return Err("output field 'refusal_reason' must be a string".to_string());
        }
    };
    let score = match primitive {
        "choice" | "abstain" => None,
        "score" => Some(
            get(d, "score")?
                .as_f64()
                .ok_or_else(|| "score output field 'score' must be a number".to_string())?,
        ),
        other => return Err(format!("unknown primitive: {other:?}")),
    };
    Ok(AdapterOutput {
        primitive: primitive.to_string(),
        decision,
        confidence,
        abstained,
        refusal_reason,
        usage,
        score,
    })
}

/// Strictly validate one transcript JSONL entry (replay input).
///
/// Mirrors `concurrency.validate_transcript_entry`: required fields,
/// variant enum, bool-rejecting integer checks, response-kind enum,
/// output-object check, and the provider adapter-name requirement.
/// Returns `Ok(())` when the entry is well-formed; the entry itself is
/// returned by the caller (the Python reference returns it unchanged).
pub fn validate_transcript_entry(entry: &Value, lineno: i64) -> Result<(), String> {
    let where_ = format!("transcript line {lineno}");
    let obj = entry
        .as_object()
        .ok_or_else(|| format!("{where_}: expected an object"))?;
    for key in TRANSCRIPT_REQUIRED {
        if !obj.contains_key(key) {
            return Err(format!("{where_}: missing field {key:?}"));
        }
    }
    match entry.get("variant").and_then(|v| v.as_str()) {
        Some("benign") | Some("attacked") => {}
        other => {
            return Err(format!(
                "{where_}: variant must be 'benign' or 'attacked', got {}",
                other.map_or("null".to_string(), |s| format!("{s:?}"))
            ));
        }
    }
    for key in [
        "dispatch_index",
        "seed",
        "dispatch_limit",
        "max_concurrency",
    ] {
        let v = &entry[key];
        let ok = v.as_i64().is_some() || v.as_u64().is_some();
        // bool subclasses int in Python: explicitly rejected there, and
        // serde_json never parses a bool as a number here, so the check
        // above already excludes them.
        if !ok {
            return Err(format!("{where_}: {key} must be an integer"));
        }
    }
    let response = &entry["response"];
    let kind = response.get("kind").and_then(|v| v.as_str());
    if !response.is_object() || !matches!(kind, Some("output") | Some("error")) {
        return Err(format!(
            "{where_}: response.kind must be 'output' or 'error'"
        ));
    }
    if kind == Some("output") && !response.get("output").is_some_and(|v| v.is_object()) {
        return Err(format!("{where_}: response.output must be an object"));
    }
    let provider = &entry["provider"];
    let has_name = provider
        .get("adapter_name")
        .and_then(|v| v.as_str())
        .is_some_and(|s| !s.is_empty());
    if !provider.is_object() || !has_name {
        return Err(format!("{where_}: provider.adapter_name is required"));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn usage() -> Value {
        json!({
            "model": "hf:x",
            "tokens_in": 10,
            "tokens_out": 0,
            "latency_ms": 12.5,
            "cost_usd": 0.0,
        })
    }

    fn output_entry() -> Value {
        json!({
            "seed": 7,
            "dispatch_index": 3,
            "dispatch_limit": 4,
            "primitive": "choice",
            "response": {
                "kind": "output",
                "output": {
                    "decision": "approve",
                    "confidence": 0.9,
                    "abstained": false,
                    "refusal_reason": "",
                    "usage": usage(),
                },
            },
        })
    }

    #[test]
    fn blank_record_shape() {
        let r = blank_record(7, 3, 4);
        assert_eq!(r.decision, "<error>");
        assert_eq!(r.confidence, None);
        assert!(!r.abstained);
        assert!(r.malformed);
        assert_eq!(r.seed, 7);
        assert_eq!(r.dispatch_index, 3);
        assert_eq!(r.dispatch_limit, 4);
        assert_eq!(r.usage, None);
        assert_eq!(r.score, None);
    }

    #[test]
    fn record_from_output_entry() {
        let r = record_from_transcript_entry(&output_entry()).unwrap();
        assert_eq!(r.decision, "approve");
        assert_eq!(r.confidence, Some(0.9));
        assert!(!r.malformed);
        assert_eq!(r.seed, 7);
        assert_eq!(r.dispatch_index, 3);
        assert_eq!(r.dispatch_limit, 4);
        assert_eq!(r.usage.as_ref().unwrap().tokens_in, 10);
        // score on a non-score primitive must not leak through
        assert_eq!(r.score, None);
    }

    #[test]
    fn record_from_error_entry_is_blank() {
        let mut e = output_entry();
        e["response"] = json!({"kind": "error", "detail": "boom"});
        let r = record_from_transcript_entry(&e).unwrap();
        assert_eq!(r.decision, "<error>");
        assert!(r.malformed);
        assert_eq!(r.seed, 7);
    }

    #[test]
    fn record_score_only_on_score_primitive() {
        let mut e = output_entry();
        e["primitive"] = json!("score");
        e["response"]["output"]["score"] = json!(0.75);
        let r = record_from_transcript_entry(&e).unwrap();
        assert_eq!(r.score, Some(0.75));

        // Same entry, non-score primitive: score must not leak in.
        let mut e2 = output_entry();
        e2["response"]["output"]["score"] = json!(0.75);
        let r2 = record_from_transcript_entry(&e2).unwrap();
        assert_eq!(r2.score, None);
    }

    #[test]
    fn record_missing_key_errors() {
        let mut e = output_entry();
        e.as_object_mut().unwrap().remove("seed");
        assert!(record_from_transcript_entry(&e).is_err());
    }

    #[test]
    fn output_to_dict_exact_keys() {
        let out = json!({
            "decision": "deny",
            "confidence": 0.4,
            "abstained": false,
            "refusal_reason": "",
            "usage": usage(),
            "extra": "dropped",
        });
        let d = output_to_dict("choice", &out).unwrap();
        let obj = d.as_object().unwrap();
        assert_eq!(obj.len(), 5);
        assert!(!obj.contains_key("extra"));
        assert!(!obj.contains_key("score"));
        assert_eq!(d["decision"], json!("deny"));

        let d2 = output_to_dict(
            "score",
            &json!({
                "decision": "deny", "confidence": 0.4, "abstained": false,
                "refusal_reason": "", "usage": usage(), "score": 0.2,
            }),
        )
        .unwrap();
        assert_eq!(d2["score"], json!(0.2));
    }

    #[test]
    fn output_from_dict_roundtrip() {
        let d = json!({
            "decision": "approve",
            "confidence": 0.9,
            "abstained": false,
            "refusal_reason": "",
            "usage": usage(),
        });
        let o = output_from_dict("choice", &d).unwrap();
        assert_eq!(o.primitive, "choice");
        assert_eq!(o.decision, "approve");
        assert_eq!(o.score, None);

        let back = output_to_dict("choice", &serde_json::to_value(&o).unwrap()).unwrap();
        assert_eq!(back["decision"], json!("approve"));
        assert_eq!(back["usage"]["tokens_in"], json!(10));
    }

    #[test]
    fn output_from_dict_score_required() {
        let d = json!({
            "decision": "approve", "confidence": 0.9, "abstained": false,
            "refusal_reason": "", "usage": usage(),
        });
        assert!(output_from_dict("score", &d).is_err());
        let mut d2 = d.clone();
        d2["score"] = json!(0.3);
        let o = output_from_dict("score", &d2).unwrap();
        assert_eq!(o.score, Some(0.3));
    }

    #[test]
    fn output_from_dict_unknown_primitive() {
        let d = json!({"decision": "x"});
        let err = output_from_dict("nope", &d).unwrap_err();
        assert!(err.contains("unknown primitive"), "{err}");
    }

    #[test]
    fn output_from_dict_defaults() {
        // Missing keys stay missing (None): the Python wrapper's
        // `.get("abstained", False)` / `.get("refusal_reason", "")`
        // defaults apply downstream, exactly like the reference.
        let o = output_from_dict("abstain", &json!({"decision": "abstain"})).unwrap();
        assert_eq!(o.abstained, None);
        assert_eq!(o.refusal_reason, None);
        assert_eq!(o.usage, None);
        assert_eq!(o.confidence, None);
    }

    #[test]
    fn output_from_dict_explicit_null_optionals() {
        // An explicit null is NOT the missing-key default: it must
        // serialize as null so the reference passes None through.
        let o = output_from_dict(
            "choice",
            &json!({"decision": "approve", "abstained": null, "refusal_reason": null}),
        )
        .unwrap();
        assert_eq!(o.abstained, Some(None));
        assert_eq!(o.refusal_reason, Some(None));
        let v = serde_json::to_value(&o).unwrap();
        assert!(v.get("abstained").is_some());
        assert_eq!(v["abstained"], Value::Null);
        assert_eq!(v["refusal_reason"], Value::Null);
        // ...while a missing key serializes absent.
        let o2 = output_from_dict("choice", &json!({"decision": "approve"})).unwrap();
        let v2 = serde_json::to_value(&o2).unwrap();
        assert!(v2.get("abstained").is_none());
        assert!(v2.get("refusal_reason").is_none());
    }

    fn transcript_entry() -> Value {
        json!({
            "dispatch_index": 0,
            "case_id": "c1",
            "variant": "benign",
            "primitive": "choice",
            "request": {"prompt": "hi"},
            "response": {"kind": "output", "output": {"decision": "approve"}},
            "provider": {"adapter_name": "dummy"},
            "seed": 7,
            "dispatch_limit": 4,
            "max_concurrency": 8,
        })
    }

    #[test]
    fn validate_transcript_entry_ok() {
        assert!(validate_transcript_entry(&transcript_entry(), 1).is_ok());
    }

    #[test]
    fn validate_transcript_entry_rejects() {
        // not an object
        assert!(validate_transcript_entry(&json!([1]), 3).is_err());
        // missing field
        let mut e = transcript_entry();
        e.as_object_mut().unwrap().remove("seed");
        let err = validate_transcript_entry(&e, 5).unwrap_err();
        assert!(
            err.contains("transcript line 5") && err.contains("missing field"),
            "{err}"
        );
        // bad variant
        let mut e = transcript_entry();
        e["variant"] = json!("evil");
        assert!(validate_transcript_entry(&e, 1).is_err());
        // bool is not an integer
        let mut e = transcript_entry();
        e["seed"] = json!(true);
        assert!(validate_transcript_entry(&e, 1).is_err());
        // bad response kind
        let mut e = transcript_entry();
        e["response"] = json!({"kind": "weird"});
        assert!(validate_transcript_entry(&e, 1).is_err());
        // output must be an object
        let mut e = transcript_entry();
        e["response"] = json!({"kind": "output", "output": [1]});
        assert!(validate_transcript_entry(&e, 1).is_err());
        // error kind needs no output object
        let mut e = transcript_entry();
        e["response"] = json!({"kind": "error", "detail": "x"});
        assert!(validate_transcript_entry(&e, 1).is_ok());
        // provider name required
        let mut e = transcript_entry();
        e["provider"] = json!({"adapter_name": ""});
        assert!(validate_transcript_entry(&e, 1).is_err());
    }
}
