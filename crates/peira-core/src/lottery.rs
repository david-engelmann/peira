//! Leave-one-family-out ranking stability ("lottery index").
//!
//! This module ports `python/peira/lottery.py` (R-09): for a set of runs
//! (one row per adapter/dataset on a leaderboard) it recomputes the
//! ranking once per family with that family removed, and measures how
//! much the ranking moves. The headline number is the **lottery index**:
//! the mean Kendall's tau rank correlation between the full ranking and
//! each leave-one-out ranking.
//!
//! Parity-critical details (see `docs/rust-max-queue.md`):
//! - `_round4` banker's rounding is replicated as
//!   `format!("{:.4}", v).parse::<f64>()` — Rust has no
//!   round-to-N-decimals. The `{:.4}` formatter rounds the exact binary
//!   value half-to-even, and parsing the decimal string back yields the
//!   float nearest the rounded decimal, exactly what Python's `round`
//!   returns.
//! - The verdict bands in [`lottery_analysis`] run on the ROUNDED index:
//!   round first, then band.
//! - `lottery_index` is the mean of the RAW taus summed with Python's
//!   compensated builtin `sum()` (Neumaier) — replicated in
//!   [`neumaier_sum`], not a naive accumulation.
//! - `most_influential_family` replicates `min` with key `(tau, family)`
//!   on the ROUNDED tau, with strict less-than so the first family wins
//!   ties, exactly like Python's `min`.
//! - [`rank_runs`] sorts by the RAW asr from [`asr_conditional`](crate::metrics::asr_conditional),
//!   never re-rounded before the sort.
//! - `dropped_runs` is a sorted set difference; `per_family` follows the
//!   input `families` order (never a `HashMap`).

use crate::metrics::{asr_conditional, check_eligibility, PerCaseResult};
use std::collections::{HashMap, HashSet};

/// One run's position inputs: id, headline ASR, eligibility.
///
/// Mirrors `python/peira/lottery.py::RankedRun`.
#[derive(Debug, Clone, PartialEq)]
pub struct RankedRun {
    pub run_id: String,
    /// Conditional ASR; None when the run is ineligible.
    pub asr: Option<f64>,
    pub eligible: bool,
    pub reasons: Vec<String>,
}

/// Per-family leave-one-out detail.
///
/// Mirrors one entry of the `per_family` dict in
/// `python/peira/lottery.py::lottery_analysis`. `tau` and
/// `swap_fraction` are [`round4`]-rounded; `max_rank_displacement` is
/// None when the full and reduced rankings share no run.
#[derive(Debug, Clone, PartialEq)]
pub struct FamilyDetail {
    pub tau: Option<f64>,
    pub swap_fraction: Option<f64>,
    pub n_common: usize,
    pub max_rank_displacement: Option<usize>,
    pub ranking: Vec<String>,
    pub dropped_runs: Vec<String>,
}

/// Leave-one-family-out stability report.
///
/// Mirrors the dict returned by
/// `python/peira/lottery.py::lottery_analysis`. `per_family` holds
/// `(family, detail)` pairs in the input `families` order.
#[derive(Debug, Clone, PartialEq)]
pub struct LotteryAnalysis {
    pub families: Vec<String>,
    pub n_runs: usize,
    pub n_ranked: usize,
    pub full_ranking: Vec<String>,
    pub full_ranking_detail: Vec<RankedRun>,
    /// Mean of the raw per-family taus ([`round4`]-rounded for display).
    pub lottery_index: Option<f64>,
    /// Banded on the ROUNDED index, never the raw one.
    pub verdict: String,
    /// Minimum raw tau ([`round4`]-rounded for display).
    pub min_tau: Option<f64>,
    pub most_influential_family: Option<String>,
    pub per_family: Vec<(String, FamilyDetail)>,
}

/// Banker's rounding to 4 decimals, mirroring Python's `round(v, 4)`.
///
/// Rust has no round-to-N-decimals. The `{:.4}` formatter rounds the
/// exact binary value half-to-even, and parsing the resulting decimal
/// string yields the float nearest the rounded decimal — the same value
/// Python's `round` returns. Verified against Python on a boundary
/// battery including negatives and x.xxx5 values (see tests below).
pub fn round4(v: f64) -> f64 {
    format!("{v:.4}")
        .parse::<f64>()
        .expect("formatting an f64 to 4 decimals always parses back")
}

/// Neumaier compensated summation, mirroring CPython's builtin `sum()`
/// on floats (verified bit-identical to `sum()` on thousands of random
/// trials plus adversarial magnitudes; note this is NOT `math.fsum`,
/// which is correctly rounded and can differ by ~1 ulp). CPython's
/// `sum()` is Neumaier only on 3.12+; on 3.10/3.11 it is naive
/// left-to-right, so adversarial inputs straddling a `round4` boundary
/// can diverge by 1 ulp there. The Rust/Python parity guarantee is
/// therefore bit-exact on CPython 3.12+ (CI pins 3.12).
fn neumaier_sum(xs: &[f64]) -> f64 {
    let mut sum = 0.0f64;
    let mut comp = 0.0f64;
    for &x in xs {
        let t = sum + x;
        if sum.abs() >= x.abs() {
            comp += (sum - t) + x;
        } else {
            comp += (x - t) + sum;
        }
        sum = t;
    }
    sum + comp
}

