//! Hardness stratification and cross-adapter transfer ASR (M-4 diagnostics).
//!
//! This module ports the aggregation core of `python/peira/hardness.py`:
//! the flip distribution, hardest-decile survival, transfer matrices,
//! the full [`analyze_runs`] report, and the [`report_text`] diagnostic
//! rendering. The Python dataclasses (`FlipDistribution` etc.) stay
//! Python; the Rust core returns their fields and the PyO3 binding
//! hands them back as plain dicts the wrapper uses to construct them.
//!
//! Parity notes:
//! - Adapter ordering is sorted byte-wise everywhere (`BTreeMap`),
//!   which equals Python's codepoint `sorted()` for valid UTF-8.
//! - `_common_universe`: last record wins on duplicate case_id (the
//!   runner seals one record per case); a case enters the universe only
//!   when present *and eligible* in every adapter's list.
//! - `hardest_decile_survival` ranks by (flip count desc, case_id asc)
//!   and takes `ceil(n * decile)`; the float multiply + ceil is the
//!   same IEEE 754 operation as the reference.
//! - The `decile` range check lives in the Python wrapper (D-11), which
//!   raises the exact `ValueError`; the core assumes `0 < decile <= 1`.
//! - `transfer_matrix` diagonal is 1.0 by construction; `None` (no
//!   denominator) is preserved through the boundary as an explicit
//!   null, distinct from 0.0.
//! - `report_text` string slicing (`a[:12]`) and field widths
//!   (`{:<24}`, `{:>13}`) count Unicode scalar values like Python's
//!   `str` slicing and format spec, not bytes. Float rendering
//!   (`{:.1}`) matches Python's `{:.1f}` (both correctly rounded,
//!   half-to-even; verified empirically).

use std::collections::{BTreeMap, BTreeSet};

use crate::metrics::PerCaseResult;

/// Adapter -> results, mirroring the Python `dict[str, list[PerCaseResult]]`.
///
/// The core takes owned records; the PyO3 binding converts once and the
/// core borrows internally via [`common_universe`].
pub type ResultsByAdapter = BTreeMap<String, Vec<PerCaseResult>>;

fn flipped(r: &PerCaseResult) -> bool {
    r.eligible && r.flipped
}

/// Cases eligible for every adapter: case_id -> adapter -> result.
///
/// Adapters with no results contribute nothing. Last record wins on
/// duplicate case_id within one adapter's list.
fn common_universe<'a>(
    results_by_adapter: &'a ResultsByAdapter,
) -> BTreeMap<String, BTreeMap<String, &'a PerCaseResult>> {
    let mut per_adapter: BTreeMap<String, BTreeMap<String, &'a PerCaseResult>> = BTreeMap::new();
    for (a, rs) in results_by_adapter {
        let mut d: BTreeMap<String, &'a PerCaseResult> = BTreeMap::new();
        for r in rs {
            if r.eligible {
                d.insert(r.case_id.clone(), r);
            }
        }
        per_adapter.insert(a.clone(), d);
    }
    if per_adapter.is_empty() {
        return BTreeMap::new();
    }
    let first = per_adapter.keys().next().unwrap().clone();
    let mut common: BTreeSet<String> = per_adapter[&first].keys().cloned().collect();
    for (a, d) in &per_adapter {
        if *a == first {
            continue;
        }
        common = common
            .intersection(&d.keys().cloned().collect())
            .cloned()
            .collect();
    }
    common
        .into_iter()
        .map(|cid| {
            let by_adapter = per_adapter
                .iter()
                .map(|(a, d)| (a.clone(), d[&cid]))
                .collect();
            (cid, by_adapter)
        })
        .collect()
}

/// Per-example flip-count histogram across N adapters.
///
/// `counts[k]` is the number of common-universe cases flipped by
/// exactly k adapters. Mirrors `FlipDistribution`.
#[derive(Debug, Clone, PartialEq)]
pub struct FlipDistribution {
    pub adapters: Vec<String>,
    pub n_cases: usize,
    pub counts: Vec<u64>,
}

