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
    # B2: the per-call decision enum is built from the input's explicit
    # options — the adapter-visible context carries no gold labels.
    "options": ["approve", "deny"],
}


def _ctx(**over):
    """Opaque adapter-visible context for adapter unit tests.

    The runner builds the real one; it carries only a pseudonymous
    call id — no case id, no arm, no gold labels.
    """
    from peira.adapters.base import CallContext
    return CallContext(call_id=over.get("call_id", "call-test"))

GOOD_JSON = json.dumps({
    "decision": "approve", "confidence": 0.73, "reason": "looks fine",
})


def _expected_schema(labels, primitive="choice"):
    schema = {
        "type": "object",
        "additionalProperties": False,
        # Strict-mode invariant: every property must be in required.
        "required": ["decision", "confidence", "reason"],
        "properties": {
            "decision": {"type": "string", "enum": list(labels)},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "reason": {"type": "string"},
        },
    }
    if primitive == "score":
        schema["required"] = ["decision", "confidence", "reason", "score"]
        schema["properties"]["score"] = {
            "type": "number", "minimum": 0, "maximum": 1,
        }
    return schema


def _expected_wire_schema(labels, primitive="choice"):
    """Expected schema on the output_config wire: Anthropic's
    structured-outputs subset rejects numeric constraints (minimum /
    maximum) with a 400, so the adapter strips them and moves the
    bound into the field description (mirroring the SDK transform)."""
    schema = _expected_schema(labels, primitive)
    for prop in ("confidence", "score"):
        if prop in schema["properties"]:
            subschema = schema["properties"][prop]
            del subschema["minimum"]
            del subschema["maximum"]
            subschema["description"] = "Must be between 0 and 1."
    return schema


