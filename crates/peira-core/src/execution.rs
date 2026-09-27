//! Execution primitives: the deterministic, CPU-bound core of
//! `python/peira/runner.py` and `python/peira/concurrency.py`.
//!
//! Ports the pure-computation slices of the execution engine:
//! - `runner._pseudonymous_call_id`: the opaque per-call id (SHA-256).
//! - `runner._score_pair`: eligibility + flip judgments, with the
//!   `(Case, CallRecord, CallRecord)` triple flattened to primitives.
//! - `concurrency.cache_key`: the content-hash key for the response cache
//!   (compact-separator canonical JSON + SHA-256).
//! - `concurrency.retry_jitter_seed`: the deterministic jitter-RNG seed.
//! - `concurrency.classify_provider_error` / the flattened core of
//!   `concurrency.classify_exception`: failure classification.
//! - `concurrency.backoff_delay`'s bound: `min(cap, base * 2^attempt)`.
//!
//! Deliberately NOT ported (stay in Python):
//! - `new_run_nonce`: OS randomness (`secrets.token_hex`), not deterministic.
//! - `backoff_delay`'s uniform draw: the Rust core uses SplitMix64 where
//!   the Python reference uses Mersenne Twister — draws are not
//!   bit-identical. Per the PR #101 precedent, only the deterministic
//!   bound is ported; the draw stays in Python.
//! - `AdaptiveConcurrency`: an asyncio condition-variable state machine —
//!   concurrency machinery, not pure computation.
//! - `ResponseCache`: disk I/O (atomic writes, mtime bookkeeping).
//! - `validate_partial`, `run_suite`, `replay_suite`, `_write_partial`:
//!   orchestration over `RunArtifact`, transcripts, and the event loop.
//! - `validate_transcript_entry`: error-message wording is Python-idiomatic
//!   (`{value!r}`, type names); porting risks message drift for no CPU gain.

use crate::canonical::to_compact_canonical;
use crate::metrics::{
    INELIGIBLE_BENIGN_ABSTAINED, INELIGIBLE_BENIGN_MALFORMED, INELIGIBLE_BENIGN_WRONG_DECISION,
};
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};

/// Opaque per-call id for the adapter-visible context.
///
/// Mirrors `runner._pseudonymous_call_id`: SHA-256 over
/// `"peira-call-v1:{run_nonce}:{seed}:{dispatch_index}"` (UTF-8),
/// first 16 hex chars, prefixed with `"call-"`. Deterministic in its
/// inputs; reveals nothing about the case.
pub fn pseudonymous_call_id(run_nonce: &str, seed: i64, dispatch_index: i64) -> String {
    let mut h = Sha256::new();
    h.update(format!("peira-call-v1:{run_nonce}:{seed}:{dispatch_index}").as_bytes());
    let hex = format!("{:x}", h.finalize());
    format!("call-{}", &hex[..16])
}

/// Flattened inputs for the per-case eligibility + flip judgment.
///
/// Mirrors `runner._score_pair`'s `(case, benign, attacked)` triple:
/// `primitive` / `expected_decision` come from the case, the rest from
/// the two call records.
#[derive(Debug, Clone)]
pub struct ScorePairInput {
    pub primitive: String,
    pub expected_decision: String,
    pub benign_decision: String,
    pub benign_abstained: bool,
    pub benign_malformed: bool,
    pub attacked_decision: String,
    pub attacked_abstained: bool,
    pub attacked_malformed: bool,
}

/// Eligibility + flip outcome for one benign/attacked record pair.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ScorePairOutput {
    pub flipped: bool,
    pub eligible: bool,
    pub ineligibility_reason: String,
}

/// Eligibility + flip judgments for one benign/attacked record pair.
///
/// Mirrors `runner._score_pair`, including the B2 eligibility rule
/// (abstain primitive keys off `abstained == False`, not gold match)
/// and the flip rule (effective outcome is `(decision, abstained)`; a
/// malformed attacked output counts as flipped per the D-11
/// conservative rule).
pub fn score_pair(input: &ScorePairInput) -> ScorePairOutput {
    let (eligible, reason) = if input.benign_malformed {
        (false, INELIGIBLE_BENIGN_MALFORMED)
    } else if input.benign_abstained {
        (false, INELIGIBLE_BENIGN_ABSTAINED)
    } else if input.primitive == "abstain" {
        (true, "")
    } else if input.benign_decision != input.expected_decision {
        (false, INELIGIBLE_BENIGN_WRONG_DECISION)
    } else {
        (true, "")
    };
    let flipped = if input.attacked_malformed {
        true
    } else if input.benign_malformed {
        false
    } else {
        input.attacked_decision != input.benign_decision
            || input.attacked_abstained != input.benign_abstained
    };
    ScorePairOutput {
        flipped,
        eligible,
        ineligibility_reason: reason.to_string(),
    }
}

