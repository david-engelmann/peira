"""Tests for the dashboard data layer (python/peira/dashboard.py).

Run with: PYTHONPATH=python python3 -m unittest discover tests
"""

import json
import tempfile
import unittest
from pathlib import Path

from peira.artifacts import RunArtifact
from peira.dashboard import (
    run_to_dashboard,
    leaderboard,
    comparison_to_dashboard,
    _confidence_histogram,
    _family_breakdown,
)
from peira.env_fingerprint import collect_and_fingerprint
from peira.runs_registry import scan_runs


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


def _metrics(**over):
    m = {
        "n_cases": 2,
        "n_eligible": 2,
        "asr_conditional": 0.5,
        "asr_ci95": [0.2, 0.8],
        "asr_unconditional": 0.5,
        "asr_unconditional_ci95": [0.2, 0.8],
        "benign_accuracy": 1.0,
        "benign_accuracy_ci95": [0.9, 1.0],
        "malformed_rate": 0.0,
        "refusal_rate": 0.0,
        "abstention_rate": 0.0,
        "abstention_rate_delta": 0.0,
        "latency_ms": {
            "attacked": {"p50": 400.0, "p95": 800.0, "n": 2},
        },
        "cost": {"total_cost_usd": 0.004, "n_priced": 4, "sufficient": True},
        "ranking_eligible": True,
        "eligibility_notes": [],
        "per_family": {
            "indirection": {
                "n": 2, "n_eligible": 2, "asr": 0.5,
                "asr_ci95": [0.2, 0.8], "refusal_rate": 0.0,
                "refusal_rate_ci95": [0.0, 0.3],
            },
        },
        "calibration": {
            "confidence_coverage": {"benign": 1.0, "attacked": 1.0},
            "attacked": {"ece": 0.05, "sufficient": True},
        },
    }
    m.update(over)
    return m


def _make_artifact(adapter_name="test-adapter", **overrides):
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
        "results": [
            _result_entry(case_id="c1"),
            _result_entry(case_id="c2", flipped=False,
                          attacked=_call_record(decision="approve")),
        ],
        "metrics": _metrics(),
        "termination": "complete",
        "cases_completed": 2,
        "cases_planned": 2,
        "spent_usd": 0.004,
    }
    fields.update(overrides)
    return RunArtifact(**fields).seal()


class TestConfidenceHistogram(unittest.TestCase):
    def test_basic(self):
        h = _confidence_histogram([0.1, 0.2, 0.9, 0.95])
        self.assertEqual(h["bins"], 10)
        self.assertEqual(h["n"], 4)
        self.assertEqual(h["n_missing"], 0)
        self.assertEqual(sum(h["counts"]), 4)
        # 0.1, 0.2 in bins 1, 2; 0.9, 0.95 in bin 9.
        self.assertEqual(h["counts"][1], 1)
        self.assertEqual(h["counts"][2], 1)
        self.assertEqual(h["counts"][9], 2)

    def test_none_excluded(self):
        h = _confidence_histogram([0.5, None, None])
        self.assertEqual(h["n"], 1)
        self.assertEqual(h["n_missing"], 2)

    def test_one_point_zero_in_last_bin(self):
        h = _confidence_histogram([1.0])
        self.assertEqual(h["counts"][9], 1)

    def test_empty(self):
        h = _confidence_histogram([])
        self.assertEqual(h["n"], 0)
        self.assertEqual(sum(h["counts"]), 0)


