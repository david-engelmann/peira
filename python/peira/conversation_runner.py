"""Conversational suite: turn runner and results (R-01).

The ``decide_turn`` adapter contract, turn-by-turn sync/async runners
on the shared suite driver, the scored final-turn-pair
:class:`ConversationResult`, and conversational resume. Part of the
conversational suite; see ``peira.conversation`` for the suite
overview.
"""

from __future__ import annotations

import asyncio
import dataclasses
import functools
from dataclasses import dataclass, field
from pathlib import Path
import time
from typing import Any, Callable

from peira.adapters.base import CallContext
from peira.conversation_schema import (
    CONVERSATION_DISPATCH_STRIDE,
    CONVERSATION_SUITE_ID,
    MAX_TURNS_PER_ARM,
    ConversationTurn,
    ConversationalCase,
)
from peira.metrics import CallRecord, PerCaseResult

# ---------------------------------------------------------------------------
# Adapter interop: the decide_turn contract
# ---------------------------------------------------------------------------


def _turn_payload(
    messages: list[dict[str, str]],
    options: list[str],
    turn_index: int,
    is_final_turn: bool,
) -> dict[str, Any]:
    """Build the adapter-visible payload for one executed turn.

    This is the blindness boundary: the payload carries the
    conversation content, the decision options, the turn index, and a
    final-turn flag. No case id, no family, no arm, no gold labels, no
    attack annotations, no holdout status. Anything not listed here
    does not cross.
    """
    return {
        "messages": [dict(m) for m in messages],
        "options": list(options),
        "turn_index": turn_index,
        "is_final_turn": is_final_turn,
    }


def _require_conversational_adapter(adapter: Any) -> None:
    """Fail fast when the adapter cannot run conversations.

    Conversational capability is explicit and validated up front: an
    adapter without ``decide_turn`` is rejected with an actionable
    error instead of being silently flattened into single-shot calls.
    Third-party adapters (``SubprocessAdapter``) expose the async
    ``adecide_turn``; the runner drives it instead of the sync entry
    point.
    """
    from peira.adapters.subprocess import (  # noqa: PLC0415
        SubprocessAdapter,
    )

    if isinstance(adapter, SubprocessAdapter):
        return
    if not callable(getattr(adapter, "decide_turn", None)):
        raise ValueError(
            f"adapter {getattr(adapter, 'name', adapter)!r} cannot run "
            "the conversational suite: implement "
            "decide_turn(turn_input, primitive, context) "
            "(see docs/Conversational-Suite.md)"
        )


def _invoke_adapter_turn(
    adapter: Any,
    turn_input: dict[str, Any],
    primitive: str,
    context: CallContext,
    _exec_ms: list[float] | None = None,
    _exec_start: list[float] | None = None,
) -> tuple[Any, dict[str, Any] | None]:
    """Run one conversation turn through the adapter.

    The adapter receives the sealed turn payload — exactly the keys
    ``messages``, ``options``, ``turn_index``, and ``is_final_turn`` —
    plus the primitive and the opaque call context. Provider-native
    payloads ride the output's ``transcript`` field, same as the
    single-shot path.
    """
    decide_turn = getattr(adapter, "decide_turn", None)
    if not callable(decide_turn):
        # Defense in depth: the suite entry points check capability up
        # front with _require_conversational_adapter, so reaching here
        # means a direct internal call with a wrong adapter.
        raise TypeError(
            f"adapter {getattr(adapter, 'name', adapter)!r} does not "
            "implement decide_turn(turn_input, primitive, context)"
        )
    if _exec_ms is None:
        output = decide_turn(turn_input, primitive, context)
    else:
        if _exec_start is not None:
            _exec_start.append(time.perf_counter())
        t0 = time.perf_counter()
        try:
            output = decide_turn(turn_input, primitive, context)
        finally:
            _exec_ms.append((time.perf_counter() - t0) * 1000.0)
    raw = getattr(output, "transcript", None)
    if raw is not None and not isinstance(raw, dict):
        raw = None
    return output, raw


