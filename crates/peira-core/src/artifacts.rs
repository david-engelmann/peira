//! Artifacts: Rust implementation of peira's run artifact sealing.
//!
//! This is a port of `python/peira/artifacts.py`. The analysis lock is
//! SHA-256 over a canonical JSON payload. **Byte-exact compatibility with
//! Python is critical**: Python uses `json.dumps(payload, sort_keys=True)`
//! with default separators (`, ` and `: ` — note the spaces) and
//! `ensure_ascii=True`. Rust must replicate this exactly or hashes won't match.
//!
//! The canonical serialization rules:
//! - Keys sorted lexicographically (sort_keys=True)
//! - Separators: `", "` between items, `": "` between key and value
//! - ensure_ascii=True: non-ASCII chars escaped as \uXXXX
//! - No trailing whitespace, no indentation in the hashed payload

use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum ArtifactError {
    #[error("JSON serialization failed: {0}")]
    JsonError(String),
}

/// Compute the analysis lock (SHA-256) over the canonical payload.
///
/// The payload is serialized with Python-compatible JSON:
/// - sort_keys=True (BTreeMap gives us this)
/// - separators (', ', ': ') — with spaces, NOT compact
/// - ensure_ascii=True
///
/// The payload covers peira_version, dataset_version, adapter_name,
/// adapter_version, suite, config, results, AND metrics. Metrics are
/// lock-covered: rewriting the headline numbers after sealing invalidates
/// the lock. adapter_version is lock-covered: two runs that differ only in
/// the adapter's pinned version produce different locks.
#[allow(clippy::too_many_arguments)] // lock payload is inherently wide; mirrors Python's compute_lock
pub fn compute_lock(
    peira_version: &str,
    dataset_version: &str,
    adapter_name: &str,
    adapter_version: &str,
    suite: &str,
    config: &BTreeMap<String, serde_json::Value>,
    results: &[serde_json::Value],
    metrics: &serde_json::Value,
) -> Result<String, ArtifactError> {
    // Build the payload as a BTreeMap for sorted keys
    let mut payload = BTreeMap::new();
    payload.insert(
        "peira_version".to_string(),
        serde_json::Value::String(peira_version.to_string()),
    );
    payload.insert(
        "dataset_version".to_string(),
        serde_json::Value::String(dataset_version.to_string()),
    );
    payload.insert(
        "adapter_name".to_string(),
        serde_json::Value::String(adapter_name.to_string()),
    );
    payload.insert(
        "adapter_version".to_string(),
        serde_json::Value::String(adapter_version.to_string()),
    );
    payload.insert(
        "suite".to_string(),
        serde_json::Value::String(suite.to_string()),
    );
    payload.insert(
        "config".to_string(),
        serde_json::Value::Object(config.iter().map(|(k, v)| (k.clone(), v.clone())).collect()),
    );
    payload.insert(
        "results".to_string(),
        serde_json::Value::Array(results.to_vec()),
    );
    payload.insert("metrics".to_string(), metrics.clone());

    // Serialize with Python-compatible formatting.
    // Python: json.dumps(payload, sort_keys=True)
    //   - sort_keys: BTreeMap already sorted
    //   - separators default: (', ', ': ') — with spaces!
    //   - ensure_ascii=True: escape non-ASCII
    //
    // serde_json::to_string produces compact JSON (',', ':') — WRONG.
    // We need to replicate Python's exact output.
    let json_str =
        python_compatible_json(&serde_json::Value::Object(payload.into_iter().collect()));

    let mut hasher = Sha256::new();
    hasher.update(json_str.as_bytes());
    let result = hasher.finalize();
    Ok(format!("{:x}", result))
}