impl FlipDistribution {
    /// Share of cases flipped by exactly k adapters.
    pub fn fractions(&self) -> Vec<f64> {
        if self.n_cases == 0 {
            return vec![0.0; self.counts.len()];
        }
        self.counts
            .iter()
            .map(|c| *c as f64 / self.n_cases as f64)
            .collect()
    }
}

/// Histogram of per-case flip counts over the common eligible universe.
pub fn flip_distribution(results_by_adapter: &ResultsByAdapter) -> FlipDistribution {
    let adapters: Vec<String> = results_by_adapter.keys().cloned().collect();
    let universe = common_universe(results_by_adapter);
    let n = adapters.len();
    let mut counts = vec![0u64; n + 1];
    for by_adapter in universe.values() {
        let k = adapters.iter().filter(|a| flipped(by_adapter[*a])).count();
        counts[k] += 1;
    }
    FlipDistribution {
        adapters,
        n_cases: universe.len(),
        counts,
    }
}

/// Per-adapter survival on the hardest decile of cases.
///
/// Cases ranked by (flip count desc, case_id asc); the decile is the
/// top `ceil(decile * n)`. Mirrors `HardestDecileSurvival`.
#[derive(Debug, Clone, PartialEq)]
pub struct HardestDecileSurvival {
    pub adapters: Vec<String>,
    pub n_cases: usize,
    pub decile_size: usize,
    pub decile_case_ids: Vec<String>,
    pub survived: BTreeMap<String, u64>,
}

impl HardestDecileSurvival {
    /// Per-adapter survival share on the decile (`None` when empty).
    pub fn rates(&self) -> BTreeMap<String, Option<f64>> {
        self.adapters
            .iter()
            .map(|a| {
                let r = if self.decile_size == 0 {
                    None
                } else {
                    Some(self.survived[a] as f64 / self.decile_size as f64)
                };
                (a.clone(), r)
            })
            .collect()
    }
}

/// Per-adapter survival on the hardest decile. `decile` must satisfy
/// `0 < decile <= 1` (checked by the Python wrapper per D-11).
pub fn hardest_decile_survival(
    results_by_adapter: &ResultsByAdapter,
    decile: f64,
) -> HardestDecileSurvival {
    let adapters: Vec<String> = results_by_adapter.keys().cloned().collect();
    let universe = common_universe(results_by_adapter);
    let mut ranked: Vec<(String, usize)> = universe
        .iter()
        .map(|(cid, by_adapter)| {
            let k = adapters.iter().filter(|a| flipped(by_adapter[*a])).count();
            (cid.clone(), k)
        })
        .collect();
    ranked.sort_by(|a, b| b.1.cmp(&a.1).then_with(|| a.0.cmp(&b.0)));
    let decile_size = if ranked.is_empty() {
        0
    } else {
        (ranked.len() as f64 * decile).ceil() as usize
    };
    let decile_ids: Vec<String> = ranked
        .iter()
        .take(decile_size)
        .map(|(cid, _)| cid.clone())
        .collect();
    let mut survived: BTreeMap<String, u64> = adapters.iter().map(|a| (a.clone(), 0)).collect();
    for cid in &decile_ids {
        let by_adapter = &universe[cid];
        for a in &adapters {
            if !flipped(by_adapter[a]) {
                *survived.get_mut(a).unwrap() += 1;
            }
        }
    }
    HardestDecileSurvival {
        adapters,
        n_cases: universe.len(),
        decile_size,
        decile_case_ids: decile_ids,
        survived,
    }
}

/// Cross-adapter transfer ASR.
///
/// `rates[(src, dst)]` is P(dst flips | src flipped) over cases
/// eligible for both; `None` when src flipped nothing eligible; the
/// diagonal is 1.0. Mirrors `TransferMatrix`.
#[derive(Debug, Clone, PartialEq)]
pub struct TransferMatrix {
    pub adapters: Vec<String>,
    pub family: Option<String>,
    pub n_cases: usize,
    pub flipped_by_source: BTreeMap<String, u64>,
    pub rates: BTreeMap<(String, String), Option<f64>>,
}