# Marker read by peira.runner._ainvoke_subprocess_adapter to select
# adecide_turn over adecide for third-party adapters (a module-level
# import would cycle: conversation_runner imports runner).
_invoke_adapter_turn._peira_turn_driver = True


def _record_to_history_text(record: CallRecord, primitive: str) -> str:
    """Render a sealed turn record as the next assistant message.

    Derived from the sealed record, never from adapter internals: the
    text is what the conversation history carries forward.
    """
    if record.malformed:
        return "<malformed output>"
    if record.abstained:
        reason = record.refusal_reason or "no reason given"
        return f"<abstained: {reason}>"
    if primitive == "score" and record.score is not None:
        return f"{record.decision} (score {record.score:.3f})"
    return record.decision


# ---------------------------------------------------------------------------
# Results: the scored final-turn pair plus its turn history
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConversationResult(PerCaseResult):
    """A scored conversational case.

    The base-class fields (``benign``/``attacked`` call records,
    ``flipped``, ``eligible``, ``ineligibility_reason``) describe the
    FINAL-turn pair, scored with the exact single-shot pair semantics.
    ``benign_turns``/``attacked_turns`` carry every executed turn's
    record (final turn included) for drill-down. :meth:`to_dict`
    serializes the artifact entry shape (strict base fields plus the
    turn lists under the suite-namespaced ``conversational_turns``
    field), and every metric/sort/artifact path that reads the base
    fields works unchanged.
    """

    benign_turns: list[CallRecord] = field(default_factory=list)
    attacked_turns: list[CallRecord] = field(default_factory=list)
    # EB-15: True when an attacker budget (max_attacker_rounds or
    # attacker_token_budget) truncated the attacked arm before its
    # authored trajectory finished. The scored pair is then (benign
    # final, last executed attacked turn): the case is still scored,
    # but the exhaustion is a first-class outcome, not silent
    # truncation. Omitted from the artifact dict when False so
    # pre-EB-15 artifacts round-trip byte-identically.
    attack_budget_exhausted: bool = False

    @classmethod
    def from_scored(
        cls,
        scored: PerCaseResult,
        benign_turns: list[CallRecord],
        attacked_turns: list[CallRecord],
        attack_budget_exhausted: bool = False,
    ) -> "ConversationResult":
        return cls(
            case_id=scored.case_id,
            family=scored.family,
            severity=scored.severity,
            primitive=scored.primitive,
            benign=scored.benign,
            attacked=scored.attacked,
            flipped=scored.flipped,
            eligible=scored.eligible,
            ineligibility_reason=scored.ineligibility_reason,
            benign_turns=list(benign_turns),
            attacked_turns=list(attacked_turns),
            attack_budget_exhausted=attack_budget_exhausted,
        )

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ConversationResult":
        base = PerCaseResult.from_dict(d)
        # Artifact entries nest the turn records under the
        # suite-namespaced ``conversational_turns`` field; accept the
        # flat in-memory shape too (dataclasses.asdict of a live
        # result).
        turns = d.get("conversational_turns") or {}
        benign_turn_dicts = turns.get(
            "benign_turns", d.get("benign_turns", [])
        )
        attacked_turn_dicts = turns.get(
            "attacked_turns", d.get("attacked_turns", [])
        )
        # The resume-partial path treats entries as hostile input: a
        # wrong-typed flag must fail here, not coerce silently.
        exhausted = d.get("attack_budget_exhausted", False)
        if not isinstance(exhausted, bool):
            raise ValueError(
                "bad attack_budget_exhausted: expected boolean, "
                f"got {type(exhausted).__name__}"
            )
        return cls.from_scored(
            base,
            [CallRecord.from_dict(r) for r in benign_turn_dicts],
            [CallRecord.from_dict(r) for r in attacked_turn_dicts],
            attack_budget_exhausted=exhausted,
        )

    def to_dict(self) -> dict[str, Any]:
        """Artifact entry shape: strict base fields plus the sealed
        turn records under the suite-namespaced ``conversational_turns``
        field (see RunArtifact._RESULT_OPTIONAL).

        ``attack_budget_exhausted`` is emitted only when True: the
        Rust core skips serializing a false flag, so omitting it keeps
        the two backends' canonical JSON (and analysis locks)
        byte-identical.
        """
        d = dataclasses.asdict(self)
        d["conversational_turns"] = {
            "benign_turns": d.pop("benign_turns"),
            "attacked_turns": d.pop("attacked_turns"),
        }
        exhausted = d.pop("attack_budget_exhausted")
        if exhausted:
            d["attack_budget_exhausted"] = True
        return d


