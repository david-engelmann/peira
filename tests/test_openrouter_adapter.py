"""Tests for the OpenRouter gateway structured-output baseline adapter.

The ``openai`` SDK is faked in sys.modules: no API keys, no network.
The fakes record exact client-construction kwargs and request payloads
so the tests can assert on the OpenRouter base URL, the
``google/gemini-3.8-flash`` default, retry configuration,
app-identification headers, and transcript redaction.
"""

import json
import os
import sys
import unittest
from contextlib import contextmanager
from types import ModuleType, SimpleNamespace

from peira.adapters.llm import OpenRouterAdapter, OpenAIAdapter
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

class TestOpenRouterConstruction(unittest.TestCase):
    def setUp(self):
        self.mod, self.calls, self.created = _make_openai(
            [_openai_completion(GOOD_JSON)])
        self._m = _fake_modules({"openai": self.mod})
        self._m.__enter__()
        self._e = _env(OPENROUTER_API_KEY="<redacted>")
        self._e.__enter__()
        self.addCleanup(self._e.__exit__, None, None, None)
        self.addCleanup(self._m.__exit__, None, None, None)

    def test_name(self):
        self.assertEqual(OpenRouterAdapter.name, "openrouter-structured")

    def test_default_model_is_pinned(self):
        adapter = OpenRouterAdapter()
        self.assertEqual(adapter.version, "google/gemini-3.8-flash")
        out = adapter.decide(CASE, "choice", _ctx())
        self.assertEqual(out.usage.model, "google/gemini-3.8-flash")
        self.assertEqual(self.calls[0]["model"], "google/gemini-3.8-flash")

    def test_default_model_matches_pin_registry(self):
        from peira.api_pins import PINNED_API_MODELS
        self.assertEqual(
            PINNED_API_MODELS["openrouter-structured"],
            "google/gemini-3.8-flash",
        )

    def test_model_override(self):
        adapter = OpenRouterAdapter(model="anthropic/claude-sonnet-4.6")
        self.assertEqual(adapter.version, "anthropic/claude-sonnet-4.6")
        out = adapter.decide(CASE, "choice", _ctx())
        self.assertEqual(out.usage.model, "anthropic/claude-sonnet-4.6")
        self.assertIn("anthropic/claude-sonnet-4.6", adapter.cache_namespace)
        self.assertNotIn("gemini-3.8-flash", adapter.cache_namespace)

    def test_base_url_points_at_openrouter(self):
        OpenRouterAdapter()
        self.assertEqual(
            self.created.get("base_url"), "https://openrouter.ai/api/v1")

    def test_retries_disabled(self):
        OpenRouterAdapter()
        self.assertEqual(self.created.get("max_retries"), 0)

    def test_api_key_from_env(self):
        OpenRouterAdapter()
        self.assertEqual(self.created.get("api_key"), "<redacted>")

    def test_explicit_api_key_beats_env(self):
        with _env(OPENROUTER_API_KEY="<redacted>"):
            OpenRouterAdapter(api_key="sk-explicit")
        self.assertEqual(self.created.get("api_key"), "sk-explicit")

    def test_app_identification_headers(self):
        # OpenRouter's documented convention: HTTP-Referer / X-Title.
        OpenRouterAdapter()
        headers = self.created.get("default_headers") or {}
        self.assertEqual(headers.get("HTTP-Referer"), "https://peiratrial.dev")
        self.assertEqual(headers.get("X-Title"), "peira")

    def test_constructor_signature(self):
        adapter = OpenRouterAdapter(
            model="google/gemini-3.8-flash", temperature=0.0, seed=0,
            max_tokens=128, api_key="sk-x",
        )
        self.assertEqual(adapter.version, "google/gemini-3.8-flash")
        self.assertEqual(self.created.get("api_key"), "sk-x")


class TestOpenRouterKeyHandling(unittest.TestCase):
    def test_missing_key_names_openrouter_env_var(self):
        mod, _, _ = _make_openai([])
        with _fake_modules({"openai": mod}), _env(OPENROUTER_API_KEY=None):
            with self.assertRaises(ValueError) as ctx:
                OpenRouterAdapter()
        msg = str(ctx.exception)
        self.assertIn("OPENROUTER_API_KEY", msg)
        self.assertIn("peira[openai]", msg)
        self.assertNotIn("OPENAI_API_KEY", msg)

    def test_missing_extra_names_openai_extra(self):
        with _env(OPENROUTER_API_KEY="<redacted>"):
            with self.assertRaises(ValueError) as ctx:
                OpenRouterAdapter()
        self.assertIn("peira[openai]", str(ctx.exception))


# ---------------------------------------------------------------------------
# Request shape: strict JSON schema, base_url in the transcript, redaction.
# ---------------------------------------------------------------------------

class TestOpenRouterRequestShape(unittest.TestCase):
    def setUp(self):
        self.mod, self.calls, self.created = _make_openai(
            [_openai_completion(GOOD_JSON)])
        self._m = _fake_modules({"openai": self.mod})
        self._m.__enter__()
        self._e = _env(OPENROUTER_API_KEY="sk-test")
        self._e.__enter__()
        self.addCleanup(self._e.__exit__, None, None, None)
        self.addCleanup(self._m.__exit__, None, None, None)

    def test_strict_json_schema_sent(self):
        out = OpenRouterAdapter().decide(CASE, "choice", _ctx())
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
        out = OpenRouterAdapter().decide(CASE, "choice", _ctx())
        self.assertEqual(
            out.transcript["request"]["base_url"],
            "https://openrouter.ai/api/v1",
        )

    def test_no_key_material_in_transcript(self):
        with _env(OPENROUTER_API_KEY="<redacted>"):
            out = OpenRouterAdapter().decide(CASE, "choice", _ctx())
        blob = json.dumps(out.transcript)
        self.assertNotIn("<redacted>", blob)
        self.assertNotIn("sk-", blob)

    def test_seed_and_logprobs_sent(self):
        # Unlike Moonshot (which 400s on them), OpenRouter documents
        # seed and logprobs as supported request parameters, so the
        # adapter sends both — per-model passthrough is unverified and
        # surfaces as terminal errors, not silent mismeasurement.
        out = OpenRouterAdapter().decide(CASE, "choice", _ctx())
        req = out.transcript["request"]
        self.assertEqual(req["seed"], 0)
        self.assertTrue(req["logprobs"])
        self.assertEqual(out.transcript["seed"], 0)

    def test_no_fallback_model_array_sent(self):
        # The models fallback array would silently substitute a
        # different model mid-run and break measurement identity: the
        # adapter must never send it.
        OpenRouterAdapter().decide(CASE, "choice", _ctx())
        self.assertNotIn("models", self.calls[0])

    def test_openai_still_sends_to_openai(self):
        # The base OpenAI adapter is unchanged — only OpenRouter
        # redirects to the gateway.
        with _env(OPENAI_API_KEY="<redacted>"):
            OpenAIAdapter()
        self.assertNotIn("base_url", self.created)


if __name__ == "__main__":
    unittest.main()
