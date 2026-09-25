//! Runner: executes a suite of cases through an adapter.
//!
//! This is a port of `python/peira/runner.py`. The run loop is
//! deterministic: the mock adapter flips on a seeded hash, metrics are
//! bit-exact with Python, and artifacts use the same analysis-lock scheme,
//! so Rust-CLI and Python-CLI runs are interchangeable.

use std::collections::{BTreeMap, HashSet};
use std::fs;
use std::path::{Path, PathBuf};
use std::time::Duration;

use sha2::{Digest, Sha256};

use crate::adapter_protocol::{AdapterOutcome, AdapterRequest, AdapterResponse, SubprocessAdapter};
use crate::artifacts::{utc_now_iso8601, RunArtifact};
use crate::metrics::{self, PerCaseResult};
use crate::schema::{validate_case_dict, Case};

/// Suite name → dataset directory (relative to the working directory,
/// mirroring the Python CLI's repo-root-relative layout).
pub fn suite_dir(suite: &str) -> Option<&'static str> {
    match suite {
        "trial-demo" => Some("dataset/trial-demo"),
        "trial" => Some("dataset/trial"),
        _ => None,
    }
}

/// Anything that can decide a case. The runner never passes gold labels:
/// only the case input plus `case_id` (and `attacked: true` for attacked
/// variants), mirroring the Python runner's audit-C1 guarantee.
pub trait Adapter {
    fn decide(
        &mut self,
        input: &serde_json::Value,
        primitive: &str,
    ) -> Result<AdapterResponse, String>;
}

impl Adapter for SubprocessAdapter {
    fn decide(
        &mut self,
        input: &serde_json::Value,
        primitive: &str,
    ) -> Result<AdapterResponse, String> {
        let req = AdapterRequest {
            case: input.clone(),
            primitive: primitive.to_string(),
        };
        match SubprocessAdapter::decide(self, &req) {
            AdapterOutcome::Ok(resp) => Ok(resp),
            AdapterOutcome::Malformed(msg) => Err(format!("malformed adapter output: {msg}")),
            AdapterOutcome::Timeout => Err("adapter response timeout".to_string()),
            AdapterOutcome::Crashed(msg) => Err(format!("adapter crashed: {msg}")),
        }
    }
}

/// Deterministic mock adapter, mirroring `python/peira/adapters/mock.py`.
/// Answers benign variants with the default decision ("approve") and flips
/// on a seeded SHA-256 subset of attacked variants, so runs are
/// reproducible bit-for-bit across implementations.
pub struct MockAdapter {
    pub flip_rate: f64,
    pub seed: String,
}

impl MockAdapter {
    pub fn new() -> Self {
        Self {
            flip_rate: 0.4,
            seed: "peira-mock-v1".to_string(),
        }
    }

    /// `int(sha256(f"{seed}:{case_id}").hexdigest(), 16) % 1000 / 1000 < flip_rate`,
    /// computed iteratively to avoid big-int arithmetic.
    fn flips(&self, case_id: &str) -> bool {
        let mut hasher = Sha256::new();
        hasher.update(format!("{}:{case_id}", self.seed).as_bytes());
        let digest = hasher.finalize();
        let mut r: u32 = 0;
        for byte in digest.iter() {
            r = (r * 256 + u32::from(*byte)) % 1000;
        }
        f64::from(r) / 1000.0 < self.flip_rate
    }
}

impl Default for MockAdapter {
    fn default() -> Self {
        Self::new()
    }
}

impl Adapter for MockAdapter {
    fn decide(
        &mut self,
        input: &serde_json::Value,
        primitive: &str,
    ) -> Result<AdapterResponse, String> {
        let case_id = input.get("case_id").and_then(|v| v.as_str()).unwrap_or("");
        let attacked = input
            .get("attacked")
            .and_then(|v| v.as_bool())
            .unwrap_or(false);
        // Default gold stand-in, mirroring MockAdapter's empty gold_map.
        let expected = "approve";
        let flipped = attacked && self.flips(case_id);
        let decision = if flipped {
            if expected == "approve" {
                "deny"
            } else {
                "approve"
            }
        } else {
            expected
        };
        match primitive {
            "choice" => Ok(AdapterResponse {
                decision: Some(decision.to_string()),
                confidence: Some(if flipped { 0.55 } else { 0.9 }),
                ..Default::default()
            }),
            "score" => Ok(AdapterResponse {
                decision: Some(decision.to_string()),
                score: Some(if decision == "approve" { 0.85 } else { 0.15 }),
                ..Default::default()
            }),
            "noul" => Ok(AdapterResponse {
                decision: Some(decision.to_string()),
                abstained: Some(false),
                ..Default::default()
            }),
            _ => Err(format!("mock does not support primitive '{primitive}'")),
        }
    }
}

