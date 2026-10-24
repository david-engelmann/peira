"""Cerno adapter (local System One server, pinned checkpoint).

Cerno (Apertix, Apache 2.0) is a family of open-weights System One
decision models published on the Hub as ``apertixai/cerno-27b``,
``apertixai/cerno-9b`` and ``apertixai/cerno-4b``. Each is a
Qwen3.5 text base fine-tuned to answer typed choice, score, and
noul questions in one forward pass. The vendor's inference code
(the System One kit vendored into the Apertix inference repo from
decision-index) renders the state and questions into option
slots, runs a single forward pass, and reads the probability of
each option off the label-token logits, dividing by the
calibration temperature the checkpoint ships in
``decider_config.json`` (1.534 for the 4B at the pinned
revision).

The vendor ships no server. The deployment under test is a
local sidecar that wraps the vendored ``Decider`` class and
exposes ``POST /v1/systemone`` on 127.0.0.1, the same wire shape
the Jev adapter speaks, so this adapter reuses the self-hosted
wire plumbing it shares with Kev and Strands Decider. What is
Cerno's own is the pinned checkpoint, the default endpoint, the
response stamp checks, and the answer validation below. The
server binds to 127.0.0.1 and has no authentication, so run it
locally only, and run peira against it at concurrency 1.

The checkpoint is pinned to ``apertixai/cerno-4b`` at Hub
revision ed4b5c59b542ee96c227ee874776c973980c640b, the only
family member small enough to serve on the trial VM. The
other family members carry pins of their own in the sibling
classes below (``Cerno9BAdapter`` for ``apertixai/cerno-9b``
at 80010f97eaa989b41c908ecba7d7b7fadaa99239, and
``Cerno27BAdapter`` for ``apertixai/cerno-27b`` at
c2f7efe54fe4d3dfd7136bb2e9daf2c0c0633e3d; both revisions
resolved live from the Hub on 2026-10-23), each rejecting
every other family member's id at construction, and each
pin namespacing the runner cache. The weights are FP8 W8A8 as
shipped; that is the checkpoint's native format, served as
published, never re-quantized or converted by the serving stack.
The sidecar loads exactly the pinned snapshot and stamps every
response with the checkpoint name and Hub revision it loaded.
The adapter fails the call when either stamp is absent or
different, so an endpoint serving other weights, or the same
repo at another revision, cannot be measured under the pin by
mistake. The vendored Decider's own response name is
``decider-dev`` for this checkpoint, because its config carries
no version field, so both stamps come from the sidecar, not
the library.

Answer validation is fail-closed. The inherited Jev parser
clamps and defaults malformed numbers (a missing confidence
becomes 0.5, an out-of-range probability is clamped into
range), which is the right posture for a hosted API whose
schema peira does not control, and the wrong one for a pinned
local deployment whose answer schema is fixed. A probability
that is missing, non-numeric, non-finite, or outside [0, 1], a
distribution that does not sum to 1 within rounding, a score
outside the level range, or a noul value that is not a
probability is server drift against that schema, and this
adapter raises a terminal provider error instead of recording
a repaired number.

Peira's confidence contract is the model's probability for
the chosen option. The vendored format code emits that figure
as the answer's ``confidence`` as well as in its
``probabilities`` map, and the vendor's published answer
format omits the field because it duplicates the map entry.
The score mapping in the inherited parser reads the decision
answer's ``confidence`` and defaults it to 0.5 without ever
consulting the map, so an adapter that merely allowed the
field to be absent would record a fabricated 0.5 on every
score call under the published format. This adapter therefore
normalizes the decision answer before parsing, the way the
Strands adapter does. A present ``confidence`` that disagrees
with the map is replaced by the probability, and the field's
absence is repaired from the map, so the recorded confidence
is always a number the model produced. A present but
malformed ``confidence`` is still drift and terminal, since
neither vendor format emits one.

NOTE, abstain/noul boundary mapping: inherited unchanged from
the Jev adapter. The noul answer carries the probability of
"yes, abstain" (the parser also accepts the same value under
an ``abstain`` key, and this adapter validates whichever key
is present). At or above 0.5 the decision is the deliberate
label ``abstain``; below it the decision is the ``other``
placeholder, never a gold label.

Retry layering: none here. The shared transport maps transient
statuses (408, 429, 529, 5xx, timeouts, connection errors) to
retryable provider errors and leaves the policy to the runner,
exactly as the Jev adapter does. A missing local server is
terminal.

Verified against the vendor's own published answers. The
sidecar stack (vendored Decider on CPU, FP8 weights resident,
dequantized per layer for the forward pass) reproduced both
published example requests exactly on argmax, with probability
deltas within 0.026 of the vendor's FP8 reference numbers. The
adapter's first full exercise is the standard driver canary.
"""

