"""Tests for the Lakera Guard adapter.

All transport is faked: no network, no API key, no access needed. The
fake transport receives the exact payload the adapter would POST and
returns a canned parsed response.

The fakes below are written against the documented Lakera Guard v2 wire
shape — ``messages``/``breakdown`` in requests, ``flagged``/``breakdown``
in responses (docs.lakera.ai/docs/api/guard) — not against any earlier
draft of this adapter.
"""

import unittest

from peira.adapters.base import ProviderError, validate_output
from peira.adapters import lakera as lakera_mod
from peira.adapters.lakera import (
    API_KEY_ENV,
    API_URL,
    API_VERSION,
    LakeraAdapter,
    _level_to_float,
)


def _case_input(**over):
    d = {"prompt": "Decision: approve or deny?",
         "options": ["approve", "deny"]}
    d.update(over)
    return d


def _ctx(**over):
    from peira.adapters.base import CallContext
    return CallContext(call_id=over.get("call_id", "call-test"))


def _transport_for(response, latency=12.5):
    seen = {}

    def fake(payload):
        seen["payload"] = payload
        return dict(response, _latency_ms=latency)

    fake.seen = seen
    return fake


def _flagged_response(flagged=True, breakdown=None, uuid="uuid-1"):
    resp = {
        "flagged": flagged,
        "metadata": {"request_uuid": uuid},
    }
    if breakdown is not None:
        resp["breakdown"] = breakdown
    return resp


def _detector(detector_type, detected, result):
    return {"detector_type": detector_type, "detected": detected,
            "result": result}


class TestLakeraConstruction(unittest.TestCase):
    def test_missing_key_is_actionable(self):
        import os
        old = os.environ.pop(API_KEY_ENV, None)
        try:
            with self.assertRaises(ValueError) as cm:
                LakeraAdapter()
        finally:
            if old is not None:
                os.environ[API_KEY_ENV] = old
        self.assertIn(API_KEY_ENV, str(cm.exception))

    def test_explicit_key_ok(self):
        a = LakeraAdapter(api_key="k")
        self.assertEqual(a._api_key, "k")

    def test_env_vars_declared(self):
        self.assertEqual(LakeraAdapter._env_vars, (API_KEY_ENV,))

    def test_endpoint_pinned(self):
        self.assertEqual(API_URL, "https://api.lakera.ai/v2/guard")
        a = LakeraAdapter(api_key="k")
        self.assertEqual(a.api_url, API_URL)

    def test_version_pinned(self):
        self.assertEqual(API_VERSION, "v2")
        self.assertEqual(LakeraAdapter.version, "v2")

    def test_abstain_only(self):
        self.assertEqual(LakeraAdapter.supported_primitives,
                         frozenset({"abstain"}))

    def test_cache_namespace_set(self):
        a = LakeraAdapter(api_key="k")
        self.assertEqual(a.cache_namespace, f"lakera:{API_VERSION}")

    def test_unsupported_primitive_rejected(self):
        a = LakeraAdapter(api_key="k")
        with self.assertRaises(ValueError):
            a.decide(_case_input(), "choice", _ctx())


class TestLevelMapping(unittest.TestCase):
    def test_l1_is_one(self):
        self.assertEqual(_level_to_float("l1_confident"), 1.0)

    def test_l5_is_zero(self):
        self.assertEqual(_level_to_float("l5_unlikely"), 0.0)

    def test_linear_interpolation(self):
        self.assertAlmostEqual(_level_to_float("l2_high"), 0.75)
        self.assertAlmostEqual(_level_to_float("l3_moderate"), 0.5)
        self.assertAlmostEqual(_level_to_float("l4_low"), 0.25)

    def test_no_level_is_zero(self):
        self.assertEqual(_level_to_float("no_level"), 0.0)

    def test_garbage_is_zero(self):
        self.assertEqual(_level_to_float("bogus"), 0.0)
        self.assertEqual(_level_to_float(None), 0.0)
        self.assertEqual(_level_to_float(3), 0.0)

    def test_case_insensitive(self):
        self.assertEqual(_level_to_float("L1_CONFIDENT"), 1.0)


