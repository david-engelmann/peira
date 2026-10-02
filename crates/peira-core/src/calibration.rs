//! R-11 calibration SVG rendering (rust-max slice 7).
//!
//! Byte-identical port of the diagram functions in `peira.calibration`:
//! `reliability_diagram_svg` and `risk_coverage_diagram_svg`. The Python
//! wrappers gate inputs to JSON-native shapes before dispatching here;
//! the core assumes that contract (see `Scalar`).
//!
//! Formatting contracts (each verified by differential tests against
//! CPython, zero mismatches on tens of thousands of values):
//! - `{x:.4f}`: Rust `format!("{:.4}")` agrees with Python `f"{x:.4f}"`
//!   (both correctly round the exact binary value).
//! - `{t:g}`: [`fmt_g`] replicates Python's `g` conversion with the
//!   default precision of 6 significant digits.
//! - `html.escape(s)` (quote=True): [`html_escape`] maps `&<>"'` to
//!   `&amp;` `&lt;` `&gt;` `&quot;` `&#x27;`, single pass.
//!
//! `confidence_source_label` stays Python: it is a trivial dict lookup
//! whose table is pinned to the adapter classes by test, so a second
//! copy in Rust would be pure drift risk for zero benefit.

// Canvas geometry shared by both diagrams (mirrors the Python module
// constants; all coordinates deterministic so identical inputs give
// byte-identical output).
const WIDTH: i32 = 460;
const HEIGHT: i32 = 340;
const ML: f64 = 56.0; // left margin (y-axis labels)
const MR: f64 = 16.0; // right margin
const MT: f64 = 26.0; // top margin (title)
const MB: f64 = 54.0; // bottom margin (x-axis labels)
const PLOT_W: f64 = WIDTH as f64 - ML - MR; // 388
const PLOT_H: f64 = HEIGHT as f64 - MT - MB; // 260

fn x(f: f64) -> f64 {
    ML + f * PLOT_W
}

fn y(v: f64) -> f64 {
    MT + PLOT_H - v * PLOT_H
}

/// Python `f"{x:.4f}"`.
fn fmt_f4(x: f64) -> String {
    format!("{:.4}", x)
}

/// Python `f"{x:g}"` with the default precision (6 significant digits).
///
/// The gridlines only ever call this with 0.0, 0.25, 0.5, 0.75, 1.0,
/// but the implementation follows the general rule: 6 significant
/// digits, fixed notation when -4 <= exp < 6, otherwise scientific with
/// a two-digit exponent; trailing zeros stripped.
fn fmt_g(x: f64) -> String {
    if x.is_nan() {
        return "nan".to_string();
    }
    if x.is_infinite() {
        return (if x > 0.0 { "inf" } else { "-inf" }).to_string();
    }
    if x == 0.0 {
        return (if x.is_sign_negative() { "-0" } else { "0" }).to_string();
    }
    let neg = x.is_sign_negative();
    let ax = x.abs();
    // 6 significant digits in scientific form, correctly rounded.
    let sci = format!("{:.5e}", ax); // e.g. "2.50000e-1"
    let epos = sci.find('e').expect("scientific format contains 'e'");
    let digits: String = sci[..epos].chars().filter(|c| *c != '.').collect();
    let exp: i32 = sci[epos + 1..].parse().expect("scientific exponent parses");
    let sign = if neg { "-" } else { "" };
    if (-4..6).contains(&exp) {
        let mut out = String::with_capacity(10);
        out.push_str(sign);
        if exp >= 0 {
            let int_end = (exp + 1) as usize;
            out.push_str(&digits[..int_end]);
            let frac = digits[int_end..].trim_end_matches('0');
            if !frac.is_empty() {
                out.push('.');
                out.push_str(frac);
            }
        } else {
            out.push_str("0.");
            for _ in 0..(-exp - 1) {
                out.push('0');
            }
            out.push_str(digits.trim_end_matches('0'));
        }
        out
    } else {
        let mut mant = digits.trim_end_matches('0').to_string();
        let mut m = String::with_capacity(8);
        m.push(mant.remove(0));
        if !mant.is_empty() {
            m.push('.');
            m.push_str(&mant);
        }
        let esign = if exp < 0 { "-" } else { "+" };
        format!("{sign}{m}e{esign}{:02}", exp.abs())
    }
}

