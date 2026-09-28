//! Environment fingerprint digest.
//!
//! Mirrors `python/peira/env_fingerprint.py::fingerprint_env`: the
//! SHA-256 of an environment dict's compact canonical JSON
//! (`json.dumps(env, sort_keys=True, separators=(",", ":"))`), so the
//! digest is stable across runs and machines. Collecting the
//! environment itself is platform I/O and stays in Python; hashing a
//! collected dict is pure computation and lives here.

use serde_json::Value;
use sha2::{Digest, Sha256};

use crate::canonical::hash_compact_canonical;

/// SHA-256 hex of the env dict's compact canonical JSON.
///
/// Byte-identical to the Python reference for every JSON-shaped dict.
pub fn fingerprint_env(env: &Value) -> String {
    let mut h = Sha256::new();
    hash_compact_canonical(env, &mut h);
    format!("{:x}", h.finalize())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn empty_dict_matches_python() {
        // hashlib.sha256(b"{}").hexdigest()
        assert_eq!(
            fingerprint_env(&json!({})),
            "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
        );
    }

    #[test]
    fn key_order_irrelevant() {
        let a = fingerprint_env(&json!({"b": 1, "a": [1, 2]}));
        let b = fingerprint_env(&json!({"a": [1, 2], "b": 1}));
        assert_eq!(a, b);
        // Cross-checked against CPython's json.dumps(..., sort_keys=True,
        // separators=(",", ":")).
        assert_eq!(
            a,
            "94a786c3662bc7beeb598efa7d8cb58d7bea25d6c275ea9785a0230ff1f8c2ba"
        );
    }

    #[test]
    fn nested_values() {
        // Cross-checked against CPython: hashlib.sha256(json.dumps(
        // {"os": "linux", "python": "3.12.1", "torch": {"cuda": null,
        // "version": "2.5.0"}}, sort_keys=True,
        // separators=(",", ":")).encode()).hexdigest()
        let env = json!({
            "os": "linux",
            "python": "3.12.1",
            "torch": {"cuda": null, "version": "2.5.0"},
        });
        assert_eq!(
            fingerprint_env(&env),
            "a097b51384cd9989694a0cfc5fe800b214e943ff830f086be995ba9fbd727904"
        );
    }
}
