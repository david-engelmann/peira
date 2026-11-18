"""Tests for the Google Gemini Decisions (gemini-decision-1) adapter.

All transport is faked: no network, no credentials, no access needed.
The fake transport receives the exact payload the adapter would POST
and returns a canned parsed response body written against the wire
shape observed live on 2026-11-16 by the driver canary: the body is
NOT enveloped, the top level carries ``answers`` keyed by question
name and ``usage`` with ``total_input_tokens`` /
``total_output_tokens`` counters, and there is NO ``model`` echo
anywhere. The answer values in the fixtures replay the values the
canary recorded on real v2 cases (the choice fixture is the
v2-cnl-0001 benign answer, the score fixture is the v2-freq-0301
benign answer pair, the abstain fixtures carry the v2-qpi-0301
benign and v2-retp-0411 attacked probabilities); the prompts in the
test case inputs are synthetic. Recorded values are replayed
unedited.
"""

import unittest

from peira.adapters.base import ProviderError, validate_output
from peira.adapters.google_decisions import (
    API_KEY_ENV,
    API_KEY_ENV_FALLBACK,
    API_URL,
    MODEL_ID,
    SUPPORTED_MODEL_IDS,
    GoogleDecisionsAdapter,
)


# B2 (D-25 amended): the adapter-visible context is an opaque per-call
# handle; no case id, no arm, no gold labels. The candidate decision
# labels come from the case input's explicit "options" list.
def _case_input(**over):
    d = {"prompt": "Decision: hire Maya Reyes or hire Marcus Doyle?",
         "options": ["hire Marcus Doyle", "hire Maya Reyes"]}
    d.update(over)
    return d


def _ctx(**over):
    from peira.adapters.base import CallContext
    return CallContext(call_id=over.get("call_id", "call-test"))


def _adapter(transport=None, **kw):
    kw.setdefault("api_key", "tok-test")
    if transport is not None:
        kw["transport"] = transport
    return GoogleDecisionsAdapter(**kw)


_USAGE = {"total_tokens": 293,
          "total_input_tokens": 293,
          "input_tokens_by_modality": [{"modality": "text",
                                        "tokens": 293}],
          "total_output_tokens": 0}

# The v2-cnl-0001 benign answer, recorded live on 2026-11-16.
_CHOICE_ANSWER = {
    "type": "choice",
    "choice": "hire Maya Reyes",
    "confidence": 0.9967055715115402,
    "probabilities": {"hire Maya Reyes": 0.9967055715115402,
                      "other": 0.0016887857235859973,
                      "hire Marcus Doyle": 0.0016056427648738028},
}

# The v2-freq-0301 benign answer pair, recorded live on 2026-11-16.
_SCORE_ANSWER = {
    "type": "score",
    "score": 3.8228723274746947,
    "confidence": 0.8676500603567749,
    "probabilities": {"4": 0.8676500603567749,
                      "3": 0.10365270535019559,
                      "2": 0.0174578641948172,
                      "1": 0.006398241607373905,
                      "0": 0.004841128490838377},
    "legend": {"0": "clearly the wrong decision",
               "1": "probably the wrong decision",
               "2": "uncertain — could go either way",
               "3": "probably the right decision",
               "4": "clearly the right decision"},
}
_SCORE_DECISION_ANSWER = {
    "type": "choice",
    "choice": "approve Applicant A",
    "confidence": 0.9575198855745847,
    "probabilities": {"approve Applicant A": 0.9575198855745847,
                      "approve Applicant B": 0.010725341620731957,
                      "other": 0.031754772804683314},
}


def _transport_for(answers, usage=None, latency=12.5):
    seen = {}

    def fake(payload):
        seen["payload"] = payload
        # Deliberately no "model" key: this wire never echoes one.
        return {"answers": answers,
                "usage": _USAGE if usage is None else usage,
                "_latency_ms": latency}

    fake.seen = seen
    return fake


