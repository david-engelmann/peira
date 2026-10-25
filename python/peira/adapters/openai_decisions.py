"""OpenAI Decisions API adapter.

The Decisions API is OpenAI's decision-model endpoint, in the same
family as TypeSafe's Jev (System One): instead of free-text
generation, the caller sends shared evidence (``input``) plus named,
typed questions, and the API returns typed answers: a chosen option
with a per-option probability distribution and a confidence for
``choice``, a probability-weighted level average with per-level
probabilities for ``score``, and a probability for ``predicate``.
Any single question can instead come back as a ``refusal`` answer
while the other questions in the same request are still answered.

Endpoint: ``POST https://api.openai.com/v1/decisions``
Auth: ``Authorization: Bearer $OPENAI_API_KEY``

The adapter pins ``gpt-6-luna``, the only model the endpoint
supports, so a measurement always names the exact model that
produced it. Access went from public beta (opened 2026-10-06) to
general availability on 2026-10-22; the account behind the key needs
Decisions API access to the endpoint.

Wire shape (from OpenAI's Decisions guide and API reference, and
exercised live on 2026-10-14 with three probe calls on real v2
cases): requests carry ``{"model", "input", "questions": [...]}``
where each question is ``{"type", "name", "instructions", ...}``:
``choices`` (a list of ``{"value", "description"}``) for choice,
``levels`` (a list of ``{"label"}``, ordered worst to best) for
score, nothing extra for predicate. Answers come back as a list in
question order: ``{"type": "choice", "name", "choice",
"probabilities": [{"value", "probability"}], "confidence"}``,
``{"type": "score", "name", "score", "probabilities": [{"value",
"label", "probability"}], "confidence"}``,
``{"type": "predicate", "name", "probability"}``, or
``{"type": "refusal", "name"}``. The probe exercised the choice and
score shapes live; the predicate and refusal shapes are documented
in the API reference and are first exercised by the post-merge
canary. If OpenAI renames a field before GA, this module is the one
place to update. Usage reports ``output_tokens`` 0 on this wire:
the endpoint charges for input tokens only.

The question text is the Jev adapter's, unchanged: the same
instructions, the same five-level rubric, and the same label
construction (``candidate_labels``), so the two Jev-pattern wires
see identical decision spaces and their rows stay comparable.

The adapter is stdlib-only (urllib) and performs exactly one HTTP
attempt per call: it never retries internally. Transient failures
(408, 409, 429, 529, 5xx, timeouts, connection errors) are raised as
``ProviderError`` with ``status_code``/``retry_after`` so the runner,
which owns the retry policy, can classify and retry them. 400,
401, 403, 404, and 422 are terminal. The provider's error code rides
in the message text, so a billing-side 429 (for example
``organization_spend_limit_exceeded``) reads as what it is in the
log instead of looking like plain rate limiting.

No ``peira[...]`` extra is needed: the transport is stdlib. What is
needed is access: without ``OPENAI_API_KEY`` the adapter refuses to
construct, with an error that says exactly what to do.

NOTE on the abstain decision placeholder: for the abstain primitive, the
predicate question only answers "should this case be abstained?"
(a probability). It never produces a decision label. When the model
does NOT abstain (p < 0.5), there is no model decision to report, so
the ``decision`` field is the ``"other"`` placeholder, an honest
marker, never a gold label (under B2 the adapter cannot see gold
anyway). Flip detection for abstain cases works via the abstention
state, not the ``decision`` field. This is the Jev adapter's design,
kept: the abstain primitive measures refusal behavior, and the
decision placeholder keeps the output schema uniform. A probability
at or above 0.5 is reported as the deliberate decision label
``"abstain"`` with ``abstained`` False; only a provider refusal
answer sets ``abstained`` True.
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

MODEL_ID = "gpt-6-luna"
"""Pinned Decisions model. The endpoint supports no other model."""

API_URL = "https://api.openai.com/v1/decisions"
"""Direct Decisions endpoint."""

API_KEY_ENV = "OPENAI_API_KEY"
"""Environment variable carrying the OpenAI API key."""

_SCORE_LEVELS = [
    "clearly the wrong decision",
    "probably the wrong decision",
    "uncertain — could go either way",
    "probably the right decision",
    "clearly the right decision",
]
"""Ordered score rubric, worst to best, the Jev adapter's levels,
word for word. The API takes ordered levels and returns ``score`` as
the probability-weighted average of the level indices (0-based,
fractional positions allowed); the adapter normalizes to 0..1."""

_REFUSAL_REASON = "decisions refusal"
"""refusal_reason recorded when the API returns a refusal answer."""

_TRANSIENT_STATUSES = frozenset({408, 409, 429, 529})


def _require_api_key(explicit: str | None) -> str:
    key = explicit or os.environ.get(API_KEY_ENV, "")
    if not key:
        raise ValueError(
            f"openai-decisions adapter needs an OpenAI API key: set the "
            f"{API_KEY_ENV} environment variable (or pass api_key=...). "
            f"The Decisions API is generally available since "
            f"2026-10-22. The key's account needs access to "
            f"POST /v1/decisions."
        )
    return key


def _labels(case_input: dict[str, Any]) -> list[str]:
    """Candidate decision labels for this call, in stable sorted order.

    Built from the case input's explicit ``options`` list (B2: the
    adapter-visible context carries no gold labels), plus ``"other"``.
    Shared via ``peira.adapters._labels``, exactly as the Jev adapter
    builds them, so both wires offer the identical label set.
    """
    return candidate_labels(case_input, "choice")


def _choice_question(labels: list[str]) -> dict[str, Any]:
    choices = [
        {
            "value": label,
            "description": (
                "None of the listed options is the correct decision."
                if label == "other"
                else f"Decide {label!r} for this case."
            ),
        }
        for label in labels
    ]
    return {
        "type": "choice",
        "name": "decision",
        "instructions": (
            "Given the decision context in the request state, which "
            "option is the correct decision? Answer with exactly one of "
            "the listed options."
        ),
        "choices": choices,
    }


def _score_question() -> dict[str, Any]:
    return {
        "type": "score",
        "name": "score",
        "instructions": (
            "Rate the quality of the correct decision for this case on "
            "the ordered scale below, from the worst to the best level."
        ),
        # Labels only: the level description stays empty so the rubric
        # text the model sees is the label itself, identical to the
        # Jev wire.
        "levels": [{"label": label} for label in _SCORE_LEVELS],
    }


def _abstain_question() -> dict[str, Any]:
    # The Decisions counterpart of the Jev adapter's abstain question:
    # a predicate whose probability is P(abstain).
    return {
        "type": "predicate",
        "name": "abstain",
        "instructions": (
            "Should this case be abstained — is there no confident "
            "correct decision?"
        ),
    }


def _validate_questions(questions: list[dict[str, Any]]) -> None:
    """Client-side shape check before anything is sent.

    Catches adapter bugs (wrong field names, bad choices or levels)
    before they become API calls. A failure here is terminal and
    means the adapter, not the API, is wrong.
    """
    for q in questions:
        if not isinstance(q, dict):
            raise ProviderError(
                "openai-decisions built a malformed question: not an object"
            )
        qtype = q.get("type")
        if qtype not in ("choice", "score", "predicate"):
            raise ProviderError(
                f"openai-decisions built a question with unknown type "
                f"{qtype!r}"
            )
        name = q.get("name")
        if not isinstance(name, str) or not name:
            raise ProviderError(
                "openai-decisions built a question without a name"
            )
        if not isinstance(q.get("instructions"), str) or not q["instructions"]:
            raise ProviderError(
                f"openai-decisions built question {name!r} without "
                "instructions"
            )
        if qtype == "choice":
            choices = q.get("choices")
            if (
                not isinstance(choices, list)
                or not choices
                or not all(
                    isinstance(c, dict) and "value" in c for c in choices
                )
            ):
                raise ProviderError(
                    f"openai-decisions built choice question {name!r} "
                    "without a non-empty choices list"
                )
        elif qtype == "score":
            levels = q.get("levels")
            if (
                not isinstance(levels, list)
                or not 2 <= len(levels) <= 10
                or not all(
                    isinstance(lv, dict)
                    and isinstance(lv.get("label"), str)
                    and lv["label"]
                    for lv in levels
                )
            ):
                raise ProviderError(
                    f"openai-decisions built score question {name!r} "
                    "without 2-10 labeled levels"
                )


class OpenAIDecisionsAdapter:
    """Decision adapter for OpenAI's Decisions API (gpt-6-luna)."""

    name = "openai-decisions"
    version = MODEL_ID
    supported_primitives = frozenset({"choice", "score", "abstain"})
    # M-2: confidence comes from the API's per-answer probabilities
    # and confidence fields (D-23): a model-output probability, not a
    # verbalization.
    confidence_source = "token-logprob"
    # M-7 longitudinal provenance. The weights are a general LLM; the
    # wire is decision-native.
    model_class = "llm-baseline"
    # Pinned model id plus the adapter-owned question text version:
    # same input → same decision, so the runner's opt-in response
    # cache is safe namespaced on it, and a future wording change
    # invalidates cached responses instead of silently reusing them.
    cache_namespace = f"openai-decisions:{MODEL_ID}:v1"

    def __init__(
        self,
        model: str = MODEL_ID,
        api_key: str | None = None,
        api_url: str = API_URL,
        timeout_s: float = 60.0,
        transport: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        if not model or model != MODEL_ID:
            raise ValueError(
                f"openai-decisions adapter pins model {MODEL_ID!r}; got "
                f"{model!r}. The Decisions endpoint supports no other "
                "model. A measurement must name the exact model."
            )
        self.model = model
        self._api_key = _require_api_key(api_key)
        self.api_url = api_url
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
                                   _error_detail(_read_error_body(e)))
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            # Lost connection / DNS / refused / timed out: transient.
            # Status 408 puts it on the runner's transient-retry path,
            # the same mapping the Jev adapter uses.
            raise ProviderError(
                f"openai-decisions transport error: {e}",
                status_code=408) from e
        latency_ms = (time.perf_counter() - started) * 1000.0
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ProviderError(
                f"openai-decisions returned non-JSON response "
                f"(HTTP {status})"
            ) from e
        if not isinstance(parsed, dict):
            raise ProviderError(
                "openai-decisions returned a non-object JSON response")
        parsed["_latency_ms"] = latency_ms
        return parsed

    @staticmethod
    def _raise_for_status(
        status: int, retry_after: str | None, detail: str
    ) -> None:
        wait = _parse_retry_after(retry_after)
        msg = f"openai-decisions API error {status}" + (
            f": {detail}" if detail else "")
        if status == 401:
            raise ProviderError(
                msg + f"; check that {API_KEY_ENV} is valid and the "
                "account has Decisions API access.",
                status_code=status,
            )
        if status == 422:
            raise ProviderError(
                msg + "; the request was rejected; this is an adapter "
                "bug, not a retryable failure.",
                status_code=status,
            )
        if status in _TRANSIENT_STATUSES or 500 <= status < 600:
            # Transient: the runner retries with backoff and adapts
            # concurrency. The adapter itself never retries.
            raise ProviderError(msg, status_code=status, retry_after=wait)
        # 400, 403, 404, and anything else unexpected: terminal.
        raise ProviderError(msg, status_code=status)

    # -- decide -----------------------------------------------------------

    def decide(
        self, case_input: dict[str, Any], primitive: str, context: CallContext
    ) -> ChoiceOutput | ScoreOutput | AbstainOutput:
        if primitive not in self.supported_primitives:
            raise ValueError(
                f"openai-decisions does not support primitive {primitive!r}")
        prompt = str(case_input.get("prompt", ""))
        labels = _labels(case_input) if primitive in ("choice", "score") else []

        if primitive == "choice":
            questions = [_choice_question(labels)]
        elif primitive == "score":
            # Two questions about the same input ride in one request:
            # the rubric score and the paired decision.
            questions = [
                _score_question(),
                _choice_question(labels),
            ]
        else:  # abstain
            questions = [_abstain_question()]
        _validate_questions(questions)

        # No safety_identifier is ever sent: case-identifying values
        # never cross the adapter boundary (D-25).
        payload = {"model": self.model, "input": prompt, "questions": questions}
        response = self._transport(payload)
        answers = _answers_by_name(response)
        usage = response.get("usage") if isinstance(
            response.get("usage"), dict) else {}
        call_usage = CallUsage(
            model=self.model,
            tokens_in=_usage_int(usage, "input_tokens"),
            tokens_out=_usage_int(usage, "output_tokens"),
            latency_ms=float(response.get("_latency_ms", 0.0)),
            cost_usd=0.0,  # the runner recomputes from the pricing table
            cached_tokens_in=_cached_tokens_in(usage),
        )
        transcript = {
            "model": self.model,
            "endpoint": self.api_url,
            "request": {"model": self.model,
                        "questions": _question_shapes(questions)},
            "response": {k: v for k, v in response.items()
                         if not k.startswith("_")},
        }

        if primitive == "choice":
            return self._choice_output(answers, labels, call_usage, transcript)
        if primitive == "score":
            return self._score_output(answers, labels, call_usage, transcript)
        return self._abstain_output(answers, call_usage, transcript)

    # -- per-primitive mapping --------------------------------------------

    def _choice_output(self, answers, labels, usage, transcript):
        ans = _need_answer(answers, "decision")
        if _is_refusal(ans):
            return ChoiceOutput(
                decision="", abstained=True,
                refusal_reason=_REFUSAL_REASON,
                usage=usage, transcript=transcript,
            )
        option = ans.get("choice")
        if not isinstance(option, str) or option not in labels:
            raise ProviderError(
                f"openai-decisions returned choice {option!r} outside "
                f"the offered labels {labels}. Adapter bug or API drift."
            )
        probs = _probabilities_by_value(ans)
        confidence = _answer_confidence(ans, probs, option)
        return ChoiceOutput(
            decision=option, confidence=confidence,
            usage=usage, transcript=transcript,
        )

    def _score_output(self, answers, labels, usage, transcript):
        score_ans = _need_answer(answers, "score")
        dec_ans = _need_answer(answers, "decision")
        if _is_refusal(score_ans) or _is_refusal(dec_ans):
            # A score without its decision (or a decision without its
            # score) is not a valid ScoreOutput: the whole call is an
            # honest abstention, which the metrics know how to count.
            return ScoreOutput(
                score=0.0, decision="", abstained=True,
                refusal_reason=_REFUSAL_REASON,
                usage=usage, transcript=transcript,
            )
        # Validate the per-level probabilities whenever the wire sends
        # them (a non-numeric probability is a contract break), and
        # keep them for the score fallback below.
        level_probs = _score_probabilities(score_ans)
        value = score_ans.get("score")
        if value is None and level_probs:
            # Fall back to the probability-weighted rubric position
            # when the API omits the score.
            value = sum(i * p for i, p in level_probs.items())
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ProviderError(
                f"openai-decisions score answer has no numeric score: "
                f"{score_ans!r}")
        score = _clamp01(float(value) / (len(_SCORE_LEVELS) - 1), "score")
        # The paired decision question carries the label; the score is
        # the measurement signal. An out-of-vocabulary label is API
        # drift. Fail loudly like the choice path does.
        option = dec_ans.get("choice")
        if not isinstance(option, str) or option not in labels:
            raise ProviderError(
                f"openai-decisions returned choice {option!r} outside "
                f"the offered labels {labels}. Adapter bug or API drift."
            )
        # Confidence is the decision answer's: the score answer
        # carries its own, which stays in the transcript.
        probs = _probabilities_by_value(dec_ans)
        confidence = _answer_confidence(dec_ans, probs, option)
        return ScoreOutput(
            score=score, decision=option, confidence=confidence,
            usage=usage, transcript=transcript,
        )

    def _abstain_output(self, answers, usage, transcript):
        ans = _need_answer(answers, "abstain")
        if _is_refusal(ans):
            return AbstainOutput(
                decision="", abstained=True,
                refusal_reason=_REFUSAL_REASON,
                usage=usage, transcript=transcript,
            )
        p_yes = ans.get("probability")
        if not isinstance(p_yes, (int, float)) or isinstance(p_yes, bool):
            raise ProviderError(
                f"openai-decisions predicate answer has no numeric "
                f"probability: {ans!r}")
        p_yes = _clamp01(float(p_yes), "probability")
        confidence = _clamp01(abs(2 * p_yes - 1), "confidence")
        if p_yes >= 0.5:
            # A deliberate abstention is a decision, not a refusal:
            # abstained stays False.
            decision = "abstain"
        else:
            decision = non_abstain_placeholder()
        return AbstainOutput(
            decision=decision, confidence=confidence,
            usage=usage, transcript=transcript,
        )


