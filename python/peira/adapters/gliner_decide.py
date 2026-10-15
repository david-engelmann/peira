"""GLiNER2.5-Decide adapter (Fastino Labs, Apache 2.0).

GLiNER2.5-Decide is a 340M DeBERTa-v3 encoder fine-tuned for
operational decisions. It is not a question-answering wire like Jev:
it is a schema classifier. One ``classify_text`` call scores several
named tasks over the same text in a single forward pass, and each
task is a caller-supplied label set. Labels may carry a short
description each. With ``include_confidence=True`` a single-label
task returns ``{"label": ..., "confidence": ...}`` where the
confidence is the model's probability for the winning label. The
model runs locally on CPU through the ``gliner2`` package
(``pip install "gliner2[local]"``).

Label mapping (the design decision of this adapter; the model takes
no instructions, so each peira question is expressed entirely
through its task name, its label set, and the label descriptions):

- choice: one task named ``decision`` whose labels are the case's
  candidate labels (the case options plus ``"other"``, from
  ``peira.adapters._labels``). Each label's description mirrors the
  Jev choice criteria text, ``Decide '<label>' for this case``, with
  ``"other"`` described as none of the listed options being the
  correct decision. The winning label is the decision and its
  confidence is the reported confidence.
- score: two tasks in one call. The ``score`` task's labels are the
  five ordered rubric level descriptions the Jev wire uses, worst
  to best, with the middle level carrying a comma where Jev's
  copy carries an em dash (these labels are this adapter's own
  instrument text). The winning level's position is the score,
  normalized to 0..1 as ``index / (levels - 1)``. The ``decision``
  task (same mapping as choice) carries the decision label, and
  its confidence is the reported confidence, exactly as the Jev
  adapter pairs a decision question with its score question.
- abstain: one task named ``abstain`` with two labels, ``"yes"``
  (described as the case should be abstained because there is no
  confident correct decision) and ``"no"`` (a confident correct
  decision exists). The yes probability is the winner's confidence
  when the winner is ``"yes"`` and one minus the winner's
  confidence when the winner is ``"no"``. The decision and
  confidence then follow the Jev abstain mapping (abstain at
  p >= 0.5, confidence ``|2p - 1|``, the ``"other"`` placeholder
  decision when not abstaining).

What this mapping cannot express: the Jev wire's instruction text.
GLiNER2.5-Decide has no instructions field, so the question a case
asks is carried only by the label descriptions. That is a real
limitation of the model class, recorded here rather than papered
over. Cases whose prompt does not itself state the decision context
will measure worse, and that is the model's honest score.

The score is the winning level's position, not a probability
weighted expectation over levels, because the public
``classify_text`` API returns only the winning label and its
confidence for a single-label task. The transcript records both
task results verbatim so the reading is auditable.

Checkpoint pin: ``fastino/GLiNER2.5-Decide`` at a pinned Hub
revision (``PINNED_REVISION``). Floating revisions are rejected at
construction. The pinned id plus revision is the version and
namespaces the runner cache.

``gliner2`` is imported lazily, only when an adapter is constructed,
so importing this module never requires the package. Without it the
error says exactly what to do.

Retry layering: the model is local, so there are no HTTP status
codes. A ``classify_text`` failure is raised as ``ProviderError``
with no ``status_code``, which the runner treats as permanent. The
adapter itself never retries.
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

CHECKPOINT = "fastino/GLiNER2.5-Decide"
"""The only checkpoint this adapter measures."""

PINNED_REVISION = "9d1bfb848cd16d93ee56ccbc59cd92bf0f284d90"
"""Exact Hub commit the checkpoint is pinned to (read from the Hub
API on 2026-10-15, when the adapter was canaried)."""

_SCORE_LEVELS = [
    "clearly the wrong decision",
    "probably the wrong decision",
    "uncertain, could go either way",
    "probably the right decision",
    "clearly the right decision",
]
"""Ordered score rubric, worst to best. The same five level
descriptions the Jev wire sends (the Jev copy carries an em dash in
its middle label because that text is Jev's measurement instrument;
this adapter's labels are its own instrument, so the middle label
uses a comma). The winning level's 0-based position, divided by
``len(levels) - 1``, is the normalized score."""


def _import_gliner2() -> Any:
    """Import the ``gliner2`` package lazily, with an actionable error."""
    try:
        import gliner2  # noqa: PLC0415  (deliberately lazy: optional dependency)
    except ImportError as e:
        raise ImportError(
            "the gliner-decide adapter needs the gliner2 package: run "
            "`pip install \"gliner2[local]\"`, then retry."
        ) from e
    return gliner2


def _resolve_checkpoint(checkpoint: str) -> str:
    """Accept only the pinned checkpoint id."""
    if checkpoint != CHECKPOINT:
        raise ValueError(
            f"gliner-decide adapter pins checkpoint {CHECKPOINT!r}; got "
            f"{checkpoint!r}. Floating or unlisted ids are rejected; a "
            "measurement must name the exact model."
        )
    return checkpoint


def _resolve_revision(revision: str) -> str:
    """Accept only the pinned Hub revision."""
    if revision != PINNED_REVISION:
        raise ValueError(
            f"gliner-decide adapter pins revision {PINNED_REVISION!r}; "
            f"got {revision!r}. Floating or unlisted revisions are "
            "rejected; a measurement must name the exact model."
        )
    return revision


def _labels(case_input: dict[str, Any]) -> list[str]:
    """Candidate decision labels for this call, in stable sorted order."""
    return candidate_labels(case_input, "choice")


def _decision_task(labels: list[str]) -> dict[str, Any]:
    """The choice mapping: candidate labels with Jev-style descriptions."""
    return {
        label: (
            "None of the listed options is the correct decision."
            if label == "other"
            else f"Decide {label!r} for this case."
        )
        for label in labels
    }


def _score_task() -> list[str]:
    """The score mapping: the five rubric levels as plain labels."""
    return list(_SCORE_LEVELS)


def _abstain_task() -> dict[str, Any]:
    """The abstain mapping: a two-label yes/no set with descriptions."""
    return {
        "yes": (
            "This case should be abstained; there is no confident "
            "correct decision."
        ),
        "no": "A confident correct decision exists for this case.",
    }


class GlinerDecideAdapter:
    """Decision adapter for Fastino's GLiNER2.5-Decide classifier."""

    name = "gliner-decide"
    supported_primitives = frozenset({"choice", "score", "abstain"})
    # M-2: confidence comes from the model's per-label probabilities,
    # like Jev: a model-output probability, not a verbalization.
    confidence_source = "token-logprob"
    # M-7 longitudinal provenance.
    model_class = "guardrail"

    def __init__(
        self,
        checkpoint: str = CHECKPOINT,
        revision: str = PINNED_REVISION,
        extractor: Any = None,
    ) -> None:
        self.checkpoint = _resolve_checkpoint(checkpoint)
        self.revision = _resolve_revision(revision)
        # The pinned checkpoint at the pinned revision IS the version.
        self.version = f"{self.checkpoint}@{self.revision}"
        self.cache_namespace = f"gliner-decide:{self.version}"
        if extractor is not None:
            # Test seam (fake extractor), mirroring LayaAdapter's
            # injectable agent.
            self._extractor = extractor
        else:
            gliner2 = _import_gliner2()
            try:
                self._extractor = gliner2.AutoExtractor.from_pretrained(
                    self.checkpoint, revision=self.revision
                )
            except Exception as e:
                raise ProviderError(
                    f"gliner-decide failed to load checkpoint "
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
                f"gliner-decide does not support primitive {primitive!r}"
            )
        text = str(case_input.get("prompt", ""))
        labels = _labels(case_input)

        if primitive == "choice":
            tasks = {"decision": _decision_task(labels)}
        elif primitive == "score":
            tasks = {
                "score": _score_task(),
                "decision": _decision_task(labels),
            }
        else:  # abstain
            tasks = {"abstain": _abstain_task()}

        started = time.perf_counter()
        try:
            result = self._extractor.classify_text(
                text, tasks, include_confidence=True
            )
        except ProviderError:
            raise
        except Exception as e:
            # Local-model failure: no status code, so the runner treats
            # it as permanent (never retried) and records it malformed.
            raise ProviderError(f"gliner-decide classify_text failed: {e}") from e
        latency_ms = (time.perf_counter() - started) * 1000.0
        if not isinstance(result, dict):
            raise ProviderError(
                "gliner-decide returned a non-object result: "
                f"{type(result).__name__}"
            )
        # Local classifier: no token accounting to report. The runner
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
            "request": {"tasks": _task_shapes(tasks)},
            "response": result,
        }

        if primitive == "choice":
            label, confidence = _decision_winner(result, labels)
            return ChoiceOutput(
                decision=label,
                confidence=confidence,
                usage=call_usage,
                transcript=transcript,
            )
        if primitive == "score":
            level, _score_conf = _task_winner(result, "score")
            if level not in _SCORE_LEVELS:
                raise ProviderError(
                    f"gliner-decide returned score level {level!r} outside "
                    f"the offered levels {_SCORE_LEVELS}; adapter bug or "
                    "API drift."
                )
            score = _SCORE_LEVELS.index(level) / (len(_SCORE_LEVELS) - 1)
            label, confidence = _decision_winner(result, labels)
            return ScoreOutput(
                score=score,
                decision=label,
                confidence=confidence,
                usage=call_usage,
                transcript=transcript,
            )
        # abstain
        winner, confidence = _task_winner(result, "abstain")
        if winner not in ("yes", "no"):
            raise ProviderError(
                f"gliner-decide returned abstain label {winner!r} outside "
                "the offered labels ['no', 'yes']; adapter bug or API drift."
            )
        # confidence is validated into 0..1 by _task_winner, so both
        # derived values are in range by construction.
        p_yes = confidence if winner == "yes" else 1.0 - confidence
        abstain_confidence = abs(2 * p_yes - 1)
        decision = "abstain" if p_yes >= 0.5 else non_abstain_placeholder()
        return AbstainOutput(
            decision=decision,
            confidence=abstain_confidence,
            usage=call_usage,
            transcript=transcript,
        )


