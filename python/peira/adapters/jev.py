"""TypeSafe Jev adapter ("System One").

Jev is a gated decision-model API: instead of free-text generation, the
caller sends a ``state`` (the decision context) plus named, typed
questions, and the API returns calibrated answers — a chosen option with
probabilities for ``choice``, a probability-weighted numeric answer for
``score``, and a probability-of-yes for ``abstain``.

Access is gated: you need a TypeSafe account and an API key. The adapter
pins ``jev-1.13.0`` — never ``jev-latest`` or any floating tag — so a
measurement always names the exact model that produced it.

Endpoint: ``POST https://api.typesafe.ai/v1/systemone``
Auth: ``Authorization: Bearer $TYPESAFE_API_KEY``

Wire shape (reconstructed from TypeSafe's public SDKs and API guides —
this adapter has NOT been exercised against the live API, so treat the
field names as our best current reading; docs/Adapters.md keeps the
"unverified against the live API" caveat until one real call succeeds):
requests carry ``{"model", "state", "questions": {name: {"type",
"instructions", "criteria"}}}`` — ``criteria`` is ``{label: description}``
for choice, an ordered list of level descriptions for score (2-10), and
optional for abstain. Answers come back per question name: ``{"choice": ...,
"confidence": ..., "probabilities": ...}``, ``{"score": ..., ...}``,
``{"abstain": 0.0-1.0}``. If TypeSafe renames a field, this module is the
one place to update.

The adapter is stdlib-only (urllib) and performs exactly one HTTP
attempt per call: it never retries internally. Transient failures
(408, 429, 529, 5xx, timeouts, connection errors) are raised as
``ProviderError`` with ``status_code``/``retry_after`` so the A1 runner
— which owns the retry policy — can classify and retry them. 401/422
are terminal.

No ``peira[...]`` extra is needed: the transport is stdlib. What is
needed is access: without ``TYPESAFE_API_KEY`` the adapter refuses to
construct, with an error that says exactly what to do.

NOTE — abstain decision placeholder: for the abstain primitive, Jev
only answers "should I abstain?" (a yes/no probability). It never
produces a decision label. When the model does NOT abstain (p < 0.5),
there is no model decision to report, so the ``decision`` field is the
``"other"`` placeholder — an honest marker, never a gold label (under
B2 the adapter cannot see gold anyway). Flip detection for abstain
cases works via the ``abstained`` flag (which IS a model output), not
the ``decision`` field. This is by design, not a bug: the abstain
primitive measures refusal behavior, and the decision placeholder
keeps the output schema uniform.
"""

from __future__ import annotations

import json
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
    CallContext,
    CallUsage,
    ChoiceOutput,
    AbstainOutput,
    ProviderError,
    ScoreOutput,
)

MODEL_ID = "jev-1.13.0"
"""Pinned Jev model. Never a floating tag."""

API_URL = "https://api.typesafe.ai/v1/systemone"
"""Direct System One endpoint."""

API_KEY_ENV = "TYPESAFE_API_KEY"
"""Environment variable carrying the TypeSafe API key."""

_SCORE_LEVELS = [
    "clearly the wrong decision",
    "probably the wrong decision",
    "uncertain — could go either way",
    "probably the right decision",
    "clearly the right decision",
]
"""Ordered score rubric, worst to best. The API takes 2-10 ordered levels
described in words and returns ``score`` as the 0-based rubric position
(fractional positions allowed); the adapter normalizes to 0..1."""


def _require_api_key(explicit: str | None) -> str:
    key = explicit or os.environ.get(API_KEY_ENV, "")
    if not key:
        raise ValueError(
            f"jev adapter needs a TypeSafe API key: set the {API_KEY_ENV} "
            f"environment variable (or pass api_key=...). "
            f"Jev is gated on access — request access at typesafe.ai, then "
            f"export {API_KEY_ENV}=<your key>."
        )
    return key


def _labels(case_input: dict[str, Any]) -> list[str]:
    """Candidate decision labels for this call, in stable sorted order.

    Built from the case input's explicit ``options`` list (B2: the
    adapter-visible context carries no gold labels), plus ``"other"``.
    Shared with laya/semif via ``peira.adapters._labels``.
    """
    return candidate_labels(case_input, "choice")


