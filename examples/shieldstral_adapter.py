"""Shieldstral 1.0 adapter for peira — Mistral's policy-adaptive guardrail.

Shieldstral (mistralai/Shieldstral-1.0-3B, Apache 2.0) frames moderation as
binary question-answering: each request has an <Instruct> (policy context),
a <Query> (one yes/no question), and a <Document> (content to judge). The
model emits a single yes/no token; a continuous safety score comes from the
softmax over the yes/no logits.

This adapter talks to any OpenAI-compatible chat-completions endpoint
serving Shieldstral (e.g. vLLM). It requests logprobs and computes the
yes-probability from the top logprobs; if logprobs are unavailable it falls
back to parsing the yes/no text with a neutral 0.5 confidence.

Run it with:

    # Serve Shieldstral (one-time):
    vllm serve mistralai/Shieldstral-1.0-3B --max-model-len 32768
    # Then:
    peira run --adapter examples.shieldstral_adapter:ShieldstralAdapter \\
        --suite trial-demo

Primitive mapping (Shieldstral is a yes/no classifier, like Jev's Noul):
- peira Choice -> one yes/no question per option
  ("Should the decision be '<opt>'?"), argmax of yes-probabilities.
- peira Score  -> yes-probability of "Should the decision be
  '<options[0]>'?" as the score; decision = options[0] iff score >= threshold.
- peira Noul   -> direct: "Is the correct decision '<opt>'?" per option
  (2-option fast path asks about options[0] only). Abstains when the winning
  probability is within abstain_margin of 0.5.

Stdlib only (urllib) — no third-party dependencies.
"""

from __future__ import annotations

import json
import math
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

# Default: vLLM serving Shieldstral locally. Override with api_base=.
API_URL_DEFAULT = "http://localhost:8000/v1/chat/completions"
MODEL_DEFAULT = "mistralai/Shieldstral-1.0-3B"

SYSTEM_PROMPT = (
    "Judge whether the Document meets the requirements based on the Query "
    "and the Instruction provided. Note that the answer can only be 'yes' "
    "or 'no'."
)

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class ShieldstralError(RuntimeError):
    """Shieldstral API call failed after retries."""


