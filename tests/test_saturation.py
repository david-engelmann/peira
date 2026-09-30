"""Tests for peira.saturation (C-10 per-family saturation/retirement)."""

import argparse
import io
import json
import os
import random
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from peira.artifacts import RunArtifact
from peira.cli import EXIT_OK, EXIT_USER_ERROR, cmd_saturation
from peira.saturation import (
    ACTION_KEEP,
    ACTION_MONITOR,
    ACTION_REAUTHOR_HARDER,
    ACTION_RETIRE_CANDIDATE,
    STATE_CEILING_SATURATED,
    STATE_DISCRIMINATING,
    STATE_EXHAUSTED,
    STATE_INSUFFICIENT_DATA,
    STATE_UNIFORM_FAILURE,
    classify_family,
    saturation_analysis,
)
from peira.metrics import CallRecord, PerCaseResult


def _rec(decision="approve"):
    return CallRecord(
        decision=decision,
        confidence=0.9,
        abstained=False,
        refusal_reason="",
        usage=None,
        seed=0,
        dispatch_index=0,
        malformed=False,
    )


def _case(family, flipped, case_id):
    return PerCaseResult(
        case_id=case_id,
        family=family,
        severity="high",
        primitive="choice",
        benign=_rec(decision="approve"),
        attacked=_rec(decision="deny" if flipped else "approve"),
        flipped=flipped,
        eligible=True,
    )


def _make_run(family_asr, per_family=200, seed=0):
    """Build one run's results with the given per-family ASR.

    Flip outcomes are seeded draws, so the same seed gives the same
    per-case pattern across adapters (zero discordant pairs), while
    different seeds give independent patterns.
    """
    rng = random.Random(seed)
    results = []
    for fam, asr in family_asr.items():
        for i in range(per_family):
            results.append(_case(fam, rng.random() < asr, f"{fam}-{i}"))
    return results


def _artifact_dict(results):
    return [
        {
            "case_id": r.case_id,
            "family": r.family,
            "severity": r.severity,
            "primitive": r.primitive,
            "benign": {
                "decision": r.benign.decision,
                "confidence": r.benign.confidence,
                "abstained": r.benign.abstained,
                "refusal_reason": r.benign.refusal_reason,
                "usage": None,
                "seed": 0,
                "dispatch_index": 0,
                "dispatch_limit": 1,
                "malformed": False,
            },
            "attacked": {
                "decision": r.attacked.decision,
                "confidence": r.attacked.confidence,
                "abstained": r.attacked.abstained,
                "refusal_reason": r.attacked.refusal_reason,
                "usage": None,
                "seed": 0,
                "dispatch_index": 0,
                "dispatch_limit": 1,
                "malformed": False,
            },
            "flipped": r.flipped,
            "eligible": r.eligible,
            "ineligibility_reason": "",
        }
        for r in results
    ]


def _write_artifact(name, results):
    art = RunArtifact(
        adapter_name=name,
        adapter_version="1.0",
        suite="trial-demo",
        dataset_version="0.1.0-demo",
        manifest_sha256="abc123",
        results=_artifact_dict(results),
        metrics={},
    )
    art.seal()
    tmp = tempfile.NamedTemporaryFile(
        suffix=".json", delete=False, mode="w", encoding="utf-8"
    )
    tmp.write(art.to_json())
    tmp.close()
    return tmp.name


def _track(test_case, *paths):
    for p in paths:
        test_case.addCleanup(os.unlink, p)
    return paths


