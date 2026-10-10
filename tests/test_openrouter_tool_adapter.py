"""Tests for the OpenRouter tool-calling adapter.

``OpenRouterToolAdapter`` drives the OpenRouter gateway with forced
tool calling instead of ``response_format`` JSON schema, for gateway
models that ignore the translated schema and answer in free text
(observed 2026-10-09: ``inclusionai/ling-3.0-flash`` and
``inclusionai/ling-3.0-flash-vl`` ignored ``response_format`` on ~22%
of trial calls). The ``openai`` SDK is faked in sys.modules: no API
keys, no network.

The fakes record exact client-construction kwargs and request payloads
so the tests can assert the forced tool-call shape, the tool-choice
pin, the pre-parsed verdict path, the text fallback, and the
verdict repairs (0-100 scale normalization and the ``reason`` key
typos).
"""

import json
import os
import sys
import unittest
from contextlib import contextmanager
from types import ModuleType, SimpleNamespace

from peira.adapters.llm import (
    OpenRouterAdapter,
    OpenRouterToolAdapter,
    SCHEMA_NAME,
    _RawResult,
)
from peira.adapters.base import CallContext, ProviderError


# ---------------------------------------------------------------------------
# Fake openai SDK (mirrors tests/test_openrouter_adapter.py).
# ---------------------------------------------------------------------------

def _openai_tool_completion(arguments, finish_reason="tool_calls",
                            content=""):
    """A chat completion whose verdict arrives as tool-call arguments."""
    fn = SimpleNamespace(name=SCHEMA_NAME, arguments=arguments)
    tc = SimpleNamespace(type="function", function=fn)
    choice = SimpleNamespace(
        message=SimpleNamespace(content=content, tool_calls=[tc]),
        finish_reason=finish_reason,
        logprobs=SimpleNamespace(content=[]),
    )
    return SimpleNamespace(
        choices=[choice],
        usage=SimpleNamespace(prompt_tokens=11, completion_tokens=22),
    )


def _openai_text_completion(content, finish_reason="stop"):
    """A chat completion with no tool calls (text fallback path)."""
    choice = SimpleNamespace(
        message=SimpleNamespace(content=content, tool_calls=None),
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

TOOL_ARGS = json.dumps({
    "decision": "approve", "confidence": 0.73, "reason": "looks fine",
})

# Minimal schema mirroring _build_schema for direct _resolve tests.
SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {
            "type": "string", "enum": ["approve", "deny", "other"],
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "reason": {"type": "string"},
    },
    "required": ["decision", "confidence", "reason"],
}


def _ctx(**over):
    """Opaque adapter-visible context (B2): a call id, nothing else."""
    return CallContext(call_id=over.get("call_id", "call-test"))


def _raw(parsed=None, text=""):
    return _RawResult(
        text=text,
        stop_reason="stop",
        parsed=parsed,
        tokens_in=11,
        tokens_out=22,
        logprob_tokens=None,
        request_shape={},
        response_shape={},
    )


class _ToolHarness(unittest.TestCase):
    def setUp(self):
        self.mod, self.calls, self.created = _make_openai(
            [_openai_tool_completion(TOOL_ARGS)])
        self._m = _fake_modules({"openai": self.mod})
        self._m.__enter__()
        self._e = _env(OPENROUTER_API_KEY="<redacted>")
        self._e.__enter__()
        self.addCleanup(self._e.__exit__, None, None, None)
        self.addCleanup(self._m.__exit__, None, None, None)

    def adapter(self, **kw):
        kw.setdefault("model", "inclusionai/ling-3.0-flash")
        return OpenRouterToolAdapter(**kw)


# ---------------------------------------------------------------------------
# Construction: subclass of the gateway adapter, distinct cache identity.
# ---------------------------------------------------------------------------

