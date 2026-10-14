"""Tests for the OpenAI Decisions API adapter.

All transport is faked: no network, no API key, no access needed.
The fake transport receives the exact payload the adapter would POST
and returns a canned parsed response.

The fakes are written against the documented Decisions wire shape —
``input`` plus a ``questions`` array in requests; ``choice`` /
``score`` / ``predicate`` / ``refusal`` answers with per-option
probability arrays in responses — as exercised live by the design
lane's probe on 2026-10-14 (choice and score shapes) and documented
in the API reference (predicate and refusal shapes).
"""

import unittest

from peira.adapters.base import CallContext, ProviderError, validate_output
from peira.adapters import openai_decisions as od_mod
from peira.adapters.openai_decisions import (
    API_KEY_ENV,
    MODEL_ID,
    OpenAIDecisionsAdapter,
)

_CHOICE_INSTRUCTIONS = (
    "Given the decision context in the request state, which "
    "option is the correct decision? Answer with exactly one of "
    "the listed options."
)
_SCORE_INSTRUCTIONS = (
    "Rate the quality of the correct decision for this case on "
    "the ordered scale below, from the worst to the best level."
)
_ABSTAIN_INSTRUCTIONS = (
    "Should this case be abstained — is there no confident "
    "correct decision?"
)
_RUBRIC = [
    "clearly the wrong decision",
    "probably the wrong decision",
    "uncertain — could go either way",
    "probably the right decision",
    "clearly the right decision",
]


def _case_input(**over):
    d = {"prompt": "Decision: approve or deny?",
         "options": ["approve", "deny"]}
    d.update(over)
    return d


def _ctx():
    return CallContext(call_id="call-test")


def _choice_answer(choice="approve", confidence=0.65, probs=None):
    if probs is None:
        probs = [("approve", 0.7), ("deny", 0.2), ("other", 0.1)]
    ans = {
        "type": "choice",
        "name": "decision",
        "choice": choice,
        "probabilities": [
            {"value": v, "probability": p} for v, p in probs
        ],
    }
    if confidence is not None:
        ans["confidence"] = confidence
    return ans


def _score_answer(score=2.66, confidence=0.22, probs=None):
    if probs is None:
        probs = [(0, 0.14), (1, 0.05), (2, 0.12), (3, 0.39), (4, 0.30)]
    ans = {
        "type": "score",
        "name": "score",
        "probabilities": [
            {"value": i, "label": _RUBRIC[i], "probability": p}
            for i, p in probs
        ],
        "confidence": confidence,
    }
    if score is not None:
        ans["score"] = score
    return ans


def _transport_for(answers, usage=None, latency=12.5):
    seen = {"calls": 0}

    def fake(payload):
        seen["calls"] += 1
        seen["payload"] = payload
        return {
            "model": MODEL_ID,
            "answers": answers,
            "usage": usage or {"input_tokens": 100, "output_tokens": 0},
            "_latency_ms": latency,
        }

    fake.seen = seen
    return fake


class TestConstruction(unittest.TestCase):
    def test_missing_key_is_actionable(self):
        import os
        old = os.environ.pop(API_KEY_ENV, None)
        try:
            with self.assertRaises(ValueError) as cm:
                OpenAIDecisionsAdapter()
        finally:
            if old is not None:
                os.environ[API_KEY_ENV] = old
        self.assertIn(API_KEY_ENV, str(cm.exception))

    def test_explicit_key_ok(self):
        a = OpenAIDecisionsAdapter(api_key="k")
        self.assertEqual(a._api_key, "k")

    def test_model_pinned_rejects_any_other(self):
        for bad in ("gpt-6-luna-latest", "gpt-5.6-luna", "gpt-6", ""):
            with self.subTest(model=bad):
                with self.assertRaises(ValueError):
                    OpenAIDecisionsAdapter(api_key="k", model=bad)
        a = OpenAIDecisionsAdapter(api_key="k")
        self.assertEqual(a.model, MODEL_ID)
        self.assertEqual(MODEL_ID, "gpt-6-luna")

    def test_declared_properties(self):
        a = OpenAIDecisionsAdapter(api_key="k")
        self.assertEqual(a.name, "openai-decisions")
        self.assertEqual(a.version, MODEL_ID)
        self.assertEqual(a.supported_primitives,
                         frozenset({"choice", "score", "abstain"}))
        self.assertEqual(a.confidence_source, "token-logprob")
        self.assertEqual(a.model_class, "llm-baseline")
        self.assertEqual(a.cache_namespace, f"openai-decisions:{MODEL_ID}:v1")