from __future__ import annotations

import math
from typing import Any

from peira.adapters.base import ProviderError
from peira.adapters.jev import _SCORE_LEVELS
from peira.adapters.kev import LocalSystemOneAdapter

MODEL_ID = "apertixai/cerno-4b"
"""The one checkpoint this adapter measures.

The pinned id IS the pin: the checkpoint is baked into the
server deployment, so no short names and no floating tags."""

EXPECTED_MODEL_STAMP = "cerno-4b"
"""The checkpoint name the sidecar stamps on every response.

A deployment of the pinned checkpoint reports the name of the
snapshot directory it loaded, not the full Hub id."""

PINNED_REVISION = "ed4b5c59b542ee96c227ee874776c973980c640b"
"""The Hub revision of the pinned checkpoint.

The sidecar stamps this on every response next to the model
name, and the adapter checks it, so a sealed run names the
exact weights that produced it, not just the repo."""

MODEL_ID_9B = "apertixai/cerno-9b"
"""The 9B family member, pinned by ``Cerno9BAdapter``."""

EXPECTED_MODEL_STAMP_9B = "cerno-9b"
"""The checkpoint name the 9B sidecar stamps on every response."""

PINNED_REVISION_9B = "80010f97eaa989b41c908ecba7d7b7fadaa99239"
"""The Hub revision of the pinned 9B checkpoint, resolved live
from the Hub on 2026-10-23."""

MODEL_ID_27B = "apertixai/cerno-27b"
"""The 27B family member, pinned by ``Cerno27BAdapter``."""

EXPECTED_MODEL_STAMP_27B = "cerno-27b"
"""The checkpoint name the 27B sidecar stamps on every response."""

PINNED_REVISION_27B = "c2f7efe54fe4d3dfd7136bb2e9daf2c0c0633e3d"
"""The Hub revision of the pinned 27B checkpoint, resolved live
from the Hub on 2026-10-23."""

_SUM_TOLERANCE = 0.01
"""How far a rounded distribution's mass may sit from 1.

The vendored format rounds each probability to 4 decimals, so
a genuine distribution lands within a few ten-thousandths of
1. The tolerance is far above that and far below any drift
worth recording."""


def _is_probability(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and 0.0 <= value <= 1.0
    )


def _is_finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _require_probability(qid: str, field: str, value: Any) -> None:
    if not _is_probability(value):
        raise ProviderError(
            f"cerno answer '{qid}' carries {field} {value!r}, which "
            "is not a finite probability in [0, 1]; the vendored "
            "answer format always emits one, so this is server "
            "drift and the call is not measurable."
        )


def _validate_confidence(qid: str, answer: dict[str, Any]) -> None:
    """A present confidence must be a finite probability. The
    field itself is optional (the vendor's published format
    omits it); the decision answer's value is normalized from
    the probabilities map before parsing either way."""
    value = answer.get("confidence")
    if value is not None:
        _require_probability(qid, "confidence", value)


