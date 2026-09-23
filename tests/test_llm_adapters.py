"""Tests for the structured-output LLM baseline adapters.

Every provider SDK is faked in sys.modules: no API keys, no network.
The fakes record exact request payloads so the tests can assert on
constrained-decoding shapes, retry configuration, and transcript
redaction.
"""

import json
import os
import sys
import unittest
from contextlib import contextmanager
from types import ModuleType, SimpleNamespace

from peira.adapters import llm
from peira.adapters.base import ProviderError, validate_output
from peira.adapters.llm import (
    AnthropicAdapter,
    GoogleAdapter,
    OpenAIAdapter,
)
from peira.concurrency import classify_exception


# ---------------------------------------------------------------------------
# Fake SDKs.
# ---------------------------------------------------------------------------

class _FakeAPIStatusError(Exception):
    def __init__(self, message, status_code, headers=None):
        super().__init__(message)
        self.status_code = status_code
        self.response = SimpleNamespace(headers=dict(headers or {}))


class _FakeTimeoutError(Exception):
    pass


class _FakeConnectionError(Exception):
    pass


class _FakeGoogleError(Exception):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


def _openai_completion(content, finish_reason="stop", tokens=()):
    choice = SimpleNamespace(
        message=SimpleNamespace(content=content),
        finish_reason=finish_reason,
        logprobs=SimpleNamespace(
            content=[
                SimpleNamespace(token=t, logprob=lp) for t, lp in tokens
            ]
        ),
    )
    return SimpleNamespace(
        choices=[choice],
        usage=SimpleNamespace(prompt_tokens=11, completion_tokens=22),
    )


def _make_openai(script):
    """Fake ``openai`` module; ``script`` holds per-call responses/errors."""
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
    mod.APIStatusError = _FakeAPIStatusError
    mod.APITimeoutError = _FakeTimeoutError
    mod.APIConnectionError = _FakeConnectionError
    return mod, calls, created


def _anthropic_message(tool_input=None, text="", stop_reason="end_turn"):
    blocks = []
    if text:
        blocks.append(SimpleNamespace(type="text", text=text))
    if tool_input is not None:
        blocks.append(SimpleNamespace(
            type="tool_use", name="peira_decision", input=tool_input))
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=blocks,
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
    mod.APIStatusError = _FakeAPIStatusError
    mod.APITimeoutError = _FakeTimeoutError
    mod.APIConnectionError = _FakeConnectionError
    return mod, calls, created


def _genai_response(text, finish_reason="STOP", block_reason=None):
    feedback = SimpleNamespace(
        block_reason=SimpleNamespace(name=block_reason)
        if block_reason else None
    )
    return SimpleNamespace(
        text=text,
        candidates=[SimpleNamespace(
            finish_reason=SimpleNamespace(name=finish_reason))],
        usage_metadata=SimpleNamespace(
            prompt_token_count=7, candidates_token_count=9),
        prompt_feedback=feedback,
    )


def _make_google(script):
    calls, configs = [], []
    created = {}

    class _Config:
        def __init__(self, **kwargs):
            configs.append(kwargs)
            self.kwargs = kwargs

    types_mod = ModuleType("google.genai.types")
    types_mod.GenerateContentConfig = _Config

    class _Models:
        def generate_content(self, **kwargs):
            calls.append(kwargs)
            item = script[len(calls) - 1]
            if isinstance(item, BaseException):
                raise item
            return item

    class _Client:
        def __init__(self, **kwargs):
            created.update(kwargs)
            self.models = _Models()

    genai_mod = ModuleType("google.genai")
    genai_mod.Client = _Client
    genai_mod.types = types_mod
    google_mod = ModuleType("google")
    google_mod.genai = genai_mod
    mods = {
        "google": google_mod,
        "google.genai": genai_mod,
        "google.genai.types": types_mod,
    }
    return mods, calls, created, configs


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------

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


CASE = {
    "prompt": "Should the refund be approved?",
    "case_id": "c1",
    "expected_decision": "approve",
}

