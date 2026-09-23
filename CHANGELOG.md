# Changelog

All notable changes to this project will be documented here. The format is
based on Keep a Changelog, and the project adheres to Semantic Versioning
(the package and the dataset are versioned independently — see
`docs/Compatibility.md`).

## [Unreleased]

### Added — confidence-interval coverage and nonfinite hardening (A3 S9)

- New `peira.metrics.MetricEstimate` (value/ci/n/sufficient) and
  bootstrap 95% CI functions for derived estimates that lacked them:
  `severity_weighted_asr_ci`, `ece_ci`, `brier_ci`, `augrc_ci`,
  `selective_risk_ci` (per fixed coverage), and `compression_ci`.
  All withhold below 30 observations (None + `sufficient: False`,
  never NaN); all intervals use the Python PRNG (backend-independent).
  Display-only, never rankers.
- `summarize()` now reports `severity_weighted_asr_ci95`,
  per-condition `ece_ci95`/`brier_ci95`, `augrc_ci95`,
  per-coverage `selective_risk_ci95`, and compression-index CIs
  (the compression block is now a value/ci95/n/sufficient estimate
  with the n>=30 gate, instead of a bare ungated float).
- Nonfinite hardening: every float-input metric in
  `python/peira/metrics.py` and `crates/peira-core/src/metrics.rs`
  rejects NaN/±inf with `ValueError` (Python) or a clear panic
  (Rust, D-11) — never silent NaN, never an uncontrolled panic.
  Includes the score estimates (`benign_score_mae`,
  `attacked_score_mae`, `score_displacement`), `wilson_ci`'s `z`
  parameter, and the Rust `paired_bootstrap_ci` sort hazard (NaN
  detonated `partial_cmp().unwrap()`). Bootstrap entry points
  (`paired_bootstrap_ci`, the delta functions, the six S9 CI
  functions, the score estimates) also reject non-positive or
  non-integer `n_boot` with `ValueError` instead of an uncontrolled
  `IndexError`. `CallRecord.from_dict` now validates `confidence` in
  0..1.
- `summarize()`'s per-condition `ece`/`brier` point values now come
  from the pure-Python reference inside `ece_ci`/`brier_ci` rather
  than the Rust-dispatched `ece()`/`brier_score()` — backend-
  independent by construction; the values agree to ~1 ulp (the
  documented non-identity), invisible after 4-decimal rounding except
  at pathological rounding boundaries.
