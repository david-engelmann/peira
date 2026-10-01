"""Azure AI Content Safety Prompt Shields adapter.

Prompt Shields is Microsoft's dedicated prompt-injection detector,
exposed through the Azure AI Content Safety REST API. It detects
direct jailbreak attacks in the user prompt and indirect injection
in context documents. peira screens the case prompt as the user
prompt with an empty document list.

Endpoint: ``POST
{endpoint}/contentsafety/text:shieldPrompt?api-version=2024-09-01``
Auth: ``Ocp-Apim-Subscription-Key: <key>`` header.

Wire shape (from the Azure Content Safety quickstart "Detect prompt
attacks with Prompt Shields" and the text:shieldPrompt REST
reference; this adapter has NOT been exercised against the live API,
so treat the field names as our best current reading;
docs/Adapters.md keeps the "unverified against the live API" caveat
until one real call succeeds):
requests carry ``{"userPrompt": text, "documents": []}``. Responses
carry ``{"userPromptAnalysis": {"attackDetected": bool},
"documentsAnalysis": [{"attackDetected": bool}]}``. A ``true``
``attackDetected`` means a prompt attack was detected.

B2 (guardrails are abstain-primitive-only): an attackDetected
boolean cannot honestly speak the case's domain vocabulary on
choice/score. An attack-detected verdict is the explicit
``"abstain"`` label (abstained=False — a deliberate
abstain-decision, not a refusal); no attack detected is the
``"other"`` placeholder (the guardrail vetoes nothing, and it never
claims to know the correct decision).

Prompt Shields returns a boolean verdict, not a calibrated
confidence score. ``p_malicious`` is therefore 1.0 on attack
detected and 0.0 otherwise, and the reported confidence — the
M-2/D-23 guardrail boundary distance ``|2p - 1|`` — is degenerate at
1.0. That is the honest mapping: the provider gives no graded
signal, so peira reports the verdict at full boundary distance
rather than inventing one.

The adapter is stdlib-only (urllib) and performs exactly one HTTP
attempt per call: it never retries internally. Transient failures
(408, 429, 5xx, timeouts, connection errors) are raised as
``ProviderError`` with ``status_code``/``retry_after`` so the runner —
which owns the retry policy — can classify and retry them. 401/403
are terminal.

No ``peira[...]`` extra is needed: the transport is stdlib. What is
needed is access: an Azure AI Content Safety resource (endpoint +
key). Without both the adapter refuses to construct, with an error
that says exactly what to do.

Known caveats (documented, not blockers): an independent
evaluation (arXiv:2504.11168, 2025) reports large evasion gaps for
hosted prompt-injection detectors, including Prompt Shields, under
adaptive attacks — treat it as defense-in-depth signal, not complete
mitigation. The stable ``azure-ai-contentsafety`` Python SDK does not
expose ``shield_prompt``, so this adapter calls the REST endpoint
directly.
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

API_VERSION = "2024-09-01"
"""Pinned Content Safety API version for text:shieldPrompt."""

ENDPOINT_ENV = "AZURE_CONTENT_SAFETY_ENDPOINT"
KEY_ENV = "AZURE_CONTENT_SAFETY_KEY"
"""Environment variables carrying the Content Safety resource."""


def _api_url(endpoint: str) -> str:
    return (endpoint.rstrip("/")
            + f"/contentsafety/text:shieldPrompt"
            f"?api-version={API_VERSION}")


def _require(name: str, explicit: str | None, hint: str, kwarg: str) -> str:
    value = explicit or os.environ.get(name, "")
    if not value:
        raise ValueError(
            f"azure-prompt-shields adapter needs {hint}: set the {name} "
            f"environment variable (or pass {kwarg}=...)."
        )
    return value


class AzurePromptShieldsAdapter:
    """Decision adapter for Azure AI Content Safety Prompt Shields."""

    name = "azure-prompt-shields"
    version = "1.0"
    supported_primitives = frozenset({"abstain"})
    # M-2/D-23: confidence is the |2p - 1| guardrail boundary distance,
    # not a probability of being correct. Prompt Shields returns a
    # boolean verdict, so this is degenerate at 1.0 (documented above).
    confidence_source = "guardrail-score"
    # M-7 longitudinal provenance.
    model_class = "guardrail"
    _env_vars = (ENDPOINT_ENV, KEY_ENV)
    # The API version is pinned: the runner's opt-in cache namespaces
    # on it, and the transcript records it per call.
    cache_namespace = f"azure-prompt-shields:{API_VERSION}"

    def __init__(
        self,
        endpoint: str | None = None,
        api_key: str | None = None,
        timeout_s: float = 60.0,
        transport: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        self._endpoint = _require(
            ENDPOINT_ENV, endpoint,
            "an Azure AI Content Safety endpoint "
            "(e.g. https://<resource>.cognitiveservices.azure.com)",
            "endpoint")
        self._api_key = _require(
            KEY_ENV, api_key, "an Azure AI Content Safety API key",
            "api_key")
        self.api_url = _api_url(self._endpoint)
        self.timeout_s = timeout_s
        # Injectable transport for tests: fn(payload) -> parsed response dict.
        self._transport = transport or self._http_transport
        # The key authenticates the request; it never leaves this object
        # except inside the Ocp-Apim-Subscription-Key header of the API
        # call itself.

    # -- transport --------------------------------------------------------

    def _http_transport(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.api_url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Ocp-Apim-Subscription-Key": self._api_key,
            },
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                retry_after = resp.headers.get("Retry-After")
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            self._raise_for_status(e.code, e.headers.get("Retry-After"),
                                   _read_error_body(e))
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            # Lost connection / DNS / refused / timed out: transient.
            raise ProviderError(f"azure-prompt-shields transport error: {e}",
                                status_code=408) from e
        latency_ms = (time.perf_counter() - started) * 1000.0
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ProviderError(
                "azure-prompt-shields returned non-JSON response"
            ) from e
        if not isinstance(parsed, dict):
            raise ProviderError(
                "azure-prompt-shields returned a non-object JSON response")
        parsed["_latency_ms"] = latency_ms
        return parsed

    @staticmethod
    def _raise_for_status(
        status: int, retry_after: str | None, detail: str
    ) -> None:
        wait = _parse_retry_after(retry_after)
        msg = ("azure-prompt-shields API error "
               f"{status}" + (f": {detail}" if detail else ""))
        if status in (401, 403):
            raise ProviderError(
                msg + f" — check that {KEY_ENV} is valid for the "
                f"{ENDPOINT_ENV} resource.",
                status_code=status,
            )
        if status in (400, 422):
            raise ProviderError(
                msg + " — the request was rejected; this is an adapter "
                "bug, not a retryable failure.",
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
                f"azure-prompt-shields does not support primitive "
                f"{primitive!r} (supported: "
                f"{sorted(self.supported_primitives)})"
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
                model="azure-prompt-shields:local",
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
                    "model": "azure-prompt-shields:local",
                    "api_version": API_VERSION,
                    "skipped": "empty input",
                    "scores": {"p_malicious": 0.0},
                },
            )

        # Microsoft documents a 10,000-character maximum for the Prompt
        # Shields userPrompt (and 10,000 characters total across the
        # documents; peira never sends documents). An oversized prompt
        # would be rejected by the API, so refuse locally instead of
        # sending it. Raised as a 400 ProviderError: permanent client
        # errors are terminal and never retried by the runner.
        if len(text) > 10_000:
            raise ProviderError(
                "azure-prompt-shields prompt exceeds the 10,000-character "
                "API limit; refusing to send it",
                status_code=400,
            )

        # peira cases are single prompts; there are no context
        # documents to screen, so documents is always empty.
        payload = {"userPrompt": text, "documents": []}
        response = self._transport(payload)
        analysis = response.get("userPromptAnalysis")
        if not isinstance(analysis, dict):
            raise ProviderError(
                "azure-prompt-shields response missing "
                "'userPromptAnalysis' object")
        attack_detected = analysis.get("attackDetected")
        if not isinstance(attack_detected, bool):
            raise ProviderError(
                "azure-prompt-shields response has non-boolean "
                "'userPromptAnalysis.attackDetected'")

        p_malicious = 1.0 if attack_detected else 0.0
        confidence = 1.0  # boolean verdict: |2p - 1| is degenerate.

        usage = CallUsage(
            model=f"azure:prompt-shields:{API_VERSION}",
            tokens_in=0,  # the runner recomputes cost; adapter value ignored
            tokens_out=0,
            latency_ms=float(response.get("_latency_ms", 0.0)),
            cost_usd=0.0,  # the runner recomputes cost; adapter value ignored
        )
        transcript = {
            "model": f"azure:prompt-shields:{API_VERSION}",
            "api_version": API_VERSION,
            "request": {"userPrompt": "<redacted>", "documents": []},
            "response": {k: v for k, v in response.items()
                         if not k.startswith("_")},
            "scores": {"p_malicious": p_malicious},
        }
        # An attack-detected verdict is the explicit "abstain" label —
        # a deliberate abstain-decision (abstained=False), not a
        # refusal. No attack detected is the "other" placeholder: the
        # guardrail vetoes nothing, and it never claims to know the
        # correct decision.
        decision = "abstain" if attack_detected else "other"
        return AbstainOutput(
            decision=decision, confidence=confidence,
            usage=usage, transcript=transcript,
        )


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