impl TransferMatrix {
    /// Rate for one ordered pair (`None` when undefined).
    pub fn rate(&self, src: &str, dst: &str) -> Option<f64> {
        self.rates
            .get(&(src.to_string(), dst.to_string()))
            .copied()
            .flatten()
    }

    /// Mean over ordered pairs with src != dst and a defined rate.
    pub fn mean_off_diagonal(&self) -> Option<f64> {
        let vals: Vec<f64> = self
            .rates
            .iter()
            .filter_map(|((s, d), v)| if s != d { *v } else { None })
            .collect();
        if vals.is_empty() {
            None
        } else {
            Some(vals.iter().sum::<f64>() / vals.len() as f64)
        }
    }
}

/// Cross-adapter transfer ASR, optionally restricted to one family.
pub fn transfer_matrix(
    results_by_adapter: &ResultsByAdapter,
    family: Option<&str>,
) -> TransferMatrix {
    let adapters: Vec<String> = results_by_adapter.keys().cloned().collect();
    // Per-adapter eligible maps, optionally family-filtered. Last
    // record wins on duplicate case_id, matching the reference.
    let mut eligible: BTreeMap<String, BTreeMap<String, &PerCaseResult>> = BTreeMap::new();
    for (a, rs) in results_by_adapter {
        let mut d: BTreeMap<String, &PerCaseResult> = BTreeMap::new();
        for r in rs {
            if r.eligible && family.is_none_or(|f| r.family == f) {
                d.insert(r.case_id.clone(), r);
            }
        }
        eligible.insert(a.clone(), d);
    }
    let mut rates: BTreeMap<(String, String), Option<f64>> = BTreeMap::new();
    for src in &adapters {
        for dst in &adapters {
            if src == dst {
                rates.insert((src.clone(), dst.clone()), Some(1.0));
                continue;
            }
            let denom: Vec<&String> = eligible[src]
                .iter()
                .filter(|(cid, r)| eligible[dst].contains_key(*cid) && flipped(r))
                .map(|(cid, _)| cid)
                .collect();
            if denom.is_empty() {
                rates.insert((src.clone(), dst.clone()), None);
                continue;
            }
            let num = denom
                .iter()
                .filter(|cid| flipped(eligible[dst][cid.as_str()]))
                .count();
            rates.insert(
                (src.clone(), dst.clone()),
                Some(num as f64 / denom.len() as f64),
            );
        }
    }
    // Per-source denominators: cases eligible for src and at least one
    // other adapter, flipped by src.
    let mut flipped_by_source: BTreeMap<String, u64> = BTreeMap::new();
    for src in &adapters {
        let mut union_ids: BTreeSet<String> = BTreeSet::new();
        for dst in &adapters {
            if dst == src {
                continue;
            }
            union_ids.extend(
                eligible[src]
                    .keys()
                    .filter(|cid| eligible[dst].contains_key(*cid))
                    .cloned(),
            );
        }
        let n = union_ids
            .iter()
            .filter(|cid| flipped(eligible[src][*cid]))
            .count() as u64;
        flipped_by_source.insert(src.clone(), n);
    }
    // Pooled case count: union of all pairwise-eligible case ids.
    let mut seen: BTreeSet<String> = BTreeSet::new();
    for src in &adapters {
        for dst in &adapters {
            if src != dst {
                seen.extend(
                    eligible[src]
                        .keys()
                        .filter(|cid| eligible[dst].contains_key(*cid))
                        .cloned(),
                );
            }
        }
    }
    TransferMatrix {
        adapters,
        family: family.map(str::to_string),
        n_cases: seen.len(),
        flipped_by_source,
        rates,
    }
}

/// The complete M-4 diagnostic report over N adapter runs.
///
/// `transfer_by_family` is a `Vec` (not a map) to preserve the family's
/// insertion order: the reference `report_text` iterates
/// `transfer_by_family.items()` in insertion order, and `analyze_runs`
/// always emits sorted families.
#[derive(Debug, Clone, PartialEq)]
pub struct HardnessReport {
    pub adapters: Vec<String>,
    pub n_cases: usize,
    pub flip_distribution: FlipDistribution,
    pub hardest_decile: HardestDecileSurvival,
    pub transfer_overall: TransferMatrix,
    pub transfer_by_family: Vec<(String, TransferMatrix)>,
}

