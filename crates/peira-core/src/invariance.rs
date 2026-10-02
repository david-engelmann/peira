//! Variant-flip rate: the reported metric for slot-substitution probes.
//!
//! This module ports `python/peira/probes/invariance.py`: run the
//! adapter on the original case and on `n` slot-substituted variants;
//! the flip rate is the fraction of variants whose decision differs
//! from the original case's decision. This helper is pure: it takes
//! decision strings, not adapters.
//!
//! Parity notes:
//! - A flip is any decision string inequality, including a variant
//!   that abstains (`""`) where the baseline decided or vice versa.
//! - `flip_rate` is IEEE-754 `n_flips / n_variants`, identical in both
//!   languages for the same operands.
//! - An empty variant set is a domain error (`ValueError` in Python);
//!   the core returns it as `Err` and the PyO3 binding maps it to
//!   `PyValueError` with the identical message. (The Python wrapper
//!   also validates before dispatch per D-11, so this is a backstop.)

/// Flip-rate summary for one case's variant set.
///
/// Mirrors `python/peira/probes/invariance.py::InvarianceReport`.
#[derive(Debug, Clone, PartialEq)]
pub struct InvarianceReport {
    /// Decision on the original (unsubstituted) case.
    pub baseline: String,
    pub n_variants: usize,
    pub n_flips: usize,
    /// `n_flips / n_variants`, in [0, 1].
    pub flip_rate: f64,
    /// Positions in `variant_decisions` that flipped.
    pub flipped_indices: Vec<usize>,
}

/// Domain error for [`invariance_report`].
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InvarianceError {
    message: String,
}

impl InvarianceError {
    /// The exact message the Python reference raises.
    pub fn message(&self) -> &str {
        &self.message
    }
}

impl std::fmt::Display for InvarianceError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.message)
    }
}

/// Compare variant decisions against the baseline decision.
///
/// Mirrors `python/peira/probes/invariance.py::invariance_report`.
/// Returns `Err` when `variant_decisions` is empty: an empty variant
/// set measures nothing.
pub fn invariance_report(
    baseline_decision: &str,
    variant_decisions: &[String],
) -> Result<InvarianceReport, InvarianceError> {
    if variant_decisions.is_empty() {
        return Err(InvarianceError {
            message: "variant_decisions must be non-empty".to_owned(),
        });
    }
    let flipped_indices: Vec<usize> = variant_decisions
        .iter()
        .enumerate()
        .filter(|(_, d)| d.as_str() != baseline_decision)
        .map(|(i, _)| i)
        .collect();
    let n_variants = variant_decisions.len();
    let n_flips = flipped_indices.len();
    Ok(InvarianceReport {
        baseline: baseline_decision.to_owned(),
        n_variants,
        n_flips,
        flip_rate: n_flips as f64 / n_variants as f64,
        flipped_indices,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn strs(xs: &[&str]) -> Vec<String> {
        xs.iter().map(|s| s.to_string()).collect()
    }

    #[test]
    fn no_flips() {
        let r = invariance_report("approve", &strs(&["approve", "approve"])).unwrap();
        assert_eq!(r.baseline, "approve");
        assert_eq!(r.n_variants, 2);
        assert_eq!(r.n_flips, 0);
        assert_eq!(r.flip_rate, 0.0);
        assert!(r.flipped_indices.is_empty());
    }

    #[test]
    fn some_flips_positions() {
        let r = invariance_report("approve", &strs(&["approve", "deny", "approve", "deny"])).unwrap();
        assert_eq!(r.n_variants, 4);
        assert_eq!(r.n_flips, 2);
        assert_eq!(r.flip_rate, 0.5);
        assert_eq!(r.flipped_indices, vec![1, 3]);
    }

    #[test]
    fn abstain_counts_as_flip() {
        // A variant that abstains ("") where the baseline decided flips,
        // and vice versa.
        let r = invariance_report("approve", &strs(&["approve", ""])).unwrap();
        assert_eq!(r.n_flips, 1);
        assert_eq!(r.flipped_indices, vec![1]);
        let r = invariance_report("", &strs(&["", "approve"])).unwrap();
        assert_eq!(r.n_flips, 1);
        assert_eq!(r.flipped_indices, vec![1]);
    }

    #[test]
    fn all_flip_rate_one() {
        let r = invariance_report("deny", &strs(&["deny", "deny"])).unwrap();
        assert_eq!(r.flip_rate, 0.0);
        let r = invariance_report("approve", &strs(&["deny"])).unwrap();
        assert_eq!(r.n_variants, 1);
        assert_eq!(r.n_flips, 1);
        assert_eq!(r.flip_rate, 1.0);
    }

    #[test]
    fn empty_variants_is_error() {
        let err = invariance_report("approve", &[]).unwrap_err();
        assert_eq!(err.message(), "variant_decisions must be non-empty");
    }

    #[test]
    fn flip_rate_third() {
        // 1/3: pins the exact IEEE-754 division result.
        let r = invariance_report("a", &strs(&["a", "a", "b"])).unwrap();
        assert_eq!(r.flip_rate, 1.0f64 / 3.0f64);
    }
}
