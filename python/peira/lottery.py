"""Leave-one-family-out ranking stability ("lottery index").

The Benchmark Lottery critique (Dehghani et al.) argues that benchmark
rankings are fragile: remove one task and the leaderboard shuffles.
Peira answers with its own data. For a set of runs (one row per
adapter/dataset on a leaderboard), this module recomputes the ranking
once per family with that family removed, and measures how much the
ranking moves.

The headline number is the **lottery index**: the mean Kendall's tau
rank correlation between the full ranking and each leave-one-out
ranking. 1.0 means removing any single family leaves the ranking
untouched; lower values mean the ranking depends on which families are
included. Per-family taus identify the most influential families.

Ranking rule (shared with the leaderboard): runs are ranked by
conditional ASR, ascending (a lower attack success rate is a more
robust decision model). Only ranking-eligible runs are ranked; the
eligibility gates are re-evaluated on the reduced family set, so a run
that only qualified because of the removed family drops out honestly
instead of silently keeping its rank.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from peira.metrics import PerCaseResult, asr_conditional, check_eligibility


@dataclass(frozen=True)
class RankedRun:
    """One run's position inputs: id, headline ASR, eligibility."""

    run_id: str
    asr: float | None  # conditional ASR; None when the run is ineligible
    eligible: bool
    reasons: tuple[str, ...] = ()


def rank_runs(
    results_by_run: Mapping[str, Sequence[PerCaseResult]],
    families: Sequence[str],
) -> list[RankedRun]:
    """Rank runs by conditional ASR (ascending) over ``families``.

    ``results_by_run`` maps a run id (adapter/dataset row label) to its
    per-case results. Only cases whose family is in ``families`` count;
    eligibility is checked with ``required_families=families`` so the
    per-family coverage gate applies to exactly the families ranked on.
    The returned list is ordered best-first; ties on ASR break by
    run_id so the order is deterministic. Ineligible runs are included
    with ``eligible=False`` and ``asr=None`` (they never take a rank).
    """
    fams = list(families)
    if not fams:
        raise ValueError("rank_runs: families must not be empty")
    fam_set = set(fams)
    ranked: list[RankedRun] = []
    for run_id in results_by_run:
        if not isinstance(run_id, str) or not run_id:
            raise ValueError("rank_runs: run ids must be non-empty strings")
        results = [r for r in results_by_run[run_id] if r.family in fam_set]
        elig = check_eligibility(results, list(fams))
        if elig.eligible:
            asr, _ = asr_conditional(results)
            ranked.append(RankedRun(run_id=run_id, asr=asr, eligible=True))
        else:
            ranked.append(
                RankedRun(
                    run_id=run_id,
                    asr=None,
                    eligible=False,
                    reasons=tuple(elig.reasons),
                )
            )
    eligible_runs = [r for r in ranked if r.eligible]
    eligible_runs.sort(key=lambda r: (r.asr, r.run_id))  # type: ignore[arg-type]
    ineligible = [r for r in ranked if not r.eligible]
    ineligible.sort(key=lambda r: r.run_id)
    return eligible_runs + ineligible


def _ranking_positions(order: Sequence[str]) -> dict[str, int]:
    return {run_id: i for i, run_id in enumerate(order)}


def kendall_tau(
    rank_a: Sequence[str],
    rank_b: Sequence[str],
) -> float | None:
    """Kendall's tau between two rankings (best-first run-id lists).

    Computed over the intersection of the two rankings: runs ranked in
    only one of the two do not contribute pairs. Each input list holds
    every run id at most once, so there are no ties to adjust for.
    Returns None when fewer than two runs are ranked in both (no pair
    exists to compare).
    """
    set_b = set(rank_b)
    common_a = [r for r in rank_a if r in set_b]
    if len(common_a) < 2:
        return None
    pos_b = _ranking_positions(rank_b)
    # Count concordant/discordant pairs of common_a's order vs rank_b's.
    # common_a is in rank_a order; map to rank_b positions and count
    # inversions: a pair (i<j) is concordant iff pos_b[a_i] < pos_b[a_j].
    b_positions = [pos_b[r] for r in common_a]
    concordant = 0
    discordant = 0
    n = len(b_positions)
    for i in range(n):
        for j in range(i + 1, n):
            if b_positions[i] < b_positions[j]:
                concordant += 1
            elif b_positions[i] > b_positions[j]:
                discordant += 1
    total = concordant + discordant
    if total == 0:
        return None
    return (concordant - discordant) / total