/// Rank runs by conditional ASR (ascending) over `families`.
///
/// `results_by_run` holds `(run_id, results)` in mapping order. Only
/// cases whose family is in `families` count; eligibility is checked
/// with `required_families = families` so the per-family coverage gate
/// applies to exactly the families ranked on. The returned list is
/// ordered best-first; ties on the RAW asr break by run_id so the order
/// is deterministic. Ineligible runs are included with
/// `eligible = false` and `asr = None` (they never take a rank),
/// ordered by run_id after the eligible runs.
///
/// Assumes `families` is non-empty and run ids are non-empty (the PyO3
/// boundary validates both, mirroring the Python `ValueError`s).
pub fn rank_runs(
    results_by_run: &[(String, Vec<PerCaseResult>)],
    families: &[String],
) -> Vec<RankedRun> {
    let fam_set: HashSet<&str> = families.iter().map(String::as_str).collect();
    let mut eligible_runs: Vec<RankedRun> = Vec::new();
    let mut ineligible: Vec<RankedRun> = Vec::new();
    for (run_id, results) in results_by_run {
        let filtered: Vec<PerCaseResult> = results
            .iter()
            .filter(|r| fam_set.contains(r.family.as_str()))
            .cloned()
            .collect();
        let elig = check_eligibility(&filtered, Some(families));
        if elig.eligible {
            let (asr, _) = asr_conditional(&filtered);
            eligible_runs.push(RankedRun {
                run_id: run_id.clone(),
                asr: Some(asr),
                eligible: true,
                reasons: Vec::new(),
            });
        } else {
            ineligible.push(RankedRun {
                run_id: run_id.clone(),
                asr: None,
                eligible: false,
                reasons: elig.reasons,
            });
        }
    }
    // Sort on the RAW binary double from asr_conditional — never
    // re-rounded before the sort. Run ids are unique (mapping keys), so
    // (asr, run_id) is a total order and stability is irrelevant.
    eligible_runs.sort_by(|a, b| {
        a.asr
            .partial_cmp(&b.asr)
            .expect("eligible runs always carry an asr")
            .then_with(|| a.run_id.cmp(&b.run_id))
    });
    // Python's sorted() on str is codepoint order, which is UTF-8 byte
    // order — identical to Rust's String Ord.
    ineligible.sort_by(|a, b| a.run_id.cmp(&b.run_id));
    eligible_runs.extend(ineligible);
    eligible_runs
}

/// Position map for a best-first run-id list.
fn ranking_positions(order: &[String]) -> HashMap<&str, usize> {
    order
        .iter()
        .enumerate()
        .map(|(i, r)| (r.as_str(), i))
        .collect()
}

/// Kendall's tau between two rankings (best-first run-id lists).
///
/// Computed over the intersection of the two rankings: runs ranked in
/// only one of the two do not contribute pairs. Each input list holds
/// every run id at most once, so there are no ties to adjust for.
/// Returns None when fewer than two runs are ranked in both (no pair
/// exists to compare).
pub fn kendall_tau(rank_a: &[String], rank_b: &[String]) -> Option<f64> {
    let set_b: HashSet<&str> = rank_b.iter().map(String::as_str).collect();
    // Intersection in rank_a order; map to rank_b positions and count
    // inversions: a pair (i<j) is concordant iff pos_b[a_i] < pos_b[a_j].
    let common_a: Vec<&str> = rank_a
        .iter()
        .map(String::as_str)
        .filter(|r| set_b.contains(r))
        .collect();
    if common_a.len() < 2 {
        return None;
    }
    let pos_b = ranking_positions(rank_b);
    let b_positions: Vec<usize> = common_a.iter().map(|r| pos_b[*r]).collect();
    let n = b_positions.len();
    let mut concordant = 0u64;
    let mut discordant = 0u64;
    for i in 0..n {
        for j in (i + 1)..n {
            if b_positions[i] < b_positions[j] {
                concordant += 1;
            } else if b_positions[i] > b_positions[j] {
                discordant += 1;
            }
        }
    }
    let total = concordant + discordant;
    if total == 0 {
        // Unreachable without ties (every pair is concordant or
        // discordant), but mirror the reference's guard.
        return None;
    }
    // Single division of small integers: exact on both backends.
    Some((concordant as f64 - discordant as f64) / total as f64)
}

/// Fraction of common pairs whose relative order differs.
///
/// A more literal "how much did the ranking move" companion to tau:
/// 0.0 means identical order, 1.0 means fully reversed. None when
/// fewer than two runs are ranked in both.
pub fn pairwise_swap_fraction(rank_a: &[String], rank_b: &[String]) -> Option<f64> {
    let set_b: HashSet<&str> = rank_b.iter().map(String::as_str).collect();
    let common_a: Vec<&str> = rank_a
        .iter()
        .map(String::as_str)
        .filter(|r| set_b.contains(r))
        .collect();
    if common_a.len() < 2 {
        return None;
    }
    let pos_b = ranking_positions(rank_b);
    let b_positions: Vec<usize> = common_a.iter().map(|r| pos_b[*r]).collect();
    let n = b_positions.len();
    let mut discordant = 0u64;
    let mut total = 0u64;
    for i in 0..n {
        for j in (i + 1)..n {
            total += 1;
            if b_positions[i] > b_positions[j] {
                discordant += 1;
            }
        }
    }
    // n >= 2, so total > 0; the single division is exact.
    Some(discordant as f64 / total as f64)
}

