"""R-01 conversational suite metrics.

Exercises summarize_conversation on tiny offline fixtures: empty
input, mock runs with flip_rate 0.0 and 1.0, target-hit behavior with
and without a case map, intermediate-turn quality stats, cost
summation, per-family breakdowns, and the TypeError guard. All
offline and xdist-safe (no shared mutable state).
"""

import json
import unittest
from pathlib import Path

from peira.adapters.base import CallContext, CallUsage, ChoiceOutput
from peira.adapters.mock import MockAdapter
from peira.conversation import (
    CONVERSATION_DISPATCH_STRIDE,
    ConversationResult,
    ConversationalCase,
    load_conversation_cases,
    run_conversation_case,
)
from peira.conversation_metrics import summarize_conversation
from peira.metrics import CallRecord, PerCaseResult
from peira.pricing import cost_usd, load_pricing_table
from peira.runner import new_run_nonce

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "conversational"


def _load_fixture_cases():
    return load_conversation_cases(FIXTURES)


def _run_mock(cases, flip_rate=0.0, seed=0):
    """Run every case through MockAdapter (strictly sequential).

    The sync ``run_conversation_case`` takes a per-case
    ``dispatch_base``: case i's base is
    ``dispatch_base + CONVERSATION_DISPATCH_STRIDE * i``, matching the
    script built by ``script_for_conversation``.
    """
    nonce = new_run_nonce()
    adapter = MockAdapter(
        seed="test",
        flip_rate=flip_rate,
        script=MockAdapter.script_for_conversation(
            cases, seed=seed, run_nonce=nonce
        ),
    )
    return [
        run_conversation_case(
            adapter,
            case,
            seed=seed,
            run_nonce=nonce,
            dispatch_base=CONVERSATION_DISPATCH_STRIDE * i,
        )
        for i, case in enumerate(cases)
    ]


class _FixedDecisionAdapter:
    """Adapter returning a fixed decision on every turn.

    ``usage`` is attached to every ChoiceOutput when provided (the
    runner recomputes cost_usd from the pinned pricing table, so any
    adapter-set cost_usd is ignored).
    """

    def __init__(self, decision="approve", usage=None):
        self.name = "fixed"
        self.decision = decision
        self.usage = usage

    def decide_turn(self, turn_input, primitive, context=None):
        return ChoiceOutput(
            decision=self.decision,
            confidence=0.9,
            usage=self.usage,
        )


class _ExplodingIntermediateAdapter:
    """Adapter that fails on every non-final turn."""

    def __init__(self):
        self.name = "exploding-intermediate"

    def decide_turn(self, turn_input, primitive, context=None):
        if not turn_input["is_final_turn"]:
            raise RuntimeError("simulated intermediate failure")
        return ChoiceOutput(decision="deny", confidence=0.9)


class TestSummarizeEmpty(unittest.TestCase):
    def test_empty_results(self):
        summary = summarize_conversation([])
        self.assertEqual(summary["n_cases"], 0)
        self.assertEqual(summary["n_eligible"], 0)
        self.assertIsNone(summary["flip_rate"])
        self.assertIsNone(summary["target_hit_rate"])
        self.assertIsNone(summary["mean_user_turns_benign"])
        self.assertIsNone(summary["mean_user_turns_attacked"])
        self.assertIsNone(summary["intermediate_malformed_rate"])
        self.assertIsNone(summary["intermediate_abstention_rate"])
        self.assertIsNone(summary["final_turn_eligibility_rate"])
        self.assertEqual(summary["total_cost_usd"], 0.0)
        self.assertEqual(summary["per_family"], {})
        # JSON-serializable with no floats present.
        json.dumps(summary)


class TestSummarizeMockRuns(unittest.TestCase):
    def test_flip_rate_zero(self):
        cases = _load_fixture_cases()
        results = _run_mock(cases, flip_rate=0.0)
        summary = summarize_conversation(results, cases=cases)
        self.assertEqual(summary["n_cases"], 2)
        self.assertEqual(summary["n_eligible"], 2)
        self.assertEqual(summary["flip_rate"]["value"], 0.0)
        # Mean turns: both fixtures have 2 user turns per arm.
        self.assertEqual(summary["mean_user_turns_benign"], 2.0)
        self.assertEqual(summary["mean_user_turns_attacked"], 2.0)
        # Intermediate turns answered cleanly: no malformed, no
        # abstentions.
        self.assertEqual(summary["intermediate_malformed_rate"], 0.0)
        self.assertEqual(summary["intermediate_abstention_rate"], 0.0)
        self.assertEqual(summary["final_turn_eligibility_rate"], 1.0)
        json.dumps(summary)

    def test_flip_rate_one_and_target_hit(self):
        cases = _load_fixture_cases()
        results = _run_mock(cases, flip_rate=1.0)
        summary = summarize_conversation(results, cases=cases)
        self.assertEqual(summary["flip_rate"]["value"], 1.0)
        # Fixture 001 is the fixture with a real target ("approve"
        # against a "deny" baseline): the mock flips the attacked
        # final turn toward the target.
        sub = summarize_conversation(results[:1], cases=cases[:1])
        self.assertEqual(sub["target_hit_rate"], 1.0)
        # Fixture 002's target equals its benign expected decision, so
        # the mock's approve/deny toggle flips away from it: across
        # both fixtures the hit rate is 0.5.
        self.assertEqual(summary["target_hit_rate"], 0.5)
        json.dumps(summary)

    def test_target_hit_rate_none_without_cases(self):
        cases = _load_fixture_cases()
        results = _run_mock(cases, flip_rate=1.0)
        summary = summarize_conversation(results)
        self.assertEqual(summary["flip_rate"]["value"], 1.0)
        self.assertIsNone(summary["target_hit_rate"])

    def test_per_family_breakdown(self):
        cases = _load_fixture_cases()
        results = _run_mock(cases, flip_rate=1.0)
        summary = summarize_conversation(results, cases=cases)
        families = summary["per_family"]
        self.assertEqual(
            set(families),
            {"multi_turn_escalation", "decision_splitting"},
        )
        for family in families.values():
            self.assertEqual(family["n_cases"], 1)
            self.assertEqual(family["n_eligible"], 1)
            self.assertEqual(family["flip_rate"]["value"], 1.0)

    def test_per_family_flip_rate_none_without_eligible(self):
        cases = _load_fixture_cases()
        # Final decisions oppose the benign baseline on fixture 001,
        # so nothing is eligible there.
        adapter = _FixedDecisionAdapter(decision="oppose")
        nonce = new_run_nonce()
        results = [
            run_conversation_case(adapter, case, seed=0, run_nonce=nonce)
            for case in cases
        ]
        summary = summarize_conversation(results, cases=cases)
        mte = summary["per_family"]["multi_turn_escalation"]
        self.assertEqual(mte["n_cases"], 1)
        self.assertEqual(mte["n_eligible"], 0)
        self.assertIsNone(mte["flip_rate"])
        # Top-level triple is None when no case is eligible.
        self.assertIsNone(summary["flip_rate"])
        json.dumps(summary)


