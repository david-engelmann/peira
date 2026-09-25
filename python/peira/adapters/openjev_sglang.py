"""openjev-sglang adapter (ekzhang, open models + SGLang).

openjev-sglang is a server implementing the TypeSafe/Jev HTTP API on
top of open models with prefill-only inference: a FastAPI process
fronts SGLang (Rust frontend, radix caching, prefill CUDA graphs) and
exposes Jev-compatible ``POST /v1/systemone`` — ``{"model", "state",
"questions"}`` in, ``{"answers": {...}}`` out, with the same typed
``choice``/``score``/``noul`` questions as Jev. This adapter therefore
reuses ``LocalSystemOneAdapter``'s (``peira.adapters.kev``) wire
logic — question building, answer parsing, the abstain/``"noul"``
boundary — with a different pinned model and default endpoint.

Model: ``Qwen/Qwen3.6-35B-A3B`` MoE (pinned — verified against the
project's published BoolQ eval report, 2026-09-18, which records
``Qwen/Qwen3.6-35B-A3B`` as the response model id). The model is baked
into the server deployment, so unlike Kev (which ships several sizes)
this adapter accepts only the pinned id — anything else is rejected at
construction. ``api_url=`` points at the deployment
(default ``http://localhost:8000/v1/systemone``); no API key is needed.

Verified vs unverified (2026-09-25): the Jev-compatible API claim and
the request example (typed questions, string or chat-message state)
are per the project's published README and curl examples; the model
id is verified against its eval report. This adapter has NOT been
exercised against a live openjev-sglang deployment — field names are
our best reading of the documented contract, and a server that
answers differently produces terminal provider errors, not silent
mismeasurement. The independent parity claim (95.5% vs Jev 96.3% on
the aligned subset, overlapping CIs) is the project's own published
number, not a peira measurement.

NOTE — abstain/noul boundary mapping: peira's primitive is named
``abstain``; the Jev-compatible wire type for that primitive is
``"noul"`` (inherited from ``JevAdapter._noul_question``). The
adapter translates at the boundary: peira's ``abstain`` primitive is
sent as the wire type ``"noul"`` and the ``"abstain"`` answer field is
read back as the abstain signal. Neither side is renamed — peira's
primitive name and the wire type each stay exactly as their owners
define them.

Retry layering: one HTTP attempt per call, never retried internally —
see ``peira.adapters.kev``. HTTP error statuses keep their
``status_code`` for the runner's classifier; a server that cannot be
reached is terminal with an actionable setup message.
"""

from __future__ import annotations

from typing import Any

from peira.adapters.kev import LocalSystemOneAdapter

MODEL_ID = "Qwen/Qwen3.6-35B-A3B"
"""Pinned model: the demo deployment's MoE, per the published eval report."""


class OpenJevSglangAdapter(LocalSystemOneAdapter):
    """Decision adapter for an openjev-sglang deployment."""

    name = "openjev-sglang"
    supported_primitives = frozenset({"choice", "score", "abstain"})
    PINNED_MODEL = MODEL_ID
    KNOWN_MODELS = {MODEL_ID: MODEL_ID}
    """The model is baked into the server deployment: only the pinned
    id is accepted — no short names, no floating tags."""
    DEFAULT_API_URL = "http://localhost:8000/v1/systemone"
    SETUP_HINT = (
        "deploy per github.com/ekzhang/openjev-sglang (SGLang serving "
        "Qwen/Qwen3.6-35B-A3B behind a FastAPI process), then point "
        "api_url= at its /v1/systemone endpoint."
    )

    def __init__(
        self,
        model: str | None = None,
        api_url: str | None = None,
        timeout_s: float = 60.0,
        transport: Any = None,
    ) -> None:
        if model is not None and model != MODEL_ID:
            raise ValueError(
                f"openjev-sglang adapter pins model {MODEL_ID!r}; got "
                f"{model!r}. The model is baked into the server "
                "deployment — point at a different deployment instead "
                "of passing a different model id."
            )
        super().__init__(model=model, api_url=api_url,
                         timeout_s=timeout_s, transport=transport)
