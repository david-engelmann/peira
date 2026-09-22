"""Unit tests for the human review queue (run with: python -m unittest discover tests)."""

import json
import tempfile
import unittest
from pathlib import Path

from peira.review import (mark_reviewed, pending_reviews, review_coverage,
                          load_review_states)


def _case(case_id, severity="high", attacked_prompt="p!"):
    return {
        "case_id": case_id,
        "family": "state_poisoning",
        "primitive": "choice",
        "severity": severity,
        "benign": {"input": {"prompt": "p", "options": ["a", "b"]},
                   "expected_decision": "a"},
        "attacked": {"input": {"prompt": attacked_prompt,
                               "options": ["a", "b"]},
                     "target_decision": "b"},
        "notes": "",
    }


class TestReviewQueue(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _write_cases(self, cases):
        path = self.dir / "cases.jsonl"
        path.write_text("\n".join(json.dumps(c) for c in cases) + "\n")

    def test_critical_cases_need_review(self):
        self._write_cases([_case("c1", severity="critical"),
                           _case("c2", severity="medium")])
        pending = pending_reviews(self.dir)
        self.assertEqual([p["case_id"] for p in pending], ["c1"])
        self.assertIn("critical severity", pending[0]["reasons"][0])

    def test_pii_warning_needs_review(self):
        self._write_cases([_case("c1", severity="medium",
                                 attacked_prompt="mail bob@example.com")])
        pending = pending_reviews(self.dir)
        self.assertEqual(len(pending), 1)
        self.assertTrue(any("email address" in r for r in pending[0]["reasons"]))

    def test_approve_clears_pending(self):
        self._write_cases([_case("c1", severity="critical")])
        mark_reviewed(self.dir, "c1", "approved", reviewer="dg",
                      notes="looks good")
        self.assertEqual(pending_reviews(self.dir), [])
        states = load_review_states(self.dir)
        self.assertEqual(states["c1"]["status"], "approved")
        self.assertEqual(states["c1"]["reviewer"], "dg")

    def test_reject_does_not_count_as_reviewed(self):
        self._write_cases([_case("c1", severity="critical")])
        mark_reviewed(self.dir, "c1", "rejected", notes="rework needed")
        self.assertEqual(len(pending_reviews(self.dir)), 1)

    def test_unknown_case_id_raises(self):
        self._write_cases([_case("c1")])
        with self.assertRaises(KeyError):
            mark_reviewed(self.dir, "nope", "approved")

    def test_bad_status_raises(self):
        self._write_cases([_case("c1")])
        with self.assertRaises(ValueError):
            mark_reviewed(self.dir, "c1", "maybe")

    def test_coverage(self):
        self._write_cases([_case("c1", severity="critical"),
                           _case("c2", severity="critical"),
                           _case("c3", severity="low")])
        cov = review_coverage(self.dir)
        self.assertEqual(cov["n_critical"], 2)
        self.assertEqual(cov["critical_coverage"], 0.0)
        mark_reviewed(self.dir, "c1", "approved")
        cov = review_coverage(self.dir)
        self.assertEqual(cov["n_critical_approved"], 1)
        self.assertEqual(cov["critical_coverage"], 0.5)

    def test_empty_review_file_means_nothing_reviewed(self):
        self._write_cases([_case("c1", severity="critical")])
        self.assertEqual(load_review_states(self.dir), {})

    def test_corrupt_review_file_errors(self):
        self._write_cases([_case("c1", severity="critical")])
        (self.dir / "review.json").write_text("{bad json")
        with self.assertRaises(ValueError):
            pending_reviews(self.dir)


if __name__ == "__main__":
    unittest.main()