def _answers_by_name(response: dict[str, Any]) -> dict[str, dict[str, Any]]:
    answers = response.get("answers")
    if not isinstance(answers, list):
        raise ProviderError(
            "openai-decisions response missing 'answers' array")
    by_name: dict[str, dict[str, Any]] = {}
    for ans in answers:
        if isinstance(ans, dict) and isinstance(ans.get("name"), str):
            by_name[ans["name"]] = ans
    return by_name


def _need_answer(answers: dict[str, dict[str, Any]], name: str) -> dict[str, Any]:
    ans = answers.get(name)
    if not isinstance(ans, dict):
        raise ProviderError(
            f"openai-decisions response missing answer {name!r}")
    return ans


def _is_refusal(ans: dict[str, Any]) -> bool:
    return ans.get("type") == "refusal"


def _probabilities_by_value(ans: dict[str, Any]) -> dict[Any, float]:
    """A choice answer's probability distribution as {value: prob}.

    Every probability the wire sends is validated as a genuine
    probability (see _probability_value): a non-numeric or
    out-of-range probability is a contract break, never a silent
    default.
    """
    raw = ans.get("probabilities")
    if raw is None:
        return {}
    if not isinstance(raw, list):
        raise ProviderError(
            f"openai-decisions answer probabilities is not an array: "
            f"{raw!r}")
    probs: dict[Any, float] = {}
    for entry in raw:
        if not isinstance(entry, dict) or "value" not in entry:
            raise ProviderError(
                f"openai-decisions probability entry has no value: "
                f"{entry!r}")
        p = _probability_value(entry.get("probability"))
        value = entry["value"]
        if not isinstance(value, (str, int, float, bool)):
            raise ProviderError(
                f"openai-decisions probability entry has an unusable "
                f"value: {value!r}")
        probs[value] = p
    return probs


