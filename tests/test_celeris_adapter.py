"""Tests for the Celeris celeris-1-decision (System One) adapter.

All transport is faked: no network, no credentials, no access needed.
The fake transport receives the exact payload the adapter would POST
and returns a canned parsed response body written against the wire
shape observed live on 2026-10-15: the body is NOT enveloped, the top
level carries ``answers`` keyed by question name, a ``model`` echo of
the id sent, and ``usage`` with integer counters; answers carry
``choice``/``score``/``noul`` fields plus a ``type`` echo, exactly as
on the System One wire.
"""

import unittest

from peira.adapters.base import ProviderError, validate_output
from peira.adapters import celeris as celeris_mod
from peira.adapters.celeris import (
    API_KEY_ENV,
    API_URL,
    MODEL_ID,
    SUPPORTED_MODEL_IDS,
    CelerisAdapter,
)


# B2 (D-25 amended): the adapter-visible context is an opaque per-call
# handle; no case id, no arm, no gold labels. The candidate decision
# labels come from the case input's explicit "options" list.
def _case_input(**over):
    d = {"prompt": "Decision: approve or deny?",
         "options": ["approve", "deny"]}
    d.update(over)
    return d


def _ctx(**over):
    from peira.adapters.base import CallContext
    return CallContext(call_id=over.get("call_id", "call-test"))


def _adapter(transport=None, **kw):
    kw.setdefault("api_key", "tok-test")
    if transport is not None:
        kw["transport"] = transport
    return CelerisAdapter(**kw)


def _transport_for(answers, usage=None, latency=12.5, model=MODEL_ID):
    seen = {}

    def fake(payload):
        seen["payload"] = payload
        body = {"answers": answers,
                "usage": usage or {"input_tokens": 100,
                                   "output_tokens": 0},
                "_latency_ms": latency}
        if model is not None:
            body["model"] = model
        return body

    fake.seen = seen
    return fake


class TestCelerisConstruction(unittest.TestCase):
    def test_missing_api_key_is_actionable(self):
        import os
        old = os.environ.pop(API_KEY_ENV, None)
        try:
            with self.assertRaises(ValueError) as cm:
                CelerisAdapter()
        finally:
            if old is not None:
                os.environ[API_KEY_ENV] = old
        self.assertIn(API_KEY_ENV, str(cm.exception))
        self.assertIn("Celeris API key", str(cm.exception))

    def test_explicit_api_key_ok(self):
        a = _adapter()
        self.assertEqual(a._api_token, "tok-test")

    def test_default_model_is_the_pin(self):
        a = _adapter()
        self.assertEqual(a.model, "celeris-1-decision")
        self.assertEqual(MODEL_ID, "celeris-1-decision")
        self.assertEqual(a.version, "celeris-1-decision")
        self.assertEqual(a.cache_namespace, "celeris:celeris-1-decision")
        self.assertEqual(a.api_url, API_URL)

    def test_all_supported_models_construct(self):
        for model in SUPPORTED_MODEL_IDS:
            a = _adapter(model=model)
            self.assertEqual(a.model, model)
            self.assertEqual(a.version, model)
            self.assertEqual(a.cache_namespace, f"celeris:{model}")
            self.assertEqual(a.api_url, API_URL)

    def test_model_rejects_unversioned_and_unknown_ids(self):
        # An id that does not name the exact served weights would
        # silently measure the wrong thing; "celeris" alone is the
        # vendor name, never a pin.
        for bad in ("celeris", "celeris-1", "celeris-2-decision",
                    "celeris-1-decision-v2", "", "latest"):
            with self.assertRaises(ValueError, msg=bad):
                _adapter(model=bad)

    def test_model_rejection_message_matches_troubleshooting_quote(self):
        # docs/Troubleshooting.md quotes this message verbatim in its
        # heading, so the full emitted text is pinned here. A wording
        # change must move the doc quote in the same change.
        with self.assertRaises(ValueError) as cm:
            _adapter(model="celeris")
        self.assertEqual(
            str(cm.exception),
            "celeris adapter pins model 'celeris-1-decision'; "
            "got 'celeris'. Floating tags and unversioned names "
            "are never allowed; a measurement must name the exact "
            "model.")

    def test_decide_sends_full_model_id_in_body(self):
        # The request body carries the pinned id itself, and the URL
        # names it too (probe-verified: the endpoint refuses any
        # other model with HTTP 422).
        t = _transport_for({"decision": {"type": "choice",
                                         "choice": "deny",
                                         "confidence": 0.9}})
        out = _adapter(transport=t).decide(
            _case_input(), "choice", _ctx())
        self.assertEqual(t.seen["payload"]["model"],
                         "celeris-1-decision")
        self.assertEqual(out.usage.model, "celeris-1-decision")
        self.assertEqual(out.transcript["model"], "celeris-1-decision")
        self.assertIn("celeris-1-decision", API_URL)