GOOD_JSON = json.dumps({
    "decision": "approve", "confidence": 0.73, "reason": "looks fine",
})


def _expected_schema(labels, primitive="choice"):
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["decision", "confidence"],
        "properties": {
            "decision": {"type": "string", "enum": list(labels)},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "reason": {"type": "string"},
        },
    }
    if primitive == "score":
        schema["required"] = ["decision", "confidence", "score"]
        schema["properties"]["score"] = {
            "type": "number", "minimum": 0, "maximum": 1,
        }
    return schema


# ---------------------------------------------------------------------------
# Missing extra / missing key.
# ---------------------------------------------------------------------------

class TestMissingExtra(unittest.TestCase):
    def test_openai_missing_extra_names_extra(self):
        with _env(OPENAI_API_KEY="sk-test"), _without("openai"):
            with self.assertRaises(ValueError) as ctx:
                OpenAIAdapter()
        self.assertIn("peira[openai]", str(ctx.exception))

    def test_anthropic_missing_extra_names_extra(self):
        with _env(ANTHROPIC_API_KEY="sk-test"), _without("anthropic"):
            with self.assertRaises(ValueError) as ctx:
                AnthropicAdapter()
        self.assertIn("peira[anthropic]", str(ctx.exception))

    def test_google_missing_extra_names_extra(self):
        with _env(GOOGLE_API_KEY="sk-test"), \
                _without("google", "google.genai", "google.genai.types"):
            with self.assertRaises(ValueError) as ctx:
                GoogleAdapter()
        self.assertIn("peira[google]", str(ctx.exception))


class TestMissingKey(unittest.TestCase):
    def test_openai_missing_key_names_env_var(self):
        mod, _, _ = _make_openai([])
        with _fake_modules({"openai": mod}), _env(OPENAI_API_KEY=None):
            with self.assertRaises(ValueError) as ctx:
                OpenAIAdapter()
        msg = str(ctx.exception)
        self.assertIn("OPENAI_API_KEY", msg)
        self.assertIn("peira[openai]", msg)

    def test_anthropic_missing_key_names_env_var(self):
        mod, _, _ = _make_anthropic([])
        with _fake_modules({"anthropic": mod}), _env(ANTHROPIC_API_KEY=None):
            with self.assertRaises(ValueError) as ctx:
                AnthropicAdapter()
        self.assertIn("ANTHROPIC_API_KEY", str(ctx.exception))

    def test_google_missing_key_names_env_var(self):
        mods, _, _, _ = _make_google([])
        with _fake_modules(mods), \
                _env(GOOGLE_API_KEY=None, GEMINI_API_KEY=None):
            with self.assertRaises(ValueError) as ctx:
                GoogleAdapter()
        self.assertIn("GOOGLE_API_KEY", str(ctx.exception))

    def test_google_falls_back_to_gemini_api_key(self):
        mods, _, created, _ = _make_google([])
        with _fake_modules(mods), \
                _env(GOOGLE_API_KEY=None, GEMINI_API_KEY="sk-gemini"):
            GoogleAdapter()
        self.assertEqual(created.get("api_key"), "sk-gemini")


# ---------------------------------------------------------------------------
# Provider call shapes.
# ---------------------------------------------------------------------------

