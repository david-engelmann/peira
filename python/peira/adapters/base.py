"""Adapter protocol: how a decision model plugs into peira.

An adapter wraps any decision-making system (a guardrail model, an LLM with
structured output, a rules engine) and exposes it through one typed method
per primitive. Adapters declare which primitives they support; partial
coverage is fine and is reported honestly on the leaderboard.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class CaseContext:
    """Everything an adapter is allowed to see for one decide() call.

    Deliberately EXCLUDES gold labels (expected_decision, expected_score,
    target_decision). The type system — not a code comment — now enforces
    the no-gold-leak invariant (audit C1): there is simply no field to leak
    from.

    ``input`` is the variant input (prompt, options, ...). ``attacked`` and
    ``variant`` are redundant by design: the explicit ``variant`` string
    replaces the old ``"attacked": True`` dict-mutation convention, and
    ``__post_init__`` enforces they agree.
    """

    case_id: str
    primitive: str  # "choice" | "score" | "abstain"
    input: dict[str, Any]  # the variant input (prompt, options, ...)
    attacked: bool  # True for the attacked variant
    variant: str  # "benign" | "attacked"

    def __post_init__(self) -> None:
        if self.primitive not in ("choice", "score", "abstain"):
            raise ValueError(f"unknown primitive: {self.primitive!r}")
        if self.variant not in ("benign", "attacked"):
            raise ValueError(f"unknown variant: {self.variant!r}")
        if self.attacked != (self.variant == "attacked"):
            raise ValueError("attacked flag disagrees with variant")

    def to_wire(self) -> dict[str, Any]:
        """Serialize to the language-neutral subprocess wire format.

        Byte-compatible with the pre-v2 runner: ``{"case": {...},
        "primitive": ...}`` where ``"case"`` is the input dict plus
        ``case_id`` and (for attacked variants) the ``attacked`` flag.
        The Rust side (``crates/peira-core/src/adapter_protocol.rs``) is
        untouched — v2 is a Python-SDK typing change; the wire protocol
        does not move.
        """
        case = dict(self.input)
        case["case_id"] = self.case_id
        if self.attacked:
            case["attacked"] = True
        return {"case": case, "primitive": self.primitive}


@dataclass(frozen=True)
class ChoiceOutput:
    decision: str
    confidence: float  # 0..1


@dataclass(frozen=True)
class ScoreOutput:
    score: float  # 0..1, higher = more toward the positive class
    decision: str  # derived by the adapter's own threshold


@dataclass(frozen=True)
class AbstainOutput:
    decision: str
    abstained: bool


AdapterOutput = ChoiceOutput | ScoreOutput | AbstainOutput


def validate_output(output: AdapterOutput, primitive: str) -> list[str]:
    """Check an adapter output against its primitive contract.
    
    Returns a list of error strings; empty means valid. Enforces type
    matching, 0..1 ranges (booleans are rejected — ``True`` is not a valid
    confidence, even though ``0.0 <= True <= 1.0`` in Python), NaN/inf
    rejection via the range check, and a 10 KiB cap on decision strings
    (DoS guard).
    
    SECURITY (audit M-2): Enforces size limits to prevent memory/disk DoS
    via oversized adapter outputs. A malicious adapter returning a 50MB
    decision string would otherwise create a 250GB artifact.
    """
    errors: list[str] = []
    # Maximum decision string length: 10KB (generous for legitimate use,
    # blocks the 50MB PoC from the security audit).
    MAX_DECISION_LEN = 10 * 1024
    
    def check_decision_len(decision: str, output_type: str) -> None:
        if len(decision) > MAX_DECISION_LEN:
            errors.append(
                f"{output_type} decision string too long: {len(decision)} chars "
                f"(max {MAX_DECISION_LEN})"
            )
    
    if primitive == "choice":
        if not isinstance(output, ChoiceOutput):
            errors.append(f"choice primitive needs ChoiceOutput, got {type(output).__name__}")
        else:
            if isinstance(output.confidence, bool):
                errors.append(
                    f"confidence {output.confidence!r} is a bool, not a number in 0..1"
                )
            elif not 0.0 <= output.confidence <= 1.0:
                errors.append(f"confidence {output.confidence} outside 0..1")
            check_decision_len(output.decision, "choice")
    elif primitive == "score":
        if not isinstance(output, ScoreOutput):
            errors.append(f"score primitive needs ScoreOutput, got {type(output).__name__}")
        else:
            if isinstance(output.score, bool):
                errors.append(
                    f"score {output.score!r} is a bool, not a number in 0..1"
                )
            elif not 0.0 <= output.score <= 1.0:
                errors.append(f"score {output.score} outside 0..1")
            check_decision_len(output.decision, "score")
    elif primitive == "abstain":
        if not isinstance(output, AbstainOutput):
            errors.append(f"abstain primitive needs AbstainOutput, got {type(output).__name__}")
        else:
            check_decision_len(output.decision, "abstain")
    else:
        errors.append(f"unknown primitive: {primitive!r}")
    return errors


class BaseAdapter(Protocol):
    """Protocol every adapter implements."""

    name: str
    version: str  # exact pinned model version — never an alias like "latest"
    supported_primitives: frozenset[str]

    def decide(self, ctx: CaseContext) -> AdapterOutput:
        """Run the decision model on one variant of one case.

        The context carries everything the adapter may see: case id,
        primitive, variant input, and which variant this is. Gold labels
        are structurally absent — there is no field to leak.
        """
        ...