class TestCelerisChoice(unittest.TestCase):
    def test_choice_maps_option_and_confidence(self):
        t = _transport_for({
            "decision": {"type": "choice", "choice": "approve",
                         "probabilities": {"deny": 0.2, "approve": 0.7,
                                           "other": 0.1},
                         "confidence": 0.7},
        })
        out = _adapter(transport=t).decide(_case_input(), "choice", _ctx())
        self.assertEqual(validate_output(out, "choice"), [])
        self.assertEqual(out.decision, "approve")
        self.assertAlmostEqual(out.confidence, 0.7)
        self.assertEqual(out.usage.model, MODEL_ID)
        self.assertEqual(out.usage.tokens_in, 100)
        self.assertEqual(out.usage.tokens_out, 0)

    def test_choice_confidence_field_wins_over_probability(self):
        # The live wire's confidence is close to but NOT equal to
        # probabilities[choice] (probe: 0.94 vs 0.96). The adapter
        # reports the API's confidence field.
        t = _transport_for({
            "decision": {"type": "choice", "choice": "approve",
                         "probabilities": {"approve": 0.96,
                                           "deny": 0.02,
                                           "other": 0.02},
                         "confidence": 0.94},
        })
        out = _adapter(transport=t).decide(_case_input(), "choice", _ctx())
        self.assertAlmostEqual(out.confidence, 0.94)

    def test_choice_missing_confidence_everywhere_is_terminal(self):
        # No confidence field and no probabilities map: the value is
        # a measurement the model reports, never a midpoint the
        # adapter invents (pplx second red team, 2026-10-15).
        t = _transport_for({
            "decision": {"type": "choice", "choice": "approve"},
        })
        with self.assertRaises(ProviderError):
            _adapter(transport=t).decide(_case_input(), "choice", _ctx())

    def test_choice_string_confidence_is_terminal(self):
        t = _transport_for({
            "decision": {"type": "choice", "choice": "approve",
                         "confidence": "0.73"},
        })
        with self.assertRaises(ProviderError):
            _adapter(transport=t).decide(_case_input(), "choice", _ctx())

    def test_choice_confidence_above_one_is_terminal(self):
        t = _transport_for({
            "decision": {"type": "choice", "choice": "approve",
                         "confidence": 1.2},
        })
        with self.assertRaises(ProviderError):
            _adapter(transport=t).decide(_case_input(), "choice", _ctx())

    def test_choice_probability_fallback_value_is_validated(self):
        # The fallback reads probabilities[choice]; a value of -5
        # must not clamp into a measured 0.0.
        t = _transport_for({
            "decision": {"type": "choice", "choice": "approve",
                         "probabilities": {"approve": -5}},
        })
        with self.assertRaises(ProviderError):
            _adapter(transport=t).decide(_case_input(), "choice", _ctx())

    def test_score_missing_decision_confidence_is_terminal(self):
        t = _transport_for({
            "score": {"type": "score", "score": 3.0},
            "decision": {"type": "choice", "choice": "approve"},
        })
        with self.assertRaises(ProviderError):
            _adapter(transport=t).decide(_case_input(), "score", _ctx())

    def test_choice_request_shape(self):
        t = _transport_for({"decision": {"type": "choice",
                                         "choice": "deny",
                                         "confidence": 0.9}})
        _adapter(transport=t).decide(_case_input(), "choice", _ctx())
        payload = t.seen["payload"]
        self.assertEqual(payload["model"], "celeris-1-decision")
        self.assertEqual(payload["state"], "Decision: approve or deny?")
        q = payload["questions"]["decision"]
        self.assertEqual(set(q), {"type", "instructions", "criteria"})
        self.assertEqual(q["type"], "choice")
        self.assertTrue(q["instructions"])
        self.assertIn("deny", q["criteria"])
        self.assertIn("approve", q["criteria"])

    def test_choice_labels_come_from_input_options(self):
        t = _transport_for({"decision": {"type": "choice",
                                         "choice": "deny",
                                         "confidence": 0.9}})
        _adapter(transport=t).decide(
            _case_input(options=["deny", "approve", "hold"]),
            "choice", _ctx())
        labels = list(t.seen["payload"]["questions"]["decision"]["criteria"])
        self.assertEqual(labels, ["approve", "deny", "hold", "other"])

    def test_choice_unknown_option_is_terminal(self):
        t = _transport_for({"decision": {"type": "choice",
                                         "choice": "maybe",
                                         "confidence": 0.5}})
        with self.assertRaises(ProviderError):
            _adapter(transport=t).decide(_case_input(), "choice", _ctx())

    def test_unsupported_primitive(self):
        with self.assertRaises(ValueError):
            _adapter().decide(_case_input(), "bogus", _ctx())


    def test_choice_confidence_huge_int_is_terminal(self):
        # An int confidence is genuine only as 0 or 1. A several-
        # hundred-digit JSON integer parses to an int whose float()
        # raises OverflowError. It must fail closed here instead of
        # escaping as an unclassified error.
        t = _transport_for({
            "decision": {"type": "choice", "choice": "approve",
                         "confidence": 10**400},
        })
        with self.assertRaises(ProviderError):
            _adapter(transport=t).decide(_case_input(), "choice", _ctx())

