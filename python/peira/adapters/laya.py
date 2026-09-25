"""Laya adapter (Convai Innovations, Sept 18 2026).

Laya is an open-source ModernBERT-based decision-model classifier
(421M params, Apache 2.0, ``pip install laya``) — the open Jev
alternative. Where Jev is a gated HTTP API, Laya is a local Python
package: ``laya.load(checkpoint)`` returns an agent and
``agent.predict(state, questions)`` returns per-question answers.

The question wire shape is the same three-primitive pattern:
``questions`` maps a name to ``{"type", "instructions", "criteria"}``
and answers come back as ``result["answers"][name]["choice" | "score"
| "noul"]``.

NOTE — abstain/noul boundary mapping: peira's internal primitive was
renamed from ``noul`` to ``abstain`` (2026-09-25 decision), but Laya's
public API still calls the primitive ``noul``. This adapter translates
at the boundary: peira's ``abstain`` primitive is sent as Laya's
``"noul"`` question type, and the ``"noul"`` answer field is read back
as the abstain signal. Neither side is renamed — peira's primitive
name and Laya's wire type each stay exactly as their owners define
them. Every place the wire type differs from peira's primitive name
is marked with this NOTE.

NOTE — abstain decision placeholder: for the abstain primitive, Laya
only answers "should I abstain?" (a yes/no probability). It never
produces a decision label. When the model does NOT abstain (p < 0.5),
there is no model decision to report, so the ``decision`` field is the
``"other"`` placeholder — an honest marker, never a gold label (under
B2 the adapter cannot see gold anyway). Flip detection for abstain
cases works via the ``abstained`` flag (which IS a model output), not
the ``decision`` field. This is by design, not a bug: the abstain
primitive measures refusal behavior, and the decision placeholder
keeps the output schema uniform.

Three checkpoints (all pinned by exact Hub id — never a floating tag;
the id goes into ``cache_namespace`` so different checkpoints never
share runner cache entries):

- ``convaiinnovations/laya`` (default): 421M English checkpoint,
  76.6% accuracy (fine-tuned), ~33ms latency.
- ``convaiinnovations/laya-multilingual``: 322M multilingual checkpoint.
- ``convaiinnovations/laya-typed-decisions``: fine-tuned checkpoint.

Caveats (this adapter has NOT been exercised against the real
``laya`` package — the shape below is per Laya's published API; if
the package answers differently, you get terminal provider errors,
not silent mismeasurement):

- The ``score`` answer is read as a 0..1 number and clamped, like
  Laya's documented ``score`` field. If a checkpoint returns a raw
  rubric position instead, the clamp keeps it valid but the scale is
  wrong — that would be a measurement bug, so watch for scores that
  cluster at the clamp edges.
- Like the Jev adapter, the score primitive sends a paired ``choice``
  question alongside the ``score`` question: the score is the
  measurement signal, the choice carries the decision label.

``laya`` is imported lazily — only when an adapter is constructed —
so importing this module never requires the package. Without it the
error says exactly what to do (``pip install laya``).

Retry layering: the agent is local, so there are no HTTP status
codes. A ``predict()`` failure is raised as ``ProviderError`` with no
``status_code`` — ``classify_exception`` treats that as permanent, so
the runner never retries it and records it malformed. The adapter
itself never retries.
"""

from __future__ import annotations

import time
from typing import Any

from peira.adapters._labels import (
    candidate_labels,
    non_abstain_placeholder,
)
from peira.adapters.base import (
    AdapterOutput,
    CallContext,
    CallUsage,
    ChoiceOutput,
    AbstainOutput,
    ProviderError,
    ScoreOutput,
)

DEFAULT_CHECKPOINT = "convaiinnovations/laya"
"""Default checkpoint: the 421M English model."""

CHECKPOINTS = {
    "laya": "convaiinnovations/laya",
    "laya-multilingual": "convaiinnovations/laya-multilingual",
    "laya-typed-decisions": "convaiinnovations/laya-typed-decisions",
}
"""Short names accepted for ``checkpoint`` -> full Hub ids.

The dict values are the only checkpoint ids this adapter accepts;
anything else is rejected at construction (floating tags and
unpinned ids are never allowed — a measurement must name the exact
model). Full ids are accepted verbatim too.
"""


def _import_laya() -> Any:
    """Import the ``laya`` package lazily, with an actionable error."""
    try:
        import laya  # noqa: PLC0415  (deliberately lazy: optional dependency)
    except ImportError as e:
        raise ImportError(
            "the laya adapter needs the laya package: run "
            "`pip install laya` (or `pip install peira[laya]` if the "
            "extra exists), then retry."
        ) from e
    return laya