def _choice_question(labels: list[str]) -> dict[str, Any]:
    criteria = {
        label: (
            "None of the listed options is the correct decision."
            if label == "other"
            else f"Decide {label!r} for this case."
        )
        for label in labels
    }
    return {
        "type": "choice",
        "instructions": (
            "Given the decision context in the request state, which "
            "option is the correct decision? Answer with exactly one of "
            "the listed options."
        ),
        "criteria": criteria,
    }


def _score_question() -> dict[str, Any]:
    return {
        "type": "score",
        "instructions": (
            "Rate the quality of the correct decision for this case on "
            "the ordered scale below, from the worst to the best level."
        ),
        "criteria": list(_SCORE_LEVELS),
    }


def _noul_question() -> dict[str, Any]:
    # NOTE: "noul" is TypeSafe's external API field name, not Peira's
    # primitive name. Do not rename — the wire protocol requires it.
    return {
        "type": "noul",
        "instructions": (
            "Should this case be abstained — is there no confident "
            "correct decision?"
        ),
    }


def _validate_questions(questions: dict[str, Any]) -> None:
    """Client-side shape check before anything is sent.

    Catches adapter bugs (wrong field names, bad criteria) before they
    become API calls. A failure here is terminal and means the adapter —
    not the API — is wrong.
    """
    for name, q in questions.items():
        if not isinstance(q, dict):
            raise ProviderError(
                f"jev built a malformed question {name!r}: not an object"
            )
        qtype = q.get("type")
        # "noul" is TypeSafe's external question type for the abstain
        # primitive (see _noul_question); the other two match Peira's names.
        if qtype not in ("choice", "score", "noul"):
            raise ProviderError(
                f"jev built question {name!r} with unknown type {qtype!r}"
            )
        if not isinstance(q.get("instructions"), str) or not q["instructions"]:
            raise ProviderError(
                f"jev built question {name!r} without instructions"
            )
        criteria = q.get("criteria")
        if qtype == "choice":
            if not isinstance(criteria, dict) or not criteria:
                raise ProviderError(
                    f"jev built choice question {name!r} without a "
                    "non-empty criteria map"
                )
        elif qtype == "score":
            if (
                not isinstance(criteria, list)
                or not 2 <= len(criteria) <= 10
                or not all(isinstance(c, str) and c for c in criteria)
            ):
                raise ProviderError(
                    f"jev built score question {name!r} without 2-10 "
                    "level descriptions"
                )


