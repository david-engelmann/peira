"""Backend-parity tests for ``peira.hardness`` (rust-max SLICE-3).

Each test compares the dispatched public function (the compiled Rust
core when ``peira._core`` is importable, the ``_xxx_py`` reference
otherwise) against the pure-Python ``_xxx_py`` reference on identical
inputs. Dataclasses compare by equality; ``report_text`` output is
byte-identical; floats inside use ``assertAlmostEqual(places=12)``
(the documented ~1 ulp precedent). ``None`` transfer rates are
distinguished from 0.0 explicitly.

``test_backend_under_test`` records which backend ran so the gate
report can confirm Rust-active mode actually exercised the core.
"""

import os
import random
import unittest

import peira.hardness as hardness_mod
from peira._rust import _impl as _rust
from peira.hardness import (
    _analyze_runs_py,
    _flip_distribution_py,
    _hardest_decile_survival_py,
    _report_text_py,
    _transfer_matrix_py,
    analyze_runs,
    flip_distribution,
    hardest_decile_survival,
    report_text,
    transfer_matrix,
)
from peira.metrics import PerCaseResult


class TestBackendUnderTest(unittest.TestCase):
    def test_backend_under_test(self):
        self.assertIs(hardness_mod._rust, _rust)
        if os.environ.get("PEIRA_NO_RUST"):
            self.assertIsNone(_rust, "PEIRA_NO_RUST=1 must force the reference backend")
        print(f"\nhardness parity backend: {'rust' if _rust is not None else 'python'}")


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


def _small_data():
    return {
        "ada": _results([
            _case("c1", flipped=True),
            _case("c2"),
            _case("c3", flipped=True),
            _case("c4", eligible=False, flipped=True),
        ]),
        "bob": _results([
            _case("c1", flipped=True),
            _case("c2", flipped=True),
            _case("c3"),
        ]),
    }


def _assert_dist_equal(test, got, want, msg=None):
    test.assertEqual(got.adapters, want.adapters)
    test.assertEqual(got.n_cases, want.n_cases)
    test.assertEqual(got.counts, want.counts)
    test.assertEqual(len(got.fractions), len(want.fractions))
    for g, w in zip(got.fractions, want.fractions):
        test.assertAlmostEqual(g, w, places=12, msg=msg)


def _assert_matrix_equal(test, got, want, msg=None):
    test.assertEqual(got.adapters, want.adapters)
    test.assertEqual(got.family, want.family)
    test.assertEqual(got.n_cases, want.n_cases)
    test.assertEqual(got.flipped_by_source, want.flipped_by_source)
    test.assertEqual(set(got.rates), set(want.rates))
    for k in want.rates:
        test.assertIs(got.rates[k] is None, want.rates[k] is None, msg=f"rate {k}")
        if want.rates[k] is not None:
            test.assertAlmostEqual(got.rates[k], want.rates[k], places=12, msg=f"{msg}: rate {k}" if msg else f"rate {k}")
    if want.mean_off_diagonal is None:
        test.assertIsNone(got.mean_off_diagonal)
    else:
        test.assertAlmostEqual(
            got.mean_off_diagonal, want.mean_off_diagonal, places=12, msg=msg
        )


