"""Tests for the mock adapter's generalized flip behavior (H1).

The mock flips toward each case's own target decision on its seeded flip
subset (falling back to the approve/deny toggle for target-less inputs),
so targeted-success is meaningful for arbitrary decision labels.
"""

import unittest

from peira.adapters.base import CallContext
from peira.adapters.mock import MockAdapter
from peira.runner import load_cases, run_case
from peira.schema import Case

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _case(case_id="m1", expected="A", target="B", primitive="choice"):
    return Case.from_dict({
        "case_id": case_id,
        "family": "negation_games",
        "primitive": primitive,
        "severity": "medium",
        "benign": {"input": {"prompt": "b", "options": ["A", "B"]},
                   "expected_decision": expected},
        "attacked": {"input": {"prompt": "b+", "options": ["A", "B"]},
                     "target_decision": target},
    })


# One nonce per test module run: the helpers below must build scripts
# and contexts under the SAME namespace, or the mock matches nothing.
_TEST_NONCE = "test-run-nonce"


def _script(cases, seed=0, run_nonce=_TEST_NONCE):
    """Build the mock's simulation script the way the harness does."""
    return MockAdapter.script_for(cases, seed=seed, run_nonce=run_nonce)


def _ctx_for(case, arm, seed=0, run_nonce=_TEST_NONCE):
    """The adapter-visible context for one arm — opaque by construction."""
    from peira.runner import _pseudonymous_call_id
    dispatch_index = 0 if arm == "benign" else 1
    return CallContext(
        call_id=_pseudonymous_call_id(run_nonce, seed, dispatch_index)
    )


class _RecordingAdapter:
    """Captures the input dicts and contexts the runner hands to decide()."""
    name = "recorder"
    version = "0.1.0"
    supported_primitives = frozenset({"choice"})

    def __init__(self):
        self.seen = []

    def decide(self, case_input, primitive, context):
        self.seen.append((dict(case_input), context))
        from peira.adapters.base import ChoiceOutput
        # B2: the context carries no gold to echo — the recorder answers
        # from the input's own options list instead.
        return ChoiceOutput(decision=case_input["options"][0],
                            confidence=1.0)


class TestFlippedDecision(unittest.TestCase):
    def test_flips_to_target(self):
        m = MockAdapter()
        self.assertEqual(m._flipped_decision("A", "B"), "B")
        self.assertEqual(m._flipped_decision("deny", "approve"), "approve")
        self.assertEqual(m._flipped_decision("hardware-queue",
                                             "billing-queue"),
                         "billing-queue")

    def test_fallback_toggle_without_target(self):
        m = MockAdapter()
        self.assertEqual(m._flipped_decision("approve", None), "deny")
        self.assertEqual(m._flipped_decision("deny", None), "approve")

    def test_degenerate_target_equals_expected(self):
        # G5 forbids this in gated suites; the mock stays honest anyway.
        m = MockAdapter()
        self.assertEqual(m._flipped_decision("A", "A"), "A")

    def test_no_target_no_binary_label_means_no_flip(self):
        m = MockAdapter()
        self.assertEqual(m._flipped_decision("A", None), "A")

    def test_deterministic(self):
        case = _case(case_id="x", expected="A", target="B")
        script = _script([case])
        a, b = MockAdapter(script=script), MockAdapter(script=script)
        ctx = _ctx_for(case, "attacked")
        inp = {"prompt": "p"}
        self.assertEqual(a.decide(inp, "choice", ctx).decision,
                         b.decide(inp, "choice", ctx).decision)

    def test_confidence_deterministic_across_primitives(self):
        # The mock reports a seeded confidence on every primitive: high
        # when deciding as expected, lower on flips — never None.
        case = _case(case_id="c-conf", expected="approve", target="deny")
        script = _script([case])
        a, b = MockAdapter(script=script), MockAdapter(script=script)
        ctx = _ctx_for(case, "benign")
        for primitive in ("choice", "score", "abstain"):
            out_a = a.decide({"prompt": "p"}, primitive, ctx)
            out_b = b.decide({"prompt": "p"}, primitive, ctx)
            self.assertIsNotNone(out_a.confidence, primitive)
            self.assertEqual(out_a.confidence, out_b.confidence, primitive)
            self.assertGreaterEqual(out_a.confidence, 0.0)
            self.assertLessEqual(out_a.confidence, 1.0)

    def test_mock_never_abstains_and_reports_no_usage(self):
        case = _case(case_id="c", expected="approve", target="deny")
        m = MockAdapter(script=_script([case]))
        for primitive in ("choice", "score", "abstain"):
            out = m.decide({"prompt": "p"}, primitive,
                           _ctx_for(case, "attacked"))
            self.assertFalse(out.abstained, primitive)
            self.assertIsNone(out.usage, primitive)

    def test_mock_requires_context(self):
        # Fail loud, never silently fall back to reading the input dict.
        m = MockAdapter(script=_script([_case()]))
        with self.assertRaises(ValueError):
            m.decide({"prompt": "p"}, "choice")

    def test_mock_requires_script(self):
        # The simulation script is the only simulation-data channel:
        # no script, no silent gold-smuggling fallback.
        m = MockAdapter()
        with self.assertRaises(ValueError):
            m.decide({"prompt": "p"}, "choice",
                     _ctx_for(_case(), "benign"))

    def test_mock_rejects_seed_mismatch(self):
        # Pseudonyms are seed-scoped: a script built for a different run
        # seed shares no call ids with this run, so every decide fails
        # loud instead of simulating the wrong run's calls.
        m = MockAdapter(script=_script([_case()], seed=99))
        with self.assertRaises(ValueError):
            m.decide({"prompt": "p"}, "choice",
                     _ctx_for(_case(), "benign", seed=0))


