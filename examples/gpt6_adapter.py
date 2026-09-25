"""GPT-6 adapter for peira — OpenAI's GPT-6 Sol / Luna via OpenRouter.

Uses OpenRouter chat completions with structured outputs (JSON schema) so
every primitive returns typed, validated output. Luna is the default: it is
the cheapest sufficient flash-tier model ($0.10/$0.50 per 1M, Sept 2026).

Run it with:

    export OPENROUTER_API_KEY="sk-or-..."
    peira run --adapter examples.gpt6_adapter:Gpt6LunaAdapter --suite trial-demo
    # or Sol:
    peira run --adapter examples.gpt6_adapter:Gpt6SolAdapter --suite trial-demo

Primitive mapping (structured outputs, temperature 0.0):
- peira Choice -> {"decision": "<one of options>", "confidence": 0..1}
- peira Score  -> {"score": 0..1, "decision": "<one of options>"}
- peira Noul   -> {"decision": "<one of options>", "abstained": bool}

Cost (Sept 2026, OpenRouter standard routing): Luna $0.10/$0.50 per 1M
input/output. A full 2,500-case run ~= 5,000 calls x ~400 tokens ~= 2M
tokens ~= **$0.20-$0.30 per full run** (input-dominated).

Stdlib only (urllib) — no third-party dependencies.
"""

from __future__ import annotations

from peira.adapters.base import ChoiceOutput, NoulOutput, ScoreOutput

from examples._openrouter_base import OpenRouterAdapter, OpenRouterError, _clamp01


class _Gpt6Base(OpenRouterAdapter):
    """Shared decide() logic; subclasses pin the model slug."""

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


class Gpt6LunaAdapter(_Gpt6Base):
    """peira adapter backed by OpenAI GPT-6 Luna (efficient tier)."""

    name = "gpt6-luna"
    version = "openai/gpt-6-luna"  # pinned slug — never "latest"
    model = "openai/gpt-6-luna"
    supported_primitives = frozenset({"choice", "score", "noul"})


class Gpt6SolAdapter(_Gpt6Base):
    """peira adapter backed by OpenAI GPT-6 Sol (strong reasoning tier)."""

    name = "gpt6-sol"
    version = "openai/gpt-6-sol"  # pinned slug — never "latest"
    model = "openai/gpt-6-sol"
    supported_primitives = frozenset({"choice", "score", "noul"})


# The CLI resolves `--adapter` names to classes; keep these aliases stable.
adapter = None  # constructed per-run; needs OPENROUTER_API_KEY (see docstring)
