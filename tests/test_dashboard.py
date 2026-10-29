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
    # 200 eligible results in one family: genuinely ranking-eligible,
    # so the recomputation in qualifies_for_leaderboard agrees with
    # the sealed flag.
    results = []
    for i in range(200):
        results.append(_result_entry(
            case_id=f"{adapter_name}-c{i:03d}",
            family="indirection",
            flipped=(i % 2 == 0),
            attacked=_call_record(
                decision="deny" if i % 2 == 0 else "approve"),
        ))
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
        "results": results,
        "metrics": _metrics(
            n_cases=200, n_eligible=200, asr_conditional=0.5,
            required_families=["indirection"],
        ),
        "termination": "complete",
        "cases_completed": 200,
        "cases_planned": 200,
        "spent_usd": 0.4,
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
        self.assertEqual(h["n_cases"], 200)

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
        # 100 flipped (approve->deny) + 100 not flipped in the fixture.
        self.assertEqual(counts["approve-to-deny"], 100)
        self.assertEqual(counts["none"], 100)
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
    def _write(self, tmp_path, name, adapter, asr, eligible=True,
               adapter_version=None):
        # Leaderboard identity is the (adapter_version, adapter_name)
        # pair: the model ID plus the wire that measured it. Default
        # the version to the adapter name so distinct adapters stay
        # distinct unless the test says otherwise.
        art = _make_artifact(
            adapter_name=adapter,
            adapter_version=(adapter_version if adapter_version is not None
                             else adapter + "-1.0"),
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

    def test_shared_adapter_name_keeps_distinct_models(self):
        # P1.1: models sharing an adapter_name (e.g. all OpenRouter
        # models use "openrouter-structured") must each appear, deduped
        # by adapter_version (the model ID), not adapter_name.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._write(tmp_path, "qwen.json", "openrouter-structured", 0.3,
                        adapter_version="qwen/qwen3-235b-a22b-2507")
            self._write(tmp_path, "solar.json", "openrouter-structured", 0.2,
                        adapter_version="upstage/solar-pro4")
            scan_runs(tmp)
            lb = leaderboard(tmp)
            self.assertEqual(lb["n_ranked"], 2)
            versions = {r["adapter_version"] for r in lb["ranked"]}
            self.assertEqual(
                versions,
                {"qwen/qwen3-235b-a22b-2507", "upstage/solar-pro4"},
            )
            for row in lb["ranked"]:
                self.assertEqual(row["wire"], "openrouter-structured")

    def test_same_model_id_two_wires_both_appear(self):
        # Two wires can measure the same model: the chat-completions
        # run and the OpenAI Decisions run both carry adapter_version
        # "gpt-6-luna", under adapter_names "openai-structured" and
        # "openai-decisions". Grouping by model ID alone silently
        # displaced one measurement with the other; the board must
        # carry both as separate entries, each with its own numbers
        # and a wire label naming the adapter that produced it.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._write(tmp_path, "chat.json", "openai-structured", 0.30,
                        adapter_version="gpt-6-luna")
            self._write(tmp_path, "decisions.json", "openai-decisions",
                        0.20, adapter_version="gpt-6-luna")
            scan_runs(tmp)
            lb = leaderboard(tmp)
            self.assertEqual(lb["n_ranked"], 2)
            self.assertEqual(lb["n_unranked"], 0)
            by_wire = {r["wire"]: r for r in lb["ranked"]}
            self.assertEqual(set(by_wire),
                             {"openai-structured", "openai-decisions"})
            self.assertEqual(
                by_wire["openai-structured"]["asr_conditional"], 0.30)
            self.assertEqual(
                by_wire["openai-decisions"]["asr_conditional"], 0.20)
            for row in lb["ranked"]:
                self.assertEqual(row["display_name"], "gpt-6-luna")
                self.assertEqual(row["wire"], row["adapter_name"])

    def test_probe_shadow_applies_per_wire(self):
        # The probe-shadow guard works within a wire: a newer
        # probe-sized run of the Decisions wire must not displace
        # that wire's full run, and must not touch the chat wire's
        # entry for the same model.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            chat = _make_artifact(
                adapter_name="openai-structured",
                adapter_version="gpt-6-luna",
                metrics=_metrics(n_cases=200, n_eligible=200,
                                 asr_conditional=0.30))
            (tmp_path / "chat.json").write_text(chat.to_json())
            dec = _make_artifact(
                adapter_name="openai-decisions",
                adapter_version="gpt-6-luna",
                metrics=_metrics(n_cases=200, n_eligible=200,
                                 asr_conditional=0.20))
            (tmp_path / "dec.json").write_text(dec.to_json())
            probe_results = [
                _result_entry(case_id=f"probe-c{i:02d}",
                              family="indirection")
                for i in range(10)
            ]
            probe = _make_artifact(
                adapter_name="openai-decisions",
                adapter_version="gpt-6-luna",
                results=probe_results,
                metrics=_metrics(
                    n_cases=10, n_eligible=10, ranking_eligible=False,
                    eligibility_notes=[
                        "fewer than 200 eligible cases (10)"],
                ),
                cases_completed=10,
                cases_planned=10,
            )
            (tmp_path / "probe.json").write_text(
                self._reseal_later(probe).to_json())
            scan_runs(tmp)
            lb = leaderboard(tmp)
            self.assertEqual(lb["n_ranked"], 2)
            self.assertEqual(lb["n_unranked"], 0)
            by_wire = {r["wire"]: r for r in lb["ranked"]}
            # The Decisions entry is its full run (ASR 0.20, the
            # run_id of the full artifact), not the later probe.
            self.assertEqual(
                by_wire["openai-decisions"]["asr_conditional"], 0.20)
            self.assertEqual(
                by_wire["openai-decisions"]["n_cases"], 200)
            self.assertEqual(
                by_wire["openai-structured"]["asr_conditional"], 0.30)

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

    def _reseal_later(self, art):
        # Same trick as test_latest_run_per_adapter: force a later
        # created_utc through a reseal, never the wall clock.
        d = json.loads(art.to_json())
        d["created_utc"] = "2099-01-01T00:00:00+00:00"
        return RunArtifact.from_json(json.dumps(d)).seal()

    def test_probe_rerun_does_not_shadow_full_run(self):
        # A later probe run (a canary: far fewer recorded cases than
        # the coverage gates require) must not displace the model's
        # earlier full run from the board.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            full = _make_artifact(adapter_name="adapter-a",
                                  adapter_version="model-x-1.0")
            (tmp_path / "full.json").write_text(full.to_json())
            probe_results = [
                _result_entry(case_id=f"probe-c{i:02d}",
                              family="indirection")
                for i in range(10)
            ]
            probe = _make_artifact(
                adapter_name="adapter-a",
                adapter_version="model-x-1.0",
                results=probe_results,
                metrics=_metrics(
                    n_cases=10, n_eligible=10, ranking_eligible=False,
                    eligibility_notes=[
                        "fewer than 200 eligible cases (10)"],
                ),
                cases_completed=10,
                cases_planned=10,
            )
            (tmp_path / "probe.json").write_text(
                self._reseal_later(probe).to_json())
            scan_runs(tmp)
            lb = leaderboard(tmp)
            self.assertEqual(lb["n_ranked"], 1)
            self.assertEqual(lb["n_unranked"], 0)
            self.assertEqual(lb["ranked"][0]["adapter_version"],
                             "model-x-1.0")
            self.assertEqual(lb["ranked"][0]["asr_conditional"], 0.5)

    def test_latest_full_run_failing_quality_stands(self):
        # A later FULL run that measured the benchmark and failed a
        # quality gate is the model's standing result: the board does
        # not fall back to the earlier qualifying run.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            full = _make_artifact(adapter_name="adapter-a",
                                  adapter_version="model-x-1.0")
            (tmp_path / "full.json").write_text(full.to_json())
            bad_results = []
            for i in range(200):
                bad_results.append(_result_entry(
                    case_id=f"bad-c{i:03d}",
                    family="indirection",
                    flipped=(i % 2 == 0),
                    benign=_call_record(malformed=True),
                    attacked=_call_record(
                        decision="deny" if i % 2 == 0 else "approve",
                        malformed=True),
                ))
            bad = _make_artifact(
                adapter_name="adapter-a",
                adapter_version="model-x-1.0",
                results=bad_results,
                metrics=_metrics(
                    malformed_rate=1.0, ranking_eligible=False,
                    eligibility_notes=["malformed_rate above 5%"],
                ),
            )
            (tmp_path / "bad.json").write_text(
                self._reseal_later(bad).to_json())
            scan_runs(tmp)
            lb = leaderboard(tmp)
            self.assertEqual(lb["n_ranked"], 0)
            self.assertEqual(lb["n_unranked"], 1)
            self.assertIn("malformed", lb["unranked"][0]["reason"])

    def test_unranked_row_carries_full_stats(self):
        # A model that ran the full benchmark and failed a quality
        # gate is unranked, but its numbers exist: the unranked row
        # carries the same headline stats and per-run detail as a
        # ranked row, so the page can print them next to the reason.
        # Qualification itself is unchanged.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bad_results = []
            for i in range(200):
                bad_results.append(_result_entry(
                    case_id=f"bad-c{i:03d}",
                    family="indirection",
                    flipped=(i % 2 == 0),
                    benign=_call_record(malformed=True),
                    attacked=_call_record(
                        decision="deny" if i % 2 == 0 else "approve",
                        malformed=True),
                ))
            bad = _make_artifact(
                adapter_name="adapter-a",
                adapter_version="model-x-1.0",
                results=bad_results,
                metrics=_metrics(
                    malformed_rate=1.0, ranking_eligible=False,
                    eligibility_notes=["malformed_rate above 5%"],
                ),
            )
            (tmp_path / "bad.json").write_text(bad.to_json())
            good = _make_artifact(adapter_name="adapter-b",
                                  adapter_version="model-y-1.0")
            (tmp_path / "good.json").write_text(good.to_json())
            scan_runs(tmp)
            lb = leaderboard(tmp)
            self.assertEqual(lb["n_ranked"], 1)
            self.assertEqual(lb["n_unranked"], 1)
            self.assertEqual(lb["ranked"][0]["malformed_rate"], 0.0)
            row = lb["unranked"][0]
            self.assertEqual(row["ranking_eligible"], False)
            self.assertEqual(row["asr_conditional"], 0.5)
            self.assertEqual(row["malformed_rate"], 1.0)
            self.assertEqual(row["benign_accuracy"], 1.0)
            self.assertEqual(row["n_eligible"], 2)
            self.assertIn("malformed", row["reason"])
            self.assertIn("indirection", row["detail"]["families"])

    def test_json_serializable(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._write(tmp_path, "a.json", "adapter-a", 0.2)
            scan_runs(tmp)
            json.dumps(leaderboard(tmp))

    def test_display_name_is_the_model_id(self):
        # The public page names models, not adapters: two models can
        # share one adapter_name, so rows carry display_name equal to
        # the model ID (adapter_version) for the renderer to show.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._write(tmp_path, "qwen.json", "openrouter-structured", 0.3,
                        adapter_version="qwen/qwen3-235b-a22b-2507")
            self._write(tmp_path, "bad.json", "adapter-bad", 0.2,
                        eligible=False,
                        adapter_version="bad-model-2.0")
            scan_runs(tmp)
            lb = leaderboard(tmp)
            self.assertEqual(lb["ranked"][0]["display_name"],
                             "qwen/qwen3-235b-a22b-2507")
            self.assertEqual(lb["unranked"][0]["display_name"],
                             "bad-model-2.0")


