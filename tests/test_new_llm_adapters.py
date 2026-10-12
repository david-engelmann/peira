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
    MiniMaxAdapter,
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


class TestDeepSeekScoreNormalization(unittest.TestCase):
    """DeepSeek's best-effort json_object mode sometimes emits
    confidence/score on a 0-100 scale (observed 2026-10-04). The adapter
    normalizes (1, 100] to 0-1 before validation; anything else is left
    for the schema to reject."""

    def _decide(self, payload):
        mod, _, _ = _make_openai([_openai_completion(json.dumps(payload))])
        with _fake_modules({"openai": mod}), \
                _env(DEEPSEEK_API_KEY="sk-test"):
            return DeepSeekAdapter().decide(CASE, "choice", _ctx())

    def test_confidence_0_to_1_unchanged(self):
        out = self._decide(
            {"decision": "approve", "confidence": 0.95, "reason": "ok"})
        self.assertAlmostEqual(out.confidence, 0.95)

    def test_confidence_100_scale_normalized(self):
        out = self._decide(
            {"decision": "approve", "confidence": 95, "reason": "ok"})
        self.assertAlmostEqual(out.confidence, 0.95)

    def test_confidence_out_of_range_still_rejected(self):
        # 150 is not a plausible 0-100 slip — _resolve must still report
        # validation errors (not silently rescale). The decide() repair
        # path then raises ProviderError after two failures.
        from peira.adapters.llm import _validate_schema_object, _build_schema
        schema = _build_schema(["approve", "deny"], "choice")
        obj = {"decision": "approve", "confidence": 150, "reason": "ok"}
        # Normalization leaves it alone...
        from peira.adapters.llm import _normalize_verbalized_scales
        self.assertEqual(_normalize_verbalized_scales(obj)["confidence"], 150)
        # ...so validation still fails.
        errors = _validate_schema_object(obj, schema)
        self.assertTrue(any("confidence" in e for e in errors))

    def test_normalize_helper_boundaries(self):
        from peira.adapters.llm import _normalize_verbalized_scales
        # 0-1 passes through untouched.
        self.assertEqual(
            _normalize_verbalized_scales({"confidence": 0.95}),
            {"confidence": 0.95})
        self.assertEqual(
            _normalize_verbalized_scales({"confidence": 0}),
            {"confidence": 0})
        self.assertEqual(
            _normalize_verbalized_scales({"confidence": 1}),
            {"confidence": 1})
        # (1, 100] normalizes.
        self.assertEqual(
            _normalize_verbalized_scales({"confidence": 95}),
            {"confidence": 0.95})
        self.assertEqual(
            _normalize_verbalized_scales({"confidence": 100}),
            {"confidence": 1.0})
        # Out of range left alone for validation to reject.
        self.assertEqual(
            _normalize_verbalized_scales({"confidence": 150}),
            {"confidence": 150})
        self.assertEqual(
            _normalize_verbalized_scales({"confidence": -5}),
            {"confidence": -5})
        # Bools are not numbers for this purpose — never rescale.
        self.assertEqual(
            _normalize_verbalized_scales({"confidence": True}),
            {"confidence": True})
        # Score gets the same treatment.
        self.assertEqual(
            _normalize_verbalized_scales({"score": 73}),
            {"score": 0.73})
        # Input dict is not mutated.
        src = {"confidence": 95}
        _normalize_verbalized_scales(src)
        self.assertEqual(src, {"confidence": 95})


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


