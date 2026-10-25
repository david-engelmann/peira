"""Tests for the Inception Mercury Decide (Decisions API) adapter.

All transport is faked: no network, no credentials, no access needed.
The fake transport receives the exact payload the adapter would POST
and returns a canned parsed response body written against the wire
shape observed live on 2026-10-16: the body is NOT enveloped, the top
level carries ``answers`` keyed by question name, a ``model`` echo of
the id sent, and ``usage`` with integer counters; answers carry
``choice``/``score``/``noul`` fields plus a ``type`` echo, exactly as
on the System One wire.
"""

import unittest

from peira.adapters.base import ProviderError, validate_output
from peira.adapters import mercury_decide as mercury_mod
from peira.adapters.mercury_decide import (
    API_KEY_ENV,
    API_URL,
    MODEL_ID,
    SUPPORTED_MODEL_IDS,
    MercuryDecideAdapter,
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
    return MercuryDecideAdapter(**kw)


def _transport_for(answers, usage=None, latency=12.5, model=MODEL_ID):
    seen = {}

    def fake(payload):
        seen["payload"] = payload
        body = {"answers": answers,
                "usage": usage or {"input_tokens": 100,
                                   "output_tokens": 3},
                "_latency_ms": latency}
        if model is not None:
            body["model"] = model
        return body

    fake.seen = seen
    return fake


class TestMercuryConstruction(unittest.TestCase):
    def test_missing_api_key_is_actionable(self):
        import os
        old = os.environ.pop(API_KEY_ENV, None)
        try:
            with self.assertRaises(ValueError) as cm:
                MercuryDecideAdapter()
        finally:
            if old is not None:
                os.environ[API_KEY_ENV] = old
        self.assertIn(API_KEY_ENV, str(cm.exception))
        self.assertIn("Inception API key", str(cm.exception))

    def test_explicit_api_key_ok(self):
        a = _adapter()
        self.assertEqual(a._api_token, "tok-test")

    def test_default_model_is_mercury_decide(self):
        a = _adapter()
        self.assertEqual(a.model, "mercury-decide")
        self.assertEqual(MODEL_ID, "mercury-decide")

    def test_supported_models_construct(self):
        for model in SUPPORTED_MODEL_IDS:
            a = _adapter(model=model)
            self.assertEqual(a.model, model)
            self.assertEqual(a.version, model)
            self.assertEqual(a.cache_namespace, f"mercury-decide:{model}")
            # Literal, not the module constant: the endpoint itself
            # is the claim (Standards axis, 2026-10-16).
            self.assertEqual(a.api_url,
                             "https://api.inceptionlabs.ai/v1/decisions")

    def test_model_rejects_unversioned_and_unknown_ids(self):
        # An id that does not name the exact served weights would
        # silently measure the wrong thing. mercury-2 and
        # mercury-2.5 are real chat models on the account, but they
        # are not the decision model this adapter pins.
        for bad in ("mercury", "mercury-2", "mercury-2.5",
                    "mercury-decide-v1", "decide", "", "latest"):
            with self.assertRaises(ValueError, msg=bad):
                _adapter(model=bad)

    def test_model_rejection_message_matches_troubleshooting_quote(self):
        # docs/Troubleshooting.md quotes this message verbatim in its
        # heading, so the full emitted text is pinned here. A wording
        # change must move the doc quote in the same change.
        with self.assertRaises(ValueError) as cm:
            _adapter(model="mercury")
        self.assertEqual(
            str(cm.exception),
            "mercury-decide adapter pins model 'mercury-decide'; "
            "got 'mercury'. Floating tags and unversioned names "
            "are never allowed; a measurement must name the "
            "exact model.")

    def test_decide_sends_full_model_id_in_body(self):
        # The request body carries the pinned id itself
        # (probe-verified); there is no short body name.
        t = _transport_for({"decision": {"type": "choice",
                                         "choice": "deny",
                                         "confidence": 0.9}})
        out = _adapter(transport=t).decide(
            _case_input(), "choice", _ctx())
        self.assertEqual(t.seen["payload"]["model"], "mercury-decide")
        self.assertEqual(out.usage.model, "mercury-decide")
        self.assertEqual(out.transcript["model"], "mercury-decide")


class TestMercuryBuildersMirrorJev(unittest.TestCase):
    """The builders are the Jev adapter's, byte for byte.

    The adapter docstring and the CHANGELOG claim identical
    decision spaces across the wires. That claim is pinned here
    against the Jev module itself, so a future edit to either
    side's instrument text fails loudly instead of silently
    diverging (Standards axis judgement call, 2026-10-16).
    """

    def test_builders_byte_identical_to_jev(self):
        import json as _json

        from peira.adapters import jev as jev_mod

        labels = ["fix", "hold", "ask", "deny"]
        pairs = [
            (mercury_mod._choice_question(labels),
             jev_mod._choice_question(labels)),
            (mercury_mod._score_question(), jev_mod._score_question()),
            (mercury_mod._noul_question(), jev_mod._noul_question()),
        ]
        for mine, theirs in pairs:
            self.assertEqual(mine, theirs)
            self.assertEqual(_json.dumps(mine).encode(),
                             _json.dumps(theirs).encode())
        self.assertEqual(mercury_mod._SCORE_LEVELS,
                         jev_mod._SCORE_LEVELS)


class TestMercuryChoice(unittest.TestCase):
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
        self.assertEqual(out.usage.tokens_out, 3)

    def test_choice_confidence_field_wins_over_probability(self):
        # The API's confidence field is authoritative; the
        # probabilities value for the chosen option is the fallback.
        t = _transport_for({
            "decision": {"type": "choice", "choice": "approve",
                         "probabilities": {"approve": 0.99877,
                                           "deny": 0.00057,
                                           "other": 0.00066},
                         "confidence": 0.99816},
        })
        out = _adapter(transport=t).decide(_case_input(), "choice", _ctx())
        self.assertAlmostEqual(out.confidence, 0.99816)

    def test_choice_missing_confidence_everywhere_is_terminal(self):
        # No confidence field and no probabilities map: the value is
        # a measurement the model reports, never a midpoint the
        # adapter invents.
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
        self.assertEqual(payload["model"], "mercury-decide")
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


class TestMercuryScore(unittest.TestCase):
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

    def test_score_out_of_range_is_terminal(self):
        # The wire computes the score as a probability-weighted
        # average of the level indices, so a value far outside
        # [0, 4] is malformed wire data. Clamping it would fabricate
        # an extreme measurement (red team, 2026-10-16).
        for bad in (99, -5, 5):
            a, _ = self._score_adapter(bad)
            with self.assertRaises(ProviderError, msg=repr(bad)):
                a.decide(_case_input(), "score", _ctx())

    def test_score_direct_huge_int_is_terminal(self):
        # A several-hundred-digit JSON integer parses to an int
        # whose float() raises OverflowError. The direct path
        # compares before converting, so a huge int takes the
        # out-of-range path instead of escaping unclassified.
        for bad in (10**400, -(10**400)):
            a, _ = self._score_adapter(bad)
            with self.assertRaises(ProviderError, msg=repr(bad)):
                a.decide(_case_input(), "score", _ctx())

    def test_score_float_dust_at_the_band_edge_clamps(self):
        # Within the 0.01 tolerance band the value is float dust
        # from the weighted average and normalizes as before.
        a, _ = self._score_adapter(4.005)
        out = a.decide(_case_input(), "score", _ctx())
        self.assertEqual(out.score, 1.0)
        a, _ = self._score_adapter(-0.005)
        out = a.decide(_case_input(), "score", _ctx())
        self.assertEqual(out.score, 0.0)

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
        # The stated mass totals 0.1; the missing 0.9 is not the
        # adapter's to invent or silently ignore.
        t = self._score_with_probs({"4": 0.1})
        with self.assertRaises(ProviderError):
            _adapter(transport=t).decide(_case_input(), "score", _ctx())

    def test_score_fallback_string_value_is_terminal(self):
        # float("1.0") would coerce this into a maximal score.
        t = self._score_with_probs({"4": "1.0"})
        with self.assertRaises(ProviderError):
            _adapter(transport=t).decide(_case_input(), "score", _ctx())

    def test_score_fallback_noncanonical_keys_are_terminal(self):
        # Only the canonical decimal spelling names a level. Loose
        # spellings would let one level be counted twice under two
        # keys and fake a total of 1 (red team, 2026-10-16).
        for probs in ({"0": 0.5, "00": 0.5}, {" 1": 1.0}, {"+1": 1.0},
                      {4: 1.0}, {1.9: 1.0}, {True: 1.0}):
            t = self._score_with_probs(probs)
            with self.assertRaises(ProviderError, msg=repr(probs)):
                _adapter(transport=t).decide(_case_input(), "score",
                                              _ctx())

    def test_score_fallback_huge_int_probability_is_terminal(self):
        # An int probability is genuine only as 0 or 1. A several-
        # hundred-digit JSON integer parses to an int whose float()
        # raises OverflowError. The fallback must void it (and fail
        # closed) instead of letting the exception escape.
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
        # The live probe's score answer shape, legend included.
        t = _transport_for({
            "score": {"type": "score", "score": 3.9069,
                      "confidence": 0.9535,
                      "legend": {str(i): lvl for i, lvl in enumerate([
                          "clearly the wrong decision",
                          "probably the wrong decision",
                          "uncertain — could go either way",
                          "probably the right decision",
                          "clearly the right decision"])},
                      "probabilities": {"0": 0.0041, "1": 0.0032,
                                        "2": 0.0063, "3": 0.0543,
                                        "4": 0.9321}},
            "decision": {"type": "choice", "choice": "approve",
                         "confidence": 0.9982},
        })
        out = _adapter(transport=t).decide(_case_input(), "score", _ctx())
        self.assertEqual(validate_output(out, "score"), [])
        self.assertAlmostEqual(out.score, 3.9069 / 4)
        self.assertEqual(out.decision, "approve")


class TestMercuryNoul(unittest.TestCase):
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

    def test_bool_in_either_abstain_slot_is_terminal(self):
        # 1 == True in Python, so an equality-only ambiguity check
        # would accept {"abstain": 1, "noul": True} and read the
        # unchecked slot as a probability (red team, 2026-10-16).
        # Every carried value is type-checked before any comparison.
        for ans in ({"abstain": 1, "noul": True},
                    {"abstain": True, "noul": 1}):
            t = _transport_for({"abstain": dict(ans, type="noul")})
            with self.assertRaises(ProviderError, msg=repr(ans)):
                _adapter(transport=t).decide(_case_input(), "abstain",
                                              _ctx())


class TestMercuryResponseValidation(unittest.TestCase):
    def test_missing_answers_is_terminal(self):
        def fake(payload):
            return {"model": MODEL_ID,
                    "usage": {"input_tokens": 5, "output_tokens": 3},
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
                           model="mercury-2")
        with self.assertRaises(ProviderError) as cm:
            _adapter(transport=t).decide(_case_input(), "choice", _ctx())
        self.assertIn("mercury-2", str(cm.exception))
        self.assertIn("mercury-decide", str(cm.exception))

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
                    "model": MODEL_ID, "usage": [217, 3]}
        with self.assertRaises(ProviderError):
            _adapter(transport=fake).decide(_case_input(), "choice",
                                           _ctx())

    def test_missing_usage_counter_is_terminal(self):
        def fake(payload):
            return {"answers": {"decision": {"type": "choice",
                                             "choice": "deny",
                                             "confidence": 0.9}},
                    "model": MODEL_ID, "usage": {"input_tokens": 217}}
        with self.assertRaises(ProviderError):
            _adapter(transport=fake).decide(_case_input(), "choice",
                                           _ctx())


