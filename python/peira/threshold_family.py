"""Threshold-by-family interaction (C-7): optimal review thresholds per family.

A review policy routes a case to human review iff its risk score
(``1 - confidence``) is >= pt. R-08's buyer-cost model prices that
policy: reviewed cases cost ``cost_review`` each; trusted cases cost
nothing when correct and ``cost_false_approve`` / ``cost_false_deny``
when the trusted output is wrong in that direction.

This module asks the interaction question: does the buyer do better
with one global threshold or a threshold per attack family? For each
family it finds the threshold minimizing expected cost per case on the
buyer's cost numbers, finds the same optimum on the pooled (all-family)
data, and reports the gain from family-specific thresholding. Families
whose gain is positive are the ones that justify their own threshold;
the table carries the magnitudes so the reader judges materiality,
not a verdict band.

Cost model, not net benefit: outputs are dollars per case, never
Vickers-Elkin net benefit. Python-only: no Rust port.
"""

from __future__ import annotations

from typing import Any, Mapping

from peira import families as _families
from peira.metrics import (
    DEFAULT_NB_THRESHOLDS,
    PerCaseResult,
    _check_threshold,
    _round4,
    buyer_cost_at_threshold,
)


def _check_costs(
    cost_false_approve: float,
    cost_false_deny: float,
    cost_review: float,
    cost_false_unknown: float | None,
) -> float:
    """Validate buyer costs; return the resolved cost_false_unknown."""
    for name, v in (
        ("cost_false_approve", cost_false_approve),
        ("cost_false_deny", cost_false_deny),
        ("cost_review", cost_review),
    ):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError(f"{name} must be a number, got {v!r}")
        if not (v == v and v != float("inf") and v != float("-inf")) or v < 0:
            raise ValueError(
                f"{name} must be finite and non-negative, got {v!r}"
            )
    if cost_false_unknown is None:
        return (cost_false_approve + cost_false_deny) / 2.0
    if (
        isinstance(cost_false_unknown, bool)
        or not isinstance(cost_false_unknown, (int, float))
    ):
        raise ValueError(
            "cost_false_unknown must be a number, "
            f"got {cost_false_unknown!r}"
        )
    if (
        not (
            cost_false_unknown == cost_false_unknown
            and cost_false_unknown != float("inf")
            and cost_false_unknown != float("-inf")
        )
        or cost_false_unknown < 0
    ):
        raise ValueError(
            "cost_false_unknown must be finite and non-negative, "
            f"got {cost_false_unknown!r}"
        )
    return cost_false_unknown


def _check_grid(
    thresholds: list[float] | tuple[float, ...] | None,
) -> list[float]:
    """Validate and sort the threshold grid."""
    if thresholds is None:
        return list(DEFAULT_NB_THRESHOLDS)
    grid = list(thresholds)
    if not grid:
        raise ValueError("thresholds must be non-empty")
    for pt in grid:
        _check_threshold(pt, "thresholds")
    grid.sort()
    return grid


def _optimal_on_grid(
    curve: list[tuple[float, float | None]],
) -> tuple[float | None, float | None]:
    """Argmin cost over a ``(pt, cost_per_case)`` curve.

    Returns ``(optimal_pt, min_cost)``. Ties break toward the larger
    threshold: at equal expected cost the buyer prefers the fewest
    reviews (lower operational burden). Points with unresolvable cost
    (None: no priced cases) never win. An all-None curve returns
    ``(None, None)``: the optimum is withheld, not zero.
    """
    best_pt: float | None = None
    best_cost: float | None = None
    for pt, cost in curve:
        if cost is None:
            continue
        if best_cost is None or cost < best_cost or (
            cost == best_cost and pt > best_pt  # type: ignore[operator]
        ):
            best_pt = pt
            best_cost = cost
    return best_pt, best_cost


def _cost_curve(
    results: list[PerCaseResult],
    grid: list[float],
    *,
    cost_false_approve: float,
    cost_false_deny: float,
    cost_review: float,
    cost_false_unknown: float,
    arm: str,
    expected_decisions: Mapping[str, str] | None,
) -> tuple[list[tuple[float, float | None]], int, int]:
    """``(pt, cost_per_case)`` over the grid plus considered/priced counts."""
    curve: list[tuple[float, float | None]] = []
    considered = 0
    priced = 0
    for pt in grid:
        block = buyer_cost_at_threshold(
            results,
            pt,
            cost_false_approve=cost_false_approve,
            cost_false_deny=cost_false_deny,
            cost_review=cost_review,
            cost_false_unknown=cost_false_unknown,
            arm=arm,
            expected_decisions=expected_decisions,
        )
        curve.append((pt, block["cost_per_case"]))
        considered = block["considered"]
        priced = block["considered"] - block["excluded"]["ineligible"]
    return curve, considered, priced


