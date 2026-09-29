"""Tests for peira.economic_lottery (C-6 economic lottery index)."""

import argparse
import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from peira.economic_lottery import (
    economic_lottery_analysis,
    paired_stability_report,
    rank_runs_economic,
)
from peira.economics import load_cost_scenario
from peira.metrics import CallRecord, PerCaseResult


def _cli_rec(decision="approve"):
    return {
        "decision": decision,
        "confidence": 0.9,
        "abstained": False,
        "refusal_reason": "",
        "usage": None,
        "seed": 0,
        "dispatch_index": 0,
        "dispatch_limit": 1,
        "malformed": False,
    }


def _cli_args(*runs, families=None, json=None, economic=False, scenario=None):
    return argparse.Namespace(runs=list(runs), families=families, json=json,
                              economic=economic, scenario=scenario)


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


def _case(family, direction, case_id):
    """One eligible case flipping in the given M-1 direction.

    direction="cheap": benign approve -> attacked deny (approve-to-deny,
    $50 under the standard scenario). direction="jailbreak": benign deny
    -> attacked approve (deny-to-approve, $1000 under standard).
    """
    if direction == "cheap":
        benign, attacked = _rec("approve"), _rec("deny")
    elif direction == "jailbreak":
        benign, attacked = _rec("deny"), _rec("approve")
    else:
        raise ValueError(direction)
    return PerCaseResult(
        case_id=case_id,
        family=family,
        severity="high",
        primitive="choice",
        benign=benign,
        attacked=attacked,
        flipped=True,
        eligible=True,
    )


def _clean_case(family, case_id):
    r = _rec("approve")
    return PerCaseResult(
        case_id=case_id,
        family=family,
        severity="high",
        primitive="choice",
        benign=r,
        attacked=r,
        flipped=False,
        eligible=True,
    )


def _make_run(spec, per_family=200):
    """Build a run from {family: (n_cheap_flips, n_jailbreak_flips)}.

    200 cases per family keeps every run ranking-eligible, including
    under leave-one-out (mirrors tests/test_lottery.py).
    """
    results = []
    for fam, (n_cheap, n_jb) in spec.items():
        for i in range(per_family):
            if i < n_cheap:
                results.append(_case(fam, "cheap", f"{fam}-{i}"))
            elif i < n_cheap + n_jb:
                results.append(_case(fam, "jailbreak", f"{fam}-{i}"))
            else:
                results.append(_clean_case(fam, f"{fam}-{i}"))
    return results


CHEAP = "volume"
JB = "tail_risk"
NEUTRAL = "neutral"


def _disagreement_runs():
    """Runs where the ASR ranking and the economic ranking disagree.

    Flip *counts* are proportional across runs in every family, so the
    robustness (ASR) ranking is perfectly stable under family removal
    (lottery index 1.0). But run-1's tail_risk flips are catastrophic
    deny-to-approve jailbreaks ($1000 each under the standard scenario)
    while every other flip is a cheap $50 approve-to-deny: run-1 carries
    nearly all the dollars in the tail_risk family. Removing tail_risk
    decorrelates the economic ranking (tau 0.0, index 0.67, fragile)
    while the ASR ranking does not move at all.

    Flip totals: run-1=14, run-2=28, run-3=42, run-4=56
    -> ASR order run-1, run-2, run-3, run-4.
    Standard-scenario dollars: run-2=$1400, run-3=$2100, run-4=$2800,
    run-1=$4500 -> economic order run-2, run-3, run-4, run-1.
    """
    return {
        "run-1": _make_run(
            {CHEAP: (10, 0), JB: (0, 4), NEUTRAL: (0, 0)}
        ),
        "run-2": _make_run(
            {CHEAP: (20, 0), JB: (8, 0), NEUTRAL: (0, 0)}
        ),
        "run-3": _make_run(
            {CHEAP: (30, 0), JB: (12, 0), NEUTRAL: (0, 0)}
        ),
        "run-4": _make_run(
            {CHEAP: (40, 0), JB: (16, 0), NEUTRAL: (0, 0)}
        ),
    }


