# TESTS-AUDIT Findings — peira FINAL-AUDIT

**Worker:** TESTS-AUDIT · **Worktree:** `~/workspace/peira-final-audit`
**Audited HEAD:** `2821b7fd` (note: the worktree was at `15382b37` when this
task started; sibling final-audit lanes landed `cd2e93da`, `b780491d`,
`2821b7fd` during the audit — "fix tests for P1 changes", "fix red-team P1s
(ReDoS, ASR gaming)", "fix red-team P2s". All mutation results below were
re-verified against `2821b7fd`.)
**Method:** real mutation testing (mutants applied to a scratch copy under
`~/workspace/.tmp-tests-audit`, never to the worktree), targeted test-file
runs with `PEIRA_NO_RUST=1`, plus static analysis of all 130+ test files.
**Verdict up front:** the suite is strong — 11 of 12 behavior-breaking
mutants were caught, assertions are hand-computed (not tautological), and
the official run path is covered end to end. Two P1 gaps, one P2, four P3s.

---

## Mutation scorecard

| # | Mutant (file) | Target | Result |
|---|---------------|--------|--------|
| R1 | `runner.py` `_score_pair_py`: flip `or`→`and` | `test_runner.py::TestScorePairFlipSemantics` | **CAUGHT** (3 tests) |
| R2 | `runner.py` `validate_partial`: drop seed-mismatch rejection | `test_runner.py::TestValidatePartial` | **CAUGHT** (`test_seed_mismatch_rejected` + 2 cascade) |
| R3 | `runner.py`: `dispatch_base` off-by-one | `test_runner.py::TestResumeProgress` | **CAUGHT** (`test_dispatch_indices_are_suite_positioned_across_resume`) |
| M1 | `metrics.py` `_asr_conditional_py`: denominator = all cases, not eligible | `test_metrics.py` | **CAUGHT** (2 hand-computed tests) |
| M2 | `metrics.py` `_benign_accuracy_py`: inverted hits | `test_metrics.py` | **CAUGHT** (7 tests) |
| W1 | `metrics.py` `_wilson_ci_py`: z 1.96→1.0 | `test_metrics.py` | **CAUGHT** (6 tests) |
| G1 | `schema.py`: remove gold-in-options check | `test_gates.py` | **CAUGHT** (`test_g1_gold_must_be_in_options`) |
| A1 | `artifacts.py` `verify()` → always `True` | `test_artifacts.py` | **CAUGHT** (`test_lock_covers_metrics` + 2) |
| A2 | `artifacts.py` `from_json`: accept unknown fields | `test_artifacts.py` | **CAUGHT** (`test_unknown_field_rejected`) |
| C1 | `adapters/conformance.py`: determinism suite always passes | `test_adapter_conformance.py` | **CAUGHT** (`test_nondeterministic_fails_determinism`) |
| P1 | `report_html.py`: ASR formatted `.2f` not `.4f` | `integration/test_pipeline_end_to_end.py` | **CAUGHT** (`test_full_pipeline_end_to_end`) |
| H1 | `runner.py` `_pseudonymous_call_id_py`: leak `dispatch_index` into `call_id` | blindness tests | **SURVIVED** → P1 finding |
| E1 | `metrics.py` `_asr_excluding_malformed_py`: stop excluding malformed flips | `test_metrics.py` (full file, 320 tests) | **SURVIVED** → P1 finding |

---

## Ranked findings

### P1 — `call_id` opacity is not pinned; a dispatch-index leak passes all blindness tests

**Files:** `tests/integration/test_holdout_blindness.py:108`
(`test_adapter_never_sees_trial_bookkeeping`),
`tests/test_mock.py:174` (`test_context_carries_no_trial_bookkeeping`,
line 184), `python/peira/runner.py:1701`
(`_pseudonymous_call_id_py`), `python/peira/adapters/base.py:150-169`
(`CallContext` docstring).

**What's wrong:** the blind-holdout invariant (D-25/D-28) rests on
`call_id` being an opaque pseudonym — the docstring promises it "reveals
nothing about the case's family, suite, arm, holdout status, or real case
id". The tests check that `case_id`/family/labels don't appear in adapter
inputs/contexts, and `test_mock.py:184` asserts only
`ctx.call_id.startswith("call-")`. Nothing asserts the full format
`^call-[0-9a-f]{16}$`. I mutated `_pseudonymous_call_id_py` to return
`f"call-{dispatch_index}-{digest[:8]}"` — the dispatch index encodes the
arm (even = benign, odd = attacked) and the case's suite position — and
all 29 tests in `test_holdout_blindness.py`, `test_mock.py`, and
`test_determinism.py` still passed.