def family_threshold_table(
    results: list[PerCaseResult],
    *,
    cost_false_approve: float,
    cost_false_deny: float,
    cost_review: float,
    cost_false_unknown: float | None = None,
    thresholds: list[float] | tuple[float, ...] | None = None,
    arm: str = "attacked",
    expected_decisions: Mapping[str, str] | None = None,
    families: list[str] | None = None,
) -> dict[str, Any]:
    """Optimal review threshold per family under buyer-cost economics.

    For each family (and once on the pooled results): sweep the
    threshold grid through R-08's
    :func:`~peira.metrics.buyer_cost_at_threshold` and take the
    cost-minimizing threshold. The interaction table then prices every
    family at both its own optimum and the global optimum; the
    ``gain_per_case`` column is the per-case saving from
    family-specific thresholding (always >= 0: the family optimum
    minimizes over the same grid).

    ``families`` restricts the table to the given families (ValueError
    on any family absent from ``results``); the default is the sorted
    union present in ``results``. Families with no priced cases report
    None costs and optima: unresolvable, not free.

    Returns a JSON-serializable dict with ``global`` (pooled optimum),
    ``families`` (per-family rows incl. the full cost curve), and
    ``families_justifying_specific`` (positive-gain families, sorted by
    total gain descending). All costs name the inputs that produced
    them; this is a cost model, not net benefit.
    """
    resolved_unknown = _check_costs(
        cost_false_approve, cost_false_deny, cost_review, cost_false_unknown
    )
    grid = _check_grid(thresholds)

    present = sorted({r.family for r in results})
    if families is None:
        wanted = present
    else:
        wanted = list(families)
        unknown = [f for f in wanted if f not in present]
        if unknown:
            raise ValueError(
                "families not present in results: "
                + ", ".join(sorted(set(unknown)))
            )

    common = dict(
        cost_false_approve=cost_false_approve,
        cost_false_deny=cost_false_deny,
        cost_review=cost_review,
        cost_false_unknown=resolved_unknown,
        arm=arm,
        expected_decisions=expected_decisions,
    )

    global_curve, g_considered, g_priced = _cost_curve(results, grid, **common)
    global_pt, global_cost = _optimal_on_grid(global_curve)

    family_rows: dict[str, dict[str, Any]] = {}
    for family_id in wanted:
        fam_results = [r for r in results if r.family == family_id]
        curve, considered, priced = _cost_curve(fam_results, grid, **common)
        opt_pt, opt_cost = _optimal_on_grid(curve)
        if opt_cost is None or global_pt is None:
            cost_at_global: float | None = None
            gain_per_case: float | None = None
            gain_total: float | None = None
        else:
            cost_at_global = dict(curve)[global_pt]
            gain_per_case = _round4(cost_at_global - opt_cost)  # type: ignore[operator]
            gain_total = (
                _round4(gain_per_case * priced)
                if gain_per_case is not None
                else None
            )
        family_rows[family_id] = {
            "family_id": family_id,
            "display_name": _families.display_name(family_id),
            "considered": considered,
            "priced": priced,
            "optimal_threshold": opt_pt,
            "cost_at_family_optimal": _round4(opt_cost),
            "cost_at_global_threshold": _round4(cost_at_global),
            "gain_per_case": gain_per_case,
            "gain_total": gain_total,
            "curve": [(pt, _round4(c)) for pt, c in curve],
        }

    justifying = sorted(
        (
            fid
            for fid, row in family_rows.items()
            if row["gain_per_case"] is not None and row["gain_per_case"] > 0
        ),
        key=lambda fid: (
            -(family_rows[fid]["gain_total"] or 0.0),
            fid,
        ),
    )

    return {
        "arm": arm,
        "costs": {
            "cost_false_approve": cost_false_approve,
            "cost_false_deny": cost_false_deny,
            "cost_review": cost_review,
            "cost_false_unknown": resolved_unknown,
        },
        "threshold_grid": grid,
        "global": {
            "optimal_threshold": global_pt,
            "cost_per_case": _round4(global_cost),
            "considered": g_considered,
            "priced": g_priced,
            "curve": [(pt, _round4(c)) for pt, c in global_curve],
        },
        "families": family_rows,
        "families_justifying_specific": justifying,
    }