class TestFlipDistributionParity(unittest.TestCase):
    def test_small(self):
        data = _small_data()
        _assert_dist_equal(self, flip_distribution(data), _flip_distribution_py(data))

    def test_empty(self):
        for data in ({}, {"ada": []}):
            got, want = flip_distribution(data), _flip_distribution_py(data)
            self.assertEqual(got.n_cases, 0)
            _assert_dist_equal(self, got, want)

    def test_non_dict_input_matches_reference(self):
        # D-11: non-dict input skips the Rust path; the reference raises
        # the natural exception (TypeError, not AttributeError).
        for bad in (["ada"], "ada", None, 42):
            for fn, ref in (
                (flip_distribution, _flip_distribution_py),
                (transfer_matrix, _transfer_matrix_py),
                (analyze_runs, _analyze_runs_py),
            ):
                try:
                    fn(bad)
                    got_exc = None
                except Exception as e:  # noqa: BLE001
                    got_exc = type(e).__name__
                try:
                    ref(bad)
                    want_exc = None
                except Exception as e:  # noqa: BLE001
                    want_exc = type(e).__name__
                self.assertEqual(got_exc, want_exc, msg=f"{fn.__name__}({bad!r})")

    def test_no_common_universe(self):
        data = {
            "ada": _results([_case("c1", flipped=True)]),
            "bob": _results([_case("c2", flipped=True)]),
        }
        _assert_dist_equal(self, flip_distribution(data), _flip_distribution_py(data))

    def test_fuzz(self):
        rng = random.Random(20261004)
        for trial in range(25):
            adapters = [f"adapter-{i}" for i in range(rng.randint(1, 4))]
            n_cases = rng.randint(0, 30)
            data = {}
            for a in adapters:
                cases = []
                for c in range(n_cases):
                    # Randomly drop / disqualify cases per adapter.
                    roll = rng.random()
                    if roll < 0.1:
                        continue
                    cases.append(_case(
                        f"case-{c:03d}",
                        family=rng.choice(["fam-a", "fam-b"]),
                        eligible=rng.random() > 0.15,
                        flipped=rng.random() < 0.4,
                    ))
                data[a] = _results(cases)
            _assert_dist_equal(
                self, flip_distribution(data), _flip_distribution_py(data),
                msg=f"trial {trial}",
            )


class TestHardestDecileParity(unittest.TestCase):
    def test_small(self):
        data = _small_data()
        got, want = hardest_decile_survival(data, 0.5), _hardest_decile_survival_py(data, 0.5)
        self.assertEqual(got.adapters, want.adapters)
        self.assertEqual(got.n_cases, want.n_cases)
        self.assertEqual(got.decile_size, want.decile_size)
        self.assertEqual(got.decile_case_ids, want.decile_case_ids)
        self.assertEqual(got.survived, want.survived)
        self.assertEqual(set(got.rates), set(want.rates))
        for a in want.adapters:
            if want.rates[a] is None:
                self.assertIsNone(got.rates[a])
            else:
                self.assertAlmostEqual(got.rates[a], want.rates[a], places=12)

    def test_decile_validation_both_backends(self):
        data = _small_data()
        for bad in (0.0, -0.1, 1.5, 2):
            for fn in (hardest_decile_survival, _hardest_decile_survival_py):
                with self.assertRaises(ValueError) as ctx:
                    fn(data, bad)
                self.assertIn("decile must be in (0, 1]", str(ctx.exception))
        # Boundaries are legal.
        for good in (0.10, 1.0, 0.001):
            hardest_decile_survival(data, good)
            _hardest_decile_survival_py(data, good)

    def test_fuzz(self):
        rng = random.Random(20261005)
        for trial in range(25):
            adapters = [f"a{i}" for i in range(rng.randint(1, 4))]
            data = {}
            for a in adapters:
                data[a] = _results([
                    _case(f"c{c:03d}", flipped=rng.random() < 0.4)
                    for c in range(rng.randint(0, 25))
                ])
            decile = rng.choice([0.10, 0.25, 0.5, 1.0])
            got = hardest_decile_survival(data, decile)
            want = _hardest_decile_survival_py(data, decile)
            self.assertEqual(got.decile_case_ids, want.decile_case_ids,
                             msg=f"trial {trial}")
            self.assertEqual(got.survived, want.survived, msg=f"trial {trial}")


