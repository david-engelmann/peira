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

    def test_missing_answers_is_terminal(self):
        t = _transport_for({})
        with self.assertRaises(ProviderError):
            OpenRouterDecisionsAdapter(
                api_key="k", transport=t).decide(_case_input(), "choice",
                                                _ctx())


if __name__ == "__main__":
    unittest.main()
