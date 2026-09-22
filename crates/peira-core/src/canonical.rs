//! Canonical JSON: byte-identical to Python's `json.dumps(sort_keys=True)`.
//!
//! The analysis lock is SHA-256 over canonical JSON, so Rust and Python
//! must serialize identically or they can't verify each other's artifacts.
//! The rules replicate CPython exactly:
//!
//! - Objects: keys sorted by Unicode code point (`BTreeMap` order on UTF-8
//!   is the same), `"key": value` separators (colon + space), `", "`
//!   between items, `{}` when empty.
//! - Arrays: `[a, b]` separators, `[]` when empty.
//! - Strings: `ensure_ascii` escaping — `"` and `\` escaped, the short
//!   escapes for `\n \r \t \b \f`, every other char outside `0x20..=0x7E`
//!   as `\uXXXX` (lowercase hex), astral chars as UTF-16 surrogate pairs.
//!   DEL (`0x7F`) is escaped; `~` and space pass through.
//! - Floats: shortest round-trip digits (via ryu), then Python's notation
//!   decision — scientific iff the decimal exponent puts the point at
//!   `decpt <= -4` or `decpt > 16` — with `e+XX`/`e-XX` exponents (sign
//!   always, at least two digits) and a `.0` suffix on integral values.
//!   Non-finite floats render as `Infinity`/`-Infinity`/`NaN`, matching
//!   Python's (non-standard) `json.dumps` behavior.
//! - Integers render as plain decimal; `true`/`false`/`null` lowercase.
//!
//! These are public because cross-language verification (and the future
//! PyO3 layer) needs them directly; most callers should prefer the typed
//! APIs in [`crate::artifact`] and [`crate::dataset`].
//!
//! [`to_pretty`] additionally replicates `json.dumps(indent=2, sort_keys=True)`
//! for human-readable artifact files: 2-space indent, `,` item separators
//! (no trailing space), `": "` key separators.

use serde_json::Value;

pub fn to_canonical(v: &Value) -> String {
    let mut out = String::new();
    write_canonical(v, &mut out);
    out
}

pub fn to_pretty(v: &Value) -> String {
    let mut out = String::new();
    write_pretty(v, &mut out, 0);
    out
}

fn write_canonical(v: &Value, out: &mut String) {
    match v {
        Value::Null => out.push_str("null"),
        Value::Bool(true) => out.push_str("true"),
        Value::Bool(false) => out.push_str("false"),
        Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                out.push_str(&i.to_string());
            } else if let Some(u) = n.as_u64() {
                out.push_str(&u.to_string());
            } else if let Some(f) = n.as_f64() {
                write_float(f, out);
            }
        }
        Value::String(s) => write_escaped(s, out),
        Value::Array(items) => {
            out.push('[');
            for (i, item) in items.iter().enumerate() {
                if i > 0 {
                    out.push_str(", ");
                }
                write_canonical(item, out);
            }
            out.push(']');
        }
        Value::Object(map) => {
            out.push('{');
            for (i, (k, val)) in map.iter().enumerate() {
                if i > 0 {
                    out.push_str(", ");
                }
                write_escaped(k, out);
                out.push_str(": ");
                write_canonical(val, out);
            }
            out.push('}');
        }
    }
}

/// `ensure_ascii` string escaping, matching CPython's encoder.
fn write_escaped(s: &str, out: &mut String) {
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{08}' => out.push_str("\\b"),
            '\u{0C}' => out.push_str("\\f"),
            c => {
                let n = c as u32;
                if (0x20..=0x7E).contains(&n) {
                    out.push(c);
                } else if n > 0xFFFF {
                    // Astral char: UTF-16 surrogate pair, lowercase hex.
                    let n = n - 0x1_0000;
                    let (hi, lo) = (0xD800 + (n >> 10), 0xDC00 + (n & 0x3FF));
                    out.push_str(&format!("\\u{hi:04x}\\u{lo:04x}"));
                } else {
                    out.push_str(&format!("\\u{n:04x}"));
                }
            }
        }
    }
    out.push('"');
}

/// Shortest round-trip digits from ryu, re-emitted with Python's notation
/// decision and exponent style.
fn write_float(f: f64, out: &mut String) {
    if f.is_nan() {
        out.push_str("NaN");
        return;
    }
    if f.is_infinite() {
        out.push_str(if f > 0.0 { "Infinity" } else { "-Infinity" });
        return;
    }
    let mut buf = ryu::Buffer::new();
    out.push_str(&python_float_repr(buf.format_finite(f)));
}