def _conversation_case_cost_usd(result: PerCaseResult) -> float:
    """Total priced spend for one conversational case: all turn records.

    Accepts the base type so it plugs into the shared budget/spend
    machinery; conversational results always carry the turn lists.
    """
    total = 0.0
    turns: list[CallRecord] = []
    if isinstance(result, ConversationResult):
        turns = result.benign_turns + result.attacked_turns
    else:  # pragma: no cover - defensive; the suite only emits these
        turns = [result.benign, result.attacked]
    for rec in turns:
        if rec.usage is not None:
            total += rec.usage.cost_usd
    return total


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def _scoring_case(case: ConversationalCase):
    """Single-shot shim for scoring the final-turn pair.

    The final-turn pair is scored with the exact single-shot pair
    semantics (eligibility, flip, abstention/malformed handling),
    including the Rust dispatch: only the labels the scorer reads are
    carried over, never the trajectory.
    """
    from peira.schema import AttackedVariant, BenignVariant, Case

    return Case(
        case_id=case.case_id,
        family=case.family,
        primitive=case.primitive,
        severity=case.severity,
        benign=BenignVariant(
            input={},
            expected_decision=case.benign.expected_decision,
            expected_score=case.benign.expected_score,
            positive_decision=case.benign.positive_decision,
        ),
        attacked=AttackedVariant(
            input={},
            target_decision=case.attacked.target_decision,
        ),
        notes="conversational scoring shim: final-turn pair only",
    )


def _conversation_turn_dispatch_index(
    dispatch_base: int, arm: str, turn_index: int
) -> int:
    """Dispatch index for one executed turn.

    ``dispatch_base`` is the case's stride-derived base (see
    :func:`run_conversation_suite`): benign turn t uses base + 2t,
    attacked turn t uses base + 2t + 1. Suite-position-derived, never
    run order, so resumed runs re-derive identical indices.
    """
    arm_offset = 1 if arm == "attacked" else 0
    return dispatch_base + 2 * turn_index + arm_offset


def _validate_attack_budgets(
    max_attacker_rounds: int | None,
    attacker_token_budget: int | None,
) -> None:
    """Validate EB-15 attacker budgets; raise ValueError when unusable.

    Budgets are opt-in (None disables); when given they must be
    positive ints. A bool is not an int here (``True`` would silently
    mean one round), and zero or negative budgets would truncate the
    attacked arm before its first turn, which is a configuration
    error, not a measurement.
    """
    for name, value in (
        ("max_attacker_rounds", max_attacker_rounds),
        ("attacker_token_budget", attacker_token_budget),
    ):
        if value is None:
            continue
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < 1
        ):
            raise ValueError(
                f"{name} must be a positive int or None, "
                f"got {value!r}"
            )


def _attacked_tokens(records: list[CallRecord]) -> int:
    """Cumulative attacker tokens (in + out) over executed turns."""
    total = 0
    for rec in records:
        if rec.usage is not None:
            total += rec.usage.tokens_in + rec.usage.tokens_out
    return total


# ---------------------------------------------------------------------------
# Per-case execution
# ---------------------------------------------------------------------------


