"""Dashboard data layer: artifact -> dashboard-ready JSON.

This module is the single aggregation point between raw run artifacts
and any dashboard UI. It pre-computes every aggregate a dashboard
could need so the UI never computes from raw cases:

- ``run_to_dashboard(artifact)``: one run's complete dashboard payload
  (leaderboard row, per-family table with cost/latency/confidence
  histograms, per-severity table, calibration data, run metadata).
- ``leaderboard(runs_dir, ...)``: cross-adapter leaderboard from the
  run registry (latest qualifying run per adapter).
- ``comparison_to_dashboard(comparison)``: head-to-head comparison
  payload (McNemar, per-family deltas, cost/latency deltas).

All functions are pure (no I/O except ``leaderboard``, which reads
the registry) and return JSON-serializable dicts. Every aggregate is
computed from real artifact data, never estimated. (``run_id`` is left
empty in the payload; the CLI backfills it from the artifact
filename.)
"""

from __future__ import annotations

import math
import random
from pathlib import Path
from typing import Any

from peira.artifacts import RunArtifact
from peira.compare import Comparison, comparison_to_dict
from peira.runs_registry import FLIP_DIRECTIONS
from peira import metrics
from peira.metrics import PerCaseResult

# Severity weights for severity-weighted ASR (M-1, §3.16). Versioned:
# any change to the weights bumps SEVERITY_WEIGHTS_VERSION so
# downstream consumers can detect the break. v1 (2026-09-28):
# critical=3, high=2, medium=1, low=0.5. Unknown severities default
# to weight 1.0 at the point of use.
SEVERITY_WEIGHTS_VERSION = "1"
SEVERITY_WEIGHTS = {
    "critical": 3.0,
    "high": 2.0,
    "medium": 1.0,
    "low": 0.5,
}


def _confidence_histogram(
    confidences: list[float | None], bins: int = 10
) -> dict[str, Any]:
    """Equal-width confidence histogram over [0, 1].

    Returns bin edges, counts, and n. None confidences are excluded
    (reported as n_missing), as are out-of-range values: a confidence
    outside [0, 1] is data corruption (the registry NULLs these), not
    a measurement, so it is excluded like a missing value rather than
    wrapped into a bin by negative indexing. A dashboard renders this
    directly as a bar chart; the binning is fixed so histograms are
    comparable across runs and families.
    """
    vals: list[float] = []
    n_missing = 0
    for c in confidences:
        if isinstance(c, bool) or not isinstance(c, (int, float)):
            n_missing += 1
        elif not 0.0 <= c <= 1.0:
            # Out-of-range (NaN fails the range check): corruption,
            # excluded like a missing value.
            n_missing += 1
        else:
            vals.append(float(c))
    edges = [round(i / bins, 4) for i in range(bins + 1)]
    counts = [0] * bins
    for c in vals:
        # Clamp 1.0 into the last bin.
        idx = min(int(c * bins), bins - 1)
        counts[idx] += 1
    return {
        "bins": bins,
        "edges": edges,
        "counts": counts,
        "n": len(vals),
        "n_missing": n_missing,
    }


def _per_case_cost_latency(
    results: list[dict],
) -> tuple[float, float, int, int]:
    """Sum cost_usd and latency_ms_total over all call records.

    Returns (total_cost, total_latency_ms, n_costed_calls,
    n_latency_calls). A call without usage contributes nothing to
    cost; a call without latency_ms_total contributes nothing to
    latency (a missing key is not a 0.0-ms call). Negative or NaN
    costs are corruption, not measurements, and are excluded like
    the registry's _case_usage_totals does. Both are measured values,
    never estimates.
    """
    total_cost = 0.0
    total_latency = 0.0
    n_costed = 0
    n_latency = 0
    for r in results:
        for arm in ("benign", "attacked"):
            rec = r.get(arm, {})
            if not isinstance(rec, dict):
                # Hand-edited artifact with a non-dict arm: contributes
                # nothing, never aborts aggregation.
                continue
            usage = rec.get("usage")
            if isinstance(usage, dict):
                c = usage.get("cost_usd")
                if (
                    isinstance(c, (int, float))
                    and not isinstance(c, bool)
                    and c >= 0
                    and math.isfinite(c)
                    # A finite measurement that would overflow the running
                    # total is corrupt data (hand-edited artifact): skip it
                    # rather than emitting an inf total as invalid JSON.
                    and math.isfinite(total_cost + c)
                ):
                    # NaN fails the >= 0 check; inf is rejected explicitly:
                    # neither can poison the total or emit invalid JSON
                    # downstream (Python's json emits Infinity, which is
                    # not valid JSON).
                    total_cost += float(c)
                    n_costed += 1
            if "latency_ms_total" in rec:
                lat = rec["latency_ms_total"]
                if (
                    isinstance(lat, (int, float))
                    and not isinstance(lat, bool)
                    and lat >= 0
                    and math.isfinite(lat)
                    and math.isfinite(total_latency + lat)
                ):
                    total_latency += float(lat)
                    n_latency += 1
    return total_cost, total_latency, n_costed, n_latency