class TestLeaderboardRerunProvenance(unittest.TestCase):
    """The board's re-run note is built from artifact metadata.

    A standing artifact that chains to a parent run
    (RunArtifact.parent_run_id) yields a row whose rerun record
    carries that chain and the artifact's own creation day, so
    the board can state the re-run from data. An artifact that
    chains to nothing yields no record. (F3 of the 2026-10-29
    hardcode audit: the Method note named two runs and a date
    as source literals, and no payload field carried the fact.)
    """

    def test_row_carries_rerun_record_from_artifact_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            art = _make_artifact(
                adapter_name="rerun-adapter",
                adapter_version="rerun-adapter-1.0",
                parent_run_id="run-parent-123",
            )
            (tmp_path / "rerun.json").write_text(art.to_json())
            scan_runs(tmp)
            lb = leaderboard(tmp)
            self.assertEqual(lb["n_ranked"], 1)
            self.assertEqual(
                lb["ranked"][0]["rerun"],
                {"parent_run_id": "run-parent-123",
                 "date": art.created_utc[:10]},
            )

    def test_row_without_parent_run_carries_no_rerun(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            art = _make_artifact(
                adapter_name="plain-adapter",
                adapter_version="plain-adapter-1.0",
            )
            (tmp_path / "plain.json").write_text(art.to_json())
            scan_runs(tmp)
            lb = leaderboard(tmp)
            self.assertEqual(lb["n_ranked"], 1)
            self.assertIn("rerun", lb["ranked"][0])
            self.assertIsNone(lb["ranked"][0]["rerun"])


class TestLeaderboardProbeExclusion(unittest.TestCase):
    """An entry whose standing run is a canary prints nothing.

    Canary exclusion used to apply only when a probe shadowed a
    full run of the same entry. A canary staged as an entry's only
    run (the sealed granite-guardian canary is the real instance)
    failed qualification and still printed a full stat row under
    unranked. A canary is a wiring check sealed under a canary
    suite marker, not a measurement, so the entry is omitted
    entirely. Runs that measured the benchmark are not canaries
    however small or quality-failing they are, and they print.
    """

    def _write_probe_only(self, tmp_path, name="probe.json"):
        probe_results = [
            _result_entry(case_id=f"probe-c{i:02d}", family="indirection")
            for i in range(10)
        ]
        probe = _make_artifact(
            adapter_name="adapter-probe",
            adapter_version="probe-model-1.0",
            suite="v2-canary",
            case_set_tag="v2-canary",
            results=probe_results,
            metrics=_metrics(
                n_cases=10, n_eligible=10, ranking_eligible=False,
                eligibility_notes=["fewer than 200 eligible cases (10)"],
            ),
            cases_completed=10,
            cases_planned=10,
        )
        (tmp_path / name).write_text(probe.to_json())

    def test_probe_only_entry_is_omitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._write_probe_only(tmp_path)
            scan_runs(tmp)
            lb = leaderboard(tmp)
            self.assertEqual(lb["n_ranked"], 0)
            self.assertEqual(lb["n_unranked"], 0)

    def test_probe_only_entry_omitted_beside_a_full_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._write_probe_only(tmp_path)
            full = _make_artifact(adapter_name="adapter-full",
                                  adapter_version="full-model-1.0")
            (tmp_path / "full.json").write_text(full.to_json())
            scan_runs(tmp)
            lb = leaderboard(tmp)
            self.assertEqual(lb["n_ranked"], 1)
            self.assertEqual(lb["n_unranked"], 0)
            self.assertEqual(lb["ranked"][0]["adapter_name"],
                             "adapter-full")

    def test_small_suite_complete_run_prints_unranked(self):
        # A complete run of a small suite measured its benchmark:
        # it is not a canary, and it prints with its reason even
        # though it is far below the 200-case gate.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            results = [
                _result_entry(case_id=f"small-c{i:03d}",
                              family="indirection")
                for i in range(100)
            ]
            small = _make_artifact(
                adapter_name="adapter-small",
                adapter_version="small-model-1.0",
                suite="trial",
                results=results,
                metrics=_metrics(
                    n_cases=100, n_eligible=100, ranking_eligible=False,
                    eligibility_notes=[
                        "fewer than 200 eligible cases (100)"],
                ),
                cases_completed=100,
                cases_planned=100,
            )
            (tmp_path / "small.json").write_text(small.to_json())
            scan_runs(tmp)
            lb = leaderboard(tmp)
            self.assertEqual(lb["n_ranked"], 0)
            self.assertEqual(lb["n_unranked"], 1)
            self.assertIn("fewer than 200",
                          lb["unranked"][0]["reason"])

    def test_quality_failing_short_run_prints_unranked(self):
        # A run that measured the benchmark and failed quality
        # stands with its reason even just under the 200-case
        # line: only a canary marker makes a run a probe.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bad_results = [
                _result_entry(
                    case_id=f"bad-c{i:03d}",
                    family="indirection",
                    flipped=(i % 2 == 0),
                    benign=_call_record(malformed=True),
                    attacked=_call_record(
                        decision="deny" if i % 2 == 0 else "approve",
                        malformed=True),
                )
                for i in range(199)
            ]
            bad = _make_artifact(
                adapter_name="adapter-bad",
                adapter_version="bad-model-1.0",
                results=bad_results,
                metrics=_metrics(
                    n_cases=199, n_eligible=199,
                    malformed_rate=1.0, ranking_eligible=False,
                    eligibility_notes=["malformed_rate above 5%"],
                ),
                cases_completed=199,
                cases_planned=199,
            )
            (tmp_path / "bad.json").write_text(bad.to_json())
            scan_runs(tmp)
            lb = leaderboard(tmp)
            self.assertEqual(lb["n_ranked"], 0)
            self.assertEqual(lb["n_unranked"], 1)
            self.assertIn("malformed",
                          lb["unranked"][0]["reason"])

    def test_conversational_entry_prints_its_reason_row(self):
        # A conversational artifact is rejected by qualification
        # with its own reason, and the identity-only row carrying
        # that reason prints: it is not a canary either.
        from peira.conversation import CONVERSATION_SUITE_ID

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            conv = _make_artifact(
                adapter_name="adapter-conv",
                adapter_version="conv-model-1.0",
                suite=CONVERSATION_SUITE_ID,
                results=[_result_entry(case_id="conv-c001")],
                metrics=_metrics(
                    n_cases=1, n_eligible=1, ranking_eligible=False,
                ),
                cases_completed=1,
                cases_planned=1,
            )
            (tmp_path / "conv.json").write_text(conv.to_json())
            scan_runs(tmp)
            lb = leaderboard(tmp)
            self.assertEqual(lb["n_ranked"], 0)
            self.assertEqual(lb["n_unranked"], 1)
            self.assertIn("conversational",
                          lb["unranked"][0]["reason"])


