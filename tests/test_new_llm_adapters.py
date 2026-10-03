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
                if cls is ZaiAdapter:
                    # Zhipu ignores json_schema response_format; Zai
                    # sends json_object with the schema in the prompt
                    # (see TestZaiJsonObjectMode).
                    continue
                if cls is DeepSeekAdapter:
                    # DeepSeek 400s on json_schema response_format;
                    # DeepSeek sends json_object with the schema in the
                    # prompt (see TestDeepSeekJsonObjectMode).
                    continue
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
        # ``thinking`` is not an OpenAI SDK kwarg — it must travel in
        # ``extra_body`` or the SDK raises TypeError before the request
        # ever reaches DeepSeek.
        self.assertNotIn("thinking", calls[0])
        self.assertEqual(
            (calls[0].get("extra_body") or {}).get("thinking"),
            {"type": "disabled"},
        )

    def test_openai_does_not_send_thinking(self):
        # The base OpenAI adapter is unchanged — only DeepSeek sets it.
        mod, calls, _ = _make_openai([_openai_completion(GOOD_JSON)])
        with _fake_modules({"openai": mod}), \
                _env(OPENAI_API_KEY="sk-test"):
            OpenAIAdapter().decide(CASE, "choice", _ctx())
        self.assertNotIn("thinking", calls[0])

    def test_thinking_recorded_in_transcript(self):
        # The thinking kill-switch is load-bearing — the transcript
        # must describe it, not just the wire kwargs.
        mod, calls, _ = _make_openai([_openai_completion(GOOD_JSON)])
        with _fake_modules({"openai": mod}), \
                _env(DEEPSEEK_API_KEY="sk-test"):
            out = DeepSeekAdapter().decide(CASE, "choice", _ctx())
        self.assertEqual(
            out.transcript["request"].get("thinking"),
            {"type": "disabled"},
        )


class TestDeepSeekJsonObjectMode(unittest.TestCase):
    """DeepSeek rejects json_schema response_format (400): the adapter
    sends json_object and inlines the schema in the system prompt."""

    def _setup(self, **adapter_kwargs):
        mod, calls, _ = _make_openai([_openai_completion(GOOD_JSON)])
        with _fake_modules({"openai": mod}), \
                _env(DEEPSEEK_API_KEY="sk-test"):
            adapter = DeepSeekAdapter(**adapter_kwargs)
            out = adapter.decide(CASE, "choice", _ctx())
        return calls, out, adapter

    def test_response_format_is_json_object_not_json_schema(self):
        # Live smoke 2026-10-03: api.deepseek.com 400s
        # "This response_format type is unavailable now" on the
        # json_schema block — json_object is the only structured mode
        # DeepSeek accepts.
        calls, _, _ = self._setup()
        self.assertEqual(calls[0]["response_format"], {"type": "json_object"})

    def test_system_prompt_inlines_schema(self):
        # With no server-side schema enforcement, the model only knows
        # the required keys if the prompt tells it. The decision enum
        # must be present — it is injected per call from the labels.
        calls, _, _ = self._setup()
        system = calls[0]["messages"][0]["content"]
        self.assertEqual(calls[0]["messages"][0]["role"], "system")
        for key in ("decision", "confidence", "reason"):
            self.assertIn(f'"{key}"', system)
        self.assertIn("approve", system)
        self.assertIn("deny", system)

    def test_transcript_records_json_object_mode(self):
        # The transcript must never claim strict json_schema
        # enforcement for this adapter — the override records what was
        # actually sent.
        _, out, _ = self._setup()
        self.assertEqual(
            out.transcript["request"]["response_format"],
            "json_object:prompt-inlined-schema",
        )


