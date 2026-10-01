"""Tests for the Azure AI Content Safety Prompt Shields adapter.

All transport is faked: no network, no Azure resource, no API key
needed. The fake transport receives the exact payload the adapter
would POST and returns a canned parsed response.

The fakes below are written against the documented Content Safety
``text:shieldPrompt`` wire shape — ``{"userPrompt": ...,
"documents": []}`` in requests,
``{"userPromptAnalysis": {"attackDetected": bool}}`` in responses —
not against any earlier draft of this adapter.
"""

import os
import unittest

from peira.adapters.base import ProviderError, validate_output
from peira.adapters.azure_prompt_shields import (
    API_VERSION,
    ENDPOINT_ENV,
    KEY_ENV,
    AzurePromptShieldsAdapter,
    _api_url,
)


def _case_input(**over):
    d = {"prompt": "Decision: approve or deny?",
         "options": ["approve", "deny"]}
    d.update(over)
    return d


def _ctx(**over):
    from peira.adapters.base import CallContext
    return CallContext(call_id=over.get("call_id", "call-test"))


def _adapter(transport):
    return AzurePromptShieldsAdapter(
        endpoint="https://res.cognitiveservices.azure.com",
        api_key="key", transport=transport)


def _response(attack_detected=False, latency=12.5):
    seen = {}

    def fake(payload):
        seen["payload"] = payload
        return {
            "userPromptAnalysis": {"attackDetected": attack_detected},
            "documentsAnalysis": [],
            "_latency_ms": latency,
        }

    fake.seen = seen
    return fake


class TestAzurePromptShieldsConstruction(unittest.TestCase):
    def test_missing_endpoint_is_actionable(self):
        old = os.environ.pop(ENDPOINT_ENV, None)
        try:
            with self.assertRaises(ValueError) as cm:
                AzurePromptShieldsAdapter(api_key="k")
        finally:
            if old is not None:
                os.environ[ENDPOINT_ENV] = old
        self.assertIn(ENDPOINT_ENV, str(cm.exception))

    def test_missing_key_is_actionable(self):
        old = os.environ.pop(KEY_ENV, None)
        try:
            with self.assertRaises(ValueError) as cm:
                AzurePromptShieldsAdapter(
                    endpoint="https://res.cognitiveservices.azure.com")
        finally:
            if old is not None:
                os.environ[KEY_ENV] = old
        self.assertIn(KEY_ENV, str(cm.exception))

    def test_explicit_config_ok(self):
        a = _adapter(_response())
        self.assertEqual(a._endpoint,
                         "https://res.cognitiveservices.azure.com")
        self.assertEqual(a._api_key, "key")

    def test_missing_hint_names_real_kwarg(self):
        old = os.environ.pop(KEY_ENV, None)
        try:
            with self.assertRaises(ValueError) as cm:
                AzurePromptShieldsAdapter(
                    endpoint="https://res.cognitiveservices.azure.com")
        finally:
            if old is not None:
                os.environ[KEY_ENV] = old
        # The hint must name the real constructor kwarg, not the env var
        # lowercased.
        self.assertIn("(or pass api_key=...)", str(cm.exception))

    def test_env_vars_declared(self):
        self.assertEqual(AzurePromptShieldsAdapter._env_vars,
                         (ENDPOINT_ENV, KEY_ENV))

    def test_endpoint_pinned(self):
        url = _api_url("https://res.cognitiveservices.azure.com/")
        self.assertEqual(
            url,
            "https://res.cognitiveservices.azure.com/contentsafety/"
            "text:shieldPrompt?api-version=2024-09-01")
        a = _adapter(_response())
        self.assertEqual(a.api_url, url)

    def test_api_version_pinned(self):
        self.assertEqual(API_VERSION, "2024-09-01")
        self.assertEqual(AzurePromptShieldsAdapter.cache_namespace,
                         f"azure-prompt-shields:{API_VERSION}")

    def test_abstain_only(self):
        self.assertEqual(AzurePromptShieldsAdapter.supported_primitives,
                         frozenset({"abstain"}))

    def test_unsupported_primitive_rejected(self):
        a = _adapter(_response())
        with self.assertRaises(ValueError):
            a.decide(_case_input(), "choice", _ctx())

    def test_name_and_version(self):
        self.assertEqual(AzurePromptShieldsAdapter.name,
                         "azure-prompt-shields")
        self.assertEqual(AzurePromptShieldsAdapter.version, "1.0")


