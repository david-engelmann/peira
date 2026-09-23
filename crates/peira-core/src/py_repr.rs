//! Python `repr()` for strings and small JSON values.
//!
//! The schema validator and the dataset verifier interpolate values into
//! error messages that must read identically no matter which module — or
//! which language — produced them. This module is the Rust side of that
//! contract, and it is the *only* copy: [`crate::schema`] and
//! [`crate::dataset`] both use these helpers (an earlier revision carried
//! two divergent copies).
//!
//! The escaping rule is fixed and shared, not "CPython repr as close as
//! we can get it": CPython's `repr()` escapes non-printable non-ASCII
//! (e.g. U+200B ZERO WIDTH SPACE) as `\uNNNN`, which this crate cannot
//! reproduce without a Unicode database. The Python side therefore does
//! *not* use `repr()` for the mirrored messages — it uses `_safe_repr`
//! (`python/peira/schema.py`), which implements exactly the rule below.
//! The two implementations must stay in sync; the cross-language tests in
//! `tests/test_rust_backend.py` pin the contract.
//!
//! Fidelity rules, checked against CPython 3.12 for the overlapping
//! domain (pinned in the tests below):
//!
//! - Strings are single-quoted unless they contain `'` but not `"`, in
//!   which case they are double-quoted (CPython's quote-selection rule).
//! - `\n`, `\r`, `\t`, `\\`, and the active quote get their short
//!   escapes. Every other control character — all of C0, DEL, and C1,
//!   i.e. `c.is_control()` — renders as `\xNN`. Notably CPython's
//!   `repr()` does *not* use `\b`/`\f`.
//! - Everything else passes through raw: printable non-ASCII (`'café'`,
//!   `'😀'`) exactly like CPython, and non-printable non-ASCII outside
//!   C1 (U+200B, unassigned, private-use, ...) raw as well — this last
//!   class is where the rule deliberately differs from `repr()`.
//! - Floats go through [`crate::canonical`] so `1e-5` renders as
//!   `1e-05`, matching `repr(1e-5)`.

use serde_json::Value;

/// Python `repr()` for a string.
pub fn py_repr_str(s: &str) -> String {
    // CPython's rule: single quotes, unless the string contains a single
    // quote but no double quote.
    let quote = if s.contains('\'') && !s.contains('"') {
        '"'
    } else {
        '\''
    };
    let mut out = String::with_capacity(s.len() + 2);
    out.push(quote);
    for c in s.chars() {
        match c {
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if c == quote => {
                out.push('\\');
                out.push(c);
            }
            // C0, DEL, C1: \xNN, never raw and never \b / \f.
            c if c.is_control() => {
                out.push_str(&format!("\\x{:02x}", c as u32));
            }
            c => out.push(c),
        }
    }
    out.push(quote);
    out
}