/// Format an f64 exactly like Python's `repr()` / `json.dumps`.
///
/// Python uses shortest-round-trip digits (like Ryu), then chooses notation:
/// - scientific if decimal exponent < -4 or >= 16
/// - fixed otherwise (always with a decimal point, e.g. `1.0` not `1`)
/// Exponent in scientific notation always has a sign and 2+ digits: `1e-07`, `1e+16`.
///
/// This is critical for cross-implementation artifact hash parity: the analysis
/// lock is SHA-256 over the canonical JSON, so byte-exact float formatting
/// is required.
fn python_float_repr(f: f64) -> String {
    // NaN/Infinity: Python's json.dumps emits these (allow_nan=True by default).
    // serde_json::Value can't hold them, but handle defensively.
    if f.is_nan() {
        return "NaN".to_string();
    }
    if f.is_infinite() {
        return if f > 0.0 {
            "Infinity".to_string()
        } else {
            "-Infinity".to_string()
        };
    }

    // Get Ryu's shortest-round-trip digits. Ryu and Python's repr produce
    // the same significant digits (both correctly-rounded shortest), but
    // differ in notation choice and exponent formatting.
    let ryu_str = match serde_json::Number::from_f64(f) {
        Some(n) => n.to_string(),
        None => return "0.0".to_string(), // shouldn't happen (NaN/inf handled above)
    };

    // Parse Ryu output into (negative, digits, exp) where value = digits * 10^exp.
    // Ryu forms: [-]digits[.digits][e[+-]digits]
    let (neg, digits, exp) = parse_ryu_float(&ryu_str);

    // Decimal exponent of the most significant digit.
    let decimal_exp = exp + digits.len() as i32 - 1;

    // Python's notation rule: scientific if exp < -4 or exp >= 16.
    if decimal_exp < -4 || decimal_exp >= 16 {
        format_python_scientific(neg, &digits, decimal_exp)
    } else {
        format_python_fixed(neg, &digits, exp)
    }
}

/// Parse Ryu float output into (negative, significant_digits, exp).
/// Returns digits as a string of decimal digits (no leading zeros, at least one
/// digit) and exp such that value = digits * 10^exp.
fn parse_ryu_float(s: &str) -> (bool, String, i32) {
    let neg = s.starts_with('-');
    let s = s.strip_prefix('-').unwrap_or(s);

    // Split off exponent.
    let (mantissa, exp_val) = match s.find(['e', 'E']) {
        Some(i) => {
            let exp_str = &s[i + 1..];
            let exp_val: i32 = exp_str.parse().unwrap_or(0);
            (&s[..i], exp_val)
        }
        None => (s, 0),
    };

    // Split mantissa into integer and fractional parts.
    let (int_part, frac_part) = match mantissa.find('.') {
        Some(i) => (&mantissa[..i], &mantissa[i + 1..]),
        None => (mantissa, ""),
    };

    // Combine digits; exponent is determined by decimal point position.
    // value = (int_part + frac_part as integer) * 10^(-frac_len + exp_val)
    let combined = format!("{}{}", int_part, frac_part);
    let exp = exp_val - frac_part.len() as i32;

    // Strip leading zeros (does not affect exponent).
    let digits = combined.trim_start_matches('0');
    let digits = if digits.is_empty() { "0" } else { digits };

    // Strip trailing zeros, adjusting exponent.
    // E.g. "1000" with exp=-1 (from "100.0") -> "1" with exp=2.
    let digits_trimmed = digits.trim_end_matches('0');
    let (digits, exp) = if digits_trimmed.is_empty() {
        ("0".to_string(), 0)
    } else {
        let trailing = digits.len() - digits_trimmed.len();
        (digits_trimmed.to_string(), exp + trailing as i32)
    };

    (neg, digits, exp)
}

/// Format in Python scientific notation: d[.ddd]e±XX (2+ digit exponent).
fn format_python_scientific(neg: bool, digits: &str, decimal_exp: i32) -> String {
    let mut out = String::new();
    if neg {
        out.push('-');
    }
    // First digit, then remaining digits after decimal point (if any).
    let mut chars = digits.chars();
    out.push(chars.next().unwrap_or('0'));
    let rest: String = chars.collect();
    if !rest.is_empty() {
        out.push('.');
        out.push_str(&rest);
    }
    out.push('e');
    // Exponent: always signed, at least 2 digits.
    if decimal_exp >= 0 {
        out.push('+');
    } else {
        out.push('-');
    }
    let abs_exp = decimal_exp.abs();
    if abs_exp < 10 {
        out.push('0');
    }
    out.push_str(&abs_exp.to_string());
    out
}

