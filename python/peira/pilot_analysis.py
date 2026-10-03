"""Pilot-run analysis framework: deep analysis over sealed v2 run artifacts.

This module consumes the pilot results (8 vendors + local models on the
v2 suite) and produces publication-ready analysis:

- ``load_pilot_runs``: scan the run registry for qualifying v2 runs.
- ``family_matrix``: per-model x per-family ASR + CI matrix.
- ``attack_effectiveness``: which families flip which models most.
- ``pairwise_significance``: McNemar + Benjamini-Hochberg across all pairs.
- ``ranking_analysis``: Friedman + Nemenyi for multi-model ranking.
- ``cost_effectiveness``: $ per correct decision, cost per flip prevented.

All functions are pure (no I/O except ``load_pilot_runs``) and return
JSON-serializable dicts. Every number is computed from real artifact
data, never estimated.

Design notes:
- Works from ``dashboard.run_to_dashboard`` payloads, the canonical
  aggregate. Per-case drill-down goes through ``runs_registry``.
- Pairwise tests use ``compare.compare_artifacts`` on the sealed
  artifacts (McNemar on paired per-case outcomes).
- Cost comes from the artifact's sealed pricing provenance.
"""

from __future__ import annotations

import itertools
from pathlib import Path
from typing import Any

from peira.artifacts import RunArtifact
from peira import dashboard
from peira import compare
from peira import metrics
from peira import runs_registry


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_pilot_runs(
    runs_dir: str | Path | None = None,
    suite: str = "v2",
) -> list[dict[str, Any]]:
    """Load all qualifying v2 runs as analysis-ready records.

    Each record carries the sealed artifact, its dashboard payload, and
    identity metadata. Only runs passing ``qualifies_for_leaderboard``
    are included; budget-terminated or partial runs are excluded from
    ranking analysis (they are analyzable but never rankable).
    """
    runs = runs_registry.list_runs(runs_dir=runs_dir)
    records = []
    for r in runs:
        if r.get("suite") != suite:
            continue
        if r.get("termination") != "complete":
            continue
        path = r.get("path")
        if not path:
            continue
        try:
            artifact = RunArtifact.load(Path(path))
        except Exception:
            continue
        if not runs_registry.qualifies_for_leaderboard(artifact):
            continue
        try:
            payload = dashboard.run_to_dashboard(artifact)
        except ValueError:
            continue
        records.append({
            "adapter_name": artifact.adapter_name,
            "adapter_version": artifact.adapter_version,
            "run_id": artifact.run_id,
            "path": path,
            "artifact": artifact,
            "dashboard": payload,
        })
    # Deterministic order: sort by adapter name for reproducible output.
    records.sort(key=lambda r: (r["adapter_name"] or "", r["adapter_version"] or ""))
    return records


def _headline(rec: dict[str, Any]) -> dict[str, Any]:
    return rec["dashboard"].get("headline", {})