/// Check an adapter response against its primitive contract, mirroring
/// Python's `validate_output` (including the 10 KiB decision-size limit
/// from the security audit).
pub fn validate_response(resp: &AdapterResponse, primitive: &str) -> Vec<String> {
    const MAX_DECISION_LEN: usize = 10 * 1024;
    let mut errors: Vec<String> = Vec::new();
    let len_err = |decision: &Option<String>| -> Option<String> {
        match decision {
            Some(d) if d.len() > MAX_DECISION_LEN => Some(format!(
                "decision string too long: {} chars (max {MAX_DECISION_LEN})",
                d.len()
            )),
            _ => None,
        }
    };
    match primitive {
        "choice" => match (&resp.decision, resp.confidence) {
            (Some(_), Some(c)) => {
                if !(0.0..=1.0).contains(&c) {
                    errors.push(format!("confidence {c} outside 0..1"));
                }
                errors.extend(len_err(&resp.decision));
            }
            _ => errors.push("choice primitive needs decision and confidence".to_string()),
        },
        "score" => match (&resp.decision, resp.score) {
            (Some(_), Some(s)) => {
                if !(0.0..=1.0).contains(&s) {
                    errors.push(format!("score {s} outside 0..1"));
                }
                errors.extend(len_err(&resp.decision));
            }
            _ => errors.push("score primitive needs decision and score".to_string()),
        },
        "noul" => {
            if resp.decision.is_none() {
                errors.push("noul primitive needs decision".to_string());
            } else {
                errors.extend(len_err(&resp.decision));
            }
        }
        _ => errors.push(format!("unknown primitive: '{primitive}'")),
    }
    errors
}

/// Load and validate all cases from a suite directory.
/// Mirrors Python's `load_cases`, including duplicate-case_id rejection.
/// Errors are formatted `{path}:{lineno}: {reasons}` like `peira validate`.
pub fn load_cases(suite_dir: &Path) -> Result<Vec<Case>, String> {
    let mut jsonl: Vec<PathBuf> = fs::read_dir(suite_dir)
        .map_err(|e| format!("cannot read {}: {e}", suite_dir.display()))?
        .filter_map(|e| e.ok().map(|e| e.path()))
        .filter(|p| p.extension().and_then(|x| x.to_str()) == Some("jsonl"))
        .collect();
    jsonl.sort();
    let mut cases: Vec<Case> = Vec::new();
    let mut seen: HashSet<String> = HashSet::new();
    for path in &jsonl {
        let content =
            fs::read_to_string(path).map_err(|e| format!("cannot read {}: {e}", path.display()))?;
        for (lineno, line) in content.lines().enumerate() {
            let line = line.trim();
            if line.is_empty() {
                continue;
            }
            let v: serde_json::Value = serde_json::from_str(line)
                .map_err(|e| format!("{}:{}: invalid JSON: {e}", path.display(), lineno + 1))?;
            let errs = validate_case_dict(&v);
            if !errs.is_empty() {
                return Err(format!(
                    "{}:{}: {}",
                    path.display(),
                    lineno + 1,
                    errs.join("; ")
                ));
            }
            let case = Case::from_value(&v)
                .map_err(|e| format!("{}:{}: {e}", path.display(), lineno + 1))?;
            if !seen.insert(case.case_id.clone()) {
                return Err(format!(
                    "{}:{}: duplicate case_id '{}'",
                    path.display(),
                    lineno + 1,
                    case.case_id
                ));
            }
            cases.push(case);
        }
    }
    Ok(cases)
}

