"""Tests for the Cursor harness adapter.

The agent CLI is faked through the adapter's injectable runner: no
subprocess, no API key, no network. The fakes return envelopes in
the live-verified shape so the tests can assert on the pin, the
usage mapping, the sampling incapability flags, and error mapping.
"""

import json
import os
import unittest
from contextlib import contextmanager

from peira.adapters.cursor_harness import CursorHarnessAdapter
from peira.adapters.base import CallContext, ProviderError


CASE = {"prompt": "Should the refund be approved?",
        "options": ["approve", "deny"]}

GOOD_JSON = json.dumps({
    "decision": "approve", "confidence": 0.73, "reason": "looks fine",
})


def _envelope(text=GOOD_JSON, **over):
    env = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "duration_ms": 100,
        "duration_api_ms": 90,
        "result": text,
        "session_id": "sess-1",
        "request_id": "req-1",
        "usage": {
            "inputTokens": 13366,
            "outputTokens": 31,
            "cacheReadTokens": 6016,
            "cacheWriteTokens": 0,
        },
    }
    env.update(over)
    return env


@contextmanager
def _env(**vars):
    old = {k: os.environ.get(k) for k in vars}
    try:
        for k, v in vars.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _ctx():
    return CallContext(call_id="call-test")


def _adapter(**over):
    kwargs = {
        "api_key": "crsr-test",
        "runner_fn": lambda prompt: _envelope(),
    }
    kwargs.update(over)
    return CursorHarnessAdapter(**kwargs)


class TestCursorHarnessConstruction(unittest.TestCase):
    def test_name(self):
        self.assertEqual(CursorHarnessAdapter.name, "cursor-harness")

    def test_default_model_is_the_cursor_variant_label(self):
        adapter = _adapter()
        self.assertEqual(adapter.version, "grok-4.7-high-fast")

    def test_default_model_matches_pin_registry(self):
        from peira.api_pins import PINNED_API_MODELS
        self.assertEqual(
            PINNED_API_MODELS["cursor-harness"], "grok-4.7-high-fast")

    def test_bare_vendor_id_is_rejected(self):
        # grok-4.7 is xAI's id. The harness surface answers under
        # Cursor's variant label, and the pin must say so.
        with self.assertRaises(ValueError):
            _adapter(model="grok-4.7")

    def test_sampling_is_provider_incapable(self):
        adapter = _adapter()
        self.assertFalse(adapter._supports_temperature)
        self.assertFalse(adapter._supports_seed)
        self.assertIsNone(adapter._sent_seed())

    def test_missing_key_names_cursor_env_var(self):
        with _env(CURSOR_API_KEY=None):
            with self.assertRaises(ValueError) as ctx:
                CursorHarnessAdapter(
                    runner_fn=lambda prompt: _envelope())
        self.assertIn("CURSOR_API_KEY", str(ctx.exception))


class TestCursorHarnessCalls(unittest.TestCase):
    def test_decide_parses_agent_json(self):
        seen = {}

        def runner(prompt):
            seen["prompt"] = prompt
            return _envelope()

        adapter = _adapter(runner_fn=runner)
        out = adapter.decide(CASE, "choice", _ctx())
        self.assertEqual(out.decision, "approve")
        # The structured pipeline's composed prompt is what was sent.
        self.assertIn("Should the refund be approved?", seen["prompt"])

    def test_usage_comes_from_the_envelope(self):
        adapter = _adapter()
        out = adapter.decide(CASE, "choice", _ctx())
        self.assertEqual(out.usage.model, "grok-4.7-high-fast")
        # Cursor's components are disjoint: total input is the sum.
        self.assertEqual(out.usage.tokens_in, 13366 + 6016)
        self.assertEqual(out.usage.tokens_out, 31)
        self.assertEqual(out.usage.cached_tokens_in, 6016)

    def test_error_envelope_maps_to_provider_error(self):
        adapter = _adapter(
            runner_fn=lambda prompt: _envelope(
                text="rate limit exceeded", is_error=True))
        with self.assertRaises(ProviderError) as ctx:
            adapter.decide(CASE, "choice", _ctx())
        self.assertEqual(ctx.exception.status_code, 429)

    def test_missing_text_result_is_a_provider_error(self):
        env = _envelope()
        env["result"] = None
        adapter = _adapter(runner_fn=lambda prompt: env)
        with self.assertRaises(ProviderError):
            adapter.decide(CASE, "choice", _ctx())

    def test_prose_around_json_still_parses(self):
        adapter = _adapter(runner_fn=lambda prompt: _envelope(
            text=f"Here is my decision.\n{GOOD_JSON}\nDone."))
        out = adapter.decide(CASE, "choice", _ctx())
        self.assertEqual(out.decision, "approve")


if __name__ == "__main__":
    unittest.main()
