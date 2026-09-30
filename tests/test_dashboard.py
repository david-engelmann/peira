"""Tests for the dashboard data layer (python/peira/dashboard.py).

Run with: PYTHONPATH=python python3 -m pytest tests
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
    _per_case_cost_latency,
    _classify_flip_direction,
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

    def test_out_of_range_excluded(self):
        # Negative (or > 1) confidences are corruption: excluded like a
        # missing value, never wrapped into a bin by negative indexing.
        h = _confidence_histogram([-0.5, 0.5, 1.5])
        self.assertEqual(h["n"], 1)
        self.assertEqual(h["n_missing"], 2)
        self.assertEqual(sum(h["counts"]), 1)
        self.assertEqual(h["counts"][5], 1)

    def test_nan_excluded(self):
        h = _confidence_histogram([float("nan"), 0.5])
        self.assertEqual(h["n"], 1)
        self.assertEqual(h["n_missing"], 1)


class TestPerCaseCostLatency(unittest.TestCase):
    def test_missing_latency_not_counted(self):
        # A missing latency_ms_total key is not a 0.0-ms call.
        rec = _call_record()
        del rec["latency_ms_total"]
        entry = _result_entry(benign=rec, attacked=rec)
        cost, latency, n_costed, n_latency = _per_case_cost_latency([entry])
        self.assertEqual(n_latency, 0)
        self.assertEqual(latency, 0.0)
        # Cost is unaffected (usage still present on both arms).
        self.assertEqual(n_costed, 2)
        self.assertAlmostEqual(cost, 0.002)

    def test_explicit_zero_latency_counted(self):
        rec = _call_record(latency_ms_total=0.0)
        entry = _result_entry(benign=rec, attacked=rec)
        _, _, _, n_latency = _per_case_cost_latency([entry])
        self.assertEqual(n_latency, 2)

    def test_negative_and_nan_cost_excluded(self):
        benign = _call_record()
        benign["usage"] = dict(benign["usage"], cost_usd=-5.0)
        attacked = _call_record()
        attacked["usage"] = dict(attacked["usage"], cost_usd=float("nan"))
        entry = _result_entry(benign=benign, attacked=attacked)
        cost, _, n_costed, _ = _per_case_cost_latency([entry])
        self.assertEqual(n_costed, 0)
        self.assertEqual(cost, 0.0)


class TestClassifyFlipDirection(unittest.TestCase):
    def test_non_dict_reports_none(self):
        # A non-dict entry carries no flip evidence: "none", not "other".
        self.assertEqual(_classify_flip_direction("not a dict"), "none")
        self.assertEqual(_classify_flip_direction(None), "none")
        self.assertEqual(_classify_flip_direction([1, 2]), "none")


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
        self.assertEqual(
            ind["flip_direction"],
            {
                "approve-to-deny": 1,
                "deny-to-approve": 0,
                "to-abstain": 0,
                "to-malformed": 0,
                "score-shifted": 0,
                "other": 0,
                # c2 is eligible but unflipped: it counts as "none".
                # flip_direction runs over the eligible population,
                # matching _flip_anatomy.
                "none": 1,
            },
        )

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
            ind["flip_direction"],
            {
                "approve-to-deny": 1,
                "deny-to-approve": 0,
                "to-abstain": 0,
                "to-malformed": 1,
                "score-shifted": 0,
                "other": 0,
                "none": 0,
            },
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

    def test_rejects_non_numeric_wins(self):
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
                    n=6, both_right=2, a_only="3", b_only=1, both_wrong=0
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
        with self.assertRaises(TypeError):
            comparison_to_dashboard(comp)


class TestSeverityBreakdownCI(unittest.TestCase):
    """M-6: every severity aggregate cell retains n and CI inputs."""

    def test_flip_rate_carries_wilson_ci(self):
        from peira.dashboard import _severity_breakdown
        from peira.metrics import wilson_ci

        results = [
            _result_entry(case_id="c1", severity="high", flipped=True),
            _result_entry(case_id="c2", severity="high", flipped=True),
            _result_entry(case_id="c3", severity="high", flipped=False),
            _result_entry(
                case_id="c4", severity="high", flipped=False, eligible=False
            ),
        ]
        sev = _severity_breakdown(results)["high"]
        self.assertEqual(sev["n"], 4)
        self.assertEqual(sev["n_eligible"], 3)
        self.assertEqual(sev["n_flipped"], 2)
        lo, hi = wilson_ci(2, 3)
        self.assertEqual(
            sev["flip_rate_ci95"], [round(lo, 4), round(hi, 4)]
        )
        # The point estimate stays consistent with the CI inputs.
        self.assertAlmostEqual(sev["flip_rate_raw"], 2 / 3, places=4)

    def test_empty_eligible_population(self):
        from peira.dashboard import _severity_breakdown

        results = [
            _result_entry(case_id="c1", severity="low", flipped=False,
                          eligible=False),
        ]
        sev = _severity_breakdown(results)["low"]
        self.assertIsNone(sev["flip_rate_raw"])
        self.assertEqual(sev["flip_rate_ci95"], [0.0, 0.0])


class TestPairwiseResampleAhead(unittest.TestCase):
    """M-6: the rank-stability resample view is recomputable."""

    def _runs_dir_with_two_adapters(self, tmp_path):
        from peira.runs_registry import query_cases  # noqa: F401

        def _results(flips):
            out = []
            for i, flipped in enumerate(flips):
                entry = _result_entry(
                    case_id=f"shared-{i:03d}",
                    flipped=flipped,
                    attacked=_call_record(
                        decision="deny" if flipped else "approve",
                        dispatch_index=1,
                    ),
                )
                out.append(entry)
            return out

        # Adapter A flips 10/40, adapter B flips 30/40: A is clearly ahead.
        flips_a = [True] * 10 + [False] * 30
        flips_b = [True] * 30 + [False] * 10
        for name, flips in (("adapter-a", flips_a), ("adapter-b", flips_b)):
            art = _make_dashboard_artifact(
                adapter_name=name, results=_results(flips)
            )
            (tmp_path / f"{name}.json").write_text(art)
        return tmp_path

    def test_ahead_fraction_reflects_point_estimates(self):
        from peira.dashboard import pairwise_resample_ahead

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._runs_dir_with_two_adapters(tmp_path)
            out = pairwise_resample_ahead(
                runs_dir=tmp_path, n_boot=2000, seed=0
            )
            self.assertEqual(out["adapters"], ["adapter-a", "adapter-b"])
            pair = out["pairs"]["adapter-a|adapter-b"]
            self.assertEqual(pair["n_shared"], 40)
            # A flips far less than B: A is ahead in ~all resamples.
            self.assertGreater(pair["ahead_fraction"], 0.99)
            # Mirror entry reads the other direction (exact: ties were
            # counted separately, so behind_fraction is the true
            # reverse fraction, not 1 - ahead).
            mirror = out["pairs"]["adapter-b|adapter-a"]
            self.assertAlmostEqual(
                mirror["ahead_fraction"],
                pair["behind_fraction"],
                places=4,
            )
            self.assertAlmostEqual(
                mirror["behind_fraction"],
                pair["ahead_fraction"],
                places=4,
            )
            # Diagonal is 0.5 by definition.
            self.assertEqual(
                out["pairs"]["adapter-a|adapter-a"]["ahead_fraction"], 0.5
            )

    def test_deterministic_across_calls(self):
        from peira.dashboard import pairwise_resample_ahead

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._runs_dir_with_two_adapters(tmp_path)
            first = pairwise_resample_ahead(
                runs_dir=tmp_path, n_boot=500, seed=42
            )
            second = pairwise_resample_ahead(
                runs_dir=tmp_path, n_boot=500, seed=42
            )
            self.assertEqual(first["pairs"], second["pairs"])

    def test_uses_latest_run_per_adapter(self):
        # Two runs for the same adapter: the vector must come from the
        # latest qualifying run only, never a mix with stale values.
        import json

        from peira.dashboard import pairwise_resample_ahead

        def _artifact_with_time(name, flips, created):
            art = json.loads(
                _make_dashboard_artifact(
                    adapter_name=name,
                    results=[
                        _result_entry(
                            case_id=f"c-{i:03d}",
                            flipped=f,
                            attacked=_call_record(
                                decision="deny" if f else "approve",
                                dispatch_index=1,
                            ),
                        )
                        for i, f in enumerate(flips)
                    ],
                )
            )
            art["created_utc"] = created
            return json.dumps(art)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            flips = [True] * 20 + [False] * 20
            # Old run: adapter-a flips everything (bad).
            (tmp_path / "a-old.json").write_text(
                _artifact_with_time(
                    "multi-a", [True] * 40, "2026-01-01T00:00:00Z"
                )
            )
            # New run: adapter-a flips half (good). Must win.
            (tmp_path / "a-new.json").write_text(
                _artifact_with_time(
                    "multi-a", flips, "2026-06-01T00:00:00Z"
                )
            )
            (tmp_path / "b.json").write_text(
                _make_dashboard_artifact(
                    adapter_name="multi-b",
                    results=[
                        _result_entry(
                            case_id=f"c-{i:03d}",
                            flipped=(i % 2 == 0),
                            attacked=_call_record(
                                decision="deny" if i % 2 == 0 else "approve",
                                dispatch_index=1,
                            ),
                        )
                        for i in range(40)
                    ],
                )
            )
            out = pairwise_resample_ahead(
                runs_dir=tmp_path, n_boot=2000, seed=0
            )
            # multi-a's latest run (50% ASR) vs multi-b (50% ASR):
            # roughly tied, NOT the 100%-vs-50% blowout the stale
            # old run would produce.
            pair = out["pairs"]["multi-a|multi-b"]
            self.assertEqual(pair["n_shared"], 40)
            self.assertLess(pair["ahead_fraction"], 0.9)
            self.assertLess(pair["behind_fraction"], 0.9)
            # Provenance identifies the new run.
            self.assertEqual(
                pair["provenance_a"]["created_utc"],
                "2026-06-01T00:00:00Z",
            )

    def test_draw_stream_matches_paired_bootstrap(self):
        # Pins the M-6 requirement 3 contract: pairwise_resample_ahead
        # must use the same seeded paired draw stream as
        # metrics.paired_bootstrap_ci. Replicates the draw pattern
        # independently and asserts the fractions match exactly.
        import random

        from peira.dashboard import pairwise_resample_ahead

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._runs_dir_with_two_adapters(tmp_path)
            seed, n_boot = 7, 1500
            out = pairwise_resample_ahead(
                runs_dir=tmp_path, n_boot=n_boot, seed=seed
            )
            pair = out["pairs"]["adapter-a|adapter-b"]

            # Independent replication: shared cases sorted, same RNG
            # stream, same mean comparison.
            flips_a = [True] * 10 + [False] * 30
            flips_b = [True] * 30 + [False] * 10
            xs = [1.0 if f else 0.0 for f in flips_a]
            ys = [1.0 if f else 0.0 for f in flips_b]
            rng = random.Random(seed)
            ahead = behind = 0
            n = 40
            for _ in range(n_boot):
                idx = [rng.randrange(n) for _ in range(n)]
                ma = sum(xs[j] for j in idx) / n
                mb = sum(ys[j] for j in idx) / n
                if ma < mb:
                    ahead += 1
                elif mb < ma:
                    behind += 1
            self.assertEqual(
                pair["ahead_fraction"], round(ahead / n_boot, 4)
            )
            self.assertEqual(
                pair["behind_fraction"], round(behind / n_boot, 4)
            )

    def test_n_boot_validation(self):
        from peira.dashboard import pairwise_resample_ahead

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._runs_dir_with_two_adapters(tmp_path)
            for bad in (0, -5, True, 1.5, "100"):
                with self.assertRaises(ValueError):
                    pairwise_resample_ahead(
                        runs_dir=tmp_path, n_boot=bad
                    )

    def test_thin_pairs_withheld(self):
        from peira.dashboard import pairwise_resample_ahead

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            art = _make_dashboard_artifact(
                adapter_name="thin-a",
                results=[_result_entry(case_id="only-1")],
            )
            (tmp_path / "thin-a.json").write_text(art)
            art2 = _make_dashboard_artifact(
                adapter_name="thin-b",
                results=[_result_entry(case_id="only-1")],
            )
            (tmp_path / "thin-b.json").write_text(art2)
            out = pairwise_resample_ahead(
                runs_dir=tmp_path, n_boot=100, seed=0
            )
            pair = out["pairs"]["thin-a|thin-b"]
            self.assertEqual(pair["n_shared"], 1)
            self.assertIsNone(pair["ahead_fraction"])
            self.assertIsNone(pair["behind_fraction"])

    def test_ties_count_for_neither(self):
        # Identical flip vectors: every resample ties, so both
        # directions read 0.0 (not 0.0 and 1.0).
        from peira.dashboard import pairwise_resample_ahead

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            flips = [True] * 20 + [False] * 20
            for name in ("tie-a", "tie-b"):
                results = [
                    _result_entry(
                        case_id=f"shared-{i:03d}",
                        flipped=f,
                        attacked=_call_record(
                            decision="deny" if f else "approve",
                            dispatch_index=1,
                        ),
                    )
                    for i, f in enumerate(flips)
                ]
                art = _make_dashboard_artifact(
                    adapter_name=name, results=results
                )
                (tmp_path / f"{name}.json").write_text(art)
            out = pairwise_resample_ahead(
                runs_dir=tmp_path, n_boot=500, seed=0
            )
            pair = out["pairs"]["tie-a|tie-b"]
            self.assertEqual(pair["ahead_fraction"], 0.0)
            self.assertEqual(pair["behind_fraction"], 0.0)
            mirror = out["pairs"]["tie-b|tie-a"]
            self.assertEqual(mirror["ahead_fraction"], 0.0)
            self.assertEqual(mirror["behind_fraction"], 0.0)


def _make_dashboard_artifact(adapter_name, results):
    """Minimal sealed artifact JSON with real results for dashboard tests."""
    from peira.artifacts import RunArtifact
    from peira.env_fingerprint import collect_and_fingerprint

    env, env_sha256 = collect_and_fingerprint()
    artifact = RunArtifact(
        adapter_name=adapter_name,
        adapter_version="1.0-test",
        suite="v1",
        dataset_version="1.2.1",
        manifest_sha256="abc123" * 10 + "abcd",
        seed=0,
        max_concurrency=8,
        env=env,
        env_sha256=env_sha256,
        config={"cache_enabled": False},
        results=results,
        metrics={"ranking_eligible": True, "eligibility_notes": []},
    )
    return artifact.seal().to_json()


if __name__ == "__main__":
    unittest.main()
