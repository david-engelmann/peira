"""Minimal peira adapter in ~30 lines.

An adapter wraps any decision model and exposes it through the typed
primitive protocol. This one always approves with high confidence —
a deliberately naive baseline. Run it with:

    peira run --adapter examples.minimal_adapter --suite trial-demo
"""

from peira.adapters.base import ChoiceOutput


class MinimalAdapter:
    name = "minimal"
    supported_primitives = frozenset({"choice"})

    def decide(self, case_input, primitive):
        assert primitive == "choice", f"minimal supports choice only, got {primitive}"
        return ChoiceOutput(decision="approve", confidence=0.95)


# The CLI resolves `--adapter` names to classes; keep this alias stable.
adapter = MinimalAdapter()
