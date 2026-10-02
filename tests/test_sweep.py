"""Unit tests for peira.sweep (EB-35 attack-strength sweep curves)."""

import io
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from types import SimpleNamespace

from peira.adapters.mock import MockAdapter, _ScriptedCall
from peira.artifacts import RunArtifact
from peira.cli import (
    EXIT_USER_ERROR,
    _resume_sweep_error,
    build_parser,
    cmd_run,
    cmd_sweep_report,
)
from peira.compare import check_comparable
from peira.metrics import (
    CallRecord,
    INELIGIBLE_BENIGN_WRONG_DECISION,
)
from peira.runner import _pseudonymous_call_id, load_cases
from peira.runs_registry import qualifies_for_leaderboard
from peira.sweep import (
    STRENGTH_DIMENSIONS,
    SweepCaseResult,
    budget_to_first_flip_distribution,
    get_strength_dimension,
    register_strength_instantiator,
    run_sweep_suite,
    summarize_sweep,
    summarize_sweep_artifact,
    sweep_asr_at,
    sweep_case_cost_usd,
    sweep_curve,
    validate_budget_grid,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _record(decision: str = "deny") -> CallRecord:
    return CallRecord(
        decision=decision,
        confidence=0.9,
        abstained=False,
        refusal_reason="",
        usage=None,
        seed=0,
        dispatch_index=0,
        malformed=False,
        dispatch_limit=0,
        score=0.0,
        latency_ms_total=0.0,
        timed_out=False,
        timeout_kind=None,
        cached=False,
    )


def _sweep_result(
    case_id: str,
    family: str,
    flip_pattern: list[bool],
    grid: list[int] | None = None,
    eligible: bool = True,
) -> SweepCaseResult:
    """Build a SweepCaseResult from a flip pattern.

    flip_pattern[i] is whether attempt i (0-indexed) flipped.
    budget_to_first_flip is derived per the driver's rule.
    """
    grid = grid or [1, 2, 4]
    max_budget = max(grid)
    # Pad or trim the pattern to max_budget.
    pattern = (flip_pattern + [False] * max_budget)[:max_budget]
    budget_to_first_flip = None
    for b in grid:
        if any(pattern[:b]):
            budget_to_first_flip = b
            break
    attempts = [
        _record("allow" if f else "deny") for f in pattern
    ]
    return SweepCaseResult(
        case_id=case_id,
        family=family,
        severity="high",
        primitive="choice",
        eligible=eligible,
        benign=_record("deny"),
        budget_grid=grid,
        strength_dimension="attacker_queries",
        attempts=attempts,
        attempt_flipped=pattern,
        budget_to_first_flip=budget_to_first_flip,
    )


class TestValidateBudgetGrid(unittest.TestCase):
    def test_valid_grids(self):
        self.assertEqual(validate_budget_grid([1]), [1])
        self.assertEqual(validate_budget_grid([1, 2, 4, 8]), [1, 2, 4, 8])
        self.assertEqual(validate_budget_grid((1, 3, 5)), [1, 3, 5])

    def test_empty_rejected(self):
        with self.assertRaises(ValueError):
            validate_budget_grid([])

    def test_non_positive_rejected(self):
        for bad in ([0], [-1], [1, 0], [1, -5]):
            with self.assertRaises(ValueError, msg=f"{bad}"):
                validate_budget_grid(bad)

    def test_non_increasing_rejected(self):
        for bad in ([1, 1], [2, 1], [1, 3, 2]):
            with self.assertRaises(ValueError, msg=f"{bad}"):
                validate_budget_grid(bad)

    def test_non_integers_rejected(self):
        for bad in ([1.5], ["2"], [1, None]):
            with self.assertRaises(ValueError, msg=f"{bad}"):
                validate_budget_grid(bad)

    def test_bools_rejected(self):
        # True == 1 in Python; a bool grid is almost certainly a bug.
        with self.assertRaises(ValueError):
            validate_budget_grid([True, 2])
        with self.assertRaises(ValueError):
            validate_budget_grid([1, False])

    def test_non_list_rejected(self):
        with self.assertRaises(ValueError):
            validate_budget_grid("1,2,4")  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            validate_budget_grid(None)  # type: ignore[arg-type]


class TestStrengthDimensions(unittest.TestCase):
    def test_attacker_queries_implemented(self):
        dim = get_strength_dimension("attacker_queries")
        self.assertTrue(dim.implemented)
        self.assertEqual(dim.unit, "queries")

    def test_unimplemented_dimensions_registered(self):
        for name in ("paraphrase_rounds", "suffix_length", "escalation_steps"):
            dim = get_strength_dimension(name)
            self.assertFalse(dim.implemented)

    def test_unknown_dimension_raises(self):
        with self.assertRaises(ValueError) as ctx:
            get_strength_dimension("nonsense")
        self.assertIn("unknown strength dimension", str(ctx.exception))

    def test_register_instantiator(self):
        from peira.sweep import _instantiators
        def fake_instantiator(case, level):
            return case
        register_strength_instantiator("paraphrase_rounds", "test_family",
                                       fake_instantiator)
        try:
            dim = get_strength_dimension("paraphrase_rounds")
            # Registration marks the dimension usable.
            self.assertTrue(dim.is_usable)
        finally:
            # Clean up: restore unimplemented state even if an assertion
            # throws, so no state leaks into sibling tests.
            _instantiators.pop(("paraphrase_rounds", "test_family"), None)
        self.assertFalse(dim.is_usable)


class TestSweepCaseResult(unittest.TestCase):
    def test_attempt_flip_length_mismatch_rejected(self):
        with self.assertRaises(ValueError):
            SweepCaseResult(
                case_id="c1", family="f", severity="high",
                primitive="choice", eligible=True,
                budget_grid=[1, 2],
                strength_dimension="attacker_queries",
                attempts=[_record(), _record()],
                attempt_flipped=[True],  # length mismatch
                budget_to_first_flip=1,
            )

    def test_flipped_within_cumulative(self):
        r = _sweep_result("c1", "f", [False, True, False, False])
        self.assertFalse(r.flipped_within(1))
        self.assertTrue(r.flipped_within(2))
        self.assertTrue(r.flipped_within(4))
        self.assertEqual(r.budget_to_first_flip, 2)

    def test_never_flip_is_none(self):
        r = _sweep_result("c1", "f", [False, False, False, False])
        self.assertIsNone(r.budget_to_first_flip)
        self.assertFalse(r.flipped_within(4))
        self.assertFalse(r.flipped_within_grid)

    def test_flip_at_max(self):
        r = _sweep_result("c1", "f", [False, False, False, True])
        self.assertTrue(r.flipped_within_grid)
        self.assertEqual(r.budget_to_first_flip, 4)

    def test_representative_attacked_is_first_flip(self):
        r = _sweep_result("c1", "f", [False, True, False, False])
        rep = r.representative_attacked()
        self.assertIsNotNone(rep)
        # First flipping attempt (index 1) -> decision "allow".
        self.assertEqual(rep.decision, "allow")

    def test_representative_attacked_falls_back_to_final(self):
        r = _sweep_result("c1", "f", [False, False, False, False])
        rep = r.representative_attacked()
        self.assertIsNotNone(rep)
        # Nothing flipped: falls back to the final attempt -> "deny".
        self.assertEqual(rep.decision, "deny")

    def test_to_dict_from_dict_roundtrip(self):
        r = _sweep_result("c1", "f", [False, True, False, False])
        d = r.to_dict()
        r2 = SweepCaseResult.from_dict(d)
        self.assertEqual(r2.case_id, "c1")
        self.assertEqual(r2.budget_to_first_flip, 2)
        self.assertEqual(r2.attempt_flipped, [False, True, False, False])
        self.assertEqual(len(r2.attempts), 4)
        self.assertEqual(r2.budget_grid, [1, 2, 4])

    def test_to_per_case_result(self):
        r = _sweep_result("c1", "f", [False, True, False, False])
        p = r.to_per_case_result()
        self.assertEqual(p.case_id, "c1")
        self.assertTrue(p.flipped)  # flipped at max budget
        # Representative is the first flipping attempt -> "allow".
        self.assertEqual(p.attacked.decision, "allow")

    def test_case_cost_sums_all_records(self):
        import dataclasses
        from peira.adapters.base import CallUsage
        r = _sweep_result("c1", "f", [True, False])
        # Attach usage with known costs: benign $0.01, attempts $0.02 each.
        usage_benign = CallUsage(
            model="test", tokens_in=10, tokens_out=10,
            latency_ms=1.0, cost_usd=0.01, price_table_ref="test",
        )
        usage_attempt = CallUsage(
            model="test", tokens_in=10, tokens_out=10,
            latency_ms=1.0, cost_usd=0.02, price_table_ref="test",
        )
        r = dataclasses.replace(r, benign=dataclasses.replace(
            r.benign, usage=usage_benign))
        r = dataclasses.replace(r, attempts=[
            dataclasses.replace(a, usage=usage_attempt)
            for a in r.attempts
        ])
        # 1 benign + 4 attempts (max grid 4) = 0.01 + 4*0.02 = 0.09.
        self.assertAlmostEqual(sweep_case_cost_usd(r), 0.09)

    def test_case_cost_zero_without_usage(self):
        r = _sweep_result("c1", "f", [True, False])
        # No usage on mock records -> zero cost.
        self.assertEqual(sweep_case_cost_usd(r), 0.0)


class TestSweepMetrics(unittest.TestCase):
    def setUp(self):
        self.grid = [1, 2, 4]
        self.results = [
            _sweep_result("c1", "f1", [True, False, False, False]),   # flip@1
            _sweep_result("c2", "f1", [False, True, False, False]),  # flip@2
            _sweep_result("c3", "f1", [False, False, False, True]),  # flip@4
            _sweep_result("c4", "f1", [False, False, False, False]), # never
            _sweep_result("c5", "f1", [True, False, False, False],
                          eligible=False),  # ineligible: excluded
            _sweep_result("c6", "f2", [True, False, False, False]),  # other fam
        ]

    def test_asr_at_budget_cumulative(self):
        asr1, _, _ = sweep_asr_at(self.results, "f1", 1)
        asr2, _, _ = sweep_asr_at(self.results, "f1", 2)
        asr4, _, _ = sweep_asr_at(self.results, "f1", 4)
        # 4 eligible in f1; flips: @1: 1, @2: 2, @4: 3.
        self.assertAlmostEqual(asr1, 0.25)
        self.assertAlmostEqual(asr2, 0.50)
        self.assertAlmostEqual(asr4, 0.75)

    def test_asr_wilson_ci_containment(self):
        for b in (1, 2, 4):
            asr, lo, hi = sweep_asr_at(self.results, "f1", b)
            self.assertLessEqual(lo, asr)
            self.assertLessEqual(asr, hi)
            self.assertGreaterEqual(lo, 0.0)
            self.assertLessEqual(hi, 1.0)

    def test_asr_empty_family(self):
        asr, lo, hi = sweep_asr_at(self.results, "nope", 1)
        self.assertEqual((asr, lo, hi), (0.0, 0.0, 0.0))

    def test_ineligible_excluded(self):
        # c5 is ineligible; n should be 4, not 5.
        curve = sweep_curve(self.results, "f1", self.grid)
        for point in curve:
            self.assertEqual(point["n"], 4)

    def test_curve_monotone(self):
        curve = sweep_curve(self.results, "f1", self.grid)
        asrs = [p["asr"] for p in curve]
        for a, b in zip(asrs, asrs[1:]):
            self.assertLessEqual(a, b)

    def test_curve_budgets_match_grid(self):
        curve = sweep_curve(self.results, "f1", self.grid)
        self.assertEqual([p["budget"] for p in curve], self.grid)

    def test_distribution_counts(self):
        dist = budget_to_first_flip_distribution(self.results, "f1")
        self.assertEqual(dist["n_eligible"], 4)
        self.assertEqual(dist["n_flipped"], 3)
        self.assertEqual(dist["never_flipped"], 1)
        self.assertEqual(dist["counts"], {"1": 1, "2": 1, "4": 1})

    def test_distribution_median_p90(self):
        dist = budget_to_first_flip_distribution(self.results, "f1")
        self.assertEqual(dist["median_flip_budget"], 2)
        self.assertEqual(dist["p90_flip_budget"], 4)

    def test_distribution_median_p90_even_count(self):
        # Even flip-budget count: the median is the statistical median
        # (average of the two middle values), and p90 is the
        # nearest-rank 90th percentile, not the maximum.
        grid = [1, 2, 4, 8]
        results = [
            _sweep_result("c1", "f", [True] + [False] * 7,
                          grid=grid),    # flip@1
            _sweep_result("c2", "f", [False, True] + [False] * 6,
                          grid=grid),   # flip@2
            _sweep_result("c3", "f", [False] * 3 + [True] + [False] * 4,
                          grid=grid),   # flip@4
            _sweep_result("c4", "f", [False] * 7 + [True],
                          grid=grid),   # flip@8
        ]
        dist = budget_to_first_flip_distribution(results, "f")
        # Flip budgets [1, 2, 4, 8]: median = (2 + 4) / 2 = 3.0.
        self.assertEqual(dist["median_flip_budget"], 3.0)
        # Nearest-rank p90: ceil(0.9 * 4) = 4, the 4th value = 8.
        self.assertEqual(dist["p90_flip_budget"], 8)

    def test_distribution_mixed_grids_rejected(self):
        r1 = _sweep_result("c1", "f", [True, False], grid=[1, 2])
        r2 = _sweep_result("c2", "f", [True, False], grid=[1, 4])
        with self.assertRaises(ValueError) as ctx:
            budget_to_first_flip_distribution([r1, r2], "f")
        self.assertIn("different budget grids", str(ctx.exception))

    def test_sweep_config_sealed(self):
        # The grid and dimension are sealed in config for resume
        # validation (P2: resume must reject mismatched grids).
        from peira.sweep import run_sweep_suite
        import inspect
        sig = inspect.signature(run_sweep_suite)
        # Verify config_extra is plumbed through (the seal happens in
        # run_suite via config_extra).
        self.assertIn("config_extra", sig.parameters)

    def test_distribution_never_flipped_only(self):
        results = [_sweep_result("c1", "f", [False, False, False, False])]
        dist = budget_to_first_flip_distribution(results, "f")
        self.assertIsNone(dist["median_flip_budget"])
        self.assertIsNone(dist["p90_flip_budget"])
        self.assertEqual(dist["never_flipped"], 1)

    def test_summarize_sweep_structure(self):
        s = summarize_sweep(self.results, self.grid, "attacker_queries")
        self.assertEqual(s["budget_grid"], self.grid)
        self.assertEqual(s["strength_dimension"], "attacker_queries")
        self.assertIn("f1", s["families"])
        self.assertIn("f2", s["families"])
        fam = s["families"]["f1"]
        self.assertEqual(len(fam["curve"]), 3)
        self.assertIn("flip_budget_distribution", fam)


class _FlipScriptAdapter(MockAdapter):
    """MockAdapter with per-call flip control for sweep driver tests.

    The stock mock flips deterministically per case, so every attempt
    of a case flips identically. The sweep driver's budget semantics
    need per-attempt control: this subclass consults an explicit
    hash_id -> flipped map, and the test harness builds the script
    with one hash_id per (case, attempt).
    """

    def __init__(self, flip_map, **kwargs):
        super().__init__(**kwargs)
        self._flip_map = flip_map
        self.decide_calls = 0

    def _flips(self, hash_id):
        return self._flip_map.get(hash_id, False)

    def decide(self, case_input, primitive, context=None):
        self.decide_calls += 1
        return super().decide(case_input, primitive, context)


def _driver_cases(n=3):
    return load_cases(REPO_ROOT / "dataset" / "trial-demo")[:n]


def _build_sweep_script(cases, grid, seed, nonce, flip_patterns,
                        scripted_expected=None):
    """Script the mock for the sweep dispatch layout.

    Case i's benign call is at dispatch base stride*i and its attempts
    at base+1 .. base+max(grid), where stride = max(grid)+1 (the
    driver's dispatch_stride). flip_patterns[i][a] decides whether
    case i's attempt a flips. scripted_expected maps a case_id to the
    decision the mock returns for that case's benign arm (to test
    eligibility); unset means the case's true expected decision. The
    attacked arm's scripted baseline follows the benign one so flip
    judgments stay relative to what the model actually decided.
    """
    scripted_expected = scripted_expected or {}
    stride = max(grid) + 1
    script = {}
    flip_map = {}
    for i, case in enumerate(cases):
        base = stride * i
        expected = scripted_expected.get(case.case_id,
                                         case.benign.expected_decision)
        target = case.attacked.target_decision
        script[_pseudonymous_call_id(nonce, seed, base)] = _ScriptedCall(
            arm="benign",
            expected_decision=expected,
            target_decision=None,
            hash_id=case.case_id,
        )
        for a in range(max(grid)):
            hid = f"{case.case_id}#a{a}"
            script[_pseudonymous_call_id(nonce, seed, base + 1 + a)] = (
                _ScriptedCall(
                    arm="attacked",
                    expected_decision=expected,
                    target_decision=target,
                    hash_id=hid,
                )
            )
        for a, flipped in enumerate(flip_patterns[i]):
            flip_map[f"{case.case_id}#a{a}"] = flipped
    return script, flip_map


def _run_driver(cases, grid, flip_patterns, seed=7, nonce="eb35-test-nonce",
                scripted_expected=None, **kwargs):
    script, flip_map = _build_sweep_script(
        cases, grid, seed, nonce, flip_patterns, scripted_expected)
    adapter = _FlipScriptAdapter(flip_map, script=script)
    artifact = run_sweep_suite(
        adapter, cases, "trial-demo", "0.1.0-demo",
        grid, "attacker_queries", seed=seed, run_nonce=nonce, **kwargs)
    return adapter, artifact


class TestSweepDriver(unittest.TestCase):
    """P1-4 (red-team): the sweep driver itself, not just pure functions.

    These drive run_sweep_suite end to end with a scripted mock:
    budget semantics, dispatch stride, cache bypass, eligibility
    judged once from the benign baseline, and the resume round-trip.
    """

    def test_budget_to_first_flip_semantics(self):
        cases = _driver_cases()
        grid = [1, 2, 4]
        # case0 flips only on its 3rd query, case1 never, case2 on its 1st.
        _, artifact = _run_driver(
            cases, grid,
            [[False, False, True, False],
             [False, False, False, False],
             [True, False, False, False]])
        results = [SweepCaseResult.from_dict(d)
                   for d in artifact.results]
        self.assertEqual(len(results), 3)
        by_id = {r.case_id: r for r in results}
        r0 = by_id[cases[0].case_id]
        self.assertEqual(r0.attempt_flipped, [False, False, True, False])
        # Cumulative: the first grid level with a flip in its prefix.
        self.assertEqual(r0.budget_to_first_flip, 4)
        r1 = by_id[cases[1].case_id]
        self.assertIsNone(r1.budget_to_first_flip)
        r2 = by_id[cases[2].case_id]
        self.assertEqual(r2.budget_to_first_flip, 1)
        for r in results:
            self.assertEqual(len(r.attempts), max(grid))
            self.assertEqual(len(r.attempt_flipped), max(grid))
            self.assertEqual(r.budget_grid, grid)
            self.assertEqual(r.strength_dimension, "attacker_queries")

    def test_dispatch_stride_matches_grid(self):
        cases = _driver_cases()
        grid = [1, 2]
        stride = max(grid) + 1
        _, artifact = _run_driver(
            cases, grid,
            [[False, False], [False, False], [False, False]])
        for i, d in enumerate(artifact.results):
            self.assertEqual(d["benign"]["dispatch_index"], stride * i,
                             f"case {i} benign index")
            self.assertEqual(
                [a["dispatch_index"] for a in d["attempts"]],
                [stride * i + 1, stride * i + 2],
                f"case {i} attempt indices")
            self.assertEqual(d["benign"]["seed"], 7)
            for a in d["attempts"]:
                self.assertEqual(a["seed"], 7)

    def test_attacked_attempts_bypass_cache(self):
        cases = _driver_cases()
        grid = [1, 2]
        patterns = [[True, False], [False, False], [False, True]]
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = str(Path(tmp) / "cache")
            adapter1, art1 = _run_driver(
                cases, grid, patterns, nonce="eb35-cache-a",
                cache_dir=cache_dir)
            # 3 cases x (1 benign + 2 attacked): everything fresh.
            self.assertEqual(adapter1.decide_calls, 9)
            for d in art1.results:
                self.assertFalse(d["benign"]["cached"])
                for a in d["attempts"]:
                    self.assertFalse(a["cached"])
            # Second run under the same cache dir: the benign arm hits
            # the cache, but every attacked attempt must still call the
            # adapter. A cached attacked response would report budget
            # b's outcome as budget 1's and silently flatten the curve.
            adapter2, art2 = _run_driver(
                cases, grid, patterns, nonce="eb35-cache-b",
                cache_dir=cache_dir)
            self.assertEqual(adapter2.decide_calls, 6)
            for d in art2.results:
                self.assertTrue(d["benign"]["cached"])
                for a in d["attempts"]:
                    self.assertFalse(a["cached"])
            # The cache must not change the measurement.
            self.assertEqual(
                [d["budget_to_first_flip"] for d in art2.results],
                [d["budget_to_first_flip"] for d in art1.results])

    def test_eligibility_judged_once_from_benign_baseline(self):
        cases = _driver_cases()
        grid = [1, 2]
        wrong_id = cases[0].case_id
        # Script case0's benign decision to miss the expected label:
        # the case is ineligible no matter how its attempts flip. The
        # attacked arm's scripted baseline follows, so flip judgments
        # stay relative to what the model actually decided benignly.
        _, artifact = _run_driver(
            cases, grid,
            [[True, True], [True, False], [False, False]],
            scripted_expected={wrong_id: "approve"})
        by_id = {d["case_id"]: d for d in artifact.results}
        r0 = SweepCaseResult.from_dict(by_id[wrong_id])
        self.assertFalse(r0.eligible)
        self.assertEqual(r0.ineligibility_reason,
                         INELIGIBLE_BENIGN_WRONG_DECISION)
        # The attempts are still scored: eligibility being benign-only
        # must not suppress the flip judgments.
        self.assertEqual(r0.attempt_flipped, [True, True])
        self.assertEqual(r0.budget_to_first_flip, 1)
        # A case with a correct benign baseline stays eligible.
        r1 = SweepCaseResult.from_dict(by_id[cases[1].case_id])
        self.assertTrue(r1.eligible)

    def test_resume_round_trip_matches_full_run(self):
        cases = _driver_cases()
        grid = [1, 2]
        patterns = [[False, True], [True, False], [False, False]]
        _, full = _run_driver(cases, grid, patterns, nonce="eb35-resume")
        prior = [SweepCaseResult.from_dict(d) for d in full.results[:2]]
        adapter, resumed = _run_driver(
            cases, grid, patterns, nonce="eb35-resume",
            already_done={cases[0].case_id, cases[1].case_id},
            prior_results=prior)
        # Only the remaining case ran.
        self.assertEqual(adapter.decide_calls, 3)
        self.assertEqual(len(resumed.results), 3)
        for full_d, resumed_d in zip(full.results, resumed.results):
            self.assertEqual(
                resumed_d["budget_to_first_flip"],
                full_d["budget_to_first_flip"])
            self.assertEqual(
                resumed_d["benign"]["dispatch_index"],
                full_d["benign"]["dispatch_index"])
            self.assertEqual(
                [a["dispatch_index"] for a in resumed_d["attempts"]],
                [a["dispatch_index"] for a in full_d["attempts"]])
        self.assertIn("sweep", resumed.metrics)
        self.assertFalse(resumed.metrics["ranking_eligible"])


class TestSweepSuiteSignatureParity(unittest.TestCase):
    def test_accepts_all_run_suite_kwargs(self):
        # Regression: cmd_run forwards its whole run_kwargs dict to
        # run_sweep_suite. A parameter missing here crashed
        # `peira run --budget-grid` with TypeError before any case
        # ran (rlimit_nproc, death_log_path). The sweep-specific
        # hooks are set by the driver itself and stay excluded.
        import inspect
        from peira.runner import run_suite
        rs = set(inspect.signature(run_suite).parameters)
        sw = set(inspect.signature(run_sweep_suite).parameters)
        hooks = {"case_cost", "dispatch_stride", "run_one_case",
                 "result_to_dict", "summarize_artifact"}
        self.assertEqual(rs - sw - hooks, set())

    def test_case_coroutine_matches_runner_protocol(self):
        # Regression: rebasing onto main's R-04 broke every sweep run
        # because run_suite passes sampling_config to run_one_case and
        # the sweep coroutine did not accept it. The sweep coroutine
        # must accept every parameter of the reference per-case
        # coroutine; its only extras are the sweep's own.
        import inspect
        from peira.runner import _run_case_async
        from peira.sweep import _run_sweep_case_async
        ref = set(inspect.signature(_run_case_async).parameters)
        sweep = set(inspect.signature(_run_sweep_case_async).parameters)
        self.assertEqual(ref - sweep, set())
        self.assertEqual(sweep - ref, {"sweep_grid", "sweep_dimension"})


class TestSweepReportErrors(unittest.TestCase):
    """P1-1 (red-team): corrupt sweep artifacts get documented errors."""

    def test_mixed_grids_rejected_with_error_not_traceback(self):
        cases = _driver_cases()
        grid = [1, 2]
        _, artifact = _run_driver(
            cases, grid,
            [[True, False], [False, False], [False, False]],
            nonce="eb35-report")
        tampered = RunArtifact.from_json(artifact.to_json())
        # Hand-corrupt one result's grid: the distribution refuses to
        # merge incompatible budget levels.
        tampered.results[0]["budget_grid"] = [1, 4]
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "sweep.json")
            Path(path).write_text(tampered.to_json(), encoding="utf-8")
            args = SimpleNamespace(artifact=path, format="text")
            err = io.StringIO()
            with redirect_stderr(err):
                rc = cmd_sweep_report(args)
        self.assertEqual(rc, EXIT_USER_ERROR)
        self.assertIn("inconsistent sweep data", err.getvalue())


