"""Tests for the OpenAI gpt-5.6-luna temperature override.

``gpt-5.6-luna`` only accepts ``temperature=1``: any other value 400s
with "Unsupported value: 'temperature' does not support 0.0 with this
model. Only the default (1) value is supported." (observed live
2026-10-03). The adapter must force temperature=1 for that model even
though the constructor default is 0.0, via ``_MODEL_TEMPERATURE_OVERRIDES``
— the same pattern PR #420 established for Moonshot's kimi-k3.

The ``openai`` SDK is faked in sys.modules: no API keys, no network.
The fakes record exact request payloads so the tests can assert on the
temperature actually placed on the wire and in the transcript.
"""

import json
import os
import sys
import unittest
from contextlib import contextmanager
from types import ModuleType, SimpleNamespace

from peira.adapters.llm import OpenAIAdapter
from peira.adapters.base import CallContext


# ---------------------------------------------------------------------------
# Fake openai SDK (mirrors tests/test_moonshot_adapter.py).
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
        # B2: the per-call decision enum is built from the input's
        # explicit options — the context carries no gold labels.
        "options": ["approve", "deny"]}

GOOD_JSON = json.dumps({
    "decision": "approve", "confidence": 0.73, "reason": "looks fine",
})


def _ctx(**over):
    """Opaque adapter-visible context (B2): a call id, nothing else."""
    return CallContext(call_id=over.get("call_id", "call-test"))


class TestOpenAITemperatureOverride(unittest.TestCase):
    """gpt-5.6-luna only accepts temperature=1 (live 400 on any other value).

    Regression test: the adapter must force temperature=1 for the
    pinned model even though the constructor default is 0.0, and the
    transcript must record the temperature actually sent.
    """

    def setUp(self):
        self.mod, self.calls, self.created = _make_openai(
            [_openai_completion(GOOD_JSON)])
        self._m = _fake_modules({"openai": self.mod})
        self._m.__enter__()
        self._e = _env(OPENAI_API_KEY="sk-test")
        self._e.__enter__()
        self.addCleanup(self._e.__exit__, None, None, None)
        self.addCleanup(self._m.__exit__, None, None, None)

    def test_pinned_model_sends_temperature_one(self):
        # Constructor default is 0.0, but gpt-5.6-luna must send 1.0.
        OpenAIAdapter().decide(CASE, "choice", _ctx())
        self.assertEqual(self.calls[0]["temperature"], 1.0)

    def test_pinned_model_transcript_records_override(self):
        out = OpenAIAdapter().decide(CASE, "choice", _ctx())
        self.assertEqual(out.transcript["request"]["temperature"], 1.0)

    def test_pinned_model_effective_temperature_is_one(self):
        # The override is applied in __init__, so the instance itself
        # carries the effective value — cache namespace, decode_params,
        # and transcript agree with what is sent.
        adapter = OpenAIAdapter()
        self.assertEqual(adapter._temperature, 1.0)
        self.assertIn(":t1.0:", adapter.cache_namespace)
        self.assertEqual(adapter.decode_params["temperature"], 1.0)

    def test_explicit_temperature_does_not_leak_into_cache(self):
        # A caller-passed temperature for gpt-5.6-luna must not create
        # a phantom cache namespace: the effective value wins everywhere.
        adapter = OpenAIAdapter(temperature=0.5)
        self.assertEqual(adapter._temperature, 1.0)
        self.assertIn(":t1.0:", adapter.cache_namespace)
        self.assertNotIn(":t0.5:", adapter.cache_namespace)

    def test_explicit_temperature_still_overridden_for_luna(self):
        # Even an explicit constructor temperature cannot beat the
        # provider's constraint — the override wins.
        OpenAIAdapter(temperature=0.5).decide(CASE, "choice", _ctx())
        self.assertEqual(self.calls[0]["temperature"], 1.0)

    def test_unlisted_model_keeps_constructor_temperature(self):
        # Models without an override entry keep the caller's value.
        OpenAIAdapter(model="gpt-4o").decide(CASE, "choice", _ctx())
        self.assertEqual(self.calls[0]["temperature"], 0.0)

    def test_unlisted_model_transcript_records_constructor_value(self):
        out = OpenAIAdapter(model="gpt-4o").decide(CASE, "choice", _ctx())
        self.assertEqual(out.transcript["request"]["temperature"], 0.0)

    def test_override_map_covers_pinned_model(self):
        self.assertIn("gpt-5.6-luna",
                      OpenAIAdapter._MODEL_TEMPERATURE_OVERRIDES)
        self.assertEqual(
            OpenAIAdapter._MODEL_TEMPERATURE_OVERRIDES["gpt-5.6-luna"], 1.0)


