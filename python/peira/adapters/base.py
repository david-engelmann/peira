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
class ChoiceOutput:
    decision: str
    confidence: float  # 0..1


@dataclass(frozen=True)
class ScoreOutput:
    score: float  # 0..1, higher = more toward the positive class
    decision: str  # derived by the adapter's own threshold


@dataclass(frozen=True)
class NoulOutput:
    decision: str
    abstained: bool


AdapterOutput = ChoiceOutput | ScoreOutput | NoulOutput


def validate_output(output: AdapterOutput, primitive: str) -> list[str]:
    """Check an adapter output against its primitive contract."""
    errors: list[str] = []
    if primitive == "choice":
        if not isinstance(output, ChoiceOutput):
            errors.append(f"choice primitive needs ChoiceOutput, got {type(output).__name__}")
        elif not 0.0 <= output.confidence <= 1.0:
            errors.append(f"confidence {output.confidence} outside 0..1")
    elif primitive == "score":
        if not isinstance(output, ScoreOutput):
            errors.append(f"score primitive needs ScoreOutput, got {type(output).__name__}")
        elif not 0.0 <= output.score <= 1.0:
            errors.append(f"score {output.score} outside 0..1")
    elif primitive == "noul":
        if not isinstance(output, NoulOutput):
            errors.append(f"noul primitive needs NoulOutput, got {type(output).__name__}")
    else:
        errors.append(f"unknown primitive: {primitive!r}")
    return errors


class BaseAdapter(Protocol):
    """Protocol every adapter implements."""

    name: str
    supported_primitives: frozenset[str]

    def decide(self, case_input: dict[str, Any], primitive: str) -> AdapterOutput:
        """Run the decision model on one variant input."""
        ...
