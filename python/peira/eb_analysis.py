"""External-benchmark Tier 1 analyses (EB-23, EB-40, EB-10, EB-7).

Four analysis-on-existing-data features from the external-benchmark
disposition (research_notes/external-benchmark-disposition-20260930.md,
Tier 1). All four are pure aggregation over fields the runner already
records; none requires new data collection.

EB-23 confidence-erosion distribution
    Per non-flipped attacked case, the erosion
    ``benign.confidence - attacked.confidence``: how much confidence
    the attack destroyed while the decision held. Per-family
    distribution (fixed-bin histogram, p50/p90) plus the near-flip
    fraction (large erosion, decision held). Complements M-6's Wilson
    CIs on severity flip rates with the within-case confidence view.

EB-40 robustness-tax analysis
    Cross-adapter: does a lower ASR cost benign accuracy or
    calibration (the RobustBench clean/robust-gap lesson)? Per-adapter
    tax estimates with CIs relative to the observed frontier, plus
    cross-adapter Spearman correlations (ASR vs benign accuracy,
    ASR vs ECE). The leaderboard's tax column is the combined-tax
    point estimate; the full report carries the components and CIs.

EB-10 generation-length protocol + length-sensitivity analysis
    (a) Adapters declare their generation cap; the runner seals it
    into the artifact config (see runner.py ``generation_max_tokens``).
    (b) Per-family regression of the flip indicator on attacked-arm
    output length (adapter-reported ``tokens_out``), with bootstrap
    CIs: does length alone move ASR (HarmBench found up to 30pp
    swings)?

EB-7 length de-confounding diagnostics
    Per-family regression of per-case ASR on response length and on
    verbosity features (attacked-minus-benign token delta), with
    Holm-adjusted significance, plus the bivariate OLS slope of flips
    on attacked length *adjusted for* the verbosity delta: the
    de-confounded length effect. A significant family gets length as
    a reported covariate and feeds EB-10's protocol decision. When
    the univariate length slope is significant but the adjusted slope
    is not, verbosity was carrying the effect, not length.

Conventions (same as peira.metrics): stdlib only, deterministic
seeded bootstrap via ``random.Random``, withheld values are None
with ``sufficient: False`` (never NaN, never silently dropped),
every reported float rounded to 4 decimals, invalid inputs raise
``ValueError``.
"""

from __future__ import annotations

import math
import random
from typing import Any, NamedTuple

from peira.metrics import PerCaseResult, holm_adjust, wilson_ci

#: EB-23: a non-flipped case is a "near-flip" when the attack destroyed
#: at least this much absolute confidence while the decision held.
#: 0.5 is half the confidence scale: a model that went from 0.9 to
#: 0.4 but kept its decision came genuinely close. Absolute, not
#: relative, so a 0.55 -> 0.05 collapse and a 0.95 -> 0.45 collapse
#: count the same: both lost half the scale.
NEAR_FLIP_EROSION = 0.5

#: EB-23: fixed histogram bins over [-1, 1] with this width, so
#: erosion histograms are comparable across families and runs
#: without re-binning.
EROSION_HIST_BIN_WIDTH = 0.2

#: EB-23/EB-7/EB-10: minimum observations before a distribution or
#: regression is reported (the S9 30-observation discipline:
#: withheld as insufficient, never as zero).
MIN_OBSERVATIONS = 30

#: EB-40: minimum adapters for a cross-adapter correlation. Below
#: this the rank correlation is noise; the per-adapter taxes are
#: still reported.
MIN_CORR_ADAPTERS = 5

#: EB-7/EB-10: bootstrap resamples for the slope CIs. Capped below
#: summarize()'s default: slope quantiles converge faster than the
#: tail-quantile estimates elsewhere, and these run per family.
LENGTH_BOOTSTRAP_RESAMPLES = 2000


def _round4(x: float | None) -> float | None:
    return None if x is None else round(x, 4)


def _check_results(results: list[PerCaseResult]) -> None:
    if not isinstance(results, list):
        raise ValueError(
            f"results must be a list, got {type(results).__name__}"
        )
    for r in results:
        if not isinstance(r, PerCaseResult):
            raise ValueError(
                "results must contain PerCaseResult, got "
                f"{type(r).__name__}"
            )


def _check_seed(seed: int) -> None:
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError(f"seed must be an integer, got {seed!r}")


def _check_n_boot(n_boot: int) -> None:
    if isinstance(n_boot, bool) or not isinstance(n_boot, int):
        raise ValueError(f"n_boot must be an integer, got {n_boot!r}")
    if n_boot <= 0:
        raise ValueError(f"n_boot must be positive, got {n_boot!r}")