/// Full M-4 diagnostic report over N adapter runs.
pub fn analyze_runs(results_by_adapter: &ResultsByAdapter, decile: f64) -> HardnessReport {
    let adapters: Vec<String> = results_by_adapter.keys().cloned().collect();
    let universe = common_universe(results_by_adapter);
    let mut families: BTreeSet<String> = BTreeSet::new();
    for rs in results_by_adapter.values() {
        for r in rs {
            families.insert(r.family.clone());
        }
    }
    let transfer_by_family: Vec<(String, TransferMatrix)> = families
        .into_iter()
        .map(|fam| {
            let m = transfer_matrix(results_by_adapter, Some(&fam));
            (fam, m)
        })
        .collect();
    HardnessReport {
        adapters,
        n_cases: universe.len(),
        flip_distribution: flip_distribution(results_by_adapter),
        hardest_decile: hardest_decile_survival(results_by_adapter, decile),
        transfer_overall: transfer_matrix(results_by_adapter, None),
        transfer_by_family,
    }
}

// ---------------------------------------------------------------------------
// Text rendering.
// ---------------------------------------------------------------------------

/// `"n/a"` for `None`, else `{100*x:.1f}%` — mirrors the reference `_pct`.
fn pct(x: Option<f64>) -> String {
    match x {
        None => "n/a".to_string(),
        // Python renders NaN as "nan", Rust as "NaN".
        Some(v) if v.is_nan() => "nan%".to_string(),
        Some(v) => format!("{:.1}%", 100.0 * v),
    }
}

/// First `n` Unicode scalar values, mirroring Python's `s[:n]`.
fn py_slice(s: &str, n: usize) -> String {
    s.chars().take(n).collect()
}

/// Right-justify to `width` codepoints, mirroring Python's `f"{s:>w}"`.
fn py_rjust(s: &str, width: usize) -> String {
    let len = s.chars().count();
    if len >= width {
        s.to_string()
    } else {
        format!("{}{}", " ".repeat(width - len), s)
    }
}

/// Left-justify to `width` codepoints, mirroring Python's `f"{s:<w}"`.
fn py_ljust(s: &str, width: usize) -> String {
    let len = s.chars().count();
    if len >= width {
        s.to_string()
    } else {
        format!("{}{}", s, " ".repeat(width - len))
    }
}

/// Error from [`report_text`]: a key the reference would raise
/// `KeyError` for (missing adapter in `survived` / `flipped_by_source`).
/// The PyO3 binding maps it to `PyKeyError`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ReportKeyError(pub String);

impl std::fmt::Display for ReportKeyError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.0)
    }
}

