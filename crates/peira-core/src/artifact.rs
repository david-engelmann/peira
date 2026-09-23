//! Run artifacts: the frozen record of one evaluation run.
//!
//! Mirrors `python/peira/artifacts.py`. An artifact bundles the config,
//! the per-case results, and the aggregate metrics, plus an analysis-lock
//! hash (SHA-256 over config + dataset version + manifest SHA-256 +
//! peira version + adapter name/version). The hash is the mechanical
//! guarantee behind "no post-hoc editing": any change to inputs changes
//! the lock.
//!
//! The lock payload is serialized with [`crate::canonical`] so locks are
//! byte-identical across the Python and Rust implementations.
//!
//! Loading is deliberately strict: unknown fields are rejected
//! (`deny_unknown_fields`, mirroring Python's `from_json`, which raises
//! `ValueError` on them) rather than silently preserved. A lenient
//! loader would let a newer artifact with renamed fields "verify"
//! against a lock computed over different semantics; the frozen format
//! makes strictness the safe default, and both backends agree on it.
//! Missing `config`/`metrics` default to `{}` (not `null`): `config` is
//! part of the lock payload, so a `null`-vs-`{}` default would seal
//! different locks for the same degenerate artifact on each backend.

use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};

use crate::canonical::{hash_canonical, to_pretty};
use crate::metrics::PerCaseResult;

/// One evaluation run, sealed with an analysis lock.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RunArtifact {
    #[serde(default = "default_artifact_version")]
    pub artifact_version: String,
    pub peira_version: String,
    pub dataset_version: String,
    /// SHA-256 of the suite manifest.json bytes, verified before scoring.
    /// Empty when the suite ships no manifest — the run is then explicitly
    /// unbound, not silently bound.
    #[serde(default)]
    pub manifest_sha256: String,
    #[serde(default)]
    pub adapter_name: String,
    #[serde(default)]
    pub adapter_version: String,
    #[serde(default)]
    pub suite: String,
    #[serde(default)]
    pub created_utc: String,
    // `{}` when absent, matching the Python reference: `config` feeds the
    // lock payload, so the default must agree across backends.
    #[serde(default = "default_empty_object")]
    pub config: Value,
    #[serde(default)]
    pub results: Vec<PerCaseResult>,
    #[serde(default = "default_empty_object")]
    pub metrics: Value,
    #[serde(default)]
    pub analysis_lock: String,
}

fn default_artifact_version() -> String {
    "1".to_string()
}

fn default_empty_object() -> Value {
    Value::Object(serde_json::Map::new())
}

impl RunArtifact {
    /// SHA-256 hex over the canonical JSON of the lock payload, mirroring
    /// Python's `compute_lock` exactly (same keys, same serialization).
    pub fn compute_lock(&self) -> String {
        lock_payload(
            &self.peira_version,
            &self.dataset_version,
            &self.manifest_sha256,
            &self.adapter_name,
            &self.adapter_version,
            &self.suite,
            &self.config,
            &serde_json::to_value(&self.results).unwrap_or(Value::Null),
        )
    }

    /// Seal the artifact in place (mirrors `seal()`).
    pub fn seal(&mut self) {
        self.analysis_lock = self.compute_lock();
    }

    /// `true` when the embedded lock matches a fresh computation.
    pub fn verify(&self) -> bool {
        self.analysis_lock == self.compute_lock()
    }

    /// Serialize with 2-space indent and sorted keys, mirroring Python's
    /// `to_json` (`json.dumps(asdict(self), indent=2, sort_keys=True)`).
    pub fn to_json(&self) -> String {
        let v = serde_json::to_value(self).unwrap_or(Value::Null);
        to_pretty(&v)
    }

    pub fn from_json(s: &str) -> Result<Self, serde_json::Error> {
        let artifact: Self = serde_json::from_str(s)?;
        // Python's from_json requires `config`/`metrics` to be objects;
        // the struct fields stay `Value` (the format is frozen), but the
        // trust boundary enforces the same rule here.
        for (key, value) in [("config", &artifact.config), ("metrics", &artifact.metrics)] {
            if !value.is_object() {
                return Err(serde::de::Error::custom(format!(
                    "artifact field '{key}' must be an object, got {}",
                    json_type_name(value)
                )));
            }
        }
        Ok(artifact)
    }
}

