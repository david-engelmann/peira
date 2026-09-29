"""Economic lottery index (C-6): ranking stability under cost scenarios.

R-09's lottery index tests whether the *robustness* ranking (conditional
ASR, ascending) survives family removal. But the buyer's ranking is the
*economic* ranking: expected attack cost per decision (``E_attacked``,
M-3) under a versioned cost scenario, ascending. A family with rare but
catastrophic ``deny-to-approve`` flips can account for most of
``E_attacked`` while barely moving headline ASR.

This module computes leave-one-family-out stability on the economic
ranking, once per cost scenario, and always reports the **pair**
``(robustness-stability, economic-stability)``: never a single lottery
index. When the two disagree -- "robustness ranking stable, economic
ranking fragile, family X carries the dollar risk" -- that disagreement
is the finding, not a footnote.

The economic ranking rule: runs are ranked by ``E_attacked`` ascending
(a lower expected attack cost is the better deployment). ``E_attacked``
scales every run by the scenario's attack rate, so for any positive rate
the ranking is invariant to that rate (at rate zero every cost is zero
and the ranking degenerates); the scenario's default rate is used and
documented in the output. Eligibility gates are re-evaluated on each
reduced family set exactly as in R-09, so a run that only qualified
because of the removed family drops out honestly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from peira.economics import (
    CostScenario,
    e_attacked,
    list_cost_scenarios,
    load_cost_scenario,
)
from peira.lottery import (
    kendall_tau,
    lottery_analysis,
    pairwise_swap_fraction,
    stability_verdict,
)
from peira.metrics import PerCaseResult, check_eligibility


@dataclass(frozen=True)
class EconomicRankedRun:
    """One run's position inputs: id, E_attacked, eligibility."""

    run_id: str
    e_attacked: float | None  # None when the run is ineligible
    eligible: bool
    reasons: tuple[str, ...] = ()


def rank_runs_economic(
    results_by_run: Mapping[str, Sequence[PerCaseResult]],
    families: Sequence[str],
    scenario: CostScenario,
) -> list[EconomicRankedRun]:
    """Rank runs by E_attacked (ascending) over ``families``.

    Mirrors :func:`peira.lottery.rank_runs`: only cases whose family is
    in ``families`` count, eligibility is checked with
    ``required_families=families``, and the returned list is ordered
    best-first with ties broken by run_id for determinism. Ineligible
    runs are included with ``eligible=False`` and ``e_attacked=None``.
    """
    fams = list(families)
    if not fams:
        raise ValueError("rank_runs_economic: families must not be empty")
    fam_set = set(fams)
    ranked: list[EconomicRankedRun] = []
    for run_id in results_by_run:
        if not isinstance(run_id, str) or not run_id:
            raise ValueError(
                "rank_runs_economic: run ids must be non-empty strings"
            )
        results = [r for r in results_by_run[run_id] if r.family in fam_set]
        elig = check_eligibility(results, list(fams))
        if elig.eligible:
            est = e_attacked(list(results), scenario)
            ranked.append(
                EconomicRankedRun(
                    run_id=run_id, e_attacked=est.e_attacked, eligible=True
                )
            )
        else:
            ranked.append(
                EconomicRankedRun(
                    run_id=run_id,
                    e_attacked=None,
                    eligible=False,
                    reasons=tuple(elig.reasons),
                )
            )
    eligible_runs = [r for r in ranked if r.eligible]
    eligible_runs.sort(key=lambda r: (r.e_attacked, r.run_id))  # type: ignore[arg-type]
    ineligible = [r for r in ranked if not r.eligible]
    ineligible.sort(key=lambda r: r.run_id)
    return eligible_runs + ineligible


def _positions(order: Sequence[str]) -> dict[str, int]:
    return {run_id: i for i, run_id in enumerate(order)}


def _round4(v: float | None) -> float | None:
    return None if v is None else round(v, 4)


def economic_lottery_analysis(
    results_by_run: Mapping[str, Sequence[PerCaseResult]],
    families: Sequence[str],
    scenario: CostScenario,
) -> dict[str, Any]:
    """Leave-one-family-out stability of the economic ranking.

    Mirrors :func:`peira.lottery.lottery_analysis`: the full economic
    ranking, then one economic ranking per family with that family
    removed (eligibility re-gated on the remaining families), each
    correlated against the full ranking with Kendall's tau.

    Returns a JSON-serializable dict with the scenario identity, the
    full ranking, the economic ``lottery_index`` (mean tau across
    families where tau is defined), the minimum tau and most
    influential family, and per-family detail.

    This returns the economic half of the C-6 pair on its own: the
    never-a-single-index invariant is enforced by
    :func:`paired_stability_report` and by the ``peira lottery
    --economic`` CLI, which always present this index beside the
    robustness index.
    """
    fams = list(families)
    if not fams:
        raise ValueError(
            "economic_lottery_analysis: families must not be empty"
        )
    for run_id in results_by_run:
        if not isinstance(run_id, str) or not run_id:
            raise ValueError(
                "economic_lottery_analysis: run ids must be non-empty strings"
            )

    full = rank_runs_economic(results_by_run, fams, scenario)
    full_order = [r.run_id for r in full if r.eligible]
    full_detail = [
        {
            "run_id": r.run_id,
            "e_attacked": _round4(r.e_attacked),
            "eligible": r.eligible,
            "reasons": list(r.reasons),
        }
        for r in full
    ]

    per_family: dict[str, dict[str, Any]] = {}
    taus: list[float] = []
    for fam in fams:
        reduced_fams = [f for f in fams if f != fam]
        reduced = rank_runs_economic(results_by_run, reduced_fams, scenario)
        reduced_order = [r.run_id for r in reduced if r.eligible]
        tau = kendall_tau(full_order, reduced_order)
        swap = pairwise_swap_fraction(full_order, reduced_order)
        pos_full = _positions(full_order)
        pos_red = _positions(reduced_order)
        common = [r for r in full_order if r in pos_red]
        displacement = (
            max(abs(pos_full[r] - pos_red[r]) for r in common)
            if common
            else None
        )
        if tau is not None:
            taus.append(tau)
        per_family[fam] = {
            "tau": _round4(tau),
            "swap_fraction": _round4(swap),
            "n_common": len(common),
            "max_rank_displacement": displacement,
            "ranking": reduced_order,
            "dropped_runs": sorted(set(full_order) - set(reduced_order)),
        }

    lottery_index = sum(taus) / len(taus) if taus else None
    min_tau: float | None = min(taus) if taus else None
    most_influential: str | None = None
    if taus:
        most_influential = min(
            (f for f in fams if per_family[f]["tau"] is not None),
            key=lambda f: (per_family[f]["tau"], f),
        )

    return {
        "scenario_id": scenario.scenario_id,
        "scenario_version": scenario.version,
        "attack_rate": scenario.baseline_attack_rate,
        "families": fams,
        "n_runs": len(results_by_run),
        "n_ranked": len(full_order),
        "full_ranking": full_order,
        "full_ranking_detail": full_detail,
        "lottery_index": _round4(lottery_index),
        "verdict": stability_verdict(
            lottery_index if lottery_index is None else round(lottery_index, 4)
        ),
        "min_tau": _round4(min_tau),
        "most_influential_family": most_influential,
        "per_family": per_family,
    }


