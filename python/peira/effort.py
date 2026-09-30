"""Reasoning effort as a first-class primitive.

This module owns the normalized representation of provider reasoning /
thinking effort controls, and the effort-aware analysis built on top of
run records. Provider capability metadata reflects official provider
documentation as of September 2026.

Two facts shape the whole design:

1. Provider ladders are genuinely different (Anthropic low..max with
   xhigh; OpenAI none..max with minimal; DeepSeek low/high/max; Gemini
   named levels OR raw token budgets; Mistral binary high/none; Qwen token
   caps). There is no universal ladder to normalize onto.
2. Reasoning/thinking tokens are billed at OUTPUT rates on every provider
   with an explicit billing statement, as a subset of reported output
   tokens. They are never double-counted in pricing.

So the primitive carries BOTH:

- the provider-native value (``effort_native``), never lost and never
  collapsed — ``xhigh`` stays ``xhigh``, it is not folded into ``high``;
- a normalized tier (``effort_tier``) for cross-model grouping, mapped
  injectively per provider (two distinct native values never share a
  tier).

Budget-based models (Gemini 2.5 ``thinkingBudget``, Qwen
``thinking_budget``) carry native ``"budget:<n>"`` with tier None: they
are ordered by budget value in analysis, never forced onto the ladder.

Tiers are a grouping aid, not a commensurability claim: "high" on
Anthropic is not "high" on OpenAI. Analysis output always labels both.
"""

from __future__ import annotations

from typing import Any

# Normalized tiers. Every provider-native value maps onto exactly one of
# these (or None for budget-based controls). The mapping is injective per
# provider: no two distinct native values of one provider share a tier.
EFFORT_TIERS: tuple[str, ...] = (
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
)

_TIER_RANK: dict[str, int] = {tier: i for i, tier in enumerate(EFFORT_TIERS)}


def tier_rank(tier: str | None) -> int | None:
    """Rank of a normalized tier (0 = least effort), None when unknown."""
    if tier is None:
        return None
    return _TIER_RANK.get(tier)


# Provider key -> {native value -> normalized tier}. Sourced from the
# September 2026 provider survey of official docs. "none" is the
# disabled/minimal-thinking state where the provider exposes one.
PROVIDER_EFFORT_MAP: dict[str, dict[str, str]] = {
    "anthropic": {
        "low": "low",
        "medium": "medium",
        "high": "high",
        "xhigh": "xhigh",
        "max": "max",
    },
    "openai": {
        "none": "none",
        "minimal": "minimal",
        "low": "low",
        "medium": "medium",
        "high": "high",
        "xhigh": "xhigh",
        "max": "max",
    },
    "deepseek": {
        # Chat format disables via thinking.type; the Responses format
        # uses effort "none". Both normalize to the "none" tier.
        "none": "none",
        "low": "low",
        "high": "high",
        "max": "max",
    },
    "google": {
        "minimal": "minimal",
        "low": "low",
        "medium": "medium",
        "high": "high",
    },
    "xai": {
        "low": "low",
        "medium": "medium",
        "high": "high",
        "xhigh": "xhigh",
    },
    "mistral": {
        "none": "none",
        "high": "high",
    },
}

# Provider key -> {alias -> canonical native value}. Aliases are resolved
# before tier mapping so records always carry the canonical native value.
# DeepSeek documents these compatibility aliases (survey, 2026-09-29).
PROVIDER_EFFORT_ALIASES: dict[str, dict[str, str]] = {
    "deepseek": {
        "minimal": "low",
        "medium": "high",
        "xhigh": "high",
        "ultra": "max",
    },
}


def normalize_effort(provider: str, native: str | None) -> str | None:
    """Map a provider-native effort value to its normalized tier.

    Returns None for None input (not requested) and for budget-based
    native values (``"budget:<n>"``), which have no tier. Raises
    KeyError for an unknown provider key and ValueError for a native
    value outside that provider's documented ladder — both are adapter
    bugs, never silently coerced.
    """
    if native is None:
        return None
    if _is_budget_native(native):
        return None
    try:
        ladder = PROVIDER_EFFORT_MAP[provider]
    except KeyError:
        raise KeyError(f"unknown effort provider: {provider!r}")
    canonical = PROVIDER_EFFORT_ALIASES.get(provider, {}).get(native, native)
    try:
        return ladder[canonical]
    except KeyError:
        raise ValueError(
            f"unknown effort value {native!r} for provider {provider!r} "
            f"(expected one of {sorted(ladder)} or an alias)"
        )


