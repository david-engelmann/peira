"""Backend-parity tests for ``peira.combo_metrics`` (rust-max SLICE-3).

Each test compares the dispatched public function (the compiled Rust
core when ``peira._core`` is importable, the ``_xxx_py`` reference
otherwise) against the pure-Python ``_xxx_py`` reference on identical
inputs. Floats compare with ``assertAlmostEqual(places=12)`` to tolerate
any ~1 ulp summation-order differences between the backends; everything
else is exact, including the ``format_interaction`` rendered strings.

``test_backend_under_test`` records which backend ran so the gate
report can confirm Rust-active mode actually exercised the core.
"""

import os
import random
import unittest

import peira.combo_metrics as cm_mod
from peira._rust import _impl as _rust
from peira.combo_metrics import (
    InteractionResult,
    _format_interaction_py,
    _paired_interaction_py,
    format_interaction,
    paired_interaction,
)


class TestBackendUnderTest(unittest.TestCase):
    def test_backend_under_test(self):
        self.assertIs(cm_mod._rust, _rust)
        if os.environ.get("PEIRA_NO_RUST"):
            self.assertIsNone(_rust, "PEIRA_NO_RUST=1 must force the reference backend")
        print(f"\ncombo_metrics parity backend: {'rust' if _rust is not None else 'python'}")


def _assert_results_equal(test, got, want, msg=None):
    """Field-by-field comparison: exact except floats (places=12)."""
    test.assertEqual(got.pair_id, want.pair_id)
    test.assertEqual(got.n_substrates, want.n_substrates)
    for field in (
        "rate_ctrl", "rate_a", "rate_b", "rate_ab",
        "interaction", "se", "ci_lo", "ci_hi", "mde_80",
    ):
        test.assertAlmostEqual(
            getattr(got, field), getattr(want, field), places=12,
            msg=f"field {field}" if msg is None else f"{msg}: field {field}",
        )
    test.assertEqual(got.classification, want.classification)
    test.assertEqual(got.hypothesis, want.hypothesis)
    test.assertEqual(got.hypothesis_confirmed, want.hypothesis_confirmed)


class TestPairedInteractionParity(unittest.TestCase):
    def test_empty_raises_value_error_both_backends(self):
        for fn in (paired_interaction, _paired_interaction_py):
            with self.assertRaises(ValueError) as ctx:
                fn([], "p", "super")
            self.assertEqual(str(ctx.exception), "no substrates")

    def test_known_values(self):
        outcomes = [(0, 0, 0, 1), (0, 1, 0, 1), (1, 1, 1, 1), (0, 0, 1, 0)]
        _assert_results_equal(
            self,
            paired_interaction(outcomes, "p", ""),
            _paired_interaction_py(outcomes, "p", ""),
        )

    def test_classifications(self):
        cases = [
            ([(0, 0, 0, 1)] * 200, "super"),
            ([(0, 0, 0, 1), (0, 1, 0, 0), (0, 0, 0, 1)], "unresolved"),
            ([(0, 1, 1, 0)] * 200, "sub"),
            ([(0, i % 2, i % 2, (i % 2) * 2) for i in range(200)], "additive"),
        ]
        for outcomes, want_class in cases:
            got = paired_interaction(outcomes, "p", want_class)
            want = _paired_interaction_py(outcomes, "p", want_class)
            self.assertEqual(got.classification, want_class)
            _assert_results_equal(self, got, want)

    def test_hypothesis_confirmation(self):
        outcomes = [(0, 0, 0, 1)] * 200
        got = paired_interaction(outcomes, "p", "super")
        self.assertTrue(got.hypothesis_confirmed)
        got = paired_interaction(outcomes, "p", "sub")
        self.assertFalse(got.hypothesis_confirmed)
        # Unresolved -> None even with a hypothesis.
        outcomes = [(0, 0, 0, 1), (0, 1, 0, 0)]
        got = paired_interaction(outcomes, "p", "super")
        self.assertIsNone(got.hypothesis_confirmed)
        self.assertEqual(got.classification, "unresolved")

    def test_fuzz_against_reference(self):
        rng = random.Random(20261002)
        for trial in range(60):
            n = rng.randint(1, 120)
            outcomes = [
                (
                    rng.randint(0, 1),
                    rng.randint(0, 1),
                    rng.randint(0, 1),
                    rng.randint(0, 1),
                )
                for _ in range(n)
            ]
            pair_id = rng.choice(["", "p", "combo-dfl-ind"])
            hypothesis = rng.choice(["", "super", "additive", "sub", "bogus"])
            _assert_results_equal(
                self,
                paired_interaction(outcomes, pair_id, hypothesis),
                _paired_interaction_py(outcomes, pair_id, hypothesis),
                msg=f"trial {trial}",
            )

    def test_non_integer_outcomes_fall_back(self):
        # Floats fail the PyO3 i64 extraction -> the reference computes.
        outcomes = [(0.0, 0.0, 0.0, 1.0)] * 10
        got = paired_interaction(outcomes, "p", "")
        want = _paired_interaction_py(outcomes, "p", "")
        _assert_results_equal(self, got, want)

    def test_oversized_int_falls_back(self):
        # Ints wider than i64 raise OverflowError from PyO3 extraction;
        # the wrapper falls back and the reference computes exactly.
        outcomes = [(2**70, 0, 0, 0), (0, 0, 0, 1)]
        got = paired_interaction(outcomes, "p", "")
        want = _paired_interaction_py(outcomes, "p", "")
        _assert_results_equal(self, got, want)


