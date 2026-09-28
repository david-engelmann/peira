"""Tests for the new OpenAI-compatible structured-output baseline adapters.

Covers XAIAdapter (xAI/Grok), DeepSeekAdapter (DeepSeek),
MetaLlamaAdapter (Meta Llama API), and ZaiAdapter (Zhipu GLM).

The ``openai`` SDK is faked in sys.modules: no API keys, no network.
The fakes record exact client-construction kwargs and request payloads
so the tests can assert on each provider's base URL, pinned default,
retry configuration, and transcript redaction. Follows the pattern in
tests/test_moonshot_adapter.py.
"""

import json
import os
import sys
import unittest
from contextlib import contextmanager
from types import ModuleType, SimpleNamespace

from peira.adapters.llm import (
    DeepSeekAdapter,
    MetaLlamaAdapter,
    OpenAIAdapter,
    XAIAdapter,
    ZaiAdapter,
)
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


# ---------------------------------------------------------------------------
# Per-adapter expectations: name, env var, base URL, pinned model.
# ---------------------------------------------------------------------------

ADAPTER_SPECS = [
    # (class, name, env var, base URL, pinned model)
    (XAIAdapter, "xai-structured", "XAI_API_KEY",
     "https://api.x.ai/v1", "grok-4"),
    (DeepSeekAdapter, "deepseek-structured", "DEEPSEEK_API_KEY",
     "https://api.deepseek.com", "deepseek-flash"),
    (MetaLlamaAdapter, "meta-structured", "META_API_KEY",
     "https://api.llama.com/compat/v1",
     "Llama-4-Maverick-17B-128E-Instruct-FP8"),
    (ZaiAdapter, "zai-structured", "ZAI_API_KEY",
     "https://open.bigmodel.cn/api/paas/v4", "glm-4-plus"),
]


class TestNewAdapterConstruction(unittest.TestCase):
    """Each adapter: name, pinned default, base URL, no retries, env key."""

    def _setup(self, env_var):
        mod, calls, created = _make_openai([_openai_completion(GOOD_JSON)])
        m = _fake_modules({"openai": mod})
        m.__enter__()
        e = _env(**{env_var: "sk-test"})
        e.__enter__()
        self.addCleanup(e.__exit__, None, None, None)
        self.addCleanup(m.__exit__, None, None, None)
        return calls, created

    def test_names(self):
        for cls, name, _, _, _ in ADAPTER_SPECS:
            with self.subTest(adapter=name):
                self.assertEqual(cls.name, name)

    def test_default_models_are_pinned(self):
        for cls, name, env_var, _, pin in ADAPTER_SPECS:
            with self.subTest(adapter=name):
                calls, _ = self._setup(env_var)
                adapter = cls()
                self.assertEqual(adapter.version, pin)
                out = adapter.decide(CASE, "choice", _ctx())
                self.assertEqual(out.usage.model, pin)
                self.assertEqual(calls[0]["model"], pin)

    def test_base_urls(self):
        for cls, name, env_var, base_url, _ in ADAPTER_SPECS:
            with self.subTest(adapter=name):
                _, created = self._setup(env_var)
                cls()
                self.assertEqual(created.get("base_url"), base_url)

    def test_retries_disabled(self):
        for cls, name, env_var, _, _ in ADAPTER_SPECS:
            with self.subTest(adapter=name):
                _, created = self._setup(env_var)
                cls()
                self.assertEqual(created.get("max_retries"), 0)

    def test_api_key_from_env(self):
        for cls, name, env_var, _, _ in ADAPTER_SPECS:
            with self.subTest(adapter=name):
                _, created = self._setup(env_var)
                cls()
                self.assertEqual(created.get("api_key"), "sk-test")

    def test_explicit_api_key_beats_env(self):
        for cls, name, env_var, _, _ in ADAPTER_SPECS:
            with self.subTest(adapter=name):
                _, created = self._setup(env_var)
                with _env(**{env_var: "sk-env"}):
                    cls(api_key="sk-explicit")
                self.assertEqual(created.get("api_key"), "sk-explicit")

    def test_missing_key_names_own_env_var(self):
        for cls, name, env_var, _, _ in ADAPTER_SPECS:
            with self.subTest(adapter=name):
                mod, _, _ = _make_openai([])
                with _fake_modules({"openai": mod}), \
                        _env(**{env_var: None}):
                    with self.assertRaises(ValueError) as ctx:
                        cls()
                self.assertIn(env_var, str(ctx.exception))
                # Must not name a different provider's variable.
                for _, _, other_var, _, _ in ADAPTER_SPECS:
                    if other_var != env_var:
                        self.assertNotIn(other_var, str(ctx.exception))


class TestNewAdapterRequestShape(unittest.TestCase):
    """Strict JSON schema, base_url in transcript, key redaction."""

    def _setup(self, env_var):
        mod, calls, created = _make_openai([_openai_completion(GOOD_JSON)])
        m = _fake_modules({"openai": mod})
        m.__enter__()
        e = _env(**{env_var: "sk-test"})
        e.__enter__()
        self.addCleanup(e.__exit__, None, None, None)
        self.addCleanup(m.__exit__, None, None, None)
        return calls, created

    def test_strict_json_schema_sent(self):
        for cls, name, env_var, _, _ in ADAPTER_SPECS:
            with self.subTest(adapter=name):
                calls, _ = self._setup(env_var)
                out = cls().decide(CASE, "choice", _ctx())
                self.assertEqual(out.decision, "approve")
                fmt = calls[0]["response_format"]
                self.assertEqual(fmt["type"], "json_schema")
                self.assertTrue(fmt["json_schema"]["strict"])

    def test_base_url_recorded_in_transcript(self):
        for cls, name, env_var, base_url, _ in ADAPTER_SPECS:
            with self.subTest(adapter=name):
                self._setup(env_var)
                out = cls().decide(CASE, "choice", _ctx())
                self.assertEqual(
                    out.transcript["request"]["base_url"], base_url)

    def test_no_key_material_in_transcript(self):
        for cls, name, env_var, _, _ in ADAPTER_SPECS:
            with self.subTest(adapter=name):
                self._setup(env_var)
                out = cls().decide(CASE, "choice", _ctx())
                blob = json.dumps(out.transcript)
                self.assertNotIn("sk-test", blob)


class TestDeepSeekThinkingDisabled(unittest.TestCase):
    """DeepSeekAdapter disables thinking per the evaluation design."""

    def test_thinking_disabled_in_request(self):
        mod, calls, _ = _make_openai([_openai_completion(GOOD_JSON)])
        with _fake_modules({"openai": mod}), \
                _env(DEEPSEEK_API_KEY="sk-test"):
            DeepSeekAdapter().decide(CASE, "choice", _ctx())
        self.assertEqual(calls[0].get("thinking"), {"type": "disabled"})

    def test_openai_does_not_send_thinking(self):
        # The base OpenAI adapter is unchanged — only DeepSeek sets it.
        mod, calls, _ = _make_openai([_openai_completion(GOOD_JSON)])
        with _fake_modules({"openai": mod}), \
                _env(OPENAI_API_KEY="sk-test"):
            OpenAIAdapter().decide(CASE, "choice", _ctx())
        self.assertNotIn("thinking", calls[0])


if __name__ == "__main__":
    unittest.main()
