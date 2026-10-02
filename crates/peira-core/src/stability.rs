//! M-7 multi-seed stability protocol + longitudinal drift watch, ported
//! from `python/peira/stability.py` (rust-max slice 5).
//!
//! This module ports the pure numeric core; the Python package keeps:
//! - the dataclasses (`StabilityResult`, `FamilyDrift`, `DriftResult`);
//!   the Rust core returns their fields and the PyO3 binding hands them
//!   back as plain dicts the wrapper uses to construct them
//!   (the slice-4 pattern),
//! - `summary_text` (f-string display formatting stays Python),
//! - `StabilityArtifact` (sealed output: `compute_lock` / `seal` /
//!   `verify` / `to_json` / `from_json`; artifact sealing and the JSON
//!   lock stay Python per the SPLIT #5 recommendation (byte-exact
//!   `json.dumps` parity risk),
//! - input validation (lone-surrogate rejection lives in the Python
//!   wrapper via `peira.metrics._require_result_strings`, so both
//!   backends raise the same `ValueError`).
//!
//! Parity notes:
//! - Float aggregates can differ from the reference by a few ulp
//!   (worst measured: 6 ulp on `item_variance`, 2 ulp on `run_sd`):
//!   on Python 3.12+ the reference sums with the builtin `sum()`
//!   (Neumaier compensated summation) while this core accumulates
//!   naively left-to-right in list order, never a tree reduction;
//!   the reference also computes `** 2` through CPython's C `pow()`
//!   where this core uses `.powi(2)` (exact multiplication). On
//!   Python 3.10/3.11 the builtin `sum()` is itself naive
//!   left-to-right, so the summation matches exactly there. A few
//!   ulp is ~1e-15 relative, immaterial to every reported number.
//! - `per_case_flip_rate` preserves the canonical case order (first
//!   seed's order) as an ordered pair list; the Python wrapper builds
//!   the dict from it in that order.
//! - `newly_flipping` / `newly_fixed` are sorted, and families are
//!   sorted by family name, matching the reference's `sorted(...)`.
//! - `drift_watch` old-run duplicate case ids keep Python-dict
//!   semantics: first-seen position, last-seen value.
//! - `mcnemar_p_value` / `wilson_ci` are the shared `metrics::`
//!   implementations, so the R-07 three-tier withholding policy and the
//!   Wilson formula are identical by construction.
//! - Alignment errors carry the reference's exact messages.

use crate::metrics::{self, PerCaseResult};
use std::collections::{BTreeSet, HashMap, HashSet};
use std::fmt;

/// Significance level for drift-watch degradation flags (DRIFT_ALPHA).
pub const DRIFT_ALPHA: f64 = 0.05;

/// Errors from [`flip_agreement`]'s seed-alignment check. Messages match
/// the Python reference exactly.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum StabilityError {
    /// Fewer than 2 seed runs were provided.
    TooFewRuns(usize),
    /// Duplicate case ids in the first seed run.
    DuplicateCaseIds,
    /// A later seed run scored a different case set (or has dupes).
    MisalignedCaseSet { run: usize, got: usize, want: usize },
}

impl fmt::Display for StabilityError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            StabilityError::TooFewRuns(n) => {
                write!(f, "stability needs >= 2 seed runs, got {n}")
            }
            StabilityError::DuplicateCaseIds => {
                write!(f, "duplicate case ids in the first seed run")
            }
            StabilityError::MisalignedCaseSet { run, got, want } => {
                write!(
                    f,
                    "seed run {run} scored a different case set than seed \
                     run 0 ({got} cases vs {want})"
                )
            }
        }
    }
}

impl std::error::Error for StabilityError {}

/// The k-seed stability analysis fields (numeric core of
/// `StabilityResult`). `seeds` / `excluded_seeds` are filled by the
/// caller and are not part of the numeric core.
#[derive(Debug, Clone, PartialEq)]
pub struct StabilitySummary {
    pub k: usize,
    pub n_cases: usize,
    pub n_cases_total: usize,
    pub per_seed_asr: Vec<f64>,
    pub pooled_asr: f64,
    pub pass_k: f64,
    pub n_agree: usize,
    /// (case_id, flip rate) in canonical case order.
    pub per_case_flip_rate: Vec<(String, f64)>,
    pub wilson_ci: (f64, f64),
    pub run_sd: f64,
    pub item_variance: f64,
    pub n_churn: usize,
}

