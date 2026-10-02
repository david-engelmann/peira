//! Interaction-contrast metrics for the combo suite.
//!
//! This module ports `python/peira/combo_metrics.py`: the paired
//! interaction contrast over the 2x2 factorial unit
//! (`paired_interaction`) and its one-paragraph human summary
//! (`format_interaction`). The `InteractionResult` dataclass stays
//! Python; the Rust core returns its fields and the PyO3 binding
//! hands them back as a dict the wrapper uses to construct it.
//!
//! Parity notes:
//! - `_mean` / `_var_sample` replicate the reference exactly: the mean
//!   divides by `n` (0.0 on empty, unreachable from the public entry
//!   point), the sample variance divides by `n - 1` (0.0 when `n < 2`).
//! - The 95% CI uses the normal 1.96 multiplier and MDE80 uses
//!   `(1.96 + 0.84) * se`, matching the reference constants.
//! - `format_interaction` float rendering (`{:.3}`, `{:+.3}`) is
//!   byte-identical to Python's `{:.3f}` / `{:+.3f}`: both round the
//!   exact binary value half-to-even (verified empirically, including
//!   2.675, -0.0, and sub-ulp ties; see the unit tests).
//! - The verdict table and the hypothesis CONFIRMED/REJECTED suffix
//!   replicate the reference's string assembly exactly, including the
//!   leading space before "Pre-registered".

/// Result of [`paired_interaction`], mirroring the
/// `InteractionResult` dataclass field-for-field.
#[derive(Debug, Clone, PartialEq)]
pub struct InteractionResult {
    pub pair_id: String,
    pub n_substrates: usize,
    pub rate_ctrl: f64,
    pub rate_a: f64,
    pub rate_b: f64,
    pub rate_ab: f64,
    pub interaction: f64,
    pub se: f64,
    pub ci_lo: f64,
    pub ci_hi: f64,
    pub mde_80: f64,
    /// "super" | "additive" | "sub" | "unresolved"
    pub classification: String,
    pub hypothesis: String,
    pub hypothesis_confirmed: Option<bool>,
}

/// Error from [`paired_interaction`]: the reference raises
/// `ValueError("no substrates")` on empty input.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InteractionError(pub String);

impl std::fmt::Display for InteractionError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.0)
    }
}

fn mean(xs: &[f64]) -> f64 {
    if xs.is_empty() {
        0.0
    } else {
        xs.iter().sum::<f64>() / xs.len() as f64
    }
}

fn var_sample(xs: &[f64]) -> f64 {
    let n = xs.len();
    if n < 2 {
        return 0.0;
    }
    let m = mean(xs);
    xs.iter().map(|x| (x - m).powi(2)).sum::<f64>() / (n - 1) as f64
}

/// Compute the paired interaction contrast.
///
/// `outcomes` is one `(y_ctrl, y_a, y_b, y_ab)` binary-outcome tuple
/// per substrate. Mirrors
/// `python/peira/combo_metrics.py::paired_interaction`; empty input
/// returns the `"no substrates"` error the reference raises as
/// `ValueError`.
pub fn paired_interaction(
    outcomes: &[(i64, i64, i64, i64)],
    pair_id: &str,
    hypothesis: &str,
) -> Result<InteractionResult, InteractionError> {
    let n = outcomes.len();
    if n == 0 {
        return Err(InteractionError("no substrates".to_string()));
    }
    // Cast to f64 BEFORE the arithmetic: the reference computes exact
    // Python ints, and i64 arithmetic would panic (debug) or wrap
    // (release) on extreme inputs. f64 arithmetic matches the
    // reference's float conversion for the realistic domain.
    let d: Vec<f64> = outcomes
        .iter()
        .map(|(ctrl, a, b, ab)| (*ab as f64) - (*a as f64) - (*b as f64) + (*ctrl as f64))
        .collect();
    let interaction = mean(&d);
    let var_d = var_sample(&d);
    let se = (var_d / n as f64).sqrt();
    // Normal 95% CI; the t critical value at 99 df (1.984) differs
    // negligibly, per the reference comment.
    let ci_lo = interaction - 1.96 * se;
    let ci_hi = interaction + 1.96 * se;
    // MDE at 80% power, two-sided alpha=0.05: (z_.975 + z_.80) * se.
    let mde_80 = (1.96 + 0.84) * se;

    let classification = if mde_80 > 0.20 {
        // Floor not met: cannot resolve even a large interaction.
        "unresolved"
    } else if ci_lo > 0.0 {
        "super"
    } else if ci_hi < 0.0 {
        "sub"
    } else {
        "additive"
    };

    let hypothesis_confirmed = if classification != "unresolved" && !hypothesis.is_empty() {
        Some(classification == hypothesis)
    } else {
        None
    };

    let rate = |idx: usize| {
        mean(
            &outcomes
                .iter()
                .map(|o| match idx {
                    0 => o.0 as f64,
                    1 => o.1 as f64,
                    2 => o.2 as f64,
                    _ => o.3 as f64,
                })
                .collect::<Vec<f64>>(),
        )
    };

    Ok(InteractionResult {
        pair_id: pair_id.to_string(),
        n_substrates: n,
        rate_ctrl: rate(0),
        rate_a: rate(1),
        rate_b: rate(2),
        rate_ab: rate(3),
        interaction,
        se,
        ci_lo,
        ci_hi,
        mde_80,
        classification: classification.to_string(),
        hypothesis: hypothesis.to_string(),
        hypothesis_confirmed,
    })
}

