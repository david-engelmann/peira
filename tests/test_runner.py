"""Unit tests for runner resume validation and progress (run with: python -m unittest discover tests)."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from peira.adapters.mock import MockAdapter
from peira.artifacts import RunArtifact, results_to_dicts
from peira.metrics import CallRecord, PerCaseResult
from peira.runner import load_cases, run_suite, validate_partial

REPO_ROOT = Path(__file__).resolve().parents[1]


def _rec(**kw):
    base = dict(decision="approve", confidence=0.9, abstained=False,
                refusal_reason="", usage=None, seed=0, dispatch_index=0,
                malformed=False)
    base.update(kw)
    return CallRecord(**base)


def _r(case_id="c1", **kw):
    benign_kw = {k[7:]: v for k, v in kw.items() if k.startswith("benign_")}
    attacked_kw = {k[9:]: v for k, v in kw.items() if k.startswith("attacked_")}
    rest = {k: v for k, v in kw.items()
            if not (k.startswith("benign_") or k.startswith("attacked_"))}
    base = dict(case_id=case_id, family="f", severity="high",
                primitive="choice",
                benign=_rec(**benign_kw), attacked=_rec(**attacked_kw),
                flipped=False, eligible=True, ineligibility_reason="")
    base.update(rest)
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
        p.results[0]["flipped"] = True  # modify after sealing
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

    def test_scalar_result_entry_is_value_error(self):
        # A hand-edited partial with a scalar entry used to die in
        # AttributeError on r.get; it is now a clear ValueError.
        p = _partial([_r("c1")])
        p.results.append("bogus")
        p.seal()  # re-seal so the lock passes and the entry is reached
        with self.assertRaisesRegex(
            ValueError, "partial run has malformed result entry at index 1"
        ):
            validate_partial(p, MockAdapter(), _cases("c1"),
                             "trial-demo", "0.1.0-demo")

    def test_wrong_shaped_result_dict_is_value_error(self):
        # A dict entry that PerCaseResult rejects is hostile input too:
        # TypeError becomes ValueError with the entry's position.
        p = _partial([_r("c1")])
        p.results.append({"case_id": "c2", "bogus_key": 1})
        p.seal()
        with self.assertRaisesRegex(
            ValueError, "partial run has malformed result entry at index 1"
        ):
            validate_partial(p, MockAdapter(), _cases("c1", "c2"),
                             "trial-demo", "0.1.0-demo")

    def test_seed_mismatch_rejected(self):
        # Resume with a different seed would silently re-score nothing
        # (dispatch indices and per-call seeds are seed-derived): the
        # partial is rejected with a clear message instead.
        p = _partial([_r("c1")])
        p.seed = 7
        p.seal()
        with self.assertRaisesRegex(ValueError, "recorded with seed 7"):
            validate_partial(p, MockAdapter(), _cases("c1", "c2"),
                             "trial-demo", "0.1.0-demo", seed=8)
        # Same seed resumes fine.
        done, prior = validate_partial(
            p, MockAdapter(), _cases("c1", "c2"),
            "trial-demo", "0.1.0-demo", seed=7)
        self.assertEqual(done, {"c1"})


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

    def test_dispatch_indices_are_suite_positioned_across_resume(self):
        # Dispatch indices derive from the case's suite position
        # (benign = 2i, attacked = 2i+1), not run order: a resumed run
        # must record the same indices as an uninterrupted one.
        from peira.runner import run_case

        cases = load_cases(REPO_ROOT / "dataset" / "trial-demo")
        half = len(cases) // 2
        adapter = MockAdapter()
        prior = [run_case(adapter, cases[i], seed=3, dispatch_base=2 * i)
                 for i in range(half)]
        resumed = run_suite(
            adapter, cases, "trial-demo", "0.1.0-demo",
            already_done={cases[i].case_id for i in range(half)},
            prior_results=prior,
            seed=3,
        )
        self.assertEqual(len(resumed.results), len(cases))
        for i, entry in enumerate(resumed.results):
            self.assertEqual(entry["benign"]["dispatch_index"], 2 * i,
                             f"case {i} benign index")
            self.assertEqual(entry["attacked"]["dispatch_index"], 2 * i + 1,
                             f"case {i} attacked index")
            self.assertEqual(entry["benign"]["seed"], 3)
            self.assertEqual(entry["attacked"]["seed"], 3)


class TestLoadCases(unittest.TestCase):
    def _write_case_file(self, d, name, case_id="c1"):
        case = {
            "case_id": case_id, "family": "indirection",
            "primitive": "choice", "severity": "low",
            "benign": {"input": {}, "expected_decision": "a"},
            "attacked": {"input": {}},
        }
        (d / name).write_text(json.dumps(case) + "\n", encoding="utf-8")

    def test_broken_symlink_is_skipped_not_crashed(self):
        # A broken x.jsonl symlink is not a case file (is_file() is
        # False through the dead link): the runner skips it instead of
        # crashing in open().
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            self._write_case_file(d, "cases.jsonl")
            try:
                os.symlink(d / "missing-target.jsonl", d / "x.jsonl")
            except OSError as e:
                self.skipTest(f"symlinks unavailable: {e}")
            cases = load_cases(d)
            self.assertEqual([c.case_id for c in cases], ["c1"])

    def test_dot_jsonl_file_is_scored(self):
        # A file named exactly ".jsonl" is a case file (name ends with
        # .jsonl): the runner must see exactly the files the manifest
        # build and the sweep see.
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            self._write_case_file(d, "cases.jsonl", "c1")
            self._write_case_file(d, ".jsonl", "c2")
            cases = load_cases(d)
            self.assertEqual(sorted(c.case_id for c in cases), ["c1", "c2"])


if __name__ == "__main__":
    unittest.main()