class TestTransferMatrixParity(unittest.TestCase):
    def test_small(self):
        data = _small_data()
        _assert_matrix_equal(
            self, transfer_matrix(data), _transfer_matrix_py(data)
        )

    def test_family_filter(self):
        data = {
            "ada": _results([
                _case("c1", family="fam-a", flipped=True),
                _case("c2", family="fam-b", flipped=True),
            ]),
            "bob": _results([
                _case("c1", family="fam-a", flipped=True),
                _case("c2", family="fam-b"),
            ]),
        }
        for fam in (None, "fam-a", "fam-b", "nope"):
            _assert_matrix_equal(
                self,
                transfer_matrix(data, family=fam),
                _transfer_matrix_py(data, family=fam),
                msg=f"family {fam}",
            )

    def test_none_vs_zero(self):
        # src flips nothing eligible -> None, distinct from 0.0.
        data = {
            "ada": _results([_case("c1")]),
            "bob": _results([_case("c1")]),
        }
        got = transfer_matrix(data)
        self.assertIsNone(got.rates[("ada", "bob")])
        self.assertEqual(got.rates[("ada", "ada")], 1.0)
        _assert_matrix_equal(self, got, _transfer_matrix_py(data))

    def test_fuzz(self):
        rng = random.Random(20261006)
        for trial in range(25):
            adapters = [f"a{i}" for i in range(rng.randint(1, 4))]
            data = {}
            for a in adapters:
                data[a] = _results([
                    _case(
                        f"c{c:03d}",
                        family=rng.choice(["x", "y"]),
                        eligible=rng.random() > 0.1,
                        flipped=rng.random() < 0.4,
                    )
                    for c in range(rng.randint(0, 20))
                ])
            fam = rng.choice([None, "x", "y"])
            _assert_matrix_equal(
                self,
                transfer_matrix(data, family=fam),
                _transfer_matrix_py(data, family=fam),
                msg=f"trial {trial}",
            )


class TestAnalyzeRunsParity(unittest.TestCase):
    def test_small(self):
        data = _small_data()
        got, want = analyze_runs(data), _analyze_runs_py(data)
        self.assertEqual(got, want)

    def test_fuzz(self):
        rng = random.Random(20261007)
        for trial in range(15):
            adapters = [f"a{i}" for i in range(rng.randint(1, 3))]
            data = {}
            for a in adapters:
                data[a] = _results([
                    _case(
                        f"c{c:03d}",
                        family=rng.choice(["x", "y", "z"]),
                        eligible=rng.random() > 0.1,
                        flipped=rng.random() < 0.4,
                    )
                    for c in range(rng.randint(0, 15))
                ])
            got, want = analyze_runs(data), _analyze_runs_py(data)
            self.assertEqual(got.adapters, want.adapters, msg=f"trial {trial}")
            self.assertEqual(got.n_cases, want.n_cases, msg=f"trial {trial}")
            _assert_dist_equal(self, got.flip_distribution, want.flip_distribution)
            self.assertEqual(got.hardest_decile.decile_case_ids,
                             want.hardest_decile.decile_case_ids)
            _assert_matrix_equal(self, got.transfer_overall, want.transfer_overall)
            self.assertEqual(set(got.transfer_by_family),
                             set(want.transfer_by_family))
            for fam in want.transfer_by_family:
                _assert_matrix_equal(
                    self, got.transfer_by_family[fam], want.transfer_by_family[fam]
                )