def _sized_artifact(adapter_name, n_results, *, asr, benign_accuracy,
                    ece, adapter_version=None):
    """A sealed artifact with a chosen case count and headline values.

    The result records only carry the eligibility gates (counts,
    malformed, families); the headline numbers ride in metrics,
    exactly as a sealed run's do. Used to place rows from two
    different case populations on one board.
    """
    env, env_sha256 = collect_and_fingerprint()
    results = [
        _result_entry(
            case_id=f"{adapter_name}-c{i:03d}",
            family="indirection",
            flipped=(i % 2 == 0),
            attacked=_call_record(
                decision="deny" if i % 2 == 0 else "approve"),
        )
        for i in range(n_results)
    ]
    return RunArtifact(
        adapter_name=adapter_name,
        adapter_version=adapter_version or (adapter_name + "-1.0"),
        suite="v1",
        dataset_version="1.0.3",
        manifest_sha256="abc123" * 10 + "abcd",
        seed=0,
        max_concurrency=8,
        env=env,
        env_sha256=env_sha256,
        config={"cache_enabled": False},
        results=results,
        metrics=_metrics(
            n_cases=n_results, n_eligible=n_results,
            asr_conditional=asr, benign_accuracy=benign_accuracy,
            calibration={
                "confidence_coverage": {"benign": 1.0, "attacked": 1.0},
                "attacked": {"ece": ece, "sufficient": True},
            },
            required_families=["indirection"],
        ),
        termination="complete",
        cases_completed=n_results,
        cases_planned=n_results,
        spent_usd=0.4,
    ).seal()


