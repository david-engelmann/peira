"""Tests for the Laya adapter.

Everything is mocked: the ``laya`` package is faked in ``sys.modules``
or bypassed entirely via the ``agent=`` test seam — no model weights
are downloaded, no network calls happen, and the real package is never
required.

The fakes below are written against Laya's documented API —
``laya.load(checkpoint)`` returning an agent with
``agent.predict(state, questions)`` -> ``{"answers": {name: {...}}}`` —
not against any earlier draft of this adapter.
"""

import sys
import types
import unittest

from peira.adapters.base import CallContext, ProviderError, validate_output
from peira.adapters import laya as laya_mod
from peira.adapters.laya import (
    CHECKPOINTS,
    DEFAULT_CHECKPOINT,
    LayaAdapter,
)


# Trial-bookkeeping defaults for adapter unit tests (the runner builds
# the real CallContext).
_CTX_DEFAULTS = {
    "case_id": "l1",
    "expected_decision": "deny",
    "target_decision": "approve",
    "attacked": True,
}


def _case_input(**over):
    # The pure case input: trial bookkeeping lives on the context now,
    # never in the input dict.
    d = {"prompt": "Decision: approve or deny?"}
    for k, v in over.items():
        if k not in _CTX_DEFAULTS:
            d[k] = v
    return d


def _ctx(**over):
    vals = dict(_CTX_DEFAULTS)
    vals.update(over)
    return CallContext(
        case_id=vals["case_id"],
        arm="attacked" if vals["attacked"] else "benign",
        expected_decision=vals["expected_decision"],
        target_decision=vals["target_decision"],
    )


class FakeAgent:
    """Stands in for the object ``laya.load`` returns."""

    def __init__(self, answers=None, result=None, exc=None):
        # ``answers`` is the inner {"answers": ...} payload and gets
        # wrapped; ``result`` is the raw predict() return value (for
        # malformed-response tests).
        if result is not None:
            self._result = result
        else:
            self._result = {"answers": answers if answers is not None else {}}
        self._exc = exc
        self.seen = {}

    def predict(self, state, questions):
        self.seen["state"] = state
        self.seen["questions"] = questions
        if self._exc is not None:
            raise self._exc
        return self._result


def _adapter(agent, checkpoint=DEFAULT_CHECKPOINT):
    # The agent= seam bypasses laya.load entirely: no package needed.
    return LayaAdapter(checkpoint=checkpoint, agent=agent)


class _BlockLayaImport:
    """Meta-path hook that makes ``import laya`` fail, simulating a
    machine where the package is not installed."""

    def find_module(self, name, path=None):
        if name == "laya" or name.startswith("laya."):
            return self
        return None

    def load_module(self, name):
        raise ImportError(f"No module named {name!r} (blocked for test)")


class TestLayaConstruction(unittest.TestCase):
    def test_missing_laya_package_is_actionable(self):
        saved = sys.modules.pop("laya", None)
        blocker = _BlockLayaImport()
        sys.meta_path.insert(0, blocker)
        try:
            with self.assertRaises(ImportError) as cm:
                LayaAdapter()
        finally:
            sys.meta_path.remove(blocker)
            if saved is not None:
                sys.modules["laya"] = saved
        self.assertIn("pip install laya", str(cm.exception))

    def test_lazy_import_calls_laya_load_with_checkpoint(self):
        fake = types.ModuleType("laya")
        seen = {}
        agent = FakeAgent({"decision": {"choice": "deny", "confidence": 0.9}})

        def fake_load(checkpoint):
            seen["checkpoint"] = checkpoint
            return agent

        fake.load = fake_load
        saved = sys.modules.get("laya")
        sys.modules["laya"] = fake
        try:
            a = LayaAdapter(checkpoint="convaiinnovations/laya-multilingual")
        finally:
            if saved is not None:
                sys.modules["laya"] = saved
            else:
                sys.modules.pop("laya", None)
        self.assertEqual(seen["checkpoint"],
                         "convaiinnovations/laya-multilingual")
        self.assertIs(a._agent, agent)

    def test_default_checkpoint(self):
        a = _adapter(FakeAgent())
        self.assertEqual(a.checkpoint, "convaiinnovations/laya")
        self.assertEqual(a.version, "convaiinnovations/laya")
        self.assertEqual(a.name, "laya")

    def test_all_three_checkpoints_configurable(self):
        expected = {
            "convaiinnovations/laya",
            "convaiinnovations/laya-multilingual",
            "convaiinnovations/laya-typed-decisions",
        }
        self.assertEqual(set(CHECKPOINTS.values()), expected)
        self.assertEqual(DEFAULT_CHECKPOINT, "convaiinnovations/laya")
        seen_namespaces = set()
        for cp in expected | set(CHECKPOINTS):
            a = _adapter(FakeAgent(), checkpoint=cp)
            self.assertEqual(a.checkpoint, CHECKPOINTS.get(cp, cp))
            self.assertEqual(a.version, a.checkpoint)
            # Cache namespace must differ per checkpoint so runner cache
            # entries never cross checkpoints.
            self.assertTrue(a.cache_namespace.startswith("laya:"))
            seen_namespaces.add(a.cache_namespace)
        self.assertEqual(len(seen_namespaces), 3)

    def test_unknown_checkpoint_rejected(self):
        with self.assertRaises(ValueError):
            _adapter(FakeAgent(), checkpoint="convaiinnovations/laya-latest")
        with self.assertRaises(ValueError):
            _adapter(FakeAgent(), checkpoint="")
        with self.assertRaises(ValueError):
            _adapter(FakeAgent(), checkpoint=None)

    def test_supported_primitives(self):
        a = _adapter(FakeAgent())
        self.assertEqual(a.supported_primitives,
                         frozenset({"choice", "score", "abstain"}))

    def test_unsupported_primitive(self):
        with self.assertRaises(ValueError):
            _adapter(FakeAgent()).decide(_case_input(), "bogus", _ctx())


