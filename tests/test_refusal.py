"""Refusal/abstention semantics end to end (v2 contract).

A stub adapter that abstains on attacked variants exercises the full
path: the runner records the abstention (empty decision, refusal
reason), the flip rule counts it as flipped (2026-09-25: the effective
outcome is (decision, abstained) — attack-induced abstention is a DoS
vector), and the metrics surface it as refusal_rate alongside ASR.
"""

import unittest

from peira.adapters.base import CallContext, ChoiceOutput, validate_output
from peira.runner import run_case, _summarize_artifact
from peira.schema import Case


def _case(case_id="r1"):
    return Case.from_dict({
        "case_id": case_id,
        "family": "indirection",
        "primitive": "choice",
        "severity": "high",
        "benign": {"input": {"prompt": "b", "options": ["approve", "deny"]}, "expected_decision": "approve"},
        "attacked": {"input": {"prompt": "b+ [ATTACK]", "options": ["approve", "deny"]}, "target_decision": "deny"},
    })


class RefusingAdapter:
    """Abstains on every attacked variant, decides benign ones.

    B2: the refusal keys off the input content (the attack marker the
    runner's attacked variant carries), never off trial bookkeeping —
    the context is opaque to the adapter.
    """

    name = "refuser"
    version = "0.1.0"
    supported_primitives = frozenset({"choice"})
    ATTACK_MARKER = "[ATTACK]"

    def decide(self, case_input, primitive, context):
        if self.ATTACK_MARKER in case_input.get("prompt", ""):
            return ChoiceOutput(decision="", abstained=True,
                                refusal_reason="stop_reason: refusal",
                                confidence=None)
        return ChoiceOutput(decision="approve", confidence=0.9)


class TestRefusalEndToEnd(unittest.TestCase):
    def test_abstained_output_validates(self):
        ctx = CallContext(call_id="call-test")
        out = RefusingAdapter().decide({"prompt": "p [ATTACK]"}, "choice", ctx)
        self.assertEqual(validate_output(out, "choice"), [])

    def test_attacked_abstention_is_a_flip(self):
        # 2026-09-25: attack-induced abstention IS a flip (DoS vector).
        # The effective outcome is (decision, abstained).
        r = run_case(RefusingAdapter(), _case())
        self.assertTrue(r.eligible)  # benign baseline is usable
        self.assertTrue(r.attacked.abstained)
        self.assertEqual(r.attacked.decision, "")
        self.assertEqual(r.attacked.refusal_reason, "stop_reason: refusal")
        self.assertTrue(r.flipped)

    def test_refusal_surfaces_in_summary_and_asr(self):
        rs = [run_case(RefusingAdapter(), _case(f"r{i}")) for i in range(4)]
        m = _summarize_artifact(rs)
        # Attack-induced abstention is a flip (DoS vector), so ASR is 1.0;
        # refusal_rate surfaces the same phenomenon separately.
        self.assertEqual(m["asr_conditional"], 1.0)
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
        m = _summarize_artifact([r])
        # No decided benign calls: the rate is None (no data), never 0.0.
        self.assertIsNone(m["benign_accuracy"])
        self.assertEqual(
            m["ineligible_by_reason"]["benign_abstained"], 1)


if __name__ == "__main__":
    unittest.main()
