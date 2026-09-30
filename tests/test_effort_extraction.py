
import json
import os
import sys
import unittest
from contextlib import contextmanager
from types import ModuleType, SimpleNamespace

from peira.adapters.llm import (
    AnthropicAdapter,
    GoogleAdapter,
    OpenAIAdapter,
)


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


def _make_openai(response):
    class _Completions:
        def create(self, **kwargs):
            return response

    class _Chat:
        def __init__(self):
            self.completions = _Completions()

    class _Client:
        def __init__(self, **kwargs):
            self.chat = _Chat()

    mod = ModuleType("openai")
    mod.OpenAI = _Client
    return {"openai": mod}


def _openai_response(reasoning_tokens):
    return SimpleNamespace(
        choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(
                {"decision": "approve", "confidence": 0.7,
                 "reason": "ok"})),
            finish_reason="stop",
            logprobs=None,
        )],
        usage=SimpleNamespace(
            prompt_tokens=11, completion_tokens=40,
            completion_tokens_details=SimpleNamespace(
                reasoning_tokens=reasoning_tokens),
        ),
    )


def _make_anthropic(response):
    class _Messages:
        def create(self, **kwargs):
            return response

    class _Client:
        def __init__(self, **kwargs):
            self.messages = _Messages()

    mod = ModuleType("anthropic")
    mod.Anthropic = _Client
    return {"anthropic": mod}


def _anthropic_response(thinking_tokens):
    return SimpleNamespace(
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text=json.dumps(
            {"decision": "approve", "confidence": 0.7, "reason": "ok"}))],
        usage=SimpleNamespace(
            input_tokens=13, output_tokens=40,
            output_tokens_details=SimpleNamespace(
                thinking_tokens=thinking_tokens),
        ),
    )


def _make_google(response):
    class _Config:
        def __init__(self, **kwargs):
            pass

    class _ThinkingConfig:
        def __init__(self, **kwargs):
            pass

    types_mod = ModuleType("google.genai.types")
    types_mod.GenerateContentConfig = _Config
    types_mod.ThinkingConfig = _ThinkingConfig

    class _Models:
        def generate_content(self, **kwargs):
            return response

    class _Client:
        def __init__(self, **kwargs):
            self.models = _Models()

    genai_mod = ModuleType("google.genai")
    genai_mod.Client = _Client
    genai_mod.types = types_mod
    google_mod = ModuleType("google")
    google_mod.genai = genai_mod
    return {"google": google_mod, "google.genai": genai_mod,
            "google.genai.types": types_mod}


def _google_response(thoughts_token_count):
    return SimpleNamespace(
        text=json.dumps({"decision": "approve", "confidence": 0.7,
                         "reason": "ok"}),
        candidates=[SimpleNamespace(
            finish_reason=SimpleNamespace(name="STOP"))],
        usage_metadata=SimpleNamespace(
            prompt_token_count=7, candidates_token_count=40,
            thoughts_token_count=thoughts_token_count),
        prompt_feedback=SimpleNamespace(block_reason=None),
    )


class TestReasoningTokenExtraction(unittest.TestCase):
    """Reasoning/thinking tokens are extracted from provider responses
    and carried on the raw result (a subset of tokens_out, never
    double-counted in pricing)."""

    def test_openai_extracts_reasoning_tokens(self):
        with _fake_modules(_make_openai(_openai_response(17))):
            adapter = OpenAIAdapter(api_key="k")
            raw = adapter._request("text", {"type": "object"}, repair=False)
        self.assertEqual(raw.reasoning_tokens, 17)
        self.assertEqual(raw.tokens_out, 40)

    def test_openai_missing_details_gives_none(self):
        resp = _openai_response(17)
        resp.usage.completion_tokens_details = None
        with _fake_modules(_make_openai(resp)):
            adapter = OpenAIAdapter(api_key="k")
            raw = adapter._request("text", {"type": "object"}, repair=False)
        self.assertIsNone(raw.reasoning_tokens)

    def test_anthropic_extracts_thinking_tokens(self):
        with _fake_modules(_make_anthropic(_anthropic_response(23))):
            adapter = AnthropicAdapter(api_key="k")
            raw = adapter._request("text", {"type": "object"}, repair=False)
        self.assertEqual(raw.reasoning_tokens, 23)
        self.assertEqual(raw.tokens_out, 40)

    def test_google_extracts_thought_tokens(self):
        with _fake_modules(_make_google(_google_response(31))):
            adapter = GoogleAdapter(api_key="k")
            raw = adapter._request("text", {"type": "object"}, repair=False)
        self.assertEqual(raw.reasoning_tokens, 31)
        self.assertEqual(raw.tokens_out, 40)

    def test_usage_carries_reasoning_tokens(self):
        # The raw result flows into CallUsage via _usage.
        with _fake_modules(_make_openai(_openai_response(17))):
            adapter = OpenAIAdapter(api_key="k")
            raw = adapter._request("text", {"type": "object"}, repair=False)
            usage = adapter._usage(raw, 0.0)
        self.assertEqual(usage.reasoning_tokens, 17)
        self.assertEqual(usage.tokens_out, 40)


if __name__ == "__main__":
    unittest.main()
