"""OpenAI omni-moderation adapter.

OpenAI's production moderation endpoint: the caller sends the content
to screen and the API returns a ``flagged`` boolean plus 13
per-category confidence scores in the 0-1 range.

Endpoint: ``POST https://api.openai.com/v1/moderations``
Auth: ``Authorization: Bearer $OPENAI_API_KEY``

Wire shape (from the official OpenAI API reference, docs "Moderation";
this adapter has NOT been exercised against the live API, so treat the
field names as our best current reading; docs/Adapters.md keeps the
"unverified against the live API" caveat until one real call succeeds):
requests carry ``{"model": "omni-moderation-latest", "input": text}``.
Responses carry ``{"id": ..., "model": <served model>, "results":
[{"flagged": bool, "categories": {name: bool}, "category_scores":
{name: float}}]}``. The 13 categories are ``harassment``,
``harassment/threatening``, ``hate``, ``hate/threatening``,
``illicit``, ``illicit/violent``, ``self-harm``, ``self-harm/intent``,
``self-harm/instructions``, ``sexual``, ``sexual/minors``,
``violence``, ``violence/graphic``.

B2 (guardrails are abstain-primitive-only): a flagged/not-flagged
verdict cannot honestly speak the case's domain vocabulary on
choice/score. A flagged verdict is the explicit ``"abstain"`` label
(abstained=False — a deliberate abstain-decision, not a refusal);
unflagged content is the ``"other"`` placeholder (the guardrail vetoes
nothing, and it never claims to know the correct decision).

The score is ``max(category_scores)`` — the honest aggregation when
categories do not map 1:1 to peira's families. The ``flagged`` boolean
is authoritative for the decision; the scores refine it.

The adapter is stdlib-only (urllib) and performs exactly one HTTP
attempt per call: it never retries internally. Transient failures
(408, 429, 5xx, timeouts, connection errors) are raised as
``ProviderError`` with ``status_code``/``retry_after`` so the runner —
which owns the retry policy — can classify and retry them. 401/403
are terminal.

No ``peira[...]`` extra is needed: the transport is stdlib. What is
needed is access: without ``OPENAI_API_KEY`` the adapter refuses to
construct, with an error that says exactly what to do. The endpoint
itself is free to use.

Known blind spot (documented, not a blocker): a 2026-04 probe found
phishing-style credential-theft prompts can pass silently. Treat
clean verdicts on credential-solicitation cases with skepticism.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Callable

from peira.adapters.base import (
    CallContext,
    CallUsage,
    AbstainOutput,
    ProviderError,
)

API_URL = "https://api.openai.com/v1/moderations"
"""Pinned OpenAI Moderation API endpoint."""

MODEL_ID = "omni-moderation-latest"
"""Pinned model. The response's ``model`` field records what was
actually served; the transcript keeps both."""

API_KEY_ENV = "OPENAI_API_KEY"
"""Environment variable carrying the OpenAI API key."""

_THRESHOLD = 0.5
"""Flagged/not-flagged decision threshold on p_malicious, matching the
HF guardrail adapters."""

#: The 13 omni-moderation categories, per the OpenAI API reference.
CATEGORIES = (
    "harassment",
    "harassment/threatening",
    "hate",
    "hate/threatening",
    "illicit",
    "illicit/violent",
    "self-harm",
    "self-harm/intent",
    "self-harm/instructions",
    "sexual",
    "sexual/minors",
    "violence",
    "violence/graphic",
)


def _require_api_key(explicit: str | None) -> str:
    key = explicit or os.environ.get(API_KEY_ENV, "")
    if not key:
        raise ValueError(
            f"openai-moderation adapter needs an OpenAI API key: set the "
            f"{API_KEY_ENV} environment variable (or pass api_key=...). "
            f"Get one at https://platform.openai.com/api-keys — the "
            f"moderation endpoint is free to use."
        )
    return key


class OmniModerationAdapter:
    """Decision adapter for OpenAI omni-moderation."""

    name = "openai-moderation"
    version = "1.0"
    supported_primitives = frozenset({"abstain"})
    # M-2/D-23: confidence is the |2p - 1| guardrail boundary distance,
    # not a probability of being correct.
    confidence_source = "guardrail-score"
    # M-7 longitudinal provenance.
    model_class = "guardrail"
    _env_vars = (API_KEY_ENV,)
    # The served model can change behind the pinned alias; the runner's
    # opt-in cache namespaces on the alias, and the transcript records
    # the served model per call so drift is visible, not silent.
    cache_namespace = f"openai-moderation:{MODEL_ID}"

    def __init__(
        self,
        api_key: str | None = None,
        timeout_s: float = 60.0,
        transport: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        self._api_key = _require_api_key(api_key)
        # The endpoint is pinned: it is part of the versioned contract
        # (cache_namespace names it), so it is not a constructor knob.
        self.api_url = API_URL
        self.timeout_s = timeout_s
        # Injectable transport for tests: fn(payload) -> parsed response dict.
        self._transport = transport or self._http_transport
        # The key authenticates the request; it never leaves this object
        # except inside the Authorization header of the API call itself.

    # -- transport --------------------------------------------------------

    def _http_transport(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.api_url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                status = resp.status
                retry_after = resp.headers.get("Retry-After")
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            self._raise_for_status(e.code, e.headers.get("Retry-After"),
                                   _read_error_body(e))
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            # Lost connection / DNS / refused / timed out: transient.
            raise ProviderError(f"openai-moderation transport error: {e}",
                                status_code=408) from e
        latency_ms = (time.perf_counter() - started) * 1000.0
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ProviderError(
                "openai-moderation returned non-JSON response "
                f"(HTTP {status})"
            ) from e
        if not isinstance(parsed, dict):
            raise ProviderError(
                "openai-moderation returned a non-object JSON response")
        parsed["_latency_ms"] = latency_ms
        return parsed

    @staticmethod
    def _raise_for_status(
        status: int, retry_after: str | None, detail: str
    ) -> None:
        wait = _parse_retry_after(retry_after)
        msg = ("openai-moderation API error "
               f"{status}" + (f": {detail}" if detail else ""))
        if status in (401, 403):
            raise ProviderError(
                msg + f" — check that {API_KEY_ENV} is valid.",
                status_code=status,
            )
        if status == 422:
            raise ProviderError(
                msg + " — the request was rejected; this is an adapter bug, "
                "not a retryable failure.",
                status_code=status,
            )
        if status == 429 or 500 <= status < 600:
            # Transient: the runner retries with backoff and adapts
            # concurrency. The adapter itself never retries.
            raise ProviderError(msg, status_code=status, retry_after=wait)
        raise ProviderError(msg, status_code=status)

    # -- decide -----------------------------------------------------------

    def decide(
        self, case_input: dict[str, Any], primitive: str, context: CallContext
    ) -> AbstainOutput:
        if primitive not in self.supported_primitives:
            raise ValueError(
                f"openai-moderation does not support primitive {primitive!r} "
                f"(supported: {sorted(self.supported_primitives)})"
            )
        raw_prompt = case_input.get("prompt", "")
        text = raw_prompt if isinstance(raw_prompt, str) else str(raw_prompt)
        # ``context`` is intentionally unused: under B2 it carries no
        # gold, and a guardrail's verdict never depends on trial
        # bookkeeping.

        if not text.strip():
            # Empty/whitespace-only input is benign and never an API
            # call. Matches the other API guardrail adapters. The model
            # ID must NOT be the priced ID: the runner recomputes cost
            # from usage.model via the pricing table, and a local
            # short-circuit must never bill.
            usage = CallUsage(
                model="openai-moderation:local",
                tokens_in=0,
                tokens_out=0,
                latency_ms=0.0,
                cost_usd=0.0,
            )
            return AbstainOutput(
                decision="other",
                confidence=1.0,
                usage=usage,
                transcript={
                    "model": "openai-moderation:local",
                    "endpoint": self.api_url,
                    "skipped": "empty input",
                    "scores": {"p_malicious": 0.0},
                    "threshold": _THRESHOLD,
                },
            )

        payload = {"model": MODEL_ID, "input": text}
        response = self._transport(payload)
        results = response.get("results")
        if not isinstance(results, list) or not results:
            raise ProviderError(
                "openai-moderation response missing non-empty 'results' "
                "array"
            )
        result = results[0]
        if not isinstance(result, dict):
            raise ProviderError(
                "openai-moderation response 'results[0]' is not an object")
        flagged = result.get("flagged")
        if not isinstance(flagged, bool):
            raise ProviderError(
                "openai-moderation response missing boolean "
                "'results[0].flagged'"
            )

        # p_malicious: max over the 13 per-category confidence scores.
        # The boolean is authoritative for the decision; the scores
        # refine it.
        p_malicious = self._p_malicious(result, flagged)

        if flagged:
            p_malicious = max(p_malicious, _THRESHOLD)
            malicious = True
        else:
            p_malicious = min(p_malicious, _THRESHOLD - 1e-9)
            malicious = False

        confidence = max(0.0, min(1.0, abs(2.0 * p_malicious - 1.0)))
        served_model = response.get("model")
        usage = CallUsage(
            model=f"openai:{MODEL_ID}",
            tokens_in=0,  # the endpoint is free; no token billing
            tokens_out=0,
            latency_ms=float(response.get("_latency_ms", 0.0)),
            cost_usd=0.0,  # the runner recomputes cost; adapter value ignored
        )
        transcript = {
            "model": f"openai:{MODEL_ID}",
            "served_model": served_model,
            "endpoint": self.api_url,
            "request": {"model": MODEL_ID, "input": "<redacted>"},
            "response": {k: v for k, v in response.items()
                         if not k.startswith("_")},
            "scores": {"p_malicious": p_malicious},
            "threshold": _THRESHOLD,
        }
        # A flagged verdict is the explicit "abstain" label — a
        # deliberate abstain-decision (abstained=False), not a refusal.
        # Unflagged content is the "other" placeholder: the guardrail
        # vetoes nothing, and it never claims to know the correct
        # decision.
        decision = "abstain" if malicious else "other"
        return AbstainOutput(
            decision=decision, confidence=confidence,
            usage=usage, transcript=transcript,
        )

    @staticmethod
    def _p_malicious(result: dict[str, Any], flagged: bool) -> float:
        """Max over the per-category scores, 0..1."""
        scores = result.get("category_scores")
        if not isinstance(scores, dict) or not scores:
            return 1.0 if flagged else 0.0
        best = 0.0
        for value in scores.values():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                best = max(best, float(value))
        # Clamp: category scores are 0-1 confidence values.
        best = max(0.0, min(1.0, best))
        # If nothing scored but flagged is true, trust the flag.
        if flagged and best == 0.0:
            return 1.0
        return best


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


def _read_error_body(e: urllib.error.HTTPError) -> str:
    try:
        return e.read().decode("utf-8", errors="replace")[:500]
    except OSError:
        return ""