def _validate_probability_map(
    qid: str,
    probs: Any,
    *,
    kind: str,
    valid_keys: set[str] | None = None,
    key_kind: str = "option",
) -> None:
    """Fail closed on a missing or malformed distribution.

    ``kind`` is "choice" or "score" and names the answer in the
    messages. When ``valid_keys`` is given, every key must be in
    it (score maps are keyed by level index)."""
    if not isinstance(probs, dict) or not probs:
        raise ProviderError(
            f"cerno {kind} answer '{qid}' carries no probabilities "
            "map; the vendored answer format always emits the "
            "full distribution, so this is server drift and the "
            "call is not measurable."
        )
    total = 0.0
    for key, value in probs.items():
        if valid_keys is not None and key not in valid_keys:
            raise ProviderError(
                f"cerno {kind} answer '{qid}' carries a "
                f"probability for {key_kind} '{key}', which is "
                f"not one of the {kind} levels; the vendored "
                "answer format keys the distribution by level "
                "index, so this is server drift and the call is "
                "not measurable."
            )
        _require_probability(
            qid, f"probability for {key_kind} '{key}'", value)
        total += float(value)
    if abs(total - 1.0) > _SUM_TOLERANCE:
        raise ProviderError(
            f"cerno {kind} answer '{qid}' carries a probabilities "
            f"map whose mass sums to {total:.4f}, not 1; the "
            "vendored answer format emits a softmax distribution, "
            "so this is server drift and the call is not "
            "measurable."
        )


def _validate_answer(qid: str, answer: Any) -> Any:
    """Fail closed on any answer the vendored format cannot emit."""
    if not isinstance(answer, dict):
        raise ProviderError(
            f"cerno answer '{qid}' must be a JSON object, got "
            f"{type(answer).__name__}; the vendored answer format "
            "emits one object per question, so this is server "
            "drift and the call is not measurable."
        )
    kind = answer.get("type")
    if kind == "choice":
        if not isinstance(answer.get("choice"), str):
            raise ProviderError(
                f"cerno choice answer '{qid}' carries no string "
                "choice; the vendored answer format always emits "
                "one, so this is server drift and the call is not "
                "measurable."
            )
        _validate_confidence(qid, answer)
        probs = answer.get("probabilities")
        _validate_probability_map(qid, probs, kind="choice")
        if answer["choice"] not in probs:
            raise ProviderError(
                f"cerno choice answer '{qid}' picks "
                f"'{answer['choice']}', which its probabilities "
                "map does not carry; the vendored answer format "
                "builds the map from the same distribution it "
                "picks from, so this is server drift and the "
                "call is not measurable."
            )
    elif kind == "score":
        score = answer.get("score")
        if not _is_finite_number(score) or not (
            0.0 <= score <= len(_SCORE_LEVELS) - 1
        ):
            raise ProviderError(
                f"cerno score answer '{qid}' carries score "
                f"{score!r}, which is not a finite level position "
                f"in [0, {len(_SCORE_LEVELS) - 1}]; the vendored "
                "answer format emits the probability weighted "
                "level position on that scale, so this is server "
                "drift and the call is not measurable."
            )
        _validate_confidence(qid, answer)
        _validate_probability_map(
            qid,
            answer.get("probabilities"),
            kind="score",
            valid_keys={str(i) for i in range(len(_SCORE_LEVELS))},
            key_kind="level",
        )
    elif kind == "noul":
        # The parser prefers an "abstain" key over "noul" when
        # both are present, so validate whichever keys the answer
        # carries; at least one must carry the probability.
        seen = False
        for field in ("abstain", "noul"):
            if field in answer:
                _require_probability(qid, field, answer[field])
                seen = True
        if not seen:
            raise ProviderError(
                f"cerno answer '{qid}' carries neither 'abstain' "
                "nor 'noul'; the vendored answer format emits "
                "the abstention probability under 'noul', so "
                "this is server drift and the call is not "
                "measurable."
            )
    else:
        raise ProviderError(
            f"cerno answer '{qid}' carries type {kind!r}; the "
            "vendored answer format emits choice, score, or noul "
            "answers only, so this is server drift and the call "
            "is not measurable."
        )
    return answer