async def _run_conversation_case_async(
    adapter: Any,
    adapter_version: str,
    case: ConversationalCase,
    seed: int,
    dispatch_base: int,
    pricing_table: dict[str, Any],
    manifest_sha256: str,
    *,
    controller: Any,
    max_attempts: int,
    max_concurrency: int,
    call_timeout: float | None,
    cache: Any | None,
    transcript: Any | None,
    run_nonce: str,
    sampling_config: dict[str, Any] | None = None,
    max_attacker_rounds: int | None = None,
    attacker_token_budget: int | None = None,
) -> ConversationResult:
    """Drive one conversational case, turn by turn.

    Same signature as :func:`peira.runner._run_case_async`, so it
    plugs into the shared suite driver. Benign arm runs before the
    attacked arm, sequentially; concurrency happens across cases.
    Within an arm, executed (user) turns run in order, each through
    the full call machinery (retries, timeouts, cache, transcript,
    pricing) via the ``invoke`` hook; fixed assistant turns are
    spliced into the history without a call; each model response is
    appended to the history the next turn sees. Only the final turn
    of each arm is scored.

    EB-15 attacker budgets: ``max_attacker_rounds`` caps the executed
    user turns of the attacked arm; ``attacker_token_budget`` caps its
    cumulative tokens (in + out). The turn that reaches a budget is
    kept (it was executed and paid for); the arm stops before the
    next turn. The benign arm is the control and always runs fully.
    A truncated attacked arm seals
    ``attack_budget_exhausted=True`` on the result; the scored pair
    is then (benign final, last executed attacked turn).
    """
    _validate_attack_budgets(max_attacker_rounds, attacker_token_budget)
    # Local imports: runner imports nothing from this module, so there
    # is no cycle, and importing this module never requires the
    # runner's asyncio machinery at module scope.
    from peira.concurrency import cache_key
    from peira.runner import (
        _pseudonymous_call_id,
        _record_call_async,
        _score_pair,
        _TrialInfo,
    )
    from peira.sampling import with_sampling_namespace

    namespace = str(getattr(adapter, "cache_namespace", "") or "")
    # R-04: fold the effective sampling config into the cache namespace
    # so the key covers the values actually sent on the wire
    # (lm-eval-harness #3881 class). Adapters with no sampling knobs
    # set keep their namespace unchanged, so their existing cache
    # entries keep working.
    namespace = with_sampling_namespace(namespace, sampling_config)
    expected = case.benign.expected_decision

    def key_for(
        payload: dict[str, Any], arm: str, turn_index: int
    ) -> str | None:
        if cache is None:
            return None
        return cache_key(
            adapter_name=adapter.name,
            adapter_version=adapter_version,
            cache_namespace=namespace,
            primitive=case.primitive,
            variant=f"{arm}/turn{turn_index}",
            case_id=case.case_id,
            case_input=payload,
            manifest_sha256=manifest_sha256,
        )

    async def run_arm(
        arm_name: str, turns: list[ConversationTurn], options: list[str]
    ) -> tuple[list[CallRecord], bool]:
        """Execute one arm's turns in order.

        Fixed assistant turns are spliced verbatim into the history —
        they are authored scene-setting, not model output — while each
        executed user turn appends the user message and then the
        model's generated response. An authored assistant turn may
        therefore sit adjacent to a generated response; both are
        assistant-role messages and the history is a message list, not
        a strict alternation.

        Returns the turn records plus whether an attacker budget
        truncated this arm (only ever True for the attacked arm).
        """
        history: list[dict[str, str]] = []
        records: list[CallRecord] = []
        executed = 0
        user_turns = [t for t in turns if t.role == "user"]
        budgeted = arm_name == "attacked" and (
            max_attacker_rounds is not None
            or attacker_token_budget is not None
        )
        for turn in turns:
            if turn.role == "assistant":
                # Fixed, authored history: spliced in, never executed.
                history.append(
                    {"role": "assistant", "content": turn.content}
                )
                continue
            is_final = executed == len(user_turns) - 1
            user_message = {"role": "user", "content": turn.content}
            messages = history + [user_message]
            payload = _turn_payload(
                messages, options, executed, is_final
            )
            dispatch_index = _conversation_turn_dispatch_index(
                dispatch_base, arm_name, executed
            )
            context = CallContext(
                call_id=_pseudonymous_call_id(
                    run_nonce, seed, dispatch_index
                )
            )
            trial = _TrialInfo(
                case_id=case.case_id,
                arm=arm_name,  # type: ignore[arg-type]
                expected_decision=expected,
                target_decision=(
                    None
                    if arm_name == "benign"
                    else case.attacked.target_decision
                ),
            )
            record = await _record_call_async(
                adapter,
                adapter_version,
                payload,
                case.primitive,
                context,
                trial,
                seed,
                dispatch_index,
                pricing_table,
                controller=controller,
                max_attempts=max_attempts,
                max_concurrency=max_concurrency,
                call_timeout=call_timeout,
                cache=cache,
                cache_key_str=key_for(payload, arm_name, executed),
                transcript=transcript,
                invoke=_invoke_adapter_turn,
                sampling_config=sampling_config,
            )
            records.append(record)
            history.append(user_message)
            history.append(
                {
                    "role": "assistant",
                    "content": _record_to_history_text(
                        record, case.primitive
                    ),
                }
            )
            executed += 1
            if budgeted and (
                (
                    max_attacker_rounds is not None
                    and executed >= max_attacker_rounds
                )
                or (
                    attacker_token_budget is not None
                    and _attacked_tokens(records) >= attacker_token_budget
                )
            ):
                # The budget fired: stop before the next turn. The
                # turn that reached the budget is kept.
                break
        exhausted = budgeted and executed < len(user_turns)
        return records, exhausted

    benign_records, _ = await run_arm(
        "benign", case.benign.turns, case.benign.options
    )
    attacked_records, attack_exhausted = await run_arm(
        "attacked", case.attacked.turns, case.attacked.options
    )
    scored = _score_pair(
        _scoring_case(case), benign_records[-1], attacked_records[-1]
    )
    return ConversationResult.from_scored(
        scored,
        benign_records,
        attacked_records,
        attack_budget_exhausted=attack_exhausted,
    )


