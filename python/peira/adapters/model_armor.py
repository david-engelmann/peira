"""Google Cloud Model Armor adapter.

Model Armor is Google Cloud's managed prompt/response screening
service. The adapter screens the case prompt as a user prompt through
``:sanitizeUserPrompt`` on a caller-supplied template.

Endpoint: ``POST
https://modelarmor.{location}.rep.googleapis.com/v1/projects/{project}/locations/{location}/templates/{template}:sanitizeUserPrompt``
Auth: ``Authorization: Bearer <OAuth2 access token>`` (scope
``https://www.googleapis.com/auth/cloud-platform``). Get one with
``gcloud auth print-access-token``; the adapter also accepts it
explicitly via ``access_token=...``.

Wire shape (from the Model Armor REST reference,
``projects.locations.templates.sanitizeUserPrompt``; this adapter has
NOT been exercised against the live API, so treat the field names as
our best current reading; docs/Adapters.md keeps the "unverified
against the live API" caveat until one real call succeeds):
requests carry ``{"userPromptData": {"text": text}}``. Responses carry
``{"sanitizationResult": {"filterMatchState": "MATCH_FOUND" |
"NO_MATCH_FOUND", "filterResults": {...}, "invocationResult":
"SUCCESS"}}``. The template decides which filters run (CSAM,
malicious URIs, responsible-AI categories, prompt-injection /
jailbreak, sensitive-data protection); the adapter reads the
top-level ``filterMatchState`` and records the per-filter breakdown
in the transcript.

B2 (guardrails are abstain-primitive-only): a match/no-match verdict
cannot honestly speak the case's domain vocabulary on
choice/score. A ``MATCH_FOUND`` verdict is the explicit ``"abstain"``
label (abstained=False — a deliberate abstain-decision, not a
refusal); ``NO_MATCH_FOUND`` is the ``"other"`` placeholder (the
guardrail vetoes nothing, and it never claims to know the correct
decision).

Model Armor returns a boolean verdict per filter, not a calibrated
confidence score. ``p_malicious`` is therefore 1.0 on ``MATCH_FOUND``
and 0.0 otherwise, and the reported confidence — the M-2/D-23
guardrail boundary distance ``|2p - 1|`` — is degenerate at 1.0. That
is the honest mapping: the provider gives no graded signal, so peira
reports the verdict at full boundary distance rather than inventing
one.

The adapter is stdlib-only (urllib) and performs exactly one HTTP
attempt per call: it never retries internally. Transient failures
(408, 429, 5xx, timeouts, connection errors) are raised as
``ProviderError`` with ``status_code``/``retry_after`` so the runner —
which owns the retry policy — can classify and retry them. 401/403
are terminal.

No ``peira[...]`` extra is needed: the transport is stdlib. What is
needed is access: a GCP project with Model Armor enabled, a template,
and an OAuth2 access token. Without all four pieces the adapter
refuses to construct, with an error that says exactly what to do.

Known caveats (documented, not blockers): the prompt-injection
filter has a ~512-token analysis window — very long case prompts are
screened in full by the service, but the PI signal degrades on long
inputs; Model Armor is text-only.
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

DEFAULT_LOCATION = "us-central1"
"""Default Model Armor region when MODEL_ARMOR_LOCATION is unset."""

PROJECT_ENV = "MODEL_ARMOR_PROJECT_ID"
LOCATION_ENV = "MODEL_ARMOR_LOCATION"
TEMPLATE_ENV = "MODEL_ARMOR_TEMPLATE_ID"
TOKEN_ENV = "MODEL_ARMOR_ACCESS_TOKEN"
"""Environment variables carrying the Model Armor configuration."""


def _api_url(project: str, location: str, template: str) -> str:
    return (
        f"https://modelarmor.{location}.rep.googleapis.com/v1/"
        f"projects/{project}/locations/{location}/"
        f"templates/{template}:sanitizeUserPrompt"
    )


def _require(name: str, explicit: str | None, hint: str, kwarg: str) -> str:
    value = explicit or os.environ.get(name, "")
    if not value:
        raise ValueError(
            f"model-armor adapter needs {hint}: set the {name} "
            f"environment variable (or pass {kwarg}=...)."
        )
    return value


class ModelArmorAdapter:
    """Decision adapter for Google Cloud Model Armor."""

    name = "model-armor"
    version = "1.0"
    supported_primitives = frozenset({"abstain"})
    # M-2/D-23: confidence is the |2p - 1| guardrail boundary distance,
    # not a probability of being correct. Model Armor returns a boolean
    # verdict, so this is degenerate at 1.0 (documented above).
    confidence_source = "guardrail-score"
    # M-7 longitudinal provenance.
    model_class = "guardrail"
    _env_vars = (PROJECT_ENV, LOCATION_ENV, TEMPLATE_ENV, TOKEN_ENV)
    # The template is part of the versioned contract: the same prompt
    # screened under a different template is a different measurement.
    # The runner's opt-in cache namespaces on project/template, and the
    # transcript records the template resource name per call.
    cache_namespace = "model-armor"

    def __init__(
        self,
        project_id: str | None = None,
        location: str | None = None,
        template_id: str | None = None,
        access_token: str | None = None,
        timeout_s: float = 60.0,
        transport: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        self._project_id = _require(
            PROJECT_ENV, project_id,
            "a GCP project ID with Model Armor enabled", "project_id")
        self._location = location or os.environ.get(
            LOCATION_ENV, "") or DEFAULT_LOCATION
        self._template_id = _require(
            TEMPLATE_ENV, template_id, "a Model Armor template ID",
            "template_id")
        self._access_token = _require(
            TOKEN_ENV, access_token,
            "an OAuth2 access token "
            "(e.g. from `gcloud auth print-access-token`)",
            "access_token")
        self.api_url = _api_url(
            self._project_id, self._location, self._template_id)
        self.timeout_s = timeout_s
        # Injectable transport for tests: fn(payload) -> parsed response dict.
        self._transport = transport or self._http_transport
        # The token authenticates the request; it never leaves this object
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
                "Authorization": f"Bearer {self._access_token}",
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
            raise ProviderError(f"model-armor transport error: {e}",
                                status_code=408) from e
        latency_ms = (time.perf_counter() - started) * 1000.0
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ProviderError(
                "model-armor returned non-JSON response"
            ) from e
        if not isinstance(parsed, dict):
            raise ProviderError(
                "model-armor returned a non-object JSON response")
        parsed["_latency_ms"] = latency_ms
        return parsed

    @staticmethod
    def _raise_for_status(
        status: int, retry_after: str | None, detail: str
    ) -> None:
        wait = _parse_retry_after(retry_after)
        msg = ("model-armor API error "
               f"{status}" + (f": {detail}" if detail else ""))
        if status in (401, 403):
            raise ProviderError(
                msg + f" — check that {TOKEN_ENV} is a valid OAuth2 "
                "access token with the cloud-platform scope, and that "
                "the caller has the modelarmor.user role.",
                status_code=status,
            )
        if status in (400, 422):
            raise ProviderError(
                msg + " — the request was rejected; this is an adapter "
                "bug or a bad template resource name, not a retryable "
                "failure.",
                status_code=status,
            )
        if status == 404:
            raise ProviderError(
                msg + " — the template resource name was not found; "
                f"check {PROJECT_ENV}/{LOCATION_ENV}/{TEMPLATE_ENV}.",
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
                f"model-armor does not support primitive {primitive!r} "
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
                model="model-armor:local",
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
                    "model": "model-armor:local",
                    "template": self._template_resource_name(),
                    "skipped": "empty input",
                    "scores": {"p_malicious": 0.0},
                },
            )

        payload = {"userPromptData": {"text": text}}
        response = self._transport(payload)
        result = response.get("sanitizationResult")
        if not isinstance(result, dict):
            raise ProviderError(
                "model-armor response missing 'sanitizationResult' object")
        match_state = result.get("filterMatchState")
        if match_state not in ("MATCH_FOUND", "NO_MATCH_FOUND"):
            raise ProviderError(
                "model-armor response has unexpected "
                f"'filterMatchState': {match_state!r}")
        matched = match_state == "MATCH_FOUND"

        p_malicious = 1.0 if matched else 0.0
        confidence = 1.0  # boolean verdict: |2p - 1| is degenerate.

        usage = CallUsage(
            model="gcp:model-armor",
            # The API returns no token usage, so peira cannot meter
            # per-token spend: cost is explicitly unaccounted (0.0),
            # never silently estimated. The runner recomputes cost_usd
            # from these token counts via the pricing table.
            tokens_in=0,
            tokens_out=0,
            latency_ms=float(response.get("_latency_ms", 0.0)),
            cost_usd=0.0,
        )
        transcript = {
            "model": "gcp:model-armor",
            "template": self._template_resource_name(),
            "request": {"userPromptData": {"text": "<redacted>"}},
            "response": {k: v for k, v in response.items()
                         if not k.startswith("_")},
            "scores": {"p_malicious": p_malicious},
            "matched_filters": _matched_filter_names(result),
        }
        # A MATCH_FOUND verdict is the explicit "abstain" label — a
        # deliberate abstain-decision (abstained=False), not a refusal.
        # NO_MATCH_FOUND is the "other" placeholder: the guardrail
        # vetoes nothing, and it never claims to know the correct
        # decision.
        decision = "abstain" if matched else "other"
        return AbstainOutput(
            decision=decision, confidence=confidence,
            usage=usage, transcript=transcript,
        )

    def _template_resource_name(self) -> str:
        return (f"projects/{self._project_id}/locations/{self._location}/"
                f"templates/{self._template_id}")


def _matched_filter_names(result: dict[str, Any]) -> list[str]:
    """Names of filters with a MATCH_FOUND anywhere in their subtree.

    Filter results nest matchState at varying depths (e.g. one level
    for piAndJailbreakFilterResult, two for sdpFilterResult.inspectResult
    and raiFilterResult.raiFilterTypeResults.<type>), so this walks the
    whole subtree rather than assuming a fixed depth.
    """
    matched: list[str] = []
    filter_results = result.get("filterResults")
    if not isinstance(filter_results, dict):
        return matched
    for filter_name, filter_result in filter_results.items():
        if _contains_match(filter_result):
            matched.append(filter_name)
    return matched


def _contains_match(node: Any) -> bool:
    if isinstance(node, dict):
        if node.get("matchState") == "MATCH_FOUND":
            return True
        return any(_contains_match(v) for v in node.values())
    if isinstance(node, list):
        return any(_contains_match(v) for v in node)
    return False


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
