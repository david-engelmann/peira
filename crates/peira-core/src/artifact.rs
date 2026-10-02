//! Run artifacts: the versioned record of one evaluation run.
//!
//! Mirrors `python/peira/artifacts.py`. An artifact bundles the config,
//! the per-case results, and the aggregate metrics, plus an analysis-lock
//! hash (SHA-256 over the lock payload). The hash is the mechanical
//! guarantee behind "no post-hoc editing": any change to inputs changes
//! the lock.
//!
//! Format versions: v1 (flat results) and v2 (per-variant call records)
//! are REJECTED — both predate the v3 agent-consumer schema and cannot
//! be migrated; re-run the adapter to produce a v3 artifact. v3 adds
//! stable run identity, a machine-checkable run status, schema_ref,
//! structured threat-model / attack-provenance / adjudication / exposure
//! blocks, fully-pinned adapter identity, license + access tier,
//! typed per-family stats, uncertainty semantics, retry/cache
//! transparency, determinism-check results, and a machine-readable
//! error log. Every new field is lock-covered.
//!
//! The lock payload is serialized with [`crate::canonical`] so locks are
//! byte-identical across the Python and Rust implementations.
//!
//! Loading is deliberately strict: unknown fields are rejected
//! (`deny_unknown_fields`, mirroring Python's `from_json`, which raises
//! `ValueError` on them) rather than silently preserved. A lenient
//! loader would let a newer artifact with renamed fields "verify"
//! against a lock computed over different semantics; the format makes
//! strictness the safe default, and both backends agree on it.
//! Missing `config`/`metrics` default to `{}` (not `null`): `config` is
//! part of the lock payload, so a `null`-vs-`{}` default would seal
//! different locks for the same degenerate artifact on each backend.

use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};

use crate::canonical::{hash_canonical, to_pretty};
use crate::metrics::PerCaseResult;

/// Current artifact format version. Anything else is rejected at load.
pub const ARTIFACT_VERSION: &str = "3";

/// Canonical resolvable URI of the JSON Schema this artifact validates
/// against (mirrors Python's SCHEMA_REF).
pub const SCHEMA_REF: &str = "https://peiratrial.dev/schemas/run-artifact/3.json";

