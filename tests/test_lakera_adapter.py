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

    def test_empty_prompt_skips_api_call(self):
        # Empty/whitespace-only input is benign without a paid API
        # call, matching the HF guardrail adapters.
        calls = []

        def fake(payload):
            calls.append(payload)
            return _flagged_response(True)

        for prompt in ("", "   ", "\n\t "):
            out = LakeraAdapter(api_key="k", transport=fake).decide(
                _case_input(prompt=prompt), "abstain", _ctx())
            self.assertEqual(validate_output(out, "abstain"), [])
            self.assertEqual(out.decision, "other")
            self.assertAlmostEqual(out.confidence, 1.0)
            self.assertEqual(out.usage.model, f"lakera:{API_VERSION}")
        self.assertEqual(calls, [])


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


class TestLakeraHttpTransport(unittest.TestCase):
    """Exercise the real stdlib transport with a mocked urlopen.

    The P1 gap: every other test injects a fake transport, so the
    urllib request-building, header, status-classification, and
    body-parsing code had zero coverage.
    """

    def _adapter(self):
        # Bypass __init__'s transport default only to reach the real
        # _http_transport; urlopen itself is mocked below.
        return LakeraAdapter(api_key="k")

    def _mock_urlopen(self, *, status=200, body=b'{"flagged": false}',
                      headers=None, error=None):
        import urllib.request
        from unittest import mock

        class FakeHeaders(dict):
            def get(self, k, d=None):
                return super().get(k, d)

        class FakeResp:
            def __init__(self):
                self.status = status
                self.headers = FakeHeaders(headers or {})

            def read(self):
                return body

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        if error is not None:
            return mock.patch.object(urllib.request, "urlopen",
                                     side_effect=error)
        return mock.patch.object(urllib.request, "urlopen",
                                 return_value=FakeResp())

    def test_request_shape_and_headers(self):
        import urllib.request
        from unittest import mock
        seen = {}

        class FakeResp:
            status = 200

            def __init__(self):
                self.headers = {}

            def read(self):
                return b'{"flagged": false}'

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout=None):
            seen["req"] = req
            seen["timeout"] = timeout
            return FakeResp()

        a = self._adapter()
        with mock.patch.object(urllib.request, "urlopen", fake_urlopen):
            out = a._http_transport({"messages": [], "breakdown": True})
        req = seen["req"]
        self.assertEqual(req.full_url, API_URL)
        self.assertEqual(req.get_header("Content-type"), "application/json")
        self.assertEqual(req.get_header("Authorization"), "Bearer k")
        self.assertEqual(seen["timeout"], 60.0)
        import json
        self.assertEqual(json.loads(req.data),
                         {"messages": [], "breakdown": True})
        self.assertFalse(out["flagged"])
        self.assertIn("_latency_ms", out)

    def test_401_is_terminal(self):
        import urllib.error
        err = urllib.error.HTTPError(API_URL, 401, "Unauthorized", {}, None)
        with self._mock_urlopen(error=err):
            with self.assertRaises(ProviderError) as cm:
                self._adapter()._http_transport({})
        self.assertEqual(cm.exception.status_code, 401)
        self.assertIsNone(cm.exception.retry_after)

    def test_422_is_terminal(self):
        import urllib.error
        err = urllib.error.HTTPError(API_URL, 422, "Unprocessable", {}, None)
        with self._mock_urlopen(error=err):
            with self.assertRaises(ProviderError) as cm:
                self._adapter()._http_transport({})
        self.assertEqual(cm.exception.status_code, 422)

    def test_429_is_transient_with_retry_after(self):
        import urllib.error
        import io
        err = urllib.error.HTTPError(
            API_URL, 429, "Too Many Requests",
            {"Retry-After": "30"}, io.BytesIO(b"slow down"))
        with self._mock_urlopen(error=err):
            with self.assertRaises(ProviderError) as cm:
                self._adapter()._http_transport({})
        self.assertEqual(cm.exception.status_code, 429)
        self.assertEqual(cm.exception.retry_after, 30.0)

    def test_500_is_transient(self):
        import urllib.error
        err = urllib.error.HTTPError(API_URL, 500, "Server Error", {}, None)
        with self._mock_urlopen(error=err):
            with self.assertRaises(ProviderError) as cm:
                self._adapter()._http_transport({})
        self.assertEqual(cm.exception.status_code, 500)

    def test_urlerror_is_transient_408(self):
        import urllib.error
        err = urllib.error.URLError("connection refused")
        with self._mock_urlopen(error=err):
            with self.assertRaises(ProviderError) as cm:
                self._adapter()._http_transport({})
        self.assertEqual(cm.exception.status_code, 408)

    def test_non_json_response_raises(self):
        with self._mock_urlopen(body=b"not json"):
            with self.assertRaises(ProviderError) as cm:
                self._adapter()._http_transport({})
        self.assertIn("non-JSON", str(cm.exception))

    def test_non_object_json_raises(self):
        with self._mock_urlopen(body=b"[1, 2, 3]"):
            with self.assertRaises(ProviderError):
                self._adapter()._http_transport({})

    def test_custom_timeout_propagates(self):
        import urllib.request
        from unittest import mock
        seen = {}

        class FakeResp:
            status = 200

            def __init__(self):
                self.headers = {}

            def read(self):
                return b'{"flagged": true}'

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout=None):
            seen["timeout"] = timeout
            return FakeResp()

        a = LakeraAdapter(api_key="k", timeout_s=5.0)
        with mock.patch.object(urllib.request, "urlopen", fake_urlopen):
            a._http_transport({})
        self.assertEqual(seen["timeout"], 5.0)


if __name__ == "__main__":
    unittest.main()
