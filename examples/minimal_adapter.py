"""Minimal peira adapter in ~30 lines.

An adapter wraps any decision model and exposes it through the typed
primitive protocol. This one always approves with high confidence —
a deliberately naive baseline. Run it with:

    peira run --adapter examples.minimal_adapter --suite trial-demo
"""

from peira.adapters.base import CaseContext, ChoiceOutput


class MinimalAdapter:
    name = "minimal"
    version = "1.0.0-pinned"  # exact — never an alias
    supported_primitives = frozenset({"choice"})

    def decide(self, ctx: CaseContext):
        assert ctx.primitive == "choice", f"minimal supports choice only, got {ctx.primitive}"
        return ChoiceOutput(decision="approve", confidence=0.95)


# The CLI resolves `--adapter` names to classes; keep this alias stable.
adapter = MinimalAdapter()
