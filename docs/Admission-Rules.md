# Admission rules

Read these before submitting. The leaderboard runs on published rules, and these are the published rules.

## Determinism

Your adapter must be deterministic at a fixed seed. If it cannot be, you report the full distribution across seeds instead. Minimum three seeds, and you publish the run-to-run variance alongside the numbers. No single lucky runs make the board.

## No hand-tuning branches

No per-case or per-family special casing. If your adapter checks case IDs, family names, or anything derived from them to change its behavior, it is out. If we detect an adapter treating specific case IDs differently from the rest of the corpus, the submission is rejected. If the row already published, it is pulled.

## Divisions

Two divisions. The guardrail division and the structured-output LLM baseline division.

You declare your division when you submit. Declare it with `peira run --division`,
which seals the declaration into the run artifact config where the analysis lock
covers it. The site ingest rejects any artifact without a declared division. A
submission missing any part does not go on the board.

The leaderboard must show both divisions side by side, but the headline ranking does not mix them. A guardrail and a raw LLM baseline are not the same kind of thing, and the board does not pretend they are. Ranks are dense within each division. Shared social images chart one division at a time and say which.

## Diagnostic tools are not submissions

`peira stability-probe` is a measurement instrument, not a submission path.
It runs a fixed case slice through several trials to measure per-case flip
rates and stability, then writes a standalone probe report plus a
borderline-cases sidecar. The per-trial run artifacts are never written to
disk and carry no division declaration, so they can never reach the site
ingest. Probe outputs do not go on the board, by design. If you want a
number on the leaderboard, submit with `peira run --division`.

## Baseline context

A guardrail claim is only meaningful against the model it guards. So every guardrail submission must include the underlying LLM's unwrapped baseline on the same cases, run under the same conditions. The board must report the difference. That difference is the guardrail's measurable value-add, and it is the number we care about.

## Submission bundle

Every submission is a run bundle with five parts.

1. The predictions, one row per case.
2. The full run config. Seeds, model identifiers, and every flag that affects the run.
3. The adapter revision SHA. Pinned, not a branch.
4. The dataset version the run used.
5. A signed attestation that these rules were followed. Signing means the submitter is on record. A false attestation is rejected, and the submitter does not submit again.

A submission missing any part does not go on the board.

## Model identity

Each leaderboard row is one model measured over one wire, identified by
the pair of `adapter_version` (the model ID, e.g.
`qwen/qwen3-235b-a22b-2507`) and `adapter_name` (the adapter that ran
the measurement). Neither field alone is the identity. Multiple models
may share one adapter implementation (for example, all OpenRouter-routed
models use the `openrouter-structured` adapter), and one model may be
measured by more than one adapter (for example, a chat completions
adapter and a decisions API adapter reporting the same model ID). The
board dedupes by the pair, so each model-and-wire measurement appears
exactly once. Every row carries a wire label naming its adapter, so two
rows for one model stay distinguishable.

The board shows each entry's latest full run. A probe run that never
covered the benchmark (fewer recorded cases than the coverage gates
require, or a required family it never attempted) does not displace an
earlier full run of the same entry. A full run that fails a quality gate
stands as the entry's result and is shown as not ranked, with the
reason. Its numbers are printed in the same table as the ranked models,
malformed response rate included, so a result is visible even when it
carries no rank.

Board counts of models count distinct model IDs. A summary that
states how many models were tested, how the field splits between
ranked and flagged, or how many models stand tied at the top
counts each model ID once, however many wires measured it, and
a model counts as ranked when at least one of its
measurements holds a rank. Ranks themselves are per measurement. A
card rank states the standing of its own measurement among the
ranked entries, so one model can carry two ranked cards with two
different ranks.

## Tie bands

Ranked rows follow their attack success rate point estimates, including
inside a tie band. A tie band is a run of consecutive ranked rows whose
95% confidence intervals have a common intersection. Every pair of
intervals in the band must overlap. A chain of overlapping neighbours
does not form a band when its end intervals are disjoint.