/// One-word verdict for a lottery index.
///
/// Bands: >= 0.9 "stable", >= 0.7 "mostly stable", below "fragile",
/// None "undefined". Callers band the ROUNDED index (see
/// [`lottery_analysis`]); this function bands whatever it is given.
pub fn stability_verdict(lottery_index: Option<f64>) -> String {
    match lottery_index {
        None => "undefined".to_string(),
        Some(v) if v >= 0.9 => "stable".to_string(),
        Some(v) if v >= 0.7 => "mostly stable".to_string(),
        Some(_) => "fragile".to_string(),
    }
}

/// Leave-one-family-out ranking stability over `families`.
///
/// Computes the full ranking, then one ranking per family with that
/// family removed (eligibility re-gated on the remaining families),
/// and correlates each reduced ranking against the full ranking with
/// Kendall's tau.
///
/// Returns Err with the reference's exact message when `families` is
/// empty ("lottery_analysis: families must not be empty"), or when a
/// leave-one-out step would rank on no families at all (the
/// single-family case: "rank_runs: families must not be empty").
pub fn lottery_analysis(
    results_by_run: &[(String, Vec<PerCaseResult>)],
    families: &[String],
) -> Result<LotteryAnalysis, String> {
    if families.is_empty() {
        return Err("lottery_analysis: families must not be empty".to_string());
    }

    let full = rank_runs(results_by_run, families);
    let full_order: Vec<String> = full
        .iter()
        .filter(|r| r.eligible)
        .map(|r| r.run_id.clone())
        .collect();

    let mut per_family: Vec<(String, FamilyDetail)> = Vec::with_capacity(families.len());
    let mut taus: Vec<f64> = Vec::with_capacity(families.len());
    for fam in families {
        let reduced_fams: Vec<String> = families.iter().filter(|f| *f != fam).cloned().collect();
        if reduced_fams.is_empty() {
            return Err("rank_runs: families must not be empty".to_string());
        }
        let reduced = rank_runs(results_by_run, &reduced_fams);
        let reduced_order: Vec<String> = reduced
            .iter()
            .filter(|r| r.eligible)
            .map(|r| r.run_id.clone())
            .collect();
        let tau = kendall_tau(&full_order, &reduced_order);
        let swap = pairwise_swap_fraction(&full_order, &reduced_order);
        let pos_full = ranking_positions(&full_order);
        let pos_red = ranking_positions(&reduced_order);
        let common: Vec<&str> = full_order
            .iter()
            .map(String::as_str)
            .filter(|r| pos_red.contains_key(r))
            .collect();
        let max_rank_displacement = common
            .iter()
            .map(|r| pos_full[*r].abs_diff(pos_red[*r]))
            .max();
        if let Some(t) = tau {
            taus.push(t);
        }
        let full_set: HashSet<&str> = full_order.iter().map(String::as_str).collect();
        let mut dropped_runs: Vec<String> = full_set
            .iter()
            .filter(|r| !pos_red.contains_key(**r))
            .map(|r| r.to_string())
            .collect();
        dropped_runs.sort();
        per_family.push((
            fam.clone(),
            FamilyDetail {
                tau: tau.map(round4),
                swap_fraction: swap.map(round4),
                n_common: common.len(),
                max_rank_displacement,
                ranking: reduced_order,
                dropped_runs,
            },
        ));
    }

    // Mean of the RAW taus (compensated sum, like Python's sum()), then
    // rounded for display; the verdict bands the ROUNDED index.
    let lottery_index_raw: Option<f64> = if taus.is_empty() {
        None
    } else {
        Some(neumaier_sum(&taus) / taus.len() as f64)
    };
    // Strict fold: mirrors Python's min (first occurrence wins ties).
    let mut min_tau_raw: Option<f64> = None;
    for &t in &taus {
        min_tau_raw = Some(match min_tau_raw {
            None => t,
            Some(cur) => {
                if t < cur {
                    t
                } else {
                    cur
                }
            }
        });
    }
    // The family whose removal moves the ranking most: min over the
    // input-order families with key (ROUNDED tau, family name), strict
    // less-than so the first family wins ties — exactly Python's min().
    let most_influential_family = select_most_influential(&per_family);

    Ok(LotteryAnalysis {
        families: families.to_vec(),
        n_runs: results_by_run.len(),
        n_ranked: full_order.len(),
        full_ranking: full_order,
        full_ranking_detail: full,
        lottery_index: lottery_index_raw.map(round4),
        verdict: stability_verdict(lottery_index_raw.map(round4)),
        min_tau: min_tau_raw.map(round4),
        most_influential_family,
        per_family,
    })
}