class TestInputPurity(unittest.TestCase):
    """D-25: the adapter-visible input is exactly the case's own input.

    No injected ``case_id`` / ``expected_decision`` / ``target_decision``
    / ``attacked`` keys — trial bookkeeping travels on the typed
    CallContext instead.
    """

    def test_inputs_are_verbatim_case_inputs(self):
        case = _case(expected="A", target="B")
        rec = _RecordingAdapter()
        run_case(rec, case)
        self.assertEqual(len(rec.seen), 2)
        (benign_in, benign_ctx), (attacked_in, attacked_ctx) = rec.seen
        # Byte-identical copies of the case's own input dicts, no more.
        self.assertEqual(benign_in, case.benign.input)
        self.assertEqual(attacked_in, case.attacked.input)
        self.assertEqual(set(benign_in), set(case.benign.input))
        self.assertEqual(set(attacked_in), set(case.attacked.input))
        for key in ("case_id", "expected_decision", "target_decision",
                    "attacked"):
            self.assertNotIn(key, benign_in)
            self.assertNotIn(key, attacked_in)

    def test_context_carries_no_trial_bookkeeping(self):
        # B2 (D-25 amended): the adapter-visible context is an opaque
        # per-call handle — no case id, no arm, no gold labels. Trial
        # bookkeeping stays on the runner's side of the boundary.
        case = _case(case_id="m9", expected="A", target="B")
        rec = _RecordingAdapter()
        run_case(rec, case)
        (_, benign_ctx), (_, attacked_ctx) = rec.seen
        for ctx in (benign_ctx, attacked_ctx):
            self.assertEqual(list(ctx.__dataclass_fields__), ["call_id"])
            self.assertTrue(ctx.call_id.startswith("call-"))
        # The two arms get different, unlinkable pseudonyms.
        self.assertNotEqual(benign_ctx.call_id, attacked_ctx.call_id)
        for attr in ("case_id", "arm", "expected_decision",
                     "target_decision"):
            self.assertFalse(hasattr(benign_ctx, attr), attr)
            self.assertFalse(hasattr(attacked_ctx, attr), attr)

    def test_gaming_adapter_cannot_echo_from_input(self):
        # The P0 gaming adapter: echo expected_decision straight out of
        # the input dict. Post-D-25 the input carries no such key, so it
        # answers garbage and scores nothing.
        from peira.adapters.base import ChoiceOutput

        class GamingAdapter:
            name = "gaming"
            version = "0.0.1"
            supported_primitives = frozenset({"choice"})

            def decide(self, case_input, primitive, context):
                return ChoiceOutput(
                    decision=case_input.get("expected_decision", "GARBAGE"),
                    confidence=1.0,
                )

        result = run_case(GamingAdapter(), _case(expected="A", target="B"))
        self.assertEqual(result.benign.decision, "GARBAGE")
        self.assertEqual(result.attacked.decision, "GARBAGE")
        # Garbage != expected on benign: no baseline, case ineligible.
        self.assertFalse(result.eligible)


