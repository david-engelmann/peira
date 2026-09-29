"""Tests for per-case drill-down (case_results table) and query_cases.

Run with: PYTHONPATH=python python3 -m unittest discover tests
"""

import json
import tempfile
import unittest
from pathlib import Path

from peira.artifacts import RunArtifact
from peira.env_fingerprint import collect_and_fingerprint
from peira.runs_registry import (
    scan_runs,
    query_cases,
    get_family_results,
)


def _call_record(**over):
    record = {
        "decision": "approve",
        "confidence": 0.9,
        "abstained": False,
        "refusal_reason": "",
        "usage": {
            "model": "test-model",
            "tokens_in": 100,
            "tokens_out": 20,
            "latency_ms": 350.0,
            "cost_usd": 0.001,
        },
        "seed": 7,
        "dispatch_index": 0,
        "malformed": False,
        "dispatch_limit": 1,
        "latency_ms_total": 400.0,
    }
    record.update(over)
    return record


def _result_entry(**over):
    entry = {
        "case_id": "c1",
        "family": "indirection",
        "severity": "high",
        "primitive": "choice",
        "benign": _call_record(),
        "attacked": _call_record(decision="deny", dispatch_index=1),
        "flipped": True,
        "eligible": True,
        "ineligibility_reason": "",
    }
    entry.update(over)
    return entry


def _make_artifact(adapter_name="test-adapter", results=None, **overrides):
    env, env_sha256 = collect_and_fingerprint()
    fields = {
        "adapter_name": adapter_name,
        "adapter_version": "1.0-test",
        "suite": "v1",
        "dataset_version": "1.0.3",
        "manifest_sha256": "abc123" * 10 + "abcd",
        "seed": 0,
        "max_concurrency": 8,
        "env": env,
        "env_sha256": env_sha256,
        "config": {"cache_enabled": False},
        "results": results if results is not None else [],
        "metrics": {"ranking_eligible": True, "eligibility_notes": []},
    }
    fields.update(overrides)
    return RunArtifact(**fields).seal()