/// Select the most influential family from per-family details.
///
/// Min over the input-order families with key (ROUNDED tau, family
/// name); strict less-than so the first family wins ties — exactly
/// Python's `min(..., key=lambda f: (per_family[f]["tau"], f))`.
/// Families with undefined tau are skipped. Returns None when every
/// tau is undefined (or `per_family` is empty).
fn select_most_influential(per_family: &[(String, FamilyDetail)]) -> Option<String> {
    let mut best: Option<(f64, &str)> = None;
    for (fam, detail) in per_family {
        if let Some(t) = detail.tau {
            let better = match best {
                None => true,
                Some((best_t, best_fam)) => t < best_t || (t == best_t && fam.as_str() < best_fam),
            };
            if better {
                best = Some((t, fam.as_str()));
            }
        }
    }
    best.map(|(_, fam)| fam.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::metrics::CallRecord;

    fn rec(decision: &str) -> CallRecord {
        CallRecord {
            decision: decision.to_string(),
            confidence: Some(0.9),
            abstained: false,
            refusal_reason: String::new(),
            usage: None,
            seed: 0,
            dispatch_index: 0,
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

    fn case(family: &str, case_id: &str, flipped: bool) -> PerCaseResult {
        PerCaseResult {
            case_id: case_id.to_string(),
            family: family.to_string(),
            severity: "high".to_string(),
            primitive: "choice".to_string(),
            benign: rec("approve"),
            attacked: rec(if flipped { "deny" } else { "approve" }),
            flipped,
            eligible: true,
            ineligibility_reason: String::new(),
            conversational_turns: None,
            attack_budget_exhausted: false,
        }
    }

    /// A run's results: `per_family` cases per family, the first
    /// `n_flip` of each family flipped. Benign accuracy is 1.0 and the
    /// malformed rate is 0, so eligibility rests on the case counts.
    fn make_run(specs: &[(&str, usize)], per_family: usize) -> Vec<PerCaseResult> {
        let mut out = Vec::new();
        for (fam, n_flip) in specs {
            for i in 0..per_family {
                out.push(case(fam, &format!("{fam}-{i}"), i < *n_flip));
            }
        }
        out
    }

    fn s(v: &str) -> String {
        v.to_string()
    }

    fn strs(vs: &[&str]) -> Vec<String> {
        vs.iter().map(|v| v.to_string()).collect()
    }

    // ------------------------------------------------------------------
    // round4: banker's rounding, verified against Python's round(v, 4).
    // ------------------------------------------------------------------

    #[test]
    fn round4_matches_python_on_boundary_battery() {
        // (input, expected) pairs computed with Python's round(v, 4).
        // Includes x.xxx5 boundaries where the binary value sits just
        // above or below the decimal halfway point, and negatives.
        let cases: &[(f64, f64)] = &[
            (2.675, 2.675),
            (2.665, 2.665),
            (-2.675, -2.675),
            (-2.665, -2.665),
            (1.23455, 1.2346),
            (1.23465, 1.2347),
            (-1.23455, -1.2346),
            (-1.23465, -1.2347),
            (0.89995, 0.9),
            (0.89994999, 0.8999),
            (-5e-05, -0.0001),
            (5e-05, 0.0001),
            (-5.1e-05, -0.0001),
            (5.1e-05, 0.0001),
            (0.12345, 0.1235),
            (0.12344, 0.1234),
            (0.12346, 0.1235),
            (-0.12345, -0.1235),
            (1.0, 1.0),
            (-1.0, -1.0),
            (0.0, 0.0),
            (1.23456789, 1.2346),
            (-1.23456789, -1.2346),
            // Half-even on the 4th decimal: 123.45675 sits just below
            // the halfway point in binary, 123.45685 just above.
            (123.45675, 123.4567),
            (123.45685, 123.4569),
            (0.5, 0.5),
            (2.5, 2.5),
            (3.5, 3.5),
            (1e20, 1e20),
            (1.5e-05, 0.0),
            (2.50005, 2.5),
            (2.50015, 2.5002),
            (-2.50005, -2.5),
            (0.12494, 0.1249),
            (1.0 / 3.0, 0.3333),
            (-1.0 / 3.0, -0.3333),
        ];
        for (input, expected) in cases {
            assert_eq!(
                round4(*input),
                *expected,
                "round4({input}) should be {expected}"
            );
        }
    }

    #[test]
    fn round4_preserves_negative_zero_sign_like_python() {
        // Python round(-1e-9, 4) is -0.0; the sign bit survives.
        let r = round4(-1e-9);
        assert_eq!(r, 0.0);
        assert!(r.is_sign_negative());
        let r2 = round4(1e-9);
        assert_eq!(r2, 0.0);
        assert!(r2.is_sign_positive());
    }

    #[test]
    fn round4_handles_non_finite_like_python() {
        assert_eq!(round4(f64::INFINITY), f64::INFINITY);
        assert_eq!(round4(f64::NEG_INFINITY), f64::NEG_INFINITY);
        assert!(round4(f64::NAN).is_nan());
    }

    // ------------------------------------------------------------------
    // neumaier_sum mirrors Python's compensated builtin sum().
    // ------------------------------------------------------------------

    #[test]
    fn neumaier_sum_matches_python_sum() {
        // Expected values computed with Python's sum().
        let cases: &[(&[f64], f64)] = &[
            (&[1e16, 1.0, -1e16], 1.0),
            (&[1.0, 1e16, -1e16, 1.0], 2.0),
            (&[0.1; 10], 1.0),
            (&[1.0 / 3.0; 3], 1.0),
            (&[-1.0 / 3.0, 1.0 / 3.0], 0.0),
            (&[0.9, 0.9, 0.6999], 2.4999000000000002),
            (&[1.0, -1.0], 0.0),
            (&[], 0.0),
        ];
        for (xs, expected) in cases {
            assert_eq!(
                neumaier_sum(xs),
                *expected,
                "neumaier_sum({xs:?}) should be {expected}"
            );
        }
    }

    // ------------------------------------------------------------------
    // kendall_tau
    // ------------------------------------------------------------------

    #[test]
    fn kendall_tau_identical_is_one() {
        assert_eq!(
            kendall_tau(&strs(&["a", "b", "c"]), &strs(&["a", "b", "c"])),
            Some(1.0)
        );
    }

    #[test]
    fn kendall_tau_reversed_is_minus_one() {
        assert_eq!(
            kendall_tau(&strs(&["a", "b", "c"]), &strs(&["c", "b", "a"])),
            Some(-1.0)
        );
    }

    #[test]
    fn kendall_tau_single_swap() {
        // One discordant pair out of three: (2-1)/3.
        let tau = kendall_tau(&strs(&["a", "b", "c"]), &strs(&["a", "c", "b"])).unwrap();
        assert!((tau - 1.0 / 3.0).abs() < 1e-15);
    }

    #[test]
    fn kendall_tau_partial_overlap() {
        // Only a,b common and in the same order.
        assert_eq!(
            kendall_tau(&strs(&["a", "b", "c"]), &strs(&["a", "b"])),
            Some(1.0)
        );
    }

    #[test]
    fn kendall_tau_insufficient_overlap_is_none() {
        assert_eq!(kendall_tau(&strs(&["a"]), &strs(&["a"])), None);
        assert_eq!(kendall_tau(&strs(&["a", "b"]), &strs(&["c", "d"])), None);
        assert_eq!(kendall_tau(&[], &[]), None);
    }

    #[test]
    fn kendall_tau_two_items() {
        assert_eq!(
            kendall_tau(&strs(&["a", "b"]), &strs(&["b", "a"])),
            Some(-1.0)
        );
        assert_eq!(
            kendall_tau(&strs(&["a", "b"]), &strs(&["a", "b"])),
            Some(1.0)
        );
    }

    #[test]
    fn kendall_tau_ignores_ranking_only_runs() {
        // "x" is only in rank_a: contributes no pairs.
        assert_eq!(
            kendall_tau(&strs(&["x", "a", "b"]), &strs(&["a", "b"])),
            Some(1.0)
        );
    }

    // ------------------------------------------------------------------
    // pairwise_swap_fraction
    // ------------------------------------------------------------------

    #[test]
    fn swap_fraction_identical_is_zero() {
        assert_eq!(
            pairwise_swap_fraction(&strs(&["a", "b", "c"]), &strs(&["a", "b", "c"])),
            Some(0.0)
        );
    }

    #[test]
    fn swap_fraction_reversed_is_one() {
        assert_eq!(
            pairwise_swap_fraction(&strs(&["a", "b", "c"]), &strs(&["c", "b", "a"])),
            Some(1.0)
        );
    }

    #[test]
    fn swap_fraction_single_swap() {
        let f = pairwise_swap_fraction(&strs(&["a", "b", "c"]), &strs(&["a", "c", "b"])).unwrap();
        assert!((f - 1.0 / 3.0).abs() < 1e-15);
    }

    #[test]
    fn swap_fraction_insufficient_overlap_is_none() {
        assert_eq!(pairwise_swap_fraction(&strs(&["a"]), &strs(&["a"])), None);
    }

    // ------------------------------------------------------------------
    // stability_verdict
    // ------------------------------------------------------------------

    #[test]
    fn verdict_bands() {
        assert_eq!(stability_verdict(Some(1.0)), "stable");
        assert_eq!(stability_verdict(Some(0.9)), "stable");
        assert_eq!(stability_verdict(Some(0.8999)), "mostly stable");
        assert_eq!(stability_verdict(Some(0.7)), "mostly stable");
        assert_eq!(stability_verdict(Some(0.6999)), "fragile");
        assert_eq!(stability_verdict(Some(-1.0)), "fragile");
        assert_eq!(stability_verdict(None), "undefined");
    }

    #[test]
    fn verdict_bands_the_rounded_index() {
        // 0.89996 rounds to 0.9: "stable" on the rounded index, even
        // though the raw value sits below the 0.9 band.
        assert_eq!(stability_verdict(Some(round4(0.89996))), "stable");
        assert_eq!(stability_verdict(Some(0.89996)), "mostly stable");
    }

    // ------------------------------------------------------------------
    // rank_runs
    // ------------------------------------------------------------------

    fn three_runs() -> Vec<(String, Vec<PerCaseResult>)> {
        vec![
            (s("run-high"), make_run(&[("f1", 160), ("f2", 160)], 200)),
            (s("run-low"), make_run(&[("f1", 20), ("f2", 20)], 200)),
            (s("run-mid"), make_run(&[("f1", 100), ("f2", 100)], 200)),
        ]
    }

    #[test]
    fn rank_runs_orders_by_asr_ascending() {
        let ranked = rank_runs(&three_runs(), &strs(&["f1", "f2"]));
        let ids: Vec<&str> = ranked.iter().map(|r| r.run_id.as_str()).collect();
        assert_eq!(ids, vec!["run-low", "run-mid", "run-high"]);
        assert!(ranked.iter().all(|r| r.eligible));
        assert!((ranked[0].asr.unwrap() - 0.1).abs() < 1e-12);
        assert!(ranked.iter().all(|r| r.reasons.is_empty()));
    }

    #[test]
    fn rank_runs_ties_break_by_run_id() {
        let runs = vec![
            (s("b-run"), make_run(&[("f1", 60), ("f2", 60)], 200)),
            (s("a-run"), make_run(&[("f1", 60), ("f2", 60)], 200)),
        ];
        let ranked = rank_runs(&runs, &strs(&["f1", "f2"]));
        let ids: Vec<&str> = ranked.iter().map(|r| r.run_id.as_str()).collect();
        assert_eq!(ids, vec!["a-run", "b-run"]);
    }

    #[test]
    fn rank_runs_sorts_by_raw_asr_not_rounded() {
        // Both asrs round to 0.1249, but the raw values differ:
        // 12490/100000 = 0.1249 < 12494/100000 = 0.12494. A sort on
        // rounded asr would tie and fall back to run_id ("a-run"
        // first); the raw sort puts "b-run" first.
        assert_eq!(round4(12490.0 / 100000.0), round4(12494.0 / 100000.0));
        let runs = vec![
            (s("a-run"), make_run(&[("f1", 12494)], 100000)),
            (s("b-run"), make_run(&[("f1", 12490)], 100000)),
        ];
        let ranked = rank_runs(&runs, &strs(&["f1"]));
        let ids: Vec<&str> = ranked.iter().map(|r| r.run_id.as_str()).collect();
        assert_eq!(ids, vec!["b-run", "a-run"]);
    }

    #[test]
    fn rank_runs_filters_to_given_families() {
        let runs = vec![(s("r"), make_run(&[("f1", 0), ("f2", 200)], 200))];
        let ranked = rank_runs(&runs, &strs(&["f1"]));
        assert!((ranked[0].asr.unwrap() - 0.0).abs() < 1e-12);
    }

    #[test]
    fn rank_runs_marks_ineligible_with_reasons() {
        // 10 eligible cases per family: fails the >= 20 per-family
        // gate and the >= 200 total gate.
        let runs = vec![(s("tiny"), make_run(&[("f1", 0), ("f2", 0)], 10))];
        let ranked = rank_runs(&runs, &strs(&["f1", "f2"]));
        assert!(!ranked[0].eligible);
        assert_eq!(ranked[0].asr, None);
        assert!(!ranked[0].reasons.is_empty());
    }

    #[test]
    fn rank_runs_orders_ineligible_by_run_id_after_eligible() {
        let mut runs = three_runs();
        runs.push((s("z-tiny"), make_run(&[("f1", 0)], 10)));
        runs.push((s("a-tiny"), make_run(&[("f1", 0)], 10)));
        let ranked = rank_runs(&runs, &strs(&["f1", "f2"]));
        let ids: Vec<&str> = ranked.iter().map(|r| r.run_id.as_str()).collect();
        assert_eq!(
            ids,
            vec!["run-low", "run-mid", "run-high", "a-tiny", "z-tiny"]
        );
    }

    #[test]
    fn rank_runs_orders_unicode_run_ids_by_byte_order() {
        // Codepoint order == UTF-8 byte order; assert it explicitly.
        let mk = |id: &str| (id.to_string(), make_run(&[("f1", 0)], 10));
        let runs = vec![mk("z"), mk("é"), mk("ä"), mk("a")];
        let ranked = rank_runs(&runs, &strs(&["f1", "f2"]));
        let ids: Vec<&str> = ranked.iter().map(|r| r.run_id.as_str()).collect();
        assert_eq!(ids, vec!["a", "z", "ä", "é"]);
    }

    // ------------------------------------------------------------------
    // lottery_analysis
    // ------------------------------------------------------------------

    #[test]
    fn analysis_stable_rankings_index_one() {
        // Every run has the same ASR in every family: removing any
        // family cannot move the ranking.
        let runs = vec![
            (s("a"), make_run(&[("f1", 20), ("f2", 20)], 200)),
            (s("b"), make_run(&[("f1", 100), ("f2", 100)], 200)),
            (s("c"), make_run(&[("f1", 180), ("f2", 180)], 200)),
        ];
        let out = lottery_analysis(&runs, &strs(&["f1", "f2"])).unwrap();
        assert_eq!(out.full_ranking, strs(&["a", "b", "c"]));
        assert_eq!(out.lottery_index, Some(1.0));
        assert_eq!(out.verdict, "stable");
        assert_eq!(out.min_tau, Some(1.0));
        assert_eq!(out.n_runs, 3);
        assert_eq!(out.n_ranked, 3);
        assert_eq!(out.families, strs(&["f1", "f2"]));
        for (fam, detail) in &out.per_family {
            assert_eq!(detail.tau, Some(1.0), "family {fam}");
            assert_eq!(detail.swap_fraction, Some(0.0), "family {fam}");
            assert_eq!(detail.max_rank_displacement, Some(0), "family {fam}");
            assert!(detail.dropped_runs.is_empty(), "family {fam}");
        }
        // Full-ranking detail carries rounded asrs in ranked order.
        let detail_asrs: Vec<Option<f64>> = out.full_ranking_detail.iter().map(|r| r.asr).collect();
        assert_eq!(detail_asrs, vec![Some(0.1), Some(0.5), Some(0.9)]);
    }

    #[test]
    fn analysis_detects_influential_family() {
        // A: strong on f1, weak on f2. B: weak on f1, strong on f2.
        // C: middling on both. Full ranking ties A/B on 0.25, broken
        // by run id -> [a, b, c].
        let runs = vec![
            (s("a"), make_run(&[("f1", 0), ("f2", 100)], 200)),
            (s("b"), make_run(&[("f1", 100), ("f2", 0)], 200)),
            (s("c"), make_run(&[("f1", 80), ("f2", 80)], 200)),
        ];
        let out = lottery_analysis(&runs, &strs(&["f1", "f2"])).unwrap();
        assert_eq!(out.full_ranking, strs(&["a", "b", "c"]));
        let f1 = &out.per_family[0].1;
        let f2 = &out.per_family[1].1;
        // Remove f1 -> [b, c, a]: pairs (a,b) and (a,c) discordant.
        assert!((f1.tau.unwrap() - round4(-1.0 / 3.0)).abs() < 1e-15);
        // Remove f2 -> [a, c, b]: only (b,c) discordant.
        assert!((f2.tau.unwrap() - round4(1.0 / 3.0)).abs() < 1e-15);
        assert_eq!(out.lottery_index, Some(0.0));
        assert_eq!(out.min_tau, Some(round4(-1.0 / 3.0)));
        assert_eq!(out.most_influential_family.as_deref(), Some("f1"));
        assert_eq!(f1.ranking, strs(&["b", "c", "a"]));
        assert_eq!(f1.max_rank_displacement, Some(2));
        assert_eq!(out.verdict, "fragile");
    }

    #[test]
    fn analysis_leave_one_out_regates_eligibility() {
        // "thin" has 200 eligible cases in f1 but only 25 in f2:
        // eligible overall, but dropping f1 leaves it under the total
        // gate -> it drops out of that reduced ranking honestly.
        let mut thin = make_run(&[("f1", 40)], 200);
        for i in 0..25 {
            thin.push(case("f2", &format!("f2-{i}"), false));
        }
        let runs = vec![
            (s("thin"), thin),
            (s("solid"), make_run(&[("f1", 120), ("f2", 120)], 200)),
        ];
        let out = lottery_analysis(&runs, &strs(&["f1", "f2"])).unwrap();
        // Full ranking: thin (asr 40/225 ~ 0.178) beats solid (0.6).
        assert_eq!(out.full_ranking, strs(&["thin", "solid"]));
        let drop_f1 = &out.per_family[0].1;
        assert_eq!(drop_f1.ranking, strs(&["solid"]));
        assert_eq!(drop_f1.dropped_runs, strs(&["thin"]));
        // Only "solid" is common to both rankings: tau undefined.
        assert_eq!(drop_f1.tau, None);
        assert_eq!(drop_f1.n_common, 1);
        // f2's removal keeps both runs: tau defined.
        assert!(out.per_family[1].1.tau.is_some());
    }

    #[test]
    fn analysis_undefined_index_when_no_comparable_pair() {
        let runs = vec![(s("solo"), make_run(&[("f1", 40), ("f2", 60)], 200))];
        let out = lottery_analysis(&runs, &strs(&["f1", "f2"])).unwrap();
        assert_eq!(out.lottery_index, None);
        assert_eq!(out.verdict, "undefined");
        assert_eq!(out.min_tau, None);
        assert_eq!(out.most_influential_family, None);
        for (_, detail) in &out.per_family {
            assert_eq!(detail.tau, None);
            assert_eq!(detail.swap_fraction, None);
            assert_eq!(detail.n_common, 1);
            assert_eq!(detail.max_rank_displacement, Some(0));
        }
    }

    #[test]
    fn analysis_empty_families_errors() {
        let runs = vec![(s("a"), make_run(&[("f1", 40)], 200))];
        let err = lottery_analysis(&runs, &[]).unwrap_err();
        assert_eq!(err, "lottery_analysis: families must not be empty");
    }

    #[test]
    fn analysis_single_family_errors() {
        // One family: removing it leaves no families to rank on.
        let runs = vec![(s("a"), make_run(&[("f1", 40)], 200))];
        let err = lottery_analysis(&runs, &strs(&["f1"])).unwrap_err();
        assert_eq!(err, "rank_runs: families must not be empty");
    }

    #[test]
    fn analysis_per_family_follows_input_order() {
        let runs = vec![
            (s("a"), make_run(&[("f1", 20), ("f2", 20)], 200)),
            (s("b"), make_run(&[("f1", 100), ("f2", 100)], 200)),
        ];
        // Reverse-sorted input order must survive into per_family.
        let out = lottery_analysis(&runs, &strs(&["f2", "f1"])).unwrap();
        let order: Vec<&str> = out.per_family.iter().map(|(fam, _)| fam.as_str()).collect();
        assert_eq!(order, vec!["f2", "f1"]);
    }

    #[test]
    fn analysis_most_influential_tie_break_by_name() {
        let runs = vec![
            (s("a"), make_run(&[("zz", 20), ("aa", 20)], 200)),
            (s("b"), make_run(&[("zz", 100), ("aa", 100)], 200)),
        ];
        let out = lottery_analysis(&runs, &strs(&["zz", "aa"])).unwrap();
        assert_eq!(out.per_family[0].1.tau, Some(1.0));
        assert_eq!(out.per_family[1].1.tau, Some(1.0));
        assert_eq!(out.most_influential_family.as_deref(), Some("aa"));
    }

    #[test]
    fn analysis_most_influential_uses_rounded_tau() {
        // Two families whose raw taus differ below the 4th decimal but
        // round to the same value: the tie-break falls to the family
        // name, exactly like Python's min on the rounded taus.
        // (Covered end-to-end by the Python parity suite; here pin the
        // selection logic on synthetic details.)
        let detail = |tau: f64| FamilyDetail {
            tau: Some(round4(tau)),
            swap_fraction: None,
            n_common: 2,
            max_rank_displacement: Some(0),
            ranking: vec![],
            dropped_runs: vec![],
        };
        let per_family = vec![
            (s("b-fam"), detail(0.123446)),
            (s("a-fam"), detail(0.123444)),
        ];
        assert_eq!(round4(0.123446), round4(0.123444));
        assert_eq!(round4(0.123446), 0.1234);
        // The raw taus differ below the 4th decimal but round equal, so
        // the name tie-break picks "a-fam".
        assert_eq!(
            select_most_influential(&per_family).as_deref(),
            Some("a-fam")
        );
    }

    #[test]
    fn select_most_influential_skips_undefined_taus() {
        let detail = |tau: Option<f64>| FamilyDetail {
            tau,
            swap_fraction: None,
            n_common: 1,
            max_rank_displacement: Some(0),
            ranking: vec![],
            dropped_runs: vec![],
        };
        let per_family = vec![(s("f1"), detail(None)), (s("f2"), detail(Some(0.5)))];
        assert_eq!(select_most_influential(&per_family).as_deref(), Some("f2"));
        let all_none = vec![(s("f1"), detail(None))];
        assert_eq!(select_most_influential(&all_none), None);
        let empty: Vec<(String, FamilyDetail)> = vec![];
        assert_eq!(select_most_influential(&empty), None);
    }

    #[test]
    fn analysis_verdict_bands_rounded_index() {
        // taus [1.0, 1.0, 0.6999... ] hmm — instead pin the rule:
        // lottery_analysis bands round4(raw), not raw.
        let raw = 0.89996f64;
        assert_eq!(stability_verdict(Some(round4(raw))), "stable");
        // And the full pipeline applies it: build an analysis whose
        // raw mean sits just under 0.9 but rounds to 0.9.
        // taus of exactly [0.9, 0.9, 0.8999]: mean = 0.8999666...,
        // which Python's sum() reports as 2.6999/3; round to 0.9.
        let mean = {
            let xs = [0.9f64, 0.9, 0.8999];
            neumaier_sum(&xs) / xs.len() as f64
        };
        assert!(mean < 0.9);
        assert_eq!(round4(mean), 0.9);
        assert_eq!(stability_verdict(Some(round4(mean))), "stable");
    }

    #[test]
    fn analysis_dropped_runs_sorted_and_unicode() {
        // Non-ASCII family ids: dropped_runs sorted in byte order
        // (== codepoint order for UTF-8); assert it explicitly.
        let mut thin = make_run(&[("éa", 40)], 200);
        for i in 0..25 {
            thin.push(case("éb", &format!("éb-{i}"), false));
        }
        let runs = vec![
            (s("thin"), thin),
            (s("solid"), make_run(&[("éa", 120), ("éb", 120)], 200)),
        ];
        let out = lottery_analysis(&runs, &strs(&["éa", "éb"])).unwrap();
        let drop_ea = &out.per_family[0].1;
        assert_eq!(drop_ea.dropped_runs, strs(&["thin"]));
        // per_family order follows the input list, not sorted order.
        let order: Vec<&str> = out.per_family.iter().map(|(fam, _)| fam.as_str()).collect();
        assert_eq!(order, vec!["éa", "éb"]);
    }

    #[test]
    fn analysis_n_common_counts_intersection() {
        let runs = vec![
            (s("a"), make_run(&[("f1", 20), ("f2", 20)], 200)),
            (s("b"), make_run(&[("f1", 100), ("f2", 100)], 200)),
            (s("c"), make_run(&[("f1", 180), ("f2", 180)], 200)),
        ];
        let out = lottery_analysis(&runs, &strs(&["f1", "f2"])).unwrap();
        for (_, detail) in &out.per_family {
            assert_eq!(detail.n_common, 3);
        }
    }
}