class TestOpenRouterToolConstruction(_ToolHarness):
    def test_name_is_distinct(self):
        # The behavioral property that matters: the tool variant's
        # cache namespace can never equal the response_format
        # adapter's for the same model id.
        self.assertNotEqual(
            OpenRouterToolAdapter.name, OpenRouterAdapter.name)

    def test_inherits_gateway_transport(self):
        self.assertTrue(issubclass(OpenRouterToolAdapter, OpenRouterAdapter))
        adapter = self.adapter()
        self.assertEqual(adapter._base_url, "https://openrouter.ai/api/v1")
        # Client construction kwargs mirror the parent: gateway host,
        # no retries, app-identification headers.
        self.assertEqual(
            self.created.get("base_url"), "https://openrouter.ai/api/v1")
        self.assertEqual(self.created.get("max_retries"), 0)
        headers = self.created.get("default_headers") or {}
        self.assertEqual(headers.get("HTTP-Referer"), "https://peiratrial.dev")
        self.assertEqual(headers.get("X-Title"), "peira")

    def test_cache_namespace_does_not_collide_with_response_format(self):
        # The name is part of the cache namespace: tool-calling runs
        # must never share cache entries with response_format runs of
        # the same model id.
        tool = self.adapter()
        fmt = OpenRouterAdapter(model="inclusionai/ling-3.0-flash",
                                api_key="k")
        self.assertIn("openrouter-tool", tool.cache_namespace)
        self.assertNotIn("openrouter-tool", fmt.cache_namespace)
        self.assertNotEqual(tool.cache_namespace, fmt.cache_namespace)

    def test_missing_key_names_openrouter_env_var(self):
        mod, _, _ = _make_openai([])
        with _fake_modules({"openai": mod}), _env(OPENROUTER_API_KEY=None):
            with self.assertRaises(ValueError) as ctx:
                OpenRouterToolAdapter()
        self.assertIn("OPENROUTER_API_KEY", str(ctx.exception))


# ---------------------------------------------------------------------------
# Request shape: forced tool call, no response_format.
# ---------------------------------------------------------------------------

class TestOpenRouterToolRequestShape(_ToolHarness):
    def test_forced_tool_call_sent(self):
        out = self.adapter().decide(CASE, "choice", _ctx())
        self.assertEqual(out.decision, "approve")
        kwargs = self.calls[0]
        self.assertNotIn("response_format", kwargs)
        tools = kwargs["tools"]
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["type"], "function")
        fn = tools[0]["function"]
        self.assertEqual(fn["name"], SCHEMA_NAME)
        self.assertEqual(
            fn["parameters"]["properties"]["decision"]["enum"],
            ["approve", "deny", "other"],
        )
        choice = kwargs["tool_choice"]
        self.assertEqual(choice["type"], "function")
        self.assertEqual(choice["function"]["name"], SCHEMA_NAME)

    def test_no_vendor_specific_fields(self):
        # "thinking" is a vendor-specific reasoning field some APIs
        # accept; the plain OpenAI tool-calling shape must not send it
        # (an unknown field risks a 400).
        self.adapter().decide(CASE, "choice", _ctx())
        self.assertNotIn("thinking", self.calls[0])

    def test_seed_and_logprobs_still_sent(self):
        self.adapter().decide(CASE, "choice", _ctx())
        self.assertEqual(self.calls[0]["seed"], 0)
        self.assertTrue(self.calls[0]["logprobs"])

    def test_transcript_records_tool_call_contract(self):
        out = self.adapter().decide(CASE, "choice", _ctx())
        req = out.transcript["request"]
        self.assertEqual(req["response_format"], "tool_call:peira_decision:forced")
        self.assertEqual(req["base_url"], "https://openrouter.ai/api/v1")
        self.assertTrue(out.transcript["response"]["tool_call_parsed"])

    def test_no_key_material_in_transcript(self):
        with _env(OPENROUTER_API_KEY="<redacted>"):
            out = self.adapter().decide(CASE, "choice", _ctx())
        blob = json.dumps(out.transcript)
        self.assertNotIn("<redacted>", blob)
        self.assertNotIn("sk-", blob)

    def test_system_prompt_names_the_function(self):
        self.adapter().decide(CASE, "choice", _ctx())
        system = self.calls[0]["messages"][0]["content"]
        self.assertIn("peira_decision", system)
        self.assertIn('"confidence"', system)


# ---------------------------------------------------------------------------
# Verdict extraction: tool-call arguments, text fallback, repair nudge.
# ---------------------------------------------------------------------------

