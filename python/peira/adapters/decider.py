"""Decider adapter (Mapika AI, Apache 2.0).

Decider is a family of System One-style models fine-tuned from
Qwen3.5 bases. A Decider reads a state plus a set of typed questions
and returns, from one forward pass, a probability distribution for
every question: choice over 2 to 255 options, score over 2 to 10
described levels, or noul, the probability of yes. This adapter
measures the small arm, ``Mapika/decider-0.8b`` (Qwen3.5-0.8B base),
through the package's library API (``pip install decider-ai``,
``from decider.infer import Decider``), whose ``system_one`` method
takes the same question shapes the Jev wire takes and returns the
same answer shapes. The question builders are therefore Jev's,
reused unchanged, so the rubric text and the abstain question are
the same measurement instrument every Jev-family adapter sends.

Two answer-shape readings matter:

- Confidence. A choice answer carries ``confidence`` in the
  TypeSafe sense (the top probability rescaled so an even split
  gives 0) plus ``probabilities`` and ``x_p_max``. Peira's
  confidence contract is the model's probability for the chosen
  option, so this adapter reports ``probabilities[decision]``
  and leaves the rescaled figure in the transcript only. An
  answer that carries no probability for its chosen option is
  drift, and the adapter refuses it rather than substituting
  another figure. The same reading applies to the paired
  decision answer on score calls.
- Score scale. A score answer's ``score`` is the probability
  weighted level position on the 0..levels-1 index scale, not
  normalized. The adapter divides by ``levels - 1``, exactly the
  normalization the Jev adapter applies to the same rubric.

Temperatures: every answer is a softmax over its option letters
divided by a temperature from the checkpoint's
``decider_config.json``, one fitted value per question type where
the checkpoint carries a per-type map. Those temperatures are part
of the measured instrument. This adapter never overrides them (no
``temperature=``, no ``temperature_by_type=``, no
``DECIDER_TEMPERATURE``), so a run measures the checkpoint as its
authors shipped it.

Device: ``Decider`` picks CUDA, then MPS, then CPU when constructed
without a device. Pass ``device=`` to this adapter to force one
(``"cpu"``, ``"cuda"``, ``"mps"``). On CPU the package runs float32
eager. The 0.8B checkpoint is the family's CPU-sized arm.

Checkpoint pin: ``Mapika/decider-0.8b`` at a pinned Hub revision
(``PINNED_REVISION``). Anything else is rejected at construction.
The pinned pair is the version and namespaces the runner cache.
The package's constructor takes no revision argument, so the pin
is enforced by downloading the pinned revision with
``huggingface_hub.snapshot_download`` (a ``decider-ai`` dependency)
and constructing the engine on the local snapshot directory. A
measurement therefore runs the exact pinned weights even if the
Hub default branch moves.

``decider`` is imported lazily, only when an adapter is constructed,
so importing this module never requires the package. Without it the
error says exactly what to do.

Retry layering: the model is local, so there are no HTTP status
codes. A ``system_one`` failure is raised as ``ProviderError`` with
no ``status_code``, which the runner treats as permanent. The
adapter itself never retries.

NOTE, abstain/noul boundary mapping: peira's primitive is named
``abstain`` and the wire type for that primitive is ``"noul"`` (the
question builder is ``JevAdapter``'s). The adapter translates at the
boundary. Neither side is renamed. The abstain decision placeholder
follows the Jev rule (the ``"other"`` placeholder when the model
does not abstain), for the reasons stated in ``peira.adapters.jev``.
"""

from __future__ import annotations

import math
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
from peira.adapters.jev import (
    _SCORE_LEVELS,
    _choice_question,
    _noul_question,
    _score_question,
    _validate_questions,
)

CHECKPOINT = "Mapika/decider-0.8b"
"""The only checkpoint this adapter measures (the family's small arm)."""

PINNED_REVISION = "a0a01d6f8135298f400a8c856b355793012ae971"
"""Exact Hub commit the checkpoint is pinned to (read from the Hub
API on 2026-10-15, when the adapter was canaried)."""


def _import_decider() -> Any:
    """Import ``decider.infer`` lazily, with an actionable error."""
    try:
        import decider.infer as infer  # noqa: PLC0415  (deliberately lazy: optional dependency)
    except ImportError as e:
        raise ImportError(
            "the decider adapter needs the decider-ai package: run "
            "`pip install decider-ai`, then retry."
        ) from e
    return infer


def _resolve_checkpoint(checkpoint: str) -> str:
    """Accept only the pinned checkpoint id."""
    if checkpoint != CHECKPOINT:
        raise ValueError(
            f"decider adapter pins checkpoint {CHECKPOINT!r}; got "
            f"{checkpoint!r}. Floating or unlisted ids are rejected; a "
            "measurement must name the exact model."
        )
    return checkpoint


def _labels(case_input: dict[str, Any]) -> list[str]:
    """Candidate decision labels for this call, in stable sorted order."""
    return candidate_labels(case_input, "choice")