class TestAzurePromptShieldsDecide(unittest.TestCase):
    def test_attack_detected_abstains(self):
        fake = _response(attack_detected=True)
        a = _adapter(fake)
        out = a.decide(_case_input(), "abstain", _ctx())
        self.assertEqual(validate_output(out, "abstain"), [])
        self.assertEqual(out.decision, "abstain")
        self.assertFalse(out.abstained)
        self.assertEqual(out.confidence, 1.0)

    def test_no_attack_is_other(self):
        fake = _response(attack_detected=False)
        a = _adapter(fake)
        out = a.decide(_case_input(), "abstain", _ctx())
        self.assertEqual(validate_output(out, "abstain"), [])
        self.assertEqual(out.decision, "other")
        self.assertFalse(out.abstained)

    def test_payload_shape(self):
        fake = _response()
        a = _adapter(fake)
        a.decide(_case_input(prompt="screen me"), "abstain", _ctx())
        self.assertEqual(fake.seen["payload"],
                         {"userPrompt": "screen me", "documents": []})

    def test_empty_input_short_circuits(self):
        calls = []

        def fake(payload):
            calls.append(payload)
            raise AssertionError("should not be called")

        a = _adapter(fake)
        out = a.decide(_case_input(prompt=""), "abstain", _ctx())
        self.assertEqual(validate_output(out, "abstain"), [])
        self.assertEqual(calls, [])
        self.assertEqual(out.decision, "other")
        self.assertEqual(out.usage.cost_usd, 0.0)
        self.assertNotEqual(out.usage.model,
                            f"azure:prompt-shields:{API_VERSION}")
        self.assertEqual(out.transcript["scores"]["p_malicious"], 0.0)

    def test_oversized_prompt_refused_locally(self):
        calls = []

        def fake(payload):
            calls.append(payload)
            raise AssertionError("should not be called")

        a = _adapter(fake)
        with self.assertRaises(ProviderError) as cm:
            a.decide(_case_input(prompt="x" * 10_001), "abstain", _ctx())
        self.assertEqual(cm.exception.status_code, 400)
        self.assertIn("10,000-character", str(cm.exception))
        self.assertEqual(calls, [])

    def test_boundary_prompt_is_sent(self):
        fake = _response()
        a = _adapter(fake)
        out = a.decide(_case_input(prompt="x" * 10_000), "abstain", _ctx())
        self.assertEqual(validate_output(out, "abstain"), [])
        self.assertEqual(len(fake.seen["payload"]["userPrompt"]), 10_000)

    def test_missing_analysis_raises(self):
        def fake(payload):
            return {"_latency_ms": 1.0}

        a = _adapter(fake)
        with self.assertRaises(ProviderError) as cm:
            a.decide(_case_input(), "abstain", _ctx())
        self.assertIn("userPromptAnalysis", str(cm.exception))

    def test_non_boolean_verdict_raises(self):
        def fake(payload):
            return {"userPromptAnalysis": {"attackDetected": "yes"},
                    "_latency_ms": 1.0}

        a = _adapter(fake)
        with self.assertRaises(ProviderError):
            a.decide(_case_input(), "abstain", _ctx())

    def test_usage_model_pinned(self):
        a = _adapter(_response())
        out = a.decide(_case_input(), "abstain", _ctx())
        self.assertEqual(out.usage.model,
                         f"azure:prompt-shields:{API_VERSION}")
        self.assertEqual(out.usage.latency_ms, 12.5)
        self.assertEqual(out.transcript["api_version"], API_VERSION)


class TestAzurePromptShieldsErrorMapping(unittest.TestCase):
    def test_401_terminal(self):
        with self.assertRaises(ProviderError) as cm:
            AzurePromptShieldsAdapter._raise_for_status(401, None, "denied")
        self.assertEqual(cm.exception.status_code, 401)
        self.assertIn(KEY_ENV, str(cm.exception))

    def test_429_transient_with_retry_after(self):
        with self.assertRaises(ProviderError) as cm:
            AzurePromptShieldsAdapter._raise_for_status(429, "5", "busy")
        self.assertEqual(cm.exception.status_code, 429)
        self.assertEqual(cm.exception.retry_after, 5.0)

    def test_500_transient(self):
        with self.assertRaises(ProviderError) as cm:
            AzurePromptShieldsAdapter._raise_for_status(500, None, "oops")
        self.assertEqual(cm.exception.status_code, 500)
        self.assertIsNone(cm.exception.retry_after)

    def test_400_terminal(self):
        with self.assertRaises(ProviderError) as cm:
            AzurePromptShieldsAdapter._raise_for_status(400, None, "bad")
        self.assertEqual(cm.exception.status_code, 400)
        self.assertIsNone(cm.exception.retry_after)


if __name__ == "__main__":
    unittest.main()
