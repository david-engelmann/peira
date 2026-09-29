# Peira Data-Capture Gap Matrix: Dashboard Foundation Lane

**Date:** 2026-09-28 · **Branch:** `data/foundation-v2` · **Lane:** 7dbfd20d
**Status:** Audit of what the data layer captures vs what the dashboard needs.

Every row: the field, where it comes from, what level it lives at,
whether it is exact/estimated/unknown, how missingness is handled,
what dashboard view consumes it, and what remediation (if any) is
outstanding.

## Run identity and provenance

| Field | Source | Level | Exactness | Missingness | Dashboard use | Remediation |
|---|---|---|---|---|---|---|
| adapter_name/version | artifact header | run | exact | "" (never missing in practice) | run provenance, leaderboard grouping | none |
| suite, dataset_version, manifest_sha256 | artifact header | run | exact | "" | provenance bundle, reproduce | none |
| peira_version, contract_version | artifact header | run | exact | "" | methodology disclosure | none |
| pricing_version/source/date | artifact header | run | exact | "" | cost provenance, price-date stamps | none |
| seed, max_concurrency | artifact header | run | exact | 0 | stability protocol inputs | none |
| env_sha256 | artifact header | run | exact | "" | environment provenance | none |
| created_utc | artifact header | run | exact | "" | timeline, longitudinal registry | none |
| termination, budget_usd, spent_usd | artifact header | run | exact | None/0.0 | ranking eligibility, cost headline | none |
| cases_completed/planned | artifact header | run | exact | 0 | completeness, eligibility | none |
| analysis_lock | computed at seal | run | exact | "" (verify fails) | tamper evidence | none |
| model_class | artifact header (§3.7) | run | exact (registration) | "" = unclassified | family×class interaction matrix | adapters must declare at registration |
| confidence_source | artifact header (§3.8) | run | exact (registration) | "" = unknown | honest calibration comparison | adapters must declare at registration |
| checkpoint_hash | artifact header (§3.11) | run | exact | "" = unknown | longitudinal drift-watch | runner must populate for API adapters |
| api_version, call_date | artifact header (§3.11) | run | exact | "" = unknown | longitudinal registry | runner must populate |
| decode_params | artifact header (§3.12) | run | exact (JSON blob) | "" = unknown | reproducibility, M-5 reproduce | runner must populate |
| template_hash | artifact header (§3.13) | run | exact | "" = unknown | prompt-change detection | runner must populate |
| case_set_tag | artifact header (§3.14) | run | exact | "" = unknown | dataset versioning | runner must populate |
| cost_scenario_version | artifact header (§3.15) | run | exact | "" = none applied | value-view versioning | value-view sets it |

**Gap:** `model_class`, `confidence_source`, and the 7 longitudinal
fields are schema-ready but populated as `""` until the runner and
adapter registration paths fill them. No placeholder values are
invented: `""` means "not recorded", never "default".

## Per-case paired records

| Field | Source | Level | Exactness | Missingness | Dashboard use | Remediation |
|---|---|---|---|---|---|---|
| case_id, family, severity, primitive | result entry | case | exact | "" (entry skipped if case_id/family missing) | all drill-down, grouping | none |
| flipped, eligible, ineligibility_reason | result entry | case | exact | False/"" | ASR denominators, eligibility gating | none |
| benign/attacked decision | call record | case×arm | exact | "" | flip taxonomy, target-hit | none |
| benign/attacked confidence | call record | case×arm | exact | NULL (never 0-filled) | calibration, Δ-calibration, AUROC | none |
| confidence_delta | computed (§3.2) | case | exact | NULL when either arm missing | "does the attack collapse confidence" | none |
| benign/attacked abstained | call record | case×arm | exact | False | fail-closed/open analysis | none |
| benign/attacked malformed | call record | case×arm | exact | False | malformed rate, to-malformed direction | none |
| flip_direction | computed (§3.1) | case | exact | "none" when no flip | flip-anatomy table, cost matrices | none |
| target_hit | computed (§3.4) | case | exact | NULL when case has no target_decision | targeted-vs-random flip separation | dataset must define target_decision for targeted families |
| score_delta | computed (§3.3) | case | exact | NULL when not score primitive | score-delta analytics (M-8) | none |
| tokens_in/out (per arm) | usage record | case×arm | exact when reported | 0 when usage missing (**see gap**) | cost-per-flip, token-based ledger | **OPEN:** missing usage contributes 0, indistinguishable from free calls |
| cost_usd (per arm) | usage record | case×arm | exact (runner-priced) | 0.0 when missing (**see gap**) | all economics | **OPEN:** same as above |
| latency_ms_total (per arm) | call record | case×arm | exact (runner wall-clock) | 0.0 when missing | latency aggregates | **OPEN:** phase-level timing not captured |
| price_table_ref | usage record (§3.6) | case×arm | exact | None = unknown table | cost recomputability | adapters should populate from pricing context |
| seed, dispatch_index/limit | call record | case×arm | exact | 0/1 | stability, dispatch audit | none |

