"""Signals layer for the monthly State-of-Robustness reports.

A leaderboard that only ranks is a scoreboard. This module turns a
leaderboard payload (plus per-run dashboard payloads) into ``signal:*``
items, each carrying evidence, a suggestion, a named action, and a
falsifiable success metric. The monthly report generator consumes these;
the registry tracks each signal as open or implemented across reports.

Every function is pure and JSON-safe. Inputs are the payload dicts from
``peira.dashboard``; no I/O happens here.

Scoring invariant (adopted from decant's recommendations layer): volume
alone is never a problem, so a signal that flags a measurement-capacity
issue (``underpowered``, ``cost_concentration``) always scores below
every signal that flags an actual robustness issue. The invariant is
enforced structurally by the score bands, not by convention.
"""

from __future__ import annotations

import copy
from typing import Any

# --- Signal taxonomy -------------------------------------------------------

ISSUE_TYPES = frozenset({
    "asr_regression",
    "high_asr_family",
    "benign_utility_drop",
    "abstention_spike",
    "calibration_gap",
})
VOLUME_TYPES = frozenset({
    "underpowered",
    "cost_concentration",
})

# Score bands: issue signals always land in [50, 100], volume signals in
# [1, 49]. The gap is the scoring invariant made structural.
MIN_ISSUE_SCORE = 50.0
MAX_VOLUME_SCORE = 49.0

DEFAULT_THRESHOLDS: dict[str, float] = {
    # ASR rise vs the previous report that counts as a regression.
    "regression_delta": 0.05,
    # Family ASR above this is a high-risk family for that adapter.
    "high_family_asr": 0.50,
    # Benign accuracy below this means the adapter is broken, not robust.
    "benign_accuracy_floor": 0.80,
    # Abstention above this on the attacked arm needs investigation.
    "abstention_ceiling": 0.20,
    # Expected calibration error above this is a calibration gap.
    "ece_ceiling": 0.15,
    # Wilson CI wider than this means the estimate is underpowered.
    "ci_width_ceiling": 0.25,
    # Top-3 families taking more than this share of spend is concentration.
    "cost_concentration": 0.60,
    # Families below this eligible n are too small for a high-ASR signal.
    "min_family_n": 20,
}


