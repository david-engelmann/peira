"""Perplexity pplx-decider adapter (Decisions API).

pplx-decider is Perplexity's decision model, served through the
Decisions API: the caller sends a ``state`` (the decision context)
plus named, typed questions, and the API returns calibrated answers;
a chosen option with probabilities for ``choice``, a
probability-weighted numeric answer for ``score``, and a
probability-of-yes for ``abstain`` (the wire type is ``noul``, as on
the Jev wire). Perplexity positions pplx-decider directly against
TypeSafe's Jev, so peira measures it on the same wire shape with the
same question text the Jev adapter sends.

Two pinned models are supported, each named by its full served id so
a measurement always names the exact weights that produced it:

- ``pplx-decider-v1.1-27b`` (the default): the current version,
  served since 2026-10-06. $0.02 per 1M input tokens, output free.
- ``pplx-decider-v1-27b``: the launch version, served since
  2026-10-01. $0.02 per 1M input tokens, output free.

Both are fine-tunes of Qwen3.8-27B with Apache-2.0 weights. The
hosted context limit is 262,144 input tokens per request, far above
anything a peira case sends.

Endpoint: ``POST https://api.perplexity.ai/v1/decisions``
Auth: ``Authorization: Bearer <API key>``; a key sent in an
``x-api-key`` header is not read and returns 401. API access is
prepaid: the account needs API credit, and an out-of-credit account
returns 402. The response is NOT enveloped: the top level carries
``answers`` (keyed by question name), ``model`` (an echo of the model
id sent) and ``usage``. The adapter refuses a response whose echoed
model differs from the pin, so a measurement can never seal under
the wrong model's name.

Live state: the wire shape below was verified against the live API
on 2026-10-15, before this adapter was written, with a probe call
carrying the adapter's exact question text. The probe returned
HTTP 200 for ``pplx-decider-v1.1-27b``; the choice answer carried
``choice``, ``confidence`` and per-option ``probabilities``, the
score answer carried ``score`` on the 0-based rubric scale with
``legend`` and ``probabilities`` keyed by level index, and the
abstain answer carried the probability under ``noul`` only, with no
``abstain`` key. ``usage`` carried integer ``input_tokens`` (435 for
the probe) and ``output_tokens`` (3; output is billed free). The
adapter's first measured exercise is the standard driver canary.

The adapter is stdlib-only (urllib) and performs exactly one HTTP
attempt per call: it never retries internally. Transient failures
(408, 409, 429, 529, 5xx, timeouts, connection errors) are raised as
``ProviderError`` with ``status_code``/``retry_after`` so the runner,
which owns the retry policy, can classify and retry them. 401/403,
402, 404 and 400/422 are terminal. The organization rate limit is 10
requests per second; the runner owns concurrency.

No ``peira[...]`` extra is needed: the transport is stdlib. What is
needed is access: without ``PERPLEXITY_API_KEY`` the adapter refuses
to construct, with an error that says exactly what to do.

NOTE, abstain decision placeholder: for the abstain primitive,
pplx-decider only answers "should I abstain?" (a yes/no probability).
It never produces a decision label. When the model does NOT abstain
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

SUPPORTED_MODEL_IDS = frozenset({
    "pplx-decider-v1.1-27b",
    "pplx-decider-v1-27b",
})
"""Pinned served model ids. Ids outside this table are rejected at
construction; a measurement must name the exact model."""

MODEL_ID = "pplx-decider-v1.1-27b"
"""Default pinned pplx-decider model: the current served version."""

API_KEY_ENV = "PERPLEXITY_API_KEY"
"""Environment variable carrying the Perplexity API key."""

API_URL = "https://api.perplexity.ai/v1/decisions"
"""The Decisions endpoint. Any other path, including a trailing
slash, returns 404."""

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


def _require_api_key(explicit: str | None) -> str:
    key = explicit or os.environ.get(API_KEY_ENV, "")
    if not key:
        raise ValueError(
            f"pplx-decider adapter needs a Perplexity API key: set "
            f"the {API_KEY_ENV} environment variable (or pass "
            f"api_key=<redacted>). Perplexity API access is prepaid; "
            f"create a key in the API Console at perplexity.ai and "
            f"load API credit, then export {API_KEY_ENV}=<your key>."
        )
    return key


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
    # protocol requires it. The text carries a U+2014 by design: it is
    # the Jev adapter's measurement-instrument text, byte-identical.
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
                f"pplx-decider built a malformed question {name!r}: "
                "not an object"
            )
        qtype = q.get("type")
        # "noul" is the wire question type for the abstain primitive
        # (see _noul_question); the other two match Peira's names.
        if qtype not in ("choice", "score", "noul"):
            raise ProviderError(
                f"pplx-decider built question {name!r} with unknown "
                f"type {qtype!r}"
            )
        if not isinstance(q.get("instructions"), str) or not q["instructions"]:
            raise ProviderError(
                f"pplx-decider built question {name!r} without "
                "instructions"
            )
        criteria = q.get("criteria")
        if qtype == "choice":
            if not isinstance(criteria, dict) or not criteria:
                raise ProviderError(
                    f"pplx-decider built choice question {name!r} "
                    "without a non-empty criteria map"
                )
        elif qtype == "score":
            if (
                not isinstance(criteria, list)
                or not 2 <= len(criteria) <= 10
                or not all(isinstance(c, str) and c for c in criteria)
            ):
                raise ProviderError(
                    f"pplx-decider built score question {name!r} "
                    "without 2-10 level descriptions"
                )


class PplxDeciderAdapter:
    """Decision adapter for Perplexity's pplx-decider (Decisions API)."""

    name = "pplx-decider"
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
        timeout_s: float = 60.0,
        transport: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        if model not in SUPPORTED_MODEL_IDS:
            pins = " or ".join(
                repr(m) for m in sorted(SUPPORTED_MODEL_IDS))
            raise ValueError(
                f"pplx-decider adapter pins model {pins}; "
                f"got {model!r}. Floating tags and unversioned names "
                "are never allowed; a measurement must name the "
                "exact model."
            )
        self.model = model
        # Per-instance identity follows the chosen pin, so runs of
        # different pplx-decider versions seal and cache apart.
        self.version = model
        self.cache_namespace = f"pplx-decider:{model}"
        credential = _require_api_key(api_key)
        self._api_token = credential
        self.api_url = API_URL
        self.timeout_s = timeout_s
        # Injectable transport for tests: fn(payload) -> parsed body.
        self._transport = transport or self._http_transport
        # The key authenticates the request; it never leaves this
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
                f"pplx-decider transport error: {e}",
                status_code=408) from e
        latency_ms = (time.perf_counter() - started) * 1000.0
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ProviderError(
                f"pplx-decider returned non-JSON response (HTTP {status})"
            ) from e
        if not isinstance(parsed, dict):
            raise ProviderError(
                "pplx-decider returned a non-object JSON response")
        parsed["_latency_ms"] = latency_ms
        return parsed

    def _raise_for_status(
        self, status: int, retry_after: str | None, detail: str
    ) -> None:
        wait = _parse_retry_after(retry_after)
        msg = f"pplx-decider API error {status}" + (
            f": {detail}" if detail else "")
        if status in (401, 403):
            raise ProviderError(
                msg + f"; check that {API_KEY_ENV} is valid and "
                "active, and sent as a Bearer token.",
                status_code=status,
            )
        if status == 402:
            raise ProviderError(
                msg + "; the account is out of API credit; add "
                "credit in the API Console under Billing, then rerun.",
                status_code=status,
            )
        if status == 404:
            raise ProviderError(
                msg + "; the Decisions endpoint path was not found; "
                "this is an adapter bug or an API change, not a "
                "retryable failure.",
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
            # concurrency. The adapter itself never retries. A 504 is
            # the API's own timeout and lands here as a 5xx. 409 is
            # in the runner's transient set, so the server's
            # Retry-After must reach it like every other transient's.
            raise ProviderError(msg, status_code=status, retry_after=wait)
        raise ProviderError(msg, status_code=status)

    # -- decide -----------------------------------------------------------

    def decide(
        self, case_input: dict[str, Any], primitive: str, context: CallContext
    ) -> ChoiceOutput | ScoreOutput | AbstainOutput:
        if primitive not in self.supported_primitives:
            raise ValueError(
                f"pplx-decider does not support primitive {primitive!r}")
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
            "state": prompt,
            "questions": questions,
        }
        response = self._transport(payload)
        if not isinstance(response, dict):
            raise ProviderError(
                "pplx-decider returned a non-object JSON response")
        answers = response.get("answers")
        if not isinstance(answers, dict):
            raise ProviderError(
                "pplx-decider response missing 'answers' object")
        echoed = response.get("model")
        if echoed != self.model:
            # The response names the weights that actually ran. Any
            # other name (or none) means the measurement cannot be
            # recorded under this pin.
            raise ProviderError(
                f"pplx-decider response names model {echoed!r} but "
                f"the adapter pinned {self.model!r}; refusing a "
                "measurement under the wrong model name.")
        usage = response.get("usage")
        if not isinstance(usage, dict):
            # Cost accounting fails closed: a response without usage
            # counters cannot be priced, and recording it as a free
            # call would silently understate the run's spend.
            raise ProviderError(
                "pplx-decider response missing 'usage' object")
        # Strict, never coerced: int() would silently accept bools,
        # truncate floats, parse strings and pass negatives through
        # to a negative cost. A counter that is not a non-negative
        # integer is malformed wire data and fails closed.
        tokens_in = usage.get("input_tokens")
        tokens_out = usage.get("output_tokens")
        if not all(type(v) is int and v >= 0
                   for v in (tokens_in, tokens_out)):
            raise ProviderError(
                f"pplx-decider returned malformed usage counters: "
                f"{usage!r}")
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
                "model": self.model,
                "questions": _question_shapes(questions),
            },
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
                f"pplx-decider returned choice {option!r} outside the "
                f"offered labels {labels}; adapter bug or API drift."
            )
        probs = ans.get("probabilities") or {}
        if not isinstance(probs, dict):
            raise ProviderError(
                f"pplx-decider returned probabilities that are not "
                f"an object: {probs!r}")
        confidence = _answer_confidence(ans, option)
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
                f"pplx-decider score answer has no numeric score: {ans!r}")
        score = _clamp01(float(value) / (len(_SCORE_LEVELS) - 1), "score")
        # The paired decision question carries the label; the score is
        # the measurement signal. An out-of-vocabulary label is API
        # drift; fail loudly like the choice path does.
        dec_ans = _need_answer(answers, "decision")
        option = str(dec_ans.get("choice", ""))
        if option not in labels:
            raise ProviderError(
                f"pplx-decider returned choice {option!r} outside the "
                f"offered labels {labels}; adapter bug or API drift."
            )
        decision = option
        confidence = _answer_confidence(dec_ans, option)
        return ScoreOutput(
            score=score, decision=decision, confidence=confidence,
            usage=usage, transcript=transcript,
        )

    def _noul_output(self, answers, usage, transcript):
        # The answer is keyed by OUR question name ("abstain"); the
        # nested "type": "noul" is the wire field (see _noul_question).
        #
        # NOTE (abstain decision placeholder): pplx-decider only
        # answers "should I abstain?"; it never emits a decision label.
        # When p < 0.5 (no abstention) the `decision` below is the
        # "other" placeholder, NOT a model output and NOT gold. Flip
        # detection uses the `abstained` flag. See the module docstring.
        ans = _need_answer(answers, "abstain")
        # The wire returns the abstain probability under its own field
        # name, {'type': 'noul', 'noul': 0.73}, and the 2026-10-15
        # Perplexity probe carried the noul key only. The Jev wire's
        # documented key is "abstain", so that key is accepted as an
        # alias. If both keys ever arrive with different values, the
        # API has drifted and no preference order can say which one
        # is the probability; fail closed instead of guessing.
        # An explicit null carries no value on the wire; it counts
        # as absent, not as a competing reading.
        carried = [ans[k] for k in ("abstain", "noul")
                   if ans.get(k) is not None]
        if len(carried) == 2 and carried[0] != carried[1]:
            raise ProviderError(
                f"pplx-decider abstain answer carries both "
                f"'abstain' ({carried[0]!r}) and 'noul' "
                f"({carried[1]!r}) with different values; refusing a "
                "measurement whose probability is ambiguous.")
        p_yes = carried[0] if carried else None
        if not isinstance(p_yes, (int, float)) or isinstance(p_yes, bool):
            raise ProviderError(
                f"pplx-decider abstain answer has no numeric abstain "
                f"value: {ans!r}")
        if not 0.0 <= float(p_yes) <= 1.0:
            # A probability outside [0, 1] (NaN included; its
            # comparisons are all false) is malformed wire data, not
            # a value to clamp into a fabricated extreme.
            raise ProviderError(
                f"pplx-decider abstain answer probability out of "
                f"range: {ans!r}")
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
        raise ProviderError(f"pplx-decider response missing answer {name!r}")
    return ans


