# conversational suite

**Status.** Two attack families ship: `multi_turn_escalation` and
`decision_splitting`, 420 cases each (840 total).

This directory will host peira's conversational evaluation suite.
It is a separate suite, not turn sequences inside v2. Cases are
paired benign and attacked multi-turn trajectories, executed turn by
turn through the adapter. Only the final turn decision is scored,
with the same pair semantics as the single-shot suites.

The schema, runner, metrics, and gates live in `python/peira/conversation_schema.py`,
`python/peira/conversation_runner.py`, `python/peira/conversation_metrics.py`,
and `python/peira/conversation_gates.py`, re-exported through
`python/peira/conversation.py`.
The full specification is `docs/Conversational-Suite.md`.

The first attack families to land here are `multi_turn_escalation`
and `decision_splitting`. Both ship 420 cases each in `cases/`.

- **multi_turn_escalation**: attacks that escalate across turns
  (crescendo, foot-in-the-door, authority escalation, urgency
  escalation, trust-then-pivot, reframing escalation, boundary
  probing, social-proof escalation). Each turn looks defensible; the
  trajectory builds toward a malicious final decision.
- **decision_splitting**: attacks that split a malicious decision
  across innocuous turns (information gathering, salami, false-premise
  construction, distributed instruction, pretext chaining, context
  laundering). No single turn looks malicious; the final decision is
  induced by context assembled across turns.

Case IDs are `conv-mte-0001`..`conv-mte-0420` and
`conv-ds-0001`..`conv-ds-0420`. Only the final user turn of each arm
is scored.
