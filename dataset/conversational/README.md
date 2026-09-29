# conversational suite

**Status.** R-01 schema and runner only. No cases ship yet.

This directory will host peira's conversational evaluation suite.
It is a separate suite, not turn sequences inside v2. Cases are
paired benign and attacked multi-turn trajectories, executed turn by
turn through the adapter. Only the final turn decision is scored,
with the same pair semantics as the single-shot suites.

The schema, runner, and gates live in `python/peira/conversation.py`.
The full specification is `docs/Conversational-Suite.md`.

The first attack families to land here are `multi_turn_escalation`
and `decision_splitting`. Neither is authored yet. The `cases/`
subdirectory will appear with the first family drop.