class TestFamilyBreakdown(unittest.TestCase):
    def test_aggregates(self):
        results = [
            _result_entry(case_id="c1", family="indirection"),
            _result_entry(case_id="c2", family="indirection", flipped=False,
                          attacked=_call_record(decision="approve")),
            _result_entry(case_id="c3", family="pretexting"),
        ]
        bd = _family_breakdown(results)
        self.assertEqual(set(bd), {"indirection", "pretexting"})
        ind = bd["indirection"]
        self.assertEqual(ind["n"], 2)
        self.assertEqual(ind["n_eligible"], 2)
        self.assertEqual(ind["n_flipped"], 1)
        self.assertAlmostEqual(ind["flip_rate_raw"], 0.5)
        # Cost: 2 cases x 2 arms x 0.001 = 0.004 for indirection.
        self.assertAlmostEqual(ind["cost_usd"], 0.004)
        self.assertEqual(ind["n_costed_calls"], 4)
        # Confidence histogram has 2 attacked confidences (0.9 each).
        self.assertEqual(
            ind["confidence_histogram_attacked"]["n"], 2
        )
        self.assertEqual(ind["flip_direction"], {"approve-to-deny": 1})

    def test_flip_direction(self):
        results = [
            _result_entry(case_id="c1", flipped=True),
            _result_entry(
                case_id="c2", flipped=True,
                attacked=_call_record(malformed=True, decision="deny"),
            ),
        ]
        bd = _family_breakdown(results)
        ind = bd["indirection"]
        self.assertEqual(
            ind["flip_direction"], {"approve-to-deny": 1, "to-malformed": 1}
        )


class TestRunToDashboard(unittest.TestCase):
    def test_sections_present(self):
        payload = run_to_dashboard(_make_artifact())
        self.assertIn("run", payload)
        self.assertIn("headline", payload)
        self.assertIn("families", payload)
        self.assertIn("severities", payload)
        self.assertIn("calibration", payload)

    def test_run_metadata(self):
        payload = run_to_dashboard(_make_artifact())
        run = payload["run"]
        self.assertEqual(run["adapter_name"], "test-adapter")
        self.assertEqual(run["adapter_version"], "1.0-test")
        self.assertTrue(run["lock_valid"])
        self.assertTrue(run["ranking_eligible"])

    def test_headline_passthrough(self):
        payload = run_to_dashboard(_make_artifact())
        h = payload["headline"]
        self.assertEqual(h["asr_conditional"], 0.5)
        self.assertEqual(h["asr_ci95"], [0.2, 0.8])
        self.assertEqual(h["n_cases"], 2)

    def test_families_merge_metrics_and_dashboard(self):
        payload = run_to_dashboard(_make_artifact())
        fam = payload["families"]["indirection"]
        # From metrics layer.
        self.assertEqual(fam["asr"], 0.5)
        self.assertEqual(fam["asr_ci95"], [0.2, 0.8])
        # From dashboard aggregation.
        self.assertIn("cost_usd", fam)
        self.assertIn("confidence_histogram_attacked", fam)
        self.assertIn("flip_direction", fam)

    def test_json_serializable(self):
        payload = run_to_dashboard(_make_artifact())
        json.dumps(payload)  # must not raise

    def test_flip_anatomy_present(self):
        payload = run_to_dashboard(_make_artifact())
        self.assertIn("flip_anatomy", payload)
        anatomy = payload["flip_anatomy"]["indirection"]
        # M-6: every cell carries n, no pre-rounded percentages alone.
        self.assertIn("n_eligible", anatomy)
        self.assertIn("direction_counts", anatomy)
        counts = anatomy["direction_counts"]
        # One flipped (approve->deny) + one not flipped in the fixture.
        self.assertEqual(counts["approve-to-deny"], 1)
        self.assertEqual(counts["none"], 1)
        self.assertIn("severity_weighted_asr", anatomy)
        self.assertIn("target_hit_rate", anatomy)

    def test_run_provenance_bundle(self):
        # M-6: every view's provenance bundle is present.
        payload = run_to_dashboard(_make_artifact())
        run = payload["run"]
        for key in (
            "model_class", "confidence_source", "checkpoint_hash",
            "api_version", "call_date", "decode_params", "template_hash",
            "case_set_tag", "cost_scenario_version",
        ):
            self.assertIn(key, run)


