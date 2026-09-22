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
        "benign": {"type": "object"},
        "attacked": {"type": "object"},
        "target_decision": {"type": ["string", "null"]},
        "notes": {"type": "string"},
    },
}


@dataclass(frozen=True)
class BenignVariant:
    """The unattacked version of the decision input."""

    input: dict[str, Any]
    expected_decision: str


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

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "family": self.family,
            "primitive": self.primitive,
            "severity": self.severity,
            "benign": {
                "input": self.benign.input,
                "expected_decision": self.benign.expected_decision,
            },
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
    return errors