class TestReportTextParity(unittest.TestCase):
    def test_byte_identical_small(self):
        data = _small_data()
        report = analyze_runs(data)
        self.assertEqual(report_text(report), _report_text_py(report))

    def test_byte_identical_empty(self):
        report = analyze_runs({})
        self.assertEqual(report_text(report), _report_text_py(report))

    def test_fuzz_byte_identical(self):
        rng = random.Random(20261008)
        for trial in range(20):
            adapters = [f"adapter-{i}" for i in range(rng.randint(0, 4))]
            data = {}
            for a in adapters:
                data[a] = _results([
                    _case(
                        f"case-{c:03d}",
                        family=rng.choice(["fam-a", "fam-b"]),
                        eligible=rng.random() > 0.15,
                        flipped=rng.random() < 0.4,
                    )
                    for c in range(rng.randint(0, 20))
                ])
            report = analyze_runs(data)
            self.assertEqual(
                report_text(report), _report_text_py(report),
                msg=f"trial {trial}",
            )

    def test_unicode_adapter_names(self):
        data = {
            "日本語-adapter": _results([_case("c1", flipped=True)]),
            "éclair": _results([_case("c1")]),
        }
        report = analyze_runs(data)
        # Byte-identical even with non-ASCII names (char-based slicing).
        self.assertEqual(report_text(report), _report_text_py(report))

    def test_report_text_family_insertion_order(self):
        # P1-2: per-family tables follow insertion order, not sorted order.
        from peira.hardness import HardnessReport, FlipDistribution, \
            HardestDecileSurvival, TransferMatrix
        def _tm():
            return TransferMatrix(
                adapters=("a",), family=None, n_cases=1,
                flipped_by_source={"a": 1}, rates={("a", "a"): 1.0},
            )
        report = HardnessReport(
            adapters=("a",), n_cases=1,
            flip_distribution=FlipDistribution(
                adapters=("a",), n_cases=1, counts=(1,)),
            hardest_decile=HardestDecileSurvival(
                adapters=("a",), n_cases=1, decile_size=1,
                decile_case_ids=("c1",), survived={"a": 1}),
            transfer_overall=_tm(),
            transfer_by_family={"z": _tm(), "a": _tm()},
        )
        text = report_text(report)
        text_py = _report_text_py(report)
        self.assertEqual(text, text_py)
        # "z" row must come before "a" row in the per-family table
        # (insertion order, not sorted).
        table = text[text.index("Per-family transfer"):]
        z_pos = table.index("\n  z ")
        a_pos = table.index("\n  a ")
        self.assertLess(z_pos, a_pos)

    def test_report_text_missing_adapter_keyerror(self):
        # P1-3: missing adapter raises KeyError, not a panic.
        from peira.hardness import HardnessReport, FlipDistribution, \
            HardestDecileSurvival, TransferMatrix
        def _tm():
            return TransferMatrix(
                adapters=("a", "bob"), family=None, n_cases=1,
                flipped_by_source={"a": 1},  # "bob" missing
                rates={("a", "a"): 1.0, ("bob", "bob"): 1.0},
            )
        report = HardnessReport(
            adapters=("a", "bob"), n_cases=1,
            flip_distribution=FlipDistribution(
                adapters=("a", "bob"), n_cases=1, counts=(1, 0)),
            hardest_decile=HardestDecileSurvival(
                adapters=("a", "bob"), n_cases=1, decile_size=1,
                decile_case_ids=("c1",),
                survived={"a": 1}),  # "bob" missing
            transfer_overall=_tm(),
            transfer_by_family={},
        )
        for fn in (report_text, _report_text_py):
            with self.assertRaises(KeyError) as ctx:
                fn(report)
            self.assertEqual(ctx.exception.args[0], "bob")

    def test_duck_typed_records(self):
        # P1-4: duck-typed records (only eligible/case_id/flipped/family)
        # are accepted by the reference; the dispatched path falls back.
        from types import SimpleNamespace
        data = {
            "a": [SimpleNamespace(case_id="c1", eligible=True,
                                  flipped=True, family="f")],
        }
        self.assertEqual(
            flip_distribution(data), _flip_distribution_py(data))

    def test_int_adapter_keys(self):
        # P1-5: non-string adapter keys fall back to the reference.
        data = {1: _results([_case("c1", flipped=True)])}
        self.assertEqual(
            flip_distribution(data), _flip_distribution_py(data))

    def test_surrogate_family_valueerror(self):
        # P1-6: lone surrogates in the family param raise ValueError from
        # the public wrapper (D-11 validation); the lenient reference
        # computes.
        data = {"a": _results([_case("c1", flipped=True, family="f")])}
        with self.assertRaises(ValueError):
            transfer_matrix(data, "\ud800")

    def test_analyze_runs_bad_input_decile_precedence(self):
        # P2-3: non-dict input raises the reference's TypeError before
        # the decile ValueError.
        for fn in (analyze_runs, _analyze_runs_py):
            with self.assertRaises(TypeError):
                fn("bad", 0.0)


if __name__ == "__main__":
    unittest.main()