/// Re-emit a ryu shortest-digits string with Python `repr` formatting.
///
/// Parses the ryu output into (negative, digit string, decpt) where
/// value = 0.digits × 10^decpt, then applies CPython's rule: scientific
/// notation iff `decpt <= -4 || decpt > 16`.
fn python_float_repr(ryu: &str) -> String {
    let (neg, rest) = match ryu.strip_prefix('-') {
        Some(r) => (true, r),
        None => (false, ryu),
    };
    // Split mantissa / exponent.
    let (mant, exp): (&str, i32) = match rest.find(['e', 'E']) {
        Some(i) => (&rest[..i], rest[i + 1..].parse().unwrap_or(0)),
        None => (rest, 0),
    };
    // All digits of the mantissa, and decpt for 0.digits × 10^decpt.
    let dot = mant.find('.');
    let digits: String = mant.chars().filter(|c| c.is_ascii_digit()).collect();
    let k = digits.len() as i32; // total digits (ryu never emits empty)
                                 // decpt: value = 0.digits × 10^decpt.
                                 // With 'e': mantissa d1[.d2..] × 10^exp → decpt = exp + 1.
                                 // Without: mantissa int.frac with k digits, frac_len after the point
                                 //   → decpt = k - frac_len.
    let mut decpt = match dot {
        Some(d) if exp == 0 => {
            let frac_len = mant.len() as i32 - d as i32 - 1;
            k - frac_len
        }
        _ => exp + 1,
    };
    // Strip leading zeros (0.00001 → digits "1", decpt shifts down).
    // All-zero is exactly zero: normalize to digits "0", decpt 0.
    let stripped = digits.trim_start_matches('0');
    let (digits, decpt) = if stripped.is_empty() {
        ("0", 0)
    } else {
        decpt -= (digits.len() - stripped.len()) as i32;
        (stripped, decpt)
    };

    let mut s = String::new();
    if neg {
        s.push('-');
    }
    if decpt <= -4 || decpt > 16 {
        // Scientific: d1[.rest]e±XX.
        let (d1, rest_d) = digits.split_at(1);
        s.push_str(d1);
        if !rest_d.is_empty() {
            s.push('.');
            s.push_str(rest_d);
        }
        s.push_str(&format!("e{:+03}", decpt - 1));
    } else if decpt <= 0 {
        s.push_str("0.");
        s.push_str(&"0".repeat(-decpt as usize));
        s.push_str(digits);
    } else {
        let n = digits.len() as i32;
        if decpt >= n {
            s.push_str(digits);
            s.push_str(&"0".repeat((decpt - n) as usize));
            s.push_str(".0");
        } else {
            let d = decpt as usize;
            s.push_str(&digits[..d]);
            s.push('.');
            s.push_str(&digits[d..]);
        }
    }
    s
}

fn write_pretty(v: &Value, out: &mut String, indent: usize) {
    match v {
        Value::Array(items) if !items.is_empty() => {
            out.push_str("[\n");
            for (i, item) in items.iter().enumerate() {
                if i > 0 {
                    out.push_str(",\n");
                }
                out.push_str(&"  ".repeat(indent + 1));
                write_pretty(item, out, indent + 1);
            }
            out.push('\n');
            out.push_str(&"  ".repeat(indent));
            out.push(']');
        }
        Value::Object(map) if !map.is_empty() => {
            out.push_str("{\n");
            for (i, (k, val)) in map.iter().enumerate() {
                if i > 0 {
                    out.push_str(",\n");
                }
                out.push_str(&"  ".repeat(indent + 1));
                write_escaped(k, out);
                out.push_str(": ");
                write_pretty(val, out, indent + 1);
            }
            out.push('\n');
            out.push_str(&"  ".repeat(indent));
            out.push('}');
        }
        // Empty containers and scalars render inline, like Python.
        _ => write_canonical(v, out),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn separators_and_sorting() {
        let v = json!({"b": [1, 2], "a": {"z": null, "y": true}});
        assert_eq!(
            to_canonical(&v),
            r#"{"a": {"y": true, "z": null}, "b": [1, 2]}"#
        );
    }

    #[test]
    fn empty_containers() {
        assert_eq!(to_canonical(&json!({})), "{}");
        assert_eq!(to_canonical(&json!([])), "[]");
    }

    #[test]
    fn string_escapes() {
        // DEL escaped, ~ and space pass through, astral → surrogate pair.
        assert_eq!(
            to_canonical(&json!("\u{7f}~ \u{e9}\u{1f600}")),
            "\"\\u007f~ \\u00e9\\ud83d\\ude00\""
        );
        assert_eq!(to_canonical(&json!("a\"b\\c\nd")), "\"a\\\"b\\\\c\\nd\"");
    }

    #[test]
    fn float_notation() {
        // (ryu input is via f64; expected = Python repr)
        for (f, want) in [
            (0.0, "0.0"),
            (1.0, "1.0"),
            (0.1, "0.1"),
            (0.0001, "0.0001"),
            (1e-5, "1e-05"),
            (2.5e-7, "2.5e-07"),
            (1e15, "1000000000000000.0"),
            (1e16, "1e+16"),
            (5e-324, "5e-324"),
            (100.0, "100.0"),
            (0.30000000000000004, "0.30000000000000004"),
        ] {
            assert_eq!(to_canonical(&json!(f)), want, "for {f}");
        }
    }

    #[test]
    fn non_finite_floats_match_python_json() {
        // serde_json::Value cannot hold non-finite floats (like Python's
        // parsed JSON), so exercise write_float directly.
        for (f, want) in [
            (f64::INFINITY, "Infinity"),
            (f64::NEG_INFINITY, "-Infinity"),
            (f64::NAN, "NaN"),
        ] {
            let mut s = String::new();
            write_float(f, &mut s);
            assert_eq!(s, want);
        }
    }

    #[test]
    fn negative_zero() {
        assert_eq!(to_canonical(&json!(-0.0)), "-0.0");
    }

    #[test]
    fn pretty_matches_python_indent2() {
        let v = json!({"b": [1, {"x": []}], "a": 1});
        assert_eq!(
            to_pretty(&v),
            "{\n  \"a\": 1,\n  \"b\": [\n    1,\n    {\n      \"x\": []\n    }\n  ]\n}"
        );
    }
}
