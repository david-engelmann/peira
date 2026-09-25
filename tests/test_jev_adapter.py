"""Tests for the Jev adapter (examples/jev_adapter.py).

All HTTP is mocked — no live API calls. The adapter is the only real-model
adapter in the repo, so it gets real coverage: every primitive, the
multi-option Noul mapping, abstention, and every error path in the HTTP
layer (retry, fail-fast, timeout, malformed responses, missing keys).
"""

import io
import json
import os
import time
import urllib.error
from unittest import mock

import pytest

from examples.jev_adapter import JevAdapter, JevError
from peira.adapters.base import (
    CaseContext,
    ChoiceOutput,
    AbstainOutput,
    ScoreOutput,
)


# ------------------------------------------------------------------
# Mock HTTP plumbing
# ------------------------------------------------------------------
class MockHTTPResponse:
    """Minimal context-manager response: read() -> bytes."""

    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def answer_payload(answer: dict) -> dict:
    """Wrap a per-question answer in the Jev response envelope."""
    return {"answers": {"q": answer}}


def make_urlopen(script):
    """Build a fake urlopen from a script.

    Each item is either:
    - dict  -> served as the JSON body of {"answers": {"q": <dict>}}
    - bytes -> served raw (for malformed-response tests)
    - Exception -> raised
    Records every call on .calls as (request, timeout).
    """
    calls = []
    items = iter(script)

    def fake_urlopen(req, timeout=None):
        calls.append((req, timeout))
        item = next(items)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, bytes):
            return MockHTTPResponse(item)
        return MockHTTPResponse(json.dumps(answer_payload(item)).encode())

    fake_urlopen.calls = calls
    return fake_urlopen


def make_adapter(script, **kwargs):
    """JevAdapter with urlopen patched to the script. Returns (adapter, fake)."""
    kwargs.setdefault("api_key", "test-key")
    kwargs.setdefault("min_interval", 0)  # no throttle unless the test says so
    adapter = JevAdapter(**kwargs)
    fake = make_urlopen(script)
    patcher = mock.patch("urllib.request.urlopen", fake)
    patcher.start()
    return adapter, fake, patcher


def http_error(code: int, body: bytes = b"error body") -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://api.typesafe.ai/v1/systemone", code, "HTTP error", {}, io.BytesIO(body)
    )


@pytest.fixture
def no_keys(monkeypatch):
    """Ensure neither API key env var is set."""
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)


def decide_ctx(prompt="Should we approve?", options=("approve", "deny"), primitive="choice"):
    return CaseContext(
        case_id="test-001",
        primitive=primitive,
        input={"prompt": prompt, "options": list(options)},
        attacked=False,
        variant="benign",
    )


# ------------------------------------------------------------------
# Primitive mapping
# ------------------------------------------------------------------
def test_choice_maps_winner_and_confidence():
    adapter, fake, patcher = None, None, None
    try:
        adapter, fake, patcher = make_adapter(
            [{"choice": "deny", "confidence": 0.82}]
        )
        out = adapter.decide(decide_ctx(primitive="choice"))
        assert isinstance(out, ChoiceOutput)
        assert out.decision == "deny"
        assert out.confidence == pytest.approx(0.82)
        assert len(fake.calls) == 1
    finally:
        if patcher:
            patcher.stop()


def test_score_maps_score_and_threshold_decision():
    adapter, fake, patcher = None, None, None
    try:
        adapter, fake, patcher = make_adapter([{"score": 0.7}])
        out = adapter.decide(decide_ctx(primitive="score"))
        assert isinstance(out, ScoreOutput)
        assert out.score == pytest.approx(0.7)
        assert out.decision == "approve"  # 0.7 >= 0.5 -> options[0]
    finally:
        if patcher:
            patcher.stop()


def test_score_below_threshold_picks_options_1():
    adapter, fake, patcher = None, None, None
    try:
        adapter, fake, patcher = make_adapter([{"score": 0.3}])
        out = adapter.decide(decide_ctx(primitive="score"))
        assert out.decision == "deny"  # 0.3 < 0.5 -> options[1]
    finally:
        if patcher:
            patcher.stop()


def test_noul_two_option_yes():
    adapter, fake, patcher = None, None, None
    try:
        adapter, fake, patcher = make_adapter([{"noul": 0.8}])
        out = adapter.decide(decide_ctx(primitive="abstain"))
        assert isinstance(out, AbstainOutput)
        assert out.decision == "approve"
        assert out.abstained is False
        assert len(fake.calls) == 1  # fast path: single query
    finally:
        if patcher:
            patcher.stop()