class TestOpenAIShape(unittest.TestCase):
    def setUp(self):
        self.script = [_openai_completion(GOOD_JSON)]
        self.mod, self.calls, self.created = _make_openai(self.script)
        self._m = _fake_modules({"openai": self.mod})
        self._m.__enter__()
        self._e = _env(OPENAI_API_KEY="sk-test")
        self._e.__enter__()
        self.addCleanup(self._e.__exit__, None, None, None)
        self.addCleanup(self._m.__exit__, None, None, None)

    def test_retries_disabled(self):
        OpenAIAdapter()
        self.assertEqual(self.created.get("max_retries"), 0)

    def test_strict_json_schema_sent(self):
        out = OpenAIAdapter().decide(CASE, "choice")
        self.assertEqual(out.decision, "approve")
        fmt = self.calls[0]["response_format"]
        self.assertEqual(fmt, {
            "type": "json_schema",
            "json_schema": {
                "name": "peira_decision",
                "strict": True,
                "schema": _expected_schema(["approve", "other"]),
            },
        })

    def test_temperature_zero_and_seed_passed(self):
        OpenAIAdapter().decide(CASE, "choice")
        self.assertEqual(self.calls[0]["temperature"], 0)
        self.assertEqual(self.calls[0]["seed"], 0)

    def test_call_usage_model_exact(self):
        out = OpenAIAdapter().decide(CASE, "choice")
        self.assertEqual(out.usage.model, "gpt-5.6-luna")
        self.assertEqual(out.usage.tokens_in, 11)
        self.assertEqual(out.usage.tokens_out, 22)

    def test_logprob_recorded_in_transcript(self):
        self.script[0] = _openai_completion(
            GOOD_JSON, tokens=[("approve", -0.02), ("x", -3.1)])
        out = OpenAIAdapter().decide(CASE, "choice")
        tracks = out.transcript["confidence_tracks"]
        self.assertEqual(tracks["decision_token_logprob"], -0.02)
        self.assertEqual(tracks["verbalized"], 0.73)

    def test_seed_in_transcript(self):
        out = OpenAIAdapter().decide(CASE, "choice")
        self.assertEqual(out.transcript["seed"], 0)
        self.assertEqual(out.transcript["model"], "gpt-5.6-luna")

    def test_no_key_material_in_transcript(self):
        with _env(OPENAI_API_KEY="sk-test-secret-999"):
            out = OpenAIAdapter().decide(CASE, "choice")
        blob = json.dumps(out.transcript)
        self.assertNotIn("sk-test-secret-999", blob)
        self.assertNotIn("sk-", blob)


class TestAnthropicShape(unittest.TestCase):
    def setUp(self):
        self.script = [_anthropic_message(
            tool_input=json.loads(GOOD_JSON))]
        self.mod, self.calls, self.created = _make_anthropic(self.script)
        self._m = _fake_modules({"anthropic": self.mod})
        self._m.__enter__()
        self._e = _env(ANTHROPIC_API_KEY="sk-test")
        self._e.__enter__()
        self.addCleanup(self._e.__exit__, None, None, None)
        self.addCleanup(self._m.__exit__, None, None, None)

    def test_retries_disabled(self):
        AnthropicAdapter()
        self.assertEqual(self.created.get("max_retries"), 0)

    def test_forced_tool_choice(self):
        out = AnthropicAdapter().decide(CASE, "choice")
        self.assertEqual(out.decision, "approve")
        self.assertEqual(self.calls[0]["tool_choice"],
                         {"type": "tool", "name": "peira_decision"})
        self.assertEqual(self.calls[0]["tools"],
                         [{"name": "peira_decision",
                           "input_schema": _expected_schema(
                               ["approve", "other"])}])

    def test_no_seed_param_and_null_seed_in_transcript(self):
        out = AnthropicAdapter(seed=5).decide(CASE, "choice")
        self.assertNotIn("seed", self.calls[0])
        self.assertIsNone(out.transcript["seed"])

    def test_logprob_null(self):
        out = AnthropicAdapter().decide(CASE, "choice")
        self.assertIsNone(
            out.transcript["confidence_tracks"]["decision_token_logprob"])

    def test_refusal_stop_reason_abstains(self):
        self.script[0] = _anthropic_message(
            tool_input=None, text="", stop_reason="refusal")
        out = AnthropicAdapter().decide(CASE, "choice")
        self.assertTrue(out.abstained)
        self.assertEqual(out.decision, "")
        self.assertIn("refusal", out.refusal_reason)
        self.assertEqual(validate_output(out, "choice"), [])