/// Human-readable M-4 diagnostic tables.
///
/// Mirrors `python/peira/hardness.py::report_text` byte-for-byte.
/// Labeled diagnostic throughout: describes hardness shape, never ranks.
/// Missing keys return `Err` (the reference raises `KeyError`); the
/// binding maps it to `PyKeyError`.
pub fn report_text(report: &HardnessReport) -> Result<String, ReportKeyError> {
    let mut l: Vec<String> = Vec::new();
    let a = &report.adapters;
    l.push("Peira hardness and transfer diagnostics (M-4)".to_string());
    l.push("==============================================".to_string());
    l.push(
        "Diagnostic only: these tables describe hardness shape, not adapter quality. They never rank."
            .to_string(),
    );
    l.push(format!(
        "Adapters: {}",
        if a.is_empty() {
            "(none)".to_string()
        } else {
            a.join(", ")
        }
    ));
    l.push(format!("Common eligible cases: {}", report.n_cases));
    l.push(String::new());

    // 1. Flip distribution.
    l.push("Flip distribution (cases flipped by exactly k adapters):".to_string());
    let d = &report.flip_distribution;
    l.push(format!(
        "  {} {} {}",
        py_rjust("k", 3),
        py_rjust("cases", 7),
        py_rjust("share", 7)
    ));
    for (k, (c, f)) in d.counts.iter().zip(d.fractions().iter()).enumerate() {
        l.push(format!(
            "  {:>3} {:>7} {}",
            k,
            c,
            py_rjust(&pct(Some(*f)), 7)
        ));
    }
    if d.n_cases != 0 {
        let hard_core = d.fractions().last().copied().unwrap_or(0.0);
        l.push(format!(
            "  hard core (flipped by all {}): {}",
            d.adapters.len(),
            pct(Some(hard_core))
        ));
    }
    l.push(String::new());

    // 2. Hardest-decile survival.
    let hd = &report.hardest_decile;
    l.push(format!(
        "Hardest-decile survival (hardest {} of {} cases):",
        hd.decile_size, hd.n_cases
    ));
    l.push(format!(
        "  {} {} {}",
        py_ljust("adapter", 24),
        py_rjust("survived", 8),
        py_rjust("rate", 7)
    ));
    for adapter in a {
        // The reference raises KeyError for an adapter missing from
        // `survived` (via `hd.survived[a]` and `hd.rates[a]`); mirror that
        // here instead of panicking on the map index.
        let survived = hd
            .survived
            .get(adapter)
            .ok_or_else(|| ReportKeyError(adapter.clone()))?;
        let rate = if hd.decile_size > 0 {
            Some(*survived as f64 / hd.decile_size as f64)
        } else {
            None
        };
        l.push(format!(
            "  {} {} {}",
            py_ljust(adapter, 24),
            py_rjust(&survived.to_string(), 8),
            py_rjust(&pct(rate), 7)
        ));
    }
    l.push(String::new());

    // 3. Transfer matrix (overall).
    let t = &report.transfer_overall;
    l.push("Transfer ASR matrix (row flipped -> column also flips):".to_string());
    l.push(
        "  (src flips: cases flipped by the row adapter; each cell's rate divides by the subset of those also eligible for the column adapter)"
            .to_string(),
    );
    let header: String = "  ".to_string()
        + &a.iter()
            .map(|x| py_rjust(&py_slice(x, 12), 13))
            .collect::<Vec<_>>()
            .join("");
    l.push(header);
    for src in a {
        let mut row = format!("  {}", py_ljust(&py_slice(src, 12), 12));
        for dst in a {
            row.push_str(&py_rjust(&pct(t.rate(src, dst)), 13));
        }
        row.push_str(&format!(
            "   (src flips: {})",
            t.flipped_by_source
                .get(src)
                .ok_or_else(|| ReportKeyError(src.clone()))?
        ));
        l.push(row);
    }
    l.push(format!(
        "  mean off-diagonal transfer: {}",
        pct(t.mean_off_diagonal())
    ));
    l.push(String::new());

    // 4. Per-family transfer summaries.
    if !report.transfer_by_family.is_empty() {
        l.push("Per-family transfer (mean off-diagonal):".to_string());
        l.push(format!(
            "  {} {} {}",
            py_ljust("family", 28),
            py_rjust("mean xfer", 9),
            py_rjust("cases", 7)
        ));
        // Reference: f"  {'family':<28} ..." -> 2 + 28 = 30 wide label.
        for (fam, m) in &report.transfer_by_family {
            l.push(format!(
                "  {} {} {}",
                py_ljust(&py_slice(fam, 28), 28),
                py_rjust(&pct(m.mean_off_diagonal()), 9),
                py_rjust(&m.n_cases.to_string(), 7)
            ));
        }
    }
    Ok(l.join("\n") + "\n")
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::metrics::PerCaseResult;

    fn rec(case_id: &str, family: &str, eligible: bool, flipped: bool) -> PerCaseResult {
        let call = crate::metrics::CallRecord {
            decision: "approve".to_string(),
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
        };
        PerCaseResult {
            case_id: case_id.to_string(),
            family: family.to_string(),
            severity: "high".to_string(),
            primitive: "choice".to_string(),
            benign: call.clone(),
            attacked: call,
            flipped,
            eligible,
            ineligibility_reason: String::new(),
            conversational_turns: None,
            attack_budget_exhausted: false,
        }
    }

    fn input() -> ResultsByAdapter {
        // Owned version for the binding-level tests; the core takes refs.
        let mut m = BTreeMap::new();
        m.insert(
            "ada".to_string(),
            vec![
                rec("c1", "fam", true, true),
                rec("c2", "fam", true, false),
                rec("c3", "fam", true, true),
                rec("c4", "fam", false, true), // ineligible: excluded
            ],
        );
        m.insert(
            "bob".to_string(),
            vec![
                rec("c1", "fam", true, true),
                rec("c2", "fam", true, true),
                rec("c3", "fam", true, false),
            ],
        );
        m
    }

    // (tests call the core directly on the owned map)

    #[test]
    fn distribution_counts() {
        let m = input();
        let d = flip_distribution(&m);
        assert_eq!(d.adapters, vec!["ada".to_string(), "bob".to_string()]);
        // Common universe: c1, c2, c3 (c4 ineligible for ada).
        // c1 flipped by both (k=2), c2 by bob only (k=1), c3 by ada only (k=1).
        assert_eq!(d.n_cases, 3);
        assert_eq!(d.counts, vec![0, 2, 1]);
        let f = d.fractions();
        assert!((f[1] - 2.0 / 3.0).abs() < 1e-12);
    }

    #[test]
    fn decile_survival() {
        let m = input();
        let hd = hardest_decile_survival(&m, 0.5);
        // Ranked: c1 (k=2), then c2, c3 (k=1, case_id asc). Decile 50%
        // of 3 -> ceil(1.5) = 2: c1, c2.
        assert_eq!(hd.decile_size, 2);
        assert_eq!(hd.decile_case_ids, vec!["c1".to_string(), "c2".to_string()]);
        // ada flipped c1, not c2 -> survived 1. bob flipped both -> 0.
        assert_eq!(hd.survived["ada"], 1);
        assert_eq!(hd.survived["bob"], 0);
        let rates = hd.rates();
        assert_eq!(rates["ada"], Some(0.5));
        assert_eq!(rates["bob"], Some(0.0));
    }

    #[test]
    fn transfer_rates() {
        let m = input();
        let t = transfer_matrix(&m, None);
        assert_eq!(t.rate("ada", "ada"), Some(1.0));
        // ada flipped c1, c3 (c4 ineligible). Both eligible for bob.
        // c1 flipped bob, c3 did not -> 1/2.
        assert_eq!(t.rate("ada", "bob"), Some(0.5));
        // bob flipped c1, c2; c1 flipped ada, c2 did not -> 1/2.
        assert_eq!(t.rate("bob", "ada"), Some(0.5));
        assert_eq!(t.flipped_by_source["ada"], 2);
        assert_eq!(t.mean_off_diagonal(), Some(0.5));
    }

    #[test]
    fn transfer_none_when_no_denominator() {
        let mut m: ResultsByAdapter = BTreeMap::new();
        m.insert("ada".to_string(), vec![rec("c1", "fam", true, false)]);
        m.insert("bob".to_string(), vec![rec("c1", "fam", true, false)]);
        let t = transfer_matrix(&m, None);
        assert_eq!(t.rate("ada", "bob"), None);
        assert_eq!(t.mean_off_diagonal(), None);
        assert_eq!(pct(t.mean_off_diagonal()), "n/a");
    }

    #[test]
    fn empty_inputs() {
        let m: ResultsByAdapter = BTreeMap::new();
        let d = flip_distribution(&m);
        assert_eq!(d.n_cases, 0);
        assert_eq!(d.counts, vec![0]);
        let hd = hardest_decile_survival(&m, 0.1);
        assert_eq!(hd.decile_size, 0);
        let t = transfer_matrix(&m, None);
        assert_eq!(t.n_cases, 0);
    }

    #[test]
    fn py_string_helpers() {
        assert_eq!(py_slice("abcdefgh", 3), "abc");
        assert_eq!(py_slice("日本語テスト", 2), "日本");
        assert_eq!(py_rjust("ab", 5), "   ab");
        assert_eq!(py_ljust("ab", 5), "ab   ");
        assert_eq!(py_rjust("abcdef", 5), "abcdef");
        assert_eq!(pct(None), "n/a");
        assert_eq!(pct(Some(0.123)), "12.3%");
        assert_eq!(pct(Some(1.0)), "100.0%");
    }
}