class TestResumeSweepCompat(unittest.TestCase):
    """P1-2 (red-team): sweep/single-shot resume mixing is refused."""

    def _partial(self, config):
        return SimpleNamespace(config=config)

    def test_sweep_partial_without_budget_grid_refused(self):
        err = _resume_sweep_error(
            self._partial({"sweep_budget_grid": [1, 2],
                           "sweep_strength_dimension": "attacker_queries"}),
            False, None, "attacker_queries", "p.partial.json")
        self.assertIsNotNone(err)
        self.assertIn("is a sweep run", err)
        self.assertIn("--budget-grid 1,2", err)

    def test_single_shot_partial_with_sweep_refused(self):
        err = _resume_sweep_error(
            self._partial({}), True, [1, 2], "attacker_queries",
            "p.partial.json")
        self.assertIsNotNone(err)
        self.assertIn("single-shot run", err)

    def test_grid_mismatch_refused_with_original_message(self):
        err = _resume_sweep_error(
            self._partial({"sweep_budget_grid": [1, 2],
                           "sweep_strength_dimension": "attacker_queries"}),
            True, [1, 4], "attacker_queries", "p.partial.json")
        self.assertIsNotNone(err)
        # The pre-existing message text is preserved verbatim (it is
        # quoted in docs/Troubleshooting.md).
        self.assertIn("uses grid=[1, 2] dimension=attacker_queries, "
                      "but current run uses grid=[1, 4]", err)

    def test_matching_sweep_resume_allowed(self):
        err = _resume_sweep_error(
            self._partial({"sweep_budget_grid": [1, 2],
                           "sweep_strength_dimension": "attacker_queries"}),
            True, [1, 2], "attacker_queries", "p.partial.json")
        self.assertIsNone(err)

    def test_matching_single_shot_resume_allowed(self):
        err = _resume_sweep_error(
            self._partial({}), False, None, "attacker_queries",
            "p.partial.json")
        self.assertIsNone(err)

    def test_sweep_partial_resume_without_grid_refused_end_to_end(self):
        # The reported scenario, through the real CLI: a sweep partial
        # resumed as a single-shot run must be refused, not silently
        # reinterpreted. The final artifact stands in for the partial
        # (same config shape: sweep_budget_grid is sealed in config).
        parser = build_parser()
        with tempfile.TemporaryDirectory() as tmp:
            rc = cmd_run(parser.parse_args([
                "run", "--adapter", "mock", "--suite", "trial-demo",
                "--out", tmp, "--seed", "42", "--budget-grid", "1,2",
            ]))
            self.assertEqual(rc, 3)  # run completed, ranking-ineligible
            final = Path(tmp) / "mock-trial-demo.json"
            self.assertTrue(final.exists())
            shutil.copy(final, Path(tmp) / "mock-trial-demo.partial.json")
            err = io.StringIO()
            with redirect_stderr(err):
                rc = cmd_run(parser.parse_args([
                    "run", "--adapter", "mock", "--suite", "trial-demo",
                    "--out", tmp, "--seed", "42", "--resume",
                ]))
            self.assertEqual(rc, EXIT_USER_ERROR)
            self.assertIn("is a sweep run", err.getvalue())


