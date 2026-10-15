"""Von adapter (wfzyx, Apache 2.0).

Von is an open-source non-autoregressive System One decision model
(395M ModernBERT-large encoder plus an option-marker scoring head)
that answers the same three typed questions as Jev in one forward
pass, with a probability over every option and no token generation.
``von serve`` exposes a TypeSafe-compatible ``POST /v1/systemone``
endpoint and runs on CPU through OpenVINO, so this adapter reuses
``LocalSystemOneAdapter``'s (``peira.adapters.kev``) wire logic,
question building, answer parsing, and the abstain/``"noul"``
boundary, with a different pinned model and default endpoint.

Model pin: the wire model id is ``von-1.3.0``, the checkpoint
``von serve`` serves (``wfzyx/von`` on the Hub; its model card
identifies it as Von 1.3, an engine release whose weights are
unchanged from 1.2). No separately servable von-1.1 checkpoint
exists: the SDK accepts ``von-1.1`` only as an alias that resolves
to the current model, and the one older Hub tree identifies
itself as Von-1.0 and predates the Option-Marker scoring head the
server loads. The pin names the weights that actually run. The
checkpoint is baked into the server deployment, so like
openjev-sglang this adapter accepts only the pinned id. Anything
else is rejected at construction. ``api_url=`` points at the
deployment (default ``http://127.0.0.1:8000/v1/systemone``,
``von serve``'s default port). Weights are fetched by the server
from the Hub on first use.

Two server behaviours matter for measurement, and both are operator
settings on the server, not things this adapter can see or fix:

- Noul decision rule. By default ``von serve`` passes the abstain
  probability through its band rule, which pushes every returned
  value outside the 0.2 to 0.8 range while preserving which side of
  0.5 it falls on. The abstain decision is unchanged, but the
  confidence peira derives from the returned value is inflated.
  Run the server with ``--noul-decision raw`` (or
  ``VON_NOUL_DECISION=raw``) for peira measurements so the returned
  value is the calibrated posterior.
- State truncation. By default a state longer than the server's
  token window is middle-truncated and the answer silently measures
  the truncated text. Run the server with ``--on-overflow refuse``
  (or ``VON_ON_OVERFLOW=refuse``) for peira measurements so an
  oversize state fails with a 422 instead.

First request: the server loads its weights lazily, and on a
loaded CPU box that load can exceed this adapter's 60 second
default timeout. Trial wiring should pass a larger ``timeout_s``
(the recorded canary used 900).

Served-model stamp: the server stamps every response with the
model it actually served, and this adapter checks the stamp on
every call. A response naming a different model fails the call
rather than being recorded under the pin, and so does a response
with no stamp at all, because the wire type always carries one.
A server that starts serving a different model (an SDK upgrade,
a wrong endpoint) therefore cannot silently relabel a run. A
checkpoint directory chosen with ``VON_CHECKPOINT_DIR`` keeps the
same stamp, so that choice stays an operator attestation for the
run record.

Auth: ``von serve`` takes no auth unless started with ``VON_API_KEY``
set. When a key is configured here (``api_key=`` or the
``VON_API_KEY`` environment variable) requests carry it as a Bearer
token to whatever endpoint ``api_url`` names, so a remote
deployment should be reached over HTTPS or a tunnel. Without a
key, requests go keyless. The key never appears in transcripts.

Verified vs unverified: the wire compatibility claim, the serve
flags above, and the model facts are per the project's published
README and model card (read 2026-10-15). The adapter's focused tests
use a fake transport. A live canary against a real ``von serve``
is recorded in docs/Adapters.md. A server that answers
differently than the shared TypeSafe-shaped contract produces
terminal provider errors, not silent mismeasurement.

NOTE, abstain/noul boundary mapping: peira's primitive is named
``abstain`` and the Jev-compatible wire type for that primitive is
``"noul"`` (inherited from ``JevAdapter._noul_question``). The
adapter translates at the boundary. Neither side is renamed.

Retry layering: one HTTP attempt per call, never retried internally,
see ``peira.adapters.kev``. HTTP error statuses keep their
``status_code`` for the runner's classifier. A server that cannot be
reached is terminal with an actionable setup message.
"""

from __future__ import annotations

import os
from typing import Any

from peira.adapters.base import ProviderError
from peira.adapters.kev import LocalSystemOneAdapter

MODEL_ID = "von-1.3.0"
"""Pinned model: the Von 1.3 snapshot id the server reports."""


class VonAdapter(LocalSystemOneAdapter):
    """Decision adapter for a self-hosted Von server."""

    name = "von"
    supported_primitives = frozenset({"choice", "score", "abstain"})
    PINNED_MODEL = MODEL_ID
    KNOWN_MODELS = {MODEL_ID: MODEL_ID}
    """The checkpoint is baked into the server deployment: only the
    pinned id is accepted, no short names, no floating tags."""
    DEFAULT_API_URL = "http://127.0.0.1:8000/v1/systemone"
    """``von serve``'s default port."""
    SETUP_HINT = (
        "start the server with `von serve --port 8000 "
        "--noul-decision raw --on-overflow refuse` (install with "
        "`pip install von-sdk`), then retry."
    )
    _env_vars = ("VON_API_KEY",)

    def __init__(
        self,
        model: str | None = None,
        api_url: str | None = None,
        timeout_s: float = 60.0,
        transport: Any = None,
        api_key: str | None = None,
    ) -> None:
        if model is not None and model != MODEL_ID:
            raise ValueError(
                f"von adapter pins model {MODEL_ID!r}; got {model!r}. "
                "The checkpoint is baked into the server deployment; "
                "point at a different deployment instead of passing a "
                "different model id."
            )
        super().__init__(model=model, api_url=api_url,
                         timeout_s=timeout_s, transport=transport)
        self._transport = self._stamping_transport(self._transport)
        # Optional auth: explicit api_key= wins over the env var; None
        # means keyless requests.
        self._api_key = api_key if api_key is not None else os.environ.get(
            "VON_API_KEY"
        )

    @staticmethod
    def _stamping_transport(inner: Any) -> Any:
        """Wrap a transport with the served-model stamp check.

        The server stamps every response with the model it actually
        served; the stamp is a required field of the wire type, so
        every genuine response carries one. A stamp naming any
        other model means the deployment is not running the pinned
        checkpoint, and a missing stamp means the endpoint is not
        answering as a Von deployment at all. Either way, recording
        the answers under the pin would mislabel the run, so the
        call fails terminally instead.
        """

        def checked(payload: Any) -> Any:
            response = inner(payload)
            if isinstance(response, dict):
                served = response.get("model")
                if served is None:
                    raise ProviderError(
                        "von server response carries no model stamp; "
                        f"this adapter measures only {MODEL_ID!r} and "
                        "cannot verify what served this answer. The "
                        "endpoint is not answering as a von serve "
                        f"deployment; point api_url= at a {MODEL_ID} "
                        "deployment."
                    )
                if served != MODEL_ID:
                    raise ProviderError(
                        f"von server response names model {served!r}; "
                        f"this adapter measures only {MODEL_ID!r}. The "
                        "deployment is serving a different checkpoint "
                        "than the pin names; point api_url= at a "
                        f"{MODEL_ID} deployment."
                    )
            return response

        return checked

    def _auth_headers(self) -> dict[str, str]:
        if self._api_key:
            return {"Authorization": f"Bearer {self._api_key}"}
        return {}

    def _unauthorized_hint(self) -> str:
        return (
            "the server rejected the request as unauthorized; if this "
            "deployment was started with VON_API_KEY set, pass the same "
            "key here (api_key= or the VON_API_KEY environment variable)."
        )
