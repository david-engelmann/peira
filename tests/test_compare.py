"""Tests for `peira compare`: head-to-head comparison of two artifacts.

Builds synthetic sealed artifacts with known outcomes and checks the
McNemar/Bradley-Terry/delta machinery, the comparability gates, and the
CLI surface (stdout summary, --out HTML, error paths).
"""

import argparse
import json
import tempfile
import unittest
from pathlib import Path

from peira.artifacts import RunArtifact
from peira.cli import EXIT_OK, EXIT_USER_ERROR, cmd_compare
from peira.compare import (
    check_comparable,
    compare_artifacts,
    comparison_to_dict,
)


def _rec(decision="approve", confidence=0.9, abstained=False, malformed=False,
         cost_usd=0.001, latency_ms=50.0, usage=True):
    rec = {
        "decision": decision,
        "confidence": confidence,
        "abstained": abstained,
        "refusal_reason": "",
        "seed": 0,
        "dispatch_index": 0,
        "malformed": malformed,
        "dispatch_limit": 1,
    }
    rec["usage"] = {
        "model": "test-model",
        "tokens_in": 10,
        "tokens_out": 5,
        "latency_ms": latency_ms,
        "cost_usd": cost_usd,
    } if usage else None
    return rec


def _case(case_id, family="fam", primitive="choice", eligible=True,
          flipped=False, confidence=0.9, usage=True):
    return {
        "case_id": case_id,
        "family": family,
        "severity": "high",
        "primitive": primitive,
        "benign": _rec(confidence=confidence, usage=usage),
        "attacked": _rec(confidence=confidence, usage=usage),
        "flipped": flipped,
        "eligible": eligible,
        "ineligibility_reason": "" if eligible else "benign_wrong_decision",
    }