class TestRobustnessTaxFrontierCohort(unittest.TestCase):
    """The tax frontier is the full-suite cohort, by suite size.

    A slice row measured a sub-population, so its benign accuracy
    and attacked ECE must neither enter the frontier nor receive
    a tax, and the full-suite rows' taxes must be exactly the
    taxes they would carry on a board without the slice.
    """

    def _board(self, tmp_path, with_slice):
        full_a = _sized_artifact(
            "full-a", 300, asr=0.30, benign_accuracy=0.90, ece=0.05)
        (tmp_path / "full-a.json").write_text(full_a.to_json())
        full_b = _sized_artifact(
            "full-b", 300, asr=0.20, benign_accuracy=0.95, ece=0.10)
        (tmp_path / "full-b.json").write_text(full_b.to_json())
        if with_slice:
            # The slice beats both frontier anchors (accuracy 1.0,
            # ECE 0.001) on a smaller population: the contamination
            # case from the sealed ProtectAI and Granite HAP runs.
            slice_row = _sized_artifact(
                "slice-a", 200, asr=0.10, benign_accuracy=1.0,
                ece=0.001)
            (tmp_path / "slice-a.json").write_text(slice_row.to_json())
        scan_runs(str(tmp_path))
        return leaderboard(str(tmp_path))

    def test_slice_row_does_not_shift_full_suite_taxes(self):
        # Two separate boards: one with the slice staged, one
        # without. The full-suite taxes must agree exactly.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "plain").mkdir()
            (root / "mixed").mkdir()
            plain = self._board(root / "plain", with_slice=False)
            mixed = self._board(root / "mixed", with_slice=True)
            plain_taxes = {r["adapter_name"]: r["robustness_tax"]
                           for r in plain["ranked"]}
            mixed_taxes = {r["adapter_name"]: r["robustness_tax"]
                           for r in mixed["ranked"]}
            self.assertEqual(plain_taxes["full-a"], 0.05)
            self.assertEqual(plain_taxes["full-b"], 0.05)
            self.assertEqual(mixed_taxes["full-a"],
                             plain_taxes["full-a"])
            self.assertEqual(mixed_taxes["full-b"],
                             plain_taxes["full-b"])

    def test_slice_row_prints_its_numbers_without_a_tax(self):
        with tempfile.TemporaryDirectory() as tmp:
            mixed = self._board(Path(tmp), with_slice=True)
            rows = {r["adapter_name"]: r for r in mixed["ranked"]}
            self.assertIn("slice-a", rows)
            self.assertEqual(rows["slice-a"]["asr_conditional"], 0.10)
            self.assertEqual(rows["slice-a"]["benign_accuracy"], 1.0)
            self.assertEqual(rows["slice-a"]["ece_attacked"], 0.001)
            self.assertIn("robustness_tax", rows["slice-a"])
            self.assertIsNone(rows["slice-a"]["robustness_tax"])

    def test_tied_populations_withhold_the_frontier(self):
        # Two suites tie for the top case count on one board:
        # no single frontier describes the board, so every tax is
        # withheld rather than blending populations that measured
        # different cases.
        from peira.dashboard import _apply_robustness_tax_column

        def row(name, suite, acc, ece):
            return {
                "adapter_name": name,
                "adapter_version": name + "-1.0",
                "suite": suite,
                "dataset_version": "1.0",
                "n_cases": 300,
                "asr_conditional": 0.2,
                "benign_accuracy": acc,
                "ece_attacked": ece,
            }

        rows = [
            row("v2-a", "v2", 0.90, 0.05),
            row("v2-b", "v2", 0.95, 0.10),
            row("v1-c", "v1", 0.99, 0.001),
        ]
        _apply_robustness_tax_column(rows)
        self.assertTrue(all(r["robustness_tax"] is None for r in rows))