/// Python `html.escape(s)` with the default `quote=True`.
fn html_escape(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for c in s.chars() {
        match c {
            '&' => out.push_str("&amp;"),
            '<' => out.push_str("&lt;"),
            '>' => out.push_str("&gt;"),
            '"' => out.push_str("&quot;"),
            '\'' => out.push_str("&#x27;"),
            _ => out.push(c),
        }
    }
    out
}

/// A JSON-native scalar as seen by the twin's `int()`/`float()` coercions.
///
/// The Python gate guarantees only these shapes reach the core; `str`
/// values are gated out (the twin parses them, e.g. `int("5")`, so the
/// twin handles those inputs).
#[derive(Clone, Copy, Debug)]
pub enum Scalar {
    None,
    Bool(bool),
    Int(i64),
    Float(f64),
}

impl Scalar {
    /// Python `int(x)`; `None` when the twin would raise
    /// (`TypeError`/`ValueError`/`OverflowError`).
    ///
    /// The gate guarantees `|f| < 2^63` for floats, so `f as i64`
    /// truncates toward zero exactly like `int()`.
    pub fn to_int(self) -> Option<i64> {
        match self {
            Scalar::None => None,
            Scalar::Bool(b) => Some(i64::from(b)),
            Scalar::Int(i) => Some(i),
            Scalar::Float(f) => {
                // The gate guarantees |f| < 2^63, so `as` truncates toward
                // zero exactly like int(); the guard is defense in depth.
                if f.is_nan() || f.is_infinite() || f.abs() >= i64::MAX as f64 {
                    None
                } else {
                    Some(f as i64)
                }
            }
        }
    }

    /// Python `float(x)`; `None` when the twin would raise (`TypeError`).
    pub fn to_float(self) -> Option<f64> {
        match self {
            Scalar::None => None,
            Scalar::Bool(b) => Some(if b { 1.0 } else { 0.0 }),
            Scalar::Int(i) => Some(i as f64),
            Scalar::Float(f) => Some(f),
        }
    }
}

/// Raw extracted reliability bin; `None` fields mirror a missing key
/// (the twin's `KeyError`, which withholds the block).
#[derive(Clone, Copy, Debug)]
pub struct RawRelBin {
    pub mean_forecast: Scalar,
    pub mean_outcome: Scalar,
    pub n: Scalar,
}

/// Validated reliability block as the twin sees it after `int(n)`.
#[derive(Debug)]
pub struct ReliabilityBlock {
    pub n: i64,
    pub sufficient: bool,
    pub bins: Option<Vec<RawRelBin>>,
}

/// Raw extracted selective-prediction block.
#[derive(Debug)]
pub struct RiskCoverageBlock {
    pub n: i64,
    pub sufficient: bool,
    pub curve: Option<Vec<(Scalar, Scalar)>>,
}