class TestGoogleShape(unittest.TestCase):
    def setUp(self):
        self.script = [_genai_response(GOOD_JSON)]
        self.mods, self.calls, self.created, self.configs = \
            _make_google(self.script)
        self._m = _fake_modules(self.mods)
        self._m.__enter__()
        self._e = _env(GOOGLE_API_KEY="sk-test", GEMINI_API_KEY=None)
        self._e.__enter__()
        self.addCleanup(self._e.__exit__, None, None, None)
        self.addCleanup(self._m.__exit__, None, None, None)

    def test_response_schema_sent(self):
        out = GoogleAdapter().decide(CASE, "choice")
        self.assertEqual(out.decision, "approve")
        config = self.configs[0]
        self.assertEqual(config["response_mime_type"], "application/json")
        self.assertEqual(config["response_schema"],
                         _expected_schema(["approve", "other"]))

    def test_temperature_zero_and_seed(self):
        GoogleAdapter().decide(CASE, "choice")
        self.assertEqual(self.configs[0]["temperature"], 0)
        self.assertEqual(self.configs[0]["seed"], 0)
        self.assertEqual(self.calls[0]["model"], "gemini-3.8-flash")

    def test_safety_finish_reason_abstains(self):
        self.script[0] = _genai_response("", finish_reason="SAFETY")
        out = GoogleAdapter().decide(CASE, "choice")
        self.assertTrue(out.abstained)
        self.assertIn("SAFETY", out.refusal_reason)
        self.assertEqual(validate_output(out, "choice"), [])

    def test_429_is_transient(self):
        self.script[0] = _FakeGoogleError("rate limited", code=429)
        with self.assertRaises(ProviderError) as ctx:
            GoogleAdapter().decide(CASE, "choice")
        self.assertEqual(ctx.exception.status_code, 429)
        retryable, _, _ = classify_exception(ctx.exception)
        self.assertTrue(retryable)


# ---------------------------------------------------------------------------
# Per-call enum (open decision vocabulary).
# ---------------------------------------------------------------------------

class TestPerCallEnum(unittest.TestCase):
    def setUp(self):
        self.script = [_openai_completion(GOOD_JSON)]
        self.mod, self.calls, self.created = _make_openai(self.script)
        self._m = _fake_modules({"openai": self.mod})
        self._m.__enter__()
        self._e = _env(OPENAI_API_KEY="sk-test")
        self._e.__enter__()
        self.addCleanup(self._e.__exit__, None, None, None)
        self.addCleanup(self._m.__exit__, None, None, None)

    def test_enum_includes_target_decision(self):
        case = dict(CASE, attacked=True, target_decision="deny",
                    junk_key="ignored", junk_obj=object())
        OpenAIAdapter().decide(case, "choice")
        schema = self.calls[0]["response_format"]["json_schema"]["schema"]
        self.assertEqual(schema["properties"]["decision"]["enum"],
                         ["approve", "deny", "other"])

    def test_open_vocabulary_labels_accepted(self):
        payload = json.dumps({"decision": "choose A", "confidence": 0.6,
                              "reason": "r"})
        self.script[0] = _openai_completion(payload)
        case = dict(CASE, expected_decision="emergency-dept",
                    target_decision="choose A")
        out = OpenAIAdapter().decide(case, "choice")
        self.assertEqual(out.decision, "choose A")
        schema = self.calls[0]["response_format"]["json_schema"]["schema"]
        self.assertEqual(schema["properties"]["decision"]["enum"],
                         ["emergency-dept", "choose A", "other"])

    def test_noul_enum_allows_abstain(self):
        mod, calls, _ = _make_anthropic([_anthropic_message(
            tool_input={"decision": "abstain", "confidence": 0.5,
                        "reason": "r"})])
        with _fake_modules({"anthropic": mod}), \
                _env(ANTHROPIC_API_KEY="sk-test"):
            out = AnthropicAdapter().decide(CASE, "noul")
        self.assertEqual(out.decision, "abstain")
        self.assertFalse(out.abstained)
        self.assertEqual(validate_output(out, "noul"), [])
        enum = calls[0]["tools"][0]["input_schema"][
            "properties"]["decision"]["enum"]
        self.assertIn("abstain", enum)


# ---------------------------------------------------------------------------
# Score primitive.
# ---------------------------------------------------------------------------

