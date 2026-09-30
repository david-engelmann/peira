"""Conversational suite: case schema and validation (R-01).

Paired-trajectory case schema (benign/attacked multi-turn
trajectories), raw-dict validation, and the JSONL loader. Part of the
conversational suite; see ``peira.conversation`` for the suite
overview. Conversational results are never blended with the paired
single-decision v1/v2 numbers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from peira.schema import PRIMITIVES, SEVERITIES

# The suite id sealed into run artifacts. Conversational artifacts are
# namespaced by this id and never pooled with v1/v2 numbers.
CONVERSATION_SUITE_ID = "conversational"

# Turn roles. "user" turns are executed through the adapter; "assistant"
# turns are fixed, authored history spliced in without a call.
CONVERSATION_ROLES = ("user", "assistant")

# Bound on executed (user) turns per arm. The dispatch-index stride is
# derived from this bound, so raising it changes dispatch indices: do
# it deliberately, never casually. Sixteen turns is generous headroom
# for the escalation/splitting families this suite will host.
MAX_TURNS_PER_ARM = 16

# Dispatch-index stride per case: 2 * MAX_TURNS_PER_ARM. Benign turn t
# of case i uses base + 2t, attacked turn t uses base + 2t + 1, where
# base = stride * i. Indices are suite-position-derived (never run
# order), so resumed runs re-derive identical indices.
CONVERSATION_DISPATCH_STRIDE = 2 * MAX_TURNS_PER_ARM

# The only keys a turn object may carry. Turns have a fixed contract:
# there is nowhere in a turn to smuggle gold, family, or holdout
# labels. Case-level extras ride on the case, never on turns.
_TURN_KEYS = frozenset({"role", "content", "attack", "attack_note"})

# Attack families this suite will host, in landing order. Unknown
# families are a gate warning, not an error, so future families never
# need a gate change to land.
KNOWN_CONVERSATION_FAMILIES = frozenset(
    {"multi_turn_escalation", "decision_splitting"}
)


@dataclass(frozen=True)
class ConversationTurn:
    """One authored turn of a trajectory."""

    role: str  # "user" (executed) or "assistant" (fixed history)
    content: str  # non-empty
    # True when this turn advances the attack. Only meaningful in the
    # attacked arm: a benign trajectory must not carry attack marks.
    attack: bool = False
    # The author's note on what this turn does (mechanism annotation).
    # Required on attack turns; never shown to the adapter.
    attack_note: str = ""


@dataclass(frozen=True)
class BenignConversation:
    """The unattacked trajectory of a conversational case."""

    turns: list[ConversationTurn]
    # The decision vocabulary for the final turn (B2 discipline, same
    # as single-shot inputs): the adapter's options on every turn.
    options: list[str]
    expected_decision: str
    # Author reference score (0..1) for score-primitive cases; same
    # semantics as the single-shot BenignVariant.
    expected_score: float | None = None
    positive_decision: str | None = None


@dataclass(frozen=True)
class AttackedConversation:
    """The attacked trajectory (paired with the benign one)."""

    turns: list[ConversationTurn]
    options: list[str]
    # The decision the attacker tries to induce. None means the attack
    # only tries to change the decision, not steer it somewhere.
    target_decision: str | None = None


@dataclass(frozen=True)
class ConversationalCase:
    case_id: str
    family: str
    primitive: str
    severity: str
    benign: BenignConversation
    attacked: AttackedConversation
    notes: str = ""
    # Same training-exclusion flags as single-shot cases: every peira
    # benchmark case is evaluation-only data.
    evaluation_only: bool = True
    do_not_train: bool = True
    # Unknown top-level fields, preserved verbatim (forward compat).
    extras: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.primitive not in PRIMITIVES:
            raise ValueError(f"unknown primitive: {self.primitive!r}")
        if self.severity not in SEVERITIES:
            raise ValueError(f"unknown severity: {self.severity!r}")
        if not isinstance(self.evaluation_only, bool):
            raise ValueError(
                f"bad evaluation_only: {self.evaluation_only!r}"
            )
        if not isinstance(self.do_not_train, bool):
            raise ValueError(f"bad do_not_train: {self.do_not_train!r}")

    def user_turns(self, arm: str) -> list[ConversationTurn]:
        """The executed (user) turns of one arm, in order."""
        traj = self.benign if arm == "benign" else self.attacked
        return [t for t in traj.turns if t.role == "user"]

    def to_dict(self) -> dict[str, Any]:
        def _arm_to_dict(arm: Any, gold: dict[str, Any]) -> dict[str, Any]:
            return {
                "turns": [
                    {
                        "role": t.role,
                        "content": t.content,
                        "attack": t.attack,
                        "attack_note": t.attack_note,
                    }
                    for t in arm.turns
                ],
                "options": list(arm.options),
                **gold,
            }

        d: dict[str, Any] = {
            "case_id": self.case_id,
            "family": self.family,
            "primitive": self.primitive,
            "severity": self.severity,
            "benign": _arm_to_dict(
                self.benign,
                {
                    "expected_decision": self.benign.expected_decision,
                    "expected_score": self.benign.expected_score,
                    "positive_decision": self.benign.positive_decision,
                },
            ),
            "attacked": _arm_to_dict(
                self.attacked,
                {"target_decision": self.attacked.target_decision},
            ),
            "notes": self.notes,
            "evaluation_only": self.evaluation_only,
            "do_not_train": self.do_not_train,
        }
        d.update(self.extras)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ConversationalCase":
        known = {
            "case_id", "family", "primitive", "severity",
            "benign", "attacked", "notes",
            "evaluation_only", "do_not_train",
        }

        def _turn(t: dict[str, Any]) -> ConversationTurn:
            return ConversationTurn(
                role=t["role"],
                content=t["content"],
                attack=t.get("attack", False),
                attack_note=t.get("attack_note", ""),
            )

        b, a = d["benign"], d["attacked"]
        return cls(
            case_id=d["case_id"],
            family=d["family"],
            primitive=d["primitive"],
            severity=d["severity"],
            benign=BenignConversation(
                turns=[_turn(t) for t in b["turns"]],
                options=list(b["options"]),
                expected_decision=b["expected_decision"],
                expected_score=b.get("expected_score"),
                positive_decision=b.get("positive_decision"),
            ),
            attacked=AttackedConversation(
                turns=[_turn(t) for t in a["turns"]],
                options=list(a["options"]),
                target_decision=a.get("target_decision"),
            ),
            notes=d.get("notes", ""),
            evaluation_only=d.get("evaluation_only", True),
            do_not_train=d.get("do_not_train", True),
            extras={k: v for k, v in d.items() if k not in known},
        )


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

CONVERSATION_JSON_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "peira conversational case",
    "type": "object",
    "required": [
        "case_id", "family", "primitive", "severity",
        "benign", "attacked",
    ],
    "properties": {
        "case_id": {"type": "string"},
        "family": {"type": "string"},
        "primitive": {"type": "string", "enum": sorted(PRIMITIVES)},
        "severity": {"type": "string", "enum": sorted(SEVERITIES)},
        "benign": {"$ref": "#/$defs/benignArm"},
        "attacked": {"$ref": "#/$defs/attackedArm"},
        "notes": {"type": "string"},
        "evaluation_only": {"type": "boolean"},
        "do_not_train": {"type": "boolean"},
    },
    "$defs": {
        "turn": {
            "type": "object",
            "required": ["role", "content"],
            "properties": {
                "role": {"type": "string",
                         "enum": sorted(CONVERSATION_ROLES)},
                "content": {"type": "string", "minLength": 1},
                "attack": {"type": "boolean"},
                "attack_note": {"type": "string"},
            },
        },
        "armBase": {
            "type": "object",
            "required": ["turns", "options"],
            "properties": {
                "turns": {"type": "array", "items": {"$ref": "#/$defs/turn"}},
                "options": {"type": "array", "items": {"type": "string"},
                            "minItems": 1},
            },
        },
        "benignArm": {
            "allOf": [{"$ref": "#/$defs/armBase"}],
            "required": ["expected_decision"],
            "properties": {
                "expected_decision": {"type": "string"},
                "expected_score": {"type": "number",
                                   "minimum": 0.0, "maximum": 1.0},
                "positive_decision": {"type": "string"},
            },
        },
        "attackedArm": {
            "allOf": [{"$ref": "#/$defs/armBase"}],
            "properties": {
                "target_decision": {"type": ["string", "null"]},
            },
        },
    },
}


def _validate_options_shape(options: Any) -> list[str] | None:
    """Return the options list when it passes the shape check."""
    if (
        isinstance(options, list)
        and options
        and all(isinstance(o, str) and o for o in options)
        and len(set(options)) == len(options)
    ):
        return options
    return None


def _validate_arm_dict(
    arm: Any, name: str, errors: list[str], gold_key: str
) -> list[str] | None:
    """Validate one arm's shape; return shape-valid options or None."""
    if not isinstance(arm, dict):
        errors.append(f"bad {name}: expected object")
        return None
    turns = arm.get("turns")
    if not isinstance(turns, list) or not turns:
        errors.append(f"bad {name}.turns: expected non-empty array")
        turns_ok = False
    else:
        turns_ok = True
        for i, t in enumerate(turns):
            where = f"{name}.turns[{i}]"
            if not isinstance(t, dict):
                errors.append(f"bad {where}: expected object")
                continue
            unknown = set(t) - _TURN_KEYS
            if unknown:
                errors.append(
                    f"bad {where}: unknown keys {sorted(unknown)} "
                    f"(turns have a fixed contract)"
                )
            role = t.get("role")
            if role not in CONVERSATION_ROLES:
                errors.append(f"bad {where}.role: {role!r}")
            content = t.get("content")
            if not isinstance(content, str) or not content:
                errors.append(f"bad {where}.content: expected non-empty string")
            attack = t.get("attack", False)
            if not isinstance(attack, bool):
                errors.append(f"bad {where}.attack: expected boolean")
            note = t.get("attack_note", "")
            if not isinstance(note, str):
                errors.append(f"bad {where}.attack_note: expected string")
            if attack and not note:
                errors.append(
                    f"bad {where}: attack turns require attack_note"
                )
    if turns_ok:
        roles = [t.get("role") for t in turns if isinstance(t, dict)]
        if roles and roles[0] != "user":
            errors.append(f"bad {name}.turns: first turn must be user")
        if roles and roles[-1] != "user":
            errors.append(f"bad {name}.turns: last turn must be user")
        if any(
            a == b == "assistant"
            for a, b in zip(roles, roles[1:])
        ):
            errors.append(
                f"bad {name}.turns: consecutive assistant turns "
                f"(assistant turns are fixed history between user turns)"
            )
        n_user = sum(1 for r in roles if r == "user")
        if n_user < 2:
            errors.append(
                f"bad {name}.turns: need at least 2 user turns "
                f"(got {n_user}): a single user turn is single-shot, "
                f"not a conversation"
            )
        if n_user > MAX_TURNS_PER_ARM:
            errors.append(
                f"bad {name}.turns: {n_user} user turns exceeds "
                f"MAX_TURNS_PER_ARM={MAX_TURNS_PER_ARM}"
            )
    options = _validate_options_shape(arm.get("options"))
    if options is None:
        errors.append(
            f"bad {name}.options: expected non-empty array of unique "
            f"non-empty strings"
        )
    gold = arm.get(gold_key)
    if gold_key == "expected_decision":
        if not isinstance(gold, str) or not gold:
            errors.append(
                f"bad {name}.expected_decision: expected non-empty string"
            )
        elif options is not None and gold not in options:
            errors.append(
                f"bad {name}.expected_decision: {gold!r} not in options"
            )
    else:
        if gold is not None and not isinstance(gold, str):
            errors.append(
                f"bad {name}.target_decision: expected string or null"
            )
        elif (
            isinstance(gold, str) and options is not None
            and gold not in options
        ):
            errors.append(
                f"bad {name}.target_decision: {gold!r} not in options"
            )
    return options