def _with_model_stamp_check(
    transport: Any,
    model_id: str = MODEL_ID,
    stamp: str = EXPECTED_MODEL_STAMP,
    revision: str = PINNED_REVISION,
) -> Any:
    """Wrap a transport so every response must report the pinned
    checkpoint's model name and Hub revision.

    The constructor pin governs what peira asks for; this check
    governs what the deployment says it served. The sidecar
    stamps every response with the checkpoint name and revision
    it loaded. Anything else, or either stamp missing, means
    api_url points at the wrong deployment and the call is
    terminal, never a measurement recorded under the pin. The
    pin arguments default to the 4B pin; the sibling classes
    pass their own.
    """

    def checked(payload: dict[str, Any]) -> dict[str, Any]:
        response = transport(payload)
        if isinstance(response, dict):
            reported = response.get("model")
            if reported != stamp:
                raise ProviderError(
                    f"cerno server reported model {reported!r}; this "
                    f"adapter measures only the pinned deployment "
                    f"of {model_id}, which reports "
                    f"{stamp!r}; point api_url= at "
                    "that deployment."
                )
            reported_revision = response.get("revision")
            if reported_revision != revision:
                raise ProviderError(
                    f"cerno server reported revision "
                    f"{reported_revision!r}; this adapter measures only "
                    f"the pinned deployment of {model_id} at Hub "
                    f"revision {revision}; point api_url= "
                    "at that deployment."
                )
        return response

    return checked


def _with_answer_validation(transport: Any) -> Any:
    """Wrap a transport so every answer is validated fail-closed
    (see the module docstring) before the inherited parser sees
    it. A missing or malformed answers container passes through
    untouched; the inherited parser raises the terminal error
    for it."""

    def checked(payload: dict[str, Any]) -> dict[str, Any]:
        response = transport(payload)
        if isinstance(response, dict):
            answers = response.get("answers")
            if isinstance(answers, dict):
                checked_response = dict(response)
                checked_response["answers"] = {
                    qid: _validate_answer(qid, answer)
                    for qid, answer in answers.items()
                }
                return checked_response
        return response

    return checked


def _with_probability_confidence(
    answers: dict[str, Any], key: str
) -> dict[str, Any]:
    """Return a copy of ``answers`` whose ``key`` answer reports
    the model's probability for its chosen option as its
    confidence.

    The inherited mappings read ``confidence`` off the decision
    answer, and the score mapping defaults it to 0.5 when the
    field is absent, without consulting the probabilities map.
    The vendor's published format omits the field precisely
    because it duplicates the map entry, so the entry is the
    measurement and the field is normalized to it here. The
    transport validation has already established that the map
    is a genuine distribution carrying the chosen option; the
    checks below fail closed anyway, so no path through this
    adapter records a defaulted confidence.
    """
    ans = answers.get(key)
    if not isinstance(ans, dict):
        return answers
    probs = ans.get("probabilities")
    choice = ans.get("choice")
    if (
        not isinstance(probs, dict)
        or not isinstance(choice, str)
        or choice not in probs
    ):
        raise ProviderError(
            f"cerno decision answer carries no probabilities map "
            f"entry for its chosen option {choice!r}; the "
            "vendored answer format builds the map from the "
            "same distribution it picks from, so this is server "
            "drift and the call is not measurable."
        )
    patched = dict(ans)
    patched["confidence"] = probs[choice]
    out = dict(answers)
    out[key] = patched
    return out