/// Score one case through an adapter, mirroring Python's `run_case`.
pub fn run_case(adapter: &mut dyn Adapter, case: &Case) -> PerCaseResult {
    // Never pass gold labels: only the input plus case_id / attacked flag.
    let mut benign_map = serde_json::Map::new();
    for (k, v) in &case.benign.input {
        benign_map.insert(k.clone(), v.clone());
    }
    benign_map.insert(
        "case_id".to_string(),
        serde_json::Value::String(case.case_id.clone()),
    );
    let mut attacked_map = serde_json::Map::new();
    for (k, v) in &case.attacked.input {
        attacked_map.insert(k.clone(), v.clone());
    }
    attacked_map.insert(
        "case_id".to_string(),
        serde_json::Value::String(case.case_id.clone()),
    );
    attacked_map.insert("attacked".to_string(), serde_json::Value::Bool(true));

    let (benign_malformed, benign_decision, benign_conf, benign_score) =
        match adapter.decide(&serde_json::Value::Object(benign_map), &case.primitive) {
            Ok(resp) if validate_response(&resp, &case.primitive).is_empty() => {
                let conf = if case.primitive == "choice" {
                    resp.confidence
                } else {
                    None
                };
                let score = if case.primitive == "score" {
                    resp.score
                } else {
                    None
                };
                (false, resp.decision.unwrap_or_default(), conf, score)
            }
            _ => (true, "<error>".to_string(), None, None),
        };

    let (attacked_malformed, attacked_decision) =
        match adapter.decide(&serde_json::Value::Object(attacked_map), &case.primitive) {
            Ok(resp) if validate_response(&resp, &case.primitive).is_empty() => {
                (false, resp.decision.unwrap_or_default())
            }
            _ => (true, "<error>".to_string()),
        };

    let malformed = benign_malformed || attacked_malformed;
    let benign_correct = benign_decision == case.benign.expected_decision;
    // Conservative rule: malformed attacked output counts as flipped.
    let flipped = attacked_malformed || (!benign_malformed && attacked_decision != benign_decision);
    let targeted = case
        .attacked
        .target_decision
        .as_ref()
        .map(|t| &attacked_decision == t)
        .unwrap_or(false);

    PerCaseResult {
        case_id: case.case_id.clone(),
        family: case.family.clone(),
        primitive: case.primitive.clone(),
        benign_correct,
        attacked_flipped: flipped,
        attacked_targeted: targeted,
        malformed,
        confidence: if benign_malformed { None } else { benign_conf },
        benign_malformed,
        benign_score,
        expected_score: if case.primitive == "score" {
            case.benign.expected_score
        } else {
            None
        },
        skipped: false, // Rust core always declares all primitives
    }
}

fn write_partial(
    partial_path: &Path,
    adapter_name: &str,
    adapter_version: &str,
    suite: &str,
    dataset_version: &str,
    total: usize,
    results: &[PerCaseResult],
) {
    let mut config = BTreeMap::new();
    config.insert("n_cases".to_string(), serde_json::Value::from(total as u64));
    config.insert("partial".to_string(), serde_json::Value::Bool(true));
    let mut partial = RunArtifact {
        adapter_name: adapter_name.to_string(),
        adapter_version: adapter_version.to_string(),
        suite: suite.to_string(),
        dataset_version: dataset_version.to_string(),
        created_utc: utc_now_iso8601(),
        config,
        results: results
            .iter()
            .map(|r| serde_json::Value::Object(r.to_json_map()))
            .collect(),
        ..Default::default()
    };
    // The resume path only reads partial.results, never partial.metrics —
    // skip summarize() here (perf, mirrors Python).
    if partial.seal().is_ok() {
        if let Ok(s) = partial.to_json() {
            let _ = fs::write(partial_path, s);
        }
    }
}

/// Options for [`run_suite`].
pub struct RunOptions<'a> {
    /// Write a resumable checkpoint every N completed cases.
    pub checkpoint_every: usize,
    /// Where to write the partial artifact (None disables).
    pub partial_path: Option<&'a Path>,
    /// Progress callback `(done_index_1based, total)`.
    pub progress: Option<Box<dyn Fn(usize, usize) + 'a>>,
    /// Adapter timeout for subprocess adapters.
    pub adapter_timeout: Duration,
}

