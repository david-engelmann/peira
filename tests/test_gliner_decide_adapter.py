"""Tests for the GLiNER2.5-Decide adapter.

No network, no gliner2 package: the extractor is faked like
LayaAdapter's agent in test_laya_adapter.py. Under test: the pinned
checkpoint, the label mapping per primitive (choice labels as a
described set, score levels as labels, abstain as a two-label set),
and the confidence readings.
"""

import unittest

from peira.adapters.base import CallContext, ProviderError, validate_output
from peira.adapters.gliner_decide import (
    CHECKPOINT,
    PINNED_REVISION,
    GlinerDecideAdapter,
)

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


class _FakeExtractor:
    """Records classify_text calls and returns scripted winners."""

    def __init__(self, winners):
        self.winners = winners  # task name -> (label, confidence)
        self.calls = []

    def classify_text(self, text, tasks, include_confidence=False):
        self.calls.append(
            {"text": text, "tasks": tasks,
             "include_confidence": include_confidence}
        )
        return {
            task: {"label": label, "confidence": conf}
            for task, (label, conf) in self.winners.items()
        }


def _adapter(winners):
    fake = _FakeExtractor(winners)
    return GlinerDecideAdapter(extractor=fake), fake


class TestGlinerDecideConstruction(unittest.TestCase):
    def test_checkpoint_pinned(self):
        self.assertEqual(CHECKPOINT, "fastino/GLiNER2.5-Decide")
        a, _ = _adapter({})
        self.assertEqual(a.checkpoint, CHECKPOINT)
        self.assertEqual(a.revision, PINNED_REVISION)
        self.assertEqual(a.version, f"{CHECKPOINT}@{PINNED_REVISION}")
        self.assertEqual(a.cache_namespace, f"gliner-decide:{a.version}")

    def test_other_checkpoints_rejected(self):
        for bad in ("fastino/GLiNER2.5-multi-Decide", "fastino/gliner2-large-v1",
                    "", "latest"):
            with self.assertRaises(ValueError, msg=bad):
                GlinerDecideAdapter(checkpoint=bad, extractor=_FakeExtractor({}))

    def test_empty_revision_rejected(self):
        with self.assertRaises(ValueError):
            GlinerDecideAdapter(revision="", extractor=_FakeExtractor({}))

    def test_checkpoint_rejection_message_matches_troubleshooting_quote(self):
        # docs/Troubleshooting.md quotes this message in its heading,
        # so the full emitted text is pinned here. A wording change
        # must move the doc quote in the same change.
        with self.assertRaises(ValueError) as cm:
            GlinerDecideAdapter(checkpoint="fastino/gliner2-large-v1",
                                extractor=_FakeExtractor({}))
        self.assertEqual(
            str(cm.exception),
            "gliner-decide adapter pins checkpoint "
            "'fastino/GLiNER2.5-Decide'; got 'fastino/gliner2-large-v1'. "
            "Floating or unlisted ids are rejected; a measurement must "
            "name the exact model.")

    def test_revision_rejection_message_matches_troubleshooting_quote(self):
        # Same pinning convention as the checkpoint message above,
        # and the regression test for the unenforced pin: a branch
        # name is a floating revision and must not construct.
        with self.assertRaises(ValueError) as cm:
            GlinerDecideAdapter(revision="main",
                                extractor=_FakeExtractor({}))
        self.assertEqual(
            str(cm.exception),
            "gliner-decide adapter pins revision "
            "'9d1bfb848cd16d93ee56ccbc59cd92bf0f284d90'; got 'main'. "
            "Floating or unlisted revisions are rejected; a "
            "measurement must name the exact model.")

    def test_other_revisions_rejected(self):
        for bad in ("0e311eae23d1" + "0" * 28, 123, None):
            with self.assertRaises(ValueError, msg=repr(bad)):
                GlinerDecideAdapter(revision=bad,
                                    extractor=_FakeExtractor({}))

    def test_supported_primitives(self):
        self.assertEqual(GlinerDecideAdapter.name, "gliner-decide")
        self.assertEqual(GlinerDecideAdapter.supported_primitives,
                         frozenset({"choice", "score", "abstain"}))