def validate_conversation_dict(d: dict[str, Any]) -> list[str]:
    """Validate a raw conversational case dict; return error strings.

    Pure-Python reference: presence, enum membership, JSON types, turn
    structure, and gold coherence. A schema-valid case can never crash
    the runner downstream.
    """
    errors: list[str] = []
    if not isinstance(d, dict):
        for key in CONVERSATION_JSON_SCHEMA["required"]:
            errors.append(f"missing required key: {key}")
        return errors
    for key in CONVERSATION_JSON_SCHEMA["required"]:
        if key not in d:
            errors.append(f"missing required key: {key}")
    if errors:
        return errors
    if not isinstance(d["case_id"], str) or not d["case_id"]:
        errors.append("bad case_id: expected non-empty string")
    if not isinstance(d["family"], str) or not d["family"]:
        errors.append("bad family: expected non-empty string")
    if not isinstance(d["primitive"], str):
        errors.append("bad primitive: expected string")
    elif d["primitive"] not in PRIMITIVES:
        errors.append(f"bad primitive: {d['primitive']!r}")
    if not isinstance(d["severity"], str):
        errors.append("bad severity: expected string")
    elif d["severity"] not in SEVERITIES:
        errors.append(f"bad severity: {d['severity']!r}")
    benign_options = _validate_arm_dict(
        d.get("benign"), "benign", errors, "expected_decision"
    )
    attacked_options = _validate_arm_dict(
        d.get("attacked"), "attacked", errors, "target_decision"
    )
    # Score-reference coherence (mirrors the single-shot rule): the
    # author reference only exists on score-primitive cases, and the
    # positive-class label is required exactly when the reference is
    # present.
    b = d.get("benign")
    if isinstance(b, dict):
        expected_score = b.get("expected_score")
        positive = b.get("positive_decision")
        if expected_score is not None:
            if d.get("primitive") != "score":
                errors.append(
                    "bad benign.expected_score: only score-primitive "
                    "cases carry a reference score"
                )
            elif not isinstance(expected_score, (int, float)) or isinstance(
                expected_score, bool
            ):
                errors.append(
                    "bad benign.expected_score: expected number"
                )
            elif not 0.0 <= expected_score <= 1.0:
                errors.append(
                    "bad benign.expected_score: expected 0..1, "
                    f"got {expected_score!r}"
                )
            if not isinstance(positive, str) or not positive:
                errors.append(
                    "bad benign.positive_decision: required when "
                    "expected_score is present"
                )
            elif benign_options is not None and positive not in benign_options:
                errors.append(
                    "bad benign.positive_decision: "
                    f"{positive!r} not in options"
                )
        elif positive is not None:
            errors.append(
                "bad benign.positive_decision: only meaningful with "
                "expected_score"
            )
    for flag in ("evaluation_only", "do_not_train"):
        if flag in d and not isinstance(d[flag], bool):
            errors.append(f"bad {flag}: expected boolean")
    if "notes" in d and not isinstance(d["notes"], str):
        errors.append("bad notes: expected string")
    # The benign trajectory must not carry attack annotations: a benign
    # conversation with marked attack turns is a contradiction.
    bb = d.get("benign")
    if isinstance(bb, dict) and isinstance(bb.get("turns"), list):
        for i, t in enumerate(bb["turns"]):
            if isinstance(t, dict) and t.get("attack") is True:
                errors.append(
                    f"bad benign.turns[{i}]: attack marks are not "
                    f"allowed in the benign arm"
                )
    return errors


def load_conversation_cases(suite_dir: Path) -> list["ConversationalCase"]:
    """Load and validate every ``*.jsonl`` conversational case file.

    Mirrors :func:`peira.runner.load_cases`: fail fast with file:line
    on the first invalid line, and reject duplicate case ids.
    """
    cases: list[ConversationalCase] = []
    seen: set[str] = set()
    for path in sorted(Path(suite_dir).glob("*.jsonl")):
        # Explicit UTF-8: the platform default would silently mojibake
        # non-ASCII case content.
        with open(path, encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                errors = validate_conversation_dict(d)
                if errors:
                    raise ValueError(
                        f"{path}:{lineno}: {'; '.join(errors)}"
                    )
                case = ConversationalCase.from_dict(d)
                if case.case_id in seen:
                    raise ValueError(
                        f"{path}:{lineno}: duplicate case_id "
                        f"{case.case_id!r}"
                    )
                seen.add(case.case_id)
                cases.append(case)
    return cases
