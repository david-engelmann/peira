"""DeepSeek V4.1 Flash adapter for peira — via OpenRouter, thinking disabled.

Model id ``deepseek/deepseek-v4.1-flash`` (1M context, released 2026-09-10).
Thinking is disabled via ``reasoning: {"effort": "none"}`` so every call is
a single fast forward pass — this is the cheap, deterministic seat.

Run it with:

    export OPENROUTER_API_KEY="sk-or-..."
    peira run --adapter examples.deepseek_adapter:DeepSeekAdapter --suite trial-demo

Primitive mapping (structured outputs, temperature 0.0, thinking off):
- peira Choice -> {"decision": "<one of options>", "confidence": 0..1}
- peira Score  -> {"score": 0..1, "decision": "<one of options>"}
- peira Noul   -> {"decision": "<one of options>", "abstained": bool}

Cost (Sept 2026, OpenRouter off-peak): $0.15/$0.60 per 1M input/output
(peak 2x during weekday windows). A full 2,500-case run ~= 5,000 calls x
~400 tokens ~= 2M tokens ~= **$0.30-$0.60 per full run** off-peak.

Stdlib only (urllib) — no third-party dependencies.
"""

from __future__ import annotations

from peira.adapters.base import (
    CaseContext,
    ChoiceOutput,
    AbstainOutput,
    ScoreOutput,
)

from examples._openrouter_base import OpenRouterAdapter, OpenRouterError, _clamp01


class DeepSeekAdapter(OpenRouterAdapter):
    """peira adapter backed by DeepSeek V4.1 Flash (thinking disabled)."""

    name = "deepseek-v4.1-flash"
    version = "deepseek/deepseek-v4.1-flash"  # pinned slug — never "latest"
    model = "deepseek/deepseek-v4.1-flash"
    supported_primitives = frozenset({"choice", "score", "abstain"})

    def __init__(self, **kwargs):
        # Thinking disabled: single fast pass, deterministic, cheaper.
        # DeepSeek's API uses reasoning.effort; "none" disables thinking.
        extra = dict(kwargs.pop("extra_body", {}) or {})
        extra.setdefault("reasoning", {"effort": "none"})
        super().__init__(extra_body=extra, **kwargs)

    def decide(self, ctx: CaseContext):
        prompt = ctx.input.get("prompt", "")
        options = list(ctx.input.get("options", []))
        if len(options) < 2:
            raise OpenRouterError(
                f"{ctx.primitive} needs >= 2 options, got {options!r}")
        if ctx.primitive == "choice":
            return self._decide_choice(prompt, options)
        if ctx.primitive == "score":
            return self._decide_score(prompt, options)
        if ctx.primitive == "abstain":
            return self._decide_noul(prompt, options)
        raise ValueError(f"unsupported primitive: {ctx.primitive!r}")

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
            schema=self.ABSTAIN_SCHEMA,
            schema_name="peira_noul",
        )
        decision = str(out["decision"])
        if decision not in options:
            raise OpenRouterError(
                f"model returned unknown decision {decision!r}")
        return AbstainOutput(decision=decision, abstained=bool(out["abstained"]))


# The CLI resolves `--adapter` names to classes; keep this alias stable.
adapter = None  # constructed per-run; needs OPENROUTER_API_KEY (see docstring)