class TestDisplayNameResolution(unittest.TestCase):
    """Rows carry the served model's name, not an adapter tag.

    The HF guardrail family seals an adapter release tag as
    adapter_version ("2.0", "125m"); the model is the class's
    HF_MODEL_ID, trusted only when the artifact's pinned
    hf_revision matches the class pin.
    """

    _PROTECTAI_PIN = "90c9989b1a342275dd0d1a95aad283c04e075671"
    _PROTECTAI_MODEL = "protectai/deberta-v3-base-prompt-injection-v2"

    def _hf_artifact(self, *, spec, hf_revision, adapter_version="2.0"):
        return _make_artifact(
            adapter_name="protectai-prompt-injection",
            adapter_version=adapter_version,
            config={"cache_enabled": False, "adapter_spec": spec},
            adapter_pins={
                "provider_snapshot": "",
                "hf_revision": hf_revision,
                "code_sha": "",
                "code_dirty": False,
            },
        )

    def test_hf_display_name_is_the_served_model(self):
        art = self._hf_artifact(
            spec="peira.adapters.hf:ProtectAIAdapter",
            hf_revision=self._PROTECTAI_PIN)
        from peira.dashboard import _display_name
        self.assertEqual(_display_name(art), self._PROTECTAI_MODEL)

    def test_hf_display_name_falls_back_on_revision_mismatch(self):
        # The class pin does not attest the weights this artifact
        # served, so the model name is not claimed: the sealed
        # version tag stands rather than a wrong model name.
        art = self._hf_artifact(
            spec="peira.adapters.hf:ProtectAIAdapter",
            hf_revision="0" * 40)
        from peira.dashboard import _display_name
        self.assertEqual(_display_name(art), "2.0")

    def test_hf_display_name_requires_the_running_adapter(self):
        # The spec is artifact-recorded text and the class pins
        # are public constants, so a spec naming another adapter's
        # class (here the Granite HAP class, with its real pin)
        # must not relabel this row with that adapter's model: the
        # resolved class must be the adapter that ran.
        art = self._hf_artifact(
            spec="peira.adapters.hf:GraniteGuardianHapAdapter",
            hf_revision="a76ccfd3ddb790fa7c23db58149bfec7ba1aa57f")
        from peira.dashboard import _display_name
        self.assertEqual(_display_name(art), "2.0")

    def test_display_name_falls_back_on_unresolvable_spec(self):
        art = self._hf_artifact(
            spec="peira.adapters.hf:NoSuchAdapterClass",
            hf_revision=self._PROTECTAI_PIN)
        from peira.dashboard import _display_name
        self.assertEqual(_display_name(art), "2.0")

    def test_display_name_falls_back_without_spec(self):
        art = _make_artifact(adapter_name="plain-adapter",
                             adapter_version="some-model-1.0")
        from peira.dashboard import _display_name
        self.assertEqual(_display_name(art), "some-model-1.0")

    def test_hf_row_on_the_board_carries_the_model_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            art = self._hf_artifact(
                spec="peira.adapters.hf:ProtectAIAdapter",
                hf_revision=self._PROTECTAI_PIN)
            (tmp_path / "hf.json").write_text(art.to_json())
            scan_runs(tmp)
            lb = leaderboard(tmp)
            self.assertEqual(lb["n_ranked"], 1)
            self.assertEqual(lb["ranked"][0]["display_name"],
                             self._PROTECTAI_MODEL)
            self.assertEqual(lb["ranked"][0]["adapter_version"], "2.0")

    def test_load_failure_row_still_resolves_the_model_name(self):
        # The identity-only fallback (the artifact file indexes
        # but fails strict loading) must not print the fragment
        # either: its display name resolves from the spec and pin
        # the file itself records.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            art = self._hf_artifact(
                spec="peira.adapters.hf:ProtectAIAdapter",
                hf_revision=self._PROTECTAI_PIN)
            d = json.loads(art.to_json())
            d["seed"] = "zero"  # strict loading rejects the type
            (tmp_path / "broken.json").write_text(json.dumps(d))
            scan_runs(tmp)
            lb = leaderboard(tmp)
            self.assertEqual(lb["n_ranked"], 0)
            self.assertEqual(lb["n_unranked"], 1)
            row = lb["unranked"][0]
            self.assertEqual(row["display_name"], self._PROTECTAI_MODEL)
            self.assertIn("load failed", row["reason"])

    def test_load_failure_row_falls_back_when_pin_unattested(self):
        # Same broken artifact, but the recorded pin does not
        # match the class pin: no model name is claimed.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            art = self._hf_artifact(
                spec="peira.adapters.hf:ProtectAIAdapter",
                hf_revision="0" * 40)
            d = json.loads(art.to_json())
            d["seed"] = "zero"
            (tmp_path / "broken.json").write_text(json.dumps(d))
            scan_runs(tmp)
            lb = leaderboard(tmp)
            self.assertEqual(lb["n_unranked"], 1)
            self.assertEqual(lb["unranked"][0]["display_name"], "2.0")


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
        self.assertIsNone(sev["flip_rate_ci95"])


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
        # metrics.paired_bootstrap_ci. Derives the expected fractions
        # from the metrics module's own draw-stream function
        # (_bootstrap_randbelow), so a drift in either module's stream
        # breaks this test.
        from peira.dashboard import pairwise_resample_ahead
        from peira.metrics import _bootstrap_randbelow

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._runs_dir_with_two_adapters(tmp_path)
            seed, n_boot = 7, 1500
            out = pairwise_resample_ahead(
                runs_dir=tmp_path, n_boot=n_boot, seed=seed
            )
            pair = out["pairs"]["adapter-a|adapter-b"]

            # Expected fractions from the metrics module's draw stream:
            # shared cases sorted, paired diffs via _bootstrap_randbelow.
            import random

            flips_a = [True] * 10 + [False] * 30
            flips_b = [True] * 30 + [False] * 10
            xs = [1.0 if f else 0.0 for f in flips_a]
            ys = [1.0 if f else 0.0 for f in flips_b]
            rng = random.Random(seed)
            randbelow = _bootstrap_randbelow(rng)
            ahead = behind = 0
            n = 40
            xs_get = xs.__getitem__
            ys_get = ys.__getitem__
            for _ in range(n_boot):
                idx = [randbelow(n) for _ in range(n)]
                diff = sum(map(xs_get, idx)) / n - sum(map(ys_get, idx)) / n
                if diff < 0:
                    ahead += 1
                elif diff > 0:
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


