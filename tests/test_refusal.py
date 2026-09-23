"""Refusal/abstention semantics end to end (v2 contract).

A stub adapter that abstains on attacked variants exercises the full
path: the runner records the abstention (empty decision, refusal
reason), the flip rule does NOT count it as flipped, and the metrics
surface it as refusal_rate instead of ASR.
"""

import unittest

from peira.adapters.base import CallContext, ChoiceOutput, validate_output
from peira.runner import run_case, summarize
from peira.schema import Case


def _case(case_id="r1"):
    return Case.from_dict({
        "case_id": case_id,
        "family": "indirection",
        "primitive": "choice",
        "severity": "high",
        "benign": {"input": {"prompt": "b"}, "expected_decision": "approve"},
        "attacked": {"input": {"prompt": "b+"}, "target_decision": "deny"},
    })


class RefusingAdapter:
    """Abstains on every attacked variant, decides benign ones."""

    name = "refuser"
    version = "0.1.0"
    supported_primitives = frozenset({"choice"})

    def decide(self, case_input, primitive, context):
        if context.arm == "attacked":
            return ChoiceOutput(decision="", abstained=True,
                                refusal_reason="stop_reason: refusal",
                                confidence=None)
        return ChoiceOutput(decision="approve", confidence=0.9)


class TestRefusalEndToEnd(unittest.TestCase):
    def test_abstained_output_validates(self):
        ctx = CallContext(case_id="r", arm="attacked",
                          expected_decision="approve")
        out = RefusingAdapter().decide({"prompt": "p"}, "choice", ctx)
        self.assertEqual(validate_output(out, "choice"), [])

    def test_attacked_abstention_is_not_a_flip(self):
        r = run_case(RefusingAdapter(), _case())
        self.assertTrue(r.eligible)  # benign baseline is usable
        self.assertTrue(r.attacked.abstained)
        self.assertEqual(r.attacked.decision, "")
        self.assertEqual(r.attacked.refusal_reason, "stop_reason: refusal")
        self.assertFalse(r.flipped)

    def test_refusal_surfaces_in_summary_not_asr(self):
        rs = [run_case(RefusingAdapter(), _case(f"r{i}")) for i in range(4)]
        m = summarize(rs)
        self.assertEqual(m["asr_conditional"], 0.0)
        self.assertEqual(m["refusal_rate"], 1.0)
        self.assertEqual(m["n_eligible"], 4)
        self.assertEqual(m["per_family"]["indirection"]["refusal_rate"], 1.0)

    def test_benign_abstention_makes_case_ineligible(self):
        class BenignRefuser(RefusingAdapter):
            name = "benign-refuser"

            def decide(self, case_input, primitive, context):
                return ChoiceOutput(decision="", abstained=True,
                                    refusal_reason="nope", confidence=None)

        r = run_case(BenignRefuser(), _case())
        self.assertFalse(r.eligible)
        self.assertEqual(r.ineligibility_reason, "benign_abstained")
        m = summarize([r])
        self.assertEqual(m["benign_accuracy"], 0.0)  # no decided benign calls
        self.assertEqual(
            m["ineligible_by_reason"]["benign_abstained"], 1)


if __name__ == "__main__":
    unittest.main()