**Why it matters:** this is the test suite for the single most
security-sensitive runtime invariant in the repo (blind holdout
execution). A future refactor that degrades `call_id` opacity — e.g.
adding a debug suffix, switching to a sequential id — would ship with a
green suite while violating the documented contract the holdout protocol
depends on.

**Fix:** assert the exact format, e.g.
`re.fullmatch(r"call-[0-9a-f]{16}", ctx.call_id)` in
`test_mock.py::test_context_carries_no_trial_bookkeeping` and in the
integration blindness test's context inspection loop.

### P1 — `asr_excluding_malformed` (added 2026-10-02, commit `b780491d`) has zero test coverage

**Files:** `python/peira/metrics.py:498-530`
(`_asr_excluding_malformed_py`, `asr_excluding_malformed`); wired into
`summarize()` and therefore into every sealed artifact's metrics.

**What's wrong:** the red-team "ASR gaming" fix added this metric so the
leaderboard can separate true flips from malformed-driven flips. No test
in the repo references it (verified by grep and by mutation). I mutated
the numerator to count all flips — making it definitionally identical to
`asr_conditional`, defeating its entire purpose — and the full
`test_metrics.py` (320 tests) passed.

**Why it matters:** it is on the official-run path (sealed into
`artifact.metrics`, rendered in reports). A regression that silently
re-merges malformed flips into this metric would erase the exact signal
the red-team P1 fix was built to provide, with no test failing.