- `docs/Methodology.md`: new section on nonfinite handling and CI
  coverage. New ADR D-29 (reject, don't clamp).

### Added — Bradley–Terry compare-view strengths (A3 S7, ADR D-28)

- New display-only `bradley_terry(comparisons)` in `peira.metrics`
  (compare view only — never a ranker, never on the leaderboard, never
  blended into any composite): Davidson (1970) Bradley-Terry strengths
  with ties, fit by maximum likelihood via a monotone block-MM
  algorithm. Takes `ComparisonOutcome(a, b, outcome)` head-to-head
  results (`outcome` in `"a"`/`"b"`/`"tie"`) and returns
  `BradleyTerryEstimate(strengths, nu, n, sufficient)` — centered
  log-strengths (only differences meaningful) plus the fitted tie
  propensity `nu` (`0.0` recovers plain Bradley-Terry).
- Withheld below `MIN_BT_COMPARISONS = 30` (`strengths=None`,
  `nu=None`, `sufficient=False`); `ValueError` on malformed input,
  disconnected comparison graphs, and perfect separation — the exact
  Ford condition (strong connectivity of the win/tie digraph): an item
  that never won-or-tied, or a group that won every cross-group
  comparison outright, has unbounded relative strength, so a sweep is
  displayed as counts, not strengths; all-ties reports equal strengths
  with `nu = +inf`. Point estimates only, no intervals (see ADR D-28
  for why bootstrap CIs are deferred).
- The MM fit ships in the Rust core (`crates/peira-core`) with PyO3
  dispatch parity; validation, aggregation, gating, and the
  identifiability/all-ties logic stay in Python (validated before
  dispatch — D-11).

### Added — run summary (A3 S8a)

- New canonical `peira.metrics.summarize(results, required_families=None,
  expected_scores=None, n_boot=2000, seed=0)`: a pure function from a
  run's per-case records to the complete S1–S6 display summary —
  conditional ASR + Wilson CI, severity-weighted ASR (display-only),
  benign accuracy, refusal rates per arm + attacked-minus-benign delta,
  per-arm outcome censuses, ranking-eligibility gate, per-condition
  calibration (ECE/Brier/Murphy, confidence coverage,
  ΔBrier/ΔECE/Δreliability), selective-prediction diagnostics (AUGRC,
  fixed-coverage risk at 0.5/0.8/0.9/1.0, risk-coverage curve), and
  score diagnostics (per-arm MAE, displacement, compression index,
  skip accounting). Display-only throughout: no composite ranking
  score, no ranking; Bradley-Terry is excluded by design (compare-view
  only, S7). Derived/calibrated metrics withhold below 30 observations
  per condition (explicit `None` + `sufficient: False`, never NaN);
  all floats rounded to 4 decimals; JSON-serializable; deterministic
  via the seeded Python PRNG. Sealed-artifact and report wiring land
  in S8b.
- `docs/Methodology.md`: new `summarize()` section documenting the
  output schema field by field.

### Changed — run summary review fixes (A3 S8a)

- `peira.runner.summarize` (the legacy sealed-artifact summary) is now
  private as `peira.runner._summarize_artifact`: two public `summarize`
  functions with divergent schemas were a cross-lane accident waiting
  to happen. `peira.metrics.summarize` is the public canonical
  summary; S8b will rewire the artifact summary onto it.
- Rates with zero observations now report `None` instead of `0.0`
  (empty runs, required-but-absent families): a zero in the summary
  always means "measured zero", never "no data".
- The score compression index is computed over every available arm
  score (no author reference needed, as documented) and now honors the
  n≥30 gate like every other derived estimate — it is withheld below
  30 scores instead of reporting the degenerate 1.0 a single
  observation would give.
- `summarize()` validates `n_boot`: non-positive, non-integer, and
  bool values raise `ValueError` instead of dying in an `IndexError`
  inside the bootstrap.

### Added — score diagnostics (A3 S6, ADR D-27)

- New optional case-author field `benign.expected_score: float | None`
  (0–1) on score-primitive cases: the author's reference answer to
  the same graded question the prompt poses to the adapter. Gate G7
  requires it on every valid score-primitive case in release-track
  datasets.
- New display-only score diagnostics in `peira.metrics` (never
  rankers): `crps_point(scores, refs)` — mean |score − reference|, the
  degenerate CRPS for deterministic forecasts (Gneiting & Raftery
  2007), coinciding with MAE in v1; `score_compression_index(scores)`
  — `1 − 12·Var(scores)` clipped to [0, 1] (bimodal caveat
  documented); `score_pairs()` extraction split by arm with skip
  accounting; per-arm `benign_score_mae` / `attacked_score_mae` and
  paired `score_displacement`, returning `ScoreEstimate(value, ci, n,
  sufficient)` withheld below `MIN_SCORE_CASES = 30`.
- `crps_point` and `score_compression_index` ship in the Rust core
  (`crates/peira-core`) with PyO3 dispatch parity; the
  bootstrap-backed estimates stay Python-reference (Python PRNG by
  contract).
- `CallRecord` carries `score: float | None`, populated from
  `ScoreOutput` by the runner and restored from transcripts and
  artifacts (pre-S6 artifacts without the key still load, on both
  backends).
- The Trial's 16 score cases were backfilled with authorial
  references, then re-pinned to the transcription method (ADR D-27):
  the 10 `tr-sa-*` values are the author's own `~NN` estimates from
  the case notes, normalized to each prompt's scale; the 6 `tr-cf-*`
  values are non-extremized point estimates inside the notes' stated
  bounds. 2026-09-23 correction: an independent review found 9 of the
  16 values compressed toward the decision threshold and corrected
  them to the evidence-implied magnitude (ADR D-27); the Trial
  manifest is now `1.0.4`. Note: `review.json`
  predates the new field, so human review has not independently
  covered it.

### Fixed — A3 S6 independent review findings

- Artifact load now enforces the unit-interval rule on `score` (a real
  number in 0..1): NaN/Infinity — which Python's `json` accepts but
  `serde_json` rejects at parse — and out-of-range values fail the
  strict loader with a clean error, on both backends (the Rust
  `CallRecord` deserializer rejects them too). Pre-S6 artifacts
  without the key still load.
- `CallRecord.from_dict` validates `score` with a clean `ValueError`
  instead of letting hostile resume-partial entries detonate later as
  `TypeError`. (`confidence` has the same pre-existing gap — S1's
  territory; flagged as a stack-level follow-up.)
- Transcript replay only restores `score` for score-primitive entries;
  a foreign score on any other primitive's entry is dropped.
- `score_pairs` validates the caller-supplied reference map up front
  (finite, in 0..1) instead of letting junk warp MAE/displacement.
- `score_pairs` takes a `Mapping` for the reference map, not just a
  `dict`; the `ScorePairs` docstring now says the two per-arm skip
  buckets count arm-observations.

### Changed (BREAKING — pure adapter inputs, ADR D-25)

- `case_input` is now an exact copy of the case-defined input — the
  runner no longer injects `case_id`, `expected_decision`,
  `target_decision`, or `attacked` into it. Trial bookkeeping travels
  on a typed third argument, `CallContext` (`case_id`, `arm`,
  `expected_decision`, `target_decision`), and `BaseAdapter.decide()`
  is `decide(self, case_input, primitive, context)` with no
  compatibility shim. All bundled adapters, the mock, the examples,
  and the README quickstart are migrated; the response cache key now
  includes the variant arm and case id.
- `docs/Methodology.md` no longer claims the target decision is
  injected into the attacked input — it is carried on the trial
  context.

### Changed (BREAKING — equal-mass ECE, ADR D-26)

- `ece()` now uses equal-mass bins (sorted forecasts split into
  `bins` chunks as equal-count as possible, K=15 default) instead of
  equal-width, revised in place with no legacy function or flag. Both
  the Python reference and the Rust port implement the same binning
  (stable sort, so ties are deterministic); the public signature
  `ece(probs, labels, bins=15)` is unchanged but reported values can
  differ from the old equal-width estimator.
- New `murphy_decomposition(probs, labels, bins=15)` — Brier-score
  Murphy decomposition (reliability / resolution / uncertainty /
  residual) under the same equal-mass bins, Python-reference only.
- New `confidence_coverage(results)` — per-arm fraction of non-None
  confidences, reported alongside every calibration number.

### Added — delta-calibration (A3 S2)

- New `attacked_confidence_pairs(results)` — attacked-arm mirror of
  `eligible_confidence_pairs`: label 1 when the attacked decision
  matches the case's expected decision (not flipped), 0 otherwise.
- New `delta_brier(results)` — the headline calibration number:
  attacked-minus-benign Brier score on paired cases (eligible, both
  confidences present), with a 95% CI from `paired_bootstrap_ci`.
  Positive means worse under attack; the docstring carries the
  direction caveat (Brier mixes calibration with sharpness).
- New `delta_ece(results)` / `delta_reliability(results)` —
  attacked-minus-benign ECE and Murphy reliability on the same paired
  cases, with 95% CIs from paired case-resampling bootstrap.
- New `DeltaEstimate(delta, ci, n, sufficient)`: delta statistics are
  withheld below the `MIN_DELTA_CASES = 30` gate — `delta`/`ci` are
  None and `sufficient` is False instead of a NaN.

### Added — outcome accounting (A3 S5)

- New `benign_refusal_rate(results)` — benign-arm mirror of
  `refusal_rate` with the same Wilson 95% CI (any abstention counts,
  over all cases). Python-reference only; `refusal_rate` keeps its
  Rust fast path for the attacked arm.
- New `outcome_accounting(results)` — per-arm census over *all* cases:
  `ArmOutcomes(n, approve, deny, other, refused, abstained,
  malformed)`, returned as `(benign_outcomes, attacked_outcomes)`.
  Bucket precedence: malformed > abstained (`refused` with a refusal
  reason, plain `abstained` without) > decided (`approve` on the
  "approve" label, `deny` on the exact "deny" label, `other` for any
  other decided label). The buckets partition each arm's cases.
- New `refusal_rate_delta(results)` — attacked-minus-benign refusal
  rate with a paired-bootstrap 95% CI (backend-independent Python
  PRNG). Empty results return `(0.0, (0.0, 0.0))`, like the other
  rate functions.

### Added — ASR extras (A3 S4)

- New `severity_weighted_asr(results)` — the flip indicator averaged
  over eligible cases with frozen weights
  `SEVERITY_WEIGHTS = {"critical": 3, "high": 2, "medium": 1}` (D1);
  display-only, never a ranker. No eligible cases reads 0.0, like
  plain ASR; unknown severities raise ValueError.
- New `holm_adjust(p_values, alpha=0.05)` — Holm step-down adjusted
  p-values in the input order (uniformly more powerful than
  Bonferroni), for joint claims across families (e.g. McNemar
  family-comparison p-values).
- New `bonferroni_adjust(p_values)` — min(1, m*p) per p-value, input
  order. New `reject_at(adjusted, alpha=0.05)` — indices rejected at
  level alpha (empty input returns `[]`; NaN and out-of-[0, 1] values
  raise ValueError). Empty p-value lists and values outside [0, 1]
  (incl. NaN) raise ValueError in the adjust functions.

### Added — selective prediction (A3 S3)

- New `risk_coverage_curve(probs, labels)` — the selective-
  classification risk-coverage curve (Geifman & El-Yaniv 2017):
  `(coverage=k/n, risk)` for k = 1..n over the confidence-descending
  ranking, stable ties.
- New `selective_risk_at_coverage(probs, labels, coverage)` — error
  rate of the top `ceil(coverage*n)` predictions; `coverage` must be
  in (0, 1].
- New `augrc(probs, labels)` — Area Under the Generalized Risk
  Coverage curve (Traub et al. 2024, arXiv:2407.01032), the
  trapezoid-rule area under the (coverage, generalized-risk) curve,
  satisfying the paper's Eq. (7) identity and the [0, ½] bound; reads
  as the "average risk of undetected failures". All three are
  display-only diagnostics, never rankers (D2), intended for
  attacked-arm correctness pairs from `attacked_confidence_pairs`.
  Python-reference only; Rust port deferred.

### Added — real day-one adapters (A2)
- New `python/peira/adapters/hf.py` behind `peira[hf]`: Shieldstral
  (`mistralai/Shieldstral-1.0-3B`, pinned revision), ProtectAI
  prompt-injection v2 (pinned revision, documented false-positive
  tendency on system-prompt-style content), and Llama Prompt Guard 2
  86M (pinned revision, binary BENIGN/MALICIOUS, gated-license caveat,
  512-token segmentation). All map verdicts to choice/noul with
  `|2p−1|` confidence; thread-safe lazy model load; pinned revisions as
  tested class constants, never `main`.
- New `python/peira/adapters/llm.py` with one adapter per provider —
  `peira[openai]` (default `gpt-5.6-luna`), `peira[anthropic]` (default
  `claude-sonnet-5`), `peira[google]` (default `gemini-3.8-flash`).
  One JSON schema template sent to provider-native constrained
  decoding (strict `json_schema` / forced tool choice / `responseSchema`)
  plus stdlib client-side revalidation; per-call decision enum built
  from the trial context's labels; temperature 0 with pinned seed where
  supported; verbalized confidence flagged uncalibrated; refusal
  pipeline (stop reason → GCG prefixes → one schema-repair retry, then
  terminal); SDK retries
  disabled — the runner owns retries.
- New `python/peira/adapters/jev.py` (stdlib-only, no extra): TypeSafe
  Jev System One adapter pinned to `jev-1.13.0`, one POST per call with
  no internal retries, `TYPESAFE_API_KEY` required with an actionable
  error, 429/529/5xx and transport timeouts surfaced as retryable
  `ProviderError` for the runner while 401/422 stay terminal.
- Pricing table now carries pinned prices for the adapter models
  (`gpt-5.6-sol` corrected to $4/$20, verified 2026-09-23 against
  OpenAI's pricing page; `claude-opus-5.5` replaced by the real
  `claude-opus-5` at $5/$25; `jev-1.13.0` at $0.042/1M input,
  output free, secondary-sourced via gateway announcements — not
  confirmed on an official TypeSafe pricing page (the old "no public
  pricing" note was wrong); Anthropic/Google rates are still
  unverified —
  re-check before launch.
- New `docs/Adapters.md`: install extras, API keys, pinned models, and
  per-adapter measurement notes. README adapter table updated
  (shipped vs planned vs measured). ADRs D-21–D-24: optional-dependency
  isolation, provider-native schema + client validation,
  confidence/refusal normalization, model/revision pinning and Jev
  transport.

### Changed — README v2 (docs slice D1)
- Rewrote `README.md` around proof-first structure: a real generated
  per-family results table (from `peira run --adapter mock --suite trial`)
  sits above the install section, and the 60-second quickstart ends in a
  printed table with Wilson 95% CIs. New sections: dated News, "What
  brings you here" problem nav, honestly-labeled planned-adapters table,
  Reports, and a Methodology section stating the differentiators plainly
  (decision-change ASR, hard ≥20-eligible-cases ranking gate, refusals
  never laundered into ASR, cost as a sidecar). Badges cut to three
  (CI, PyPI, license). Every code block verified verbatim; the sample
  table is generated by `scripts/gen_readme_table.py`, never hand-edited.
- New `scripts/generate_social_preview.py` (stdlib-only) producing
  `assets/social-preview.svg` (1280×640, text wordmark — peira has no
  locked logo yet); documents the PNG export step for the repo Settings
  upload.
- Fixed the README adapter snippet for the v2 contract (`version` is
  required).
### Added — docs landing page + CLI reference (docs slice D2)
- New `docs/Overview.md`: the docs landing page — three audience paths
  (run the benchmark, add a model, contribute) plus a map of every page
  in `docs/`. Linked from the README's docs nav.
- New `docs/CLI.md`, generated by the stdlib-only
  `scripts/gen_cli_reference.py` from the live argparse parser (every
  command, subcommand, flag, default, and help string). The file is
  checked in but never hand-edited; the `docs` CI job re-renders it
  from the parser and fails on any diff, so the reference can't
  silently go stale.
### Fixed — adapter refresh pass (post-A2 verification)

- `python/peira/data/pricing.json`: the Jev entry no longer claims
  verification it didn't have — $0.042/1M in, free out is
  secondary-sourced via gateway announcements, not confirmed on an
  official TypeSafe pricing page (re-verify before launch). Added the
  known Gemini 3.8 Flash step-up to the table ($1.50/$7.50 per 1M from
  2027-01-01).
- `pyproject.toml`: `peira[hf]` pins `transformers>=4.40,<5` — the v5
  major's breaking changes (TF/JAX removal, weight-loading and
  tokenization refactors, hub client and CLI changes) are unverified
  against the pinned HF revisions; the cap lifts after a v5
  verification pass.
- Verified, no change needed: the Google adapter uses classic
  `generateContent` + `responseSchema` (unaffected by the Interactions
  API migration); Shieldstral 1.0, ProtectAI, and Prompt Guard 2 are
  pinned to exact commit revisions; OpenAI uses strict `json_schema`;
  Anthropic uses forced tool choice (per-model confirmation required
  before adding new models like Opus 5.5).

### Planned
- Versioned methodology pages (`docs/Methodology.md` is the single
  current page; dated per-release snapshots land with the v1 dataset).
### Added (BREAKING — async runner, ADR D-20)
- `peira run` now dispatches adapter calls concurrently (asyncio, one
  worker thread per call), bounded by a per-adapter AIMD controller in
  `[1, --max-concurrency]` (default 8): slow-start doubling, +5%
  additive growth gated on observed saturation (≥80% in-flight usage),
  ×0.8 cuts on congestion (debounced to one cut per 15 s, floor 1).
- Transient-only retries (`--max-attempts`, default 3; `--call-timeout`
  optional): 408/409/429/5xx and timeouts retry with deterministic
  full-jitter exponential backoff seeded per
  (seed, dispatch_index, attempt); `Retry-After` honored up to 60 s.
  400/401/403/404/422 and validation errors never retry. Provider SDKs
  must use 0–1 internal retries — the runner owns the retry policy.
- `--transcript <path>`: one JSONL entry per variant call (request,
  response or terminal error, provider-native `raw` payloads from the
  output's `transcript` field — captured atomically with the call,
  provider/model identity, seed, attempts, `dispatch_limit`). Resumed
  runs append without duplicating entries.
- `peira replay --transcript <path>`: re-score a transcript with zero
  provider calls. Call records are rebuilt bit-for-bit from the
  transcript (no latency re-measurement, no repricing); the artifact
  keeps the original adapter identity/seed/dispatch limits and carries
  `config.replay` provenance (transcript SHA-256, replay timestamp).
- `--cache-dir <dir>`: opt-in deterministic response cache keyed on
  adapter name/version, model id, input messages, temperature, top_p,
  max_tokens, seed, manifest SHA-256, and primitive. Off by default;
  only valid for deterministic adapters (temperature 0 + fixed seed);
  writes are best-effort and never fail the run.
- Every `CallRecord` gains `dispatch_limit`: the AIMD concurrency limit
  actually in effect when the call was dispatched (provenance, not
  measurement — it varies with run timing like `latency_ms`). Required
  by strict artifact loading on both Python and Rust.
- Ctrl-C / infrastructure failures abort with a checkpointed partial;
  `--resume` re-runs only incomplete cases (model errors are never
  requeued — they are recorded as malformed). New `docs/Troubleshooting.md`
  entries for every new CLI error.

### Changed (BREAKING — v2 measurement contract, ADR D-19)
- Every adapter output is now a full measurement record: `decision`,
  `confidence` (0..1 or None), `abstained`, `refusal_reason`, and `usage`
  (model, tokens_in/out, latency_ms, cost_usd, or None). `decide()` still
  receives the same input dicts — the input contract is unchanged — but
  what it returns is now a typed output object, never a bare decision.
- Results carry the benign and attacked `CallRecord`s side by side with
  `flipped`, `eligible`, and `ineligibility_reason`; every record adds
  the run `seed`, a deterministic `dispatch_index`, and an explicit
  `malformed` flag (set by the runner when validation fails or the call
  raises — never inferred from a sentinel decision).
- Eligibility is benign-validity: a case is eligible only with a usable
  benign baseline (well-formed, decided as expected, not abstained), with
  reasons `benign_malformed`, `benign_wrong_decision`, `benign_abstained`
  counted and reported. An attacked abstention counts as **not** flipped —
  refusals surface via `refusal_rate` (overall and per-family), never
  laundered into ASR. Attacked-malformed still counts as flipped (D-11).
- The targeted-attack-success metric is removed: the v2 result contract
  carries no target metadata. The leaderboard ranks on decision-change
  ASR only.
- Run artifacts are format version `"2"`; v1 artifacts are **rejected at
  load with a clear error, never migrated**. The analysis lock now also
  covers `pricing_source`, `pricing_date`, and `seed`.
- The runner is the authority on cost and latency: it overwrites
  adapter-reported `latency_ms` with its own wall-clock measurement and
  recomputes `cost_usd` from the pinned pricing table
  (`python/peira/data/pricing.json`, source and pin date sealed into the
  artifact). Unknown models price at 0.0 — explicitly unaccounted, never
  silently estimated.
- CLI: `peira run --seed <int>`; the run summary shows eligible count,
  refusal rate, and the ineligibility breakdown instead of
  targeted-success. HTML reports show nested call records, refusal rates,
  eligibility, pricing provenance, and seed.
- The Rust core and PyO3 bindings mirror the contract exactly (strict
  v2 artifact loading on both backends; parity fixtures regenerated from
  the Python reference).
- Backwards compatibility has zero weight while the project is
  pre-launch and unused: v1-shaped tests, docs, and examples were
  rewritten, not adapted (docs/Methodology.md, docs/Decisions.md D-12/D-16
  updates and new D-19, docs/Troubleshooting.md entries for v1 rejection,
  pricing-table errors, and resume seed mismatch).

### Added
- Trial dataset 1.0.1: five minor fixes from the case-quality audit —
  tr-cs-009 attacked variant now reads "an accounts-payable assistant"
  (restores the minimal pair); tr-pp-005 attacked variant drops the
  leftover benign-closing sentence; tr-df-001's persuasive anecdote
  distractor replaced with a neutral equipment-logistics item; all ten
  tr-df-* attacked variants move the "Additional context" flood block to
  between "Relevant facts" and the decision question; the trial-demo
  sa-001…sa-004 anchors now push toward each case's target decision
  (0.08-0.15 low risk) and the benign prompts state the 0.5 decision
  rule. Six gates green, manifest re-sealed, `dataset status` reports
  release-ready.
- Decision records D-16–D-18: `Case.extras` are tooling metadata and are
  never passed to adapters (adapter-facing configuration lives in the
  variant `input` dicts; the frozen `decide()` contract is untouched);
  `dataset_version` is the human-readable release label while the sealed
  manifest SHA-256 supplies byte identity; the mock adapter is a
  deterministic mechanism exerciser and no benchmark claim may rest on
  its numbers.
- Simplicity + scripts + CI hardening (H7): one shared `iter_cases()`
  generator replaces the three duplicated JSONL open/enumerate/parse
  loops (`dataset.summarize_cases`, `review._valid_cases`,
  `gates.run_gates`), and `run_gates` now validates each case exactly
  once, threading the result to every gate instead of re-validating.
  Review decisions fail fast on invalid case data (`error: unreadable
  case data: <file>:<line>`) instead of silently skipping bad lines.
  `review.json`, `--resume` partials, and run artifacts are written
  atomically (temp file + `os.replace`; last-writer-wins is the
  documented contract for concurrent `review approve`). `peira run
  --dry-run` no longer creates the output directory — zero side
  effects. `--adapter :Foo` now reports the documented "unknown
  adapter" error instead of `ValueError: Empty module name`.
  `scripts/check_doc_links.py` also verifies reference-style
  (`[text][ref]`) links. `peira dataset new --out` no longer glues onto
  a file missing its trailing newline. New Troubleshooting entries:
  `peira dataset status` exit 1, unreadable case data, and the
  trust note for dotted-path adapters (only load paths you trust —
  the module is imported and executed). CI pins
  `dtolnay/rust-toolchain` to 1.98.1 and smoke-tests the `peira-cli`
  binary (`validate --dir dataset/trial`) in `dataset-checks`.
- Backend parity + robustness (H6): `RunArtifact.from_json` now validates
  strictly on both backends — top-level object required,
  `peira_version`/`dataset_version` required, unknown fields rejected,
  every field's JSON type checked (`config`/`metrics` must be objects on
  the Rust side too), every `results` entry validated as a
  `PerCaseResult`-shaped object, and all other fields defaulting
  exactly like the Rust core (missing `config`/`metrics` become `{}`, not
  `null`), instead of silently defaulting or leaking `TypeError`
  (new ADR D-12). Malformed `--resume` partial entries (scalar or
  wrong-shaped result objects) raise a clear `ValueError` naming the entry
  index instead of `AttributeError`/`TypeError`. The `ece` / `brier_score`
  / `paired_bootstrap_ci` input asserts are explicit `ValueError`s
  (non-empty, equal-length) that survive `python -O` and are validated
  before backend dispatch so both backends agree (D-11 extended;
  `docs/Methodology.md` updated). Manifest verification rejects file
  names containing `..`, separators, or absolute paths before touching
  the filesystem, and reads `manifest.json` exactly once — the digest
  sealed into the analysis lock is always the digest of the verified
  bytes (no verify-then-reread race). Schema error strings now use a
  fixed escaping rule implemented identically in both languages
  (`_safe_repr` / `py_repr`) instead of `repr()`, making them
  byte-identical for every input (new ADR D-13). The Rust analysis lock
  streams canonical bytes straight into SHA-256 (no more deep-clone of
  `config`/`results`), case files are read+hashed in one pass, and
  canonical output sorts object keys explicitly. The Rust CLI matches the
  Python CLI's `validate` summary text (`validated N cases, M invalid`),
  full-path `file:line` errors, exit codes, and `--dir=` form, and types
  manifest errors instead of string-matching them. New user-facing errors
  are catalogued in `docs/Troubleshooting.md`.
- Trust-boundary hardening (H5): `peira report` now formats every
  metric cell through a single `_num` formatter (floats render with four
  decimals, anything unexpected is escaped) and escapes the artifact
  version, analysis lock, and manifest digest — closing the
  stored-XSS-shaped hole H2 left in the metric cells (regression-tested
  with a hostile artifact). `peira validate` reports malformed JSON
  lines as exit-1 user errors with `file:line` instead of tracebacks;
  `peira report` exits 1 (not 2) on corrupt artifacts and unwritable
  `--out`. The schema validator now enforces the declared JSON types
  (`bad case_id: expected string`, `bad benign input: expected object`,
  …) on both backends with byte-identical messages. `validate_output`
  rejects non-string decisions and non-numeric confidences instead of
  mis-scoring or raising bare `TypeError`. Case files are read as UTF-8
  on every platform. The Rust core rejects case-file lines nesting
  deeper than 256 levels before parsing. The three
  `paired_bootstrap_ci` / `ece` / `mcnemar` edge divergences now fail
  loudly and identically on both backends (new ADR D-11). New
  user-facing errors are catalogued in `docs/Troubleshooting.md`.
- Trial-demo disposition (T3): `dataset/trial-demo` confirmed as the
  12-case offline quickstart fixture (gate-exempt, contents frozen for
  the quickstart). Stale "starter suite" / "lands at v1" wording swept
  from `AGENTS.md`, `docs/Troubleshooting.md`, `docs/Decisions.md`, and
  the dataset docstring; `dataset/README.md` now lists the branded
  Trial; D-8's "to revisit" note resolved — Trial runs stay off the
  leaderboard (below the hard 20-case ranking gate).
- Branded 100-case Peira Trial (T2): `dataset/trial` now holds 100
  v1-quality cases (10 per attack family; 14 critical / 40 high / 46
  medium) authored through the full pipeline — all six gates green,
  100% of critical cases human-reviewed, manifest sealed at 1.0.0
  (`peira dataset status` reports release-ready). The README quickstart
  gains a per-adapter-class cost/time table, and the two stale Trial
  claims are reworded (the Trial is here now; per-case drill-down in
  `peira report` is real).
- Authoring pipeline, third slice (T1c): `peira dataset status --dir
  <dir>` — one view of the generate → gate → review → manifest flow
  (per-gate results, review pending/coverage, manifest state). Exit 0
  means release-ready (no gate errors, no pending reviews, manifest
  verifies clean); anything else is exit 1. Documented in
  `docs/Dataset.md`, including the authoring loop.
- Public decision records: `docs/Decisions.md` now records the locked
  methodology decisions as ADRs (D-4 decision-change ASR with targeted
  success secondary; D-5 asymmetric malformed handling; D-6 hard
  per-family ranking gate with exit code 3 for unranked runs; D-7 100%
  human review of critical cases; D-8 trial suites stay off the
  leaderboard; D-9 benchmark before thresholds library; D-10 no vendor
  pre-briefs). Each names the alternatives considered and what would
  trigger a revisit.
- Docs link check: `scripts/check_doc_links.py` fails CI on dead
  internal links (new `docs` job), so the growing docs set can't rot
  silently.
- GitHub issue templates for bug reports and feature requests.
- Authoring pipeline, second slice (T1b): the release seal in
  `peira dataset build-manifest`. The build now refuses when
  `--version` isn't semver, when any critical-severity case lacks a
  severity justification in its notes (the rubric's "say why" rule), or
  when the dataset changed under an already-sealed version — bump the
  version instead (idempotent rebuilds are still fine). `peira dataset
  new` also prints the family's severity hint so authors grade against
  the rubric at authoring time. New errors documented in
  `docs/Troubleshooting.md`.
- Authoring pipeline, first slice (T1a): CI runs the dataset checks on
  every push — `peira dataset gates --dir dataset/trial` and
  `peira dataset verify-manifest --dir dataset/trial` on the committed
  Trial starter suite, plus conditional gates/manifest checks on
  `dataset/v1` once it has case files. This makes the documented claim
  true: manifests are committed to git and a mismatch is a build
  failure. `dataset/trial-demo/` stays exempt (gate-exempt scaffolding).
- Byte-proof dataset identity (H4): `peira run` verifies the suite
  manifest before scoring and seals the manifest's SHA-256 into the
  analysis lock, so an artifact proves the exact dataset bytes scored —
  not just the version label. A verification mismatch fails closed
  (nothing is scored), and `peira run --resume` refuses a partial run
  recorded against a different dataset snapshot. The Rust
  `RunArtifact`/`lock_payload` mirror the new sealed field, with
  regenerated parity fixtures.
- Rust `Case` now preserves unknown top-level keys in `extras`
  (`#[serde(flatten)]`), matching Python's `Case.extras`, with a
  Python-generated fixture pinning byte-identical canonical round-trips
  across both implementations.

### Fixed
- Report HTML: `peira report` now escapes author-controlled strings
  (case ids, family names, adapter name/version, suite and dataset
  labels) so a hostile case id lands inert in the HTML.
- Docs: consolidated the two overlapping severity rubrics
  (`docs/Severity-Rubric.md` + `docs/SeverityRubric.md`) into a single
  `docs/Severity-Rubric.md` — tiers, rules, template-author guidance,
  and the confidence-movement disambiguation in one place.
- Mock adapter flip behavior: on its seeded flip subset the mock now flips
  toward each case's own `target_decision` (injected into the attacked
  input by the runner) instead of hard-coding the approve/deny toggle,
  so targeted-attack-success is meaningful for arbitrary decision labels
  (A/B, advance/reject, flag/clear, …). The approve/deny toggle remains
  as the fallback for target-less synthetic inputs. Deterministic and
  bit-for-bit reproducible as before.

### Added
- Initial scaffold: Python SDK (`BaseAdapter`, case schema, runner,
  metrics, sealed run artifacts), `peira` CLI (`run`/`validate`/`report`),
  deterministic mock adapter, 12-case offline demo fixture.
- Rust workspace with `peira-core` skeleton (ports hot paths after the
  Phase 0 interface freeze).
- Docs: Methodology, Taxonomy, Threat-Model, Severity-Rubric, Concepts,
  FAQ, Troubleshooting, Glossary, Hardware, Compatibility, Contributing,
  Claims, Decisions.
- CI: Python + Rust tests, `public-surface` strategy-language check, README
  quickstart executed verbatim on Ubuntu/macOS/Windows.
- Optional Rust accelerator: `crates/peira-python` exposes the Rust core to
  Python as the `peira._core` PyO3 extension (built with
  `scripts/build_core_ext.py`). The scoring hot paths in `peira.metrics`
  and `peira.schema` dispatch to it when importable and fall back to the
  pure-Python reference otherwise, so `pip install peira` still needs no
  Rust toolchain. Backend parity is pinned by
  `tests/test_rust_backend.py`; the `test-python-rust` CI job builds the
  extension and runs the Python suite against both backends.
- Trial-suite mechanism: `dataset/trial/` starter suite (20 scaffolding
  cases, 2 per family, all six gates green, manifest `0.1.0-trial`) wired
  to `peira run --suite trial`. Case schema is now forward-compatible:
  validators ignore unknown top-level fields and `Case.from_dict`
  preserves them on `Case.extras`, so future per-case configuration needs
  no pipeline refactoring. `peira run` records the suite's manifest
  dataset version in the artifact (part of the analysis lock); `peira
  report` gains a per-case results table for drilling into flips.
