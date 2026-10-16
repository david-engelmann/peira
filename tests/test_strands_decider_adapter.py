"""Tests for the Strands Decider adapter.

No network, no Strands server: the transport is faked like in
test_openjev_sglang_adapter.py. Under test: the pinned v21
checkpoint id, the configurable endpoint, the inherited
Jev-compatible wire behavior, and the one wire difference that
matters (the server's rescaled confidence must not reach peira's
output when the answer carries per-option probabilities).
"""

import unittest
import urllib.error
from unittest import mock

from peira.adapters.base import CallContext, ProviderError, validate_output
from peira.adapters.jev import JevAdapter
from peira.adapters.kev import LocalSystemOneAdapter
from peira.adapters.strands_decider import MODEL_ID, StrandsDeciderAdapter

# B2 (D-25 amended): the adapter-visible context is an opaque per-call
# handle — no case id, no arm, no gold labels. The candidate decision
# labels come from the case input's explicit "options" list.
def _case_input(**over):
    d = {"prompt": "Decision: approve or deny?",
         "options": ["approve", "deny"]}
    d.update(over)
    return d


def _ctx(**over):
    return CallContext(call_id=over.get("call_id", "call-test"))


# The real server reports the checkpoint basename as `model`
# (its default naming), not the full Hub id.
_STAMP = "strands-decider-2B-hobson-v21"


def _transport_for(answers, latency=12.5, model=_STAMP):
    seen = {}

    def fake(payload):
        seen["payload"] = payload
        response = {"answers": answers, "_latency_ms": latency}
        if model is not None:
            response["model"] = model
        return response

    fake.seen = seen
    return fake


class TestStrandsDeciderConstruction(unittest.TestCase):
    def test_model_pinned(self):
        self.assertEqual(
            MODEL_ID, "StrandsAgents/strands-decider-2B-hobson-v21")
        a = StrandsDeciderAdapter()
        self.assertEqual(a.model, MODEL_ID)
        self.assertEqual(a.version, MODEL_ID)
        self.assertEqual(a.cache_namespace, f"strands-decider:{MODEL_ID}")

    def test_other_models_rejected(self):
        for bad in ("hobson-latest", "", "StrandsAgents/strands-decider-2B-hobson-v19",
                    "amazon/strands-decider-2B-hobson-v21", "Qwen/Qwen3.5-2B-Base"):
            with self.assertRaises(ValueError, msg=bad):
                StrandsDeciderAdapter(model=bad)
        self.assertEqual(
            StrandsDeciderAdapter(model=MODEL_ID).model, MODEL_ID)

    def test_pin_error_names_the_pin(self):
        with self.assertRaises(ValueError) as cm:
            StrandsDeciderAdapter(model="hobson-latest")
        self.assertIn("strands-decider adapter pins model", str(cm.exception))

    def test_default_api_url(self):
        a = StrandsDeciderAdapter()
        self.assertEqual(a.api_url, "http://127.0.0.1:8000/v1/systemone")

    def test_custom_api_url(self):
        a = StrandsDeciderAdapter(api_url="http://gpu:8100/v1/systemone")
        self.assertEqual(a.api_url, "http://gpu:8100/v1/systemone")

    def test_reuses_local_wire_plumbing(self):
        a = StrandsDeciderAdapter()
        self.assertIsInstance(a, JevAdapter)
        self.assertIsInstance(a, LocalSystemOneAdapter)
        self.assertEqual(StrandsDeciderAdapter.name, "strands-decider")
        self.assertEqual(StrandsDeciderAdapter.supported_primitives,
                         frozenset({"choice", "score", "abstain"}))