class TestLakeraDecide(unittest.TestCase):
    def test_flagged_maps_to_abstain(self):
        t = _transport_for(_flagged_response(True))
        out = LakeraAdapter(api_key="k", transport=t).decide(
            _case_input(), "abstain", _ctx())
        self.assertEqual(validate_output(out, "abstain"), [])
        self.assertEqual(out.decision, "abstain")
        self.assertFalse(out.abstained)

    def test_unflagged_maps_to_other(self):
        t = _transport_for(_flagged_response(False))
        out = LakeraAdapter(api_key="k", transport=t).decide(
            _case_input(), "abstain", _ctx())
        self.assertEqual(validate_output(out, "abstain"), [])
        self.assertEqual(out.decision, "other")
        self.assertFalse(out.abstained)

    def test_request_shape(self):
        t = _transport_for(_flagged_response(False))
        LakeraAdapter(api_key="k", transport=t).decide(
            _case_input(prompt="hello"), "abstain", _ctx())
        payload = t.seen["payload"]
        self.assertEqual(payload["messages"],
                         [{"role": "user", "content": "hello"}])
        self.assertTrue(payload["breakdown"])

    def test_breakdown_confidence_refines_score(self):
        # Flagged with an l1 detector: p_malicious is 1.0, confidence 1.0.
        t = _transport_for(_flagged_response(True, breakdown=[
            _detector("prompt_attack", True, "l1_confident"),
            _detector("jailbreak", False, "no_level"),
        ]))
        out = LakeraAdapter(api_key="k", transport=t).decide(
            _case_input(), "abstain", _ctx())
        self.assertEqual(out.decision, "abstain")
        self.assertAlmostEqual(
            out.transcript["scores"]["p_malicious"], 1.0)
        self.assertAlmostEqual(out.confidence, 1.0)

    def test_highest_detector_wins(self):
        t = _transport_for(_flagged_response(True, breakdown=[
            _detector("prompt_attack", True, "l3_moderate"),
            _detector("jailbreak", True, "l1_confident"),
        ]))
        out = LakeraAdapter(api_key="k", transport=t).decide(
            _case_input(), "abstain", _ctx())
        self.assertAlmostEqual(
            out.transcript["scores"]["p_malicious"], 1.0)

    def test_undetected_entries_contribute_nothing(self):
        # A detected=false entry with a scary level must not inflate
        # the score.
        t = _transport_for(_flagged_response(False, breakdown=[
            _detector("prompt_attack", False, "l1_confident"),
        ]))
        out = LakeraAdapter(api_key="k", transport=t).decide(
            _case_input(), "abstain", _ctx())
        self.assertEqual(out.decision, "other")
        self.assertAlmostEqual(
            out.transcript["scores"]["p_malicious"], 0.0)

    def test_flagged_without_breakdown_trusts_flag(self):
        t = _transport_for(_flagged_response(True, breakdown=[]))
        out = LakeraAdapter(api_key="k", transport=t).decide(
            _case_input(), "abstain", _ctx())
        self.assertEqual(out.decision, "abstain")

    def test_missing_flagged_raises_provider_error(self):
        t = _transport_for({"metadata": {}})
        with self.assertRaises(ProviderError):
            LakeraAdapter(api_key="k", transport=t).decide(
                _case_input(), "abstain", _ctx())

    def test_nonboolean_flagged_raises_provider_error(self):
        t = _transport_for({"flagged": "yes"})
        with self.assertRaises(ProviderError):
            LakeraAdapter(api_key="k", transport=t).decide(
                _case_input(), "abstain", _ctx())

    def test_usage_model_pinned(self):
        t = _transport_for(_flagged_response(False))
        out = LakeraAdapter(api_key="k", transport=t).decide(
            _case_input(), "abstain", _ctx())
        self.assertEqual(out.usage.model, f"lakera:{API_VERSION}")
        self.assertEqual(out.usage.cost_usd, 0.0)

    def test_transcript_redacts_prompt(self):
        t = _transport_for(_flagged_response(False))
        out = LakeraAdapter(api_key="k", transport=t).decide(
            _case_input(prompt="sensitive attack text"), "abstain", _ctx())
        req = out.transcript["request"]
        self.assertNotIn("sensitive attack text", str(req))


class TestLakeraErrors(unittest.TestCase):
    def _adapter_with_status(self, status):
        # The fake mimics the real transport's contract: HTTP failures
        # surface as ProviderError, never as raw urllib exceptions.
        def fake(payload):
            raise ProviderError(f"lakera API error {status}",
                                status_code=status)

        return LakeraAdapter(api_key="k", transport=fake)

    def test_401_is_terminal(self):
        a = self._adapter_with_status(401)
        with self.assertRaises(ProviderError) as cm:
            a.decide(_case_input(), "abstain", _ctx())
        self.assertEqual(cm.exception.status_code, 401)

    def test_429_is_transient(self):
        a = self._adapter_with_status(429)
        with self.assertRaises(ProviderError) as cm:
            a.decide(_case_input(), "abstain", _ctx())
        self.assertEqual(cm.exception.status_code, 429)

    def test_500_is_transient(self):
        a = self._adapter_with_status(500)
        with self.assertRaises(ProviderError) as cm:
            a.decide(_case_input(), "abstain", _ctx())
        self.assertEqual(cm.exception.status_code, 500)

    def test_422_is_terminal(self):
        a = self._adapter_with_status(422)
        with self.assertRaises(ProviderError) as cm:
            a.decide(_case_input(), "abstain", _ctx())
        self.assertEqual(cm.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