def run_conversation_case(
    adapter: Any,
    case: ConversationalCase,
    seed: int = 0,
    dispatch_base: int = 0,
    pricing_table: dict[str, Any] | None = None,
    run_nonce: str | None = None,
    max_attacker_rounds: int | None = None,
    attacker_token_budget: int | None = None,
) -> ConversationResult:
    """Run one conversational case synchronously (debugging aid).

    Mirrors :func:`peira.runner.run_case`: strictly sequential, no
    concurrency, retries, cache, or transcript. Every turn goes
    through the adapter's turn entry point. EB-15 attacker budgets
    (``max_attacker_rounds``, ``attacker_token_budget``) truncate the
    attacked arm exactly as in the async path; the benign arm always
    runs fully.
    """
    _require_conversational_adapter(adapter)
    _validate_attack_budgets(max_attacker_rounds, attacker_token_budget)
    from peira.pricing import load_pricing_table
    from peira.runner import (
        _pseudonymous_call_id,
        _record_call,
        _score_pair,
        new_run_nonce,
    )

    nonce = run_nonce if run_nonce is not None else new_run_nonce()
    table = pricing_table if pricing_table is not None else load_pricing_table()

    def run_arm(
        arm_name: str, turns: list[ConversationTurn], options: list[str]
    ) -> tuple[list[CallRecord], bool]:
        """Execute one arm's turns in order (sync; same semantics as
        the async path: authored assistant turns splice verbatim into
        the history, executed user turns append the user message and
        the model's generated response). Returns the turn records
        plus whether an attacker budget truncated this arm."""
        history: list[dict[str, str]] = []
        records: list[CallRecord] = []
        executed = 0
        user_turns = [t for t in turns if t.role == "user"]
        budgeted = arm_name == "attacked" and (
            max_attacker_rounds is not None
            or attacker_token_budget is not None
        )
        for turn in turns:
            if turn.role == "assistant":
                history.append(
                    {"role": "assistant", "content": turn.content}
                )
                continue
            is_final = executed == len(user_turns) - 1
            user_message = {"role": "user", "content": turn.content}
            messages = history + [user_message]
            payload = _turn_payload(
                messages, options, executed, is_final
            )
            dispatch_index = _conversation_turn_dispatch_index(
                dispatch_base, arm_name, executed
            )
            context = CallContext(
                call_id=_pseudonymous_call_id(
                    nonce, seed, dispatch_index
                )
            )
            record = _record_call(
                adapter,
                payload,
                case.primitive,
                context,
                seed,
                dispatch_index,
                table,
                invoke=_invoke_adapter_turn,
            )
            records.append(record)
            history.append(user_message)
            history.append(
                {
                    "role": "assistant",
                    "content": _record_to_history_text(
                        record, case.primitive
                    ),
                }
            )
            executed += 1
            if budgeted and (
                (
                    max_attacker_rounds is not None
                    and executed >= max_attacker_rounds
                )
                or (
                    attacker_token_budget is not None
                    and _attacked_tokens(records) >= attacker_token_budget
                )
            ):
                break
        exhausted = budgeted and executed < len(user_turns)
        return records, exhausted

    benign_records, _ = run_arm(
        "benign", case.benign.turns, case.benign.options
    )
    attacked_records, attack_exhausted = run_arm(
        "attacked", case.attacked.turns, case.attacked.options
    )
    scored = _score_pair(
        _scoring_case(case), benign_records[-1], attacked_records[-1]
    )
    return ConversationResult.from_scored(
        scored,
        benign_records,
        attacked_records,
        attack_budget_exhausted=attack_exhausted,
    )


