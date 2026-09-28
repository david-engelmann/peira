"""Tests for `peira.hardness`: M-4 hardness stratification + transfer ASR.

Builds synthetic per-case results with known flip patterns and checks
the flip distribution, hardest-decile survival, transfer matrices (overall
and per family), the mean off-diagonal summary, and the CLI surface.
"""

import argparse
import json
import tempfile
import unittest
from pathlib import Path

from peira.artifacts import RunArtifact
from peira.cli import EXIT_OK, EXIT_USER_ERROR, cmd_hardness
from peira.hardness import (
    analyze_runs,
    flip_distribution,
    hardest_decile_survival,
    report_text,
    transfer_matrix,
)
from peira.metrics import PerCaseResult


def _rec(decision="approve", confidence=0.9):
    return {
        "decision": decision,
        "confidence": confidence,
        "abstained": False,
        "refusal_reason": "",
        "seed": 0,
        "dispatch_index": 0,
        "malformed": False,
        "dispatch_limit": 1,
        "usage": {
            "model": "test-model",
            "tokens_in": 10,
            "tokens_out": 5,
            "latency_ms": 50.0,
            "cost_usd": 0.001,
        },
    }


def _case(case_id, family="fam", eligible=True, flipped=False):
    return {
        "case_id": case_id,
        "family": family,
        "severity": "high",
        "primitive": "choice",
        "benign": _rec(),
        "attacked": _rec(),
        "flipped": flipped,
        "eligible": eligible,
        "ineligibility_reason": "" if eligible else "benign_wrong_decision",
    }


def _results(cases):
    return [PerCaseResult.from_dict(c) for c in cases]


def _artifact(name, cases, suite="trial-demo"):
    art = RunArtifact(
        adapter_name=name,
        adapter_version="1.0",
        suite=suite,
        dataset_version="0.1.0-demo",
        manifest_sha256="abc123",
        results=cases,
        metrics={},
    )
    art.seal()
    return art


def _write(art):
    tmp = tempfile.NamedTemporaryFile(
        suffix=".json", delete=False, mode="w", encoding="utf-8")
    tmp.write(art.to_json())
    tmp.close()
    return tmp.name


def _ns(**kw):
    base = {"runs": [], "out": None}
    base.update(kw)
    return argparse.Namespace(**base)


class FlipDistributionTest(unittest.TestCase):
    def test_two_adapters_known_pattern(self):
        # 4 cases: c1 flipped by neither, c2 by A only, c3 by B only,
        # c4 by both.
        a = _results([
            _case("c1"), _case("c2", flipped=True),
            _case("c3"), _case("c4", flipped=True),
        ])
        b = _results([
            _case("c1"), _case("c2"),
            _case("c3", flipped=True), _case("c4", flipped=True),
        ])
        d = flip_distribution({"a": a, "b": b})
        self.assertEqual(d.adapters, ("a", "b"))
        self.assertEqual(d.n_cases, 4)
        self.assertEqual(d.counts, (1, 2, 1))
        self.assertEqual(d.fractions, (0.25, 0.5, 0.25))

    def test_ineligible_cases_excluded_from_universe(self):
        # c2 ineligible for b: universe is {c1, c3}.
        a = _results([_case("c1"), _case("c2", flipped=True), _case("c3")])
        b = _results([
            _case("c1"), _case("c2", eligible=False), _case("c3", flipped=True),
        ])
        d = flip_distribution({"a": a, "b": b})
        self.assertEqual(d.n_cases, 2)
        self.assertEqual(d.counts, (1, 1, 0))

    def test_ineligible_flip_does_not_count(self):
        # a "flipped" c1 but c1 is ineligible for a: no flip counted.
        a = _results([_case("c1", eligible=False, flipped=True)])
        b = _results([_case("c1")])
        d = flip_distribution({"a": a, "b": b})
        self.assertEqual(d.n_cases, 0)
        self.assertEqual(d.counts, (0, 0, 0))
        self.assertEqual(d.fractions, (0.0, 0.0, 0.0))

    def test_single_adapter(self):
        a = _results([_case("c1", flipped=True), _case("c2")])
        d = flip_distribution({"a": a})
        self.assertEqual(d.counts, (1, 1))

    def test_empty(self):
        d = flip_distribution({})
        self.assertEqual(d.adapters, ())
        self.assertEqual(d.n_cases, 0)
        self.assertEqual(d.counts, (0,))

    def test_to_dict_roundtrip(self):
        a = _results([_case("c1", flipped=True)])
        d = flip_distribution({"a": a})
        dd = d.to_dict()
        self.assertEqual(dd["adapters"], ["a"])
        self.assertEqual(dd["n_cases"], 1)
        self.assertEqual(dd["counts"], [0, 1])
        self.assertEqual(dd["fractions"], [0.0, 1.0])


