"""Tests for the Shieldstral adapter (examples/shieldstral_adapter.py).

All HTTP is mocked — no live API calls. Covers every primitive, the
logprobs yes-probability extraction (with text fallback), and the HTTP
error paths (retry, fail-fast, malformed responses).
"""

import io
import json
import urllib.error
from unittest import mock

import pytest

from examples.shieldstral_adapter import (
    ShieldstralAdapter,
    ShieldstralError,
    _extract_yes_prob,
)
from peira.adapters.base import (
    CaseContext,
    ChoiceOutput,
    AbstainOutput,
    ScoreOutput,
    validate_output,
)


# ------------------------------------------------------------------
# Mock HTTP plumbing
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


def chat_payload(top_logprobs=None, text="yes"):
    """Build an OpenAI-compatible chat response with logprobs."""
    content = [{"top_logprobs": top_logprobs}] if top_logprobs else None
    choice = {"message": {"role": "assistant", "content": text}}
    if content:
        choice["logprobs"] = {"content": content}
    return {"choices": [choice]}


def yes_no_logprobs(p_yes: float):
    """Top-logprobs list encoding P(yes) = p_yes (log-space)."""
    import math
    return [
        {"token": "yes", "logprob": math.log(p_yes)},
        {"token": "no", "logprob": math.log(1 - p_yes)},
        {"token": "maybe", "logprob": -10.0},
    ]


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
    kwargs.setdefault("min_interval", 0)
    adapter = ShieldstralAdapter(**kwargs)
    fake = make_urlopen(script)
    patcher = mock.patch("urllib.request.urlopen", fake)
    patcher.start()
    return adapter, fake, patcher


def http_error(code: int, body: bytes = b"error") -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "http://localhost:8000/v1/chat/completions", code, "err", {}, io.BytesIO(body))


def decide_ctx(prompt="Should we approve?", options=("approve", "deny"), primitive="choice"):
    return CaseContext(
        case_id="test-001",
        primitive=primitive,
        input={"prompt": prompt, "options": list(options)},
        attacked=False,
        variant="benign",
    )


# ------------------------------------------------------------------
# _extract_yes_prob
# ------------------------------------------------------------------
def test_extract_yes_prob_from_logprobs():
    p = _extract_yes_prob(chat_payload(yes_no_logprobs(0.8)))
    assert p == pytest.approx(0.8, abs=1e-6)


def test_extract_yes_prob_low():
    p = _extract_yes_prob(chat_payload(yes_no_logprobs(0.2)))
    assert p == pytest.approx(0.2, abs=1e-6)


def test_extract_yes_prob_text_fallback_yes():
    assert _extract_yes_prob(chat_payload(text="yes")) == 1.0


def test_extract_yes_prob_text_fallback_no():
    assert _extract_yes_prob(chat_payload(text="no")) == 0.0


def test_extract_yes_prob_text_fallback_ambiguous():
    assert _extract_yes_prob(chat_payload(text="maybe")) == 0.5


def test_extract_yes_prob_malformed_payload():
    assert _extract_yes_prob({}) == 0.5


# ------------------------------------------------------------------
# Primitive mapping
# ------------------------------------------------------------------
def test_choice_argmax():
    script = [
        chat_payload(yes_no_logprobs(0.3)),  # approve
        chat_payload(yes_no_logprobs(0.9)),  # deny
    ]
    adapter, fake, patcher = make_adapter(script)
    try:
        out = adapter.decide(decide_ctx(primitive="choice"))
    finally:
        patcher.stop()
    assert isinstance(out, ChoiceOutput)
    assert out.decision == "deny"
    assert out.confidence == pytest.approx(0.9, abs=1e-6)
    assert validate_output(out, "choice") == []


def test_score_uses_options0():
    script = [chat_payload(yes_no_logprobs(0.75))]
    adapter, fake, patcher = make_adapter(script)
    try:
        out = adapter.decide(decide_ctx(primitive="score"))
    finally:
        patcher.stop()
    assert isinstance(out, ScoreOutput)
    assert out.score == pytest.approx(0.75, abs=1e-6)
    assert out.decision == "approve"  # 0.75 >= 0.5
    assert validate_output(out, "score") == []


def test_score_below_threshold():
    script = [chat_payload(yes_no_logprobs(0.2))]
    adapter, fake, patcher = make_adapter(script)
    try:
        out = adapter.decide(decide_ctx(primitive="score"))
    finally:
        patcher.stop()
    assert out.decision == "deny"


