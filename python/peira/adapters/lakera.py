"""Lakera Guard adapter (Check Point AI Guardrails).

Lakera Guard is a commercial AI guardrail API: the caller sends the
content to screen and the API returns whether any threat was flagged,
optionally with a per-detector breakdown carrying ordinal confidence
levels.

Endpoint: ``POST https://api.lakera.ai/v2/guard``
Auth: ``Authorization: Bearer $LAKERA_API_KEY``

Wire shape (from the official docs at docs.lakera.ai/docs/api/guard —
this adapter has NOT been exercised against the live API, so treat the
field names as our best current reading; docs/Adapters.md keeps the
"unverified against the live API" caveat until one real call succeeds):
requests carry ``{"messages": [{"role", "content"}], "breakdown": true}``
(the OpenAI chat-completions message format; Guard screens the last
interaction). Responses carry ``{"flagged": bool, "breakdown": [...],
"metadata": {"request_uuid": ...}}``. Each breakdown entry has
``detector_type``, ``detected`` (bool), and ``result`` (ordinal
confidence: ``l1_confident`` … ``l5_unlikely`` / ``no_level``).

B2 (guardrails are abstain-primitive-only): a binary flagged/not-flagged
verdict cannot honestly speak the case's domain vocabulary on
choice/score. A flagged verdict is the explicit ``"abstain"`` label
(abstained=False — a deliberate abstain-decision, not a refusal);
unflagged content is the ``"other"`` placeholder (the guardrail vetoes
nothing, and it never claims to know the correct decision).

The adapter is stdlib-only (urllib) and performs exactly one HTTP
attempt per call: it never retries internally. Transient failures
(408, 429, 5xx, timeouts, connection errors) are raised as
``ProviderError`` with ``status_code``/``retry_after`` so the runner —
which owns the retry policy — can classify and retry them. 401/422
are terminal.

No ``peira[...]`` extra is needed: the transport is stdlib. What is
needed is access: without ``LAKERA_API_KEY`` the adapter refuses to
construct, with an error that says exactly what to do.
"""

from __future__ import annotations

import json
import os
import re
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

API_URL = "https://api.lakera.ai/v2/guard"
"""Pinned Lakera Guard v2 screening endpoint."""

API_VERSION = "v2"
"""Pinned API major version. The endpoint path carries it; a v3 would
need a new adapter revision, not a silent upgrade."""

API_KEY_ENV = "LAKERA_API_KEY"
"""Environment variable carrying the Lakera API key."""

_THRESHOLD = 0.5
"""Flagged/not-flagged decision threshold on p_malicious, matching the
HF guardrail adapters."""

# Ordinal confidence levels from the breakdown, mapped to a float.
# The API returns strings like "l1_confident" … "l5_unlikely" or
# "no_level". We parse the digit and interpolate linearly; anything
# unparseable is 0.0 (fail toward benign, never toward flagged).
_LEVEL_RE = re.compile(r"^l([1-5])", re.IGNORECASE)


def _level_to_float(level: Any) -> float:
    """Map a Lakera ordinal confidence level to 0..1."""
    if not isinstance(level, str):
        return 0.0
    m = _LEVEL_RE.match(level.strip().lower())
    if not m:
        return 0.0
    n = int(m.group(1))
    # l1 (most confident) -> 1.0 … l5 (least) -> 0.0
    return (5 - n) / 4.0


def _require_api_key(explicit: str | None) -> str:
    key = explicit or os.environ.get(API_KEY_ENV, "")
    if not key:
        raise ValueError(
            f"lakera adapter needs a Lakera API key: set the {API_KEY_ENV} "
            f"environment variable (or pass api_key=...). Get one at "
            f"https://platform.lakera.ai/ (free Community tier: "
            f"10k requests/month)."
        )
    return key