class TestChoice(unittest.TestCase):
    def test_choice_maps_option_and_confidence_field(self):
        # Confidence 0.65 differs from the top probability 0.7: the
        # output must carry the answer's confidence field, not the
        # chosen option's probability.
        t = _transport_for([_choice_answer()])
        out = OpenAIDecisionsAdapter(api_key="k", transport=t).decide(
            _case_input(), "choice", _ctx())
        self.assertEqual(validate_output(out, "choice"), [])
        self.assertEqual(out.decision, "approve")
        self.assertAlmostEqual(out.confidence, 0.65)
        self.assertFalse(out.abstained)

    def test_choice_usage_and_cached_tokens(self):
        usage = {
            "input_tokens": 301,
            "output_tokens": 0,
            "input_tokens_details": {"cached_tokens": 12,
                                     "cache_write_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": 301,
        }
        t = _transport_for([_choice_answer()], usage=usage)
        out = OpenAIDecisionsAdapter(api_key="k", transport=t).decide(
            _case_input(), "choice", _ctx())
        self.assertEqual(out.usage.model, MODEL_ID)
        self.assertEqual(out.usage.tokens_in, 301)
        self.assertEqual(out.usage.tokens_out, 0)
        self.assertEqual(out.usage.cached_tokens_in, 12)

    def test_choice_cached_tokens_absent_is_none(self):
        t = _transport_for([_choice_answer()])
        out = OpenAIDecisionsAdapter(api_key="k", transport=t).decide(
            _case_input(), "choice", _ctx())
        self.assertIsNone(out.usage.cached_tokens_in)

    def test_malformed_usage_values_raise_provider_error(self):
        # A present usage value that is not a non-negative int is wire
        # drift. It must raise ProviderError, never be coerced into a
        # wrong token count or silently dropped to None.
        from peira.adapters.base import ProviderError
        bad_usages = [
            {"input_tokens": True, "output_tokens": 0},
            {"input_tokens": 301.5, "output_tokens": 0},
            {"input_tokens": -1, "output_tokens": 0},
            {"input_tokens": "301", "output_tokens": 0},
            {"input_tokens": 301, "output_tokens": 0,
             "input_tokens_details": {"cached_tokens": "12"}},
            {"input_tokens": 301, "output_tokens": 0,
             "input_tokens_details": {"cached_tokens": -3}},
        ]
        for usage in bad_usages:
            t = _transport_for([_choice_answer()], usage=usage)
            with self.assertRaises(ProviderError, msg=f"usage={usage!r}"):
                OpenAIDecisionsAdapter(api_key="k", transport=t).decide(
                    _case_input(), "choice", _ctx())

    def test_choice_request_shape(self):
        t = _transport_for([_choice_answer()])
        OpenAIDecisionsAdapter(api_key="k", transport=t).decide(
            _case_input(), "choice", _ctx())
        payload = t.seen["payload"]
        self.assertEqual(set(payload), {"model", "input", "questions"})
        self.assertEqual(payload["model"], MODEL_ID)
        # The case prompt rides as the plain-string input form.
        self.assertEqual(payload["input"], "Decision: approve or deny?")
        # No safety_identifier: case-identifying values never cross
        # the adapter boundary (D-25).
        self.assertNotIn("safety_identifier", payload)
        self.assertEqual(len(payload["questions"]), 1)
        q = payload["questions"][0]
        self.assertEqual(set(q), {"type", "name", "instructions", "choices"})
        self.assertEqual(q["type"], "choice")
        self.assertEqual(q["name"], "decision")
        self.assertEqual(q["instructions"], _CHOICE_INSTRUCTIONS)
        values = [c["value"] for c in q["choices"]]
        self.assertEqual(values, ["approve", "deny", "other"])
        by_value = {c["value"]: c["description"] for c in q["choices"]}
        self.assertEqual(by_value["approve"],
                         "Decide 'approve' for this case.")
        self.assertEqual(by_value["other"],
                         "None of the listed options is the correct decision.")

    def test_choice_labels_sorted_and_deduplicated(self):
        # B2: labels are exactly the input's options (sorted, deduped)
        # plus "other" — the adapter cannot see the arm or gold.
        t = _transport_for([_choice_answer()])
        OpenAIDecisionsAdapter(api_key="k", transport=t).decide(
            _case_input(options=["deny", "deny", "approve", "hold"]),
            "choice", _ctx())
        values = [c["value"]
                  for c in t.seen["payload"]["questions"][0]["choices"]]
        self.assertEqual(values, ["approve", "deny", "hold", "other"])

    def test_choice_distribution_rides_in_transcript(self):
        ans = _choice_answer()
        t = _transport_for([ans])
        out = OpenAIDecisionsAdapter(api_key="k", transport=t).decide(
            _case_input(), "choice", _ctx())
        recorded = out.transcript["response"]["answers"][0]
        self.assertEqual(recorded["probabilities"], ans["probabilities"])
        self.assertEqual(recorded["confidence"], 0.65)

    def test_choice_confidence_fallback_to_chosen_probability(self):
        t = _transport_for([_choice_answer(confidence=None)])
        out = OpenAIDecisionsAdapter(api_key="k", transport=t).decide(
            _case_input(), "choice", _ctx())
        self.assertAlmostEqual(out.confidence, 0.7)  # P(approve)

    def test_choice_confidence_fallback_to_half(self):
        # No confidence field and the chosen value missing from the
        # distribution: the neutral 0.5, never an invented number.
        ans = _choice_answer(confidence=None,
                             probs=[("deny", 0.6), ("other", 0.4)])
        t = _transport_for([ans])
        out = OpenAIDecisionsAdapter(api_key="k", transport=t).decide(
            _case_input(), "choice", _ctx())
        self.assertAlmostEqual(out.confidence, 0.5)

    def test_choice_unknown_option_is_terminal(self):
        t = _transport_for([_choice_answer(choice="maybe")])
        with self.assertRaises(ProviderError):
            OpenAIDecisionsAdapter(api_key="k", transport=t).decide(
                _case_input(), "choice", _ctx())

    def test_choice_non_numeric_probability_is_terminal(self):
        ans = _choice_answer(probs=[("approve", "high"), ("deny", 0.2),
                                    ("other", 0.1)])
        t = _transport_for([ans])
        with self.assertRaises(ProviderError):
            OpenAIDecisionsAdapter(api_key="k", transport=t).decide(
                _case_input(), "choice", _ctx())

    def test_choice_refusal_maps_to_abstained(self):
        t = _transport_for([{"type": "refusal", "name": "decision"}])
        out = OpenAIDecisionsAdapter(api_key="k", transport=t).decide(
            _case_input(), "choice", _ctx())
        self.assertEqual(validate_output(out, "choice"), [])
        self.assertTrue(out.abstained)
        self.assertEqual(out.decision, "")
        self.assertEqual(out.refusal_reason, "decisions refusal")

    def test_unsupported_primitive(self):
        with self.assertRaises(ValueError):
            OpenAIDecisionsAdapter(api_key="k").decide(
                _case_input(), "bogus", _ctx())


class TestScore(unittest.TestCase):
    def _adapter(self, answers, **kw):
        t = _transport_for(answers, **kw)
        return OpenAIDecisionsAdapter(api_key="k", transport=t), t

    def test_score_batches_two_questions_in_one_request(self):
        a, t = self._adapter([_score_answer(), _choice_answer()])
        a.decide(_case_input(), "score", _ctx())
        # One HTTP call, two questions about the same input.
        self.assertEqual(t.seen["calls"], 1)
        questions = t.seen["payload"]["questions"]
        self.assertEqual([q["name"] for q in questions],
                         ["score", "decision"])
        sq = questions[0]
        self.assertEqual(set(sq), {"type", "name", "instructions", "levels"})
        self.assertEqual(sq["type"], "score")
        self.assertEqual(sq["instructions"], _SCORE_INSTRUCTIONS)
        # The five rubric labels in order, labels only (no
        # descriptions), so the rubric text is the Jev wire's.
        self.assertEqual([lv["label"] for lv in sq["levels"]], _RUBRIC)
        for lv in sq["levels"]:
            self.assertEqual(set(lv), {"label"})

    def test_score_normalized_and_decision_confidence(self):
        # Score 2.66 on the five-level rubric normalizes to 0.665.
        # The confidence is the paired decision answer's (0.65), not
        # the score answer's own (0.22).
        a, _ = self._adapter([_score_answer(), _choice_answer()])
        out = a.decide(_case_input(), "score", _ctx())
        self.assertEqual(validate_output(out, "score"), [])
        self.assertAlmostEqual(out.score, 2.66 / 4)
        self.assertEqual(out.decision, "approve")
        self.assertAlmostEqual(out.confidence, 0.65)

    def test_score_fallback_weighted_from_probabilities(self):
        probs = [(0, 0.0), (1, 0.0), (2, 0.0), (3, 0.5), (4, 0.5)]
        a, _ = self._adapter([
            _score_answer(score=None, probs=probs), _choice_answer()])
        out = a.decide(_case_input(), "score", _ctx())
        self.assertAlmostEqual(out.score, 3.5 / 4)

    def test_score_missing_score_and_probabilities_is_terminal(self):
        ans = _score_answer(score=None, probs=[])
        a, _ = self._adapter([ans, _choice_answer()])
        with self.assertRaises(ProviderError):
            a.decide(_case_input(), "score", _ctx())

    def test_score_non_numeric_probability_is_terminal(self):
        # Probabilities are validated whenever the wire sends them,
        # even when the score itself is present.
        probs = [(0, 0.14), (1, "high"), (2, 0.12), (3, 0.39), (4, 0.30)]
        a, _ = self._adapter([
            _score_answer(probs=probs), _choice_answer()])
        with self.assertRaises(ProviderError):
            a.decide(_case_input(), "score", _ctx())

    def test_score_refusal_on_score_question_abstains(self):
        a, _ = self._adapter([
            {"type": "refusal", "name": "score"}, _choice_answer()])
        out = a.decide(_case_input(), "score", _ctx())
        self.assertEqual(validate_output(out, "score"), [])
        self.assertTrue(out.abstained)
        self.assertEqual(out.decision, "")
        self.assertEqual(out.refusal_reason, "decisions refusal")

    def test_score_refusal_on_decision_question_abstains(self):
        a, _ = self._adapter([
            _score_answer(), {"type": "refusal", "name": "decision"}])
        out = a.decide(_case_input(), "score", _ctx())
        self.assertTrue(out.abstained)
        self.assertEqual(out.decision, "")

    def test_score_unknown_decision_is_terminal(self):
        a, _ = self._adapter([
            _score_answer(), _choice_answer(choice="maybe")])
        with self.assertRaises(ProviderError):
            a.decide(_case_input(), "score", _ctx())

    def test_score_missing_decision_answer_is_terminal(self):
        a, _ = self._adapter([_score_answer()])
        with self.assertRaises(ProviderError):
            a.decide(_case_input(), "score", _ctx())


class TestAbstain(unittest.TestCase):
    def _run(self, ans):
        t = _transport_for([ans])
        return OpenAIDecisionsAdapter(api_key="k", transport=t).decide(
            _case_input(), "abstain", _ctx()), t

    def test_abstain_request_shape(self):
        _, t = self._run({"type": "predicate", "name": "abstain",
                          "probability": 0.1})
        q = t.seen["payload"]["questions"][0]
        self.assertEqual(set(q), {"type", "name", "instructions"})
        self.assertEqual(q["type"], "predicate")
        self.assertEqual(q["name"], "abstain")
        self.assertEqual(q["instructions"], _ABSTAIN_INSTRUCTIONS)

    def test_probability_at_or_above_half_is_abstain_decision(self):
        out, _ = self._run({"type": "predicate", "name": "abstain",
                            "probability": 0.8})
        self.assertEqual(validate_output(out, "abstain"), [])
        self.assertEqual(out.decision, "abstain")
        # A deliberate abstention is a decision, not a refusal.
        self.assertFalse(out.abstained)
        self.assertAlmostEqual(out.confidence, 0.6)  # |2*.8-1|

    def test_probability_exactly_half_abstains(self):
        out, _ = self._run({"type": "predicate", "name": "abstain",
                            "probability": 0.5})
        self.assertEqual(out.decision, "abstain")
        self.assertAlmostEqual(out.confidence, 0.0)

    def test_probability_below_half_returns_other_placeholder(self):
        # No abstention means the model emitted no decision label:
        # the placeholder is "other", never a gold label.
        out, _ = self._run({"type": "predicate", "name": "abstain",
                            "probability": 0.2})
        self.assertEqual(out.decision, "other")
        self.assertFalse(out.abstained)
        self.assertAlmostEqual(out.confidence, 0.6)

    def test_abstain_refusal_maps_to_abstained(self):
        out, _ = self._run({"type": "refusal", "name": "abstain"})
        self.assertEqual(validate_output(out, "abstain"), [])
        self.assertTrue(out.abstained)
        self.assertEqual(out.decision, "")
        self.assertEqual(out.refusal_reason, "decisions refusal")

    def test_missing_probability_is_terminal(self):
        with self.assertRaises(ProviderError):
            self._run({"type": "predicate", "name": "abstain"})

    def test_non_numeric_probability_is_terminal(self):
        with self.assertRaises(ProviderError):
            self._run({"type": "predicate", "name": "abstain",
                       "probability": "high"})


class TestResponseShapeBreaks(unittest.TestCase):
    def test_missing_answers_key_is_terminal(self):
        def fake(payload):
            return {"model": MODEL_ID, "_latency_ms": 1.0}
        with self.assertRaises(ProviderError):
            OpenAIDecisionsAdapter(api_key="k", transport=fake).decide(
                _case_input(), "choice", _ctx())

    def test_answers_not_a_list_is_terminal(self):
        def fake(payload):
            return {"model": MODEL_ID,
                    "answers": {"decision": {}},
                    "_latency_ms": 1.0}
        with self.assertRaises(ProviderError):
            OpenAIDecisionsAdapter(api_key="k", transport=fake).decide(
                _case_input(), "choice", _ctx())

    def test_empty_answers_is_terminal(self):
        t = _transport_for([])
        with self.assertRaises(ProviderError):
            OpenAIDecisionsAdapter(api_key="k", transport=t).decide(
                _case_input(), "choice", _ctx())

    def test_transcript_has_no_key_material(self):
        import json
        t = _transport_for([_choice_answer()])
        adapter = OpenAIDecisionsAdapter(api_key="sk-secret-key",
                                         transport=t)
        out = adapter.decide(_case_input(), "choice", _ctx())
        self.assertNotIn("sk-secret-key", json.dumps(out.transcript))
        self.assertNotIn("sk-secret-key", json.dumps(t.seen["payload"]))


class TestQuestionValidation(unittest.TestCase):
    def test_malformed_questions_are_terminal_before_send(self):
        with self.assertRaises(ProviderError):
            od_mod._validate_questions(
                [{"type": "choice", "name": "d", "instructions": "i"}])
        with self.assertRaises(ProviderError):
            od_mod._validate_questions(
                [{"type": "score", "name": "s", "instructions": "i",
                  "levels": [{"label": "only"}]}])
        with self.assertRaises(ProviderError):
            od_mod._validate_questions(
                [{"type": "bogus", "name": "x", "instructions": "i"}])
        with self.assertRaises(ProviderError):
            od_mod._validate_questions(
                [{"type": "predicate", "instructions": "i"}])  # no name
        # The adapter's own builders pass silently.
        od_mod._validate_questions([
            od_mod._choice_question(["approve", "other"]),
            od_mod._score_question(),
            od_mod._abstain_question(),
        ])


class TestErrors(unittest.TestCase):
    def test_raise_for_status_mapping(self):
        a = OpenAIDecisionsAdapter.__new__(OpenAIDecisionsAdapter)
        for status in (400, 401, 403, 404, 422, 408, 409, 429, 529,
                       500, 503):
            with self.subTest(status=status):
                with self.assertRaises(ProviderError) as cm:
                    a._raise_for_status(status, None, "detail")
                self.assertEqual(cm.exception.status_code, status)

    def test_429_carries_retry_after(self):
        a = OpenAIDecisionsAdapter.__new__(OpenAIDecisionsAdapter)
        with self.assertRaises(ProviderError) as cm:
            a._raise_for_status(429, "7", "rate limited code=slow_down")
        self.assertEqual(cm.exception.status_code, 429)
        self.assertEqual(cm.exception.retry_after, 7.0)
        # The provider code rides in the message, so a billing-side
        # stop is visible as what it is.
        self.assertIn("slow_down", str(cm.exception))

    def test_transport_error_passes_through_decide(self):
        def boom(payload):
            raise ProviderError("openai-decisions API error 503",
                                status_code=503)
        with self.assertRaises(ProviderError) as cm:
            OpenAIDecisionsAdapter(api_key="k", transport=boom).decide(
                _case_input(), "choice", _ctx())
        self.assertEqual(cm.exception.status_code, 503)

    def test_connection_failure_maps_to_408(self):
        import urllib.error
        from unittest import mock
        adapter = OpenAIDecisionsAdapter(api_key="k")
        with mock.patch("urllib.request.urlopen",
                        side_effect=urllib.error.URLError("timed out")):
            with self.assertRaises(ProviderError) as cm:
                adapter._http_transport({"model": MODEL_ID})
        # 408 is on the runner's transient-retry path.
        self.assertEqual(cm.exception.status_code, 408)

    def test_http_error_envelope_surfaces_code_and_retry_after(self):
        import email.message
        import io
        import urllib.error
        from unittest import mock
        body = (b'{"error": {"message": "Requests ramped too fast", '
                b'"type": "rate_limit_error", "code": "slow_down"}}')
        hdrs = email.message.Message()
        hdrs["Retry-After"] = "3"
        err = urllib.error.HTTPError(
            "https://api.openai.com/v1/decisions", 429,
            "Too Many Requests", hdrs, io.BytesIO(body))
        adapter = OpenAIDecisionsAdapter(api_key="k")
        with mock.patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(ProviderError) as cm:
                adapter._http_transport({"model": MODEL_ID})
        self.assertEqual(cm.exception.status_code, 429)
        self.assertEqual(cm.exception.retry_after, 3.0)
        self.assertIn("slow_down", str(cm.exception))

    def test_non_json_response_is_terminal(self):
        import io
        from unittest import mock

        class FakeResp:
            status = 200
            headers = {}

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b"not json"

        adapter = OpenAIDecisionsAdapter(api_key="k")
        with mock.patch("urllib.request.urlopen",
                        return_value=FakeResp()):
            with self.assertRaises(ProviderError):
                adapter._http_transport({"model": MODEL_ID})


class TestPricing(unittest.TestCase):
    def test_decisions_usage_prices_at_input_rate_only(self):
        # The decisions wire reports output_tokens 0, so the real
        # pricing table (gpt-6-luna: $0.10 in / $0.50 out, official)
        # computes exactly the endpoint's input-only charge. The
        # usage model string must be the table key or the runner
        # prices the call at 0.0 (explicitly unaccounted).
        from peira.pricing import (
            cost_usd,
            is_cost_accounted,
            load_pricing_table,
        )
        table = load_pricing_table()
        usage = {
            "input_tokens": 301,
            "output_tokens": 0,
            "input_tokens_details": {"cached_tokens": 0},
            "total_tokens": 301,
        }
        t = _transport_for([_choice_answer()], usage=usage)
        out = OpenAIDecisionsAdapter(api_key="k", transport=t).decide(
            _case_input(), "choice", _ctx())
        self.assertEqual(out.usage.tokens_out, 0)
        self.assertTrue(is_cost_accounted(out.usage.model, table))
        got = cost_usd(out.usage.model, out.usage.tokens_in,
                       out.usage.tokens_out, table)
        self.assertAlmostEqual(got, 301 * 0.10 / 1_000_000, places=12)
        # The contrast that proves the point: the same call with a
        # nonzero output count would price higher, so the zero is
        # load-bearing, not a rounding artifact.
        with_output = cost_usd(out.usage.model, out.usage.tokens_in,
                               1000, table)
        self.assertGreater(with_output, got)


if __name__ == "__main__":
    unittest.main()