def _answer_confidence(ans: dict[str, Any], option: str) -> float:
    """The decision answer's confidence, strictly validated.

    The API's ``confidence`` field is authoritative; the fallback is
    the probabilities map's value for the chosen option. Both must be
    genuine numbers in [0, 1], never coerced. A missing or malformed
    confidence is malformed wire data and fails closed: confidence is
    a measurement the model reported, never a value the adapter
    invents (there is no midpoint default).
    """
    raw = ans.get("confidence")
    if raw is None:
        probs = ans.get("probabilities")
        if isinstance(probs, dict):
            raw = probs.get(option)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ProviderError(
            f"pplx-decider decision answer has no usable confidence: "
            f"{ans!r}")
    value = float(raw)
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ProviderError(
            f"pplx-decider decision answer has no usable confidence: "
            f"{ans!r}")
    return value


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
            f"pplx-decider returned non-numeric {name}: {value!r}")
    try:
        f = float(value)
    except (TypeError, ValueError):
        raise ProviderError(
            f"pplx-decider returned non-numeric {name}: {value!r}") from None
    if not math.isfinite(f):
        raise ProviderError(
            f"pplx-decider returned non-numeric {name}: {value!r}")
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

    Most Decisions API errors return a JSON body with an ``error``
    object; read its ``message`` (never branch on ``error.code``,
    whose type varies). A 504 can return an HTML page instead, so any
    parse failure falls back to the raw body prefix.
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