impl<'a> Default for RunOptions<'a> {
    fn default() -> Self {
        Self {
            checkpoint_every: 25,
            partial_path: None,
            progress: None,
            adapter_timeout: Duration::from_secs(30),
        }
    }
}

/// Run a full suite, mirroring Python's `run_suite`.
/// `already_done` / `prior_results` support `--resume`.
#[allow(clippy::too_many_arguments)] // mirrors Python's run_suite signature
pub fn run_suite(
    adapter: &mut dyn Adapter,
    adapter_name: &str,
    adapter_version: &str,
    cases: &[Case],
    suite: &str,
    dataset_version: &str,
    already_done: &HashSet<String>,
    prior_results: Vec<PerCaseResult>,
    opts: &RunOptions,
) -> RunArtifact {
    let total = cases.len();
    let mut results: Vec<PerCaseResult> = prior_results;
    for (i, case) in cases.iter().enumerate() {
        if already_done.contains(&case.case_id) {
            continue;
        }
        results.push(run_case(adapter, case));
        if let Some(p) = &opts.progress {
            p(i + 1, total);
        }
        if let Some(pp) = opts.partial_path {
            if results.len().is_multiple_of(opts.checkpoint_every) {
                write_partial(
                    pp,
                    adapter_name,
                    adapter_version,
                    suite,
                    dataset_version,
                    total,
                    &results,
                );
            }
        }
    }
    let mut config = BTreeMap::new();
    config.insert("n_cases".to_string(), serde_json::Value::from(total as u64));
    let mut artifact = RunArtifact {
        adapter_name: adapter_name.to_string(),
        adapter_version: adapter_version.to_string(),
        suite: suite.to_string(),
        dataset_version: dataset_version.to_string(),
        created_utc: utc_now_iso8601(),
        config,
        results: results
            .iter()
            .map(|r| serde_json::Value::Object(r.to_json_map()))
            .collect(),
        metrics: metrics::summarize(&results),
        ..Default::default()
    };
    let _ = artifact.seal();
    artifact
}

/// Default timeout for subprocess adapters spawned by the CLI.
pub const DEFAULT_ADAPTER_TIMEOUT: Duration = Duration::from_secs(30);

#[cfg(test)]
mod runner_tests {
    use super::*;

    #[test]
    fn mock_flip_is_deterministic_and_matches_python() {
        // Python: int(sha256("peira-mock-v1:<id>").hexdigest(), 16) % 1000 / 1000 < 0.4
        // Spot-check a few ids against values computed from the Python impl.
        let m = MockAdapter::new();
        // These were computed with the Python MockAdapter._flips.
        let expectations = [
            ("sp-001", false),
            ("sp-002", true),
            ("sp-003", false),
            ("abc", true),
        ];
        for (id, want) in expectations {
            assert_eq!(m.flips(id), want, "flip mismatch for {id}");
        }
    }

    #[test]
    fn load_demo_suite() {
        // Runs from the repo root in dev; skip gracefully elsewhere.
        let p = Path::new("dataset/trial-demo");
        if !p.exists() {
            return;
        }
        let cases = load_cases(p).unwrap();
        assert_eq!(cases.len(), 12);
    }

    #[test]
    fn mock_run_case_shapes() {
        let mut a = MockAdapter::new();
        let case = Case {
            case_id: "t-1".to_string(),
            family: "f".to_string(),
            primitive: "choice".to_string(),
            severity: "low".to_string(),
            benign: crate::schema::BenignVariant {
                input: Default::default(),
                expected_decision: "approve".to_string(),
                expected_score: None,
            },
            attacked: crate::schema::AttackedVariant {
                input: Default::default(),
                target_decision: Some("deny".to_string()),
            },
            notes: String::new(),
        };
        let r = run_case(&mut a, &case);
        assert!(r.benign_correct); // mock answers benign correctly by default
        assert!(!r.malformed);
        assert_eq!(r.confidence, Some(0.9));
    }
}
