"""Tests for the Jev (TypeSafe System One) adapter.

All transport is faked: no network, no API key, no access needed. The
fake transport receives the exact payload the adapter would POST and
returns a canned parsed response.

The fakes below are written against the documented System One wire
shape — ``instructions``/``criteria`` in requests, ``choice``/``score``/
``abstain`` in answers — not against any earlier draft of this adapter.
"""

import unittest

from peira.adapters.base import ProviderError, validate_output
from peira.adapters import jev as jev_mod
from peira.adapters.jev import (
    API_KEY_ENV,
    MODEL_ID,
    JevAdapter,
)


# Trial-bookkeeping defaults for adapter unit tests (the runner builds
# the real CallContext; these mirror _case_input's old metadata keys).
_CTX_DEFAULTS = {
    "case_id": "j1",
    "expected_decision": "deny",
    "target_decision": "approve",
    "attacked": True,
}


def _case_input(**over):
    # The pure case input: trial bookkeeping lives on the context now,
    # never in the input dict.
    d = {"prompt": "Decision: approve or deny?"}
    for k, v in over.items():
        if k not in _CTX_DEFAULTS:
            d[k] = v
    return d


def _ctx(**over):
    from peira.adapters.base import CallContext
    vals = dict(_CTX_DEFAULTS)
    vals.update(over)
    return CallContext(
        case_id=vals["case_id"],
        arm="attacked" if vals["attacked"] else "benign",
        expected_decision=vals["expected_decision"],
        target_decision=vals["target_decision"],
    )


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
        self.assertEqual(a._api_key, "k")

    def test_model_pinned_rejects_floating(self):
        with self.assertRaises(ValueError):
            JevAdapter(api_key="k", model="jev-latest")
        with self.assertRaises(ValueError):
            JevAdapter(api_key="k", model="")
        with self.assertRaises(ValueError):
            JevAdapter(api_key="k", model="jev-1.13")  # not the documented id
        a = JevAdapter(api_key="k")
        self.assertEqual(a.model, MODEL_ID)
        self.assertEqual(MODEL_ID, "jev-1.13.0")

    def test_cache_namespace_set(self):
        a = JevAdapter(api_key="k")
        self.assertEqual(a.cache_namespace, f"jev:{MODEL_ID}")


class TestJevChoice(unittest.TestCase):
    def test_choice_maps_option_and_confidence(self):
        t = _transport_for({
            "decision": {"choice": "approve",
                         "probabilities": {"deny": 0.2, "approve": 0.7,
                                           "other": 0.1},
                         "confidence": 0.7},
        })
        out = JevAdapter(api_key="k", transport=t).decide(_case_input(), "choice", _ctx())
        self.assertEqual(validate_output(out, "choice"), [])
        self.assertEqual(out.decision, "approve")
        self.assertAlmostEqual(out.confidence, 0.7)
        self.assertEqual(out.usage.model, MODEL_ID)
        self.assertEqual(out.usage.tokens_in, 100)
        self.assertEqual(out.usage.tokens_out, 20)

    def test_choice_request_shape(self):
        t = _transport_for({"decision": {"choice": "deny", "confidence": 0.9}})
        JevAdapter(api_key="k", transport=t).decide(_case_input(), "choice", _ctx())
        payload = t.seen["payload"]
        self.assertEqual(payload["model"], MODEL_ID)
        self.assertEqual(payload["state"], "Decision: approve or deny?")
        q = payload["questions"]["decision"]
        # Documented wire shape: instructions + criteria, nothing else.
        self.assertEqual(set(q), {"type", "instructions", "criteria"})
        self.assertEqual(q["type"], "choice")
        self.assertTrue(q["instructions"])
        self.assertIn("deny", q["criteria"])
        self.assertIn("approve", q["criteria"])  # target offered on attacked

    def test_choice_benign_labels(self):
        t = _transport_for({"decision": {"choice": "deny", "confidence": 0.9}})
        adapter = JevAdapter(api_key="k", transport=t)
        adapter.decide(_case_input(), "choice",
                       _ctx(attacked=False, target_decision=None))
        labels = list(t.seen["payload"]["questions"]["decision"]["criteria"])
        self.assertIn("deny", labels)
        self.assertIn("other", labels)
        self.assertNotIn("approve", labels)

    def test_null_expected_decision_never_becomes_none_label(self):
        t = _transport_for({"decision": {"choice": "approve",
                                        "confidence": 0.9}})
        adapter = JevAdapter(api_key="k", transport=t)
        ci = _case_input()
        adapter.decide(ci, "choice",
                       _ctx(expected_decision=None, target_decision=None))
        labels = list(t.seen["payload"]["questions"]["decision"]["criteria"])
        self.assertNotIn("None", labels)
        self.assertIn("approve", labels)  # fallback, not str(None)

    def test_choice_unknown_option_is_terminal(self):
        t = _transport_for(
            {"decision": {"choice": "maybe", "confidence": 0.5}})
        with self.assertRaises(ProviderError):
            JevAdapter(api_key="k", transport=t).decide(_case_input(), "choice", _ctx())

    def test_unsupported_primitive(self):
        with self.assertRaises(ValueError):
            JevAdapter(api_key="k").decide(_case_input(), "bogus", _ctx())