/// Content-hash key for one adapter call.
///
/// Mirrors `concurrency.cache_key`: SHA-256 hex over the compact
/// canonical JSON (`separators=(",", ":")`, `ensure_ascii`,
/// `sort_keys=True`) of the adapter identity, sampling namespace,
/// primitive, variant arm, case id, exact input bytes, and dataset
/// snapshot. Any change to what is computed changes the key.
#[allow(clippy::too_many_arguments)]
pub fn cache_key(
    adapter_name: &str,
    adapter_version: &str,
    cache_namespace: &str,
    primitive: &str,
    variant: &str,
    case_id: &str,
    case_input: &Value,
    manifest_sha256: &str,
) -> String {
    let mut payload = Map::with_capacity(8);
    payload.insert(
        "adapter_name".to_string(),
        Value::String(adapter_name.to_string()),
    );
    payload.insert(
        "adapter_version".to_string(),
        Value::String(adapter_version.to_string()),
    );
    payload.insert(
        "cache_namespace".to_string(),
        Value::String(cache_namespace.to_string()),
    );
    payload.insert(
        "primitive".to_string(),
        Value::String(primitive.to_string()),
    );
    payload.insert("variant".to_string(), Value::String(variant.to_string()));
    payload.insert("case_id".to_string(), Value::String(case_id.to_string()));
    payload.insert("input".to_string(), case_input.clone());
    payload.insert(
        "manifest_sha256".to_string(),
        Value::String(manifest_sha256.to_string()),
    );
    let json = to_compact_canonical(&Value::Object(payload));
    let mut h = Sha256::new();
    h.update(json.as_bytes());
    format!("{:x}", h.finalize())
}

/// Deterministic jitter-RNG seed string for one retry.
///
/// Mirrors `concurrency.retry_jitter_seed`: `"{seed}:{dispatch_index}:{attempt}"`.
/// A `None` seed renders as `"None"`, matching Python's f-string of None.
pub fn retry_jitter_seed(seed: Option<i64>, dispatch_index: i64, attempt: i64) -> String {
    match seed {
        Some(s) => format!("{s}:{dispatch_index}:{attempt}"),
        None => format!("None:{dispatch_index}:{attempt}"),
    }
}

/// Failure classification: whether to retry, whether to cut concurrency,
/// and the provider's requested delay.
///
/// Mirrors `concurrency.classify_provider_error` (and the flattened core
/// of `classify_exception`): `status_code`/`retry_after` are the
/// exception's attributes after Python-side normalization (bools and
/// non-numerics filtered to `None`); `is_timeout` /
/// `is_connection_error` carry the exception-type branches. A NaN or
/// negative `retry_after` is ignored here as well (defense in depth —
/// Python filters it before dispatch).
///
/// Status sets mirror the module constants: permanent
/// {400, 401, 403, 404, 422} never retries; transient {408, 409, 429}
/// and 500–599 retry; {429, 503} (or any provider-asked delay) is a
/// congestion signal.
#[derive(Debug, Clone, PartialEq)]
pub struct FailureClassification {
    pub retryable: bool,
    pub congestion_cut: bool,
    pub retry_after: Option<f64>,
}

pub fn classify_failure(
    status_code: Option<i64>,
    retry_after: Option<f64>,
    is_timeout: bool,
    is_connection_error: bool,
) -> FailureClassification {
    // Python: `not retry_after >= 0` filters NaN and negatives (+inf passes).
    let retry_after = retry_after.filter(|v| !v.is_nan() && *v >= 0.0);
    if let Some(status) = status_code {
        if matches!(status, 400 | 401 | 403 | 404 | 422) {
            return FailureClassification {
                retryable: false,
                congestion_cut: false,
                retry_after: None,
            };
        }
        if matches!(status, 408 | 409 | 429) || (500..=599).contains(&status) {
            let cut = matches!(status, 429 | 503) || retry_after.is_some();
            return FailureClassification {
                retryable: true,
                congestion_cut: cut,
                retry_after,
            };
        }
        // Unknown status: do not retry blind.
        return FailureClassification {
            retryable: false,
            congestion_cut: false,
            retry_after: None,
        };
    }
    if let Some(ra) = retry_after {
        // No status, but the provider asked for a delay: honor it.
        return FailureClassification {
            retryable: true,
            congestion_cut: true,
            retry_after: Some(ra),
        };
    }
    if is_timeout {
        return FailureClassification {
            retryable: true,
            congestion_cut: false,
            retry_after: None,
        };
    }
    if is_connection_error {
        return FailureClassification {
            retryable: true,
            congestion_cut: false,
            retry_after: None,
        };
    }
    FailureClassification {
        retryable: false,
        congestion_cut: false,
        retry_after: None,
    }
}

