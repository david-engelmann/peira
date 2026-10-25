"""Strands Decider adapter (AWS Strands Labs, Apache 2.0).

Strands Decider is a small decision model (Qwen3.5-2B base with the
LM head removed, a rank-16 LoRA, and a pointer readout head) that
answers typed choice, score, and noul questions in one forward pass
with a probability distribution per question and no generated text.
``strands-decider serve`` exposes ``POST /v1/systemone`` on
127.0.0.1 with no authentication, and JevBench's TypeSafe adapter
runs against it unmodified, so this adapter reuses
``LocalSystemOneAdapter``'s (``peira.adapters.kev``) wire logic with
a different pinned checkpoint and default endpoint.

One wire difference from Jev matters, and this adapter corrects for
it. The server's ``confidence`` field on a choice answer is a
rescaled value (the top probability stretched so an even split
gives 0 and certainty gives 1, whatever the number of options).
Peira's confidence contract is the model's probability for the
chosen option, so this adapter reports ``probabilities[decision]``
and leaves the server's rescaled figure in the transcript only.
The same correction applies to the paired decision answer on score
calls. The server's answer schema always carries the probabilities
map on a decision answer, so a decision answer without one, or
whose map holds no numeric probability for the chosen option, is
contract drift and terminal, never a silent fallback to the
rescaled figure. A score answer's ``score`` field is the
probability-weighted level position on the 0..levels-1 scale,
which is exactly the shape the Jev score mapping normalizes, so
the inherited score handling is correct unchanged.

The constructor pin cannot see what a deployment actually
serves, so the adapter also checks the model name every response
reports. A deployment of the pinned checkpoint reports the
checkpoint's basename (the server's default naming); a response
reporting anything else, or nothing, is terminal. A deployment
renamed with the server's ``--model-name`` option is therefore
out of contract for this adapter.

Checkpoint pin: ``StrandsAgents/strands-decider-2B-hobson-v21``,
the current published reference weights. The checkpoint is baked
into the server deployment (the server downloads the checkpoint
repo plus the Qwen3.5-2B base weights, about 4.5 GB, on first use),
so this adapter accepts only the pinned id. ``api_url=`` points at
the deployment (default ``http://127.0.0.1:8000/v1/systemone``).

Device selection is the server's, not the adapter's: pass
``--device cuda``, ``mps``, or ``cpu`` to ``strands-decider
serve`` (the CLI picks cuda, then mps, then cpu when the flag
is absent). The setup hint in this module's errors omits the
flag so the server auto-detects; which device served a run is
part of the run's configuration, because the stacks do not
give interchangeable numbers (see docs/Adapters.md). CPU
practicality for this 2B checkpoint, measured on this
project's hardware during the adapter's canary, is recorded in
docs/Adapters.md rather than asserted here. The adapter's
default timeout is 120 s, twice the shared base's, because
this checkpoint answers in seconds on CPU and a loaded host
needs the headroom.

The server binds to 127.0.0.1 by default and has no authentication,
and its behaviour under concurrent requests is not verified by its
authors. Run it locally only, and run peira against it at
concurrency 1.

Verified vs unverified: the wire shape, the confidence formula, the
serve flags, and the checkpoint facts are per the project's
published README and inference docs (read 2026-10-15). The
adapter's focused tests use a fake transport. A live canary against
a real server is recorded in the lane's gate notes. A server that
answers differently than the documented contract produces terminal
provider errors, not silent mismeasurement.

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

from typing import Any

from peira.adapters.base import ProviderError
from peira.adapters.kev import LocalSystemOneAdapter

MODEL_ID = "StrandsAgents/strands-decider-2B-hobson-v21"
"""Pinned checkpoint: the current published reference weights."""

EXPECTED_MODEL_STAMP = MODEL_ID.rsplit("/", 1)[-1]
"""The ``model`` name a deployment of the pinned checkpoint
reports on every response (the server's default naming is the
checkpoint basename)."""


def _with_probability_confidence(
    answers: dict[str, Any], name: str
) -> dict[str, Any]:
    """Copy ``answers`` with one answer's confidence set to its
    probability for the chosen option.

    The server's ``confidence`` is a rescaled value (see the module
    docstring). Peira measures the model's probability, which the
    answer's ``probabilities`` map carries verbatim. The server's
    answer schema requires that map on a decision answer, so its
    absence, or a map with no numeric probability for the chosen
    option, is contract drift and terminal here rather than a
    silent fallback to the rescaled figure.
    """
    ans = answers.get(name)
    if not isinstance(ans, dict):
        return answers
    option = ans.get("choice")
    if not isinstance(option, str):
        return answers
    probs = ans.get("probabilities")
    if not isinstance(probs, dict):
        raise ProviderError(
            f"strands-decider decision answer for chosen option "
            f"{option!r} carries no probabilities map; the "
            "server contract puts the model's probability for "
            "the chosen option in that map, so this is server "
            "drift and the call is not measurable."
        )
    p = probs.get(option)
    if not isinstance(p, (int, float)) or isinstance(p, bool):
        # The server builds the probabilities map from its slot
        # labels and reports the argmax as the choice, so the
        # chosen option is in the map by construction. A map
        # without a numeric probability for it is contract
        # drift; falling back to the rescaled confidence here
        # would record a number peira does not measure.
        raise ProviderError(
            f"strands-decider decision answer for chosen option "
            f"{option!r} carries no numeric probability in its "
            f"probabilities map; the server contract puts the "
            "chosen option in the map, so this is server drift "
            "and the call is not measurable."
        )
    if not 0 <= p <= 1:
        # The comparison runs on the raw value: a several-hundred-
        # digit JSON integer parses to an int whose float() below
        # raises OverflowError, and any value outside [0, 1] is not
        # a probability at all. Either is server drift, never a
        # confidence to record (NaN included; its comparisons are
        # all false, so it lands here too).
        raise ProviderError(
            f"strands-decider decision answer for chosen option "
            f"{option!r} carries a probability outside [0, 1] in "
            f"its probabilities map; the server contract puts a "
            f"genuine probability for the chosen option in that "
            f"map, so this is server drift and the call is not "
            f"measurable."
        )
    patched = dict(answers)
    patched_ans = dict(ans)
    patched_ans["confidence"] = float(p)
    patched[name] = patched_ans
    return patched


def _with_model_stamp_check(transport: Any) -> Any:
    """Wrap a transport so every response must report the pinned
    checkpoint's model name.

    The constructor pin governs what peira asks for; this check
    governs what the deployment says it served. The server's
    response schema always carries ``model``, and a deployment of
    the pinned checkpoint reports EXPECTED_MODEL_STAMP under the
    server's default naming. Anything else, or no stamp at all,
    means api_url points at the wrong deployment (or one renamed
    with --model-name) and the call is terminal, never a
    measurement recorded under the pin.
    """

    def checked(payload: dict[str, Any]) -> dict[str, Any]:
        response = transport(payload)
        if isinstance(response, dict):
            stamp = response.get("model")
            if stamp != EXPECTED_MODEL_STAMP:
                raise ProviderError(
                    f"strands-decider server reported model "
                    f"{stamp!r}; this adapter measures only the "
                    f"pinned deployment of {MODEL_ID}, which "
                    f"reports {EXPECTED_MODEL_STAMP!r}; point "
                    "api_url= at that deployment."
                )
        return response

    return checked


class StrandsDeciderAdapter(LocalSystemOneAdapter):
    """Decision adapter for a self-hosted Strands Decider server."""

    name = "strands-decider"
    supported_primitives = frozenset({"choice", "score", "abstain"})
    PINNED_MODEL = MODEL_ID
    KNOWN_MODELS = {MODEL_ID: MODEL_ID}
    """The checkpoint is baked into the server deployment: only the
    pinned id is accepted, no short names, no floating tags."""
    DEFAULT_API_URL = "http://127.0.0.1:8000/v1/systemone"
    """``strands-decider serve``'s default bind and port."""
    SETUP_HINT = (
        "start the server with `strands-decider serve "
        "StrandsAgents/strands-decider-2B-hobson-v21 --port 8000` "
        "(install with `pip install strands-decider`; the server "
        "picks cuda, then mps, then cpu when --device is not "
        "passed), then retry."
    )

    def __init__(
        self,
        model: str | None = None,
        api_url: str | None = None,
        timeout_s: float = 120.0,
        transport: Any = None,
    ) -> None:
        if model is not None and model != MODEL_ID:
            raise ValueError(
                f"strands-decider adapter pins model {MODEL_ID!r}; got "
                f"{model!r}. The checkpoint is baked into the server "
                "deployment; point at a different deployment instead "
                "of passing a different model id."
            )
        super().__init__(model=model, api_url=api_url,
                         timeout_s=timeout_s, transport=transport)
        self._transport = _with_model_stamp_check(self._transport)

    # -- per-primitive mapping --------------------------------------------
    # The inherited Jev mappings read ``confidence`` off the decision
    # answer. Strands serves a rescaled confidence there, so each
    # mapping first rewrites that field to the raw probability for
    # the chosen option (see _with_probability_confidence).

    def _choice_output(self, answers, labels, usage, transcript):
        return super()._choice_output(
            _with_probability_confidence(answers, "decision"),
            labels, usage, transcript,
        )

    def _score_output(self, answers, labels, usage, transcript):
        return super()._score_output(
            _with_probability_confidence(answers, "decision"),
            labels, usage, transcript,
        )