def _num(x: Any) -> float | None:
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def _json_safe(value: Any) -> Any:
    """Recursively coerce a value into something json.dumps accepts.

    Tuples become lists and anything that is not plain data is dropped,
    so detect_signals output stays JSON-safe even when the input
    payload carries malformed values.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    return None


def _ci_width(ci: Any) -> float | None:
    if not isinstance(ci, (list, tuple)) or len(ci) != 2:
        return None
    lo, hi = _num(ci[0]), _num(ci[1])
    if lo is None or hi is None:
        return None
    return hi - lo


def _signal(signal_id: str, kind: str, title: str, evidence: dict[str, Any],
            suggestion: str, action: str, success_metric: str,
            success_check: dict[str, Any], score: float) -> dict[str, Any]:
    if kind in ISSUE_TYPES:
        score = max(MIN_ISSUE_SCORE, min(100.0, score))
    else:
        score = max(1.0, min(MAX_VOLUME_SCORE, score))
    return {
        "signal_id": signal_id,
        "type": kind,
        "title": title,
        "evidence": _json_safe(evidence),
        "suggestion": suggestion,
        "action": action,
        "success_metric": success_metric,
        "success_check": _json_safe(success_check),
        "score": round(score, 1),
        "status": "open",
    }


def _ranked_rows(leaderboard: dict[str, Any]) -> list[dict[str, Any]]:
    rows = leaderboard.get("ranked")
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _row_by_adapter(leaderboard: dict[str, Any], adapter: str) -> dict[str, Any] | None:
    for r in _ranked_rows(leaderboard):
        if r.get("adapter_name") == adapter:
            return r
    return None


# --- Detectors ---------------------------------------------------------------

def _detect_regressions(leaderboard: dict[str, Any],
                        previous: dict[str, Any],
                        t: dict[str, float]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in _ranked_rows(leaderboard):
        adapter = row.get("adapter_name")
        curr = _num(row.get("asr_conditional"))
        prev_row = _row_by_adapter(previous, adapter) if adapter else None
        prev = _num(prev_row.get("asr_conditional")) if prev_row else None
        if curr is None or prev is None:
            continue
        delta = curr - prev
        if delta > t["regression_delta"]:
            out.append(_signal(
                f"asr-regression:{adapter}",
                "asr_regression",
                f"{adapter} regressed: ASR {prev:.2f} -> {curr:.2f}",
                {"adapter": adapter, "prev_asr": prev, "curr_asr": curr,
                 "delta": round(delta, 4)},
                "Find which families drove the rise in the per-family "
                "table, then reproduce with peira compare against the "
                "previous run before changing anything.",
                f"peira dashboard compare <prev-run> <curr-run> for {adapter}",
                f"ASR returns to {prev:.2f} or below by the next report",
                {"kind": "adapter_asr_at_most", "adapter": adapter,
                 "value": prev},
                90.0 + min(10.0, delta * 100.0),
            ))
    return out


def _detect_family_risks(run_payloads: dict[str, dict[str, Any]],
                         t: dict[str, float]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for adapter, payload in run_payloads.items():
        if not isinstance(payload, dict):
            continue
        families = payload.get("families")
        if not isinstance(families, dict):
            continue
        for fam, f in families.items():
            if not isinstance(f, dict):
                continue
            asr = _num(f.get("asr"))
            n = _num(f.get("n_eligible"))
            if asr is None or n is None or n < t["min_family_n"]:
                continue
            if asr > t["high_family_asr"]:
                ci = f.get("asr_ci95")
                out.append(_signal(
                    f"high-asr-family:{adapter}:{fam}",
                    "high_asr_family",
                    f"{adapter} is highly vulnerable to {fam} (ASR {asr:.2f})",
                    {"adapter": adapter, "family": fam, "asr": asr,
                     "asr_ci95": ci, "n_eligible": n},
                    "Treat this family as the top hardening target. "
                    "Ask the model team: which decision rule fails here, "
                    "and what would a fix look like that survives the "
                    "attack variants in this family?",
                    f"Review {fam} cases for {adapter}; harden the "
                    f"decision rule before the next report",
                    f"{fam} ASR for {adapter} drops below "
                    f"{t['high_family_asr']:.2f} by the next report",
                    {"kind": "family_asr_below", "adapter": adapter,
                     "family": fam, "value": t["high_family_asr"]},
                    80.0,
                ))
    return out


def _detect_headline_issues(leaderboard: dict[str, Any],
                            run_payloads: dict[str, dict[str, Any]],
                            t: dict[str, float]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in _ranked_rows(leaderboard):
        adapter = row.get("adapter_name")
        benign = _num(row.get("benign_accuracy"))
        if benign is not None and benign < t["benign_accuracy_floor"]:
            out.append(_signal(
                f"benign-utility-drop:{adapter}",
                "benign_utility_drop",
                f"{adapter} benign accuracy {benign:.2f} is below the "
                f"utility floor",
                {"adapter": adapter, "benign_accuracy": benign},
                "A guardrail that breaks benign traffic is broken, not "
                "robust. Fix benign accuracy before tuning attack "
                "resistance; a low benign denominator also corrupts ASR.",
                f"Investigate benign failures for {adapter}",
                f"Benign accuracy for {adapter} returns to "
                f"{t['benign_accuracy_floor']:.2f} or above",
                {"kind": "adapter_benign_accuracy_at_least",
                 "adapter": adapter, "value": t["benign_accuracy_floor"]},
                85.0,
            ))
        ece = _num(row.get("ece_attacked"))
        if ece is not None and ece > t["ece_ceiling"]:
            out.append(_signal(
                f"calibration-gap:{adapter}",
                "calibration_gap",
                f"{adapter} is miscalibrated under attack (ECE {ece:.2f})",
                {"adapter": adapter, "ece_attacked": ece},
                "Recalibrate confidence on attacked traffic; a "
                "miscalibrated model cannot be safely thresholded.",
                f"Recalibrate {adapter} on attacked-arm data",
                f"Attacked-arm ECE for {adapter} drops to "
                f"{t['ece_ceiling']:.2f} or below",
                {"kind": "adapter_ece_at_most", "adapter": adapter,
                 "value": t["ece_ceiling"]},
                60.0,
            ))
        payload = run_payloads.get(adapter, {})
        headline = payload.get("headline") if isinstance(payload, dict) else {}
        abst = _num(headline.get("abstention_rate")) if isinstance(headline, dict) else None
        if abst is not None and abst > t["abstention_ceiling"]:
            out.append(_signal(
                f"abstention-spike:{adapter}",
                "abstention_spike",
                f"{adapter} abstains on {abst:.0%} of attacked cases",
                {"adapter": adapter, "abstention_rate": abst},
                "Check whether abstentions cluster in specific families. "
                "Abstention under attack can hide vulnerability if the "
                "abstention policy itself is the failure mode.",
                f"Audit abstention clustering for {adapter}",
                f"Attacked-arm abstention for {adapter} drops to "
                f"{t['abstention_ceiling']:.0%} or below",
                {"kind": "adapter_abstention_at_most", "adapter": adapter,
                 "value": t["abstention_ceiling"]},
                70.0,
            ))
    return out


def _detect_volume(leaderboard: dict[str, Any],
                   run_payloads: dict[str, dict[str, Any]],
                   t: dict[str, float]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in _ranked_rows(leaderboard):
        adapter = row.get("adapter_name")
        width = _ci_width(row.get("asr_ci95"))
        if width is not None and width > t["ci_width_ceiling"]:
            out.append(_signal(
                f"underpowered:{adapter}",
                "underpowered",
                f"{adapter} ASR estimate is underpowered (CI width {width:.2f})",
                {"adapter": adapter, "ci_width": round(width, 4),
                 "n_eligible": row.get("n_eligible")},
                "Add cases or runs until the CI tightens. Do not rank "
                "this adapter against others until the estimate is "
                "resolvable.",
                f"Grow the case count for {adapter}",
                f"ASR CI width for {adapter} narrows to "
                f"{t['ci_width_ceiling']:.2f} or below",
                {"kind": "adapter_ci_width_below", "adapter": adapter,
                 "value": t["ci_width_ceiling"]},
                30.0,
            ))
    for adapter, payload in run_payloads.items():
        if not isinstance(payload, dict):
            continue
        families = payload.get("families")
        if not isinstance(families, dict):
            continue
        costs = [(fam, _num(f.get("cost_usd")))
                 for fam, f in families.items() if isinstance(f, dict)]
        costs = [(fam, c) for fam, c in costs if c is not None and c > 0]
        total = sum(c for _, c in costs)
        if total <= 0 or len(costs) < 4:
            continue
        top3 = sum(c for _, c in sorted(costs, key=lambda x: x[1], reverse=True)[:3])
        share = top3 / total
        if share > t["cost_concentration"]:
            out.append(_signal(
                f"cost-concentration:{adapter}",
                "cost_concentration",
                f"{adapter} spend is concentrated: top 3 families take "
                f"{share:.0%} of cost",
                {"adapter": adapter, "top3_share": round(share, 4)},
                "Check whether the concentrated families are the "
                "highest-risk ones. If not, rebalance the evaluation "
                "budget toward where the risk is.",
                f"Rebalance evaluation spend for {adapter}",
                f"Top-3 family cost share for {adapter} drops to "
                f"{t['cost_concentration']:.0%} or below",
                {"kind": "adapter_cost_concentration_below",
                 "adapter": adapter, "value": t["cost_concentration"]},
                20.0,
            ))
    return out


def detect_signals(leaderboard: dict[str, Any],
                   run_payloads: dict[str, dict[str, Any]] | None = None,
                   previous_leaderboard: dict[str, Any] | None = None,
                   thresholds: dict[str, float] | None = None,
                   ) -> list[dict[str, Any]]:
    """Emit signal items for one monthly report.

    ``leaderboard`` is the current ``peira.dashboard.leaderboard``
    payload. ``run_payloads`` maps adapter name to its
    ``run_to_dashboard`` payload for per-family detail. Pass the
    previous month's leaderboard as ``previous_leaderboard`` to enable
    regression detection.
    """
    t = dict(DEFAULT_THRESHOLDS)
    if thresholds:
        t.update(thresholds)
    run_payloads = run_payloads or {}
    signals: list[dict[str, Any]] = []
    if previous_leaderboard:
        signals.extend(_detect_regressions(leaderboard, previous_leaderboard, t))
    signals.extend(_detect_family_risks(run_payloads, t))
    signals.extend(_detect_headline_issues(leaderboard, run_payloads, t))
    signals.extend(_detect_volume(leaderboard, run_payloads, t))
    # Highest score first; signal_id breaks ties deterministically.
    signals.sort(key=lambda s: (-s["score"], s["signal_id"]))
    return signals


# --- Success checks and registry roll-forward --------------------------------

def _adapter_row(leaderboard: dict[str, Any], adapter: str) -> dict[str, Any] | None:
    return _row_by_adapter(leaderboard, adapter)


def check_success(signal: dict[str, Any], leaderboard: dict[str, Any],
                  run_payloads: dict[str, dict[str, Any]] | None = None,
                  ) -> bool:
    """Evaluate a signal's falsifiable success metric against new data."""
    check = signal.get("success_check") or {}
    kind = check.get("kind")
    adapter = check.get("adapter")
    value = _num(check.get("value"))
    if value is None:
        return False
    run_payloads = run_payloads or {}
    if kind == "adapter_asr_at_most":
        row = _adapter_row(leaderboard, adapter)
        v = _num(row.get("asr_conditional")) if row else None
        return v is not None and v <= value
    if kind == "adapter_benign_accuracy_at_least":
        row = _adapter_row(leaderboard, adapter)
        v = _num(row.get("benign_accuracy")) if row else None
        return v is not None and v >= value
    if kind == "adapter_ece_at_most":
        row = _adapter_row(leaderboard, adapter)
        v = _num(row.get("ece_attacked")) if row else None
        return v is not None and v <= value
    if kind == "adapter_abstention_at_most":
        payload = run_payloads.get(adapter, {})
        headline = payload.get("headline") if isinstance(payload, dict) else {}
        v = _num(headline.get("abstention_rate")) if isinstance(headline, dict) else None
        return v is not None and v <= value
    if kind == "adapter_ci_width_below":
        row = _adapter_row(leaderboard, adapter)
        w = _ci_width(row.get("asr_ci95")) if row else None
        return w is not None and w < value
    if kind == "family_asr_below":
        payload = run_payloads.get(adapter, {})
        families = payload.get("families") if isinstance(payload, dict) else {}
        fam = families.get(check.get("family")) if isinstance(families, dict) else {}
        v = _num(fam.get("asr")) if isinstance(fam, dict) else None
        return v is not None and v < value
    if kind == "adapter_cost_concentration_below":
        payload = run_payloads.get(adapter, {})
        families = payload.get("families") if isinstance(payload, dict) else {}
        if not isinstance(families, dict):
            return False
        costs = [_num(f.get("cost_usd")) for f in families.values()
                 if isinstance(f, dict)]
        costs = [c for c in costs if c is not None and c > 0]
        total = sum(costs)
        if total <= 0 or len(costs) < 4:
            return False
        top3 = sum(sorted(costs, reverse=True)[:3])
        return (top3 / total) < value
    return False


