"""Tests for the Cloudflare Workers AI (Llama Guard 3 8B) adapter.

All transport is faked: no network, no Cloudflare account, no API
token needed. The fake transport receives the exact payload the
adapter would POST and returns a canned parsed response.

The fakes below are written against the documented Workers AI REST
wire shape — ``{"messages": [...]}`` in requests,
``{"result": {"response": text}, "success": bool, "errors": []}`` in
responses — and against the Llama Guard text verdict format (first
line ``safe``/``unsafe``, optional second line of category codes),
not against any earlier draft of this adapter.
"""

import os
import unittest

from peira.adapters.base import ProviderError, validate_output
from peira.adapters.cloudflare_workers_ai import (
    ACCOUNT_ENV,
    MODEL_ID,
    TOKEN_ENV,
    CloudflareWorkersAiAdapter,
    _api_url,
    _llama_guard_prompt,
    _parse_verdict,
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
    return CloudflareWorkersAiAdapter(account_id="acct-1", api_token="tok",
                                      transport=transport)


def _response(verdict="safe", latency=12.5, success=True, errors=None):
    seen = {}

    def fake(payload):
        seen["payload"] = payload
        return {
            "result": {"response": verdict},
            "success": success,
            "errors": errors or [],
            "messages": [],
            "_latency_ms": latency,
        }

    fake.seen = seen
    return fake


class TestCloudflareConstruction(unittest.TestCase):
    def test_missing_account_is_actionable(self):
        old = os.environ.pop(ACCOUNT_ENV, None)
        try:
            with self.assertRaises(ValueError) as cm:
                CloudflareWorkersAiAdapter(api_token="tok")
        finally:
            if old is not None:
                os.environ[ACCOUNT_ENV] = old
        self.assertIn(ACCOUNT_ENV, str(cm.exception))

    def test_missing_token_is_actionable(self):
        old = os.environ.pop(TOKEN_ENV, None)
        try:
            with self.assertRaises(ValueError) as cm:
                CloudflareWorkersAiAdapter(account_id="acct-1")
        finally:
            if old is not None:
                os.environ[TOKEN_ENV] = old
        self.assertIn(TOKEN_ENV, str(cm.exception))

    def test_explicit_config_ok(self):
        a = _adapter(_response())
        self.assertEqual(a._account_id, "acct-1")
        self.assertEqual(a._api_token, "tok")

    def test_missing_hint_names_real_kwarg(self):
        old = os.environ.pop(TOKEN_ENV, None)
        try:
            with self.assertRaises(ValueError) as cm:
                CloudflareWorkersAiAdapter(account_id="acct-1")
        finally:
            if old is not None:
                os.environ[TOKEN_ENV] = old
        # The hint must name the real constructor kwarg, not the env var
        # lowercased.
        self.assertIn("(or pass api_token=...)", str(cm.exception))

    def test_env_vars_declared(self):
        self.assertEqual(CloudflareWorkersAiAdapter._env_vars,
                         (ACCOUNT_ENV, TOKEN_ENV))

    def test_endpoint_pinned(self):
        url = _api_url("acct-1")
        self.assertEqual(
            url,
            "https://api.cloudflare.com/client/v4/accounts/acct-1/"
            "ai/run/@cf/meta/llama-guard-3-8b")
        a = _adapter(_response())
        self.assertEqual(a.api_url, url)

    def test_model_pinned(self):
        self.assertEqual(MODEL_ID, "@cf/meta/llama-guard-3-8b")
        self.assertEqual(CloudflareWorkersAiAdapter.cache_namespace,
                         f"cloudflare-workers-ai:{MODEL_ID}")

    def test_abstain_only(self):
        self.assertEqual(CloudflareWorkersAiAdapter.supported_primitives,
                         frozenset({"abstain"}))

    def test_unsupported_primitive_rejected(self):
        a = _adapter(_response())
        with self.assertRaises(ValueError):
            a.decide(_case_input(), "choice", _ctx())

    def test_name_and_version(self):
        self.assertEqual(CloudflareWorkersAiAdapter.name,
                         "cloudflare-workers-ai")
        self.assertEqual(CloudflareWorkersAiAdapter.version, "1.0")


class TestCloudflareDecide(unittest.TestCase):
    def test_safe_is_other(self):
        a = _adapter(_response(verdict="safe"))
        out = a.decide(_case_input(), "abstain", _ctx())
        self.assertEqual(validate_output(out, "abstain"), [])
        self.assertEqual(out.decision, "other")
        self.assertFalse(out.abstained)
        self.assertEqual(out.confidence, 1.0)

    def test_unsafe_abstains(self):
        a = _adapter(_response(verdict="unsafe\nS1,S7"))
        out = a.decide(_case_input(), "abstain", _ctx())
        self.assertEqual(validate_output(out, "abstain"), [])
        self.assertEqual(out.decision, "abstain")
        self.assertFalse(out.abstained)
        self.assertEqual(out.confidence, 1.0)

    def test_violated_categories_recorded(self):
        a = _adapter(_response(verdict="unsafe\nS1,S7"))
        out = a.decide(_case_input(), "abstain", _ctx())
        self.assertEqual(out.transcript["violated_categories"], ["S1", "S7"])

    def test_payload_shape(self):
        fake = _response()
        a = _adapter(fake)
        a.decide(_case_input(prompt="screen me"), "abstain", _ctx())
        payload = fake.seen["payload"]
        self.assertEqual(len(payload["messages"]), 1)
        self.assertEqual(payload["messages"][0]["role"], "user")
        content = payload["messages"][0]["content"]
        self.assertIn("screen me", content)
        self.assertIn("UNSAFE CONTENT CATEGORIES", content)
        # Workers AI applies the chat template itself: the prompt must
        # carry the Llama Guard task format only, never raw
        # chat-template control tokens.
        for token in ("<|begin_of_text|>", "<|start_header_id|>",
                      "<|end_header_id|>", "<|eot_id|>"):
            self.assertNotIn(token, content)

    def test_prompt_contains_all_fourteen_categories(self):
        prompt = _llama_guard_prompt("x")
        for n in range(1, 15):
            self.assertIn(f"S{n}:", prompt)

    def test_empty_input_short_circuits(self):
        calls = []

        def fake(payload):
            calls.append(payload)
            raise AssertionError("should not be called")

        a = _adapter(fake)
        out = a.decide(_case_input(prompt="   "), "abstain", _ctx())
        self.assertEqual(validate_output(out, "abstain"), [])
        self.assertEqual(calls, [])
        self.assertEqual(out.decision, "other")
        self.assertEqual(out.usage.cost_usd, 0.0)
        self.assertNotEqual(out.usage.model, f"cloudflare:{MODEL_ID}")
        self.assertEqual(out.transcript["scores"]["p_malicious"], 0.0)

    def test_success_false_raises(self):
        a = _adapter(_response(success=False, errors=[{"code": 7003}]))
        with self.assertRaises(ProviderError) as cm:
            a.decide(_case_input(), "abstain", _ctx())
        self.assertIn("success=false", str(cm.exception))

    def test_missing_result_raises(self):
        def fake(payload):
            return {"success": True, "errors": [], "_latency_ms": 1.0}

        a = _adapter(fake)
        with self.assertRaises(ProviderError) as cm:
            a.decide(_case_input(), "abstain", _ctx())
        self.assertIn("'result'", str(cm.exception))

    def test_unparseable_verdict_raises(self):
        # A malformed guardrail verdict fails closed, never silently
        # treated as clean.
        a = _adapter(_response(verdict="hmm, not sure"))
        with self.assertRaises(ProviderError) as cm:
            a.decide(_case_input(), "abstain", _ctx())
        self.assertIn("unparseable", str(cm.exception))

    def test_empty_verdict_raises(self):
        a = _adapter(_response(verdict="   "))
        with self.assertRaises(ProviderError):
            a.decide(_case_input(), "abstain", _ctx())

    def test_usage_model_pinned(self):
        a = _adapter(_response())
        out = a.decide(_case_input(), "abstain", _ctx())
        self.assertEqual(out.usage.model, f"cloudflare:{MODEL_ID}")
        self.assertEqual(out.usage.latency_ms, 12.5)
        self.assertEqual(out.transcript["model"], f"cloudflare:{MODEL_ID}")


class TestParseVerdict(unittest.TestCase):
    def test_safe(self):
        self.assertEqual(_parse_verdict("safe"), (False, []))

    def test_safe_with_trailing_newline(self):
        self.assertEqual(_parse_verdict("safe\n"), (False, []))

    def test_unsafe_without_categories(self):
        self.assertEqual(_parse_verdict("unsafe"), (True, []))

    def test_unsafe_with_categories(self):
        self.assertEqual(_parse_verdict("unsafe\nS3, S10"),
                         (True, ["S3", "S10"]))

    def test_case_insensitive(self):
        self.assertEqual(_parse_verdict("UNSAFE\nS1"), (True, ["S1"]))
        self.assertEqual(_parse_verdict("Safe"), (False, []))

    def test_gibberish_fails_closed(self):
        with self.assertRaises(ProviderError):
            _parse_verdict("I cannot comply")


class TestCloudflareErrorMapping(unittest.TestCase):
    def test_401_terminal(self):
        with self.assertRaises(ProviderError) as cm:
            CloudflareWorkersAiAdapter._raise_for_status(
                401, None, "invalid token")
        self.assertEqual(cm.exception.status_code, 401)
        self.assertIn(TOKEN_ENV, str(cm.exception))

    def test_429_transient_with_retry_after(self):
        with self.assertRaises(ProviderError) as cm:
            CloudflareWorkersAiAdapter._raise_for_status(
                429, "30", "rate limited")
        self.assertEqual(cm.exception.status_code, 429)
        self.assertEqual(cm.exception.retry_after, 30.0)

    def test_500_transient(self):
        with self.assertRaises(ProviderError) as cm:
            CloudflareWorkersAiAdapter._raise_for_status(500, None, "oops")
        self.assertEqual(cm.exception.status_code, 500)
        self.assertIsNone(cm.exception.retry_after)

    def test_404_points_at_account(self):
        with self.assertRaises(ProviderError) as cm:
            CloudflareWorkersAiAdapter._raise_for_status(404, None, "nope")
        self.assertEqual(cm.exception.status_code, 404)
        self.assertIn(ACCOUNT_ENV, str(cm.exception))


if __name__ == "__main__":
    unittest.main()
