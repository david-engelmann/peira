"""Google Gemini Decisions adapter (gemini-decision-1).

gemini-decision-1 is Google's decision model, served through the
Gemini Decisions API: instead of generating text, the caller sends
one shared input (the decision context) plus named, typed questions,
and the API scores the options in a single forward pass. It returns
a chosen option with probabilities for ``choice``, a
probability-weighted numeric answer for ``score``, and a
probability-of-yes for ``abstain`` (the wire type is ``noul``, as on
the Jev wire). The questions are Jev's builders, imported from
``peira.adapters.jev`` exactly as the TypeSafe Decider adapter
imports them, so this wire sees the same decision spaces as the
other Decisions wires and the rows stay comparable.

One pinned model is supported, named by its full served id so a
measurement always names the exact model that produced it:

- ``gemini-decision-1`` (the only pin): launched 2026-11-11.
  $0.10 per 1M input tokens, output free (the wire reports zero
  output tokens on every call).

Endpoint: ``POST https://generativelanguage.googleapis.com/v1beta/decisions``
Auth: the API key travels in the ``x-goog-api-key`` header, the
placement the Gemini API reads. Without a key the adapter refuses
to construct, with an error that says exactly what to do.

Live state: the wire shape below was verified against the live API
on 2026-11-16 by the standard driver canary, before this adapter
was written. Twenty calls on real v2 cases (ten cases, both arms)
returned twenty clean decisions with zero refusals and zero errors,
and two complete executions produced identical totals and identical
spot-checked probabilities, so the service is deterministic on
these inputs. The plain string form of ``input`` was accepted on
the first call, so the documented content-block form was never
needed. The canary is the specification this adapter implements:
the same question builders, the same label construction, the same
per-primitive mapping, and the same fail-closed wire validation.

No model echo: the response carries only ``answers`` and ``usage``,
with no model field anywhere. There is therefore nothing to check
the pin against on the way back, and this adapter does not pretend
otherwise. Served identity rests on the request alone. Every
transcript records ``echoed_model`` (null on this wire) so the gap
is visible in the sealed record rather than smoothed over. This is
the one structural respect in which a Google Decisions measurement
is weaker than a Perplexity one, whose adapter refuses a response
whose echoed model differs from its pin.

Mapping notes. A choice case sends one choice question whose
options are the case answer labels, and the top-probability option
is the decision. A score case sends a score question plus a paired
decision question in the same call (the Perplexity decider
precedent): the reported score is the probability-weighted rubric
position divided by levels minus one, recomputed from the answer's
probabilities, with the wire ``score`` field as the fallback when
no probabilities arrive, and the paired answer carries the decision
label. An abstain case sends one noul question: a probability at or
above 0.5 is the abstention, and below it the decision is the
``other`` placeholder, with flip detection keyed off the
``abstained`` flag. A scoring API returns no generated text, so the
malformed text class does not exist for this model. Wire validation
failures (a missing answer, missing or non-integer usage counters,
an out-of-vocabulary choice, an ambiguous abstain reading) fail
closed as provider errors and are never recorded as decisions.

The adapter is stdlib-only (urllib) and performs exactly one HTTP
attempt per call: it never retries internally. Transient failures
(408, 409, 429, 529, 5xx, timeouts, connection errors) are raised
as ``ProviderError`` with ``status_code``/``retry_after`` so the
runner, which owns the retry policy, can classify and retry them.
401/403, 404 and 400/422 are terminal. The runner owns concurrency.

No ``peira[...]`` extra is needed: the transport is stdlib.

NOTE, abstain decision placeholder: for the abstain primitive, the
model only answers "should I abstain?" (a yes/no probability). It
never produces a decision label. When the model does NOT abstain
(p < 0.5), there is no model decision to report, so the ``decision``
field is the ``"other"`` placeholder; an honest marker, never a
gold label (under B2 the adapter cannot see gold anyway). Flip
detection for abstain cases works via the ``abstained`` flag (which
IS a model output), not the ``decision`` field. This is by design,
not a bug, and matches the Jev and Perplexity adapters exactly.
"""

from __future__ import annotations

import json
import math
import os
import time
import urllib.error
import urllib.request
from typing import Any, Callable

