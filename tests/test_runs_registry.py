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
from peira.metrics import PerCaseResult
from peira.runs_registry import (
    scan_runs,
    list_runs,
    verify_runs,
    qualifies_for_leaderboard,
    query_cases,
)


class TestQueryCasesIncludeTexts(unittest.TestCase):
    """M-6: the drill-down completes case_id -> texts, decisions, confidences."""

    def _artifact_with_case(self, case_id, dataset_version):
        env, env_sha256 = collect_and_fingerprint()
        result = {
            "case_id": case_id,
            "family": "indirection",
            "severity": "high",
            "primitive": "choice",
            "benign": {
                "decision": "approve", "confidence": 0.9,
                "abstained": False, "refusal_reason": "",
                "usage": {"model": "m", "tokens_in": 10,
                          "tokens_out": 5, "latency_ms": 100.0,
                          "cost_usd": 0.001},
                "seed": 0, "dispatch_index": 0, "malformed": False,
                "dispatch_limit": 1, "latency_ms_total": 100.0,
            },
            "attacked": {
                "decision": "deny", "confidence": 0.8,
                "abstained": False, "refusal_reason": "",
                "usage": {"model": "m", "tokens_in": 10,
                          "tokens_out": 5, "latency_ms": 100.0,
                          "cost_usd": 0.001},
                "seed": 0, "dispatch_index": 1, "malformed": False,
                "dispatch_limit": 1, "latency_ms_total": 100.0,
            },
            "flipped": True,
            "eligible": True,
            "ineligibility_reason": "",
        }
        artifact = RunArtifact(
            adapter_name="text-adapter",
            adapter_version="1.0-test",
            suite="v1",
            dataset_version=dataset_version,
            manifest_sha256="abc123" * 10 + "abcd",
            seed=0,
            max_concurrency=8,
            env=env,
            env_sha256=env_sha256,
            config={"cache_enabled": False},
            results=[result],
            metrics={"ranking_eligible": True, "eligibility_notes": []},
        )
        return artifact.seal().to_json()

    def test_include_texts_enriches_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "run.json").write_text(
                self._artifact_with_case("v1-spo-001", "1.2.1")
            )
            scan_runs(tmp)
            rows = query_cases(
                runs_dir=tmp, adapter="text-adapter", include_texts=True
            )
            self.assertEqual(len(rows), 1)
            row = rows[0]
            # The M-6 linkage: both texts, both decisions, confidences.
            self.assertIsInstance(row["benign_text"], str)
            self.assertTrue(len(row["benign_text"]) > 0)
            self.assertIsInstance(row["attacked_text"], str)
            self.assertTrue(len(row["attacked_text"]) > 0)
            self.assertEqual(row["benign_decision"], "approve")
            self.assertEqual(row["attacked_decision"], "deny")
            self.assertAlmostEqual(row["benign_confidence"], 0.9)
            self.assertAlmostEqual(row["attacked_confidence"], 0.8)

    def test_texts_opt_in_default_off(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "run.json").write_text(
                self._artifact_with_case("v1-spo-001", "1.2.1")
            )
            scan_runs(tmp)
            rows = query_cases(runs_dir=tmp, adapter="text-adapter")
            self.assertEqual(len(rows), 1)
            self.assertNotIn("benign_text", rows[0])
            self.assertNotIn("attacked_text", rows[0])

    def test_unknown_case_texts_are_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "run.json").write_text(
                self._artifact_with_case("not-a-real-case", "1.2.1")
            )
            scan_runs(tmp)
            rows = query_cases(
                runs_dir=tmp, adapter="text-adapter", include_texts=True
            )
            self.assertEqual(len(rows), 1)
            self.assertIsNone(rows[0]["benign_text"])
            self.assertIsNone(rows[0]["attacked_text"])


def _make_artifact(adapter_name="test-adapter", **overrides):
    """Create a minimal valid artifact for testing."""
    from peira.artifacts import results_to_dicts
    from peira.metrics import CallRecord
    env, env_sha256 = collect_and_fingerprint()
    # 200 eligible results across 10 families (20 each): genuinely
    # ranking-eligible, so the recomputation in
    # qualifies_for_leaderboard agrees with the sealed flag.
    per_case = []
    for fi in range(10):
        for i in range(20):
            def _rec(decision):
                return CallRecord(
                    decision=decision, confidence=0.9, abstained=False,
                    refusal_reason="", usage=None, seed=0,
                    dispatch_index=0, malformed=False,
                    latency_ms_total=1.0,
                )
            per_case.append(PerCaseResult(
                case_id=f"c{fi}-{i}", family=f"fam{fi}",
                severity="high", primitive="choice",
                benign=_rec("approve"),
                attacked=_rec("deny" if i % 2 == 0 else "approve"),
                flipped=(i % 2 == 0), eligible=True,
                ineligibility_reason="",
            ))
    results = results_to_dicts(per_case)
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
        "config": {"cache_enabled": False},
        "results": results,
        "metrics": {
            "ranking_eligible": True,
            "eligibility_notes": [],
            "required_families": [f"fam{fi}" for fi in range(10)],
        },
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