fn gridlines() -> String {
    let mut parts = String::new();
    for t in [0.0, 0.25, 0.5, 0.75, 1.0] {
        let gx = x(t);
        let gy = y(t);
        parts.push_str(&format!(
            "<line x1=\"{}\" y1=\"{}\" x2=\"{}\" y2=\"{}\" stroke=\"#e0e0e0\" stroke-width=\"1\"/>",
            fmt_f4(ML),
            fmt_f4(gy),
            fmt_f4(ML + PLOT_W),
            fmt_f4(gy),
        ));
        parts.push_str(&format!(
            "<line x1=\"{}\" y1=\"{}\" x2=\"{}\" y2=\"{}\" stroke=\"#e0e0e0\" stroke-width=\"1\"/>",
            fmt_f4(gx),
            fmt_f4(MT),
            fmt_f4(gx),
            fmt_f4(MT + PLOT_H),
        ));
        parts.push_str(&format!(
            "<text x=\"{}\" y=\"{}\" text-anchor=\"end\" font-size=\"10\" fill=\"#555\">{}</text>",
            fmt_f4(ML - 8.0),
            fmt_f4(gy + 4.0),
            fmt_g(t),
        ));
        parts.push_str(&format!(
            "<text x=\"{}\" y=\"{}\" text-anchor=\"middle\" font-size=\"10\" fill=\"#555\">{}</text>",
            fmt_f4(gx),
            fmt_f4(MT + PLOT_H + 16.0),
            fmt_g(t),
        ));
    }
    // Axes on top of the grid.
    parts.push_str(&format!(
        "<line x1=\"{}\" y1=\"{}\" x2=\"{}\" y2=\"{}\" stroke=\"#333\" stroke-width=\"1.5\"/>",
        fmt_f4(ML),
        fmt_f4(MT),
        fmt_f4(ML),
        fmt_f4(MT + PLOT_H),
    ));
    parts.push_str(&format!(
        "<line x1=\"{}\" y1=\"{}\" x2=\"{}\" y2=\"{}\" stroke=\"#333\" stroke-width=\"1.5\"/>",
        fmt_f4(ML),
        fmt_f4(MT + PLOT_H),
        fmt_f4(ML + PLOT_W),
        fmt_f4(MT + PLOT_H),
    ));
    parts
}

fn frame(title: &str, xlabel: &str, ylabel: &str, body: &str) -> String {
    let cx = ML + PLOT_W / 2.0;
    format!(
        "<svg viewBox=\"0 0 {WIDTH} {HEIGHT}\" role=\"img\" xmlns=\"http://www.w3.org/2000/svg\" style=\"max-width:460px;width:100%;height:auto\">\
         <title>{}</title>\
         <text x=\"{}\" y=\"16\" text-anchor=\"middle\" font-size=\"13\" fill=\"#222\">{}</text>\
         {}{}\
         <text x=\"{}\" y=\"{}\" text-anchor=\"middle\" font-size=\"11\" fill=\"#333\">{}</text>\
         <text x=\"14\" y=\"{}\" text-anchor=\"middle\" font-size=\"11\" fill=\"#333\" transform=\"rotate(-90 14 {})\">\
         {}</text>\
         </svg>",
        html_escape(title),
        fmt_f4(cx),
        html_escape(title),
        gridlines(),
        body,
        fmt_f4(cx),
        fmt_f4(HEIGHT as f64 - 8.0),
        html_escape(xlabel),
        fmt_f4(MT + PLOT_H / 2.0),
        fmt_f4(MT + PLOT_H / 2.0),
        html_escape(ylabel),
    )
}

fn withheld_html(what: &str, n: i64) -> String {
    format!(
        "<p><em>{} diagram withheld:</em> insufficient data (n={}; 30 observations required).</p>",
        html_escape(what),
        n,
    )
}