/// One-paragraph human summary of an interaction result.
///
/// Mirrors `python/peira/combo_metrics.py::format_interaction`
/// byte-for-byte, including the `{:.3}` / `{:+.3}` float rendering
/// (identical to Python's `{:.3f}` / `{:+.3f}`) and the verdict table.
/// Unknown classifications return `Err` (the reference raises
/// `KeyError`); the PyO3 binding maps it to `PyKeyError`.
/// Format a float like Python's `f"{v:.3f}"`: Rust renders NaN as
/// `NaN`, Python as `nan`.
fn py_f3(v: f64) -> String {
    if v.is_nan() {
        "nan".to_string()
    } else {
        format!("{v:.3}")
    }
}

/// Format a float like Python's `f"{v:+.3f}"`.
fn py_f3_signed(v: f64) -> String {
    if v.is_nan() {
        "+nan".to_string()
    } else {
        format!("{v:+.3}")
    }
}

pub fn format_interaction(r: &InteractionResult) -> Result<String, String> {
    let verdict = match r.classification.as_str() {
        "super" => "SUPER-ADDITIVE (synergy)",
        "additive" => "additive (independent)",
        "sub" => "SUB-ADDITIVE (redundancy)",
        "unresolved" => "UNRESOLVED (not resolvable at this n)",
        other => return Err(other.to_string()),
    };
    // Python-compatible float rendering (NaN -> "nan", not "NaN").
    let mut s = format!(
        "{}: n={} substrates; arm rates \
         ctrl={} a={} b={} ab={}; interaction={} \
         95% CI [{}, {}], MDE80={} -> {}.",
        r.pair_id,
        r.n_substrates,
        py_f3(r.rate_ctrl),
        py_f3(r.rate_a),
        py_f3(r.rate_b),
        py_f3(r.rate_ab),
        py_f3_signed(r.interaction),
        py_f3_signed(r.ci_lo),
        py_f3_signed(r.ci_hi),
        py_f3(r.mde_80),
        verdict,
    );
    if !r.hypothesis.is_empty() && r.hypothesis_confirmed.is_some() {
        s.push_str(&format!(
            " Pre-registered hypothesis '{}' {}.",
            r.hypothesis,
            if r.hypothesis_confirmed.unwrap() {
                "CONFIRMED"
            } else {
                "REJECTED"
            },
        ));
    }
    Ok(s)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn outcomes_super(n: usize) -> Vec<(i64, i64, i64, i64)> {
        // ab flips always, nothing else does -> d = 1 everywhere,
        // interaction = 1, se = 0 -> "super".
        vec![(0, 0, 0, 1); n]
    }

    fn outcomes_unresolved() -> Vec<(i64, i64, i64, i64)> {
        // d = [1, -1, 1]: high variance at n = 3 -> MDE80 > 0.20.
        vec![(0, 0, 0, 1), (0, 1, 0, 0), (0, 0, 0, 1)]
    }

    #[test]
    fn empty_is_no_substrates() {
        let err = paired_interaction(&[], "p", "super").unwrap_err();
        assert_eq!(err.0, "no substrates");
    }

    #[test]
    fn contrast_math_matches_reference() {
        // Hand-computed: d = ab - a - b + ctrl.
        let outcomes = vec![(0, 0, 0, 1), (0, 1, 0, 1), (1, 1, 1, 1), (0, 0, 1, 0)];
        // d = [1, 0, 0, -1]; mean = 0; var = (1+0+0+1)/3 = 2/3.
        let r = paired_interaction(&outcomes, "p", "").unwrap();
        assert_eq!(r.n_substrates, 4);
        assert!((r.interaction - 0.0).abs() < 1e-12);
        let se = ((2.0 / 3.0) / 4.0f64).sqrt();
        assert!((r.se - se).abs() < 1e-12);
        assert!((r.ci_lo - (0.0 - 1.96 * se)).abs() < 1e-12);
        assert!((r.ci_hi - (0.0 + 1.96 * se)).abs() < 1e-12);
        assert!((r.mde_80 - 2.8 * se).abs() < 1e-12);
        assert_eq!(r.rate_ctrl, 0.25);
        assert_eq!(r.rate_a, 0.5);
        assert_eq!(r.rate_b, 0.5);
        assert_eq!(r.rate_ab, 0.75);
    }

    #[test]
    fn classification_branches() {
        // Strong positive interaction, tight CI -> super.
        let r = paired_interaction(&outcomes_super(200), "p", "super").unwrap();
        assert_eq!(r.classification, "super");
        assert_eq!(r.hypothesis_confirmed, Some(true));
        // Tiny n, high variance -> unresolved regardless of the point estimate.
        let r = paired_interaction(&outcomes_unresolved(), "p", "super").unwrap();
        assert_eq!(r.classification, "unresolved");
        assert_eq!(r.hypothesis_confirmed, None);
        // Strong negative interaction -> sub.
        let outcomes: Vec<(i64, i64, i64, i64)> = (0..200).map(|_| (0, 1, 1, 0)).collect();
        let r = paired_interaction(&outcomes, "p", "").unwrap();
        assert_eq!(r.classification, "sub");
        // Zero interaction, resolved -> additive.
        let outcomes: Vec<(i64, i64, i64, i64)> =
            (0..200).map(|i| (0, i % 2, i % 2, (i % 2) * 2)).collect();
        let r = paired_interaction(&outcomes, "p", "").unwrap();
        assert_eq!(r.classification, "additive");
    }

    #[test]
    fn format_matches_reference_shape() {
        let r = paired_interaction(&outcomes_super(200), "combo-dfl-ind", "super").unwrap();
        let s = format_interaction(&r).unwrap();
        assert!(s.starts_with("combo-dfl-ind: n=200 substrates; arm rates "));
        assert!(s.contains("SUPER-ADDITIVE (synergy)."));
        assert!(s.ends_with("Pre-registered hypothesis 'super' CONFIRMED."));
        // No hypothesis -> no suffix.
        let mut r2 = r.clone();
        r2.hypothesis.clear();
        r2.hypothesis_confirmed = None;
        let s2 = format_interaction(&r2).unwrap();
        assert!(!s2.contains("Pre-registered"));
        assert!(s2.ends_with('.'));
    }

    #[test]
    fn float_rendering_edge_cases() {
        // Tricky values for :.3 / :+.3 parity (cf. the module docs).
        // Expectations are hardcoded from CPython's format(), not built
        // with Rust's format! (which would make the test tautological).
        let cases: &[(f64, &str, &str)] = &[
            (2.675, "2.675", "+2.675"),
            (-0.0, "-0.000", "-0.000"),
            (0.0005, "0.001", "+0.001"),
            (0.0015, "0.002", "+0.002"),
            (999.9999, "1000.000", "+1000.000"),
            (1.005, "1.005", "+1.005"),
            (0.15, "0.150", "+0.150"),
            (f64::NAN, "nan", "+nan"),
        ];
        for (v, plain, signed) in cases {
            let r = InteractionResult {
                pair_id: "p".into(),
                n_substrates: 100,
                rate_ctrl: *v,
                rate_a: *v,
                rate_b: *v,
                rate_ab: *v,
                interaction: *v,
                se: *v,
                ci_lo: -*v,
                ci_hi: *v,
                mde_80: *v,
                classification: "additive".into(),
                hypothesis: String::new(),
                hypothesis_confirmed: None,
            };
            let s = format_interaction(&r).unwrap();
            assert!(s.contains(&format!("ctrl={plain}")), "{v} -> {s}");
            assert!(s.contains(&format!("interaction={signed}")), "{v} -> {s}");
        }
    }
}