/// Python `repr()` for a JSON value, for error messages.
///
/// Strings get Python quoting; `null`/`true`/`false` get Python
/// spellings; numbers render like `repr()` (floats via
/// [`crate::canonical`]'s notation rules); containers recurse with
/// Python's `", "` separators and single-quoted keys, matching
/// `str()` of a Python dict/list.
pub fn py_repr_value(v: &Value) -> String {
    match v {
        Value::String(s) => py_repr_str(s),
        Value::Null => "None".to_string(),
        Value::Bool(true) => "True".to_string(),
        Value::Bool(false) => "False".to_string(),
        Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                i.to_string()
            } else if let Some(u) = n.as_u64() {
                u.to_string()
            } else if let Some(f) = n.as_f64() {
                let mut buf = ryu::Buffer::new();
                crate::canonical::python_float_repr(buf.format_finite(f))
            } else {
                // Unreachable: serde_json numbers are i64/u64/f64.
                n.to_string()
            }
        }
        Value::Array(items) => {
            format!(
                "[{}]",
                items
                    .iter()
                    .map(py_repr_value)
                    .collect::<Vec<_>>()
                    .join(", ")
            )
        }
        Value::Object(map) => {
            // Explicit sort: never trust the map's iteration order
            // (see canonical.rs on the `preserve_order` hazard).
            let mut keys: Vec<&String> = map.keys().collect();
            keys.sort();
            let inner = keys
                .iter()
                .map(|k| format!("{}: {}", py_repr_str(k), py_repr_value(&map[*k])))
                .collect::<Vec<_>>()
                .join(", ");
            format!("{{{inner}}}")
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    // Ground truth produced by CPython 3.12's repr(); if any of these
    // fail, the Rust side has drifted from the reference implementation.
    #[test]
    fn strings_match_cpython_repr() {
        let cases = [
            ("bogus", "'bogus'"),
            // No \b / \f short escapes in repr(); every control -> \xNN.
            ("\u{08}\u{0c}\u{01}\u{7f}", r"'\x08\x0c\x01\x7f'"),
            ("it's", "\"it's\""),
            ("say \"hi\"", "'say \"hi\"'"),
            // Both quote types: CPython keeps single quotes and escapes
            // the single quotes (verified against CPython 3.12).
            ("both'\"", "'both\\'\"'"),
            ("a\\b", "'a\\\\b'"),
            ("line\nbreak", "'line\\nbreak'"),
            ("tab\there", "'tab\\there'"),
            ("carriage\rret", "'carriage\\rret'"),
            // Printable non-ASCII passes through raw.
            ("café", "'café'"),
            ("😀", "'😀'"),
            // C1 controls -> \xNN.
            ("\u{80}\u{9f}", r"'\x80\x9f'"),
            ("", "''"),
            ("plain-id_123", "'plain-id_123'"),
        ];
        for (input, want) in cases {
            assert_eq!(py_repr_str(input), want, "for {input:?}");
        }
    }

    #[test]
    fn scalars_match_cpython_repr() {
        assert_eq!(py_repr_value(&Value::Null), "None");
        assert_eq!(py_repr_value(&json!(true)), "True");
        assert_eq!(py_repr_value(&json!(false)), "False");
        assert_eq!(py_repr_value(&json!(42)), "42");
        assert_eq!(py_repr_value(&json!(-7)), "-7");
    }

    #[test]
    fn floats_match_cpython_repr() {
        // serde_json renders 1e-5 as "1e-5"; repr(1e-5) is "1e-05".
        for (f, want) in [
            (1e-5, "1e-05"),
            (2.5e-7, "2.5e-07"),
            (1e16, "1e+16"),
            (0.30000000000000004, "0.30000000000000004"),
            (100.0, "100.0"),
            (-0.0, "-0.0"),
            (1.5, "1.5"),
        ] {
            assert_eq!(py_repr_value(&json!(f)), want, "for {f}");
        }
    }

    #[test]
    fn containers_match_python_str() {
        // str({'b': 1, 'a': None}) -> "{'a': None, 'b': 1}"
        assert_eq!(
            py_repr_value(&json!({"b": 1, "a": null})),
            "{'a': None, 'b': 1}"
        );
        assert_eq!(py_repr_value(&json!(["x", true, 1.5])), "['x', True, 1.5]");
    }

    #[test]
    fn nested_containers_recurse() {
        assert_eq!(
            py_repr_value(&json!({"o": {"z": [1, {"y": "it's"}], "a": null}, "l": []})),
            "{'l': [], 'o': {'a': None, 'z': [1, {'y': \"it's\"}]}}"
        );
    }

    #[test]
    fn nonprintable_non_ascii_passes_through_raw() {
        // Deliberate, documented difference from repr(): U+200B ZERO
        // WIDTH SPACE is not C0/DEL/C1, so it passes through raw where
        // repr() would emit '\u200b'. The Python `_safe_repr` implements
        // the same rule, so the two sides stay byte-identical.
        assert_eq!(py_repr_str("a\u{200b}b"), "'a\u{200b}b'");
        assert_ne!(py_repr_str("a\u{200b}b"), "'a\\u200bb'");
    }
}