class TestCelerisScore(unittest.TestCase):
    def _score_adapter(self, value, option="deny", conf=0.8):
        t = _transport_for({
            "score": {"type": "score", "score": value, "confidence": conf},
            "decision": {"type": "choice", "choice": option,
                         "confidence": conf},
        })
        return _adapter(transport=t), t

    def test_score_normalized_to_unit_interval(self):
        a, _ = self._score_adapter(3.2)
        out = a.decide(_case_input(), "score", _ctx())
        self.assertEqual(validate_output(out, "score"), [])
        self.assertAlmostEqual(out.score, 3.2 / 4)  # 5 levels, 0-based
        self.assertEqual(out.decision, "deny")

    def test_score_boundary_values_accepted(self):
        for raw, expected in ((0, 0.0), (4, 1.0), (0.0, 0.0), (4.0, 1.0)):
            a, _ = self._score_adapter(raw)
            out = a.decide(_case_input(), "score", _ctx())
            self.assertAlmostEqual(out.score, expected)

    def test_score_out_of_range_is_terminal(self):
        # The score is a position on the 0-based rubric. A value
        # outside it is malformed wire data; clamping it would
        # fabricate an extreme measurement.
        for bad in (99, 4.5, -1, -0.5):
            a, _ = self._score_adapter(bad)
            with self.assertRaises(ProviderError, msg=repr(bad)):
                a.decide(_case_input(), "score", _ctx())

    def test_score_direct_huge_int_is_terminal(self):
        # A several-hundred-digit JSON integer parses to an int
        # whose float() raises OverflowError. The direct score path
        # compares before converting, so a huge int takes the
        # out-of-range path instead of escaping as an unclassified
        # OverflowError.
        for bad in (10**400, -(10**400)):
            a, _ = self._score_adapter(bad)
            with self.assertRaises(ProviderError, msg=repr(bad)):
                a.decide(_case_input(), "score", _ctx())

    def test_score_missing_value_computed_from_probabilities(self):
        t = _transport_for({
            "score": {"type": "score",
                      "probabilities": {str(i): (1.0 if i == 4 else 0.0)
                                        for i in range(5)}},
            "decision": {"type": "choice", "choice": "approve",
                         "confidence": 0.9},
        })
        out = _adapter(transport=t).decide(_case_input(), "score", _ctx())
        self.assertAlmostEqual(out.score, 1.0)

    def test_score_bool_probability_is_terminal(self):
        # The score fallback must not let float(True) == 1.0 turn a
        # bool into a fabricated rubric position. Bools are rejected
        # everywhere else this adapter reads a probability.
        t = _transport_for({
            "score": {"type": "score",
                      "probabilities": {"0": 0.0, "1": 0.0, "2": True,
                                        "3": 0.0, "4": 0.0}},
            "decision": {"type": "choice", "choice": "approve",
                         "confidence": 0.9},
        })
        with self.assertRaises(ProviderError):
            _adapter(transport=t).decide(_case_input(), "score", _ctx())

    def test_score_non_numeric_probabilities_is_terminal(self):
        t = _transport_for({
            "score": {"type": "score",
                      "probabilities": {"0": "high", "1": 0.5}},
            "decision": {"type": "choice", "choice": "approve",
                         "confidence": 0.9},
        })
        with self.assertRaises(ProviderError):
            _adapter(transport=t).decide(_case_input(), "score", _ctx())

    def _score_with_probs(self, probs):
        return _transport_for({
            "score": {"type": "score", "probabilities": probs},
            "decision": {"type": "choice", "choice": "approve",
                         "confidence": 0.9},
        })

    def test_score_missing_value_non_dict_probabilities_is_terminal(self):
        # A missing score with a non-object probabilities value meets
        # the same clean ProviderError as any other unusable fallback
        # input, never an AttributeError from the parser (red-team
        # claim checked against this head, 2026-10-15: the clean
        # error is the shipped behavior, pinned here).
        for probs in ([0.1, 0.9], "str", 42, None):
            t = _transport_for({
                "score": {"type": "score", "probabilities": probs},
                "decision": {"type": "choice", "choice": "approve",
                             "confidence": 0.9},
            })
            with self.assertRaises(ProviderError, msg=repr(probs)):
                _adapter(transport=t).decide(_case_input(), "score",
                                              _ctx())

    def test_score_fallback_empty_probabilities_is_terminal(self):
        # An empty map is missing data, not a measured worst score:
        # sum() of nothing would read as 0.0.
        t = self._score_with_probs({})
        with self.assertRaises(ProviderError):
            _adapter(transport=t).decide(_case_input(), "score", _ctx())

    def test_score_fallback_out_of_range_level_is_terminal(self):
        t = self._score_with_probs({"99": 1.0})
        with self.assertRaises(ProviderError):
            _adapter(transport=t).decide(_case_input(), "score", _ctx())

    def test_score_fallback_value_above_one_is_terminal(self):
        t = self._score_with_probs({"4": 2.0})
        with self.assertRaises(ProviderError):
            _adapter(transport=t).decide(_case_input(), "score", _ctx())

    def test_score_fallback_partial_mass_is_terminal(self):
        # The stated mass totals 0.1. The missing 0.9 is not the
        # adapter's to invent or silently ignore.
        t = self._score_with_probs({"4": 0.1})
        with self.assertRaises(ProviderError):
            _adapter(transport=t).decide(_case_input(), "score", _ctx())

    def test_score_fallback_string_value_is_terminal(self):
        # float("1.0") would coerce this into a maximal score.
        t = self._score_with_probs({"4": "1.0"})
        with self.assertRaises(ProviderError):
            _adapter(transport=t).decide(_case_input(), "score", _ctx())

    def test_score_fallback_noncanonical_key_spellings_are_terminal(self):
        # A probability key is matched against the canonical level
        # spellings, never parsed into a level: int() accepts every
        # spelling below and would fabricate a rubric position.
        for probs in ({" 2": 1.0}, {"01": 1.0}, {"+1": 1.0}):
            t = self._score_with_probs(probs)
            with self.assertRaises(ProviderError, msg=repr(probs)):
                _adapter(transport=t).decide(_case_input(), "score",
                                              _ctx())

    def test_score_fallback_duplicate_level_spellings_are_terminal(self):
        # "1" and "01" name the same level under int() parsing and
        # their mass sums to 1.0, so parsing double-counted level 1
        # into a fabricated score instead of failing closed.
        t = self._score_with_probs({"1": 0.5, "01": 0.5})
        with self.assertRaises(ProviderError):
            _adapter(transport=t).decide(_case_input(), "score", _ctx())

    def test_score_fallback_huge_int_probability_is_terminal(self):
        # A several-hundred-digit JSON integer parses to a Python
        # int, and float() on it raises OverflowError. The fallback
        # must void it like any other out-of-range value instead of
        # letting the OverflowError escape in ProviderError's place.
        t = self._score_with_probs({"2": 10**400})
        with self.assertRaises(ProviderError):
            _adapter(transport=t).decide(_case_input(), "score", _ctx())

    def test_score_fallback_sparse_full_mass_accepted(self):
        # Levels carrying no probability may be omitted; the stated
        # mass still totals 1 and the weighted position is exact.
        t = self._score_with_probs({"0": 0.25, "4": 0.75})
        out = _adapter(transport=t).decide(_case_input(), "score",
                                           _ctx())
        self.assertAlmostEqual(out.score, 0.75)

    def test_score_sends_two_questions(self):
        a, t = self._score_adapter(3)
        a.decide(_case_input(), "score", _ctx())
        qs = t.seen["payload"]["questions"]
        self.assertEqual(set(qs), {"score", "decision"})
        sq = qs["score"]
        self.assertEqual(set(sq), {"type", "instructions", "criteria"})
        self.assertEqual(sq["type"], "score")
        self.assertEqual(len(sq["criteria"]), 5)
        self.assertTrue(all(isinstance(c, str) and c for c in sq["criteria"]))

    def test_score_full_live_shape(self):
        # The probe's actual score answer shape, legend included.
        t = _transport_for({
            "score": {"type": "score", "score": 3.82,
                      "confidence": 0.86,
                      "legend": {str(i): lvl for i, lvl in enumerate([
                          "clearly the wrong decision",
                          "probably the wrong decision",
                          "uncertain — could go either way",
                          "probably the right decision",
                          "clearly the right decision"])},
                      "probabilities": {"0": 0.01, "1": 0.01,
                                        "2": 0.02, "3": 0.07,
                                        "4": 0.89}},
            "decision": {"type": "choice", "choice": "approve",
                         "confidence": 0.94,
                         "probabilities": {"approve": 0.96,
                                            "deny": 0.02,
                                            "other": 0.02}},
        })
        out = _adapter(transport=t).decide(_case_input(), "score", _ctx())
        self.assertEqual(validate_output(out, "score"), [])
        self.assertAlmostEqual(out.score, 3.82 / 4)
        self.assertEqual(out.decision, "approve")