def test_noul_two_option_no():
    adapter, fake, patcher = None, None, None
    try:
        adapter, fake, patcher = make_adapter([{"noul": 0.2}])
        out = adapter.decide(decide_ctx(primitive="abstain"))
        assert out.decision == "deny"
        assert out.abstained is False
    finally:
        if patcher:
            patcher.stop()


def test_noul_three_option_picks_argmax():
    """P0-4 regression: options[2] must be reachable."""
    adapter, fake, patcher = None, None, None
    try:
        adapter, fake, patcher = make_adapter(
            [{"noul": 0.2}, {"noul": 0.35}, {"noul": 0.85}]
        )
        out = adapter.decide(
            decide_ctx(options=("a", "b", "c"), primitive="abstain")
        )
        assert out.decision == "c"
        assert out.abstained is False
        assert len(fake.calls) == 3  # one yes/no question per option
        # Each question names its own option.
        bodies = [
            json.loads(req.data.decode()) for req, _ in fake.calls
        ]
        instructions = [b["questions"]["q"]["instructions"] for b in bodies]
        assert "'a'" in instructions[0]
        assert "'b'" in instructions[1]
        assert "'c'" in instructions[2]
    finally:
        if patcher:
            patcher.stop()


def test_noul_four_option_picks_argmax():
    adapter, fake, patcher = None, None, None
    try:
        adapter, fake, patcher = make_adapter(
            [{"noul": 0.1}, {"noul": 0.75}, {"noul": 0.3}, {"noul": 0.6}]
        )
        out = adapter.decide(
            decide_ctx(options=("w", "x", "y", "z"), primitive="abstain")
        )
        assert out.decision == "x"
        assert len(fake.calls) == 4
    finally:
        if patcher:
            patcher.stop()


def test_noul_abstains_when_torn():
    adapter, fake, patcher = None, None, None
    try:
        adapter, fake, patcher = make_adapter([{"noul": 0.52}])
        out = adapter.decide(decide_ctx(primitive="abstain"))
        # |0.52 - 0.5| = 0.02 < 0.1 (default margin) -> abstain
        assert out.abstained is True
        assert out.decision == "approve"  # 0.52 >= 0.5 still picks options[0]
    finally:
        if patcher:
            patcher.stop()


def test_noul_multi_option_abstains_when_winner_torn():
    adapter, fake, patcher = None, None, None
    try:
        adapter, fake, patcher = make_adapter(
            [{"noul": 0.45}, {"noul": 0.55}, {"noul": 0.48}]
        )
        out = adapter.decide(
            decide_ctx(options=("a", "b", "c"), primitive="abstain")
        )
        assert out.decision == "b"  # argmax at 0.55
        assert out.abstained is True  # |0.55 - 0.5| < 0.1
    finally:
        if patcher:
            patcher.stop()


def test_score_threshold_boundary():
    """score exactly at threshold -> options[0] (>= semantics)."""
    adapter, fake, patcher = None, None, None
    try:
        adapter, fake, patcher = make_adapter([{"score": 0.5}])
        out = adapter.decide(decide_ctx(primitive="score"))
        assert out.decision == "approve"
    finally:
        if patcher:
            patcher.stop()


def test_choice_unknown_option_raises():
    adapter, fake, patcher = None, None, None
    try:
        adapter, fake, patcher = make_adapter(
            [{"choice": "maybe", "confidence": 0.9}]
        )
        with pytest.raises(JevError, match="unknown choice"):
            adapter.decide(decide_ctx(primitive="choice"))
    finally:
        if patcher:
            patcher.stop()


# ------------------------------------------------------------------
# HTTP layer: retries, fail-fast, timeouts, malformed
# ------------------------------------------------------------------
def test_429_retries_with_backoff_then_succeeds():
    adapter, fake, patcher = None, None, None
    try:
        adapter, fake, patcher = make_adapter(
            [http_error(429), {"choice": "approve", "confidence": 0.9}],
            max_retries=3,
        )
        with mock.patch("time.sleep") as sleep_mock:
            out = adapter.decide(decide_ctx(primitive="choice"))
        assert out.decision == "approve"
        assert len(fake.calls) == 2
        # Exponential backoff: first retry waits 2**0 = 1s.
        sleep_mock.assert_called_once_with(1.0)
    finally:
        if patcher:
            patcher.stop()


