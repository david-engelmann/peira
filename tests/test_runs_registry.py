"""Tests for the run registry (Layer 5a)."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from peira.artifacts import RunArtifact
from peira.env_fingerprint import collect_and_fingerprint
from peira.runs_registry import (
    scan_runs,
    list_runs,
    verify_runs,
    qualifies_for_leaderboard,
)


def _make_artifact(adapter_name="test-adapter", **overrides):
    """Create a minimal valid artifact for testing."""
    env, env_sha256 = collect_and_fingerprint()
    fields = {
        "adapter_name": adapter_name,
        "adapter_version": "1.0-test",
        "suite": "v1",
        "dataset_version": "1.0.3",
        "manifest_sha256": "abc123" * 10 + "abcd",  # 64 chars
        "seed": 0,
        "max_concurrency": 8,
        "env": env,
        "env_sha256": env_sha256,
        "results": [],
        "metrics": {},
    }
    fields.update(overrides)
    artifact = RunArtifact(**fields)
    return artifact.seal()


class TestScanRuns(unittest.TestCase):
    def test_scan_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            n = scan_runs(tmp)
            self.assertEqual(n, 0)
            # Index DB should exist
            self.assertTrue((Path(tmp) / "index.db").exists())

    def test_scan_indexes_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            # Write two artifacts
            for i in range(2):
                art = _make_artifact(adapter_name=f"adapter-{i}")
                (tmp_path / f"run-{i}.json").write_text(art.to_json())
            n = scan_runs(tmp)
            self.assertEqual(n, 2)

    def test_scan_skips_invalid_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "good.json").write_text(
                _make_artifact().to_json()
            )
            (tmp_path / "bad.json").write_text("not valid json{")
            (tmp_path / "not-artifact.json").write_text(
                json.dumps({"foo": "bar"})
            )
            n = scan_runs(tmp)
            self.assertEqual(n, 1)

    def test_scan_records_lock_validity(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            art = _make_artifact()
            (tmp_path / "good.json").write_text(art.to_json())
            # Corrupt the lock
            data = json.loads(art.to_json())
            data["analysis_lock"] = "0" * 64
            (tmp_path / "bad-lock.json").write_text(json.dumps(data))
            scan_runs(tmp)
            runs = list_runs(tmp)
            by_id = {r["run_id"]: r for r in runs}
            self.assertEqual(by_id["good"]["lock_valid"], 1)
            self.assertEqual(by_id["bad-lock"]["lock_valid"], 0)


class TestListRuns(unittest.TestCase):
    def test_list_with_filters(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "a1.json").write_text(
                _make_artifact(adapter_name="shieldstral", suite="v1").to_json()
            )
            (tmp_path / "a2.json").write_text(
                _make_artifact(adapter_name="shieldstral", suite="v2").to_json()
            )
            (tmp_path / "b1.json").write_text(
                _make_artifact(adapter_name="other", suite="v1").to_json()
            )
            scan_runs(tmp)
            # No filter
            self.assertEqual(len(list_runs(tmp)), 3)
            # Adapter filter
            self.assertEqual(len(list_runs(tmp, adapter="shieldstral")), 2)
            # Suite filter
            self.assertEqual(len(list_runs(tmp, suite="v1")), 2)
            # Combined
            runs = list_runs(tmp, adapter="shieldstral", suite="v1")
            self.assertEqual(len(runs), 1)
            self.assertEqual(runs[0]["run_id"], "a1")

    def test_list_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(list_runs(tmp), [])

    def test_list_includes_env_sha(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            art = _make_artifact()
            (tmp_path / "run.json").write_text(art.to_json())
            scan_runs(tmp)
            runs = list_runs(tmp)
            self.assertEqual(len(runs), 1)
            self.assertEqual(runs[0]["env_sha256"], art.env_sha256)


class TestVerifyRuns(unittest.TestCase):
    def test_verify_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            p = tmp_path / "run.json"
            p.write_text(_make_artifact().to_json())
            results = verify_runs([p])
            self.assertEqual(len(results), 1)
            path, valid, msg = results[0]
            self.assertTrue(valid)

    def test_verify_invalid_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            art = _make_artifact()
            data = json.loads(art.to_json())
            data["analysis_lock"] = "0" * 64
            p = tmp_path / "run.json"
            p.write_text(json.dumps(data))
            results = verify_runs([p])
            path, valid, msg = results[0]
            self.assertFalse(valid)
            self.assertIn("mismatch", msg)

    def test_verify_missing_file(self):
        results = verify_runs(["/nonexistent/path.json"])
        path, valid, msg = results[0]
        self.assertFalse(valid)


class TestQualifiesForLeaderboard(unittest.TestCase):
    def test_qualifies(self):
        art = _make_artifact()
        qualifies, reason = qualifies_for_leaderboard(art)
        self.assertTrue(qualifies)

    def test_rejects_invalid_lock(self):
        art = _make_artifact()
        art.analysis_lock = "0" * 64
        qualifies, reason = qualifies_for_leaderboard(art)
        self.assertFalse(qualifies)
        self.assertIn("lock", reason)

    def test_rejects_missing_manifest(self):
        art = _make_artifact(manifest_sha256="")
        qualifies, reason = qualifies_for_leaderboard(art)
        self.assertFalse(qualifies)
        self.assertIn("manifest", reason)

    def test_rejects_unpinned_adapter(self):
        art = _make_artifact(adapter_version="")
        qualifies, reason = qualifies_for_leaderboard(art)
        self.assertFalse(qualifies)
        self.assertIn("pinned", reason)


if __name__ == "__main__":
    unittest.main()