class HardestDecileTest(unittest.TestCase):
    def _ten_cases(self):
        # 10 cases, flip counts: c1..c3 flipped by both (k=2),
        # c4..c6 by a only (k=1), c7..c10 by neither (k=0).
        a, b = [], []
        for i in range(1, 11):
            cid = f"c{i}"
            fa = i <= 6
            fb = i <= 3
            a.append(_case(cid, flipped=fa))
            b.append(_case(cid, flipped=fb))
        return {"a": _results(a), "b": _results(b)}

    def test_decile_is_hardest(self):
        r = hardest_decile_survival(self._ten_cases())
        # 10 cases -> decile size 1: the single hardest case.
        self.assertEqual(r.n_cases, 10)
        self.assertEqual(r.decile_size, 1)
        # Hardest cases are c1..c3 (k=2); tie broken by case_id -> c1.
        self.assertEqual(r.decile_case_ids, ("c1",))
        # c1 flipped by both -> neither survives.
        self.assertEqual(r.survived, {"a": 0, "b": 0})
        self.assertEqual(r.rates, {"a": 0.0, "b": 0.0})

    def test_survival_counts_non_flips(self):
        # 20 cases: c01..c02 flipped by both, rest clean.
        a, b = [], []
        for i in range(1, 21):
            cid = f"c{i:02d}"
            f = i <= 2
            a.append(_case(cid, flipped=f))
            b.append(_case(cid, flipped=f))
        r = hardest_decile_survival({"a": _results(a), "b": _results(b)})
        self.assertEqual(r.decile_size, 2)
        self.assertEqual(r.decile_case_ids, ("c01", "c02"))
        self.assertEqual(r.survived, {"a": 0, "b": 0})

    def test_partial_survival(self):
        # a flips the two hardest, b flips only one of them.
        a = _results([_case("c1", flipped=True), _case("c2", flipped=True)])
        b = _results([_case("c1", flipped=True), _case("c2")])
        r = hardest_decile_survival({"a": a, "b": b})
        self.assertEqual(r.decile_size, 1)
        self.assertEqual(r.decile_case_ids, ("c1",))
        self.assertEqual(r.survived, {"a": 0, "b": 0})

    def test_decile_rounds_up(self):
        # 5 cases -> ceil(0.5) = 1.
        a = _results([_case(f"c{i}", flipped=(i == 1)) for i in range(1, 6)])
        b = _results([_case(f"c{i}") for i in range(1, 6)])
        r = hardest_decile_survival({"a": a, "b": b})
        self.assertEqual(r.decile_size, 1)
        self.assertEqual(r.decile_case_ids, ("c1",))

    def test_custom_decile(self):
        a = _results([_case(f"c{i}", flipped=(i <= 2)) for i in range(1, 11)])
        b = _results([_case(f"c{i}") for i in range(1, 11)])
        r = hardest_decile_survival({"a": a, "b": b}, decile=0.2)
        self.assertEqual(r.decile_size, 2)

    def test_bad_decile_rejected(self):
        a = _results([_case("c1")])
        with self.assertRaises(ValueError):
            hardest_decile_survival({"a": a}, decile=0)
        with self.assertRaises(ValueError):
            hardest_decile_survival({"a": a}, decile=1.5)

    def test_empty_rates_none(self):
        r = hardest_decile_survival({})
        self.assertEqual(r.decile_size, 0)
        self.assertEqual(r.rates, {})


