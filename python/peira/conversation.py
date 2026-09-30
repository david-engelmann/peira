"""Conversational evaluation suite: schema, gates, and runner (R-01).

The conversational suite is a SEPARATE suite, not turn sequences inside
v2: it has its own schema, runner, metrics, flip definitions, and
blind-holdout machinery, while sharing the single-shot suite's call
machinery (timeouts, retries, response cache, transcript sink, pricing,
budgets, pseudonymous call contexts), validation gates, artifacts, and
report tooling where valid. Conversational results are never blended
with the paired single-decision v1/v2 numbers.

A conversational case is a paired benign/attacked pair of multi-turn
trajectories. Each trajectory is an ordered list of turns. ``user``
turns are executed through the adapter in order; ``assistant`` turns
are fixed, authored history spliced into the conversation without an
adapter call. Only the FINAL user turn's decision is scored, with the
exact single-shot pair semantics (eligibility, flip, abstention and
malformed handling): a :class:`ConversationResult` is the scored
final-turn pair plus its turn history, so every metric, artifact, and
report path works unchanged.

Blind execution: the adapter sees only the conversation content, the
decision options, the turn index, and a final-turn flag, plus an opaque
per-turn call id. No case id, no family, no arm, no gold labels, no
attack annotations, and no holdout status ever cross the adapter
boundary. Turn payloads are built by :func:`_turn_payload`, and the
no-gold-leakage property is pinned by unit tests.

Adapter capability contract: conversational capability is explicit.
Adapters implement ``decide_turn(turn_input, primitive, context)``
where ``turn_input`` is the sealed turn payload — exactly
``messages`` (the full history, a list of ``{"role", "content"}``
dicts ending with the current user turn), ``options`` (the decision
vocabulary), ``turn_index`` (the 0-based executed-turn index within
the arm), and ``is_final_turn``. An adapter that only implements the
single-shot ``decide()`` cannot run this suite: the runner rejects it
with an actionable error instead of silently flattening the
conversation into one prompt, because that would measure a different
thing while pretending it was multi-turn. Every executed turn must
return a primitive-valid output; intermediate turns are recorded but
unscored.
"""

from peira.conversation_gates import (
    ConversationGateResult,
    run_conversation_gates,
)
from peira.conversation_metrics import (
    summarize_conversation,
    summarize_conversation_artifact,
)
from peira.conversation_runner import (
    ConversationResult,
    _conversation_case_cost_usd,
    _conversation_turn_dispatch_index,
    _invoke_adapter_turn,
    _record_to_history_text,
    _require_conversational_adapter,
    _run_conversation_case_async,
    _scoring_case,
    _turn_payload,
    run_conversation_case,
    run_conversation_suite,
    validate_conversation_partial,
)
from peira.conversation_schema import (
    CONVERSATION_DISPATCH_STRIDE,
    CONVERSATION_JSON_SCHEMA,
    CONVERSATION_ROLES,
    CONVERSATION_SUITE_ID,
    KNOWN_CONVERSATION_FAMILIES,
    MAX_TURNS_PER_ARM,
    AttackedConversation,
    BenignConversation,
    ConversationTurn,
    ConversationalCase,
    load_conversation_cases,
    validate_conversation_dict,
)

__all__ = [
    "CONVERSATION_DISPATCH_STRIDE",
    "CONVERSATION_JSON_SCHEMA",
    "CONVERSATION_ROLES",
    "CONVERSATION_SUITE_ID",
    "KNOWN_CONVERSATION_FAMILIES",
    "MAX_TURNS_PER_ARM",
    "AttackedConversation",
    "BenignConversation",
    "ConversationGateResult",
    "ConversationResult",
    "ConversationTurn",
    "ConversationalCase",
    "_conversation_case_cost_usd",
    "_conversation_turn_dispatch_index",
    "_invoke_adapter_turn",
    "_record_to_history_text",
    "_require_conversational_adapter",
    "_run_conversation_case_async",
    "_scoring_case",
    "_turn_payload",
    "load_conversation_cases",
    "run_conversation_case",
    "run_conversation_gates",
    "run_conversation_suite",
    "summarize_conversation",
    "summarize_conversation_artifact",
    "validate_conversation_dict",
    "validate_conversation_partial",
]
