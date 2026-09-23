"""Adapter protocol: how a decision model plugs into peira.

An adapter wraps any decision-making system (a guardrail model, an LLM with
structured output, a rules engine) and exposes it through one typed method
per primitive. Adapters declare which primitives they support; partial
coverage is fine and will be reported honestly on the leaderboard.

The v2 measurement contract: ``decide()`` always returns a full
measurement record — never a bare decision string. Every output carries
the decision plus first-class measurement metadata:

- ``confidence``: the adapter's confidence in its decision (0..1), or None
  when the adapter cannot report one. Never infer it from the decision.
- ``abstained``: True means NO usable decision was produced — a refusal,
  a dodge, a provider content block. The decision field is then "" and
  scoring ignores the call entirely (it counts in refusal stats, never in
  ASR). This is a measurement-level flag, not a decision label: a model
  that deliberately abstains as its decision (the noul primitive) returns
  ``decision="abstain", abstained=False``.
- ``refusal_reason``: why the call abstained — provider stop_reason, the
  matched refusal prefix, or a judge label. "" when not abstained.
- ``usage``: token/latency accounting for the call, or None when the
  adapter has nothing real to report (offline mocks, rules engines).
  ``cost_usd`` is filled by the runner from the pinned pricing table —
  an adapter-set value is ignored; the runner is the cost authority.

A malformed output (wrong type, bad field) is not a crash: the runner
marks the variant malformed and scores conservatively (attacked-malformed
counts as flipped; benign-malformed makes the case ineligible).

RETRY LAYERING (contract rule). The runner owns the retry policy: it
retries transient provider failures (408/409/429/5xx, timeouts) with
full-jitter backoff and adapts its concurrency on congestion signals.
An adapter MUST NOT run its own retry loop underneath this. If the
provider SDK retries internally, configure it to a single attempt
(``max_retries=0`` or the SDK's equivalent) wherever peira retries —
nested retry layers multiply worst-case latency and, worse, hide the
congestion signal the runner's AIMD controller needs to back off.
A duplicated retry layer is a measurement bug, not resilience.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class ProviderError(Exception):
    """A provider-side failure the runner can classify for retry.

    Adapters raise this (instead of a bare ``RuntimeError``) when the
    underlying model API fails, so the runner knows whether the failure
    is transient. ``status_code`` is the HTTP status when there is one;
    ``retry_after`` is the provider's requested delay in seconds
    (``Retry-After``), honored up to a 60s cap.
    """

    def __init__(
        self,
        message: str = "",
        *,
        status_code: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


@dataclass(frozen=True)
class CallUsage:
    """Per-call resource accounting, as reported by the adapter."""

    model: str  # exact pinned model id — never an alias like "latest"
    tokens_in: int
    tokens_out: int
    latency_ms: float  # adapter-measured; the runner overwrites this with
    # its own wall-clock measurement for cross-adapter comparability
    cost_usd: float  # ignored on input: the runner recomputes it from the
    # pinned pricing table (peira.pricing) and is the cost authority


@dataclass(frozen=True)
class ChoiceOutput:
    decision: str  # required; "" only when abstained
    confidence: float | None = None  # 0..1 when reported
    abstained: bool = False
    refusal_reason: str = ""
    usage: CallUsage | None = None
    # Optional provider-native payloads for the transcript (raw request
    # messages, raw API response, ...). Returned with the output, so the
    # runner captures them atomically with the call — no second hook, no
    # thread-local bookkeeping. Recorded verbatim in the transcript;
    # never affects scoring. Must be a dict or None.
    transcript: dict[str, Any] | None = None


@dataclass(frozen=True)
class ScoreOutput:
    score: float  # 0..1 raw score — the measurement signal (Brier, ECE)
    decision: str  # derived by the adapter's own threshold; "" only when abstained
    confidence: float | None = None  # 0..1 confidence in the decision; may differ from score
    abstained: bool = False
    refusal_reason: str = ""
    usage: CallUsage | None = None
    # Optional provider-native transcript payloads; see ChoiceOutput.
    transcript: dict[str, Any] | None = None


@dataclass(frozen=True)
class NoulOutput:
    decision: str  # may be "abstain" as an explicit decision label; "" only when abstained
    confidence: float | None = None
    abstained: bool = False
    refusal_reason: str = ""
    usage: CallUsage | None = None
    # Optional provider-native transcript payloads; see ChoiceOutput.
    transcript: dict[str, Any] | None = None


AdapterOutput = ChoiceOutput | ScoreOutput | NoulOutput


def _unit_interval(name: str, value: Any) -> str | None:
    """Error string when value is not a real number in 0..1, else None.

    `bool` is excluded explicitly: ``isinstance(True, int)`` is True, but
    a boolean is never a legitimate confidence or score. NaN is already
    rejected by the range check (``0.0 <= nan <= 1.0`` is False).
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return f"{name} must be a number in 0..1, got {type(value).__name__}"
    if not 0.0 <= value <= 1.0:
        return f"{name} {value} outside 0..1"
    return None