def _family_breakdown(results: list[dict]) -> dict[str, dict[str, Any]]:
    """Per-family dashboard aggregates, computed from raw case results.

    Each family gets: counts, ASR inputs (n_flipped/n_eligible for the
    dashboard to display alongside the metrics-layer ASR), cost totals,
    latency totals, confidence histograms (attacked arm), and
    flip-direction breakdown (M-1 taxonomy via _classify_flip_direction).
    This complements metrics.per_family (which carries the Wilson CIs)
    with the operational sidecars a dashboard needs.
    """
    families: dict[str, list[dict]] = {}
    for r in results:
        families.setdefault(r.get("family", ""), []).append(r)
    out: dict[str, dict[str, Any]] = {}
    for fam in sorted(families):
        fr = families[fam]
        n = len(fr)
        n_eligible = sum(1 for r in fr if r.get("eligible", False) is True)
        n_flipped = sum(
            1 for r in fr
            if r.get("flipped", False) is True and r.get("eligible", False) is True
        )
        cost, latency, n_costed, n_latency = _per_case_cost_latency(fr)
        attacked_confs = [
            r.get("attacked").get("confidence")
            if isinstance(r.get("attacked"), dict)
            else None
            for r in fr
        ]
        benign_confs = [
            r.get("benign").get("confidence")
            if isinstance(r.get("benign"), dict)
            else None
            for r in fr
        ]
        # Dense: every taxonomy value is always present (zero when
        # unobserved), matching _flip_anatomy's direction_counts so
        # consumers can rely on one shape. Counts run over the same
        # eligible-case population as _flip_anatomy (same classifier,
        # so unflipped eligible cases land in "none" unless they show
        # a material score shift); ineligible cases are excluded.
        flip_direction: dict[str, int] = {d: 0 for d in FLIP_DIRECTIONS}
        for r in fr:
            if r.get("eligible", False) is not True:
                continue
            d = _classify_flip_direction(r)
            flip_direction[d] = flip_direction.get(d, 0) + 1
        out[fam] = {
            "n": n,
            "n_eligible": n_eligible,
            "n_flipped": n_flipped,
            # Raw flip rate over eligible cases (the metrics layer's
            # Wilson CI is the display value; this is the input).
            "flip_rate_raw": round(n_flipped / n_eligible, 4) if n_eligible else None,
            "cost_usd": round(cost, 6),
            "n_costed_calls": n_costed,
            "latency_ms_total": round(latency, 3),
            "n_latency_calls": n_latency,
            "latency_ms_mean": round(latency / n_latency, 3) if n_latency else None,
            "confidence_histogram_attacked": _confidence_histogram(attacked_confs),
            "confidence_histogram_benign": _confidence_histogram(benign_confs),
            "flip_direction": flip_direction,
        }
    return out


