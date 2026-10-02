"""Tests for the Mistral and Qwen structured-output baseline adapters,
plus the D3 Opus 5.5 reconciliation in AnthropicAdapter.

Covers MistralAdapter (Mistral La Plateforme) and QwenAdapter (Alibaba
DashScope), and the Anthropic routing for ``claude-opus-5-5`` /
``claude-sonnet-5-5`` (structured-outputs path, temperature omitted).

The ``openai`` and ``anthropic`` SDKs are faked in sys.modules: no API
keys, no network. The fakes record exact client-construction kwargs
and request payloads so the tests can assert on each provider's base
URL, pinned default, retry configuration, seed wire names, and the
thinking kill-switch. Follows the pattern in
tests/test_new_llm_adapters.py.
"""

import json
import os
import sys
import unittest
from contextlib import contextmanager
from types import ModuleType, SimpleNamespace

from peira.adapters.llm import (
    AnthropicAdapter,
    MistralAdapter,
    OpenAIAdapter,
    QwenAdapter,
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


# ---------------------------------------------------------------------------
# Fake anthropic SDK (mirrors tests/test_llm_adapters.py).
# ---------------------------------------------------------------------------

def _anthropic_message(text="", stop_reason="end_turn"):
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=13, output_tokens=23),
    )


def _make_anthropic(script):
    calls, created = [], {}

    class _Messages:
        def create(self, **kwargs):
            calls.append(kwargs)
            item = script[len(calls) - 1]
            if isinstance(item, BaseException):
                raise item
            return item

    class _Client:
        def __init__(self, **kwargs):
            created.update(kwargs)
            self.messages = _Messages()

    mod = ModuleType("anthropic")
    mod.Anthropic = _Client
    mod.APIStatusError = type("APIStatusError", (Exception,), {})
    mod.APITimeoutError = type("APITimeoutError", (Exception,), {})
    mod.APIConnectionError = type("APIConnectionError", (Exception,), {})
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
    (MistralAdapter, "mistral-structured", "MISTRAL_API_KEY",
     "https://api.mistral.ai/v1", "mistral-large-2512"),
    (QwenAdapter, "qwen-structured", "DASHSCOPE_API_KEY",
     "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
     "qwen3.8-max"),
]


class TestMistralQwenConstruction(unittest.TestCase):
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


class TestMistralQwenRequestShape(unittest.TestCase):
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


class TestMistralSeedWireName(unittest.TestCase):
    """Mistral's seed parameter is ``random_seed``, not ``seed``."""

    def test_random_seed_sent_not_seed(self):
        mod, calls, _ = _make_openai([_openai_completion(GOOD_JSON)])
        with _fake_modules({"openai": mod}), \
                _env(MISTRAL_API_KEY="sk-test"):
            MistralAdapter(seed=42).decide(CASE, "choice", _ctx())
        self.assertEqual(calls[0].get("random_seed"), 42)
        self.assertNotIn("seed", calls[0])

    def test_logprobs_omitted(self):
        # Undocumented for Mistral chat completions — omit, don't
        # negotiate. No decision-token logprob track on this adapter.
        mod, calls, _ = _make_openai([_openai_completion(GOOD_JSON)])
        with _fake_modules({"openai": mod}), \
                _env(MISTRAL_API_KEY="sk-test"):
            out = MistralAdapter().decide(CASE, "choice", _ctx())
        self.assertNotIn("logprobs", calls[0])
        self.assertIsNone(
            out.transcript["confidence_tracks"]["decision_token_logprob"])

    def test_seed_recorded_under_wire_name(self):
        # The transcript must not claim an unsent ``seed`` field.
        mod, _, _ = _make_openai([_openai_completion(GOOD_JSON)])
        with _fake_modules({"openai": mod}), \
                _env(MISTRAL_API_KEY="sk-test"):
            out = MistralAdapter(seed=42).decide(CASE, "choice", _ctx())
        self.assertEqual(out.transcript["request"]["seed"], 42)

    def test_openai_still_sends_seed(self):
        # The base adapter is unchanged — only Mistral renames it.
        mod, calls, _ = _make_openai([_openai_completion(GOOD_JSON)])
        with _fake_modules({"openai": mod}), \
                _env(OPENAI_API_KEY="sk-test"):
            OpenAIAdapter(seed=42).decide(CASE, "choice", _ctx())
        self.assertEqual(calls[0].get("seed"), 42)
        self.assertNotIn("random_seed", calls[0])