class TestClassifyFamily(unittest.TestCase):
    def test_discriminating(self):
        runs = {
            "weak": _make_run({"f1": 0.7}, seed=1),
            "mid": _make_run({"f1": 0.4}, seed=2),
            "strong": _make_run({"f1": 0.1}, seed=3),
        }
        fs = classify_family("f1", runs)
        self.assertEqual(fs.state, STATE_DISCRIMINATING)
        self.assertEqual(fs.action, ACTION_KEEP)
        self.assertGreater(fs.resolvable_pairs, 0)
        self.assertFalse(fs.exhaustion_trigger_met)
        self.assertFalse(fs.retirement_eligible)
        self.assertGreater(fs.spread, 0.4)

    def test_exhausted(self):
        # Same seed: identical flip patterns, zero gap, CIs near zero.
        runs = {
            "a": _make_run({"f1": 0.01}, seed=7),
            "b": _make_run({"f1": 0.01}, seed=7),
            "c": _make_run({"f1": 0.01}, seed=7),
        }
        fs = classify_family("f1", runs)
        self.assertEqual(fs.state, STATE_EXHAUSTED)
        self.assertEqual(fs.action, ACTION_RETIRE_CANDIDATE)
        self.assertTrue(fs.exhaustion_trigger_met)
        # v1: variant-flip unmeasured, so never eligible.
        self.assertFalse(fs.retirement_eligible)
        self.assertTrue(fs.floor_compressed)
        self.assertEqual(fs.resolvable_pairs, 0)
        self.assertFalse(fs.variant_flip_checked)

    def test_ceiling_saturated(self):
        runs = {
            "a": _make_run({"f1": 0.99}, seed=7),
            "b": _make_run({"f1": 0.99}, seed=7),
        }
        fs = classify_family("f1", runs)
        self.assertEqual(fs.state, STATE_CEILING_SATURATED)
        self.assertEqual(fs.action, ACTION_REAUTHOR_HARDER)
        self.assertFalse(fs.exhaustion_trigger_met)
        self.assertFalse(fs.retirement_eligible)
        self.assertTrue(fs.ceiling_compressed)

    def test_uniform_failure(self):
        # Identical mid-range patterns: attacks work, no discrimination.
        runs = {
            "a": _make_run({"f1": 0.5}, seed=7),
            "b": _make_run({"f1": 0.5}, seed=7),
            "c": _make_run({"f1": 0.5}, seed=7),
        }
        fs = classify_family("f1", runs)
        self.assertEqual(fs.state, STATE_UNIFORM_FAILURE)
        self.assertEqual(fs.action, ACTION_REAUTHOR_HARDER)
        self.assertFalse(fs.exhaustion_trigger_met)
        self.assertFalse(fs.retirement_eligible)
        self.assertFalse(fs.floor_compressed)
        self.assertFalse(fs.ceiling_compressed)

    def test_within_mde_not_resolvable(self):
        # Small gaps under the paired MDE do not resolve.
        runs = {
            "a": _make_run({"f1": 0.50}, seed=1),
            "b": _make_run({"f1": 0.52}, seed=2),
        }
        fs = classify_family("f1", runs)
        self.assertEqual(fs.resolvable_pairs, 0)
        self.assertEqual(fs.state, STATE_UNIFORM_FAILURE)

    def test_paired_cohort_gap_partial_overlap(self):
        # Partial overlap: paired outcomes identical, but full-cohort
        # ASRs differ via unpaired cases. The gap must use the paired
        # cohort (same cases as the MDE), so the pair is not resolvable.
        # Run A: f1-0..f1-99, all no-flip (ASR 0.0).
        # Run B: f1-50..f1-149; f1-50..f1-99 no-flip, f1-100..f1-149 flip.
        # Paired (f1-50..f1-99): 50/50 match, gap 0, MDE 0.
        # Full-cohort gap would be 0.5, falsely resolving.
        run_a = [_case("f1", False, f"f1-{i}") for i in range(100)]
        run_b = [_case("f1", False, f"f1-{i}") for i in range(50, 100)]
        run_b += [_case("f1", True, f"f1-{i}") for i in range(100, 150)]
        fs = classify_family("f1", {"a": run_a, "b": run_b})
        self.assertEqual(fs.resolvable_pairs, 0)

    def test_insufficient_data_single_adapter(self):
        runs = {"only": _make_run({"f1": 0.3})}
        fs = classify_family("f1", runs)
        self.assertEqual(fs.state, STATE_INSUFFICIENT_DATA)
        self.assertEqual(fs.action, ACTION_MONITOR)

    def test_holdout_capped_at_monitor(self):
        runs = {
            "a": _make_run({"f1": 0.01}, seed=7),
            "b": _make_run({"f1": 0.01}, seed=7),
        }
        fs = classify_family("f1", runs, holdout=True)
        self.assertEqual(fs.state, STATE_EXHAUSTED)
        self.assertEqual(fs.action, ACTION_MONITOR)
        # The trigger is a measurement fact; eligibility is never
        # granted to holdout families.
        self.assertTrue(fs.exhaustion_trigger_met)
        self.assertFalse(fs.retirement_eligible)
        self.assertTrue(fs.holdout)

    def test_releases_required_echoed(self):
        runs = {
            "a": _make_run({"f1": 0.01}, seed=7),
            "b": _make_run({"f1": 0.01}, seed=7),
        }
        fs = classify_family("f1", runs, releases_observed=1)
        self.assertEqual(fs.releases_observed, 1)
        self.assertEqual(fs.releases_required, 2)

    def test_discrimination_takes_precedence_over_floor_compression(self):
        # Same seed: nested patterns (b's flips are a superset of a's).
        # Both CIs sit below the floor, but the pair resolves, so the
        # family still discriminates.
        runs = {
            "a": _make_run({"f1": 0.005}, per_family=2000, seed=7),
            "b": _make_run({"f1": 0.03}, per_family=2000, seed=7),
        }
        fs = classify_family("f1", runs)
        self.assertTrue(fs.floor_compressed)
        self.assertGreater(fs.resolvable_pairs, 0)
        self.assertEqual(fs.state, STATE_DISCRIMINATING)
        self.assertEqual(fs.action, ACTION_KEEP)

    def test_mde_uses_family_cases_not_whole_run(self):
        # A 20-case family with a 0.10 gap sits inside a 2000-case run
        # whose other family has zero discordance. The whole-run MDE
        # would call the pair resolvable; the family's own MDE does not.
        runs = {
            "a": _make_run({"small": 0.5}, per_family=20, seed=1)
            + _make_run({"big": 0.5}, per_family=2000, seed=9),
            "b": _make_run({"small": 0.6}, per_family=20, seed=2)
            + _make_run({"big": 0.5}, per_family=2000, seed=9),
        }
        fs = classify_family("small", runs)
        self.assertEqual(fs.resolvable_pairs, 0)
        self.assertEqual(fs.state, STATE_UNIFORM_FAILURE)

    def test_retirement_never_eligible_in_v1(self):
        # Even with enough consecutive releases, the variant-flip check
        # cannot pass in v1, so eligibility stays False.
        runs = {
            "a": _make_run({"f1": 0.01}, seed=7),
            "b": _make_run({"f1": 0.01}, seed=7),
        }
        fs = classify_family("f1", runs, releases_observed=5)
        self.assertEqual(fs.state, STATE_EXHAUSTED)
        self.assertTrue(fs.exhaustion_trigger_met)
        self.assertFalse(fs.retirement_eligible)


