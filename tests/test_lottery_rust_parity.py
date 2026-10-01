"""Backend-parity tests for ``peira.lottery`` (rust-max SLICE-1).

Each test compares the dispatched public function (the compiled Rust
core when ``peira._core`` is importable, the ``_xxx_py`` reference
otherwise) against the pure-Python ``_xxx_py`` reference on identical
inputs. Exact equality: floats must be bit-identical, dicts key- and
order-identical.

When the Rust extension is absent the dispatched function *is* the
reference, so the tests hold trivially and still pin the reference
behavior. ``test_backend_under_test`` records which backend ran so the
gate report can confirm Rust-active mode actually exercised the core.

Error parity: the dispatched entry points validate before dispatch
(D-11), so both backends raise the same exception types and messages.
"""

import math
import random
import unittest

from peira._rust import _impl as _rust
from peira.lottery import (
    RankedRun,
    _kendall_tau_py,
    _lottery_analysis_py,
    _pairwise_swap_fraction_py,
    _rank_runs_py,
    _round4,
    _stability_verdict_py,
    kendall_tau,
    lottery_analysis,
    pairwise_swap_fraction,
    rank_runs,
    stability_verdict,
)
from peira.metrics import CallRecord, PerCaseResult


# Fixture builders mirror tests/test_lottery.py: eligibility needs
# >= 200 eligible cases total and >= 20 per required family, benign
# accuracy 1.0, malformed rate 0. ASR is the flipped fraction among
# eligible cases.
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


def _make_run(family_asr, per_family=100):
    """Build a run's results with the given per-family ASR.

    per_family=100 keeps runs ranking-eligible even under
    leave-one-out (3 x 100 = 300 total, 200 after dropping one family).
    """
    results = []
    for fam, asr in family_asr.items():
        n_flip = int(round(asr * per_family))
        for i in range(per_family):
            results.append(_case(fam, i < n_flip, f"{fam}-{i}"))
    return results


def _random_run(rng, families, per_family):
    return _make_run(
        {fam: rng.random() for fam in families}, per_family=per_family
    )


# (input, expected) boundary battery for round(v, 4): negatives,
# x.xxx5 values, and magnitudes where naive binary rounding differs.
ROUND4_BATTERY = [
    (2.675, 2.675),
    (2.665, 2.665),
    (-2.675, -2.675),
    (-2.665, -2.665),
    (1.23455, 1.2346),
    (1.23465, 1.2347),
    (-1.23455, -1.2346),
    (-1.23465, -1.2347),
    (0.89995, 0.9),
    (0.89994999, 0.8999),
    (-5e-05, -0.0001),
    (5e-05, 0.0001),
    (0.12345, 0.1235),
    (0.12344, 0.1234),
    (0.12346, 0.1235),
    (-0.12345, -0.1235),
    (123.45675, 123.4567),
    (123.45685, 123.4569),
    (2.50005, 2.5),
    (2.50015, 2.5002),
    (-2.50005, -2.5),
    (0.12494, 0.1249),
    (1e20, 1e20),
    (1.5e-05, 0.0),
]


class TestBackendUnderTest(unittest.TestCase):
    def test_backend_under_test(self):
        # The backend handle this file inspects must be the same object
        # the entry points dispatch on, otherwise the parity tests would
        # be comparing against the wrong backend. PEIRA_NO_RUST=1 must
        # force the pure-Python backend.
        import os

        import peira.lottery

        self.assertIs(peira.lottery._rust, _rust)
        if os.environ.get("PEIRA_NO_RUST"):
            self.assertIsNone(_rust, "PEIRA_NO_RUST=1 must force the reference backend")
        print(f"\nlottery parity backend: {'rust' if _rust is not None else 'python'}")


class TestRound4Parity(unittest.TestCase):
    def test_round4_boundary_battery(self):
        for v, expected in ROUND4_BATTERY:
            self.assertEqual(_round4(v), expected, f"python round({v!r}, 4)")
            if _rust is not None:
                self.assertEqual(
                    _rust.lottery_round4(v), expected, f"rust round4({v!r})"
                )


