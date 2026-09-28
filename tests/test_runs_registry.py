"""Tests for the run registry (Layer 5a)."""

import json
import sqlite3
import tempfile
import threading
import time
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
        "metrics": {"ranking_eligible": True, "eligibility_notes": []},
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


class TestIndexFreshness(unittest.TestCase):
    """Regression tests for the retrospective review of PR #105."""

    def test_deleted_artifact_disappears_from_list(self):
        # P1-1: deletions bump no mtime, so a pure "newer than index"
        # check leaves phantom rows forever.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "run1.json").write_text(
                _make_artifact(adapter_name="a1").to_json()
            )
            (tmp_path / "run2.json").write_text(
                _make_artifact(adapter_name="a2").to_json()
            )
            self.assertEqual(len(list_runs(tmp)), 2)
            (tmp_path / "run2.json").unlink()
            runs = list_runs(tmp)
            self.assertEqual(len(runs), 1)
            self.assertEqual(runs[0]["adapter_name"], "a1")

    def test_modified_artifact_triggers_rescan(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "run1.json").write_text(
                _make_artifact(adapter_name="a1").to_json()
            )
            self.assertEqual(len(list_runs(tmp)), 1)
            # Rewrite with a different adapter name and force a newer mtime
            # (some filesystems have coarse mtime granularity).
            (tmp_path / "run1.json").write_text(
                _make_artifact(adapter_name="a2").to_json()
            )
            p = tmp_path / "run1.json"
            newer = p.stat().st_mtime + 5
            import os
            os.utime(p, (newer, newer))
            runs = list_runs(tmp)
            self.assertEqual(len(runs), 1)
            self.assertEqual(runs[0]["adapter_name"], "a2")

    def test_corrupt_index_db_rebuilds(self):
        # P1-2: the module docstring promises deleting index.db is always
        # safe; a truncated / non-database file must be treated the same.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "run1.json").write_text(
                _make_artifact(adapter_name="a1").to_json()
            )
            self.assertEqual(scan_runs(tmp), 1)
            (tmp_path / "index.db").write_bytes(b"\x00" * 64)  # not a db
            runs = list_runs(tmp)
            self.assertEqual(len(runs), 1)
            self.assertEqual(runs[0]["adapter_name"], "a1")

    def test_corrupt_index_db_rebuilds_on_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "run1.json").write_text(
                _make_artifact(adapter_name="a1").to_json()
            )
            (tmp_path / "index.db").write_bytes(b"garbage, not sqlite")
            self.assertEqual(scan_runs(tmp), 1)
            self.assertEqual(len(list_runs(tmp)), 1)

    def test_concurrent_writer_waits_instead_of_crashing(self):
        # P2: a second writer must wait out a held write lock (timeout=30)
        # instead of raising "database is locked" (default timeout=5).
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "run1.json").write_text(
                _make_artifact(adapter_name="a1").to_json()
            )
            self.assertEqual(scan_runs(tmp), 1)
            db_path = tmp_path / "index.db"
            holder = sqlite3.connect(
                str(db_path), timeout=30, check_same_thread=False
            )
            holder.execute("BEGIN IMMEDIATE")  # take the write lock

            def release():
                time.sleep(7)  # longer than the old 5s default timeout
                holder.rollback()
                holder.close()

            t = threading.Thread(target=release)
            t.start()
            try:
                n = scan_runs(tmp)  # must wait, not raise
            finally:
                t.join()
            self.assertEqual(n, 1)


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

    def test_rejects_ranking_ineligible(self):
        art = _make_artifact(
            metrics={
                "ranking_eligible": False,
                "eligibility_notes": ["benign accuracy below 0.5"],
            }
        )
        qualifies, reason = qualifies_for_leaderboard(art)
        self.assertFalse(qualifies)
        self.assertIn("ranking-ineligible", reason)
        self.assertIn("benign accuracy below 0.5", reason)

    def test_rejects_missing_eligibility(self):
        art = _make_artifact(metrics={})
        qualifies, reason = qualifies_for_leaderboard(art)
        self.assertFalse(qualifies)
        self.assertIn("ranking-ineligible", reason)


if __name__ == "__main__":
    unittest.main()