def pairwise_swap_fraction(
    rank_a: Sequence[str],
    rank_b: Sequence[str],
) -> float | None:
    """Fraction of common pairs whose relative order differs.

    A more literal "how much did the ranking move" companion to tau:
    0.0 means identical order, 1.0 means fully reversed. None when
    fewer than two runs are ranked in both.
    """
    set_b = set(rank_b)
    common_a = [r for r in rank_a if r in set_b]
    if len(common_a) < 2:
        return None
    pos_b = _ranking_positions(rank_b)
    b_positions = [pos_b[r] for r in common_a]
    discordant = 0
    total = 0
    n = len(b_positions)
    for i in range(n):
        for j in range(i + 1, n):
            total += 1
            if b_positions[i] > b_positions[j]:
                discordant += 1
    return discordant / total if total else None


def _round4(v: float | None) -> float | None:
    return None if v is None else round(v, 4)


def stability_verdict(lottery_index: float | None) -> str:
    """One-word verdict for a lottery index.

    Bands: >= 0.9 "stable", >= 0.7 "mostly stable", below "fragile",
    None "undefined". The bands are coarse on purpose: the index is a
    summary, not a gate: the per-family taus carry the detail.
    """
    if lottery_index is None:
        return "undefined"
    if lottery_index >= 0.9:
        return "stable"
    if lottery_index >= 0.7:
        return "mostly stable"
    return "fragile"


def lottery_analysis(
    results_by_run: Mapping[str, Sequence[PerCaseResult]],
    families: Sequence[str],
) -> dict[str, Any]:
    """Leave-one-family-out ranking stability over ``families``.

    Computes the full ranking, then one ranking per family with that
    family removed (eligibility re-gated on the remaining families),
    and correlates each reduced ranking against the full ranking with
    Kendall's tau.

    Returns a JSON-serializable dict with the full ranking, the
    ``lottery_index`` (mean tau across families where tau is defined;
    None when no family yields a comparable pair), the minimum tau and
    most influential family, and per-family detail (tau, swap
    fraction, reduced ranking, common-run count, max rank
    displacement).
    """
    fams = list(families)
    if not fams:
        raise ValueError("lottery_analysis: families must not be empty")
    for run_id in results_by_run:
        if not isinstance(run_id, str) or not run_id:
            raise ValueError(
                "lottery_analysis: run ids must be non-empty strings"
            )

    full = rank_runs(results_by_run, fams)
    full_order = [r.run_id for r in full if r.eligible]
    full_detail = [
        {
            "run_id": r.run_id,
            "asr": _round4(r.asr),
            "eligible": r.eligible,
            "reasons": list(r.reasons),
        }
        for r in full
    ]

    per_family: dict[str, dict[str, Any]] = {}
    taus: list[float] = []
    for fam in fams:
        reduced_fams = [f for f in fams if f != fam]
        reduced = rank_runs(results_by_run, reduced_fams)
        reduced_order = [r.run_id for r in reduced if r.eligible]
        tau = kendall_tau(full_order, reduced_order)
        swap = pairwise_swap_fraction(full_order, reduced_order)
        pos_full = _ranking_positions(full_order)
        pos_red = _ranking_positions(reduced_order)
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
        # The family whose removal moves the ranking most (lowest tau;
        # ties break by family name for determinism).
        most_influential = min(
            (f for f in fams if per_family[f]["tau"] is not None),
            key=lambda f: (per_family[f]["tau"], f),
        )

    return {
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