class ShieldstralAdapter:
    """peira adapter backed by Mistral's Shieldstral 1.0 guardrail."""

    name = "shieldstral"
    version = "mistralai/Shieldstral-1.0-3B"  # pinned checkpoint — never an alias
    supported_primitives = frozenset({"choice", "score", "abstain"})

    def __init__(
        self,
        api_base: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        threshold: float = 0.5,
        abstain_margin: float = 0.1,
        timeout: float = 60.0,
        max_retries: int = 5,
        min_interval: float = 0.0,
    ):
        """Args:
        api_base: OpenAI-compatible chat-completions URL serving
            Shieldstral. Defaults to SHIELDSTRAL_API_BASE env var, else
            http://localhost:8000/v1/chat/completions (vLLM).
        api_key: Bearer token if the endpoint needs one. Defaults to
            SHIELDSTRAL_API_KEY env var (optional for local vLLM).
        model: Override the model id sent to the endpoint.
        threshold: Score >= threshold -> options[0], else options[1].
        abstain_margin: Abstain abstains when |p - 0.5| < abstain_margin.
        timeout: Per-request HTTP timeout in seconds.
        max_retries: Retries on 429/5xx with exponential backoff.
        min_interval: Minimum seconds between requests (client-side throttle).
        """
        self._api_base = (
            api_base or os.environ.get("SHIELDSTRAL_API_BASE") or API_URL_DEFAULT
        )
        self._api_key = api_key or os.environ.get("SHIELDSTRAL_API_KEY")
        self._model = model or MODEL_DEFAULT
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
            return self._decide_noul(prompt, options)
        raise ValueError(f"unsupported primitive: {ctx.primitive!r}")

    # ------------------------------------------------------------------
    # primitive implementations
    # ------------------------------------------------------------------
    def _decide_choice(self, prompt, options):
        if len(options) < 2:
            raise ShieldstralError(f"choice needs >= 2 options, got {options!r}")
        probs = [self._yes_prob(prompt, f"Should the decision be '{o}'?")
                 for o in options]
        best = max(range(len(options)), key=lambda i: probs[i])
        return ChoiceOutput(decision=options[best],
                            confidence=_clamp01(probs[best]))

    def _decide_score(self, prompt, options):
        if len(options) < 2:
            raise ShieldstralError(f"score needs >= 2 options, got {options!r}")
        # The score is P(yes | "Should the decision be '<options[0]>'?").
        # options[0] is the positive/approve pole by peira convention.
        score = _clamp01(
            self._yes_prob(prompt, f"Should the decision be '{options[0]}'?"))
        decision = options[0] if score >= self.threshold else options[1]
        return ScoreOutput(score=score, decision=decision)

    def _decide_noul(self, prompt, options):
        if len(options) < 2:
            raise ShieldstralError(f"noul needs >= 2 options, got {options!r}")
        if len(options) == 2:
            p = _clamp01(
                self._yes_prob(prompt,
                               f"Is the correct decision '{options[0]}'?"))
            abstained = abs(p - 0.5) < self.abstain_margin
            decision = options[0] if p >= 0.5 else options[1]
            return AbstainOutput(decision=decision, abstained=abstained)
        probs = [self._yes_prob(prompt, f"Is the correct decision '{o}'?")
                 for o in options]
        best = max(range(len(options)), key=lambda i: probs[i])
        p_best = _clamp01(probs[best])
        abstained = abs(p_best - 0.5) < self.abstain_margin
        return AbstainOutput(decision=options[best], abstained=abstained)

    # ------------------------------------------------------------------
    # Shieldstral query layer
    # ------------------------------------------------------------------
    def _yes_prob(self, prompt: str, query: str) -> float:
        """P(yes) for one Instruct/Query/Document question."""
        user_content = (
            f"<Instruct>\nYou are a safety classifier. Be strict.\n\n"
            f"<Query>\n{query}\n\n<Document>\n{prompt}"
        )
        body = json.dumps({
            "model": self._model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "max_tokens": 1,
            "temperature": 0.0,
            "logprobs": True,
            "top_logprobs": 20,
        }).encode()

        last_err: Exception | None = None
        for attempt in range(self.max_retries + 1):
            self._throttle()
            headers = {"Content-Type": "application/json"}
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"
            req = urllib.request.Request(
                self._api_base, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    payload = json.loads(resp.read().decode())
                return _extract_yes_prob(payload)
            except urllib.error.HTTPError as e:
                last_err = e
                if e.code not in _RETRYABLE_STATUS or attempt == self.max_retries:
                    raise ShieldstralError(
                        f"Shieldstral HTTP {e.code}: {e.read()[:300]!r}")
            except (urllib.error.URLError, TimeoutError) as e:
                last_err = e
                if attempt == self.max_retries:
                    raise ShieldstralError(f"Shieldstral request failed: {e}")
            except (json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
                raise ShieldstralError(f"Shieldstral bad response: {e}")
            time.sleep(2.0**attempt)
        raise ShieldstralError(
            f"Shieldstral request failed after retries: {last_err}")

    def _throttle(self):
        if self.min_interval <= 0:
            return
        now = time.monotonic()
        wait = self.min_interval - (now - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()


def _extract_yes_prob(payload: dict) -> float:
    """Softmax over yes/no logits from the first generated position.

    Falls back to parsing the yes/no text (0.5 when ambiguous).
    """
    try:
        choice = payload["choices"][0]
        top = choice["logprobs"]["content"][0]["top_logprobs"]
        z_yes, z_no = -10.0, -10.0
        for tok in top:
            t = str(tok["token"]).strip().lower()
            lp = float(tok["logprob"])
            if t in ("yes",):
                z_yes = max(z_yes, lp)
            elif t in ("no",):
                z_no = max(z_no, lp)
        if z_yes > -10.0 or z_no > -10.0:
            return math.exp(z_yes) / (math.exp(z_yes) + math.exp(z_no))
    except (KeyError, IndexError, TypeError, ValueError):
        pass
    # Fallback: parse the generated text.
    try:
        text = payload["choices"][0]["message"]["content"].strip().lower()
    except (KeyError, IndexError, TypeError, AttributeError):
        return 0.5
    if text.startswith("yes"):
        return 1.0
    if text.startswith("no"):
        return 0.0
    return 0.5


def _clamp01(x: float) -> float:
    if x != x:  # NaN -> fail closed
        return 0.0
    return max(0.0, min(1.0, x))


# The CLI resolves `--adapter` names to classes; keep this alias stable.
adapter = None  # constructed per-run (see module docstring)