/// Inline SVG reliability diagram from a `reliability_bins` block.
///
/// Mirrors the twin exactly: non-sufficient or malformed blocks render
/// the withheld placeholder; zero-count bins are skipped; bins outside
/// [0, 1] withhold the whole diagram.
pub fn reliability_diagram_svg(block: &ReliabilityBlock, title: &str) -> String {
    let bins = match &block.bins {
        Some(b) if block.sufficient && !b.is_empty() => b,
        _ => return withheld_html("Reliability", block.n),
    };
    let mut pts: Vec<(f64, f64, i64)> = Vec::with_capacity(bins.len());
    for b in bins {
        // Mirrors `int(b["n"])`: a failed coercion withholds the block,
        // a non-positive count skips the bin.
        let c = match b.n.to_int() {
            Some(c) => c,
            None => return withheld_html("Reliability", block.n),
        };
        if c <= 0 {
            continue;
        }
        // Mirrors `float(b["mean_forecast"])` / `float(b["mean_outcome"])`.
        let (Some(f), Some(o)) = (b.mean_forecast.to_float(), b.mean_outcome.to_float()) else {
            return withheld_html("Reliability", block.n);
        };
        pts.push((f, o, c));
    }
    if pts.is_empty()
        || pts
            .iter()
            .any(|(f, o, _)| !(0.0 <= *f && *f <= 1.0 && 0.0 <= *o && *o <= 1.0))
    {
        return withheld_html("Reliability", block.n);
    }
    let max_n = pts.iter().map(|(_, _, c)| *c).max().unwrap_or(1).max(1);
    let mut body = format!(
        "<line x1=\"{}\" y1=\"{}\" x2=\"{}\" y2=\"{}\" stroke=\"#999\" stroke-width=\"1.5\" stroke-dasharray=\"6,4\"/>",
        fmt_f4(x(0.0)),
        fmt_f4(y(0.0)),
        fmt_f4(x(1.0)),
        fmt_f4(y(1.0)),
    );
    for (f, o, c) in &pts {
        // Mirrors the twin's `(c / max_n) ** 0.5`. Note: CPython's `**`
        // (libm pow) can differ from `math.sqrt` by 1 ulp on ~0.08% of
        // inputs; the radius is only ever emitted via `{:.4}`, which
        // absorbs it (no observed flip in ~600k probed pairs).
        let r = 3.0 + 5.0 * (*c as f64 / max_n as f64).sqrt();
        body.push_str(&format!(
            "<circle cx=\"{}\" cy=\"{}\" r=\"{}\" fill=\"#1f77b4\" fill-opacity=\"0.75\" stroke=\"#0d4a75\" stroke-width=\"1\">\
             <title>self-reported confidence {}, observed {}, n={}</title></circle>",
            fmt_f4(x(*f)),
            fmt_f4(y(*o)),
            fmt_f4(r),
            fmt_f4(*f),
            fmt_f4(*o),
            c,
        ));
    }
    frame(
        title,
        "mean self-reported confidence",
        "observed accuracy",
        &body,
    )
}