// v3 closed vocabularies, mirroring the Python frozensets in
// python/peira/artifacts.py (`RUN_STATUSES`, `TERMINATIONS`,
// `MODEL_CLASSES`, `CONFIDENCE_SOURCES`, `ACCESS_TIERS`,
// `ERROR_CODES`, `ATTACKER_ACCESS_LEVELS`, `ATTACKER_KNOWLEDGE`,
// `ATTACK_ADAPTIVITY`, `ATTACK_METHODS`, `CASE_SUBSETS`). Free-form
// strings are a silent schema-drift vector for agent consumers, so
// the strict loader (`from_json`, both backends) rejects anything
// outside the closed sets. `decision` is deliberately NOT closed:
// decisions are case-option labels, case-dependent by construction.
const RUN_STATUSES: &[&str] = &["started", "success", "cancelled", "error", "partial"];
const TERMINATIONS: &[&str] = &[
    "complete", "budget", "timeout", "partial", "operator", "error",
];
const MODEL_CLASSES: &[&str] = &["", "guardrail", "llm-baseline", "hybrid", "rule-based"];
const CONFIDENCE_SOURCES: &[&str] = &["", "verbalized", "token-logprob", "guardrail-score", "none"];
const ACCESS_TIERS: &[&str] = &["public", "internal", "confidential"];
const ATTACKER_ACCESS_LEVELS: &[&str] = &["black_box", "gray_box", "white_box"];
const ATTACKER_KNOWLEDGE: &[&str] = &["none", "architecture", "weights", "training_data"];
const ATTACK_ADAPTIVITY: &[&str] = &["static", "adaptive"];
const ATTACK_METHODS: &[&str] = &["static_template", "adaptive_search", "manual"];
const CASE_SUBSETS: &[&str] = &["public", "private", "blind", "mixed"];
const FLIPPED_OUTCOMES: &[&str] = &["flipped", "not_flipped"];
const MULTIPLE_COMPARISONS: &[&str] = &["none", "holm", "bonferroni"];
const ERROR_CODES: &[&str] = &[
    "timeout",
    "rate_limit",
    "api_error",
    "parse_failure",
    "refused_to_format",
];
const ERROR_LOG_ARMS: &[&str] = &["benign", "attacked"];

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
    /// Pricing provenance: which pinned table priced this run's calls.
    #[serde(default)]
    pub pricing_source: String,
    #[serde(default)]
    pub pricing_date: String,
    /// Run seed, recorded on every call record.
    #[serde(default)]
    pub seed: i64,
    /// Concurrency cap the run was dispatched with (performance
    /// parameter, sealed for provenance).
    #[serde(default)]
    pub max_concurrency: i64,
    /// Environment fingerprint: where the run executed (Python version,
    /// torch/CUDA, OS, etc.). Empty object when absent.
    #[serde(default = "default_empty_object")]
    pub env: Value,
    /// SHA-256 of the canonical env JSON. Part of the analysis lock —
    /// environment changes invalidate the lock.
    #[serde(default)]
    pub env_sha256: String,
    /// Pricing table version that priced this run. Part of the lock.
    #[serde(default)]
    pub pricing_version: String,
    /// Measurement contract version. Part of the lock.
    #[serde(default)]
    pub contract_version: String,
    /// How the run ended ("complete", "budget", ...). Part of the lock:
    /// a budget-stopped run must never verify as complete.
    #[serde(default = "default_termination")]
    pub termination: String,
    /// Hard spend cap in USD, if any. Part of the lock.
    #[serde(default)]
    pub budget_usd: Option<f64>,
    /// Per-call output-token cap, if any. Part of the lock: a run
    /// measured under a different cap is a different measurement.
    #[serde(default)]
    pub max_tokens_per_call: Option<i64>,
    /// Actual spend in USD. Part of the lock.
    #[serde(default)]
    pub spent_usd: f64,
    /// Cases completed vs planned. Part of the lock.
    #[serde(default)]
    pub cases_completed: i64,
    #[serde(default)]
    pub cases_planned: i64,
    /// Measurement framework (§3.7-3.8, §3.11-3.15): adapter
    /// registration metadata and longitudinal provenance. All part of
    /// the lock.
    #[serde(default)]
    pub model_class: String,
    #[serde(default)]
    pub confidence_source: String,
    #[serde(default)]
    pub checkpoint_hash: String,
    #[serde(default)]
    pub api_version: String,
    #[serde(default)]
    pub call_date: String,
    #[serde(default)]
    pub decode_params: String,
    #[serde(default)]
    pub template_hash: String,
    #[serde(default)]
    pub case_set_tag: String,
    #[serde(default)]
    pub cost_scenario_version: String,
    // ---- v3 agent-consumer fields (all lock-covered) ----
    /// Stable run identity: the join key that survives renames and
    /// copies. Empty when absent (hand-written artifacts); the Python
    /// reference generates a uuid4 hex for new runs.
    #[serde(default)]
    pub run_id: String,
    /// Chains reruns/resumes for longitudinal tracking.
    #[serde(default)]
    pub parent_run_id: String,
    /// Machine-checkable run gate ("success", "partial", ...).
    #[serde(default = "default_run_status")]
    pub run_status: String,
    /// Resolvable JSON Schema URI for this artifact version.
    #[serde(default = "default_schema_ref")]
    pub schema_ref: String,
    /// Metric formula version that produced `metrics`.
    #[serde(default)]
    pub metrics_version: String,
    /// Structured threat model (attacker access/knowledge/budget).
    /// Defaults match Python's `_default_threat_model()` factory.
    #[serde(default = "default_threat_model")]
    pub threat_model: Value,
    /// Attack provenance (attacker model, budget, method).
    /// Defaults match Python's `_default_attack_provenance()` factory.
    #[serde(default = "default_attack_provenance")]
    pub attack_provenance: Value,
    /// Adjudication policy (eligibility/flip rules).
    /// Defaults match Python's `_default_adjudication_policy()` factory.
    #[serde(default = "default_adjudication_policy")]
    pub adjudication_policy: Value,
    /// Exposure/blindness attestation.
    /// Defaults match Python's `_default_exposure_attestation()` factory.
    #[serde(default = "default_exposure_attestation")]
    pub exposure_attestation: Value,
    /// Fully-pinned adapter identity.
    /// Defaults match Python's `_default_adapter_pins()` factory.
    #[serde(default = "default_adapter_pins")]
    pub adapter_pins: Value,
    /// Redistribution license, in-band.
    #[serde(default = "default_license")]
    pub license: String,
    /// Access tier ("public", "internal", "confidential").
    #[serde(default = "default_access_tier")]
    pub access_tier: String,
    /// Precomputed typed per-family stats. `[]` when absent, matching
    /// the Python reference.
    #[serde(default = "default_empty_array")]
    pub per_family_stats: Value,
    /// Uncertainty semantics for the sealed CIs.
    /// Defaults match Python's `_default_uncertainty()` factory.
    #[serde(default = "default_uncertainty")]
    pub uncertainty: Value,
    /// Retry/timeout policy and observed counts.
    /// Defaults match Python's `_default_retry_policy()` factory.
    #[serde(default = "default_retry_policy")]
    pub retry_policy: Value,
    /// Cache policy and observed hits.
    /// Defaults match Python's `_default_cache_policy()` factory.
    #[serde(default = "default_cache_policy")]
    pub cache_policy: Value,
    /// Determinism-contract self-check results.
    /// Defaults match Python's `_default_determinism_check()` factory.
    #[serde(default = "default_determinism_check")]
    pub determinism_check: Value,
    /// Machine-readable exclusion table. `[]` when absent, matching
    /// the Python reference.
    #[serde(default = "default_empty_array")]
    pub error_log: Value,
}

fn default_run_status() -> String {
    "success".to_string()
}

fn default_schema_ref() -> String {
    SCHEMA_REF.to_string()
}

fn default_license() -> String {
    "CC-BY-4.0".to_string()
}

fn default_access_tier() -> String {
    "public".to_string()
}

// v3 block defaults: byte-identical to the Python factories in
// python/peira/artifacts.py (`_default_*`). Both backends must seal
// the same lock for a minimal artifact, so these are pinned here,
// not left as empty objects.
fn default_threat_model() -> Value {
    serde_json::json!({
        "attacker_access": "black_box",
        "attacker_knowledge": "none",
        "query_budget_per_case": 0,
        "attack_adaptivity": "static",
        "notes": "",
    })
}

fn default_attack_provenance() -> Value {
    serde_json::json!({
        "attacker_model": "",
        "attacker_model_version": "",
        "attack_budget_variants": 1,
        "attack_method": "static_template",
        "attack_code_ref": "",
    })
}

fn default_adjudication_policy() -> Value {
    serde_json::json!({
        "policy_version": "1",
        "eligibility_rule": "benign_well_formed_and_correct_and_not_abstained",
        "ineligibility_reasons": [
            "benign_malformed",
            "benign_wrong_decision",
            "benign_abstained",
        ],
        "attacked_abstain_counts_as": "not_flipped",
        "attacked_malformed_counts_as": "flipped",
        "conditional_asr_denominator": "eligible_cases",
        "unconditional_asr_denominator": "all_cases",
    })
}

fn default_exposure_attestation() -> Value {
    serde_json::json!({
        "case_subset": "public",
        "blindness_protocol_id": "",
        "prior_exposure_attested": false,
        "holdout_access_log_ref": "",
    })
}

fn default_adapter_pins() -> Value {
    serde_json::json!({
        "provider_snapshot": "",
        "hf_revision": "",
        "code_sha": "",
        "code_dirty": false,
    })
}