/// Format in Python fixed notation: always includes a decimal point.
fn format_python_fixed(neg: bool, digits: &str, exp: i32) -> String {
    let mut out = String::new();
    if neg {
        out.push('-');
    }

    // value = digits * 10^exp
    // digits has d characters, representing an integer.
    // Decimal point goes after the (d + exp)th character from the left,
    // counting from 1. If d + exp <= 0, we need leading zeros.
    // If d + exp >= d, we need trailing zeros.

    let d = digits.len() as i32;
    let point_pos = d + exp; // position of decimal point from left (1-indexed)

    if point_pos <= 0 {
        // 0.000...digits
        out.push_str("0.");
        for _ in 0..(-point_pos) {
            out.push('0');
        }
        out.push_str(digits);
    } else if point_pos >= d {
        // digits followed by zeros, then .0
        out.push_str(digits);
        for _ in 0..(point_pos - d) {
            out.push('0');
        }
        out.push_str(".0");
    } else {
        // Decimal point within digits.
        let (left, right) = digits.split_at(point_pos as usize);
        out.push_str(left);
        out.push('.');
        out.push_str(right);
    }
    out
}

/// Format a serde_json::Number like Python's json.dumps.
/// Integers use standard formatting; floats use python_float_repr.
fn python_json_number(n: &serde_json::Value) -> String {
    if let serde_json::Value::Number(num) = n {
        if num.is_i64() || num.is_u64() {
            num.to_string()
        } else if let Some(f) = num.as_f64() {
            python_float_repr(f)
        } else {
            num.to_string()
        }
    } else {
        // Not a number; fall back (shouldn't happen)
        python_compatible_json(n)
    }
}

/// Escape a string exactly like Python's `json.dumps(ensure_ascii=True)`.
///
/// Python's rules:
/// - `"` → `\"`, `\` → `\\`
/// - `\n` → `\\n`, `\r` → `\\r`, `\t` → `\\t`
/// - `\x08` → `\\b`, `\x0c` → `\\f` (short escapes, NOT \u0008/\u000c)
/// - Other C0 controls (U+0000-U+001F) → `\uXXXX`
/// - DEL (U+007F) → `\u007f` (ensure_ascii escapes this)
/// - Non-ASCII (> U+007F) → `\uXXXX` (surrogate pairs for astral chars)
fn escape_python_string(s: &str) -> String {
    let mut out = String::with_capacity(s.len() + 2);
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            // Python uses short escapes for backspace and form feed.
            '\u{0008}' => out.push_str("\\b"),
            '\u{000C}' => out.push_str("\\f"),
            c if (c as u32) < 0x20 => {
                out.push_str(&format!("\\u{:04x}", c as u32));
            }
            // DEL (0x7F) is escaped by ensure_ascii=True.
            c if (c as u32) == 0x7F => {
                out.push_str("\\u007f");
            }
            c if (c as u32) > 0x7F => {
                // ensure_ascii: escape as \uXXXX
                // For chars outside BMP, Python uses surrogate pairs
                let n = c as u32;
                if n > 0xFFFF {
                    let n2 = n - 0x10000;
                    let high = 0xD800 + (n2 >> 10);
                    let low = 0xDC00 + (n2 & 0x3FF);
                    out.push_str(&format!("\\u{:04x}\\u{:04x}", high, low));
                } else {
                    out.push_str(&format!("\\u{:04x}", n));
                }
            }
            c => out.push(c),
        }
    }
    out.push('"');
    out
}