class TestLayaChoice(unittest.TestCase):
    def test_choice_maps_option_and_confidence(self):
        agent = FakeAgent({"decision": {"choice": "approve",
                                        "probabilities": {"deny": 0.2,
                                                          "approve": 0.7,
                                                          "other": 0.1},
                                        "confidence": 0.7}})
        out = _adapter(agent).decide(_case_input(), "choice", _ctx())
        self.assertEqual(validate_output(out, "choice"), [])
        self.assertEqual(out.decision, "approve")
        self.assertAlmostEqual(out.confidence, 0.7)
        self.assertEqual(out.usage.model, "convaiinnovations/laya")
        # Transcript carries the checkpoint, never secrets.
        self.assertEqual(out.transcript["checkpoint"],
                         "convaiinnovations/laya")

    def test_choice_request_shape(self):
        agent = FakeAgent({"decision": {"choice": "deny", "confidence": 0.9}})
        _adapter(agent).decide(_case_input(), "choice", _ctx())
        self.assertEqual(agent.seen["state"], "Decision: approve or deny?")
        q = agent.seen["questions"]["decision"]
        self.assertEqual(set(q), {"type", "instructions", "criteria"})
        self.assertEqual(q["type"], "choice")
        self.assertTrue(q["instructions"])
        # criteria is a dict (label -> description), per Laya's API.
        self.assertIsInstance(q["criteria"], dict)
        self.assertIn("deny", q["criteria"])
        self.assertIn("approve", q["criteria"])  # target offered on attacked

    def test_choice_benign_labels(self):
        agent = FakeAgent({"decision": {"choice": "deny", "confidence": 0.9}})
        _adapter(agent).decide(_case_input(), "choice",
                               _ctx(attacked=False, target_decision=None))
        labels = list(agent.seen["questions"]["decision"]["criteria"])
        self.assertIn("deny", labels)
        self.assertIn("other", labels)
        self.assertNotIn("approve", labels)

    def test_null_expected_decision_never_becomes_none_label(self):
        agent = FakeAgent({"decision": {"choice": "approve",
                                        "confidence": 0.9}})
        _adapter(agent).decide(_case_input(), "choice",
                               _ctx(expected_decision=None,
                                    target_decision=None))
        labels = list(agent.seen["questions"]["decision"]["criteria"])
        self.assertNotIn("None", labels)
        self.assertIn("approve", labels)  # fallback, not str(None)

    def test_unknown_keys_ignored(self):
        agent = FakeAgent({"decision": {"choice": "deny", "confidence": 0.9}})
        out = _adapter(agent).decide(_case_input(weird_key="x"),
                                     "choice", _ctx())
        self.assertEqual(out.decision, "deny")


class TestLayaScore(unittest.TestCase):
    def _score_agent(self, value, option="deny", conf=0.8):
        return FakeAgent({
            "score": {"score": value},
            "decision": {"choice": option, "confidence": conf},
        })

    def test_score_maps_value_and_decision(self):
        out = _adapter(self._score_agent(0.8)).decide(_case_input(), "score",
                                                     _ctx())
        self.assertEqual(validate_output(out, "score"), [])
        self.assertAlmostEqual(out.score, 0.8)
        self.assertEqual(out.decision, "deny")
        self.assertAlmostEqual(out.confidence, 0.8)

    def test_score_clamped(self):
        out = _adapter(self._score_agent(99)).decide(_case_input(), "score",
                                                     _ctx())
        self.assertEqual(out.score, 1.0)
        out = _adapter(self._score_agent(-3)).decide(_case_input(), "score",
                                                     _ctx())
        self.assertEqual(out.score, 0.0)

    def test_score_sends_two_questions_with_list_criteria(self):
        agent = self._score_agent(0.5)
        _adapter(agent).decide(_case_input(), "score", _ctx())
        qs = agent.seen["questions"]
        self.assertEqual(set(qs), {"score", "decision"})
        sq = qs["score"]
        self.assertEqual(set(sq), {"type", "instructions", "criteria"})
        self.assertEqual(sq["type"], "score")
        # criteria is a list of level descriptions, per Laya's API.
        self.assertIsInstance(sq["criteria"], list)
        self.assertTrue(all(isinstance(c, str) and c for c in sq["criteria"]))