def canonical_native(provider: str, native: str | None) -> str | None:
    """Resolve provider aliases to the canonical native value."""
    if native is None or _is_budget_native(native):
        return native
    return PROVIDER_EFFORT_ALIASES.get(provider, {}).get(native, native)


def _is_budget_native(native: str) -> bool:
    """True for ``"budget:<n>"`` native values (token-budget controls)."""
    if not native.startswith("budget:"):
        return False
    try:
        n = int(native.split(":", 1)[1])
    except (ValueError, IndexError):
        return False
    return n >= 0


def budget_native(budget: int) -> str:
    """Native value for a token-budget effort control."""
    if isinstance(budget, bool) or not isinstance(budget, int) or budget < 0:
        raise ValueError(
            f"thinking budget must be a non-negative int, got {budget!r}"
        )
    return f"budget:{budget}"


def effort_sort_key(native: str | None, tier: str | None) -> tuple[int, int, str]:
    """Sort key ordering effort levels for curves and tables.

    Tier levels sort by rank; budget-based values sort by budget after the
    tier ladder; unrecognized non-empty natives sort next; unset
    (provider default, ``""``/None) sorts last as its own group — it is
    a real measurement point but not on the ladder, and placing it with
    the ranked levels would invent a rank the provider never stated.
    """
    native = native or ""
    if tier is not None and tier in _TIER_RANK:
        return (0, _TIER_RANK[tier], native)
    if _is_budget_native(native):
        return (1, int(native.split(":", 1)[1]), native)
    if native:
        return (2, 0, native)
    return (3, 0, "")


# ---------------------------------------------------------------------------
# Effort-aware analysis over run records.
#
# All functions take plain run-metadata dicts shaped like the registry's
# list_runs rows (keys: adapter_name, adapter_version, effort,
# effort_tier, run_id, ...) plus a "metrics" key holding the top-level
# metrics.summarize() payload for that run:
#
#   n_cases, n_eligible,
#   asr_conditional (fraction), asr_ci95 [lo, hi] (fractions),
#   asr_unconditional (fraction), asr_unconditional_ci95 [lo, hi],
#   cost.total_cost_usd
#
# Per-family analysis takes rows shaped like
# runs_registry.get_family_results output (keys: adapter_name,
# adapter_version, effort, effort_tier, family, n, n_eligible, asr,
# asr_lo, asr_hi, refusal_rate). All functions return plain
# dicts/lists. No I/O, no provider calls, no significance claims beyond
# what the intervals show.
# ---------------------------------------------------------------------------


def _num(v: Any) -> float | None:
    """A JSON number as float; bools and non-numbers become None."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


def _ci_pair(metrics: dict[str, Any], key: str) -> tuple[float | None, float | None]:
    pair = metrics.get(key)
    if not isinstance(pair, (list, tuple)) or len(pair) != 2:
        return None, None
    return _num(pair[0]), _num(pair[1])


def _metrics_of(run: dict[str, Any]) -> dict[str, Any]:
    metrics = run.get("metrics") or {}
    return metrics if isinstance(metrics, dict) else {}


def _asr_of(run: dict[str, Any]) -> tuple[float | None, float | None, float | None]:
    """(asr_conditional, lo, hi) from the run's metrics payload."""
    metrics = _metrics_of(run)
    return _num(metrics.get("asr_conditional")), *_ci_pair(metrics, "asr_ci95")


def _unconditional_asr_of(
    run: dict[str, Any],
) -> tuple[float | None, float | None, float | None]:
    """(asr_unconditional, lo, hi) from the run's metrics payload."""
    metrics = _metrics_of(run)
    return _num(metrics.get("asr_unconditional")), *_ci_pair(
        metrics, "asr_unconditional_ci95"
    )