class TestCelerisNoul(unittest.TestCase):
    def test_noul_yes_means_abstain(self):
        t = _transport_for({"abstain": {"type": "noul", "noul": 0.8}})
        out = _adapter(transport=t).decide(_case_input(), "abstain", _ctx())
        self.assertEqual(validate_output(out, "abstain"), [])
        self.assertEqual(out.decision, "abstain")
        self.assertAlmostEqual(out.confidence, 0.6)  # |2*.8-1|

    def test_noul_no_returns_other_placeholder(self):
        t = _transport_for({"abstain": {"type": "noul", "noul": 0.2}})
        out = _adapter(transport=t).decide(_case_input(), "abstain", _ctx())
        self.assertEqual(out.decision, "other")
        self.assertFalse(out.abstained)
        self.assertAlmostEqual(out.confidence, 0.6)

    def test_noul_probe_value(self):
        # The probe's own reading: noul 0.03 on a clearly decidable
        # state is a confident non-abstention.
        t = _transport_for({"abstain": {"type": "noul", "noul": 0.03}})
        out = _adapter(transport=t).decide(_case_input(), "abstain", _ctx())
        self.assertEqual(out.decision, "other")
        self.assertAlmostEqual(out.confidence, 0.94)

    def test_noul_request_shape(self):
        t = _transport_for({"abstain": {"type": "noul", "noul": 0.1}})
        _adapter(transport=t).decide(_case_input(), "abstain", _ctx())
        q = t.seen["payload"]["questions"]["abstain"]
        self.assertEqual(q["type"], "noul")
        self.assertTrue(q["instructions"])
        self.assertNotIn("criteria", q)

    def test_agreeing_abstain_and_noul_keys_accepted(self):
        # The Jev-documented "abstain" key is an accepted alias for
        # the verified "noul" key when both carry the same value.
        t = _transport_for({"abstain": {"type": "noul", "abstain": 0.2,
                                        "noul": 0.2}})
        out = _adapter(transport=t).decide(_case_input(), "abstain", _ctx())
        self.assertEqual(out.decision, "other")
        self.assertFalse(out.abstained)

    def test_null_abstain_alias_falls_back_to_noul(self):
        # An explicit null under the alias key carries no value; the
        # verified noul reading stands.
        t = _transport_for({"abstain": {"type": "noul", "abstain": None,
                                        "noul": 0.9}})
        out = _adapter(transport=t).decide(_case_input(), "abstain",
                                           _ctx())
        self.assertEqual(out.decision, "abstain")

    def test_abstain_probability_out_of_range_is_terminal(self):
        # 1.7 is not a probability; clamping it would fabricate a
        # maximal measurement.
        t = _transport_for({"abstain": {"type": "noul", "noul": 1.7}})
        with self.assertRaises(ProviderError):
            _adapter(transport=t).decide(_case_input(), "abstain",
                                         _ctx())

    def test_disagreeing_abstain_keys_are_terminal(self):
        # If the API ever adds an "abstain" key that disagrees with
        # the verified "noul" value, no preference order can say which
        # is the probability. The adapter fails closed.
        t = _transport_for({"abstain": {"type": "noul", "abstain": 0.2,
                                        "noul": 0.9}})
        with self.assertRaises(ProviderError) as cm:
            _adapter(transport=t).decide(_case_input(), "abstain", _ctx())
        self.assertIn("ambiguous", str(cm.exception))

    def test_missing_both_keys_still_terminal(self):
        t = _transport_for({"abstain": {"type": "noul"}})
        with self.assertRaises(ProviderError):
            _adapter(transport=t).decide(_case_input(), "abstain", _ctx())


    def test_abstain_probability_huge_int_is_terminal(self):
        # A several-hundred-digit JSON integer parses to an int
        # whose float() raises OverflowError. The range check
        # compares before converting, so a huge int takes the
        # out-of-range path instead of escaping unclassified.
        t = _transport_for({"abstain": {"type": "noul",
                                        "noul": 10**400}})
        with self.assertRaises(ProviderError):
            _adapter(transport=t).decide(_case_input(), "abstain",
                                         _ctx())