class TestQwenThinkingDisabled(unittest.TestCase):
    """QwenAdapter sets ``enable_thinking: false`` via ``extra_body``."""

    def test_enable_thinking_false_in_extra_body(self):
        # DashScope rejects requests that omit the parameter, and
        # json_schema is honored only with thinking disabled.
        mod, calls, _ = _make_openai([_openai_completion(GOOD_JSON)])
        with _fake_modules({"openai": mod}), \
                _env(DASHSCOPE_API_KEY="sk-test"):
            QwenAdapter().decide(CASE, "choice", _ctx())
        extra_body = calls[0].get("extra_body") or {}
        self.assertIs(extra_body.get("enable_thinking"), False)

    def test_enable_thinking_recorded_in_transcript(self):
        # The kill-switch is load-bearing — it belongs in the
        # transcript, not just the wire kwargs.
        mod, _, _ = _make_openai([_openai_completion(GOOD_JSON)])
        with _fake_modules({"openai": mod}), \
                _env(DASHSCOPE_API_KEY="sk-test"):
            out = QwenAdapter().decide(CASE, "choice", _ctx())
        self.assertIs(
            out.transcript["request"].get("enable_thinking"), False)

    def test_openai_does_not_send_enable_thinking(self):
        # The base OpenAI adapter is unchanged — only Qwen sets it.
        mod, calls, _ = _make_openai([_openai_completion(GOOD_JSON)])
        with _fake_modules({"openai": mod}), \
                _env(OPENAI_API_KEY="sk-test"):
            OpenAIAdapter().decide(CASE, "choice", _ctx())
        self.assertNotIn("extra_body", calls[0])


class TestAnthropicOpusReconciliation(unittest.TestCase):
    """D3: claude-opus-5-5 / claude-sonnet-5-5 route to structured
    outputs and omit temperature; the default pin is unchanged."""

    def _setup(self, model):
        mod, calls, created = _make_anthropic(
            [_anthropic_message(text=GOOD_JSON)])
        m = _fake_modules({"anthropic": mod})
        m.__enter__()
        e = _env(ANTHROPIC_API_KEY="sk-test")
        e.__enter__()
        self.addCleanup(e.__exit__, None, None, None)
        self.addCleanup(m.__exit__, None, None, None)
        return calls, created

    def test_opus_uses_output_config_not_forced_tool(self):
        for model in ("claude-opus-5-5", "claude-sonnet-5-5"):
            with self.subTest(model=model):
                calls, _ = self._setup(model)
                out = AnthropicAdapter(model=model).decide(
                    CASE, "choice", _ctx())
                self.assertEqual(out.decision, "approve")
                self.assertIn("output_config", calls[0])
                self.assertNotIn("tools", calls[0])
                self.assertNotIn("tool_choice", calls[0])

    def test_opus_omits_temperature(self):
        # Opus 4.6+ rejects temperature with a 400.
        for model in ("claude-opus-5-5", "claude-sonnet-5-5"):
            with self.subTest(model=model):
                calls, _ = self._setup(model)
                out = AnthropicAdapter(model=model).decide(
                    CASE, "choice", _ctx())
                self.assertNotIn("temperature", calls[0])
                self.assertIsNone(
                    out.transcript["request"]["temperature"])

    def test_sonnet_5_5_default_path_uses_output_config(self):
        # D3 decided 2026-10-02: default pin is claude-sonnet-5-5, which
        # routes to native output_config.format structured outputs and
        # omits temperature entirely (rejected with 400 on 5.x models).
        calls, _ = self._setup("claude-sonnet-5-5")
        out = AnthropicAdapter().decide(CASE, "choice", _ctx())
        self.assertEqual(out.usage.model, "claude-sonnet-5-5")
        self.assertIn("output_config", calls[0])
        self.assertNotIn("tools", calls[0])
        self.assertNotIn("tool_choice", calls[0])
        self.assertNotIn("temperature", calls[0])
        self.assertNotIn("extra_body", calls[0])
        self.assertIsNone(
            out.transcript["request"]["temperature"])

    def test_explicit_opt_out_still_works(self):
        # structured_outputs=False forces the legacy path even for a
        # routed model id.
        calls, _ = self._setup("claude-opus-5-5")
        AnthropicAdapter(
            model="claude-opus-5-5", structured_outputs=False).decide(
                CASE, "choice", _ctx())
        self.assertIn("tools", calls[0])
        self.assertNotIn("output_config", calls[0])


if __name__ == "__main__":
    unittest.main()
