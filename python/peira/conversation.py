"""Conversational evaluation suite: schema, gates, and runner (R-01).

The conversational suite is a SEPARATE suite, not turn sequences inside
v2: it has its own schema, runner, metrics, flip definitions, and
blind-holdout machinery, while sharing the single-shot suite's call
machinery (timeouts, retries, response cache, transcript sink, pricing,
budgets, pseudonymous call contexts), validation gates, artifacts, and
report tooling where valid. Conversational results are never blended
with the paired single-decision v1/v2 numbers.

A conversational case is a paired benign/attacked pair of multi-turn
trajectories. Each trajectory is an ordered list of turns. ``user``
turns are executed through the adapter in order; ``assistant`` turns
are fixed, authored history spliced into the conversation without an
adapter call. Only the FINAL user turn's decision is scored, with the
exact single-shot pair semantics (eligibility, flip, abstention and
malformed handling): a :class:`ConversationResult` is the scored
final-turn pair plus its turn history, so every metric, artifact, and
report path works unchanged.

Blind execution: the adapter sees only the conversation content, the
decision options, the turn index, and a final-turn flag, plus an opaque
per-turn call id. No case id, no family, no arm, no gold labels, no
attack annotations, and no holdout status ever cross the adapter
boundary. Turn payloads are built by :func:`_turn_payload`, and the
no-gold-leakage property is pinned by unit tests.

Adapter capability contract: adapters implement
``decide_turn(messages, primitive, context)`` where ``messages`` is the
full history (a list of ``{"role": ..., "content": ...}`` dicts) ending
with the current user turn. Adapters that only implement the
single-shot ``decide()`` still run: the runner flattens the history
into one prompt (see :func:`_flatten_turn_input`). Every executed turn
must return a primitive-valid output; intermediate turns are recorded
but unscored.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from peira.adapters.base import CallContext
from peira.metrics import CallRecord, PerCaseResult
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


# ---------------------------------------------------------------------------
# Adapter interop: the decide_turn contract
# ---------------------------------------------------------------------------


def _turn_payload(
    messages: list[dict[str, str]],
    options: list[str],
    turn_index: int,
    is_final_turn: bool,
) -> dict[str, Any]:
    """Build the adapter-visible payload for one executed turn.

    This is the blindness boundary: the payload carries the
    conversation content, the decision options, the turn index, and a
    final-turn flag. No case id, no family, no arm, no gold labels, no
    attack annotations, no holdout status. Anything not listed here
    does not cross.
    """
    return {
        "messages": [dict(m) for m in messages],
        "options": list(options),
        "turn_index": turn_index,
        "is_final_turn": is_final_turn,
    }


def _flatten_turn_input(turn_input: dict[str, Any]) -> dict[str, Any]:
    """Render a turn payload as a single-shot case input.

    Fallback for adapters that only implement ``decide()``: the full
    history becomes one prompt, labeled by role, with the same options
    list the single-shot protocol expects.
    """
    lines = []
    for m in turn_input["messages"]:
        lines.append(f"{m['role'].upper()}: {m['content']}")
    return {
        "prompt": "\n".join(lines),
        "options": list(turn_input["options"]),
    }


def _invoke_adapter_turn(
    adapter: Any,
    turn_input: dict[str, Any],
    primitive: str,
    context: CallContext,
) -> tuple[Any, dict[str, Any] | None]:
    """Run one conversation turn through the adapter.

    Adapters implementing ``decide_turn(messages, primitive, context)``
    receive the full message history ending with the current user turn.
    Adapters without it fall back to a flattened single-shot
    ``decide()`` call. Provider-native payloads ride the output's
    ``transcript`` field, same as the single-shot path.
    """
    decide_turn = getattr(adapter, "decide_turn", None)
    if decide_turn is not None:
        output = decide_turn(turn_input["messages"], primitive, context)
    else:
        output = adapter.decide(
            _flatten_turn_input(turn_input), primitive, context
        )
    raw = getattr(output, "transcript", None)
    if raw is not None and not isinstance(raw, dict):
        raw = None
    return output, raw


def _record_to_history_text(record: CallRecord, primitive: str) -> str:
    """Render a sealed turn record as the next assistant message.

    Derived from the sealed record, never from adapter internals: the
    text is what the conversation history carries forward.
    """
    if record.malformed:
        return "<malformed output>"
    if record.abstained:
        reason = record.refusal_reason or "no reason given"
        return f"<abstained: {reason}>"
    if primitive == "score" and record.score is not None:
        return f"{record.decision} (score {record.score:.3f})"
    return record.decision


# ---------------------------------------------------------------------------
# Results: the scored final-turn pair plus its turn history
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConversationResult(PerCaseResult):
    """A scored conversational case.

    The base-class fields (``benign``/``attacked`` call records,
    ``flipped``, ``eligible``, ``ineligibility_reason``) describe the
    FINAL-turn pair, scored with the exact single-shot pair semantics.
    ``benign_turns``/``attacked_turns`` carry every executed turn's
    record (final turn included) for drill-down. :meth:`to_dict`
    serializes the artifact entry shape (strict base fields plus the
    turn lists under the suite-namespaced ``conversational_turns``
    field), and every metric/sort/artifact path that reads the base
    fields works unchanged.
    """

    benign_turns: list[CallRecord] = field(default_factory=list)
    attacked_turns: list[CallRecord] = field(default_factory=list)

    @classmethod
    def from_scored(
        cls,
        scored: PerCaseResult,
        benign_turns: list[CallRecord],
        attacked_turns: list[CallRecord],
    ) -> "ConversationResult":
        return cls(
            case_id=scored.case_id,
            family=scored.family,
            severity=scored.severity,
            primitive=scored.primitive,
            benign=scored.benign,
            attacked=scored.attacked,
            flipped=scored.flipped,
            eligible=scored.eligible,
            ineligibility_reason=scored.ineligibility_reason,
            benign_turns=list(benign_turns),
            attacked_turns=list(attacked_turns),
        )

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ConversationResult":
        base = PerCaseResult.from_dict(d)
        # Artifact entries nest the turn records under the
        # suite-namespaced ``conversational_turns`` field; accept the
        # flat in-memory shape too (dataclasses.asdict of a live
        # result).
        turns = d.get("conversational_turns") or {}
        benign_turn_dicts = turns.get(
            "benign_turns", d.get("benign_turns", [])
        )
        attacked_turn_dicts = turns.get(
            "attacked_turns", d.get("attacked_turns", [])
        )
        return cls.from_scored(
            base,
            [CallRecord.from_dict(r) for r in benign_turn_dicts],
            [CallRecord.from_dict(r) for r in attacked_turn_dicts],
        )

    def to_dict(self) -> dict[str, Any]:
        """Artifact entry shape: strict base fields plus the sealed
        turn records under the suite-namespaced ``conversational_turns``
        field (see RunArtifact._RESULT_OPTIONAL)."""
        d = dataclasses.asdict(self)
        d["conversational_turns"] = {
            "benign_turns": d.pop("benign_turns"),
            "attacked_turns": d.pop("attacked_turns"),
        }
        return d


def _conversation_case_cost_usd(result: PerCaseResult) -> float:
    """Total priced spend for one conversational case: all turn records.

    Accepts the base type so it plugs into the shared budget/spend
    machinery; conversational results always carry the turn lists.
    """
    total = 0.0
    turns: list[CallRecord] = []
    if isinstance(result, ConversationResult):
        turns = result.benign_turns + result.attacked_turns
    else:  # pragma: no cover - defensive; the suite only emits these
        turns = [result.benign, result.attacked]
    for rec in turns:
        if rec.usage is not None:
            total += rec.usage.cost_usd
    return total


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def _scoring_case(case: ConversationalCase):
    """Single-shot shim for scoring the final-turn pair.

    The final-turn pair is scored with the exact single-shot pair
    semantics (eligibility, flip, abstention/malformed handling),
    including the Rust dispatch: only the labels the scorer reads are
    carried over, never the trajectory.
    """
    from peira.schema import AttackedVariant, BenignVariant, Case

    return Case(
        case_id=case.case_id,
        family=case.family,
        primitive=case.primitive,
        severity=case.severity,
        benign=BenignVariant(
            input={},
            expected_decision=case.benign.expected_decision,
            expected_score=case.benign.expected_score,
            positive_decision=case.benign.positive_decision,
        ),
        attacked=AttackedVariant(
            input={},
            target_decision=case.attacked.target_decision,
        ),
        notes="conversational scoring shim: final-turn pair only",
    )


def _conversation_turn_dispatch_index(
    dispatch_base: int, arm: str, turn_index: int
) -> int:
    """Dispatch index for one executed turn.

    ``dispatch_base`` is the case's stride-derived base (see
    :func:`run_conversation_suite`): benign turn t uses base + 2t,
    attacked turn t uses base + 2t + 1. Suite-position-derived, never
    run order, so resumed runs re-derive identical indices.
    """
    arm_offset = 1 if arm == "attacked" else 0
    return dispatch_base + 2 * turn_index + arm_offset


# ---------------------------------------------------------------------------
# Per-case execution
# ---------------------------------------------------------------------------


async def _run_conversation_case_async(
    adapter: Any,
    adapter_version: str,
    case: ConversationalCase,
    seed: int,
    dispatch_base: int,
    pricing_table: dict[str, Any],
    manifest_sha256: str,
    *,
    controller: Any,
    max_attempts: int,
    max_concurrency: int,
    call_timeout: float | None,
    cache: Any | None,
    transcript: Any | None,
    run_nonce: str,
) -> ConversationResult:
    """Drive one conversational case, turn by turn.

    Same signature as :func:`peira.runner._run_case_async`, so it
    plugs into the shared suite driver. Benign arm runs before the
    attacked arm, sequentially; concurrency happens across cases.
    Within an arm, executed (user) turns run in order, each through
    the full call machinery (retries, timeouts, cache, transcript,
    pricing) via the ``invoke`` hook; fixed assistant turns are
    spliced into the history without a call; each model response is
    appended to the history the next turn sees. Only the final turn
    of each arm is scored.
    """
    # Local imports: runner imports nothing from this module, so there
    # is no cycle, and importing this module never requires the
    # runner's asyncio machinery at module scope.
    from peira.concurrency import cache_key
    from peira.runner import (
        _pseudonymous_call_id,
        _record_call_async,
        _score_pair,
        _TrialInfo,
    )

    namespace = str(getattr(adapter, "cache_namespace", "") or "")
    expected = case.benign.expected_decision

    def key_for(
        payload: dict[str, Any], arm: str, turn_index: int
    ) -> str | None:
        if cache is None:
            return None
        return cache_key(
            adapter_name=adapter.name,
            adapter_version=adapter_version,
            cache_namespace=namespace,
            primitive=case.primitive,
            variant=f"{arm}/turn{turn_index}",
            case_id=case.case_id,
            case_input=payload,
            manifest_sha256=manifest_sha256,
        )

    async def run_arm(
        arm_name: str, turns: list[ConversationTurn], options: list[str]
    ) -> list[CallRecord]:
        history: list[dict[str, str]] = []
        records: list[CallRecord] = []
        executed = 0
        user_turns = [t for t in turns if t.role == "user"]
        for turn in turns:
            if turn.role == "assistant":
                # Fixed, authored history: spliced in, never executed.
                history.append(
                    {"role": "assistant", "content": turn.content}
                )
                continue
            is_final = executed == len(user_turns) - 1
            user_message = {"role": "user", "content": turn.content}
            messages = history + [user_message]
            payload = _turn_payload(
                messages, options, executed, is_final
            )
            dispatch_index = _conversation_turn_dispatch_index(
                dispatch_base, arm_name, executed
            )
            context = CallContext(
                call_id=_pseudonymous_call_id(
                    run_nonce, seed, dispatch_index
                )
            )
            trial = _TrialInfo(
                case_id=case.case_id,
                arm=arm_name,  # type: ignore[arg-type]
                expected_decision=expected,
                target_decision=(
                    None
                    if arm_name == "benign"
                    else case.attacked.target_decision
                ),
            )
            record = await _record_call_async(
                adapter,
                adapter_version,
                payload,
                case.primitive,
                context,
                trial,
                seed,
                dispatch_index,
                pricing_table,
                controller=controller,
                max_attempts=max_attempts,
                max_concurrency=max_concurrency,
                call_timeout=call_timeout,
                cache=cache,
                cache_key_str=key_for(payload, arm_name, executed),
                transcript=transcript,
                invoke=_invoke_adapter_turn,
            )
            records.append(record)
            history.append(user_message)
            history.append(
                {
                    "role": "assistant",
                    "content": _record_to_history_text(
                        record, case.primitive
                    ),
                }
            )
            executed += 1
        return records

    benign_records = await run_arm(
        "benign", case.benign.turns, case.benign.options
    )
    attacked_records = await run_arm(
        "attacked", case.attacked.turns, case.attacked.options
    )
    scored = _score_pair(
        _scoring_case(case), benign_records[-1], attacked_records[-1]
    )
    return ConversationResult.from_scored(
        scored, benign_records, attacked_records
    )


def run_conversation_case(
    adapter: Any,
    case: ConversationalCase,
    seed: int = 0,
    dispatch_base: int = 0,
    pricing_table: dict[str, Any] | None = None,
    run_nonce: str | None = None,
) -> ConversationResult:
    """Run one conversational case synchronously (debugging aid).

    Mirrors :func:`peira.runner.run_case`: strictly sequential, no
    concurrency, retries, cache, or transcript. Every turn goes
    through the adapter's turn entry point.
    """
    from peira.pricing import load_pricing_table
    from peira.runner import (
        _pseudonymous_call_id,
        _record_call,
        _score_pair,
        new_run_nonce,
    )

    nonce = run_nonce if run_nonce is not None else new_run_nonce()
    table = pricing_table if pricing_table is not None else load_pricing_table()

    def run_arm(
        arm_name: str, turns: list[ConversationTurn], options: list[str]
    ) -> list[CallRecord]:
        history: list[dict[str, str]] = []
        records: list[CallRecord] = []
        executed = 0
        user_turns = [t for t in turns if t.role == "user"]
        for turn in turns:
            if turn.role == "assistant":
                history.append(
                    {"role": "assistant", "content": turn.content}
                )
                continue
            is_final = executed == len(user_turns) - 1
            user_message = {"role": "user", "content": turn.content}
            messages = history + [user_message]
            payload = _turn_payload(
                messages, options, executed, is_final
            )
            dispatch_index = _conversation_turn_dispatch_index(
                dispatch_base, arm_name, executed
            )
            context = CallContext(
                call_id=_pseudonymous_call_id(
                    nonce, seed, dispatch_index
                )
            )
            record = _record_call(
                adapter,
                payload,
                case.primitive,
                context,
                seed,
                dispatch_index,
                table,
                invoke=_invoke_adapter_turn,
            )
            records.append(record)
            history.append(user_message)
            history.append(
                {
                    "role": "assistant",
                    "content": _record_to_history_text(
                        record, case.primitive
                    ),
                }
            )
            executed += 1
        return records

    benign_records = run_arm("benign", case.benign.turns, case.benign.options)
    attacked_records = run_arm(
        "attacked", case.attacked.turns, case.attacked.options
    )
    scored = _score_pair(
        _scoring_case(case), benign_records[-1], attacked_records[-1]
    )
    return ConversationResult.from_scored(
        scored, benign_records, attacked_records
    )


# ---------------------------------------------------------------------------
# Suite driver
# ---------------------------------------------------------------------------


def run_conversation_suite(
    adapter: Any,
    cases: list[ConversationalCase],
    suite: str = CONVERSATION_SUITE_ID,
    dataset_version: str = "0.1.0-conversational",
    progress: Callable[[int, int], None] | None = None,
    already_done: set[str] | None = None,
    prior_results: list[ConversationResult] | None = None,
    partial_path: Path | None = None,
    checkpoint_every: int = 25,
    required_families: list[str] | None = None,
    manifest_sha256: str = "",
    seed: int = 0,
    max_concurrency: int = 8,
    max_attempts: int = 3,
    call_timeout: float | None = 300.0,
    cache_dir: Path | str | None = None,
    transcript_path: Path | str | None = None,
    config_extra: dict[str, Any] | None = None,
    rlimit_cpu_seconds: float | None = None,
    rlimit_as_mb: float | None = None,
    rlimit_fsize_mb: float | None = None,
    run_nonce: str | None = None,
    budget_usd: float | None = None,
):
    """Run a conversational suite through an adapter, concurrently.

    The shared suite driver (:func:`peira.runner.run_suite`) with the
    conversational suite-shape hooks: a wider dispatch stride (each
    case drives up to ``2 * MAX_TURNS_PER_ARM`` calls), the turn-driving
    per-case coroutine, and turn-aware spend for the budget gate and
    totals. Everything else — concurrency, retries, timeouts, cache,
    transcripts, checkpoints, resume, environment fingerprinting, the
    sealed artifact — is the shared machinery, unchanged.

    The artifact's ``suite`` is ``"conversational"`` (or the override
    passed here): conversational results are namespaced away from the
    v1/v2 numbers by construction.
    """
    from peira.runner import run_suite

    return run_suite(
        adapter,
        cases,  # type: ignore[arg-type]
        suite,
        dataset_version,
        progress=progress,
        already_done=already_done,
        prior_results=prior_results,  # type: ignore[arg-type]
        partial_path=partial_path,
        checkpoint_every=checkpoint_every,
        required_families=required_families,
        manifest_sha256=manifest_sha256,
        seed=seed,
        max_concurrency=max_concurrency,
        max_attempts=max_attempts,
        call_timeout=call_timeout,
        cache_dir=cache_dir,
        transcript_path=transcript_path,
        config_extra=config_extra,
        rlimit_cpu_seconds=rlimit_cpu_seconds,
        rlimit_as_mb=rlimit_as_mb,
        rlimit_fsize_mb=rlimit_fsize_mb,
        run_nonce=run_nonce,
        budget_usd=budget_usd,
        dispatch_stride=CONVERSATION_DISPATCH_STRIDE,
        run_one_case=_run_conversation_case_async,
        case_cost=_conversation_case_cost_usd,
        result_to_dict=lambda r: r.to_dict(),
    )


def validate_conversation_partial(
    partial: Any,
    adapter: Any,
    cases: list[ConversationalCase],
    suite: str = CONVERSATION_SUITE_ID,
    dataset_version: str = "0.1.0-conversational",
    manifest_sha256: str = "",
    seed: int = 0,
    budget_usd: float | None = None,
    cache_enabled: bool = False,
) -> tuple[set[str], list[ConversationResult]]:
    """Strictly validate a conversational partial run for --resume.

    Same contract as :func:`peira.runner.validate_partial`, but
    result entries rebuild as :class:`ConversationResult` so the turn
    history survives the resume round-trip.
    """
    from peira.runner import validate_partial

    return validate_partial(  # type: ignore[return-value]
        partial,
        adapter,
        cases,  # type: ignore[arg-type]
        suite,
        dataset_version,
        manifest_sha256=manifest_sha256,
        seed=seed,
        budget_usd=budget_usd,
        cache_enabled=cache_enabled,
        result_from_dict=ConversationResult.from_dict,
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