class TestOpenAISolTemperatureOverride(unittest.TestCase):
    """gpt-6.1-sol only accepts temperature=1.

    Observed live 2026-10-13 (canary probes against api.openai.com,
    run for this model on its own evidence, not inherited from the
    5.6 family): temperature=0.0 400s with "Unsupported value:
    'temperature' does not support 0.0 with this model. Only the
    default (1) value is supported." The adapter must force
    temperature=1 for ``gpt-6.1-sol`` even though the constructor
    default is 0.0.
    """

    def setUp(self):
        self.mod, self.calls, self.created = _make_openai(
            [_openai_completion(GOOD_JSON)])
        self._m = _fake_modules({"openai": self.mod})
        self._m.__enter__()
        self._e = _env(OPENAI_API_KEY="sk-test")
        self._e.__enter__()
        self.addCleanup(self._e.__exit__, None, None, None)
        self.addCleanup(self._m.__exit__, None, None, None)

    def test_sol_sends_temperature_one(self):
        OpenAIAdapter(model="gpt-6.1-sol").decide(CASE, "choice", _ctx())
        self.assertEqual(self.calls[0]["temperature"], 1.0)

    def test_sol_transcript_records_override(self):
        out = OpenAIAdapter(model="gpt-6.1-sol").decide(
            CASE, "choice", _ctx())
        self.assertEqual(out.transcript["request"]["temperature"], 1.0)

    def test_sol_effective_temperature_is_one(self):
        adapter = OpenAIAdapter(model="gpt-6.1-sol")
        self.assertEqual(adapter._temperature, 1.0)
        self.assertIn(":t1.0:", adapter.cache_namespace)
        self.assertEqual(adapter.decode_params["temperature"], 1.0)

    def test_sol_explicit_temperature_still_overridden(self):
        # Even an explicit constructor temperature cannot beat the
        # provider's constraint — the override wins.
        OpenAIAdapter(
            model="gpt-6.1-sol", temperature=0.5).decide(
                CASE, "choice", _ctx())
        self.assertEqual(self.calls[0]["temperature"], 1.0)

    def test_override_map_covers_sol(self):
        self.assertIn("gpt-6.1-sol",
                      OpenAIAdapter._MODEL_TEMPERATURE_OVERRIDES)
        self.assertEqual(
            OpenAIAdapter._MODEL_TEMPERATURE_OVERRIDES["gpt-6.1-sol"], 1.0)


class TestOpenAILuna6TemperatureOverride(unittest.TestCase):
    """gpt-6-luna only accepts temperature=1.

    Observed live 2026-10-13 (canary probes against api.openai.com,
    run for this model on its own evidence, not inherited from the
    5.6 family): temperature=0.0 400s with "Unsupported value:
    'temperature' does not support 0.0 with this model. Only the
    default (1) value is supported." The adapter must force
    temperature=1 for ``gpt-6-luna`` even though the constructor
    default is 0.0.
    """

    def setUp(self):
        self.mod, self.calls, self.created = _make_openai(
            [_openai_completion(GOOD_JSON)])
        self._m = _fake_modules({"openai": self.mod})
        self._m.__enter__()
        self._e = _env(OPENAI_API_KEY="sk-test")
        self._e.__enter__()
        self.addCleanup(self._e.__exit__, None, None, None)
        self.addCleanup(self._m.__exit__, None, None, None)

    def test_luna6_sends_temperature_one(self):
        OpenAIAdapter(model="gpt-6-luna").decide(CASE, "choice", _ctx())
        self.assertEqual(self.calls[0]["temperature"], 1.0)

    def test_luna6_transcript_records_override(self):
        out = OpenAIAdapter(model="gpt-6-luna").decide(
            CASE, "choice", _ctx())
        self.assertEqual(out.transcript["request"]["temperature"], 1.0)

    def test_luna6_effective_temperature_is_one(self):
        adapter = OpenAIAdapter(model="gpt-6-luna")
        self.assertEqual(adapter._temperature, 1.0)
        self.assertIn(":t1.0:", adapter.cache_namespace)
        self.assertEqual(adapter.decode_params["temperature"], 1.0)

    def test_luna6_explicit_temperature_still_overridden(self):
        # Even an explicit constructor temperature cannot beat the
        # provider's constraint — the override wins.
        OpenAIAdapter(
            model="gpt-6-luna", temperature=0.5).decide(
                CASE, "choice", _ctx())
        self.assertEqual(self.calls[0]["temperature"], 1.0)

    def test_override_map_covers_luna6(self):
        self.assertIn("gpt-6-luna",
                      OpenAIAdapter._MODEL_TEMPERATURE_OVERRIDES)
        self.assertEqual(
            OpenAIAdapter._MODEL_TEMPERATURE_OVERRIDES["gpt-6-luna"], 1.0)


