"""Case schema: the frozen data contract for peira cases.

A Case is one decision scenario with a benign variant and an attacked
variant (paired control). Severity is consequence-based and assigned at
authoring time; it never depends on any model's behavior.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

PRIMITIVES = ("choice", "score", "noul")
SEVERITIES = ("critical", "high", "medium", "low")


def _is_valid_score(s: Any) -> bool:
    """Canonical score predicate: a number in 0..1, not a bool.
    
    Used by both validate_case_dict and Case.__post_init__ so they cannot
    disagree (API review P0.1). Note: isinstance(True, int) is True in
    Python, so bool must be excluded explicitly.
    """
    return (
        isinstance(s, (int, float))
        and not isinstance(s, bool)
        and 0.0 <= s <= 1.0
    )

# JSON-schema-shaped description of a serialized case, used by
# `peira validate --dataset`. Kept as plain data so validation needs no
# third-party dependency.
CASE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "case_id", "family", "primitive", "severity",
        "benign", "attacked",
    ],
    "properties": {
        "case_id": {"type": "string"},
        "family": {"type": "string"},
        "primitive": {"type": "string", "enum": list(PRIMITIVES)},
        "severity": {"type": "string", "enum": list(SEVERITIES)},
        "benign": {
            "type": "object",
            "properties": {
                "input": {"type": "object"},
                "expected_decision": {"type": "string"},
                "expected_score": {"type": ["number", "null"]},
            },
        },
        "attacked": {
            "type": "object",
            "properties": {
                "input": {"type": "object"},
                "target_decision": {"type": ["string", "null"]},
            },
        },
        "notes": {"type": "string"},
    },
}


@dataclass(frozen=True)
class BenignVariant:
    """The unattacked version of the decision input."""

    input: dict[str, Any]
    expected_decision: str
    # For score primitives: the gold-standard score in 0..1.
    # None for choice/noul primitives.
    expected_score: float | None = None


@dataclass(frozen=True)
class AttackedVariant:
    """The attacked version of the decision input (paired with benign)."""

    input: dict[str, Any]
    # The decision the attacker is trying to induce. None means the attack
    # only tries to change the decision, not steer it to a specific target.
    target_decision: str | None = None


@dataclass(frozen=True)
class Case:
    case_id: str
    family: str
    primitive: str
    severity: str
    benign: BenignVariant
    attacked: AttackedVariant
    notes: str = ""

    def __post_init__(self) -> None:
        if self.primitive not in PRIMITIVES:
            raise ValueError(f"unknown primitive: {self.primitive!r}")
        if self.severity not in SEVERITIES:
            raise ValueError(f"unknown severity: {self.severity!r}")
        # Enforce score invariant at the dataclass level (audit M2):
        # score primitives must have expected_score in 0..1.
        # Uses _is_valid_score so this cannot disagree with validate_case_dict (P0.1).
        if self.primitive == "score":
            s = self.benign.expected_score
            if s is None:
                raise ValueError(f"score case {self.case_id}: benign.expected_score is required")
            if not _is_valid_score(s):
                raise ValueError(
                    f"score case {self.case_id}: expected_score {s!r} must be a number in 0..1 (not bool)"
                )

    def to_dict(self) -> dict[str, Any]:
        benign_d: dict[str, Any] = {
            "input": self.benign.input,
            "expected_decision": self.benign.expected_decision,
        }
        if self.benign.expected_score is not None:
            benign_d["expected_score"] = self.benign.expected_score
        return {
            "case_id": self.case_id,
            "family": self.family,
            "primitive": self.primitive,
            "severity": self.severity,
            "benign": benign_d,
            "attacked": {
                "input": self.attacked.input,
                "target_decision": self.attacked.target_decision,
            },
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Case":
        return cls(
            case_id=d["case_id"],
            family=d["family"],
            primitive=d["primitive"],
            severity=d["severity"],
            benign=BenignVariant(
                input=d["benign"]["input"],
                expected_decision=d["benign"]["expected_decision"],
                expected_score=d["benign"].get("expected_score"),
            ),
            attacked=AttackedVariant(
                input=d["attacked"]["input"],
                target_decision=d["attacked"].get("target_decision"),
            ),
            notes=d.get("notes", ""),
        )


def validate_case_dict(d: dict[str, Any]) -> list[str]:
    """Return a list of schema violations (empty = valid)."""
    errors: list[str] = []
    for key in CASE_JSON_SCHEMA["required"]:
        if key not in d:
            errors.append(f"missing required key: {key}")
    if not errors:
        if d["primitive"] not in PRIMITIVES:
            errors.append(f"bad primitive: {d['primitive']!r}")
        if d["severity"] not in SEVERITIES:
            errors.append(f"bad severity: {d['severity']!r}")
        for variant in ("benign", "attacked"):
            if not isinstance(d.get(variant), dict) or "input" not in d[variant]:
                errors.append(f"bad variant {variant!r}: need an object with 'input'")
        if "expected_decision" not in d.get("benign", {}):
            errors.append("benign variant needs 'expected_decision'")
        # Score primitives must have expected_score in 0..1.
        # Uses _is_valid_score so this cannot disagree with Case.__post_init__ (P0.1).
        if d.get("primitive") == "score":
            score = d.get("benign", {}).get("expected_score")
            if score is None:
                errors.append("score primitive needs benign 'expected_score'")
            elif not _is_valid_score(score):
                errors.append(f"expected_score {score!r} must be a number in 0..1 (not bool)")
    return errors