from peira.adapters._labels import (
    candidate_labels,
    non_abstain_placeholder,
)

from peira.adapters.base import (
    AbstainOutput,
    CallContext,
    CallUsage,
    ChoiceOutput,
    ProviderError,
    ScoreOutput,
)

from peira.adapters.jev import (
    _SCORE_LEVELS,
    _choice_question,
    _noul_question,
    _score_question,
    _validate_questions,
)

SUPPORTED_MODEL_IDS = frozenset({
    "gemini-decision-1",
})
"""Pinned served model ids. Ids outside this table are rejected at
construction; a measurement must name the exact model."""

MODEL_ID = "gemini-decision-1"
"""Default pinned Gemini Decisions model: the only served version."""

API_KEY_ENV = "GOOGLE_API_KEY"
"""Environment variable carrying the Google API key."""

API_KEY_ENV_FALLBACK = "GEMINI_API_KEY"
"""Second environment variable tried, the Gemini name for the same
key, matching the GoogleAdapter convention in peira.adapters.llm."""

API_URL = "https://generativelanguage.googleapis.com/v1beta/decisions"
"""The Gemini Decisions endpoint."""


def _require_api_key(explicit: str | None) -> str:
    key = explicit or os.environ.get(API_KEY_ENV, "") \
        or os.environ.get(API_KEY_ENV_FALLBACK, "")
    if not key:
        raise ValueError(
            f"google-decisions adapter needs a Google API key: set "
            f"the {API_KEY_ENV} environment variable (or pass "
            f"api_key=<redacted>). Create a key in Google AI Studio "
            f"at aistudio.google.com and export "
            f"{API_KEY_ENV}=<your key>. {API_KEY_ENV_FALLBACK} is "
            f"also accepted."
        )
    return key


def _labels(case_input: dict[str, Any]) -> list[str]:
    """Candidate decision labels for this call, in stable sorted order.

    Built from the case input's explicit ``options`` list (B2: the
    adapter-visible context carries no gold labels), plus ``"other"``.
    Shared with the other decision adapters via
    ``peira.adapters._labels``. The canary and the Jev-family
    adapters build labels with the ``"choice"`` primitive name for
    every primitive, and this adapter does the same so the offered
    label sets are identical across wires.
    """
    return candidate_labels(case_input, "choice")