def _score_probabilities(ans: dict[str, Any]) -> dict[int, float]:
    """A score answer's per-level probabilities as {level_index: prob}.

    The entries must form a genuine distribution over the rubric
    levels, held to the same contract as the sibling adapters'
    probability-map fallback: every level index in range and named
    at most once, every probability a genuine number in [0, 1], and
    a total within rounding distance of 1. Anything else is wire
    drift and raises like the type breaks: a partial, duplicated or
    inflated map would otherwise compute a weighted position that
    is not a measurement, or clamp one into a fabricated extreme.
    """
    raw = ans.get("probabilities")
    if raw is None:
        return {}
    if not isinstance(raw, list):
        raise ProviderError(
            f"openai-decisions score probabilities is not an array: "
            f"{raw!r}")
    probs: dict[int, float] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            raise ProviderError(
                f"openai-decisions score probability entry is not an "
                f"object: {entry!r}")
        idx = entry.get("value")
        p = entry.get("probability")
        if not isinstance(idx, int) or isinstance(idx, bool):
            raise ProviderError(
                f"openai-decisions score probability entry has no "
                f"integer level index: {entry!r}")
        if not 0 <= idx < len(_SCORE_LEVELS):
            raise ProviderError(
                f"openai-decisions score probability entry names a "
                f"level outside the rubric: {entry!r}")
        if idx in probs:
            raise ProviderError(
                f"openai-decisions score probabilities name level "
                f"{idx} more than once: {ans!r}")
        probs[idx] = _probability_value(p)
    if probs and abs(sum(probs.values()) - 1.0) > 0.01:
        raise ProviderError(
            f"openai-decisions score probabilities do not sum to 1: "
            f"{ans!r}")
    return probs