/// Drift-watch fields for one family (numeric core of `FamilyDrift`).
#[derive(Debug, Clone, PartialEq)]
pub struct FamilyDriftSummary {
    pub family: String,
    pub n_paired: usize,
    pub asr_old: f64,
    pub asr_new: f64,
    pub delta: f64,
    pub n_newly_flipping: usize,
    pub n_newly_fixed: usize,
    /// `None` when withheld (< 10 discordant pairs).
    pub mcnemar_p: Option<f64>,
    pub degraded: bool,
}

/// Drift-watch comparison fields (numeric core of `DriftResult`).
#[derive(Debug, Clone, PartialEq)]
pub struct DriftSummary {
    /// Sorted by family name.
    pub families: Vec<FamilyDriftSummary>,
    /// Sorted case ids.
    pub newly_flipping: Vec<String>,
    /// Sorted case ids.
    pub newly_fixed: Vec<String>,
}

/// Validate that every seed run scored the same case set.
///
/// Returns the canonical case-id order (from the first run). Mirrors
/// the reference's `_check_seed_alignment`.
fn check_seed_alignment(
    results_by_seed: &[Vec<PerCaseResult>],
) -> Result<Vec<String>, StabilityError> {
    if results_by_seed.len() < 2 {
        return Err(StabilityError::TooFewRuns(results_by_seed.len()));
    }
    let canonical: Vec<String> = results_by_seed[0]
        .iter()
        .map(|r| r.case_id.clone())
        .collect();
    {
        let mut seen = HashSet::with_capacity(canonical.len());
        if canonical.iter().any(|cid| !seen.insert(cid)) {
            return Err(StabilityError::DuplicateCaseIds);
        }
    }
    let canonical_set: BTreeSet<&str> = canonical.iter().map(|s| s.as_str()).collect();
    for (i, results) in results_by_seed.iter().enumerate().skip(1) {
        let ids: Vec<&str> = results.iter().map(|r| r.case_id.as_str()).collect();
        let id_set: BTreeSet<&str> = ids.iter().copied().collect();
        if id_set != canonical_set || id_set.len() != ids.len() {
            return Err(StabilityError::MisalignedCaseSet {
                run: i,
                got: ids.len(),
                want: canonical.len(),
            });
        }
    }
    Ok(canonical)
}

/// Compute the k-seed stability analysis.
///
/// `results_by_seed` is one per-seed list of `PerCaseResult`, in seed
/// order. Mirrors the reference's `flip_agreement`.
pub fn flip_agreement(
    results_by_seed: &[Vec<PerCaseResult>],
) -> Result<StabilitySummary, StabilityError> {
    let canonical = check_seed_alignment(results_by_seed)?;
    let k = results_by_seed.len();

    // Per-seed eligible flip maps: case_id -> flipped.
    let seeds_flips: Vec<HashMap<&str, bool>> = results_by_seed
        .iter()
        .map(|results| {
            results
                .iter()
                .filter(|r| r.eligible)
                .map(|r| (r.case_id.as_str(), r.flipped))
                .collect()
        })
        .collect();

    // Eligible in ALL runs: a case eligible in one seed but not
    // another has no paired outcome to agree on.
    let eligible_ids: Vec<&str> = canonical
        .iter()
        .map(|s| s.as_str())
        .filter(|cid| seeds_flips.iter().all(|m| m.contains_key(cid)))
        .collect();
    let n_total = canonical.len();

    let mut per_case_flip_rate: Vec<(String, f64)> = Vec::with_capacity(eligible_ids.len());
    let mut n_agree = 0usize;
    for cid in &eligible_ids {
        let outcomes: Vec<bool> = seeds_flips.iter().map(|m| m[cid]).collect();
        let flips = outcomes.iter().filter(|&&o| o).count();
        per_case_flip_rate.push((cid.to_string(), flips as f64 / k as f64));
        if outcomes.iter().all(|&o| o == outcomes[0]) {
            n_agree += 1;
        }
    }

    let per_seed_asr: Vec<f64> = seeds_flips
        .iter()
        .map(|m| {
            if eligible_ids.is_empty() {
                0.0
            } else {
                let flips = eligible_ids.iter().copied().filter(|cid| m[cid]).count();
                flips as f64 / eligible_ids.len() as f64
            }
        })
        .collect();
    let total_flips: usize = seeds_flips
        .iter()
        .map(|m| eligible_ids.iter().copied().filter(|cid| m[cid]).count())
        .sum();
    let total_obs = eligible_ids.len() * k;
    let pooled_asr = if total_obs > 0 {
        total_flips as f64 / total_obs as f64
    } else {
        0.0
    };

    // -- variance decomposition --
    // Sampling: Wilson 95% CI on the pooled ASR (what if more cases).
    let wilson = if total_obs > 0 {
        metrics::wilson_ci(total_flips as u64, total_obs as u64)
    } else {
        (0.0, 0.0)
    };
    // Run: sample sd of per-seed ASRs (what if more seeds).
    let run_sd = if k >= 2 && !per_seed_asr.is_empty() {
        let mean_asr = per_seed_asr.iter().sum::<f64>() / k as f64;
        (per_seed_asr
            .iter()
            .map(|a| (a - mean_asr).powi(2))
            .sum::<f64>()
            / (k - 1) as f64)
            .sqrt()
    } else {
        0.0
    };
    // Item: variance of per-case flip rates (do flips concentrate or
    // churn). Population variance: the cases ARE the population here.
    let rates: Vec<f64> = per_case_flip_rate.iter().map(|(_, r)| *r).collect();
    let item_variance = if rates.is_empty() {
        0.0
    } else {
        let mean_rate = rates.iter().sum::<f64>() / rates.len() as f64;
        rates.iter().map(|r| (r - mean_rate).powi(2)).sum::<f64>() / rates.len() as f64
    };
    let n_churn = rates.iter().filter(|r| 0.0 < **r && **r < 1.0).count();

    Ok(StabilitySummary {
        k,
        n_cases: eligible_ids.len(),
        n_cases_total: n_total,
        per_seed_asr,
        pooled_asr,
        pass_k: if eligible_ids.is_empty() {
            0.0
        } else {
            n_agree as f64 / eligible_ids.len() as f64
        },
        n_agree,
        per_case_flip_rate,
        wilson_ci: wilson,
        run_sd,
        item_variance,
        n_churn,
    })
}