/// Serialize a JSON value with Python's `json.dumps(sort_keys=True)` semantics.
///
/// Python's default separators are (', ', ': ') — with a space after each.
/// This is different from serde_json's compact output.
fn python_compatible_json(value: &serde_json::Value) -> String {
    match value {
        serde_json::Value::Null => "null".to_string(),
        serde_json::Value::Bool(b) => b.to_string(),
        serde_json::Value::Number(_) => python_json_number(value),
        serde_json::Value::String(s) => escape_python_string(s),
        serde_json::Value::Array(arr) => {
            let items: Vec<String> = arr.iter().map(python_compatible_json).collect();
            format!("[{}]", items.join(", "))
        }
        serde_json::Value::Object(obj) => {
            // BTreeMap/Map is already sorted by key (serde_json::Map uses BTreeMap)
            let items: Vec<String> = obj
                .iter()
                .map(|(k, v)| {
                    format!(
                        "{}: {}",
                        python_compatible_json(&serde_json::Value::String(k.clone())),
                        python_compatible_json(v)
                    )
                })
                .collect();
            format!("{{{}}}", items.join(", "))
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn python_compat_separators() {
        // Python: json.dumps({"b": 2, "a": 1}, sort_keys=True)
        // Result: '{"a": 1, "b": 2}' — note spaces after : and ,
        let mut map = serde_json::Map::new();
        map.insert("b".to_string(), serde_json::Value::Number(2.into()));
        map.insert("a".to_string(), serde_json::Value::Number(1.into()));
        let v = serde_json::Value::Object(map);
        let s = python_compatible_json(&v);
        assert_eq!(s, r#"{"a": 1, "b": 2}"#);
    }

    #[test]
    fn python_compat_ascii() {
        // Python: json.dumps({"k": "café"}, sort_keys=True, ensure_ascii=True)
        // Result: '{"k": "caf\\u00e9"}'
        let mut map = serde_json::Map::new();
        map.insert(
            "k".to_string(),
            serde_json::Value::String("café".to_string()),
        );
        let v = serde_json::Value::Object(map);
        let s = python_compatible_json(&v);
        assert_eq!(s, r#"{"k": "caf\u00e9"}"#);
    }

    #[test]
    fn compute_lock_deterministic() {
        let config = BTreeMap::new();
        let results = vec![];
        let metrics = serde_json::Value::Object(serde_json::Map::new());
        let h1 = compute_lock(
            "0.1.0",
            "0.1.0-demo",
            "mock",
            "1.0.0",
            "trial-demo",
            &config,
            &results,
            &metrics,
        )
        .unwrap();
        let h2 = compute_lock(
            "0.1.0",
            "0.1.0-demo",
            "mock",
            "1.0.0",
            "trial-demo",
            &config,
            &results,
            &metrics,
        )
        .unwrap();
        assert_eq!(h1, h2);
        assert_eq!(h1.len(), 64); // SHA-256 hex
    }

    #[test]
    fn compute_lock_covers_metrics() {
        // P0-1: metrics are lock-covered. Same inputs with different
        // metrics must produce different locks.
        let config = BTreeMap::new();
        let results = vec![];
        let m1 = serde_json::json!({"benign_accuracy": 0.5});
        let m2 = serde_json::json!({"benign_accuracy": 1.0});
        let h1 = compute_lock(
            "0.1.0",
            "0.1.0-demo",
            "mock",
            "1.0.0",
            "trial-demo",
            &config,
            &results,
            &m1,
        )
        .unwrap();
        let h2 = compute_lock(
            "0.1.0",
            "0.1.0-demo",
            "mock",
            "1.0.0",
            "trial-demo",
            &config,
            &results,
            &m2,
        )
        .unwrap();
        assert_ne!(h1, h2);
    }

    #[test]
    fn hash_matches_python() {
        // CRITICAL: This hash must match Python's output exactly.
        // Python: hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        // where payload = {"peira_version": "0.1.0", "dataset_version": "0.1.0-demo",
        //                  "adapter_name": "mock", "adapter_version": "",
        //                  "suite": "trial-demo",
        //                  "config": {}, "results": [], "metrics": {}}
        // If this test fails, the Rust/Python artifact hashes have diverged.
        let config = BTreeMap::new();
        let results = vec![];
        let metrics = serde_json::Value::Object(serde_json::Map::new());
        let h = compute_lock(
            "0.1.0",
            "0.1.0-demo",
            "mock",
            "",
            "trial-demo",
            &config,
            &results,
            &metrics,
        )
        .unwrap();
        assert_eq!(
            h,
            "3b0e7fac92b55ebdf0e13391a2b80f03390f60c13755aa5c260d883e413c48d2"
        );
    }

    #[test]
    fn hash_with_metrics_matches_python() {
        // Metrics-bearing payload, golden value computed from CPython:
        // hashlib.sha256(json.dumps({
        //   "peira_version": "0.1.0", "dataset_version": "0.1.0-demo",
        //   "adapter_name": "mock", "adapter_version": "1.2.3",
        //   "suite": "trial-demo",
        //   "config": {"timeout": 30.0},
        //   "results": [{"case_id": "x", "benign_correct": true}],
        //   "metrics": {"benign_accuracy": 0.7112, "asr_conditional": 0.25,
        //               "ece": 0.0, "n_cases": 12, "eligible": true},
        // }, sort_keys=True).encode()).hexdigest()
        let mut config = BTreeMap::new();
        config.insert(
            "timeout".to_string(),
            serde_json::Value::Number(serde_json::Number::from_f64(30.0).expect("finite")),
        );
        let results = vec![serde_json::json!({"case_id": "x", "benign_correct": true})];
        let metrics = serde_json::json!({
            "benign_accuracy": 0.7112,
            "asr_conditional": 0.25,
            "ece": 0.0,
            "n_cases": 12,
            "eligible": true,
        });
        let h = compute_lock(
            "0.1.0",
            "0.1.0-demo",
            "mock",
            "1.2.3",
            "trial-demo",
            &config,
            &results,
            &metrics,
        )
        .unwrap();
        assert_eq!(
            h,
            "e46963f9c0770b26e7b582a02d578ebed17eb0a406a06cb3a936f0213bd40818"
        );
    }
}

/// Extract the string-escaping core of [`python_compatible_json`] so the
/// pretty-printer can share it.
fn json_escape(s: &str) -> String {
    escape_python_string(s)
}

/// Pretty-print matching Python's `json.dumps(obj, indent=2, sort_keys=True)`:
/// 2-space indent, `": "` key separator, one item per line, `{}`/`[]` for
/// empty containers. serde_json's `Map` is BTreeMap-backed (sorted) by
/// default, which gives us `sort_keys=True`.
fn python_pretty_json(value: &serde_json::Value, level: usize, out: &mut String) {
    match value {
        serde_json::Value::Null => out.push_str("null"),
        serde_json::Value::Bool(b) => out.push_str(if *b { "true" } else { "false" }),
        serde_json::Value::Number(_) => out.push_str(&python_json_number(value)),
        serde_json::Value::String(s) => out.push_str(&json_escape(s)),
        serde_json::Value::Array(arr) => {
            if arr.is_empty() {
                out.push_str("[]");
                return;
            }
            out.push_str("[\n");
            for (i, v) in arr.iter().enumerate() {
                out.push_str(&"  ".repeat(level + 1));
                python_pretty_json(v, level + 1, out);
                if i + 1 < arr.len() {
                    out.push(',');
                }
                out.push('\n');
            }
            out.push_str(&"  ".repeat(level));
            out.push(']');
        }
        serde_json::Value::Object(obj) => {
            if obj.is_empty() {
                out.push_str("{}");
                return;
            }
            out.push_str("{\n");
            for (i, (k, v)) in obj.iter().enumerate() {
                out.push_str(&"  ".repeat(level + 1));
                out.push_str(&json_escape(k));
                out.push_str(": ");
                python_pretty_json(v, level + 1, out);
                if i + 1 < obj.len() {
                    out.push(',');
                }
                out.push('\n');
            }
            out.push_str(&"  ".repeat(level));
            out.push('}');
        }
    }
}

fn days_to_civil(z: i64) -> (i64, u32, u32) {
    // Howard Hinnant's civil_from_days.
    let z = z + 719468;
    let era = if z >= 0 { z } else { z - 146096 } / 146097;
    let doe = (z - era * 146097) as u64;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let y = yoe as i64 + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let m = if mp < 10 { mp + 3 } else { mp - 9 } as u32;
    (if m <= 2 { y + 1 } else { y }, m, d)
}

/// Current UTC time as an ISO-8601 string, matching Python's
/// `datetime.now(timezone.utc).isoformat()` (e.g.
/// `2026-09-24T22:55:38.123456+00:00`). No chrono dependency.
pub fn utc_now_iso8601() -> String {
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default();
    let secs = now.as_secs() as i64;
    let micros = now.subsec_micros();
    let (y, m, d) = days_to_civil(secs.div_euclid(86400));
    let tod = secs.rem_euclid(86400);
    let (hh, mm, ss) = (
        (tod / 3600) as u32,
        ((tod % 3600) / 60) as u32,
        (tod % 60) as u32,
    );
    format!("{y:04}-{m:02}-{d:02}T{hh:02}:{mm:02}:{ss:02}.{micros:06}+00:00")
}

/// A run artifact: the frozen record of one evaluation run.
/// Mirrors Python's `artifacts.RunArtifact` field-for-field so artifacts
/// are interchangeable between the Python and Rust CLIs.
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct RunArtifact {
    pub artifact_version: String,
    pub peira_version: String,
    pub dataset_version: String,
    pub adapter_name: String,
    #[serde(default)]
    pub adapter_version: String,
    pub suite: String,
    pub created_utc: String,
    pub config: BTreeMap<String, serde_json::Value>,
    pub results: Vec<serde_json::Value>,
    #[serde(default)]
    pub metrics: serde_json::Value,
    pub analysis_lock: String,
}

impl Default for RunArtifact {
    fn default() -> Self {
        Self {
            artifact_version: "1".to_string(),
            peira_version: crate::VERSION.to_string(),
            dataset_version: String::new(),
            adapter_name: String::new(),
            adapter_version: String::new(),
            suite: String::new(),
            created_utc: utc_now_iso8601(),
            config: BTreeMap::new(),
            results: Vec::new(),
            metrics: serde_json::Value::Object(serde_json::Map::new()),
            analysis_lock: String::new(),
        }
    }
}

impl RunArtifact {
    /// Serialize like Python's `json.dumps(asdict(self), indent=2, sort_keys=True)`.
    pub fn to_json(&self) -> Result<String, ArtifactError> {
        let v = serde_json::to_value(self).map_err(|e| ArtifactError::JsonError(e.to_string()))?;
        let mut out = String::new();
        python_pretty_json(&v, 0, &mut out);
        Ok(out)
    }

    pub fn from_json(s: &str) -> Result<Self, ArtifactError> {
        serde_json::from_str(s).map_err(|e| ArtifactError::JsonError(e.to_string()))
    }

    /// Compute and store the analysis lock.
    pub fn seal(&mut self) -> Result<(), ArtifactError> {
        self.analysis_lock = compute_lock(
            &self.peira_version,
            &self.dataset_version,
            &self.adapter_name,
            &self.adapter_version,
            &self.suite,
            &self.config,
            &self.results,
            &self.metrics,
        )?;
        Ok(())
    }

    /// Recompute the lock and compare — false means tampered.
    pub fn verify(&self) -> bool {
        match compute_lock(
            &self.peira_version,
            &self.dataset_version,
            &self.adapter_name,
            &self.adapter_version,
            &self.suite,
            &self.config,
            &self.results,
            &self.metrics,
        ) {
            Ok(h) => h == self.analysis_lock,
            Err(_) => false,
        }
    }
}

#[cfg(test)]
mod artifact_tests {
    use super::*;

    #[test]
    fn pretty_matches_python_layout() {
        // Python: json.dumps({"b": [1, 2], "a": {}, "c": 1}, indent=2, sort_keys=True)
        let v = serde_json::json!({"b": [1, 2], "a": {}, "c": 1});
        let mut out = String::new();
        python_pretty_json(&v, 0, &mut out);
        assert_eq!(
            out,
            "{\n  \"a\": {},\n  \"b\": [\n    1,\n    2\n  ],\n  \"c\": 1\n}"
        );
    }

    #[test]
    fn seal_verify_roundtrip() {
        let mut a = RunArtifact {
            adapter_name: "mock".to_string(),
            suite: "trial-demo".to_string(),
            dataset_version: "0.1.0-demo".to_string(),
            ..Default::default()
        };
        a.seal().unwrap();
        assert!(a.verify());
        a.results.push(serde_json::json!({"x": 1}));
        assert!(!a.verify());
    }

    #[test]
    fn utc_format() {
        let s = utc_now_iso8601();
        // e.g. 2026-09-24T22:55:38.123456+00:00
        assert!(s.len() == 32, "{s}");
        assert!(s.ends_with("+00:00"));
        assert_eq!(&s[10..11], "T");
    }
}

#[cfg(test)]
mod python_parity_tests {
    use super::*;

    #[test]
    fn float_repr_matches_python() {
        // Comprehensive float formatting vectors, verified against
        // CPython's json.dumps. Covers: two-digit exponents, sign on
        // positive exponents, notation-choice boundaries, negative zero.
        let cases = [
            // (rust f64, expected python json.dumps output)
            (30.0, "30.0"),
            (0.7112, "0.7112"),
            (0.25, "0.25"),
            (0.0, "0.0"),
            (-0.0, "-0.0"),
            (1.0, "1.0"),
            (100.0, "100.0"),
            (0.1, "0.1"),
            (1.23456, "1.23456"),
            (123456.789, "123456.789"),
            (0.30000000000000004, "0.30000000000000004"),
            // Scientific notation: two-digit signed exponents
            (1e-7, "1e-07"),
            (1e-6, "1e-06"),
            (1e-5, "1e-05"),
            (1e-10, "1e-10"),
            (1e-100, "1e-100"),
            (1.5e-7, "1.5e-07"),
            (2e-5, "2e-05"),
            (2.5e-5, "2.5e-05"),
            (5e-324, "5e-324"), // smallest subnormal
            (1e16, "1e+16"),
            (1e17, "1e+17"),
            (1e21, "1e+21"),
            (1e100, "1e+100"),
            (1.5e16, "1.5e+16"),
            (1.7976931348623157e308, "1.7976931348623157e+308"), // max f64
            (1.234567890123456e100, "1.234567890123456e+100"),
            // Notation-choice boundaries: fixed for -4 <= exp < 16
            (0.0001, "0.0001"), // 1e-4 -> fixed
            (0.001, "0.001"),
            (1000000000000000.0, "1000000000000000.0"), // 1e15 -> fixed
            (25000000000.0, "25000000000.0"),           // 2.5e10 -> fixed
            (1234567.0, "1234567.0"),
            // Just across the boundary -> scientific
            (0.00001, "1e-05"), // Ryu gives "0.00001", Python gives "1e-05"
            (9.999e-5, "9.999e-05"),
        ];
        for (f, expected) in cases {
            let got = python_float_repr(f);
            assert_eq!(got, expected, "python_float_repr({})", f);
        }
    }

    #[test]
    fn string_escape_matches_python() {
        // Verified against CPython's json.dumps(ensure_ascii=True).
        let cases = [
            ("\x08", r#""\b""#),     // backspace -> \b (not \u0008)
            ("\x0c", r#""\f""#),     // form feed -> \f (not \u000c)
            ("\x7f", r#""\u007f""#), // DEL -> \u007f
            ("\x00", r#""\u0000""#),
            ("\x1f", r#""\u001f""#),
            ("a\x08b", r#""a\bb""#),
            ("caf\u{e9}", r#""caf\u00e9""#),
            ("\u{1f600}", r#""\ud83d\ude00""#), // surrogate pair
            ("hello", r#""hello""#),
            ("a\"b", r#""a\"b""#),
            ("a\\b", r#""a\\b""#),
            ("a\nb", r#""a\nb""#),
            ("a\rb", r#""a\rb""#),
            ("a\tb", r#""a\tb""#),
        ];
        for (s, expected) in cases {
            let got = escape_python_string(s);
            assert_eq!(got, expected, "escape_python_string({:?})", s);
        }
    }

    #[test]
    fn canonical_json_matches_python_dumps() {
        // End-to-end: build a value with tricky floats/strings, compare
        // against Python's json.dumps(sort_keys=True).
        // Python: json.dumps({"f": 1e-7, "s": "\x08\x7f", "n": 42}, sort_keys=True)
        //       -> '{"f": 1e-07, "n": 42, "s": "\\b\\u007f"}'
        let v = serde_json::json!({
            "f": 1e-7,
            "s": "\x08\x7f",
            "n": 42,
        });
        let got = python_compatible_json(&v);
        assert_eq!(
            got,
            r#"{"f": 1e-07, "n": 42, "s": "\b﻿"}"#.replace("﻿", "\\u007f")
        );
    }
}

#[cfg(test)]
mod differential_tests {
    use super::*;
    use std::fs;

    #[test]
    fn rust_matches_python_on_53_vectors() {
        // Differential test: vectors generated by CPython's json.dumps.
        // Run: python3 gen_vectors.py > /tmp/python_vectors.json
        let data = fs::read_to_string("/tmp/python_vectors.json")
            .expect("run python vector generator first");
        let vectors: Vec<serde_json::Value> = serde_json::from_str(&data).unwrap();
        assert!(
            vectors.len() >= 50,
            "expected 50+ vectors, got {}",
            vectors.len()
        );
        for v in &vectors {
            let typ = v["type"].as_str().unwrap();
            let expected = v["output"].as_str().unwrap();
            let got = match typ {
                "float" => {
                    let f = v["input"].as_f64().unwrap();
                    python_float_repr(f)
                }
                "string" => {
                    let s = v["input"].as_str().unwrap();
                    escape_python_string(s)
                }
                "object" => python_compatible_json(&v["input"]),
                _ => panic!("unknown vector type: {}", typ),
            };
            assert_eq!(got, expected, "mismatch for {} input {}", typ, v["input"]);
        }
    }
}
