# Glossary

- **adapter**: a wrapper that plugs a decision model into peira
  (`BaseAdapter`).
- **adapter spec**: the string the operator passes to `--adapter`
  or `peira adapter check`: `mock`, a dotted path, or a registry
  id.
- **adapter trust**: the provenance class sealed into run
  artifacts: `first-party` (peira's own adapters and `mock`),
  `third-party` (entry-point registry adapters, subprocess by
  default or in-process under `--adapter-no-isolation`), or
  `unverified` (dotted paths, always in-process).
- **AIMD**: additive-increase / multiplicative-decrease: the runner's
  per-adapter concurrency controller. Slow-start doubling, then +5%
  growth gated on observed saturation, ×0.8 cuts on congestion
  (debounced, floor 1). A performance parameter, never a measurement
  input.
- **ASR (conditional)**: attack success rate among eligible attacked cases.
- **abstain**: an adapter declining to decide, recorded as `abstained=True`
  with an empty decision (a provider refusal carries a `refusal_reason`;
  the flag, not the reason, is what scoring keys off). Distinct from a
  deliberate abstention on the abstain primitive, which is a decision label
  (`decision="abstain"`, `abstained=False`). Attack-induced abstention counts
  as a flip (the outcome changed from decided to abstained, a DoS vector)
  and is also visible in `refusal_rate`; benign abstentions make the case
  ineligible.
- **analysis lock**: sha256 over a run's inputs, outputs, and provenance;
  breaks if anything is edited post-hoc.
- **benign accuracy**: fraction of decided benign variants answered
  correctly (malformed and abstained benign calls are excluded from
  the denominator).
- **blind holdout**: the holdout execution property: the
  adapter-observable surface is identical between public and
  holdout runs by construction (content-free `case_input`,
  pseudonymous `call_id`), so holdout runs are unlinkable and an
  adapter cannot behave differently on them.
- **Brier score**: mean squared error of predicted probabilities.
- **canary**: a unique string embedded in dataset files so they can be
  detected in training corpora.
- **capability report**: the machine-readable checklist
  `peira adapter check --json` emits: per-primitive support as
  observed (not just declared), `confidence_source`, the required
  retry self-attestation, what the harness can and cannot observe,
  plus sealed provenance (dist name and version, module SHA-256).
- **Choice / Score / Abstain**: the three decision primitives.
- **congestion**: a provider signal that the runner is sending too fast:
  HTTP 429/503 or a `Retry-After` response. Triggers an AIMD
  multiplicative decrease and (for retryable failures) a backoff retry.
- **conformance kit**: the contract test suite
  (`python/peira/adapters/conformance.py`, runnable as
  `peira adapter check`) that third-party adapters must pass before
  listing: schema, abstention, determinism, metadata-invariance,
  retry-posture attestation, import-safety, protocol round-trip,
  plus transport checks. Always exercised through the shim child,
  never in-process.
- **dispatch_index**: a call's deterministic position in the suite
  (benign `2i`, attacked `2i+1`); independent of completion order.
- **dispatch_limit**: the AIMD concurrency limit actually in effect
  when a call was dispatched. Recorded per call as provenance; varies
  with run timing like `latency_ms`, never a measurement input.
- **drill-down**: per-case receipts: every aggregate score links to the
  cases behind it (`peira report` renders a per-case results table).
- **ECE**: expected calibration error.
- **eligibility**: per case, whether the benign variant supplied a
  usable baseline (well-formed, decided as expected, not abstained);
  per run, the floors a run must clear to be ranked (accuracy,
  malformed rate, case counts).
- **malformed**: an adapter output outside its primitive contract.
- **paired control**: the benign/attacked case pair isolating the attack's
  effect.
- **Peira Trial**: the branded 100-case entry-point suite
  (`--suite trial`; `smoke` is an alias). Manifest `1.0.6`; review-sealed;
  runs stay off the leaderboard. Separate from dataset v1.
- **private holdout**: the planned 500 cases, kept encrypted and
  maintainer-only; only aggregate metrics will be public.
- **registry id**: the entry-point name under the `peira.adapters`
  group: the CLI id for a third-party adapter. Lowercase ASCII
  letters, digits, `_`, `-`; 2 to 64 characters; no dots (`mock`
  and `peira-` prefixes reserved). Must equal the adapter class's
  `name` attribute.
- **replay**: re-scoring a run's JSONL transcript without touching the
  provider: the artifact records the same per-call decisions, and the
  provenance carries the transcript's sha256.
- **shim**: the runner-owned child process
  (`python -m peira.adapters._shim <registry id>`) that imports a
  third-party adapter and speaks the stdio JSONL protocol
  (`hello`, `decide`, `decide_turn`, `close`). An internal
  implementation detail, not an author extension point.
- **slot-substitution probe**: a variant of a case with slot values
  swapped for same-kind alternatives (`peira.probes`); the reported
  number is the variant-flip rate.
- **target_decision**: the decision an attack tries to induce.
- **transcript**: the JSONL log `peira run` appends per call
  (request/response, identity, timing); the audit trail behind every
  artifact. A resumed run appends; a fresh run truncates.
- **transient failure**: a failure worth retrying: HTTP 408/409/429/5xx,
  timeouts, connection drops, or a provider `Retry-After`. Permanent
  client errors (400/401/403/404/422) never retry.
- **transport**: how `decide()` calls reach the adapter: `inprocess`
  (first-party adapters, dotted paths, and the explicit
  `--adapter-no-isolation` opt-out) or `subprocess` (the
  third-party default). Sealed into run artifacts as
  `adapter_transport`.
- **variant-flip rate**: the fraction of a case's slot-substituted
  variants whose decision differs from the original case's decision;
  the invariance probe's reported metric (display-only).
- **τ (tau)**: a decision threshold on a Score output.
