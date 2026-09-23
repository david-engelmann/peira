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
        "benign": {"input": {"prompt": "b"}, "expected_decision": expected},
        "attacked": {"input": {"prompt": "b+"}, "target_decision": target},
    })


def _ctx(case, arm):
    return CallContext(
        case_id=case.case_id,
        arm=arm,
        expected_decision=case.benign.expected_decision,
        target_decision=case.attacked.target_decision
        if arm == "attacked" else None,
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
        return ChoiceOutput(decision=context.expected_decision,
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
        a, b = MockAdapter(), MockAdapter()
        case = _case(case_id="x", expected="A", target="B")
        ctx = _ctx(case, "attacked")
        inp = {"prompt": "p"}
        self.assertEqual(a.decide(inp, "choice", ctx).decision,
                         b.decide(inp, "choice", ctx).decision)

    def test_confidence_deterministic_across_primitives(self):
        # The mock reports a seeded confidence on every primitive: high
        # when deciding as expected, lower on flips — never None.
        a, b = MockAdapter(), MockAdapter()
        case = _case(case_id="c-conf", expected="approve", target="deny")
        ctx = _ctx(case, "benign")
        for primitive in ("choice", "score", "noul"):
            out_a = a.decide({"prompt": "p"}, primitive, ctx)
            out_b = b.decide({"prompt": "p"}, primitive, ctx)
            self.assertIsNotNone(out_a.confidence, primitive)
            self.assertEqual(out_a.confidence, out_b.confidence, primitive)
            self.assertGreaterEqual(out_a.confidence, 0.0)
            self.assertLessEqual(out_a.confidence, 1.0)

    def test_mock_never_abstains_and_reports_no_usage(self):
        m = MockAdapter()
        case = _case(case_id="c", expected="approve", target="deny")
        for primitive in ("choice", "score", "noul"):
            out = m.decide({"prompt": "p"}, primitive, _ctx(case, "attacked"))
            self.assertFalse(out.abstained, primitive)
            self.assertIsNone(out.usage, primitive)

    def test_mock_requires_context(self):
        # Fail loud, never silently fall back to reading the input dict.
        m = MockAdapter()
        with self.assertRaises(ValueError):
            m.decide({"prompt": "p"}, "choice")


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

    def test_context_carries_trial_bookkeeping(self):
        case = _case(case_id="m9", expected="A", target="B")
        rec = _RecordingAdapter()
        run_case(rec, case)
        (_, benign_ctx), (_, attacked_ctx) = rec.seen
        self.assertEqual(benign_ctx.case_id, "m9")
        self.assertEqual(benign_ctx.arm, "benign")
        self.assertEqual(benign_ctx.expected_decision, "A")
        self.assertIsNone(benign_ctx.target_decision)
        self.assertEqual(attacked_ctx.case_id, "m9")
        self.assertEqual(attacked_ctx.arm, "attacked")
        self.assertEqual(attacked_ctx.expected_decision, "A")
        self.assertEqual(attacked_ctx.target_decision, "B")

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
        adapter = MockAdapter()
        cases = load_cases(REPO_ROOT / "dataset" / "trial")
        self.assertEqual(len(cases), 100)
        flips = targeted = 0
        for case in cases:
            r = run_case(adapter, case)
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


if __name__ == "__main__":
    unittest.main()