class GoogleDecisionsAdapter:
    """Decision adapter for Google's gemini-decision-1 (Decisions API)."""

    name = "google-decisions"
    supported_primitives = frozenset({"choice", "score", "abstain"})
    # M-2: confidence comes from the API's per-answer probabilities
    # (D-23): a model-output probability, not a verbalization.
    confidence_source = "token-logprob"
    # M-7 longitudinal provenance.
    model_class = "guardrail"

    def __init__(
        self,
        model: str = MODEL_ID,
        api_key: str | None = None,
        timeout_s: float = 120.0,
        transport: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        if model not in SUPPORTED_MODEL_IDS:
            pins = " or ".join(
                repr(m) for m in sorted(SUPPORTED_MODEL_IDS))
            raise ValueError(
                f"google-decisions adapter pins model {pins}; "
                f"got {model!r}. Floating tags and unversioned names "
                "are never allowed; a measurement must name the "
                "exact model."
            )
        self.model = model
        # Per-instance identity follows the chosen pin, so runs seal
        # and cache under the exact model that produced them.
        self.version = model
        self.cache_namespace = f"google-decisions:{model}"
        credential = _require_api_key(api_key)
        self._api_token = credential
        self.api_url = API_URL
        self.timeout_s = timeout_s
        # Injectable transport for tests: fn(payload) -> parsed body.
        self._transport = transport or self._http_transport
        # The key authenticates the request; it never leaves this
        # object except inside the x-goog-api-key header of the API
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
                "x-goog-api-key": self._api_token,
            },
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                status = resp.status
                retry_after = resp.headers.get("Retry-After")
                # errors="replace": a body with invalid UTF-8 is not
                # valid JSON and must reach the non-JSON ProviderError
                # path, not escape as an unclassified UnicodeDecodeError.
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            retry_after = e.headers.get("Retry-After") if e.headers \
                else None
            self._raise_for_status(e.code, retry_after,
                                   _read_error_detail(e))
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            # Lost connection / DNS / refused / timed out: transient.
            # Status 408 puts it on the runner's transient-retry path.
            raise ProviderError(
                f"google-decisions transport error: {e}",
                status_code=408) from e
        latency_ms = (time.perf_counter() - started) * 1000.0
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ProviderError(
                f"google-decisions returned non-JSON response "
                f"(HTTP {status})"
            ) from e
        if not isinstance(parsed, dict):
            raise ProviderError(
                "google-decisions returned a non-object JSON response")
        parsed["_latency_ms"] = latency_ms
        return parsed

    def _raise_for_status(
        self, status: int, retry_after: str | None, detail: str
    ) -> None:
        wait = _parse_retry_after(retry_after)
        msg = f"google-decisions API error {status}" + (
            f": {detail}" if detail else "")
        if status in (401, 403):
            raise ProviderError(
                msg + f"; check that {API_KEY_ENV} is valid and "
                "active, and that the Gemini API is enabled for the "
                "key's project.",
                status_code=status,
            )
        if status == 404:
            raise ProviderError(
                msg + "; the Decisions endpoint or the pinned model "
                "was not found; this is an adapter bug or an API "
                "change, not a retryable failure.",
                status_code=status,
            )
        if status in (400, 422):
            raise ProviderError(
                msg + "; the request was rejected; this is an adapter "
                "bug, not a retryable failure.",
                status_code=status,
            )
        if status in (408, 409, 429, 529) or 500 <= status < 600:
            # Transient: the runner retries with backoff and adapts
            # concurrency. The adapter itself never retries.
            raise ProviderError(msg, status_code=status, retry_after=wait)
        raise ProviderError(msg, status_code=status)

    # -- decide -----------------------------------------------------------

    def decide(
        self, case_input: dict[str, Any], primitive: str, context: CallContext
    ) -> ChoiceOutput | ScoreOutput | AbstainOutput:
        if primitive not in self.supported_primitives:
            raise ValueError(
                f"google-decisions does not support primitive "
                f"{primitive!r}")
        prompt = str(case_input.get("prompt", ""))
        labels = _labels(case_input)

        if primitive == "choice":
            questions = {"decision": _choice_question(labels)}
        elif primitive == "score":
            questions = {
                "score": _score_question(),
                "decision": _choice_question(labels),
            }
        else:  # abstain
            questions = {"abstain": _noul_question()}
        _validate_questions(questions)

        payload = {
            "model": self.model,
            "input": prompt,
            "questions": questions,
        }
        response = self._transport(payload)
        if not isinstance(response, dict):
            raise ProviderError(
                "google-decisions returned a non-object JSON response")
        answers = response.get("answers")
        if not isinstance(answers, dict):
            raise ProviderError(
                "google-decisions response missing 'answers' object")
        # No model echo exists on this wire: the response carries no
        # model field, so there is no served identity to verify and
        # none is fabricated. The transcript records the absence.
        tokens_in, tokens_out = _extract_usage(response)
        call_usage = CallUsage(
            model=self.model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=float(response.get("_latency_ms", 0.0)),
            cost_usd=0.0,  # the runner recomputes from the pricing table
        )
        transcript = {
            "model": self.model,
            "endpoint": self.api_url,
            "echoed_model": response.get("model"),
            "identity_note": (
                "the Gemini Decisions response carries no model "
                "echo; served identity rests on the request alone"),
            "request": {
                "model": self.model,
                "questions": _question_shapes(questions),
            },
            "response": {k: v for k, v in response.items()
                         if not k.startswith("_")},
        }

        if primitive == "choice":
            return self._choice_output(answers, labels, call_usage,
                                       transcript)
        if primitive == "score":
            return self._score_output(answers, labels, call_usage,
                                      transcript)
        return self._noul_output(answers, call_usage, transcript)

    # -- per-primitive mapping --------------------------------------------

    def _choice_output(self, answers, labels, usage, transcript):
        ans = _need_answer(answers, "decision")
        option = str(ans.get("choice", ""))
        if option not in labels:
            raise ProviderError(
                f"google-decisions returned choice {option!r} outside "
                f"the offered labels {labels}; adapter bug or API "
                "drift."
            )
        confidence = _answer_confidence(ans, option)
        return ChoiceOutput(
            decision=option, confidence=confidence,
            usage=usage, transcript=transcript,
        )

    def _score_output(self, answers, labels, usage, transcript):
        ans = _need_answer(answers, "score")
        # The reported score is the probability-weighted rubric
        # position, recomputed from the answer's probabilities (the
        # canary verified the wire ``score`` field equals this value
        # on live answers). The wire field is the fallback for an
        # answer that carries no probabilities.
        value = None
        probs = ans.get("probabilities")
        if isinstance(probs, dict) and probs:
            try:
                value = sum(float(k) * float(v)
                            for k, v in probs.items())
            except (TypeError, ValueError):
                value = None
        if value is None:
            wire_score = ans.get("score")
            if isinstance(wire_score, (int, float)) \
                    and not isinstance(wire_score, bool):
                value = wire_score
        if value is None:
            raise ProviderError(
                f"google-decisions score answer has no numeric "
                f"score: {ans!r}")
        if isinstance(value, int) \
                and not 0 <= value <= len(_SCORE_LEVELS) - 1:
            # A several-hundred-digit JSON integer parses to an int
            # whose float() raises OverflowError, which would escape
            # as an unclassified error. Compared exactly, a huge int
            # is out of range in its own direction, so it clamps to
            # the same extreme a large finite value would.
            score = 1.0 if value > 0 else 0.0
        else:
            score = _clamp01(
                float(value) / (len(_SCORE_LEVELS) - 1), "score")
        # The paired decision question carries the label; the score
        # is the measurement signal. An out-of-vocabulary label is
        # API drift; fail loudly like the choice path does.
        dec_ans = _need_answer(answers, "decision")
        option = str(dec_ans.get("choice", ""))
        if option not in labels:
            raise ProviderError(
                f"google-decisions returned choice {option!r} outside "
                f"the offered labels {labels}; adapter bug or API "
                "drift."
            )
        confidence = _answer_confidence(dec_ans, option)
        return ScoreOutput(
            score=score, decision=option, confidence=confidence,
            usage=usage, transcript=transcript,
        )

    def _noul_output(self, answers, usage, transcript):
        # The answer is keyed by OUR question name ("abstain"); the
        # nested "type": "noul" is the wire field (see _noul_question
        # in peira.adapters.jev).
        #
        # NOTE (abstain decision placeholder): the model only answers
        # "should I abstain?"; it never emits a decision label. When
        # p < 0.5 (no abstention) the `decision` below is the "other"
        # placeholder, NOT a model output and NOT gold. Flip
        # detection uses the `abstained` flag. See the module
        # docstring.
        ans = _need_answer(answers, "abstain")
        # The wire returns the abstain probability under the "noul"
        # key (the 2026-11-16 canary answer carried `noul` only). The
        # Jev wire's documented key is "abstain", so that key is
        # accepted as an alias. If both keys ever arrive with
        # different values, the API has drifted and no preference
        # order can say which one is the probability; fail closed
        # instead of guessing. An explicit null carries no value on
        # the wire; it counts as absent, not as a competing reading.
        carried = [ans[k] for k in ("abstain", "noul")
                   if ans.get(k) is not None]
        if len(carried) == 2 and carried[0] != carried[1]:
            raise ProviderError(
                f"google-decisions abstain answer carries both "
                f"'abstain' ({carried[0]!r}) and 'noul' "
                f"({carried[1]!r}) with different values; refusing a "
                "measurement whose probability is ambiguous.")
        p_yes = carried[0] if carried else None
        if not isinstance(p_yes, (int, float)) \
                or isinstance(p_yes, bool):
            raise ProviderError(
                f"google-decisions abstain answer has no numeric "
                f"abstain value: {ans!r}")
        if not 0.0 <= float(p_yes) <= 1.0:
            # A probability outside [0, 1] (NaN included; its
            # comparisons are all false) is malformed wire data, not
            # a value to clamp into a fabricated extreme.
            raise ProviderError(
                f"google-decisions abstain answer probability out "
                f"of range: {ans!r}")
        p_yes = float(p_yes)
        confidence = _clamp01(abs(2 * p_yes - 1), "confidence")
        if p_yes >= 0.5:
            decision = "abstain"
        else:
            decision = non_abstain_placeholder()
        return AbstainOutput(
            decision=decision, confidence=confidence,
            usage=usage, transcript=transcript,
        )