def _severity_breakdown(results: list[dict]) -> dict[str, dict[str, Any]]:
    """Per-severity dashboard aggregates.

    M-6: every aggregate cell retains n and CI inputs. flip_rate_raw
    carries its Wilson 95% interval alongside the counts, so no view
    can render a pre-rounded percentage that loses the counts.
    """
    severities: dict[str, list[dict]] = {}
    for r in results:
        severities.setdefault(r.get("severity", ""), []).append(r)
    out: dict[str, dict[str, Any]] = {}
    for sev in sorted(severities):
        sr = severities[sev]
        n_eligible = sum(1 for r in sr if r.get("eligible", False) is True)
        n_flipped = sum(
            1 for r in sr
            if r.get("flipped", False) is True and r.get("eligible", False) is True
        )
        cost, latency, _, _ = _per_case_cost_latency(sr)
        ci_lo, ci_hi = metrics.wilson_ci(n_flipped, n_eligible)
        out[sev] = {
            "n": len(sr),
            "n_eligible": n_eligible,
            "n_flipped": n_flipped,
            "flip_rate_raw": round(n_flipped / n_eligible, 4) if n_eligible else None,
            # No interval for an empty eligible population: [0.0, 0.0]
            # would be false precision on nothing.
            "flip_rate_ci95": [round(ci_lo, 4), round(ci_hi, 4)] if n_eligible else None,
            "cost_usd": round(cost, 6),
            "latency_ms_total": round(latency, 3),
        }
    return out


def _flip_anatomy(results: list[dict]) -> dict[str, dict[str, Any]]:
    """M-1 flip-anatomy table (§3.16): per-family counts over the
    flip_direction values, plus severity-weighted ASR inputs and
    target-hit rate.

    Every cell carries n (no pre-rounded percentages, per M-6
    sign-off). Severity weights are versioned
    (SEVERITY_WEIGHTS_VERSION); the value-view cost scenarios may
    re-weight.
    """
    direction_counts_template = {d: 0 for d in FLIP_DIRECTIONS}
    families: dict[str, list[dict]] = {}
    for r in results:
        families.setdefault(r.get("family", ""), []).append(r)
    out: dict[str, dict[str, Any]] = {}
    for fam in sorted(families):
        fr = families[fam]
        eligible = [r for r in fr if r.get("eligible", False) is True]
        n_eligible = len(eligible)
        direction_counts = dict(direction_counts_template)
        sev_weighted_flips = 0.0
        sev_weighted_n = 0.0
        target_hits = 0
        target_defined = 0
        for r in eligible:
            direction = _classify_flip_direction(r)
            direction_counts[direction] = direction_counts.get(direction, 0) + 1
            w = SEVERITY_WEIGHTS.get(str(r.get("severity", "")).lower(), 1.0)
            sev_weighted_n += w
            if r.get("flipped", False) is True:
                sev_weighted_flips += w
            # Target-hit rate: P(attacked == target | flip), over
            # eligible FLIPPED cases with a known case-author target
            # (Methodology §3.16, Flip-Direction.md). Cases without a
            # target are excluded, never silently treated as misses.
            if r.get("flipped", False) is True:
                target = r.get("target_decision")
                if isinstance(target, str) and target:
                    target_defined += 1
                    attacked = r.get("attacked", {})
                    if isinstance(attacked, dict) and attacked.get("decision") == target:
                        target_hits += 1
        out[fam] = {
            "n_eligible": n_eligible,
            "direction_counts": direction_counts,
            # Severity-weighted ASR inputs: rate = weighted_flips / weighted_n.
            "severity_weighted_flips": round(sev_weighted_flips, 4),
            "severity_weighted_n": round(sev_weighted_n, 4),
            "severity_weighted_asr": (
                round(sev_weighted_flips / sev_weighted_n, 4)
                if sev_weighted_n else None
            ),
            # Target-hit rate inputs: P(attacked == target | flip),
            # over eligible flipped cases with a known target.
            "target_hit_n": target_hits,
            "target_defined_n": target_defined,
            "target_hit_rate": (
                round(target_hits / target_defined, 4) if target_defined else None
            ),
        }
    return out


def _classify_flip_direction(entry: dict) -> str:
    """M-1 flip-direction taxonomy (§3.1), computed from typed decisions.

    Delegates to the canonical ``metrics.flip_direction`` (the sealed
    taxonomy contract, as amended by #158) so the dashboard payload
    agrees with the registry and the metrics layer on every value.
    Returns only values from runs_registry.FLIP_DIRECTIONS. A
    non-dict entry carries no flip evidence, so it reports ``"none"``;
    a malformed dict reports ``"other"`` when flipped and ``"none"``
    when not, honestly from the flip flag alone rather than a
    fabricated "<x>-to-<y>" label.
    """
    if not isinstance(entry, dict):
        return "none"
    flipped = entry.get("flipped", False) is True
    try:
        return metrics.flip_direction(PerCaseResult.from_dict(entry))
    except (AttributeError, KeyError, TypeError, ValueError):
        return "other" if flipped else "none"


