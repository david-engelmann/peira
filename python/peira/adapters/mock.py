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
    CaseContext,
    ChoiceOutput,
    AbstainOutput,
    ScoreOutput,
)


class MockAdapter:
    """A deterministic fake decision model.

    IMPORTANT: This adapter does NOT receive gold labels. The runner passes
    a CaseContext, which structurally excludes expected_decision /
    expected_score (audit C1). For testing, pass expected decisions at
    construction time via gold_map. In production, adapters must NOT have
    access to golds.
    """

    name = "mock"
    version = "0.1.0"
    supported_primitives = frozenset({"choice", "score", "abstain"})

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

    def decide(self, ctx: CaseContext) -> AdapterOutput:
        case_id = ctx.case_id
        attacked = ctx.attacked
        primitive = ctx.primitive

        # For benign: use gold_map if provided (testing), else default.
        # The runner does NOT pass expected_decision in the CaseContext (audit C1).
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
        if primitive == "abstain":
            return AbstainOutput(decision=decision, abstained=False)
        raise ValueError(f"mock does not support primitive {primitive!r}")