def _need_answer(answers: dict[str, Any], name: str) -> dict[str, Any]:
    ans = answers.get(name)
    if not isinstance(ans, dict):
        raise ProviderError(
            f"google-decisions response missing answer {name!r}")
    return ans


def _extract_usage(response: dict[str, Any]) -> tuple[int, int]:
    """Usage counters from the response, failing closed.

    The live wire carries ``total_input_tokens`` and
    ``total_output_tokens`` (zero on every call: output is free).
    The other key spellings are the Gemini family's alternates, kept
    in the canary's lookup order so a renamed counter is still found
    and a missing one still fails. Cost accounting fails closed: a
    response without usage counters cannot be priced, and recording
    it as a free call would silently understate the run's spend.
    Counters are strict, never coerced: a counter that is not a
    non-negative integer is malformed wire data.
    """
    usage = response.get("usage")
    if not isinstance(usage, dict):
        raise ProviderError(
            "google-decisions response missing 'usage' object")
    tokens_in = None
    for key in ("input_tokens", "prompt_tokens", "inputTokens",
                "promptTokenCount", "total_input_tokens"):
        if key in usage:
            tokens_in = usage[key]
            break
    tokens_out = None
    for key in ("output_tokens", "outputTokens",
                "candidatesTokenCount", "total_output_tokens"):
        if key in usage:
            tokens_out = usage[key]
            break
    if tokens_out is None:
        tokens_out = 0
    if type(tokens_in) is not int or tokens_in < 0 \
            or type(tokens_out) is not int or tokens_out < 0:
        raise ProviderError(
            f"google-decisions returned malformed usage counters: "
            f"{usage!r}")
    return tokens_in, tokens_out


