"""Tests for the Von adapter.

No network, no Von server: the transport is faked like in
test_openjev_sglang_adapter.py. Under test: the pinned von-1.3.0
model id, the configurable endpoint, the optional Bearer auth, and
the inherited Jev-compatible wire behavior.
"""

import os
import unittest
import urllib.error
from unittest import mock

from peira.adapters.base import CallContext, ProviderError, validate_output
from peira.adapters.jev import JevAdapter
from peira.adapters.kev import LocalSystemOneAdapter
from peira.adapters.von import MODEL_ID, VonAdapter

# B2 (D-25 amended): the adapter-visible context is an opaque per-call
# handle, with no case id, no arm, no gold labels. The candidate decision
# labels come from the case input's explicit "options" list.
def _case_input(**over):
    d = {"prompt": "Decision: approve or deny?",
         "options": ["approve", "deny"]}
    d.update(over)
    return d


def _ctx(**over):
    return CallContext(call_id=over.get("call_id", "call-test"))


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


class TestVonConstruction(unittest.TestCase):
    def test_model_pinned(self):
        self.assertEqual(MODEL_ID, "von-1.3.0")
        a = VonAdapter()
        self.assertEqual(a.model, MODEL_ID)
        self.assertEqual(a.version, MODEL_ID)
        self.assertEqual(a.cache_namespace, f"von:{MODEL_ID}")

    def test_other_models_rejected(self):
        for bad in ("von-latest", "", "wfzyx/von", "von-1.0.0",
                    "von-1.1.0", "von-1.2.0", "jaredpalmer/kev-0.8b"):
            with self.assertRaises(ValueError, msg=bad):
                VonAdapter(model=bad)
        # The pinned id itself is accepted explicitly.
        self.assertEqual(VonAdapter(model=MODEL_ID).model, MODEL_ID)

    def test_pin_error_names_the_pin(self):
        with self.assertRaises(ValueError) as cm:
            VonAdapter(model="von-latest")
        self.assertIn("von adapter pins model 'von-1.3.0'", str(cm.exception))

    def test_default_api_url(self):
        a = VonAdapter()
        self.assertEqual(a.api_url, "http://127.0.0.1:8000/v1/systemone")

    def test_custom_api_url(self):
        a = VonAdapter(api_url="http://gpu:8100/v1/systemone")
        self.assertEqual(a.api_url, "http://gpu:8100/v1/systemone")

    def test_reuses_local_wire_plumbing(self):
        a = VonAdapter()
        self.assertIsInstance(a, JevAdapter)
        self.assertIsInstance(a, LocalSystemOneAdapter)
        self.assertEqual(VonAdapter.name, "von")
        self.assertEqual(VonAdapter.supported_primitives,
                         frozenset({"choice", "score", "abstain"}))


class TestVonWire(unittest.TestCase):
    def test_choice_happy_path(self):
        t = _transport_for({
            "decision": {"choice": "deny", "confidence": 0.9},
        })
        out = VonAdapter(transport=t).decide(
            _case_input(), "choice", _ctx())
        self.assertEqual(validate_output(out, "choice"), [])
        self.assertEqual(out.decision, "deny")
        self.assertAlmostEqual(out.confidence, 0.9)
        self.assertEqual(out.usage.model, MODEL_ID)

    def test_payload_model_is_pinned_id(self):
        t = _transport_for({"decision": {"choice": "deny", "confidence": 0.9}})
        VonAdapter(transport=t).decide(_case_input(), "choice", _ctx())
        self.assertEqual(t.seen["payload"]["model"], MODEL_ID)

    def test_score_happy_path(self):
        t = _transport_for({
            "score": {"score": 2.0, "confidence": 0.6},
            "decision": {"choice": "approve", "confidence": 0.6},
        })
        out = VonAdapter(transport=t).decide(
            _case_input(), "score", _ctx())
        self.assertEqual(validate_output(out, "score"), [])
        self.assertAlmostEqual(out.score, 2.0 / 4)
        self.assertEqual(out.decision, "approve")

    def test_abstain_yes_means_abstain(self):
        t = _transport_for({"abstain": {"abstain": 0.75}})
        out = VonAdapter(transport=t).decide(
            _case_input(), "abstain", _ctx())
        self.assertEqual(validate_output(out, "abstain"), [])
        self.assertEqual(out.decision, "abstain")

    def test_abstain_no_means_placeholder_decision(self):
        t = _transport_for({"abstain": {"noul": 0.1}})
        out = VonAdapter(transport=t).decide(
            _case_input(), "abstain", _ctx())
        self.assertEqual(validate_output(out, "abstain"), [])
        self.assertEqual(out.decision, "other")
        self.assertAlmostEqual(out.confidence, 0.8)

    def test_unsupported_primitive(self):
        with self.assertRaises(ValueError):
            VonAdapter().decide(_case_input(), "bogus", _ctx())


