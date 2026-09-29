# Admission rules

Read these before submitting. The leaderboard runs on published rules, and these are the published rules.

## Determinism

Your adapter must be deterministic at a fixed seed. If it cannot be, you report the full distribution across seeds instead. Minimum three seeds, and you publish the run-to-run variance alongside the numbers. No single lucky runs make the board.

## No hand-tuning branches

No per-case or per-family special casing. If your adapter checks case IDs, family names, or anything derived from them to change its behavior, it is out. If we detect an adapter treating specific case IDs differently from the rest of the corpus, the submission is rejected. If the row already published, it is pulled.

## Divisions

Two divisions. The guardrail division and the structured-output LLM baseline division.

You declare your division when you submit. The leaderboard shows both divisions side by side, but the headline ranking does not mix them. A guardrail and a raw LLM baseline are not the same kind of thing, and the board does not pretend they are.

## Baseline context

A guardrail claim is only meaningful against the model it guards. So every guardrail submission must include the underlying LLM's unwrapped baseline on the same cases, run under the same conditions. The board reports the difference. That difference is the guardrail's measurable value-add, and it is the number we care about.

## Submission bundle

Every submission is a run bundle with five parts.

1. The predictions, one row per case.
2. The full run config. Seeds, model identifiers, and every flag that affects the run.
3. The adapter revision SHA. Pinned, not a branch.
4. The dataset version the run used.
5. A signed attestation that these rules were followed. Signing means the submitter is on record. A false attestation is rejected, and the submitter does not submit again.

A submission missing any part does not go on the board.
