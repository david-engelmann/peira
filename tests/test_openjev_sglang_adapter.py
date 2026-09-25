"""Tests for the openjev-sglang adapter.

No network, no SGLang deployment: the transport is faked like in
test_jev_adapter.py. Under test: the pinned Qwen3.6-35B-A3B model id,
the configurable endpoint, and the inherited Jev-compatible wire
behavior.
"""

import os
import unittest
import urllib.error
from unittest import mock

from peira.adapters.base import CallContext, ProviderError, validate_output
from peira.adapters.jev import JevAdapter
from peira.adapters.kev import LocalSystemOneAdapter
from peira.adapters.openjev_sglang import MODEL_ID, OpenJevSglangAdapter

_CTX_DEFAULTS = {
    "case_id": "o1",
    "expected_decision": "deny",
    "target_decision": "approve",
    "attacked": True,
}


def _case_input(**over):
    d = {"prompt": "Decision: approve or deny?"}
    for k, v in over.items():
        if k not in _CTX_DEFAULTS:
            d[k] = v
    return d


def _ctx(**over):
    vals = dict(_CTX_DEFAULTS)
    vals.update(over)
    return CallContext(
        case_id=vals["case_id"],
        arm="attacked" if vals["attacked"] else "benign",
        expected_decision=vals["expected_decision"],
        target_decision=vals["target_decision"],
    )


def _transport_for(answers, latency=12.5):
    seen = {}

    def fake(payload):
        seen["payload"] = payload
        return {
            "model": MODEL_ID,
            "answers": answers,
            "_latency_ms": latency,
        }

    fake.seen = seen
    return fake


class TestOpenJevSglangConstruction(unittest.TestCase):
    def test_no_api_key_needed(self):
        old = os.environ.pop("TYPESAFE_API_KEY", None)
        try:
            a = OpenJevSglangAdapter()
        finally:
            if old is not None:
                os.environ["TYPESAFE_API_KEY"] = old
        self.assertIsNone(a._api_key)

    def test_model_pinned(self):
        self.assertEqual(MODEL_ID, "Qwen/Qwen3.6-35B-A3B")
        a = OpenJevSglangAdapter()
        self.assertEqual(a.model, MODEL_ID)
        self.assertEqual(a.version, MODEL_ID)
        self.assertEqual(a.cache_namespace, f"openjev-sglang:{MODEL_ID}")

    def test_other_models_rejected(self):
        for bad in ("jev-latest", "", "Qwen/Qwen3.5-4B",
                    "jaredpalmer/kev-4b", "Qwen/Qwen3.6-35B-A3B-GGUF"):
            with self.assertRaises(ValueError, msg=bad):
                OpenJevSglangAdapter(model=bad)
        # The pinned id itself is accepted explicitly.
        self.assertEqual(OpenJevSglangAdapter(model=MODEL_ID).model, MODEL_ID)

    def test_default_api_url(self):
        a = OpenJevSglangAdapter()
        self.assertEqual(a.api_url, "http://localhost:8000/v1/systemone")

    def test_custom_api_url(self):
        a = OpenJevSglangAdapter(api_url="http://gpu:8100/v1/systemone")
        self.assertEqual(a.api_url, "http://gpu:8100/v1/systemone")

    def test_reuses_local_wire_plumbing(self):
        a = OpenJevSglangAdapter()
        self.assertIsInstance(a, JevAdapter)
        self.assertIsInstance(a, LocalSystemOneAdapter)
        self.assertEqual(OpenJevSglangAdapter.name, "openjev-sglang")
        self.assertEqual(OpenJevSglangAdapter.supported_primitives,
                         frozenset({"choice", "score", "abstain"}))


class TestOpenJevSglangWire(unittest.TestCase):
    def test_choice_happy_path(self):
        t = _transport_for({
            "decision": {"choice": "deny", "confidence": 0.9},
        })
        out = OpenJevSglangAdapter(transport=t).decide(
            _case_input(), "choice", _ctx())
        self.assertEqual(validate_output(out, "choice"), [])
        self.assertEqual(out.decision, "deny")
        self.assertAlmostEqual(out.confidence, 0.9)
        self.assertEqual(out.usage.model, MODEL_ID)

    def test_payload_model_is_pinned_id(self):
        t = _transport_for({"decision": {"choice": "deny", "confidence": 0.9}})
        OpenJevSglangAdapter(transport=t).decide(_case_input(), "choice",
                                                 _ctx())
        self.assertEqual(t.seen["payload"]["model"], MODEL_ID)

    def test_score_happy_path(self):
        t = _transport_for({
            "score": {"score": 2.0, "confidence": 0.6},
            "decision": {"choice": "approve", "confidence": 0.6},
        })
        out = OpenJevSglangAdapter(transport=t).decide(
            _case_input(), "score", _ctx())
        self.assertEqual(validate_output(out, "score"), [])
        self.assertAlmostEqual(out.score, 2.0 / 4)
        self.assertEqual(out.decision, "approve")

    def test_abstain_yes_means_abstain(self):
        t = _transport_for({"abstain": {"abstain": 0.75}})
        out = OpenJevSglangAdapter(transport=t).decide(
            _case_input(), "abstain", _ctx())
        self.assertEqual(validate_output(out, "abstain"), [])
        self.assertEqual(out.decision, "abstain")

    def test_no_authorization_header(self):
        seen = {}

        class FakeResp:
            status = 200
            headers = {}

            def read(self):
                return (b'{"answers": {"decision": {"choice": "deny", '
                        b'"confidence": 0.9}}}')

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout=None):
            seen["req"] = req
            return FakeResp()

        a = OpenJevSglangAdapter()
        with mock.patch("urllib.request.urlopen", fake_urlopen):
            a._http_transport({"model": a.model})
        self.assertNotIn("Authorization",
                         dict(seen["req"].header_items()))

    def test_unsupported_primitive(self):
        with self.assertRaises(ValueError):
            OpenJevSglangAdapter().decide(_case_input(), "bogus", _ctx())


class TestOpenJevSglangErrors(unittest.TestCase):
    def test_connection_refused_is_terminal_and_actionable(self):
        a = OpenJevSglangAdapter()
        with mock.patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("connection refused"),
        ):
            with self.assertRaises(ProviderError) as cm:
                a._http_transport({"model": a.model})
        err = cm.exception
        self.assertIsNone(err.status_code)
        self.assertIn("openjev-sglang", str(err))
        self.assertIn("github.com/ekzhang/openjev-sglang", str(err))

    def test_missing_answers_is_terminal(self):
        t = _transport_for(None)
        with self.assertRaises(ProviderError):
            OpenJevSglangAdapter(transport=t).decide(
                _case_input(), "choice", _ctx())

    def test_unknown_option_is_terminal(self):
        t = _transport_for({"decision": {"choice": "maybe", "confidence": 0.5}})
        with self.assertRaises(ProviderError):
            OpenJevSglangAdapter(transport=t).decide(
                _case_input(), "choice", _ctx())

    def test_non_numeric_score_is_terminal(self):
        t = _transport_for({
            "score": {"score": "high"},
            "decision": {"choice": "deny", "confidence": 0.9},
        })
        with self.assertRaises(ProviderError):
            OpenJevSglangAdapter(transport=t).decide(
                _case_input(), "score", _ctx())


if __name__ == "__main__":
    unittest.main()