def test_401_fails_fast_single_attempt():
    adapter, fake, patcher = None, None, None
    try:
        adapter, fake, patcher = make_adapter(
            [http_error(401, b"bad key")], max_retries=5
        )
        with mock.patch("time.sleep") as sleep_mock:
            with pytest.raises(JevError, match="Jev HTTP 401"):
                adapter.decide(decide_ctx(primitive="choice"))
        assert len(fake.calls) == 1  # no retry on 401
        sleep_mock.assert_not_called()
    finally:
        if patcher:
            patcher.stop()


def test_500_retries_then_gives_up():
    adapter, fake, patcher = None, None, None
    try:
        adapter, fake, patcher = make_adapter(
            [http_error(500), http_error(500), http_error(500)],
            max_retries=2,
        )
        with mock.patch("time.sleep"):
            with pytest.raises(JevError, match="Jev HTTP 500"):
                adapter.decide(decide_ctx(primitive="choice"))
        assert len(fake.calls) == 3  # initial + 2 retries
    finally:
        if patcher:
            patcher.stop()


def test_missing_api_key_raises_clear_error(no_keys):
    with pytest.raises(JevError, match="no API key"):
        JevAdapter()


def test_openrouter_key_selects_passthrough(no_keys, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    adapter = JevAdapter(min_interval=0)
    assert adapter._api_base == "https://openrouter.ai/api/v1/systemone"
    assert adapter._model == "typesafe/jev-1.13"


def test_typesafe_key_preferred_over_openrouter(no_keys, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-test")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    adapter = JevAdapter(min_interval=0)
    assert adapter._api_base == "https://api.typesafe.ai/v1/systemone"
    assert adapter._model == "jev-1.13.0"


def test_malformed_json_raises_jev_error():
    adapter, fake, patcher = None, None, None
    try:
        adapter, fake, patcher = make_adapter(
            [b"not json {{{", b"not json {{{}"],
            max_retries=1,
        )
        with mock.patch("time.sleep"):
            with pytest.raises(JevError, match="Jev request failed"):
                adapter.decide(decide_ctx(primitive="choice"))
    finally:
        if patcher:
            patcher.stop()


def test_http_timeout_raises_jev_error():
    adapter, fake, patcher = None, None, None
    try:
        adapter, fake, patcher = make_adapter(
            [TimeoutError("timed out")], max_retries=0
        )
        with pytest.raises(JevError, match="Jev request failed"):
            adapter.decide(decide_ctx(primitive="choice"))
        assert len(fake.calls) == 1
    finally:
        if patcher:
            patcher.stop()


def test_missing_answer_key_raises():
    adapter, fake, patcher = None, None, None
    try:
        # Envelope without the "q" answer.
        fake_raw = make_urlopen([b'{"answers": {}}'])
        adapter = JevAdapter(api_key="test-key", min_interval=0)
        patcher = mock.patch("urllib.request.urlopen", fake_raw)
        patcher.start()
        with pytest.raises(JevError, match="missing answer"):
            adapter.decide(decide_ctx(primitive="choice"))
    finally:
        if patcher:
            patcher.stop()


def test_min_interval_throttle():
    adapter, fake, patcher = None, None, None
    try:
        adapter, fake, patcher = make_adapter(
            [
                {"choice": "approve", "confidence": 0.9},
                {"choice": "deny", "confidence": 0.9},
            ],
            min_interval=0.3,
        )
        t0 = time.monotonic()
        adapter.decide(decide_ctx(primitive="choice"))
        t1 = time.monotonic()
        adapter.decide(decide_ctx(primitive="choice"))
        t2 = time.monotonic()
        # The second call was throttled: it waited until >= 0.3s after the
        # first call's request before sending its own.
        assert (t2 - t1) >= 0.29
        assert len(fake.calls) == 2
    finally:
        if patcher:
            patcher.stop()


def test_unsupported_primitive_raises():
    adapter = JevAdapter(api_key="test-key", min_interval=0)
    with pytest.raises(ValueError, match="unknown primitive"):
        CaseContext(case_id="x", primitive="bogus", input={}, attacked=False, variant="benign")


def test_choice_needs_two_options():
    adapter = JevAdapter(api_key="test-key", min_interval=0)
    with pytest.raises(JevError, match="choice needs"):
        adapter.decide(decide_ctx(options=("only",), primitive="choice"))