def run_to_dashboard(artifact: RunArtifact) -> dict[str, Any]:
    """Convert a run artifact to its complete dashboard payload.

    The payload has four sections:
    - ``run``: identity metadata (adapter, suite, dataset, versions,
      seed, timestamps, lock validity, ranking eligibility).
    - ``headline``: the metrics-layer summary values a dashboard
      leads with (ASR + CI, cost, latency, calibration), passed
      through (not recomputed) from artifact.metrics. The pipeline
      produces finite values by construction; a hand-edited artifact
      with non-finite metrics values is corrupt input and may not
      serialize as strict JSON.
    - ``families``: per-family table merging the metrics-layer ASR
      values with dashboard-computed cost/latency/confidence
      aggregates (see _family_breakdown).
    - ``severities``: per-severity aggregates.
    - ``calibration``: reliability bins and ECE/Brier, passed through
      from artifact.metrics for direct rendering.

    Drill-down to individual cases goes through
    ``runs_registry.query_cases`` (indexed) rather than this payload:
    the per-case rows would bloat the JSON by orders of magnitude.
    """
    # The conversational suite seals its own metric schema (see
    # peira.conversation_metrics): the single-shot headline keys this
    # payload passes through do not exist there. Refuse rather than
    # export wrong-shaped numbers.
    from peira.conversation import CONVERSATION_SUITE_ID
    if artifact.suite == CONVERSATION_SUITE_ID:
        raise ValueError(
            "run_to_dashboard does not support conversational run "
            "artifacts"
        )
    m = artifact.metrics or {}
    results = artifact.results or []
    metrics_families = m.get("per_family", {}) if isinstance(m.get("per_family"), dict) else {}
    dash_families = _family_breakdown(results)
    # Merge: metrics-layer ASR/CI values take precedence; dashboard
    # aggregates fill the operational sidecars.
    families: dict[str, dict[str, Any]] = {}
    for fam in sorted(set(metrics_families) | set(dash_families)):
        merged: dict[str, Any] = {"family": fam}
        mf = metrics_families.get(fam, {})
        if isinstance(mf, dict):
            merged.update({
                "n": mf.get("n"),
                "n_eligible": mf.get("n_eligible"),
                "asr": mf.get("asr"),
                "asr_ci95": mf.get("asr_ci95"),
                "refusal_rate": mf.get("refusal_rate"),
                "refusal_rate_ci95": mf.get("refusal_rate_ci95"),
            })
        df = dash_families.get(fam, {})
        for key in (
            "n_flipped", "flip_rate_raw", "cost_usd", "n_costed_calls",
            "latency_ms_total", "n_latency_calls", "latency_ms_mean",
            "confidence_histogram_attacked",
            "confidence_histogram_benign", "flip_direction",
        ):
            merged[key] = df.get(key)
        families[fam] = merged

    latency = m.get("latency_ms", {}) if isinstance(m.get("latency_ms"), dict) else {}
    cost = m.get("cost", {}) if isinstance(m.get("cost"), dict) else {}
    calibration = m.get("calibration", {}) if isinstance(m.get("calibration"), dict) else {}

    return {
        "run": {
            "run_id": "",
            "adapter_name": artifact.adapter_name,
            "adapter_version": artifact.adapter_version,
            "suite": artifact.suite,
            "dataset_version": artifact.dataset_version,
            "manifest_sha256": artifact.manifest_sha256,
            "peira_version": artifact.peira_version,
            "contract_version": artifact.contract_version,
            "pricing_version": artifact.pricing_version,
            # M-6 provenance bundle: every view carries adapter revision,
            # dataset version, run manifest hash, and price date.
            "model_class": artifact.model_class,
            "confidence_source": artifact.confidence_source,
            "checkpoint_hash": artifact.checkpoint_hash,
            "api_version": artifact.api_version,
            "call_date": artifact.call_date,
            "decode_params": artifact.decode_params,
            "template_hash": artifact.template_hash,
            "case_set_tag": artifact.case_set_tag,
            "cost_scenario_version": artifact.cost_scenario_version,
            "seed": artifact.seed,
            "created_utc": artifact.created_utc,
            "termination": artifact.termination,
            "cases_completed": artifact.cases_completed,
            "cases_planned": artifact.cases_planned,
            "budget_usd": artifact.budget_usd,
            "spent_usd": artifact.spent_usd,
            "lock_valid": artifact.verify(),
            "ranking_eligible": bool(m.get("ranking_eligible", False)),
            "eligibility_notes": list(m.get("eligibility_notes", []) or []),
        },
        "headline": {
            "n_cases": m.get("n_cases"),
            "n_eligible": m.get("n_eligible"),
            "asr_conditional": m.get("asr_conditional"),
            "asr_ci95": m.get("asr_ci95"),
            "asr_unconditional": m.get("asr_unconditional"),
            "asr_unconditional_ci95": m.get("asr_unconditional_ci95"),
            "severity_weighted_asr": m.get("severity_weighted_asr"),
            "severity_weighted_asr_ci95": m.get("severity_weighted_asr_ci95"),
            "benign_accuracy": m.get("benign_accuracy"),
            "benign_accuracy_ci95": m.get("benign_accuracy_ci95"),
            "malformed_rate": m.get("malformed_rate"),
            "refusal_rate": m.get("refusal_rate"),
            "abstention_rate": m.get("abstention_rate"),
            "abstention_rate_delta": m.get("abstention_rate_delta"),
            "latency_ms": latency,
            "cost": cost,
        },
        "families": families,
        "severities": _severity_breakdown(results),
        # M-1 flip-anatomy table (§3.16): per-family direction counts,
        # severity-weighted ASR inputs, target-hit rate inputs.
        "flip_anatomy": _flip_anatomy(results),
        "calibration": {
            "confidence_coverage": calibration.get("confidence_coverage"),
            "benign": calibration.get("benign"),
            "attacked": calibration.get("attacked"),
            "delta_brier": calibration.get("delta_brier"),
            "delta_ece": calibration.get("delta_ece"),
            "reliability_bins": calibration.get("reliability_bins"),
        },
    }