class TestRankRunsParity(unittest.TestCase):
    def assertRankedEqual(self, got, want, msg=None):
        self.assertEqual(len(got), len(want), msg)
        for g, w in zip(got, want):
            self.assertIsInstance(g, RankedRun)
            self.assertEqual(g.run_id, w.run_id)
            self.assertEqual(g.asr, w.asr)
            self.assertEqual(g.eligible, w.eligible)
            self.assertEqual(g.reasons, w.reasons)

    def test_mixed_fixture(self):
        # Ties on ASR (run_id tie-break), an ineligible run with
        # reasons, and a family filtered out of the ranking.
        runs = {
            # Same ASRs as alpha on f1/f2, plus an ignored fx family.
            "bravo": _make_run({"f1": 0.8, "f2": 0.2, "fx": 0.0}),
            "alpha": _make_run({"f1": 0.8, "f2": 0.2}),
            # Too few cases -> ineligible with reasons.
            "thin": _make_run({"f1": 0.2}, per_family=5),
            "empty": [],
        }
        self.assertRankedEqual(
            rank_runs(runs, ["f1", "f2"]), _rank_runs_py(runs, ["f1", "f2"])
        )

    def test_unicode_families(self):
        runs = {
            "r1": _make_run({"fäm": 0.75, "f2": 0.5}),
            "r2": _make_run({"fäm": 0.0, "f2": 1.0}),
        }
        self.assertRankedEqual(
            rank_runs(runs, ["fäm", "f2"]), _rank_runs_py(runs, ["fäm", "f2"])
        )

    def test_randomized(self):
        rng = random.Random(20260930)
        families = ["f1", "f2"]
        for trial in range(10):
            runs = {
                f"run-{i}": _random_run(rng, families, 100)
                for i in range(rng.randint(1, 5))
            }
            # Sometimes add a thin ineligible run and an empty one.
            if rng.random() < 0.5:
                runs["thin"] = _make_run({"f1": 0.3}, per_family=3)
            self.assertRankedEqual(
                rank_runs(runs, families),
                _rank_runs_py(runs, families),
                f"trial {trial}",
            )


class TestTauParity(unittest.TestCase):
    CASES = [
        (["a", "b", "c"], ["a", "b", "c"]),
        (["a", "b", "c"], ["c", "b", "a"]),
        (["a", "b", "c", "d"], ["b", "a", "d", "c"]),
        (["a", "b", "c"], ["a", "c", "b"]),
        (["a", "b"], ["b", "a", "c"]),  # partial overlap
        (["a"], ["a", "b"]),  # single common run -> None
        (["a"], ["b"]),  # disjoint -> None
        ([], []),
        (["x"], []),
    ]

    def test_cases(self):
        for rank_a, rank_b in self.CASES:
            self.assertEqual(
                kendall_tau(rank_a, rank_b),
                _kendall_tau_py(rank_a, rank_b),
                f"tau({rank_a}, {rank_b})",
            )
            self.assertEqual(
                pairwise_swap_fraction(rank_a, rank_b),
                _pairwise_swap_fraction_py(rank_a, rank_b),
                f"swap({rank_a}, {rank_b})",
            )

    def test_randomized_permutations(self):
        rng = random.Random(777)
        ids = [f"run-{i}" for i in range(8)]
        for trial in range(50):
            a = ids[:]
            b = ids[:]
            rng.shuffle(a)
            rng.shuffle(b)
            # Drop random runs from each side to vary the overlap.
            a = [r for r in a if rng.random() < 0.9]
            b = [r for r in b if rng.random() < 0.9]
            self.assertEqual(
                kendall_tau(a, b), _kendall_tau_py(a, b), f"trial {trial}"
            )
            self.assertEqual(
                pairwise_swap_fraction(a, b),
                _pairwise_swap_fraction_py(a, b),
                f"trial {trial}",
            )


class TestStabilityVerdictParity(unittest.TestCase):
    VALUES = [
        None,
        1.0,
        0.9,
        0.89995,  # rounds up to the stable band only after round4
        0.8999,
        0.7,
        0.6999999,
        0.0,
        -1.0,
        float("nan"),
        2,
        True,
    ]

    def test_values(self):
        for v in self.VALUES:
            got = stability_verdict(v)
            want = _stability_verdict_py(v)
            if v is not None and isinstance(v, float) and math.isnan(v):
                self.assertEqual(got, "fragile")
            else:
                self.assertEqual(got, want, f"verdict({v!r})")