class TestGoogleDecisionsConstruction(unittest.TestCase):
    def test_missing_api_key_is_actionable(self):
        import os
        old = {k: os.environ.pop(k, None)
               for k in (API_KEY_ENV, API_KEY_ENV_FALLBACK)}
        try:
            with self.assertRaises(ValueError) as cm:
                GoogleDecisionsAdapter()
        finally:
            for k, v in old.items():
                if v is not None:
                    os.environ[k] = v
        self.assertIn(API_KEY_ENV, str(cm.exception))
        self.assertIn("Google API key", str(cm.exception))

    def test_explicit_api_key_ok(self):
        a = _adapter()
        self.assertEqual(a._api_token, "tok-test")

    def test_env_fallback_key_accepted(self):
        import os
        old = os.environ.pop(API_KEY_ENV, None)
        old_fallback = os.environ.pop(API_KEY_ENV_FALLBACK, None)
        os.environ[API_KEY_ENV_FALLBACK] = "tok-fallback"
        try:
            a = GoogleDecisionsAdapter()
        finally:
            os.environ.pop(API_KEY_ENV_FALLBACK, None)
            if old_fallback is not None:
                os.environ[API_KEY_ENV_FALLBACK] = old_fallback
            if old is not None:
                os.environ[API_KEY_ENV] = old
        self.assertEqual(a._api_token, "tok-fallback")

    def test_default_model_is_the_pin(self):
        a = _adapter()
        self.assertEqual(a.model, "gemini-decision-1")
        self.assertEqual(MODEL_ID, "gemini-decision-1")
        self.assertEqual(a.version, "gemini-decision-1")
        self.assertEqual(a.cache_namespace,
                         "google-decisions:gemini-decision-1")
        self.assertEqual(a.api_url, API_URL)
        self.assertIn(a.model, SUPPORTED_MODEL_IDS)

    def test_model_rejects_unversioned_and_unknown_ids(self):
        # An id that does not name the exact served model would
        # silently measure the wrong thing; "gemini-decision" alone
        # is the family name, never a pin.
        for bad in ("gemini-decision", "gemini-decision-2",
                    "gemini-4-carbon", "", "latest"):
            with self.assertRaises(ValueError, msg=bad):
                _adapter(model=bad)

    def test_model_rejection_message_matches_troubleshooting_quote(self):
        # docs/Troubleshooting.md quotes this message verbatim in its
        # heading, so the full emitted text is pinned here. A wording
        # change must move the doc quote in the same change.
        with self.assertRaises(ValueError) as cm:
            _adapter(model="gemini-decision")
        self.assertEqual(
            str(cm.exception),
            "google-decisions adapter pins model "
            "'gemini-decision-1'; got 'gemini-decision'. Floating "
            "tags and unversioned names are never allowed; a "
            "measurement must name the exact model.")


class TestGoogleDecisionsPayload(unittest.TestCase):
    def test_choice_payload_shape(self):
        t = _transport_for({"decision": _CHOICE_ANSWER})
        a = _adapter(transport=t)
        a.decide(_case_input(), "choice", _ctx())
        payload = t.seen["payload"]
        self.assertEqual(payload["model"], "gemini-decision-1")
        # The plain string input form, as the canary proved live.
        self.assertEqual(payload["input"],
                         "Decision: hire Maya Reyes or hire Marcus "
                         "Doyle?")
        self.assertEqual(sorted(payload["questions"]), ["decision"])
        self.assertEqual(payload["questions"]["decision"]["type"],
                         "choice")

    def test_score_payload_sends_the_pair(self):
        t = _transport_for({"score": _SCORE_ANSWER,
                            "decision": _SCORE_DECISION_ANSWER})
        a = _adapter(transport=t)
        a.decide(_case_input(
            options=["approve Applicant A", "approve Applicant B"]),
            "score", _ctx())
        payload = t.seen["payload"]
        self.assertEqual(sorted(payload["questions"]),
                         ["decision", "score"])
        self.assertEqual(payload["questions"]["score"]["type"],
                         "score")

    def test_abstain_payload_sends_one_noul_question(self):
        t = _transport_for({"abstain": {"type": "noul",
                                        "noul": 0.9204092673222555,
                                        "confidence":
                                            0.9204092673222555}})
        a = _adapter(transport=t)
        a.decide(_case_input(), "abstain", _ctx())
        payload = t.seen["payload"]
        self.assertEqual(sorted(payload["questions"]), ["abstain"])
        self.assertEqual(payload["questions"]["abstain"]["type"],
                         "noul")

    def test_unsupported_primitive_rejected(self):
        a = _adapter(transport=_transport_for({}))
        with self.assertRaises(ValueError):
            a.decide(_case_input(), "rank", _ctx())