**Gaps (carried, not new):**
1. **Cost/token missingness:** missing usage contributes zero to
   indexed totals. The dashboard must display explicit
   priced/unpriced/missing-usage counts alongside any cost total so
   "unknown" is never rendered as "$0.00". The registry schema now
   carries the raw sums; the missingness counters are a dashboard
   aggregation follow-up.
2. **Latency phases:** only final-attempt and cumulative latency are
   captured. Queue/provider/retry/backoff phase timings are not in the
   call record schema. Requires runner instrumentation (separate lane).
3. **Transcripts:** attempt-level transcripts exist in the artifact
   (`transcript` payloads on ChoiceOutput) but are not indexed in the
   registry. Drill-down to evidence goes through the artifact file,
   not the registry; acceptable for now, indexed transcript search
   is a follow-up.

## Aggregations (dashboard.py)

| Artifact | Inputs | n/CI discipline | Provenance | Status |
|---|---|---|---|---|
| per-family ASR/CI | metrics.per_family (canonical) | n, n_eligible, Wilson CI passed through | run bundle | done |
| per-family cost/latency/confidence | raw results | n_costed_calls, n_latency_calls carried | run bundle | done |
| flip-anatomy (§3.16) | raw results | n_eligible, direction counts, weighted n | run bundle | done (this lane) |
| severity-weighted ASR | flip-anatomy | weighted flips / weighted n | run bundle | done (inputs); CI follow-up |
| target-hit rate | flip-anatomy | target_hit_n / target_defined_n | run bundle | done |
| per-arm calibration (§3.17) | metrics.calibration | ECE/Brier per arm passed through | run bundle | done (split exists); AUROC follow-up |
| family×class matrix (§3.18) | registry (multi-adapter) | ASR + CI per cell | run bundle | **needs multi-adapter data + model_class populated** |
| hardness table (§3.19) | registry (multi-adapter) | flip counts 0..N per case | run bundle | **post-run** |
| transfer matrix (§3.20) | registry (multi-adapter) | off-diagonal transfer ASR | run bundle | **post-run** |
| score-delta (§3.21) | raw results (score primitive) | histogram bins + n | run bundle | **follow-up (M-8)** |
| stability record (§3.22) | multi-seed runs | flip-agreement, run-to-run std | run bundle | **needs k-seed runner (R-04)** |
| economics (§3.24) | flip-anatomy + cost scenarios | bootstrap CIs (not points) | run + scenario version | **post-run (M-3)** |

## M-6 sign-off checklist

- [x] Every aggregate cell retains n and CI inputs (no pre-rounded percentages).
- [x] Per-case pair linkage preserved end-to-end (registry `case_results`
      carries both arms' decisions/confidences; drill-down via
      `query_cases`).
- [x] Bootstrap/resample distributions stored or recomputable
      (per-case rows + seeds retained; distributions recomputable from
      the registry; no pre-aggregated resamples stored yet, by design).
- [x] Every view's provenance bundle present (`run` section carries
      adapter revision, dataset version, manifest hash, pricing
      version/date, and the 9 new measurement-framework fields).

## Blocking-for-big-run coverage (section 4 items 1 to 10)

1. Flip-direction taxonomy: **done** (registry + dashboard).
2. Per-arm ECE split: exists; flip-detection AUROC: **follow-up**.
3. model_class + confidence_source: **schema done**; population needs adapter registration.
4. Token counts + price_table_ref: **schema done**; population needs adapter/runner.
5. Cost-scenario file v1: **structure done** (values are placeholders).
6. 3-seed protocol: **R-04 lane**, not this one.
7. Severity-weighted ASR + target-hit: **done** (inputs; CI follow-up).
8. Hardness stratification: **post-run**.
9. Confidence-delta: **done**.
10. Cost ledger recompute: **evaluation-readiness lane**, not this one.