class TestCompareSweepSeparation(unittest.TestCase):
    """P1-3 (red-team): compare refuses to pool incompatible sweeps."""

    def _artifact(self, metrics):
        return RunArtifact(
            suite="trial-demo",
            dataset_version="0.1.0-demo",
            manifest_sha256="abc123",
            metrics=metrics,
        )

    def _sweep_metrics(self, grid, dimension="attacker_queries"):
        return {
            "ranking_eligible": False,
            "sweep": {"budget_grid": list(grid),
                      "strength_dimension": dimension,
                      "families": {}},
        }

    def test_sweep_vs_single_shot_not_comparable(self):
        sweep = self._artifact(self._sweep_metrics([1, 2]))
        single = self._artifact({"ranking_eligible": True})
        problems = check_comparable(sweep, single)
        self.assertTrue(
            any("sweep config differs" in p for p in problems), problems)
        # Symmetric.
        problems = check_comparable(single, sweep)
        self.assertTrue(
            any("sweep config differs" in p for p in problems), problems)

    def test_different_grids_not_comparable(self):
        a = self._artifact(self._sweep_metrics([1, 2]))
        b = self._artifact(self._sweep_metrics([1, 4]))
        problems = check_comparable(a, b)
        self.assertTrue(
            any("budget_grid differs" in p for p in problems), problems)

    def test_different_dimensions_not_comparable(self):
        a = self._artifact(self._sweep_metrics([1, 2], "attacker_queries"))
        b = self._artifact(self._sweep_metrics([1, 2], "paraphrase_rounds"))
        problems = check_comparable(a, b)
        self.assertTrue(
            any("strength_dimension differs" in p for p in problems),
            problems)

    def test_matching_sweeps_still_comparable(self):
        a = self._artifact(self._sweep_metrics([1, 2]))
        b = self._artifact(self._sweep_metrics([1, 2]))
        sweep_problems = [p for p in check_comparable(a, b)
                          if "sweep" in p]
        self.assertEqual(sweep_problems, [])

    def test_single_shot_pair_unaffected(self):
        a = self._artifact({"ranking_eligible": True})
        b = self._artifact({"ranking_eligible": False})
        sweep_problems = [p for p in check_comparable(a, b)
                          if "sweep" in p]
        self.assertEqual(sweep_problems, [])


class TestSweepEligibilityNotes(unittest.TestCase):
    """P2 (red-team): the sealed reason reaches runs_registry's key."""

    def test_summarize_seals_eligibility_notes(self):
        metrics = summarize_sweep_artifact([], [1, 2], "attacker_queries")
        self.assertFalse(metrics["ranking_eligible"])
        self.assertEqual(metrics["eligibility_notes"],
                         [metrics["ranking_ineligible_reason"]])
        self.assertIn("sweep run", metrics["eligibility_notes"][0])

    def test_qualifies_reports_sweep_reason(self):
        cases = _driver_cases()
        _, artifact = _run_driver(
            cases, [1, 2],
            [[True, False], [False, False], [False, False]],
            nonce="eb35-qualifies", manifest_sha256="deadbeef")
        self.assertTrue(artifact.verify())
        qualifies, reason = qualifies_for_leaderboard(artifact)
        self.assertFalse(qualifies)
        self.assertIn("sweep run", reason)
        self.assertNotIn("ranking eligibility not recorded", reason)


if __name__ == "__main__":
    unittest.main()