class TestLotteryAnalysisParity(unittest.TestCase):
    def test_influential_family(self):
        # f1/f2 are identical across runs; only f3 separates them, so
        # removing f3 collapses the ranking to a run_id tie-break while
        # removing f1 or f2 changes nothing.
        runs = {
            "alpha": _make_run({"f1": 0.5, "f2": 0.5, "f3": 0.1}, per_family=100),
            "bravo": _make_run({"f1": 0.5, "f2": 0.5, "f3": 0.9}, per_family=100),
            "charlie": _make_run(
                {"f1": 0.5, "f2": 0.5, "f3": 0.5}, per_family=100
            ),
        }
        fams = ["f1", "f2", "f3"]
        got = lottery_analysis(runs, fams)
        want = _lottery_analysis_py(runs, fams)
        self.assertEqual(got, want)
        self.assertEqual(got["full_ranking"], ["alpha", "charlie", "bravo"])
        self.assertEqual(got["per_family"]["f1"]["tau"], 1.0)
        self.assertEqual(got["per_family"]["f2"]["tau"], 1.0)
        self.assertLess(got["per_family"]["f3"]["tau"], 1.0)
        self.assertEqual(got["most_influential_family"], "f3")

    def test_stable_rankings(self):
        runs = {
            f"r{i}": _make_run(
                {"f1": i / 5, "f2": i / 5, "f3": i / 5}, per_family=100
            )
            for i in range(1, 5)
        }
        got = lottery_analysis(runs, ["f1", "f2", "f3"])
        want = _lottery_analysis_py(runs, ["f1", "f2", "f3"])
        self.assertEqual(got, want)
        self.assertEqual(got["lottery_index"], 1.0)
        self.assertEqual(got["verdict"], "stable")

    def test_undefined_index(self):
        # One run: no family yields a comparable pair.
        runs = {"solo": _make_run({"f1": 0.4, "f2": 0.6}, per_family=100)}
        got = lottery_analysis(runs, ["f1", "f2"])
        want = _lottery_analysis_py(runs, ["f1", "f2"])
        self.assertEqual(got, want)
        self.assertIsNone(got["lottery_index"])
        self.assertEqual(got["verdict"], "undefined")

    def test_randomized(self):
        rng = random.Random(424242)
        families = ["f1", "f2", "f3"]
        for trial in range(10):
            runs = {
                f"run-{i}": _random_run(rng, families, 100) for i in range(4)
            }
            got = lottery_analysis(runs, families)
            want = _lottery_analysis_py(runs, families)
            self.assertEqual(got, want, f"trial {trial}")

    def test_error_parity(self):
        runs = {"a": _make_run({"f1": 0.3})}
        for func, args in [
            (rank_runs, (runs, [])),
            (lottery_analysis, (runs, [])),
        ]:
            with self.assertRaises(ValueError) as cm:
                func(*args)
            self.assertTrue(str(cm.exception).endswith("must not be empty"))
        # Single family: the reference's rank_runs message, both backends.
        with self.assertRaises(ValueError) as cm:
            lottery_analysis(runs, ["f1"])
        self.assertEqual(
            str(cm.exception), "rank_runs: families must not be empty"
        )
        # Bad run ids.
        with self.assertRaises(ValueError) as cm:
            rank_runs({"": []}, ["f1"])
        self.assertEqual(
            str(cm.exception), "rank_runs: run ids must be non-empty strings"
        )
        # Non-string families / ranking elements: TypeError both backends.
        with self.assertRaises(TypeError):
            rank_runs(runs, ["f1", 2])
        with self.assertRaises(TypeError):
            lottery_analysis(runs, ["f1", "f2", None])
        with self.assertRaises(TypeError):
            kendall_tau(["a", 1], ["a", "b"])
        with self.assertRaises(TypeError):
            pairwise_swap_fraction(["a"], [None])
        # Lone surrogate in a run id: ValueError both backends (D-11).
        with self.assertRaises(ValueError):
            rank_runs({"a\ud800": []}, ["f1"])

    def test_per_family_key_order_parity(self):
        # Spec: dict insertion order preserved via ordered Vec. Dict
        # equality is order-insensitive, so pin the key order
        # explicitly — a backend that scrambled per_family would still
        # pass test_influential_family.
        rng = random.Random(31337)
        families = ["fz", "fa", "fm"]  # non-alphabetical input order
        runs = {f"r{i}": _random_run(rng, families, 100) for i in range(4)}
        got = lottery_analysis(runs, families)
        want = _lottery_analysis_py(runs, families)
        self.assertEqual(list(got["per_family"]), families)
        self.assertEqual(list(got["per_family"]), list(want["per_family"]))

    def test_json_serializable(self):
        import json

        rng = random.Random(9)
        runs = {f"r{i}": _random_run(rng, ["f1", "f2"], 100) for i in range(3)}
        json.dumps(lottery_analysis(runs, ["f1", "f2"]))  # must not raise


if __name__ == "__main__":
    unittest.main()