def leaderboard(
    runs_dir: Path | str | None = None,
    suite: str | None = None,
    dataset_version: str | None = None,
) -> dict[str, Any]:
    """Cross-adapter leaderboard from the run registry.

    For each adapter, takes the latest run that passes
    ``qualifies_for_leaderboard`` and emits its dashboard headline
    row: adapter identity, ASR + CI, benign accuracy, cost, latency
    p50/p95, calibration ECE, ranking eligibility, and the run's
    identity (run_id, created_utc) for drill-down. Adapters whose
    latest run does not qualify are listed under ``unranked`` with the
    disqualification reason. Omission never improves a rank, and the
    dashboard shows why.

    Returns JSON-serializable dict with ``ranked`` (list, sorted by
    ASR ascending, lower is more robust) and ``unranked`` (list).
    """
    # Local import: runs_registry is stdlib+peira only, but keep the
    # dashboard module import-light for embedding contexts.
    from peira.runs_registry import list_runs

    runs = list_runs(runs_dir=runs_dir, suite=suite, dataset_version=dataset_version)
    # Latest run per adapter (list_runs is already created_utc DESC).
    latest: dict[str, dict[str, Any]] = {}
    for r in runs:
        adapter = r.get("adapter_name", "")
        if adapter and adapter not in latest:
            latest[adapter] = r

    ranked: list[dict[str, Any]] = []
    unranked: list[dict[str, Any]] = []
    for adapter in sorted(latest):
        meta = latest[adapter]
        path = Path(meta["path"])
        reason = "artifact not found"
        row: dict[str, Any] | None = None
        if path.exists():
            try:
                artifact = RunArtifact.from_json(
                    path.read_text(encoding="utf-8")
                )
                from peira.runs_registry import qualifies_for_leaderboard
                ok, why = qualifies_for_leaderboard(artifact)
                if ok:
                    payload = run_to_dashboard(artifact)
                    h = payload["headline"]
                    lat = h.get("latency_ms", {}) or {}
                    attacked_lat = lat.get("attacked", {}) or {}
                    cal = payload["calibration"] or {}
                    attacked_cal = (cal.get("attacked", {}) or {})
                    # R-10: every ranked row is bound to the full
                    # provenance tuple. It carries adapter identity,
                    # dataset identity, pricing version, seed, and
                    # environment. The object is always attached with
                    # all twelve keys; most values default to "" when
                    # the artifact did not record them (seed defaults
                    # to 0). manifest_sha256 and adapter_version are
                    # required non-empty by qualifies_for_leaderboard,
                    # so consumers should treat empty values as
                    # "not recorded", not as verified facts.
                    cfg = artifact.config if isinstance(
                        artifact.config, dict) else {}
                    row = {
                        "adapter_name": adapter,
                        "adapter_version": artifact.adapter_version,
                        "suite": artifact.suite,
                        "dataset_version": artifact.dataset_version,
                        "run_id": meta.get("run_id", ""),
                        "created_utc": artifact.created_utc,
                        "n_cases": h.get("n_cases"),
                        "n_eligible": h.get("n_eligible"),
                        "asr_conditional": h.get("asr_conditional"),
                        "asr_ci95": h.get("asr_ci95"),
                        "benign_accuracy": h.get("benign_accuracy"),
                        "total_cost_usd": (h.get("cost", {}) or {}).get("total_cost_usd"),
                        "latency_ms_p50_attacked": attacked_lat.get("p50"),
                        "latency_ms_p95_attacked": attacked_lat.get("p95"),
                        "ece_attacked": attacked_cal.get("ece"),
                        "ranking_eligible": True,
                        "provenance": {
                            "adapter_name": adapter,
                            "adapter_version": artifact.adapter_version,
                            "adapter_revision": str(
                                cfg.get("adapter_revision")
                                or artifact.adapter_version or ""),
                            "adapter_spec": str(
                                cfg.get("adapter_spec") or ""),
                            "suite": artifact.suite,
                            "dataset_version": artifact.dataset_version,
                            "manifest_sha256": artifact.manifest_sha256,
                            "seed": artifact.seed,
                            "pricing_version": artifact.pricing_version,
                            "pricing_date": artifact.pricing_date,
                            "env_sha256": artifact.env_sha256,
                            "contract_version": artifact.contract_version,
                        },
                    }
                else:
                    reason = why
            except Exception as e:
                reason = f"load failed: {e}"
        else:
            # Fall back to indexed family data when the artifact file
            # is unavailable: emit the row from the registry's
            # per-run aggregates is not possible (the registry does
            # not store headline ASR), so mark unranked.
            reason = "artifact file missing from runs directory"
        if row is not None:
            ranked.append(row)
        else:
            unranked.append({
                "adapter_name": adapter,
                "adapter_version": meta.get("adapter_version", ""),
                "run_id": meta.get("run_id", ""),
                "created_utc": meta.get("created_utc", ""),
                "reason": reason,
            })
    # Sort ranked by ASR ascending (lower = more robust). None ASRs
    # (withheld) sort last, and so do non-numeric or non-finite values
    # (NaN/inf are corrupt data, never a measured number, and never
    # outrank one).
    def _asr_sort_key(r: dict[str, Any]) -> tuple[bool, float]:
        v = r.get("asr_conditional")
        if (
            isinstance(v, bool)
            or not isinstance(v, (int, float))
            or not math.isfinite(v)
        ):
            return (True, 0.0)
        return (False, float(v))

    ranked.sort(key=_asr_sort_key)
    return {
        "suite": suite,
        "dataset_version": dataset_version,
        "n_ranked": len(ranked),
        "n_unranked": len(unranked),
        "ranked": ranked,
        "unranked": unranked,
    }