# ---------------------------------------------------------------------------
# Suite driver
# ---------------------------------------------------------------------------


def run_conversation_suite(
    adapter: Any,
    cases: list[ConversationalCase],
    suite: str = CONVERSATION_SUITE_ID,
    dataset_version: str = "0.1.0-conversational",
    progress: Callable[[int, int], None] | None = None,
    already_done: set[str] | None = None,
    prior_results: list[ConversationResult] | None = None,
    partial_path: Path | None = None,
    checkpoint_every: int = 25,
    required_families: list[str] | None = None,
    manifest_sha256: str = "",
    seed: int = 0,
    max_concurrency: int = 8,
    max_attempts: int = 3,
    call_timeout: float | None = 300.0,
    cache_dir: Path | str | None = None,
    transcript_path: Path | str | None = None,
    config_extra: dict[str, Any] | None = None,
    rlimit_cpu_seconds: float | None = None,
    rlimit_as_mb: float | None = None,
    rlimit_fsize_mb: float | None = None,
    rlimit_nproc: int | None = None,
    death_log_path: Path | str | None = None,
    run_nonce: str | None = None,
    budget_usd: float | None = None,
    max_tokens_per_call: int | None = None,
    item_timeout: float | None = None,
    run_timeout: float | None = None,
    max_attacker_rounds: int | None = None,
    attacker_token_budget: int | None = None,
):
    """Run a conversational suite through an adapter, concurrently.

    The shared suite driver (:func:`peira.runner.run_suite`) with the
    conversational suite-shape hooks: a wider dispatch stride (each
    case drives up to ``2 * MAX_TURNS_PER_ARM`` calls), the turn-driving
    per-case coroutine, turn-aware spend for the budget gate and totals,
    and the conversational metric summary sealed into the artifact
    (``peira.conversation_metrics.summarize_conversation_artifact``).
    Everything else — concurrency, retries, timeouts, cache,
    transcripts, checkpoints, resume, environment fingerprinting, the
    sealed artifact — is the shared machinery, unchanged.

    EB-15 attacker budgets: ``max_attacker_rounds`` caps the executed
    user turns of each case's attacked arm; ``attacker_token_budget``
    caps its cumulative tokens (in + out). A truncated arm seals
    ``attack_budget_exhausted=True`` on its result (a scored outcome
    class, not silent truncation); the benign arm always runs fully.
    Both budgets are sealed into the artifact config for
    reproducibility.

    The artifact's ``suite`` is ``"conversational"`` (or the override
    passed here): conversational results are namespaced away from the
    v1/v2 numbers by construction.

    ``max_tokens_per_call`` is accepted for signature parity with
    :func:`peira.runner.run_suite` and recorded in the artifact config.
    Enforcement is post-hoc only: over-limit calls are flagged
    ``token_limit_exceeded`` in the transcript (see the R-18 note in
    the shared driver); the turn driver cannot stop a provider
    mid-generation.
    """
    _require_conversational_adapter(adapter)
    _validate_attack_budgets(max_attacker_rounds, attacker_token_budget)
    from peira.runner import run_suite

    # Lazy import: peira.conversation_metrics imports this module's
    # public names, so a module-level import would be circular.
    from peira.conversation_metrics import summarize_conversation_artifact

    # The driver calls run_one_case positionally for the shared
    # leading args and by keyword for the rest: bind the attacker
    # budgets as keywords so the driver signature stays untouched.
    run_one = functools.partial(
        _run_conversation_case_async,
        max_attacker_rounds=max_attacker_rounds,
        attacker_token_budget=attacker_token_budget,
    )
    sealed_extra = dict(config_extra or {})
    sealed_extra["max_attacker_rounds"] = max_attacker_rounds
    sealed_extra["attacker_token_budget"] = attacker_token_budget

    return run_suite(
        adapter,
        cases,  # type: ignore[arg-type]
        suite,
        dataset_version,
        progress=progress,
        already_done=already_done,
        prior_results=prior_results,  # type: ignore[arg-type]
        partial_path=partial_path,
        checkpoint_every=checkpoint_every,
        required_families=required_families,
        manifest_sha256=manifest_sha256,
        seed=seed,
        max_concurrency=max_concurrency,
        max_attempts=max_attempts,
        call_timeout=call_timeout,
        cache_dir=cache_dir,
        transcript_path=transcript_path,
        config_extra=sealed_extra,
        rlimit_cpu_seconds=rlimit_cpu_seconds,
        rlimit_as_mb=rlimit_as_mb,
        rlimit_fsize_mb=rlimit_fsize_mb,
        rlimit_nproc=rlimit_nproc,
        death_log_path=death_log_path,
        run_nonce=run_nonce,
        budget_usd=budget_usd,
        max_tokens_per_call=max_tokens_per_call,
        item_timeout=item_timeout,
        run_timeout=run_timeout,
        dispatch_stride=CONVERSATION_DISPATCH_STRIDE,
        run_one_case=run_one,
        case_cost=_conversation_case_cost_usd,
        result_to_dict=lambda r: r.to_dict(),
        summarize_artifact=summarize_conversation_artifact,
    )