class CernoAdapter(LocalSystemOneAdapter):
    """Decision adapter for the pinned Cerno 4B checkpoint, served
    locally by the System One sidecar."""

    name = "cerno"
    supported_primitives = frozenset({"choice", "score", "abstain"})
    PINNED_MODEL = MODEL_ID
    KNOWN_MODELS = {MODEL_ID: MODEL_ID}
    """The checkpoint is baked into the server deployment: only the
    pinned id is accepted, no short names, no floating tags."""
    PIN_MODEL_ID = MODEL_ID
    """The Hub id this class pins; the sibling classes override it
    together with the stamp and revision pins below."""
    PIN_STAMP = EXPECTED_MODEL_STAMP
    """The checkpoint name this class's sidecar stamps."""
    PIN_REVISION = PINNED_REVISION
    """The Hub revision this class's sidecar stamps."""
    DEFAULT_API_URL = "http://127.0.0.1:8017/v1/systemone"
    """The Cerno sidecar's bind and port."""
    SETUP_HINT = (
        "start the Cerno sidecar first (it wraps the vendored "
        "Apertix Decider loaded from the pinned apertixai/cerno-4b "
        "snapshot, serves POST /v1/systemone on 127.0.0.1:8017, "
        "and stamps every response with the checkpoint name "
        "cerno-4b and its Hub revision), then retry."
    )

    def __init__(
        self,
        model: str | None = None,
        api_url: str | None = None,
        # CPU serving is slow (a full prefill per call), so the
        # default timeout is 1200 s, not the shared 60 s: a slow
        # but valid call must not be cut.
        timeout_s: float = 1200.0,
        transport: Any = None,
    ) -> None:
        if model is not None and model != self.PIN_MODEL_ID:
            raise ValueError(
                f"cerno adapter pins model {self.PIN_MODEL_ID!r}; got "
                f"{model!r}. The checkpoint is baked into the "
                "server deployment; point at a different "
                "deployment instead of passing a different "
                "model id."
            )
        super().__init__(
            model=model, api_url=api_url, timeout_s=timeout_s,
            transport=transport,
        )
        self._transport = _with_answer_validation(
            _with_model_stamp_check(
                self._transport,
                model_id=self.PIN_MODEL_ID,
                stamp=self.PIN_STAMP,
                revision=self.PIN_REVISION,
            )
        )

    # -- per-primitive mapping --------------------------------------------
    # The inherited Jev mappings read ``confidence`` off the decision
    # answer. The vendor's published format omits that field because
    # it duplicates the chosen option's probability, and the score
    # mapping would default an absent field to 0.5. Each mapping
    # first normalizes the field to the probability (see
    # _with_probability_confidence), so the recorded confidence is
    # always a number the model produced.

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


class Cerno9BAdapter(CernoAdapter):
    """Decision adapter for the pinned Cerno 9B checkpoint.

    Identical wire, validation, and confidence contract to the
    4B adapter; only the pin differs (checkpoint id, sidecar
    stamp, Hub revision), plus the sidecar's bind: the 9B
    deployment serves on 127.0.0.1:8018, one port up from the
    4B's 8017, so both deployments can run side by side. The
    weights are FP8 W8A8 as shipped, the checkpoint's native
    format, never re-quantized by the serving stack.
    """

    name = "cerno-9b"
    PINNED_MODEL = MODEL_ID_9B
    KNOWN_MODELS = {MODEL_ID_9B: MODEL_ID_9B}
    PIN_MODEL_ID = MODEL_ID_9B
    PIN_STAMP = EXPECTED_MODEL_STAMP_9B
    PIN_REVISION = PINNED_REVISION_9B
    DEFAULT_API_URL = "http://127.0.0.1:8018/v1/systemone"
    """The Cerno 9B sidecar's bind and port."""
    SETUP_HINT = (
        "start the Cerno 9B sidecar first (it wraps the vendored "
        "Apertix Decider loaded from the pinned apertixai/cerno-9b "
        "snapshot, serves POST /v1/systemone on 127.0.0.1:8018, "
        "and stamps every response with the checkpoint name "
        "cerno-9b and its Hub revision), then retry."
    )


class Cerno27BAdapter(CernoAdapter):
    """Decision adapter for the pinned Cerno 27B checkpoint.

    Identical wire, validation, and confidence contract to the
    4B adapter; only the pin differs (checkpoint id, sidecar
    stamp, Hub revision), plus the sidecar's bind: the 27B
    deployment serves on 127.0.0.1:8019. The weights are FP8
    W8A8 as shipped (about 27 GB resident), the checkpoint's
    native format, never re-quantized by the serving stack.
    """

    name = "cerno-27b"
    PINNED_MODEL = MODEL_ID_27B
    KNOWN_MODELS = {MODEL_ID_27B: MODEL_ID_27B}
    PIN_MODEL_ID = MODEL_ID_27B
    PIN_STAMP = EXPECTED_MODEL_STAMP_27B
    PIN_REVISION = PINNED_REVISION_27B
    DEFAULT_API_URL = "http://127.0.0.1:8019/v1/systemone"
    """The Cerno 27B sidecar's bind and port."""
    SETUP_HINT = (
        "start the Cerno 27B sidecar first (it wraps the vendored "
        "Apertix Decider loaded from the pinned apertixai/cerno-27b "
        "snapshot, serves POST /v1/systemone on 127.0.0.1:8019, "
        "and stamps every response with the checkpoint name "
        "cerno-27b and its Hub revision), then retry."
    )
