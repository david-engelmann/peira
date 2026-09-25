"""Shared OpenRouter chat-completions client for peira LLM adapters.

Stdlib only (urllib). Handles auth, retries with exponential backoff,
client-side throttling, and structured-output requests. Each model-specific
adapter subclasses ``OpenRouterAdapter`` and defines its primitive prompts.

Not an adapter itself — import this from your adapter module.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

API_URL = "https://openrouter.ai/api/v1/chat/completions"

# Retryable: rate limits and transient server errors. Anything else fails fast.
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class OpenRouterError(RuntimeError):
    """OpenRouter API call failed after retries."""


class OpenRouterAdapter:
    """Base class for peira adapters backed by OpenRouter chat models.

    Subclasses set:
      - ``name``: adapter name (e.g. "gpt6-luna")
      - ``version``: exact pinned model id (e.g. "openai/gpt-6-luna")
      - ``model``: OpenRouter model slug
      - ``supported_primitives``: frozenset of {"choice", "score", "noul"}
    and implement ``decide()`` using ``self._chat()``.
    """

    name = "openrouter-base"
    version = "openai/gpt-6-luna"
    model = "openai/gpt-6-luna"
    supported_primitives = frozenset({"choice", "score", "noul"})

    # JSON schemas for structured outputs. Anthropic-style constraints
    # (additionalProperties: false everywhere) are used so the same schemas
    # work if a subclass targets the Anthropic API directly.
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
        abstain_margin: float = 0.1,
        timeout: float = 60.0,
        max_retries: int = 5,
        min_interval: float = 0.2,
        temperature: float = 0.0,
        extra_body: dict | None = None,
    ):
        """Args:
        api_key: OpenRouter key. Defaults to OPENROUTER_API_KEY env var.
        api_base: Override the chat-completions endpoint URL.
        model: Override the pinned model slug.
        threshold: Score >= threshold -> options[0], else options[1].
        abstain_margin: Noul abstains when |p - 0.5| < abstain_margin.
        timeout: Per-request HTTP timeout in seconds.
        max_retries: Retries on 429/5xx with exponential backoff.
        min_interval: Minimum seconds between requests (client-side throttle).
        temperature: Sampling temperature (0.0 = deterministic).
        extra_body: Extra top-level fields merged into the request body
            (e.g. {"reasoning": {"effort": "none"}} to disable thinking).
        """
        key = api_key or os.environ.get("OPENROUTER_API_KEY")
        if key is None:
            raise OpenRouterError(
                "no API key: set OPENROUTER_API_KEY (or pass api_key=)"
            )
        self._api_key = key
        self._api_base = api_base
        if model is not None:
            self.model = model
        self.threshold = threshold
        self.abstain_margin = abstain_margin
        self.timeout = timeout
        self.max_retries = max_retries
        self.min_interval = min_interval
        self.temperature = temperature
        self.extra_body = extra_body or {}
        self._last_call = 0.0

    # ------------------------------------------------------------------
    # HTTP layer
    # ------------------------------------------------------------------
    def _chat(self, messages: list[dict], schema: dict | None = None,
              schema_name: str = "peira_output") -> dict:
        """Send a chat-completions request, return the parsed JSON content.

        With ``schema``, requests structured outputs via response_format.
        Raises OpenRouterError on failure or unparseable content.
        """
        body: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }
        if schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": schema,
                },
            }
        body.update(self.extra_body)

        data = json.dumps(body).encode()
        last_err: Exception | None = None
        for attempt in range(self.max_retries + 1):
            self._throttle()
            req = urllib.request.Request(
                self._api_base,
                data=data,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://peiratrial.dev",
                    "X-Title": "peira benchmark",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    payload = json.loads(resp.read().decode())
                content = payload["choices"][0]["message"]["content"]
                if not content or not content.strip():
                    raise OpenRouterError("empty content in response")
                return json.loads(content)
            except urllib.error.HTTPError as e:
                last_err = e
                if e.code not in _RETRYABLE_STATUS or attempt == self.max_retries:
                    raise OpenRouterError(f"OpenRouter HTTP {e.code}: {e.read()[:300]!r}")
            except (urllib.error.URLError, TimeoutError) as e:
                last_err = e
                if attempt == self.max_retries:
                    raise OpenRouterError(f"OpenRouter request failed: {e}")
            except (json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
                raise OpenRouterError(f"OpenRouter bad response: {e}")
            time.sleep(2.0**attempt)
        raise OpenRouterError(f"OpenRouter request failed after retries: {last_err}")

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
    """Clamp to 0..1. NaN becomes 0.0 (fail-closed, never silently 1.0)."""
    if x != x:  # NaN
        return 0.0
    return max(0.0, min(1.0, x))