class RankRunsEconomicTest(unittest.TestCase):
    def test_ranks_by_e_attacked_ascending(self):
        scenario = load_cost_scenario("standard")
        runs = _disagreement_runs()
        ranked = rank_runs_economic(runs, [CHEAP, JB, NEUTRAL], scenario)
        order = [r.run_id for r in ranked if r.eligible]
        # run-1's 4 tail-risk flips are $1000 jailbreaks: worst economics
        # despite the fewest flips. The rest scale with flip counts.
        self.assertEqual(order, ["run-2", "run-3", "run-4", "run-1"])
        for r in ranked:
            if r.eligible:
                self.assertIsNotNone(r.e_attacked)
                self.assertGreaterEqual(r.e_attacked, 0.0)

    def test_differs_from_asr_ranking(self):
        # Sanity: the fixture really does separate the two rankings.
        from peira.lottery import rank_runs

        runs = _disagreement_runs()
        asr_order = [
            r.run_id for r in rank_runs(runs, [CHEAP, JB, NEUTRAL]) if r.eligible
        ]
        # By ASR: run-1 (14 flips) best through run-4 (56) worst.
        self.assertEqual(
            asr_order, ["run-1", "run-2", "run-3", "run-4"]
        )
        scenario = load_cost_scenario("standard")
        econ_order = [
            r.run_id
            for r in rank_runs_economic(runs, [CHEAP, JB, NEUTRAL], scenario)
            if r.eligible
        ]
        self.assertNotEqual(asr_order, econ_order)

    def test_empty_families_raises(self):
        scenario = load_cost_scenario("standard")
        with self.assertRaises(ValueError):
            rank_runs_economic(_disagreement_runs(), [], scenario)

    def test_ties_break_by_run_id(self):
        scenario = load_cost_scenario("standard")
        runs = {
            "b-run": _make_run({CHEAP: (10, 0)}),
            "a-run": _make_run({CHEAP: (10, 0)}),
        }
        ranked = rank_runs_economic(runs, [CHEAP], scenario)
        self.assertEqual(
            [r.run_id for r in ranked if r.eligible], ["a-run", "b-run"]
        )


class EconomicLotteryAnalysisTest(unittest.TestCase):
    def test_shape_and_scenario_identity(self):
        scenario = load_cost_scenario("standard")
        a = economic_lottery_analysis(
            _disagreement_runs(), [CHEAP, JB, NEUTRAL], scenario
        )
        self.assertEqual(a["scenario_id"], "standard")
        self.assertEqual(a["scenario_version"], 1)
        self.assertIn("attack_rate", a)
        self.assertEqual(a["n_runs"], 4)
        self.assertEqual(a["n_ranked"], 4)
        self.assertEqual(len(a["full_ranking"]), 4)
        self.assertIn(a["verdict"], ("stable", "mostly stable", "fragile", "undefined"))
        self.assertEqual(set(a["per_family"]), {CHEAP, JB, NEUTRAL})
        for fam, p in a["per_family"].items():
            self.assertTrue(p["tau"] is None or -1.0 <= p["tau"] <= 1.0)

    def test_jailbreak_family_moves_economic_ranking_most(self):
        scenario = load_cost_scenario("standard")
        a = economic_lottery_analysis(
            _disagreement_runs(), [CHEAP, JB, NEUTRAL], scenario
        )
        self.assertEqual(a["most_influential_family"], JB)

    def test_json_serializable(self):
        import json

        scenario = load_cost_scenario("standard")
        a = economic_lottery_analysis(
            _disagreement_runs(), [CHEAP, JB, NEUTRAL], scenario
        )
        self.assertEqual(json.loads(json.dumps(a)), a)


class CmdEconomicLotteryTest(unittest.TestCase):
    """End-to-end: peira lottery --economic over sealed run artifacts."""

    def _artifact_case(self, case_id, family, direction):
        if direction == "cheap":
            benign, attacked, flipped = "approve", "deny", True
        elif direction == "jailbreak":
            benign, attacked, flipped = "deny", "approve", True
        else:
            benign, attacked, flipped = "approve", "approve", False
        return {
            "case_id": case_id,
            "family": family,
            "severity": "high",
            "primitive": "choice",
            "benign": _cli_rec(benign),
            "attacked": _cli_rec(attacked),
            "flipped": flipped,
            "eligible": True,
            "ineligibility_reason": "",
        }

    def _write_run(self, name, spec):
        from peira.artifacts import RunArtifact

        cases = []
        for fam, (n_cheap, n_jb) in spec.items():
            for i in range(200):
                if i < n_cheap:
                    cases.append(
                        self._artifact_case(f"{fam}-{i}", fam, "cheap")
                    )
                elif i < n_cheap + n_jb:
                    cases.append(
                        self._artifact_case(f"{fam}-{i}", fam, "jailbreak")
                    )
                else:
                    cases.append(
                        self._artifact_case(f"{fam}-{i}", fam, "clean")
                    )
        art = RunArtifact(
            adapter_name=name,
            adapter_version="1.0",
            suite="trial-demo",
            dataset_version="0.1.0-demo",
            manifest_sha256="abc123",
            results=cases,
            metrics={},
        )
        art.seal()
        tmp = tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w", encoding="utf-8"
        )
        tmp.write(art.to_json())
        tmp.close()
        return tmp.name

    def _two_runs(self):
        a = self._write_run(
            "run-1", {CHEAP: (10, 0), JB: (0, 4), NEUTRAL: (0, 0)}
        )
        b = self._write_run(
            "run-2", {CHEAP: (20, 0), JB: (8, 0), NEUTRAL: (0, 0)}
        )
        return a, b

    def test_economic_stdout_reports_the_pair(self):
        from peira.cli import EXIT_OK, cmd_lottery

        a, b = self._two_runs()
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_lottery(_cli_args(a, b, economic=True))
        self.assertEqual(rc, EXIT_OK)
        out = buf.getvalue()
        self.assertIn("economic lottery index (C-6)", out)
        self.assertIn("Robustness ranking", out)
        self.assertIn("Economic ranking", out)
        # The pair is always reported; never a lone index.
        self.assertIn("[standard]", out)
        self.assertIn("[low-stakes]", out)
        self.assertIn("[high-stakes]", out)

    def test_economic_json_and_single_scenario(self):
        import json

        from peira.cli import EXIT_OK, cmd_lottery

        a, b = self._two_runs()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            out_path = f.name
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_lottery(
                _cli_args(a, b, economic=True, scenario="standard",
                          json=out_path)
            )
        self.assertEqual(rc, EXIT_OK)
        report = json.loads(Path(out_path).read_text(encoding="utf-8"))
        self.assertIn("robustness", report)
        self.assertIn("economic", report)
        self.assertEqual(set(report["pair"]), {"standard"})

    def test_economic_unknown_scenario_errors(self):
        from peira.cli import EXIT_USER_ERROR, cmd_lottery

        a, b = self._two_runs()
        err = io.StringIO()
        with redirect_stderr(err):
            rc = cmd_lottery(_cli_args(a, b, economic=True, scenario="nope"))
        self.assertEqual(rc, EXIT_USER_ERROR)
        self.assertIn("unknown cost scenario", err.getvalue())

    def test_scenario_without_economic_warns_and_ignores(self):
        from peira.cli import EXIT_OK, cmd_lottery

        a, b = self._two_runs()
        err = io.StringIO()
        buf = io.StringIO()
        with redirect_stderr(err), redirect_stdout(buf):
            rc = cmd_lottery(_cli_args(a, b, scenario="standard"))
        self.assertEqual(rc, EXIT_OK)
        self.assertIn("--scenario only applies with --economic", err.getvalue())
        # Plain R-09 path ran: no economic section in stdout.
        self.assertNotIn("Economic ranking", buf.getvalue())