class TestXAISeedHandling(unittest.TestCase):
    """xAI 400s on non-positive seeds: the adapter omits, not negotiates."""

    def _setup(self, **adapter_kwargs):
        mod, calls, _ = _make_openai([_openai_completion(GOOD_JSON)])
        with _fake_modules({"openai": mod}), _env(XAI_API_KEY="sk-test"):
            out = XAIAdapter(**adapter_kwargs).decide(CASE, "choice", _ctx())
        return calls, out

    def test_seed_zero_omitted_from_wire(self):
        # Live smoke CG-0027: xAI 400s "Seed must be positive but
        # seed = 0" on the default seed=0, so it must not go on the wire.
        calls, out = self._setup()
        self.assertNotIn("seed", calls[0])
        # The transcript's request shape reads back from the actually
        # sent kwargs, so it honestly records the omission.
        self.assertIsNone(out.transcript["request"]["seed"])
        # The top-level transcript seed agrees: nothing was sent.
        self.assertIsNone(out.transcript["seed"])

    def test_seed_none_omitted_from_wire(self):
        calls, out = self._setup(seed=None)
        self.assertNotIn("seed", calls[0])
        self.assertIsNone(out.transcript["request"]["seed"])
        self.assertIsNone(out.transcript["seed"])

    def test_negative_seed_omitted_from_wire(self):
        calls, out = self._setup(seed=-7)
        self.assertNotIn("seed", calls[0])
        self.assertIsNone(out.transcript["request"]["seed"])
        self.assertIsNone(out.transcript["seed"])

    def test_positive_seed_still_sent(self):
        # xAI documents seed as supported (best-effort deterministic):
        # positive seeds go on the wire, preserving the M-7 protocol.
        calls, out = self._setup(seed=42)
        self.assertEqual(calls[0]["seed"], 42)
        self.assertEqual(out.transcript["request"]["seed"], 42)
        self.assertEqual(out.transcript["seed"], 42)

    def test_decode_params_agrees_with_wire(self):
        # decode_params is sealed into run artifacts as "actually sent":
        # it must not claim a seed the wire omitted.
        mod, _, _ = _make_openai([])
        with _fake_modules({"openai": mod}), _env(XAI_API_KEY="sk-test"):
            self.assertIsNone(XAIAdapter().decode_params["seed"])
            self.assertIsNone(XAIAdapter(seed=None).decode_params["seed"])
            self.assertEqual(XAIAdapter(seed=42).decode_params["seed"], 42)

    def test_openai_still_sends_seed_zero(self):
        # The base OpenAI adapter is unchanged: only xAI omits.
        mod, calls, _ = _make_openai([_openai_completion(GOOD_JSON)])
        with _fake_modules({"openai": mod}), \
                _env(OPENAI_API_KEY="sk-test"):
            out = OpenAIAdapter().decide(CASE, "choice", _ctx())
        self.assertEqual(calls[0]["seed"], 0)
        self.assertEqual(out.transcript["request"]["seed"], 0)
        self.assertEqual(out.transcript["seed"], 0)


