"""Unit tests for scripts/s1_apply.py (run with: python -m pytest tests)."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import s1_apply  # noqa: E402


def _case(cid, severity="high"):
    return {
        "case_id": cid, "family": "test_family", "primitive": "choice",
        "severity": severity,
        "benign": {"input": {"prompt": "p", "options": ["a", "b"]},
                   "expected_decision": "a"},
        "attacked": {"input": {"prompt": "p!", "options": ["a", "b"]},
                     "target_decision": "b"},
        "notes": "",
    }


def _grading(cid, **over):
    g = {
        "case_id": cid, "grader_id": "adj",
        "severity_tier": "high", "severity_bullet": "b", "severity_notes": "n",
        "gold_verdict": "ok", "gold_derivation": "d",
        "factual_issues": [], "attack_integrity": "ok", "format_issues": [],
    }
    g.update(over)
    return g


def _env(root: Path, verdicts, changelog_entries=None):
    cases = root / "cases"
    cases.mkdir(parents=True)
    with open(cases / "test_family.jsonl", "w", encoding="utf-8") as f:
        for cid in ("v1-tst-001", "v1-tst-002", "v1-tst-003"):
            f.write(json.dumps(_case(cid)) + "\n")
    cl = root / "CHANGELOG.json"
    cl.write_text(json.dumps({
        "$schema_id": "https://peiratrial.dev/schemas/dataset-changelog-1.json",
        "format_version": "1",
        "dataset": "peira-v1",
        "dataset_version": "1.0.3",
        "entries": changelog_entries or [],
    }), encoding="utf-8")
    ver = root / "adjudicated.json"
    ver.write_text(json.dumps([
        {"case_id": cid, "verdict": v} for cid, v in verdicts
    ]), encoding="utf-8")
    plan = root / "s1" / "corrections.json"
    return cases, cl, ver, plan


def _args(root, cases, cl, ver, plan, extra=()):
    return ["--verdicts", str(ver), "--cases", str(cases),
            "--changelog", str(cl), "--plan-out", str(plan), *extra]


class ApplyTest(unittest.TestCase):
    def _defect_verdicts(self):
        return [
            # class 2: grader says critical, current high -> annotate
            ("v1-tst-001", _grading("v1-tst-001", severity_tier="critical",
                                    severity_bullet="Moves money.")),
            # class 1: unfounded golds -> retire+add
            ("v1-tst-002", _grading("v1-tst-002", gold_verdict="unfounded",
                                    gold_derivation="no facts in prompt")),
            # confirmed KEEP -> skipped
            ("v1-tst-003", _grading("v1-tst-003")),
        ]

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cases, cl, ver, plan = _env(root, self._defect_verdicts())
            before = {p: Path(p).read_bytes() for p in
                      [cl, ver] + list(cases.glob("*.jsonl"))}
            self.assertEqual(
                s1_apply.main(_args(root, cases, cl, ver, plan,
                                    extra=("--dry-run",))), 0)
            self.assertFalse(plan.exists())
            self.assertFalse((root / "s1" / "annotations").exists())
            for p, content in before.items():
                self.assertEqual(Path(p).read_bytes(), content,
                                 f"{p} modified by dry-run")

    def test_full_run_plan_and_changelog(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cases, cl, ver, plan = _env(root, self._defect_verdicts())
            self.assertEqual(s1_apply.main(_args(root, cases, cl, ver, plan)), 0)

            saved = json.loads(plan.read_text())
            self.assertEqual(saved["n_confirmed_defects"], 2)
            self.assertEqual(saved["n_confirmed_keep"], 1)
            self.assertEqual(saved["pre_version"], "1.0.3")
            self.assertEqual(saved["version_bump"], "minor")
            self.assertEqual(saved["new_version"], "1.1.0")

            by_id = {c["case_id"]: c for c in saved["corrections"]}
            # class 2 -> annotate
            self.assertEqual(by_id["v1-tst-001"]["action"], "annotate")
            self.assertEqual(by_id["v1-tst-001"]["annotation"]["severity_tier"],
                             "critical")
            # class 1 -> retire+add with minted ID (live max 3 -> 004)
            self.assertEqual(by_id["v1-tst-002"]["action"], "retire+add")
            self.assertEqual(by_id["v1-tst-002"]["new_id"], "v1-tst-004")

            # CHANGELOG: retire + add + annotate entries, version bumped
            doc = json.loads(cl.read_text())
            types = [e["type"] for e in doc["entries"]]
            self.assertEqual(types, ["retire", "add", "annotate"])
            self.assertEqual(doc["dataset_version"], "1.1.0")
            retire = doc["entries"][0]
            self.assertEqual(retire["case_ids"], ["v1-tst-002"])
            self.assertEqual(retire["replacements"],
                             {"v1-tst-002": "v1-tst-004"})
            for e in doc["entries"]:
                self.assertEqual(e["dataset_version"], "1.1.0")
                self.assertEqual(e["origin"], "s1_apply")

            # annotation sidecar written
            ann = root / "s1" / "annotations" / "v1-tst-001.json"
            self.assertTrue(ann.is_file())
            self.assertEqual(json.loads(ann.read_text())["severity_tier"],
                             "critical")

    def test_patch_bump_for_fix_only(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            verdicts = [("v1-tst-001",
                         _grading("v1-tst-001", format_issues=["recieve"]))]
            cases, cl, ver, plan = _env(root, verdicts)
            s1_apply.main(_args(root, cases, cl, ver, plan))
            saved = json.loads(plan.read_text())
            self.assertEqual(saved["version_bump"], "patch")
            self.assertEqual(saved["new_version"], "1.0.4")
            doc = json.loads(cl.read_text())
            self.assertEqual([e["type"] for e in doc["entries"]], ["fix"])

    def test_minting_skips_retired_numbers(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # v1-tst-009 retired earlier (not live); live max is 3.
            old_retire = {
                "date": "2026-09-20", "type": "retire",
                "dataset_version": "1.0.3", "description": "old",
                "case_ids": ["v1-tst-009"], "rationale": "r",
                "replacements": {"v1-tst-009": "v1-tst-010"},
            }
            verdicts = [("v1-tst-002",
                         _grading("v1-tst-002", gold_verdict="unfounded",
                                  gold_derivation="x"))]
            cases, cl, ver, plan = _env(root, verdicts, [old_retire])
            s1_apply.main(_args(root, cases, cl, ver, plan))
            saved = json.loads(plan.read_text())
            # max(3 live, 9 retired, 10 replacement) + 1 = 011
            self.assertEqual(saved["corrections"][0]["new_id"], "v1-tst-011")

    def test_rerun_guard_requires_force(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cases, cl, ver, plan = _env(root, self._defect_verdicts())
            args = _args(root, cases, cl, ver, plan)
            self.assertEqual(s1_apply.main(args), 0)
            # second run without --force: entries-exist guard fires
            with self.assertRaises(SystemExit):
                s1_apply.main(args)
            # forced re-run: the retire was recorded, so the verdict for the
            # now-retired case is refused instead of re-processed
            with self.assertRaises(SystemExit):
                s1_apply.main([*args, "--force"])

    def test_unknown_case_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cases, cl, ver, plan = _env(
                root, [("v1-nope-999", _grading("v1-nope-999"))])
            with self.assertRaises(SystemExit):
                s1_apply.main(_args(root, cases, cl, ver, plan))

    def test_no_defects_no_changelog_touch(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cases, cl, ver, plan = _env(
                root, [("v1-tst-001", _grading("v1-tst-001"))])
            before = cl.read_bytes()
            s1_apply.main(_args(root, cases, cl, ver, plan))
            saved = json.loads(plan.read_text())
            self.assertEqual(saved["n_confirmed_defects"], 0)
            self.assertIsNone(saved["version_bump"])
            self.assertEqual(cl.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