def _cost_of(run: dict[str, Any]) -> float | None:
    """Total measured run cost in USD (reasoning tokens already inside)."""
    metrics = _metrics_of(run)
    cost = metrics.get("cost") or {}
    if not isinstance(cost, dict):
        return None
    return _num(cost.get("total_cost_usd"))


def _counts_of(run: dict[str, Any]) -> tuple[int | None, int | None]:
    """(n_cases, n_eligible) from the run's metrics payload."""
    metrics = _metrics_of(run)
    n_cases = metrics.get("n_cases")
    n_eligible = metrics.get("n_eligible")
    if isinstance(n_cases, bool) or not isinstance(n_cases, int):
        n_cases = None
    if isinstance(n_eligible, bool) or not isinstance(n_eligible, int):
        n_eligible = None
    return n_cases, n_eligible


def _model_key(run: dict[str, Any]) -> tuple[str, str]:
    """Group within-model runs: strip the effort suffix from the version.

    Explicit effort is part of the adapter version
    (``model@effort=<native>``), so same-model different-effort runs
    share the version prefix before ``@effort=``. Runs whose version
    carries no suffix (provider default) group on the full version.
    """
    version = str(run.get("adapter_version") or "")
    base = version.split("@effort=", 1)[0]
    return (str(run.get("adapter_name") or ""), base)