class TestStrandsDeciderWire(unittest.TestCase):
    def test_choice_happy_path(self):
        t = _transport_for({
            "decision": {
                "choice": "deny",
                "confidence": 0.9,
                "probabilities": {"approve": 0.1, "deny": 0.9},
            },
        })
        out = StrandsDeciderAdapter(transport=t).decide(
            _case_input(), "choice", _ctx())
        self.assertEqual(validate_output(out, "choice"), [])
        self.assertEqual(out.decision, "deny")
        self.assertAlmostEqual(out.confidence, 0.9)
        self.assertEqual(out.usage.model, MODEL_ID)

    def test_choice_confidence_is_the_probability_not_the_rescaled_value(self):
        # The server sends a rescaled confidence (0.8 here) alongside
        # the raw distribution (top probability 0.9). Peira measures
        # the probability.
        t = _transport_for({
            "decision": {
                "choice": "deny",
                "confidence": 0.8,
                "probabilities": {"approve": 0.1, "deny": 0.9},
            },
        })
        out = StrandsDeciderAdapter(transport=t).decide(
            _case_input(), "choice", _ctx())
        self.assertAlmostEqual(out.confidence, 0.9)

    def test_decision_answer_without_probabilities_map_is_terminal(self):
        # The server's answer schema requires the map on every
        # decision answer. Without it there is no measured
        # probability to report, and the rescaled confidence
        # (0.9 here) is not a substitute peira may record.
        t = _transport_for({
            "decision": {"choice": "deny", "confidence": 0.9},
        })
        with self.assertRaises(ProviderError):
            StrandsDeciderAdapter(transport=t).decide(
                _case_input(), "choice", _ctx())

    def test_non_dict_probabilities_is_terminal(self):
        t = _transport_for({
            "decision": {
                "choice": "deny",
                "confidence": 0.9,
                "probabilities": [0.1, 0.9],
            },
        })
        with self.assertRaises(ProviderError):
            StrandsDeciderAdapter(transport=t).decide(
                _case_input(), "choice", _ctx())

    def test_non_numeric_probability_for_the_decision_is_terminal(self):
        t = _transport_for({
            "decision": {
                "choice": "deny",
                "confidence": 0.9,
                "probabilities": {"approve": 0.1, "deny": "high"},
            },
        })
        with self.assertRaises(ProviderError):
            StrandsDeciderAdapter(transport=t).decide(
                _case_input(), "choice", _ctx())

    def test_score_path_missing_probability_is_terminal(self):
        # The same drift on the decision answer paired with a
        # score call is terminal through _score_output too.
        t = _transport_for({
            "score": {"score": 2.0, "confidence": 0.6},
            "decision": {
                "choice": "approve",
                "confidence": 0.2,
                "probabilities": {"deny": 1.0},
            },
        })
        with self.assertRaises(ProviderError):
            StrandsDeciderAdapter(transport=t).decide(
                _case_input(), "score", _ctx())

    def test_probabilities_map_missing_the_decision_is_terminal(self):
        # The server builds the map from its slot labels and
        # reports the argmax as the choice, so a map without the
        # chosen option is contract drift. The adapter must not
        # fall back to the rescaled confidence (0.8 here); that
        # would record a number peira does not measure.
        t = _transport_for({
            "decision": {
                "choice": "deny",
                "confidence": 0.8,
                "probabilities": {"approve": 1.0},
            },
        })
        with self.assertRaises(ProviderError):
            StrandsDeciderAdapter(transport=t).decide(
                _case_input(), "choice", _ctx())

    def test_score_confidence_comes_from_the_decision_probability(self):
        t = _transport_for({
            "score": {"score": 2.0, "confidence": 0.6},
            "decision": {
                "choice": "approve",
                "confidence": 0.2,
                "probabilities": {"approve": 0.6, "deny": 0.4},
            },
        })
        out = StrandsDeciderAdapter(transport=t).decide(
            _case_input(), "score", _ctx())
        self.assertEqual(validate_output(out, "score"), [])
        self.assertAlmostEqual(out.score, 2.0 / 4)
        self.assertEqual(out.decision, "approve")
        self.assertAlmostEqual(out.confidence, 0.6)

    def test_payload_model_is_pinned_id(self):
        t = _transport_for({
            "decision": {
                "choice": "deny",
                "confidence": 0.9,
                "probabilities": {"approve": 0.1, "deny": 0.9},
            },
        })
        StrandsDeciderAdapter(transport=t).decide(
            _case_input(), "choice", _ctx())
        self.assertEqual(t.seen["payload"]["model"], MODEL_ID)

    def test_wrong_model_stamp_is_terminal(self):
        # api_url pointed at a deployment of other weights: the
        # response reports that deployment's name, and the call
        # must not be recorded under the pin.
        t = _transport_for(
            {"decision": {
                "choice": "deny",
                "confidence": 0.9,
                "probabilities": {"approve": 0.1, "deny": 0.9},
            }},
            model="strands-decider-2B-hobson-v19",
        )
        with self.assertRaises(ProviderError):
            StrandsDeciderAdapter(transport=t).decide(
                _case_input(), "choice", _ctx())

    def test_missing_model_stamp_is_terminal(self):
        t = _transport_for(
            {"decision": {
                "choice": "deny",
                "confidence": 0.9,
                "probabilities": {"approve": 0.1, "deny": 0.9},
            }},
            model=None,
        )
        with self.assertRaises(ProviderError):
            StrandsDeciderAdapter(transport=t).decide(
                _case_input(), "choice", _ctx())

    def test_abstain_yes_means_abstain(self):
        t = _transport_for({"abstain": {"noul": 0.75}})
        out = StrandsDeciderAdapter(transport=t).decide(
            _case_input(), "abstain", _ctx())
        self.assertEqual(validate_output(out, "abstain"), [])
        self.assertEqual(out.decision, "abstain")
        self.assertAlmostEqual(out.confidence, 0.5)

    def test_abstain_no_returns_other_placeholder(self):
        # The shape the pod GPU canary produced on the
        # duplicate-charge case (p just under the halfway
        # threshold): the decision is the "other" placeholder
        # and the confidence honestly reports near-indifference.
        t = _transport_for({"abstain": {"noul": 0.4791}})
        out = StrandsDeciderAdapter(transport=t).decide(
            _case_input(), "abstain", _ctx())
        self.assertEqual(validate_output(out, "abstain"), [])
        self.assertEqual(out.decision, "other")
        self.assertAlmostEqual(out.confidence, abs(2 * 0.4791 - 1))


class TestStrandsDeciderErrors(unittest.TestCase):
    def test_connection_refused_is_terminal_and_actionable(self):
        a = StrandsDeciderAdapter()
        with mock.patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("connection refused"),
        ):
            with self.assertRaises(ProviderError) as cm:
                a._http_transport({"model": a.model})
        err = cm.exception
        self.assertIsNone(err.status_code)
        self.assertIn("strands-decider", str(err))
        self.assertIn("strands-decider serve", str(err))

    def test_missing_answers_is_terminal(self):
        t = _transport_for(None)
        with self.assertRaises(ProviderError):
            StrandsDeciderAdapter(transport=t).decide(
                _case_input(), "choice", _ctx())

    def test_unknown_option_is_terminal(self):
        # The map carries the drifted label, so the confidence
        # restoration succeeds and the inherited label check is
        # the check that fires.
        t = _transport_for({
            "decision": {
                "choice": "maybe",
                "confidence": 0.5,
                "probabilities": {"maybe": 1.0},
            },
        })
        with self.assertRaises(ProviderError):
            StrandsDeciderAdapter(transport=t).decide(
                _case_input(), "choice", _ctx())

    def test_unsupported_primitive(self):
        with self.assertRaises(ValueError):
            StrandsDeciderAdapter().decide(_case_input(), "bogus", _ctx())


if __name__ == "__main__":
    unittest.main()