def _families(rec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return rec["dashboard"].get("families", {})


# ---------------------------------------------------------------------------
# Family matrix: per-model x per-family ASR + CI
# ---------------------------------------------------------------------------

def family_matrix(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-model x per-family attack-success-rate matrix with CIs.

    Returns the sorted family list, per-model rows, and the column
    means (mean ASR per family across models) for the heatmap.
    """
    families: list[str] = sorted({
        fam for rec in records for fam in _families(rec)
    })
    rows = []
    for rec in records:
        fams = _families(rec)
        cells = {}
        for fam in families:
            f = fams.get(fam, {})
            cells[fam] = {
                "asr": f.get("asr"),
                "asr_ci95": f.get("asr_ci95"),
                "n_eligible": f.get("n_eligible"),
                "n": f.get("n"),
            }
        rows.append({
            "adapter_name": rec["adapter_name"],
            "adapter_version": rec["adapter_version"],
            "cells": cells,
        })
    # Column means over models that reported the family.
    col_mean = {}
    for fam in families:
        vals = [
            r["cells"][fam]["asr"] for r in rows
            if isinstance(r["cells"][fam].get("asr"), (int, float))
        ]
        col_mean[fam] = sum(vals) / len(vals) if vals else None
    return {"families": families, "rows": rows, "column_mean_asr": col_mean}


# ---------------------------------------------------------------------------
# Attack effectiveness: which families flip which models most
# ---------------------------------------------------------------------------

def attack_effectiveness(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Rank families by mean ASR across models (most effective attacks).

    Also reports per-model weakest families (highest ASR = the attacks
    that model is most vulnerable to) and the overall hardest family.
    """
    mat = family_matrix(records)
    families = mat["families"]
    # Most effective attacks: highest mean ASR first.
    ranked = sorted(
        ((fam, mat["column_mean_asr"][fam]) for fam in families),
        key=lambda kv: (kv[1] is None, -(kv[1] or 0.0)),
    )
    per_model_weakest = []
    for row in mat["rows"]:
        fam_asr = [
            (fam, row["cells"][fam]["asr"]) for fam in families
            if isinstance(row["cells"][fam].get("asr"), (int, float))
        ]
        fam_asr.sort(key=lambda kv: -kv[1])
        per_model_weakest.append({
            "adapter_name": row["adapter_name"],
            "weakest_families": [
                {"family": fam, "asr": asr} for fam, asr in fam_asr[:3]
            ],
            "strongest_families": [
                {"family": fam, "asr": asr} for fam, asr in fam_asr[-3:][::-1]
            ],
        })
    return {
        "most_effective_attacks": [
            {"family": fam, "mean_asr": mean} for fam, mean in ranked
        ],
        "per_model": per_model_weakest,
    }


# ---------------------------------------------------------------------------
# Pairwise significance: McNemar + Benjamini-Hochberg
# ---------------------------------------------------------------------------

def pairwise_significance(
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    """All-pairs McNemar tests with BH FDR correction.

    Uses ``compare_artifacts`` on each pair of sealed artifacts. The
    McNemar p-value follows the R-07 three-tier rule; pairs with too
    few discordant pairs report p=None (withheld, not zero).
    """
    pairs = []
    raw_p: list[float] = []
    pair_keys: list[tuple[int, int]] = []
    for i, j in itertools.combinations(range(len(records)), 2):
        a, b = records[i]["artifact"], records[j]["artifact"]
        try:
            cmp = compare.compare_artifacts(a, b)
        except ValueError:
            continue
        mcn = cmp.mcnemar or {}
        p = mcn.get("p_value")
        pairs.append({
            "adapter_a": records[i]["adapter_name"],
            "adapter_b": records[j]["adapter_name"],
            "n_paired": cmp.n_paired,
            "mcnemar_stat": mcn.get("statistic"),
            "p_value": p,
            "p_value_adjusted": None,  # filled after BH
            "significant_at_05": None,
        })
        if p is not None:
            raw_p.append(p)
            pair_keys.append((len(pairs) - 1,))
    # BH over the non-withheld p-values only.
    if raw_p:
        adj = metrics.bh_adjust(raw_p)
        for (idx,), a in zip(pair_keys, adj):
            pairs[idx]["p_value_adjusted"] = a
            pairs[idx]["significant_at_05"] = a < 0.05
    return {"pairs": pairs, "n_models": len(records)}


# ---------------------------------------------------------------------------
# Ranking: Friedman + Nemenyi
# ---------------------------------------------------------------------------

def ranking_analysis(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Multi-model ranking via Friedman test + Nemenyi post-hoc.

    Blocks are families (each model ranked within each family by ASR,
    lower = better). Returns the Friedman p-value, the Nemenyi critical
    difference, mean ranks, and which pairs differ significantly.
    """
    mat = family_matrix(records)
    families = mat["families"]
    rows = mat["rows"]
    k = len(rows)
    if k < 2 or not families:
        return {"error": "need at least 2 models and 1 family"}
    # Build rank matrix: rows=models, cols=families. Lower ASR = rank 1.
    rank_matrix: list[list[float]] = []
    valid_families = []
    for fam in families:
        col = []
        for row in rows:
            asr = row["cells"][fam].get("asr")
            col.append(asr if isinstance(asr, (int, float)) else None)
        if all(v is None for v in col):
            continue
        # Rank with average ties; missing -> worst rank.
        valid_families.append(fam)
        order = sorted(
            range(k),
            key=lambda i: (col[i] is None, col[i] if col[i] is not None else 0.0),
        )
        ranks = [0.0] * k
        i = 0
        while i < k:
            j = i
            while j + 1 < k and col[order[j + 1]] == col[order[i]]:
                j += 1
            avg_rank = (i + j) / 2.0 + 1.0
            for t in range(i, j + 1):
                ranks[order[t]] = avg_rank
            i = j + 1
        rank_matrix.append(ranks)
    n = len(rank_matrix)  # blocks
    if n == 0:
        return {"error": "no family with ASR data"}
    # Mean rank per model.
    mean_ranks = [
        sum(rank_matrix[b][m] for b in range(n)) / n for m in range(k)
    ]
    try:
        friedman_stat, friedman_p = metrics.friedman_test(
            [[rank_matrix[b][m] for b in range(n)] for m in range(k)]
        )
    except Exception:
        friedman_stat, friedman_p = None, None
    try:
        cd = metrics.nemenyi_cd(k, n, alpha=0.05)
    except Exception:
        cd = None
    sig_pairs = []
    if cd is not None:
        for i, j in itertools.combinations(range(k), 2):
            if abs(mean_ranks[i] - mean_ranks[j]) > cd:
                sig_pairs.append({
                    "adapter_a": rows[i]["adapter_name"],
                    "adapter_b": rows[j]["adapter_name"],
                    "rank_diff": abs(mean_ranks[i] - mean_ranks[j]),
                    "critical_difference": cd,
                })
    return {
        "n_models": k,
        "n_blocks": n,
        "families_used": valid_families,
        "mean_ranks": [
            {"adapter_name": rows[m]["adapter_name"], "mean_rank": mean_ranks[m]}
            for m in range(k)
        ],
        "friedman_statistic": friedman_stat,
        "friedman_p_value": friedman_p,
        "nemenyi_cd_05": cd,
        "significant_pairs": sig_pairs,
    }


# ---------------------------------------------------------------------------
# Cost effectiveness
# ---------------------------------------------------------------------------

def cost_effectiveness(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Cost per correct decision and cost per flip prevented.

    - ``cost_per_decision``: total USD / eligible decisions.
    - ``cost_per_correct``: total USD / correct decisions (benign correct
      + attacked correctly rejected). Lower is better.
    - ``flip_prevention_value``: flips prevented per dollar vs the
      worst model (a relative efficiency, not an absolute claim).
    """
    rows = []
    for rec in records:
        h = _headline(rec)
        cost = h.get("total_cost_usd")
        n_elig = h.get("n_eligible")
        benign_acc = h.get("benign_accuracy")
        asr = h.get("asr_conditional")
        row: dict[str, Any] = {
            "adapter_name": rec["adapter_name"],
            "total_cost_usd": cost,
            "n_eligible": n_elig,
        }
        if isinstance(cost, (int, float)) and isinstance(n_elig, (int, float)) and n_elig > 0:
            row["cost_per_decision"] = cost / n_elig
            # Correct decisions: benign correct + attacked not flipped.
            n_correct = None
            if isinstance(benign_acc, (int, float)) and isinstance(asr, (int, float)):
                # benign_acc and asr are rates; n_correct needs counts.
                # Use eligible n as the base for both arms (paired design).
                n_correct = n_elig * benign_acc + n_elig * (1.0 - asr)
                row["cost_per_correct"] = cost / n_correct if n_correct > 0 else None
            else:
                row["cost_per_correct"] = None
        else:
            row["cost_per_decision"] = None
            row["cost_per_correct"] = None
        # Flip rate for the prevention comparison.
        fams = _families(rec)
        asrs = [
            f.get("asr") for f in fams.values()
            if isinstance(f.get("asr"), (int, float))
        ]
        row["mean_asr"] = sum(asrs) / len(asrs) if asrs else None
        rows.append(row)
    # Relative flip-prevention efficiency vs the worst (highest ASR) model.
    worst_asr = max(
        (r["mean_asr"] for r in rows if isinstance(r.get("mean_asr"), (int, float))),
        default=None,
    )
    for r in rows:
        if (
            worst_asr is not None
            and isinstance(r.get("mean_asr"), (int, float))
            and isinstance(r.get("total_cost_usd"), (int, float))
            and r["total_cost_usd"] > 0
        ):
            prevented = worst_asr - r["mean_asr"]  # ASR points prevented
            r["flips_prevented_per_dollar"] = (
                prevented / r["total_cost_usd"] if prevented > 0 else 0.0
            )
        else:
            r["flips_prevented_per_dollar"] = None
    # Sort by cost per correct decision (cheapest first).
    rows.sort(key=lambda r: (
        r["cost_per_correct"] is None,
        r["cost_per_correct"] if r["cost_per_correct"] is not None else 0.0,
    ))
    return {"rows": rows, "worst_mean_asr": worst_asr}


# ---------------------------------------------------------------------------
# Full pilot report assembly
# ---------------------------------------------------------------------------

def analyze_pilot(runs_dir: str | Path | None = None) -> dict[str, Any]:
    """Run the complete pilot analysis. Returns the full report dict."""
    records = load_pilot_runs(runs_dir)
    # Strip artifacts for JSON-serializability in the summary; the
    # pairwise step needs them, so run it before stripping.
    pairwise = pairwise_significance(records)
    ranking = ranking_analysis(records)
    report = {
        "n_models": len(records),
        "models": [
            {
                "adapter_name": r["adapter_name"],
                "adapter_version": r["adapter_version"],
                "run_id": r["run_id"],
            }
            for r in records
        ],
        "family_matrix": family_matrix(records),
        "attack_effectiveness": attack_effectiveness(records),
        "pairwise_significance": pairwise,
        "ranking": ranking,
        "cost_effectiveness": cost_effectiveness(records),
    }
    return report
