"""Tests for the Inception Mercury direct structured-output adapter.

The ``openai`` SDK is faked in sys.modules: no API keys, no network.
The fakes record exact client-construction kwargs and request payloads
so the tests can assert on the Inception base URL, the ``mercury-3``
default, retry configuration, and key handling.
"""

import json
import os
import sys
import unittest
from contextlib import contextmanager
from types import ModuleType, SimpleNamespace

from peira.adapters.llm import MercuryAdapter
from peira.adapters.base import CallContext


# ---------------------------------------------------------------------------
# Fake openai SDK (mirrors tests/test_openrouter_adapter.py).
# ---------------------------------------------------------------------------

def _openai_completion(content, finish_reason="stop"):
    choice = SimpleNamespace(
        message=SimpleNamespace(content=content),
        finish_reason=finish_reason,
        logprobs=SimpleNamespace(content=[]),
    )
    return SimpleNamespace(
        choices=[choice],
        usage=SimpleNamespace(prompt_tokens=11, completion_tokens=22),
    )


def _make_openai(script):
    calls, created = [], {}

    class _Completions:
        def create(self, **kwargs):
            calls.append(kwargs)
            item = script[len(calls) - 1]
            if isinstance(item, BaseException):
                raise item
            return item

    class _Chat:
        def __init__(self):
            self.completions = _Completions()

    class _Client:
        def __init__(self, **kwargs):
            created.update(kwargs)
            self.chat = _Chat()

    mod = ModuleType("openai")
    mod.OpenAI = _Client
    return mod, calls, created


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


@contextmanager
def _fake_modules(mods):
    old = {k: sys.modules.get(k, None) for k in mods}
    try:
        sys.modules.update(mods)
        yield
    finally:
        for k, v in old.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


CASE = {"prompt": "Should the refund be approved?",
        "options": ["approve", "deny"]}

GOOD_JSON = json.dumps({
    "decision": "approve", "confidence": 0.73, "reason": "looks fine",
})


def _ctx(**over):
    return CallContext(call_id=over.get("call_id", "call-test"))


# ---------------------------------------------------------------------------
# Construction: model default, name, env var, base URL, no retries.
# ---------------------------------------------------------------------------

class TestMercuryConstruction(unittest.TestCase):
    def setUp(self):
        self.mod, self.calls, self.created = _make_openai(
            [_openai_completion(GOOD_JSON)])
        self._m = _fake_modules({"openai": self.mod})
        self._m.__enter__()
        self._e = _env(INCEPTION_API_KEY="inc" + "-test")
        self._e.__enter__()
        self.addCleanup(self._e.__exit__, None, None, None)
        self.addCleanup(self._m.__exit__, None, None, None)

    def test_name(self):
        self.assertEqual(MercuryAdapter.name, "mercury-structured")

    def test_default_model_is_pinned(self):
        adapter = MercuryAdapter()
        self.assertEqual(adapter.version, "mercury-3")
        out = adapter.decide(CASE, "choice", _ctx())
        self.assertEqual(out.usage.model, "mercury-3")
        self.assertEqual(self.calls[0]["model"], "mercury-3")

    def test_default_model_matches_pin_registry(self):
        from peira.api_pins import PINNED_API_MODELS
        self.assertEqual(
            PINNED_API_MODELS["mercury-structured"], "mercury-3")

    def test_base_url_points_at_inception(self):
        MercuryAdapter()
        self.assertEqual(
            self.created.get("base_url"),
            "https://api.inceptionlabs.ai/v1")

    def test_retries_disabled(self):
        MercuryAdapter()
        self.assertEqual(self.created.get("max_retries"), 0)

    def test_api_key_from_env(self):
        MercuryAdapter()
        self.assertEqual(self.created.get("api_key"), "inc-test")

    def test_explicit_api_key_beats_env(self):
        with _env(INCEPTION_API_KEY="inc-env"):
            MercuryAdapter(api_key="inc-explicit")
        self.assertEqual(self.created.get("api_key"), "inc-explicit")

    def test_decide_parses_schema_json(self):
        adapter = MercuryAdapter()
        out = adapter.decide(CASE, "choice", _ctx())
        self.assertEqual(out.decision, "approve")
        # Strict JSON schema is the request shape on the wire.
        fmt = self.calls[0]["response_format"]
        self.assertEqual(fmt["type"], "json_schema")
        self.assertTrue(fmt["json_schema"]["strict"])


class TestMercuryKeyHandling(unittest.TestCase):
    def test_missing_key_names_inception_env_var(self):
        mod, _, _ = _make_openai([])
        with _fake_modules({"openai": mod}), _env(INCEPTION_API_KEY=None):
            with self.assertRaises(ValueError) as ctx:
                MercuryAdapter()
        msg = str(ctx.exception)
        self.assertIn("INCEPTION_API_KEY", msg)
        self.assertIn("peira[openai]", msg)
        self.assertNotIn("OPENAI_API_KEY", msg)

    def test_missing_extra_names_openai_extra(self):
        with _env(INCEPTION_API_KEY="inc-test"):
            with self.assertRaises(ValueError) as ctx:
                MercuryAdapter()
        self.assertIn("peira[openai]", str(ctx.exception))


class TestMercuryReasoningEffort(unittest.TestCase):
    def setUp(self):
        self.mod, self.calls, self.created = _make_openai(
            [_openai_completion(GOOD_JSON)])
        self._m = _fake_modules({"openai": self.mod})
        self._m.__enter__()
        self._e = _env(INCEPTION_API_KEY="inc" + "-test")
        self._e.__enter__()
        self.addCleanup(self._e.__exit__, None, None, None)
        self.addCleanup(self._m.__exit__, None, None, None)

    def test_effort_pinned_medium_on_the_wire(self):
        adapter = MercuryAdapter()
        adapter.decide(CASE, "choice", _ctx())
        self.assertEqual(self.calls[0]["reasoning_effort"], "medium")

    def test_effort_in_decode_params(self):
        adapter = MercuryAdapter()
        self.assertEqual(
            adapter.decode_params["reasoning_effort"], "medium")

    def test_effort_override_changes_wire_and_namespace(self):
        adapter = MercuryAdapter(reasoning_effort="high")
        adapter.decide(CASE, "choice", _ctx())
        self.assertEqual(self.calls[0]["reasoning_effort"], "high")
        self.assertIn(":rehigh", adapter.cache_namespace)

    def test_invalid_effort_rejected(self):
        with self.assertRaises(ValueError):
            MercuryAdapter(reasoning_effort="max")

    def test_effort_and_base_url_recorded_in_transcript(self):
        adapter = MercuryAdapter()
        out = adapter.decide(CASE, "choice", _ctx())
        request = out.transcript["request"]
        self.assertEqual(request["reasoning_effort"], "medium")
        self.assertEqual(
            request["base_url"], "https://api.inceptionlabs.ai/v1")

    def test_effort_pinned_on_the_repair_attempt(self):
        # First answer is unparseable prose, forcing the base class's
        # single repair attempt; the pin must ride on both calls.
        mod, calls, _created = _make_openai([
            _openai_completion("the answer is approve, trust me"),
            _openai_completion(GOOD_JSON),
        ])
        with _fake_modules({"openai": mod}):
            adapter = MercuryAdapter()
            out = adapter.decide(CASE, "choice", _ctx())
        self.assertEqual(out.decision, "approve")
        self.assertEqual(len(calls), 2)
        self.assertEqual(
            [c["reasoning_effort"] for c in calls], ["medium", "medium"])


if __name__ == "__main__":
    unittest.main()