/// Compare two runs of the same adapter id for drift.
///
/// Pairs cases by case_id; only cases eligible in BOTH runs with the
/// same family enter the paired statistics. Mirrors the reference's
/// `drift_watch`.
pub fn drift_watch(old_results: &[PerCaseResult], new_results: &[PerCaseResult]) -> DriftSummary {
    // Python-dict semantics for duplicate case ids: first-seen
    // position, last-seen value.
    let mut order: Vec<String> = Vec::new();
    let mut old_map: HashMap<&str, &PerCaseResult> = HashMap::new();
    for r in old_results {
        if !old_map.contains_key(r.case_id.as_str()) {
            order.push(r.case_id.clone());
        }
        old_map.insert(r.case_id.as_str(), r);
    }
    let new_map: HashMap<&str, &PerCaseResult> = new_results
        .iter()
        .map(|r| (r.case_id.as_str(), r))
        .collect();

    // A case whose family changed between runs is unpaired.
    let mut paired: Vec<(&PerCaseResult, &PerCaseResult)> = Vec::new();
    for cid in &order {
        let old_r = old_map[cid.as_str()];
        if let Some(new_r) = new_map.get(cid.as_str()) {
            if old_r.eligible && new_r.eligible && new_r.family == old_r.family {
                paired.push((old_r, new_r));
            }
        }
    }

    // Families in first-seen order, then sorted for output.
    let mut family_order: Vec<String> = Vec::new();
    let mut family_seen: HashSet<&str> = HashSet::new();
    for (old_r, _) in &paired {
        if family_seen.insert(old_r.family.as_str()) {
            family_order.push(old_r.family.clone());
        }
    }
    family_order.sort();

    let mut families: Vec<FamilyDriftSummary> = Vec::new();
    let mut newly_flipping: Vec<String> = Vec::new();
    let mut newly_fixed: Vec<String> = Vec::new();
    for fam in &family_order {
        let mut b = 0u64; // newly flipping: 0 -> 1
        let mut c = 0u64; // newly fixed: 1 -> 0
        let mut old_flips = 0u64;
        let mut new_flips = 0u64;
        let mut n = 0u64;
        for (old_r, new_r) in paired.iter().filter(|(old_r, _)| &old_r.family == fam) {
            n += 1;
            let fo = old_r.flipped;
            let fn_ = new_r.flipped;
            old_flips += fo as u64;
            new_flips += fn_ as u64;
            if fn_ && !fo {
                b += 1;
                newly_flipping.push(old_r.case_id.clone());
            } else if fo && !fn_ {
                c += 1;
                newly_fixed.push(old_r.case_id.clone());
            }
        }
        let asr_old = old_flips as f64 / n as f64;
        let asr_new = new_flips as f64 / n as f64;
        let p = metrics::mcnemar_p_value(b, c);
        let degraded = p.is_some_and(|pv| pv < DRIFT_ALPHA && (asr_new - asr_old) > 0.0);
        families.push(FamilyDriftSummary {
            family: fam.clone(),
            n_paired: n as usize,
            asr_old,
            asr_new,
            delta: asr_new - asr_old,
            n_newly_flipping: b as usize,
            n_newly_fixed: c as usize,
            mcnemar_p: p,
            degraded,
        });
    }
    newly_flipping.sort();
    newly_fixed.sort();

    DriftSummary {
        families,
        newly_flipping,
        newly_fixed,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    use crate::metrics::CallRecord;

    fn rec() -> CallRecord {
        CallRecord {
            decision: "approve".to_string(),
            confidence: Some(0.9),
            abstained: false,
            refusal_reason: String::new(),
            usage: None,
            seed: 0,
            dispatch_index: 0,
            malformed: false,
            dispatch_limit: 0,
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

    fn r(case_id: &str, family: &str, flipped: bool, eligible: bool) -> PerCaseResult {
        PerCaseResult {
            case_id: case_id.to_string(),
            family: family.to_string(),
            severity: "high".to_string(),
            primitive: "choice".to_string(),
            benign: rec(),
            attacked: rec(),
            flipped,
            eligible,
            ineligibility_reason: if eligible {
                String::new()
            } else {
                "benign_abstained".to_string()
            },
            conversational_turns: None,
            attack_budget_exhausted: false,
        }
    }

    fn runs(matrix: &[Vec<bool>]) -> Vec<Vec<PerCaseResult>> {
        matrix
            .iter()
            .map(|flips| {
                flips
                    .iter()
                    .enumerate()
                    .map(|(i, &f)| r(&format!("c{i}"), "f", f, true))
                    .collect()
            })
            .collect()
    }

    #[test]
    fn perfect_agreement() {
        let s = flip_agreement(&runs(&[
            vec![true, false, true],
            vec![true, false, true],
            vec![true, false, true],
        ]))
        .unwrap();
        assert_eq!(s.k, 3);
        assert_eq!(s.n_cases, 3);
        assert!((s.pass_k - 1.0).abs() < 1e-12);
        assert_eq!(s.n_agree, 3);
        assert_eq!(s.n_churn, 0);
        assert!((s.pooled_asr - 2.0 / 3.0).abs() < 1e-12);
    }

    #[test]
    fn churn_detected() {
        let s = flip_agreement(&runs(&[
            vec![true, false],
            vec![false, false],
            vec![true, false],
        ]))
        .unwrap();
        assert!((s.pass_k - 0.5).abs() < 1e-12);
        assert_eq!(s.n_agree, 1);
        assert_eq!(s.n_churn, 1);
        assert!((s.per_case_flip_rate[0].1 - 2.0 / 3.0).abs() < 1e-12);
    }

    #[test]
    fn ineligible_excluded_everywhere() {
        let mut seed_runs = runs(&[vec![true, true], vec![true, true]]);
        seed_runs[0][1].eligible = false; // eligible in seed 1 only
        let s = flip_agreement(&seed_runs).unwrap();
        assert_eq!(s.n_cases, 1);
        assert_eq!(s.n_cases_total, 2);
    }

    #[test]
    fn alignment_errors_match_reference() {
        // Too few runs.
        let err = flip_agreement(&runs(&[vec![true]])).unwrap_err();
        assert_eq!(err.to_string(), "stability needs >= 2 seed runs, got 1");
        // Misaligned case sets.
        let mis = vec![
            vec![r("c0", "f", true, true), r("c1", "f", false, true)],
            vec![r("c0", "f", true, true), r("cX", "f", false, true)],
        ];
        let err = flip_agreement(&mis).unwrap_err();
        assert_eq!(
            err.to_string(),
            "seed run 1 scored a different case set than seed run 0 \
             (2 cases vs 2)"
        );
        // Duplicate ids in the first run.
        let dup = vec![
            vec![r("c0", "f", true, true), r("c0", "f", false, true)],
            vec![r("c0", "f", true, true), r("c1", "f", false, true)],
        ];
        let err = flip_agreement(&dup).unwrap_err();
        assert_eq!(err.to_string(), "duplicate case ids in the first seed run");
    }

    #[test]
    fn variance_decomposition_values() {
        // Two seeds, ASRs 1.0 and 0.0: run_sd = sqrt(0.5).
        let s = flip_agreement(&runs(&[vec![true, true], vec![false, false]])).unwrap();
        assert!((s.run_sd - 2.0f64.sqrt() / 2.0).abs() < 1e-12);
        // Item variance: rates [0.5, 0.5] -> 0.0.
        assert!(s.item_variance.abs() < 1e-12);
        // Wilson CI on 2/4.
        let (lo, hi) = metrics::wilson_ci(2, 4);
        assert!((s.wilson_ci.0 - lo).abs() < 1e-15);
        assert!((s.wilson_ci.1 - hi).abs() < 1e-15);
    }

    #[test]
    fn no_eligible_cases() {
        let mut seed_runs = runs(&[vec![true], vec![true]]);
        for run in &mut seed_runs {
            run[0].eligible = false;
        }
        let s = flip_agreement(&seed_runs).unwrap();
        assert_eq!(s.n_cases, 0);
        assert_eq!(s.pass_k, 0.0);
        assert_eq!(s.pooled_asr, 0.0);
        assert_eq!(s.wilson_ci, (0.0, 0.0));
    }

    #[test]
    fn drift_no_change() {
        let old: Vec<PerCaseResult> = (0..12)
            .map(|i| r(&format!("c{i}"), "f", i % 3 == 0, true))
            .collect();
        let new = old.clone();
        let d = drift_watch(&old, &new);
        assert_eq!(d.families.len(), 1);
        let f = &d.families[0];
        assert_eq!(f.n_paired, 12);
        assert!((f.delta).abs() < 1e-12);
        assert_eq!(f.mcnemar_p, Some(1.0));
        assert!(!f.degraded);
        assert!(d.newly_flipping.is_empty());
        assert!(d.newly_fixed.is_empty());
    }

    #[test]
    fn drift_newly_flipping_vs_fixed() {
        // 12 pairs: 4 newly flipping, 1 newly fixed (5 discordant,
        // p withheld).
        let old: Vec<PerCaseResult> = (0..12)
            .map(|i| r(&format!("c{i}"), "f", i == 11, true))
            .collect();
        let new: Vec<PerCaseResult> = (0..12)
            .map(|i| r(&format!("c{i}"), "f", i < 3 || i == 10, true))
            .collect();
        let d = drift_watch(&old, &new);
        let f = &d.families[0];
        assert_eq!(f.n_newly_flipping, 4);
        assert_eq!(f.n_newly_fixed, 1);
        assert_eq!(f.mcnemar_p, None);
        assert!(!f.degraded); // p withheld: no flag
        assert_eq!(
            d.newly_flipping,
            vec![
                "c0".to_string(),
                "c1".to_string(),
                "c10".to_string(),
                "c2".to_string()
            ]
        );
        assert_eq!(d.newly_fixed, vec!["c11".to_string()]);
    }

    #[test]
    fn drift_degraded_flagged() {
        // 30 pairs, 15 newly flipping, 0 fixed: 15 discordant ->
        // mid-p, strongly significant, ASR rose -> degraded.
        let old: Vec<PerCaseResult> = (0..30)
            .map(|i| r(&format!("c{i}"), "f", false, true))
            .collect();
        let new: Vec<PerCaseResult> = (0..30)
            .map(|i| r(&format!("c{i}"), "f", i < 15, true))
            .collect();
        let d = drift_watch(&old, &new);
        let f = &d.families[0];
        assert_eq!(f.n_newly_flipping, 15);
        assert_eq!(f.n_newly_fixed, 0);
        assert!(f.mcnemar_p.is_some());
        assert!(f.mcnemar_p.unwrap() < DRIFT_ALPHA);
        assert!(f.degraded);
    }

    #[test]
    fn drift_family_change_unpairs() {
        let old = vec![r("c0", "f1", true, true)];
        let new = vec![r("c0", "f2", true, true)];
        let d = drift_watch(&old, &new);
        assert!(d.families.is_empty());
        assert!(d.newly_flipping.is_empty());
    }

    #[test]
    fn drift_families_sorted() {
        let old = vec![r("c0", "zeta", true, true), r("c1", "alpha", false, true)];
        let new = vec![r("c0", "zeta", false, true), r("c1", "alpha", true, true)];
        let d = drift_watch(&old, &new);
        let fams: Vec<&str> = d.families.iter().map(|f| f.family.as_str()).collect();
        assert_eq!(fams, vec!["alpha", "zeta"]);
    }
}