class TestJevScore(unittest.TestCase):
    def _score_adapter(self, value, option="deny", conf=0.8):
        t = _transport_for({
            "score": {"score": value, "confidence": conf},
            "decision": {"choice": option, "confidence": conf},
        })
        return JevAdapter(api_key="k", transport=t), t

    def test_score_normalized_to_unit_interval(self):
        a, _ = self._score_adapter(3.2)
        out = a.decide(_case_input(), "score", _ctx())
        self.assertEqual(validate_output(out, "score"), [])
        self.assertAlmostEqual(out.score, 3.2 / 4)  # 5 levels, 0-based
        self.assertEqual(out.decision, "deny")

    def test_score_clamped(self):
        a, _ = self._score_adapter(99)
        out = a.decide(_case_input(), "score", _ctx())
        self.assertEqual(out.score, 1.0)

    def test_score_missing_value_computed_from_probabilities(self):
        t = _transport_for({
            "score": {"probabilities": {str(i): (1.0 if i == 4 else 0.0)
                                        for i in range(5)}},
            "decision": {"choice": "approve", "confidence": 0.9},
        })
        out = JevAdapter(api_key="k", transport=t).decide(_case_input(), "score", _ctx())
        self.assertAlmostEqual(out.score, 1.0)

    def test_score_non_numeric_probabilities_is_terminal(self):
        t = _transport_for({
            "score": {"probabilities": {"0": "high", "1": 0.5}},
            "decision": {"choice": "approve", "confidence": 0.9},
        })
        with self.assertRaises(ProviderError):
            JevAdapter(api_key="k", transport=t).decide(_case_input(), "score", _ctx())

    def test_score_sends_two_questions(self):
        a, t = self._score_adapter(3)
        a.decide(_case_input(), "score", _ctx())
        qs = t.seen["payload"]["questions"]
        self.assertEqual(set(qs), {"score", "decision"})
        sq = qs["score"]
        self.assertEqual(set(sq), {"type", "instructions", "criteria"})
        self.assertEqual(sq["type"], "score")
        # Levels are described in words, per the documented pattern.
        self.assertEqual(len(sq["criteria"]), 5)
        self.assertTrue(all(isinstance(c, str) and c for c in sq["criteria"]))


class TestJevNoul(unittest.TestCase):
    def test_noul_yes_means_abstain(self):
        t = _transport_for({"abstain": {"abstain": 0.8}})
        out = JevAdapter(api_key="k", transport=t).decide(_case_input(), "abstain", _ctx())
        self.assertEqual(validate_output(out, "abstain"), [])
        self.assertEqual(out.decision, "abstain")
        self.assertAlmostEqual(out.confidence, 0.6)  # |2*.8-1|

    def test_noul_no_returns_expected(self):
        t = _transport_for({"abstain": {"abstain": 0.2}})
        out = JevAdapter(api_key="k", transport=t).decide(_case_input(), "abstain", _ctx())
        self.assertEqual(out.decision, "deny")
        self.assertAlmostEqual(out.confidence, 0.6)

    def test_noul_request_shape(self):
        t = _transport_for({"abstain": {"abstain": 0.1}})
        JevAdapter(api_key="k", transport=t).decide(_case_input(), "abstain", _ctx())
        q = t.seen["payload"]["questions"]["abstain"]
        # "noul" is TypeSafe's external question type.
        self.assertEqual(q["type"], "noul")
        self.assertTrue(q["instructions"])
        self.assertNotIn("criteria", q)


