"""Adapter output contract: validate_output rejects malformed outputs.

A non-string decision or a non-numeric confidence must come back as an
error string — never as a bare TypeError, and never silently accepted
into mis-scoring. Confidence may be None (the adapter cannot always
report one); abstention requires an empty decision.
"""

import unittest

from peira.adapters.base import (
    CallUsage,
    ChoiceOutput,
    NoulOutput,
    ScoreOutput,
    validate_output,
)


class TestValidateOutput(unittest.TestCase):
    def test_valid_outputs_pass(self):
        self.assertEqual(
            validate_output(ChoiceOutput(decision="approve", confidence=0.9),
                            "choice"), [])
        self.assertEqual(
            validate_output(ScoreOutput(score=0.2, decision="deny"),
                            "score"), [])
        # Abstained outputs carry no decision: "" is the only legal one.
        self.assertEqual(
            validate_output(NoulOutput(decision="", abstained=True,
                                       refusal_reason="provider block"),
                            "noul"), [])
        # Confidence is optional everywhere.
        self.assertEqual(
            validate_output(ChoiceOutput(decision="approve"), "choice"), [])
        self.assertEqual(
            validate_output(ScoreOutput(score=0.2, decision="deny"),
                            "score"), [])

    def test_non_string_decision_rejected_per_primitive(self):
        # 123 == "approve" is False in Python: without this check a
        # non-string decision silently mis-scores instead of flagging
        # the adapter output as malformed.
        for output, primitive in [
            (ChoiceOutput(decision=123, confidence=0.5), "choice"),
            (ScoreOutput(score=0.5, decision=None), "score"),
            (NoulOutput(decision=["approve"], abstained=False), "noul"),
        ]:
            with self.subTest(primitive=primitive):
                errors = validate_output(output, primitive)
                self.assertEqual(len(errors), 1)
                self.assertIn("decision must be a string", errors[0])

    def test_non_numeric_confidence_returns_error_not_typeerror(self):
        # The chained comparison `0.0 <= "x" <= 1.0` used to raise a bare
        # TypeError, breaking the documented list[str] contract.
        for bad in ["high", [0.5], {"c": 0.5}]:
            with self.subTest(bad=bad):
                errors = validate_output(
                    ChoiceOutput(decision="approve", confidence=bad), "choice")
                self.assertEqual(len(errors), 1)
                self.assertIn("must be a number in 0..1", errors[0])
        # None is the one legitimate non-number: the adapter may not be
        # able to report a confidence.
        self.assertEqual(
            validate_output(ChoiceOutput(decision="approve", confidence=None),
                            "choice"), [])
        # Same guard on the score primitive.
        errors = validate_output(
            ScoreOutput(score="0.5", decision="approve"), "score")
        self.assertEqual(len(errors), 1)
        self.assertIn("must be a number in 0..1", errors[0])

    def test_bool_confidence_and_score_rejected(self):
        # bool subclasses int; a boolean is never a legitimate
        # confidence or score.
        errors = validate_output(
            ChoiceOutput(decision="approve", confidence=True), "choice")
        self.assertEqual(len(errors), 1)
        self.assertIn("must be a number in 0..1", errors[0])
        errors = validate_output(
            ScoreOutput(score=False, decision="deny"), "score")
        self.assertEqual(len(errors), 1)
        self.assertIn("must be a number in 0..1", errors[0])

    def test_out_of_range_still_reported(self):
        errors = validate_output(
            ChoiceOutput(decision="approve", confidence=1.4), "choice")
        self.assertEqual(errors, ["confidence 1.4 outside 0..1"])
        errors = validate_output(
            ScoreOutput(score=-0.1, decision="deny"), "score")
        self.assertEqual(errors, ["score -0.1 outside 0..1"])

    def test_nan_confidence_rejected(self):
        errors = validate_output(
            ChoiceOutput(decision="approve", confidence=float("nan")),
            "choice")
        self.assertEqual(len(errors), 1)
        self.assertIn("outside 0..1", errors[0])

    def test_wrong_output_type(self):
        errors = validate_output(
            ScoreOutput(score=0.5, decision="approve"), "choice")
        self.assertEqual(
            errors, ["choice primitive needs ChoiceOutput, got ScoreOutput"])

    def test_unknown_primitive(self):
        self.assertEqual(validate_output(
            ChoiceOutput(decision="a", confidence=0.5), "bogus"),
            ["unknown primitive: 'bogus'"])

    def test_decision_and_confidence_both_bad(self):
        errors = validate_output(
            ChoiceOutput(decision=123, confidence="high"), "choice")
        self.assertEqual(len(errors), 2)

    def test_abstention_semantics(self):
        # Abstained with a non-empty decision is malformed: the "" is
        # what keeps refusals out of the decision comparisons.
        errors = validate_output(
            ChoiceOutput(decision="approve", abstained=True), "choice")
        self.assertEqual(
            errors, ['abstained output must have an empty decision ("")'])
        # An empty decision without the abstained flag is malformed: the
        # runner needs the flag to know the call produced nothing usable.
        errors = validate_output(ChoiceOutput(decision=""), "choice")
        self.assertEqual(
            errors, ["non-abstained output must have a non-empty decision"])
        # A deliberate noul abstain-label is NOT abstention.
        self.assertEqual(
            validate_output(NoulOutput(decision="abstain", abstained=False),
                            "noul"), [])

    def test_usage_validation(self):
        good = CallUsage(model="gpt-5.6-sol", tokens_in=10, tokens_out=5,
                         latency_ms=120.5, cost_usd=0.0)
        self.assertEqual(
            validate_output(
                ChoiceOutput(decision="approve", confidence=0.9, usage=good),
                "choice"), [])
        bad = CallUsage(model="x", tokens_in=-1, tokens_out=0,
                        latency_ms=1.0, cost_usd=0.0)
        errors = validate_output(
            ChoiceOutput(decision="approve", usage=bad), "choice")
        self.assertTrue(any("tokens_in" in e for e in errors))
        errors = validate_output(
            ChoiceOutput(decision="approve", usage="nope"), "choice")
        self.assertEqual(len(errors), 1)
        self.assertIn("usage must be CallUsage or None", errors[0])


if __name__ == "__main__":
    unittest.main()