def _assert_no_numeric_constraints(node, path="schema"):
    """Recursively assert no minimum/maximum/multipleOf anywhere."""
    if isinstance(node, dict):
        for key in ("minimum", "maximum", "multipleOf"):
            assert key not in node, f"{path} still has {key!r}"
        for name, value in node.items():
            _assert_no_numeric_constraints(value, f"{path}.{name}")
    elif isinstance(node, list):
        for i, item in enumerate(node):
            _assert_no_numeric_constraints(item, f"{path}[{i}]")


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

    def test_missing_key_message_has_no_embedded_prefix(self):
        # The CLI prints its own "error: " prefix; messages must not
        # embed one, or the user sees "error: error: ...".
        mod, _, _ = _make_openai([])
        with _fake_modules({"openai": mod}), _env(OPENAI_API_KEY=None):
            with self.assertRaises(ValueError) as ctx:
                OpenAIAdapter()
        self.assertEqual(str(ctx.exception),
                         "OPENAI_API_KEY is not set — OpenAIAdapter "
                         "needs it (and the peira[openai] extra)")

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
        out = OpenAIAdapter().decide(CASE, "choice", _ctx())
        self.assertEqual(out.decision, "approve")
        fmt = self.calls[0]["response_format"]
        self.assertEqual(fmt, {
            "type": "json_schema",
            "json_schema": {
                "name": "peira_decision",
                "strict": True,
                "schema": _expected_schema(["approve", "deny", "other"]),
            },
        })

    def test_strict_mode_invariant_every_property_required(self):
        # OpenAI strict mode 400s any schema with a property missing
        # from required. Assert the invariant on the schema actually
        # sent, for both the choice and score shapes.
        from peira.adapters.llm import _build_schema
        for primitive in ("choice", "score", "abstain"):
            schema = _build_schema(["approve", "other"], primitive)
            self.assertEqual(set(schema["required"]),
                             set(schema["properties"]),
                             f"strict-mode invariant broken for {primitive}")

    def test_temperature_zero_and_seed_passed(self):
        OpenAIAdapter().decide(CASE, "choice", _ctx())
        self.assertEqual(self.calls[0]["temperature"], 0)
        self.assertEqual(self.calls[0]["seed"], 0)

    def test_call_usage_model_exact(self):
        out = OpenAIAdapter().decide(CASE, "choice", _ctx())
        self.assertEqual(out.usage.model, "gpt-5.6-luna")
        self.assertEqual(out.usage.tokens_in, 11)
        self.assertEqual(out.usage.tokens_out, 22)

    def test_logprob_recorded_in_transcript(self):
        self.script[0] = _openai_completion(
            GOOD_JSON, tokens=[("approve", -0.02), ("x", -3.1)])
        out = OpenAIAdapter().decide(CASE, "choice", _ctx())
        tracks = out.transcript["confidence_tracks"]
        self.assertEqual(tracks["decision_token_logprob"], -0.02)
        self.assertEqual(tracks["verbalized"], 0.73)

    def test_seed_in_transcript(self):
        out = OpenAIAdapter().decide(CASE, "choice", _ctx())
        self.assertEqual(out.transcript["seed"], 0)
        self.assertEqual(out.transcript["model"], "gpt-5.6-luna")

    def test_no_key_material_in_transcript(self):
        with _env(OPENAI_API_KEY="sk-test-secret-999"):
            out = OpenAIAdapter().decide(CASE, "choice", _ctx())
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
        out = AnthropicAdapter().decide(CASE, "choice", _ctx())
        self.assertEqual(out.decision, "approve")
        self.assertEqual(self.calls[0]["tool_choice"],
                         {"type": "tool", "name": "peira_decision"})
        self.assertEqual(self.calls[0]["tools"],
                         [{"name": "peira_decision",
                           "input_schema": _expected_schema(
                               ["approve", "deny", "other"])}])

    def test_no_seed_param_and_null_seed_in_transcript(self):
        out = AnthropicAdapter(seed=5).decide(CASE, "choice", _ctx())
        self.assertNotIn("seed", self.calls[0])
        self.assertIsNone(out.transcript["seed"])

    def test_logprob_null(self):
        out = AnthropicAdapter().decide(CASE, "choice", _ctx())
        self.assertIsNone(
            out.transcript["confidence_tracks"]["decision_token_logprob"])

    def test_refusal_stop_reason_abstains(self):
        self.script[0] = _anthropic_message(
            tool_input=None, text="", stop_reason="refusal")
        out = AnthropicAdapter().decide(CASE, "choice", _ctx())
        self.assertTrue(out.abstained)
        self.assertEqual(out.decision, "")
        self.assertIn("refusal", out.refusal_reason)
        self.assertEqual(validate_output(out, "choice"), [])

    def test_temperature_sent_via_extra_body_not_kwarg(self):
        # anthropic SDK 1.x removed the temperature kwarg from
        # messages.create (passing it is a TypeError). The adapter
        # must carry temperature in extra_body — identical wire JSON
        # on the 0.x and 1.x SDK lines — never as a top-level kwarg.
        out = AnthropicAdapter().decide(CASE, "choice", _ctx())
        self.assertEqual(out.decision, "approve")
        self.assertNotIn("temperature", self.calls[0])
        self.assertEqual(self.calls[0]["extra_body"],
                         {"temperature": 0.0})
        self.assertEqual(out.transcript["request"]["temperature"],
                         0.0)

    def test_no_temperature_model_omits_extra_body(self):
        # claude-opus-5-5 rejects temperature with a 400: nothing
        # temperature-shaped may reach the wire for it.
        mod, calls, _ = _make_anthropic(
            [_anthropic_message(text=GOOD_JSON)])
        with _fake_modules({"anthropic": mod}), \
                _env(ANTHROPIC_API_KEY="sk-test"):
            out = AnthropicAdapter(
                model="claude-opus-5-5").decide(CASE, "choice", _ctx())
        self.assertEqual(out.decision, "approve")
        self.assertNotIn("temperature", calls[0])
        self.assertNotIn("extra_body", calls[0])
        self.assertIsNone(
            out.transcript["request"]["temperature"])


