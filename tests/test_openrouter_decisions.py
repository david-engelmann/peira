"""Tests for the OpenRouter Decisions adapter.

All transport is faked: no network, no API key, no access needed. The
fake transport receives the exact payload the adapter would POST to
OpenRouter's System One surface and returns a canned parsed response.

The instrument-identity tests pin the load-bearing contract: the
question text this adapter sends must be the Jev adapter's, word for
word, so every decision wire measures the same decision space.
"""

import unittest

from peira.adapters.base import CallContext, ProviderError
from peira.adapters import jev as jev_mod
from peira.adapters import openrouter_decisions as ord_mod
from peira.adapters.openrouter_decisions import (
    API_KEY_ENV,
    API_URL,
    MODEL_ID,
    SUPPORTED_MODEL_IDS,
    OpenRouterDecisionsAdapter,
)


def _case_input(**over):
    d = {"prompt": "Decision: approve or deny?",
         "options": ["approve", "deny"]}
    d.update(over)
    return d


def _ctx(**over):
    return CallContext(call_id=over.get("call_id", "call-test"))


def _transport_for(answers, usage=None, latency=12.5):
    seen = {}

    def transport(payload):
        seen["payload"] = payload
        return {
            "answers": answers,
            "usage": usage or {"input_tokens": 100, "output_tokens": 0},
            "_latency_ms": latency,
        }

    transport.seen = seen
    return transport


class TestPinning(unittest.TestCase):
    def test_default_pin(self):
        self.assertEqual(MODEL_ID, "microsoft/microsoft-decision-1")
        self.assertEqual(SUPPORTED_MODEL_IDS,
                         frozenset({"microsoft/microsoft-decision-1"}))

    def test_rejects_unversioned_and_other_ids(self):
        for bad in ("microsoft-decision-1", "microsoft/other-model",
                    "typesafe/jev-1.14", ""):
            with self.assertRaises(ValueError, msg=bad):
                OpenRouterDecisionsAdapter(model=bad, api_key="k",
                                           transport=_transport_for({}))

    def test_rejection_names_the_pin(self):
        with self.assertRaises(ValueError) as cm:
            OpenRouterDecisionsAdapter(model="nope", api_key="k",
                                       transport=_transport_for({}))
        self.assertIn("microsoft/microsoft-decision-1", str(cm.exception))

    def test_name_binding(self):
        self.assertEqual(OpenRouterDecisionsAdapter.name,
                         "openrouter-decisions")

    def test_api_surface(self):
        self.assertEqual(API_URL, "https://openrouter.ai/api/v1/systemone")
        self.assertEqual(API_KEY_ENV, "OPENROUTER_API_KEY")

    def test_missing_key_names_openrouter_env_var(self):
        import os
        old = os.environ.pop(API_KEY_ENV, None)
        try:
            with self.assertRaises(ValueError) as ctx:
                OpenRouterDecisionsAdapter(
                    transport=_transport_for({}))
            self.assertIn(API_KEY_ENV, str(ctx.exception))
            self.assertNotIn("TYPESAFE_API_KEY", str(ctx.exception))
        finally:
            if old is not None:
                os.environ[API_KEY_ENV] = old

    def test_cache_namespace_names_wire_and_model(self):
        a = OpenRouterDecisionsAdapter(
            api_key="k", transport=_transport_for({}))
        self.assertEqual(
            a.cache_namespace,
            "openrouter-decisions:microsoft/microsoft-decision-1")
        self.assertNotEqual(a.cache_namespace, "jev:microsoft/microsoft-decision-1")


class TestInstrumentIdentity(unittest.TestCase):
    """The question text is the measurement instrument. It must be the
    Jev adapter's, unchanged."""

    def test_choice_question_matches_jev(self):
        self.assertEqual(ord_mod._choice_question(["a", "b"]),
                         jev_mod._choice_question(["a", "b"]))

    def test_score_question_matches_jev(self):
        self.assertEqual(ord_mod._score_question(),
                         jev_mod._score_question())

    def test_noul_question_matches_jev(self):
        self.assertEqual(ord_mod._noul_question(),
                         jev_mod._noul_question())

    def test_score_levels_match_jev(self):
        self.assertEqual(ord_mod._SCORE_LEVELS, jev_mod._SCORE_LEVELS)