fn default_uncertainty() -> Value {
    serde_json::json!({
        "ci_method": "wilson",
        "ci_level": 0.95,
        "ci_unit": "per_case_binomial",
        "multiple_comparison": "none",
        "familywise_alpha": 0.05,
    })
}

fn default_retry_policy() -> Value {
    serde_json::json!({
        "per_call_timeout_s": null,
        "max_retries": 0,
        "total_retries": 0,
        "rate_limit_hits": 0,
    })
}

fn default_cache_policy() -> Value {
    serde_json::json!({
        "cache_enabled": false,
        "cache_key_scheme": "",
        "cache_hits": 0,
        "cache_misses": 0,
    })
}

fn default_determinism_check() -> Value {
    serde_json::json!({
        "checked": false,
        "passed": false,
        "mismatches": 0,
        "sample_n": 0,
    })
}

fn default_termination() -> String {
    "complete".to_string()
}

fn default_artifact_version() -> String {
    ARTIFACT_VERSION.to_string()
}

fn default_empty_object() -> Value {
    Value::Object(serde_json::Map::new())
}

fn default_empty_array() -> Value {
    Value::Array(Vec::new())
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
            &self.pricing_source,
            &self.pricing_date,
            &self.pricing_version,
            &self.contract_version,
            &self.termination,
            self.budget_usd,
            self.spent_usd,
            self.cases_completed,
            self.cases_planned,
            self.seed,
            self.max_concurrency,
            self.max_tokens_per_call,
            &self.metrics,
            &self.env,
            &self.env_sha256,
            &self.model_class,
            &self.confidence_source,
            &self.checkpoint_hash,
            &self.api_version,
            &self.call_date,
            &self.decode_params,
            &self.template_hash,
            &self.case_set_tag,
            &self.cost_scenario_version,
            &self.run_id,
            &self.parent_run_id,
            &self.run_status,
            &self.schema_ref,
            &self.metrics_version,
            &self.threat_model,
            &self.attack_provenance,
            &self.adjudication_policy,
            &self.exposure_attestation,
            &self.adapter_pins,
            &self.license,
            &self.access_tier,
            &self.per_family_stats,
            &self.uncertainty,
            &self.retry_policy,
            &self.cache_policy,
            &self.determinism_check,
            &self.error_log,
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
        // v1/v2 artifacts predate the v3 agent-consumer schema: no
        // migration, no silent acceptance — re-run to produce v3.
        if artifact.artifact_version != ARTIFACT_VERSION {
            return Err(serde::de::Error::custom(format!(
                "unsupported artifact_version '{}': only v3 artifacts load. \
                 v1/v2 artifacts predate the v3 agent-consumer schema and \
                 cannot be loaded or migrated. Re-run the adapter to \
                 produce a v3 artifact (see docs/Artifact-Versions.md)",
                artifact.artifact_version,
            )));
        }
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
        // v3 closed vocabularies: mirror Python's strict loader. An
        // out-of-vocabulary string is a silent schema-drift vector for
        // agent consumers, so it is rejected, not preserved.
        for (field, value, vocab) in [
            ("run_status", artifact.run_status.as_str(), RUN_STATUSES),
            ("termination", artifact.termination.as_str(), TERMINATIONS),
            ("model_class", artifact.model_class.as_str(), MODEL_CLASSES),
            (
                "confidence_source",
                artifact.confidence_source.as_str(),
                CONFIDENCE_SOURCES,
            ),
            ("access_tier", artifact.access_tier.as_str(), ACCESS_TIERS),
        ] {
            check_vocab(field, value, vocab)?;
        }
        for (block, field, block_value, vocab) in [
            (
                "threat_model",
                "attacker_access",
                &artifact.threat_model,
                ATTACKER_ACCESS_LEVELS,
            ),
            (
                "threat_model",
                "attacker_knowledge",
                &artifact.threat_model,
                ATTACKER_KNOWLEDGE,
            ),
            (
                "threat_model",
                "attack_adaptivity",
                &artifact.threat_model,
                ATTACK_ADAPTIVITY,
            ),
            (
                "attack_provenance",
                "attack_method",
                &artifact.attack_provenance,
                ATTACK_METHODS,
            ),
            (
                "adjudication_policy",
                "attacked_abstain_counts_as",
                &artifact.adjudication_policy,
                FLIPPED_OUTCOMES,
            ),
            (
                "adjudication_policy",
                "attacked_malformed_counts_as",
                &artifact.adjudication_policy,
                FLIPPED_OUTCOMES,
            ),
            (
                "exposure_attestation",
                "case_subset",
                &artifact.exposure_attestation,
                CASE_SUBSETS,
            ),
            (
                "uncertainty",
                "multiple_comparison",
                &artifact.uncertainty,
                MULTIPLE_COMPARISONS,
            ),
        ] {
            check_block_vocab(block, field, block_value, vocab)?;
        }
        // The exclusion table is machine-readable: entries carry a
        // closed arm and a non-empty closed error code (Python's
        // `_checked_error_log` rejects "" codes and unknown arms).
        if let Some(entries) = artifact.error_log.as_array() {
            for (i, entry) in entries.iter().enumerate() {
                let where_ = format!("artifact field 'error_log'[{i}]");
                match entry.get("arm").and_then(Value::as_str) {
                    Some(arm) if ERROR_LOG_ARMS.contains(&arm) => {}
                    Some(arm) => {
                        return Err(serde::de::Error::custom(format!(
                            "{where_} field 'arm' must be one of [{}], got '{arm}'",
                            ERROR_LOG_ARMS.join(", ")
                        )))
                    }
                    None => {
                        return Err(serde::de::Error::custom(format!(
                            "{where_} field 'arm' must be a string"
                        )))
                    }
                }
                match entry.get("error_code").and_then(Value::as_str) {
                    Some(code) if !code.is_empty() && ERROR_CODES.contains(&code) => {}
                    Some(code) => {
                        return Err(serde::de::Error::custom(format!(
                            "{where_} field 'error_code' must be a non-empty error code \
                             (one of [{}]), got '{code}'",
                            ERROR_CODES.join(", ")
                        )))
                    }
                    None => {
                        return Err(serde::de::Error::custom(format!(
                            "{where_} field 'error_code' must be a string"
                        )))
                    }
                }
            }
        }
        // Usage accounting is non-negative by construction (the runner's
        // validate_output rejects negatives before scoring); a stored
        // artifact with negative usage signals a broken producer, so
        // strict loading rejects it like the Python reference does.
        for (i, r) in artifact.results.iter().enumerate() {
            for (variant, rec) in [("benign", &r.benign), ("attacked", &r.attacked)] {
                if let Some(u) = &rec.usage {
                    let where_ = format!("artifact results entry {i} {variant}");
                    for (name, v) in [("tokens_in", u.tokens_in), ("tokens_out", u.tokens_out)] {
                        if v < 0 {
                            return Err(serde::de::Error::custom(format!(
                                "{where_} usage field '{name}' must be non-negative, got {v}"
                            )));
                        }
                    }
                    for (name, v) in [("latency_ms", u.latency_ms), ("cost_usd", u.cost_usd)] {
                        // NaN is rejected too: no measurement can be NaN.
                        if v < 0.0 || v.is_nan() {
                            return Err(serde::de::Error::custom(format!(
                                "{where_} usage field '{name}' must be non-negative, got {v}"
                            )));
                        }
                    }
                }
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

/// Reject an out-of-vocabulary string, mirroring Python's strict-loader
/// vocabulary checks (`artifact field {key!r} must be one of ...`).
fn check_vocab(field: &str, value: &str, vocab: &[&str]) -> Result<(), serde_json::Error> {
    if !vocab.contains(&value) {
        return Err(serde::de::Error::custom(format!(
            "artifact field '{field}' must be one of [{}], got '{value}'",
            vocab.join(", ")
        )));
    }
    Ok(())
}

/// Reject an out-of-vocabulary string inside a structured v3 block
/// (e.g. `threat_model.attacker_access`). A missing field is fine:
/// absent blocks take the serde defaults, which match the Python
/// factories and are in-vocabulary. A present non-string is rejected
/// like Python's type check.
fn check_block_vocab(
    block: &str,
    field: &str,
    block_value: &Value,
    vocab: &[&str],
) -> Result<(), serde_json::Error> {
    match block_value.get(field) {
        None => Ok(()),
        Some(Value::String(s)) => {
            if !vocab.contains(&s.as_str()) {
                return Err(serde::de::Error::custom(format!(
                    "artifact {block} field '{field}' must be one of [{}], got '{s}'",
                    vocab.join(", ")
                )));
            }
            Ok(())
        }
        Some(other) => Err(serde::de::Error::custom(format!(
            "artifact {block} field '{field}' must be a string, got {}",
            json_type_name(other)
        ))),
    }
}

/// Compute the analysis lock from the payload fields. Exposed so
/// tests (and future verifiers) can lock payloads built outside a
/// [`RunArtifact`], e.g. from a JSON fixture produced by the Python side.
// Positional params mirror the lock-payload field list; a struct
// would just rename the problem.
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
    pricing_source: &str,
    pricing_date: &str,
    pricing_version: &str,
    contract_version: &str,
    termination: &str,
    budget_usd: Option<f64>,
    spent_usd: f64,
    cases_completed: i64,
    cases_planned: i64,
    seed: i64,
    max_concurrency: i64,
    max_tokens_per_call: Option<i64>,
    metrics: &Value,
    env: &Value,
    env_sha256: &str,
    model_class: &str,
    confidence_source: &str,
    checkpoint_hash: &str,
    api_version: &str,
    call_date: &str,
    decode_params: &str,
    template_hash: &str,
    case_set_tag: &str,
    cost_scenario_version: &str,
    run_id: &str,
    parent_run_id: &str,
    run_status: &str,
    schema_ref: &str,
    metrics_version: &str,
    threat_model: &Value,
    attack_provenance: &Value,
    adjudication_policy: &Value,
    exposure_attestation: &Value,
    adapter_pins: &Value,
    license: &str,
    access_tier: &str,
    per_family_stats: &Value,
    uncertainty: &Value,
    retry_policy: &Value,
    cache_policy: &Value,
    determinism_check: &Value,
    error_log: &Value,
) -> String {
    // The forty-nine payload keys in canonical (sorted) order, hashed
    // by streaming straight into SHA-256: `config` and `results` are
    // never cloned. The field order is written out explicitly — it is
    // part of the lock contract, and spelling it out beats a
    // separator-tracking macro.
    let mut h = Sha256::new();
    h.update(b"{\"access_tier\": ");
    hash_canonical(&Value::String(access_tier.to_owned()), &mut h);
    h.update(b", \"adapter_name\": ");
    hash_canonical(&Value::String(adapter_name.to_owned()), &mut h);
    h.update(b", \"adapter_pins\": ");
    hash_canonical(adapter_pins, &mut h);
    h.update(b", \"adapter_version\": ");
    hash_canonical(&Value::String(adapter_version.to_owned()), &mut h);
    h.update(b", \"adjudication_policy\": ");
    hash_canonical(adjudication_policy, &mut h);
    h.update(b", \"api_version\": ");
    hash_canonical(&Value::String(api_version.to_owned()), &mut h);
    h.update(b", \"attack_provenance\": ");
    hash_canonical(attack_provenance, &mut h);
    h.update(b", \"budget_usd\": ");
    hash_canonical(&budget_usd.map(Value::from).unwrap_or(Value::Null), &mut h);
    h.update(b", \"cache_policy\": ");
    hash_canonical(cache_policy, &mut h);
    h.update(b", \"call_date\": ");
    hash_canonical(&Value::String(call_date.to_owned()), &mut h);
    h.update(b", \"case_set_tag\": ");
    hash_canonical(&Value::String(case_set_tag.to_owned()), &mut h);
    h.update(b", \"cases_completed\": ");
    hash_canonical(&Value::Number(cases_completed.into()), &mut h);
    h.update(b", \"cases_planned\": ");
    hash_canonical(&Value::Number(cases_planned.into()), &mut h);
    h.update(b", \"checkpoint_hash\": ");
    hash_canonical(&Value::String(checkpoint_hash.to_owned()), &mut h);
    h.update(b", \"confidence_source\": ");
    hash_canonical(&Value::String(confidence_source.to_owned()), &mut h);
    h.update(b", \"config\": ");
    hash_canonical(config, &mut h);
    h.update(b", \"contract_version\": ");
    hash_canonical(&Value::String(contract_version.to_owned()), &mut h);
    h.update(b", \"cost_scenario_version\": ");
    hash_canonical(&Value::String(cost_scenario_version.to_owned()), &mut h);
    h.update(b", \"dataset_version\": ");
    hash_canonical(&Value::String(dataset_version.to_owned()), &mut h);
    h.update(b", \"decode_params\": ");
    hash_canonical(&Value::String(decode_params.to_owned()), &mut h);
    h.update(b", \"determinism_check\": ");
    hash_canonical(determinism_check, &mut h);
    h.update(b", \"env\": ");
    hash_canonical(env, &mut h);
    h.update(b", \"env_sha256\": ");
    hash_canonical(&Value::String(env_sha256.to_owned()), &mut h);
    h.update(b", \"error_log\": ");
    hash_canonical(error_log, &mut h);
    h.update(b", \"exposure_attestation\": ");
    hash_canonical(exposure_attestation, &mut h);
    h.update(b", \"license\": ");
    hash_canonical(&Value::String(license.to_owned()), &mut h);
    h.update(b", \"manifest_sha256\": ");
    hash_canonical(&Value::String(manifest_sha256.to_owned()), &mut h);
    h.update(b", \"max_concurrency\": ");
    hash_canonical(&Value::Number(max_concurrency.into()), &mut h);
    h.update(b", \"max_tokens_per_call\": ");
    hash_canonical(
        &max_tokens_per_call.map(Value::from).unwrap_or(Value::Null),
        &mut h,
    );
    h.update(b", \"metrics\": ");
    // P0-1 (2026-09-25): metrics are lock-covered; forging headline
    // numbers invalidates the lock.
    hash_canonical(metrics, &mut h);
    h.update(b", \"metrics_version\": ");
    hash_canonical(&Value::String(metrics_version.to_owned()), &mut h);
    h.update(b", \"model_class\": ");
    hash_canonical(&Value::String(model_class.to_owned()), &mut h);
    h.update(b", \"parent_run_id\": ");
    hash_canonical(&Value::String(parent_run_id.to_owned()), &mut h);
    h.update(b", \"peira_version\": ");
    hash_canonical(&Value::String(peira_version.to_owned()), &mut h);
    h.update(b", \"per_family_stats\": ");
    hash_canonical(per_family_stats, &mut h);
    h.update(b", \"pricing_date\": ");
    hash_canonical(&Value::String(pricing_date.to_owned()), &mut h);
    h.update(b", \"pricing_source\": ");
    hash_canonical(&Value::String(pricing_source.to_owned()), &mut h);
    h.update(b", \"pricing_version\": ");
    hash_canonical(&Value::String(pricing_version.to_owned()), &mut h);
    h.update(b", \"results\": ");
    hash_canonical(results, &mut h);
    h.update(b", \"retry_policy\": ");
    hash_canonical(retry_policy, &mut h);
    h.update(b", \"run_id\": ");
    hash_canonical(&Value::String(run_id.to_owned()), &mut h);
    h.update(b", \"run_status\": ");
    hash_canonical(&Value::String(run_status.to_owned()), &mut h);
    h.update(b", \"schema_ref\": ");
    hash_canonical(&Value::String(schema_ref.to_owned()), &mut h);
    h.update(b", \"seed\": ");
    hash_canonical(&Value::Number(seed.into()), &mut h);
    h.update(b", \"spent_usd\": ");
    hash_canonical(&Value::from(spent_usd), &mut h);
    h.update(b", \"suite\": ");
    hash_canonical(&Value::String(suite.to_owned()), &mut h);
    h.update(b", \"template_hash\": ");
    hash_canonical(&Value::String(template_hash.to_owned()), &mut h);
    h.update(b", \"termination\": ");
    hash_canonical(&Value::String(termination.to_owned()), &mut h);
    h.update(b", \"threat_model\": ");
    hash_canonical(threat_model, &mut h);
    h.update(b", \"uncertainty\": ");
    hash_canonical(uncertainty, &mut h);
    h.update(b"}");
    format!("{:x}", h.finalize())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::metrics::CallRecord;
    use serde_json::json;

    fn record(decision: &str, index: i64) -> CallRecord {
        CallRecord {
            decision: decision.to_string(),
            confidence: Some(0.9),
            abstained: false,
            refusal_reason: String::new(),
            usage: None,
            seed: 7,
            dispatch_index: index,
            malformed: false,
            dispatch_limit: 1,
            score: None,
            cached: false,
            latency_ms_total: 0.0,
            timed_out: false,
            timeout_kind: None,
            timing_ms: None,
            error_code: String::new(),
            retry_count: 0,
            sampling_config: None,
            prompt_hash: String::new(),
            completion_hash: String::new(),
        }
    }

    fn sample() -> RunArtifact {
        RunArtifact {
            artifact_version: "3".into(),
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
                severity: "high".into(),
                primitive: "choice".into(),
                benign: record("approve", 0),
                attacked: record("deny", 1),
                flipped: true,
                eligible: true,
                ineligibility_reason: String::new(),
                conversational_turns: None,
                attack_budget_exhausted: false,
            }],
            metrics: json!({}),
            analysis_lock: String::new(),
            pricing_source: "test".into(),
            pricing_date: "2026-09-23".into(),
            pricing_version: String::new(),
            contract_version: "1".into(),
            termination: "complete".into(),
            budget_usd: None,
            max_tokens_per_call: None,
            spent_usd: 0.0,
            cases_completed: 0,
            cases_planned: 0,
            seed: 7,
            max_concurrency: 8,
            env: json!({}),
            env_sha256: String::new(),
            model_class: String::new(),
            confidence_source: String::new(),
            checkpoint_hash: String::new(),
            api_version: String::new(),
            call_date: String::new(),
            decode_params: String::new(),
            template_hash: String::new(),
            case_set_tag: String::new(),
            cost_scenario_version: String::new(),
            run_id: "abc123run".into(),
            parent_run_id: String::new(),
            run_status: "success".into(),
            schema_ref: SCHEMA_REF.into(),
            metrics_version: "3.0.0".into(),
            threat_model: json!({"attacker_access": "black_box"}),
            attack_provenance: json!({}),
            adjudication_policy: json!({"policy_version": "1"}),
            exposure_attestation: json!({}),
            adapter_pins: json!({}),
            license: "CC-BY-4.0".into(),
            access_tier: "public".into(),
            per_family_stats: json!([]),
            uncertainty: json!({}),
            retry_policy: json!({}),
            cache_policy: json!({}),
            determinism_check: json!({}),
            error_log: json!([]),
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
    fn lock_covers_pricing_and_seed() {
        // Pricing provenance and seed are measurement inputs: changing
        // them must change the lock.
        let mut a = sample();
        a.seal();
        let mut b = sample();
        b.pricing_date = "2026-09-24".into();
        b.seal();
        assert_ne!(a.analysis_lock, b.analysis_lock);
        let mut c = sample();
        c.seed = 8;
        c.seal();
        assert_ne!(a.analysis_lock, c.analysis_lock);
    }

    #[test]
    fn tampering_breaks_the_lock() {
        let mut a = sample();
        a.seal();
        a.results[0].flipped = false;
        assert!(!a.verify());
        let mut b = sample();
        b.seal();
        b.config = json!({"n_cases": 2});
        assert!(!b.verify());
        // Tampering with metrics breaks the lock (P0-1: metrics are
        // lock-covered; forging headline numbers invalidates the seal).
        let mut c = sample();
        c.seal();
        c.metrics = json!({"asr_conditional": 1.0});
        assert!(!c.verify());
    }

    #[test]
    fn json_roundtrip() {
        let mut a = sample();
        a.seal();
        let b = RunArtifact::from_json(&a.to_json()).unwrap();
        assert_eq!(a, b);
    }

    #[test]
    fn v1_and_v2_artifacts_rejected_with_clear_error() {
        for version in ["1", "2"] {
            let mut v = serde_json::to_value(sample()).unwrap();
            v["artifact_version"] = json!(version);
            let err = RunArtifact::from_json(&crate::canonical::to_canonical(&v))
                .unwrap_err()
                .to_string();
            assert!(err.contains("only v3 artifacts load"), "{err}");
            assert!(err.contains("cannot be loaded or migrated"), "{err}");
        }
    }

    #[test]
    fn unknown_fields_rejected_like_python() {
        let mut v = serde_json::to_value(sample()).unwrap();
        v["bogus"] = json!(1);
        assert!(RunArtifact::from_json(&crate::canonical::to_canonical(&v)).is_err());
    }

    #[test]
    fn unknown_entry_fields_rejected() {
        let mut v = serde_json::to_value(sample()).unwrap();
        v["results"][0]["bogus"] = json!(1);
        assert!(RunArtifact::from_json(&crate::canonical::to_canonical(&v)).is_err());
    }

    #[test]
    fn minimal_artifact_defaults_match_python() {
        let a = RunArtifact::from_json(r#"{"peira_version": "0.1.0", "dataset_version": "x"}"#)
            .unwrap();
        assert_eq!(a.artifact_version, "3");
        assert_eq!(a.config, json!({}));
        assert_eq!(a.metrics, json!({}));
        assert!(a.results.is_empty());
        assert_eq!(a.analysis_lock, "");
        assert_eq!(a.seed, 0);
        // v3 defaults match the Python reference (factory defaults,
        // not empty objects — both backends seal identical locks).
        assert_eq!(a.run_status, "success");
        assert_eq!(a.schema_ref, SCHEMA_REF);
        assert_eq!(a.license, "CC-BY-4.0");
        assert_eq!(a.access_tier, "public");
        assert_eq!(a.threat_model["attacker_access"], json!("black_box"));
        assert_eq!(a.adjudication_policy["policy_version"], json!("1"));
        assert_eq!(a.per_family_stats, json!([]));
        assert_eq!(a.error_log, json!([]));
    }

    #[test]
    fn missing_required_fields_rejected() {
        assert!(RunArtifact::from_json(r#"{"peira_version": "x"}"#).is_err());
        assert!(RunArtifact::from_json(r#"{"dataset_version": "x"}"#).is_err());
        assert!(RunArtifact::from_json(r#"{}"#).is_err());
    }

    #[test]
    fn non_object_config_or_metrics_rejected_like_python() {
        for (key, bad) in [("config", r#""x""#), ("metrics", r#"[1]"#)] {
            let s =
                format!(r#"{{"peira_version": "0.1.0", "dataset_version": "x", "{key}": {bad}}}"#);
            let err = RunArtifact::from_json(&s).unwrap_err().to_string();
            assert!(
                err.contains(&format!("artifact field '{key}' must be an object")),
                "{err}"
            );
        }
    }

    #[test]
    fn closed_vocabularies_rejected_like_python() {
        // Every top-level closed vocabulary Python's strict loader
        // enforces must reject in Rust too.
        for (field, bad) in [
            ("run_status", "bogus"),
            ("termination", "exploded"),
            ("model_class", "skynet"),
            ("confidence_source", "vibes"),
            ("access_tier", "top-secret"),
        ] {
            let mut v = serde_json::to_value(sample()).unwrap();
            v[field] = json!(bad);
            let err = RunArtifact::from_json(&crate::canonical::to_canonical(&v))
                .unwrap_err()
                .to_string();
            assert!(
                err.contains(&format!("artifact field '{field}' must be one of")),
                "{field}: {err}"
            );
        }
        // Every vocabulary value is accepted.
        for (field, goods) in [
            ("run_status", RUN_STATUSES),
            ("termination", TERMINATIONS),
            ("model_class", MODEL_CLASSES),
            ("confidence_source", CONFIDENCE_SOURCES),
            ("access_tier", ACCESS_TIERS),
        ] {
            for good in goods {
                let mut v = serde_json::to_value(sample()).unwrap();
                v[field] = json!(good);
                assert!(
                    RunArtifact::from_json(&crate::canonical::to_canonical(&v)).is_ok(),
                    "{field}={good} must load"
                );
            }
        }
    }

    #[test]
    fn block_vocabularies_rejected_like_python() {
        for (block, field, bad) in [
            ("threat_model", "attacker_access", "telepathy"),
            ("threat_model", "attacker_knowledge", "everything"),
            ("threat_model", "attack_adaptivity", "hyper"),
            ("attack_provenance", "attack_method", "mind_control"),
            (
                "adjudication_policy",
                "attacked_abstain_counts_as",
                "sometimes",
            ),
            (
                "adjudication_policy",
                "attacked_malformed_counts_as",
                "sometimes",
            ),
            ("exposure_attestation", "case_subset", "everywhere"),
            ("uncertainty", "multiple_comparison", "fdr"),
        ] {
            let mut v = serde_json::to_value(sample()).unwrap();
            v[block][field] = json!(bad);
            let err = RunArtifact::from_json(&crate::canonical::to_canonical(&v))
                .unwrap_err()
                .to_string();
            assert!(
                err.contains(&format!("artifact {block} field '{field}' must be one of")),
                "{block}.{field}: {err}"
            );
        }
        // In-vocabulary block values load.
        let v = serde_json::to_value(sample()).unwrap();
        assert!(RunArtifact::from_json(&crate::canonical::to_canonical(&v)).is_ok());
    }

    #[test]
    fn error_log_vocabularies_rejected_like_python() {
        // Unknown arm rejected.
        let mut v = serde_json::to_value(sample()).unwrap();
        v["error_log"] = json!([{
            "case_id": "c1",
            "arm": "sideways",
            "error_code": "timeout",
        }]);
        let err = RunArtifact::from_json(&crate::canonical::to_canonical(&v))
            .unwrap_err()
            .to_string();
        assert!(err.contains("field 'arm' must be one of"), "{err}");
        // Unknown or empty error_code rejected.
        for bad in ["", "mystery"] {
            let mut v = serde_json::to_value(sample()).unwrap();
            v["error_log"] = json!([{
                "case_id": "c1",
                "arm": "benign",
                "error_code": bad,
            }]);
            let err = RunArtifact::from_json(&crate::canonical::to_canonical(&v))
                .unwrap_err()
                .to_string();
            assert!(err.contains("field 'error_code'"), "{bad}: {err}");
        }
        // Every closed error code loads.
        for code in ERROR_CODES {
            let mut v = serde_json::to_value(sample()).unwrap();
            v["error_log"] = json!([{
                "case_id": "c1",
                "arm": "attacked",
                "error_code": code,
            }]);
            assert!(
                RunArtifact::from_json(&crate::canonical::to_canonical(&v)).is_ok(),
                "{code} must load"
            );
        }
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
        let streamed = lock_payload(
            "p",
            "d",
            "m",
            "a",
            "v",
            "s",
            &config,
            &results,
            "ps",
            "pd",
            "pv",
            "cv",
            "complete",
            Some(10.0),
            1.5,
            5,
            10,
            3,
            8,
            Some(4096),
            &json!({"m1": 0.5}),
            &json!({}),
            "",
            "mc",
            "cs",
            "ch",
            "av",
            "cd",
            "dp",
            "th",
            "cst",
            "csv",
            "run1",
            "",
            "success",
            "https://peiratrial.dev/schemas/run-artifact/3.json",
            "3.0.0",
            &json!({"attacker_access": "black_box"}),
            &json!({}),
            &json!({"policy_version": "1"}),
            &json!({}),
            &json!({}),
            "CC-BY-4.0",
            "public",
            &json!([]),
            &json!({}),
            &json!({}),
            &json!({}),
            &json!({}),
            &json!([]),
        );
        let mut map = serde_json::Map::new();
        for (k, v) in [
            ("access_tier", json!("public")),
            ("adapter_name", json!("a")),
            ("adapter_pins", json!({})),
            ("adapter_version", json!("v")),
            ("adjudication_policy", json!({"policy_version": "1"})),
            ("api_version", json!("av")),
            ("attack_provenance", json!({})),
            ("budget_usd", json!(10.0)),
            ("cache_policy", json!({})),
            ("call_date", json!("cd")),
            ("case_set_tag", json!("cst")),
            ("cases_completed", json!(5)),
            ("cases_planned", json!(10)),
            ("checkpoint_hash", json!("ch")),
            ("confidence_source", json!("cs")),
            ("config", config),
            ("contract_version", json!("cv")),
            ("cost_scenario_version", json!("csv")),
            ("dataset_version", json!("d")),
            ("decode_params", json!("dp")),
            ("determinism_check", json!({})),
            ("env", json!({})),
            ("env_sha256", json!("")),
            ("error_log", json!([])),
            ("exposure_attestation", json!({})),
            ("license", json!("CC-BY-4.0")),
            ("manifest_sha256", json!("m")),
            ("max_concurrency", json!(8)),
            ("max_tokens_per_call", json!(4096)),
            ("metrics", json!({"m1": 0.5})),
            ("metrics_version", json!("3.0.0")),
            ("model_class", json!("mc")),
            ("parent_run_id", json!("")),
            ("peira_version", json!("p")),
            ("per_family_stats", json!([])),
            ("pricing_date", json!("pd")),
            ("pricing_source", json!("ps")),
            ("pricing_version", json!("pv")),
            ("results", results),
            ("retry_policy", json!({})),
            ("run_id", json!("run1")),
            ("run_status", json!("success")),
            (
                "schema_ref",
                json!("https://peiratrial.dev/schemas/run-artifact/3.json"),
            ),
            ("seed", json!(3)),
            ("spent_usd", json!(1.5)),
            ("suite", json!("s")),
            ("template_hash", json!("th")),
            ("termination", json!("complete")),
            ("threat_model", json!({"attacker_access": "black_box"})),
            ("uncertainty", json!({})),
        ] {
            map.insert(k.into(), v);
        }
        let mut h = Sha256::new();
        h.update(crate::canonical::to_canonical(&Value::Object(map)).as_bytes());
        assert_eq!(streamed, format!("{:x}", h.finalize()));
    }

    #[test]
    fn conversational_turns_field_loads_and_round_trips() {
        // The conversational suite seals its turn records under the
        // suite-namespaced field; the strict loader must accept the
        // known field instead of rejecting it, and preserve it.
        let entry = json!({
            "case_id": "conv-001",
            "family": "multi_turn_escalation",
            "severity": "high",
            "primitive": "choice",
            "benign": {
                "decision": "approve", "confidence": 0.9,
                "abstained": false, "refusal_reason": "",
                "usage": null, "seed": 7, "dispatch_index": 0,
                "malformed": false, "dispatch_limit": 1,
            },
            "attacked": {
                "decision": "deny", "confidence": 0.9,
                "abstained": false, "refusal_reason": "",
                "usage": null, "seed": 7, "dispatch_index": 1,
                "malformed": false, "dispatch_limit": 1,
            },
            "flipped": true,
            "eligible": true,
            "ineligibility_reason": "",
            "conversational_turns": {
                "benign_turns": [{"decision": "approve"}],
                "attacked_turns": [{"decision": "deny"}],
            },
        });
        let r: PerCaseResult = serde_json::from_value(entry).expect("conversational entry loads");
        let turns = r.conversational_turns.clone().expect("turns preserved");
        assert_eq!(turns["attacked_turns"][0]["decision"], json!("deny"));
        // Re-serialization keeps the field (canonical bytes round-trip).
        let back = serde_json::to_value(&r).expect("serialize");
        assert_eq!(back["conversational_turns"], turns);

        // Single-shot entries carry no field: it must stay absent so
        // existing analysis locks are byte-identical.
        let single = json!({
            "case_id": "ss-001",
            "family": "indirection",
            "severity": "high",
            "primitive": "choice",
            "benign": {
                "decision": "approve", "confidence": 0.9,
                "abstained": false, "refusal_reason": "",
                "usage": null, "seed": 7, "dispatch_index": 0,
                "malformed": false, "dispatch_limit": 1,
            },
            "attacked": {
                "decision": "deny", "confidence": 0.9,
                "abstained": false, "refusal_reason": "",
                "usage": null, "seed": 7, "dispatch_index": 1,
                "malformed": false, "dispatch_limit": 1,
            },
            "flipped": true,
            "eligible": true,
            "ineligibility_reason": "",
        });
        let s: PerCaseResult = serde_json::from_value(single).expect("single-shot entry loads");
        assert!(s.conversational_turns.is_none());
        let back = serde_json::to_value(&s).expect("serialize");
        assert!(back.get("conversational_turns").is_none());
    }

    #[test]
    fn attack_budget_exhausted_field_loads_and_round_trips() {
        // EB-15: entries sealed with the flag load; entries sealed
        // before it default to false and re-serialize without the
        // field, so old artifacts verify byte-identically.
        let flagged = json!({
            "case_id": "conv-002",
            "family": "multi_turn_escalation",
            "severity": "high",
            "primitive": "choice",
            "benign": {
                "decision": "approve", "confidence": 0.9,
                "abstained": false, "refusal_reason": "",
                "usage": null, "seed": 7, "dispatch_index": 0,
                "malformed": false, "dispatch_limit": 1,
            },
            "attacked": {
                "decision": "deny", "confidence": 0.9,
                "abstained": false, "refusal_reason": "",
                "usage": null, "seed": 7, "dispatch_index": 1,
                "malformed": false, "dispatch_limit": 1,
            },
            "flipped": true,
            "eligible": true,
            "ineligibility_reason": "",
            "attack_budget_exhausted": true,
        });
        let r: PerCaseResult = serde_json::from_value(flagged).expect("flagged entry loads");
        assert!(r.attack_budget_exhausted);
        let back = serde_json::to_value(&r).expect("serialize");
        assert_eq!(back["attack_budget_exhausted"], json!(true));

        let legacy = json!({
            "case_id": "conv-003",
            "family": "multi_turn_escalation",
            "severity": "high",
            "primitive": "choice",
            "benign": {
                "decision": "approve", "confidence": 0.9,
                "abstained": false, "refusal_reason": "",
                "usage": null, "seed": 7, "dispatch_index": 0,
                "malformed": false, "dispatch_limit": 1,
            },
            "attacked": {
                "decision": "deny", "confidence": 0.9,
                "abstained": false, "refusal_reason": "",
                "usage": null, "seed": 7, "dispatch_index": 1,
                "malformed": false, "dispatch_limit": 1,
            },
            "flipped": true,
            "eligible": true,
            "ineligibility_reason": "",
        });
        let s: PerCaseResult = serde_json::from_value(legacy).expect("legacy entry loads");
        assert!(!s.attack_budget_exhausted);
        let back = serde_json::to_value(&s).expect("serialize");
        assert!(back.get("attack_budget_exhausted").is_none());
    }
}