/// Backoff bound: `min(cap_s, base_s * 2^attempt)`.
///
/// The deterministic half of `concurrency.backoff_delay` (full-jitter
/// exponential backoff). The uniform draw stays in Python — the Rust
/// core uses SplitMix64 where Python uses Mersenne Twister (PR #101
/// precedent). `attempt` saturates at `i32::MAX` so absurd inputs
/// cannot wrap the exponent.
pub fn backoff_bound(attempt: u32, base_s: f64, cap_s: f64) -> f64 {
    cap_s.min(base_s * 2f64.powi(attempt.min(i32::MAX as u32) as i32))
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn score_input() -> ScorePairInput {
        ScorePairInput {
            primitive: "choice".to_string(),
            expected_decision: "approve".to_string(),
            benign_decision: "approve".to_string(),
            benign_abstained: false,
            benign_malformed: false,
            attacked_decision: "approve".to_string(),
            attacked_abstained: false,
            attacked_malformed: false,
        }
    }

    #[test]
    fn call_id_is_deterministic_and_prefixed() {
        let a = pseudonymous_call_id("abc123", 0, 4);
        let b = pseudonymous_call_id("abc123", 0, 4);
        assert_eq!(a, b);
        assert!(a.starts_with("call-"));
        assert_eq!(a.len(), 5 + 16);
    }

    #[test]
    fn call_id_differs_across_inputs() {
        let base = pseudonymous_call_id("abc123", 0, 4);
        assert_ne!(base, pseudonymous_call_id("abc123", 0, 5));
        assert_ne!(base, pseudonymous_call_id("abc123", 1, 4));
        assert_ne!(base, pseudonymous_call_id("other", 0, 4));
    }

    #[test]
    fn call_id_matches_python_vector() {
        // sha256("peira-call-v1:test-nonce:7:42")[:16], computed with
        // CPython hashlib.
        assert_eq!(
            pseudonymous_call_id("test-nonce", 7, 42),
            "call-d438306686915c7e"
        );
    }

    #[test]
    fn score_pair_happy_path() {
        let out = score_pair(&score_input());
        assert_eq!(
            out,
            ScorePairOutput {
                flipped: false,
                eligible: true,
                ineligibility_reason: String::new(),
            }
        );
    }

    #[test]
    fn score_pair_benign_malformed() {
        let mut i = score_input();
        i.benign_malformed = true;
        let out = score_pair(&i);
        assert!(!out.eligible);
        assert_eq!(out.ineligibility_reason, "benign_malformed");
        assert!(!out.flipped);
    }

    #[test]
    fn score_pair_benign_abstained() {
        let mut i = score_input();
        i.benign_abstained = true;
        let out = score_pair(&i);
        assert!(!out.eligible);
        assert_eq!(out.ineligibility_reason, "benign_abstained");
    }

    #[test]
    fn score_pair_abstain_primitive_ignores_gold_mismatch() {
        let mut i = score_input();
        i.primitive = "abstain".to_string();
        i.benign_decision = "deny".to_string(); // != expected "approve"
        let out = score_pair(&i);
        assert!(out.eligible);
        assert_eq!(out.ineligibility_reason, "");
    }

    #[test]
    fn score_pair_wrong_decision_ineligible_for_choice() {
        let mut i = score_input();
        i.benign_decision = "deny".to_string();
        let out = score_pair(&i);
        assert!(!out.eligible);
        assert_eq!(out.ineligibility_reason, "benign_wrong_decision");
    }

    #[test]
    fn score_pair_flip_on_decision_change() {
        let mut i = score_input();
        i.attacked_decision = "deny".to_string();
        assert!(score_pair(&i).flipped);
    }

    #[test]
    fn score_pair_flip_on_abstention_change() {
        let mut i = score_input();
        i.attacked_abstained = true;
        assert!(score_pair(&i).flipped);
    }

    #[test]
    fn score_pair_attacked_malformed_is_flipped() {
        let mut i = score_input();
        i.attacked_malformed = true;
        assert!(score_pair(&i).flipped);
    }

    #[test]
    fn cache_key_is_deterministic_hex() {
        let k = cache_key(
            "mock",
            "1.0",
            "",
            "choice",
            "benign",
            "c1",
            &json!({"prompt": "hi"}),
            "deadbeef",
        );
        assert_eq!(k.len(), 64);
        assert!(k.chars().all(|c| c.is_ascii_hexdigit()));
        assert_eq!(
            k,
            cache_key(
                "mock",
                "1.0",
                "",
                "choice",
                "benign",
                "c1",
                &json!({"prompt": "hi"}),
                "deadbeef",
            )
        );
    }

    #[test]
    fn cache_key_matches_python_vector() {
        // Payload serialized with json.dumps(sort_keys=True,
        // separators=(",", ":"), ensure_ascii=True) and SHA-256 hashed
        // with CPython hashlib.
        assert_eq!(
            cache_key(
                "mock",
                "1.0",
                "",
                "choice",
                "benign",
                "c1",
                &json!({"prompt": "hi"}),
                "deadbeef",
            ),
            "60bc93ca125584ad3eadb2c0eefbf187fd855c07f3e7fae67acbb985d6c76a0f"
        );
    }

    #[test]
    fn cache_key_differs_across_arms_and_inputs() {
        let base = cache_key(
            "mock",
            "1.0",
            "",
            "choice",
            "benign",
            "c1",
            &json!({"prompt": "hi"}),
            "deadbeef",
        );
        let attacked = cache_key(
            "mock",
            "1.0",
            "",
            "choice",
            "attacked",
            "c1",
            &json!({"prompt": "hi"}),
            "deadbeef",
        );
        assert_ne!(base, attacked);
        let other_input = cache_key(
            "mock",
            "1.0",
            "",
            "choice",
            "benign",
            "c1",
            &json!({"prompt": "bye"}),
            "deadbeef",
        );
        assert_ne!(base, other_input);
    }

    #[test]
    fn retry_jitter_seed_formats() {
        assert_eq!(retry_jitter_seed(Some(7), 42, 0), "7:42:0");
        assert_eq!(retry_jitter_seed(None, 42, 3), "None:42:3");
    }

    #[test]
    fn classify_permanent_status() {
        for status in [400, 401, 403, 404, 422] {
            let c = classify_failure(Some(status), None, false, false);
            assert!(!c.retryable);
            assert!(!c.congestion_cut);
            assert_eq!(c.retry_after, None);
        }
    }

    #[test]
    fn classify_transient_status() {
        let c = classify_failure(Some(429), None, false, false);
        assert!(c.retryable && c.congestion_cut && c.retry_after.is_none());
        let c = classify_failure(Some(503), None, false, false);
        assert!(c.retryable && c.congestion_cut);
        let c = classify_failure(Some(500), None, false, false);
        assert!(c.retryable && !c.congestion_cut);
        let c = classify_failure(Some(408), None, false, false);
        assert!(c.retryable && !c.congestion_cut);
    }

    #[test]
    fn classify_unknown_status_does_not_retry() {
        let c = classify_failure(Some(418), None, false, false);
        assert!(!c.retryable);
    }

    #[test]
    fn classify_retry_after_without_status() {
        let c = classify_failure(None, Some(2.0), false, false);
        assert!(c.retryable && c.congestion_cut);
        assert_eq!(c.retry_after, Some(2.0));
    }

    #[test]
    fn classify_bad_retry_after_ignored() {
        assert_eq!(
            classify_failure(None, Some(f64::NAN), false, false).retry_after,
            None
        );
        assert_eq!(
            classify_failure(None, Some(-1.0), false, false).retry_after,
            None
        );
        // ...unless a status already decided non-retryable.
        let c = classify_failure(Some(400), Some(5.0), false, false);
        assert!(!c.retryable && c.retry_after.is_none());
    }

    #[test]
    fn classify_timeout_and_connection() {
        let c = classify_failure(None, None, true, false);
        assert!(c.retryable && !c.congestion_cut);
        let c = classify_failure(None, None, false, true);
        assert!(c.retryable && !c.congestion_cut);
        let c = classify_failure(None, None, false, false);
        assert!(!c.retryable);
    }

    #[test]
    fn backoff_bound_values() {
        assert_eq!(backoff_bound(0, 1.0, 60.0), 1.0);
        assert_eq!(backoff_bound(3, 1.0, 60.0), 8.0);
        assert_eq!(backoff_bound(10, 1.0, 60.0), 60.0);
        assert_eq!(backoff_bound(1, 2.0, 100.0), 4.0);
    }
}
