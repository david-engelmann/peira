"""Rust-parity tests for the calibration SVG core (rust-max slice 7).

Byte-identical parity: the Rust core must produce character-for-character
the same SVG (or withheld placeholder) as the pure-Python twins on every
gated input. The twins are the PEIRA_NO_RUST=1 fallback, so this file
proves the dispatched path agrees with the fallback path.

Tests are skipped when the Rust extension is unavailable.
"""

import random
import unittest

from peira._rust import _impl as _rust, RUST_AVAILABLE
from peira.calibration import (
    _reliability_diagram_svg_py,
    _require_reliability_rust_input,
    _require_risk_coverage_rust_input,
    _risk_coverage_diagram_svg_py,
    reliability_diagram_svg,
    risk_coverage_diagram_svg,
)


@unittest.skipUnless(RUST_AVAILABLE, "Rust extension not available")
class TestReliabilityParity(unittest.TestCase):
    def assertParity(self, block, title):
        """Rust binding output is byte-identical to the Python twin."""
        if not _require_reliability_rust_input(block):
            self.skipTest("gate excludes this input by design")
        expected = _reliability_diagram_svg_py(block, title)
        actual = _rust.calibration_reliability_diagram_svg(block, title)
        self.assertEqual(actual, expected)

    def test_valid_blocks_byte_identical(self):
        rng = random.Random(20261002)
        for trial in range(100):
            bins = [
                {
                    "mean_forecast": rng.random(),
                    "mean_outcome": rng.random(),
                    "n": rng.randint(0, 500),
                    "edge_lo": 0.0,
                    "edge_hi": 1.0,
                }
                for _ in range(rng.randint(1, 12))
            ]
            block = {
                "bins": bins,
                "n": rng.randint(0, 2000),
                "sufficient": rng.random() < 0.9,
            }
            self.assertParity(block, f"Reliability (trial {trial})")

    def test_title_escaping_byte_identical(self):
        block = {
            "bins": [{"n": 10, "mean_forecast": 0.8, "mean_outcome": 0.7}],
            "n": 10,
            "sufficient": True,
        }
        for title in (
            "<script>alert(1)</script>",
            'a&b"c\'d',
            "plain title",
            "unicode: \u00e9\u4e2d\u2764",
            "",
        ):
            self.assertParity(block, title)

    def test_withheld_blocks_byte_identical(self):
        cases = [
            {"bins": None, "n": 5, "sufficient": False},
            {},
            {"bins": [], "n": 10, "sufficient": True},
            {"bins": [{"n": 0, "mean_forecast": 0.8, "mean_outcome": 0.7}],
             "n": 0, "sufficient": True},
            {"bins": [{"n": 1}], "n": 1, "sufficient": True},  # missing keys
            {"bins": [{"n": 5, "mean_forecast": 1.5, "mean_outcome": 0.5}],
             "n": 5, "sufficient": True},  # out of range
            {"bins": [{"n": 5, "mean_forecast": 0.8, "mean_outcome": 0.7}],
             "n": 5, "sufficient": 0},  # falsy sufficient
            {"bins": [{"n": 5, "mean_forecast": None, "mean_outcome": 0.7}],
             "n": 5, "sufficient": True},  # None field
            {"bins": [{"n": 5, "mean_forecast": 0.8, "mean_outcome": 0.7}],
             "n": None, "sufficient": True},  # None n -> 0
            {"bins": [{"n": 5, "mean_forecast": 0.8, "mean_outcome": 0.7}],
             "n": 3.9, "sufficient": True},  # float n -> 3
            {"bins": [{"n": True, "mean_forecast": 0.8, "mean_outcome": 0.7}],
             "n": 1, "sufficient": True},  # bool n
            {"bins": [{"n": -2, "mean_forecast": 0.8, "mean_outcome": 0.7}],
             "n": 1, "sufficient": True},  # negative count skipped
            {"bins": [{"n": 3.7, "mean_forecast": 0.8, "mean_outcome": 0.7}],
             "n": 1, "sufficient": True},  # float n truncates
        ]
        for i, block in enumerate(cases):
            with self.subTest(i=i):
                self.assertParity(block, "t")

    def test_large_float_counts_byte_identical(self):
        # Float counts near 2^63 pass the gate; int() truncation must match.
        block = {
            "bins": [{"n": 1e16, "mean_forecast": 0.8, "mean_outcome": 0.7}],
            "n": 1e16,
            "sufficient": True,
        }
        self.assertTrue(_require_reliability_rust_input(block))
        self.assertParity(block, "t")
        # At/above 2^63 the gate excludes; the twin still handles it.
        block2 = {
            "bins": [{"n": 1e19, "mean_forecast": 0.8, "mean_outcome": 0.7}],
            "n": 5,
            "sufficient": True,
        }
        self.assertFalse(_require_reliability_rust_input(block2))
        self.assertEqual(
            reliability_diagram_svg(block2, "t"),
            _reliability_diagram_svg_py(block2, "t"),
        )

    def test_dispatched_matches_twin(self):
        """The public dispatched function equals the twin on gated inputs."""
        block = {
            "bins": [
                {"n": 10, "mean_forecast": 0.8, "mean_outcome": 0.7},
                {"n": 20, "mean_forecast": 0.9, "mean_outcome": 0.95},
            ],
            "n": 30,
            "sufficient": True,
        }
        self.assertEqual(
            reliability_diagram_svg(block, "t"),
            _reliability_diagram_svg_py(block, "t"),
        )

    def test_gate_exclusions_fall_back_to_twin(self):
        """Gate-failing inputs still behave exactly as before (twin)."""
        # String numerics: the twin parses them; the gate sends them there.
        block = {
            "bins": [{"n": "5", "mean_forecast": "0.8", "mean_outcome": 0.7}],
            "n": 5,
            "sufficient": True,
        }
        self.assertFalse(_require_reliability_rust_input(block))
        out = reliability_diagram_svg(block, "t")
        self.assertTrue(out.startswith("<svg"))
        self.assertEqual(out, _reliability_diagram_svg_py(block, "t"))
        # Non-dict blocks never reach Rust.
        for bad in (None, "not-a-dict", 42, {"bins": "nope", "n": 30,
                                             "sufficient": True}):
            self.assertFalse(_require_reliability_rust_input(bad))
            self.assertEqual(
                reliability_diagram_svg(bad, "t"),
                _reliability_diagram_svg_py(bad, "t"),
            )

    def test_subclass_inputs_fall_back_to_twin(self):
        """Subclasses with overridden dunders go to the twin (exact-type gates)."""

        class EvilFloat(float):
            def __float__(self):
                return 0.999

        class EvilDict(dict):
            def get(self, key, default=None):
                if key == "n":
                    return 12345
                return super().get(key, default)

        base = {
            "bins": [{"n": 10, "mean_forecast": 0.8, "mean_outcome": 0.7}],
            "n": 10,
            "sufficient": True,
        }
        evil_block = EvilDict(base)
        evil_block["bins"] = [
            {"n": 10, "mean_forecast": EvilFloat(0.1), "mean_outcome": 0.7}
        ]
        self.assertFalse(_require_reliability_rust_input(evil_block))
        self.assertEqual(
            reliability_diagram_svg(evil_block, "t"),
            _reliability_diagram_svg_py(evil_block, "t"),
        )


