"""Tests for the Jev (TypeSafe System One) adapter.

All transport is faked: no network, no API key, no access needed. The
fake transport receives the exact payload the adapter would POST and
returns a canned parsed response.
"""

import unittest

from peira.adapters.base import ProviderError, validate_output
from peira.adapters.jev import (
    API_KEY_ENV,
    MODEL_ID,
    JevAdapter,
)


def _case_input(**over):
    d = {
        "prompt": "Decision: approve or deny?",
        "case_id": "j1",
        "expected_decision": "deny",
        "target_decision": "approve",
        "attacked": True,
    }
    d.update(over)
    return d


def _transport_for(answers, usage=None, latency=12.5):
    seen = {}

    def fake(payload):
        seen["payload"] = payload
        return {
            "model": MODEL_ID,
            "answers": answers,
            "usage": usage or {"input_tokens": 100, "output_tokens": 20},
            "_latency_ms": latency,
        }

    fake.seen = seen
    return fake


class TestJevConstruction(unittest.TestCase):
    def test_missing_key_is_actionable(self):
        import os
        old = os.environ.pop(API_KEY_ENV, None)
        try:
            with self.assertRaises(ValueError) as cm:
                JevAdapter()
        finally:
            if old is not None:
                os.environ[API_KEY_ENV] = old
        self.assertIn(API_KEY_ENV, str(cm.exception))

    def test_explicit_key_ok(self):
        a = JevAdapter(api_key="k")
        self.assertEqual(a.api_key, "k")

    def test_model_pinned_rejects_floating(self):
        with self.assertRaises(ValueError):
            JevAdapter(api_key="k", model="jev-latest")
        with self.assertRaises(ValueError):
            JevAdapter(api_key="k", model="")
        a = JevAdapter(api_key="k")
        self.assertEqual(a.model, MODEL_ID)


class TestJevChoice(unittest.TestCase):
    def test_choice_maps_option_and_confidence(self):
        t = _transport_for({
            "decision": {"option": "approve",
                         "probabilities": {"deny": 0.2, "approve": 0.7,
                                           "other": 0.1},
                         "confidence": 0.7},
        })
        out = JevAdapter(api_key="k", transport=t).decide(_case_input(), "choice")
        self.assertEqual(validate_output(out, "choice"), [])
        self.assertEqual(out.decision, "approve")
        self.assertAlmostEqual(out.confidence, 0.7)
        self.assertEqual(out.usage.model, MODEL_ID)
        self.assertEqual(out.usage.tokens_in, 100)
        self.assertEqual(out.usage.tokens_out, 20)

    def test_choice_request_shape(self):
        t = _transport_for({"decision": {"option": "deny", "confidence": 0.9}})
        JevAdapter(api_key="k", transport=t).decide(_case_input(), "choice")
        payload = t.seen["payload"]
        self.assertEqual(payload["model"], MODEL_ID)
        self.assertEqual(payload["state"], "Decision: approve or deny?")
        q = payload["questions"]["decision"]
        self.assertEqual(q["type"], "choice")
        self.assertIn("deny", q["options"])
        self.assertIn("approve", q["options"])  # target offered on attacked

    def test_choice_benign_labels(self):
        t = _transport_for({"decision": {"option": "deny", "confidence": 0.9}})
        adapter = JevAdapter(api_key="k", transport=t)
        benign = _case_input(attacked=False)
        del benign["target_decision"]
        adapter.decide(benign, "choice")
        labels = list(t.seen["payload"]["questions"]["decision"]["options"])
        self.assertIn("deny", labels)
        self.assertIn("other", labels)
        self.assertNotIn("approve", labels)

    def test_choice_unknown_option_is_terminal(self):
        t = _transport_for({"decision": {"option": "maybe", "confidence": 0.5}})
        with self.assertRaises(ProviderError):
            JevAdapter(api_key="k", transport=t).decide(_case_input(), "choice")

    def test_unsupported_primitive(self):
        with self.assertRaises(ValueError):
            JevAdapter(api_key="k").decide(_case_input(), "bogus")