class TestMercuryQuestionValidation(unittest.TestCase):
    def test_malformed_question_is_terminal_before_send(self):
        with self.assertRaises(ProviderError):
            mercury_mod._validate_questions({"bad": {"type": "choice"}})
        with self.assertRaises(ProviderError):
            mercury_mod._validate_questions(
                {"bad": {"type": "bogus", "instructions": "x"}})
        mercury_mod._validate_questions({
            "d": {"type": "choice", "instructions": "i",
                  "criteria": {"a": "A"}},
            "s": {"type": "score", "instructions": "i",
                  "criteria": ["low", "high"]},
            "n": {"type": "noul", "instructions": "i"},
        })


class TestMercuryErrors(unittest.TestCase):
    def test_raise_for_status_mapping(self):
        a = _adapter()
        for status in (401, 402, 403, 404, 413, 400, 422, 429, 500,
                       502, 503, 504):
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
            "mercury-decide API error 401; check that "
            "INCEPTION_API_KEY is valid and active, and sent as a "
            "Bearer token.")

    def test_402_message_matches_troubleshooting_quote(self):
        a = _adapter()
        with self.assertRaises(ProviderError) as cm:
            a._raise_for_status(402, None, "")
        self.assertEqual(
            str(cm.exception),
            "mercury-decide API error 402; the account's billing is "
            "inactive or its quota is exhausted; check billing in "
            "the Inception console at "
            "platform.inceptionlabs.ai, then rerun.")

    def test_404_message_matches_troubleshooting_quote(self):
        a = _adapter()
        with self.assertRaises(ProviderError) as cm:
            a._raise_for_status(404, None, "")
        self.assertEqual(
            str(cm.exception),
            "mercury-decide API error 404; the pinned model was not "
            "found; the served model id may have changed; this is "
            "an adapter bug or an API change, not a retryable "
            "failure.")

    def test_413_message_matches_troubleshooting_quote(self):
        a = _adapter()
        with self.assertRaises(ProviderError) as cm:
            a._raise_for_status(413, None, "")
        self.assertEqual(
            str(cm.exception),
            "mercury-decide API error 413; the request exceeded "
            "the API's 20 MiB body limit; this is an adapter bug "
            "or an oversized case, not a retryable failure.")

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

    def test_error_detail_reads_api_error_message(self):
        # The Decisions API error body carries an ``error`` object;
        # the adapter surfaces its message as detail and never
        # branches on a type or code field.
        import io
        import json as _json
        import urllib.error
        body = _json.dumps({"error": {
            "message": "Model not found",
            "type": "model_not_found"}}).encode()
        err = urllib.error.HTTPError(
            API_URL, 404, "Not Found", {}, io.BytesIO(body))
        self.assertEqual(mercury_mod._read_error_detail(err),
                         "Model not found")

    def test_error_detail_falls_back_for_non_json_body(self):
        # A gateway error can return an HTML page; the raw prefix
        # is the detail.
        import io
        import urllib.error
        err = urllib.error.HTTPError(
            API_URL, 504, "Gateway Timeout", {},
            io.BytesIO(b"<html>gateway timeout</html>"))
        self.assertEqual(mercury_mod._read_error_detail(err),
                         "<html>gateway timeout</html>")

    def test_error_detail_survives_incomplete_read(self):
        # A connection dropped mid-body makes read() raise
        # IncompleteRead, an http.client.HTTPException, which is
        # not an OSError. The detail is best-effort, so it reads as
        # empty instead of escaping as an unclassified exception.
        import http.client
        import urllib.error

        class DroppedBody:
            def read(self, *args):
                raise http.client.IncompleteRead(b"partial body")

            def close(self):
                pass

        err = urllib.error.HTTPError(
            API_URL, 500, "Internal Server Error", {}, DroppedBody())
        self.assertEqual(mercury_mod._read_error_detail(err), "")


    def test_latency_ms_huge_int_reads_as_unknown(self):
        # Latency is run metadata, not a measurement input: a
        # several-hundred-digit int reported by an injected
        # transport reads as 0.0 (unknown) instead of escaping
        # decide() as an unclassified OverflowError.
        self.assertEqual(
            mercury_mod._latency_ms({"_latency_ms": 10**400}), 0.0)

    def test_http_error_message_includes_api_detail(self):
        import io
        import json as _json
        import urllib.error
        from unittest import mock
        body = _json.dumps({"error": {
            "message": "Model not found",
            "type": "model_not_found"}}).encode()
        err = urllib.error.HTTPError(
            API_URL, 404, "Not Found", {}, io.BytesIO(body))
        adapter = _adapter()
        with mock.patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(ProviderError) as cm:
                adapter._http_transport({"model": MODEL_ID})
        self.assertIn("Model not found", str(cm.exception))
        self.assertEqual(cm.exception.status_code, 404)

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

    def test_http_client_exception_maps_to_408(self):
        # http.client failures are neither URLError nor OSError: a
        # connection dropped mid-response (BadStatusLine out of
        # getresponse, IncompleteRead out of read) must still land
        # on the transient-retry path as a 408 ProviderError, per
        # the module's documented contract (CodeRabbit, 2026-10-22).
        import http.client
        from unittest import mock
        adapter = _adapter()
        with mock.patch(
                "urllib.request.urlopen",
                side_effect=http.client.BadStatusLine("dropped")):
            with self.assertRaises(ProviderError) as cm:
                adapter._http_transport({"model": MODEL_ID})
        self.assertEqual(cm.exception.status_code, 408)

        class _Resp:
            status = 200
            headers = {}

            def read(self):
                raise http.client.IncompleteRead(b"partial")

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        with mock.patch("urllib.request.urlopen", return_value=_Resp()):
            with self.assertRaises(ProviderError) as cm:
                adapter._http_transport({"model": MODEL_ID})
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

    def test_error_detail_never_carries_the_api_key(self):
        # A vendor or gateway error body can echo request material.
        # The key must be scrubbed before the detail rides an
        # exception into logs or artifacts (red team, 2026-10-16).
        import io
        import json as _json
        import urllib.error
        from unittest import mock
        body = _json.dumps({"error": {
            "message": "bad auth Bearer keymaterial-xyz",
            "type": "invalid_api_key"}}).encode()
        err = urllib.error.HTTPError(
            API_URL, 400, "Bad Request", {}, io.BytesIO(body))
        adapter = _adapter(api_key="keymaterial-xyz")
        with mock.patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(ProviderError) as cm:
                adapter._http_transport({"model": MODEL_ID})
        self.assertNotIn("keymaterial-xyz", str(cm.exception))
        self.assertIn("<redacted>", str(cm.exception))
        self.assertEqual(cm.exception.status_code, 400)

    def test_retry_after_nonfinite_is_dropped(self):
        # "inf" and "nan" parse as floats; neither is a usable
        # delay. Finite values pass through (the runner caps the
        # delay at MAX_RETRY_AFTER_S when it consumes the value).
        self.assertIsNone(mercury_mod._parse_retry_after("inf"))
        self.assertIsNone(mercury_mod._parse_retry_after("nan"))
        self.assertIsNone(mercury_mod._parse_retry_after("tomorrow"))
        self.assertEqual(mercury_mod._parse_retry_after("1e9"), 1e9)

    def test_junk_latency_from_injected_transport_reads_unknown(self):
        # Latency is run metadata, not a measurement input. An
        # injected transport reporting junk gets 0.0 rather than an
        # unclassified exception escaping decide().
        for junk in ("abc", float("nan"), -5, True):
            t = _transport_for({"decision": {"type": "choice",
                                             "choice": "deny",
                                             "confidence": 0.9}},
                               latency=junk)
            out = _adapter(transport=t).decide(_case_input(), "choice",
                                                _ctx())
            self.assertEqual(out.usage.latency_ms, 0.0, msg=repr(junk))

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


class TestMercuryMalformedValues(unittest.TestCase):
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
        t = _transport_for({"decision": {"type": "choice",
                                         "choice": "deny",
                                         "probabilities": [0.1, 0.9]}})
        with self.assertRaises(ProviderError):
            _adapter(transport=t).decide(_case_input(), "choice", _ctx())

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
        # four (and produced a negative cost for one of them).
        for bad in (True, 1.9, "12", -5, float("inf")):
            t = _transport_for(
                {"decision": {"type": "choice", "choice": "deny",
                              "confidence": 0.9}},
                usage={"input_tokens": bad, "output_tokens": 0})
            with self.assertRaises(ProviderError, msg=repr(bad)):
                _adapter(transport=t).decide(_case_input(), "choice",
                                              _ctx())

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



class TestMercuryClampStringGate(unittest.TestCase):
    def test_clamp_rejects_string_values(self):
        with self.assertRaises(ProviderError):
            mercury_mod._clamp01("0.9", "confidence")

if __name__ == "__main__":
    unittest.main()