def test_noul_two_option_yes():
    script = [chat_payload(yes_no_logprobs(0.8))]
    adapter, fake, patcher = make_adapter(script)
    try:
        out = adapter.decide(decide_ctx(primitive="abstain"))
    finally:
        patcher.stop()
    assert isinstance(out, AbstainOutput)
    assert out.decision == "approve"
    assert out.abstained is False


def test_noul_two_option_abstain():
    script = [chat_payload(yes_no_logprobs(0.52))]
    adapter, fake, patcher = make_adapter(script, abstain_margin=0.1)
    try:
        out = adapter.decide(decide_ctx(primitive="abstain"))
    finally:
        patcher.stop()
    assert out.abstained is True  # |0.52 - 0.5| < 0.1


def test_noul_three_option_argmax():
    script = [
        chat_payload(yes_no_logprobs(0.2)),
        chat_payload(yes_no_logprobs(0.85)),
        chat_payload(yes_no_logprobs(0.4)),
    ]
    adapter, fake, patcher = make_adapter(script)
    try:
        out = adapter.decide(
            decide_ctx(options=("a", "b", "c"), primitive="abstain"))
    finally:
        patcher.stop()
    assert out.decision == "b"
    assert len(fake.calls) == 3  # one question per option


def test_choice_sends_three_field_format():
    script = [
        chat_payload(yes_no_logprobs(0.6)),
        chat_payload(yes_no_logprobs(0.4)),
    ]
    adapter, fake, patcher = make_adapter(script)
    try:
        adapter.decide(decide_ctx(primitive="choice"))
    finally:
        patcher.stop()
    req_body = json.loads(fake.calls[0][0].data.decode())
    user_content = req_body["messages"][1]["content"]
    assert "<Instruct>" in user_content
    assert "<Query>" in user_content
    assert "<Document>" in user_content
    assert req_body["messages"][0]["content"].startswith("Judge whether")
    assert req_body.get("logprobs") is True


def test_interface_attributes():
    a = ShieldstralAdapter()
    assert a.name == "shieldstral"
    assert a.version == "mistralai/Shieldstral-1.0-3B"
    assert a.supported_primitives == frozenset({"choice", "score", "abstain"})


def test_unsupported_primitive():
    adapter = ShieldstralAdapter()
    with pytest.raises(ValueError, match="unknown primitive"):
        CaseContext(case_id="x", primitive="bogus", input={}, attacked=False, variant="benign")


def test_too_few_options():
    adapter = ShieldstralAdapter()
    with pytest.raises(ShieldstralError, match=">= 2 options"):
        adapter.decide(decide_ctx(options=("only",), primitive="choice"))


# ------------------------------------------------------------------
# HTTP layer
# ------------------------------------------------------------------
def test_retry_on_429_then_success():
    script = [
        http_error(429),
        chat_payload(yes_no_logprobs(0.7)),
        chat_payload(yes_no_logprobs(0.3)),
    ]
    adapter, fake, patcher = make_adapter(script)
    try:
        with mock.patch("time.sleep"):  # don't actually back off
            out = adapter.decide(decide_ctx(primitive="choice"))
    finally:
        patcher.stop()
    assert out.decision == "approve"


def test_fail_fast_on_400():
    script = [http_error(400)]
    adapter, fake, patcher = make_adapter(script)
    try:
        with pytest.raises(ShieldstralError, match="HTTP 400"):
            adapter.decide(decide_ctx(primitive="choice"))
    finally:
        patcher.stop()
    assert len(fake.calls) == 1  # no retry


def test_gives_up_after_max_retries():
    script = [http_error(500)] * 10
    adapter, fake, patcher = make_adapter(script, max_retries=2)
    try:
        with mock.patch("time.sleep"):
            with pytest.raises(ShieldstralError, match="HTTP 500"):
                adapter.decide(decide_ctx(primitive="choice"))
    finally:
        patcher.stop()
    assert len(fake.calls) == 3  # 1 + 2 retries


def test_malformed_json_raises():
    script = [b"not json"]
    adapter, fake, patcher = make_adapter(script)
    try:
        with pytest.raises(ShieldstralError, match="bad response"):
            adapter.decide(decide_ctx(primitive="choice"))
    finally:
        patcher.stop()