class TestCaseResultsTable(unittest.TestCase):
    def _write_artifact(self, tmp_path, name, results, adapter="test-adapter"):
        art = _make_artifact(adapter_name=adapter, results=results)
        (tmp_path / name).write_text(art.to_json())
        return art

    def test_scan_populates_case_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            results = [
                _result_entry(case_id="c1", family="indirection"),
                _result_entry(
                    case_id="c2", family="pretexting",
                    flipped=False, eligible=False,
                    ineligibility_reason="benign_malformed",
                ),
            ]
            self._write_artifact(tmp_path, "run.json", results)
            n = scan_runs(tmp)
            self.assertEqual(n, 1)
            cases = query_cases(tmp)
            self.assertEqual(len(cases), 2)

    def test_query_filter_by_family(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            results = [
                _result_entry(case_id="c1", family="indirection"),
                _result_entry(case_id="c2", family="pretexting", flipped=False),
            ]
            self._write_artifact(tmp_path, "run.json", results)
            scan_runs(tmp)
            cases = query_cases(tmp, family="indirection")
            self.assertEqual(len(cases), 1)
            self.assertEqual(cases[0]["case_id"], "c1")

    def test_query_filter_by_flipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            results = [
                _result_entry(case_id="c1", flipped=True),
                _result_entry(case_id="c2", flipped=False),
            ]
            self._write_artifact(tmp_path, "run.json", results)
            scan_runs(tmp)
            flipped = query_cases(tmp, flipped=True)
            self.assertEqual(len(flipped), 1)
            self.assertEqual(flipped[0]["case_id"], "c1")
            self.assertTrue(flipped[0]["flipped"])
            not_flipped = query_cases(tmp, flipped=False)
            self.assertEqual(len(not_flipped), 1)
            self.assertFalse(not_flipped[0]["flipped"])

    def test_query_filter_by_confidence(self):
        """The dashboard's key query: flipped + high confidence."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            results = [
                _result_entry(
                    case_id="c1", family="indirection", flipped=True,
                    attacked=_call_record(decision="deny", confidence=0.95),
                ),
                _result_entry(
                    case_id="c2", family="indirection", flipped=True,
                    attacked=_call_record(decision="deny", confidence=0.3),
                ),
                _result_entry(
                    case_id="c3", family="indirection", flipped=False,
                    attacked=_call_record(confidence=0.99),
                ),
            ]
            self._write_artifact(tmp_path, "run.json", results)
            scan_runs(tmp)
            # "all cases where adapter X flipped on family Y with confidence > 0.8"
            cases = query_cases(
                tmp, adapter="test-adapter", family="indirection",
                flipped=True, min_attacked_confidence=0.8,
            )
            self.assertEqual(len(cases), 1)
            self.assertEqual(cases[0]["case_id"], "c1")
            self.assertAlmostEqual(cases[0]["attacked_confidence"], 0.95)

    def test_query_confidence_null_excluded_by_bounds(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            results = [
                _result_entry(
                    case_id="c1",
                    attacked=_call_record(decision="deny", confidence=None),
                ),
            ]
            self._write_artifact(tmp_path, "run.json", results)
            scan_runs(tmp)
            cases = query_cases(tmp, min_attacked_confidence=0.0)
            # NULL confidence cannot satisfy a bound.
            self.assertEqual(len(cases), 0)
            # But it appears without the bound.
            cases = query_cases(tmp)
            self.assertEqual(len(cases), 1)
            self.assertIsNone(cases[0]["attacked_confidence"])

    def test_flip_direction_classification(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            results = [
                # approve-to-deny: approve -> deny
                _result_entry(case_id="c1", flipped=True),
                # deny-to-approve: deny -> approve
                _result_entry(
                    case_id="c1b", flipped=True,
                    benign=_call_record(decision="deny"),
                    attacked=_call_record(decision="approve", dispatch_index=1),
                ),
                # to-abstain
                _result_entry(
                    case_id="c2", flipped=True,
                    benign=_call_record(abstained=False),
                    attacked=_call_record(abstained=True, decision="abstain"),
                ),
                # to-malformed: attacked broke
                _result_entry(
                    case_id="c3", flipped=True,
                    attacked=_call_record(malformed=True, decision="deny"),
                ),
                # not flipped
                _result_entry(case_id="c4", flipped=False),
            ]
            self._write_artifact(tmp_path, "run.json", results)
            scan_runs(tmp)
            by_type = {c["case_id"]: c["flip_direction"] for c in query_cases(tmp)}
            self.assertEqual(by_type["c1"], "approve-to-deny")
            self.assertEqual(by_type["c1b"], "deny-to-approve")
            self.assertEqual(by_type["c2"], "to-abstain")
            self.assertEqual(by_type["c3"], "to-malformed")
            self.assertEqual(by_type["c4"], "none")

    def test_flip_direction_other_fallback(self):
        # Flipped but unclassifiable: benign was malformed, attacked was
        # not. Must report "other", never a fabricated typed label.
        from peira.runs_registry import _flip_direction, FLIP_DIRECTIONS
        entry = _result_entry(
            flipped=True,
            benign=_call_record(malformed=True, decision="approve"),
            attacked=_call_record(malformed=False, decision="approve",
                                  dispatch_index=1),
        )
        self.assertEqual(_flip_direction(entry), "other")
        self.assertIn("other", FLIP_DIRECTIONS)
        # Abstention cleared (benign abstained, attacked did not).
        entry2 = _result_entry(
            flipped=True,
            benign=_call_record(abstained=True, decision="abstain"),
            attacked=_call_record(abstained=False, decision="deny",
                                  dispatch_index=1),
        )
        self.assertEqual(_flip_direction(entry2), "other")
        # Null arms do not crash.
        self.assertEqual(_flip_direction({"flipped": True, "benign": None,
                                           "attacked": None}), "other")
        self.assertEqual(_flip_direction({"flipped": False}), "none")

    def test_flip_direction_non_dict_reports_none(self):
        # A non-dict entry carries no flip evidence: "none", not "other".
        from peira.runs_registry import _flip_direction
        self.assertEqual(_flip_direction("not a dict"), "none")
        self.assertEqual(_flip_direction(None), "none")
        self.assertEqual(_flip_direction([1, 2]), "none")

    def test_case_usage_totals_rejects_bool_tokens(self):
        # bool is a subclass of int: tokens_in=True must not count as 1.
        from peira.runs_registry import _case_usage_totals
        entry = _result_entry()
        entry["benign"]["usage"] = dict(entry["benign"]["usage"],
                                        tokens_in=True, tokens_out=False)
        entry["attacked"]["usage"] = dict(entry["attacked"]["usage"],
                                          tokens_in=True, tokens_out=False)
        ti, to, _, _ = _case_usage_totals(entry)
        self.assertEqual(ti, 0)
        self.assertEqual(to, 0)

    def test_score_delta_score_primitive_only(self):
        from peira.runs_registry import _score_delta
        # Score primitive with a score delta.
        entry = _result_entry(
            primitive="score",
            benign=_call_record(score=0.8),
            attacked=_call_record(score=0.3, decision="deny", dispatch_index=1),
        )
        self.assertAlmostEqual(_score_delta(entry), -0.5)
        # Choice primitive with score fields present: still NULL.
        entry2 = _result_entry(
            primitive="choice",
            benign=_call_record(score=0.8),
            attacked=_call_record(score=0.3, decision="deny", dispatch_index=1),
        )
        self.assertIsNone(_score_delta(entry2))

    def test_case_result_columns_migration(self):
        # An index.db created with the pre-measurement-framework schema
        # (flip_type, no confidence_delta/target_hit/score_delta) must
        # migrate explicitly, not via the corruption-recovery path.
        import sqlite3
        from peira.runs_registry import _ensure_case_result_columns, _SCHEMA
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "index.db"
            conn = sqlite3.connect(db_path)
            # Simulate the old schema: flip_type instead of flip_direction,
            # missing the three new columns.
            old_schema = _SCHEMA.replace(
                "flip_direction TEXT NOT NULL,   -- M-1 taxonomy (see above)",
                "flip_type TEXT NOT NULL,",
            )
            old_schema = old_schema.replace(
                "    confidence_delta REAL,          -- attacked - benign, NULL if either missing\n",
                "",
            )
            old_schema = old_schema.replace(
                "    target_hit INTEGER,             -- 1/0/NULL (NULL = no target_decision)\n",
                "",
            )
            old_schema = old_schema.replace(
                "    score_delta REAL,               -- attacked.score - benign.score, NULL if N/A\n",
                "",
            )
            old_schema = old_schema.replace(
                "CREATE INDEX IF NOT EXISTS idx_case_flip_direction ON case_results(flip_direction);",
                "CREATE INDEX IF NOT EXISTS idx_case_flip_type ON case_results(flip_type);",
            )
            conn.executescript(old_schema)
            cols_before = {r[1] for r in conn.execute("PRAGMA table_info(case_results)")}
            self.assertIn("flip_type", cols_before)
            self.assertNotIn("flip_direction", cols_before)
            _ensure_case_result_columns(conn)
            cols_after = {r[1] for r in conn.execute("PRAGMA table_info(case_results)")}
            self.assertNotIn("flip_type", cols_after)
            self.assertIn("flip_direction", cols_after)
            self.assertIn("confidence_delta", cols_after)
            self.assertIn("target_hit", cols_after)
            self.assertIn("score_delta", cols_after)
            # Idempotent: second run is a no-op.
            _ensure_case_result_columns(conn)
            conn.close()

    def test_confidence_delta_computed(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            results = [
                _result_entry(
                    case_id="c1",
                    benign=_call_record(confidence=0.9),
                    attacked=_call_record(confidence=0.4, decision="deny",
                                          dispatch_index=1),
                ),
                # Missing confidence on one arm -> NULL delta.
                _result_entry(
                    case_id="c2",
                    benign=_call_record(confidence=None),
                    attacked=_call_record(confidence=0.4, decision="deny",
                                          dispatch_index=1),
                ),
            ]
            self._write_artifact(tmp_path, "run.json", results)
            scan_runs(tmp)
            by_id = {c["case_id"]: c for c in query_cases(tmp)}
            self.assertAlmostEqual(by_id["c1"]["confidence_delta"], -0.5)
            self.assertIsNone(by_id["c2"]["confidence_delta"])

    def test_cost_latency_tokens_summed(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            results = [
                _result_entry(
                    case_id="c1",
                    benign=_call_record(
                        usage={"model": "m", "tokens_in": 100,
                               "tokens_out": 20, "latency_ms": 1.0,
                               "cost_usd": 0.001},
                        latency_ms_total=400.0,
                    ),
                    attacked=_call_record(
                        usage={"model": "m", "tokens_in": 150,
                               "tokens_out": 30, "latency_ms": 2.0,
                               "cost_usd": 0.002},
                        latency_ms_total=500.0,
                    ),
                ),
            ]
            self._write_artifact(tmp_path, "run.json", results)
            scan_runs(tmp)
            cases = query_cases(tmp)
            self.assertEqual(len(cases), 1)
            c = cases[0]
            self.assertEqual(c["tokens_in"], 250)
            self.assertEqual(c["tokens_out"], 50)
            self.assertAlmostEqual(c["cost_usd"], 0.003)
            self.assertAlmostEqual(c["latency_ms"], 900.0)

    def test_missing_usage_contributes_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            results = [
                _result_entry(
                    case_id="c1",
                    benign=_call_record(usage=None),
                    attacked=_call_record(usage=None),
                ),
            ]
            self._write_artifact(tmp_path, "run.json", results)
            scan_runs(tmp)
            cases = query_cases(tmp)
            self.assertEqual(cases[0]["tokens_in"], 0)
            self.assertEqual(cases[0]["cost_usd"], 0.0)

    def test_filter_by_flip_direction(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            results = [
                _result_entry(case_id="c1", flipped=True),
                _result_entry(
                    case_id="c2", flipped=True,
                    attacked=_call_record(malformed=True, decision="deny"),
                ),
            ]
            self._write_artifact(tmp_path, "run.json", results)
            scan_runs(tmp)
            malformed = query_cases(tmp, flip_direction="to-malformed")
            self.assertEqual(len(malformed), 1)
            self.assertEqual(malformed[0]["case_id"], "c2")

    def test_filter_by_adapter_and_suite(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._write_artifact(
                tmp_path, "a.json",
                [_result_entry(case_id="c1")], adapter="adapter-a",
            )
            art_b = _make_artifact(
                adapter_name="adapter-b", suite="v2",
                results=[_result_entry(case_id="c2")],
            )
            (tmp_path / "b.json").write_text(art_b.to_json())
            scan_runs(tmp)
            a_cases = query_cases(tmp, adapter="adapter-a")
            self.assertEqual(len(a_cases), 1)
            self.assertEqual(a_cases[0]["adapter_name"], "adapter-a")
            v2_cases = query_cases(tmp, suite="v2")
            self.assertEqual(len(v2_cases), 1)
            self.assertEqual(v2_cases[0]["case_id"], "c2")

    def test_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            results = [_result_entry(case_id=f"c{i}") for i in range(5)]
            self._write_artifact(tmp_path, "run.json", results)
            scan_runs(tmp)
            self.assertEqual(len(query_cases(tmp, limit=2)), 2)
            self.assertEqual(len(query_cases(tmp, limit=0)), 5)

    def test_run_metadata_joined(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._write_artifact(
                tmp_path, "run.json", [_result_entry(case_id="c1")]
            )
            scan_runs(tmp)
            cases = query_cases(tmp)
            c = cases[0]
            self.assertEqual(c["adapter_name"], "test-adapter")
            self.assertEqual(c["adapter_version"], "1.0-test")
            self.assertEqual(c["suite"], "v1")
            self.assertEqual(c["dataset_version"], "1.0.3")


class TestQueryCasesEmpty(unittest.TestCase):
    def test_missing_dir_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            cases = query_cases(Path(tmp) / "nonexistent")
            self.assertEqual(cases, [])


if __name__ == "__main__":
    unittest.main()
