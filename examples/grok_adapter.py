"""Grok 4.7 adapter for peira — xAI's flagship via OpenRouter.

Uses OpenRouter chat completions with structured outputs (JSON schema).
Model id ``x-ai/grok-4.7`` (500k context, released 2026-09-21).

Run it with:

    export OPENROUTER_API_KEY="sk-or-..."
    peira run --adapter examples.grok_adapter:GrokAdapter --suite trial-demo

Primitive mapping (structured outputs, temperature 0.0):
- peira Choice -> {"decision": "<one of options>", "confidence": 0..1}
- peira Score  -> {"score": 0..1, "decision": "<one of options>"}
- peira Noul   -> {"decision": "<one of options>", "abstained": bool}

Cost (Sept 2026): ~$2/$6 per 1M input/output via xAI-direct pricing;
OpenRouter routing may vary. This is NOT a flash-tier model — use it for
the flagship comparison seat, not for bulk runs.

Stdlib only (urllib) — no third-party dependencies.
"""

from __future__ import annotations

from peira.adapters.base import ChoiceOutput, NoulOutput, ScoreOutput

from examples._openrouter_base import OpenRouterAdapter, OpenRouterError, _clamp01


class GrokAdapter(OpenRouterAdapter):
    """peira adapter backed by xAI Grok 4.7."""

    name = "grok-4.7"
    version = "x-ai/grok-4.7"  # pinned slug — never "latest"
    model = "x-ai/grok-4.7"
    supported_primitives = frozenset({"choice", "score", "noul"})

    def decide(self, case_input, primitive):
        prompt = case_input.get("prompt", "")
        options = list(case_input.get("options", []))
        if len(options) < 2:
            raise OpenRouterError(
                f"{primitive} needs >= 2 options, got {options!r}")
        if primitive == "choice":
            return self._decide_choice(prompt, options)
        if primitive == "score":
            return self._decide_score(prompt, options)
        if primitive == "noul":
            return self._decide_noul(prompt, options)
        raise ValueError(f"unsupported primitive: {primitive!r}")

    def _decide_choice(self, prompt, options):
        out = self._chat(
            [{"role": "user", "content": (
                f"{prompt}\n\nWhich option is the correct decision? "
                f"Options: {options}. Respond with your decision "
                f"(exactly one of the options) and your confidence 0..1."
            )}],
            schema=self.CHOICE_SCHEMA,
            schema_name="peira_choice",
        )
        decision = str(out["decision"])
        if decision not in options:
            raise OpenRouterError(
                f"model returned unknown choice {decision!r}")
        return ChoiceOutput(decision=decision,
                            confidence=_clamp01(float(out["confidence"])))

    def _decide_score(self, prompt, options):
        out = self._chat(
            [{"role": "user", "content": (
                f"{prompt}\n\nOn a scale of 0.0 to 1.0, how strongly does "
                f"this case warrant '{options[0]}' (vs '{options[1]}')? "
                f"Respond with the score and the decision it implies "
                f"(exactly one of {options})."
            )}],
            schema=self.SCORE_SCHEMA,
            schema_name="peira_score",
        )
        score = _clamp01(float(out["score"]))
        # The score is authoritative; the adapter's threshold derives the
        # decision. If the model's decision string contradicts the score,
        # the score wins (prevents silent threshold drift).
        decision = options[0] if score >= self.threshold else options[1]
        return ScoreOutput(score=score, decision=decision)

    def _decide_noul(self, prompt, options):
        out = self._chat(
            [{"role": "user", "content": (
                f"{prompt}\n\nWhat is the correct decision? "
                f"Options: {options}. If you are genuinely torn "
                f"(no option is clearly better), set abstained to true. "
                f"Respond with your decision (exactly one of the options) "
                f"and whether you abstained."
            )}],
            schema=self.NOUL_SCHEMA,
            schema_name="peira_noul",
        )
        decision = str(out["decision"])
        if decision not in options:
            raise OpenRouterError(
                f"model returned unknown decision {decision!r}")
        return NoulOutput(decision=decision, abstained=bool(out["abstained"]))


# The CLI resolves `--adapter` names to classes; keep this alias stable.
adapter = None  # constructed per-run; needs OPENROUTER_API_KEY (see docstring)
