"""Rust-parity tests for the MDE numeric core (mde_mcnemar lane).

Each test compares the dispatched public function against its
pure-Python ``_xxx_py`` reference twin with assertAlmostEqual(places=12).
The twins are the PEIRA_NO_RUST=1 fallback, so this file proves the Rust
core agrees with the fallback path on real-shaped data.

Skipped entirely when the Rust extension is not built
(``PEIRA_NO_RUST=1``): in that mode the public functions ARE the twins.
"""

import math
import unittest

from peira._rust import _impl as _rust
from peira.metrics import (
    MDE_ALPHA,
    MDE_POWER,
    _mde_from_se_py,
    _mde_mcnemar_py,
    _normal_quantile_py,
    mde_from_se,
    mde_mcnemar,
)


@unittest.skipIf(_rust is None, "Rust extension not built")
class TestNormalQuantileParity(unittest.TestCase):
    def test_reference_points(self):
        for p in (0.975, 0.8, 0.95, 0.99, 0.5, 0.025, 0.001, 0.999):
            with self.subTest(p=p):
                # The dispatcher calls the private _normal_quantile; reach
                # it via mde_from_se's internals is awkward, so compare the
                # PyO3 export directly against the twin.
                self.assertAlmostEqual(
                    _rust.normal_quantile(p), _normal_quantile_py(p), places=12
                )

    def test_grid(self):
        p = 0.01
        while p < 1.0:
            with self.subTest(p=p):
                self.assertAlmostEqual(
                    _rust.normal_quantile(p), _normal_quantile_py(p), places=11
                )
            p += 0.017

    def test_tails(self):
        for p in (1e-6, 1e-9, 1 - 1e-6, 1 - 1e-9):
            with self.subTest(p=p):
                # Extreme tails: Newton refinement on the continued-fraction
                # CDF converges to ~1e-10 relative; places=7 is the honest bar.
                self.assertAlmostEqual(
                    _rust.normal_quantile(p), _normal_quantile_py(p), places=7
                )


@unittest.skipIf(_rust is None, "Rust extension not built")
class TestMdeFromSeParity(unittest.TestCase):
    def test_defaults(self):
        for se in (0.0223606797749979, 0.0, 1e-9, 0.5, 2.0):
            with self.subTest(se=se):
                self.assertAlmostEqual(
                    mde_from_se(se), _mde_from_se_py(se), places=12
                )

    def test_alpha_power_grid(self):
        for alpha in (0.01, 0.05, 0.1):
            for power in (0.7, 0.8, 0.9):
                with self.subTest(alpha=alpha, power=power):
                    self.assertAlmostEqual(
                        mde_from_se(0.03, alpha, power),
                        _mde_from_se_py(0.03, alpha, power),
                        places=12,
                    )

    def test_matches_documented_multiplier(self):
        # At the defaults the multiplier is z_0.975 + z_0.8 = 2.801585218112968.
        self.assertAlmostEqual(
            mde_from_se(1.0) / 1.0, 2.801585218112968, places=9
        )


@unittest.skipIf(_rust is None, "Rust extension not built")
class TestMdeMcnemarParity(unittest.TestCase):
    def test_documented_reference_values(self):
        # From the metrics.py docstring: n=400/pd=20% -> 6.3pp,
        # n=200/pd=20% -> 8.9pp.
        self.assertAlmostEqual(mde_mcnemar(400, 0.2), 0.063, places=3)
        self.assertAlmostEqual(mde_mcnemar(200, 0.2), 0.089, places=3)
        self.assertAlmostEqual(_mde_mcnemar_py(400, 0.2), 0.063, places=3)
        self.assertAlmostEqual(_mde_mcnemar_py(200, 0.2), 0.089, places=3)

    def test_grid(self):
        for n in (50, 100, 400, 1000, 5000):
            for pd in (0.0, 0.05, 0.2, 0.5, 1.0):
                with self.subTest(n=n, pd=pd):
                    self.assertAlmostEqual(
                        mde_mcnemar(n, pd), _mde_mcnemar_py(n, pd), places=12
                    )

    def test_degenerate(self):
        self.assertEqual(mde_mcnemar(100, 0.0), 0.0)
        self.assertEqual(_mde_mcnemar_py(100, 0.0), 0.0)

    def test_validation_parity(self):
        # Both backends reject the same bad inputs with ValueError.
        for bad_call in (
            lambda f: f(0, 0.2),
            lambda f: f(-5, 0.2),
            lambda f: f(100, -0.1),
            lambda f: f(100, 1.5),
        ):
            with self.subTest():
                with self.assertRaises(ValueError):
                    bad_call(mde_mcnemar)
                with self.assertRaises(ValueError):
                    bad_call(_mde_mcnemar_py)


@unittest.skipIf(_rust is None, "Rust extension not built")
class TestMdeConsistency(unittest.TestCase):
    def test_mcnemar_equals_from_se(self):
        # mde_mcnemar(n, pd) == mde_from_se(sqrt(pd / n)) on both backends.
        for n, pd in ((400, 0.2), (100, 0.05), (1000, 0.5)):
            se = math.sqrt(pd / n)
            self.assertAlmostEqual(mde_mcnemar(n, pd), mde_from_se(se), places=12)
            self.assertAlmostEqual(
                _mde_mcnemar_py(n, pd), _mde_from_se_py(se), places=12
            )


class BackendUnderTest(unittest.TestCase):
    def test_backend_under_test(self):
        # Records which backend the parity suite exercised; the suite
        # must run in both modes (Rust-active and PEIRA_NO_RUST=1).
        print(f"\n[parity] rust backend active: {_rust is not None}")
        # In no-Rust mode the public functions are the twins.
        import os

        if os.environ.get("PEIRA_NO_RUST") == "1":
            self.assertIsNone(_rust)
            self.assertAlmostEqual(mde_mcnemar(400, 0.2), 0.063, places=3)