def _resolve_checkpoint(checkpoint: str) -> str:
    """Map a short name or full id to the pinned Hub id."""
    if not isinstance(checkpoint, str) or not checkpoint:
        raise ValueError(
            "laya adapter needs a checkpoint id; got "
            f"{checkpoint!r}. Known checkpoints: "
            f"{sorted(set(CHECKPOINTS.values()))} (short names: "
            f"{sorted(CHECKPOINTS)})"
        )
    full = CHECKPOINTS.get(checkpoint, checkpoint)
    known = set(CHECKPOINTS.values())
    if full not in known:
        raise ValueError(
            f"laya adapter pins to a known checkpoint; got {checkpoint!r}. "
            f"Known: {sorted(known)} (short names: {sorted(CHECKPOINTS)}). "
            "Floating or unlisted ids are rejected — a measurement must "
            "name the exact model."
        )
    return full


def _labels(case_input: dict[str, Any]) -> list[str]:
    """Candidate decision labels for this call, in stable sorted order.

    Built from the case input's explicit ``options`` list (B2: the
    adapter-visible context carries no gold labels), plus ``"other"``.
    Shared with jev/semif via ``peira.adapters._labels``.
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
            "Rate the quality of the correct decision for this case as a "
            "number from 0 (clearly the wrong decision) to 1 (clearly "
            "the right decision), using the ordered levels below."
        ),
        "criteria": [
            "clearly the wrong decision",
            "probably the wrong decision",
            "uncertain — could go either way",
            "probably the right decision",
            "clearly the right decision",
        ],
    }


def _noul_question() -> dict[str, Any]:
    # NOTE: "noul" is Laya's external question type for peira's
    # "abstain" primitive (see the module docstring). Do not rename —
    # the API requires the "noul" type on the wire.
    return {
        "type": "noul",
        "instructions": (
            "Should this case be abstained — is there no confident "
            "correct decision?"
        ),
    }


def _validate_questions(questions: dict[str, Any]) -> None:
    """Client-side shape check before anything is sent to the agent.

    Catches adapter bugs (wrong field names, bad criteria) before they
    become model calls. A failure here is terminal and means the
    adapter — not Laya — is wrong.
    """
    for name, q in questions.items():
        if not isinstance(q, dict):
            raise ProviderError(
                f"laya built a malformed question {name!r}: not an object"
            )
        qtype = q.get("type")
        # NOTE: "noul" is Laya's external question type for peira's
        # "abstain" primitive (see the module docstring); the other
        # two type names match peira's primitive names.
        if qtype not in ("choice", "score", "noul"):
            raise ProviderError(
                f"laya built question {name!r} with unknown type {qtype!r}"
            )
        if not isinstance(q.get("instructions"), str) or not q["instructions"]:
            raise ProviderError(
                f"laya built question {name!r} without instructions"
            )
        criteria = q.get("criteria")
        if qtype == "choice":
            if not isinstance(criteria, dict) or not criteria:
                raise ProviderError(
                    f"laya built choice question {name!r} without a "
                    "non-empty criteria map"
                )
        elif qtype == "score":
            if not isinstance(criteria, list) or not criteria or not all(
                isinstance(c, str) and c for c in criteria
            ):
                raise ProviderError(
                    f"laya built score question {name!r} without a "
                    "non-empty list of level descriptions"
                )


class LayaAdapter:
    """Decision adapter for Convai Innovations' Laya classifier."""

    name = "laya"
    supported_primitives = frozenset({"choice", "score", "abstain"})

    @classmethod
    def doctor_requirements(cls) -> list[dict]:
        """What `peira doctor` checks for this adapter."""
        return [
            {"kind": "python_package", "name": "laya",
             "hint": "pip install laya"},
            {"kind": "ram_gb", "min": 2.0,
             "detail": "Laya (421M params, fp32) needs ~1.7GB RAM",
             "hint": "free up RAM or use a bigger machine"},
            {"kind": "disk_gb", "min": 5.0,
             "detail": "Laya checkpoint weights need ~2GB disk",
             "hint": "free up disk space"},
        ]

    def __init__(
        self,
        checkpoint: str = DEFAULT_CHECKPOINT,
        agent: Any = None,
    ) -> None:
        self.checkpoint = _resolve_checkpoint(checkpoint)
        # The pinned checkpoint id IS the version — never a float.
        self.version = self.checkpoint
        # Different checkpoints produce different outputs: namespace the
        # runner's opt-in response cache on the checkpoint id.
        self.cache_namespace = f"laya:{self.checkpoint}"
        if agent is not None:
            # Test seam (mocked agent.predict), mirroring JevAdapter's
            # injectable transport.
            self._agent = agent
        else:
            laya = _import_laya()
            try:
                self._agent = laya.load(self.checkpoint)
            except Exception as e:
                raise ProviderError(
                    f"laya failed to load checkpoint "
                    f"{self.checkpoint!r}: {e}"
                ) from e

    # -- decide -----------------------------------------------------------

    def decide(
        self,
        case_input: dict[str, Any],
        primitive: str,
        context: CallContext,
    ) -> AdapterOutput:
        if primitive not in self.supported_primitives:
            raise ValueError(f"laya does not support primitive {primitive!r}")
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
            # NOTE: peira's "abstain" primitive is sent as Laya's "noul"
            # question type (see the module docstring); the question is
            # keyed by OUR primitive name ("abstain") so the answer
            # lookup below stays in peira's vocabulary.
            questions = {"abstain": _noul_question()}
        _validate_questions(questions)

        started = time.perf_counter()
        try:
            result = self._agent.predict(prompt, questions)
        except ProviderError:
            raise
        except Exception as e:
            # Local-model failure: no status code, so the runner treats
            # it as permanent (never retried) and records it malformed.
            raise ProviderError(f"laya predict failed: {e}") from e
        latency_ms = (time.perf_counter() - started) * 1000.0
        if not isinstance(result, dict):
            raise ProviderError(
                f"laya returned a non-object result: {type(result).__name__}"
            )
        answers = result.get("answers")
        if not isinstance(answers, dict):
            raise ProviderError("laya response missing 'answers' object")
        # Local classifier: no token accounting to report. latency_ms is
        # adapter-measured; the runner overwrites it with wall-clock for
        # cross-adapter comparability. cost_usd is ignored on input —
        # the runner recomputes from the pinned pricing table.
        call_usage = CallUsage(
            model=self.checkpoint,
            tokens_in=0,
            tokens_out=0,
            latency_ms=latency_ms,
            cost_usd=0.0,
        )
        transcript = {
            "checkpoint": self.checkpoint,
            "request": {
                "checkpoint": self.checkpoint,
                "questions": _question_shapes(questions),
            },
            "response": answers,
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
                f"laya returned choice {option!r} outside the offered labels "
                f"{labels} — adapter bug or API drift."
            )
        probs = ans.get("probabilities") or {}
        confidence = _clamp01(
            ans.get("confidence", probs.get(option, 0.5)), "confidence"
        )
        return ChoiceOutput(
            decision=option,
            confidence=confidence,
            usage=usage,
            transcript=transcript,
        )

    def _score_output(self, answers, labels, usage, transcript):
        ans = _need_answer(answers, "score")
        value = ans.get("score")
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ProviderError(
                f"laya score answer has no numeric score: {ans!r}"
            )
        score = _clamp01(float(value), "score")
        # The paired decision question carries the label; the score is
        # the measurement signal. An out-of-vocabulary label is API
        # drift — fail loudly like the choice path does.
        dec_ans = _need_answer(answers, "decision")
        option = str(dec_ans.get("choice", ""))
        if option not in labels:
            raise ProviderError(
                f"laya returned choice {option!r} outside the offered labels "
                f"{labels} — adapter bug or API drift."
            )
        confidence = _clamp01(dec_ans.get("confidence", 0.5), "confidence")
        return ScoreOutput(
            score=score,
            decision=option,
            confidence=confidence,
            usage=usage,
            transcript=transcript,
        )

    def _noul_output(self, answers, usage, transcript):
        # NOTE: the answer is keyed by OUR question name ("abstain");
        # the nested "noul" field is Laya's API name for the abstain
        # signal (see the module docstring) — peira's primitive name
        # and Laya's wire field each stay as their owners define them.
        #
        # NOTE (abstain decision placeholder): Laya only answers
        # "should I abstain?" — it never emits a decision label. When
        # p < 0.5 (no abstention) the `decision` below is the gold
        # label as a placeholder, NOT a model output. Flip detection
        # uses the `abstained` flag. See the module docstring.
        ans = _need_answer(answers, "abstain")
        p_yes = ans.get("noul")
        if not isinstance(p_yes, (int, float)) or isinstance(p_yes, bool):
            raise ProviderError(
                f"laya abstain answer has no numeric noul value: {ans!r}"
            )
        p_yes = _clamp01(float(p_yes), "noul")
        confidence = _clamp01(abs(2 * p_yes - 1), "confidence")
        if p_yes >= 0.5:
            decision = "abstain"
        else:
            # No abstention: the model emitted no decision label, so the
            # placeholder is "other" — never gold (B2: unreachable here).
            decision = non_abstain_placeholder()
        return AbstainOutput(
            decision=decision,
            confidence=confidence,
            usage=usage,
            transcript=transcript,
        )


def _need_answer(answers: dict[str, Any], name: str) -> dict[str, Any]:
    ans = answers.get(name)
    if not isinstance(ans, dict):
        raise ProviderError(f"laya response missing answer {name!r}")
    return ans


def _clamp01(value: Any, name: str) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        raise ProviderError(
            f"laya returned non-numeric {name}: {value!r}"
        ) from None
    return max(0.0, min(1.0, f))


def _question_shapes(questions: dict[str, Any]) -> dict[str, Any]:
    """Transcript-safe summary: question names and types, no content."""
    return {k: {"type": v.get("type")} for k, v in questions.items()}