class TestFormatInteractionParity(unittest.TestCase):
    def _result(self, **kw):
        base = dict(
            pair_id="combo-dfl-ind",
            n_substrates=200,
            rate_ctrl=0.123456,
            rate_a=0.5,
            rate_b=0.25,
            rate_ab=0.875,
            interaction=0.333333,
            se=0.012345,
            ci_lo=0.309,
            ci_hi=0.357,
            mde_80=0.03456,
            classification="super",
            hypothesis="super",
            hypothesis_confirmed=True,
        )
        base.update(kw)
        return InteractionResult(**base)

    def test_exact_string(self):
        r = self._result()
        self.assertEqual(format_interaction(r), _format_interaction_py(r))
        # Spot-check the shape against the reference contract.
        s = format_interaction(r)
        self.assertIn("combo-dfl-ind: n=200 substrates; arm rates ", s)
        self.assertIn("ctrl=0.123 a=0.500 b=0.250 ab=0.875", s)
        self.assertIn("interaction=+0.333 95% CI [+0.309, +0.357], MDE80=0.035", s)
        self.assertIn("SUPER-ADDITIVE (synergy).", s)
        self.assertIn("Pre-registered hypothesis 'super' CONFIRMED.", s)

    def test_no_hypothesis_no_suffix(self):
        r = self._result(hypothesis="", hypothesis_confirmed=None)
        s = format_interaction(r)
        self.assertEqual(s, _format_interaction_py(r))
        self.assertNotIn("Pre-registered", s)

    def test_rejected_hypothesis(self):
        r = self._result(hypothesis="sub", hypothesis_confirmed=False)
        s = format_interaction(r)
        self.assertEqual(s, _format_interaction_py(r))
        self.assertIn("REJECTED.", s)

    def test_all_classifications(self):
        verdicts = {
            "super": "SUPER-ADDITIVE (synergy)",
            "additive": "additive (independent)",
            "sub": "SUB-ADDITIVE (redundancy)",
            "unresolved": "UNRESOLVED (not resolvable at this n)",
        }
        for cls, verdict in verdicts.items():
            r = self._result(classification=cls)
            s = format_interaction(r)
            self.assertEqual(s, _format_interaction_py(r))
            self.assertIn(verdict + ".", s)

    def test_fuzz_float_rendering(self):
        # Tricky floats for :.3 / :+.3 rendering parity.
        rng = random.Random(20261003)
        tricky = [2.675, -0.0, 0.0005, 0.0015, 999.9999, 1.005, 0.15, 1e-10]
        for trial in range(40):
            v = rng.choice(tricky + [rng.uniform(-2, 2) for _ in range(4)])
            r = self._result(
                rate_ctrl=v, rate_a=-v, interaction=v, ci_lo=-v, ci_hi=v,
                mde_80=abs(v),
                classification=rng.choice(["super", "additive", "sub", "unresolved"]),
            )
            self.assertEqual(
                format_interaction(r), _format_interaction_py(r),
                msg=f"trial {trial} v={v!r}",
            )

    def test_unicode_pair_id(self):
        r = self._result(pair_id="combo-日本語-1")
        self.assertEqual(format_interaction(r), _format_interaction_py(r))

    def test_unknown_classification_keyerror_both_backends(self):
        # D-11: unknown classification raises KeyError identically.
        r = self._result(classification="bogus")
        for fn in (format_interaction, _format_interaction_py):
            with self.assertRaises(KeyError) as ctx:
                fn(r)
            self.assertEqual(ctx.exception.args[0], "bogus")

    def test_extreme_i64_contrast_no_panic(self):
        # P1-1: i64 arithmetic overflow must not panic; the f64 path
        # matches the reference's float conversion.
        outcomes = [(2**62, -(2**62), -(2**62), 2**62)]
        r = paired_interaction(outcomes, "p", "")
        rp = _paired_interaction_py(outcomes, "p", "")
        self.assertAlmostEqual(r.interaction, rp.interaction, places=12)

    def test_malformed_tuple_shape_valueerror(self):
        # P2-2: malformed tuple raises the reference's ValueError (not
        # PyO3's differently-worded one) on both backends.
        for fn in (paired_interaction, _paired_interaction_py):
            with self.assertRaises(ValueError) as ctx:
                fn([(0, 0, 0)], "p", "")
            self.assertIn("not enough values to unpack", str(ctx.exception))

    def test_surrogate_pair_id_valueerror_both_backends(self):
        # P1-6: lone surrogates raise ValueError from the public wrapper
        # (D-11 validation); the lenient reference computes.
        with self.assertRaises(ValueError):
            paired_interaction([(0, 0, 0, 1)], "\ud800", "")

    def test_nan_rendering(self):
        # P2-1: NaN renders as "nan" (Python), not "NaN" (Rust).
        r = self._result(rate_ctrl=float("nan"), interaction=float("nan"))
        self.assertEqual(format_interaction(r), _format_interaction_py(r))
        self.assertIn("ctrl=nan", format_interaction(r))


if __name__ == "__main__":
    unittest.main()