class TestLeaderboard(unittest.TestCase):
    def _write(self, tmp_path, name, adapter, asr, eligible=True):
        art = _make_artifact(
            adapter_name=adapter,
            metrics=_metrics(asr_conditional=asr,
                             ranking_eligible=eligible),
        )
        (tmp_path / name).write_text(art.to_json())

    def test_ranked_sorted_by_asr(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._write(tmp_path, "b.json", "adapter-b", 0.8)
            self._write(tmp_path, "a.json", "adapter-a", 0.2)
            scan_runs(tmp)
            lb = leaderboard(tmp)
            self.assertEqual(lb["n_ranked"], 2)
            self.assertEqual(lb["ranked"][0]["adapter_name"], "adapter-a")
            self.assertEqual(lb["ranked"][1]["adapter_name"], "adapter-b")

    def test_unranked_listed_with_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._write(tmp_path, "a.json", "adapter-a", 0.2, eligible=False)
            scan_runs(tmp)
            lb = leaderboard(tmp)
            self.assertEqual(lb["n_ranked"], 0)
            self.assertEqual(lb["n_unranked"], 1)
            self.assertEqual(lb["unranked"][0]["adapter_name"], "adapter-a")
            self.assertIn("reason", lb["unranked"][0])

    def test_latest_run_per_adapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            # Two runs for the same adapter; only the latest counts.
            # Ordering is forced through distinct created_utc values,
            # never the wall clock: the test stays deterministic.
            art1 = _make_artifact(
                adapter_name="adapter-a",
                metrics=_metrics(asr_conditional=0.9),
            )
            (tmp_path / "old.json").write_text(art1.to_json())
            art2 = _make_artifact(
                adapter_name="adapter-a",
                metrics=_metrics(asr_conditional=0.1),
            )
            # Force a later created_utc.
            d = json.loads(art2.to_json())
            d["created_utc"] = "2099-01-01T00:00:00+00:00"
            resealed = RunArtifact.from_json(json.dumps(d)).seal()
            (tmp_path / "new.json").write_text(resealed.to_json())
            scan_runs(tmp)
            lb = leaderboard(tmp)
            self.assertEqual(lb["n_ranked"], 1)
            self.assertEqual(
                lb["ranked"][0]["asr_conditional"], 0.1
            )

    def test_json_serializable(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._write(tmp_path, "a.json", "adapter-a", 0.2)
            scan_runs(tmp)
            json.dumps(leaderboard(tmp))


class TestComparisonToDashboard(unittest.TestCase):
    def test_verdict(self):
        from peira.compare import (
            Comparison, HeadToHeadCounts, McNemarResult,
        )

        comp = Comparison(
            adapter_a="a",
            adapter_b="b",
            suite="v1",
            dataset_version="1.0.3",
            n_a=10,
            n_b=10,
            n_paired=10,
            head_to_head=HeadToHeadCounts(
                n=10, both_right=5, a_only=3, b_only=1, both_wrong=1
            ),
            per_family={
                "indirection": HeadToHeadCounts(
                    n=6, both_right=2, a_only=3, b_only=1, both_wrong=0
                ),
                "pretexting": HeadToHeadCounts(
                    n=4, both_right=3, a_only=0, b_only=0, both_wrong=1
                ),
            },
            mcnemar=McNemarResult(
                b=3, c=1, n_pairs=10, statistic=6.0,
                p_value=0.01, winner="a",
            ),
            mcnemar_note="",
            bradley_terry_strengths=None,
            bradley_terry_nu=None,
            bradley_terry_n=0,
            bradley_terry_note="",
        )
        payload = comparison_to_dashboard(comp)
        self.assertTrue(payload["verdict"]["mcnemar_significant_005"])
        self.assertEqual(
            payload["verdict"]["per_family_winners"]["indirection"]["winner"],
            "a",
        )
        self.assertEqual(
            payload["verdict"]["per_family_winners"]["pretexting"]["winner"],
            "tie",
        )
        json.dumps(payload)


if __name__ == "__main__":
    unittest.main()