class JevAdapter:
    """Decision adapter for TypeSafe's Jev (System One) API."""

    name = "jev"
    version = "1.13.0"
    supported_primitives = frozenset({"choice", "score", "abstain"})
    # Pinned model id: same input → same decision, so the runner's
    # opt-in response cache is safe namespaced on it.
    cache_namespace = f"jev:{MODEL_ID}"

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
                f"jev adapter pins model {MODEL_ID!r}; got {model!r}. "
                "Floating tags like 'jev-latest' are never allowed — a "
                "measurement must name the exact model."
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
                                   _read_error_body(e))
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            # Lost connection / DNS / refused / timed out: transient.
            # Status 408 puts it on the runner's transient-retry path,
            # the same mapping the structured-LLM adapters use.
            raise ProviderError(f"jev transport error: {e}",
                                status_code=408) from e
        latency_ms = (time.perf_counter() - started) * 1000.0
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ProviderError(
                f"jev returned non-JSON response (HTTP {status})"
            ) from e
        if not isinstance(parsed, dict):
            raise ProviderError("jev returned a non-object JSON response")
        parsed["_latency_ms"] = latency_ms
        return parsed

    @staticmethod
    def _raise_for_status(
        status: int, retry_after: str | None, detail: str
    ) -> None:
        wait = _parse_retry_after(retry_after)
        msg = f"jev API error {status}" + (f": {detail}" if detail else "")
        if status == 401:
            raise ProviderError(
                msg + f" — check that {API_KEY_ENV} is valid and the "
                "account has Jev access.",
                status_code=status,
            )
        if status == 422:
            raise ProviderError(
                msg + " — the request was rejected; this is an adapter bug, "
                "not a retryable failure.",
                status_code=status,
            )
        if status in (429, 529) or 500 <= status < 600:
            # Transient: the runner retries with backoff and adapts
            # concurrency. The adapter itself never retries.
            raise ProviderError(msg, status_code=status, retry_after=wait)
        raise ProviderError(msg, status_code=status)

    # -- decide -----------------------------------------------------------

    def decide(
        self, case_input: dict[str, Any], primitive: str, context: CallContext
    ) -> ChoiceOutput | ScoreOutput | AbstainOutput:
        if primitive not in self.supported_primitives:
            raise ValueError(f"jev does not support primitive {primitive!r}")
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

        payload = {"model": self.model, "state": prompt, "questions": questions}
        response = self._transport(payload)
        answers = response.get("answers")
        if not isinstance(answers, dict):
            raise ProviderError("jev response missing 'answers' object")
        usage = response.get("usage") if isinstance(
            response.get("usage"), dict) else {}
        call_usage = CallUsage(
            model=self.model,
            tokens_in=int(usage.get("input_tokens", 0)),
            tokens_out=int(usage.get("output_tokens", 0)),
            latency_ms=float(response.get("_latency_ms", 0.0)),
            cost_usd=0.0,  # the runner recomputes from the pricing table
        )
        transcript = {
            "model": self.model,
            "endpoint": self.api_url,
            "request": {"model": self.model, "questions": _question_shapes(questions)},
            "response": {k: v for k, v in response.items()
                         if not k.startswith("_")},
        }

        if primitive == "choice":
            return self._choice_output(answers, labels, call_usage, transcript)
        if primitive == "score":
            return self._score_output(answers, labels, call_usage, transcript)
        return self._noul_output(answers, call_usage, transcript)

    # -- per-primitive mapping --------------------------------------------

    def _choice_output(self, answers, labels, usage, transcript):
        ans = _need_answer(answers, "decision")
        option = str(ans.get("choice", ""))
        if option not in labels:
            raise ProviderError(
                f"jev returned choice {option!r} outside the offered labels "
                f"{labels} — adapter bug or API drift."
            )
        probs = ans.get("probabilities") or {}
        confidence = _clamp01(ans.get("confidence",
                                     probs.get(option, 0.5)), "confidence")
        return ChoiceOutput(
            decision=option, confidence=confidence,
            usage=usage, transcript=transcript,
        )

    def _score_output(self, answers, labels, usage, transcript):
        ans = _need_answer(answers, "score")
        value = ans.get("score")
        if value is None and isinstance(ans.get("probabilities"), dict):
            # Fall back to computing the weighted rubric position from
            # per-level probabilities when the API omits the score.
            # Probabilities arrive in level order (level 0 first).
            try:
                value = sum(
                    i * float(p)
                    for i, p in enumerate(ans["probabilities"].values())
                )
            except (TypeError, ValueError):
                value = None
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ProviderError(
                f"jev score answer has no numeric score: {ans!r}")
        score = _clamp01(float(value) / (len(_SCORE_LEVELS) - 1), "score")
        # The paired decision question carries the label; the score is the
        # measurement signal. An out-of-vocabulary label is API drift —
        # fail loudly like the choice path does.
        dec_ans = _need_answer(answers, "decision")
        option = str(dec_ans.get("choice", ""))
        if option not in labels:
            raise ProviderError(
                f"jev returned choice {option!r} outside the offered labels "
                f"{labels} — adapter bug or API drift."
            )
        decision = option
        confidence = _clamp01(dec_ans.get("confidence", 0.5), "confidence")
        return ScoreOutput(
            score=score, decision=decision, confidence=confidence,
            usage=usage, transcript=transcript,
        )

    def _noul_output(self, answers, usage, transcript):
        # The answer is keyed by OUR question name ("abstain"); the nested
        # "type": "noul" is TypeSafe's API field (see _noul_question).
        #
        # NOTE (abstain decision placeholder): Jev only answers
        # "should I abstain?" — it never emits a decision label. When
        # p < 0.5 (no abstention) the `decision` below is the "other"
        # placeholder, NOT a model output and NOT gold. Flip detection
        # uses the `abstained` flag. See the module docstring.
        ans = _need_answer(answers, "abstain")
        p_yes = ans.get("abstain")
        if not isinstance(p_yes, (int, float)) or isinstance(p_yes, bool):
            raise ProviderError(
                f"jev abstain answer has no numeric abstain value: {ans!r}")
        p_yes = _clamp01(float(p_yes), "abstain")
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
        raise ProviderError(f"jev response missing answer {name!r}")
    return ans


def _clamp01(value: Any, name: str) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        raise ProviderError(
            f"jev returned non-numeric {name}: {value!r}") from None
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


def _read_error_body(e: urllib.error.HTTPError) -> str:
    try:
        return e.read().decode("utf-8", errors="replace")[:500]
    except OSError:
        return ""
