"""Tests for the Cerno adapter.

No network, no Cerno server: the transport is faked like in
test_strands_decider_adapter.py. Under test: the pinned 4B
checkpoint id, the configurable endpoint, the inherited
Jev-compatible wire behavior, the response stamp check, and the
fail-closed answer validation (the inherited parser clamps and
defaults malformed numbers; for this pinned local deployment a
malformed probability is server drift and must be terminal).
Also under test: the vendor's published answer format, which
omits the confidence field the vendored format code emits, must
be accepted, because the field duplicates the chosen option's
probability and requiring it would measure nothing extra.
"""

import unittest
import urllib.error
from unittest import mock

from peira.adapters.base import CallContext, ProviderError, validate_output
from peira.adapters import cerno as cerno_mod
from peira.adapters.cerno import (
    EXPECTED_MODEL_STAMP,
    EXPECTED_MODEL_STAMP_9B,
    EXPECTED_MODEL_STAMP_27B,
    MODEL_ID,
    MODEL_ID_9B,
    MODEL_ID_27B,
    PINNED_REVISION,
    PINNED_REVISION_9B,
    PINNED_REVISION_27B,
    CernoAdapter,
    Cerno9BAdapter,
    Cerno27BAdapter,
)
from peira.adapters.jev import JevAdapter
from peira.adapters.kev import LocalSystemOneAdapter

# B2 (D-25 amended): the adapter-visible context is an opaque per-call
# handle — no case id, no arm, no gold labels. The candidate decision
# labels come from the case input's explicit "options" list.
def _case_input(**over):
    d = {"prompt": "Decision: approve or deny?",
         "options": ["approve", "deny"]}
    d.update(over)
    return d


def _ctx(**over):
    return CallContext(call_id=over.get("call_id", "call-test"))


# The sidecar stamps every response with the checkpoint basename
# and Hub revision it loaded, not the full Hub id.
_STAMP = "cerno-4b"
_REVISION = "ed4b5c59b542ee96c227ee874776c973980c640b"


def _transport_for(answers, latency=12.5, model=_STAMP,
                   revision=_REVISION):
    seen = {}

    def fake(payload):
        seen["payload"] = payload
        response = {"answers": answers, "_latency_ms": latency}
        if model is not None:
            response["model"] = model
        if revision is not None:
            response["revision"] = revision
        return response

    fake.seen = seen
    return fake


def _choice_answer(**over):
    a = {
        "type": "choice",
        "choice": "deny",
        "confidence": 0.9,
        "certainty": 0.8,
        "probabilities": {"approve": 0.1, "deny": 0.9},
    }
    a.update(over)
    return a


class TestCernoConstruction(unittest.TestCase):
    def test_model_pinned(self):
        self.assertEqual(MODEL_ID, "apertixai/cerno-4b")
        self.assertEqual(EXPECTED_MODEL_STAMP, "cerno-4b")
        self.assertEqual(
            PINNED_REVISION,
            "ed4b5c59b542ee96c227ee874776c973980c640b")
        a = CernoAdapter()
        self.assertEqual(a.model, MODEL_ID)
        self.assertEqual(a.version, MODEL_ID)
        self.assertEqual(a.cache_namespace, f"cerno:{MODEL_ID}")

    def test_other_models_rejected(self):
        for bad in ("apertixai/cerno-27b", "apertixai/cerno-9b",
                    "cerno-4b", "", "apertixai/cerno-4b-v1",
                    "Qwen/Qwen3.5-4B"):
            with self.assertRaises(ValueError, msg=bad):
                CernoAdapter(model=bad)
        self.assertEqual(CernoAdapter(model=MODEL_ID).model, MODEL_ID)

    def test_pin_error_names_the_pin(self):
        with self.assertRaises(ValueError) as cm:
            CernoAdapter(model="apertixai/cerno-27b")
        self.assertIn("cerno adapter pins model", str(cm.exception))

    def test_default_api_url(self):
        a = CernoAdapter()
        self.assertEqual(a.api_url, "http://127.0.0.1:8017/v1/systemone")

    def test_custom_api_url(self):
        a = CernoAdapter(api_url="http://gpu:8100/v1/systemone")
        self.assertEqual(a.api_url, "http://gpu:8100/v1/systemone")

    def test_default_timeout_covers_cpu_serving(self):
        # A CPU forward pass over a long case state takes far
        # longer than the hosted adapters' timeouts; the default
        # must not cut a slow-but-valid call.
        self.assertEqual(CernoAdapter().timeout_s, 1200.0)

    def test_reuses_local_wire_plumbing(self):
        a = CernoAdapter()
        self.assertIsInstance(a, JevAdapter)
        self.assertIsInstance(a, LocalSystemOneAdapter)
        self.assertEqual(CernoAdapter.name, "cerno")
        self.assertEqual(CernoAdapter.supported_primitives,
                         frozenset({"choice", "score", "abstain"}))