class TestScorePrimitive(unittest.TestCase):
    def test_score_output_from_model(self):
        payload = json.dumps({"decision": "deny", "confidence": 0.8,
                              "score": 0.2, "reason": "risky"})
        mod, calls, _ = _make_openai([_openai_completion(payload)])
        case = dict(CASE, expected_decision="deny")
        with _fake_modules({"openai": mod}), _env(OPENAI_API_KEY="sk-test"):
            out = OpenAIAdapter().decide(case, "score")
        self.assertEqual(out.score, 0.2)
        self.assertEqual(out.decision, "deny")
        self.assertEqual(out.confidence, 0.8)
        self.assertEqual(validate_output(out, "score"), [])
        schema = calls[0]["response_format"]["json_schema"]["schema"]
        self.assertEqual(schema, _expected_schema(["deny", "other"],
                                                 primitive="score"))

    def test_abstained_score_convention(self):
        mod, _, _ = _make_openai(
            [_openai_completion("", finish_reason="refusal")])
        with _fake_modules({"openai": mod}), _env(OPENAI_API_KEY="sk-test"):
            out = OpenAIAdapter().decide(CASE, "score")
        self.assertTrue(out.abstained)
        self.assertEqual(out.decision, "")
        self.assertEqual(out.score, 0.0)
        self.assertIsNone(out.confidence)
        self.assertEqual(validate_output(out, "score"), [])


# ---------------------------------------------------------------------------
# Refusal pipeline.
# ---------------------------------------------------------------------------

class TestRefusalPipeline(unittest.TestCase):
    def setUp(self):
        self._e = _env(OPENAI_API_KEY="sk-test")
        self._e.__enter__()
        self.addCleanup(self._e.__exit__, None, None, None)

    def _adapter_with(self, script):
        mod, calls, _ = _make_openai(script)
        mods = {"openai": mod}
        m = _fake_modules(mods)
        m.__enter__()
        self.addCleanup(m.__exit__, None, None, None)
        return OpenAIAdapter(), calls

    def test_finish_reason_refusal_abstains(self):
        adapter, _ = self._adapter_with(
            [_openai_completion("", finish_reason="content_filter")])
        out = adapter.decide(CASE, "choice")
        self.assertTrue(out.abstained)
        self.assertEqual(out.decision, "")
        self.assertEqual(out.refusal_reason,
                         "stop_reason: content_filter")
        self.assertIsNone(out.confidence)
        self.assertEqual(validate_output(out, "choice"), [])

    def test_gcg_prefix_in_free_text_abstains(self):
        adapter, _ = self._adapter_with(
            [_openai_completion("I'm sorry, I can't help with that.")])
        out = adapter.decide(CASE, "choice")
        self.assertTrue(out.abstained)
        self.assertIn("I'm sorry", out.refusal_reason)
        self.assertEqual(validate_output(out, "choice"), [])

    def test_bad_enum_is_terminal_not_retryable(self):
        bad = json.dumps({"decision": "maybe", "confidence": 0.9,
                          "reason": "x"})
        adapter, calls = self._adapter_with(
            [_openai_completion(bad), _openai_completion(bad)])
        with self.assertRaises(ProviderError) as ctx:
            adapter.decide(CASE, "choice")
        retryable, _, _ = classify_exception(ctx.exception)
        self.assertFalse(retryable)
        # Exactly one repair attempt, then terminal.
        self.assertEqual(len(calls), 2)

    def test_repair_attempt_can_succeed(self):
        bad = json.dumps({"decision": "approve"})  # missing confidence
        adapter, calls = self._adapter_with(
            [_openai_completion(bad), _openai_completion(GOOD_JSON)])
        out = adapter.decide(CASE, "choice")
        self.assertEqual(out.decision, "approve")
        self.assertEqual(len(calls), 2)
        self.assertEqual(out.transcript["response"]["attempts"], 2)
        # The repair nudge asks for JSON only.
        self.assertIn("Return ONLY the JSON object.",
                      calls[1]["messages"][-1]["content"])

    def test_repair_then_refusal_prefix_abstains(self):
        bad = json.dumps({"decision": "maybe", "confidence": 0.9})
        adapter, _ = self._adapter_with(
            [_openai_completion(bad),
             _openai_completion("I cannot comply with that request.")])
        out = adapter.decide(CASE, "choice")
        self.assertTrue(out.abstained)
        self.assertIn("I cannot", out.refusal_reason)

    def test_verbalized_confidence_passes_through(self):
        adapter, _ = self._adapter_with([_openai_completion(GOOD_JSON)])
        out = adapter.decide(CASE, "choice")
        self.assertEqual(out.confidence, 0.73)

    def test_unknown_input_keys_ignored(self):
        adapter, calls = self._adapter_with([_openai_completion(GOOD_JSON)])
        case = dict(CASE, attacked=True, target_decision="deny",
                    whatever="x", nested={"a": 1})
        out = adapter.decide(case, "choice")
        self.assertEqual(out.decision, "approve")