class PairedStabilityReportTest(unittest.TestCase):
    def test_always_reports_the_pair_never_a_single_index(self):
        report = paired_stability_report(
            _disagreement_runs(), [CHEAP, JB, NEUTRAL]
        )
        # Both halves present; no top-level single lottery index.
        self.assertIn("robustness", report)
        self.assertIn("economic", report)
        self.assertIn("pair", report)
        self.assertNotIn("lottery_index", report)
        # Every scenario in the versioned file is covered by default.
        self.assertEqual(
            set(report["economic"]), {"low-stakes", "standard", "high-stakes"}
        )
        for sid, p in report["pair"].items():
            for key in (
                "robustness_index",
                "economic_index",
                "robustness_verdict",
                "economic_verdict",
                "disagree",
                "disagreement_note",
            ):
                self.assertIn(key, p, f"{sid} missing {key}")

    def test_detects_robustness_stable_economic_fragile(self):
        report = paired_stability_report(
            _disagreement_runs(), [CHEAP, JB, NEUTRAL], ["standard"]
        )
        p = report["pair"]["standard"]
        # Removing the tail_risk family leaves the ASR ranking untouched
        # (flip counts are proportional) but decorrelates the economic
        # ranking (run-1's dollars were concentrated there).
        self.assertTrue(p["disagree"])
        self.assertIsNotNone(p["disagreement_note"])
        self.assertIn("tail_risk", p["disagreement_note"])
        self.assertIn("dollar risk", p["disagreement_note"])

    def test_note_names_no_family_that_moved_nothing(self):
        # The robustness ranking does not move at all here (all taus
        # 1.0), so the note must not credit any family with moving it:
        # "neutral" is the alphabetical argmin, but nothing moved.
        report = paired_stability_report(
            _disagreement_runs(), [CHEAP, JB, NEUTRAL], ["standard"]
        )
        note = report["pair"]["standard"]["disagreement_note"]
        self.assertNotIn("neutral", note)
        self.assertIn("tail_risk", note)

    def test_no_disagreement_when_rankings_agree(self):
        # All flips cheap: the economic ranking tracks the ASR ranking.
        runs = {
            "adapter-a": _make_run({CHEAP: (60, 0), JB: (10, 0)}),
            "adapter-b": _make_run({CHEAP: (10, 0), JB: (5, 0)}),
        }
        report = paired_stability_report(runs, [CHEAP, JB], ["standard"])
        p = report["pair"]["standard"]
        self.assertFalse(p["disagree"])
        self.assertIsNone(p["disagreement_note"])

    def test_unknown_scenario_raises(self):
        with self.assertRaises(ValueError):
            paired_stability_report(
                _disagreement_runs(), [CHEAP, JB], ["nope"]
            )

    def test_empty_families_raises(self):
        with self.assertRaises(ValueError):
            paired_stability_report(_disagreement_runs(), [])

    def test_json_serializable(self):
        import json

        report = paired_stability_report(
            _disagreement_runs(), [CHEAP, JB, NEUTRAL]
        )
        self.assertEqual(json.loads(json.dumps(report)), report)


if __name__ == "__main__":
    unittest.main()