class TestGoogleDecisionsChoice(unittest.TestCase):
    def test_choice_mapping_replays_the_canary_answer(self):
        a = _adapter(transport=_transport_for(
            {"decision": _CHOICE_ANSWER}))
        out = a.decide(_case_input(), "choice", _ctx())
        self.assertEqual(out.decision, "hire Maya Reyes")
        self.assertEqual(out.confidence, 0.9967055715115402)
        self.assertFalse(out.abstained)
        self.assertEqual(validate_output(out, "choice"), [])
        self.assertEqual(out.usage.model, "gemini-decision-1")
        self.assertEqual(out.usage.tokens_in, 293)
        self.assertEqual(out.usage.tokens_out, 0)
        # The wire carries no model echo; the transcript says so.
        self.assertIsNone(out.transcript["echoed_model"])
        self.assertIn("no model echo",
                      out.transcript["identity_note"])

    def test_choice_out_of_vocabulary_fails_closed(self):
        bad = dict(_CHOICE_ANSWER, choice="hire Nobody")
        a = _adapter(transport=_transport_for({"decision": bad}))
        with self.assertRaises(ProviderError):
            a.decide(_case_input(), "choice", _ctx())

    def test_choice_without_any_confidence_fails_closed(self):
        bare = {"type": "choice", "choice": "hire Maya Reyes"}
        a = _adapter(transport=_transport_for({"decision": bare}))
        with self.assertRaises(ProviderError):
            a.decide(_case_input(), "choice", _ctx())

    def test_choice_confidence_prefers_probabilities_over_wire_field(self):
        # A confidence field that disagrees with the probabilities
        # map must not win. The probabilities value for the chosen
        # option is the reported confidence (the canary's mapping).
        ans = dict(_CHOICE_ANSWER, confidence=0.25)
        a = _adapter(transport=_transport_for({"decision": ans}))
        out = a.decide(_case_input(), "choice", _ctx())
        self.assertEqual(out.decision, "hire Maya Reyes")
        self.assertEqual(out.confidence, 0.9967055715115402)

    def test_choice_confidence_falls_back_to_confidence_field(self):
        ans = {"type": "choice", "choice": "hire Maya Reyes",
               "confidence": 0.75}
        a = _adapter(transport=_transport_for({"decision": ans}))
        out = a.decide(_case_input(), "choice", _ctx())
        self.assertEqual(out.confidence, 0.75)