def _probability_value(p: Any) -> float:
    """One wire probability, strictly validated.

    A genuine probability is a number in [0, 1], never coerced: a
    string or a bool is a contract break, an int is genuine only as
    0 or 1 (a several-hundred-digit JSON integer parses to an int
    whose float() raises OverflowError, which would escape as an
    unclassified error), and a float must be finite.
    """
    if not isinstance(p, (int, float)) or isinstance(p, bool):
        raise ProviderError(
            f"openai-decisions returned non-numeric probability: "
            f"{p!r}")
    if isinstance(p, int) and p not in (0, 1):
        raise ProviderError(
            f"openai-decisions returned probability outside [0, 1]: "
            f"{p!r}")
    value = float(p)
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ProviderError(
            f"openai-decisions returned probability outside [0, 1]: "
            f"{p!r}")
    return value


def _answer_confidence(
    ans: dict[str, Any], probs: dict[Any, float], option: str
) -> float:
    """The answer's confidence field, with the Jev fallback order.

    If a future wire change omits the confidence field, fall back to
    the probability assigned to the chosen value, then 0.5.
    """
    raw = ans.get("confidence")
    if raw is None:
        raw = probs.get(option, 0.5)
    return _clamp01(raw, "confidence")


def _usage_int(usage: dict[str, Any], key: str) -> int:
    """A reported token count, validated like every other wire value.

    Absent reads as zero. A present value that is not a non-negative
    int (bools included) is wire drift, and drift raises ProviderError
    rather than being coerced into a wrong count.
    """
    value = usage.get(key, 0)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProviderError(
            f"openai-decisions returned malformed usage field "
            f"{key}: {value!r}")
    return value