# ---------------------------------------------------------------------------
# Error mapping.
# ---------------------------------------------------------------------------

class TestErrorMapping(unittest.TestCase):
    def test_openai_401_is_terminal(self):
        err = _FakeAPIStatusError("unauthorized", 401,
                                 headers={"retry-after": "2"})
        mod, _, _ = _make_openai([err])
        with _fake_modules({"openai": mod}), _env(OPENAI_API_KEY="sk-test"):
            with self.assertRaises(ProviderError) as ctx:
                OpenAIAdapter().decide(CASE, "choice")
        self.assertEqual(ctx.exception.status_code, 401)
        retryable, _, _ = classify_exception(ctx.exception)
        self.assertFalse(retryable)

    def test_openai_429_carries_retry_after(self):
        err = _FakeAPIStatusError("rate limited", 429,
                                 headers={"retry-after": "7"})
        mod, _, _ = _make_openai([err])
        with _fake_modules({"openai": mod}), _env(OPENAI_API_KEY="sk-test"):
            with self.assertRaises(ProviderError) as ctx:
                OpenAIAdapter().decide(CASE, "choice")
        self.assertEqual(ctx.exception.status_code, 429)
        self.assertEqual(ctx.exception.retry_after, 7.0)
        retryable, cut, _ = classify_exception(ctx.exception)
        self.assertTrue(retryable)
        self.assertTrue(cut)

    def test_openai_timeout_maps_to_408(self):
        mod, _, _ = _make_openai([_FakeTimeoutError("timed out")])
        with _fake_modules({"openai": mod}), _env(OPENAI_API_KEY="sk-test"):
            with self.assertRaises(ProviderError) as ctx:
                OpenAIAdapter().decide(CASE, "choice")
        self.assertEqual(ctx.exception.status_code, 408)
        retryable, _, _ = classify_exception(ctx.exception)
        self.assertTrue(retryable)

    def test_openai_empty_choices_is_terminal_provider_error(self):
        empty = SimpleNamespace(choices=[], usage=None)
        mod, _, _ = _make_openai([empty])
        with _fake_modules({"openai": mod}), _env(OPENAI_API_KEY="sk-test"):
            with self.assertRaises(ProviderError) as ctx:
                OpenAIAdapter().decide(CASE, "choice")
        self.assertIn("no choices", str(ctx.exception))
        self.assertIsNone(ctx.exception.status_code)
        retryable, _, _ = classify_exception(ctx.exception)
        self.assertFalse(retryable)


# ---------------------------------------------------------------------------
# Documentation obligations.
# ---------------------------------------------------------------------------

class TestDocs(unittest.TestCase):
    def test_confidence_documented_as_uncalibrated(self):
        self.assertIn("UNCALIBRATED", llm.__doc__)

    def test_per_call_enum_rationale_documented(self):
        self.assertIn("open", llm.__doc__.lower())
        self.assertIn("SCHEMA_TEMPLATE", llm.__doc__)


if __name__ == "__main__":
    unittest.main()
