"""Custom threshold walkthrough for the Score primitive.

A Score adapter returns a score in 0..1 and derives its own decision from
its own threshold (tau). This example shows how the threshold changes the
measured ASR — the point being that peira measures *your* deployed
behavior, threshold included.
"""

from peira.adapters.base import ScoreOutput


class ThresholdAdapter:
    name = "threshold-demo"
    supported_primitives = frozenset({"score"})

    def __init__(self, tau: float = 0.5):
        self.tau = tau

    def _score(self, case_input) -> float:
        # Toy scorer: real adapters call a model here.
        prompt = case_input.get("prompt", "")
        return 0.8 if "urgent" in prompt.lower() else 0.3

    def decide(self, case_input, primitive):
        assert primitive == "score"
        s = self._score(case_input)
        return ScoreOutput(score=s, decision="approve" if s >= self.tau else "deny")


# Try tau=0.5 vs tau=0.9 and compare the two run artifacts:
#   peira run --adapter examples.custom_threshold:ThresholdAdapter ...
# (adapter registry wiring for dotted paths lands with the plugin system;
# for now, subclass and set `adapter = ThresholdAdapter(tau=0.9)`.)
adapter = ThresholdAdapter(tau=0.5)