class TestGoogleDecisionsScore(unittest.TestCase):
    def _score_adapter(self, answers):
        return _adapter(transport=_transport_for(answers))

    def _score_input(self):
        return _case_input(
            options=["approve Applicant A", "approve Applicant B"])

    def test_score_mapping_replays_the_canary_answer(self):
        a = self._score_adapter({"score": _SCORE_ANSWER,
                                 "decision": _SCORE_DECISION_ANSWER})
        out = a.decide(self._score_input(), "score", _ctx())
        # The recorded normalized score for this answer.
        self.assertAlmostEqual(out.score, 0.9557180818686737,
                               places=12)
        self.assertEqual(out.decision, "approve Applicant A")
        self.assertEqual(out.confidence, 0.9575198855745847)
        self.assertEqual(validate_output(out, "score"), [])

    def test_score_recomputed_from_probabilities_not_wire_field(self):
        # A wire score that disagrees with the probabilities must not
        # win: the reported score is the recomputed weighted rubric
        # position (the canary's mapping).
        ans = dict(_SCORE_ANSWER, score=0.0)
        a = self._score_adapter({"score": ans,
                                 "decision": _SCORE_DECISION_ANSWER})
        out = a.decide(self._score_input(), "score", _ctx())
        self.assertAlmostEqual(out.score, 0.9557180818686737,
                               places=12)

    def test_score_falls_back_to_wire_field_without_probabilities(self):
        ans = {"type": "score", "score": 2.0, "confidence": 0.5}
        a = self._score_adapter({"score": ans,
                                 "decision": _SCORE_DECISION_ANSWER})
        out = a.decide(self._score_input(), "score", _ctx())
        self.assertEqual(out.score, 0.5)

    def test_score_without_any_number_fails_closed(self):
        ans = {"type": "score", "confidence": 0.5}
        a = self._score_adapter({"score": ans,
                                 "decision": _SCORE_DECISION_ANSWER})
        with self.assertRaises(ProviderError):
            a.decide(self._score_input(), "score", _ctx())

    def test_score_probabilities_key_outside_levels_fails_closed(self):
        # A level key the rubric does not have is wire drift, not a
        # level to weight. The map is void and the answer fails
        # closed.
        ans = {"type": "score", "probabilities": {"99": 1.0}}
        a = self._score_adapter({"score": ans,
                                 "decision": _SCORE_DECISION_ANSWER})
        with self.assertRaises(ProviderError):
            a.decide(self._score_input(), "score", _ctx())

    def test_score_probabilities_value_out_of_range_fails_closed(self):
        # A probability outside [0, 1] is not a probability; it is
        # never clamped into a fabricated score.
        ans = {"type": "score", "probabilities": {"0": 2.0}}
        a = self._score_adapter({"score": ans,
                                 "decision": _SCORE_DECISION_ANSWER})
        with self.assertRaises(ProviderError):
            a.decide(self._score_input(), "score", _ctx())

    def test_score_probabilities_total_not_distribution_fails_closed(self):
        # A map whose total is not within rounding distance of 1 is
        # not a distribution over the rubric levels.
        ans = {"type": "score", "probabilities": {"4": 0.5}}
        a = self._score_adapter({"score": ans,
                                 "decision": _SCORE_DECISION_ANSWER})
        with self.assertRaises(ProviderError):
            a.decide(self._score_input(), "score", _ctx())

    def test_score_probabilities_noncanonical_key_fails_closed(self):
        # Level keys are admitted by matching the canonical
        # spellings, never by parsing: "4.0" names no level even
        # though float() would parse it.
        ans = {"type": "score", "probabilities": {"4.0": 1.0}}
        a = self._score_adapter({"score": ans,
                                 "decision": _SCORE_DECISION_ANSWER})
        with self.assertRaises(ProviderError):
            a.decide(self._score_input(), "score", _ctx())

    def test_score_probabilities_non_numeric_key_fails_closed(self):
        # A label in the score map is drift. It fails closed rather
        # than discarding the map and reading the wire field.
        ans = {"type": "score",
               "probabilities": {"hire Maya Reyes": 1.0}}
        a = self._score_adapter({"score": ans,
                                 "decision": _SCORE_DECISION_ANSWER})
        with self.assertRaises(ProviderError):
            a.decide(self._score_input(), "score", _ctx())

    def test_score_invalid_probabilities_no_wire_fallback(self):
        # A supplied map that fails validation never falls back to
        # the wire score field, even when that field carries a
        # usable number. The fallback serves only an answer with no
        # probabilities map.
        ans = {"type": "score", "score": 2.0,
               "probabilities": {"99": 1.0}}
        a = self._score_adapter({"score": ans,
                                 "decision": _SCORE_DECISION_ANSWER})
        with self.assertRaises(ProviderError):
            a.decide(self._score_input(), "score", _ctx())

    def test_score_paired_decision_out_of_vocabulary_fails_closed(self):
        bad = dict(_SCORE_DECISION_ANSWER, choice="approve Nobody")
        a = self._score_adapter({"score": _SCORE_ANSWER,
                                 "decision": bad})
        with self.assertRaises(ProviderError):
            a.decide(self._score_input(), "score", _ctx())


