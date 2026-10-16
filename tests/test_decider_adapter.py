"""Tests for the Decider adapter.

No network, no decider-ai package: the engine is faked like
LayaAdapter's agent in test_laya_adapter.py. Under test: the pinned
checkpoint, the Jev question builders reused unchanged, and the two
answer readings that matter (confidence is the raw probability for
the chosen option rather than the rescaled TypeSafe figure, and the
score arrives on the 0..levels-1 index scale).
"""

import unittest

from peira.adapters.base import CallContext, ProviderError, validate_output
from peira.adapters.decider import CHECKPOINT, PINNED_REVISION, DeciderAdapter

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


class _FakeEngine:
    """Records system_one calls and returns scripted answers."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def system_one(self, state, questions):
        self.calls.append({"state": state, "questions": questions})
        return {"answers": self.answers}


def _adapter(answers):
    fake = _FakeEngine(answers)
    return DeciderAdapter(engine=fake), fake


class TestDeciderConstruction(unittest.TestCase):
    def test_checkpoint_pinned(self):
        self.assertEqual(CHECKPOINT, "Mapika/decider-0.8b")
        a, _ = _adapter({})
        self.assertEqual(a.checkpoint, CHECKPOINT)
        self.assertEqual(a.revision, PINNED_REVISION)
        self.assertEqual(a.version, f"{CHECKPOINT}@{PINNED_REVISION}")
        self.assertEqual(a.cache_namespace, f"decider:{a.version}")

    def test_other_checkpoints_rejected(self):
        for bad in ("Mapika/decider-2b", "Mapika/decider-4b", "", "latest"):
            with self.assertRaises(ValueError, msg=bad):
                DeciderAdapter(checkpoint=bad, engine=_FakeEngine({}))

    def test_unpinned_revisions_rejected(self):
        for bad in ("", "main", "v1.0", None,
                    "b50019a70ccd" + "0" * 28):
            with self.assertRaises(ValueError, msg=repr(bad)):
                DeciderAdapter(revision=bad, engine=_FakeEngine({}))

    def test_supported_primitives(self):
        self.assertEqual(DeciderAdapter.name, "decider")
        self.assertEqual(DeciderAdapter.supported_primitives,
                         frozenset({"choice", "score", "abstain"}))


class TestDeciderWire(unittest.TestCase):
    def test_choice_confidence_is_the_probability(self):
        a, fake = _adapter({
            "decision": {
                "choice": "deny",
                "confidence": 0.8,  # rescaled TypeSafe figure
                "x_p_max": 0.9,
                "probabilities": {"approve": 0.1, "deny": 0.9, "other": 0.0},
            },
        })
        out = a.decide(_case_input(), "choice", _ctx())
        self.assertEqual(validate_output(out, "choice"), [])
        self.assertEqual(out.decision, "deny")
        self.assertAlmostEqual(out.confidence, 0.9)
        (call,) = fake.calls
        self.assertEqual(call["questions"]["decision"]["type"], "choice")

    def test_score_index_scale_is_normalized(self):
        a, _ = _adapter({
            "score": {"score": 3.0, "probabilities": {"0": 0.0, "1": 0.0,
                                                      "2": 0.0, "3": 1.0,
                                                      "4": 0.0}},
            "decision": {
                "choice": "approve",
                "confidence": 0.5,
                "probabilities": {"approve": 0.75, "deny": 0.25},
            },
        })
        out = a.decide(_case_input(), "score", _ctx())
        self.assertEqual(validate_output(out, "score"), [])
        self.assertAlmostEqual(out.score, 3.0 / 4)
        self.assertEqual(out.decision, "approve")
        self.assertAlmostEqual(out.confidence, 0.75)

    def test_abstain_yes_means_abstain(self):
        a, fake = _adapter({"abstain": {"noul": 0.75}})
        out = a.decide(_case_input(), "abstain", _ctx())
        self.assertEqual(validate_output(out, "abstain"), [])
        self.assertEqual(out.decision, "abstain")
        self.assertAlmostEqual(out.confidence, 0.5)
        (call,) = fake.calls
        self.assertEqual(call["questions"]["abstain"]["type"], "noul")

    def test_abstain_no_means_placeholder_decision(self):
        a, _ = _adapter({"abstain": {"noul": 0.1}})
        out = a.decide(_case_input(), "abstain", _ctx())
        self.assertEqual(out.decision, "other")
        self.assertAlmostEqual(out.confidence, 0.8)

    def test_unsupported_primitive(self):
        a, _ = _adapter({})
        with self.assertRaises(ValueError):
            a.decide(_case_input(), "bogus", _ctx())


class TestDeciderErrors(unittest.TestCase):
    def test_unknown_choice_label_is_terminal(self):
        a, _ = _adapter({
            "decision": {"choice": "maybe", "confidence": 0.5,
                         "probabilities": {"maybe": 0.5}},
        })
        with self.assertRaises(ProviderError):
            a.decide(_case_input(), "choice", _ctx())

    def test_missing_answers_is_terminal(self):
        class Empty:
            def system_one(self, state, questions):
                return {}

        a = DeciderAdapter(engine=Empty())
        with self.assertRaises(ProviderError):
            a.decide(_case_input(), "choice", _ctx())

    def test_non_numeric_score_is_terminal(self):
        a, _ = _adapter({
            "score": {"score": "high"},
            "decision": {"choice": "deny", "confidence": 0.9},
        })
        with self.assertRaises(ProviderError):
            a.decide(_case_input(), "score", _ctx())

    def test_non_numeric_noul_is_terminal(self):
        a, _ = _adapter({"abstain": {"noul": "yes"}})
        with self.assertRaises(ProviderError):
            a.decide(_case_input(), "abstain", _ctx())

    def test_choice_without_probabilities_is_terminal(self):
        # Only the rescaled TypeSafe figure is present. Reporting it
        # as the raw probability would fabricate the measurement.
        a, _ = _adapter({
            "decision": {"choice": "approve", "confidence": 0.8},
        })
        with self.assertRaises(ProviderError):
            a.decide(_case_input(), "choice", _ctx())

    def test_probability_of_another_option_is_not_used(self):
        # The distribution lacks the chosen option and x_p_max names
        # a different one. A fallback ladder once reported 0.9 as
        # deny's confidence; the answer is drift and is terminal.
        a, _ = _adapter({
            "decision": {"choice": "deny", "x_p_max": 0.9,
                         "probabilities": {"approve": 0.9}},
        })
        with self.assertRaises(ProviderError):
            a.decide(_case_input(), "choice", _ctx())

    def test_abstain_answer_under_the_wrong_key_is_terminal(self):
        # The engine emits the value under "noul" only. The same
        # number under an "abstain" key is drift, not a reading.
        a, _ = _adapter({"abstain": {"abstain": 0.75}})
        with self.assertRaises(ProviderError):
            a.decide(_case_input(), "abstain", _ctx())

    def test_engine_failure_is_terminal_provider_error(self):
        class Boom:
            def system_one(self, state, questions):
                raise RuntimeError("weights missing")

        a = DeciderAdapter(engine=Boom())
        with self.assertRaises(ProviderError) as cm:
            a.decide(_case_input(), "choice", _ctx())
        self.assertIsNone(cm.exception.status_code)
        self.assertIn("decider system_one failed", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
