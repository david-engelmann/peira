"""Tests for the OpenAI omni-moderation adapter.

All transport is faked: no network, no API key, no access needed. The
fake transport receives the exact payload the adapter would POST and
returns a canned parsed response.

The fakes below are written against the documented OpenAI Moderation
API wire shape — ``model``/``input`` in requests, ``results`` with
``flagged``/``categories``/``category_scores`` in responses — not
against any earlier draft of this adapter.
"""

import unittest

from peira.adapters.base import ProviderError, validate_output
from peira.adapters.omni_moderation import (
    API_KEY_ENV,
    API_URL,
    CATEGORIES,
    MODEL_ID,
    OmniModerationAdapter,
)


def _case_input(**over):
    d = {"prompt": "Decision: approve or deny?",
         "options": ["approve", "deny"]}
    d.update(over)
    return d


def _ctx(**over):
    from peira.adapters.base import CallContext
    return CallContext(call_id=over.get("call_id", "call-test"))


def _scores(**over):
    d = {c: 0.0 for c in CATEGORIES}
    d.update(over)
    return d


def _response(flagged=False, latency=12.5, **score_over):
    seen = {}

    def fake(payload):
        seen["payload"] = payload
        return {
            "id": "modr-1",
            "model": "omni-moderation-2024-09-26",
            "results": [{
                "flagged": flagged,
                "categories": {c: False for c in CATEGORIES},
                "category_scores": _scores(**score_over),
            }],
            "_latency_ms": latency,
        }

    fake.seen = seen
    return fake


class TestOmniConstruction(unittest.TestCase):
    def test_missing_key_is_actionable(self):
        import os
        old = os.environ.pop(API_KEY_ENV, None)
        try:
            with self.assertRaises(ValueError) as cm:
                OmniModerationAdapter()
        finally:
            if old is not None:
                os.environ[API_KEY_ENV] = old
        self.assertIn(API_KEY_ENV, str(cm.exception))

    def test_explicit_key_ok(self):
        a = OmniModerationAdapter(api_key="k")
        self.assertEqual(a._api_key, "k")

    def test_env_vars_declared(self):
        self.assertEqual(OmniModerationAdapter._env_vars, (API_KEY_ENV,))

    def test_endpoint_pinned(self):
        self.assertEqual(API_URL, "https://api.openai.com/v1/moderations")
        a = OmniModerationAdapter(api_key="k")
        self.assertEqual(a.api_url, API_URL)

    def test_model_pinned(self):
        self.assertEqual(MODEL_ID, "omni-moderation-latest")
        self.assertEqual(OmniModerationAdapter.cache_namespace,
                         f"openai-moderation:{MODEL_ID}")

    def test_thirteen_categories(self):
        self.assertEqual(len(CATEGORIES), 13)
        self.assertIn("violence/graphic", CATEGORIES)

    def test_abstain_only(self):
        self.assertEqual(OmniModerationAdapter.supported_primitives,
                         frozenset({"abstain"}))

    def test_unsupported_primitive_rejected(self):
        a = OmniModerationAdapter(api_key="k")
        with self.assertRaises(ValueError):
            a.decide(_case_input(), "choice", _ctx())


class TestOmniDecide(unittest.TestCase):
    def test_flagged_maps_to_abstain(self):
        out = OmniModerationAdapter(
            api_key="k", transport=_response(True)).decide(
            _case_input(), "abstain", _ctx())
        self.assertEqual(validate_output(out, "abstain"), [])
        self.assertEqual(out.decision, "abstain")
        self.assertFalse(out.abstained)

    def test_unflagged_maps_to_other(self):
        out = OmniModerationAdapter(
            api_key="k", transport=_response(False)).decide(
            _case_input(), "abstain", _ctx())
        self.assertEqual(validate_output(out, "abstain"), [])
        self.assertEqual(out.decision, "other")
        self.assertFalse(out.abstained)

    def test_p_malicious_is_max_category_score(self):
        out = OmniModerationAdapter(
            api_key="k",
            transport=_response(True, harassment=0.2, violence=0.87),
        ).decide(_case_input(), "abstain", _ctx())
        self.assertAlmostEqual(
            out.transcript["scores"]["p_malicious"], 0.87)
        self.assertEqual(out.decision, "abstain")

    def test_flagged_with_no_scores_trusts_flag(self):
        # Breakdown absent of signal: the boolean is authoritative.
        out = OmniModerationAdapter(
            api_key="k", transport=_response(True)).decide(
            _case_input(), "abstain", _ctx())
        self.assertEqual(out.decision, "abstain")
        self.assertGreaterEqual(
            out.transcript["scores"]["p_malicious"], 0.5)

    def test_unflagged_high_score_is_clamped_benign(self):
        # The boolean is authoritative for the decision even when a
        # category scores high.
        out = OmniModerationAdapter(
            api_key="k",
            transport=_response(False, violence=0.9),
        ).decide(_case_input(), "abstain", _ctx())
        self.assertEqual(out.decision, "other")
        self.assertLess(out.transcript["scores"]["p_malicious"], 0.5)

    def test_served_model_recorded_in_transcript(self):
        out = OmniModerationAdapter(
            api_key="k", transport=_response(False)).decide(
            _case_input(), "abstain", _ctx())
        self.assertEqual(out.transcript["served_model"],
                         "omni-moderation-2024-09-26")
        self.assertEqual(out.transcript["model"], f"openai:{MODEL_ID}")

    def test_payload_shape(self):
        t = _response(False)
        OmniModerationAdapter(api_key="k", transport=t).decide(
            _case_input(prompt="hello"), "abstain", _ctx())
        self.assertEqual(t.seen["payload"],
                         {"model": MODEL_ID, "input": "hello"})

    def test_empty_input_never_calls_api(self):
        called = []

        def fake(payload):
            called.append(payload)
            raise AssertionError("transport must not be called")

        out = OmniModerationAdapter(api_key="k", transport=fake).decide(
            _case_input(prompt="   "), "abstain", _ctx())
        self.assertEqual(called, [])
        self.assertEqual(out.decision, "other")
        self.assertEqual(out.confidence, 1.0)
        # A local short-circuit must never bill the priced model id.
        self.assertEqual(out.usage.model, "openai-moderation:local")

    def test_missing_results_is_provider_error(self):
        def fake(payload):
            return {"id": "modr-1", "model": "m", "_latency_ms": 1.0}

        with self.assertRaises(ProviderError):
            OmniModerationAdapter(api_key="k", transport=fake).decide(
                _case_input(), "abstain", _ctx())

    def test_non_boolean_flagged_is_provider_error(self):
        def fake(payload):
            return {"results": [{"flagged": "yes",
                                 "category_scores": _scores()}],
                    "_latency_ms": 1.0}

        with self.assertRaises(ProviderError):
            OmniModerationAdapter(api_key="k", transport=fake).decide(
                _case_input(), "abstain", _ctx())

    def test_confidence_is_boundary_distance(self):
        out = OmniModerationAdapter(
            api_key="k",
            transport=_response(True, violence=0.87),
        ).decide(_case_input(), "abstain", _ctx())
        p = out.transcript["scores"]["p_malicious"]
        self.assertAlmostEqual(out.confidence, abs(2 * p - 1))