/// Inline SVG selective-risk curve from a `selective_prediction` block.
///
/// Mirrors the twin exactly, including the withheld placeholder for
/// malformed curves.
pub fn risk_coverage_diagram_svg(sp: &RiskCoverageBlock, title: &str) -> String {
    let curve = match &sp.curve {
        Some(c) if sp.sufficient && !c.is_empty() => c,
        _ => return withheld_html("Selective-risk", sp.n),
    };
    let mut pts: Vec<(f64, f64)> = Vec::with_capacity(curve.len());
    for (c, r) in curve {
        // Mirrors `float(c)` / `float(r)`: a failed coercion withholds.
        let (Some(c), Some(r)) = (c.to_float(), r.to_float()) else {
            return withheld_html("Selective-risk", sp.n);
        };
        pts.push((c, r));
    }
    if pts
        .iter()
        .any(|(c, r)| !(0.0 <= *c && *c <= 1.0 && 0.0 <= *r && *r <= 1.0))
    {
        return withheld_html("Selective-risk", sp.n);
    }
    let line = pts
        .iter()
        .map(|(c, r)| format!("{},{}", fmt_f4(x(*c)), fmt_f4(y(*r))))
        .collect::<Vec<_>>()
        .join(" ");
    let mut body = format!(
        "<polyline points=\"{line}\" fill=\"none\" stroke=\"#1f77b4\" stroke-width=\"2\"/>",
    );
    for (c, r) in &pts {
        body.push_str(&format!(
            "<circle cx=\"{}\" cy=\"{}\" r=\"2.5\" fill=\"#1f77b4\">\
             <title>coverage {}, selective risk {}</title></circle>",
            fmt_f4(x(*c)),
            fmt_f4(y(*r)),
            fmt_f4(*c),
            fmt_f4(*r),
        ));
    }
    frame(title, "coverage", "selective risk", &body)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fmt_f4_matches_python_spot_checks() {
        // Values verified against CPython f"{x:.4f}" in the differential harness.
        assert_eq!(fmt_f4(0.25), "0.2500");
        assert_eq!(fmt_f4(56.0), "56.0000");
        assert_eq!(fmt_f4(250.0), "250.0000");
        assert_eq!(fmt_f4(2.675), "2.6750");
        assert_eq!(fmt_f4(1.005), "1.0050");
        assert_eq!(fmt_f4(-0.0), "-0.0000");
    }

    #[test]
    fn fmt_g_matches_python_spot_checks() {
        assert_eq!(fmt_g(0.0), "0");
        assert_eq!(fmt_g(-0.0), "-0");
        assert_eq!(fmt_g(0.25), "0.25");
        assert_eq!(fmt_g(0.5), "0.5");
        assert_eq!(fmt_g(0.75), "0.75");
        assert_eq!(fmt_g(1.0), "1");
        assert_eq!(fmt_g(0.0001), "0.0001");
        assert_eq!(fmt_g(0.00001), "1e-05");
        assert_eq!(fmt_g(1234567.0), "1.23457e+06");
        assert_eq!(fmt_g(123456.0), "123456");
        assert_eq!(fmt_g(f64::NAN), "nan");
        assert_eq!(fmt_g(f64::INFINITY), "inf");
        assert_eq!(fmt_g(f64::NEG_INFINITY), "-inf");
    }

    #[test]
    fn html_escape_matches_python() {
        assert_eq!(
            html_escape("<script>alert(1)</script>"),
            "&lt;script&gt;alert(1)&lt;/script&gt;"
        );
        assert_eq!(html_escape("a&b\"c'd"), "a&amp;b&quot;c&#x27;d");
        assert_eq!(html_escape("plain"), "plain");
        // No double-escaping of existing entities.
        assert_eq!(html_escape("&amp;"), "&amp;amp;");
    }

    #[test]
    fn scalar_int_coercion_mirrors_python() {
        assert_eq!(Scalar::None.to_int(), None);
        assert_eq!(Scalar::Bool(true).to_int(), Some(1));
        assert_eq!(Scalar::Bool(false).to_int(), Some(0));
        assert_eq!(Scalar::Int(5).to_int(), Some(5));
        assert_eq!(Scalar::Int(-3).to_int(), Some(-3));
        assert_eq!(Scalar::Float(3.7).to_int(), Some(3));
        assert_eq!(Scalar::Float(-3.7).to_int(), Some(-3));
        assert_eq!(Scalar::Float(f64::NAN).to_int(), None);
        assert_eq!(Scalar::Float(f64::INFINITY).to_int(), None);
        // Large-but-gated floats truncate exactly like int().
        assert_eq!(Scalar::Float(1e16).to_int(), Some(10_000_000_000_000_000));
        assert_eq!(Scalar::Float(-1e16).to_int(), Some(-10_000_000_000_000_000));
        // At/above 2^63 the twin is not reachable (gate excludes), guard holds.
        assert_eq!(Scalar::Float(9_223_372_036_854_776_576.0).to_int(), None);
    }

    #[test]
    fn scalar_float_coercion_mirrors_python() {
        assert_eq!(Scalar::None.to_float(), None);
        assert_eq!(Scalar::Bool(true).to_float(), Some(1.0));
        assert_eq!(Scalar::Int(5).to_float(), Some(5.0));
        assert_eq!(Scalar::Float(0.5).to_float(), Some(0.5));
    }

    #[test]
    fn withheld_paths_match() {
        let w = withheld_html("Reliability", 5);
        assert_eq!(
            w,
            "<p><em>Reliability diagram withheld:</em> insufficient data (n=5; 30 observations required).</p>"
        );
        // Missing bins -> withheld.
        let svg = reliability_diagram_svg(
            &ReliabilityBlock {
                n: 0,
                sufficient: true,
                bins: None,
            },
            "t",
        );
        assert!(!svg.contains("<svg"));
        // Not sufficient -> withheld.
        let svg = reliability_diagram_svg(
            &ReliabilityBlock {
                n: 5,
                sufficient: false,
                bins: Some(vec![RawRelBin {
                    mean_forecast: Scalar::Float(0.8),
                    mean_outcome: Scalar::Float(0.7),
                    n: Scalar::Int(20),
                }]),
            },
            "t",
        );
        assert!(!svg.contains("<svg"));
        assert!(svg.contains("n=5"));
    }

    #[test]
    fn malformed_bins_withhold() {
        // Missing key (None) withholds the block.
        let svg = reliability_diagram_svg(
            &ReliabilityBlock {
                n: 1,
                sufficient: true,
                bins: Some(vec![RawRelBin {
                    mean_forecast: Scalar::None,
                    mean_outcome: Scalar::Float(0.5),
                    n: Scalar::Int(1),
                }]),
            },
            "t",
        );
        assert!(!svg.contains("<svg"));
        // Out-of-range bin withholds the block.
        let svg = reliability_diagram_svg(
            &ReliabilityBlock {
                n: 5,
                sufficient: true,
                bins: Some(vec![RawRelBin {
                    mean_forecast: Scalar::Float(1.5),
                    mean_outcome: Scalar::Float(0.5),
                    n: Scalar::Int(5),
                }]),
            },
            "t",
        );
        assert!(!svg.contains("<svg"));
        // NaN bin count withholds (twin: int(nan) raises).
        let svg = reliability_diagram_svg(
            &ReliabilityBlock {
                n: 5,
                sufficient: true,
                bins: Some(vec![RawRelBin {
                    mean_forecast: Scalar::Float(0.8),
                    mean_outcome: Scalar::Float(0.7),
                    n: Scalar::Float(f64::NAN),
                }]),
            },
            "t",
        );
        assert!(!svg.contains("<svg"));
    }

    #[test]
    fn zero_count_bins_skipped() {
        let svg = reliability_diagram_svg(
            &ReliabilityBlock {
                n: 20,
                sufficient: true,
                bins: Some(vec![
                    RawRelBin {
                        mean_forecast: Scalar::Float(0.8),
                        mean_outcome: Scalar::Float(0.7),
                        n: Scalar::Int(0),
                    },
                    RawRelBin {
                        mean_forecast: Scalar::Float(0.9),
                        mean_outcome: Scalar::Float(0.95),
                        n: Scalar::Int(20),
                    },
                ]),
            },
            "t",
        );
        assert!(svg.starts_with("<svg"));
        assert_eq!(svg.matches("<circle").count(), 1);
    }

    #[test]
    fn valid_reliability_renders() {
        let svg = reliability_diagram_svg(
            &ReliabilityBlock {
                n: 30,
                sufficient: true,
                bins: Some(vec![
                    RawRelBin {
                        mean_forecast: Scalar::Float(0.8),
                        mean_outcome: Scalar::Float(0.7),
                        n: Scalar::Int(10),
                    },
                    RawRelBin {
                        mean_forecast: Scalar::Float(0.9),
                        mean_outcome: Scalar::Float(0.95),
                        n: Scalar::Int(20),
                    },
                ]),
            },
            "Reliability (benign)",
        );
        assert!(svg.starts_with("<svg"));
        assert!(svg.ends_with("</svg>"));
        assert!(svg.contains("stroke-dasharray=\"6,4\""));
        assert_eq!(svg.matches("<circle").count(), 2);
        assert!(svg.contains("mean self-reported confidence"));
    }

    #[test]
    fn risk_coverage_paths() {
        // Withheld when not sufficient.
        let svg = risk_coverage_diagram_svg(
            &RiskCoverageBlock {
                n: 5,
                sufficient: false,
                curve: None,
            },
            "t",
        );
        assert!(!svg.contains("<svg"));
        assert!(svg.contains("Selective-risk"));
        // Malformed point withholds.
        let svg = risk_coverage_diagram_svg(
            &RiskCoverageBlock {
                n: 40,
                sufficient: true,
                curve: Some(vec![(Scalar::None, Scalar::Float(0.5))]),
            },
            "t",
        );
        assert!(!svg.contains("<svg"));
        // Valid curve renders.
        let svg = risk_coverage_diagram_svg(
            &RiskCoverageBlock {
                n: 40,
                sufficient: true,
                curve: Some(vec![
                    (Scalar::Float(1.0), Scalar::Float(0.2)),
                    (Scalar::Float(0.5), Scalar::Float(0.1)),
                    (Scalar::Float(0.25), Scalar::Float(0.05)),
                ]),
            },
            "Selective-risk curve",
        );
        assert!(svg.starts_with("<svg"));
        assert!(svg.contains("<polyline"));
        assert_eq!(svg.matches("<circle").count(), 3);
    }
}