def _fmt_index(v: float | None) -> str:
    return "undefined" if v is None else f"{v:.4f}"


def _family_clause(half: dict[str, Any], half_name: str) -> str | None:
    """Name the family that moves one ranking most, or None.

    Returns None when no family is most influential, or when the most
    influential family's tau is 1.0: naming it would claim it "moves
    the ranking most" when in fact nothing moved.
    """
    fam = half["most_influential_family"]
    if fam is None:
        return None
    if half["per_family"][fam]["tau"] == 1.0:
        return None
    return f"removing '{fam}' moves the {half_name} ranking most"


def _disagreement_note(
    scenario_id: str,
    robustness: dict[str, Any],
    economic: dict[str, Any],
) -> str | None:
    """Explain a robustness/economic verdict disagreement, or None.

    A disagreement means the verdict bands differ: one ranking is
    stable while the other is fragile (or one is undefined). The note
    names both verdicts and the families that move each ranking most,
    because "family X carries the dollar risk" is the actionable
    reading. A half whose ranking did not move at all names no family.
    """
    r_verdict = robustness["verdict"]
    e_verdict = economic["verdict"]
    if r_verdict == e_verdict:
        return None
    r_fam = robustness["most_influential_family"]
    e_fam = economic["most_influential_family"]
    note = (
        f"robustness ranking is {r_verdict} "
        f"(index {_fmt_index(robustness['lottery_index'])}) but the "
        f"economic ranking under scenario '{scenario_id}' is {e_verdict} "
        f"(index {_fmt_index(economic['lottery_index'])})"
    )
    r_clause = _family_clause(robustness, "robustness")
    e_clause = _family_clause(economic, "economic")
    if r_clause is not None and e_clause is not None:
        if r_fam == e_fam:
            note += f"; removing '{r_fam}' moves both rankings most"
        else:
            note += (
                f"; {r_clause}, {e_clause}: "
                f"'{e_fam}' carries the dollar risk"
            )
    elif e_clause is not None:
        note += f"; {e_clause}: '{e_fam}' carries the dollar risk"
    elif r_clause is not None:
        note += f"; {r_clause}"
    return note


def paired_stability_report(
    results_by_run: Mapping[str, Sequence[PerCaseResult]],
    families: Sequence[str],
    scenario_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    """The C-6 paired report: robustness-stability and economic-stability.

    Always returns both halves, never a single lottery index. For each
    cost scenario the report pairs the R-09 robustness lottery index
    (conditional-ASR ranking) with the economic lottery index
    (E_attacked ranking under that scenario) and flags verdict
    disagreements. ``scenario_ids`` defaults to every scenario in the
    versioned scenario file.
    """
    fams = list(families)
    if not fams:
        raise ValueError("paired_stability_report: families must not be empty")
    ids = list(scenario_ids) if scenario_ids is not None else list_cost_scenarios()
    if not ids:
        raise ValueError("paired_stability_report: no cost scenarios given")

    robustness = lottery_analysis(results_by_run, fams)
    economic: dict[str, dict[str, Any]] = {}
    pair: dict[str, dict[str, Any]] = {}
    for sid in ids:
        scenario = load_cost_scenario(sid)  # ValueError on unknown id
        econ = economic_lottery_analysis(results_by_run, fams, scenario)
        economic[sid] = econ
        note = _disagreement_note(sid, robustness, econ)
        pair[sid] = {
            "scenario_id": sid,
            "scenario_version": scenario.version,
            "robustness_index": robustness["lottery_index"],
            "economic_index": econ["lottery_index"],
            "robustness_verdict": robustness["verdict"],
            "economic_verdict": econ["verdict"],
            "robustness_most_influential": robustness["most_influential_family"],
            "economic_most_influential": econ["most_influential_family"],
            "disagree": note is not None,
            "disagreement_note": note,
        }

    return {
        "families": fams,
        "n_runs": len(results_by_run),
        "robustness": robustness,
        "economic": economic,
        "pair": pair,
    }