class TestCernoWire(unittest.TestCase):
    def test_choice_happy_path(self):
        t = _transport_for({"decision": _choice_answer()})
        out = CernoAdapter(transport=t).decide(
            _case_input(), "choice", _ctx())
        self.assertEqual(validate_output(out, "choice"), [])
        self.assertEqual(out.decision, "deny")
        self.assertAlmostEqual(out.confidence, 0.9)
        self.assertEqual(out.usage.model, MODEL_ID)

    def test_choice_without_confidence_uses_the_probability(self):
        # The vendor's published answer format omits confidence
        # (it duplicates the chosen option's probability). The
        # call must still measure, with the probability as the
        # confidence.
        a = _choice_answer()
        del a["confidence"]
        del a["certainty"]
        t = _transport_for({"decision": a})
        out = CernoAdapter(transport=t).decide(
            _case_input(), "choice", _ctx())
        self.assertEqual(validate_output(out, "choice"), [])
        self.assertEqual(out.decision, "deny")
        self.assertAlmostEqual(out.confidence, 0.9)

    def test_malformed_present_confidence_is_terminal(self):
        t = _transport_for({"decision": _choice_answer(confidence="high")})
        with self.assertRaises(ProviderError):
            CernoAdapter(transport=t).decide(
                _case_input(), "choice", _ctx())

    def test_decision_answer_without_probabilities_map_is_terminal(self):
        # Without the map there is no measured probability to
        # report; the inherited parser would fabricate 0.5.
        a = _choice_answer()
        del a["probabilities"]
        t = _transport_for({"decision": a})
        with self.assertRaises(ProviderError):
            CernoAdapter(transport=t).decide(
                _case_input(), "choice", _ctx())

    def test_non_dict_probabilities_is_terminal(self):
        t = _transport_for({
            "decision": _choice_answer(probabilities=[0.1, 0.9]),
        })
        with self.assertRaises(ProviderError):
            CernoAdapter(transport=t).decide(
                _case_input(), "choice", _ctx())

    def test_non_numeric_probability_is_terminal(self):
        t = _transport_for({
            "decision": _choice_answer(
                probabilities={"approve": 0.1, "deny": "high"}),
        })
        with self.assertRaises(ProviderError):
            CernoAdapter(transport=t).decide(
                _case_input(), "choice", _ctx())

    def test_out_of_range_probability_is_terminal(self):
        # The inherited parser would clamp 1.5 to 1.0 and record
        # a number the model never produced.
        t = _transport_for({
            "decision": _choice_answer(
                probabilities={"approve": -0.5, "deny": 1.5}),
        })
        with self.assertRaises(ProviderError):
            CernoAdapter(transport=t).decide(
                _case_input(), "choice", _ctx())

    def test_non_finite_probability_is_terminal(self):
        t = _transport_for({
            "decision": _choice_answer(
                probabilities={"approve": 0.1, "deny": float("nan")}),
        })
        with self.assertRaises(ProviderError):
            CernoAdapter(transport=t).decide(
                _case_input(), "choice", _ctx())

    def test_zero_mass_probabilities_is_terminal(self):
        t = _transport_for({
            "decision": _choice_answer(
                choice="approve", confidence=0.0,
                probabilities={"approve": 0.0, "deny": 0.0}),
        })
        with self.assertRaises(ProviderError):
            CernoAdapter(transport=t).decide(
                _case_input(), "choice", _ctx())

    def test_probabilities_map_missing_the_decision_is_terminal(self):
        t = _transport_for({
            "decision": _choice_answer(probabilities={"approve": 1.0}),
        })
        with self.assertRaises(ProviderError):
            CernoAdapter(transport=t).decide(
                _case_input(), "choice", _ctx())

    def test_score_happy_path(self):
        t = _transport_for({
            "score": {
                "type": "score",
                "score": 2.0,
                "confidence": 0.6,
                "probabilities": {"0": 0.1, "1": 0.2, "2": 0.4,
                                  "3": 0.2, "4": 0.1},
            },
            "decision": _choice_answer(
                choice="approve", confidence=0.6,
                probabilities={"approve": 0.6, "deny": 0.4}),
        })
        out = CernoAdapter(transport=t).decide(
            _case_input(), "score", _ctx())
        self.assertEqual(validate_output(out, "score"), [])
        self.assertAlmostEqual(out.score, 2.0 / 4)
        self.assertEqual(out.decision, "approve")
        self.assertAlmostEqual(out.confidence, 0.6)

    def test_score_without_confidence_uses_the_probability(self):
        # The vendor's published format omits confidence on BOTH
        # answers. The inherited score mapping defaults an absent
        # decision confidence to 0.5 without consulting the map;
        # the adapter normalizes the field from the map instead,
        # so the recorded confidence is the model's probability
        # for the decision (0.9 from _choice_answer's map), never
        # the default.
        decision = _choice_answer()
        del decision["confidence"]
        del decision["certainty"]
        t = _transport_for({
            "score": {
                "type": "score",
                "score": 0.6,
                "probabilities": {"0": 0.7, "1": 0.2, "2": 0.1},
            },
            "decision": decision,
        })
        out = CernoAdapter(transport=t).decide(
            _case_input(), "score", _ctx())
        self.assertEqual(validate_output(out, "score"), [])
        self.assertAlmostEqual(out.score, 0.6 / 4)
        self.assertAlmostEqual(out.confidence, 0.9)

    def test_score_without_probabilities_map_is_terminal(self):
        # The vendored score format always emits the level map;
        # its absence is drift, like the choice map's absence.
        t = _transport_for({
            "score": {"type": "score", "score": 0.6,
                      "confidence": 0.9},
            "decision": _choice_answer(),
        })
        with self.assertRaises(ProviderError):
            CernoAdapter(transport=t).decide(
                _case_input(), "score", _ctx())

    def test_score_out_of_range_is_terminal(self):
        t = _transport_for({
            "score": {"type": "score", "score": 4.5, "confidence": 0.6},
            "decision": _choice_answer(),
        })
        with self.assertRaises(ProviderError):
            CernoAdapter(transport=t).decide(
                _case_input(), "score", _ctx())

    def test_score_probability_for_unknown_level_is_terminal(self):
        t = _transport_for({
            "score": {
                "type": "score", "score": 2.0, "confidence": 0.6,
                "probabilities": {"0": 0.5, "7": 0.5},
            },
            "decision": _choice_answer(),
        })
        with self.assertRaises(ProviderError):
            CernoAdapter(transport=t).decide(
                _case_input(), "score", _ctx())

    def test_abstain_yes_means_abstain(self):
        t = _transport_for({"abstain": {"type": "noul", "noul": 0.75}})
        out = CernoAdapter(transport=t).decide(
            _case_input(), "abstain", _ctx())
        self.assertEqual(validate_output(out, "abstain"), [])
        self.assertEqual(out.decision, "abstain")
        self.assertAlmostEqual(out.confidence, 0.5)

    def test_abstain_no_returns_other_placeholder(self):
        t = _transport_for({"abstain": {"type": "noul", "noul": 0.4791}})
        out = CernoAdapter(transport=t).decide(
            _case_input(), "abstain", _ctx())
        self.assertEqual(validate_output(out, "abstain"), [])
        self.assertEqual(out.decision, "other")
        self.assertAlmostEqual(out.confidence, abs(2 * 0.4791 - 1))

    def test_abstain_missing_noul_is_terminal(self):
        t = _transport_for({"abstain": {"type": "noul"}})
        with self.assertRaises(ProviderError):
            CernoAdapter(transport=t).decide(
                _case_input(), "abstain", _ctx())

    def test_abstain_out_of_range_noul_is_terminal(self):
        t = _transport_for({"abstain": {"type": "noul", "noul": 1.2}})
        with self.assertRaises(ProviderError):
            CernoAdapter(transport=t).decide(
                _case_input(), "abstain", _ctx())

    def test_unknown_answer_type_is_terminal(self):
        # The answer is otherwise a valid choice answer, so only
        # the type check can reject it (the inherited parser
        # never looks at the type field).
        t = _transport_for({
            "decision": _choice_answer(type="rank"),
        })
        with self.assertRaises(ProviderError):
            CernoAdapter(transport=t).decide(
                _case_input(), "choice", _ctx())

    def test_non_object_answer_is_terminal(self):
        t = _transport_for({"decision": "deny"})
        with self.assertRaises(ProviderError):
            CernoAdapter(transport=t).decide(
                _case_input(), "choice", _ctx())

    def test_payload_model_is_pinned_id(self):
        t = _transport_for({"decision": _choice_answer()})
        CernoAdapter(transport=t).decide(_case_input(), "choice", _ctx())
        self.assertEqual(t.seen["payload"]["model"], MODEL_ID)

    def test_wrong_model_stamp_is_terminal(self):
        t = _transport_for({"decision": _choice_answer()},
                           model="cerno-9b")
        with self.assertRaises(ProviderError):
            CernoAdapter(transport=t).decide(
                _case_input(), "choice", _ctx())

    def test_vendored_default_stamp_is_terminal(self):
        # The vendored Decider names its responses decider-dev
        # when the checkpoint config carries no version. A
        # sidecar that forgets to stamp the checkpoint name is
        # out of contract, and the call must not be recorded
        # under the pin.
        t = _transport_for({"decision": _choice_answer()},
                           model="decider-dev")
        with self.assertRaises(ProviderError):
            CernoAdapter(transport=t).decide(
                _case_input(), "choice", _ctx())

    def test_missing_model_stamp_is_terminal(self):
        t = _transport_for({"decision": _choice_answer()}, model=None)
        with self.assertRaises(ProviderError):
            CernoAdapter(transport=t).decide(
                _case_input(), "choice", _ctx())

    def test_wrong_revision_stamp_is_terminal(self):
        # Same repo, different snapshot: the response names the
        # right model but the wrong revision, and the call must
        # not be recorded under the pin.
        t = _transport_for({"decision": _choice_answer()},
                           revision="0" * 40)
        with self.assertRaises(ProviderError):
            CernoAdapter(transport=t).decide(
                _case_input(), "choice", _ctx())

    def test_missing_revision_stamp_is_terminal(self):
        t = _transport_for({"decision": _choice_answer()},
                           revision=None)
        with self.assertRaises(ProviderError):
            CernoAdapter(transport=t).decide(
                _case_input(), "choice", _ctx())

    def test_disagreeing_confidence_is_normalized_to_the_probability(self):
        # A present confidence (0.8 here) that disagrees with the
        # distribution is not what peira records; the probability
        # for the chosen option (0.9) is.
        t = _transport_for({
            "decision": _choice_answer(confidence=0.8),
        })
        out = CernoAdapter(transport=t).decide(
            _case_input(), "choice", _ctx())
        self.assertAlmostEqual(out.confidence, 0.9)

    def test_choice_probabilities_must_sum_to_one(self):
        # Each value is individually in range, but the map is not
        # a distribution; the inherited parser would record the
        # chosen value (1.0) as if it were a probability from a
        # genuine softmax.
        t = _transport_for({
            "decision": _choice_answer(
                confidence=1.0,
                probabilities={"approve": 1.0, "deny": 1.0}),
        })
        with self.assertRaises(ProviderError):
            CernoAdapter(transport=t).decide(
                _case_input(), "choice", _ctx())

    def test_score_probabilities_must_sum_to_one(self):
        t = _transport_for({
            "score": {
                "type": "score", "score": 2.0, "confidence": 0.6,
                "probabilities": {"0": 0.5, "1": 0.5, "2": 0.5},
            },
            "decision": _choice_answer(),
        })
        with self.assertRaises(ProviderError):
            CernoAdapter(transport=t).decide(
                _case_input(), "score", _ctx())

    def test_score_non_dict_probabilities_is_terminal(self):
        t = _transport_for({
            "score": {
                "type": "score", "score": 2.0, "confidence": 0.6,
                "probabilities": [0.25, 0.25, 0.25, 0.25],
            },
            "decision": _choice_answer(),
        })
        with self.assertRaises(ProviderError):
            CernoAdapter(transport=t).decide(
                _case_input(), "score", _ctx())

    def test_score_probability_value_must_be_a_probability(self):
        t = _transport_for({
            "score": {
                "type": "score", "score": 2.0, "confidence": 0.6,
                "probabilities": {"0": 0.5, "1": "high", "2": 0.5},
            },
            "decision": _choice_answer(),
        })
        with self.assertRaises(ProviderError):
            CernoAdapter(transport=t).decide(
                _case_input(), "score", _ctx())

    def test_non_string_choice_is_terminal(self):
        t = _transport_for({
            "decision": _choice_answer(choice=3),
        })
        with self.assertRaises(ProviderError):
            CernoAdapter(transport=t).decide(
                _case_input(), "choice", _ctx())

    def test_abstain_key_alone_is_accepted(self):
        # The parser prefers an "abstain" key over "noul"; an
        # answer carrying the probability under that key (the
        # hosted Jev shape) measures normally.
        t = _transport_for({"abstain": {"type": "noul",
                                        "abstain": 0.75}})
        out = CernoAdapter(transport=t).decide(
            _case_input(), "abstain", _ctx())
        self.assertEqual(validate_output(out, "abstain"), [])
        self.assertEqual(out.decision, "abstain")

    def test_abstain_key_out_of_range_is_terminal(self):
        # The validated "noul" value (0.2) must not launder an
        # unvalidated "abstain" value (1.7) that the parser would
        # prefer and clamp to 1.0.
        t = _transport_for({"abstain": {"type": "noul", "noul": 0.2,
                                        "abstain": 1.7}})
        with self.assertRaises(ProviderError):
            CernoAdapter(transport=t).decide(
                _case_input(), "abstain", _ctx())

    def test_abstain_key_wins_over_noul(self):
        # Both keys present and valid: the parser reads
        # "abstain", so the outcome follows it (0.1, no abstain),
        # not the "noul" value (0.9).
        t = _transport_for({"abstain": {"type": "noul", "noul": 0.9,
                                        "abstain": 0.1}})
        out = CernoAdapter(transport=t).decide(
            _case_input(), "abstain", _ctx())
        self.assertEqual(validate_output(out, "abstain"), [])
        self.assertEqual(out.decision, "other")