class TestCelerisResponseValidation(unittest.TestCase):
    def test_missing_answers_is_terminal(self):
        def fake(payload):
            return {"model": MODEL_ID,
                    "usage": {"input_tokens": 5, "output_tokens": 0},
                    "_latency_ms": 1.0}
        with self.assertRaises(ProviderError) as cm:
            _adapter(transport=fake).decide(_case_input(), "choice", _ctx())
        self.assertIn("'answers'", str(cm.exception))

    def test_model_echo_mismatch_is_terminal(self):
        # The response names the weights that actually ran; a
        # different echo means this pin did not produce the answers.
        t = _transport_for({"decision": {"type": "choice",
                                         "choice": "deny",
                                         "confidence": 0.9}},
                           model="celeris-2-decision")
        with self.assertRaises(ProviderError) as cm:
            _adapter(transport=t).decide(_case_input(), "choice", _ctx())
        self.assertIn("celeris-2-decision", str(cm.exception))
        self.assertIn("celeris-1-decision", str(cm.exception))

    def test_model_echo_missing_is_terminal(self):
        t = _transport_for({"decision": {"type": "choice",
                                         "choice": "deny",
                                         "confidence": 0.9}},
                           model=None)
        with self.assertRaises(ProviderError):
            _adapter(transport=t).decide(_case_input(), "choice", _ctx())

    def test_missing_usage_is_terminal(self):
        # Cost accounting fails closed: a response without usage
        # counters cannot be priced, and recording it as a free call
        # would silently understate the run's spend.
        def fake(payload):
            return {"answers": {"decision": {"type": "choice",
                                             "choice": "deny",
                                             "confidence": 0.9}},
                    "model": MODEL_ID, "_latency_ms": 3.0}
        with self.assertRaises(ProviderError):
            _adapter(transport=fake).decide(_case_input(), "choice",
                                           _ctx())

    def test_non_dict_usage_is_terminal(self):
        def fake(payload):
            return {"answers": {"decision": {"type": "choice",
                                             "choice": "deny",
                                             "confidence": 0.9}},
                    "model": MODEL_ID, "usage": [300, 0]}
        with self.assertRaises(ProviderError):
            _adapter(transport=fake).decide(_case_input(), "choice",
                                           _ctx())

    def test_missing_usage_counter_is_terminal(self):
        def fake(payload):
            return {"answers": {"decision": {"type": "choice",
                                             "choice": "deny",
                                             "confidence": 0.9}},
                    "model": MODEL_ID, "usage": {"input_tokens": 300}}
        with self.assertRaises(ProviderError):
            _adapter(transport=fake).decide(_case_input(), "choice",
                                           _ctx())

    def test_x_celeris_extension_never_enters_a_metric(self):
        # Vendor material describes per-answer reasons in an
        # x_celeris extension object. If one ever arrives, the
        # standard fields alone decide the measurement; reason text
        # is not a number and must not move any output value.
        def fake(payload):
            return {
                "answers": {
                    "decision": {
                        "type": "choice", "choice": "deny",
                        "confidence": 0.9,
                        "probabilities": {"approve": 0.05,
                                          "deny": 0.9, "other": 0.05},
                        "x_celeris": {"reason": "approve, surely"},
                    },
                },
                "model": MODEL_ID,
                "usage": {"input_tokens": 169, "output_tokens": 0},
                "x_celeris": {"reason": "approve with confidence 0.01"},
                "_latency_ms": 3.0,
            }
        out = _adapter(transport=fake).decide(_case_input(), "choice",
                                              _ctx())
        self.assertEqual(out.decision, "deny")
        self.assertAlmostEqual(out.confidence, 0.9)