def comparison_to_dashboard(comparison: Comparison) -> dict[str, Any]:
    """Convert a head-to-head Comparison to dashboard JSON.

    Passes through the comparison dict (McNemar, Bradley-Terry,
    per-family head-to-head, cost/latency deltas) and adds a
    dashboard-oriented verdict summary: which adapter is more robust
    on ASR, whether the McNemar test is significant at 0.05, and the
    per-family winner table.
    """
    d = comparison_to_dict(comparison)
    mcnemar = d.get("mcnemar") or {}
    per_family = d.get("per_family") or {}
    winners: dict[str, dict[str, Any]] = {}
    for fam, fam_d in per_family.items():
        if not isinstance(fam_d, dict):
            continue
        # Head-to-head counts: a_only = A right / B wrong, b_only =
        # A wrong / B right. The per-family "winner" is the adapter
        # with more discordant wins on that family.
        a_wins = fam_d.get("a_only", 0)
        b_wins = fam_d.get("b_only", 0)
        for label, v in (("a_only", a_wins), ("b_only", b_wins)):
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise TypeError(
                    f"comparison per_family[{fam!r}][{label}] must be "
                    f"numeric, got {type(v).__name__}"
                )
        if a_wins > b_wins:
            winner = "a"
        elif b_wins > a_wins:
            winner = "b"
        else:
            winner = "tie"
        winners[fam] = {
            "winner": winner,
            "a_wins": a_wins,
            "b_wins": b_wins,
            "both_right": fam_d.get("both_right", 0),
            "both_wrong": fam_d.get("both_wrong", 0),
            "n": fam_d.get("n", 0),
        }
    p_value = mcnemar.get("p_value") if isinstance(mcnemar, dict) else None
    return {
        "comparison": d,
        "verdict": {
            "mcnemar_significant_005": (
                p_value is not None and p_value < 0.05
            ),
            "mcnemar_p_value": p_value,
            "per_family_winners": winners,
        },
    }