class TestXAISeedHandling(unittest.TestCase):
    """xAI 400s on non-positive seeds: the adapter omits, not negotiates."""

    def _setup(self, **adapter_kwargs):
        mod, calls, _ = _make_openai([_openai_completion(GOOD_JSON)])
        with _fake_modules({"openai": mod}), _env(XAI_API_KEY="sk-test"):
            out = XAIAdapter(**adapter_kwargs).decide(CASE, "choice", _ctx())
        return calls, out

    def test_seed_zero_omitted_from_wire(self):
        # Live smoke CG-0027: xAI 400s "Seed must be positive but
        # seed = 0" on the default seed=0, so it must not go on the wire.
        calls, out = self._setup()
        self.assertNotIn("seed", calls[0])
        # The transcript's request shape reads back from the actually
        # sent kwargs, so it honestly records the omission.
        self.assertIsNone(out.transcript["request"]["seed"])
        # The top-level transcript seed agrees: nothing was sent.
        self.assertIsNone(out.transcript["seed"])

    def test_seed_none_omitted_from_wire(self):
        calls, out = self._setup(seed=None)
        self.assertNotIn("seed", calls[0])
        self.assertIsNone(out.transcript["request"]["seed"])
        self.assertIsNone(out.transcript["seed"])

    def test_negative_seed_omitted_from_wire(self):
        calls, out = self._setup(seed=-7)
        self.assertNotIn("seed", calls[0])
        self.assertIsNone(out.transcript["request"]["seed"])
        self.assertIsNone(out.transcript["seed"])

    def test_positive_seed_still_sent(self):
        # xAI documents seed as supported (best-effort deterministic):
        # positive seeds go on the wire, preserving the M-7 protocol.
        calls, out = self._setup(seed=42)
        self.assertEqual(calls[0]["seed"], 42)
        self.assertEqual(out.transcript["request"]["seed"], 42)
        self.assertEqual(out.transcript["seed"], 42)

    def test_decode_params_agrees_with_wire(self):
        # decode_params is sealed into run artifacts as "actually sent":
        # it must not claim a seed the wire omitted.
        mod, _, _ = _make_openai([])
        with _fake_modules({"openai": mod}), _env(XAI_API_KEY="sk-test"):
            self.assertIsNone(XAIAdapter().decode_params["seed"])
            self.assertIsNone(XAIAdapter(seed=None).decode_params["seed"])
            self.assertEqual(XAIAdapter(seed=42).decode_params["seed"], 42)

    def test_openai_still_sends_seed_zero(self):
        # The base OpenAI adapter is unchanged: only xAI omits.
        mod, calls, _ = _make_openai([_openai_completion(GOOD_JSON)])
        with _fake_modules({"openai": mod}), \
                _env(OPENAI_API_KEY="sk-test"):
            out = OpenAIAdapter().decide(CASE, "choice", _ctx())
        self.assertEqual(calls[0]["seed"], 0)
        self.assertEqual(out.transcript["request"]["seed"], 0)
        self.assertEqual(out.transcript["seed"], 0)


class TestZaiJsonObjectMode(unittest.TestCase):
    """Zhipu ignores json_schema response_format: the adapter sends
    json_object and inlines the schema in the system prompt."""

    def _setup(self, **adapter_kwargs):
        mod, calls, _ = _make_openai([_openai_completion(GOOD_JSON)])
        with _fake_modules({"openai": mod}), _env(ZAI_API_KEY="sk-test"):
            adapter = ZaiAdapter(**adapter_kwargs)
            out = adapter.decide(CASE, "choice", _ctx())
        return calls, out, adapter

    def test_response_format_is_json_object_not_json_schema(self):
        # Live smoke 2026-10-02: open.bigmodel.cn silently ignores the
        # json_schema block (no 400) — the model never sees the schema
        # and every call fails client-side validation. json_object is
        # the only structured mode Zhipu documents.
        calls, _, _ = self._setup()
        self.assertEqual(calls[0]["response_format"], {"type": "json_object"})

    def test_system_prompt_inlines_schema(self):
        # With no server-side schema enforcement, the model only knows
        # the required keys if the prompt tells it. The decision enum
        # must be present — it is injected per call from the labels.
        calls, _, _ = self._setup()
        system = calls[0]["messages"][0]["content"]
        self.assertEqual(calls[0]["messages"][0]["role"], "system")
        for key in ("decision", "confidence", "reason"):
            self.assertIn(f'"{key}"', system)
        self.assertIn("approve", system)
        self.assertIn("deny", system)

    def test_transcript_records_json_object_mode(self):
        # The transcript must never claim strict json_schema
        # enforcement for this adapter — the override records what was
        # actually sent.
        _, out, _ = self._setup()
        self.assertEqual(
            out.transcript["request"]["response_format"],
            "json_object:prompt-inlined-schema",
        )

    def test_openai_still_sends_strict_json_schema(self):
        # The base OpenAI adapter is unchanged: only Zai downgrades.
        mod, calls, _ = _make_openai([_openai_completion(GOOD_JSON)])
        with _fake_modules({"openai": mod}), \
                _env(OPENAI_API_KEY="sk-test"):
            out = OpenAIAdapter().decide(CASE, "choice", _ctx())
        rf = calls[0]["response_format"]
        self.assertEqual(rf["type"], "json_schema")
        self.assertTrue(rf["json_schema"]["strict"])
        self.assertIn("json_schema", out.transcript["request"]["response_format"])


if __name__ == "__main__":
    unittest.main()