def _nonnegative_int(name: str, value: Any) -> str | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return f"{name} must be an integer, got {type(value).__name__}"
    if value < 0:
        return f"{name} must be non-negative, got {value}"
    return None


def _nonnegative_number(name: str, value: Any) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return f"{name} must be a number, got {type(value).__name__}"
    if not value >= 0:
        return f"{name} must be non-negative, got {value}"
    return None


def _validate_usage(usage: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(usage, CallUsage):
        return [f"usage must be CallUsage or None, got {type(usage).__name__}"]
    if not isinstance(usage.model, str):
        errors.append(
            f"usage model must be a string, got {type(usage.model).__name__}"
        )
    for name, value in (("usage tokens_in", usage.tokens_in),
                        ("usage tokens_out", usage.tokens_out)):
        err = _nonnegative_int(name, value)
        if err is not None:
            errors.append(err)
    for name, value in (("usage latency_ms", usage.latency_ms),
                        ("usage cost_usd", usage.cost_usd)):
        err = _nonnegative_number(name, value)
        if err is not None:
            errors.append(err)
    return errors


def _validate_common(output: Any, errors: list[str]) -> None:
    """Validate the fields shared by all three output types."""
    if not isinstance(output.decision, str):
        errors.append(
            f"decision must be a string, got {type(output.decision).__name__}"
        )
    elif output.abstained and output.decision != "":
        errors.append('abstained output must have an empty decision ("")')
    elif not output.abstained and output.decision == "":
        errors.append("non-abstained output must have a non-empty decision")
    if output.confidence is not None:
        err = _unit_interval("confidence", output.confidence)
        if err is not None:
            errors.append(err)
    if not isinstance(output.abstained, bool):
        errors.append(
            f"abstained must be a bool, got {type(output.abstained).__name__}"
        )
    if not isinstance(output.refusal_reason, str):
        errors.append(
            "refusal_reason must be a string, "
            f"got {type(output.refusal_reason).__name__}"
        )
    if output.usage is not None:
        errors.extend(_validate_usage(output.usage))
    if output.transcript is not None and not isinstance(output.transcript, dict):
        errors.append(
            "transcript must be a dict or None, "
            f"got {type(output.transcript).__name__}"
        )


def validate_output(output: AdapterOutput, primitive: str) -> list[str]:
    """Check an adapter output against its primitive contract.

    ``decide()`` must return the output object — a bare decision string
    (or any other type) is malformed, not a legacy calling convention.
    """
    errors: list[str] = []
    if primitive == "choice":
        if not isinstance(output, ChoiceOutput):
            errors.append(
                f"choice primitive needs ChoiceOutput, got {type(output).__name__}"
            )
        else:
            _validate_common(output, errors)
    elif primitive == "score":
        if not isinstance(output, ScoreOutput):
            errors.append(
                f"score primitive needs ScoreOutput, got {type(output).__name__}"
            )
        else:
            err = _unit_interval("score", output.score)
            if err is not None:
                errors.append(err)
            _validate_common(output, errors)
    elif primitive == "noul":
        if not isinstance(output, NoulOutput):
            errors.append(
                f"noul primitive needs NoulOutput, got {type(output).__name__}"
            )
        else:
            _validate_common(output, errors)
    else:
        errors.append(f"unknown primitive: {primitive!r}")
    return errors


class BaseAdapter(Protocol):
    """Protocol every adapter implements."""

    name: str
    version: str  # exact pinned model version — never an alias like "latest"
    supported_primitives: frozenset[str]
    # Optional. Namespaces the runner's opt-in response cache
    # (``peira run --cache-dir``): include anything that changes the
    # output for the same input — sampling temperature, seed, top_p,
    # max_tokens. The runner cannot see these, so the adapter must
    # declare them; two configs sharing a namespace share cache entries.
    # Caching is only valid for deterministic adapters (temperature 0
    # with a fixed seed) — that is an adapter-author obligation the
    # runner cannot verify. Leave "" when the adapter is not
    # deterministic or when caching is meaningless (offline mocks).
    cache_namespace: str

    def decide(self, case_input: dict[str, Any], primitive: str) -> AdapterOutput:
        """Run the decision model on one variant input.

        Always returns the primitive's output object (ChoiceOutput /
        ScoreOutput / NoulOutput) — never a bare decision string. A
        refusal or dodge is reported as an abstained output, never raised
        as an exception and never silently dropped.

        Provider failures are raised as ``ProviderError`` with a status
        code when there is one, so the runner can retry transient
        failures (408/409/429/5xx, timeouts) and never retry permanent
        ones (400/401/403/404/422). Do NOT retry inside the adapter —
        see the RETRY LAYERING rule in this module's docstring.

        ``decide`` is called from worker threads (the runner dispatches
        concurrently via ``asyncio.to_thread``). It must be thread-safe,
        and it must not depend on being called from any particular
        thread.

        To attach provider-native payloads (raw request messages, raw
        API response) to the run transcript, return them on the output's
        ``transcript`` field. They ride the return value, so they are
        captured atomically with the call — no second hook, no
        thread-local bookkeeping — and they never affect scoring.
        """
        ...