def _artifact(name, cases, suite="trial-demo", dataset_version="0.1.0-demo",
              manifest="abc123", adapter_version="1.0"):
    art = RunArtifact(
        adapter_name=name,
        adapter_version=adapter_version,
        suite=suite,
        dataset_version=dataset_version,
        manifest_sha256=manifest,
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


def _args(a, b, out=None, seed=0):
    return argparse.Namespace(run_a=a, run_b=b, out=out, seed=seed)


class CompareArtifactsTest(unittest.TestCase):
    def test_a_strictly_better_than_b(self):
        # A flips 5/60, B flips 25/60 (B's flips are a superset of A's).
        cases_a = [_case(f"c{i:03d}", flipped=(i < 5)) for i in range(60)]
        cases_b = [_case(f"c{i:03d}", flipped=(i < 25)) for i in range(60)]
        a = _artifact("alpha", cases_a)
        b = _artifact("beta", cases_b)
        c = compare_artifacts(a, b, seed=0)

        self.assertEqual(c.n_paired, 60)
        h = c.head_to_head
        # i in 0..4: both wrong; i in 5..24: A only; i in 25..59: both right.
        self.assertEqual((h.both_right, h.a_only, h.b_only, h.both_wrong),
                         (35, 20, 0, 5))

        m = c.mcnemar
        self.assertIsNotNone(m)
        self.assertEqual((m.b, m.c), (20, 0))
        self.assertAlmostEqual(m.statistic, 20.0)
        self.assertLess(m.p_value, 0.001)
        self.assertEqual(m.winner, "a")

        self.assertIsNotNone(c.bradley_terry_strengths)
        s = c.bradley_terry_strengths
        # Items are version-pinned ("alpha 1.0"); A must beat B.
        sa = next(v for k, v in s.items() if k.startswith("alpha"))
        sb = next(v for k, v in s.items() if k.startswith("beta"))
        self.assertGreater(sa, sb)
        self.assertEqual(c.bradley_terry_n, 60)

        by_name = {d.name: d for d in c.deltas}
        asr = by_name["asr"]
        self.assertTrue(asr.sufficient)
        self.assertAlmostEqual(asr.delta, 5 / 60 - 25 / 60)
        self.assertEqual(asr.favors, "a")
        lo, hi = asr.ci95
        self.assertLess(hi, 0.0)  # CI entirely negative: A robustly better
        self.assertLess(lo, hi)
        # Benign accuracy identical (all eligible): delta 0, no favors.
        ba = by_name["benign_accuracy"]
        self.assertTrue(ba.sufficient)
        self.assertAlmostEqual(ba.delta, 0.0)
        self.assertIsNone(ba.favors)

    def test_identical_adapters(self):
        cases = [_case(f"c{i:03d}", flipped=(i % 3 == 0)) for i in range(40)]
        a = _artifact("alpha", [dict(x) for x in cases])
        b = _artifact("beta", [dict(x) for x in cases])
        c = compare_artifacts(a, b, seed=1)

        h = c.head_to_head
        self.assertEqual(h.a_only, 0)
        self.assertEqual(h.b_only, 0)
        self.assertEqual(h.n, 40)

        m = c.mcnemar
        self.assertIsNotNone(m)
        self.assertEqual((m.b, m.c), (0, 0))
        self.assertEqual(m.statistic, 0.0)
        self.assertEqual(m.p_value, 1.0)
        self.assertIsNone(m.winner)

        # All ties: strengths unidentified by convention -> all zeros.
        self.assertIsNotNone(c.bradley_terry_strengths)
        for v in c.bradley_terry_strengths.values():
            self.assertAlmostEqual(v, 0.0)

        by_name = {d.name: d for d in c.deltas}
        self.assertAlmostEqual(by_name["asr"].delta, 0.0)

    def test_same_adapter_name_disambiguated(self):
        # Two runs of the same adapter (different seeds): BT items must
        # not collapse into a self-comparison.
        cases_a = [_case(f"c{i:02d}", flipped=(i < 2)) for i in range(35)]
        cases_b = [_case(f"c{i:02d}", flipped=(i < 8)) for i in range(35)]
        a = _artifact("mock", cases_a, adapter_version="1.0")
        b = _artifact("mock", cases_b, adapter_version="1.0")
        c = compare_artifacts(a, b, seed=0)
        self.assertIsNotNone(c.bradley_terry_strengths)
        names = sorted(c.bradley_terry_strengths)
        self.assertEqual(len(names), 2)
        self.assertNotEqual(names[0], names[1])

    def test_no_overlapping_cases(self):
        a = _artifact("alpha", [_case(f"a{i}") for i in range(5)])
        b = _artifact("beta", [_case(f"b{i}") for i in range(5)])
        with self.assertRaisesRegex(ValueError, "no cases"):
            compare_artifacts(a, b)

    def test_incomparable_suite(self):
        a = _artifact("alpha", [_case("c1")], suite="trial-demo")
        b = _artifact("beta", [_case("c1")], suite="trial")
        with self.assertRaisesRegex(ValueError, "not comparable"):
            compare_artifacts(a, b)
        self.assertTrue(any("suite" in p for p in check_comparable(a, b)))

    def test_incomparable_dataset_version(self):
        a = _artifact("alpha", [_case("c1")], dataset_version="1.0.0")
        b = _artifact("beta", [_case("c1")], dataset_version="1.0.1")
        with self.assertRaisesRegex(ValueError, "not comparable"):
            compare_artifacts(a, b)

    def test_incomparable_manifest(self):
        a = _artifact("alpha", [_case("c1")], manifest="aaa")
        b = _artifact("beta", [_case("c1")], manifest="bbb")
        with self.assertRaisesRegex(ValueError, "not comparable"):
            compare_artifacts(a, b)

    def test_partial_overlap_warns_and_uses_intersection(self):
        a = _artifact("alpha", [_case(f"c{i}") for i in range(10)])
        b = _artifact("beta", [_case(f"c{i}") for i in range(5, 15)])
        c = compare_artifacts(a, b)
        self.assertEqual(c.n_paired, 5)
        self.assertTrue(any("intersection" in w for w in c.warnings))

    def test_abstain_primitive_withholds_mcnemar_and_bt(self):
        cases_a = [_case(f"c{i:02d}", primitive="abstain") for i in range(10)]
        cases_b = [_case(f"c{i:02d}", primitive="abstain") for i in range(10)]
        c = compare_artifacts(_artifact("alpha", cases_a),
                              _artifact("beta", cases_b))
        self.assertEqual(c.n_paired, 10)
        self.assertEqual(c.head_to_head.n, 10)
        self.assertIsNone(c.mcnemar)
        self.assertIn("choice", c.mcnemar_note)
        self.assertIsNone(c.bradley_terry_strengths)
        # Deltas withheld below the n=30 gate.
        for d in c.deltas:
            self.assertFalse(d.sufficient)
            self.assertIsNone(d.delta)

    def test_small_n_withholds_deltas_but_reports_counts(self):
        cases_a = [_case(f"c{i:02d}", flipped=(i < 2)) for i in range(10)]
        cases_b = [_case(f"c{i:02d}", flipped=(i < 6)) for i in range(10)]
        c = compare_artifacts(_artifact("alpha", cases_a),
                              _artifact("beta", cases_b))
        self.assertEqual(c.head_to_head.a_only, 4)
        m = c.mcnemar
        self.assertIsNotNone(m)
        self.assertEqual((m.b, m.c), (4, 0))
        self.assertIn("underpowered", c.mcnemar_note)
        for d in c.deltas:
            self.assertFalse(d.sufficient)

    def test_lock_mismatch_warns_but_compares(self):
        cases = [_case(f"c{i:02d}") for i in range(10)]
        a = _artifact("alpha", cases)
        b = _artifact("beta", cases)
        # Tamper after sealing: flip a metric-free field the lock covers.
        d = json.loads(b.to_json())
        d["max_concurrency"] = 999
        tampered = RunArtifact.from_json(json.dumps(d))
        self.assertFalse(tampered.verify())
        c = compare_artifacts(a, tampered)
        self.assertEqual(c.n_paired, 10)
        self.assertTrue(any("lock" in w for w in c.warnings))

    def test_comparison_to_dict_json_serializable(self):
        cases_a = [_case(f"c{i:02d}", flipped=(i < 1)) for i in range(35)]
        cases_b = [_case(f"c{i:02d}", flipped=(i < 3)) for i in range(35)]
        c = compare_artifacts(_artifact("alpha", cases_a),
                              _artifact("beta", cases_b))
        d = comparison_to_dict(c)
        json.dumps(d)  # must not raise
        self.assertEqual(d["n_paired"], 35)
        self.assertEqual(d["adapter_a"], "alpha")


class CmdCompareTest(unittest.TestCase):
    def _pair(self, n=40):
        cases_a = [_case(f"c{i:03d}", flipped=(i < 5)) for i in range(n)]
        cases_b = [_case(f"c{i:03d}", flipped=(i < 15)) for i in range(n)]
        return _write(_artifact("alpha", cases_a)), _write(_artifact("beta", cases_b))

    def test_stdout_summary(self):
        pa, pb = self._pair()
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_compare(_args(pa, pb))
        self.assertEqual(rc, EXIT_OK)
        out = buf.getvalue()
        self.assertIn("alpha", out)
        self.assertIn("beta", out)
        self.assertIn("McNemar", out)
        self.assertIn("Bradley-Terry", out)
        self.assertIn("Deltas", out)

    def test_out_writes_html(self):
        pa, pb = self._pair()
        with tempfile.TemporaryDirectory() as td:
            out = str(Path(td) / "cmp.html")
            rc = cmd_compare(_args(pa, pb, out=out))
            self.assertEqual(rc, EXIT_OK)
            html_text = Path(out).read_text(encoding="utf-8")
            self.assertIn("<html>", html_text)
            self.assertIn("alpha", html_text)
            self.assertIn("McNemar", html_text)

    def test_missing_file(self):
        pa, _ = self._pair()
        rc = cmd_compare(_args(pa, "/nonexistent/b.json"))
        self.assertEqual(rc, EXIT_USER_ERROR)

    def test_corrupt_artifact(self):
        pa, _ = self._pair()
        with tempfile.NamedTemporaryFile(
                suffix=".json", delete=False, mode="w",
                encoding="utf-8") as f:
            f.write("{not valid json")
            bad = f.name
        rc = cmd_compare(_args(pa, bad))
        self.assertEqual(rc, EXIT_USER_ERROR)

    def test_incomparable_exits_1(self):
        a = _write(_artifact("alpha", [_case("c1")], suite="trial-demo"))
        b = _write(_artifact("beta", [_case("c1")], suite="trial"))
        rc = cmd_compare(_args(a, b))
        self.assertEqual(rc, EXIT_USER_ERROR)

    def test_no_overlap_exits_1(self):
        a = _write(_artifact("alpha", [_case("x1")]))
        b = _write(_artifact("beta", [_case("y1")]))
        rc = cmd_compare(_args(a, b))
        self.assertEqual(rc, EXIT_USER_ERROR)

    def test_hostile_adapter_name_escaped_in_html(self):
        cases = [_case(f"c{i:02d}") for i in range(5)]
        a = _write(_artifact("<script>alert(1)</script>", cases))
        b = _write(_artifact("beta", cases))
        with tempfile.TemporaryDirectory() as td:
            out = str(Path(td) / "cmp.html")
            rc = cmd_compare(_args(a, b, out=out))
            self.assertEqual(rc, EXIT_OK)
            html_text = Path(out).read_text(encoding="utf-8")
            self.assertNotIn("<script>alert(1)</script>", html_text)
            self.assertIn("&lt;script&gt;", html_text)


if __name__ == "__main__":
    unittest.main()
