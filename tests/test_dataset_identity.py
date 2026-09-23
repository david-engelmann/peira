"""Unit tests for byte-proof dataset identity (H4).

`peira run` verifies the suite manifest before scoring and seals the
manifest's SHA-256 into the analysis lock, so an artifact proves the
exact dataset bytes scored — not just the version label. Tampering fails
closed: nothing is scored.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from peira.artifacts import RunArtifact
from peira.cli import _suite_dataset_identity
from peira.dataset import build_manifest, sha256_file, write_manifest
from peira.runner import validate_partial

REPO_ROOT = Path(__file__).resolve().parents[1]
TRIAL_DIR = REPO_ROOT / "dataset" / "trial"


def _case(case_id, family="state_poisoning"):
    return {
        "case_id": case_id,
        "family": family,
        "primitive": "choice",
        "severity": "high",
        "benign": {"input": {"prompt": "p", "options": ["a", "b"]},
                   "expected_decision": "a"},
        "attacked": {"input": {"prompt": "p!", "options": ["a", "b"]},
                     "target_decision": "b"},
        "notes": "",
    }


class TestSuiteDatasetIdentity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _write_dataset(self, version="9.9.9"):
        (self.dir / "cases.jsonl").write_text(
            "\n".join(json.dumps(_case(f"c{i}")) for i in range(3)) + "\n")
        write_manifest(self.dir, build_manifest(self.dir, version))
        return self.dir

    def test_valid_manifest_returns_version_and_digest(self):
        self._write_dataset(version="9.9.9")
        version, digest = _suite_dataset_identity(self.dir)
        self.assertEqual(version, "9.9.9")
        self.assertEqual(digest, sha256_file(self.dir / "manifest.json"))
        self.assertEqual(len(digest), 64)

    def test_tampered_dataset_fails_closed(self):
        self._write_dataset()
        # Tamper with a case file after the manifest was built.
        path = self.dir / "cases.jsonl"
        path.write_text(path.read_text().replace('"c0"', '"cX"'))
        with self.assertRaises(ValueError) as ctx:
            _suite_dataset_identity(self.dir)
        self.assertIn("verification failed", str(ctx.exception))

    def test_missing_manifest_is_explicitly_unbound(self):
        (self.dir / "cases.jsonl").write_text(
            json.dumps(_case("c1")) + "\n")
        version, digest = _suite_dataset_identity(self.dir)
        self.assertEqual(version, "0.1.0-demo")
        self.assertEqual(digest, "")

    def test_corrupt_manifest_is_hard_error(self):
        # An existing-but-unreadable manifest must fail closed, not
        # silently downgrade the suite to an unbound run.
        self._write_dataset()
        (self.dir / "manifest.json").write_text("NOT JSON{{{")
        with self.assertRaises(ValueError) as ctx:
            _suite_dataset_identity(self.dir)
        self.assertIn("unreadable manifest", str(ctx.exception))

    def test_wrong_shape_manifest_is_hard_error(self):
        self._write_dataset()
        (self.dir / "manifest.json").write_text(json.dumps({"nope": []}))
        with self.assertRaises(ValueError) as ctx:
            _suite_dataset_identity(self.dir)
        self.assertIn("unreadable manifest", str(ctx.exception))

    def test_lock_covers_manifest_sha256(self):
        a = RunArtifact(dataset_version="1.0.0", manifest_sha256="a" * 64)
        b = RunArtifact(dataset_version="1.0.0", manifest_sha256="b" * 64)
        a.seal()
        b.seal()
        self.assertNotEqual(a.analysis_lock, b.analysis_lock)
        self.assertTrue(a.verify())
        self.assertTrue(b.verify())

    def test_resume_refuses_changed_snapshot(self):
        from peira.adapters.mock import MockAdapter
        from peira.runner import load_cases
        cases = load_cases(TRIAL_DIR)
        partial = RunArtifact(
            adapter_name=MockAdapter().name,
            adapter_version=getattr(MockAdapter(), "version", ""),
            suite="trial", dataset_version="1.0.0",
            manifest_sha256="a" * 64,
            results=[],
        )
        partial.seal()
        with self.assertRaises(ValueError) as ctx:
            validate_partial(partial, MockAdapter(), cases,
                             "trial", "1.0.0", "b" * 64)
        self.assertIn("different dataset snapshot", str(ctx.exception))

    def test_run_records_manifest_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(__import__("os").environ)
            env["PYTHONPATH"] = str(REPO_ROOT / "python")
            r = subprocess.run(
                [sys.executable, "-m", "peira.cli", "run",
                 "--adapter", "mock", "--suite", "trial",
                 "--out", tmp],
                capture_output=True, text=True, env=env, cwd=REPO_ROOT,
            )
            self.assertIn(r.returncode, (0, 3), r.stderr)
            artifact = RunArtifact.from_json(
                Path(tmp, "mock-trial.json").read_text())
            self.assertTrue(artifact.verify())
            self.assertEqual(
                artifact.manifest_sha256,
                sha256_file(TRIAL_DIR / "manifest.json"))
            # The digest is sealed: flipping it breaks the lock.
            artifact.manifest_sha256 = "0" * 64
            self.assertFalse(artifact.verify())


if __name__ == "__main__":
    unittest.main()