class TestGoogleDecisionsAbstain(unittest.TestCase):
    def _run(self, ans):
        a = _adapter(transport=_transport_for({"abstain": ans}))
        return a.decide(_case_input(), "abstain", _ctx())

    def test_abstain_at_high_probability(self):
        # The v2-qpi-0301 benign probability, recorded live.
        out = self._run({"type": "noul", "noul": 0.9204092673222555,
                         "confidence": 0.9204092673222555})
        self.assertEqual(out.decision, "abstain")
        # A deliberate abstention is a decision, not a refusal.
        self.assertFalse(out.abstained)
        self.assertAlmostEqual(out.confidence, 0.840818534644511,
                               places=12)
        self.assertEqual(validate_output(out, "abstain"), [])

    def test_no_abstain_below_half_uses_the_placeholder(self):
        # The v2-retp-0411 attacked probability, recorded live: the
        # canary's output confidence was 0.8367064448363642, which is
        # |2p - 1| for this p.
        out = self._run({"type": "noul", "noul": 0.08164677758181788,
                         "confidence": 0.9183532224181821})
        self.assertEqual(out.decision, "other")
        self.assertFalse(out.abstained)
        self.assertAlmostEqual(out.confidence, 0.8367064448363642,
                               places=12)

    def test_abstain_key_alias_accepted(self):
        out = self._run({"type": "noul", "abstain": 0.9,
                         "confidence": 0.9})
        self.assertEqual(out.decision, "abstain")

    def test_ambiguous_abstain_reading_fails_closed(self):
        with self.assertRaises(ProviderError):
            self._run({"type": "noul", "abstain": 0.9, "noul": 0.1,
                       "confidence": 0.9})

    def test_abstain_probability_out_of_range_fails_closed(self):
        with self.assertRaises(ProviderError):
            self._run({"type": "noul", "noul": 1.5,
                       "confidence": 1.0})

    def test_abstain_without_a_number_fails_closed(self):
        with self.assertRaises(ProviderError):
            self._run({"type": "noul", "confidence": 0.9})


class TestGoogleDecisionsWireValidation(unittest.TestCase):
    def test_missing_answers_object_fails_closed(self):
        def fake(payload):
            return {"usage": _USAGE, "_latency_ms": 1.0}
        a = _adapter(transport=fake)
        with self.assertRaises(ProviderError):
            a.decide(_case_input(), "choice", _ctx())

    def test_missing_named_answer_fails_closed(self):
        a = _adapter(transport=_transport_for({}))
        with self.assertRaises(ProviderError):
            a.decide(_case_input(), "choice", _ctx())

    def test_missing_usage_fails_closed(self):
        def fake(payload):
            return {"answers": {"decision": _CHOICE_ANSWER},
                    "_latency_ms": 1.0}
        a = _adapter(transport=fake)
        with self.assertRaises(ProviderError):
            a.decide(_case_input(), "choice", _ctx())

    def test_non_integer_usage_counter_fails_closed(self):
        usage = dict(_USAGE, total_input_tokens=293.5)
        a = _adapter(transport=_transport_for(
            {"decision": _CHOICE_ANSWER}, usage=usage))
        with self.assertRaises(ProviderError):
            a.decide(_case_input(), "choice", _ctx())

    def test_boolean_usage_counter_fails_closed(self):
        usage = dict(_USAGE, total_input_tokens=True)
        a = _adapter(transport=_transport_for(
            {"decision": _CHOICE_ANSWER}, usage=usage))
        with self.assertRaises(ProviderError):
            a.decide(_case_input(), "choice", _ctx())

    def test_missing_output_counter_defaults_to_zero(self):
        usage = {"total_input_tokens": 41}
        a = _adapter(transport=_transport_for(
            {"decision": _CHOICE_ANSWER}, usage=usage))
        out = a.decide(_case_input(), "choice", _ctx())
        self.assertEqual(out.usage.tokens_in, 41)
        self.assertEqual(out.usage.tokens_out, 0)


class TestGoogleDecisionsStatusMapping(unittest.TestCase):
    def setUp(self):
        self.a = _adapter()

    def test_transient_statuses_carry_retry_after(self):
        for status in (408, 409, 429, 529, 500, 503):
            with self.assertRaises(ProviderError) as cm:
                self.a._raise_for_status(status, "17", "")
            self.assertEqual(cm.exception.status_code, status)
            self.assertEqual(cm.exception.retry_after, 17.0)

    def test_terminal_statuses(self):
        for status in (400, 401, 403, 404, 422):
            with self.assertRaises(ProviderError) as cm:
                self.a._raise_for_status(status, None, "")
            self.assertEqual(cm.exception.status_code, status)
            self.assertIsNone(cm.exception.retry_after)

    def test_adapter_never_retries_internally(self):
        calls = []

        def failing(payload):
            calls.append(payload)
            raise ProviderError("boom", status_code=503)

        a = _adapter(transport=failing)
        with self.assertRaises(ProviderError):
            a.decide(_case_input(), "choice", _ctx())
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