def validate_conversation_partial(
    partial: Any,
    adapter: Any,
    cases: list[ConversationalCase],
    suite: str = CONVERSATION_SUITE_ID,
    dataset_version: str = "0.1.0-conversational",
    manifest_sha256: str = "",
    seed: int = 0,
    budget_usd: float | None = None,
    max_tokens_per_call: int | None = None,
    cache_enabled: bool = False,
    item_timeout: float | None = None,
    run_timeout: float | None = None,
    max_attacker_rounds: int | None = None,
    attacker_token_budget: int | None = None,
) -> tuple[set[str], list[ConversationResult]]:
    """Strictly validate a conversational partial run for --resume.

    Same contract as :func:`peira.runner.validate_partial`, but
    result entries rebuild as :class:`ConversationResult` so the turn
    history survives the resume round-trip. The EB-15 attacker
    budgets are measurement inputs like the timeout budgets: a
    partial recorded under different budgets must not merge into
    this run (a case truncated under one budget might complete under
    another), so they are validated against the sealed config.
    """
    from peira.runner import validate_partial

    for _bname, _bwant in (
        ("max_attacker_rounds", max_attacker_rounds),
        ("attacker_token_budget", attacker_token_budget),
    ):
        _bgot = partial.config.get(_bname)
        if _bgot != _bwant:
            _flag = "--" + _bname.replace("_", "-")
            raise ValueError(
                f"partial run was recorded with {_bname} "
                f"{_bgot!r}, not {_bwant!r}: re-run with the same "
                f"{_flag} or drop --resume"
            )

    return validate_partial(  # type: ignore[return-value]
        partial,
        adapter,
        cases,  # type: ignore[arg-type]
        suite,
        dataset_version,
        manifest_sha256=manifest_sha256,
        seed=seed,
        budget_usd=budget_usd,
        max_tokens_per_call=max_tokens_per_call,
        cache_enabled=cache_enabled,
        item_timeout=item_timeout,
        run_timeout=run_timeout,
        result_from_dict=ConversationResult.from_dict,
    )
