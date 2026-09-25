"""Tests for the Kev adapter (self-hosted, Jev-compatible wire).

No network, no server, no API key: the transport is faked like in
test_jev_adapter.py. The key behavioral differences under test are the
model pinning (HF ids, short names accepted), the missing auth header,
and the actionable error when no local server is listening.
"""

import os
import unittest
import urllib.error
from unittest import mock

from peira.adapters.base import CallContext, ProviderError, validate_output
from peira.adapters import kev as kev_mod
from peira.adapters.jev import JevAdapter
from peira.adapters.kev import (
    KEV_MODEL_ID,
    KNOWN_MODELS,
    KevAdapter,
    LocalSystemOneAdapter,
)

_CTX_DEFAULTS = {
    "case_id": "k1",
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


def _transport_for(answers, usage=None, latency=12.5):
    seen = {}

    def fake(payload):
        seen["payload"] = payload
        return {
            "model": KEV_MODEL_ID,
            "answers": answers,
            "usage": usage or {"input_tokens": 100, "output_tokens": 20},
            "_latency_ms": latency,
        }

    fake.seen = seen
    return fake


class TestKevConstruction(unittest.TestCase):
    def test_no_api_key_needed(self):
        old = os.environ.pop("TYPESAFE_API_KEY", None)
        try:
            a = KevAdapter()
        finally:
            if old is not None:
                os.environ["TYPESAFE_API_KEY"] = old
        self.assertIsNone(a._api_key)

    def test_default_model_pinned(self):
        a = KevAdapter()
        self.assertEqual(a.model, KEV_MODEL_ID)
        self.assertEqual(KEV_MODEL_ID, "jaredpalmer/kev-4b")
        self.assertEqual(a.version, KEV_MODEL_ID)
        self.assertEqual(a.cache_namespace, f"kev:{KEV_MODEL_ID}")

    def test_short_names_resolve(self):
        self.assertEqual(KevAdapter(model="4b").model, "jaredpalmer/kev-4b")
        self.assertEqual(KevAdapter(model="8b").model, "jaredpalmer/kev-8b")
        self.assertEqual(KevAdapter(model="0.5b").cache_namespace,
                         "kev:jaredpalmer/kev-0.5b")
        # Full ids accepted verbatim.
        self.assertEqual(KevAdapter(model="jaredpalmer/kev-8b").model,
                         "jaredpalmer/kev-8b")

    def test_known_models_match_published_repos(self):
        # The seven pinned repos, verified live against the
        # jaredpalmer/kev HF collection on 2026-09-25.
        self.assertEqual(set(KNOWN_MODELS.values()),
                         {"jaredpalmer/kev-0.5b", "jaredpalmer/kev-0.6b",
                          "jaredpalmer/kev-0.8b", "jaredpalmer/kev-4b",
                          "jaredpalmer/kev-8b", "jaredpalmer/kev-9b",
                          "jaredpalmer/kev-27b"})

    def test_current_generation_resolution(self):
        # Default is the current Qwen3.5-based 4b.
        self.assertEqual(KevAdapter().model, "jaredpalmer/kev-4b")
        # The newest/biggest arm is the Qwen3.8-based 27b.
        self.assertEqual(KevAdapter(model="27b").model,
                         "jaredpalmer/kev-27b")
        self.assertEqual(KevAdapter(model="jaredpalmer/kev-27b").model,
                         "jaredpalmer/kev-27b")
        # Current-family short names resolve.
        self.assertEqual(KevAdapter(model="0.8b").model,
                         "jaredpalmer/kev-0.8b")
        self.assertEqual(KevAdapter(model="9b").model,
                         "jaredpalmer/kev-9b")

    def test_floating_and_unknown_models_rejected(self):
        for bad in ("kev-latest", "", "jaredpalmer/kev-99b",
                    "jaredpalmer/kev-qwen3.5-4b",
                    "Qwen/Qwen3-4B"):
            with self.assertRaises(ValueError, msg=bad):
                KevAdapter(model=bad)

    def test_default_api_url(self):
        a = KevAdapter()
        self.assertEqual(a.api_url,
                         "http://127.0.0.1:8008/v1/systemone")

    def test_custom_api_url(self):
        a = KevAdapter(api_url="http://gpu-box:9000/v1/systemone")
        self.assertEqual(a.api_url, "http://gpu-box:9000/v1/systemone")

    def test_is_jev_subclass_but_reuses_wire(self):
        self.assertIsInstance(KevAdapter(), JevAdapter)
        self.assertIsInstance(KevAdapter(), LocalSystemOneAdapter)
        self.assertEqual(KevAdapter.name, "kev")
        self.assertEqual(KevAdapter.supported_primitives,
                         frozenset({"choice", "score", "abstain"}))


class TestKevWire(unittest.TestCase):
    def test_choice_happy_path(self):
        t = _transport_for({
            "decision": {"choice": "approve",
                         "probabilities": {"deny": 0.2, "approve": 0.7,
                                           "other": 0.1},
                         "confidence": 0.7},
        })
        out = KevAdapter(transport=t).decide(_case_input(), "choice", _ctx())
        self.assertEqual(validate_output(out, "choice"), [])
        self.assertEqual(out.decision, "approve")
        self.assertAlmostEqual(out.confidence, 0.7)
        self.assertEqual(out.usage.model, KEV_MODEL_ID)

    def test_score_happy_path(self):
        t = _transport_for({
            "score": {"score": 3.2, "confidence": 0.8},
            "decision": {"choice": "deny", "confidence": 0.8},
        })
        out = KevAdapter(transport=t).decide(_case_input(), "score", _ctx())
        self.assertEqual(validate_output(out, "score"), [])
        self.assertAlmostEqual(out.score, 3.2 / 4)
        self.assertEqual(out.decision, "deny")

    def test_abstain_happy_path(self):
        t = _transport_for({"abstain": {"abstain": 0.8}})
        out = KevAdapter(transport=t).decide(_case_input(), "abstain", _ctx())
        self.assertEqual(validate_output(out, "abstain"), [])
        self.assertEqual(out.decision, "abstain")

    def test_request_carries_no_authorization(self):
        # The fake transport sees the payload, not the headers — so
        # exercise _http_transport with a stubbed urlopen and inspect
        # the Request object.
        seen = {}

        class FakeResp:
            status = 200
            headers = {}

            def read(self):
                return b'{"answers": {"decision": {"choice": "deny", "confidence": 0.9}}}'

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout=None):
            seen["req"] = req
            return FakeResp()

        a = KevAdapter()
        with mock.patch("urllib.request.urlopen", fake_urlopen):
            parsed = a._http_transport({"model": a.model})
        req = seen["req"]
        self.assertEqual(req.full_url, a.api_url)
        self.assertNotIn("Authorization", dict(req.header_items()))
        self.assertEqual(parsed["answers"]["decision"]["choice"], "deny")

    def test_payload_model_is_pinned_id(self):
        t = _transport_for({"decision": {"choice": "deny", "confidence": 0.9}})
        KevAdapter(transport=t).decide(_case_input(), "choice", _ctx())
        self.assertEqual(t.seen["payload"]["model"], KEV_MODEL_ID)

    def test_unsupported_primitive(self):
        with self.assertRaises(ValueError):
            KevAdapter().decide(_case_input(), "bogus", _ctx())


