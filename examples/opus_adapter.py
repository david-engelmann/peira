"""Opus 5.5 adapter for peira — Anthropic's flagship via structured outputs.

Uses the Anthropic Messages API directly with ``output_config.format``
(JSON schema, GA since Jan 2026). NOT forced tool_choice: on Opus 5.5 only
``auto``/``none`` are allowed and ``any``/forced ``tool`` hard-400s.

Thinking is pinned to ``low`` effort via ``output_config.effort`` — thinking
tokens are always billed as output on Opus 5.5, so low keeps benchmark runs
affordable.

Run it with:

    export ANTHROPIC_API_KEY="sk-ant-..."
    peira run --adapter examples.opus_adapter:OpusAdapter --suite trial-demo

Primitive mapping (structured outputs, temperature 0.0, effort low):
- peira Choice -> {"decision": "<one of options>", "confidence": 0..1}
- peira Score  -> {"score": 0..1, "decision": "<one of options>"}
- peira Noul   -> {"decision": "<one of options>", "abstained": bool}

The JSON comes back as plain text in a ``type: "text"`` content block
(no ``parsed_output`` at the raw-HTTP level); we parse and validate it
ourselves. Schemas obey Anthropic's constraints: ``additionalProperties:
false`` on every object node, no ``minimum``/``maximum``/``pattern``.

Cost (Sept 2026): ~$4/$20 per 1M input/output. This is the expensive
flagship seat — use it for the reference comparison, not bulk runs.

Stdlib only (urllib) — no third-party dependencies.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from peira.adapters.base import ChoiceOutput, NoulOutput, ScoreOutput

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
MODEL_DEFAULT = "claude-opus-5-5"

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class OpusError(RuntimeError):
    """Anthropic API call failed after retries."""


class OpusAdapter:
    """peira adapter backed by Anthropic Claude Opus 5.5."""

    name = "opus-5.5"
    version = "claude-opus-5-5"  # pinned model id — never an alias
    supported_primitives = frozenset({"choice", "score", "noul"})

    # Anthropic-legal schemas: additionalProperties false everywhere,
    # no minimum/maximum/pattern (all hard-400 on Opus 5.5).
    CHOICE_SCHEMA = {
        "type": "object",
        "properties": {
            "decision": {"type": "string"},
            "confidence": {"type": "number"},
        },
        "required": ["decision", "confidence"],
        "additionalProperties": False,
    }
    SCORE_SCHEMA = {
        "type": "object",
        "properties": {
            "score": {"type": "number"},
            "decision": {"type": "string"},
        },
        "required": ["score", "decision"],
        "additionalProperties": False,
    }
    NOUL_SCHEMA = {
        "type": "object",
        "properties": {
            "decision": {"type": "string"},
            "abstained": {"type": "boolean"},
        },
        "required": ["decision", "abstained"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str = API_URL,
        model: str | None = None,
        threshold: float = 0.5,
        timeout: float = 120.0,
        max_retries: int = 5,
        min_interval: float = 0.5,
        max_tokens: int = 512,
    ):
        """Args:
        api_key: Anthropic key. Defaults to ANTHROPIC_API_KEY env var.
        api_base: Override the messages endpoint URL.
        model: Override the pinned model id.
        threshold: Score >= threshold -> options[0], else options[1].
        timeout: Per-request HTTP timeout in seconds.
        max_retries: Retries on 429/5xx with exponential backoff.
        min_interval: Minimum seconds between requests (client-side throttle).
        max_tokens: Cap on the structured-output response.
        """
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if key is None:
            raise OpusError(
                "no API key: set ANTHROPIC_API_KEY (or pass api_key=)"
            )
        self._api_key = key
        self._api_base = api_base
        self._model = model or MODEL_DEFAULT
        self.threshold = threshold
        self.timeout = timeout
        self.max_retries = max_retries
        self.min_interval = min_interval
        self.max_tokens = max_tokens
        self._last_call = 0.0

    # ------------------------------------------------------------------
    # peira protocol
    # ------------------------------------------------------------------
    def decide(self, case_input, primitive):
        prompt = case_input.get("prompt", "")
        options = list(case_input.get("options", []))
        if len(options) < 2:
            raise OpusError(f"{primitive} needs >= 2 options, got {options!r}")
        if primitive == "choice":
            return self._decide_choice(prompt, options)
        if primitive == "score":
            return self._decide_score(prompt, options)
        if primitive == "noul":
            return self._decide_noul(prompt, options)
        raise ValueError(f"unsupported primitive: {primitive!r}")

    # ------------------------------------------------------------------
    # primitive implementations
    # ------------------------------------------------------------------
    def _decide_choice(self, prompt, options):
        out = self._ask(
            f"{prompt}\n\nWhich option is the correct decision? "
            f"Options: {options}.",
            self.CHOICE_SCHEMA,
        )
        decision = str(out["decision"])
        if decision not in options:
            raise OpusError(f"model returned unknown choice {decision!r}")
        return ChoiceOutput(decision=decision,
                            confidence=_clamp01(float(out["confidence"])))

    def _decide_score(self, prompt, options):
        out = self._ask(
            f"{prompt}\n\nOn a scale of 0.0 to 1.0, how strongly does this "
            f"case warrant '{options[0]}' (vs '{options[1]}')?",
            self.SCORE_SCHEMA,
        )
        score = _clamp01(float(out["score"]))
        # The score is authoritative; the adapter's threshold derives the
        # decision. If the model's decision string contradicts the score,
        # the score wins (prevents silent threshold drift).
        decision = options[0] if score >= self.threshold else options[1]
        return ScoreOutput(score=score, decision=decision)

    def _decide_noul(self, prompt, options):
        out = self._ask(
            f"{prompt}\n\nWhat is the correct decision? Options: {options}. "
            f"If you are genuinely torn (no option is clearly better), "
            f"set abstained to true.",
            self.NOUL_SCHEMA,
        )
        decision = str(out["decision"])
        if decision not in options:
            raise OpusError(f"model returned unknown decision {decision!r}")
        return NoulOutput(decision=decision, abstained=bool(out["abstained"]))

    # ------------------------------------------------------------------
    # Anthropic API layer
    # ------------------------------------------------------------------
    def _ask(self, prompt: str, schema: dict) -> dict:
        """One structured-output request -> parsed JSON dict."""
        body = json.dumps({
            "model": self._model,
            "max_tokens": self.max_tokens,
            # Thinking pinned to low: billed as output, keep runs affordable.
            # NOT forced tool_choice — auto/none only on Opus 5.5.
            "output_config": {
                "effort": "low",
                "format": {"type": "json_schema", "schema": schema},
            },
            "messages": [{"role": "user", "content": prompt}],
        }).encode()

        last_err: Exception | None = None
        for attempt in range(self.max_retries + 1):
            self._throttle()
            req = urllib.request.Request(
                self._api_base,
                data=body,
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": API_VERSION,
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    payload = json.loads(resp.read().decode())
                # JSON comes back as plain text in a text block.
                text = "".join(
                    b.get("text", "") for b in payload.get("content", [])
                    if b.get("type") == "text"
                )
                if not text.strip():
                    raise OpusError("empty text block in response")
                return json.loads(text)
            except urllib.error.HTTPError as e:
                last_err = e
                if e.code not in _RETRYABLE_STATUS or attempt == self.max_retries:
                    raise OpusError(f"Anthropic HTTP {e.code}: {e.read()[:300]!r}")
            except (urllib.error.URLError, TimeoutError) as e:
                last_err = e
                if attempt == self.max_retries:
                    raise OpusError(f"Anthropic request failed: {e}")
            except (json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
                raise OpusError(f"Anthropic bad response: {e}")
            time.sleep(2.0**attempt)
        raise OpusError(f"Anthropic request failed after retries: {last_err}")

    def _throttle(self):
        if self.min_interval <= 0:
            return
        now = time.monotonic()
        wait = self.min_interval - (now - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()


def _clamp01(x: float) -> float:
    if x != x:  # NaN -> fail closed
        return 0.0
    return max(0.0, min(1.0, x))


# The CLI resolves `--adapter` names to classes; keep this alias stable.
adapter = None  # constructed per-run; needs ANTHROPIC_API_KEY (see docstring)
