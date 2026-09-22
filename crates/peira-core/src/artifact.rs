//! Run artifacts: the frozen record of one evaluation run.
//!
//! Mirrors `python/peira/artifacts.py`. An artifact bundles the config,
//! the per-case results, and the aggregate metrics, plus an analysis-lock
//! hash (SHA-256 over config + dataset version + peira version + adapter
//! name/version). The hash is the mechanical guarantee behind "no
//! post-hoc editing": any change to inputs changes the lock.
//!
//! The lock payload is serialized with [`crate::canonical`] so locks are
//! byte-identical across the Python and Rust implementations.

use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};

use crate::canonical::{to_canonical, to_pretty};
use crate::metrics::PerCaseResult;

/// One evaluation run, sealed with an analysis lock.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RunArtifact {
    #[serde(default = "default_artifact_version")]
    pub artifact_version: String,
    pub peira_version: String,
    pub dataset_version: String,
    #[serde(default)]
    pub adapter_name: String,
    #[serde(default)]
    pub adapter_version: String,
    #[serde(default)]
    pub suite: String,
    #[serde(default)]
    pub created_utc: String,
    #[serde(default)]
    pub config: Value,
    #[serde(default)]
    pub results: Vec<PerCaseResult>,
    #[serde(default)]
    pub metrics: Value,
    #[serde(default)]
    pub analysis_lock: String,
}

fn default_artifact_version() -> String {
    "1".to_string()
}

impl RunArtifact {
    /// SHA-256 hex over the canonical JSON of the lock payload, mirroring
    /// Python's `compute_lock` exactly (same keys, same serialization).
    pub fn compute_lock(&self) -> String {
        lock_payload(
            &self.peira_version,
            &self.dataset_version,
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
        serde_json::from_str(s)
    }
}

/// Compute the analysis lock from the seven payload fields. Exposed so
/// tests (and future verifiers) can lock payloads built outside a
/// [`RunArtifact`], e.g. from a JSON fixture produced by the Python side.
pub fn lock_payload(
    peira_version: &str,
    dataset_version: &str,
    adapter_name: &str,
    adapter_version: &str,
    suite: &str,
    config: &Value,
    results: &Value,
) -> String {
    let mut map = serde_json::Map::new();
    map.insert("peira_version".into(), Value::String(peira_version.into()));
    map.insert(
        "dataset_version".into(),
        Value::String(dataset_version.into()),
    );
    map.insert("adapter_name".into(), Value::String(adapter_name.into()));
    map.insert(
        "adapter_version".into(),
        Value::String(adapter_version.into()),
    );
    map.insert("suite".into(), Value::String(suite.into()));
    map.insert("config".into(), config.clone());
    map.insert("results".into(), results.clone());
    let canonical = to_canonical(&Value::Object(map));
    let mut h = Sha256::new();
    h.update(canonical.as_bytes());
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
        assert!(RunArtifact::from_json(&to_canonical(&v)).is_err());
    }
}
