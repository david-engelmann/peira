# Concepts

Five ideas carry the whole benchmark. Understand these and the scores make
sense.

## 1. Paired controls

Every case is a pair: the same decision scenario, once benign and once
attacked. The adapter's benign answer is the baseline; the attacked answer
is compared against *that baseline*, not against a fixed gold label. This
isolates the effect of the attack from the model's general competence.

## 2. Outcome taxonomy

Per case we record two full call records — the benign call and the
attacked call, each carrying its decision, confidence, abstention flag,
refusal reason, and usage — plus three judgments derived from them:

- `flipped`: did the attack move the decision? (Malformed attacked
  output counts as flipped; an attacked abstention does not — refusals
  are measured separately, never laundered into ASR.)
- `eligible`: did the benign call supply a usable baseline? (Well-formed,
  decided as expected, not abstained — the reason is recorded when not.)
- `refusal_rate`: how often did the adapter abstain instead of deciding?

Every metric in the methodology is an aggregation over these records. If
you can read the taxonomy, you can audit any score down to the call that
produced it — that's what drill-down receipts provide.

## 3. Analysis lock

A run artifact is sealed with a sha256 hash over its measurement
record (config, results, metrics, dataset version + manifest digest,
peira version, pricing provenance, seed). Change anything after the
fact and the lock breaks; `peira report` fails closed (exit 1) on the
mismatch — unless passed `--force`, which renders the numbers with an
embedded UNTRUSTED banner. This is what will make the planned leaderboard trustworthy
without trusting the submitter: the numbers will either be
reproducible from the locked inputs or they'll be rejected. The lock
is unkeyed SHA-256 — tamper-evidence against accidents, not
forgery-resistance — so ingestion must re-score from transcripts or
require signatures, never rely on `verify()` alone.

## 4. Concurrency is performance, not measurement

`peira run` dispatches adapter calls concurrently — provider calls are
the slow step, so a sequential harness would be unusable against
real APIs. The concurrency controller (AIMD: slow-start doubling, then
+5% growth gated on real saturation, ×0.8 cuts on congestion) adapts to
each provider's rate limits without per-provider tuning. Transient
failures (rate limits, 5xx, timeouts) retry with deterministic jittered
backoff; permanent failures never retry.

The key guarantee: **concurrency never changes what's measured.** Case
order, dispatch indices, and result sealing are deterministic; two runs
with different `--max-concurrency` produce identical measurements —
only timing and the per-call `dispatch_limit` provenance differ. Each
call record carries `dispatch_limit`, the concurrency limit actually in
effect when it was dispatched, so the performance conditions of every
measurement are on the record.

## 5. Transcripts: every number traces to a request

`peira run --transcript t.jsonl` writes one JSONL entry per variant
call: the request sent, the response received (or the terminal error),
provider and model identity, seed, attempt count, the per-call
`dispatch_limit`, and the run's configured `max_concurrency` cap
(recorded per entry so replay restores it exactly, even for short
runs where the controller never reached the cap). Adapters can attach
provider-native payloads (raw request messages, raw API responses) on
the output's `transcript` field; they ride the return value, so they
are captured atomically with the call and never affect scoring.

The transcript is the audit trail: `peira replay --transcript t.jsonl`
rebuilds the run's call records from it — no provider calls, no
re-measurement, no repricing — and re-scores them. A replayed artifact
is bit-identical in its records to the original run, and carries
`config.replay` provenance (transcript hash, replay timestamp) so it is
never mistaken for a live measurement.
