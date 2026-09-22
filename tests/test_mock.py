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
    """Over the real starter suite: every flip lands on the case target."""

    def test_flips_land_on_targets(self):
        adapter = MockAdapter()
        cases = load_cases(REPO_ROOT / "dataset" / "trial")
        self.assertEqual(len(cases), 20)
        flips = targeted = 0
        for case in cases:
            r = run_case(adapter, case)
            # The mock always answers the benign variant correctly.
            self.assertTrue(r.benign_correct, case.case_id)
            target = case.attacked.target_decision
            self.assertIsNotNone(target, case.case_id)
            attacked_decision = (
                target if r.attacked_flipped
                else case.benign.expected_decision
            )
            # attacked_flipped means the decision changed; with a target
            # present the mock can only have flipped *to* the target.
            if r.attacked_flipped:
                flips += 1
                self.assertTrue(r.attacked_targeted, case.case_id)
                targeted += 1
        # The seeded flip subset is non-empty and every flip is targeted.
        self.assertGreater(flips, 0)
        self.assertEqual(targeted, flips)


if __name__ == "__main__":
    unittest.main()