def _make_dashboard_artifact(adapter_name, results, adapter_version=None):
    """Minimal sealed artifact JSON with real results for dashboard tests.

    Pads results to 200 eligible cases (10 families x 20) with
    adapter-unique case IDs, so the artifact genuinely qualifies for
    the leaderboard (qualifies_for_leaderboard recomputes eligibility
    from sealed results). The padding IDs are adapter-specific, so
    pairwise shared-case counts are unaffected.
    """
    from peira.artifacts import RunArtifact
    from peira.env_fingerprint import collect_and_fingerprint

    # Pad to 200 eligible results if needed: top up existing families
    # with <20 cases, then add pad families. All padding IDs are
    # adapter-unique so pairwise shared-case counts are unaffected.
    from collections import Counter
    padded = list(results)
    fam_counts = Counter(r["family"] for r in padded)
    # Top up thin families to 20.
    for fam, cnt in list(fam_counts.items()):
        need = 20 - cnt
        for j in range(max(0, need)):
            padded.append(_result_entry(
                case_id=f"{adapter_name}-pad-{fam}-{j:03d}",
                family=fam,
                flipped=(j % 2 == 0),
                attacked=_call_record(
                    decision="deny" if j % 2 == 0 else "approve",
                    dispatch_index=1,
                ),
            ))
    # Pad with fresh families (20 cases each) until we reach >=200
    # total. May overshoot; overshoot is fine for eligibility.
    fi = 0
    while len(padded) < 200:
        for j in range(20):
            i = len(padded)
            padded.append(_result_entry(
                case_id=f"{adapter_name}-padf-{fi}-{j:03d}",
                family=f"padfam{fi}",
                flipped=(i % 2 == 0),
                attacked=_call_record(
                    decision="deny" if i % 2 == 0 else "approve",
                    dispatch_index=1,
                ),
            ))
        fi += 1
    families = sorted({r["family"] for r in padded})

    env, env_sha256 = collect_and_fingerprint()
    artifact = RunArtifact(
        adapter_name=adapter_name,
        adapter_version=(adapter_version if adapter_version is not None
                         else adapter_name + "-1.0-test"),
        suite="v1",
        dataset_version="1.2.1",
        manifest_sha256="abc123" * 10 + "abcd",
        seed=0,
        max_concurrency=8,
        env=env,
        env_sha256=env_sha256,
        config={"cache_enabled": False},
        results=padded,
        metrics={
            "ranking_eligible": True,
            "eligibility_notes": [],
            "required_families": families,
        },
    )
    return artifact.seal().to_json()


if __name__ == "__main__":
    unittest.main()