class TransferMatrixTest(unittest.TestCase):
    def test_known_transfer(self):
        # a flips c1, c2, c3; b flips c1, c2 (of those); c flips c1.
        # transfer a->b = 2/3, a->c = 1/3, b->a = 2/2 = 1.0.
        a = _results([_case(f"c{i}", flipped=(i <= 3)) for i in range(1, 5)])
        b = _results([_case(f"c{i}", flipped=(i <= 2)) for i in range(1, 5)])
        c = _results([_case(f"c{i}", flipped=(i == 1)) for i in range(1, 5)])
        t = transfer_matrix({"a": a, "b": b, "c": c})
        self.assertAlmostEqual(t.rate("a", "b"), 2 / 3)
        self.assertAlmostEqual(t.rate("a", "c"), 1 / 3)
        self.assertAlmostEqual(t.rate("b", "a"), 1.0)
        self.assertAlmostEqual(t.rate("b", "c"), 0.5)
        self.assertAlmostEqual(t.rate("c", "a"), 1.0)
        # Diagonal is 1.0 by construction.
        self.assertEqual(t.rate("a", "a"), 1.0)
        self.assertEqual(t.flipped_by_source["a"], 3)
        self.assertEqual(t.flipped_by_source["b"], 2)
        self.assertEqual(t.flipped_by_source["c"], 1)

    def test_no_source_flips_gives_none(self):
        a = _results([_case("c1"), _case("c2")])
        b = _results([_case("c1", flipped=True), _case("c2")])
        t = transfer_matrix({"a": a, "b": b})
        self.assertIsNone(t.rate("a", "b"))
        self.assertAlmostEqual(t.rate("b", "a"), 0.0)
        # Only b->a defined (0.0); a->b undefined -> mean over defined only.
        self.assertAlmostEqual(t.mean_off_diagonal, 0.0)

    def test_pairwise_eligibility(self):
        # c2 ineligible for b: transfer a->b uses {c1, c3} only.
        a = _results([
            _case("c1", flipped=True), _case("c2", flipped=True),
            _case("c3", flipped=True),
        ])
        b = _results([
            _case("c1", flipped=True), _case("c2", eligible=False),
            _case("c3"),
        ])
        t = transfer_matrix({"a": a, "b": b})
        self.assertAlmostEqual(t.rate("a", "b"), 0.5)

    def test_family_filter(self):
        a = _results([
            _case("c1", family="f1", flipped=True),
            _case("c2", family="f2", flipped=True),
        ])
        b = _results([
            _case("c1", family="f1", flipped=True),
            _case("c2", family="f2"),
        ])
        t1 = transfer_matrix({"a": a, "b": b}, family="f1")
        self.assertEqual(t1.family, "f1")
        self.assertAlmostEqual(t1.rate("a", "b"), 1.0)
        t2 = transfer_matrix({"a": a, "b": b}, family="f2")
        self.assertAlmostEqual(t2.rate("a", "b"), 0.0)
        t_none = transfer_matrix({"a": a, "b": b}, family="nope")
        self.assertIsNone(t_none.rate("a", "b"))

    def test_mean_off_diagonal_none_when_empty(self):
        t = transfer_matrix({})
        self.assertIsNone(t.mean_off_diagonal)

    def test_to_dict(self):
        a = _results([_case("c1", flipped=True)])
        b = _results([_case("c1", flipped=True)])
        t = transfer_matrix({"a": a, "b": b})
        dd = t.to_dict()
        self.assertEqual(dd["adapters"], ["a", "b"])
        self.assertIsNone(dd["family"])
        self.assertEqual(dd["rates"]["a -> b"], 1.0)
        self.assertEqual(dd["rates"]["a -> a"], 1.0)
        self.assertAlmostEqual(dd["mean_off_diagonal"], 1.0)