def _answer_confidence(ans: dict[str, Any], option: str) -> float:
    """The decision answer's confidence, from the wire probability.

    The probabilities map's value for the chosen option is
    authoritative (on live answers the API's ``confidence`` field
    equals it); the ``confidence`` field is the fallback. Both must
    be genuine numbers, never coerced. A missing or malformed
    confidence is malformed wire data and fails closed: confidence
    is a measurement the model reported, never a value the adapter
    invents (there is no midpoint default).
    """
    probs = ans.get("probabilities")
    if isinstance(probs, dict):
        raw = probs.get(option)
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            return _clamp01(raw, "confidence")
    raw = ans.get("confidence")
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return _clamp01(raw, "confidence")
    raise ProviderError(
        f"google-decisions decision answer has no usable "
        f"confidence: {ans!r}")


def _clamp01(value: Any, name: str) -> float:
    # A bool is never a legitimate probability, and a non-finite float
    # (NaN, +/-inf; Python's json accepts all three as literals) must
    # fail closed: clamping NaN would silently fabricate a maximal
    # measurement, since min/max comparisons with NaN are always
    # false.
    if isinstance(value, bool):
        raise ProviderError(
            f"google-decisions returned non-numeric {name}: {value!r}")
    try:
        f = float(value)
    except (TypeError, ValueError):
        raise ProviderError(
            f"google-decisions returned non-numeric {name}: "
            f"{value!r}") from None
    if not math.isfinite(f):
        raise ProviderError(
            f"google-decisions returned non-numeric {name}: {value!r}")
    return max(0.0, min(1.0, f))


def _question_shapes(questions: dict[str, Any]) -> dict[str, Any]:
    """Transcript-safe summary: question names and types, no content."""
    return {k: {"type": v.get("type")} for k, v in questions.items()}


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


def _read_error_detail(e: urllib.error.HTTPError) -> str:
    """Best error detail for the message: the API's error.message.

    Gemini API errors return a JSON body with an ``error`` object;
    read its ``message``. A gateway error can return an HTML page
    instead, so any parse failure falls back to the raw body prefix.
    """
    try:
        raw = e.read().decode("utf-8", errors="replace")
    except OSError:
        return ""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return raw[:500]
    if isinstance(parsed, dict):
        error = parsed.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message:
                return message[:500]
    return raw[:500]