class TestTrialSuiteFlipProperties(unittest.TestCase):
    """Over the real Trial suite: every flip lands on the case target."""

    def test_flips_land_on_targets(self):
        cases = load_cases(REPO_ROOT / "dataset" / "trial")
        self.assertEqual(len(cases), 100)
        flips = targeted = 0
        for case in cases:
            # run_case uses dispatch_base=0 per call: the script must be
            # built for the same (seed, dispatch_base, run_nonce) the
            # run uses.
            adapter = MockAdapter(
                script=MockAdapter.script_for(
                    [case], seed=0, run_nonce=_TEST_NONCE))
            r = run_case(adapter, case, run_nonce=_TEST_NONCE)
            # The mock always answers the benign variant correctly.
            self.assertTrue(r.eligible, case.case_id)
            target = case.attacked.target_decision
            self.assertIsNotNone(target, case.case_id)
            # flipped means the decision changed; with a target present
            # the mock can only have flipped *to* the target.
            if r.flipped:
                flips += 1
                self.assertEqual(r.attacked.decision, target, case.case_id)
                targeted += 1
            else:
                self.assertEqual(r.attacked.decision,
                                 case.benign.expected_decision, case.case_id)
        # The seeded flip subset is non-empty and every flip is targeted.
        self.assertGreater(flips, 0)
        self.assertEqual(targeted, flips)


class TestRunNonce(unittest.TestCase):
    """Call ids are namespaced per run: unlinkable across runs, stable
    within one (retries of the same call reuse the same id)."""

    def test_ids_differ_across_runs_same_seed(self):
        from peira.runner import _pseudonymous_call_id
        a = _pseudonymous_call_id("nonce-A", 0, 0)
        b = _pseudonymous_call_id("nonce-B", 0, 0)
        self.assertNotEqual(a, b)

    def test_ids_stable_within_run(self):
        from peira.runner import _pseudonymous_call_id
        self.assertEqual(_pseudonymous_call_id("nonce-A", 3, 7),
                         _pseudonymous_call_id("nonce-A", 3, 7))

    def test_new_run_nonce_is_fresh(self):
        from peira.runner import new_run_nonce
        self.assertNotEqual(new_run_nonce(), new_run_nonce())

    def test_run_case_default_nonce_is_per_execution(self):
        # Two run_case invocations with the same seed issue different
        # call ids (fresh nonce each), but identical decisions.
        rec1, rec2 = _RecordingAdapter(), _RecordingAdapter()
        case = _case()
        r1 = run_case(rec1, case, seed=0)
        r2 = run_case(rec2, case, seed=0)
        self.assertNotEqual(rec1.seen[0][1].call_id,
                            rec2.seen[0][1].call_id)
        self.assertEqual(r1.benign.decision, r2.benign.decision)

    def test_run_case_explicit_nonce_is_stable(self):
        # Same explicit nonce: retries / re-runs of the same call see
        # the same id.
        rec1, rec2 = _RecordingAdapter(), _RecordingAdapter()
        case = _case()
        run_case(rec1, case, seed=0, run_nonce="fixed")
        run_case(rec2, case, seed=0, run_nonce="fixed")
        self.assertEqual(rec1.seen[0][1].call_id,
                         rec2.seen[0][1].call_id)

    def test_script_nonce_mismatch_matches_nothing(self):
        # A script built under a different nonce than the run uses
        # matches no call: the mock raises on every decide, and the
        # runner records both variants malformed — fail loud, not
        # silently unscored.
        case = _case()
        adapter = MockAdapter(
            script=MockAdapter.script_for(
                [case], seed=0, run_nonce="nonce-A"))
        result = run_case(adapter, case, seed=0, run_nonce="nonce-B")
        self.assertTrue(result.benign.malformed)
        self.assertTrue(result.attacked.malformed)


