# Glossary

- **adapter** — a wrapper that plugs a decision model into peira
  (`BaseAdapter`).
- **AIMD** — additive-increase / multiplicative-decrease: the runner's
  per-adapter concurrency controller. Slow-start doubling, then +5%
  growth gated on observed saturation, ×0.8 cuts on congestion
  (debounced, floor 1). A performance parameter, never a measurement
  input.
- **ASR (conditional)** — attack success rate among eligible attacked cases.
- **abstain** — an adapter declining to decide: an empty decision with a
  `refusal_reason`. Attacked abstentions are measured by `refusal_rate`,
  never counted as flips; benign abstentions make the case ineligible.
- **analysis lock** — unkeyed sha256 over a run's measurement record
  (config, results, metrics, dataset identity, pricing, seed); breaks
  if anything is edited post-hoc. Tamper-evidence against accidents,
  not forgery-resistance.
- **benign accuracy** — fraction of decided benign variants answered
  correctly (malformed and abstained benign calls are excluded from
  the denominator).
- **Brier score** — mean squared error of predicted probabilities.
- **canary** — a unique string embedded in dataset files so they can be
  detected in training corpora.
- **Choice / Score / Noul** — the three decision primitives.
- **congestion** — a provider signal that the runner is sending too fast:
  HTTP 429/503 or a `Retry-After` response. Triggers an AIMD
  multiplicative decrease and (for retryable failures) a backoff retry.
- **dispatch_index** — a call's deterministic position in the suite
  (benign `2i`, attacked `2i+1`); independent of completion order.
- **dispatch_limit** — the AIMD concurrency limit actually in effect
  when a call was dispatched. Recorded per call as provenance; varies
  with run timing like `latency_ms`, never a measurement input.
- **drill-down** — per-case receipts: every aggregate score links to the
  cases behind it (`peira report` renders a per-case results table).
- **ECE** — expected calibration error.
- **eligibility** — per case, whether the benign variant supplied a
  usable baseline (well-formed, decided as expected, not abstained);
  per run, the floors a run must clear to be ranked (accuracy,
  malformed rate, case counts).
- **malformed** — an adapter output outside its primitive contract.
- **paired control** — the benign/attacked case pair isolating the attack's
  effect.
- **Peira Trial** — the branded 100-case entry-point suite
  (`--suite trial`; `smoke` is an alias). Manifest `1.0.1`; review-sealed;
  runs stay off the leaderboard. Separate from dataset v1.
- **private holdout** — the planned 500 cases, kept encrypted and
  maintainer-only; only aggregate metrics will be public.
- **replay** — re-scoring a run's JSONL transcript without touching the
  provider: the artifact records the same per-call decisions, and the
  provenance carries the transcript's sha256.
- **target_decision** — the decision an attack tries to induce.
- **transcript** — the JSONL log `peira run` appends per call
  (request/response, identity, timing); the audit trail behind every
  artifact. A resumed run appends; a fresh run truncates.
- **transient failure** — a failure worth retrying: HTTP 408/409/429/5xx,
  timeouts, connection drops, or a provider `Retry-After`. Permanent
  client errors (400/401/403/404/422) never retry.
- **τ (tau)** — a decision threshold on a Score output.
