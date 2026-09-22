"""Unit tests for runner resume validation and progress (run with: python -m unittest discover tests)."""

import unittest
from pathlib import Path
from types import SimpleNamespace

from peira.adapters.mock import MockAdapter
from peira.artifacts import RunArtifact, results_to_dicts
from peira.metrics import PerCaseResult
from peira.runner import load_cases, run_suite, validate_partial

REPO_ROOT = Path(__file__).resolve().parents[1]


def _r(case_id="c1", **kw):
    base = dict(case_id=case_id, family="f", primitive="choice",
                benign_correct=True, attacked_flipped=False,
                attacked_targeted=False, malformed=False, confidence=0.9)
    base.update(kw)
    return PerCaseResult(**base)


def _partial(results, adapter=None, suite="trial-demo",
             dataset_version="0.1.0-demo"):
    adapter = adapter or MockAdapter()
    return RunArtifact(
        adapter_name=adapter.name,
        adapter_version=getattr(adapter, "version", ""),
        suite=suite,
        dataset_version=dataset_version,
        results=results_to_dicts(results),
    ).seal()


def _cases(*ids):
    return [SimpleNamespace(case_id=i) for i in ids]


class TestValidatePartial(unittest.TestCase):
    def test_ok(self):
        p = _partial([_r("c1"), _r("c2")])
        done, prior = validate_partial(p, MockAdapter(), _cases("c1", "c2", "c3"),
                                       "trial-demo", "0.1.0-demo")
        self.assertEqual(done, {"c1", "c2"})
        self.assertEqual([r.case_id for r in prior], ["c1", "c2"])

    def test_wrong_adapter(self):
        p = _partial([_r("c1")])
        other = SimpleNamespace(name="other", version="9.9")
        with self.assertRaises(ValueError):
            validate_partial(p, other, _cases("c1"), "trial-demo", "0.1.0-demo")

    def test_wrong_adapter_version(self):
        p = _partial([_r("c1")])
        other = SimpleNamespace(name=MockAdapter().name, version="9.9")
        with self.assertRaises(ValueError):
            validate_partial(p, other, _cases("c1"), "trial-demo", "0.1.0-demo")

    def test_wrong_suite(self):
        p = _partial([_r("c1")], suite="trial")
        with self.assertRaises(ValueError):
            validate_partial(p, MockAdapter(), _cases("c1"),
                             "trial-demo", "0.1.0-demo")

    def test_wrong_dataset_version(self):
        p = _partial([_r("c1")], dataset_version="9.9")
        with self.assertRaises(ValueError):
            validate_partial(p, MockAdapter(), _cases("c1"),
                             "trial-demo", "0.1.0-demo")

    def test_tampered_lock(self):
        p = _partial([_r("c1")])
        p.results[0]["attacked_flipped"] = True  # modify after sealing
        with self.assertRaises(ValueError):
            validate_partial(p, MockAdapter(), _cases("c1"),
                             "trial-demo", "0.1.0-demo")

    def test_unknown_case_id(self):
        p = _partial([_r("zzz")])
        with self.assertRaises(ValueError):
            validate_partial(p, MockAdapter(), _cases("c1"),
                             "trial-demo", "0.1.0-demo")

    def test_duplicate_case_id(self):
        p = _partial([_r("c1"), _r("c1")])
        with self.assertRaises(ValueError):
            validate_partial(p, MockAdapter(), _cases("c1"),
                             "trial-demo", "0.1.0-demo")


class TestResumeProgress(unittest.TestCase):
    def test_progress_counts_completed_not_index(self):
        cases = load_cases(REPO_ROOT / "dataset" / "trial-demo")
        done_ids = {cases[0].case_id}
        seen = []
        run_suite(MockAdapter(), cases, "trial-demo", "0.1.0-demo",
                  progress=lambda d, t: seen.append((d, t)),
                  already_done=done_ids)
        total = len(cases)
        # One case skipped: progress must run 1..total-1, not jump the index.
        self.assertEqual([d for d, _ in seen], list(range(1, total)))
        self.assertTrue(all(t == total for _, t in seen))


if __name__ == "__main__":
    unittest.main()