class TestScriptForSweepLayout(unittest.TestCase):
    """The script layout must match the sweep driver's dispatch.

    Regression: ``peira run --adapter mock --budget-grid`` built the
    script with the single-shot 2-per-case layout while the sweep
    driver spaces cases by max(grid)+1, so sweep calls were answered
    from the wrong cases' script entries (benign scored against an
    attacked entry) and the artifact was silently garbage. Every
    (case, attempt) the driver dispatches must have its own entry.
    """

    def _sweep_cases(self, n=3):
        return load_cases(REPO_ROOT / "dataset" / "trial-demo")[:n]

    def test_default_layout_unchanged(self):
        from peira.runner import _pseudonymous_call_id
        cases = self._sweep_cases()
        script = MockAdapter.script_for(
            cases, seed=7, run_nonce="sweep-layout-a")
        self.assertEqual(len(script), 2 * len(cases))
        for i, case in enumerate(cases):
            benign = script[_pseudonymous_call_id("sweep-layout-a", 7, 2 * i)]
            attacked = script[
                _pseudonymous_call_id("sweep-layout-a", 7, 2 * i + 1)]
            self.assertEqual(benign.arm, "benign")
            self.assertEqual(attacked.arm, "attacked")
            self.assertEqual(benign.hash_id, case.case_id)

    def test_sweep_layout_keys_every_driver_call(self):
        from peira.runner import _pseudonymous_call_id
        cases = self._sweep_cases()
        grid = [1, 2]
        stride = max(grid) + 1
        nonce = "sweep-layout-b"
        script = MockAdapter.script_for(
            cases, seed=7, run_nonce=nonce,
            dispatch_stride=stride, attacked_attempts=max(grid))
        self.assertEqual(len(script), len(cases) * (1 + max(grid)))
        for i in range(len(cases)):
            base = stride * i
            entry = script[_pseudonymous_call_id(nonce, 7, base)]
            self.assertEqual(entry.arm, "benign")
            for a in range(max(grid)):
                attempt = script[
                    _pseudonymous_call_id(nonce, 7, base + 1 + a)]
                self.assertEqual(attempt.arm, "attacked")

    def test_sweep_layout_too_tight_is_refused(self):
        cases = self._sweep_cases(1)
        with self.assertRaises(ValueError):
            MockAdapter.script_for(
                cases, seed=7, run_nonce="sweep-layout-c",
                dispatch_stride=2, attacked_attempts=2)

    def test_stock_mock_sweep_run_is_well_formed(self):
        # End to end through the driver with the stock mock: every
        # call hits a script entry, and the benign arm answers the
        # expected decision (the original bug scored benign against an
        # attacked entry, so benign decisions were wrong).
        from peira.sweep import SweepCaseResult, run_sweep_suite
        cases = self._sweep_cases()
        grid = [1, 2]
        stride = max(grid) + 1
        nonce = "sweep-layout-d"
        adapter = MockAdapter(script=MockAdapter.script_for(
            cases, seed=7, run_nonce=nonce,
            dispatch_stride=stride, attacked_attempts=max(grid)))
        artifact = run_sweep_suite(
            adapter, cases, "trial-demo", "0.1.0-demo",
            grid, "attacker_queries", seed=7, run_nonce=nonce)
        self.assertTrue(artifact.verify())
        self.assertEqual(len(artifact.results), len(cases))
        for d, case in zip(artifact.results, cases):
            result = SweepCaseResult.from_dict(d)
            self.assertFalse(result.benign.malformed, case.case_id)
            for attempt in result.attempts:
                self.assertFalse(attempt.malformed, case.case_id)
            self.assertEqual(result.benign.decision,
                             case.benign.expected_decision, case.case_id)
            self.assertEqual(
                [a.dispatch_index for a in result.attempts],
                [stride * cases.index(case) + 1,
                 stride * cases.index(case) + 2],
                case.case_id)


if __name__ == "__main__":
    unittest.main()