class TestOpenRouterToolVerdict(_ToolHarness):
    def test_tool_call_arguments_become_decision(self):
        out = self.adapter().decide(CASE, "choice", _ctx())
        self.assertEqual(out.decision, "approve")
        self.assertAlmostEqual(out.confidence, 0.73)

    def test_preparsed_dict_arguments_accepted(self):
        # Some gateway/SDK variants pre-parse tool arguments into a
        # dict; the forced-tool verdict must not be silently dropped
        # to the text fallback in that case.
        args = {"decision": "deny", "confidence": 0.4, "reason": "risky"}
        fn = SimpleNamespace(name=SCHEMA_NAME, arguments=args)
        tc = SimpleNamespace(type="function", function=fn)
        choice = SimpleNamespace(
            message=SimpleNamespace(content="", tool_calls=[tc]),
            finish_reason="stop",
            logprobs=SimpleNamespace(content=[]),
        )
        resp = SimpleNamespace(
            choices=[choice],
            usage=SimpleNamespace(prompt_tokens=11, completion_tokens=22),
        )
        mod, _, _ = _make_openai([resp])
        with _fake_modules({"openai": mod}), _env(OPENROUTER_API_KEY="<redacted>"):
            out = OpenRouterToolAdapter(
                model="inclusionai/ling-3.0-flash").decide(
                    CASE, "choice", _ctx())
        self.assertEqual(out.decision, "deny")
        self.assertTrue(out.transcript["response"]["tool_call_parsed"])

    def test_text_fallback_when_no_tool_call(self):
        mod, calls, _ = _make_openai(
            [_openai_text_completion(json.dumps({
                "decision": "deny", "confidence": 0.4, "reason": "risky",
            }))])
        with _fake_modules({"openai": mod}), _env(OPENROUTER_API_KEY="k"):
            out = OpenRouterToolAdapter(
                model="inclusionai/ling-3.0-flash").decide(
                    CASE, "choice", _ctx())
        self.assertEqual(out.decision, "deny")
        self.assertFalse(
            out.transcript["response"]["tool_call_parsed"])

    def test_wrong_function_name_ignored(self):
        fn = SimpleNamespace(name="other_function", arguments=TOOL_ARGS)
        tc = SimpleNamespace(type="function", function=fn)
        choice = SimpleNamespace(
            message=SimpleNamespace(content="", tool_calls=[tc]),
            finish_reason="tool_calls",
            logprobs=SimpleNamespace(content=[]),
        )
        resp = SimpleNamespace(
            choices=[choice],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
        )
        # Two scripted responses: the initial call and the repair
        # attempt. Both carry the wrong function name and no usable
        # text, so the adapter raises after the repair attempt.
        mod, _, _ = _make_openai([resp, resp])
        with _fake_modules({"openai": mod}), _env(OPENROUTER_API_KEY="k"):
            # No usable verdict anywhere: the text path has no JSON,
            # so the adapter raises after the repair attempt.
            with self.assertRaises(ProviderError):
                OpenRouterToolAdapter(
                    model="inclusionai/ling-3.0-flash").decide(
                        CASE, "choice", _ctx())

    def test_repair_uses_tool_nudge_not_json_nudge(self):
        bad = _openai_text_completion("not json at all")
        good = _openai_tool_completion(TOOL_ARGS)
        mod, calls, _ = _make_openai([bad, good])
        with _fake_modules({"openai": mod}), _env(OPENROUTER_API_KEY="k"):
            out = OpenRouterToolAdapter(
                model="inclusionai/ling-3.0-flash").decide(
                    CASE, "choice", _ctx())
        self.assertEqual(out.decision, "approve")
        repair_text = calls[1]["messages"][-1]["content"]
        self.assertIn("peira_decision", repair_text)
        self.assertNotIn("Return ONLY the JSON object", repair_text)


# ---------------------------------------------------------------------------
# _resolve repairs: 0-100 scale slip and reason-key typos.
# ---------------------------------------------------------------------------

class TestOpenRouterToolResolve(unittest.TestCase):
    def setUp(self):
        mod, _, _ = _make_openai([])
        self._m = _fake_modules({"openai": mod})
        self._m.__enter__()
        self._e = _env(OPENROUTER_API_KEY="k")
        self._e.__enter__()
        self.addCleanup(self._e.__exit__, None, None, None)
        self.addCleanup(self._m.__exit__, None, None, None)
        self.adapter = OpenRouterToolAdapter(
            model="inclusionai/ling-3.0-flash")

    def test_scale_slip_normalized(self):
        obj = {"decision": "approve", "confidence": 85, "reason": "ok"}
        out, errors = self.adapter._resolve(_raw(parsed=obj), SCHEMA)
        self.assertEqual(errors, [])
        self.assertAlmostEqual(out["confidence"], 0.85)

    def test_rereason_typo_aliased(self):
        obj = {"decision": "deny", "confidence": 0.4, "rereason": "risky"}
        out, errors = self.adapter._resolve(_raw(parsed=obj), SCHEMA)
        self.assertEqual(errors, [])
        self.assertEqual(out["reason"], "risky")
        self.assertNotIn("rereason", out)

    def test_clean_object_passes_through_unchanged(self):
        obj = {"decision": "approve", "confidence": 0.9, "reason": "fine"}
        out, errors = self.adapter._resolve(_raw(parsed=obj), SCHEMA)
        self.assertEqual(errors, [])
        self.assertEqual(out, obj)

    def test_unfixable_errors_returned(self):
        obj = {"decision": "approve"}  # missing confidence and reason
        out, errors = self.adapter._resolve(_raw(parsed=obj), SCHEMA)
        self.assertTrue(errors)
        self.assertIsNotNone(out)


if __name__ == "__main__":
    unittest.main()
