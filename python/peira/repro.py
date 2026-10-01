"""Determinism-verification primitives: the executable form of the
determinism contract in docs/Execution-Contract.md.

Two runs of the same adapter on the same cases with the same seed must
produce the same decisions. Wall-clock timing and the AIMD
controller's live concurrency limit are operational telemetry, not
measurement, so the contract excludes them from the comparison.
Everything else must match exactly, except floating-point metric
values which compare within a small absolute tolerance.

Consumers: tests/test_determinism.py exercises the runner directly,
scripts/check_determinism.py applies these primitives to real CLI
reruns in CI. One shared definition of the excluded fields keeps both
honest.
"""

from __future__ import annotations

import copy
import math
from typing import Any

#: Call-record fields excluded by the determinism contract. Timing
#: values are wall-clock measurements; dispatch_limit is the AIMD
#: controller's live limit at dispatch time, which is timing-dependent
#: even under an identical configuration.
EXCLUDED_CALL_RECORD_FIELDS = frozenset(
    {"dispatch_limit", "latency_ms_total", "timing_ms"}
)

#: The usage sub-object's excluded field (wall-clock timing).
EXCLUDED_USAGE_FIELDS = frozenset({"latency_ms"})

#: Metric-summary keys excluded by the contract (wall-clock rollups).
EXCLUDED_METRIC_KEYS = frozenset({"latency_ms", "timing_ms"})

#: Absolute tolerance for floating-point metric comparison. This
#: absorbs float formatting noise only, not real divergence: a metric
#: that moves by more than this between identical reruns is a
#: determinism break.
FLOAT_ABS_TOL = 1e-9


def normalize_call_record(rec: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of a call record with contract-excluded fields blanked."""
    rec = copy.deepcopy(rec)
    for field in EXCLUDED_CALL_RECORD_FIELDS:
        if field in rec:
            rec[field] = f"excluded-by-contract:{field}"
    usage = rec.get("usage")
    if isinstance(usage, dict):
        for field in EXCLUDED_USAGE_FIELDS:
            if field in usage:
                usage[field] = f"excluded-by-contract:{field}"
    return rec


def normalize_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize every per-case entry's benign/attacked call records."""
    norm = []
    for entry in results:
        entry = copy.deepcopy(entry)
        for arm in ("benign", "attacked"):
            arm_rec = entry.get(arm)
            if isinstance(arm_rec, dict):
                entry[arm] = normalize_call_record(arm_rec)
        norm.append(entry)
    return norm


def normalize_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of a metric summary with excluded keys blanked."""
    metrics = copy.deepcopy(metrics)
    for key in EXCLUDED_METRIC_KEYS:
        if key in metrics:
            metrics[key] = f"excluded-by-contract:{key}"
    return metrics


def normalize_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    """Normalize a whole artifact dict for rerun comparison.

    Results and metrics are normalized per the contract. Run-level
    bookkeeping that legitimately differs between reruns
    (``created_utc``, ``analysis_lock``, ``env``) is left in place:
    callers compare the measurement content, not the bookkeeping.
    """
    artifact = copy.deepcopy(artifact)
    if isinstance(artifact.get("results"), list):
        artifact["results"] = normalize_results(artifact["results"])
    if isinstance(artifact.get("metrics"), dict):
        artifact["metrics"] = normalize_metrics(artifact["metrics"])
    return artifact


def _compare_values(path: str, a: Any, b: Any, tol: float) -> list[str]:
    """Compare two JSON values, returning mismatch descriptions."""
    if isinstance(a, bool) or isinstance(b, bool):
        # bool is not a number here: True must never equal 1.
        if a is not b and a != b:
            return [f"{path}: {a!r} != {b!r}"]
        return []
    if isinstance(a, float) or isinstance(b, float):
        af, bf = float(a), float(b)
        if not math.isfinite(af) or not math.isfinite(bf):
            if af != bf:
                return [f"{path}: {a!r} != {b!r}"]
            return []
        if abs(af - bf) > tol:
            return [f"{path}: {a!r} != {b!r} (tol {tol})"]
        return []
    if isinstance(a, dict) and isinstance(b, dict):
        mismatches = []
        for key in sorted(set(a) | set(b)):
            if key not in a:
                mismatches.append(f"{path}.{key}: missing in first run")
            elif key not in b:
                mismatches.append(f"{path}.{key}: missing in second run")
            else:
                mismatches.extend(
                    _compare_values(f"{path}.{key}", a[key], b[key], tol)
                )
        return mismatches
    if isinstance(a, list) and isinstance(b, list):
        mismatches = []
        if len(a) != len(b):
            return [f"{path}: length {len(a)} != {len(b)}"]
        for i, (x, y) in enumerate(zip(a, b)):
            mismatches.extend(_compare_values(f"{path}[{i}]", x, y, tol))
        return mismatches
    if a != b:
        return [f"{path}: {a!r} != {b!r}"]
    return []


def compare_artifacts(
    a: dict[str, Any],
    b: dict[str, Any],
    *,
    float_abs_tol: float = FLOAT_ABS_TOL,
) -> list[str]:
    """Compare two normalized artifact dicts.

    Returns a list of human-readable mismatch descriptions; empty
    means the reruns reproduce. Decisions, seeds, flags, and strings
    must match exactly; floats compare within ``float_abs_tol``.
    Compare :func:`normalize_artifact` output, not raw artifacts.
    """
    mismatches: list[str] = []
    for key in ("results", "metrics", "seed", "cases_completed",
                "cases_planned", "termination"):
        if key in a or key in b:
            mismatches.extend(
                _compare_values(key, a.get(key), b.get(key), float_abs_tol)
            )
    return mismatches


def artifacts_reproduce(
    a: dict[str, Any],
    b: dict[str, Any],
    *,
    float_abs_tol: float = FLOAT_ABS_TOL,
) -> bool:
    """True when two normalized artifact dicts reproduce each other."""
    return not compare_artifacts(a, b, float_abs_tol=float_abs_tol)
