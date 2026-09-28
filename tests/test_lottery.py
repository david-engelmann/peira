"""Tests for peira.lottery (R-09 leave-one-family-out ranking stability)."""

import argparse
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from peira.artifacts import RunArtifact
from peira.cli import EXIT_OK, EXIT_USER_ERROR, cmd_lottery
from peira.lottery import (
    kendall_tau,
    lottery_analysis,
    pairwise_swap_fraction,
    rank_runs,
    stability_verdict,
)
from peira.metrics import CallRecord, PerCaseResult


def _rec(decision="approve", malformed=False):
    return CallRecord(
        decision=decision,
        confidence=0.9,
        abstained=False,
        refusal_reason="",
        usage=None,
        seed=0,
        dispatch_index=0,
        malformed=malformed,
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


def _make_run(family_asr, per_family=200):
    """Build a run's results with the given per-family ASR.

    200 cases per family keeps every run ranking-eligible, including
    under leave-one-out (2 families x 200 = 400 total; removing one
    leaves 200, which still clears the >= 200 total and >= 20
    per-family gates; benign accuracy is 1.0, malformed rate 0).
    """
    results = []
    for fam, asr in family_asr.items():
        n_flip = int(round(asr * per_family))
        for i in range(per_family):
            results.append(_case(fam, i < n_flip, f"{fam}-{i}"))
    return results


class TestKendallTau(unittest.TestCase):
    def test_identical(self):
        self.assertEqual(
            kendall_tau(["a", "b", "c"], ["a", "b", "c"]), 1.0
        )

    def test_reversed(self):
        self.assertEqual(
            kendall_tau(["a", "b", "c"], ["c", "b", "a"]), -1.0
        )

    def test_single_swap(self):
        # One discordant pair out of three: (2-1)/3.
        tau = kendall_tau(["a", "b", "c"], ["a", "c", "b"])
        self.assertAlmostEqual(tau, 1 / 3, places=9)

    def test_partial_overlap(self):
        # Only a,b common and in the same order.
        self.assertEqual(kendall_tau(["a", "b", "c"], ["a", "b"]), 1.0)

    def test_insufficient_overlap_none(self):
        self.assertIsNone(kendall_tau(["a"], ["a"]))
        self.assertIsNone(kendall_tau(["a", "b"], ["c", "d"]))
        self.assertIsNone(kendall_tau([], []))

    def test_two_items(self):
        self.assertEqual(kendall_tau(["a", "b"], ["b", "a"]), -1.0)
        self.assertEqual(kendall_tau(["a", "b"], ["a", "b"]), 1.0)


class TestPairwiseSwapFraction(unittest.TestCase):
    def test_identical(self):
        self.assertEqual(
            pairwise_swap_fraction(["a", "b", "c"], ["a", "b", "c"]), 0.0
        )

    def test_reversed(self):
        self.assertEqual(
            pairwise_swap_fraction(["a", "b", "c"], ["c", "b", "a"]), 1.0
        )

    def test_single_swap(self):
        self.assertAlmostEqual(
            pairwise_swap_fraction(["a", "b", "c"], ["a", "c", "b"]),
            1 / 3,
            places=9,
        )

    def test_insufficient_overlap_none(self):
        self.assertIsNone(pairwise_swap_fraction(["a"], ["a"]))


class TestRankRuns(unittest.TestCase):
    def test_orders_by_asr_ascending(self):
        runs = {
            "run-high": _make_run({"f1": 0.8, "f2": 0.8}),
            "run-low": _make_run({"f1": 0.1, "f2": 0.1}),
            "run-mid": _make_run({"f1": 0.5, "f2": 0.5}),
        }
        ranked = rank_runs(runs, ["f1", "f2"])
        self.assertEqual(
            [r.run_id for r in ranked], ["run-low", "run-mid", "run-high"]
        )
        self.assertTrue(all(r.eligible for r in ranked))
        self.assertAlmostEqual(ranked[0].asr, 0.1, places=9)

    def test_ties_broken_by_run_id(self):
        runs = {
            "b-run": _make_run({"f1": 0.3, "f2": 0.3}),
            "a-run": _make_run({"f1": 0.3, "f2": 0.3}),
        }
        ranked = rank_runs(runs, ["f1", "f2"])
        self.assertEqual([r.run_id for r in ranked], ["a-run", "b-run"])

    def test_filters_to_given_families(self):
        runs = {"r": _make_run({"f1": 0.0, "f2": 1.0})}
        ranked = rank_runs(runs, ["f1"])
        self.assertAlmostEqual(ranked[0].asr, 0.0, places=9)

    def test_ineligible_run_excluded_with_reasons(self):
        # Only 10 eligible cases per family: fails the >= 20 gate and
        # the >= 200 total gate.
        small = []
        for fam in ("f1", "f2"):
            for i in range(10):
                small.append(_case(fam, False, f"{fam}-{i}"))
        ranked = rank_runs({"tiny": small}, ["f1", "f2"])
        self.assertFalse(ranked[0].eligible)
        self.assertIsNone(ranked[0].asr)
        self.assertTrue(ranked[0].reasons)

    def test_empty_families_raises(self):
        with self.assertRaises(ValueError):
            rank_runs({"r": _make_run({"f1": 0.5})}, [])

    def test_empty_run_id_raises(self):
        with self.assertRaises(ValueError):
            rank_runs({"": _make_run({"f1": 0.5})}, ["f1"])


class TestStabilityVerdict(unittest.TestCase):
    def test_bands(self):
        self.assertEqual(stability_verdict(1.0), "stable")
        self.assertEqual(stability_verdict(0.9), "stable")
        self.assertEqual(stability_verdict(0.8999), "mostly stable")
        self.assertEqual(stability_verdict(0.7), "mostly stable")
        self.assertEqual(stability_verdict(0.6999), "fragile")
        self.assertEqual(stability_verdict(-1.0), "fragile")
        self.assertEqual(stability_verdict(None), "undefined")


class TestLotteryAnalysis(unittest.TestCase):
    def test_stable_rankings_index_one(self):
        # Every run has the same ASR in every family: removing any
        # family cannot move the ranking.
        runs = {
            "a": _make_run({"f1": 0.1, "f2": 0.1}),
            "b": _make_run({"f1": 0.5, "f2": 0.5}),
            "c": _make_run({"f1": 0.9, "f2": 0.9}),
        }
        out = lottery_analysis(runs, ["f1", "f2"])
        self.assertEqual(out["full_ranking"], ["a", "b", "c"])
        self.assertEqual(out["lottery_index"], 1.0)
        self.assertEqual(out["verdict"], "stable")
        self.assertEqual(out["min_tau"], 1.0)
        for fam in ("f1", "f2"):
            self.assertEqual(out["per_family"][fam]["tau"], 1.0)
            self.assertEqual(out["per_family"][fam]["swap_fraction"], 0.0)
            self.assertEqual(out["per_family"][fam]["max_rank_displacement"], 0)

    def test_detects_influential_family(self):
        # A: strong on f1, weak on f2. B: weak on f1, strong on f2.
        # C: middling on both. Full ranking ties A/B on 0.25, broken
        # by run id -> [a, b, c].
        runs = {
            "a": _make_run({"f1": 0.0, "f2": 0.5}),
            "b": _make_run({"f1": 0.5, "f2": 0.0}),
            "c": _make_run({"f1": 0.4, "f2": 0.4}),
        }
        out = lottery_analysis(runs, ["f1", "f2"])
        self.assertEqual(out["full_ranking"], ["a", "b", "c"])
        # Remove f1 -> [b, c, a]: pairs (a,b) and (a,c) discordant.
        # (taus are rounded to 4 decimals in the report dict.)
        self.assertAlmostEqual(
            out["per_family"]["f1"]["tau"], round(-1 / 3, 4), places=9
        )
        # Remove f2 -> [a, c, b]: only (b,c) discordant.
        self.assertAlmostEqual(
            out["per_family"]["f2"]["tau"], round(1 / 3, 4), places=9
        )
        self.assertAlmostEqual(out["lottery_index"], 0.0, places=9)
        self.assertAlmostEqual(out["min_tau"], round(-1 / 3, 4), places=9)
        self.assertEqual(out["most_influential_family"], "f1")
        self.assertEqual(
            out["per_family"]["f1"]["ranking"], ["b", "c", "a"]
        )
        self.assertEqual(
            out["per_family"]["f1"]["max_rank_displacement"], 2
        )

    def test_leave_one_out_regates_eligibility(self):
        # Run "thin" has 200 eligible cases in f1 but only 25 in f2:
        # eligible overall (225 total >= 200, both families >= 20),
        # but dropping f1 leaves it under the total gate -> it drops
        # out of that reduced ranking honestly.
        thin = _make_run({"f1": 0.2}, per_family=200)
        for i in range(25):
            thin.append(_case("f2", False, f"f2-{i}"))
        runs = {
            "thin": thin,
            "solid": _make_run({"f1": 0.6, "f2": 0.6}),
        }
        out = lottery_analysis(runs, ["f1", "f2"])
        # Full ranking: thin (asr ~0.178) beats solid (0.6).
        self.assertEqual(out["full_ranking"], ["thin", "solid"])
        drop_f1 = out["per_family"]["f1"]
        self.assertEqual(drop_f1["ranking"], ["solid"])
        self.assertEqual(drop_f1["dropped_runs"], ["thin"])
        # Only "solid" is common to both rankings: tau undefined.
        self.assertIsNone(drop_f1["tau"])
        # f2's removal keeps both runs: tau defined.
        self.assertIsNotNone(out["per_family"]["f2"]["tau"])

    def test_result_is_json_serializable(self):
        import json

        runs = {
            "a": _make_run({"f1": 0.2, "f2": 0.3}),
            "b": _make_run({"f1": 0.7, "f2": 0.6}),
        }
        out = lottery_analysis(runs, ["f1", "f2"])
        json.dumps(out)  # must not raise

    def test_empty_families_raises(self):
        with self.assertRaises(ValueError):
            lottery_analysis({"a": _make_run({"f1": 0.5})}, [])

    def test_single_family(self):
        # Degenerate but honest: one family, removing it leaves no
        # families -> rank_runs raises ValueError. Surface it plainly.
        runs = {"a": _make_run({"f1": 0.2})}
        with self.assertRaises(ValueError):
            lottery_analysis(runs, ["f1"])


# ---------------------------------------------------------------------------
# CLI surface: `peira lottery` across run artifacts.
# ---------------------------------------------------------------------------


def _lrec(decision="approve", confidence=0.9, malformed=False):
    """CallRecord as a plain dict, for sealed test artifacts."""
    return {
        "decision": decision,
        "confidence": confidence,
        "abstained": False,
        "refusal_reason": "",
        "seed": 0,
        "dispatch_index": 0,
        "malformed": malformed,
        "dispatch_limit": 1,
        "usage": None,
    }


def _lcase(case_id, family, flipped):
    """PerCaseResult as a plain dict, for sealed test artifacts."""
    return {
        "case_id": case_id,
        "family": family,
        "severity": "high",
        "primitive": "choice",
        "benign": _lrec(decision="approve"),
        "attacked": _lrec(decision="deny" if flipped else "approve"),
        "flipped": flipped,
        "eligible": True,
        "ineligibility_reason": "",
    }


def _lrun(family_asr, per_family=200):
    """Artifact-ready results with the given per-family ASR.

    200 cases per family keeps every run ranking-eligible, including
    under leave-one-out (2 families x 200 = 400 total; removing one
    leaves 200, which still clears the >= 200 total and >= 20
    per-family gates).
    """
    cases = []
    for fam, asr in family_asr.items():
        n_flip = int(round(asr * per_family))
        for i in range(per_family):
            cases.append(_lcase(f"{fam}-{i}", fam, i < n_flip))
    return cases


def _lartifact(name, cases):
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
    return art


def _lwrite(art):
    tmp = tempfile.NamedTemporaryFile(
        suffix=".json", delete=False, mode="w", encoding="utf-8")
    tmp.write(art.to_json())
    tmp.close()
    return tmp.name


def _largs(*runs, families=None, json=None):
    return argparse.Namespace(runs=list(runs), families=families, json=json)


class CmdLotteryTest(unittest.TestCase):
    def _pair(self):
        a = _lwrite(_lartifact("alpha", _lrun({"f1": 0.1, "f2": 0.1})))
        b = _lwrite(_lartifact("beta", _lrun({"f1": 0.5, "f2": 0.5})))
        return a, b

    def test_stdout_report(self):
        a, b = self._pair()
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_lottery(_largs(a, b))
        self.assertEqual(rc, EXIT_OK)
        out = buf.getvalue()
        self.assertIn("Peira leave-one-family-out ranking stability", out)
        self.assertIn("Lottery index: 1.0000", out)
        self.assertIn("rankings are stable", out)
        self.assertIn("alpha", out)
        self.assertIn("beta", out)
        self.assertIn("Most influential family", out)
        self.assertIn("Per-family leave-one-out:", out)

    def test_undefined_index_report(self):
        # A single run cannot yield a comparable pair: the report says
        # so instead of printing a number.
        a = _lwrite(_lartifact("solo", _lrun({"f1": 0.2, "f2": 0.3})))
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_lottery(_largs(a))
        self.assertEqual(rc, EXIT_OK)
        self.assertIn("Lottery index: undefined", buf.getvalue())

    def test_missing_file(self):
        a, _ = self._pair()
        err = io.StringIO()
        with redirect_stderr(err):
            rc = cmd_lottery(_largs(a, "/nonexistent/b.json"))
        self.assertEqual(rc, EXIT_USER_ERROR)
        self.assertIn("not found", err.getvalue())

    def test_invalid_artifact(self):
        a, _ = self._pair()
        with tempfile.NamedTemporaryFile(
                suffix=".json", delete=False, mode="w",
                encoding="utf-8") as f:
            f.write("{not valid json")
            bad = f.name
        err = io.StringIO()
        with redirect_stderr(err):
            rc = cmd_lottery(_largs(a, bad))
        self.assertEqual(rc, EXIT_USER_ERROR)
        self.assertIn("is not a valid run artifact", err.getvalue())

    def test_undecodable_results(self):
        # Tamper BEFORE sealing so the artifact verifies: an
        # out-of-range confidence is numeric (passes the artifact
        # loader) but fails PerCaseResult.from_dict's unit-interval
        # check, exercising the decode-error path.
        cases = _lrun({"f1": 0.2, "f2": 0.3})
        bad_case = dict(cases[0])
        bad_benign = dict(bad_case["benign"])
        bad_benign["confidence"] = 1.5
        bad_case["benign"] = bad_benign
        a = _lwrite(_lartifact("alpha", [bad_case] + cases[1:]))
        err = io.StringIO()
        with redirect_stderr(err):
            rc = cmd_lottery(_largs(a))
        self.assertEqual(rc, EXIT_USER_ERROR)
        self.assertIn("cannot decode per-case results", err.getvalue())

    def test_no_families_in_runs(self):
        a = _lwrite(_lartifact("empty", []))
        err = io.StringIO()
        with redirect_stderr(err):
            rc = cmd_lottery(_largs(a))
        self.assertEqual(rc, EXIT_USER_ERROR)
        self.assertIn("no families found in the given runs", err.getvalue())

    def test_single_family_errors(self):
        # One family via --families: leave-one-out leaves nothing to
        # rank, and rank_runs says so.
        a = _lwrite(_lartifact("alpha", _lrun({"f1": 0.2, "f2": 0.3})))
        err = io.StringIO()
        with redirect_stderr(err):
            rc = cmd_lottery(_largs(a, families="f1"))
        self.assertEqual(rc, EXIT_USER_ERROR)
        self.assertIn("rank_runs: families must not be empty",
                      err.getvalue())

    def test_unknown_families_error(self):
        # A typo'd family name must fail loudly, not silently analyze
        # an empty family set.
        a, b = self._pair()
        err = io.StringIO()
        with redirect_stderr(err):
            rc = cmd_lottery(_largs(a, b, families="f1,f9"))
        self.assertEqual(rc, EXIT_USER_ERROR)
        self.assertIn("unknown families: f9", err.getvalue())

    def test_duplicate_adapter_name_suffix(self):
        a = _lwrite(_lartifact("alpha", _lrun({"f1": 0.1, "f2": 0.1})))
        b = _lwrite(_lartifact("alpha", _lrun({"f1": 0.5, "f2": 0.5})))
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = cmd_lottery(_largs(a, b))
        self.assertEqual(rc, EXIT_OK)
        self.assertIn("note: duplicate adapter name 'alpha': using "
                      "'alpha#2'", err.getvalue())
        # Both runs still rank under distinct ids.
        self.assertIn("alpha#2", out.getvalue())

    def test_json_write_path(self):
        a, b = self._pair()
        with tempfile.TemporaryDirectory() as td:
            out = str(Path(td) / "lottery.json")
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                rc = cmd_lottery(_largs(a, b, json=out))
            self.assertEqual(rc, EXIT_OK)
            self.assertIn(f"lottery: {out}", stdout.getvalue())
            analysis = json.loads(Path(out).read_text(encoding="utf-8"))
            self.assertEqual(analysis["lottery_index"], 1.0)
            self.assertEqual(analysis["verdict"], "stable")
            self.assertEqual(analysis["full_ranking"], ["alpha", "beta"])

    def test_json_write_error(self):
        a, b = self._pair()
        bad = "/nonexistent-dir-xyz/lottery.json"
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            rc = cmd_lottery(_largs(a, b, json=bad))
        self.assertEqual(rc, EXIT_USER_ERROR)
        self.assertIn("cannot write lottery JSON to", err.getvalue())


if __name__ == "__main__":
    unittest.main()
