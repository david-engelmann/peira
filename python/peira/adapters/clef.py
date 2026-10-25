"""Cloudflare Clef adapter (Workers AI decision models).

Clef is Cloudflare's decision-model family on Workers AI, launched
2026-10-01 as a drop-in compatible implementation of the System One
API shape: the caller sends a ``state`` (the decision context) plus
named, typed questions, and the API returns calibrated answers; a
chosen option with probabilities for ``choice``, a
probability-weighted numeric answer for ``score``, and a
probability-of-yes for ``abstain`` (the wire type is ``noul``, as on
the Jev wire). Cloudflare positions Clef head-to-head against
TypeSafe's Jev, so peira measures it on the same wire shape with the
same question text the Jev adapter sends.

Three pinned models are supported, each named by its full Workers AI
id so a measurement always names the exact model that produced it:

- ``@cf/cloudflare/clef-flash`` (9B, the default): $0.038 per 1M
  input tokens, output free, 24,576-token hosted context.
- ``@cf/cloudflare/clef`` (27B): $0.24 per 1M input tokens, output
  free, 65,536-token hosted context.
- ``@cf/cloudflare/clef-omni`` (30B-A3B MoE, multimodal): $0.15 per
  1M input tokens, output free, 64,000-token hosted context. Peira's
  v2 cases are text, so omni is exercised on its text path only.

Endpoint: ``POST
https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{model}``
Auth: ``Authorization: Bearer <API token>``; the token needs the
Workers AI scope on the account. The request body carries the short
model name (``clef-flash``, ``clef``, ``clef-omni``) in its ``model``
field, per Cloudflare's documented REST examples. Responses are the
standard Workers AI envelope: ``{"result": {"answers": {...},
"usage": {...}}, "success": true, "errors": [], "messages": []}``.
A ``success: false`` envelope is a terminal adapter error.

Access state: an owner probe on 2026-10-15 with the account's
existing Cloudflare token received HTTP 401 (error code 10000,
"Authentication error") from the run endpoint and HTTP 403 from the
model search endpoint, while the same token verified active and
listed zones; the token carries no Workers AI scope. The wire shape
below is therefore reconstructed from Cloudflare's official Clef
documentation and has NOT yet been exercised against the live API;
docs/Adapters.md keeps that caveat until one real call succeeds.
When a Workers AI scoped token is provisioned, a canary call is the
first live exercise.

The adapter is stdlib-only (urllib) and performs exactly one HTTP
attempt per call: it never retries internally. Transient failures
(408, 409, 429, 529, 5xx, timeouts, connection errors) are raised as
``ProviderError`` with ``status_code``/``retry_after`` so the runner,
which owns the retry policy, can classify and retry them. 401/403,
404 and 400/422 are terminal.

No ``peira[...]`` extra is needed: the transport is stdlib. What is
needed is access: without ``CLOUDFLARE_ACCOUNT_ID`` and
``CLOUDFLARE_API_TOKEN`` the adapter refuses to construct, with an
error that says exactly what to do.

NOTE, abstain decision placeholder: for the abstain primitive, Clef
only answers "should I abstain?" (a yes/no probability). It never
produces a decision label. When the model does NOT abstain
(p < 0.5), there is no model decision to report, so the ``decision``
field is the ``"other"`` placeholder; an honest marker, never a gold
label (under B2 the adapter cannot see gold anyway). Flip detection
for abstain cases works via the ``abstained`` flag (which IS a model
output), not the ``decision`` field. This is by design, not a bug,
and matches the Jev adapter exactly.
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
    CallContext,
    CallUsage,
    ChoiceOutput,
    AbstainOutput,
    ProviderError,
    ScoreOutput,
)

SUPPORTED_MODELS = {
    "@cf/cloudflare/clef-flash": "clef-flash",
    "@cf/cloudflare/clef": "clef",
    "@cf/cloudflare/clef-omni": "clef-omni",
}
"""Pinned Workers AI model ids mapped to the short model name the
request body carries. Ids outside this table are rejected at
construction; a measurement must name the exact model."""

MODEL_ID = "@cf/cloudflare/clef-flash"
"""Default pinned Clef model. Never a floating tag."""

ACCOUNT_ENV = "CLOUDFLARE_ACCOUNT_ID"
TOKEN_ENV = "CLOUDFLARE_API_TOKEN"
"""Environment variables carrying the Cloudflare credentials."""

# The question text below is the Jev adapter's, unchanged, so the two
# wires see identical decision spaces. It is measurement-instrument
# text: a copy or formatting lane must not alter it.
_SCORE_LEVELS = [
    "clearly the wrong decision",
    "probably the wrong decision",
    "uncertain — could go either way",
    "probably the right decision",
    "clearly the right decision",
]
"""Ordered score rubric, worst to best. The API takes 2-10 ordered
levels described in words and returns ``score`` as the 0-based rubric
position (fractional positions allowed); the adapter normalizes to
0..1."""

# The only spellings a score probability key may carry: the canonical
# decimal form of each rubric level index. A key is admitted only
# by matching this set. It is never parsed to decide whether it
# names a level, so spellings like "01", "+1" or " 2" are wire
# drift and void the score fallback outright.
_SCORE_LEVEL_KEYS = frozenset(
    str(level) for level in range(len(_SCORE_LEVELS)))


def _require_account_id(explicit: str | None) -> str:
    value = explicit or os.environ.get(ACCOUNT_ENV, "")
    if not value:
        raise ValueError(
            f"clef adapter needs a Cloudflare account ID: set the "
            f"{ACCOUNT_ENV} environment variable (or pass "
            f"account_id=...). The account ID is on the Workers AI "
            f"overview page of the Cloudflare dashboard."
        )
    return value


def _require_api_token(explicit: str | None) -> str:
    value = explicit or os.environ.get(TOKEN_ENV, "")
    if not value:
        raise ValueError(
            f"clef adapter needs a Cloudflare API token with Workers "
            f"AI scope: set the {TOKEN_ENV} environment variable (or "
            f"pass api_token=...)."
        )
    return value


def _labels(case_input: dict[str, Any]) -> list[str]:
    """Candidate decision labels for this call, in stable sorted order.

    Built from the case input's explicit ``options`` list (B2: the
    adapter-visible context carries no gold labels), plus ``"other"``.
    Shared with jev/laya/semif via ``peira.adapters._labels``.
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
    # NOTE: "noul" is the System One wire field name for the abstain
    # primitive, not Peira's primitive name. Do not rename; the wire
    # protocol requires it.
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
    become API calls. A failure here is terminal and means the
    adapter, not the API, is wrong.
    """
    for name, q in questions.items():
        if not isinstance(q, dict):
            raise ProviderError(
                f"clef built a malformed question {name!r}: not an object"
            )
        qtype = q.get("type")
        # "noul" is the wire question type for the abstain primitive
        # (see _noul_question); the other two match Peira's names.
        if qtype not in ("choice", "score", "noul"):
            raise ProviderError(
                f"clef built question {name!r} with unknown type {qtype!r}"
            )
        if not isinstance(q.get("instructions"), str) or not q["instructions"]:
            raise ProviderError(
                f"clef built question {name!r} without instructions"
            )
        criteria = q.get("criteria")
        if qtype == "choice":
            if not isinstance(criteria, dict) or not criteria:
                raise ProviderError(
                    f"clef built choice question {name!r} without a "
                    "non-empty criteria map"
                )
        elif qtype == "score":
            if (
                not isinstance(criteria, list)
                or not 2 <= len(criteria) <= 10
                or not all(isinstance(c, str) and c for c in criteria)
            ):
                raise ProviderError(
                    f"clef built score question {name!r} without 2-10 "
                    "level descriptions"
                )


def _api_url(account_id: str, model: str) -> str:
    return (f"https://api.cloudflare.com/client/v4/accounts/{account_id}"
            f"/ai/run/{model}")


class ClefAdapter:
    """Decision adapter for Cloudflare's Clef models on Workers AI."""

    name = "clef"
    supported_primitives = frozenset({"choice", "score", "abstain"})
    # M-2: confidence comes from the API's per-answer probabilities
    # (D-23): a model-output probability, not a verbalization.
    confidence_source = "token-logprob"
    # M-7 longitudinal provenance.
    model_class = "guardrail"

    def __init__(
        self,
        model: str = MODEL_ID,
        account_id: str | None = None,
        api_token: str | None = None,
        timeout_s: float = 60.0,
        transport: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        if model not in SUPPORTED_MODELS:
            raise ValueError(
                "clef adapter pins model '@cf/cloudflare/clef-flash', "
                "'@cf/cloudflare/clef' or '@cf/cloudflare/clef-omni'; "
                f"got {model!r}. Short names and floating tags are "
                "never allowed; a measurement must name the exact "
                "model."
            )
        self.model = model
        # Per-instance identity follows the chosen pin, so runs of
        # different Clef sizes seal and cache apart.
        self.version = model
        self.cache_namespace = f"clef:{model}"
        self._account_id = _require_account_id(account_id)
        self._api_token = _require_api_token(api_token)
        self.api_url = _api_url(self._account_id, model)
        self.timeout_s = timeout_s
        # Injectable transport for tests: fn(payload) -> parsed envelope.
        self._transport = transport or self._http_transport
        # The token authenticates the request; it never leaves this
        # object except inside the Authorization header of the API
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
                "Authorization": f"Bearer {self._api_token}",
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
            # Status 408 puts it on the runner's transient-retry path.
            raise ProviderError(f"clef transport error: {e}",
                                status_code=408) from e
        latency_ms = (time.perf_counter() - started) * 1000.0
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ProviderError(
                f"clef returned non-JSON response (HTTP {status})"
            ) from e
        if not isinstance(parsed, dict):
            raise ProviderError("clef returned a non-object JSON response")
        parsed["_latency_ms"] = latency_ms
        return parsed

    def _raise_for_status(
        self, status: int, retry_after: str | None, detail: str
    ) -> None:
        wait = _parse_retry_after(retry_after)
        msg = f"clef API error {status}" + (f": {detail}" if detail else "")
        if status in (401, 403):
            raise ProviderError(
                msg + f"; check that {TOKEN_ENV} is valid and has the "
                "Workers AI scope for this account.",
                status_code=status,
            )
        if status == 404:
            raise ProviderError(
                msg + f"; check that {ACCOUNT_ENV} is correct and the "
                f"model {self.model} is available on Workers AI.",
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
            # concurrency. The adapter itself never retries. 409 is
            # in the runner's transient set, so the server's
            # Retry-After must reach it like every other transient's.
            raise ProviderError(msg, status_code=status, retry_after=wait)
        raise ProviderError(msg, status_code=status)

    # -- decide -----------------------------------------------------------

    def decide(
        self, case_input: dict[str, Any], primitive: str, context: CallContext
    ) -> ChoiceOutput | ScoreOutput | AbstainOutput:
        if primitive not in self.supported_primitives:
            raise ValueError(f"clef does not support primitive {primitive!r}")
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
            "model": SUPPORTED_MODELS[self.model],
            "state": prompt,
            "questions": questions,
        }
        response = self._transport(payload)
        result = _unwrap_result(response)
        answers = result.get("answers")
        if not isinstance(answers, dict):
            raise ProviderError("clef response missing 'answers' object")
        usage = result.get("usage") if isinstance(
            result.get("usage"), dict) else {}
        # Strict, never coerced: int() would silently accept bools,
        # truncate floats, parse strings and pass negatives through
        # to a negative cost. A counter that is not a non-negative
        # integer is malformed wire data and fails closed.
        tokens_in = usage.get("input_tokens", 0)
        tokens_out = usage.get("output_tokens", 0)
        if not all(type(v) is int and v >= 0
                   for v in (tokens_in, tokens_out)):
            raise ProviderError(
                f"clef returned malformed usage counters: {usage!r}")
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
            "request": {
                "model": SUPPORTED_MODELS[self.model],
                "questions": _question_shapes(questions),
            },
            "response": {k: v for k, v in result.items()
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
                f"clef returned choice {option!r} outside the offered "
                f"labels {labels}; adapter bug or API drift."
            )
        probs = ans.get("probabilities") or {}
        if not isinstance(probs, dict):
            raise ProviderError(
                f"clef returned probabilities that are not an object: "
                f"{probs!r}")
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
            # The map's keys are the level indices; use them, never
            # the map's iteration order, which the wire does not
            # guarantee. The fallback accepts only a genuine
            # distribution (see _score_from_probabilities). Anything
            # else voids it and the answer fails closed below.
            value = _score_from_probabilities(ans["probabilities"])
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ProviderError(
                f"clef score answer has no numeric score: {ans!r}")
        if isinstance(value, int) and not 0 <= value <= len(_SCORE_LEVELS) - 1:
            # A several-hundred-digit JSON integer parses to an int
            # whose float() raises OverflowError, which would escape
            # as an unclassified error. Compared exactly, a huge int
            # is out of range in its own direction, so it clamps to
            # the same extreme a large finite value would.
            score = 1.0 if value > 0 else 0.0
        else:
            score = _clamp01(
                float(value) / (len(_SCORE_LEVELS) - 1), "score")
        # The paired decision question carries the label; the score is
        # the measurement signal. An out-of-vocabulary label is API
        # drift; fail loudly like the choice path does.
        dec_ans = _need_answer(answers, "decision")
        option = str(dec_ans.get("choice", ""))
        if option not in labels:
            raise ProviderError(
                f"clef returned choice {option!r} outside the offered "
                f"labels {labels}; adapter bug or API drift."
            )
        decision = option
        confidence = _clamp01(dec_ans.get("confidence", 0.5), "confidence")
        return ScoreOutput(
            score=score, decision=decision, confidence=confidence,
            usage=usage, transcript=transcript,
        )

    def _noul_output(self, answers, usage, transcript):
        # The answer is keyed by OUR question name ("abstain"); the
        # nested "type": "noul" is the wire field (see _noul_question).
        #
        # NOTE (abstain decision placeholder): Clef only answers
        # "should I abstain?"; it never emits a decision label. When
        # p < 0.5 (no abstention) the `decision` below is the "other"
        # placeholder, NOT a model output and NOT gold. Flip detection
        # uses the `abstained` flag. See the module docstring.
        ans = _need_answer(answers, "abstain")
        # The wire returns the abstain probability under its own field
        # name, {'type': 'noul', 'noul': 0.73}. Prefer the documented
        # key and fall back to the API's native field, as on the Jev
        # wire where this shape was observed live on 2026-10-07.
        p_yes = ans.get("abstain", ans.get("noul"))
        if not isinstance(p_yes, (int, float)) or isinstance(p_yes, bool):
            raise ProviderError(
                f"clef abstain answer has no numeric abstain value: {ans!r}")
        p_yes = _clamp01(p_yes, "abstain")
        confidence = _clamp01(abs(2 * p_yes - 1), "confidence")
        if p_yes >= 0.5:
            decision = "abstain"
        else:
            decision = non_abstain_placeholder()
        return AbstainOutput(
            decision=decision, confidence=confidence,
            usage=usage, transcript=transcript,
        )


def _unwrap_result(response: dict[str, Any]) -> dict[str, Any]:
    """Unwrap the Workers AI envelope to the model's result object.

    ``success: false`` is terminal: the API rejected the call and
    retrying the same call is pointless. A missing or non-object
    result is a malformed response, never a silent empty answer set.
    """
    if response.get("success") is False:
        raise ProviderError(
            f"clef returned success=false: {response.get('errors')}")
    result = response.get("result")
    if not isinstance(result, dict):
        raise ProviderError("clef response missing 'result' object")
    return result


def _need_answer(answers: dict[str, Any], name: str) -> dict[str, Any]:
    ans = answers.get(name)
    if not isinstance(ans, dict):
        raise ProviderError(f"clef response missing answer {name!r}")
    return ans


def _score_from_probabilities(probs: dict[str, Any]) -> float | None:
    """Weighted rubric position from a per-level probability map.

    The fallback for a score answer whose ``score`` field is absent.
    The map must be a genuine distribution over the rubric levels:
    non-empty, keys exactly the canonical level spellings "0".."4"
    (a key is admitted by matching, never by parsing, so "01",
    "+1" or " 2" is drift, not a level, and two spellings of one
    level cannot double-count
    it), values genuine numbers in [0, 1] (never coerced, so a
    string or a bool voids the fallback), and a total within
    rounding distance of 1. Anything else returns None, which the
    caller turns into a terminal error rather than a fabricated
    score.
    """
    if not probs:
        return None
    total = 0.0
    weighted = 0.0
    # With keys matched canonically the duplicate check below
    # cannot fire today. It pins the one-entry-per-level rule in
    # the code itself, so loosening key matching later cannot
    # silently reintroduce double-counting.
    seen: set[int] = set()
    for key, prob in probs.items():
        if isinstance(prob, bool) or not isinstance(prob, (int, float)):
            return None
        if isinstance(prob, int) and prob not in (0, 1):
            # An int probability is genuine only as 0 or 1. A
            # several-hundred-digit JSON integer parses to an int
            # whose float() raises OverflowError, which would escape
            # the fallback instead of voiding it.
            return None
        value = float(prob)
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            return None
        if key not in _SCORE_LEVEL_KEYS:
            return None
        level = int(key)
        if level in seen:
            return None
        seen.add(level)
        total += value
        weighted += level * value
    if abs(total - 1.0) > 0.01:
        return None
    return weighted


def _clamp01(value: Any, name: str) -> float:
    # A bool is never a legitimate probability, and a non-finite float
    # (NaN, +/-inf; Python's json accepts all three as literals) must
    # fail closed: clamping NaN would silently fabricate a maximal
    # measurement, since min/max comparisons with NaN are always
    # false.
    if isinstance(value, bool):
        raise ProviderError(
            f"clef returned non-numeric {name}: {value!r}")
    if isinstance(value, int) and not isinstance(value, bool):
        # A several-hundred-digit JSON integer parses to an int
        # whose float() raises OverflowError, which the conversion
        # below does not catch. Compared exactly, a huge int is out
        # of range in its own direction, so it clamps to the same
        # extreme a large finite value would.
        if value < 0:
            return 0.0
        if value > 1:
            return 1.0
        return float(value)
    if not isinstance(value, float):
        # Only genuine numbers reach the conversion: a string the
        # wire sent is drift, never something to coerce into a
        # measurement, and the same holds for every other type.
        raise ProviderError(
            f"clef returned non-numeric {name}: {value!r}")
    try:
        f = float(value)
    except (TypeError, ValueError):
        raise ProviderError(
            f"clef returned non-numeric {name}: {value!r}") from None
    if not math.isfinite(f):
        raise ProviderError(
            f"clef returned non-numeric {name}: {value!r}")
    return max(0.0, min(1.0, f))


def _question_shapes(questions: dict[str, Any]) -> dict[str, Any]:
    """Transcript-safe summary: question names and types, no content."""
    return {k: {"type": v.get("type")} for k, v in questions.items()}


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    # "inf" and "nan" parse as floats; neither is a usable delay.
    # Finite values pass through: the runner caps the delay at
    # MAX_RETRY_AFTER_S when it consumes the value. An HTTP-date
    # value does not parse and falls back to the runner's backoff.
    if not math.isfinite(parsed):
        return None
    return max(0.0, parsed)


def _read_error_body(e: urllib.error.HTTPError) -> str:
    try:
        return e.read().decode("utf-8", errors="replace")[:500]
    except OSError:
        return ""