class TestCacheTerminationIndexing(unittest.TestCase):
    """The registry index carries the leaderboard segmentation
    dimensions: cache_enabled and termination."""

    def _write(self, tmp, name, **over):
        art = _make_artifact(adapter_name=name, **over)
        (Path(tmp) / f"{name}.json").write_text(art.to_json())
        return art

    def _rows(self, tmp, **filters):
        scan_runs(tmp)
        return {r["adapter_name"]: r for r in list_runs(tmp, **filters)}

    def test_index_carries_cache_and_termination(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "a", config={"cache_enabled": False},
                        termination="complete")
            self._write(tmp, "b", config={"cache_enabled": True},
                        termination="complete")
            self._write(tmp, "c", config={"cache_enabled": False},
                        termination="budget")
            rows = self._rows(tmp)
            self.assertEqual(rows["a"]["cache_enabled"], 0)
            self.assertEqual(rows["a"]["termination"], "complete")
            self.assertEqual(rows["b"]["cache_enabled"], 1)
            self.assertEqual(rows["b"]["termination"], "complete")
            self.assertEqual(rows["c"]["cache_enabled"], 0)
            self.assertEqual(rows["c"]["termination"], "budget")

    def test_undeclared_cache_indexes_null(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "a", config={})
            rows = self._rows(tmp)
            self.assertIsNone(rows["a"]["cache_enabled"])

    def test_cache_filter_segments(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "a", config={"cache_enabled": False})
            self._write(tmp, "b", config={"cache_enabled": True})
            on = self._rows(tmp, cache_enabled=True)
            off = self._rows(tmp, cache_enabled=False)
            self.assertEqual(set(on), {"b"})
            self.assertEqual(set(off), {"a"})

    def test_termination_filter_segments(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "a", termination="complete")
            self._write(tmp, "b", termination="budget")
            rows = self._rows(tmp, termination="budget")
            self.assertEqual(set(rows), {"b"})

    def test_old_schema_migrated(self):
        import sqlite3
        from peira.runs_registry import INDEX_DB_NAME
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "a", config={"cache_enabled": True},
                        termination="budget")
            # Simulate a pre-change index.db (no new columns).
            db = Path(tmp) / INDEX_DB_NAME
            conn = sqlite3.connect(str(db))
            conn.execute("""CREATE TABLE runs (
                path TEXT PRIMARY KEY, mtime REAL NOT NULL, run_id TEXT,
                created_utc TEXT, adapter_name TEXT, adapter_version TEXT,
                suite TEXT, dataset_version TEXT, manifest_sha256 TEXT,
                env_sha256 TEXT, seed INTEGER, max_concurrency INTEGER,
                n_results INTEGER, lock_valid INTEGER)""")
            conn.commit()
            conn.close()
            rows = self._rows(tmp)
            self.assertEqual(rows["a"]["cache_enabled"], 1)
            self.assertEqual(rows["a"]["termination"], "budget")

    def test_legacy_index_with_rows_forces_rescan(self):
        # Regression test for CodeRabbit #179 discussion r4129770883:
        # a legacy index.db WITH ROWS but missing the new columns must
        # trigger a rescan to populate them. ALTER TABLE alone leaves
        # existing rows NULL, and filtered list_runs calls would silently
        # return no rows.
        import sqlite3
        from peira.runs_registry import INDEX_DB_NAME, _index_path
        with tempfile.TemporaryDirectory() as tmp:
            art = self._write(tmp, "a", config={"cache_enabled": True},
                              termination="budget")
            # Build the legacy index manually: old schema WITH a row.
            # The row's path/mtime must match the artifact so the
            # snapshot matches and the rescan would otherwise be skipped.
            db = Path(tmp) / INDEX_DB_NAME
            art_path = str((Path(tmp) / "a.json").resolve())
            mtime = (Path(tmp) / "a.json").stat().st_mtime
            conn = sqlite3.connect(str(db))
            conn.execute("""CREATE TABLE runs (
                path TEXT PRIMARY KEY, mtime REAL NOT NULL, run_id TEXT,
                created_utc TEXT, adapter_name TEXT, adapter_version TEXT,
                suite TEXT, dataset_version TEXT, manifest_sha256 TEXT,
                env_sha256 TEXT, seed INTEGER, max_concurrency INTEGER,
                n_results INTEGER, lock_valid INTEGER)""")
            conn.execute(
                "INSERT INTO runs (path, mtime, adapter_name) VALUES (?, ?, ?)",
                (art_path, mtime, "a"),
            )
            conn.commit()
            conn.close()
            # list_runs must rescan (not just ALTER TABLE) so the filter
            # matches the row instead of silently returning nothing.
            rows = list_runs(tmp, cache_enabled=True)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["adapter_name"], "a")
            self.assertEqual(rows[0]["cache_enabled"], 1)
            self.assertEqual(rows[0]["termination"], "budget")
            rows = list_runs(tmp, termination="budget")
            self.assertEqual(len(rows), 1)


if __name__ == "__main__":
    unittest.main()