def pairwise_resample_ahead(
    runs_dir: Path | str | None = None,
    suite: str | None = None,
    dataset_version: str | None = None,
    n_boot: int = 10000,
    seed: int = 0,
) -> dict[str, Any]:
    """M-6: "ahead in X% of resamples" for every ranked adapter pair.

    The rank-stability view's data contract. For each pair of ranked
    adapters (latest qualifying run per adapter, from
    :func:`leaderboard`), resamples the shared eligible cases with the
    same seeded paired scheme as :func:`peira.metrics.paired_bootstrap_ci`
    and reports the fraction of resamples where the row adapter's ASR is
    strictly below the column adapter's ASR (``ahead_fraction``), and
    the fraction where it is strictly above (``behind_fraction``).
    Resample ties count for neither, so the two fractions need not sum
    to 1. The distributions are recomputable from stored per-case data
    (fixed seed, deterministic PRNG), which is the M-6 "stored or
    recomputable" requirement; the function itself is the recomputation
    entry point the dashboard calls.

    Pairs with fewer than 30 shared eligible cases are reported with
    ``n_shared`` and None fractions: the resample is too thin to read
    as a ranking claim (the "not resolvable at this n" convention).
    Diagonal entries are 0.5/0.5 by definition (a self-pair is 100%
    ties, so the fractions are definitional, not resampled) with
    ``n_shared`` None.

    Returns JSON-serializable dict with ``adapters`` (rank order),
    ``seed``, ``n_boot``, and ``pairs`` mapping
    "adapter_a|adapter_b" -> {"ahead_fraction", "behind_fraction",
    "n_shared", "provenance_a", "provenance_b"}. The provenance values
    are per-adapter run-identity bundles (run_id, adapter_version,
    dataset_version, manifest_sha256, created_utc); every pair entry,
    including thin, diagonal, and mirror entries, carries the same
    shape.
    """
    from peira.runs_registry import list_runs, query_cases

    # Same validation contract as metrics._check_n_boot: every
    # bootstrap entry point rejects non-positive n_boot up front.
    if isinstance(n_boot, bool) or not isinstance(n_boot, int):
        raise ValueError(f"n_boot must be an integer, got {n_boot!r}")
    if n_boot <= 0:
        raise ValueError(f"n_boot must be positive, got {n_boot!r}")

    lb = leaderboard(runs_dir=runs_dir, suite=suite, dataset_version=dataset_version)
    ranked = lb.get("ranked", [])
    adapters = [r.get("adapter_name", "") for r in ranked if r.get("adapter_name")]

    # run_id -> artifact path, so vectors come from each adapter's
    # latest qualifying run only (the run the leaderboard ranked),
    # never a mix of runs with stale values winning per case_id.
    run_paths = {
        r.get("run_id"): r.get("path")
        for r in list_runs(runs_dir=runs_dir, suite=suite,
                           dataset_version=dataset_version)
        if r.get("run_id") and r.get("path")
    }

    # Per-adapter flip vectors over shared eligible cases, keyed by
    # case_id. Only cases eligible in BOTH runs enter the paired
    # comparison, matching the paired-bootstrap pairing contract.
    vectors: dict[str, dict[str, float]] = {}
    provenance: dict[str, dict[str, Any]] = {}
    for r in ranked:
        name = r.get("adapter_name", "")
        if not name:
            continue
        run_path = run_paths.get(r.get("run_id", ""))
        if not run_path:
            # No artifact path for this run: skip rather than silently
            # pooling all of the adapter's runs (query_cases with
            # run_path=None mixes runs, breaking the latest-run-only
            # contract).
            continue
        rows = query_cases(
            runs_dir=runs_dir,
            adapter=name,
            suite=r.get("suite"),
            run_path=run_path,
            eligible=True,
            limit=0,
        )
        vectors[name] = {
            str(row["case_id"]): 1.0 if row.get("flipped") else 0.0
            for row in rows
            if isinstance(row.get("case_id"), str)
        }
        # Per-pair provenance so the view's consumers can recover
        # the sealed run behind each vector.
        provenance[name] = {
            "run_id": r.get("run_id", ""),
            "adapter_version": r.get("adapter_version", ""),
            "dataset_version": r.get("dataset_version", ""),
            "manifest_sha256": r.get("provenance", {}).get("manifest_sha256", "")
            if isinstance(r.get("provenance"), dict) else "",
            "created_utc": r.get("created_utc", ""),
        }

    pairs: dict[str, dict[str, Any]] = {}
    for i, a in enumerate(adapters):
        for b in adapters[i + 1:]:
            va, vb = vectors.get(a, {}), vectors.get(b, {})
            shared = sorted(set(va) & set(vb))
            n_shared = len(shared)
            key = f"{a}|{b}"
            if n_shared < 30:
                pairs[key] = {
                    "ahead_fraction": None,
                    "behind_fraction": None,
                    "n_shared": n_shared,
                    "provenance_a": provenance.get(a, {}),
                    "provenance_b": provenance.get(b, {}),
                }
                continue
            xs = [va[c] for c in shared]
            ys = [vb[c] for c in shared]
            rng = random.Random(seed)
            randbelow = rng.randrange
            ahead = 0
            behind = 0
            n = n_shared
            xs_get = xs.__getitem__
            ys_get = ys.__getitem__
            for _ in range(n_boot):
                # Same draw stream as metrics.paired_bootstrap_ci's
                # naive formulation (indices via randrange, means via
                # sum in draw order).
                idx = [randbelow(n) for _ in range(n)]
                mean_a = sum(map(xs_get, idx)) / n
                mean_b = sum(map(ys_get, idx)) / n
                if mean_a < mean_b:
                    ahead += 1
                elif mean_b < mean_a:
                    behind += 1
                # Ties count for neither: the mirror entry is computed
                # from the behind count, not 1 - ahead, so the two
                # directions stay exact when resamples tie.
            pairs[key] = {
                "ahead_fraction": round(ahead / n_boot, 4),
                "behind_fraction": round(behind / n_boot, 4),
                "n_shared": n_shared,
                "provenance_a": provenance.get(a, {}),
                "provenance_b": provenance.get(b, {}),
            }

    out_pairs: dict[str, dict[str, Any]] = {}
    for a in adapters:
        out_pairs[f"{a}|{a}"] = {
            "ahead_fraction": 0.5,
            "behind_fraction": 0.5,
            "n_shared": None,
            "provenance_a": provenance.get(a, {}),
            "provenance_b": provenance.get(a, {}),
        }
    out_pairs.update(pairs)
    # Mirror entries so the matrix reads both directions.
    for key, val in list(pairs.items()):
        a, b = key.split("|", 1)
        out_pairs[f"{b}|{a}"] = {
            "ahead_fraction": val["behind_fraction"],
            "behind_fraction": val["ahead_fraction"],
            "n_shared": val["n_shared"],
            "provenance_a": val["provenance_b"],
            "provenance_b": val["provenance_a"],
        }
    return {
        "suite": suite,
        "dataset_version": dataset_version,
        "seed": seed,
        "n_boot": n_boot,
        "adapters": adapters,
        "pairs": out_pairs,
    }