class TestZaiScoreNormalization(unittest.TestCase):
    """glm-4-plus sometimes emits confidence/score on a 0-100 scale
    despite the prompt-inlined 0-1 schema (observed 2026-10-07 in the
    v2 trial: 316 of 317 zai transcript errors were "'score' N above
    maximum 1"). The adapter normalizes (1, 100] to 0-1 before
    validation, the same repair DeepSeekAdapter runs."""

    def _decide(self, payload, primitive="choice"):
        mod, _, _ = _make_openai([_openai_completion(json.dumps(payload))])
        with _fake_modules({"openai": mod}), _env(ZAI_API_KEY="sk-test"):
            return ZaiAdapter().decide(CASE, primitive, _ctx())

    def test_confidence_100_scale_normalized(self):
        out = self._decide(
            {"decision": "approve", "confidence": 85, "reason": "ok"})
        self.assertAlmostEqual(out.confidence, 0.85)

    def test_score_100_scale_normalized(self):
        # The trial's dominant failure shape: score 15 for N in
        # {15, 20, 25, 85, 90, 92, 95, 100}.
        out = self._decide(
            {"decision": "deny", "confidence": 0.8, "score": 15,
             "reason": "risky"}, primitive="score")
        self.assertAlmostEqual(out.score, 0.15)
        self.assertAlmostEqual(out.confidence, 0.8)

    def test_confidence_0_to_1_unchanged(self):
        out = self._decide(
            {"decision": "approve", "confidence": 0.85, "reason": "ok"})
        self.assertAlmostEqual(out.confidence, 0.85)

    def test_out_of_range_still_rejected(self):
        # 150 is not a plausible 0-100 slip. The repair must leave it
        # for validation to reject, not silently rescale it.
        from peira.adapters.llm import (
            _normalize_verbalized_scales,
            _validate_schema_object,
            _build_schema,
        )
        obj = {"decision": "approve", "confidence": 150, "reason": "ok"}
        self.assertEqual(_normalize_verbalized_scales(obj)["confidence"], 150)
        schema = _build_schema(["approve", "deny"], "choice")
        errors = _validate_schema_object(obj, schema)
        self.assertTrue(any("confidence" in e for e in errors))


# ---------------------------------------------------------------------------
# MiniMax: stdlib urllib transport, faked at the urlopen seam.
# ---------------------------------------------------------------------------

class _FakeHTTPResponse:
    """Minimal stand-in for the object urllib.request.urlopen returns."""

    def __init__(self, body):
        self._raw = json.dumps(body).encode("utf-8")
        self.headers = {}

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _minimax_tool_body(arguments, finish_reason="tool_calls"):
    return {
        "choices": [{
            "finish_reason": finish_reason,
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "type": "function",
                    "function": {"name": "peira_decision",
                                 "arguments": arguments},
                }],
            },
        }],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20},
    }