def _percentile(sorted_vals: list[float], q: float) -> float:
    """Linear-interpolation percentile of pre-sorted values."""
    n = len(sorted_vals)
    if n == 0:
        raise ValueError("percentile of empty sequence")
    if n == 1:
        return sorted_vals[0]
    pos = q * (n - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return sorted_vals[lo]
    frac = pos - lo
    return sorted_vals[lo] + frac * (sorted_vals[hi] - sorted_vals[lo])


def _bootstrap_percentile_ci(
    values: list[float],
    statistic,
    n_boot: int,
    seed: int,
) -> tuple[float, float] | None:
    """Seeded bootstrap percentile CI for a statistic over values."""
    n = len(values)
    if n == 0:
        return None
    rng = random.Random(seed)
    stats: list[float] = []
    for _ in range(n_boot):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        stats.append(statistic(sample))
    stats.sort()
    return (
        _percentile(stats, 0.025),
        _percentile(stats, 0.975),
    )


# ---------------------------------------------------------------------------
# EB-23: confidence-erosion distribution on failed attacks
# ---------------------------------------------------------------------------


def _erosion(r: PerCaseResult) -> float | None:
    """Benign-minus-attacked confidence for one non-flipped case.

    Only eligible, non-flipped cases with both confidences present
    contribute; a missing confidence is not a zero. Positive erosion
    means the attack destroyed confidence while the decision held.
    """
    if not r.eligible or r.flipped:
        return None
    b = r.benign.confidence
    a = r.attacked.confidence
    if b is None or a is None:
        return None
    if not (math.isfinite(b) and math.isfinite(a)):
        raise ValueError(
            f"non-finite confidence on case {r.case_id!r}"
        )
    return b - a


def erosion_pairs(
    results: list[PerCaseResult],
) -> list[tuple[str, float]]:
    """(family, erosion) pairs for the EB-23 population.

    One pair per eligible non-flipped case with both confidences
    present, in input order. Cases outside the population are
    excluded, never imputed.
    """
    _check_results(results)
    out: list[tuple[str, float]] = []
    for r in results:
        e = _erosion(r)
        if e is not None:
            out.append((r.family, e))
    return out


def _erosion_histogram(erosions: list[float]) -> dict[str, list]:
    """Fixed-bin histogram of erosions over [-1, 1].

    Bins of width EROSION_HIST_BIN_WIDTH (0.2): bin ``i`` covers
    ``[-1 + 0.2*i, -1 + 0.2*(i+1))``, the last bin closing at 1.0.
    Erosion is a difference of unit-interval confidences, so every
    in-range value lands in exactly one bin; out-of-range values
    (which cannot occur from real confidences) clamp into the edge
    bins defensively.
    """
    n_bins = int(round(2.0 / EROSION_HIST_BIN_WIDTH))
    counts = [0] * n_bins
    edges = [
        -1.0 + EROSION_HIST_BIN_WIDTH * i for i in range(n_bins + 1)
    ]
    for e in erosions:
        idx = int((e + 1.0) / EROSION_HIST_BIN_WIDTH + 1e-9)
        if idx < 0:
            idx = 0
        elif idx >= n_bins:
            idx = n_bins - 1
        counts[idx] += 1
    return {
        "bin_edges": [_round4(x) for x in edges],
        "counts": counts,
    }


class ErosionStats(NamedTuple):
    n: int
    mean: float | None
    p50: float | None
    p90: float | None
    near_flip_fraction: float | None
    near_flip_ci95: tuple[float, float] | None
    histogram: dict[str, list] | None
    sufficient: bool


def _erosion_stats(
    erosions: list[float],
    near_flip_erosion: float,
) -> ErosionStats:
    n = len(erosions)
    if n < MIN_OBSERVATIONS:
        return ErosionStats(
            n=n, mean=None, p50=None, p90=None,
            near_flip_fraction=None, near_flip_ci95=None,
            histogram=None, sufficient=False,
        )
    ordered = sorted(erosions)
    near = sum(1 for e in erosions if e >= near_flip_erosion)
    frac = near / n
    return ErosionStats(
        n=n,
        mean=sum(erosions) / n,
        p50=_percentile(ordered, 0.5),
        p90=_percentile(ordered, 0.9),
        near_flip_fraction=frac,
        near_flip_ci95=wilson_ci(near, n),
        histogram=_erosion_histogram(erosions),
        sufficient=True,
    )


def _erosion_stats_dict(s: ErosionStats) -> dict[str, Any]:
    return {
        "n": s.n,
        "sufficient": s.sufficient,
        "mean": _round4(s.mean),
        "p50": _round4(s.p50),
        "p90": _round4(s.p90),
        "near_flip_fraction": _round4(s.near_flip_fraction),
        "near_flip_ci95": (
            None if s.near_flip_ci95 is None
            else [_round4(s.near_flip_ci95[0]),
                  _round4(s.near_flip_ci95[1])]
        ),
        "histogram": s.histogram,
    }


def confidence_erosion(
    results: list[PerCaseResult],
    near_flip_erosion: float = NEAR_FLIP_EROSION,
) -> dict[str, Any]:
    """EB-23: per-family confidence-erosion distribution.

    For every eligible non-flipped case with both confidences, the
    erosion ``benign.confidence - attacked.confidence``. Reports the
    distribution (mean, p50, p90, fixed-bin histogram) overall and
    per family, plus the near-flip fraction: cases where the attack
    destroyed at least ``near_flip_erosion`` absolute confidence
    while the decision held (Wilson 95% CI). Families below
    30 observations report ``sufficient: False`` with None values.

    ``near_flip_erosion`` must be finite; non-positive values raise:
    a non-positive threshold would label every held decision a
    near-flip.
    """
    _check_results(results)
    if (
        isinstance(near_flip_erosion, bool)
        or not isinstance(near_flip_erosion, (int, float))
        or not math.isfinite(near_flip_erosion)
    ):
        raise ValueError(
            "near_flip_erosion must be a finite number, got "
            f"{near_flip_erosion!r}"
        )
    if near_flip_erosion <= 0:
        raise ValueError(
            "near_flip_erosion must be positive, got "
            f"{near_flip_erosion!r}"
        )
    pairs = erosion_pairs(results)
    by_family: dict[str, list[float]] = {}
    for fam, e in pairs:
        by_family.setdefault(fam, []).append(e)
    return {
        "near_flip_erosion_threshold": _round4(float(near_flip_erosion)),
        "n_nonflipped_with_confidence": len(pairs),
        "overall": _erosion_stats_dict(
            _erosion_stats([e for _, e in pairs], near_flip_erosion)
        ),
        "by_family": {
            fam: _erosion_stats_dict(_erosion_stats(es, near_flip_erosion))
            for fam, es in sorted(by_family.items())
        },
    }


def erosion_report_text(report: dict[str, Any]) -> str:
    """Human-readable EB-23 confidence-erosion report."""
    lines = [
        "Peira confidence-erosion distribution (EB-23)",
        "=============================================",
        f"Near-flip threshold: erosion >= "
        f"{report['near_flip_erosion_threshold']:.2f} "
        f"(decision held)",
        f"Non-flipped cases with both confidences: "
        f"{report['n_nonflipped_with_confidence']}",
        "",
    ]
    ov = report["overall"]
    if ov["sufficient"]:
        lines.append(
            f"Overall: n={ov['n']}, mean erosion {ov['mean']:.4f}, "
            f"p50 {ov['p50']:.4f}, p90 {ov['p90']:.4f}"
        )
        lo, hi = ov["near_flip_ci95"]
        lines.append(
            f"Overall near-flip fraction: "
            f"{ov['near_flip_fraction']:.4f} [{lo:.4f}, {hi:.4f}]"
        )
    else:
        lines.append(
            f"Overall: insufficient data (n={ov['n']}, "
            f"need {MIN_OBSERVATIONS})"
        )
    lines.append("")
    lines.append("Per family:")
    for fam, s in report["by_family"].items():
        if s["sufficient"]:
            lines.append(
                f"  {fam}: n={s['n']}, mean {s['mean']:.4f}, "
                f"p50 {s['p50']:.4f}, p90 {s['p90']:.4f}, "
                f"near-flip {s['near_flip_fraction']:.4f}"
            )
        else:
            lines.append(f"  {fam}: insufficient data (n={s['n']})")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# EB-40: robustness-tax analysis
# ---------------------------------------------------------------------------


class AdapterTaxInput(NamedTuple):
    """One adapter's headline numbers for the tax computation.

    Each CI is a (lo, hi) tuple from the adapter's own run (Wilson
    for the rates, bootstrap for ECE); None when the component was
    withheld. ``log_loss``/``log_loss_ci`` feed the ASR-vs-log-loss
    correlation; None when R-07 did not run or the value is not
    sealed in the artifact (the correlation is then withheld, never
    imputed).
    """

    adapter: str
    asr: float | None
    asr_ci: tuple[float, float] | None
    benign_accuracy: float | None
    benign_accuracy_ci: tuple[float, float] | None
    ece: float | None
    ece_ci: tuple[float, float] | None
    log_loss: float | None = None
    log_loss_ci: tuple[float, float] | None = None
    n_cases: int = 0


def _check_tax_inputs(runs: list[AdapterTaxInput]) -> None:
    if not isinstance(runs, list):
        raise ValueError(
            f"runs must be a list, got {type(runs).__name__}"
        )
    if len(runs) < 2:
        raise ValueError(
            "robustness tax needs at least 2 adapters, got "
            f"{len(runs)}"
        )
    for r in runs:
        if not isinstance(r, AdapterTaxInput):
            raise ValueError(
                "runs must contain AdapterTaxInput, got "
                f"{type(r).__name__}"
            )
        if not r.adapter:
            raise ValueError("adapter name must be non-empty")
    # One frontier reading per adapter: duplicate names are allowed
    # only when they agree on every analysis input. A conflicting
    # duplicate means the same adapter was measured twice with
    # different results, and the frontier would be ambiguous: the
    # caller picks one reading.
    seen: dict[str, AdapterTaxInput] = {}
    for r in runs:
        prev = seen.get(r.adapter)
        if prev is not None:
            if (prev.asr != r.asr
                    or prev.asr_ci != r.asr_ci
                    or prev.benign_accuracy != r.benign_accuracy
                    or prev.benign_accuracy_ci != r.benign_accuracy_ci
                    or prev.ece != r.ece
                    or prev.ece_ci != r.ece_ci
                    or prev.log_loss != r.log_loss
                    or prev.log_loss_ci != r.log_loss_ci
                    or prev.n_cases != r.n_cases):
                raise ValueError(
                    f"adapter {r.adapter!r} appears twice with "
                    "different readings: the tax needs one frontier "
                    "reading per adapter"
                )
        else:
            seen[r.adapter] = r


def _spearman(xs: list[float], ys: list[float]) -> float:
    """Spearman rank correlation with average tie ranks."""
    n = len(xs)
    if n != len(ys) or n == 0:
        raise ValueError("spearman needs non-empty equal-length inputs")

    def ranks(vs: list[float]) -> list[float]:
        order = sorted(range(n), key=lambda i: vs[i])
        r = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and vs[order[j + 1]] == vs[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r

    rx, ry = ranks(xs), ranks(ys)
    mx = sum(rx) / n
    my = sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = sum((a - mx) ** 2 for a in rx)
    vy = sum((b - my) ** 2 for b in ry)
    if vx == 0 or vy == 0:
        raise ValueError("spearman undefined: constant input")
    return cov / math.sqrt(vx * vy)


def _spearman_ci(
    xs: list[float], ys: list[float], n_boot: int, seed: int
) -> tuple[float, float] | None:
    n = len(xs)
    rng = random.Random(seed)
    vals: list[float] = []
    for _ in range(n_boot):
        idx = [rng.randrange(n) for _ in range(n)]
        try:
            vals.append(
                _spearman([xs[i] for i in idx], [ys[i] for i in idx])
            )
        except ValueError:
            continue
    if len(vals) < 10:
        return None
    vals.sort()
    return (_percentile(vals, 0.025), _percentile(vals, 0.975))


def robustness_tax(
    runs: list[AdapterTaxInput],
    n_boot: int = 5000,
    seed: int = 0,
) -> dict[str, Any]:
    """EB-40: per-adapter robustness tax + cross-adapter correlations.

    The tax is measured against the observed frontier: the best
    benign accuracy and the best (lowest) ECE across the input
    adapters.

    - ``accuracy_tax`` = best_benign_accuracy - adapter accuracy
      (accuracy points paid for robustness, vs the best observed).
    - ``calibration_tax`` = adapter ECE - best ECE (calibration
      points paid, vs the best observed).
    - ``combined_tax`` = accuracy_tax + calibration_tax: the
      leaderboard tax column. Both components are 0..1-scale rates,
      so the sum is interpretable as total tax points.

    Tax CIs come from the adapter's own component CIs with the
    frontier reference held fixed (documented approximation). A tax
    is None (withheld) when its component was withheld. The
    combined-tax CI sums the component CI bounds, which assumes
    perfect positive correlation between the two tax components:
    a conservative (wide) CI, documented here rather than hidden.

    Cross-adapter Spearman correlations: ASR vs benign accuracy
    (negative rho = lower ASR costs accuracy: the tax exists),
    ASR vs ECE, and ASR vs log-loss (when R-07 log-loss is
    available), with bootstrap CIs. Withheld below
    MIN_CORR_ADAPTERS adapters.
    """
    _check_tax_inputs(runs)
    _check_n_boot(n_boot)
    _check_seed(seed)
    # One reading per adapter: identical duplicates collapse (the
    # check above guarantees they agree), so no adapter is
    # double-counted in the frontier or the correlations. The dict
    # keeps the last of identical readings; they are identical, so
    # which one survives does not matter.
    runs = list({r.adapter: r for r in runs}.values())
    accs = [r.benign_accuracy for r in runs
            if r.benign_accuracy is not None]
    eces = [r.ece for r in runs if r.ece is not None]
    if not accs or not eces:
        raise ValueError(
            "robustness tax needs at least one adapter with benign "
            "accuracy and one with ECE"
        )
    best_acc = max(accs)
    best_ece = min(eces)

    per_adapter: dict[str, dict[str, Any]] = {}
    for r in runs:
        # The frontier reference is held fixed (a documented
        # approximation): each tax CI comes from the adapter's own
        # component CI alone.
        a_tax = (best_acc - r.benign_accuracy
                 if r.benign_accuracy is not None else None)
        if r.benign_accuracy is not None and r.benign_accuracy_ci:
            lo = best_acc - r.benign_accuracy_ci[1]
            hi = best_acc - r.benign_accuracy_ci[0]
            a_tax_ci: tuple[float, float] | None = (
                min(lo, hi), max(lo, hi))
        else:
            a_tax_ci = None
        c_tax = (r.ece - best_ece if r.ece is not None else None)
        if r.ece is not None and r.ece_ci:
            lo = r.ece_ci[0] - best_ece
            hi = r.ece_ci[1] - best_ece
            c_tax_ci: tuple[float, float] | None = (
                min(lo, hi), max(lo, hi))
        else:
            c_tax_ci = None
        if a_tax is not None and c_tax is not None:
            combined = a_tax + c_tax
            if a_tax_ci is not None and c_tax_ci is not None:
                combined_ci = (
                    a_tax_ci[0] + c_tax_ci[0],
                    a_tax_ci[1] + c_tax_ci[1],
                )
            else:
                combined_ci = None
        else:
            combined = None
            combined_ci = None
        per_adapter[r.adapter] = {
            "accuracy_tax": _round4(a_tax),
            "accuracy_tax_ci95": (
                None if a_tax_ci is None
                else [_round4(a_tax_ci[0]), _round4(a_tax_ci[1])]),
            "calibration_tax": _round4(c_tax),
            "calibration_tax_ci95": (
                None if c_tax_ci is None
                else [_round4(c_tax_ci[0]), _round4(c_tax_ci[1])]),
            "combined_tax": _round4(combined),
            "combined_tax_ci95": (
                None if combined_ci is None
                else [_round4(combined_ci[0]),
                      _round4(combined_ci[1])]),
            "n_cases": r.n_cases,
            "sufficient": a_tax is not None and c_tax is not None,
        }

    corr_n = len(runs)
    corr_ok = corr_n >= MIN_CORR_ADAPTERS
    correlations: dict[str, dict[str, Any]] = {}
    for key, xs_sel, ys_sel in (
        ("asr_vs_benign_accuracy",
         [r.asr for r in runs],
         [r.benign_accuracy for r in runs]),
        ("asr_vs_ece",
         [r.asr for r in runs],
         [r.ece for r in runs]),
        ("asr_vs_log_loss",
         [r.asr for r in runs],
         [r.log_loss for r in runs]),
    ):
        entry: dict[str, Any] = {
            "n_adapters": corr_n, "sufficient": False,
            "rho": None, "ci95": None,
        }
        if corr_ok and all(v is not None for v in xs_sel) \
                and all(v is not None for v in ys_sel):
            try:
                rho = _spearman(xs_sel, ys_sel)  # type: ignore[arg-type]
                ci = _spearman_ci(xs_sel, ys_sel, n_boot, seed)  # type: ignore[arg-type]
                entry = {
                    "n_adapters": corr_n, "sufficient": True,
                    "rho": _round4(rho),
                    "ci95": (None if ci is None
                             else [_round4(ci[0]), _round4(ci[1])]),
                }
            except ValueError:
                pass
        correlations[key] = entry

    return {
        "n_adapters": len(runs),
        "frontier": {
            "best_benign_accuracy": _round4(best_acc),
            "best_ece": _round4(best_ece),
        },
        "per_adapter": per_adapter,
        "correlations": correlations,
    }


def tax_report_text(report: dict[str, Any]) -> str:
    """Human-readable EB-40 robustness-tax report."""
    lines = [
        "Peira robustness-tax analysis (EB-40)",
        "=====================================",
        f"Adapters: {report['n_adapters']}",
        f"Frontier: best benign accuracy "
        f"{report['frontier']['best_benign_accuracy']:.4f}, "
        f"best ECE {report['frontier']['best_ece']:.4f}",
        "",
        "Per-adapter tax (points paid vs the observed frontier):",
    ]
    for adapter in sorted(report["per_adapter"]):
        t = report["per_adapter"][adapter]
        if t["sufficient"]:
            lines.append(
                f"  {adapter}: accuracy_tax {t['accuracy_tax']:.4f}, "
                f"calibration_tax {t['calibration_tax']:.4f}, "
                f"combined {t['combined_tax']:.4f}"
            )
        else:
            lines.append(f"  {adapter}: insufficient data")
    lines.append("")
    lines.append("Cross-adapter Spearman correlations:")
    for key, c in report["correlations"].items():
        if c["sufficient"]:
            ci = (f"[{c['ci95'][0]:.4f}, {c['ci95'][1]:.4f}]"
                  if c["ci95"] else "CI unavailable")
            lines.append(f"  {key}: rho {c['rho']:.4f} {ci}")
        else:
            lines.append(
                f"  {key}: withheld "
                f"(need {MIN_CORR_ADAPTERS} adapters, "
                f"have {c['n_adapters']})"
            )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# EB-7 / EB-10: length de-confounding diagnostics + sensitivity
# ---------------------------------------------------------------------------


def _length_features(r: PerCaseResult) -> tuple[float, float | None] | None:
    """(attacked tokens_out, verbosity delta) for one case.

    Verbosity delta = attacked.tokens_out - benign.tokens_out: how
    much longer the attacked response ran. Requires an eligible case
    whose attacked arm carries adapter-reported tokens_out; the
    benign arm may lack it (delta then falls back to None and only
    the attacked length is usable). Missing lengths are never
    imputed.
    """
    if not r.eligible:
        return None
    au = r.attacked.usage
    if au is None or au.tokens_out is None:
        return None
    a_len = au.tokens_out
    if (
        isinstance(a_len, bool)
        or not isinstance(a_len, (int, float))
        or not math.isfinite(a_len)
        or a_len < 0
    ):
        raise ValueError(
            f"invalid tokens_out on case {r.case_id!r}: {a_len!r}"
        )
    bu = r.benign.usage
    b_len = bu.tokens_out if bu is not None else None
    if b_len is None:
        delta = None
    elif (
        isinstance(b_len, bool)
        or not isinstance(b_len, (int, float))
        or not math.isfinite(b_len)
        or b_len < 0
    ):
        raise ValueError(
            f"invalid benign tokens_out on case {r.case_id!r}: "
            f"{b_len!r}"
        )
    else:
        delta = a_len - b_len
    return (float(a_len), delta)


def length_pairs(
    results: list[PerCaseResult],
) -> list[tuple[str, int, float, float | None]]:
    """(family, flipped, attacked_len, verbosity_delta) per case.

    One tuple per eligible case with attacked-arm tokens_out, in
    input order. ``flipped`` is 1/0. Cases without length data are
    excluded, never imputed.
    """
    _check_results(results)
    out: list[tuple[str, int, float, float | None]] = []
    for r in results:
        f = _length_features(r)
        if f is not None:
            out.append((r.family, 1 if r.flipped else 0, f[0], f[1]))
    return out


def _ols_slope(xs: list[float], ys: list[float]) -> float:
    """OLS slope of y on x (linear probability model for flips)."""
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        raise ValueError("ols undefined: constant predictor")
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx


def _ols_2var(
    xs1: list[float], xs2: list[float], ys: list[float]
) -> tuple[float, float]:
    """Bivariate OLS slopes: y on x1 and x2. Returns (b1, b2).

    Closed-form normal-equation solution on demeaned variables.
    b1 is the x1 slope *adjusted for* x2 (Frisch-Waugh-Lovell):
    the x1 effect with the x2 confounder partialled out. Raises
    ValueError on collinear predictors (zero determinant), in which
    case the adjusted slope is withheld, never fudged.
    """
    n = len(xs1)
    if n != len(xs2) or n != len(ys) or n == 0:
        raise ValueError("ols_2var needs non-empty equal-length inputs")
    m1 = sum(xs1) / n
    m2 = sum(xs2) / n
    my = sum(ys) / n
    x1c = [x - m1 for x in xs1]
    x2c = [x - m2 for x in xs2]
    yc = [y - my for y in ys]
    s11 = sum(a * a for a in x1c)
    s22 = sum(b * b for b in x2c)
    s12 = sum(a * b for a, b in zip(x1c, x2c))
    s1y = sum(a * c for a, c in zip(x1c, yc))
    s2y = sum(b * c for b, c in zip(x2c, yc))
    det = s11 * s22 - s12 * s12
    if det == 0:
        raise ValueError("ols_2var undefined: collinear predictors")
    b1 = (s1y * s22 - s2y * s12) / det
    b2 = (s2y * s11 - s1y * s12) / det
    return b1, b2


def _adjusted_slope_ci(
    xs_len: list[float],
    xs_delta: list[float],
    ys: list[int],
    n_boot: int,
    seed: int,
) -> tuple[float, float] | None:
    """Seeded bootstrap CI for the verbosity-adjusted length slope."""
    n = len(xs_len)
    rng = random.Random(seed)
    slopes: list[float] = []
    for _ in range(n_boot):
        idx = [rng.randrange(n) for _ in range(n)]
        try:
            b1, _ = _ols_2var(
                [xs_len[i] for i in idx],
                [xs_delta[i] for i in idx],
                [float(ys[i]) for i in idx],
            )
            slopes.append(b1)
        except ValueError:
            continue
    if len(slopes) < 10:
        return None
    slopes.sort()
    return (_percentile(slopes, 0.025), _percentile(slopes, 0.975))


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return None
    return (
        sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        / math.sqrt(sxx * syy)
    )


def _slope_ci(
    xs: list[float],
    ys: list[int],
    n_boot: int,
    seed: int,
) -> tuple[float, float] | None:
    """Seeded bootstrap CI for the OLS slope."""
    n = len(xs)
    rng = random.Random(seed)
    slopes: list[float] = []
    for _ in range(n_boot):
        idx = [rng.randrange(n) for _ in range(n)]
        try:
            slopes.append(
                _ols_slope(
                    [xs[i] for i in idx],
                    [float(ys[i]) for i in idx],
                )
            )
        except ValueError:
            continue
    if len(slopes) < 10:
        return None
    slopes.sort()
    return (_percentile(slopes, 0.025), _percentile(slopes, 0.975))


def _tertile_asr(
    xs: list[float], ys: list[int]
) -> list[dict[str, Any]]:
    """ASR in length tertiles: does the flip rate move with length?"""
    n = len(xs)
    order = sorted(range(n), key=lambda i: xs[i])
    # Contiguous thirds of the length-sorted order: tertile 1 is the
    # shortest third, tertile 3 the longest. (Interleaved thirds
    # would mix short and long in every group and answer nothing.)
    cut1, cut2 = n // 3, 2 * n // 3
    thirds = [order[:cut1], order[cut1:cut2], order[cut2:]]
    out = []
    for k, idx in enumerate(thirds):
        hits = sum(ys[i] for i in idx)
        m = len(idx)
        lo, hi = wilson_ci(hits, m)
        out.append({
            "tertile": k + 1,
            "n": m,
            "x_lo": _round4(min(xs[i] for i in idx)),
            "x_hi": _round4(max(xs[i] for i in idx)),
            "asr": _round4(hits / m),
            "asr_ci95": [_round4(lo), _round4(hi)],
        })
    return out


class LengthSlice(NamedTuple):
    n: int
    slope: float | None
    slope_ci95: tuple[float, float] | None
    pearson_r: float | None
    tertile_asr: list[dict[str, Any]] | None
    significant: bool | None
    sufficient: bool


def _length_slice(
    xs: list[float],
    ys: list[int],
    n_boot: int,
    seed: int,
) -> LengthSlice:
    n = len(xs)
    if n < MIN_OBSERVATIONS:
        return LengthSlice(
            n=n, slope=None, slope_ci95=None, pearson_r=None,
            tertile_asr=None, significant=None, sufficient=False,
        )
    try:
        slope = _ols_slope(xs, [float(y) for y in ys])
    except ValueError:
        return LengthSlice(
            n=n, slope=None, slope_ci95=None, pearson_r=None,
            tertile_asr=None, significant=None, sufficient=False,
        )
    ci = _slope_ci(xs, ys, n_boot, seed)
    return LengthSlice(
        n=n,
        slope=slope,
        slope_ci95=ci,
        pearson_r=_pearson(xs, [float(y) for y in ys]),
        tertile_asr=_tertile_asr(xs, ys),
        significant=(ci is not None and (ci[0] > 0 or ci[1] < 0)),
        sufficient=True,
    )


def _length_slice_dict(s: LengthSlice) -> dict[str, Any]:
    return {
        "n": s.n,
        "sufficient": s.sufficient,
        "slope": _round4(s.slope),
        "slope_ci95": (
            None if s.slope_ci95 is None
            else [_round4(s.slope_ci95[0]), _round4(s.slope_ci95[1])]
        ),
        "pearson_r": _round4(s.pearson_r),
        "tertile_asr": s.tertile_asr,
        "significant": s.significant,
    }


class AdjustedLengthSlice(NamedTuple):
    n_joint: int
    length_slope_adjusted: float | None
    length_slope_adjusted_ci95: tuple[float, float] | None
    verbosity_slope_adjusted: float | None
    significant: bool | None
    sufficient: bool


def _adjusted_length_slice(
    xs_len: list[float],
    xs_delta: list[float],
    ys: list[int],
    n_boot: int,
    seed: int,
) -> AdjustedLengthSlice:
    """EB-7: bivariate OLS of flips on attacked length + verbosity.

    The joint sample is the cases carrying both predictors (the
    delta list is already restricted to cases with a verbosity
    delta; ``xs_len`` is passed aligned to it by the caller).
    ``length_slope_adjusted`` is the length slope with verbosity
    partialled out: the de-confounded length effect. Withheld
    below MIN_OBSERVATIONS joint cases or on collinear predictors.
    """
    n = len(xs_delta)
    if (
        n < MIN_OBSERVATIONS
        or len(xs_len) != n
        or len(ys) != n
    ):
        return AdjustedLengthSlice(
            n_joint=n, length_slope_adjusted=None,
            length_slope_adjusted_ci95=None,
            verbosity_slope_adjusted=None,
            significant=None, sufficient=False,
        )
    try:
        b1, b2 = _ols_2var(
            xs_len, xs_delta, [float(y) for y in ys])
    except ValueError:
        return AdjustedLengthSlice(
            n_joint=n, length_slope_adjusted=None,
            length_slope_adjusted_ci95=None,
            verbosity_slope_adjusted=None,
            significant=None, sufficient=False,
        )
    ci = _adjusted_slope_ci(xs_len, xs_delta, ys, n_boot, seed)
    return AdjustedLengthSlice(
        n_joint=n,
        length_slope_adjusted=b1,
        length_slope_adjusted_ci95=ci,
        verbosity_slope_adjusted=b2,
        significant=(ci is not None and (ci[0] > 0 or ci[1] < 0)),
        sufficient=True,
    )


def _adjusted_length_dict(s: AdjustedLengthSlice) -> dict[str, Any]:
    return {
        "n_joint": s.n_joint,
        "sufficient": s.sufficient,
        "length_slope_adjusted": _round4(s.length_slope_adjusted),
        "length_slope_adjusted_ci95": (
            None if s.length_slope_adjusted_ci95 is None
            else [_round4(s.length_slope_adjusted_ci95[0]),
                  _round4(s.length_slope_adjusted_ci95[1])]
        ),
        "verbosity_slope_adjusted": _round4(s.verbosity_slope_adjusted),
        "significant": s.significant,
    }


def length_sensitivity(
    results: list[PerCaseResult],
    n_boot: int = LENGTH_BOOTSTRAP_RESAMPLES,
    seed: int = 0,
) -> dict[str, Any]:
    """EB-10(b): per-family regression of flips on response length.

    For each family, the OLS slope of the flip indicator (1/0) on
    attacked-arm ``tokens_out`` (linear probability model), with a
    seeded bootstrap 95% CI, the Pearson r, and ASR by length
    tertile. A slope CI excluding zero means length alone moves the
    flip rate in that family. Families below 30 length observations
    (or with constant length) report ``sufficient: False``.
    """
    _check_results(results)
    _check_n_boot(n_boot)
    _check_seed(seed)
    pairs = length_pairs(results)
    by_family: dict[str, tuple[list[float], list[int]]] = {}
    for fam, flipped, a_len, _ in pairs:
        xs, ys = by_family.setdefault(fam, ([], []))
        xs.append(a_len)
        ys.append(flipped)
    return {
        "n_cases_with_length": len(pairs),
        "by_family": {
            fam: _length_slice_dict(
                _length_slice(xs, ys, n_boot, seed))
            for fam, (xs, ys) in sorted(by_family.items())
        },
    }


def length_confound_diagnostics(
    results: list[PerCaseResult],
    n_boot: int = LENGTH_BOOTSTRAP_RESAMPLES,
    seed: int = 0,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """EB-7: length de-confounding diagnostics per family.

    Two univariate regressions per family: flips on attacked-arm
    length, and flips on the verbosity delta (attacked minus benign
    tokens). Each slope gets a bootstrap CI; significance is
    Holm-adjusted across all family x predictor tests at ``alpha``.
    ``covariate_recommended`` is True for a family when any
    predictor survives Holm: length is then a reported covariate
    for that family, feeding EB-10's protocol decision.

    Additionally, the bivariate OLS slope of flips on attacked
    length *adjusted for* the verbosity delta (``adjusted``): the
    de-confounded length effect. A univariate length slope that
    vanishes after adjustment was verbosity's doing, not length's.
    """
    _check_results(results)
    _check_n_boot(n_boot)
    _check_seed(seed)
    if (
        isinstance(alpha, bool)
        or not isinstance(alpha, (int, float))
        or not 0 < alpha < 1
    ):
        raise ValueError(f"alpha must be in (0, 1), got {alpha!r}")
    pairs = length_pairs(results)
    by_family: dict[str, dict[str, list]] = {}
    for fam, flipped, a_len, delta in pairs:
        d = by_family.setdefault(
            fam, {"len": ([], []), "delta": ([], []),
                  "joint": ([], [], [])})
        d["len"][0].append(a_len)
        d["len"][1].append(flipped)
        if delta is not None:
            d["delta"][0].append(delta)
            d["delta"][1].append(flipped)
            # Joint sample for the bivariate fit: attacked length,
            # verbosity delta, and flip indicator, same cases.
            d["joint"][0].append(a_len)
            d["joint"][1].append(delta)
            d["joint"][2].append(flipped)

    # Collect raw p-values via the bootstrap CI: significant iff the
    # CI excludes zero. For Holm we need p-values; approximate from
    # the bootstrap distribution of the slope: two-sided p = 2 *
    # min(P(slope <= 0), P(slope >= 0)).
    tests: list[tuple[str, str, list[float], list[int]]] = []
    for fam in sorted(by_family):
        for pred in ("len", "delta"):
            xs, ys = by_family[fam][pred]
            if len(xs) >= MIN_OBSERVATIONS:
                try:
                    _ols_slope(xs, [float(y) for y in ys])
                except ValueError:
                    continue
                tests.append((fam, pred, xs, ys))

    rng = random.Random(seed)
    p_values: list[float] = []
    boot_slopes: list[list[float]] = []
    for fam, pred, xs, ys in tests:
        n = len(xs)
        slopes: list[float] = []
        for _ in range(n_boot):
            idx = [rng.randrange(n) for _ in range(n)]
            try:
                slopes.append(_ols_slope(
                    [xs[i] for i in idx],
                    [float(ys[i]) for i in idx]))
            except ValueError:
                continue
        boot_slopes.append(slopes)
        if len(slopes) < 10:
            p_values.append(1.0)
            continue
        p_le = sum(1 for s in slopes if s <= 0) / len(slopes)
        p_ge = sum(1 for s in slopes if s >= 0) / len(slopes)
        p_values.append(min(1.0, 2.0 * min(p_le, p_ge)))

    adj = holm_adjust(p_values, alpha=alpha) if p_values else []
    sig_map = {
        (fam, pred): (a < alpha)
        for (fam, pred, _, _), a in zip(tests, adj)
    }

    families: dict[str, dict[str, Any]] = {}
    for fam in sorted(by_family):
        preds: dict[str, dict[str, Any]] = {}
        for pred in ("len", "delta"):
            xs, ys = by_family[fam][pred]
            sl = _length_slice(xs, ys, n_boot, seed + 1)
            d = _length_slice_dict(sl)
            key = (fam, pred)
            d["holm_significant"] = (
                sig_map.get(key))
            preds["attacked_length" if pred == "len"
                  else "verbosity_delta"] = d
        cov = any(
            p.get("holm_significant") is True
            for p in preds.values()
        )
        families[fam] = {
            "predictors": preds,
            "covariate_recommended": cov,
            # EB-7: the de-confounded quantity. The bivariate OLS
            # slope of flips on attacked length *adjusted for* the
            # verbosity delta: the length effect with the verbosity
            # confounder partialled out. When the univariate length
            # slope is significant but the adjusted slope is not,
            # verbosity was carrying the effect, not length.
            "adjusted": _adjusted_length_dict(
                _adjusted_length_slice(
                    by_family[fam]["joint"][0],
                    by_family[fam]["joint"][1],
                    by_family[fam]["joint"][2],
                    n_boot, seed + 2)),
        }
    return {
        "alpha": alpha,
        "n_tests": len(tests),
        "n_cases_with_length": len(pairs),
        "by_family": families,
    }


def length_report_text(
    sensitivity: dict[str, Any],
    diagnostics: dict[str, Any] | None = None,
) -> str:
    """Human-readable EB-7/EB-10 length report."""
    lines = [
        "Peira length-sensitivity diagnostics (EB-7 / EB-10)",
        "===================================================",
        f"Cases with attacked-arm length: "
        f"{sensitivity['n_cases_with_length']}",
        "",
        "Per-family flip-on-length slope (OLS, bootstrap 95% CI):",
    ]
    for fam, s in sensitivity["by_family"].items():
        if s["sufficient"]:
            ci = (f"[{s['slope_ci95'][0]:.4f}, "
                  f"{s['slope_ci95'][1]:.4f}]"
                  if s["slope_ci95"] else "CI unavailable")
            lines.append(
                f"  {fam}: n={s['n']}, slope {s['slope']:.4f} {ci}, "
                f"r={s['pearson_r'] if s['pearson_r'] is not None else 'n/a'}"
            )
        else:
            lines.append(f"  {fam}: insufficient data (n={s['n']})")
    if diagnostics is not None:
        lines.append("")
        lines.append(
            f"De-confounding (Holm alpha={diagnostics['alpha']}, "
            f"{diagnostics['n_tests']} tests):"
        )
        roster = []
        for fam, d in diagnostics["by_family"].items():
            flags = []
            for pname, p in d["predictors"].items():
                if p.get("holm_significant") is True:
                    flags.append(pname)
                elif p.get("holm_significant") is None:
                    flags.append(f"{pname}=n/a")
            rec = ("COVARIATE RECOMMENDED" if d["covariate_recommended"]
                   else "no covariate")
            if d["covariate_recommended"]:
                roster.append(fam)
            adj = d.get("adjusted") or {}
            if adj.get("sufficient"):
                ci = adj["length_slope_adjusted_ci95"]
                ci_s = (f"[{ci[0]:.4f}, {ci[1]:.4f}]"
                        if ci else "CI unavailable")
                adj_s = (f", adjusted length slope "
                         f"{adj['length_slope_adjusted']:.4f} {ci_s}")
            else:
                adj_s = ", adjusted slope n/a"
            lines.append(
                f"  {fam}: {rec}"
                + (f" ({', '.join(flags)})" if flags else "")
                + adj_s
            )
        # EB-7: the reported-covariate roster. Length is a reported
        # covariate for these families in all downstream reporting.
        lines.append(
            "Reported covariates: "
            + (", ".join(sorted(roster)) if roster else "none")
        )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# summarize() blocks: JSON-serializable sections for the run summary
# ---------------------------------------------------------------------------


def confidence_erosion_block(
    results: list[PerCaseResult],
) -> dict[str, Any]:
    """EB-23 summarize() section: the per-run erosion table."""
    return confidence_erosion(results)


def length_diagnostics_block(
    results: list[PerCaseResult],
    n_boot: int = LENGTH_BOOTSTRAP_RESAMPLES,
    seed: int = 0,
) -> dict[str, Any]:
    """EB-7/EB-10 summarize() section: per-run length diagnostics.

    Uses the capped resample count (slope quantiles converge
    faster than the tail estimates elsewhere in the summary); the
    resample budget is documented on LENGTH_BOOTSTRAP_RESAMPLES.
    """
    deconf = length_confound_diagnostics(results, n_boot=n_boot, seed=seed)
    return {
        "sensitivity": length_sensitivity(results, n_boot=n_boot,
                                          seed=seed),
        "deconfounding": deconf,
        # EB-7: length becomes a reported covariate for families where
        # the family-level association survives Holm adjustment. This
        # top-level list is the reported-covariate roster; the per-family
        # detail lives in deconfounding["by_family"].
        "covariate_recommended_families": sorted(
            fam for fam, d in deconf.get("by_family", {}).items()
            if d.get("covariate_recommended")),
    }
