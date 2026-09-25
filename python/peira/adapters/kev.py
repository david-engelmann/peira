"""Kev adapter (Jared Palmer, Apache 2.0).

Kev is an open decision model in the Jev/System One style: one document
(the ``state``) plus a set of typed questions in, calibrated
probabilities out, in a single forward pass — no text generation. It
is a LoRA adapter plus a pointer readout head on a Qwen backbone.

Serving: ``python -m kev.serve`` (from a clone of
github.com/jaredpalmer/kev, with the serve extra installed) exposes a
**TypeSafe-compatible** HTTP API — ``POST /v1/systemone`` with the
same ``{"model", "state", "questions"}`` request shape and
``{"answers": {...}}`` response shape as Jev — so this module reuses
``JevAdapter``'s question building, answer parsing, and output mapping
wholesale. Only the transport (local server, no auth) and the model
pinning differ.

Sizes (all pinned by exact Hub id, verified against the
``jaredpalmer/kev`` Hugging Face collection on 2026-09-25 — repos are
named by base-model size, checkpoint versions within a size are Hub
tags):

- ``jaredpalmer/kev-0.5b``: Qwen2.5-0.5B backbone (the original prototype).
- ``jaredpalmer/kev-0.6b``: Qwen3-0.6B-Base.
- ``jaredpalmer/kev-4b`` (default): Qwen3-4B-Base.
- ``jaredpalmer/kev-8b``: Qwen3-8B-Base — the large arm.

NOTE: early coverage described 0.8B/9B Kev sizes; the published
collection lists 0.5b / 0.6b / 4b / 8b, so ``kev-8b`` is the largest
available size and the adapter's model map follows the collection, not
the press.

Unlike Jev, Kev is self-hosted: there is no API key and no account.
``api_url=`` points at the local server (default
``http://127.0.0.1:8008/v1/systemone``, kev.serve's documented port).
A server that cannot be reached is a terminal provider error whose
message says exactly how to start it — the runner never retries a
missing local server. Cost is $0 (self-hosted); the runner's pricing
table is the cost authority and adapter-reported cost is ignored.

Verified vs unverified (2026-09-25): the wire compatibility claim
(``POST /v1/systemone``, TypeSafe SDK works with only ``base_url``
changed) is per kev's published docs and AGENTS.md; the exact model
ids are verified against the HF collection. This adapter has NOT been
exercised against a live ``kev.serve`` instance — field names are our
best reading of the shared TypeSafe-shaped contract, and a server that
answers differently produces terminal provider errors, not silent
mismeasurement.

NOTE — abstain/noul boundary mapping: peira's primitive is named
``abstain``; the Jev-compatible wire type for that primitive is
``"noul"`` (inherited from ``JevAdapter._noul_question``). The
adapter translates at the boundary: peira's ``abstain`` primitive is
sent as the wire type ``"noul"`` and the ``"abstain"`` answer field is
read back as the abstain signal. Neither side is renamed — peira's
primitive name and the wire type each stay exactly as their owners
define them.

Retry layering: like ``JevAdapter``, this adapter performs exactly one
HTTP attempt per call and never retries internally. HTTP error
statuses keep their ``status_code`` so the runner classifies them as
usual; transport-level failures (no server listening) carry no status
code and are therefore terminal — a local server that is down is a
setup problem, not congestion.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

from peira.adapters.base import ProviderError
from peira.adapters.jev import JevAdapter, _parse_retry_after, _read_error_body

KEV_MODEL_ID = "jaredpalmer/kev-4b"
"""Pinned default: the 4B Qwen3-based Kev checkpoint."""

KNOWN_MODELS = {
    "jaredpalmer/kev-0.5b": "jaredpalmer/kev-0.5b",  # Qwen2.5-0.5B backbone
    "jaredpalmer/kev-0.6b": "jaredpalmer/kev-0.6b",  # Qwen3-0.6B-Base
    "jaredpalmer/kev-4b": "jaredpalmer/kev-4b",      # Qwen3-4B-Base (default)
    "jaredpalmer/kev-8b": "jaredpalmer/kev-8b",      # Qwen3-8B-Base (large arm)
    "0.5b": "jaredpalmer/kev-0.5b",
    "0.6b": "jaredpalmer/kev-0.6b",
    "4b": "jaredpalmer/kev-4b",
    "8b": "jaredpalmer/kev-8b",
}
"""Short size names and full Hub ids accepted for ``model=``.

