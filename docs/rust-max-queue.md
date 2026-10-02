# Rust-maximization migration queue

Owner: rust-max lane. Branch: `rust-max-queue`. Worktree: `~/workspace/peira-rust-max`.

Directive (David, 2026-09-30): as much of peira as possible goes in Rust,
with a massive set of validation testing in Rust. Adapters that wrap
external APIs stay Python. Each slice: parity tests asserting
Rust/Python identical outputs on the fixture corpus, then the swap with
both-backends CI coverage. PyO3 surface kept intact.

## Phase 1: audit (pending child reports)

Cluster A (metrics): calibration, hardness, saturation, stability,
  conversation_metrics, combo_metrics, threshold_family,
  economic_lottery, lottery, economics.
Cluster B (pipeline): runner, conversation_runner, concurrency,
  artifacts, compare, dataset, schema, gates, combo_gates,
  conversation_gates, env_fingerprint, provenance, runs_registry, doctor.
Cluster C (adapters/CLI/glue): adapters/*, cli, dashboard, templates,
  review, api_pins, families, probes/*, conversation, combo,
  conversation_schema, combo_schema, pricing.

## Phase 2: slices (to be filled from audit)

| # | Module | Risk | Coverage | Slice PR |
|---|--------|------|----------|----------|
| 1 | lottery.py (R-09 lottery index) | LOW | strong (34 existing + 37 Rust unit + 15 parity) | rust-max slice 1: #300 |
| 2 | _labels.py + invariance.py + combo_schema.py validation/ID fns (C-1) | LOW | weak/moderate existing + 40 Rust unit + 62 parity | rust-max slice 2: #321 |
| 3 | combo_metrics.py + hardness.py (MIGRATE #2, #3) | LOW-MED / LOW | strong (29 hardness + 14 combo shared) + 11 Rust unit + 44 parity | rust-max slice 3: #371 |

## Phase 1 results: Cluster A (metrics) audit complete

Module risk/coverage/rec (zero `_rust`/`_core` hits anywhere in this
cluster; all stdlib + peira.* imports):

| module | risk | tests | recommendation |
|---|---|---|---|
| lottery.py | LOW | strong (34) | MIGRATE #1: zero new Rust prereqs, unblocks economic_lottery |
| combo_metrics.py | LOW-MED | weak-mod (14 shared) | MIGRATE #2: tiny, pure |
| hardness.py | LOW | strong (29) | MIGRATE #3: pure aggregation |
| economics.py (numeric core) | LOW-MED/part | strong (77) | MIGRATE #4 after flip_direction + net_benefit_at_threshold land in metrics.rs |
| stability.py (numeric core) | MED | strong (35) | SPLIT #5: artifact sealing/JSON lock stays Python (byte-exact json.dumps parity risk) |
| saturation.py | MED | moderate (23) | MIGRATE #6 after mde_mcnemar lands in metrics.rs |
| calibration.py | LOW-MED | strong (45) | MIGRATE #7: SVG byte-parity ({x:.4f}, {t:g}, html.escape) |
| economic_lottery.py | MED | moderate (18) | MIGRATE #8 after lottery.py + economics core |
| conversation_metrics.py | MED | weak (11) | DEFER: boundary types missing in Rust, banker's rounding |
| threshold_family.py | MED | moderate (25) | STAY PYTHON (declared Python-only; depends on unported buyer_cost_at_threshold) |

Hard constraints:
- cppf / break_even_attack_rate bootstraps use random.Random(seed) and must
  STAY PYTHON per the paired_bootstrap_ci PRNG precedent (documented).
- load_cost_scenario YAML subset parser stays Python (file IO by design).
- _round4 banker's rounding: replicate via format!("{:.4}") + parse; verify
  on x.xxx5 boundaries. Note double rounding in lottery_analysis (band on
  rounded index).
- Option<f64> for kendall_tau None, lottery_index None; lexicographic
  (tau, family) tie-break; dict insertion order preserved via ordered Vec.
- Cross-cluster blockers for later slices: flip_direction,
  net_benefit_at_threshold, mde_mcnemar need metrics.rs ports first.

## Phase 1 results: Cluster C (adapters/CLI/glue) audit complete

Rust CLI today (`crates/peira-cli`, 219 lines): read-only `validate`
and `verify-manifest` twins, hand-rolled arg parsing, exit codes 0/1/2
mirroring Python. No run/report/dashboard.

| module | risk | tests | recommendation |
|---|---|---|---|
| adapters/base.py (validate_output) | LOW | moderate (indirect) | MIGRATE: pure validation; keep dataclasses as Python contract |
| adapters/_labels.py | LOW | weak | MIGRATE: fold into base slice (69 lines) |
| adapters/mock.py | LOW | strong | STAY PYTHON: test double, zero hot-path value |
| adapters/jev.py | HIGH (class) | strong | STAY PYTHON; migrate pure sub-parts (Jev-family output-mapping shared with kev/laya/openjev-sglang) |
| adapters/kev.py | HIGH (class) | strong | STAY PYTHON |
| adapters/laya.py | HIGH (class) | strong | STAY PYTHON |
| adapters/lakera.py | HIGH (class) | strong | STAY PYTHON; guardrail verdict->AbstainOutput shared slice with omni_moderation |
| adapters/omni_moderation.py | HIGH (class) | strong | STAY PYTHON; joint guardrail slice with lakera |
| adapters/semif.py | HIGH (class) | strong | STAY PYTHON; richest pure logic (probability parser, renormalization) migratable |
| adapters/openjev_sglang.py | HIGH (class) | strong | STAY PYTHON (nothing worth migrating) |
| adapters/llm.py | HIGH (class) | strong | SPLIT: migrate pure middle (_validate_schema_object, _extract_json, _build_schema, refusal detection); transports stay |
| adapters/hf.py | HIGH (class) | strong | STAY PYTHON; migrate tiny pure math (_softmax, first-token-logprob proba, threshold map) |
| cli.py | HIGH (port) | moderate | STAY PYTHON: orchestration CLI; Rust CLI grows via read-only twins only |
| dashboard.py | MED | moderate (34) | SPLIT/MIGRATE aggregators later; leaderboard() registry I/O stays Python; pin pairwise_resample_ahead RNG first |
| templates.py | LOW | weak | STAY PYTHON: authoring data, docs-drift check wired to Python |
| review.py | MED | moderate | SPLIT: pure computation migratable, low priority |
| api_pins.py | LOW | strong (31) | MIGRATE: textbook slice |
| families.py | LOW | moderate | STAY PYTHON: static registry, docs-drift check wired to Python |
| probes/slots.py | MED-HIGH | moderate | MIGRATE LAST: bit-exact random.Random + difflib SequenceMatcher parity required; port small helpers first |
| probes/invariance.py | LOW | moderate | MIGRATE: trivial, bundle early |
| conversation.py | LOW | moderate | STAY PYTHON (facade) |
| combo.py | LOW | moderate | STAY PYTHON (facade) |
| conversation_schema.py | LOW-MED | weak | SPLIT: validate_conversation_dict follows schema.rs pattern; add tests |
| combo_schema.py | LOW | weak | MIGRATE validation + ID fns (early-queue candidate) |
| pricing.py | LOW | strong | FINISH: cost_usd done; migrate pricing_confidence; table loading stays Python |

Cross-cutting: dedupe _clamp01 (3 copies) + Jev-family question builders in
Rust; determinism landmines = slots.py random.Random bit-exact contract and
difflib payload protection (hardest parity in cluster C).

Suggested cluster-C slice order:
1. _labels.py + combo_schema.py + invariance.py (trivial)
2. api_pins.py validators
3. base.py validate_output
4. conversation_schema.py validation (schema.rs pattern)
5. llm.py pure middle (JSON-schema validator, _extract_json, refusal detection)
6. Jev-family + guardrail output-mapping slices
7. dashboard.py aggregators
8. pricing_confidence
9. probes/slots.py (last; parity harness first)

## Phase 1 results: Cluster B (pipeline) audit complete

| module | risk | tests | recommendation |
|---|---|---|---|
| runner.py | HIGH (async core) | weak (350 lines vs 3112) | SPLIT: async drivers stay Python forever; migrate pure carve-outs late (_assemble_timing, _validate_and_record, _transcript_entry with impurities as params, _infer_timeout_kind, validate_partial checks) |
| conversation_runner.py | HIGH | moderate | SPLIT: coroutine stays; pure helpers after runner slices |
| concurrency.py | HIGH (controller+cache) | strong | SPLIT: effectively DONE; AdaptiveConcurrency + ResponseCache stay Python forever |
| artifacts.py | LOW | moderate | MIGRATE #1: finish from_json + _checked_* validators (artifact.rs exists); byte-parity pitfalls documented (json.dumps separators, \uXXXX escaping, bool-vs-int, NaN asymmetry, unknown-field sets) |
| compare.py | LOW | moderate | MIGRATE #2: finish _delta/_severity_weights/_family_mdes/_directional_mdes/_net_benefit_comparison/pair_results/comparison_to_dict (compare.rs exists; RNG draws stay Python per PR #101) |
| dataset.py | MED | strong | SPLIT #5: migrate _parse_case_line, _verify_manifest_dict, _is_unsafe_manifest_name; atomic_write_text/build_manifest/canary/case_texts stay Python |
| schema.py | LOW | moderate | STAY: validator done; dataclass fights static typing |
| gates.py | LOW (G9 only) | moderate | MIGRATE #3: G9 gate_near_dedup only (rest done or IO); float pitfall: f"{sim:.3f}" formatting parity |
| combo_gates.py | MED (dep order) | moderate | MIGRATE #6: after combo_schema ports |
| conversation_gates.py | MED (dep order) | weak | MIGRATE #7: after conversation_schema ports |
| env_fingerprint.py | LOW / IO | weak | SPLIT: done; collection stays Python forever |
| provenance.py | LOW (build only) | strong | SPLIT #4: build_croissant migratable; git/file parts stay |
| runs_registry.py | MED | mod/strong | STAY PYTHON permanently (sqlite ops glue) |
| doctor.py | HIGH | mod/strong | STAY PYTHON permanently (platform IO diagnostics) |

Cluster B slice order: 1. artifacts.py from_json validators; 2. compare.py
finish; 3. gates.py G9; 4. provenance build_croissant; 5. dataset.py pure
slices; 6. combo_gates (after combo_schema); 7. conversation_gates (after
conversation_schema); 8. runner/conversation_runner carve-outs (late);
never: concurrency controller, runs_registry, doctor, env collection,
schema dataclass, atomic_write_text, async drivers.

## Combined cross-cluster migration queue (Phase 1 synthesis)

Wave 1 (trivial + pure, early wins):
  1. lottery.py (A-1: zero new Rust prereqs, strong tests)
  2. adapters/_labels.py + probes/invariance.py + combo_schema.py
     validation/ID fns (C-1, all trivial; add direct tests for _labels and
     combo_schema which are weak today)
  3. combo_metrics.py (A-2)
  4. hardness.py (A-3)
  5. api_pins.py validators (C-2)
Wave 2 (finish started ports):
  6. artifacts.py from_json + _checked_* validators (B-1)
  7. compare.py finish (B-2)
  8. pricing.py pricing_confidence (C-8; finish the pricing slice)
Wave 3 (metrics core expansions, unblock dependents):
  9. metrics.rs: flip_direction + net_benefit_at_threshold (block economics core)
  10. economics.py numeric core (A-4): SPLIT: YAML parser + cppf/break_even
      bootstraps stay Python (PRNG precedent)
  11. metrics.rs: mde_mcnemar (block saturation)
  12. saturation.py (A-6)
  13. stability.py numeric core (A-5): artifact sealing stays Python
Wave 4 (gates/provenance/dataset pure slices):
  14. gates.py G9 gate_near_dedup (B-3)
  15. provenance.py build_croissant (B-4)
  16. dataset.py pure slices (B-5)
  17. adapters/base.py validate_output (C-3)
  18. conversation_schema.py + combo_gates.py (C-4, B-6; schema first)
  19. conversation_gates.py (B-7)
Wave 5 (adapter pure middles, high value, bigger surface):
  20. llm.py pure middle (JSON-schema validator, _extract_json, refusal detection)
  21. Jev-family output-mapping (dedupe _clamp01 x3) + guardrail verdict slices
      (lakera + omni_moderation)
  22. semif.py probability parser/renormalization; hf.py _softmax/logprob math
Wave 6 (display/aggregation):
  23. dashboard.py aggregators (pin pairwise_resample_ahead RNG contract first)
  24. calibration.py SVG (byte-parity)
  25. economic_lottery.py (after lottery.py + economics core)
  26. review.py pure computation (low priority)
Wave 7 (late / conditional):
  27. runner.py + conversation_runner.py pure carve-outs
  28. probes/slots.py full port (needs bit-exact random.Random + difflib
      SequenceMatcher parity harness; do small helpers first)
  29. conversation_metrics.py (after conversation schema types exist in Rust)
  30. threshold_family.py (only if its Python-only decision is reopened)
Never migrate (permanent Python): provider transports + inference (llm/hf/jev/
kev/laya/lakera/omni/semif/openjev adapters), torch, subprocess spawning,
cli.py orchestration, runs_registry.py, doctor.py, env collection,
AtomicWrite + all file IO, async suite drivers, templates.py/families.py
static data + docs-drift checks, re-export facades, pricing table loading,
cppf/break_even bootstraps (PRNG), G1 gate reporting.
