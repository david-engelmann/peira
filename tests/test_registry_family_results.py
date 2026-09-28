"""Tests for the family_results table in peira/runs_registry.py."""

import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from peira import runs_registry


def _artifact(per_family: dict) -> dict:
    return {
        "peira_version": "0.1.0",
        "dataset_version": "v1",
        "adapter_name": "mock",
        "adapter_version": "0.1.0",
        "suite": "trial",
        "created_utc": "2026-09-27T00:00:00Z",
        "manifest_sha256": "abc",
        "env_sha256": "def",
        "seed": 0,
        "max_concurrency": 1,
        "results": [],
        "metrics": {"per_family": per_family},
    }


PER_FAMILY = {
    "indirection": {
        "n": 10,
        "n_eligible": 8,
        "asr": 0.5,
        "asr_ci95": [0.215, 0.785],
        "refusal_rate": 0.0,
        "refusal_rate_ci95": [0.0, 0.28],
    },
    # Withheld: all rates None. Must land as NULL, never 0.0.
    "state_poisoning": {
        "n": 10,
        "n_eligible": 2,
        "asr": None,
        "asr_ci95": None,
        "refusal_rate": None,
        "refusal_rate_ci95": None,
    },
}


class TestFamilyResults(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "run1.json").write_text(
            json.dumps(_artifact(PER_FAMILY)), encoding="utf-8"
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _db(self) -> sqlite3.Connection:
        return sqlite3.connect(self.tmp / runs_registry.INDEX_DB_NAME)

    def test_scan_populates_family_results(self):
        n = runs_registry.scan_runs(self.tmp)
        self.assertEqual(n, 1)
        conn = self._db()
        try:
            rows = conn.execute(
                "SELECT family, n, n_eligible, asr, asr_lo, asr_hi, "
                "refusal_rate FROM family_results ORDER BY family"
            ).fetchall()
        finally:
            conn.close()
        self.assertEqual(len(rows), 2)
        by_fam = {r[0]: r for r in rows}
        ind = by_fam["indirection"]
        self.assertEqual(ind[1:], (10, 8, 0.5, 0.215, 0.785, 0.0))
        # Withheld rates are NULL, never 0.0.
        sp = by_fam["state_poisoning"]
        self.assertEqual(sp[1:3], (10, 2))
        self.assertEqual(sp[3:], (None, None, None, None))

    def test_primary_key_and_family_index(self):
        runs_registry.scan_runs(self.tmp)
        conn = self._db()
        try:
            pk = conn.execute(
                "SELECT sql FROM sqlite_master WHERE name='family_results'"
            ).fetchone()[0]
            idx = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND tbl_name='family_results'"
            ).fetchall()
        finally:
            conn.close()
        self.assertIn("PRIMARY KEY (run_path, family)", pk)
        index_names = {r[0] for r in idx}
        self.assertIn("idx_family_results_family", index_names)

    def test_rescan_is_idempotent(self):
        runs_registry.scan_runs(self.tmp)
        runs_registry.scan_runs(self.tmp)
        conn = self._db()
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM family_results"
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(count, 2)

    def test_get_family_results(self):
        runs_registry.scan_runs(self.tmp)
        rows = runs_registry.get_family_results(self.tmp)
        self.assertEqual(len(rows), 2)
        by_fam = {r["family"]: r for r in rows}
        self.assertEqual(by_fam["indirection"]["adapter_name"], "mock")
        self.assertEqual(by_fam["indirection"]["asr"], 0.5)
        self.assertEqual(by_fam["indirection"]["asr_lo"], 0.215)
        self.assertEqual(by_fam["indirection"]["asr_hi"], 0.785)
        self.assertIsNone(by_fam["state_poisoning"]["asr"])
        # Adapter filter narrows; unknown adapter returns nothing.
        self.assertEqual(
            len(runs_registry.get_family_results(self.tmp, adapter="mock")), 2
        )
        self.assertEqual(
            runs_registry.get_family_results(self.tmp, adapter="nope"), []
        )

    def test_artifact_without_metrics(self):
        (self.tmp / "run2.json").write_text(
            json.dumps(_artifact({})), encoding="utf-8"
        )
        runs_registry.scan_runs(self.tmp)
        rows = runs_registry.get_family_results(self.tmp)
        self.assertEqual(len(rows), 2)

    def test_malformed_per_family_does_not_abort_scan(self):
        bad = {
            "indirection": {
                "n": "ten",  # non-numeric count: row skipped
                "n_eligible": 8,
                "asr": 0.5,
                "asr_ci95": [0.215, 0.785],
                "refusal_rate": 0.0,
            },
            "state_poisoning": {
                "n": "10",  # numeric string: coerces
                "n_eligible": 2,
                "asr": "garbage",  # garbage rate: NULL, not a crash
                "asr_ci95": ["lo", "hi"],
                "refusal_rate": None,
            },
        }
        art = _artifact(bad)
        art["adapter_name"] = "bad"
        (self.tmp / "run2.json").write_text(
            json.dumps(art), encoding="utf-8"
        )
        n = runs_registry.scan_runs(self.tmp)
        self.assertEqual(n, 2)
        # run1 intact: 2 rows.
        rows = runs_registry.get_family_results(self.tmp, adapter="mock")
        self.assertEqual(len(rows), 2)
        # run2: the garbage-count row is skipped, the rest survives.
        rows = runs_registry.get_family_results(self.tmp, adapter="bad")
        by_fam = {r["family"]: r for r in rows}
        self.assertNotIn("indirection", by_fam)
        sp = by_fam["state_poisoning"]
        self.assertEqual(sp["n"], 10)
        self.assertIsNone(sp["asr"])
        self.assertIsNone(sp["asr_lo"])
        self.assertIsNone(sp["asr_hi"])

    def test_non_dict_per_family_ignored(self):
        for bad_pf in ("oops", ["x"], 42):
            art = _artifact({})
            art["metrics"]["per_family"] = bad_pf
            (self.tmp / "run3.json").write_text(
                json.dumps(art), encoding="utf-8"
            )
            n = runs_registry.scan_runs(self.tmp)
            self.assertEqual(n, 2)
            (self.tmp / "run3.json").unlink()

    def test_coerce_rate_rejects_non_finite(self):
        for bad in (
            float("inf"),
            float("-inf"),
            float("nan"),
            "inf",
            "-inf",
            "nan",
        ):
            self.assertIsNone(runs_registry._coerce_rate(bad), bad)

    def test_coerce_rate_rejects_out_of_range(self):
        for bad in (2.0, -0.5, 1.0001, -0.0001, "2", "-1"):
            self.assertIsNone(runs_registry._coerce_rate(bad), bad)

    def test_coerce_rate_accepts_valid_rates(self):
        self.assertEqual(runs_registry._coerce_rate(0), 0.0)
        self.assertEqual(runs_registry._coerce_rate(1), 1.0)
        self.assertEqual(runs_registry._coerce_rate(0.5), 0.5)
        self.assertEqual(runs_registry._coerce_rate("0.75"), 0.75)
        self.assertIsNone(runs_registry._coerce_rate(None))
        self.assertIsNone(runs_registry._coerce_rate(True))
        self.assertIsNone(runs_registry._coerce_rate("garbage"))

    def test_coerce_int_rejects_negatives(self):
        for bad in (-1, -3, -2.0, "-2"):
            self.assertIsNone(runs_registry._coerce_int(bad), bad)

    def test_coerce_int_accepts_valid_counts(self):
        self.assertEqual(runs_registry._coerce_int(0), 0)
        self.assertEqual(runs_registry._coerce_int(5), 5)
        self.assertEqual(runs_registry._coerce_int("10"), 10)
        self.assertEqual(runs_registry._coerce_int(2.0), 2)
        self.assertIsNone(runs_registry._coerce_int(False))
        self.assertIsNone(runs_registry._coerce_int(None))
        self.assertIsNone(runs_registry._coerce_int("4x"))

    def test_garbage_rates_become_null_end_to_end(self):
        # Red-team reproduction: inf/nan/out-of-range rates must land as
        # NULL in the registry, never as inf/nan/2.0.
        bad = {
            "state_poisoning": {
                "n": 10,
                "n_eligible": 8,
                "asr": float("inf"),
                "asr_ci95": [float("nan"), 2.0],
                "refusal_rate": -0.5,
            },
        }
        art = _artifact(bad)
        art["adapter_name"] = "garbage"
        (self.tmp / "run2.json").write_text(
            json.dumps(art), encoding="utf-8"
        )
        runs_registry.scan_runs(self.tmp)
        rows = runs_registry.get_family_results(self.tmp, adapter="garbage")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertIsNone(row["asr"])
        self.assertIsNone(row["asr_lo"])
        self.assertIsNone(row["asr_hi"])
        self.assertIsNone(row["refusal_rate"])

    def test_bad_counts_skip_row_end_to_end(self):
        # missing/None/False/negative counts skip the row, exactly like a
        # non-numeric count does; only the well-formed family is indexed.
        bad = {
            "fam_missing": {"n_eligible": 5, "asr": 0.5},
            "fam_none": {"n": None, "n_eligible": 5, "asr": 0.5},
            "fam_false": {"n": False, "n_eligible": 5, "asr": 0.5},
            "fam_negative": {"n": -3, "n_eligible": 5, "asr": 0.5},
            "fam_garbage": {"n": "garbage", "n_eligible": 5, "asr": 0.5},
            "fam_ok": {"n": 10, "n_eligible": 8, "asr": 0.5},
        }
        art = _artifact(bad)
        art["adapter_name"] = "badcounts"
        (self.tmp / "run2.json").write_text(
            json.dumps(art), encoding="utf-8"
        )
        runs_registry.scan_runs(self.tmp)
        rows = runs_registry.get_family_results(self.tmp, adapter="badcounts")
        by_fam = {r["family"]: r for r in rows}
        self.assertEqual(set(by_fam), {"fam_ok"})
        self.assertEqual(by_fam["fam_ok"]["n"], 10)
        self.assertEqual(by_fam["fam_ok"]["n_eligible"], 8)


if __name__ == "__main__":
    unittest.main()