class DeciderAdapter:
    """Decision adapter for Mapika's Decider 0.8B checkpoint."""

    name = "decider"
    supported_primitives = frozenset({"choice", "score", "abstain"})
    # M-2: confidence comes from the model's per-answer probabilities,
    # like Jev: a model-output probability, not a verbalization.
    confidence_source = "token-logprob"
    # M-7 longitudinal provenance.
    model_class = "guardrail"

    def __init__(
        self,
        checkpoint: str = CHECKPOINT,
        revision: str = PINNED_REVISION,
        device: str | None = None,
        engine: Any = None,
    ) -> None:
        self.checkpoint = _resolve_checkpoint(checkpoint)
        if revision != PINNED_REVISION:
            raise ValueError(
                f"decider adapter pins revision {PINNED_REVISION!r}; "
                f"got {revision!r}. Floating or unlisted revisions "
                "are rejected; a measurement must name the exact "
                "model."
            )
        self.revision = revision
        self.device = device
        # The pinned checkpoint at the pinned revision IS the version.
        self.version = f"{self.checkpoint}@{self.revision}"
        self.cache_namespace = f"decider:{self.version}"
        if engine is not None:
            # Test seam (fake engine), mirroring LayaAdapter's
            # injectable agent.
            self._engine = engine
        else:
            infer = _import_decider()
            try:
                # The constructor takes no revision argument, so the
                # pin is a local snapshot of the pinned revision.
                from huggingface_hub import snapshot_download  # noqa: PLC0415

                local = snapshot_download(
                    self.checkpoint, revision=self.revision
                )
                self._engine = infer.Decider(local, device=self.device)
            except Exception as e:
                raise ProviderError(
                    f"decider failed to load checkpoint "
                    f"{self.checkpoint!r} at revision "
                    f"{self.revision!r}: {e}"
                ) from e

    # -- decide -----------------------------------------------------------

    def decide(
        self,
        case_input: dict[str, Any],
        primitive: str,
        context: CallContext,
    ) -> AdapterOutput:
        if primitive not in self.supported_primitives:
            raise ValueError(
                f"decider does not support primitive {primitive!r}"
            )
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

        started = time.perf_counter()
        try:
            result = self._engine.system_one(prompt, questions)
        except ProviderError:
            raise
        except Exception as e:
            # Local-model failure: no status code, so the runner treats
            # it as permanent (never retried) and records it malformed.
            raise ProviderError(f"decider system_one failed: {e}") from e
        latency_ms = (time.perf_counter() - started) * 1000.0
        if not isinstance(result, dict):
            raise ProviderError(
                f"decider returned a non-object result: {type(result).__name__}"
            )
        answers = result.get("answers")
        if not isinstance(answers, dict):
            raise ProviderError("decider response missing 'answers' object")
        # Local model: no token accounting to report. The runner
        # recomputes cost from the pinned pricing table (local, $0).
        call_usage = CallUsage(
            model=self.checkpoint,
            tokens_in=0,
            tokens_out=0,
            latency_ms=latency_ms,
            cost_usd=0.0,
        )
        transcript = {
            "checkpoint": self.checkpoint,
            "revision": self.revision,
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
                f"decider returned choice {option!r} outside the offered "
                f"labels {labels}; adapter bug or API drift."
            )
        confidence = _probability_confidence(ans, option)
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
                f"decider score answer has no numeric score: {ans!r}"
            )
        # The score arrives on the 0..levels-1 index scale; normalize
        # to 0..1 with the same divisor the Jev adapter uses.
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
        dec_ans = _need_answer(answers, "decision")
        option = str(dec_ans.get("choice", ""))
        if option not in labels:
            raise ProviderError(
                f"decider returned choice {option!r} outside the offered "
                f"labels {labels}; adapter bug or API drift."
            )
        confidence = _probability_confidence(dec_ans, option)
        return ScoreOutput(
            score=score,
            decision=option,
            confidence=confidence,
            usage=usage,
            transcript=transcript,
        )

    def _noul_output(self, answers, usage, transcript):
        ans = _need_answer(answers, "abstain")
        p_yes = ans.get("noul")
        if not isinstance(p_yes, (int, float)) or isinstance(p_yes, bool):
            raise ProviderError(
                f"decider abstain answer has no numeric noul value: {ans!r}"
            )
        p_yes = _clamp01(p_yes, "noul")
        confidence = _clamp01(abs(2 * p_yes - 1), "confidence")
        decision = "abstain" if p_yes >= 0.5 else non_abstain_placeholder()
        return AbstainOutput(
            decision=decision,
            confidence=confidence,
            usage=usage,
            transcript=transcript,
        )


def _probability_confidence(ans: dict[str, Any], option: str) -> float:
    """The model's probability for the chosen option.

    The answer's ``confidence`` field is the TypeSafe rescaled value;
    peira measures the raw probability, carried by ``probabilities``.
    Genuine answers always carry the distribution, so an answer
    without a probability for its chosen option is drift: terminal,
    never a substitute figure.
    """
    probs = ans.get("probabilities")
    if isinstance(probs, dict) and option in probs:
        return _clamp01(probs[option], "confidence")
    raise ProviderError(
        f"decider answer carries no probability for the chosen "
        f"option {option!r}: {ans!r}"
    )


def _need_answer(answers: dict[str, Any], name: str) -> dict[str, Any]:
    ans = answers.get(name)
    if not isinstance(ans, dict):
        raise ProviderError(f"decider response missing answer {name!r}")
    return ans


def _clamp01(value: Any, name: str) -> float:
    # A bool is never a legitimate probability, and a non-finite float
    # (NaN, +/-inf; Python's json accepts all three as literals) must
    # fail closed: clamping NaN would silently fabricate a maximal
    # measurement, since min/max comparisons with NaN are always
    # false.
    if isinstance(value, bool):
        raise ProviderError(
            f"decider returned non-numeric {name}: {value!r}")
    if isinstance(value, int):
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
            f"decider returned non-numeric {name}: {value!r}")
    f = float(value)
    if not math.isfinite(f):
        raise ProviderError(
            f"decider returned non-numeric {name}: {value!r}")
    return max(0.0, min(1.0, f))


def _question_shapes(questions: dict[str, Any]) -> dict[str, Any]:
    """Transcript-safe summary: question names and types, no content."""
    return {k: {"type": v.get("type")} for k, v in questions.items()}