class TestMiniMaxAdapter(unittest.TestCase):
    """MiniMax M3 through the OpenAI-compatible endpoint. The verdict
    travels as a forced tool call; thinking is disabled in the payload
    and think tags are stripped defensively. All transport is faked
    by patching urllib.request.urlopen."""

    def _decide(self, body, **adapter_kwargs):
        from unittest import mock

        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["payload"] = json.loads(req.data.decode("utf-8"))
            captured["authorization"] = req.get_header("Authorization")
            captured["timeout"] = timeout
            return _FakeHTTPResponse(body)

        adapter_kwargs.setdefault("api_key", "test-key")
        with mock.patch("urllib.request.urlopen", fake_urlopen):
            out = MiniMaxAdapter(**adapter_kwargs).decide(
                CASE, "choice", _ctx())
        return out, captured

    def test_tool_call_verdict_parsed(self):
        body = _minimax_tool_body(json.dumps(
            {"decision": "approve", "confidence": 0.9, "reason": "clear"}))
        out, _ = self._decide(body)
        self.assertEqual(out.decision, "approve")
        self.assertAlmostEqual(out.confidence, 0.9)
        self.assertEqual(out.usage.tokens_in, 100)
        self.assertEqual(out.usage.tokens_out, 20)

    def test_request_payload_shape(self):
        body = _minimax_tool_body(json.dumps(
            {"decision": "approve", "confidence": 0.9, "reason": "clear"}))
        _, captured = self._decide(body)
        self.assertEqual(
            captured["url"], "https://api.minimax.io/v1/chat/completions")
        self.assertEqual(captured["authorization"], "Bearer test-key")
        payload = captured["payload"]
        self.assertEqual(payload["model"], "MiniMax-M3")
        # The verdict travels as a forced function tool, never as
        # response_format (unreliable on this endpoint).
        self.assertNotIn("response_format", payload)
        self.assertEqual(payload["tools"][0]["function"]["name"],
                         "peira_decision")
        self.assertEqual(payload["tool_choice"],
                         {"type": "function",
                          "function": {"name": "peira_decision"}})
        # Thinking is disabled in the payload, and no logprobs are
        # requested (the endpoint exposes no token logprobs).
        self.assertEqual(payload["thinking"], {"type": "disabled"})
        self.assertNotIn("logprobs", payload)
        self.assertEqual(payload["seed"], 0)
        self.assertEqual(payload["max_tokens"], 512)

    def test_transcript_records_shape_honestly(self):
        body = _minimax_tool_body(json.dumps(
            {"decision": "approve", "confidence": 0.9, "reason": "clear"}))
        out, _ = self._decide(body)
        req = out.transcript["request"]
        self.assertEqual(req["response_format"],
                         "tool_call:peira_decision:forced")
        self.assertEqual(req["thinking"], "disabled")
        self.assertEqual(req["transport"], "urllib")
        self.assertIs(req["logprobs"], False)
        self.assertEqual(req["base_url"], "https://api.minimax.io/v1")
        self.assertTrue(
            out.transcript["response"]["tool_call_parsed"])

    def test_think_tags_stripped_before_text_fallback(self):
        # No tool call: the model answered in text with its reasoning
        # inline. The think block carries a JSON-shaped draft verdict;
        # the real verdict follows it. Without stripping, the extractor
        # would parse the draft.
        text = ('<think>{"decision": "deny", "confidence": 0.1, '
                '"reason": "draft"}</think>'
                '{"decision": "approve", "confidence": 0.9, '
                '"reason": "clear"}')
        body = {
            "choices": [{"finish_reason": "stop",
                         "message": {"role": "assistant",
                                     "content": text}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20},
        }
        out, _ = self._decide(body)
        self.assertEqual(out.decision, "approve")
        self.assertAlmostEqual(out.confidence, 0.9)

    def test_reason_typo_and_scale_slip_repaired_together(self):
        # Observed 2026-10-09 in the v2 trial: M3 typos the 'reason'
        # key ('rereason') and emits confidence on a 0-100 scale. The
        # two repairs compose in _resolve.
        body = _minimax_tool_body(json.dumps(
            {"decision": "approve", "confidence": 85,
             "rereason": "solid"}))
        out, _ = self._decide(body)
        self.assertEqual(out.decision, "approve")
        self.assertAlmostEqual(out.confidence, 0.85)

    def test_base_resp_rate_limit_maps_to_429(self):
        from peira.adapters.base import ProviderError
        body = {"base_resp": {"status_code": 1002,
                              "status_msg": "rate limit exceeded"}}
        with self.assertRaises(ProviderError) as ctx:
            self._decide(body)
        self.assertEqual(ctx.exception.status_code, 429)

    def test_base_resp_auth_failure_maps_to_401(self):
        from peira.adapters.base import ProviderError
        body = {"base_resp": {"status_code": 1004,
                              "status_msg": "authentication failed"}}
        with self.assertRaises(ProviderError) as ctx:
            self._decide(body)
        self.assertEqual(ctx.exception.status_code, 401)

    def test_default_model_is_pinned(self):
        with _env(MINIMAX_API_KEY="sk-test"):
            adapter = MiniMaxAdapter()
        self.assertEqual(adapter.name, "minimax-structured")
        self.assertEqual(adapter.version, "MiniMax-M3")

    def test_missing_key_names_own_env_var(self):
        with _env(MINIMAX_API_KEY=None):
            with self.assertRaises(ValueError) as ctx:
                MiniMaxAdapter()
        self.assertIn("MINIMAX_API_KEY", str(ctx.exception))


class TestStripThink(unittest.TestCase):
    def test_strips_blocks(self):
        from peira.adapters.llm import _strip_think
        self.assertEqual(
            _strip_think("<think>draft</think>final"), "final")
        self.assertEqual(
            _strip_think("<think>a</think>mid<think>b</think>end"),
            "midend")
        self.assertEqual(_strip_think("plain"), "plain")

    def test_case_insensitive_and_non_string(self):
        from peira.adapters.llm import _strip_think
        self.assertEqual(_strip_think("<THINK>x</THINK>y"), "y")
        self.assertEqual(_strip_think(None), "")
        self.assertEqual(_strip_think(42), "")


if __name__ == "__main__":
    unittest.main()


def test_meta_llama_api_key_fallback_resolution():
    """MetaLlamaAdapter resolves LLAMA_API_KEY when META_API_KEY is absent.

    Exercises _StructuredLLMBase._resolve_api_key directly: with only
    LLAMA_API_KEY set, the adapter must pick it up (Meta's official
    convention). With both set, META_API_KEY wins (documented order).
    """
    import os
    from unittest.mock import patch
    from peira.adapters.llm import MetaLlamaAdapter

    adapter = MetaLlamaAdapter.__new__(MetaLlamaAdapter)

    # Fallback: only LLAMA_API_KEY set.
    with patch.dict(os.environ, {"LLAMA_API_KEY": "llama-key"}, clear=True):
        assert adapter._resolve_api_key(None) == "llama-key"

    # Primary wins when both are set.
    with patch.dict(
        os.environ,
        {"META_API_KEY": "meta-key", "LLAMA_API_KEY": "llama-key"},
        clear=True,
    ):
        assert adapter._resolve_api_key(None) == "meta-key"

    # Explicit api_key arg beats both env vars.
    with patch.dict(
        os.environ,
        {"META_API_KEY": "meta-key", "LLAMA_API_KEY": "llama-key"},
        clear=True,
    ):
        assert adapter._resolve_api_key("explicit") == "explicit"


class TestOpenAIMaxCompletionTokens(unittest.TestCase):
    """gpt-5.6-luna rejects ``max_tokens`` (400 "Unsupported
    parameter"): the adapter sends ``max_completion_tokens`` for it,
    and keeps ``max_tokens`` for other OpenAI models."""

    def _setup(self, **adapter_kwargs):
        mod, calls, _ = _make_openai([_openai_completion(GOOD_JSON)])
        with _fake_modules({"openai": mod}), \
                _env(OPENAI_API_KEY="sk-test"):
            adapter = OpenAIAdapter(**adapter_kwargs)
            out = adapter.decide(CASE, "choice", _ctx())
        return calls, out

    def test_gpt_5_6_luna_sends_max_completion_tokens(self):
        # Default pin is gpt-5.6-luna (see api_pins.py) — the live
        # endpoint 400s on max_tokens for this model (Audit 5/5
        # pilot-verification, 2026-10-03), so the wire must carry the
        # renamed field instead.
        calls, _ = self._setup()
        self.assertEqual(calls[0]["model"], "gpt-5.6-luna")
        self.assertEqual(calls[0]["max_completion_tokens"], 512)
        self.assertNotIn("max_tokens", calls[0])

    def test_other_models_still_send_max_tokens(self):
        # Only models in _MAX_COMPLETION_TOKENS_MODELS get the renamed
        # field; everything else keeps the legacy field.
        calls, _ = self._setup(model="gpt-4o")
        self.assertEqual(calls[0]["max_tokens"], 512)
        self.assertNotIn("max_completion_tokens", calls[0])

    def test_transcript_records_which_field_was_sent(self):
        # The transcript must agree with the wire: max_completion_tokens
        # present and max_tokens absent for the renamed model.
        _, out = self._setup()
        req = out.transcript["request"]
        self.assertEqual(req["max_completion_tokens"], 512)
        self.assertIsNone(req["max_tokens"])