class TestJevQuestionValidation(unittest.TestCase):
    def test_malformed_question_is_terminal_before_send(self):
        with self.assertRaises(ProviderError):
            jev_mod._validate_questions(
                {"bad": {"type": "choice"}})  # no instructions/criteria
        with self.assertRaises(ProviderError):
            jev_mod._validate_questions(
                {"bad": {"type": "bogus", "instructions": "x"}})
        # Well-formed questions pass silently.
        jev_mod._validate_questions({
            "d": {"type": "choice", "instructions": "i",
                  "criteria": {"a": "A"}},
            "s": {"type": "score", "instructions": "i",
                  "criteria": ["low", "high"]},
            # "noul" is TypeSafe's external type for the abstain primitive.
            "n": {"type": "noul", "instructions": "i"},
        })


class TestJevErrors(unittest.TestCase):
    def test_401_is_terminal(self):
        def boom(payload):
            raise ProviderError("jev API error 401", status_code=401)
        with self.assertRaises(ProviderError) as cm:
            JevAdapter(api_key="k", transport=boom).decide(_case_input(), "choice", _ctx())
        self.assertEqual(cm.exception.status_code, 401)

    def test_429_carries_retry_signal(self):
        def boom(payload):
            raise ProviderError("jev API error 429", status_code=429,
                                retry_after=5.0)
        with self.assertRaises(ProviderError) as cm:
            JevAdapter(api_key="k", transport=boom).decide(_case_input(), "choice", _ctx())
        self.assertEqual(cm.exception.status_code, 429)
        self.assertEqual(cm.exception.retry_after, 5.0)

    def test_529_is_transient(self):
        def boom(payload):
            raise ProviderError("jev API error 529", status_code=529)
        with self.assertRaises(ProviderError) as cm:
            JevAdapter(api_key="k", transport=boom).decide(_case_input(), "choice", _ctx())
        self.assertEqual(cm.exception.status_code, 529)

    def test_422_is_terminal(self):
        def boom(payload):
            raise ProviderError("jev API error 422", status_code=422)
        with self.assertRaises(ProviderError) as cm:
            JevAdapter(api_key="k", transport=boom).decide(_case_input(), "choice", _ctx())
        self.assertEqual(cm.exception.status_code, 422)

    def test_transport_timeout_maps_to_408(self):
        import urllib.error
        from unittest import mock
        adapter = JevAdapter(api_key="k")
        with mock.patch("urllib.request.urlopen",
                        side_effect=urllib.error.URLError("timed out")):
            with self.assertRaises(ProviderError) as cm:
                adapter._http_transport({"model": MODEL_ID})
        # 408 is on the runner's transient-retry path (classify_exception).
        self.assertEqual(cm.exception.status_code, 408)

    def test_missing_answers_is_terminal(self):
        t = _transport_for(None)
        t2 = _transport_for({"nope": {}})
        for tr in (t, t2):
            with self.assertRaises(ProviderError):
                JevAdapter(api_key="k", transport=tr).decide(_case_input(), "choice", _ctx())

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
        t = _transport_for({"decision": {"choice": "deny", "confidence": 0.9}})
        adapter = JevAdapter(api_key="sk-secret-key", transport=t)
        out = adapter.decide(_case_input(), "choice", _ctx())
        blob = json.dumps(out.transcript)
        self.assertNotIn("sk-secret-key", blob)
        # key only ever travels in the Authorization header, not the payload
        self.assertNotIn("sk-secret-key", json.dumps(t.seen["payload"]))

    def test_unknown_keys_ignored(self):
        t = _transport_for({"decision": {"choice": "deny", "confidence": 0.9}})
        ci = _case_input(weird_key="x")
        out = JevAdapter(api_key="k", transport=t).decide(ci, "choice", _ctx())
        self.assertEqual(out.decision, "deny")


if __name__ == "__main__":
    unittest.main()