class TestOpenAITerra56TemperatureOverride(unittest.TestCase):
    """gpt-5.6-terra only accepts temperature=1.

    Observed live 2026-10-13 (canary probes against api.openai.com,
    run for this model on its own evidence, not inherited from the
    5.6 family): temperature=0.0 400s with "Unsupported value:
    'temperature' does not support 0.0 with this model. Only the
    default (1) value is supported." The adapter must force
    temperature=1 for ``gpt-5.6-terra`` even though the constructor
    default is 0.0.
    """

    def setUp(self):
        self.mod, self.calls, self.created = _make_openai(
            [_openai_completion(GOOD_JSON)])
        self._m = _fake_modules({"openai": self.mod})
        self._m.__enter__()
        self._e = _env(OPENAI_API_KEY="sk-test")
        self._e.__enter__()
        self.addCleanup(self._e.__exit__, None, None, None)
        self.addCleanup(self._m.__exit__, None, None, None)

    def test_terra_sends_temperature_one(self):
        OpenAIAdapter(model="gpt-5.6-terra").decide(CASE, "choice", _ctx())
        self.assertEqual(self.calls[0]["temperature"], 1.0)

    def test_terra_transcript_records_override(self):
        out = OpenAIAdapter(model="gpt-5.6-terra").decide(
            CASE, "choice", _ctx())
        self.assertEqual(out.transcript["request"]["temperature"], 1.0)

    def test_terra_effective_temperature_is_one(self):
        adapter = OpenAIAdapter(model="gpt-5.6-terra")
        self.assertEqual(adapter._temperature, 1.0)
        self.assertIn(":t1.0:", adapter.cache_namespace)
        self.assertEqual(adapter.decode_params["temperature"], 1.0)

    def test_terra_explicit_temperature_still_overridden(self):
        # Even an explicit constructor temperature cannot beat the
        # provider's constraint — the override wins.
        OpenAIAdapter(
            model="gpt-5.6-terra", temperature=0.5).decide(
                CASE, "choice", _ctx())
        self.assertEqual(self.calls[0]["temperature"], 1.0)

    def test_override_map_covers_terra(self):
        self.assertIn("gpt-5.6-terra",
                      OpenAIAdapter._MODEL_TEMPERATURE_OVERRIDES)
        self.assertEqual(
            OpenAIAdapter._MODEL_TEMPERATURE_OVERRIDES["gpt-5.6-terra"], 1.0)


class TestOpenAIAstraTemperatureOverride(unittest.TestCase):
    """gpt-6-astra only accepts temperature=1.

    Observed live 2026-10-13 (canary probes against api.openai.com,
    run for this model on its own evidence, not inherited from the
    5.6 family): temperature=0.0 400s with "Unsupported value:
    'temperature' does not support 0.0 with this model. Only the
    default (1) value is supported." The adapter must force
    temperature=1 for ``gpt-6-astra`` even though the constructor
    default is 0.0.
    """

    def setUp(self):
        self.mod, self.calls, self.created = _make_openai(
            [_openai_completion(GOOD_JSON)])
        self._m = _fake_modules({"openai": self.mod})
        self._m.__enter__()
        self._e = _env(OPENAI_API_KEY="sk-test")
        self._e.__enter__()
        self.addCleanup(self._e.__exit__, None, None, None)
        self.addCleanup(self._m.__exit__, None, None, None)

    def test_astra_sends_temperature_one(self):
        OpenAIAdapter(model="gpt-6-astra").decide(CASE, "choice", _ctx())
        self.assertEqual(self.calls[0]["temperature"], 1.0)

    def test_astra_transcript_records_override(self):
        out = OpenAIAdapter(model="gpt-6-astra").decide(
            CASE, "choice", _ctx())
        self.assertEqual(out.transcript["request"]["temperature"], 1.0)

    def test_astra_effective_temperature_is_one(self):
        adapter = OpenAIAdapter(model="gpt-6-astra")
        self.assertEqual(adapter._temperature, 1.0)
        self.assertIn(":t1.0:", adapter.cache_namespace)
        self.assertEqual(adapter.decode_params["temperature"], 1.0)

    def test_astra_explicit_temperature_still_overridden(self):
        # Even an explicit constructor temperature cannot beat the
        # provider's constraint — the override wins.
        OpenAIAdapter(
            model="gpt-6-astra", temperature=0.5).decide(
                CASE, "choice", _ctx())
        self.assertEqual(self.calls[0]["temperature"], 1.0)

    def test_override_map_covers_astra(self):
        self.assertIn("gpt-6-astra",
                      OpenAIAdapter._MODEL_TEMPERATURE_OVERRIDES)
        self.assertEqual(
            OpenAIAdapter._MODEL_TEMPERATURE_OVERRIDES["gpt-6-astra"], 1.0)


if __name__ == "__main__":
    unittest.main()
