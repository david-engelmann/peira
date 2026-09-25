"""Tests for the OpenRouter-based adapters.

Covers GPT-6 Luna/Sol, Grok 4.7, and DeepSeek V4.1 Flash. All HTTP is
mocked — no live API calls, zero spend. Each adapter gets: every primitive,
structured-output request shape, unknown-decision handling, error paths,
and the DeepSeek thinking-disabled extra_body.
"""

import io
import json
import urllib.error
from unittest import mock

import pytest

from examples._openrouter_base import OpenRouterError
from examples.gpt6_adapter import Gpt6LunaAdapter, Gpt6SolAdapter
from examples.grok_adapter import GrokAdapter
from examples.deepseek_adapter import DeepSeekAdapter
from peira.adapters.base import (
    CaseContext,
    ChoiceOutput,
    AbstainOutput,
    ScoreOutput,
    validate_output,
)


# ------------------------------------------------------------------
# Mock HTTP plumbing (OpenRouter chat-completions envelope)
# ------------------------------------------------------------------
class MockHTTPResponse:
    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def chat_response(content_obj: dict) -> dict:
    """Wrap a parsed JSON object in the OpenRouter chat envelope."""
    return {"choices": [{"message": {"role": "assistant",
                                    "content": json.dumps(content_obj)}}]}


def make_urlopen(script):
    calls = []
    items = iter(script)

    def fake_urlopen(req, timeout=None):
        calls.append((req, timeout))
        item = next(items)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, bytes):
            return MockHTTPResponse(item)
        return MockHTTPResponse(json.dumps(item).encode())

    fake_urlopen.calls = calls
    return fake_urlopen


def make_adapter(cls, script, **kwargs):
    kwargs.setdefault("api_key", "test-key")
    kwargs.setdefault("min_interval", 0)
    adapter = cls(**kwargs)
    fake = make_urlopen(script)
    patcher = mock.patch("urllib.request.urlopen", fake)
    patcher.start()
    return adapter, fake, patcher


def http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://openrouter.ai/api/v1/chat/completions",
        code, "err", {}, io.BytesIO(b"error"))


def decide_ctx(prompt="Should we approve?", options=("approve", "deny"), primitive="choice"):
    return CaseContext(
        case_id="test-001",
        primitive=primitive,
        input={"prompt": prompt, "options": list(options)},
        attacked=False,
        variant="benign",
    )


ADAPTER_CLASSES = [Gpt6LunaAdapter, Gpt6SolAdapter, GrokAdapter, DeepSeekAdapter]


# ------------------------------------------------------------------
# Interface attributes
# ------------------------------------------------------------------
@pytest.mark.parametrize("cls,expected_name,expected_model", [
    (Gpt6LunaAdapter, "gpt6-luna", "openai/gpt-6-luna"),
    (Gpt6SolAdapter, "gpt6-sol", "openai/gpt-6-sol"),
    (GrokAdapter, "grok-4.7", "x-ai/grok-4.7"),
    (DeepSeekAdapter, "deepseek-v4.1-flash", "deepseek/deepseek-v4.1-flash"),
])
def test_interface_attributes(cls, expected_name, expected_model):
    a = cls(api_key="k")
    assert a.name == expected_name
    assert a.version == expected_model
    assert a.model == expected_model
    assert a.supported_primitives == frozenset({"choice", "score", "abstain"})


def test_missing_api_key():
    with mock.patch.dict("os.environ", {}, clear=False):
        import os
        os.environ.pop("OPENROUTER_API_KEY", None)
        with pytest.raises(OpenRouterError, match="no API key"):
            Gpt6LunaAdapter()


# ------------------------------------------------------------------
# Primitive mapping (parametrized over all four adapters)
# ------------------------------------------------------------------
@pytest.mark.parametrize("cls", ADAPTER_CLASSES)
def test_choice(cls):
    script = [chat_response({"decision": "deny", "confidence": 0.82})]
    adapter, fake, patcher = make_adapter(cls, script)
    try:
        out = adapter.decide(decide_ctx(primitive="choice"))
    finally:
        patcher.stop()
    assert isinstance(out, ChoiceOutput)
    assert out.decision == "deny"
    assert out.confidence == pytest.approx(0.82)
    assert validate_output(out, "choice") == []


@pytest.mark.parametrize("cls", ADAPTER_CLASSES)
def test_choice_unknown_decision_raises(cls):
    script = [chat_response({"decision": "maybe", "confidence": 0.5})]
    adapter, fake, patcher = make_adapter(cls, script)
    try:
        with pytest.raises(OpenRouterError, match="unknown choice"):
            adapter.decide(decide_ctx(primitive="choice"))
    finally:
        patcher.stop()


@pytest.mark.parametrize("cls", ADAPTER_CLASSES)
def test_score(cls):
    script = [chat_response({"score": 0.7, "decision": "approve"})]
    adapter, fake, patcher = make_adapter(cls, script)
    try:
        out = adapter.decide(decide_ctx(primitive="score"))
    finally:
        patcher.stop()
    assert isinstance(out, ScoreOutput)
    assert out.score == pytest.approx(0.7)
    assert out.decision == "approve"
    assert validate_output(out, "score") == []