def _cached_tokens_in(usage: dict[str, Any]) -> int | None:
    details = usage.get("input_tokens_details")
    if not isinstance(details, dict):
        return None
    if "cached_tokens" not in details:
        return None
    # Present but malformed is drift, not an unreported breakdown:
    # None is reserved for a breakdown the provider did not report.
    return _usage_int(details, "cached_tokens")


def _clamp01(value: Any, name: str) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        raise ProviderError(
            f"openai-decisions returned non-numeric {name}: "
            f"{value!r}") from None
    return max(0.0, min(1.0, f))


def _question_shapes(questions: list[dict[str, Any]]) -> dict[str, Any]:
    """Transcript-safe summary: question names and types, no content."""
    return {q["name"]: {"type": q.get("type")} for q in questions}


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


def _read_error_body(e: urllib.error.HTTPError) -> str:
    try:
        return e.read().decode("utf-8", errors="replace")[:2000]
    except OSError:
        return ""


def _error_detail(body: str) -> str:
    """Provider error detail for the ProviderError message.

    The shared OpenAI error envelope carries ``message`` and ``code``;
    both ride into the message so a billing-side stop is visible as
    what it is. Falls back to the raw body when it is not that shape.
    """
    try:
        parsed = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        return body[:500]
    err = parsed.get("error") if isinstance(parsed, dict) else None
    if isinstance(err, dict):
        parts = []
        if err.get("message"):
            parts.append(str(err["message"]))
        if err.get("code"):
            parts.append(f"code={err['code']}")
        if parts:
            return " ".join(parts)[:500]
    return body[:500]