class TestCernoSiblingPins(unittest.TestCase):
    """The 9B and 27B pins: same adapter contract, own checkpoint.

    Each sibling class pins exactly its own checkpoint (id,
    sidecar stamp, Hub revision), rejects the other family
    members at construction, and fails closed when the sidecar
    reports a sibling's stamp or a wrong revision — a 4B
    deployment answering on the 9B port must not be measured
    under the 9B pin.
    """

    def test_9b_pin(self):
        self.assertEqual(MODEL_ID_9B, "apertixai/cerno-9b")
        self.assertEqual(EXPECTED_MODEL_STAMP_9B, "cerno-9b")
        self.assertEqual(
            PINNED_REVISION_9B,
            "80010f97eaa989b41c908ecba7d7b7fadaa99239")
        a = Cerno9BAdapter()
        self.assertEqual(a.model, MODEL_ID_9B)
        self.assertEqual(a.version, MODEL_ID_9B)
        self.assertEqual(a.cache_namespace, f"cerno-9b:{MODEL_ID_9B}")
        self.assertEqual(
            a.api_url, "http://127.0.0.1:8018/v1/systemone")
        self.assertEqual(a.timeout_s, 1200.0)
        self.assertEqual(Cerno9BAdapter.supported_primitives,
                         frozenset({"choice", "score", "abstain"}))

    def test_27b_pin(self):
        self.assertEqual(MODEL_ID_27B, "apertixai/cerno-27b")
        self.assertEqual(EXPECTED_MODEL_STAMP_27B, "cerno-27b")
        self.assertEqual(
            PINNED_REVISION_27B,
            "c2f7efe54fe4d3dfd7136bb2e9daf2c0c0633e3d")
        a = Cerno27BAdapter()
        self.assertEqual(a.model, MODEL_ID_27B)
        self.assertEqual(a.version, MODEL_ID_27B)
        self.assertEqual(a.cache_namespace, f"cerno-27b:{MODEL_ID_27B}")
        self.assertEqual(
            a.api_url, "http://127.0.0.1:8019/v1/systemone")

    def test_siblings_reject_each_other_and_the_4b(self):
        for cls, own in ((Cerno9BAdapter, MODEL_ID_9B),
                         (Cerno27BAdapter, MODEL_ID_27B)):
            for bad in (MODEL_ID, MODEL_ID_9B, MODEL_ID_27B):
                if bad == own:
                    continue
                with self.assertRaises(ValueError, msg=(cls, bad)):
                    cls(model=bad)
            self.assertEqual(cls(model=own).model, own)

    def test_9b_choice_happy_path(self):
        t = _transport_for({"decision": _choice_answer()},
                           model="cerno-9b",
                           revision=PINNED_REVISION_9B)
        out = Cerno9BAdapter(transport=t).decide(
            _case_input(), "choice", _ctx())
        self.assertEqual(validate_output(out, "choice"), [])
        self.assertEqual(out.decision, "deny")
        self.assertAlmostEqual(out.confidence, 0.9)
        self.assertEqual(out.usage.model, MODEL_ID_9B)
        self.assertEqual(t.seen["payload"]["model"], MODEL_ID_9B)

    def test_9b_rejects_the_4b_stamp(self):
        # The 4B deployment answering on the 9B port: right family,
        # wrong checkpoint — terminal, never a 9B measurement.
        t = _transport_for({"decision": _choice_answer()},
                           model=_STAMP, revision=_REVISION)
        with self.assertRaises(ProviderError):
            Cerno9BAdapter(transport=t).decide(
                _case_input(), "choice", _ctx())

    def test_27b_rejects_a_wrong_revision(self):
        t = _transport_for({"decision": _choice_answer()},
                           model="cerno-27b", revision="0" * 40)
        with self.assertRaises(ProviderError):
            Cerno27BAdapter(transport=t).decide(
                _case_input(), "choice", _ctx())

    def test_27b_abstain_happy_path(self):
        t = _transport_for({"abstain": {"type": "noul", "noul": 0.75}},
                           model="cerno-27b",
                           revision=PINNED_REVISION_27B)
        out = Cerno27BAdapter(transport=t).decide(
            _case_input(), "abstain", _ctx())
        self.assertEqual(validate_output(out, "abstain"), [])
        self.assertEqual(out.decision, "abstain")


