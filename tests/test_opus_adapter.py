"""Tests for the Opus 5.5 adapter (examples/opus_adapter.py).

All HTTP is mocked — no live API calls. Covers every primitive, the
Anthropic output_config request shape (effort low, json_schema format, no
forced tool_choice), text-block JSON parsing, and error paths.
"""

import io
import json
import urllib.error
from unittest import mock

import pytest

from examples.opus_adapter import OpusAdapter, OpusError
from peira.adapters.base import ChoiceOutput, NoulOutput, ScoreOutput, validate_output


# ------------------------------------------------------------------
# Mock HTTP plumbing (Anthropic messages envelope)
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


def messages_response(content_obj: dict) -> dict:
    """Anthropic messages response: JSON as text in a text block."""
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": json.dumps(content_obj)}],
    }


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


def make_adapter(script, **kwargs):
    kwargs.setdefault("api_key", "test-key")
    kwargs.setdefault("min_interval", 0)
    adapter = OpusAdapter(**kwargs)
    fake = make_urlopen(script)
    patcher = mock.patch("urllib.request.urlopen", fake)
    patcher.start()
    return adapter, fake, patcher


def http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://api.anthropic.com/v1/messages",
        code, "err", {}, io.BytesIO(b"error"))


def decide_input(prompt="Should we approve?", options=("approve", "deny")):
    return {"prompt": prompt, "options": list(options)}


# ------------------------------------------------------------------
# Interface
# ------------------------------------------------------------------
def test_interface_attributes():
    a = OpusAdapter(api_key="k")
    assert a.name == "opus-5.5"
    assert a.version == "claude-opus-5-5"
    assert a.supported_primitives == frozenset({"choice", "score", "noul"})


def test_missing_api_key():
    import os
    with mock.patch.dict(os.environ, {}, clear=True):
        with pytest.raises(OpusError, match="no API key"):
            OpusAdapter()


# ------------------------------------------------------------------
# Primitive mapping
# ------------------------------------------------------------------
def test_choice():
    script = [messages_response({"decision": "deny", "confidence": 0.88})]
    adapter, fake, patcher = make_adapter(script)
    try:
        out = adapter.decide(decide_input(), "choice")
    finally:
        patcher.stop()
    assert isinstance(out, ChoiceOutput)
    assert out.decision == "deny"
    assert out.confidence == pytest.approx(0.88)
    assert validate_output(out, "choice") == []


def test_choice_unknown_decision_raises():
    script = [messages_response({"decision": "maybe", "confidence": 0.5})]
    adapter, fake, patcher = make_adapter(script)
    try:
        with pytest.raises(OpusError, match="unknown choice"):
            adapter.decide(decide_input(), "choice")
    finally:
        patcher.stop()


def test_score():
    script = [messages_response({"score": 0.65, "decision": "approve"})]
    adapter, fake, patcher = make_adapter(script)
    try:
        out = adapter.decide(decide_input(), "score")
    finally:
        patcher.stop()
    assert isinstance(out, ScoreOutput)
    assert out.score == pytest.approx(0.65)
    assert validate_output(out, "score") == []


def test_score_trusts_score_over_decision_string():
    script = [messages_response({"score": 0.2, "decision": "approve"})]
    adapter, fake, patcher = make_adapter(script)
    try:
        out = adapter.decide(decide_input(), "score")
    finally:
        patcher.stop()
    assert out.decision == "deny"  # 0.2 < 0.5


def test_noul():
    script = [messages_response({"decision": "approve", "abstained": True})]
    adapter, fake, patcher = make_adapter(script)
    try:
        out = adapter.decide(decide_input(), "noul")
    finally:
        patcher.stop()
    assert isinstance(out, NoulOutput)
    assert out.abstained is True
    assert validate_output(out, "noul") == []


def test_unsupported_primitive():
    adapter = OpusAdapter(api_key="k")
    with pytest.raises(ValueError, match="unsupported primitive"):
        adapter.decide(decide_input(), "bogus")


# ------------------------------------------------------------------
# Anthropic request shape
# ------------------------------------------------------------------
def test_output_config_shape():
    """output_config.format with effort low; no forced tool_choice."""
    script = [messages_response({"decision": "approve", "confidence": 0.9})]
    adapter, fake, patcher = make_adapter(script)
    try:
        adapter.decide(decide_input(), "choice")
    finally:
        patcher.stop()
    req_body = json.loads(fake.calls[0][0].data.decode())
    assert req_body["model"] == "claude-opus-5-5"
    oc = req_body["output_config"]
    assert oc["effort"] == "low"  # thinking billed as output — pin to low
    assert oc["format"]["type"] == "json_schema"
    assert oc["format"]["schema"]["additionalProperties"] is False
    # No tool_choice / tools: forced tools hard-400 on Opus 5.5.
    assert "tools" not in req_body
    assert "tool_choice" not in req_body


def test_anthropic_headers():
    script = [messages_response({"decision": "approve", "confidence": 0.9})]
    adapter, fake, patcher = make_adapter(script, api_key="sk-ant-x")
    try:
        adapter.decide(decide_input(), "choice")
    finally:
        patcher.stop()
    req = fake.calls[0][0]
    # urllib capitalizes header names ("X-api-key"); get_header is
    # case-sensitive, so use the capitalized form.
    assert req.get_header("X-api-key") == "sk-ant-x"
    assert req.get_header("Anthropic-version") == "2023-06-01"


def test_empty_text_block_raises():
    script = [{"content": [{"type": "text", "text": "  "}]}]
    adapter, fake, patcher = make_adapter(script)
    try:
        with pytest.raises(OpusError, match="empty text block"):
            adapter.decide(decide_input(), "choice")
    finally:
        patcher.stop()


# ------------------------------------------------------------------
# HTTP error paths
# ------------------------------------------------------------------
def test_retry_on_429_then_success():
    script = [
        http_error(429),
        messages_response({"decision": "approve", "confidence": 0.9}),
    ]
    adapter, fake, patcher = make_adapter(script)
    try:
        with mock.patch("time.sleep"):
            out = adapter.decide(decide_input(), "choice")
    finally:
        patcher.stop()
    assert out.decision == "approve"


def test_fail_fast_on_400():
    script = [http_error(400)]
    adapter, fake, patcher = make_adapter(script)
    try:
        with pytest.raises(OpusError, match="HTTP 400"):
            adapter.decide(decide_input(), "choice")
    finally:
        patcher.stop()
    assert len(fake.calls) == 1