class TestKevErrors(unittest.TestCase):
    def test_connection_refused_is_terminal_and_actionable(self):
        # Full decide() path: the injected-transport seam bypasses the
        # HTTP layer, so the real _http_transport runs with urlopen
        # stubbed to refuse the connection.
        a = KevAdapter()
        with mock.patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError(
                ConnectionRefusedError(111, "Connection refused")),
        ):
            with self.assertRaises(ProviderError) as cm:
                a.decide(_case_input(), "choice", _ctx())
        err = cm.exception
        self.assertIsNone(err.status_code)  # terminal: the runner won't retry
        self.assertIn("kev.serve", str(err))
        self.assertIn("http://127.0.0.1:8008/v1/systemone", str(err))

    def test_real_transport_connection_refused(self):
        a = KevAdapter()
        with mock.patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("connection refused"),
        ):
            with self.assertRaises(ProviderError) as cm:
                a._http_transport({"model": a.model})
        self.assertIsNone(cm.exception.status_code)
        self.assertIn("kev.serve", str(cm.exception))

    def test_timeout_stays_transient(self):
        a = KevAdapter()
        with mock.patch("urllib.request.urlopen",
                        side_effect=TimeoutError("timed out")):
            with self.assertRaises(ProviderError) as cm:
                a._http_transport({"model": a.model})
        self.assertEqual(cm.exception.status_code, 408)

    def test_422_is_terminal(self):
        def boom(payload):
            raise ProviderError("kev server error 422", status_code=422)
        with self.assertRaises(ProviderError) as cm:
            KevAdapter(transport=boom).decide(_case_input(), "choice", _ctx())
        self.assertEqual(cm.exception.status_code, 422)

    def test_503_keeps_status_for_runner(self):
        def boom(payload):
            raise ProviderError("kev server error 503", status_code=503)
        with self.assertRaises(ProviderError) as cm:
            KevAdapter(transport=boom).decide(_case_input(), "choice", _ctx())
        self.assertEqual(cm.exception.status_code, 503)

    def test_missing_answers_is_terminal(self):
        t = _transport_for(None)
        with self.assertRaises(ProviderError):
            KevAdapter(transport=t).decide(_case_input(), "choice", _ctx())

    def test_unknown_option_is_terminal(self):
        t = _transport_for({"decision": {"choice": "maybe", "confidence": 0.5}})
        with self.assertRaises(ProviderError):
            KevAdapter(transport=t).decide(_case_input(), "choice", _ctx())

    def test_raise_for_status_mapping(self):
        a = KevAdapter.__new__(KevAdapter)
        a.name = "kev"
        for status in (401, 422, 429, 500, 503, 400):
            with self.assertRaises(ProviderError) as cm:
                a._raise_for_status(status, None, "detail")
            self.assertEqual(cm.exception.status_code, status)


if __name__ == "__main__":
    unittest.main()
