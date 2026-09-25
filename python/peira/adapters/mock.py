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
    """A deterministic fake decision model.
    
    IMPORTANT: This adapter does NOT receive gold labels via case_input.
    For testing, pass expected decisions at construction time via gold_map.
    The runner never provides golds in the adapter input (audit C1).
    """

    name = "mock"
    version = "0.1.0"
    supported_primitives = frozenset({"choice", "score", "noul"})

    def __init__(
        self,
        flip_rate: float = 0.4,
        seed: str = "peira-mock-v1",
        gold_map: dict[str, str] | None = None,
    ) -> None:
        self.flip_rate = flip_rate
        self.seed = seed
        # gold_map: case_id -> expected_decision, for testing only.
        # In production, adapters must NOT have access to golds.
        self.gold_map = gold_map or {}

    def _flips(self, case_id: str) -> bool:
        digest = hashlib.sha256(f"{self.seed}:{case_id}".encode()).hexdigest()
        return (int(digest, 16) % 1000) / 1000 < self.flip_rate

    def decide(self, case_input: dict[str, Any], primitive: str) -> AdapterOutput:
        case_id = str(case_input.get("case_id", ""))
        attacked = bool(case_input.get("attacked", False))

        # For benign: use gold_map if provided (testing), else default.
        # The runner does NOT pass expected_decision in case_input (audit C1).
        expected = self.gold_map.get(case_id, "approve")
        
        flipped = attacked and self._flips(case_id)
        # Flip by choosing a different decision (simplified: toggle approve/deny)
        if flipped:
            decision = "deny" if expected == "approve" else "approve"
        else:
            decision = expected

        if primitive == "choice":
            return ChoiceOutput(decision=decision, confidence=0.9 if not flipped else 0.55)
        if primitive == "score":
            score = 0.85 if decision == "approve" else 0.15
            return ScoreOutput(score=score, decision=decision)
        if primitive == "noul":
            return NoulOutput(decision=decision, abstained=False)
        raise ValueError(f"mock does not support primitive {primitive!r}")
