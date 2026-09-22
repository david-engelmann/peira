"""Unit tests for dataset manifest tooling (run with: python -m unittest discover tests)."""

import json
import tempfile
import unittest
from pathlib import Path

from peira.dataset import (
    MANIFEST_NAME,
    build_manifest,
    read_manifest,
    verify_manifest,
    write_manifest,
)


def _case(case_id, family="state_poisoning", severity="high",
          primitive="choice"):
    return {
        "case_id": case_id,
        "family": family,
        "primitive": primitive,
        "severity": severity,
        "benign": {"input": {"prompt": "p", "options": ["a", "b"]},
                   "expected_decision": "a"},
        "attacked": {"input": {"prompt": "p!", "options": ["a", "b"]},
                     "target_decision": "b"},
        "notes": "",
    }


class TestDatasetManifest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _write_cases(self, name="cases.jsonl", cases=None):
        cases = cases if cases is not None else [
            _case("c1"), _case("c2", family="indirection")]
        path = self.dir / name
        path.write_text("\n".join(json.dumps(c) for c in cases) + "\n")
        return path

    def test_build_manifest_counts(self):
        self._write_cases()
        (self.dir / "CANARY.txt").write_text("peira-canary:test\n")
        m = build_manifest(self.dir, "1.0.0")
        self.assertEqual(m["dataset"], "peira-v1")
        self.assertEqual(m["dataset_version"], "1.0.0")
        entry = m["files"]["cases.jsonl"]
        self.assertEqual(entry["kind"], "cases")
        self.assertEqual(entry["n_cases"], 2)
        self.assertEqual(entry["n_by_family"],
                         {"indirection": 1, "state_poisoning": 1})
        self.assertEqual(entry["n_by_severity"], {"high": 2})
        self.assertEqual(entry["n_by_primitive"], {"choice": 2})
        self.assertEqual(len(entry["sha256"]), 64)
        self.assertEqual(m["files"]["CANARY.txt"]["kind"], "artifact")
        self.assertNotIn(MANIFEST_NAME, m["files"])

    def test_write_and_verify_ok(self):
        self._write_cases()
        out = write_manifest(self.dir, build_manifest(self.dir, "1.0.0"))
        self.assertEqual(out.name, MANIFEST_NAME)
        self.assertEqual(verify_manifest(self.dir), [])
        # manifest is deterministic apart from the timestamp
        m1 = json.loads(out.read_text())
        m2 = build_manifest(self.dir, "1.0.0")
        self.assertEqual(m1["files"], m2["files"])

    def test_verify_detects_tamper(self):
        path = self._write_cases()
        write_manifest(self.dir, build_manifest(self.dir, "1.0.0"))
        path.write_text(path.read_text().replace('"p!"', '"p?"'))
        errors = verify_manifest(self.dir)
        self.assertTrue(any("sha256 mismatch" in e for e in errors),
                        errors)

    def test_verify_detects_missing_file(self):
        path = self._write_cases()
        write_manifest(self.dir, build_manifest(self.dir, "1.0.0"))
        path.unlink()
        errors = verify_manifest(self.dir)
        self.assertTrue(any("missing on disk" in e for e in errors), errors)

    def test_build_rejects_invalid_case(self):
        bad = _case("c1")
        del bad["severity"]
        self._write_cases(cases=[bad])
        with self.assertRaises(ValueError) as ctx:
            build_manifest(self.dir, "1.0.0")
        self.assertIn("cases.jsonl:1", str(ctx.exception))

    def test_build_rejects_bad_json(self):
        path = self._write_cases()
        path.write_text(path.read_text() + "{not json}\n")
        with self.assertRaises(ValueError):
            build_manifest(self.dir, "1.0.0")

    def test_verify_missing_manifest(self):
        self._write_cases()
        with self.assertRaises(FileNotFoundError):
            read_manifest(self.dir)

    def test_build_missing_dir(self):
        with self.assertRaises(FileNotFoundError):
            build_manifest(self.dir / "nope", "1.0.0")

    def test_empty_dir_builds(self):
        m = build_manifest(self.dir, "0.0.0")
        self.assertEqual(m["files"], {})


if __name__ == "__main__":
    unittest.main()