@unittest.skipUnless(RUST_AVAILABLE, "Rust extension not available")
class TestRiskCoverageParity(unittest.TestCase):
    def assertParity(self, sp, title):
        if not _require_risk_coverage_rust_input(sp):
            self.skipTest("gate excludes this input by design")
        expected = _risk_coverage_diagram_svg_py(sp, title)
        actual = _rust.calibration_risk_coverage_diagram_svg(sp, title)
        self.assertEqual(actual, expected)

    def test_valid_curves_byte_identical(self):
        rng = random.Random(20261003)
        for trial in range(100):
            curve = [
                [rng.random(), rng.random()]
                for _ in range(rng.randint(1, 10))
            ]
            sp = {
                "risk_coverage_curve": curve,
                "n": rng.randint(0, 500),
                "sufficient": rng.random() < 0.9,
            }
            self.assertParity(sp, f"Selective-risk (trial {trial})")

    def test_withheld_curves_byte_identical(self):
        cases = [
            {"n": 5, "sufficient": False, "risk_coverage_curve": None},
            {},
            {"n": 40, "sufficient": True, "risk_coverage_curve": []},
            {"n": 40, "sufficient": True,
             "risk_coverage_curve": [[0.5, 0.2], [None, 0.1]]},
            {"n": 40, "sufficient": True,
             "risk_coverage_curve": [[1.5, 0.2]]},  # out of range
            {"n": 40, "sufficient": True,
             "risk_coverage_curve": [[0.5, 0.2], [0.25, True]]},  # bool
            {"n": 2.5, "sufficient": True,
             "risk_coverage_curve": [[0.5, 0.2]]},  # float n
        ]
        for i, sp in enumerate(cases):
            with self.subTest(i=i):
                self.assertParity(sp, "t")

    def test_dispatched_matches_twin(self):
        sp = {
            "risk_coverage_curve": [[1.0, 0.2], [0.5, 0.1], [0.25, 0.05]],
            "n": 40,
            "sufficient": True,
        }
        self.assertEqual(
            risk_coverage_diagram_svg(sp, "t"),
            _risk_coverage_diagram_svg_py(sp, "t"),
        )

    def test_gate_exclusions_fall_back_to_twin(self):
        sp = {
            "n": 40,
            "sufficient": True,
            "risk_coverage_curve": [["a", "b"]],
        }
        self.assertFalse(_require_risk_coverage_rust_input(sp))
        self.assertEqual(
            risk_coverage_diagram_svg(sp, "t"),
            _risk_coverage_diagram_svg_py(sp, "t"),
        )
        self.assertFalse(_require_risk_coverage_rust_input(None))
        self.assertEqual(
            risk_coverage_diagram_svg(None, "t"),
            _risk_coverage_diagram_svg_py(None, "t"),
        )


if __name__ == "__main__":
    unittest.main()