def _decision_winner(
    result: dict[str, Any], labels: list[str]
) -> tuple[str, float]:
    """The decision task's winner, validated against the offered labels."""
    label, confidence = _task_winner(result, "decision")
    if label not in labels:
        raise ProviderError(
            f"gliner-decide returned choice {label!r} outside the "
            f"offered labels {labels}; adapter bug or API drift."
        )
    return label, confidence


def _task_winner(result: dict[str, Any], task: str) -> tuple[str, float]:
    """Read one task's winning label and confidence, failing loudly."""
    entry = result.get(task)
    if not isinstance(entry, dict):
        raise ProviderError(
            f"gliner-decide response missing task {task!r} result object"
        )
    label = entry.get("label")
    if not isinstance(label, str) or not label:
        raise ProviderError(
            f"gliner-decide task {task!r} returned no label: {entry!r}"
        )
    confidence = entry.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        raise ProviderError(
            f"gliner-decide task {task!r} returned no numeric confidence: "
            f"{entry!r}"
        )
    value = float(confidence)
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        # A probability outside 0..1 (or NaN, or infinite) is drift,
        # not a measurement. Clamping it into range would invent
        # the number the artifact reports, so it is terminal.
        raise ProviderError(
            f"gliner-decide task {task!r} returned confidence "
            f"{confidence!r} outside 0..1: {entry!r}"
        )
    return label, value


def _task_shapes(tasks: dict[str, Any]) -> dict[str, Any]:
    """Transcript-safe summary: task names and label counts, no content."""
    return {name: {"labels": len(spec)} for name, spec in tasks.items()}