class TestJevScore(unittest.TestCase):
    def _score_adapter(self, value, option="deny", conf=0.8):
        t = _transport_for({
            "score": {"value": value, "confidence": conf},
            "decision": {"option": option, "confidence": conf},
        })
        return JevAdapter(api_key="k", transport=t), t

    def test_score_normalized_to_unit_interval(self):
        a, _ = self._score_adapter(7.2)
        out = a.decide(_case_input(), "score")
        self.assertEqual(validate_output(out, "score"), [])
        self.assertAlmostEqual(out.score, 7.2 / 9)
        self.assertEqual(out.decision, "deny")

    def test_score_clamped(self):
        a, _ = self._score_adapter(99)
        out = a.decide(_case_input(), "score")
        self.assertEqual(out.score, 1.0)

    def test_score_missing_value_computed_from_probabilities(self):
        t = _transport_for({
            "score": {"probabilities": {str(i): (1.0 if i == 9 else 0.0)
                                        for i in range(10)}},
            "decision": {"option": "approve", "confidence": 0.9},
        })
        out = JevAdapter(api_key="k", transport=t).decide(_case_input(), "score")
        self.assertAlmostEqual(out.score, 1.0)

    def test_score_non_numeric_probabilities_is_terminal(self):
        t = _transport_for({
            "score": {"probabilities": {"0": "high", "1": 0.5}},
            "decision": {"option": "approve", "confidence": 0.9},
        })
        with self.assertRaises(ProviderError):
            JevAdapter(api_key="k", transport=t).decide(_case_input(), "score")

    def test_score_sends_two_questions(self):
        a, t = self._score_adapter(5)
        a.decide(_case_input(), "score")
        qs = t.seen["payload"]["questions"]
        self.assertEqual(set(qs), {"score", "decision"})
        self.assertEqual(len(qs["score"]["levels"]), 10)


class TestJevNoul(unittest.TestCase):
    def test_noul_yes_means_abstain(self):
        t = _transport_for({"abstain": {"probability_yes": 0.8,
                                        "confidence": 0.8}})
        out = JevAdapter(api_key="k", transport=t).decide(_case_input(), "noul")
        self.assertEqual(validate_output(out, "noul"), [])
        self.assertEqual(out.decision, "abstain")
        self.assertAlmostEqual(out.confidence, 0.6)  # |2*.8-1|

    def test_noul_no_returns_expected(self):
        t = _transport_for({"abstain": {"probability_yes": 0.2}})
        out = JevAdapter(api_key="k", transport=t).decide(_case_input(), "noul")
        self.assertEqual(out.decision, "deny")
        self.assertAlmostEqual(out.confidence, 0.6)


class TestJevErrors(unittest.TestCase):
    def test_401_is_terminal(self):
        def boom(payload):
            raise ProviderError("jev API error 401", status_code=401)
        with self.assertRaises(ProviderError) as cm:
            JevAdapter(api_key="k", transport=boom).decide(_case_input(), "choice")
        self.assertEqual(cm.exception.status_code, 401)

    def test_429_carries_retry_signal(self):
        def boom(payload):
            raise ProviderError("jev API error 429", status_code=429,
                                retry_after=5.0)
        with self.assertRaises(ProviderError) as cm:
            JevAdapter(api_key="k", transport=boom).decide(_case_input(), "choice")
        self.assertEqual(cm.exception.status_code, 429)
        self.assertEqual(cm.exception.retry_after, 5.0)

    def test_529_is_transient(self):
        def boom(payload):
            raise ProviderError("jev API error 529", status_code=529)
        with self.assertRaises(ProviderError) as cm:
            JevAdapter(api_key="k", transport=boom).decide(_case_input(), "choice")
        self.assertEqual(cm.exception.status_code, 529)

    def test_422_is_terminal(self):
        def boom(payload):
            raise ProviderError("jev API error 422", status_code=422)
        with self.assertRaises(ProviderError) as cm:
            JevAdapter(api_key="k", transport=boom).decide(_case_input(), "choice")
        self.assertEqual(cm.exception.status_code, 422)

    def test_missing_answers_is_terminal(self):
        t = _transport_for(None)
        t2 = _transport_for({"nope": {}})
        for tr in (t, t2):
            with self.assertRaises(ProviderError):
                JevAdapter(api_key="k", transport=tr).decide(_case_input(), "choice")

    def test_raise_for_status_mapping(self):
        a = JevAdapter.__new__(JevAdapter)  # no network, no key needed
        for status, transient in [(401, False), (422, False), (429, True),
                                  (529, True), (500, True), (503, True),
                                  (400, False)]:
            with self.assertRaises(ProviderError) as cm:
                a._raise_for_status(status, None, "detail")
            self.assertEqual(cm.exception.status_code, status)

    def test_transcript_has_no_key_material(self):
        import json
        t = _transport_for({"decision": {"option": "deny", "confidence": 0.9}})
        adapter = JevAdapter(api_key="sk-secret-key", transport=t)
        out = adapter.decide(_case_input(), "choice")
        blob = json.dumps(out.transcript)
        self.assertNotIn("sk-secret-key", blob)
        # key only ever travels in the Authorization header, not the payload
        self.assertNotIn("sk-secret-key", json.dumps(t.seen["payload"]))

    def test_unknown_keys_ignored(self):
        t = _transport_for({"decision": {"option": "deny", "confidence": 0.9}})
        ci = _case_input(weird_key="x", attacked=True, target_decision="approve")
        out = JevAdapter(api_key="k", transport=t).decide(ci, "choice")
        self.assertEqual(out.decision, "deny")


if __name__ == "__main__":
    unittest.main()
