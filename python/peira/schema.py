"""Case schema: the frozen data contract for peira cases.

A Case is one decision scenario with a benign variant and an attacked
variant (paired control). Severity is consequence-based and assigned at
authoring time; it never depends on any model's behavior.

Forward compatibility: the schema is closed for required fields but open
for extension. Validators ignore unknown top-level fields, and
:meth:`Case.from_dict` preserves them on :attr:`Case.extras` so they
survive the whole pipeline (load → run → artifact) without any code
changes. Future per-case configuration (new top-level fields) therefore
needs no refactoring: only the consumer of the new field has to know
about it. Adapters receive the variant ``input`` dicts unchanged, so
advanced configuration can also live inside ``input`` today.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from peira._rust import _impl as _rust

PRIMITIVES = ("choice", "score", "noul")
SEVERITIES = ("critical", "high", "medium", "low")

# The ten canonical attack families (docs/Taxonomy.md). The frozen case
# schema accepts any family string at runtime; the dataset gates (the
# authoring-time contract) require these IDs.
CANONICAL_FAMILIES = (
    "state_poisoning",
    "criteria_smuggling",
    "option_order",
    "distractor_flooding",
    "score_anchoring",
    "literal_reading",
    "negation_games",
    "policy_paraphrase",
    "indirection",
    "confidence_spoofing",
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
        "benign": {"type": "object"},
        "attacked": {"type": "object"},
        "target_decision": {"type": ["string", "null"]},
        "notes": {"type": "string"},
    },
}


def _safe_repr(s: str) -> str:
    """String rendering with a fixed escaping rule shared with the Rust core.

    This is repr() with one deliberate difference: CPython escapes
    non-printable non-ASCII (e.g. U+200B ZERO WIDTH SPACE) as ``\\uNNNN``,
    which the Rust side cannot reproduce without a Unicode database. This
    helper escapes exactly the C0/DEL/C1 controls (as ``\\xNN``),
    backslash, and the active quote — everything else passes through raw —
    so schema error strings are byte-identical no matter which language
    produced them. The rule is implemented independently in
    ``crates/peira-core/src/py_repr.rs``; the two must stay in sync.

    For all realistic inputs (ASCII case fields) the output equals
    repr().
    """
    quote = '"' if ("'" in s and '"' not in s) else "'"
    out = [quote]
    for ch in s:
        o = ord(ch)
        if ch == quote:
            out.append("\\" + quote)
        elif ch == "\\":
            out.append("\\\\")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif o < 0x20 or 0x7F <= o <= 0x9F:
            out.append(f"\\x{o:02x}")
        else:
            out.append(ch)
    out.append(quote)
    return "".join(out)


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
    # Unknown top-level fields from the source dict, preserved verbatim.
    # This is the forward-compatibility mechanism: new per-case
    # configuration rides here without touching the schema, the loader,
    # the gates, or the artifact format.
    extras: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.primitive not in PRIMITIVES:
            raise ValueError(f"unknown primitive: {_safe_repr(self.primitive)}")
        if self.severity not in SEVERITIES:
            raise ValueError(f"unknown severity: {_safe_repr(self.severity)}")

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
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
        d.update(self.extras)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Case":
        known = {
            "case_id", "family", "primitive", "severity",
            "benign", "attacked", "notes",
        }
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
            extras={k: v for k, v in d.items() if k not in known},
        )


def _validate_case_dict_py(d: dict[str, Any]) -> list[str]:
    """Reference implementation of :func:`validate_case_dict` (pure Python).

    Presence and enum membership are not enough: the declared JSON types
    are enforced too, so a schema-valid case can never crash the runner
    downstream (non-dict ``input``, non-string ``expected_decision``,
    unhashable ``case_id``, ...).
    """
    errors: list[str] = []
    if not isinstance(d, dict):
        # Mirrors the Rust behavior for non-object input: every required
        # key is "missing" from a scalar or list, and no per-field check
        # can run. Without this, a scalar JSONL line crashed outright.
        for key in CASE_JSON_SCHEMA["required"]:
            errors.append(f"missing required key: {key}")
        return errors
    for key in CASE_JSON_SCHEMA["required"]:
        if key not in d:
            errors.append(f"missing required key: {key}")
    if not errors:
        if not isinstance(d["case_id"], str):
            errors.append("bad case_id: expected string")
        if not isinstance(d["family"], str):
            errors.append("bad family: expected string")
        if not isinstance(d["primitive"], str):
            errors.append("bad primitive: expected string")
        elif d["primitive"] not in PRIMITIVES:
            errors.append(f"bad primitive: {_safe_repr(d['primitive'])}")
        if not isinstance(d["severity"], str):
            errors.append("bad severity: expected string")
        elif d["severity"] not in SEVERITIES:
            errors.append(f"bad severity: {_safe_repr(d['severity'])}")
        for variant in ("benign", "attacked"):
            v = d.get(variant)
            if not isinstance(v, dict) or "input" not in v:
                errors.append(f"bad variant {_safe_repr(variant)}: need an object with 'input'")
            elif not isinstance(v["input"], dict):
                errors.append(f"bad {variant} input: expected object")
        benign = d.get("benign")
        if isinstance(benign, dict):
            if "expected_decision" not in benign:
                errors.append("benign variant needs 'expected_decision'")
            elif not isinstance(benign["expected_decision"], str):
                errors.append("bad benign expected_decision: expected string")
        attacked = d.get("attacked")
        if isinstance(attacked, dict) and "target_decision" in attacked:
            target = attacked["target_decision"]
            if target is not None and not isinstance(target, str):
                errors.append("bad attacked target_decision: expected string or null")
        if "notes" in d and not isinstance(d["notes"], str):
            errors.append("bad notes: expected string")
    return errors


def validate_case_dict(d: dict[str, Any]) -> list[str]:
    """Return a list of schema violations (empty = valid).

    Uses the compiled Rust core when it is installed; otherwise the
    pure-Python reference implementation. Both return identical errors.
    """
    if _rust is not None:
        try:
            return _rust.validate_case_dict(d)
        except (TypeError, ValueError):
            # Values with no JSON representation (non-finite floats,
            # integers wider than u64, non-string keys) cannot cross the
            # boundary; validate them with the reference implementation.
            pass
    return _validate_case_dict_py(d)