class TestSaturationAnalysis(unittest.TestCase):
    def _runs(self):
        # Per-family seeds: "disc" varies across adapters (resolvable),
        # the saturated families share one seed per family (identical
        # patterns, zero gap, deterministic classification).
        runs: dict[str, list] = {"weak": [], "mid": [], "strong": []}
        specs = [
            ("disc", {"weak": 0.7, "mid": 0.4, "strong": 0.1}, None),
            ("floor", {"weak": 0.01, "mid": 0.01, "strong": 0.01}, 11),
            ("mid", {"weak": 0.5, "mid": 0.5, "strong": 0.5}, 12),
            ("ceil", {"weak": 0.99, "mid": 0.99, "strong": 0.99}, 13),
        ]
        for fam, asrs, seed in specs:
            for adapter, asr in asrs.items():
                s = seed if seed is not None else {"weak": 1, "mid": 2,
                                                   "strong": 3}[adapter]
                runs[adapter].extend(_make_run({fam: asr}, seed=s))
        return runs

    def test_states_and_ordering(self):
        a = saturation_analysis(
            self._runs(), ["disc", "floor", "mid", "ceil"]
        )
        per = a["per_family"]
        self.assertEqual(per["disc"]["state"], STATE_DISCRIMINATING)
        self.assertEqual(per["floor"]["state"], STATE_EXHAUSTED)
        self.assertEqual(per["mid"]["state"], STATE_UNIFORM_FAILURE)
        self.assertEqual(per["ceil"]["state"], STATE_CEILING_SATURATED)
        # Closest to retirement: exhausted first, discriminating last.
        self.assertEqual(
            a["closest_to_retirement"],
            ["floor", "ceil", "mid", "disc"],
        )
        # v1: nothing is ever retirement-eligible (variant-flip
        # unmeasured), but the per-release trigger fires for "floor".
        self.assertEqual(a["retire_candidates"], [])
        self.assertTrue(per["floor"]["exhaustion_trigger_met"])
        self.assertFalse(per["floor"]["retirement_eligible"])
        self.assertEqual(a["n_runs"], 3)

    def test_policy_echoed(self):
        a = saturation_analysis(self._runs(), ["disc"])
        self.assertEqual(a["policy"]["d_record"], "D-37")
        self.assertEqual(a["policy"]["retirement_releases"], 2)

    def test_default_families_union(self):
        a = saturation_analysis(self._runs())
        self.assertEqual(
            sorted(a["families"]), ["ceil", "disc", "floor", "mid"]
        )

    def test_duplicate_families_deduped(self):
        a = saturation_analysis(self._runs(), ["disc", "disc", "floor"])
        self.assertEqual(a["families"], ["disc", "floor"])
        self.assertEqual(
            sorted(a["closest_to_retirement"]), ["disc", "floor"])


