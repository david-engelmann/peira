"""Tests for the Moonshot (Kimi) structured-output baseline adapter.

The ``openai`` SDK is faked in sys.modules: no API keys, no network.
The fakes record exact client-construction kwargs and request payloads
so the tests can assert on the Moonshot base URL, the ``kimi-k3``
default, retry configuration, and transcript redaction.
"""

import json
import os
import sys
import unittest
from contextlib import contextmanager
from types import ModuleType, SimpleNamespace

from peira.adapters.llm import MoonshotAdapter, OpenAIAdapter
from peira.adapters.base import CallContext


# ---------------------------------------------------------------------------
# Fake openai SDK (mirrors tests/test_llm_adapters.py).
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


@contextmanager
def _without(*names):
    saved = {}
    for n in names:
        if n in sys.modules:
            saved[n] = sys.modules.pop(n)
    try:
        yield
    finally:
        sys.modules.update(saved)


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


# ---------------------------------------------------------------------------
# Construction: model default, name, env var, base URL, no retries.
# ---------------------------------------------------------------------------

class TestMoonshotConstruction(unittest.TestCase):
    def setUp(self):
        self.mod, self.calls, self.created = _make_openai(
            [_openai_completion(GOOD_JSON)])
        self._m = _fake_modules({"openai": self.mod})
        self._m.__enter__()
        self._e = _env(MOONSHOT_API_KEY="sk-moonshot-test")
        self._e.__enter__()
        self.addCleanup(self._e.__exit__, None, None, None)
        self.addCleanup(self._m.__exit__, None, None, None)

    def test_name(self):
        self.assertEqual(MoonshotAdapter.name, "moonshot-structured")

    def test_default_model_is_pinned(self):
        adapter = MoonshotAdapter()
        self.assertEqual(adapter.version, "kimi-k3")
        out = adapter.decide(CASE, "choice", _ctx())
        self.assertEqual(out.usage.model, "kimi-k3")
        self.assertEqual(self.calls[0]["model"], "kimi-k3")

    def test_model_override(self):
        adapter = MoonshotAdapter(model="kimi-k2.6")
        self.assertEqual(adapter.version, "kimi-k2.6")
        out = adapter.decide(CASE, "choice", _ctx())
        self.assertEqual(out.usage.model, "kimi-k2.6")
        self.assertIn("kimi-k2.6", adapter.cache_namespace)
        self.assertNotIn("kimi-k3", adapter.cache_namespace)

    def test_base_url_points_at_moonshot(self):
        MoonshotAdapter()
        self.assertEqual(
            self.created.get("base_url"), "https://api.moonshot.ai/v1")

    def test_retries_disabled(self):
        MoonshotAdapter()
        self.assertEqual(self.created.get("max_retries"), 0)

    def test_api_key_from_env(self):
        MoonshotAdapter()
        self.assertEqual(self.created.get("api_key"), "sk-moonshot-test")

    def test_explicit_api_key_beats_env(self):
        with _env(MOONSHOT_API_KEY=None):
            MoonshotAdapter(api_key="sk-explicit")
        self.assertEqual(self.created.get("api_key"), "sk-explicit")

    def test_constructor_signature(self):
        adapter = MoonshotAdapter(
            model="kimi-k3", temperature=0.0, seed=0, max_tokens=128,
            api_key="sk-x",
        )
        self.assertEqual(adapter.version, "kimi-k3")
        self.assertEqual(self.created.get("api_key"), "sk-x")


class TestMoonshotKeyHandling(unittest.TestCase):
    def test_missing_key_names_moonshot_env_var(self):
        mod, _, _ = _make_openai([])
        with _fake_modules({"openai": mod}), _env(MOONSHOT_API_KEY=None):
            with self.assertRaises(ValueError) as ctx:
                MoonshotAdapter()
        msg = str(ctx.exception)
        self.assertIn("MOONSHOT_API_KEY", msg)
        self.assertIn("peira[openai]", msg)
        self.assertNotIn("OPENAI_API_KEY", msg)

    def test_missing_extra_names_openai_extra(self):
        with _env(MOONSHOT_API_KEY="sk-test"), _without("openai"):
            with self.assertRaises(ValueError) as ctx:
                MoonshotAdapter()
        self.assertIn("peira[openai]", str(ctx.exception))


# ---------------------------------------------------------------------------
# Request shape: strict JSON schema, base_url in the transcript, redaction.
# ---------------------------------------------------------------------------