class TestLayaAbstainNoulBoundary(unittest.TestCase):
    """Peira's ``abstain`` primitive <-> Laya's ``noul`` wire type.

    These tests pin the boundary mapping explicitly: the question is
    keyed by peira's primitive name ("abstain"), its ``type`` is Laya's
    external name ("noul"), and the answer field is Laya's "noul".
    """

    def _abstain_agent(self, p_noul):
        return FakeAgent({"abstain": {"noul": p_noul}})

    def test_noul_question_type_not_abstain(self):
        agent = self._abstain_agent(0.1)
        _adapter(agent).decide(_case_input(), "abstain", _ctx())
        qs = agent.seen["questions"]
        # Keyed by OUR primitive name...
        self.assertEqual(set(qs), {"abstain"})
        q = qs["abstain"]
        # ...but typed with LAYA's external name (the boundary mapping).
        self.assertEqual(q["type"], "noul")
        self.assertNotEqual(q["type"], "abstain")
        self.assertTrue(q["instructions"])
        self.assertNotIn("criteria", q)

    def test_noul_yes_means_abstain(self):
        out = _adapter(self._abstain_agent(0.8)).decide(_case_input(),
                                                       "abstain", _ctx())
        self.assertEqual(validate_output(out, "abstain"), [])
        self.assertEqual(out.decision, "abstain")
        self.assertAlmostEqual(out.confidence, 0.6)  # |2*.8-1|

    def test_noul_no_returns_expected(self):
        out = _adapter(self._abstain_agent(0.2)).decide(_case_input(),
                                                       "abstain", _ctx())
        self.assertEqual(out.decision, "deny")
        self.assertAlmostEqual(out.confidence, 0.6)

    def test_noul_answer_field_is_noul_not_abstain(self):
        # If the adapter read an "abstain" field instead of Laya's
        # "noul" field, this would raise — the field name is pinned.
        agent = FakeAgent({"abstain": {"noul": 0.9, "abstain": 0.0}})
        out = _adapter(agent).decide(_case_input(), "abstain", _ctx())
        self.assertEqual(out.decision, "abstain")  # read 0.9, not 0.0


class TestLayaQuestionValidation(unittest.TestCase):
    def test_malformed_question_is_terminal_before_send(self):
        with self.assertRaises(ProviderError):
            laya_mod._validate_questions(
                {"bad": {"type": "choice"}})  # no instructions/criteria
        with self.assertRaises(ProviderError):
            laya_mod._validate_questions(
                {"bad": {"type": "bogus", "instructions": "x"}})
        # Well-formed questions pass silently — note "noul" is Laya's
        # external type for peira's abstain primitive.
        laya_mod._validate_questions({
            "d": {"type": "choice", "instructions": "i",
                  "criteria": {"a": "A"}},
            "s": {"type": "score", "instructions": "i",
                  "criteria": ["low", "high"]},
            "n": {"type": "noul", "instructions": "i"},
        })


class TestLayaMalformedResponses(unittest.TestCase):
    """Malformed Laya responses never crash: they raise ProviderError
    (no status code, so the runner treats them as permanent and marks
    the variant malformed)."""

    def _raises(self, agent):
        with self.assertRaises(ProviderError) as cm:
            _adapter(agent).decide(_case_input(), "choice", _ctx())
        # No status code: not retryable, never a crash.
        self.assertIsNone(cm.exception.status_code)

    def test_non_dict_result(self):
        self._raises(FakeAgent(result=["not", "a", "dict"]))

    def test_missing_answers(self):
        self._raises(FakeAgent(result={"nope": {}}))
        self._raises(FakeAgent(result={"answers": None}))

    def test_missing_answer_for_question(self):
        self._raises(FakeAgent({"wrong_name": {"choice": "deny"}}))

    def test_choice_outside_labels(self):
        self._raises(FakeAgent({"decision": {"choice": "maybe",
                                             "confidence": 0.5}}))

    def test_score_non_numeric(self):
        agent = FakeAgent({
            "score": {"score": "high"},
            "decision": {"choice": "deny", "confidence": 0.9},
        })
        with self.assertRaises(ProviderError):
            _adapter(agent).decide(_case_input(), "score", _ctx())

    def test_noul_non_numeric(self):
        agent = FakeAgent({"abstain": {"noul": "yes"}})
        with self.assertRaises(ProviderError):
            _adapter(agent).decide(_case_input(), "abstain", _ctx())

    def test_predict_failure_is_terminal_not_a_retry(self):
        agent = FakeAgent(exc=RuntimeError("weights exploded"))
        with self.assertRaises(ProviderError) as cm:
            _adapter(agent).decide(_case_input(), "choice", _ctx())
        self.assertIsNone(cm.exception.status_code)
        self.assertIsNone(cm.exception.retry_after)


if __name__ == "__main__":
    unittest.main()