The dict values are the only model ids this adapter accepts; anything
else (floating tags like ``kev-latest``, unlisted sizes) is rejected at
construction — a measurement must name the exact model."""


def _resolve_model(model: str | None, known: dict[str, str],
                   pinned: str, adapter_name: str) -> str:
    """Map a short name, full id, or None to the pinned Hub id."""
    if model is None:
        return pinned
    if not isinstance(model, str) or not model:
        raise ValueError(
            f"{adapter_name} adapter needs a model id; got {model!r}. "
            f"Known: {sorted(set(known.values()))} (short names: "
            f"{sorted(k for k in known if '/' not in k)})"
        )
    full = known.get(model, model)
    if full not in set(known.values()):
        raise ValueError(
            f"{adapter_name} adapter pins to a known model id; got "
            f"{model!r}. Known: {sorted(set(known.values()))} (short "
            f"names: {sorted(k for k in known if '/' not in k)}). "
            "Floating or unlisted ids are rejected — a measurement "
            "must name the exact model."
        )
    return full


def _is_connection_failure(e: BaseException) -> bool:
    """True when the error means "no server is listening".

    DNS failures, refused connections, and resets are local setup
    problems — the runner must not retry them. Timeouts stay on the
    transient path (cold local models can be slow to wake).
    """
    if isinstance(e, ConnectionRefusedError):
        return True
    if isinstance(e, urllib.error.URLError) and isinstance(
        e.reason, (ConnectionRefusedError, ConnectionResetError)
    ):
        return True
    msg = str(e).lower()
    return any(
        token in msg
        for token in ("connection refused", "name or service not known",
                      "nodename nor servname", "temporary failure in name")
    )


class LocalSystemOneAdapter(JevAdapter):
    """Shared plumbing for self-hosted Jev-compatible servers.

    Subclasses set the class contract:

    - ``name``: the peira adapter name.
    - ``PINNED_MODEL`` / ``KNOWN_MODELS``: the pinning policy used by
      ``_resolve_model``.
    - ``DEFAULT_API_URL``: where the local server is expected.
    - ``SETUP_HINT``: the actionable "how to start the server" text
      carried by connection-failure errors.

    Everything else — question building, answer parsing, the
    abstain/``"noul"`` boundary mapping — is inherited unchanged from
    ``JevAdapter``.
    """

    name = "local-systemone"  # overridden by every subclass
    PINNED_MODEL = ""         # overridden by every subclass
    KNOWN_MODELS: dict[str, str] = {}  # overridden by every subclass
    DEFAULT_API_URL = ""      # overridden by every subclass
    SETUP_HINT = ""           # overridden by every subclass

    def __init__(
        self,
        model: str | None = None,
        api_url: str | None = None,
        timeout_s: float = 60.0,
        transport: Any = None,
    ) -> None:
        resolved = _resolve_model(
            model, self.KNOWN_MODELS, self.PINNED_MODEL, self.name
        )
        self.model = resolved
        # The pinned model id IS the version — never a floating tag —
        # and it namespaces the runner's opt-in response cache so
        # different sizes never share cache entries.
        self.version = resolved
        self.cache_namespace = f"{self.name}:{resolved}"
        self._api_key = None  # local servers take no auth; the key is
        # never sent anywhere (the transport below sends no header).
        self.api_url = api_url or self.DEFAULT_API_URL
        self.timeout_s = timeout_s
        # Injectable transport for tests: fn(payload) -> parsed response
        # dict. No key material exists on this adapter at all.
        self._transport = transport or self._http_transport

    # -- transport --------------------------------------------------------

    def _http_transport(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.api_url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
            # NOTE: deliberately no Authorization header — these servers
            # are local and unauthenticated. If a deployment ever adds
            # auth, that is a new adapter, not a parameter here.
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
            if _is_connection_failure(e):
                # No server is listening: a setup problem, terminal.
                # The message says exactly how to start the server.
                raise ProviderError(
                    f"{self.name}: cannot reach the local server at "
                    f"{self.api_url} ({e}). {self.SETUP_HINT}"
                ) from e
            # Lost connection / timed out: transient, same mapping the
            # Jev adapter uses (status 408 → runner retries).
            raise ProviderError(
                f"{self.name} transport error: {e}", status_code=408
            ) from e
        latency_ms = (time.perf_counter() - started) * 1000.0
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ProviderError(
                f"{self.name} returned non-JSON response (HTTP {status})"
            ) from e
        if not isinstance(parsed, dict):
            raise ProviderError(
                f"{self.name} returned a non-object JSON response"
            )
        parsed["_latency_ms"] = latency_ms
        return parsed

    def _raise_for_status(
        self, status: int, retry_after: str | None, detail: str
    ) -> None:
        wait = _parse_retry_after(retry_after)
        msg = (f"{self.name} server error {status}"
               + (f": {detail}" if detail else ""))
        if status == 401:
            raise ProviderError(
                msg + " — the local server rejected the request as "
                "unauthorized; these servers take no auth, so this is a "
                "server misconfiguration, not a retryable failure.",
                status_code=status,
            )
        if status == 422:
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


class KevAdapter(LocalSystemOneAdapter):
    """Decision adapter for a self-hosted Kev server."""

    name = "kev"
    supported_primitives = frozenset({"choice", "score", "abstain"})
    PINNED_MODEL = KEV_MODEL_ID
    KNOWN_MODELS = KNOWN_MODELS
    DEFAULT_API_URL = "http://127.0.0.1:8008/v1/systemone"
    """kev.serve's documented default port."""
    SETUP_HINT = (
        "start the server with `python -m kev.serve --run "
        "jaredpalmer/kev-4b --port 8008` (from a clone of "
        "github.com/jaredpalmer/kev with the serve extra installed), "
        "then retry."
    )
