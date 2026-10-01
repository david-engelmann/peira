# peira record ↔ OTel GenAI mapping

peira is a batch benchmark, not a live service: the JSONL artifacts are
the log store, and there is no OTel collector (R-20, E-8). This note maps
peira's per-call record onto the OpenTelemetry GenAI semantic conventions
(`gen_ai.*`, experimental as of 2026-09) so a peira artifact can be
converted to GenAI-shaped spans by a mechanical field rename. The mapping
is one-directional and lossless on the fields both sides define.

## Per-call mapping (CallRecord.usage + CallRecord fields)

| peira field | gen_ai.* attribute | Notes |
|---|---|---|
| `usage.model` | `gen_ai.request.model` / `gen_ai.response.model` | Pinned model id; peira never aliases, so request == response. |
| `usage.tokens_in` | `gen_ai.usage.input_tokens` | Total input tokens. |
| `usage.tokens_out` | `gen_ai.usage.output_tokens` | Total output tokens. |
| `usage.cached_tokens_in` | `gen_ai.usage.cache_read.input_tokens` | Subset of `tokens_in` served from provider prompt cache. None when the provider reported no breakdown. |
| none | `gen_ai.usage.cache_creation.input_tokens` | peira does not record cache writes separately; cache-creation tokens are inside `tokens_in`. |
| `usage.finish_reason` | `gen_ai.response.finish_reasons` | peira stores the single provider string (`"stop"`, `"length"`, `"tool_calls"`, `"content_filter"`, ...); map to a one-element list. None when the provider did not report one. |
| `usage.provider_response_id` | `gen_ai.response.id` | Provider response id (`chatcmpl-...`, `msg_...`); the support-debugging handle. None when not returned. |
| `latency_ms_total` | span duration | Cumulative buyer latency: all attempts plus backoff, runner-measured wall clock. peira overwrites the adapter's self-reported `latency_ms` with its own measurement. |
| `attempt_latencies_ms` (transcript) | none | Per-attempt breakdown of the total; no gen_ai equivalent for retried attempts. This is the field that distinguishes "slow provider" from "retry storm". |
| `cached` | none | Response-cache hit (no provider call was made): the harness-level analogue of a cache read, but for peira's own cache, not the provider's. Excluded from latency percentiles. |
| `usage.cost_usd` | none | Runner-recomputed from the pinned pricing table; the runner is the cost authority, not the adapter. No gen_ai cost attribute exists. |
| `usage.price_table_ref` | none | Which table priced the call; makes historical costs recomputable without rerunning. peira-specific. |
| `usage.tokens_in` billed | none | Cached input tokens are priced at the input rate until a model entry specifies `usd_per_1m_cached_in` (reserved key in the pricing table). |

## Call-level (non-usage) mapping

| peira field | gen_ai.* attribute | Notes |
|---|---|---|
| `seed`, `dispatch_index` | none | Reproducibility pins; no gen_ai equivalent. |
| `decision`, `confidence`, `abstained` | none | Benchmark output; peira grades decisions against gold labels. `gen_ai.output.messages` would carry the raw text, which peira keeps in the transcript instead. |
| `timed_out`, `timeout_kind` | span status | `"attempt"` (per-attempt timeouts exhausted) vs `"item"` (case-level item budget fired). Map to span status error + a `timeout.kind` annotation. |
| `malformed` | none | Output failed validation (or breached `--max-tokens-per-call`); usage/cost are still recorded. |
| `dispatch_limit` | none | AIMD concurrency limit in effect at dispatch. Harness internals; no gen_ai equivalent. |

## Prompt/completion text

`gen_ai.input.messages` / `gen_ai.output.messages` map to peira's
per-call transcript entries (raw request messages and raw API response
when the adapter returns them). Adapters should run a secrets-redaction
pass over anything echoed into the transcript.

## What is deliberately not mapped

- Span hierarchy, trace ids, service names: peira has no distributed
  trace; a conversion tool assigns them.
- `gen_ai.system` / `gen_ai.provider.name`: derivable from the adapter
  id, not stored per call.
- Metrics (histograms, counters): peira's percentile/CPU/CI computation
  lives in the analysis layer (`peira analyze`), not in the per-call
  record.
