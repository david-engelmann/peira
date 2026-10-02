"""Backend-parity tests for ``peira.probes.invariance`` (rust-max SLICE-2).

Each test compares the dispatched public function (the compiled Rust
core when ``peira._core`` is importable, the ``_xxx_py`` reference
otherwise) against the pure-Python ``_xxx_py`` reference on identical
inputs. Exact equality: every report field identical, flip_rate
bit-identical.

When the Rust extension is absent the dispatched function *is* the
reference, so the tests hold trivially and still pin the reference
behavior. ``test_backend_under_test`` records which backend ran so the
gate report can confirm Rust-active mode actually exercised the core.

Error parity: the dispatched entry point validates before dispatch
(D-11), so both backends raise the same exception types and messages.
"""

import os
import random
import unittest

import peira.probes.invariance as invariance_mod
from peira._rust import _impl as _rust
from peira.probes.invariance import (
    InvarianceReport,
    _invariance_report_py,
    invariance_report,
)


def _check_equal(test, got, expected):
    test.assertIsInstance(got, InvarianceReport)
    test.assertEqual(got.baseline, expected.baseline)
    test.assertEqual(got.n_variants, expected.n_variants)
    test.assertEqual(got.n_flips, expected.n_flips)
    test.assertEqual(got.flip_rate, expected.flip_rate)
    test.assertEqual(got.flipped_indices, expected.flipped_indices)
    test.assertEqual(got, expected)


class TestBackendUnderTest(unittest.TestCase):
    def test_backend_under_test(self):
        self.assertIs(invariance_mod._rust, _rust)
        if os.environ.get("PEIRA_NO_RUST"):
            self.assertIsNone(_rust, "PEIRA_NO_RUST=1 must force the reference backend")
        print(f"\ninvariance parity backend: {'rust' if _rust is not None else 'python'}")


class TestInvarianceReportParity(unittest.TestCase):
    def test_no_flips(self):
        _check_equal(
            self,
            invariance_report("approve", ["approve", "approve"]),
            _invariance_report_py("approve", ["approve", "approve"]),
        )
        got = invariance_report("approve", ["approve", "approve"])
        self.assertEqual(got.flip_rate, 0.0)
        self.assertEqual(got.flipped_indices, ())

    def test_all_flips(self):
        got = invariance_report("approve", ["deny", "deny", "deny"])
        expected = _invariance_report_py("approve", ["deny", "deny", "deny"])
        _check_equal(self, got, expected)
        self.assertEqual(got.flip_rate, 1.0)
        self.assertEqual(got.flipped_indices, (0, 1, 2))

    def test_mixed(self):
        got = invariance_report("approve", ["deny", "approve", "escalate", "approve"])
        expected = _invariance_report_py(
            "approve", ["deny", "approve", "escalate", "approve"]
        )
        _check_equal(self, got, expected)
        self.assertEqual(got.n_flips, 2)
        self.assertEqual(got.flip_rate, 0.5)
        self.assertEqual(got.flipped_indices, (0, 2))

    def test_abstain_counts_as_flip(self):
        # "" (abstain) vs a decision is a behavioral change.
        got = invariance_report("approve", ["", "approve"])
        self.assertEqual(got.n_flips, 1)
        self.assertEqual(got.flip_rate, 0.5)
        _check_equal(self, got, _invariance_report_py("approve", ["", "approve"]))

    def test_single_variant(self):
        _check_equal(
            self,
            invariance_report("x", ["y"]),
            _invariance_report_py("x", ["y"]),
        )

    def test_empty_variants_raises(self):
        with self.assertRaises(ValueError) as ctx:
            invariance_report("approve", [])
        self.assertEqual(str(ctx.exception), "variant_decisions must be non-empty")
        with self.assertRaises(ValueError):
            _invariance_report_py("approve", [])

    def test_tuple_input_accepted(self):
        # Sequence input, not just list.
        _check_equal(
            self,
            invariance_report("a", ("b", "a", "c")),
            _invariance_report_py("a", ("b", "a", "c")),
        )

    def test_generator_input_accepted(self):
        gen = (d for d in ["a", "b", "a"])
        _check_equal(
            self,
            invariance_report("a", gen),
            _invariance_report_py("a", (d for d in ["a", "b", "a"])),
        )

    def test_unicode_decisions(self):
        variants = ["décision-α", "approve", "décision-α", ""]
        _check_equal(
            self,
            invariance_report("décision-α", variants),
            _invariance_report_py("décision-α", variants),
        )

    def test_fuzz_against_reference(self):
        rng = random.Random(20261001)
        decisions = ["approve", "deny", "escalate", "", "abstain", "αβγ"]
        for _ in range(300):
            baseline = rng.choice(decisions)
            variants = [rng.choice(decisions) for _ in range(rng.randrange(1, 12))]
            _check_equal(
                self,
                invariance_report(baseline, variants),
                _invariance_report_py(baseline, variants),
            )


if __name__ == "__main__":
    unittest.main()
