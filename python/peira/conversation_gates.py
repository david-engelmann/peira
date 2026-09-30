"""Conversational suite: dataset gates CG1-CG5 (R-01).

Part of the conversational suite; see ``peira.conversation`` for the
suite overview.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from peira.conversation_schema import (
    KNOWN_CONVERSATION_FAMILIES,
    validate_conversation_dict,
)

# ---------------------------------------------------------------------------
# Validation gates
# ---------------------------------------------------------------------------


@dataclass
class ConversationGateResult:
    gate_id: str
    name: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.errors


def _gate_conv_schema(
    checked: list[tuple[Path, int, Any, str | None]],
) -> ConversationGateResult:
    """CG1: every case parses and satisfies the conversational schema."""
    r = ConversationGateResult("CG1", "schema")
    for path, lineno, _case, error in checked:
        if error:
            where = (
                f"{path.name}:{lineno}" if path is not None
                else f"case:{lineno}"
            )
            r.errors.append(f"{where}: {error}")
    return r


def _gate_conv_paired(
    valid: list[tuple[Path, int, dict]],
) -> ConversationGateResult:
    """CG2: benign/attacked trajectories are a coherent pair."""
    r = ConversationGateResult("CG2", "paired-trajectories")
    for path, lineno, case in valid:
        where = f"{path.name}:{lineno}"
        b, a = case["benign"], case["attacked"]
        if b["options"] != a["options"]:
            r.errors.append(
                f"{where}: benign/attacked options differ "
                f"({b['options']!r} vs {a['options']!r}): the final "
                f"decisions are not comparable"
            )
        b_roles = [t["role"] for t in b["turns"]]
        a_roles = [t["role"] for t in a["turns"]]
        if b_roles != a_roles:
            r.warnings.append(
                f"{where}: benign/attacked role sequences differ "
                f"({b_roles} vs {a_roles}): paired designs usually "
                f"keep them parallel; flagged for author review"
            )
        for i, t in enumerate(a["turns"]):
            if t.get("attack") is True and not t.get("attack_note"):
                r.errors.append(
                    f"{where}: attacked.turns[{i}] is attack-marked "
                    f"without attack_note"
                )
        for i, t in enumerate(b["turns"]):
            if t.get("attack") is True:
                r.errors.append(
                    f"{where}: benign.turns[{i}] carries an attack mark"
                )
    return r


def _gate_conv_dedup(
    valid: list[tuple[Path, int, dict]],
) -> ConversationGateResult:
    """CG3: case ids are unique across the suite."""
    r = ConversationGateResult("CG3", "dedup")
    seen: dict[str, str] = {}
    for path, lineno, case in valid:
        cid = case["case_id"]
        where = f"{path.name}:{lineno}"
        if cid in seen:
            r.errors.append(
                f"{where}: duplicate case_id {cid!r} "
                f"(first seen at {seen[cid]})"
            )
        else:
            seen[cid] = where
    return r


def _gate_conv_families(
    valid: list[tuple[Path, int, dict]],
) -> ConversationGateResult:
    """CG4: family names are known (warning) and non-empty (schema)."""
    r = ConversationGateResult("CG4", "families")
    for path, lineno, case in valid:
        family = case["family"]
        if family not in KNOWN_CONVERSATION_FAMILIES:
            r.warnings.append(
                f"{path.name}:{lineno}: unknown conversational family "
                f"{family!r} (known: "
                f"{sorted(KNOWN_CONVERSATION_FAMILIES)})"
            )
    return r


def _canon_trajectory(case: dict[str, Any]) -> str:
    parts = []
    for arm in ("benign", "attacked"):
        for t in case[arm]["turns"]:
            parts.append(f"{t['role']}:{t['content']}")
    return "\n".join(parts)


def _gate_conv_near_dedup(
    valid: list[tuple[Path, int, dict]],
) -> ConversationGateResult:
    """CG5: no two cases share an identical trajectory pair."""
    r = ConversationGateResult("CG5", "near-dedup")
    seen: dict[str, str] = {}
    for path, lineno, case in valid:
        key = _canon_trajectory(case)
        where = f"{path.name}:{lineno}"
        if key in seen:
            r.warnings.append(
                f"{where}: trajectory pair duplicates {seen[key]} "
                f"(case {case['case_id']!r})"
            )
        else:
            seen[key] = f"{where} (case {case['case_id']!r})"
    return r


def run_conversation_gates(
    dataset_dir: Path,
) -> list[ConversationGateResult]:
    """Run all conversational gates over a dataset directory, in order.

    Mirrors :func:`peira.gates.run_gates`: one pass parses and
    validates every ``*.jsonl`` line exactly once; CG1 reports the
    schema errors, CG2-CG5 consume the valid subset.
    """
    checked: list[tuple[Path, int, Any, str | None]] = []
    for path in sorted(Path(dataset_dir).glob("*.jsonl")):
        with open(path, encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                if not line.strip():
                    continue
                try:
                    case = json.loads(line)
                except json.JSONDecodeError as e:
                    checked.append(
                        (path, lineno, None, f"invalid JSON ({e})")
                    )
                    continue
                errors = validate_conversation_dict(case)
                checked.append(
                    (
                        path,
                        lineno,
                        case,
                        "; ".join(errors) if errors else None,
                    )
                )
    results = [_gate_conv_schema(checked)]
    valid = [(p, n, c) for p, n, c, e in checked if e is None]
    results.append(_gate_conv_paired(valid))
    results.append(_gate_conv_dedup(valid))
    results.append(_gate_conv_families(valid))
    results.append(_gate_conv_near_dedup(valid))
    return results