@pytest.mark.parametrize("cls", ADAPTER_CLASSES)
def test_score_contradictory_decision_trusts_score(cls):
    # Model says score 0.8 but decision "deny" — adapter trusts the score.
    script = [chat_response({"score": 0.8, "decision": "deny"})]
    adapter, fake, patcher = make_adapter(cls, script)
    try:
        out = adapter.decide(decide_ctx(primitive="score"))
    finally:
        patcher.stop()
    assert out.score == pytest.approx(0.8)
    assert out.decision == "approve"  # 0.8 >= 0.5 threshold


@pytest.mark.parametrize("cls", ADAPTER_CLASSES)
def test_noul(cls):
    script = [chat_response({"decision": "approve", "abstained": False})]
    adapter, fake, patcher = make_adapter(cls, script)
    try:
        out = adapter.decide(decide_ctx(primitive="abstain"))
    finally:
        patcher.stop()
    assert isinstance(out, AbstainOutput)
    assert out.decision == "approve"
    assert out.abstained is False
    assert validate_output(out, "abstain") == []


@pytest.mark.parametrize("cls", ADAPTER_CLASSES)
def test_noul_abstained(cls):
    script = [chat_response({"decision": "deny", "abstained": True})]
    adapter, fake, patcher = make_adapter(cls, script)
    try:
        out = adapter.decide(decide_ctx(primitive="abstain"))
    finally:
        patcher.stop()
    assert out.abstained is True


@pytest.mark.parametrize("cls", ADAPTER_CLASSES)
def test_unsupported_primitive(cls):
    adapter = cls(api_key="k")
    with pytest.raises(ValueError, match="unknown primitive"):
        CaseContext(case_id="x", primitive="bogus", input={}, attacked=False, variant="benign")


@pytest.mark.parametrize("cls", ADAPTER_CLASSES)
def test_too_few_options(cls):
    adapter = cls(api_key="k")
    with pytest.raises(OpenRouterError, match=">= 2 options"):
        adapter.decide(decide_ctx(options=("only",), primitive="choice"))


# ------------------------------------------------------------------
# Structured-output request shape
# ------------------------------------------------------------------
def test_structured_output_request_shape():
    script = [chat_response({"decision": "approve", "confidence": 0.9})]
    adapter, fake, patcher = make_adapter(Gpt6LunaAdapter, script)
    try:
        adapter.decide(decide_ctx(primitive="choice"))
    finally:
        patcher.stop()
    req_body = json.loads(fake.calls[0][0].data.decode())
    assert req_body["model"] == "openai/gpt-6-luna"
    assert req_body["temperature"] == 0.0
    rf = req_body["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["strict"] is True
    schema = rf["json_schema"]["schema"]
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"decision", "confidence"}


def test_deepseek_disables_thinking():
    script = [chat_response({"decision": "approve", "confidence": 0.9})]
    adapter, fake, patcher = make_adapter(DeepSeekAdapter, script)
    try:
        adapter.decide(decide_ctx(primitive="choice"))
    finally:
        patcher.stop()
    req_body = json.loads(fake.calls[0][0].data.decode())
    assert req_body["reasoning"] == {"effort": "none"}


def test_auth_header():
    script = [chat_response({"decision": "approve", "confidence": 0.9})]
    adapter, fake, patcher = make_adapter(
        Gpt6LunaAdapter, script, api_key="sk-test-123")
    try:
        adapter.decide(decide_ctx(primitive="choice"))
    finally:
        patcher.stop()
    req = fake.calls[0][0]
    assert req.get_header("Authorization") == "Bearer sk-test-123"


# ------------------------------------------------------------------
# HTTP error paths
# ------------------------------------------------------------------
def test_retry_on_429_then_success():
    script = [
        http_error(429),
        chat_response({"decision": "approve", "confidence": 0.9}),
    ]
    adapter, fake, patcher = make_adapter(Gpt6LunaAdapter, script)
    try:
        with mock.patch("time.sleep"):
            out = adapter.decide(decide_ctx(primitive="choice"))
    finally:
        patcher.stop()
    assert out.decision == "approve"
    assert len(fake.calls) == 2


def test_fail_fast_on_401():
    script = [http_error(401)]
    adapter, fake, patcher = make_adapter(Gpt6LunaAdapter, script)
    try:
        with pytest.raises(OpenRouterError, match="HTTP 401"):
            adapter.decide(decide_ctx(primitive="choice"))
    finally:
        patcher.stop()
    assert len(fake.calls) == 1


def test_malformed_json_content_raises():
    script = [{"choices": [{"message": {"role": "assistant",
                                       "content": "not json"}}]}]
    adapter, fake, patcher = make_adapter(Gpt6LunaAdapter, script)
    try:
        with pytest.raises(OpenRouterError, match="bad response"):
            adapter.decide(decide_ctx(primitive="choice"))
    finally:
        patcher.stop()


def test_empty_content_raises():
    script = [{"choices": [{"message": {"role": "assistant", "content": ""}}]}]
    adapter, fake, patcher = make_adapter(Gpt6LunaAdapter, script)
    try:
        with pytest.raises(OpenRouterError, match="empty content"):
            adapter.decide(decide_ctx(primitive="choice"))
    finally:
        patcher.stop()


def test_nan_confidence_clamped_to_zero():
    # NaN must fail closed (0.0), never silently become 1.0.
    script = [chat_response({"decision": "approve", "confidence": float("nan")})]
    adapter, fake, patcher = make_adapter(Gpt6LunaAdapter, script)
    try:
        out = adapter.decide(decide_ctx(primitive="choice"))
    finally:
        patcher.stop()
    assert out.confidence == 0.0
