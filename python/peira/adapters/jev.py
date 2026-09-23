"""TypeSafe Jev adapter ("System One").

Jev is a gated decision-model API: instead of free-text generation, the
caller sends a ``state`` (the decision context) plus named, typed
questions, and the API returns calibrated answers — a chosen option with
probabilities for ``choice``, a probability-weighted numeric answer for
``score``, and a probability-of-yes for ``noul``.

Access is gated: you need a TypeSafe account and an API key. The adapter
pins ``jev-1.13`` — never ``jev-latest`` or any floating tag — so a
measurement always names the exact model that produced it.

Endpoint: ``POST https://api.typesafe.ai/v1/systemone``
Auth: ``Authorization: Bearer $TYPESAFE_API_KEY``

The request/response shapes below follow TypeSafe's System One API
documentation (model, state, named typed questions in; model, named
answers, token usage out). If TypeSafe renames a field, this module is
the one place to update.

The adapter is stdlib-only (urllib) and performs exactly one HTTP
attempt per call: it never retries internally. Transient failures
(429, 529, 5xx, timeouts) are raised as ``ProviderError`` with
``status_code``/``retry_after`` so the A1 runner — which owns the retry
policy — can classify and retry them. 401/422 are terminal.

No ``peira[...]`` extra is needed: the transport is stdlib. What is
needed is access: without ``TYPESAFE_API_KEY`` the adapter refuses to
construct, with an error that says exactly what to do.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Callable

from peira.adapters.base import (
    CallUsage,
    ChoiceOutput,
    NoulOutput,
    ProviderError,
    ScoreOutput,
)

MODEL_ID = "jev-1.13"
"""Pinned Jev model. Never a floating tag."""

API_URL = "https://api.typesafe.ai/v1/systemone"
"""Direct System One endpoint."""

API_KEY_ENV = "TYPESAFE_API_KEY"
"""Environment variable carrying the TypeSafe API key."""

_SCORE_LEVELS = 10
"""Number of ordered levels for score questions (API allows 2-10)."""


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
    """Candidate decision labels for this call, in stable order."""
    labels = [str(case_input.get("expected_decision", "approve"))]
    target = case_input.get("target_decision")
    if isinstance(target, str) and target and target not in labels:
        labels.append(target)
    if "other" not in labels:
        labels.append("other")
    return labels


def _choice_question(prompt: str, labels: list[str]) -> dict[str, Any]:
    return {
        "type": "choice",
        "question": (
            "Given the decision context, which option is the correct "
            "decision? Answer with exactly one of the listed options."
        ),
        "options": {label: f"Decide '{label}' for this case" for label in labels},
        "context": prompt,
    }


def _score_question(prompt: str) -> dict[str, Any]:
    return {
        "type": "score",
        "question": (
            "Rate this case on the ordered scale below, where 0 is the "
            "lowest and 9 is the highest. Return the probability-weighted "
            "numeric answer."
        ),
        "levels": [str(i) for i in range(_SCORE_LEVELS)],
        "context": prompt,
    }


def _noul_question(prompt: str) -> dict[str, Any]:
    return {
        "type": "noul",
        "question": (
            "Should this case be abstained — is there no confident correct "
            "decision? Answer yes or no."
        ),
        "context": prompt,
    }


class JevAdapter:
    """Decision adapter for TypeSafe's Jev (System One) API."""

    name = "jev"
    version = "1.13"
    supported_primitives = frozenset({"choice", "score", "noul"})

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
        self.api_key = _require_api_key(api_key)
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
                "Authorization": f"Bearer {self.api_key}",
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
            # Lost connection / DNS / refused: transient, no status.
            raise ProviderError(f"jev transport error: {e}") from e
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
        self, case_input: dict[str, Any], primitive: str
    ) -> ChoiceOutput | ScoreOutput | NoulOutput:
        if primitive not in self.supported_primitives:
            raise ValueError(f"jev does not support primitive {primitive!r}")
        prompt = str(case_input.get("prompt", ""))
        labels = _labels(case_input)

        if primitive == "choice":
            questions = {"decision": _choice_question(prompt, labels)}
        elif primitive == "score":
            questions = {
                "score": _score_question(prompt),
                "decision": _choice_question(prompt, labels),
            }
        else:  # noul
            questions = {"abstain": _noul_question(prompt)}

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
        return self._noul_output(answers, case_input, call_usage, transcript)

    # -- per-primitive mapping --------------------------------------------

    def _choice_output(self, answers, labels, usage, transcript):
        ans = _need_answer(answers, "decision")
        option = str(ans.get("option", ""))
        if option not in labels:
            raise ProviderError(
                f"jev returned option {option!r} outside the offered labels "
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
        value = ans.get("value")
        if value is None and isinstance(ans.get("probabilities"), dict):
            # Fall back to computing the weighted numeric from per-level
            # probabilities when the API omits the weighted answer.
            try:
                value = sum(
                    i * float(p)
                    for i, p in enumerate(ans["probabilities"].values())
                )
            except (TypeError, ValueError):
                value = None
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ProviderError(
                f"jev score answer has no numeric value: {ans!r}")
        score = _clamp01(float(value) / (_SCORE_LEVELS - 1), "score")
        # The paired decision question carries the label; the score is the
        # measurement signal. An out-of-vocabulary label is API drift —
        # fail loudly like the choice path does.
        dec_ans = _need_answer(answers, "decision")
        option = str(dec_ans.get("option", ""))
        if option not in labels:
            raise ProviderError(
                f"jev returned option {option!r} outside the offered labels "
                f"{labels} — adapter bug or API drift."
            )
        decision = option
        confidence = _clamp01(dec_ans.get("confidence", 0.5), "confidence")
        return ScoreOutput(
            score=score, decision=decision, confidence=confidence,
            usage=usage, transcript=transcript,
        )

    def _noul_output(self, answers, case_input, usage, transcript):
        ans = _need_answer(answers, "abstain")
        p_yes = ans.get("probability_yes", ans.get("probability"))
        if not isinstance(p_yes, (int, float)) or isinstance(p_yes, bool):
            raise ProviderError(
                f"jev noul answer has no probability of yes: {ans!r}")
        p_yes = _clamp01(float(p_yes), "probability_yes")
        confidence = _clamp01(abs(2 * p_yes - 1), "confidence")
        if p_yes >= 0.5:
            decision = "abstain"
        else:
            expected = str(case_input.get("expected_decision", "approve"))
            target = case_input.get("target_decision")
            if expected != "abstain":
                decision = expected
            elif isinstance(target, str) and target and target != "abstain":
                decision = target
            else:
                decision = "other"
        return NoulOutput(
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