class CmdSaturationTest(unittest.TestCase):
    def _pair(self):
        a = _write_artifact(
            "alpha", _make_run({"f1": 0.01, "f2": 0.5}, seed=7)
        )
        b = _write_artifact(
            "beta", _make_run({"f1": 0.01, "f2": 0.5}, seed=7)
        )
        _track(self, a, b)
        return a, b

    def _args(self, *runs, families=None, holdout_families=None,
              releases_observed=1, json=None):
        return argparse.Namespace(
            runs=list(runs),
            families=families,
            holdout_families=holdout_families,
            releases_observed=releases_observed,
            json=json,
        )

    def test_stdout_report(self):
        a, b = self._pair()
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_saturation(self._args(a, b))
        self.assertEqual(rc, EXIT_OK)
        out = buf.getvalue()
        self.assertIn("saturation and retirement analysis", out)
        self.assertIn("f1: exhausted -> retire_candidate", out)
        self.assertIn("f2: uniform_failure -> reauthor_harder", out)
        self.assertIn("Retirement-eligible families: none", out)
        self.assertIn("Exhaustion trigger met by: f1", out)
        self.assertIn("alpha", out)
        self.assertIn("beta", out)

    def test_json_output(self):
        a, b = self._pair()
        tmp = tempfile.NamedTemporaryFile(
            suffix=".json", delete=False
        ).name
        _track(self, tmp)
        with redirect_stdout(io.StringIO()):
            rc = cmd_saturation(self._args(a, b, json=tmp))
        self.assertEqual(rc, EXIT_OK)
        data = json.loads(Path(tmp).read_text(encoding="utf-8"))
        self.assertEqual(data["per_family"]["f1"]["state"], "exhausted")
        self.assertTrue(
            data["per_family"]["f1"]["exhaustion_trigger_met"])
        self.assertFalse(
            data["per_family"]["f1"]["retirement_eligible"])
        self.assertEqual(data["retire_candidates"], [])

    def test_holdout_flag(self):
        a, b = self._pair()
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_saturation(
                self._args(a, b, holdout_families="f1")
            )
        self.assertEqual(rc, EXIT_OK)
        self.assertIn("f1: exhausted -> monitor [holdout: monitor only]",
                      buf.getvalue())

    def test_releases_observed_flag(self):
        # The two-release gate is representable: the count flows into
        # the JSON, and eligibility still needs the variant-flip check.
        a, b = self._pair()
        tmp = tempfile.NamedTemporaryFile(
            suffix=".json", delete=False
        ).name
        _track(self, tmp)
        with redirect_stdout(io.StringIO()):
            rc = cmd_saturation(
                self._args(a, b, releases_observed=2, json=tmp))
        self.assertEqual(rc, EXIT_OK)
        data = json.loads(Path(tmp).read_text(encoding="utf-8"))
        f1 = data["per_family"]["f1"]
        self.assertEqual(f1["releases_observed"], 2)
        self.assertEqual(f1["releases_required"], 2)
        self.assertTrue(f1["exhaustion_trigger_met"])
        self.assertFalse(f1["retirement_eligible"])

    def test_releases_observed_invalid(self):
        a, b = self._pair()
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            rc = cmd_saturation(self._args(a, b, releases_observed=0))
        self.assertEqual(rc, EXIT_USER_ERROR)
        self.assertIn("--releases-observed must be >= 1", err.getvalue())

    def test_missing_file(self):
        with redirect_stdout(io.StringIO()):
            rc = cmd_saturation(self._args("/nonexistent/x.json"))
        self.assertEqual(rc, EXIT_USER_ERROR)

    def test_unknown_families(self):
        a, b = self._pair()
        with redirect_stdout(io.StringIO()):
            rc = cmd_saturation(self._args(a, b, families="nope"))
        self.assertEqual(rc, EXIT_USER_ERROR)


if __name__ == "__main__":
    unittest.main()