class TestCelerisQuestionValidation(unittest.TestCase):
    def test_malformed_question_is_terminal_before_send(self):
        with self.assertRaises(ProviderError):
            celeris_mod._validate_questions({"bad": {"type": "choice"}})
        with self.assertRaises(ProviderError):
            celeris_mod._validate_questions(
                {"bad": {"type": "bogus", "instructions": "x"}})
        celeris_mod._validate_questions({
            "d": {"type": "choice", "instructions": "i",
                  "criteria": {"a": "A"}},
            "s": {"type": "score", "instructions": "i",
                  "criteria": ["low", "high"]},
            "n": {"type": "noul", "instructions": "i"},
        })


class TestCelerisErrors(unittest.TestCase):
    def test_raise_for_status_mapping(self):
        a = _adapter()
        for status in (401, 403, 404, 400, 422, 429, 529, 500, 503):
            with self.assertRaises(ProviderError) as cm:
                a._raise_for_status(status, None, "detail")
            self.assertEqual(cm.exception.status_code, status)

    def test_401_message_matches_troubleshooting_quote(self):
        # docs/Troubleshooting.md quotes this message verbatim in its
        # heading, so the full emitted text is pinned here.
        a = _adapter()
        with self.assertRaises(ProviderError) as cm:
            a._raise_for_status(401, None, "")
        self.assertEqual(
            str(cm.exception),
            "celeris API error 401; check that "
            "CELERIS_API_KEY is valid and active, and sent as a "
            "Bearer token.")

    def test_422_message_matches_troubleshooting_quote(self):
        a = _adapter()
        with self.assertRaises(ProviderError) as cm:
            a._raise_for_status(422, None, "")
        self.assertEqual(
            str(cm.exception),
            "celeris API error 422; the request was rejected; "
            "this is an adapter bug, not a retryable failure.")

    def test_429_carries_retry_after(self):
        a = _adapter()
        with self.assertRaises(ProviderError) as cm:
            a._raise_for_status(429, "5", "")
        self.assertEqual(cm.exception.retry_after, 5.0)

    def test_409_carries_retry_after(self):
        # 409 is in the runner's transient set, so the server's
        # Retry-After must reach the runner like any other
        # transient's. Dropping it loses the server's stated wait.
        a = _adapter()
        with self.assertRaises(ProviderError) as cm:
            a._raise_for_status(409, "3", "")
        self.assertEqual(cm.exception.status_code, 409)
        self.assertEqual(cm.exception.retry_after, 3.0)

    def test_error_detail_reads_fastapi_messages(self):
        # The Celeris error body is FastAPI-shaped: a detail list of
        # loc/msg/type objects (probe-verified on 2026-10-15 with an
        # unknown model). The adapter surfaces the msg text as
        # detail and never branches on it.
        import io
        import json as _json
        import urllib.error
        body = _json.dumps({"detail": [{
            "loc": ["body", "model"],
            "msg": "this endpoint serves celeris-1-decision",
            "type": "value_error"}]}).encode()
        err = urllib.error.HTTPError(
            API_URL, 422, "Unprocessable Entity", {}, io.BytesIO(body))
        self.assertEqual(celeris_mod._read_error_detail(err),
                         "this endpoint serves celeris-1-decision")

    def test_error_detail_joins_multiple_fastapi_messages(self):
        import io
        import json as _json
        import urllib.error
        body = _json.dumps({"detail": [
            {"loc": ["body", "model"], "msg": "field required",
             "type": "missing"},
            {"loc": ["body", "state"], "msg": "field required",
             "type": "missing"}]}).encode()
        err = urllib.error.HTTPError(
            API_URL, 422, "Unprocessable Entity", {}, io.BytesIO(body))
        self.assertEqual(celeris_mod._read_error_detail(err),
                         "field required; field required")

    def test_error_detail_reads_string_detail(self):
        import io
        import json as _json
        import urllib.error
        body = _json.dumps({"detail": "Not Found"}).encode()
        err = urllib.error.HTTPError(
            API_URL, 404, "Not Found", {}, io.BytesIO(body))
        self.assertEqual(celeris_mod._read_error_detail(err),
                         "Not Found")

    def test_error_detail_falls_back_for_non_json_body(self):
        # A proxy or gateway error can return an HTML page; the raw
        # prefix is the detail.
        import io
        import urllib.error
        err = urllib.error.HTTPError(
            API_URL, 504, "Gateway Timeout", {},
            io.BytesIO(b"<html>gateway timeout</html>"))
        self.assertEqual(celeris_mod._read_error_detail(err),
                         "<html>gateway timeout</html>")

    def test_http_error_message_includes_api_detail(self):
        import io
        import json as _json
        import urllib.error
        from unittest import mock
        body = _json.dumps({"detail": [{
            "loc": ["body", "model"],
            "msg": "this endpoint serves celeris-1-decision",
            "type": "value_error"}]}).encode()
        err = urllib.error.HTTPError(
            API_URL, 422, "Unprocessable Entity", {}, io.BytesIO(body))
        adapter = _adapter()
        with mock.patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(ProviderError) as cm:
                adapter._http_transport({"model": MODEL_ID})
        self.assertIn("this endpoint serves celeris-1-decision",
                      str(cm.exception))
        self.assertEqual(cm.exception.status_code, 422)

    def test_http_error_without_headers_still_maps_status(self):
        # urllib can construct an HTTPError with headers=None; the
        # transport path must not die with AttributeError before it
        # can classify the status.
        import io
        import urllib.error
        from unittest import mock
        err = urllib.error.HTTPError(
            API_URL, 503, "Service Unavailable", None,
            io.BytesIO(b"upstream down"))
        adapter = _adapter()
        with mock.patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(ProviderError) as cm:
                adapter._http_transport({"model": MODEL_ID})
        self.assertEqual(cm.exception.status_code, 503)

    def test_transport_timeout_maps_to_408(self):
        import urllib.error
        from unittest import mock
        adapter = _adapter()
        with mock.patch("urllib.request.urlopen",
                        side_effect=urllib.error.URLError("timed out")):
            with self.assertRaises(ProviderError) as cm:
                adapter._http_transport({"model": MODEL_ID})
        # 408 is on the runner's transient-retry path (classify_exception).
        self.assertEqual(cm.exception.status_code, 408)

    def test_invalid_utf8_body_maps_to_non_json_provider_error(self):
        # A 200 body with invalid UTF-8 bytes is not valid JSON; the
        # transport decode must route it to the non-JSON ProviderError,
        # not let a UnicodeDecodeError escape unclassified.
        from unittest import mock

        class _Resp:
            status = 200
            headers = {}

            def read(self):
                return b"\xff\xfe not json"

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        adapter = _adapter()
        with mock.patch("urllib.request.urlopen", return_value=_Resp()):
            with self.assertRaises(ProviderError) as cm:
                adapter._http_transport({"model": MODEL_ID})
        self.assertIn("non-JSON", str(cm.exception))

    def test_non_dict_transport_body_is_terminal(self):
        # An injected transport returning a non-object body must meet
        # the same ProviderError as the real transport's non-object
        # guard, not an AttributeError from the parser.
        def fake(payload):
            return ["not", "an", "object"]
        with self.assertRaises(ProviderError):
            _adapter(transport=fake).decide(_case_input(), "choice",
                                            _ctx())

    def test_transcript_has_no_key_material(self):
        import json
        t = _transport_for({"decision": {"type": "choice",
                                         "choice": "deny",
                                         "confidence": 0.9}})
        adapter = _adapter(transport=t, api_key="keymaterial-xyz")
        out = adapter.decide(_case_input(), "choice", _ctx())
        blob = json.dumps(out.transcript)
        self.assertNotIn("keymaterial-xyz", blob)
        self.assertNotIn("keymaterial-xyz", json.dumps(t.seen["payload"]))

    def test_unknown_keys_ignored(self):
        t = _transport_for({"decision": {"type": "choice",
                                         "choice": "deny",
                                         "confidence": 0.9}})
        out = _adapter(transport=t).decide(_case_input(weird_key="x"),
                                           "choice", _ctx())
        self.assertEqual(out.decision, "deny")