class TestVonAuth(unittest.TestCase):
    def test_no_auth_by_default(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("VON_API_KEY", None)
            a = VonAdapter(transport=lambda p: {})
            self.assertEqual(a._auth_headers(), {})

    def test_explicit_api_key_sends_bearer_header(self):
        a = VonAdapter(transport=lambda p: {}, api_key="secret-key-123")
        self.assertEqual(a._auth_headers(),
                         {"Authorization": "Bearer secret-key-123"})

    def test_env_var_api_key_used_when_no_explicit(self):
        with mock.patch.dict(os.environ, {"VON_API_KEY": "env-key-456"}):
            a = VonAdapter(transport=lambda p: {})
            self.assertEqual(a._auth_headers(),
                             {"Authorization": "Bearer env-key-456"})

    def test_explicit_api_key_wins_over_env(self):
        with mock.patch.dict(os.environ, {"VON_API_KEY": "env-key-456"}):
            a = VonAdapter(transport=lambda p: {}, api_key="explicit-key")
            self.assertEqual(a._auth_headers(),
                             {"Authorization": "Bearer explicit-key"})

    def test_no_authorization_header_on_the_wire_by_default(self):
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

        a = VonAdapter()
        with mock.patch("urllib.request.urlopen", fake_urlopen):
            a._http_transport({"model": a.model})
        self.assertNotIn("Authorization",
                         dict(seen["req"].header_items()))


class TestVonErrors(unittest.TestCase):
    def test_connection_refused_is_terminal_and_actionable(self):
        a = VonAdapter()
        with mock.patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("connection refused"),
        ):
            with self.assertRaises(ProviderError) as cm:
                a._http_transport({"model": a.model})
        err = cm.exception
        self.assertIsNone(err.status_code)
        self.assertIn("von", str(err))
        self.assertIn("von serve", str(err))
        self.assertIn("pip install von-sdk", str(err))

    def test_response_model_mismatch_is_terminal(self):
        # The server stamps every response with the model it served.
        # A stamp naming a different checkpoint must fail the call:
        # recording those answers under the pin would mislabel the run.
        def bad_transport(payload):
            return {"model": "von-1.4.0",
                    "answers": {"decision": {"choice": "deny",
                                             "confidence": 0.9}}}

        with self.assertRaises(ProviderError) as cm:
            VonAdapter(transport=bad_transport).decide(
                _case_input(), "choice", _ctx())
        self.assertIn("von-1.4.0", str(cm.exception))
        self.assertIn("von-1.3.0", str(cm.exception))

    def test_response_without_model_stamp_is_terminal(self):
        # The wire type always carries the stamp, so a response
        # without one is not a Von server response; accepting its
        # answers would record an unverifiable server under the pin.
        def bare_transport(payload):
            return {"answers": {"decision": {"choice": "deny",
                                             "confidence": 0.9}}}

        with self.assertRaises(ProviderError) as cm:
            VonAdapter(transport=bare_transport).decide(
                _case_input(), "choice", _ctx())
        self.assertIn("no model stamp", str(cm.exception))

    def test_raise_for_status_error_strings(self):
        # Pins the emitted strings byte-for-byte, so drift between the
        # shared wire code and this adapter's docs is caught here. The
        # separator in the emitted strings is a U+2014 em dash from
        # the shared LocalSystemOneAdapter code; docs/Troubleshooting.md
        # quotes the same strings in the family's semicolon form
        # because the docs gate forbids U+2014 in Markdown.
        a = VonAdapter(transport=lambda p: {})
        with self.assertRaises(ProviderError) as cm:
            a._raise_for_status(401, None, "detail")
        self.assertEqual(
            str(cm.exception),
            "von server error 401: detail \u2014 the server rejected "
            "the request as unauthorized; if this deployment was "
            "started with VON_API_KEY set, pass the same key here "
            "(api_key= or the VON_API_KEY environment variable).")
        self.assertEqual(cm.exception.status_code, 401)
        with self.assertRaises(ProviderError) as cm:
            a._raise_for_status(422, None, "detail")
        self.assertEqual(
            str(cm.exception),
            "von server error 422: detail \u2014 the request was "
            "rejected; this is an adapter bug, not a retryable "
            "failure.")
        self.assertEqual(cm.exception.status_code, 422)

    def test_missing_answers_is_terminal(self):
        t = _transport_for(None)
        with self.assertRaises(ProviderError):
            VonAdapter(transport=t).decide(
                _case_input(), "choice", _ctx())

    def test_unknown_option_is_terminal(self):
        t = _transport_for({"decision": {"choice": "maybe", "confidence": 0.5}})
        with self.assertRaises(ProviderError):
            VonAdapter(transport=t).decide(
                _case_input(), "choice", _ctx())

    def test_non_numeric_score_is_terminal(self):
        t = _transport_for({
            "score": {"score": "high"},
            "decision": {"choice": "deny", "confidence": 0.9},
        })
        with self.assertRaises(ProviderError):
            VonAdapter(transport=t).decide(
                _case_input(), "score", _ctx())


if __name__ == "__main__":
    unittest.main()