class TestAnthropicStructuredOutputs(unittest.TestCase):
    """Native output_config.format path for newer Anthropic models.

    Routing: ``structured_outputs=None`` auto-routes the known newer
    reasoning models (``claude-fable-5-1``); everything else keeps the
    forced-tool path. No live API: the SDK is faked, and the tests
    assert the exact request shape plus response-parsing parity
    between the two paths.
    """

    def _run(self, script, **ctor):
        mod, calls, _ = _make_anthropic(script)
        with _fake_modules({"anthropic": mod}), \
                _env(ANTHROPIC_API_KEY="sk-test"):
            out = AnthropicAdapter(**ctor).decide(CASE, "choice", _ctx())
        return out, calls

    def test_fable_auto_routes_to_output_config(self):
        out, calls = self._run(
            [_anthropic_message(text=GOOD_JSON)],
            model="claude-fable-5-1",
        )
        self.assertEqual(out.decision, "approve")
        wire_schema = calls[0]["output_config"]["format"]["schema"]
        self.assertEqual(
            calls[0]["output_config"],
            {"format": {
                "type": "json_schema",
                "schema": _expected_wire_schema(
                    ["approve", "deny", "other"]),
            }},
        )
        self.assertNotIn("tools", calls[0])
        self.assertNotIn("tool_choice", calls[0])
        # Anthropic's structured-outputs subset rejects numeric
        # constraints with a 400: none may reach the wire.
        _assert_no_numeric_constraints(wire_schema)

    def test_default_model_keeps_forced_tool(self):
        out, calls = self._run(
            [_anthropic_message(tool_input=json.loads(GOOD_JSON))])
        self.assertEqual(out.decision, "approve")
        self.assertEqual(calls[0]["tool_choice"],
                         {"type": "tool", "name": "peira_decision"})
        # Exact tools payload: the forced-tool path keeps the full
        # JSON Schema, numeric constraints included.
        self.assertEqual(calls[0]["tools"], [{
            "name": "peira_decision",
            "input_schema": _expected_schema(
                ["approve", "deny", "other"]),
        }])
        self.assertNotIn("output_config", calls[0])

    def test_structured_wire_schema_strips_numeric_constraints(self):
        schema = _expected_schema(["approve", "deny"], primitive="score")
        wire = llm._structured_wire_schema(schema)
        _assert_no_numeric_constraints(wire)
        self.assertEqual(
            wire["properties"]["confidence"]["description"],
            "Must be between 0 and 1.")
        self.assertEqual(
            wire["properties"]["score"]["description"],
            "Must be between 0 and 1.")
        # The canonical schema is untouched: the forced-tool path
        # keeps its constraints.
        self.assertEqual(
            schema["properties"]["confidence"]["minimum"], 0)
        self.assertEqual(
            schema["properties"]["score"]["maximum"], 1)

    def test_explicit_opt_in_flag(self):
        out, calls = self._run(
            [_anthropic_message(text=GOOD_JSON)],
            model="claude-sonnet-5", structured_outputs=True,
        )
        self.assertEqual(out.decision, "approve")
        self.assertIn("output_config", calls[0])
        self.assertNotIn("tools", calls[0])

    def test_explicit_opt_out_flag(self):
        out, calls = self._run(
            [_anthropic_message(tool_input=json.loads(GOOD_JSON))],
            model="claude-fable-5-1", structured_outputs=False,
        )
        self.assertEqual(out.decision, "approve")
        self.assertEqual(calls[0]["tool_choice"],
                         {"type": "tool", "name": "peira_decision"})
        self.assertNotIn("output_config", calls[0])

    def test_routing_predicate(self):
        self.assertTrue(
            llm._wants_structured_outputs("claude-fable-5-1", None))
        self.assertFalse(
            llm._wants_structured_outputs("claude-sonnet-5", None))
        # Explicit flag always wins over the predicate.
        self.assertTrue(
            llm._wants_structured_outputs("claude-sonnet-5", True))
        self.assertFalse(
            llm._wants_structured_outputs("claude-fable-5-1", False))

    def test_parity_between_paths(self):
        # Same payload, two constrained-decoding shapes: the typed
        # contract must be identical.
        forced_out, _ = self._run(
            [_anthropic_message(tool_input=json.loads(GOOD_JSON))])
        struct_out, _ = self._run(
            [_anthropic_message(text=GOOD_JSON)],
            model="claude-fable-5-1",
        )
        for out in (forced_out, struct_out):
            self.assertEqual(out.decision, "approve")
            self.assertAlmostEqual(out.confidence, 0.73)
            self.assertEqual(validate_output(out, "choice"), [])
        self.assertEqual(struct_out.decision, forced_out.decision)
        self.assertEqual(struct_out.confidence, forced_out.confidence)

    def test_structured_path_score_primitive(self):
        score_json = json.dumps({
            "decision": "approve", "confidence": 0.6,
            "reason": "r", "score": 0.8,
        })
        mod, calls, _ = _make_anthropic(
            [_anthropic_message(text=score_json)])
        with _fake_modules({"anthropic": mod}), \
                _env(ANTHROPIC_API_KEY="sk-test"):
            out = AnthropicAdapter(
                model="claude-fable-5-1").decide(CASE, "score", _ctx())
        self.assertAlmostEqual(out.score, 0.8)
        self.assertEqual(validate_output(out, "score"), [])
        wire_schema = calls[0]["output_config"]["format"]["schema"]
        self.assertIn("score", wire_schema["properties"])
        _assert_no_numeric_constraints(wire_schema)

    def test_structured_path_abstain_primitive(self):
        payload = json.dumps({"decision": "abstain", "confidence": 0.5,
                              "reason": "r"})
        mod, _, _ = _make_anthropic([_anthropic_message(text=payload)])
        with _fake_modules({"anthropic": mod}), \
                _env(ANTHROPIC_API_KEY="sk-test"):
            out = AnthropicAdapter(
                model="claude-fable-5-1").decide(CASE, "abstain", _ctx())
        self.assertEqual(out.decision, "abstain")
        self.assertFalse(out.abstained)
        self.assertEqual(validate_output(out, "abstain"), [])

    def test_repair_retry_keeps_structured_path(self):
        mod, calls, _ = _make_anthropic([
            _anthropic_message(text="not json at all"),
            _anthropic_message(text=GOOD_JSON),
        ])
        with _fake_modules({"anthropic": mod}), \
                _env(ANTHROPIC_API_KEY="sk-test"):
            out = AnthropicAdapter(
                model="claude-fable-5-1").decide(CASE, "choice", _ctx())
        self.assertEqual(out.decision, "approve")
        self.assertEqual(len(calls), 2)
        for call in calls:
            self.assertIn("output_config", call)
            self.assertNotIn("tools", call)
            self.assertNotIn("tool_choice", call)

    def test_refusal_on_structured_path_abstains(self):
        out, _ = self._run(
            [_anthropic_message(text="", stop_reason="refusal")],
            model="claude-fable-5-1",
        )
        self.assertTrue(out.abstained)
        self.assertEqual(out.decision, "")
        self.assertEqual(validate_output(out, "choice"), [])

    def test_transcript_marks_output_config(self):
        out, _ = self._run(
            [_anthropic_message(text=GOOD_JSON)],
            model="claude-fable-5-1",
        )
        request = out.transcript["request"]
        self.assertEqual(request["output_config"], "json_schema")
        self.assertNotIn("tool_choice", request)

    def test_cache_namespace_differs_by_path(self):
        mod, _, _ = _make_anthropic([])
        with _fake_modules({"anthropic": mod}), \
                _env(ANTHROPIC_API_KEY="sk-test"):
            default = AnthropicAdapter()
            structured = AnthropicAdapter(model="claude-fable-5-1")
        # The default path keeps the historical namespace exactly.
        self.assertEqual(default.cache_namespace,
                         "anthropic-structured:claude-sonnet-5:t0.0:mt512")
        self.assertNotEqual(structured.cache_namespace,
                            default.cache_namespace)
        self.assertTrue(structured.cache_namespace.endswith(":so"))
        # with_seed (M-7 multi-seed copies) must keep the suffix.
        reseeded = structured.with_seed(None)
        self.assertTrue(reseeded.cache_namespace.endswith(":so"))


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
        out = GoogleAdapter().decide(CASE, "choice", _ctx())
        self.assertEqual(out.decision, "approve")
        config = self.configs[0]
        self.assertEqual(config["response_mime_type"], "application/json")
        self.assertEqual(config["response_schema"],
                         _expected_schema(["approve", "deny", "other"]))

    def test_temperature_zero_and_seed(self):
        GoogleAdapter().decide(CASE, "choice", _ctx())
        self.assertEqual(self.configs[0]["temperature"], 0)
        self.assertEqual(self.configs[0]["seed"], 0)
        self.assertEqual(self.calls[0]["model"], "gemini-3.8-flash")

    def test_safety_finish_reason_abstains(self):
        self.script[0] = _genai_response("", finish_reason="SAFETY")
        out = GoogleAdapter().decide(CASE, "choice", _ctx())
        self.assertTrue(out.abstained)
        self.assertIn("SAFETY", out.refusal_reason)
        self.assertEqual(validate_output(out, "choice"), [])

    def test_429_is_transient(self):
        self.script[0] = _FakeGoogleError("rate limited", code=429)
        with self.assertRaises(ProviderError) as ctx:
            GoogleAdapter().decide(CASE, "choice", _ctx())
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

    def test_enum_comes_from_input_options(self):
        # B2: the enum is built from the input's explicit options — the
        # opaque context carries no target to include.
        case = dict(CASE, junk_key="ignored", junk_obj=object())
        OpenAIAdapter().decide(case, "choice", _ctx())
        schema = self.calls[0]["response_format"]["json_schema"]["schema"]
        self.assertEqual(schema["properties"]["decision"]["enum"],
                         ["approve", "deny", "other"])

    def test_open_vocabulary_labels_accepted(self):
        payload = json.dumps({"decision": "choose A", "confidence": 0.6,
                              "reason": "r"})
        self.script[0] = _openai_completion(payload)
        case = dict(CASE, options=["emergency-dept", "choose A"])
        out = OpenAIAdapter().decide(case, "choice", _ctx())
        self.assertEqual(out.decision, "choose A")
        schema = self.calls[0]["response_format"]["json_schema"]["schema"]
        self.assertEqual(schema["properties"]["decision"]["enum"],
                         ["choose A", "emergency-dept", "other"])

    def test_noul_enum_allows_abstain(self):
        mod, calls, _ = _make_anthropic([_anthropic_message(
            tool_input={"decision": "abstain", "confidence": 0.5,
                        "reason": "r"})])
        with _fake_modules({"anthropic": mod}), \
                _env(ANTHROPIC_API_KEY="sk-test"):
            out = AnthropicAdapter().decide(CASE, "abstain", _ctx())
        self.assertEqual(out.decision, "abstain")
        self.assertFalse(out.abstained)
        self.assertEqual(validate_output(out, "abstain"), [])
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
        case = dict(CASE)
        with _fake_modules({"openai": mod}), _env(OPENAI_API_KEY="sk-test"):
            out = OpenAIAdapter().decide(case, "score", _ctx(expected="deny"))
        self.assertEqual(out.score, 0.2)
        self.assertEqual(out.decision, "deny")
        self.assertEqual(out.confidence, 0.8)
        self.assertEqual(validate_output(out, "score"), [])
        schema = calls[0]["response_format"]["json_schema"]["schema"]
        self.assertEqual(schema, _expected_schema(["approve", "deny", "other"],
                                                 primitive="score"))

    def test_abstained_score_convention(self):
        mod, _, _ = _make_openai(
            [_openai_completion("", finish_reason="refusal")])
        with _fake_modules({"openai": mod}), _env(OPENAI_API_KEY="sk-test"):
            out = OpenAIAdapter().decide(CASE, "score", _ctx())
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
        out = adapter.decide(CASE, "choice", _ctx())
        self.assertTrue(out.abstained)
        self.assertEqual(out.decision, "")
        self.assertEqual(out.refusal_reason,
                         "stop_reason: content_filter")
        self.assertIsNone(out.confidence)
        self.assertEqual(validate_output(out, "choice"), [])

    def test_gcg_prefix_in_free_text_abstains(self):
        adapter, _ = self._adapter_with(
            [_openai_completion("I'm sorry, I can't help with that.")])
        out = adapter.decide(CASE, "choice", _ctx())
        self.assertTrue(out.abstained)
        self.assertIn("I'm sorry", out.refusal_reason)
        self.assertEqual(validate_output(out, "choice"), [])

    def test_bad_enum_is_terminal_not_retryable(self):
        bad = json.dumps({"decision": "maybe", "confidence": 0.9,
                          "reason": "x"})
        adapter, calls = self._adapter_with(
            [_openai_completion(bad), _openai_completion(bad)])
        with self.assertRaises(ProviderError) as ctx:
            adapter.decide(CASE, "choice", _ctx())
        retryable, _, _ = classify_exception(ctx.exception)
        self.assertFalse(retryable)
        # Exactly one repair attempt, then terminal.
        self.assertEqual(len(calls), 2)

    def test_repair_attempt_can_succeed(self):
        bad = json.dumps({"decision": "approve"})  # missing confidence
        adapter, calls = self._adapter_with(
            [_openai_completion(bad), _openai_completion(GOOD_JSON)])
        out = adapter.decide(CASE, "choice", _ctx())
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
        out = adapter.decide(CASE, "choice", _ctx())
        self.assertTrue(out.abstained)
        self.assertIn("I cannot", out.refusal_reason)

    def test_verbalized_confidence_passes_through(self):
        adapter, _ = self._adapter_with([_openai_completion(GOOD_JSON)])
        out = adapter.decide(CASE, "choice", _ctx())
        self.assertEqual(out.confidence, 0.73)

    def test_unknown_input_keys_ignored(self):
        adapter, calls = self._adapter_with([_openai_completion(GOOD_JSON)])
        case = dict(CASE, whatever="x", nested={"a": 1})
        out = adapter.decide(case, "choice", _ctx(target="deny", attacked=True))
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
                OpenAIAdapter().decide(CASE, "choice", _ctx())
        self.assertEqual(ctx.exception.status_code, 401)
        retryable, _, _ = classify_exception(ctx.exception)
        self.assertFalse(retryable)

    def test_openai_429_carries_retry_after(self):
        err = _FakeAPIStatusError("rate limited", 429,
                                 headers={"retry-after": "7"})
        mod, _, _ = _make_openai([err])
        with _fake_modules({"openai": mod}), _env(OPENAI_API_KEY="sk-test"):
            with self.assertRaises(ProviderError) as ctx:
                OpenAIAdapter().decide(CASE, "choice", _ctx())
        self.assertEqual(ctx.exception.status_code, 429)
        self.assertEqual(ctx.exception.retry_after, 7.0)
        retryable, cut, _ = classify_exception(ctx.exception)
        self.assertTrue(retryable)
        self.assertTrue(cut)

    def test_openai_timeout_maps_to_408(self):
        mod, _, _ = _make_openai([_FakeTimeoutError("timed out")])
        with _fake_modules({"openai": mod}), _env(OPENAI_API_KEY="sk-test"):
            with self.assertRaises(ProviderError) as ctx:
                OpenAIAdapter().decide(CASE, "choice", _ctx())
        self.assertEqual(ctx.exception.status_code, 408)
        retryable, _, _ = classify_exception(ctx.exception)
        self.assertTrue(retryable)

    def test_openai_empty_choices_is_terminal_provider_error(self):
        empty = SimpleNamespace(choices=[], usage=None)
        mod, _, _ = _make_openai([empty])
        with _fake_modules({"openai": mod}), _env(OPENAI_API_KEY="sk-test"):
            with self.assertRaises(ProviderError) as ctx:
                OpenAIAdapter().decide(CASE, "choice", _ctx())
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
