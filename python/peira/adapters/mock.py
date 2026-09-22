"""Mock adapter: deterministic, offline, zero-dependency.

Used for the 30-second quickstart and CI. It answers the benign variant
correctly and flips on a fixed, seeded subset of attacked variants, so runs
are reproducible bit-for-bit.
"""

from __future__ import annotations

import hashlib
from typing import Any

from peira.adapters.base import (
    AdapterOutput,
    ChoiceOutput,
    NoulOutput,
    ScoreOutput,
)


class MockAdapter:
    """A deterministic fake decision model."""

    name = "mock"
    version = "0.1.0"
    supported_primitives = frozenset({"choice", "score", "noul"})

    def __init__(self, flip_rate: float = 0.4, seed: str = "peira-mock-v1") -> None:
        self.flip_rate = flip_rate
        self.seed = seed

    def _flips(self, case_id: str) -> bool:
        digest = hashlib.sha256(f"{self.seed}:{case_id}".encode()).hexdigest()
        return (int(digest, 16) % 1000) / 1000 < self.flip_rate

    def decide(self, case_input: dict[str, Any], primitive: str) -> AdapterOutput:
        case_id = str(case_input.get("case_id", ""))
        expected = str(case_input.get("expected_decision", "approve"))
        attacked = bool(case_input.get("attacked", False))

        flipped = attacked and self._flips(case_id)
        decision = ("deny" if expected == "approve" else "approve") if flipped else expected

        if primitive == "choice":
            return ChoiceOutput(decision=decision, confidence=0.9 if not flipped else 0.55)
        if primitive == "score":
            score = 0.85 if decision == "approve" else 0.15
            return ScoreOutput(score=score, decision=decision)
        if primitive == "noul":
            return NoulOutput(decision=decision, abstained=False)
        raise ValueError(f"mock does not support primitive {primitive!r}")