class TestGlinerDecideMapping(unittest.TestCase):
    def test_choice_uses_described_candidate_labels(self):
        a, fake = _adapter({"decision": ("deny", 0.9)})
        out = a.decide(_case_input(), "choice", _ctx())
        self.assertEqual(validate_output(out, "choice"), [])
        self.assertEqual(out.decision, "deny")
        self.assertAlmostEqual(out.confidence, 0.9)
        (call,) = fake.calls
        self.assertTrue(call["include_confidence"])
        task = call["tasks"]["decision"]
        # Candidate labels are the case options plus "other", each
        # carrying a description.
        self.assertEqual(sorted(task), ["approve", "deny", "other"])
        self.assertEqual(task["other"],
                         "None of the listed options is the correct decision.")
        self.assertIn("approve", task["approve"])

    def test_score_levels_are_labels_and_position_is_the_score(self):
        a, fake = _adapter({
            "score": ("probably the right decision", 0.6),
            "decision": ("approve", 0.7),
        })
        out = a.decide(_case_input(), "score", _ctx())
        self.assertEqual(validate_output(out, "score"), [])
        self.assertAlmostEqual(out.score, 3 / 4)
        self.assertEqual(out.decision, "approve")
        self.assertAlmostEqual(out.confidence, 0.7)
        (call,) = fake.calls
        # The rubric levels are measurement-instrument text: pin
        # them literally, not against the adapter's own constant.
        self.assertEqual(call["tasks"]["score"], [
            "clearly the wrong decision",
            "probably the wrong decision",
            "uncertain, could go either way",
            "probably the right decision",
            "clearly the right decision",
        ])
        self.assertIn("decision", call["tasks"])

    def test_score_extremes(self):
        a, _ = _adapter({
            "score": ("clearly the wrong decision", 0.95),
            "decision": ("deny", 0.8),
        })
        out = a.decide(_case_input(), "score", _ctx())
        self.assertAlmostEqual(out.score, 0.0)

    def test_score_top_extreme(self):
        a, _ = _adapter({
            "score": ("clearly the right decision", 0.95),
            "decision": ("approve", 0.8),
        })
        out = a.decide(_case_input(), "score", _ctx())
        self.assertAlmostEqual(out.score, 1.0)

    def test_transcript_records_response_verbatim(self):
        a, _ = _adapter({"decision": ("deny", 0.9)})
        out = a.decide(_case_input(), "choice", _ctx())
        self.assertEqual(out.transcript["checkpoint"], CHECKPOINT)
        self.assertEqual(out.transcript["revision"], PINNED_REVISION)
        self.assertEqual(out.transcript["response"],
                         {"decision": {"label": "deny",
                                       "confidence": 0.9}})
        self.assertEqual(out.transcript["request"],
                         {"tasks": {"decision": {"labels": 3}}})

    def test_abstain_yes_winner(self):
        a, fake = _adapter({"abstain": ("yes", 0.75)})
        out = a.decide(_case_input(), "abstain", _ctx())
        self.assertEqual(validate_output(out, "abstain"), [])
        self.assertEqual(out.decision, "abstain")
        self.assertAlmostEqual(out.confidence, 0.5)
        (call,) = fake.calls
        self.assertEqual(sorted(call["tasks"]["abstain"]), ["no", "yes"])

    def test_abstain_no_winner_inverts_confidence(self):
        a, _ = _adapter({"abstain": ("no", 0.9)})
        out = a.decide(_case_input(), "abstain", _ctx())
        self.assertEqual(out.decision, "other")
        # p_yes = 1 - 0.9 = 0.1, confidence = |2*0.1 - 1| = 0.8.
        self.assertAlmostEqual(out.confidence, 0.8)

    def test_abstain_boundary_at_half(self):
        # p_yes = 0.5 exactly meets the >= 0.5 threshold, with
        # confidence |2*0.5 - 1| = 0.
        a, _ = _adapter({"abstain": ("yes", 0.5)})
        out = a.decide(_case_input(), "abstain", _ctx())
        self.assertEqual(out.decision, "abstain")
        self.assertAlmostEqual(out.confidence, 0.0)

    def test_unsupported_primitive(self):
        a, _ = _adapter({})
        with self.assertRaises(ValueError):
            a.decide(_case_input(), "bogus", _ctx())


class TestGlinerDecideErrors(unittest.TestCase):
    def test_unknown_choice_label_is_terminal(self):
        a, _ = _adapter({"decision": ("maybe", 0.5)})
        with self.assertRaises(ProviderError):
            a.decide(_case_input(), "choice", _ctx())

    def test_unknown_score_level_is_terminal(self):
        a, _ = _adapter({
            "score": ("somewhat right", 0.5),
            "decision": ("deny", 0.5),
        })
        with self.assertRaises(ProviderError):
            a.decide(_case_input(), "score", _ctx())

    def test_unknown_abstain_label_is_terminal(self):
        a, _ = _adapter({"abstain": ("undecided", 0.5)})
        with self.assertRaises(ProviderError):
            a.decide(_case_input(), "abstain", _ctx())

    def test_missing_task_result_is_terminal(self):
        a, _ = _adapter({})
        with self.assertRaises(ProviderError):
            a.decide(_case_input(), "choice", _ctx())

    def test_missing_confidence_is_terminal(self):
        class NoConf:
            def classify_text(self, text, tasks, include_confidence=False):
                return {"decision": {"label": "deny"}}

        a = GlinerDecideAdapter(extractor=NoConf())
        with self.assertRaises(ProviderError):
            a.decide(_case_input(), "choice", _ctx())

    def test_non_object_result_is_terminal(self):
        class ListResult:
            def classify_text(self, text, tasks, include_confidence=False):
                return ["not", "a", "result", "object"]

        a = GlinerDecideAdapter(extractor=ListResult())
        with self.assertRaises(ProviderError) as cm:
            a.decide(_case_input(), "choice", _ctx())
        self.assertIn("non-object result", str(cm.exception))

    def test_empty_label_is_terminal(self):
        a, _ = _adapter({"decision": ("", 0.5)})
        with self.assertRaises(ProviderError):
            a.decide(_case_input(), "choice", _ctx())

    def test_out_of_range_confidence_is_terminal(self):
        # A drifted probability must never be clamped into a
        # measurement: 1.7, a negative, NaN and infinity all fail.
        for bad in (1.7, -0.4, float("nan"), float("inf")):
            a, _ = _adapter({"decision": ("deny", bad)})
            with self.assertRaises(ProviderError, msg=repr(bad)):
                a.decide(_case_input(), "choice", _ctx())

    def test_extractor_failure_is_terminal_provider_error(self):
        class Boom:
            def classify_text(self, text, tasks, include_confidence=False):
                raise RuntimeError("weights missing")

        a = GlinerDecideAdapter(extractor=Boom())
        with self.assertRaises(ProviderError) as cm:
            a.decide(_case_input(), "choice", _ctx())
        self.assertIsNone(cm.exception.status_code)
        self.assertIn("gliner-decide classify_text failed", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
