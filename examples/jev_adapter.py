"""Jev adapter for peira — benchmark TypeSafe AI's decision model.

Jev (https://typesafe.ai) is a "System One" decision model: typed questions
in (Choice / Score / Abstain), calibrated probabilities out. It maps 1:1 onto
peira's three primitives, which makes it the natural first production
decision model to benchmark adversarially.

Run it with:

    export TYPESAFE_API_KEY="ts-..."          # direct API (waitlist), or
    export OPENROUTER_API_KEY="sk-or-..."     # OpenRouter passthrough, no waitlist
    peira run --adapter examples.jev_adapter:JevAdapter --suite trial-demo

Pricing (public, Sept 2026): $0.042 per 1M input tokens, output free.
A full 2,500-case peira run = 5,000 decide() calls (benign + attacked).
At ~300 input tokens/call that's ~1.5M tokens ≈ **$0.06 per full run**.

Primitive mapping:
- peira Choice -> Jev Choice (options as criteria, returns winning option)
- peira Score  -> Jev Score with 2 levels [deny-like, approve-like];
                 Jev score is 0..1 directly (top level number is 1, and the
                 official docs say to divide by len(criteria)-1 to normalize).
                 Decision = options[0] iff score >= threshold (default 0.5).
- peira Abstain -> Jev Noul ("Is the correct decision '<opt>'?").
                 Jev's Noul is a yes/no probability primitive, so multi-option
                 Abstain is mapped as one yes/no question per option and the
                 argmax wins (see _decide_abstain for the design rationale).
                 Jev has no native abstain; we abstain when the winning
                 probability is within abstain_margin (default 0.1) of 0.5,
                 i.e. the model is genuinely torn. Documented, not hidden.

Stdlib only (urllib) — no third-party dependencies.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from peira.adapters.base import (
    CaseContext,
    ChoiceOutput,
    AbstainOutput,
    ScoreOutput,
)

# Endpoints. The OpenRouter /v1/systemone passthrough was reported by an
# independent benchmarker (danieleteti.it, Sept 2026); verify before relying
# on it in production.
API_URL_DIRECT = "https://api.typesafe.ai/v1/systemone"
API_URL_OPENROUTER = "https://openrouter.ai/api/v1/systemone"

MODEL_DIRECT = "jev-1.13.0"      # pinned — never "jev-latest"
MODEL_OPENROUTER = "typesafe/jev-1.13"

# Retryable: rate limits and transient server errors. Anything else fails fast.
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class JevError(RuntimeError):
    """Jev API call failed after retries."""


class JevAdapter:
    """peira adapter backed by TypeSafe AI's Jev decision model."""

    name = "jev"
    version = "jev-1.13.0"  # exact pinned model version — never an alias
    supported_primitives = frozenset({"choice", "score", "abstain"})

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str = API_URL_DIRECT,
        model: str | None = None,
        threshold: float = 0.5,
        abstain_margin: float = 0.1,
        timeout: float = 30.0,
        max_retries: int = 5,
        min_interval: float = 0.2,
    ):
        """Args:
        api_key: TypeSafe or OpenRouter key. Defaults to TYPESAFE_API_KEY,
            falling back to OPENROUTER_API_KEY (which also switches the
            default api_base/model to the OpenRouter passthrough).
        api_base: Override the endpoint URL.
        model: Override the pinned model id.
        threshold: Score >= threshold -> options[0], else options[1].
        abstain_margin: Abstain abstains when |p - 0.5| < abstain_margin.
        timeout: Per-request HTTP timeout in seconds.
        max_retries: Retries on 429/5xx with exponential backoff.
        min_interval: Minimum seconds between requests (client-side throttle).
        """
        key = api_key or os.environ.get("TYPESAFE_API_KEY")
        base = api_base
        if key is None:
            key = os.environ.get("OPENROUTER_API_KEY")
            if base == API_URL_DIRECT:
                base = API_URL_OPENROUTER
        if key is None:
            raise JevError(
                "no API key: set TYPESAFE_API_KEY or OPENROUTER_API_KEY "
                "(or pass api_key=)"
            )
        self._api_key = key
        self._api_base = base
        if model is None:
            model = (
                MODEL_OPENROUTER if base == API_URL_OPENROUTER else MODEL_DIRECT
            )
        self._model = model
        self.threshold = threshold
        self.abstain_margin = abstain_margin
        self.timeout = timeout
        self.max_retries = max_retries
        self.min_interval = min_interval
        self._last_call = 0.0

    # ------------------------------------------------------------------
    # peira protocol
    # ------------------------------------------------------------------
    def decide(self, ctx: CaseContext):
        prompt = ctx.input.get("prompt", "")
        options = list(ctx.input.get("options", []))
        if ctx.primitive == "choice":
            return self._decide_choice(prompt, options)
        if ctx.primitive == "score":
            return self._decide_score(prompt, options)
        if ctx.primitive == "abstain":
            return self._decide_abstain(prompt, options)
        raise ValueError(f"unsupported primitive: {ctx.primitive!r}")

    # ------------------------------------------------------------------
    # primitive implementations
    # ------------------------------------------------------------------
    def _decide_choice(self, prompt, options):
        if len(options) < 2:
            raise JevError(f"choice needs >= 2 options, got {options!r}")
        question = {
            "type": "choice",
            "instructions": prompt,
            # Descriptions steer the model; the option text itself is the
            # safest generic description. Override per-domain if needed.
            "criteria": {opt: f"Decide '{opt}'" for opt in options},
        }
        ans = self._ask(prompt, question)
        decision = ans.get("choice")
        if decision not in options:
            raise JevError(f"Jev returned unknown choice {decision!r}")
        return ChoiceOutput(
            decision=decision,
            confidence=_clamp01(float(ans.get("confidence", 0.0))),
        )

    def _decide_score(self, prompt, options):
        if len(options) < 2:
            raise JevError(f"score needs >= 2 options, got {options!r}")
        # Two levels -> Jev score runs 0..1 directly (official docs:
        # normalize by len(criteria)-1, which is 1 here).
        question = {
            "type": "score",
            "instructions": prompt,
            "criteria": [
                f"The correct decision is '{options[1]}'",
                f"The correct decision is '{options[0]}'",
            ],
        }
        ans = self._ask(prompt, question)
        score = _clamp01(float(ans.get("score", 0.0)))
        decision = options[0] if score >= self.threshold else options[1]
        return ScoreOutput(score=score, decision=decision)

    def _decide_abstain(self, prompt, options):
        if len(options) < 2:
            raise JevError(f"abstain needs >= 2 options, got {options!r}")
        if len(options) == 2:
            # Fast path: a single yes/no question about options[0].
            # p = P("options[0] is correct"); options[0] wins iff p >= 0.5.
            question = {
                "type": "noul",
                "instructions": (
                    f"{prompt} Is the correct decision '{options[0]}'? "
                    "Answer yes or no."
                ),
            }
            ans = self._ask(prompt, question)
            p = _clamp01(float(ans.get("noul", 0.5)))
            abstained = abs(p - 0.5) < self.abstain_margin
            decision = options[0] if p >= 0.5 else options[1]
            return AbstainOutput(decision=decision, abstained=abstained)
        # 3+ options: Jev's Noul primitive answers a single yes/no question
        # with a 0-1 probability, so there is no one-call multi-way mapping.
        # We ask one yes/no question per option ("Is the correct decision
        # '<opt>'?") and take the argmax. N calls instead of 1, but each
        # call is cheap (~$0.042/1M input tokens) and this is the only
        # faithful use of the Noul primitive — routing through Jev's Choice
        # instead would conflate the two primitives and hide which one was
        # actually benchmarked.
        #
        # Abstention generalizes the 2-option rule: abstain iff the winning
        # probability is within abstain_margin of 0.5 (the model is torn on
        # its own best answer). Limitation: this does not detect top-two
        # collisions (e.g. 0.90 vs 0.85) — both look "confident" even though
        # the model can't distinguish them.
        probs = []
        for opt in options:
            question = {
                "type": "noul",
                "instructions": (
                    f"{prompt} Is the correct decision '{opt}'? "
                    "Answer yes or no."
                ),
            }
            ans = self._ask(prompt, question)
            probs.append(_clamp01(float(ans.get("noul", 0.5))))
        best = max(range(len(options)), key=lambda i: probs[i])
        p_best = probs[best]
        abstained = abs(p_best - 0.5) < self.abstain_margin
        return AbstainOutput(decision=options[best], abstained=abstained)

    # ------------------------------------------------------------------
    # HTTP layer
    # ------------------------------------------------------------------
    def _ask(self, state: str, question: dict) -> dict:
        """Single question -> Jev answer dict. Retries on 429/5xx."""
        body = json.dumps(
            {
                "model": self._model,
                "state": state,
                "questions": {"q": question},
            }
        ).encode()
        last_err: Exception | None = None
        for attempt in range(self.max_retries + 1):
            self._throttle()
            req = urllib.request.Request(
                self._api_base,
                data=body,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    payload = json.loads(resp.read().decode())
                answers = payload.get("answers", {})
                if "q" not in answers:
                    raise JevError(f"missing answer 'q' in {payload!r}"[:500])
                return answers["q"]
            except urllib.error.HTTPError as e:
                last_err = e
                if e.code not in _RETRYABLE_STATUS or attempt == self.max_retries:
                    raise JevError(f"Jev HTTP {e.code}: {e.read()[:300]!r}")
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
                last_err = e
                if attempt == self.max_retries:
                    raise JevError(f"Jev request failed: {e}")
            # Exponential backoff: 1s, 2s, 4s, ... (plus the 429 case,
            # where the server is explicitly asking us to slow down).
            time.sleep(2.0**attempt)
        raise JevError(f"Jev request failed after retries: {last_err}")

    def _throttle(self):
        """Client-side rate limit: minimum interval between requests."""
        if self.min_interval <= 0:
            return
        now = time.monotonic()
        wait = self.min_interval - (now - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


# The CLI resolves `--adapter` names to classes; keep this alias stable.
adapter = None  # constructed per-run; needs an API key (see module docstring)
