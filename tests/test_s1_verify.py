"""Unit tests for scripts/s1_verify.py (run with: python -m pytest tests).

These drive the whole post-adjudication pipeline on fixtures:
s1_apply -> human edits -> manifest rebuild -> s1_verify.
"""

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import s1_apply  # noqa: E402
import s1_verify  # noqa: E402


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


def _write_cases(cases_dir: Path, cases):
    with open(cases_dir / "test_family.jsonl", "w", encoding="utf-8") as f:
        for c in cases:
            f.write(json.dumps(c) + "\n")


class VerifyTest(unittest.TestCase):
    def make_happy(self, root: Path):
        """Build a full post-sweep fixture; returns (manifest, plan) paths."""
        cases = root / "cases"
        cases.mkdir(parents=True)
        _write_cases(cases, [_case(f"v1-tst-00{i}") for i in (1, 2, 3)])

        cl = root / "CHANGELOG.json"
        cl.write_text(json.dumps({
            "$schema_id": "https://peiratrial.dev/schemas/"
                          "dataset-changelog-1.json",
            "format_version": "1",
            "dataset": "peira-v1",
            "dataset_version": "1.0.3",
            "entries": [],
        }), encoding="utf-8")

        ver = root / "adjudicated.json"
        ver.write_text(json.dumps([
            {"case_id": "v1-tst-001",
             "verdict": _grading("v1-tst-001", severity_tier="critical",
                                severity_bullet="moves money")},
            {"case_id": "v1-tst-002",
             "verdict": _grading("v1-tst-002", gold_verdict="unfounded",
                                gold_derivation="no facts in prompt")},
            {"case_id": "v1-tst-003", "verdict": _grading("v1-tst-003")},
        ]), encoding="utf-8")

        plan = root / "s1" / "corrections.json"
        rc = s1_apply.main(["--verdicts", str(ver), "--cases", str(cases),
                            "--changelog", str(cl), "--plan-out", str(plan)])
        self.assertEqual(rc, 0)

        # --- human work queue ---
        # v1-tst-001: annotate (sidecar written by s1_apply; case untouched)
        # v1-tst-002: retire+add -> remove old, author replacement
        _write_cases(cases, [_case("v1-tst-001"), _case("v1-tst-003"),
                             _case("v1-tst-004")])

        # --- rebuild the manifest ---
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                               / "python"))
        from peira.dataset import build_manifest
        manifest = build_manifest(cases, "1.1.0")
        man_path = cases / "manifest.json"
        man_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return man_path, plan, cl, ver

    def run_verify(self, root, man_path, plan, ver):
        return s1_verify.main([
            "--manifest", str(man_path),
            "--changelog", str(root / "CHANGELOG.json"),
            "--corrections", str(plan),
            "--verdicts", str(ver),
            "--annotations", str(root / "s1" / "annotations"),
        ])

    def assert_fails(self, fn):
        # main() returns an exit code (it only raises SystemExit via the
        # __main__ shim); a planted violation must yield non-zero.
        self.assertNotEqual(fn(), 0)

    def test_happy_path_passes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            man_path, plan, cl, ver = self.make_happy(root)
            self.assertEqual(self.run_verify(root, man_path, plan, ver), 0)

    def test_manifest_hash_mismatch_caught(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            man_path, plan, cl, ver = self.make_happy(root)
            fam = root / "cases" / "test_family.jsonl"
            fam.write_text(fam.read_text(encoding="utf-8")
                           + json.dumps(_case("v1-tst-005")) + "\n",
                           encoding="utf-8")
            self.assert_fails(lambda: self.run_verify(root, man_path, plan, ver))

    def test_duplicate_ids_caught(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            man_path, plan, cl, ver = self.make_happy(root)
            fam = root / "cases" / "test_family.jsonl"
            fam.write_text(fam.read_text() + json.dumps(
                _case("v1-tst-001")) + "\n")
            self.assert_fails(lambda: self.run_verify(root, man_path, plan, ver))

    def test_retired_id_resurrected_caught(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            man_path, plan, cl, ver = self.make_happy(root)
            fam = root / "cases" / "test_family.jsonl"
            # v1-tst-002 was retired: adding it back must fail.
            fam.write_text(fam.read_text() + json.dumps(
                _case("v1-tst-002")) + "\n")
            self.assert_fails(lambda: self.run_verify(root, man_path, plan, ver))

    def test_missing_replacement_caught(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            man_path, plan, cl, ver = self.make_happy(root)
            _write_cases(root / "cases",
                         [_case("v1-tst-001"), _case("v1-tst-003")])
            self.assert_fails(lambda: self.run_verify(root, man_path, plan, ver))

    def test_dropped_defect_caught(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            man_path, plan, cl, ver = self.make_happy(root)
            doc = json.loads(cl.read_text())
            doc["entries"] = [e for e in doc["entries"]
                              if e["type"] != "retire"]
            cl.write_text(json.dumps(doc), encoding="utf-8")
            # v1-tst-002 is a DEFECT in the ledger but has no changelog entry.
            self.assert_fails(lambda: self.run_verify(root, man_path, plan, ver))

    def test_malformed_changelog_entry_caught(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            man_path, plan, cl, ver = self.make_happy(root)
            doc = json.loads(cl.read_text())
            del doc["entries"][0]["rationale"]
            cl.write_text(json.dumps(doc), encoding="utf-8")
            self.assert_fails(lambda: self.run_verify(root, man_path, plan, ver))

    def test_wrong_version_bump_caught(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            man_path, plan, cl, ver = self.make_happy(root)
            saved = json.loads(plan.read_text())
            saved["version_bump"] = "major"
            saved["new_version"] = "2.0.0"
            plan.write_text(json.dumps(saved), encoding="utf-8")
            self.assert_fails(lambda: self.run_verify(root, man_path, plan, ver))

    def test_tampered_seal_digest_caught(self):
        # A seal entry whose manifest_sha256 does not match the recomputed
        # manifest digest must fail verification.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            man_path, plan, cl, ver = self.make_happy(root)
            doc = json.loads(cl.read_text())
            doc["entries"].append({
                "date": "2026-09-28", "type": "seal",
                "dataset_version": "1.1.0",
                "description": "post-sweep seal",
                "manifest_sha256": "0" * 64,
                "case_count": 3, "families": ["test_family"],
            })
            cl.write_text(json.dumps(doc), encoding="utf-8")
            self.assert_fails(
                lambda: self.run_verify(root, man_path, plan, ver))

    def test_schema_invalid_touched_case_caught(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            man_path, plan, cl, ver = self.make_happy(root)
            fam = root / "cases" / "test_family.jsonl"
            lines = []
            for line in fam.read_text().splitlines():
                c = json.loads(line)
                if c["case_id"] == "v1-tst-004":
                    c["severity"] = "extreme"  # invalid tier
                lines.append(json.dumps(c))
            fam.write_text("\n".join(lines) + "\n", encoding="utf-8")
            # Re-point the manifest hash at the tampered file so the failure
            # is isolated to the schema check, not the hash check.
            man = json.loads(man_path.read_text())
            man["files"]["test_family.jsonl"]["sha256"] = hashlib.sha256(
                fam.read_bytes()).hexdigest()
            man_path.write_text(json.dumps(man), encoding="utf-8")
            self.assert_fails(lambda: self.run_verify(root, man_path, plan, ver))

    def test_missing_annotation_sidecar_caught(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            man_path, plan, cl, ver = self.make_happy(root)
            ann = root / "s1" / "annotations" / "v1-tst-001.json"
            ann.unlink()
            self.assert_fails(lambda: self.run_verify(root, man_path, plan, ver))

    def test_dropped_defect_draft_missing_caught(self):
        # The ledger says v1-tst-002 is a DEFECT but the correction draft
        # was deleted from the plan: verify must fail.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            man_path, plan, cl, ver = self.make_happy(root)
            saved = json.loads(plan.read_text())
            saved["corrections"] = [c for c in saved["corrections"]
                                    if c["case_id"] != "v1-tst-002"]
            plan.write_text(json.dumps(saved), encoding="utf-8")
            self.assert_fails(
                lambda: self.run_verify(root, man_path, plan, ver))

    def test_missing_ledger_caught(self):
        # A plan without adjudicated_dispositions cannot prove no DEFECT
        # was dropped: verify must fail loudly, not pass silently.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            man_path, plan, cl, ver = self.make_happy(root)
            saved = json.loads(plan.read_text())
            del saved["adjudicated_dispositions"]
            plan.write_text(json.dumps(saved), encoding="utf-8")
            self.assert_fails(
                lambda: self.run_verify(root, man_path, plan, ver))

    def test_ledger_verdicts_mismatch_caught(self):
        # Ledger missing an adjudicated input ID: cross-check fails.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            man_path, plan, cl, ver = self.make_happy(root)
            saved = json.loads(plan.read_text())
            saved["adjudicated_dispositions"] = [
                d for d in saved["adjudicated_dispositions"]
                if d["case_id"] != "v1-tst-003"]
            plan.write_text(json.dumps(saved), encoding="utf-8")
            self.assert_fails(
                lambda: self.run_verify(root, man_path, plan, ver))

    def test_no_corrections_plan_passes(self):
        # A sweep with no corrections yet: verify only checks manifest and
        # changelog schema; nothing to cross-check.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cases = root / "cases"
            cases.mkdir(parents=True)
            _write_cases(cases, [_case("v1-tst-001")])
            cl = root / "CHANGELOG.json"
            cl.write_text(json.dumps({
                "$schema_id": "https://peiratrial.dev/schemas/"
                              "dataset-changelog-1.json",
                "format_version": "1", "dataset": "peira-v1",
                "dataset_version": "1.0.3", "entries": [],
            }), encoding="utf-8")
            sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                                   / "python"))
            from peira.dataset import build_manifest
            man_path = cases / "manifest.json"
            man_path.write_text(json.dumps(build_manifest(cases, "1.0.3")),
                                encoding="utf-8")
            rc = s1_verify.main([
                "--manifest", str(man_path),
                "--changelog", str(cl),
                "--annotations", str(root / "nope" / "annotations"),
            ])
            self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