class TestCelerisMalformedValues(unittest.TestCase):
    """Fail-closed behaviour for non-finite and mistyped wire values.

    Python's json accepts NaN/Infinity literals, so a malformed live
    response can carry them. Clamping NaN would silently fabricate a
    maximal measurement (min/max comparisons with NaN are false), so
    every numeric path must raise ProviderError instead.
    """

    def test_nan_confidence_is_terminal(self):
        t = _transport_for({"decision": {"type": "choice",
                                         "choice": "deny",
                                         "confidence": float("nan")}})
        with self.assertRaises(ProviderError):
            _adapter(transport=t).decide(_case_input(), "choice", _ctx())

    def test_inf_score_is_terminal(self):
        t = _transport_for({
            "score": {"type": "score", "score": float("inf")},
            "decision": {"type": "choice", "choice": "deny",
                         "confidence": 0.8},
        })
        with self.assertRaises(ProviderError):
            _adapter(transport=t).decide(_case_input(), "score", _ctx())

    def test_nan_abstain_is_terminal(self):
        t = _transport_for({"abstain": {"type": "noul",
                                        "noul": float("nan")}})
        with self.assertRaises(ProviderError):
            _adapter(transport=t).decide(_case_input(), "abstain", _ctx())

    def test_bool_confidence_is_terminal(self):
        # A bool is never a legitimate confidence (base._unit_interval
        # states the same rule); score and abstain values already
        # reject bools explicitly, confidence must not slip through
        # float(True) == 1.0.
        t = _transport_for({"decision": {"type": "choice",
                                         "choice": "deny",
                                         "confidence": True}})
        with self.assertRaises(ProviderError):
            _adapter(transport=t).decide(_case_input(), "choice", _ctx())

    def test_non_dict_probabilities_is_terminal(self):
        # The fake carries a valid confidence, so the ONLY branch
        # that can raise is the probabilities type check itself: a
        # regression that dropped the check would let this call
        # succeed on the confidence field (red team, 2026-10-15: the
        # earlier version of this test could not distinguish the two
        # ProviderError branches).
        t = _transport_for({"decision": {"type": "choice",
                                         "choice": "deny",
                                         "confidence": 0.9,
                                         "probabilities": [0.1, 0.9]}})
        with self.assertRaises(ProviderError) as cm:
            _adapter(transport=t).decide(_case_input(), "choice", _ctx())
        self.assertIn("probabilities that are not an object",
                      str(cm.exception))

    def test_malformed_usage_counters_are_terminal(self):
        t = _transport_for(
            {"decision": {"type": "choice", "choice": "deny",
                          "confidence": 0.9}},
            usage={"input_tokens": "abc", "output_tokens": 0})
        with self.assertRaises(ProviderError):
            _adapter(transport=t).decide(_case_input(), "choice", _ctx())

    def test_coerced_usage_counters_are_terminal(self):
        # Counters are never coerced: a bool, a float, a numeric
        # string, a negative or an infinity is malformed wire data,
        # not a number to repair. int() would have accepted the first
        # four (and produced a negative cost for one of them). Both
        # counters are exercised: a gap on one side is a negative or
        # fabricated cost the budget guard cannot see (red team,
        # 2026-10-15).
        for bad in (True, 1.9, "12", -5, float("inf")):
            for field in ("input_tokens", "output_tokens"):
                usage = {"input_tokens": 10, "output_tokens": 0}
                usage[field] = bad
                t = _transport_for(
                    {"decision": {"type": "choice", "choice": "deny",
                                  "confidence": 0.9}},
                    usage=usage)
                with self.assertRaises(ProviderError,
                                       msg=f"{field}={bad!r}"):
                    _adapter(transport=t).decide(_case_input(),
                                                  "choice", _ctx())

    def test_score_fallback_uses_level_keys_not_insertion_order(self):
        # The probability map's keys are the level indices. A map
        # delivered out of order must still weight level 4, not
        # whichever entry happens to iterate first.
        t = _transport_for({
            "score": {"type": "score",
                      "probabilities": {"4": 1.0, "0": 0.0, "1": 0.0,
                                        "2": 0.0, "3": 0.0}},
            "decision": {"type": "choice", "choice": "approve",
                         "confidence": 0.9},
        })
        out = _adapter(transport=t).decide(_case_input(), "score", _ctx())
        self.assertAlmostEqual(out.score, 1.0)

    def test_noul_exactly_half_abstains(self):
        # Boundary: p >= 0.5 is an abstention. Per base.py's contract
        # a deliberate abstain decision is decision="abstain" with
        # abstained=False (abstained=True means no usable decision was
        # produced at all); the Jev adapter returns exactly this.
        t = _transport_for({"abstain": {"type": "noul", "noul": 0.5}})
        out = _adapter(transport=t).decide(_case_input(), "abstain", _ctx())
        self.assertEqual(out.decision, "abstain")
        self.assertFalse(out.abstained)
        self.assertAlmostEqual(out.confidence, 0.0)

    def test_408_carries_retry_after(self):
        a = _adapter()
        with self.assertRaises(ProviderError) as cm:
            a._raise_for_status(408, "7", "")
        self.assertEqual(cm.exception.status_code, 408)
        self.assertEqual(cm.exception.retry_after, 7.0)



class TestRetryAfterNonfinite(unittest.TestCase):
    def test_retry_after_nonfinite_is_dropped(self):
        # "inf" and "nan" parse as floats; neither is a usable
        # delay. Finite values pass through (the runner caps the
        # delay at MAX_RETRY_AFTER_S when it consumes the value).
        self.assertIsNone(celeris_mod._parse_retry_after("inf"))
        self.assertIsNone(celeris_mod._parse_retry_after("nan"))
        self.assertIsNone(celeris_mod._parse_retry_after("1e400"))
        self.assertEqual(celeris_mod._parse_retry_after("7"), 7.0)


class TestCelerisClampStringGate(unittest.TestCase):
    def test_clamp_rejects_string_values(self):
        # Only genuine numbers reach the clamp conversion: a string
        # the wire sent is drift, never something to coerce into a
        # measurement.
        with self.assertRaises(ProviderError):
            celeris_mod._clamp01("0.9", "confidence")

if __name__ == "__main__":
    unittest.main()