class AnalyzeRunsTest(unittest.TestCase):
    def test_full_report(self):
        a = _results([
            _case("c1", family="f1", flipped=True),
            _case("c2", family="f1"),
            _case("c3", family="f2", flipped=True),
        ])
        b = _results([
            _case("c1", family="f1", flipped=True),
            _case("c2", family="f1", flipped=True),
            _case("c3", family="f2"),
        ])
        rep = analyze_runs({"mock-a": a, "mock-b": b})
        self.assertEqual(rep.adapters, ("mock-a", "mock-b"))
        self.assertEqual(rep.n_cases, 3)
        self.assertEqual(rep.flip_distribution.counts, (0, 2, 1))
        self.assertEqual(set(rep.transfer_by_family), {"f1", "f2"})
        self.assertAlmostEqual(
            rep.transfer_by_family["f1"].rate("mock-a", "mock-b"), 1.0)
        dd = rep.to_dict()
        self.assertEqual(dd["n_cases"], 3)
        self.assertIn("flip_distribution", dd)
        self.assertIn("hardest_decile", dd)
        self.assertIn("transfer_overall", dd)
        self.assertIn("transfer_by_family", dd)

    def test_report_text_is_diagnostic(self):
        a = _results([_case("c1", flipped=True), _case("c2")])
        b = _results([_case("c1"), _case("c2", flipped=True)])
        rep = analyze_runs({"a": a, "b": b})
        text = report_text(rep)
        self.assertIn("Diagnostic only", text)
        self.assertIn("never rank", text)
        self.assertIn("Flip distribution", text)
        self.assertIn("Hardest-decile survival", text)
        self.assertIn("Transfer ASR matrix", text)
        self.assertIn("mean off-diagonal transfer", text)
        self.assertIn("Per-family transfer", text)

    def test_report_text_empty(self):
        rep = analyze_runs({})
        text = report_text(rep)
        self.assertIn("(none)", text)


class CliHardnessTest(unittest.TestCase):
    def test_stdout_tables(self):
        a = _write(_artifact("mock-a", [
            _case("c1", flipped=True), _case("c2"),
        ]))
        b = _write(_artifact("mock-b", [
            _case("c1", flipped=True), _case("c2", flipped=True),
        ]))
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_hardness(_ns(runs=[a, b]))
        self.assertEqual(rc, EXIT_OK)
        out = buf.getvalue()
        self.assertIn("hardness and transfer diagnostics", out)
        self.assertIn("mock-a", out)
        self.assertIn("mock-b", out)

    def test_out_file(self):
        a = _write(_artifact("mock-a", [_case("c1", flipped=True)]))
        b = _write(_artifact("mock-b", [_case("c1")]))
        with tempfile.TemporaryDirectory() as td:
            out = str(Path(td) / "hard.txt")
            rc = cmd_hardness(_ns(runs=[a, b], out=out))
            self.assertEqual(rc, EXIT_OK)
            self.assertIn("Transfer ASR matrix", Path(out).read_text())

    def test_missing_file(self):
        rc = cmd_hardness(_ns(runs=["/nonexistent/x.json"]))
        self.assertEqual(rc, EXIT_USER_ERROR)

    def test_needs_two_runs(self):
        a = _write(_artifact("mock-a", [_case("c1")]))
        rc = cmd_hardness(_ns(runs=[a]))
        self.assertEqual(rc, EXIT_USER_ERROR)

    def test_bad_artifact(self):
        with tempfile.NamedTemporaryFile(
                suffix=".json", delete=False, mode="w") as f:
            f.write("{not json")
            bad = f.name
        rc = cmd_hardness(_ns(runs=[bad, bad]))
        self.assertEqual(rc, EXIT_USER_ERROR)

    def test_tampered_warns_but_reports(self):
        art = _artifact("mock-a", [_case("c1", flipped=True)])
        art.results.append(_case("c2", flipped=True))  # break the seal
        p = _write(art)
        q = _write(_artifact("mock-b", [_case("c1")]))
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_hardness(_ns(runs=[p, q]))
        self.assertEqual(rc, EXIT_OK)
        self.assertIn("Flip distribution", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