class TestSummarizeIntermediateTurns(unittest.TestCase):
    def test_intermediate_malformed_rate(self):
        cases = _load_fixture_cases()
        adapter = _ExplodingIntermediateAdapter()
        nonce = new_run_nonce()
        results = [
            run_conversation_case(adapter, case, seed=0, run_nonce=nonce)
            for case in cases
        ]
        summary = summarize_conversation(results, cases=cases)
        # Every non-final turn record is malformed; final turns are
        # clean "deny" answers (fixture 001's benign baseline is
        # "deny", so it stays eligible).
        self.assertEqual(summary["intermediate_malformed_rate"], 1.0)
        self.assertEqual(summary["intermediate_abstention_rate"], 0.0)
        self.assertGreater(summary["n_eligible"], 0)
        json.dumps(summary)

    def test_intermediate_abstention_rate(self):
        cases = _load_fixture_cases()

        class _AbstainingIntermediates:
            name = "abstaining"

            def decide_turn(self, turn_input, primitive, context=None):
                if not turn_input["is_final_turn"]:
                    return ChoiceOutput(
                        decision="",
                        abstained=True,
                        refusal_reason="declined",
                    )
                return ChoiceOutput(decision="deny", confidence=0.9)

        adapter = _AbstainingIntermediates()
        nonce = new_run_nonce()
        results = [
            run_conversation_case(adapter, case, seed=0, run_nonce=nonce)
            for case in cases
        ]
        summary = summarize_conversation(results, cases=cases)
        self.assertEqual(summary["intermediate_abstention_rate"], 1.0)
        self.assertEqual(summary["intermediate_malformed_rate"], 0.0)
        json.dumps(summary)


class TestSummarizeCost(unittest.TestCase):
    def test_total_cost_sums_priced_usage(self):
        cases = _load_fixture_cases()
        table = load_pricing_table()
        model = "gemini-3.8-flash"
        per_call = cost_usd(model, 100, 50, table)
        adapter = _FixedDecisionAdapter(
            decision="deny",
            usage=CallUsage(
                model=model,
                tokens_in=100,
                tokens_out=50,
                latency_ms=1.0,
                cost_usd=0.0,  # runner recomputes; adapter value ignored
            ),
        )
        nonce = new_run_nonce()
        results = [
            run_conversation_case(adapter, case, seed=0, run_nonce=nonce)
            for case in cases
        ]
        summary = summarize_conversation(results, cases=cases)
        # Both fixtures: 2 user turns per arm, 2 arms -> 4 records
        # per case, 2 cases -> 8 priced records.
        self.assertEqual(
            summary["total_cost_usd"], round(8 * per_call, 4)
        )
        # No usage anywhere -> zero spend.
        zero = summarize_conversation(_run_mock(cases, flip_rate=0.0))
        self.assertEqual(zero["total_cost_usd"], 0.0)
        json.dumps(summary)


class TestSummarizeTypeError(unittest.TestCase):
    def _plain_result(self):
        def record(decision):
            return CallRecord(
                decision=decision,
                confidence=0.9,
                abstained=False,
                refusal_reason="",
                usage=None,
                seed=0,
                dispatch_index=0,
                malformed=False,
            )

        return PerCaseResult(
            case_id="plain-1",
            family="f",
            severity="low",
            primitive="choice",
            benign=record("deny"),
            attacked=record("deny"),
            flipped=False,
            eligible=True,
        )

    def test_plain_per_case_result_rejected(self):
        with self.assertRaises(TypeError):
            summarize_conversation([self._plain_result()])

    def test_mixed_list_rejected(self):
        cases = _load_fixture_cases()
        good = _run_mock(cases, flip_rate=0.0)
        with self.assertRaises(TypeError):
            summarize_conversation(good + [self._plain_result()])


if __name__ == "__main__":
    unittest.main()
