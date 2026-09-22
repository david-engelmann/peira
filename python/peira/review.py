"""Human review queue (stdlib only).

Automation checks structure; humans judge quality. The review queue
tracks which cases a human has reviewed, enforcing the project rule:
100% of critical-severity cases are human-reviewed before release.

Review state lives in ``<dataset-dir>/review.json``::

    {"sp-001": {"status": "approved", "reviewer": "dg",
                "at": "2026-09-22T21:00:00+00:00", "notes": "..."}}

A case needs review when it is critical-severity and not approved, or
when it carries gate warnings (currently G6 pii-scan) and is not
approved. ``rejected`` means sent back for rework — it does not count
as reviewed.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from peira.dataset import iter_case_lines
from peira.gates import gate_pii_scan
from peira.schema import validate_case_dict

REVIEW_NAME = "review.json"

APPROVED = "approved"
REJECTED = "rejected"
PENDING = "pending"

STATUSES = (APPROVED, REJECTED, PENDING)


def _review_path(dataset_dir: Path) -> Path:
    return dataset_dir / REVIEW_NAME


def load_review_states(dataset_dir: Path) -> dict[str, dict[str, Any]]:
    """Read review.json. Missing file means nothing reviewed yet; a
    corrupt file is an error, not silent loss."""
    path = _review_path(dataset_dir)
    if not path.exists():
        return {}
    try:
        states = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"{REVIEW_NAME} is not valid JSON ({e})")
    if not isinstance(states, dict):
        raise ValueError(f"{REVIEW_NAME} must be a JSON object")
    return states


def save_review_states(dataset_dir: Path,
                       states: dict[str, dict[str, Any]]) -> Path:
    path = _review_path(dataset_dir)
    path.write_text(json.dumps(states, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")
    return path


def _valid_cases(dataset_dir: Path) -> list[tuple[Any, int, str, dict[str, Any]]]:
    """(path, lineno, case_id, case) for every schema-valid case."""
    out = []
    for path, lineno, case, json_error in iter_case_lines(dataset_dir):
        if json_error is None and not validate_case_dict(case):
            out.append((path, lineno, case["case_id"], case))
    return out


def pending_reviews(dataset_dir: Path) -> list[dict[str, Any]]:
    """Cases still needing human review, each with ``case_id``,
    ``severity``, and ``reasons``."""
    states = load_review_states(dataset_dir)
    cases = _valid_cases(dataset_dir)
    pending = []
    for path, lineno, case_id, case in cases:
        if states.get(case_id, {}).get("status") == APPROVED:
            continue
        reasons = []
        if case["severity"] == "critical":
            reasons.append("critical severity — requires human review")
        for w in gate_pii_scan([(path, lineno, case)]).warnings:
            reasons.append(w.split(": ", 1)[-1] if ": " in w else w)
        if reasons:
            pending.append({"case_id": case_id,
                            "severity": case["severity"],
                            "reasons": reasons})
    return pending


def review_coverage(dataset_dir: Path) -> dict[str, Any]:
    """Review statistics, including the critical-severity coverage the
    project rule requires to be 100% before release."""
    states = load_review_states(dataset_dir)
    cases = _valid_cases(dataset_dir)
    n_critical = sum(1 for _, _, _, c in cases if c["severity"] == "critical")
    n_approved = sum(1 for _, _, cid, c in cases
                     if c["severity"] == "critical"
                     and states.get(cid, {}).get("status") == APPROVED)
    pending = pending_reviews(dataset_dir)
    return {
        "n_cases": len(cases),
        "n_critical": n_critical,
        "n_critical_approved": n_approved,
        "critical_coverage": (n_approved / n_critical
                              if n_critical else None),
        "n_pending": len(pending),
    }


def mark_reviewed(dataset_dir: Path, case_id: str, status: str,
                  reviewer: str = "", notes: str = "") -> dict[str, Any]:
    """Record a review decision. Raises KeyError for an unknown case id
    and ValueError for a bad status."""
    if status not in STATUSES:
        raise ValueError(f"unknown review status {status!r} "
                         f"(choose from {', '.join(STATUSES)})")
    known = {cid for _, _, cid, _ in _valid_cases(dataset_dir)}
    if case_id not in known:
        raise KeyError(f"unknown case id {case_id!r} in {dataset_dir}")
    states = load_review_states(dataset_dir)
    entry = {"status": status,
             "reviewer": reviewer,
             "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "notes": notes}
    states[case_id] = entry
    save_review_states(dataset_dir, states)
    return entry
