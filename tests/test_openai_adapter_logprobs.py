"""Tests for the OpenAI gpt-5.6-luna logprobs omission.

``gpt-5.6-luna`` rejects ``logprobs`` with HTTP 400: "Unsupported
parameter: 'logprobs' is not supported with this model." (observed
live 2026-10-03, after PR #428 fixed the temperature 400). The
adapter must OMIT ``logprobs`` for that model via
``_NO_LOGPROBS_MODELS`` — the same per-model pattern as
``_MAX_COMPLETION_TOKENS_MODELS`` / ``_MODEL_TEMPERATURE_OVERRIDES`` —
and handle the missing logprobs gracefully: the transcript records
``"logprobs": False``, the decision-token logprob track is ``None``,
and confidence stays on the verbalized track (D-23).

The ``openai`` SDK is faked in sys.modules: no API keys, no network.
The fakes record exact request payloads so the tests can assert on
the payload actually placed on the wire and in the transcript.
"""

import json
import os
import sys
import unittest
from contextlib import contextmanager
from types import ModuleType, SimpleNamespace

from peira.adapters.llm import OpenAIAdapter
from peira.adapters.base import CallContext


# ---------------------------------------------------------------------------
# Fake openai SDK (mirrors tests/test_openai_adapter_temperature.py).
# ---------------------------------------------------------------------------

def _openai_completion(content, finish_reason="stop", with_logprobs=True):
    # When logprobs is not requested, the provider omits the field
    # from the response — mirror that by leaving the attribute off.
    choice_kwargs = {
        "message": SimpleNamespace(content=content),
        "finish_reason": finish_reason,
    }
    if with_logprobs:
        choice_kwargs["logprobs"] = SimpleNamespace(content=[])
    return SimpleNamespace(
        choices=[SimpleNamespace(**choice_kwargs)],
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


class TestOpenAILogprobsOmission(unittest.TestCase):
    """gpt-5.6-luna 400s on logprobs: the adapter must omit the field.

    Regression test: ``_request_kwargs`` must not place ``logprobs``
    on the wire for the pinned model, the transcript must honestly
    record the omission, and the missing logprobs must degrade
    gracefully (no logprob track; confidence stays verbalized).
    """

    def setUp(self):
        self.mod, self.calls, self.created = _make_openai(
            [_openai_completion(GOOD_JSON, with_logprobs=False)])
        self._m = _fake_modules({"openai": self.mod})
        self._m.__enter__()
        self._e = _env(OPENAI_API_KEY="sk-test")
        self._e.__enter__()
        self.addCleanup(self._e.__exit__, None, None, None)
        self.addCleanup(self._m.__exit__, None, None, None)

    def test_pinned_model_omits_logprobs_on_wire(self):
        # The 400 came from sending logprobs=True to gpt-5.6-luna —
        # the field must not be in the wire payload at all.
        OpenAIAdapter().decide(CASE, "choice", _ctx())
        self.assertNotIn("logprobs", self.calls[0])

    def test_pinned_model_transcript_records_omission(self):
        out = OpenAIAdapter().decide(CASE, "choice", _ctx())
        self.assertFalse(out.transcript["request"]["logprobs"])

    def test_pinned_model_decide_returns_valid_decision(self):
        # Missing logprobs must degrade gracefully: the decision and
        # verbalized confidence come through; the logprob track is None.
        out = OpenAIAdapter().decide(CASE, "choice", _ctx())
        self.assertEqual(out.decision, "approve")
        self.assertEqual(out.confidence, 0.73)
        tracks = out.transcript["confidence_tracks"]
        self.assertIsNone(tracks["decision_token_logprob"])
        self.assertEqual(tracks["verbalized"], 0.73)
        # Confidence stays on the verbalized track (D-23): the
        # adapter-level confidence_source never changes.
        self.assertEqual(OpenAIAdapter.confidence_source, "verbalized")

    def test_unlisted_model_still_sends_logprobs(self):
        # Models without an entry keep the historical wire behavior.
        mod, calls, _ = _make_openai(
            [_openai_completion(GOOD_JSON, with_logprobs=True)])
        with _fake_modules({"openai": mod}):
            OpenAIAdapter(model="gpt-4o").decide(CASE, "choice", _ctx())
        self.assertTrue(calls[0]["logprobs"])

    def test_unlisted_model_transcript_records_logprobs(self):
        mod, calls, _ = _make_openai(
            [_openai_completion(GOOD_JSON, with_logprobs=True)])
        with _fake_modules({"openai": mod}):
            out = OpenAIAdapter(model="gpt-4o").decide(CASE, "choice", _ctx())
        self.assertTrue(out.transcript["request"]["logprobs"])

    def test_no_logprobs_set_covers_pinned_model(self):
        self.assertIn("gpt-5.6-luna", OpenAIAdapter._NO_LOGPROBS_MODELS)


if __name__ == "__main__":
    unittest.main()
