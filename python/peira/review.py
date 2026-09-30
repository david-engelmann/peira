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

from peira.dataset import atomic_write_text, iter_cases
from peira.gates import gate_pii_scan

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
    # Atomic write: a crash mid-write must not leave a corrupt
    # review.json behind.
    return atomic_write_text(
        _review_path(dataset_dir),
        json.dumps(states, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")


def _valid_cases(dataset_dir: Path,
                 *, kind: str = "single") -> list[tuple[Any, int, str, dict[str, Any]]]:
    """(path, lineno, case_id, case) for every schema-valid case.

    Invalid case data raises ValueError (via `iter_cases`) instead of
    being silently skipped: review decisions must never be computed
    over a partially-read dataset.

    ``kind`` selects the case schema: ``"single"`` reads single-shot
    cases, ``"conversational"`` reads conversational cases.
    """
    if kind == "conversational":
        from peira.conversation import load_conversation_cases

        cases = load_conversation_cases(dataset_dir)
        out = []
        for i, case in enumerate(cases):
            out.append((dataset_dir, i + 1, case.case_id, {
                "case_id": case.case_id,
                "family": case.family,
                "severity": case.severity,
                "primitive": case.primitive,
                "notes": case.notes,
            }))
        return out
    return [(p, n, c["case_id"], c) for p, n, c in iter_cases(dataset_dir)]


def _cases_or_raise(dataset_dir: Path,
                    *, kind: str = "single"):
    """Valid cases, or ValueError("unreadable case data: ...").

    Centralizes the case-data error wording so every CLI review path
    reports it identically (see docs/Troubleshooting.md).
    """
    try:
        return _valid_cases(dataset_dir, kind=kind)
    except ValueError as e:
        raise ValueError(f"unreadable case data: {e}") from e


def _states_or_raise(dataset_dir: Path):
    """Review states, or ValueError("unreadable review state: ...")."""
    try:
        return load_review_states(dataset_dir)
    except ValueError as e:
        raise ValueError(f"unreadable review state: {e}") from e


def critical_cases_missing_notes(dataset_dir: Path,
                                   *, kind: str = "single") -> list[str]:
    """Case ids of critical-severity cases with no severity notes.

    The severity rubric asks the author to say why a case earned its
    tier in the case notes; the release seal (``peira dataset
    build-manifest``) refuses while any critical case lacks that
    justification. ``notes`` is an optional schema field, so a missing
    key counts the same as a blank one.

    ``kind`` selects the case schema (``"single"`` or
    ``"conversational"``).
    """
    return [cid for _, _, cid, case in _cases_or_raise(dataset_dir, kind=kind)
            if case["severity"] == "critical"
            and not str(case.get("notes") or "").strip()]


def pending_reviews(dataset_dir: Path,
                    *, kind: str = "single") -> list[dict[str, Any]]:
    """Cases still needing human review, each with ``case_id``,
    ``severity``, and ``reasons``.

    ``kind`` selects the case schema (``"single"`` or
    ``"conversational"``). For conversational cases the PII scan runs
    over the serialized turn contents of both arms.
    """
    states = _states_or_raise(dataset_dir)
    cases = _cases_or_raise(dataset_dir, kind=kind)
    conv_by_id: dict[str, Any] = {}
    if kind == "conversational":
        from peira.conversation import load_conversation_cases

        conv_by_id = {c.case_id: c
                      for c in load_conversation_cases(dataset_dir)}
    pending = []
    for path, lineno, case_id, case in cases:
        if states.get(case_id, {}).get("status") == APPROVED:
            continue
        reasons = []
        if case["severity"] == "critical":
            reasons.append("critical severity — requires human review")
        if kind == "conversational":
            conv = conv_by_id.get(case_id)
            if conv is not None:
                for w in _conversation_pii_warnings(
                        path, lineno, conv):
                    reasons.append(w)
        else:
            for w in gate_pii_scan([(path, lineno, case)]).warnings:
                reasons.append(w.split(": ", 1)[-1] if ": " in w else w)
        if reasons:
            pending.append({"case_id": case_id,
                            "severity": case["severity"],
                            "reasons": reasons})
    return pending


def _conversation_pii_warnings(path: Any, lineno: int,
                               case: Any) -> list[str]:
    """PII-pattern warnings over a conversational case's turn contents.

    Mirrors the G6 PII scan's patterns, but over the serialized turns
    of both arms instead of single-shot variant inputs.
    """
    import json as _json

    from peira.gates import _PII_PATTERNS

    warnings: list[str] = []
    for arm_name, arm in (("benign", case.benign),
                          ("attacked", case.attacked)):
        text = _json.dumps(
            [{"role": t.role, "content": t.content}
             for t in arm.turns], sort_keys=True)
        for label, pattern in _PII_PATTERNS:
            if pattern.search(text):
                name = path.name if hasattr(path, "name") else str(path)
                warnings.append(
                    f"{name}:{lineno}: possible {label} in "
                    f"{arm_name} turns")
                break
    return warnings


def review_coverage(dataset_dir: Path,
                    *, kind: str = "single") -> dict[str, Any]:
    """Review statistics, including the critical-severity coverage the
    project rule requires to be 100% before release.

    ``kind`` selects the case schema (``"single"`` or
    ``"conversational"``).
    """
    states = _states_or_raise(dataset_dir)
    cases = _cases_or_raise(dataset_dir, kind=kind)
    n_critical = sum(1 for _, _, _, c in cases if c["severity"] == "critical")
    n_approved = sum(1 for _, _, cid, c in cases
                     if c["severity"] == "critical"
                     and states.get(cid, {}).get("status") == APPROVED)
    pending = pending_reviews(dataset_dir, kind=kind)
    return {
        "n_cases": len(cases),
        "n_critical": n_critical,
        "n_critical_approved": n_approved,
        "critical_coverage": (n_approved / n_critical
                              if n_critical else None),
        "n_pending": len(pending),
    }


def mark_reviewed(dataset_dir: Path, case_id: str, status: str,
                  reviewer: str = "", notes: str = "",
                  *, kind: str = "single") -> dict[str, Any]:
    """Record a review decision. Raises KeyError for an unknown case id
    and ValueError for a bad status.

    ``kind`` selects the case schema (``"single"`` or
    ``"conversational"``).
    """
    if status not in STATUSES:
        raise ValueError(f"unknown review status {status!r} "
                         f"(choose from {', '.join(STATUSES)})")
    known = {cid for _, _, cid, _ in _cases_or_raise(dataset_dir, kind=kind)}
    if case_id not in known:
        raise KeyError(f"unknown case id {case_id!r} in {dataset_dir}")
    states = _states_or_raise(dataset_dir)
    entry = {"status": status,
             "reviewer": reviewer,
             "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "notes": notes}
    states[case_id] = entry
    # No lock around the read-modify-write: concurrent `review approve`
    # invocations race and the last writer wins. review.json is
    # human-scale and every write is a deliberate decision, so a lost
    # update surfaces at the next `review --check` — never silently.
    # The write itself is atomic (see save_review_states), so the file
    # is always well-formed.
    save_review_states(dataset_dir, states)
    return entry