**Fix:** a hand-computed test with a scenario mixing malformed-driven and
genuine flips, asserting `asr_excluding_malformed < asr_conditional` with
exact expected values (the file's existing `_scenario_a` style).

### P2 — `test_run_timeout_stops_dispatch_drains_and_checkpoints` is a ~10s test whose documented choreography never happens

**File:** `tests/test_runner_timing.py:658` (class `TestRunTimeout`).

**What's wrong:** the test's comments describe a choreography — "wait
until two cases are in-flight (dispatched and blocked on the gate)",
"the run budget (0.05s) has fired by now", "release the gate so the
in-flight cases drain". I instrumented the runner's dispatch loop and the
test's poll loop. What actually happens: both case tasks dispatch, but
the `AdaptiveConcurrency` slow-start slot (`python/peira/runner.py:1345`,
`async with controller.slot()`) serializes the second case's `decide()`
behind the first case's `gate.wait(timeout=10.0)`, so
`in_flight_count` never reaches 2 — the poll loop (`test_runner_timing.py:701`)
times out at its 10s deadline having "never saw 2 (last=1)". The run
budget fires at 50ms as intended, the drain then waits out the full
`gate.wait(10.0)` expiry, both cases complete honestly,
`termination="timeout"`, 2 results — the assertions pass, but via the
gate timeout, not via the described release.

**Why it matters:** (a) every CI run pays ~10.2s for this one test
(measured 3/3 runs: 10.16–10.47s); (b) the comments actively misdescribe
the mechanism, so a future editor "fixing" the choreography could break
a passing test for the wrong reason; (c) the test's real coverage — drain
honesty under a fired budget — is valuable and should be kept, just
faster (e.g. `gate.wait(timeout=1.0)`) and with accurate comments.

**Not flaky:** the 50ms budget vs 10s gate has no tight race — both case
tasks are created synchronously in one dispatch-loop iteration, so the
deadline always fires with exactly the intended in-flight set. Slow, not
flaky.

### P3 — `test_known_values` for `wilson_ci` doesn't pin the value

**File:** `tests/test_metrics.py:139-142`.

**What's wrong:** it asserts only `lo < 0.8 < hi` for `wilson_ci(8, 10)`.
I verified by hand that a `z=1.0` (68% CI) implementation also satisfies
this (`(0.649, 0.896)`). The direct unit test for the CI function would
not catch a wrong confidence level. (The W1 mutant was caught by
hand-computed `summarize` tests, so the behavior is covered indirectly —
this is about the unit test's own strength.)

**Fix:** assert the hand-computed interval, e.g.
`assertEqual(wilson_ci(8, 10), (<lo>, <hi>))` to 4+ places, matching the
file's `_wilson` helper convention.

### P3 — Rust/Python parity tests are vacuous when the extension isn't built

**Files:** `tests/test_*_rust_parity.py` (13 files).

**What's wrong:** each test compares the dispatched public function
against its `_xxx_py` twin. With `PEIRA_NO_RUST=1` (or no compiled
`_core`), the dispatched name *is* the twin — the test compares the
function against itself and passes trivially (verified: 16/16 pass with
`PEIRA_NO_RUST=1` and `_impl = None`). The float comparisons themselves
are tight (`assertAlmostEqual(places=12)` — effectively exact for
`[0,1]`-ranged metrics; the three `places=3` hits are hand-computed known
values, not parity comparisons). No divergence vector found in the
tolerances.

**Why it matters (mild):** the design is documented
(`test_rust_execution_parity.py` docstring) and CI runs both modes, so
this is fine today. But if CI ever drops the Rust-active leg, the parity
suite becomes a green no-op — worth a comment or a
`RUST_AVAILABLE`-aware marker so a future reader doesn't misread the
coverage. `test_pipeline_backend_parity.py` already does the right thing
(`SkipTest` when Rust is absent).

### P3 — family-coverage floor (`>= 19`) is far below the actual 29 families

**File:** `tests/integration/test_family_coverage.py:39`.

**What's wrong:** with 29 families now registered and shipping cases, a
regression that silently dropped up to 10 families' case files would still
pass. The `without_cases` list is reported but not failed on.

**Fix:** pin the expected count (or assert `not without_cases`, failing
loudly when a registered family has no shipped cases).

### P3 — `test_cancelled_call_drops_child` relies on a 2.0s "let the call reach the child" sleep

**File:** `tests/test_adapter_subprocess.py:189`.

**What's wrong:** if the event loop stalls >2s between `open_subprocess_adapter`
and the sleep elapsing (extremely loaded CI), the cancel lands before the
call reaches the child and the `ProcessLookupError` assertion fails. In
practice the margin is generous (local spawn takes ms) — no evidence of
flakes, but it is the only test in the file with a wall-clock assumption
about scheduling latency rather than a protocol timeout.

---

## Checklist answers

### 1. Mutation testing — do the tests catch real bugs?
Yes, on the sampled critical paths: 11/12 mutants caught, including all
of runner flip semantics, resume validation (seed/adapter/dataset
checks), dispatch-index bookkeeping, ASR/benign-accuracy numerators and
denominators, Wilson z-level, G1 schema checks, artifact lock/verify and
strict `from_json`, adapter determinism conformance, and report number
formatting. Every caught mutant failed on a test that names the exact
property broken — no coincidental passes. The two survivors are the P1
findings above.

### 2. Tautological tests?
None found that are genuinely tautological. Spot-checked the suspicious
candidates: `test_metrics.py` uses hand-computed values (`-(ln 0.9 +
ln 0.8)/2`, independent Wilson helper); `test_each_case_validated_once`
uses a `wraps=` spy counting real calls; `test_transcript_round_trips_timeout_kind`
asserts the field value on both backends rather than comparing the
function to itself; `test_concurrent_first_load_happens_once` widens a
race window to make a *broken* lock fail, which is the correct shape for
a concurrency test. The closest to tautology is the parity-suite
self-comparison without Rust (P3 above) — documented and CI-mitigated.

### 3. Run-path coverage (dataset load → runner → metrics → artifact seal → report)
Every step has at least one regression-catching test:
- **Dataset load:** `test_dataset.py` (incl. `run_gates` on real data,
  line 417), `test_check_families.py::test_live_repo_agrees`,
  integration `sample_v1_cases` loads the real v1 corpus.
- **Runner:** `test_runner.py` (597 lines: resume, flip semantics,
  sidecars, replay), `test_runner_timing.py`, `test_determinism.py`,
  `test_concurrency.py`.
- **Metrics:** `test_metrics.py` (4k lines, hand-computed scenarios),
  `test_flip_direction.py`, `test_calibration.py`.
- **Artifact seal:** `test_artifacts.py` (strict `from_json`, lock
  binding seed/metrics), `integration/test_artifact_roundtrip.py`
  (tamper → `verify()` false, old schema versions rejected); the
  runner-attaches-metrics step is pinned by conversational tests asserting
  `artifact.metrics[...]` after real runs.
- **Report:** `test_report.py` (`cmd_report` on real artifacts, corrupt
  input exits, XSS escaping), `test_report_html_contract.py`,
  integration `test_full_pipeline_end_to_end` (real metrics → HTML, exact
  `.4f` cell content — caught the P1 format mutant).
- **Compare (two-artifact path):** `integration/test_compare_pipeline.py`.
- **Gap:** the newly added `asr_excluding_malformed` metric (P1 above) —
  the only run-path code without a pinning test.

### 4. Parity: exact or "close enough"?
Exact in practice: `assertAlmostEqual(places=12)` on `[0,1]`-ranged
floats (≈1e-12 absolute; float64 ulp there is ~2e-16), plus `assertEqual`
on all ints/strings/dicts. The theoretical caveat in `peira/_rust.py`
("up to ~1 ulp of float summation order") cannot slip a meaningful
divergence through `places=12` at these magnitudes, and
`test_pipeline_backend_parity.py` asserts **byte-identical** normalized
payloads across backends via separate subprocesses. No looseness found.

### 5. Integration tests (`tests/integration/`, #386): overlap or new ground?
Mostly new ground, and the overlap is justified:
- `test_pipeline_end_to_end.py` — new: the only test that fails when
  stages disagree (renamed metrics key, report column drift). Proved by
  the P1 mutant, which no unit test caught.
- `test_pipeline_backend_parity.py` — justified overlap: pipeline-level
  parity catches divergence (summation order, hash, default) that
  function-level parity misses; honest subprocess mechanism; clean skip
  without Rust.
- `test_pipeline_determinism.py` — new: extends `test_determinism.py`
  (trial-demo) to the multi-family v1 sample + fresh-nonce rerun.
- `test_holdout_blindness.py` — new: adapter-boundary invariant (D-25/D-28);
  **has the P1 `call_id`-format gap**.
- `test_artifact_roundtrip.py`, `test_compare_pipeline.py`,
  `test_family_coverage.py`, `test_mock_pipeline_behaviors.py` — new
  pipeline-level ground (disk round-trip, pair-and-compare, per-family
  smoke, mock behavior contracts).
- No pure duplication found; the one duplication-adjacent case
  (backend parity vs unit parity) is explicitly motivated in its docstring.

### 6. Flaky tests?
No evidence of actual flakes. Timed/sleeping tests reviewed:
- `test_runner_timing.py::TestRunTimeout` — slow (~10s) but deterministic
  (P2 above); no tight race.
- `test_runs_registry.py::test_concurrent_writer_waits_instead_of_crashing`
  — 7s hold vs 30s sqlite busy-timeout; deterministic.
- `test_adapter_subprocess.py::test_cancelled_call_drops_child` — 2s
  scheduling assumption (P3 above); generous margin.
- `test_hf_adapters.py::test_concurrent_first_load_happens_once` — race
  window deliberately widened to catch broken locking; correct design.
- Randomness is seeded everywhere (`random.Random(<const>)`); no unseeded
  `random.*` calls in tests. Env-var manipulation restores in `finally`.
  No module-level mutable test state (xdist-safe). Per-test timeout is
  900s (`timeout_method = "thread"`), comfortably above the slowest test.

---

## Notes for the parent
- The worktree moved from `15382b37` to `2821b7fd` during this audit
  (sibling lanes landing red-team fixes). All mutation verdicts above
  were re-run against `2821b7fd`; the H1 and E1 survivors were confirmed
  on the fresh HEAD with clean, uncontended runs.
- One methodological catch worth knowing: two of my own background
  mutation runs briefly raced on the same scratch file and contaminated
  each other (an "E1 caught" result that was actually the concurrent M1
  mutant's signature). I detected it via the failure signature, re-ran
  cleanly, and the true verdict is **SURVIVED**. The scorecard above
  reflects only clean runs; the scratch dir is `~/workspace/.tmp-tests-audit`
  (safe to delete).
- Suggested fix priority: P1 `call_id` format pin (small, security-contract),
  P1 `asr_excluding_malformed` hand-computed test (small, new-code gap),
  then P2 timing-test speedup/comment correction.