def effort_curve(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Within-model effort curve: one row per run.

    Repeated runs at the same effort level stay as separate rows — they
    are measurements, not a single point. Rows carry adapter_name,
    adapter_version, run_id, effort_native, effort_tier, n_cases,
    n_eligible, asr (+ CI), asr_unconditional (+ CI), and cost_usd,
    ordered by :func:`effort_sort_key` then run identity. Runs missing
    ASR are still listed (asr None) so gaps are visible, never silently
    dropped.
    """
    rows: list[dict[str, Any]] = []
    for run in runs:
        asr, lo, hi = _asr_of(run)
        uasr, ulo, uhi = _unconditional_asr_of(run)
        n_cases, n_eligible = _counts_of(run)
        rows.append(
            {
                "adapter_name": run.get("adapter_name", ""),
                "adapter_version": run.get("adapter_version", ""),
                "run_id": run.get("run_id", ""),
                "effort_native": run.get("effort") or "",
                "effort_tier": run.get("effort_tier") or "",
                "n_cases": n_cases,
                "n_eligible": n_eligible,
                "asr": asr,
                "asr_lo": lo,
                "asr_hi": hi,
                "asr_unconditional": uasr,
                "asr_unconditional_lo": ulo,
                "asr_unconditional_hi": uhi,
                "cost_usd": _cost_of(run),
            }
        )
    rows.sort(
        key=lambda r: (
            effort_sort_key(r["effort_native"] or None, r["effort_tier"] or None),
            r["adapter_version"],
            r["run_id"],
        )
    )
    return rows


def aggregate_levels(
    curve: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Collapse a per-run curve to one row per effort level.

    Repeated runs at the same level aggregate: n_cases and n_eligible
    sum, cost sums, and ASR is the n_eligible-weighted mean (n_cases
    when n_eligible is absent; weight 1 when both are absent). The CI is
    a conservative envelope — [min lo, max hi] across the runs — labeled
    ``ci_envelope`` because it is not a recomputed interval. Levels with
    no ASR at all keep asr None rather than a fabricated number.
    """
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in curve:
        key = (row["effort_native"] or "", row["effort_tier"] or "")
        buckets.setdefault(key, []).append(row)
    levels: list[dict[str, Any]] = []
    for (native, tier), rows in buckets.items():
        n_cases_rows = [r["n_cases"] for r in rows if r["n_cases"] is not None]
        n_eligible_rows = [r["n_eligible"] for r in rows if r["n_eligible"] is not None]
        n_cases = sum(n_cases_rows) if n_cases_rows else None
        n_eligible = sum(n_eligible_rows) if n_eligible_rows else None
        cost_rows = [r["cost_usd"] for r in rows if r["cost_usd"] is not None]
        cost = sum(cost_rows) if cost_rows else None
        asr_rows = [r for r in rows if r["asr"] is not None]
        asr = None
        lo = hi = None
        if asr_rows:
            weights = [r["n_eligible"] or r["n_cases"] or 1 for r in asr_rows]
            total_w = sum(weights)
            asr = sum(r["asr"] * w for r, w in zip(asr_rows, weights)) / total_w
            los = [r["asr_lo"] for r in asr_rows if r["asr_lo"] is not None]
            his = [r["asr_hi"] for r in asr_rows if r["asr_hi"] is not None]
            lo = min(los) if los else None
            hi = max(his) if his else None
        levels.append(
            {
                "effort_native": native,
                "effort_tier": tier,
                "n_runs": len(rows),
                "n_cases": n_cases,
                "n_eligible": n_eligible,
                "asr": asr,
                "ci_envelope": [lo, hi] if lo is not None or hi is not None else None,
                "cost_usd": cost,
            }
        )
    levels.sort(
        key=lambda r: effort_sort_key(r["effort_native"] or None, r["effort_tier"] or None)
    )
    return levels


def marginal_table(
    curve: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Adjacent-level marginal economics for one effort curve.

    The curve's levels are aggregated first (see
    :func:`aggregate_levels`), so repeated runs at a level pool into one
    ASR and one cost. For each step up the ladder: delta_asr (negative =
    more robust), delta_cost_usd, and usd_per_asr_point — the dollars of
    extra spend per point of ASR reduction. Steps where either endpoint
    lacks ASR or cost, or where ASR did not improve, carry None for the
    ratio rather than a misleading number: a non-improvement has no
    price.
    """
    levels = aggregate_levels(curve)
    steps: list[dict[str, Any]] = []
    for prev, cur in zip(levels, levels[1:]):
        step: dict[str, Any] = {
            "from_effort": prev["effort_native"] or "provider default",
            "to_effort": cur["effort_native"] or "provider default",
            "from_tier": prev["effort_tier"],
            "to_tier": cur["effort_tier"],
            "delta_asr": None,
            "delta_cost_usd": None,
            "usd_per_asr_point": None,
        }
        if (
            prev["asr"] is not None
            and cur["asr"] is not None
            and prev["cost_usd"] is not None
            and cur["cost_usd"] is not None
        ):
            d_asr = cur["asr"] - prev["asr"]
            d_cost = cur["cost_usd"] - prev["cost_usd"]
            step["delta_asr"] = d_asr
            step["delta_cost_usd"] = d_cost
            # ASR reduction of at least a tenth of a point with positive
            # extra spend prices the gain; anything else has no price.
            if d_asr <= -0.001 and d_cost > 0:
                step["usd_per_asr_point"] = d_cost / (-d_asr * 100.0)
        steps.append(step)
    return steps


def crossed_comparison(
    run_a: dict[str, Any], run_b: dict[str, Any]
) -> dict[str, Any]:
    """Compare two (model, effort) configurations, e.g. sonnet@max vs opus@medium.

    Returns delta_asr (b minus a; negative favors b), a CI-overlap note,
    and the cost ratio. No significance claim beyond what the intervals
    show: overlapping CIs are reported as overlapping, not as ties.
    """
    asr_a, lo_a, hi_a = _asr_of(run_a)
    asr_b, lo_b, hi_b = _asr_of(run_b)
    cost_a, cost_b = _cost_of(run_a), _cost_of(run_b)
    out: dict[str, Any] = {
        "a": _effort_label(run_a),
        "b": _effort_label(run_b),
        "delta_asr": None,
        "ci_overlap": None,
        "cost_ratio_b_over_a": None,
    }
    if asr_a is not None and asr_b is not None:
        out["delta_asr"] = asr_b - asr_a
        if None not in (lo_a, hi_a, lo_b, hi_b):
            # Intervals overlap unless one lies strictly above the other.
            overlap = not (hi_a < lo_b or hi_b < lo_a)  # type: ignore[operator]
            out["ci_overlap"] = bool(overlap)
    if cost_a is not None and cost_b is not None and cost_a > 0:
        out["cost_ratio_b_over_a"] = cost_b / cost_a
    return out


def _effort_label(run: dict[str, Any]) -> str:
    name = run.get("adapter_name", "?")
    version = run.get("adapter_version", "?")
    native = run.get("effort") or ""
    tier = run.get("effort_tier") or ""
    eff = native if not tier or native == tier else f"{native} (tier {tier})"
    eff = eff or "provider default"
    return f"{name}:{version} @ {eff}"


def cost_per_prevented_flip(
    curve: list[dict[str, Any]],
    flips: dict[str, int],
) -> list[dict[str, Any]]:
    """Cost per prevented flip by effort level.

    ``curve`` is a per-run effort curve (see :func:`effort_curve`);
    levels are aggregated first. ``flips`` maps effort_native -> number
    of flipped cases at that level (callers with repeated runs pass the
    flip counts summed over the repeats at each level, matching the
    aggregated costs). The cheapest level is the baseline: prevented
    flips at level L = flips(baseline) - flips(L); cost per prevented
    flip = (cost(L) - cost(baseline)) / prevented. Levels preventing
    nothing (or with missing data) carry None — dividing by zero or
    pricing a non-improvement would manufacture a number.
    """
    levels = aggregate_levels(curve)
    cost_by = {
        lv["effort_native"]: lv["cost_usd"]
        for lv in levels
        if lv["cost_usd"] is not None
    }
    if not cost_by:
        return []
    baseline = min(cost_by, key=lambda k: cost_by[k])
    base_flips = flips.get(baseline)
    rows: list[dict[str, Any]] = []
    for lv in levels:
        native = lv["effort_native"]
        if native == baseline:
            continue
        row: dict[str, Any] = {
            "effort_native": native,
            "effort_tier": lv["effort_tier"],
            "vs_baseline": baseline or "provider default",
            "prevented_flips": None,
            "extra_cost_usd": None,
            "usd_per_prevented_flip": None,
        }
        n_flips = flips.get(native)
        if base_flips is not None and n_flips is not None:
            prevented = base_flips - n_flips
            row["prevented_flips"] = prevented
            extra = cost_by[native] - cost_by[baseline]
            row["extra_cost_usd"] = extra
            if prevented > 0 and extra > 0:
                row["usd_per_prevented_flip"] = extra / prevented
        rows.append(row)
    rows.sort(
        key=lambda r: effort_sort_key(r["effort_native"] or None, r["effort_tier"] or None)
    )
    return rows


def per_family_effort(
    family_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Per-family effort curves from registry family rows.

    Takes rows shaped like runs_registry.get_family_results output and
    groups them by (family, effort_native, effort_tier). Repeated runs
    aggregate like :func:`aggregate_levels`: n and n_eligible sum, ASR
    is the n_eligible-weighted mean, the CI is a conservative envelope,
    and refusal_rate is the n-weighted mean. Rows sort by family then
    effort level.
    """
    buckets: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in family_rows:
        key = (
            str(row.get("family") or ""),
            str(row.get("effort") or ""),
            str(row.get("effort_tier") or ""),
        )
        buckets.setdefault(key, []).append(row)
    out: list[dict[str, Any]] = []
    for (family, native, tier), rows in buckets.items():
        n_rows = [r for r in rows if _num(r.get("n")) is not None]
        n_el_rows = [r for r in rows if _num(r.get("n_eligible")) is not None]
        n = sum(_num(r["n"]) for r in n_rows) if n_rows else None
        n_el = sum(_num(r["n_eligible"]) for r in n_el_rows) if n_el_rows else None
        asr_rows = [r for r in rows if _num(r.get("asr")) is not None]
        asr = None
        lo = hi = None
        if asr_rows:
            weights = [_num(r.get("n_eligible")) or _num(r.get("n")) or 1
                       for r in asr_rows]
            total_w = sum(weights)
            asr = sum(_num(r["asr"]) * w for r, w in zip(asr_rows, weights)) / total_w
            los = [_num(r.get("asr_lo")) for r in asr_rows]
            his = [_num(r.get("asr_hi")) for r in asr_rows]
            los = [v for v in los if v is not None]
            his = [v for v in his if v is not None]
            lo = min(los) if los else None
            hi = max(his) if his else None
        rr_rows = [r for r in rows if _num(r.get("refusal_rate")) is not None]
        refusal_rate = None
        if rr_rows:
            rr_weights = [_num(r.get("n")) or 1 for r in rr_rows]
            refusal_rate = sum(
                _num(r["refusal_rate"]) * w for r, w in zip(rr_rows, rr_weights)
            ) / sum(rr_weights)
        out.append(
            {
                "family": family,
                "effort_native": native,
                "effort_tier": tier,
                "n_runs": len(rows),
                "n": int(n) if n is not None else None,
                "n_eligible": int(n_el) if n_el is not None else None,
                "asr": asr,
                "ci_envelope": [lo, hi] if lo is not None or hi is not None else None,
                "refusal_rate": refusal_rate,
            }
        )
    out.sort(
        key=lambda r: (
            r["family"],
            effort_sort_key(r["effort_native"] or None, r["effort_tier"] or None),
        )
    )
    return out


def summarize_effort(
    runs: list[dict[str, Any]],
    family_rows: list[dict[str, Any]] | None = None,
    flips: dict[str, dict[str, int]] | None = None,
) -> dict[str, Any]:
    """Top-level effort summary across runs.

    ``runs`` are registry list_runs rows each carrying a "metrics"
    payload (see the module header). Runs group by model — adapter_name
    plus the effort-stripped adapter version — so each model gets a
    within-model effort curve, level aggregation, marginal economics,
    and (when ``flips`` carries an entry for that model) cost per
    prevented flip. ``flips`` maps model key (``"name:base_version"``,
    the keys of the returned ``models`` dict) to an effort_native ->
    flipped-cases dict. Cross-model pairs (every distinct-model pair,
    deterministic order) get :func:`crossed_comparison` rows, e.g.
    sonnet@max vs opus@medium: one representative run per (model,
    effort level) — the first in curve order. ``family_rows`` (from
    get_family_results) adds per-family effort curves via
    :func:`per_family_effort`.

    Notes on the output flag the aggregation choices: repeated runs
    pool within a level, and CI envelopes are conservative, never
    recomputed intervals.
    """
    models: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for run in runs:
        models.setdefault(_model_key(run), []).append(run)
    model_summaries: dict[str, dict[str, Any]] = {}
    for (name, base_version), model_runs in sorted(models.items()):
        curve = effort_curve(model_runs)
        key = f"{name}:{base_version}"
        summary: dict[str, Any] = {
            "adapter_name": name,
            "adapter_version_base": base_version,
            "n_runs": len(model_runs),
            "curve": curve,
            "levels": aggregate_levels(curve),
            "marginal": marginal_table(curve),
        }
        if flips is not None and key in flips:
            summary["cost_per_prevented_flip"] = cost_per_prevented_flip(
                curve, flips[key]
            )
        model_summaries[key] = summary
    # One representative run per (model, effort level) for the crossed
    # pairs: the first run in curve order at each level. Curve rows
    # carry run_id, so map back to the original run dicts (which hold
    # the metrics payload and the "effort" key the comparison reads).
    by_id = {r.get("run_id"): r for r in runs}
    level_runs: dict[tuple[str, str], dict[str, Any]] = {}
    for key in sorted(model_summaries):
        for row in model_summaries[key]["curve"]:
            rep = by_id.get(row["run_id"], row)
            level_runs.setdefault((key, row["effort_native"]), rep)
    level_keys = sorted(
        level_runs,
        key=lambda k: (
            k[0],
            effort_sort_key(k[1] or None, level_runs[k].get("effort_tier") or None),
        ),
    )
    crossed: list[dict[str, Any]] = []
    for i, ka in enumerate(level_keys):
        for kb in level_keys[i + 1:]:
            if ka[0] == kb[0]:
                continue
            crossed.append(crossed_comparison(level_runs[ka], level_runs[kb]))
    out: dict[str, Any] = {
        "models": model_summaries,
        "crossed": crossed,
        "notes": [
            "Repeated runs at one effort level pool into a single level "
            "(n-weighted ASR, summed cost); per-run rows stay visible in "
            "each model's curve.",
            "Level CIs are conservative envelopes (min lo, max hi across "
            "the pooled runs), not recomputed intervals.",
            "Crossed comparisons report CI overlap as observed; no "
            "significance claim is made beyond the intervals.",
        ],
    }
    if family_rows is not None:
        out["per_family"] = per_family_effort(family_rows)
    return out