class TestDecide(unittest.TestCase):
    def test_choice_round_trip(self):
        t = _transport_for({"decision": {"choice": "deny", "confidence": 0.9,
                                         "probabilities": {"deny": 0.9,
                                                           "approve": 0.1}}})
        out = OpenRouterDecisionsAdapter(
            api_key="k", transport=t).decide(_case_input(), "choice", _ctx())
        self.assertEqual(out.decision, "deny")
        self.assertAlmostEqual(out.confidence, 0.9)
        payload = t.seen["payload"]
        self.assertEqual(payload["model"], "microsoft/microsoft-decision-1")
        self.assertEqual(payload["questions"]["decision"]["type"], "choice")

    def test_noul_answer_shape(self):
        t = _transport_for({"abstain": {"type": "noul", "noul": 0.8}})
        out = OpenRouterDecisionsAdapter(
            api_key="k", transport=t).decide(_case_input(), "abstain", _ctx())
        self.assertEqual(out.decision, "abstain")

    def test_score_fallback_reads_levels_by_key(self):
        # The fallback weights each probability by the level its
        # key names, never by the value's position in the map: the
        # map below arrives out of order and still computes the
        # position its keys state.
        t = _transport_for({
            "score": {"probabilities": {"4": 0.5, "0": 0.0, "3": 0.5,
                                        "1": 0.0, "2": 0.0}},
            "decision": {"choice": "deny", "confidence": 0.8},
        })
        out = OpenRouterDecisionsAdapter(
            api_key="test-key", transport=t).decide(
                _case_input(), "score", _ctx())
        self.assertAlmostEqual(out.score, (3 * 0.5 + 4 * 0.5) / 4)

    def test_score_fallback_key_naming_no_level_is_terminal(self):
        # Mass under a key naming no level was previously weighted
        # by its position in the map, so a fifth entry at full mass
        # fabricated the maximum score. It now voids the fallback.
        t = _transport_for({
            "score": {"probabilities": {"0": 0.0, "1": 0.0, "2": 0.0,
                                        "3": 0.0, "99": 1.0}},
            "decision": {"choice": "deny", "confidence": 0.8},
        })
        with self.assertRaises(ProviderError):
            OpenRouterDecisionsAdapter(
                api_key="test-key", transport=t).decide(
                    _case_input(), "score", _ctx())

    def test_score_fallback_partial_mass_is_terminal(self):
        # A map totalling 0.5 is not a distribution: weighting by
        # it would halve the position toward zero and report the
        # result as a measurement.
        t = _transport_for({
            "score": {"probabilities": {"0": 0.07, "1": 0.02,
                                        "2": 0.06, "3": 0.20,
                                        "4": 0.15}},
            "decision": {"choice": "deny", "confidence": 0.8},
        })
        with self.assertRaises(ProviderError):
            OpenRouterDecisionsAdapter(
                api_key="test-key", transport=t).decide(
                    _case_input(), "score", _ctx())

    def test_score_fallback_huge_int_probability_is_terminal(self):
        # An int probability is genuine only as 0 or 1. A several-
        # hundred-digit JSON integer parses to an int whose float()
        # raises OverflowError. The fallback must void it (and fail
        # closed) instead of letting the exception escape.
        t = _transport_for({
            "score": {"probabilities": {"0": 0.0, "1": 0.0,
                                        "2": 10**400, "3": 0.0,
                                        "4": 0.0}},
            "decision": {"choice": "deny", "confidence": 0.8},
        })
        with self.assertRaises(ProviderError):
            OpenRouterDecisionsAdapter(
                api_key="test-key", transport=t).decide(
                    _case_input(), "score", _ctx())

    def test_score_direct_huge_int_clamps_to_extreme(self):
        # The direct path clamps out-of-range scores. A several-
        # hundred-digit JSON integer parses to an int whose float()
        # raises OverflowError. Compared exactly it is out of range
        # in its own direction, so it clamps to the same extreme a
        # large finite value would instead of escaping unclassified.
        for bad, want in ((10**400, 1.0), (-(10**400), 0.0)):
            t = _transport_for({
                "score": {"score": bad},
                "decision": {"choice": "deny", "confidence": 0.8},
            })
            out = OpenRouterDecisionsAdapter(
                api_key="test-key", transport=t).decide(
                    _case_input(), "score", _ctx())
            self.assertEqual(out.score, want)

    def test_noul_huge_int_clamps_to_extreme(self):
        # The abstain path clamps through the same helper as the
        # confidence paths: a several-hundred-digit JSON integer
        # clamps to the extreme in its own direction instead of
        # escaping as an unclassified OverflowError.
        t = _transport_for({"abstain": {"abstain": 10**400}})
        out = OpenRouterDecisionsAdapter(
            api_key="test-key", transport=t).decide(
                _case_input(), "abstain", _ctx())
        self.assertEqual(out.decision, "abstain")
        self.assertEqual(out.confidence, 1.0)

    def test_choice_confidence_huge_int_clamps_to_extreme(self):
        # Confidence routes through the clamp helper, whose int
        # comparison is exact: a several-hundred-digit JSON integer
        # clamps to the same extreme a large finite value would
        # instead of escaping as an unclassified OverflowError.
        t = _transport_for({
            "decision": {"choice": "approve", "confidence": 10**400},
        })
        out = OpenRouterDecisionsAdapter(
            api_key="test-key", transport=t).decide(
                _case_input(), "choice", _ctx())
        self.assertEqual(out.confidence, 1.0)

    def test_missing_answers_is_terminal(self):
        t = _transport_for({})
        with self.assertRaises(ProviderError):
            OpenRouterDecisionsAdapter(
                api_key="k", transport=t).decide(_case_input(), "choice",
                                                _ctx())



class TestRetryAfterNonfinite(unittest.TestCase):
    def test_retry_after_nonfinite_is_dropped(self):
        # "inf" and "nan" parse as floats; neither is a usable
        # delay. Finite values pass through (the runner caps the
        # delay at MAX_RETRY_AFTER_S when it consumes the value).
        self.assertIsNone(ord_mod._parse_retry_after("inf"))
        self.assertIsNone(ord_mod._parse_retry_after("nan"))
        self.assertIsNone(ord_mod._parse_retry_after("1e400"))
        self.assertEqual(ord_mod._parse_retry_after("7"), 7.0)


class TestOpenRouterClampContract(unittest.TestCase):
    def test_choice_confidence_nan_is_terminal(self):
        t = _transport_for({"decision": {"choice": "deny",
                                         "confidence": float("nan")}})
        with self.assertRaises(ProviderError):
            OpenRouterDecisionsAdapter(
                api_key="<redacted>", transport=t).decide(
                    _case_input(), "choice", _ctx())

    def test_choice_confidence_string_is_terminal(self):
        t = _transport_for({"decision": {"choice": "deny",
                                         "confidence": "0.9"}})
        with self.assertRaises(ProviderError):
            OpenRouterDecisionsAdapter(
                api_key="<redacted>", transport=t).decide(
                    _case_input(), "choice", _ctx())

if __name__ == "__main__":
    unittest.main()