class TestCernoErrors(unittest.TestCase):
    def test_connection_refused_is_terminal_and_actionable(self):
        a = CernoAdapter()
        with mock.patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("connection refused"),
        ):
            with self.assertRaises(ProviderError) as cm:
                a._http_transport({"model": a.model})
        err = cm.exception
        self.assertIsNone(err.status_code)
        self.assertIn("cerno", str(err))
        self.assertIn("start the Cerno sidecar first", str(err))

    def test_missing_answers_is_terminal(self):
        t = _transport_for(None)
        with self.assertRaises(ProviderError):
            CernoAdapter(transport=t).decide(
                _case_input(), "choice", _ctx())

    def test_unknown_option_is_terminal(self):
        t = _transport_for({
            "decision": _choice_answer(
                choice="maybe", confidence=0.5,
                probabilities={"maybe": 1.0}),
        })
        with self.assertRaises(ProviderError):
            CernoAdapter(transport=t).decide(
                _case_input(), "choice", _ctx())

    def test_unsupported_primitive(self):
        with self.assertRaises(ValueError):
            CernoAdapter().decide(_case_input(), "bogus", _ctx())



class TestCernoHugeIntValidation(unittest.TestCase):
    def test_huge_int_probability_is_terminal(self):
        # math.isfinite converted its argument to float, so a
        # several-hundred-digit probability escaped the validator
        # as an OverflowError instead of failing closed.
        t = _transport_for({
            "decision": _choice_answer(
                probabilities={"approve": 0.1, "deny": 10**400}),
        })
        with self.assertRaises(ProviderError):
            CernoAdapter(transport=t).decide(
                _case_input(), "choice", _ctx())

    def test_huge_int_confidence_is_terminal(self):
        t = _transport_for({
            "decision": _choice_answer(confidence=10**400),
        })
        with self.assertRaises(ProviderError):
            CernoAdapter(transport=t).decide(
                _case_input(), "choice", _ctx())

    def test_probability_predicates_handle_huge_ints(self):
        self.assertFalse(cerno_mod._is_probability(10**400))
        self.assertTrue(cerno_mod._is_probability(1))
        self.assertTrue(cerno_mod._is_finite_number(10**400))
        self.assertFalse(cerno_mod._is_finite_number(float("nan")))

if __name__ == "__main__":
    unittest.main()