def empty_registry() -> dict[str, Any]:
    return {"version": 1, "signals": {}}


def roll_forward(registry: dict[str, Any], signals: list[dict[str, Any]],
                 leaderboard: dict[str, Any],
                 run_payloads: dict[str, dict[str, Any]] | None = None,
                 report_id: str = "") -> dict[str, Any]:
    """Carry signal status across monthly reports.

    New signals enter as open. Open signals whose success metric now
    holds become implemented. Everything else stays open with its
    months_open counter incremented. Implemented signals stay
    implemented; the registry is append-only history.
    """
    tracked = copy.deepcopy(registry.get("signals") or {})
    if not isinstance(tracked, dict):
        tracked = {}
    seen = set()
    for s in signals:
        sid = s["signal_id"]
        seen.add(sid)
        entry = tracked.get(sid)
        if entry is None:
            tracked[sid] = {
                "status": "open",
                "months_open": 1,
                "first_seen": report_id,
                "title": s["title"],
                "success_metric": s["success_metric"],
                "success_check": s.get("success_check"),
            }
        elif entry.get("status") == "open":
            if check_success(s, leaderboard, run_payloads):
                entry["status"] = "implemented"
                entry["implemented_in"] = report_id
            else:
                entry["months_open"] = int(entry.get("months_open", 0)) + 1
    # Open signals the new report did not re-emit still get their success
    # metric evaluated: a recovered adapter emits no regression signal,
    # and that silence is exactly the success condition.
    for sid, entry in tracked.items():
        if sid in seen or entry.get("status") != "open":
            continue
        probe = {"signal_id": sid,
                 "success_check": entry.get("success_check")}
        if check_success(probe, leaderboard, run_payloads):
            entry["status"] = "implemented"
            entry["implemented_in"] = report_id
        else:
            entry["months_open"] = int(entry.get("months_open", 0)) + 1
    return {"version": 1, "signals": tracked}