/// JSON type name for error messages, mirroring Python's `type(x).__name__`.
fn json_type_name(v: &Value) -> &'static str {
    match v {
        Value::Null => "NoneType",
        Value::Bool(_) => "bool",
        Value::Number(_) => "number",
        Value::String(_) => "str",
        Value::Array(_) => "list",
        Value::Object(_) => "dict",
    }
}

/// Compute the analysis lock from the eight payload fields. Exposed so
/// tests (and future verifiers) can lock payloads built outside a
/// [`RunArtifact`], e.g. from a JSON fixture produced by the Python side.
// Eight positional params mirror the frozen lock-payload field list;
// a struct would just rename the problem.
#[allow(clippy::too_many_arguments)]
pub fn lock_payload(
    peira_version: &str,
    dataset_version: &str,
    manifest_sha256: &str,
    adapter_name: &str,
    adapter_version: &str,
    suite: &str,
    config: &Value,
    results: &Value,
) -> String {
    // The eight payload keys in canonical (sorted) order, hashed by
    // streaming straight into SHA-256: `config` and `results` are never
    // cloned (the old code deep-cloned both into a throwaway map, ~3x
    // transient memory on large runs). The six short string fields go
    // through one-shot Values; the keys themselves are static ASCII, so
    // the quoted `"key": ` prefixes are hashed literally. The field
    // order is written out explicitly — it is part of the frozen lock
    // contract, and spelling it out beats a separator-tracking macro.
    let mut h = Sha256::new();
    h.update(b"{\"adapter_name\": ");
    hash_canonical(&Value::String(adapter_name.to_owned()), &mut h);
    h.update(b", \"adapter_version\": ");
    hash_canonical(&Value::String(adapter_version.to_owned()), &mut h);
    h.update(b", \"config\": ");
    hash_canonical(config, &mut h);
    h.update(b", \"dataset_version\": ");
    hash_canonical(&Value::String(dataset_version.to_owned()), &mut h);
    h.update(b", \"manifest_sha256\": ");
    hash_canonical(&Value::String(manifest_sha256.to_owned()), &mut h);
    h.update(b", \"peira_version\": ");
    hash_canonical(&Value::String(peira_version.to_owned()), &mut h);
    h.update(b", \"results\": ");
    hash_canonical(results, &mut h);
    h.update(b", \"suite\": ");
    hash_canonical(&Value::String(suite.to_owned()), &mut h);
    h.update(b"}");
    format!("{:x}", h.finalize())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn sample() -> RunArtifact {
        RunArtifact {
            artifact_version: "1".into(),
            peira_version: "0.1.0".into(),
            dataset_version: "0.1.0-demo".into(),
            manifest_sha256: "abc123".into(),
            adapter_name: "dummy".into(),
            adapter_version: "1".into(),
            suite: "trial-demo".into(),
            created_utc: "2026-09-22T00:00:00+00:00".into(),
            config: json!({"n_cases": 1}),
            results: vec![PerCaseResult {
                case_id: "c1".into(),
                family: "indirection".into(),
                primitive: "choice".into(),
                benign_correct: true,
                attacked_flipped: false,
                attacked_targeted: false,
                malformed: false,
                confidence: Some(0.9),
                benign_malformed: false,
                has_target: false,
            }],
            metrics: json!({}),
            analysis_lock: String::new(),
        }
    }

    #[test]
    fn seal_and_verify_roundtrip() {
        let mut a = sample();
        assert!(!a.verify()); // empty lock never verifies
        a.seal();
        assert!(a.verify());
    }

    #[test]
    fn lock_covers_manifest_sha256() {
        // Byte-proof dataset identity: two artifacts that differ only in
        // the recorded manifest digest seal different locks.
        let mut a = sample();
        a.seal();
        let mut b = sample();
        b.manifest_sha256 = "def456".into();
        b.seal();
        assert_ne!(a.analysis_lock, b.analysis_lock);
        assert!(a.verify());
        assert!(b.verify());
    }

    #[test]
    fn tampering_breaks_the_lock() {
        let mut a = sample();
        a.seal();
        a.results[0].attacked_flipped = true;
        assert!(!a.verify());
        // Tampering with config (part of the payload) also breaks it.
        let mut b = sample();
        b.seal();
        b.config = json!({"n_cases": 2});
        assert!(!b.verify());
        // Tampering with metrics (not in the payload) does not.
        let mut c = sample();
        c.seal();
        c.metrics = json!({"asr_conditional": 1.0});
        assert!(c.verify());
    }

    #[test]
    fn json_roundtrip() {
        let mut a = sample();
        a.seal();
        let b = RunArtifact::from_json(&a.to_json()).unwrap();
        assert_eq!(a, b);
    }

    #[test]
    fn unknown_fields_rejected_like_python() {
        let mut v = serde_json::to_value(sample()).unwrap();
        v["bogus"] = json!(1);
        assert!(RunArtifact::from_json(&crate::canonical::to_canonical(&v)).is_err());
    }

    #[test]
    fn minimal_artifact_defaults_match_python() {
        // A minimal artifact (only the two required lock identifiers)
        // loads with the same defaults as Python's from_json: missing
        // config/metrics become {}, not null — the lock payload must
        // agree across backends.
        let a = RunArtifact::from_json(r#"{"peira_version": "0.1.0", "dataset_version": "x"}"#)
            .unwrap();
        assert_eq!(a.artifact_version, "1");
        assert_eq!(a.config, json!({}));
        assert_eq!(a.metrics, json!({}));
        assert!(a.results.is_empty());
        assert_eq!(a.analysis_lock, "");
    }

    #[test]
    fn missing_required_fields_rejected() {
        assert!(RunArtifact::from_json(r#"{"peira_version": "x"}"#).is_err());
        assert!(RunArtifact::from_json(r#"{"dataset_version": "x"}"#).is_err());
        assert!(RunArtifact::from_json(r#"{}"#).is_err());
    }

    #[test]
    fn non_object_config_or_metrics_rejected_like_python() {
        // Python's from_json requires config/metrics to be dicts; the
        // Rust trust boundary enforces the same rule.
        for (key, bad) in [("config", r#""x""#), ("metrics", r#"[1]"#)] {
            let s =
                format!(r#"{{"peira_version": "0.1.0", "dataset_version": "x", "{key}": {bad}}}"#);
            let err = RunArtifact::from_json(&s).unwrap_err().to_string();
            assert!(
                err.contains(&format!("artifact field '{key}' must be an object")),
                "{err}"
            );
        }
        let ok = RunArtifact::from_json(
            r#"{"peira_version": "0.1.0", "dataset_version": "x",
                "config": {"a": 1}, "metrics": {}}"#,
        )
        .unwrap();
        assert_eq!(ok.config, json!({"a": 1}));
    }

    #[test]
    fn scalar_artifact_rejected() {
        assert!(RunArtifact::from_json(r#"[1, 2]"#).is_err());
        assert!(RunArtifact::from_json(r#""x""#).is_err());
    }

    #[test]
    fn streaming_lock_matches_canonical_string() {
        // Pin the streaming lock_payload against the naive implementation
        // (build the map, serialize, hash): the bytes must be identical,
        // or every cross-language lock breaks silently.
        let config = json!({"n_cases": 3, "nested": {"b": [1, 2], "a": "x"}});
        let results = json!([{"case_id": "c1", "x": 1e-5}]);
        let streamed = lock_payload("p", "d", "m", "a", "v", "s", &config, &results);
        let mut map = serde_json::Map::new();
        for (k, v) in [
            ("adapter_name", json!("a")),
            ("adapter_version", json!("v")),
            ("config", config),
            ("dataset_version", json!("d")),
            ("manifest_sha256", json!("m")),
            ("peira_version", json!("p")),
            ("results", results),
            ("suite", json!("s")),
        ] {
            map.insert(k.into(), v);
        }
        let mut h = Sha256::new();
        h.update(crate::canonical::to_canonical(&Value::Object(map)).as_bytes());
        assert_eq!(streamed, format!("{:x}", h.finalize()));
    }
}
