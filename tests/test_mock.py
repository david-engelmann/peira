"""Tests for the mock adapter's generalized flip behavior (H1).

The mock flips toward each case's own target decision on its seeded flip
subset (falling back to the approve/deny toggle for target-less inputs),
so targeted-success is meaningful for arbitrary decision labels.
"""

import unittest

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


class _RecordingAdapter:
    """Captures the input dicts the runner hands to decide()."""
    name = "recorder"
    version = "0.1.0"
    supported_primitives = frozenset({"choice"})

    def __init__(self):
        self.seen = []

    def decide(self, case_input, primitive):
        self.seen.append(dict(case_input))
        from peira.adapters.base import ChoiceOutput
        return ChoiceOutput(decision=case_input["expected_decision"],
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
        inp = {"case_id": "x", "expected_decision": "A",
               "target_decision": "B", "attacked": True}
        self.assertEqual(a.decide(inp, "choice").decision,
                         b.decide(inp, "choice").decision)

    def test_confidence_deterministic_across_primitives(self):
        # The mock reports a seeded confidence on every primitive: high
        # when deciding as expected, lower on flips — never None.
        a, b = MockAdapter(), MockAdapter()
        for primitive in ("choice", "score", "noul"):
            inp = {"case_id": "c-conf", "expected_decision": "approve",
                   "attacked": False}
            out_a, out_b = a.decide(inp, primitive), b.decide(inp, primitive)
            self.assertIsNotNone(out_a.confidence, primitive)
            self.assertEqual(out_a.confidence, out_b.confidence, primitive)
            self.assertGreaterEqual(out_a.confidence, 0.0)
            self.assertLessEqual(out_a.confidence, 1.0)

    def test_mock_never_abstains_and_reports_no_usage(self):
        m = MockAdapter()
        for primitive in ("choice", "score", "noul"):
            out = m.decide({"case_id": "c", "expected_decision": "approve",
                            "attacked": True},
                           primitive)
            self.assertFalse(out.abstained, primitive)
            self.assertIsNone(out.usage, primitive)


class TestRunnerInjection(unittest.TestCase):
    def test_attacked_input_carries_target(self):
        rec = _RecordingAdapter()
        run_case(rec, _case(expected="A", target="B"))
        benign_in, attacked_in = rec.seen
        self.assertEqual(attacked_in["target_decision"], "B")
        self.assertTrue(attacked_in["attacked"])
        self.assertNotIn("target_decision", benign_in)
        self.assertNotIn("attacked", benign_in)


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