class TestMoonshotRequestShape(unittest.TestCase):
    def setUp(self):
        self.mod, self.calls, self.created = _make_openai(
            [_openai_completion(GOOD_JSON)])
        self._m = _fake_modules({"openai": self.mod})
        self._m.__enter__()
        self._e = _env(MOONSHOT_API_KEY="sk-test")
        self._e.__enter__()
        self.addCleanup(self._e.__exit__, None, None, None)
        self.addCleanup(self._m.__exit__, None, None, None)

    def test_strict_json_schema_sent(self):
        out = MoonshotAdapter().decide(CASE, "choice", _ctx())
        self.assertEqual(out.decision, "approve")
        fmt = self.calls[0]["response_format"]
        self.assertEqual(fmt["type"], "json_schema")
        self.assertTrue(fmt["json_schema"]["strict"])
        self.assertEqual(fmt["json_schema"]["name"], "peira_decision")
        self.assertEqual(
            fmt["json_schema"]["schema"]["properties"]["decision"]["enum"],
            ["approve", "deny", "other"],
        )

    def test_base_url_recorded_in_transcript(self):
        out = MoonshotAdapter().decide(CASE, "choice", _ctx())
        self.assertEqual(
            out.transcript["request"]["base_url"],
            "https://api.moonshot.ai/v1",
        )

    def test_no_key_material_in_transcript(self):
        with _env(MOONSHOT_API_KEY="sk-moonshot-secret-999"):
            out = MoonshotAdapter().decide(CASE, "choice", _ctx())
        blob = json.dumps(out.transcript)
        self.assertNotIn("sk-moonshot-secret-999", blob)
        self.assertNotIn("sk-", blob)

    def test_seed_and_logprobs_omitted_from_request(self):
        # Moonshot 400s on seed/logprobs — the adapter must omit both.
        out = MoonshotAdapter().decide(CASE, "choice", _ctx())
        req = out.transcript["request"]
        self.assertIsNone(req["seed"])
        self.assertFalse(req["logprobs"])
        # Top-level transcript seed must also be None (not 0) since
        # Moonshot never receives the seed — _supports_seed = False.
        self.assertIsNone(out.transcript["seed"])

    def test_openai_still_sends_seed_and_logprobs(self):
        # The base OpenAI adapter is unchanged — only Moonshot omits.
        with _env(OPENAI_API_KEY="<redacted>"):
            out = OpenAIAdapter().decide(CASE, "choice", _ctx())
        req = out.transcript["request"]
        self.assertEqual(req["seed"], 0)
        self.assertTrue(req["logprobs"])


class TestMoonshotTemperatureOverride(unittest.TestCase):
    """kimi-k3 only accepts temperature=1 (live 400 on any other value).

    Regression test: the adapter must force temperature=1 for the
    pinned model even though the constructor default is 0.0, and the
    transcript must record the temperature actually sent.
    """

    def setUp(self):
        self.mod, self.calls, self.created = _make_openai(
            [_openai_completion(GOOD_JSON)])
        self._m = _fake_modules({"openai": self.mod})
        self._m.__enter__()
        self._e = _env(MOONSHOT_API_KEY="sk-test")
        self._e.__enter__()
        self.addCleanup(self._e.__exit__, None, None, None)
        self.addCleanup(self._m.__exit__, None, None, None)

    def test_pinned_model_sends_temperature_one(self):
        # Constructor default is 0.0, but kimi-k3 must send 1.0.
        MoonshotAdapter().decide(CASE, "choice", _ctx())
        self.assertEqual(self.calls[0]["temperature"], 1.0)

    def test_pinned_model_transcript_records_override(self):
        out = MoonshotAdapter().decide(CASE, "choice", _ctx())
        self.assertEqual(out.transcript["request"]["temperature"], 1.0)

    def test_pinned_model_effective_temperature_is_one(self):
        # The override is applied in __init__, so the instance itself
        # carries the effective value — cache namespace and transcript
        # agree with what is sent.
        adapter = MoonshotAdapter()
        self.assertEqual(adapter._temperature, 1.0)
        self.assertIn(":t1.0:", adapter.cache_namespace)

    def test_explicit_temperature_does_not_leak_into_cache(self):
        # A caller-passed temperature for kimi-k3 must not create a
        # phantom cache namespace: the effective value wins everywhere.
        adapter = MoonshotAdapter(temperature=0.5)
        self.assertEqual(adapter._temperature, 1.0)
        self.assertIn(":t1.0:", adapter.cache_namespace)
        self.assertNotIn(":t0.5:", adapter.cache_namespace)

    def test_explicit_temperature_still_overridden_for_kimi_k3(self):
        # Even an explicit constructor temperature cannot beat the
        # provider's constraint — the override wins.
        MoonshotAdapter(temperature=0.5).decide(CASE, "choice", _ctx())
        self.assertEqual(self.calls[0]["temperature"], 1.0)

    def test_unlisted_model_keeps_constructor_temperature(self):
        # Models without an override entry keep the caller's value.
        MoonshotAdapter(model="kimi-k2.6").decide(CASE, "choice", _ctx())
        self.assertEqual(self.calls[0]["temperature"], 0.0)

    def test_unlisted_model_transcript_records_constructor_value(self):
        out = MoonshotAdapter(model="kimi-k2.6").decide(CASE, "choice", _ctx())
        self.assertEqual(out.transcript["request"]["temperature"], 0.0)

    def test_override_map_covers_pinned_model(self):
        self.assertIn("kimi-k3", MoonshotAdapter._MODEL_TEMPERATURE_OVERRIDES)
        self.assertEqual(
            MoonshotAdapter._MODEL_TEMPERATURE_OVERRIDES["kimi-k3"], 1.0)


if __name__ == "__main__":
    unittest.main()