class LakeraAdapter:
    """Decision adapter for Lakera Guard (Check Point AI Guardrails)."""

    name = "lakera"
    version = API_VERSION
    supported_primitives = frozenset({"abstain"})
    _env_vars = (API_KEY_ENV,)
    # The policy behind the key can change server-side, but the API
    # version is pinned; the runner's opt-in cache namespaces on it.
    cache_namespace = f"lakera:{API_VERSION}"

    def __init__(
        self,
        api_key: str | None = None,
        timeout_s: float = 60.0,
        transport: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        self._api_key = _require_api_key(api_key)
        # The endpoint is pinned: it is part of the versioned contract
        # (cache_namespace names it), so it is not a constructor knob.
        # A new API version needs a new adapter revision, not a URL
        # override at call time.
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
            raise ProviderError(f"lakera transport error: {e}",
                                status_code=408) from e
        latency_ms = (time.perf_counter() - started) * 1000.0
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ProviderError(
                f"lakera returned non-JSON response (HTTP {status})"
            ) from e
        if not isinstance(parsed, dict):
            raise ProviderError("lakera returned a non-object JSON response")
        parsed["_latency_ms"] = latency_ms
        return parsed

    @staticmethod
    def _raise_for_status(
        status: int, retry_after: str | None, detail: str
    ) -> None:
        wait = _parse_retry_after(retry_after)
        msg = f"lakera API error {status}" + (f": {detail}" if detail else "")
        if status == 401:
            raise ProviderError(
                msg + f" — check that {API_KEY_ENV} is valid and the "
                "account has Guard API access.",
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
                f"lakera does not support primitive {primitive!r} "
                f"(supported: {sorted(self.supported_primitives)})"
            )
        raw_prompt = case_input.get("prompt", "")
        text = raw_prompt if isinstance(raw_prompt, str) else str(raw_prompt)
        # ``context`` is intentionally unused: under B2 it carries no
        # gold, and a guardrail's verdict never depends on trial
        # bookkeeping.

        payload = {
            "messages": [{"role": "user", "content": text}],
            "breakdown": True,
        }
        response = self._transport(payload)
        flagged = response.get("flagged")
        if not isinstance(flagged, bool):
            # Never dump the full response: it is unbounded provider
            # output and does not help the user act.
            keys = sorted(response.keys()) if isinstance(response, dict) else []
            raise ProviderError(
                "lakera response missing boolean 'flagged' "
                f"(response keys: {keys})"
            )

        # p_malicious: the highest detector confidence from the
        # breakdown; fall back to the flagged boolean when the
        # breakdown is absent or empty.
        p_malicious = self._p_malicious(response, flagged)

        malicious = p_malicious >= _THRESHOLD
        # Guard against a flagged=false response with a high-confidence
        # breakdown (or vice versa): the boolean is authoritative for
        # the decision, the breakdown refines the score.
        if flagged:
            p_malicious = max(p_malicious, _THRESHOLD)
            malicious = True
        else:
            p_malicious = min(p_malicious, _THRESHOLD - 1e-9)
            malicious = False

        confidence = max(0.0, min(1.0, abs(2.0 * p_malicious - 1.0)))
        usage = CallUsage(
            model=f"lakera:{API_VERSION}",
            tokens_in=0,  # Lakera bills per call, not per token
            tokens_out=0,
            latency_ms=float(response.get("_latency_ms", 0.0)),
            cost_usd=0.0,  # the runner recomputes cost; adapter value ignored
        )
        transcript = {
            "model": f"lakera:{API_VERSION}",
            "endpoint": self.api_url,
            "request": {
                "messages": [{"role": "user", "content": "<redacted>"}],
                "breakdown": True,
            },
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
    def _p_malicious(response: dict[str, Any], flagged: bool) -> float:
        """Highest detector confidence from the breakdown, 0..1."""
        breakdown = response.get("breakdown")
        if not isinstance(breakdown, list) or not breakdown:
            return 1.0 if flagged else 0.0
        best = 0.0
        for entry in breakdown:
            if not isinstance(entry, dict):
                continue
            if entry.get("detected") is True:
                best = max(best, _level_to_float(entry.get("result")))
            # A detected=false entry contributes nothing, whatever its
            # level claims.
        # If nothing was detected but flagged is true, trust the flag.
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
