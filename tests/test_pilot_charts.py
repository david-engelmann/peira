"""Tests for the pilot SVG charts (python/peira/pilot_charts.py).

Verifies the report_html contract: no <script>, no external
resources, inline SVG, HTML-escaped values. Also checks chart
structure (axes, labels, data points).
"""

import re
import unittest

from peira.pilot_charts import (
    family_heatmap_svg,
    cost_scatter_svg,
    attack_bars_svg,
    rank_chart_svg,
)


def _matrix():
    return {
        "families": ["f1", "f2"],
        "rows": [
            {
                "adapter_name": "alpha",
                "cells": {
                    "f1": {"asr": 0.2, "asr_ci95": [0.15, 0.25]},
                    "f2": {"asr": 0.8, "asr_ci95": [0.75, 0.85]},
                },
            },
            {
                "adapter_name": "beta",
                "cells": {
                    "f1": {"asr": 0.4, "asr_ci95": [0.35, 0.45]},
                    "f2": {"asr": None, "asr_ci95": None},
                },
            },
        ],
        "column_mean_asr": {"f1": 0.3, "f2": 0.8},
    }


class _ContractMixin:
    def assert_contract(self, svg: str):
        self.assertNotIn("<script", svg.lower())
        self.assertNotIn("http://", svg)
        self.assertNotIn("https://", svg)
        self.assertIn("<svg", svg)
        self.assertIn("</svg>", svg)


class TestFamilyHeatmap(unittest.TestCase, _ContractMixin):
    def test_contract(self):
        self.assert_contract(family_heatmap_svg(_matrix()))

    def test_cells_and_labels(self):
        svg = family_heatmap_svg(_matrix())
        self.assertIn("alpha", svg)
        self.assertIn("beta", svg)
        self.assertIn("f1", svg)
        self.assertIn("f2", svg)
        # ASR values rendered in cells.
        self.assertIn("0.20", svg)
        self.assertIn("0.80", svg)
        # Missing cell renders as n/a.
        self.assertIn("n/a", svg)

    def test_escapes_names(self):
        m = _matrix()
        m["rows"][0]["adapter_name"] = '<script>alert("x")</script>'
        svg = family_heatmap_svg(m)
        self.assertNotIn("<script>alert", svg)
        self.assertIn("&lt;script&gt;", svg)

    def test_empty(self):
        svg = family_heatmap_svg({"families": [], "rows": []})
        self.assertIn("No family matrix data", svg)

    def test_color_scale(self):
        # Low ASR -> greenish, high ASR -> reddish. Check both appear.
        svg = family_heatmap_svg(_matrix())
        rects = re.findall(r'<rect[^>]*fill="(#[0-9a-f]{6})"', svg)
        self.assertTrue(len(rects) >= 3)


class TestCostScatter(unittest.TestCase, _ContractMixin):
    def _data(self):
        return {
            "rows": [
                {"adapter_name": "cheap", "total_cost_usd": 1.0,
                 "mean_asr": 0.3, "n_eligible": 1000},
                {"adapter_name": "pricey", "total_cost_usd": 100.0,
                 "mean_asr": 0.1, "n_eligible": 1000},
            ],
            "worst_mean_asr": 0.3,
        }

    def test_contract(self):
        self.assert_contract(cost_scatter_svg(self._data()))

    def test_points_labeled(self):
        svg = cost_scatter_svg(self._data())
        self.assertIn("cheap", svg)
        self.assertIn("pricey", svg)
        self.assertIn("<circle", svg)

    def test_log_scale_ticks(self):
        svg = cost_scatter_svg(self._data())
        # $1 and $100 ticks on the log axis.
        self.assertIn("$1", svg)
        self.assertIn("$100", svg)

    def test_empty(self):
        svg = cost_scatter_svg({"rows": []})
        self.assertIn("No cost data", svg)

    def test_missing_values_skipped(self):
        data = {"rows": [
            {"adapter_name": "nocost", "total_cost_usd": None, "mean_asr": 0.2},
        ]}
        svg = cost_scatter_svg(data)
        self.assertIn("No cost data", svg)


class TestAttackBars(unittest.TestCase, _ContractMixin):
    def _eff(self):
        return {
            "most_effective_attacks": [
                {"family": "zz_top", "mean_asr": 0.7},
                {"family": "yy_mid", "mean_asr": 0.5},
                {"family": "xx_low", "mean_asr": 0.2},
            ],
            "per_model": [],
        }

    def test_contract(self):
        self.assert_contract(attack_bars_svg(self._eff()))

    def test_sorted_descending(self):
        svg = attack_bars_svg(self._eff())
        # zz_top (0.7) appears before yy_mid (0.5) before xx_low (0.2).
        self.assertLess(svg.index("zz_top"), svg.index("yy_mid"))
        self.assertLess(svg.index("yy_mid"), svg.index("xx_low"))

    def test_values_shown(self):
        svg = attack_bars_svg(self._eff())
        self.assertIn("0.700", svg)

    def test_empty(self):
        svg = attack_bars_svg({"most_effective_attacks": []})
        self.assertIn("No attack effectiveness data", svg)


class TestRankChart(unittest.TestCase, _ContractMixin):
    def _ranking(self):
        return {
            "mean_ranks": [
                {"adapter_name": "a", "mean_rank": 1.2},
                {"adapter_name": "b", "mean_rank": 2.8},
            ],
            "nemenyi_cd_05": 0.9,
        }

    def test_contract(self):
        self.assert_contract(rank_chart_svg(self._ranking()))

    def test_ranks_shown(self):
        svg = rank_chart_svg(self._ranking())
        self.assertIn("1.20", svg)
        self.assertIn("2.80", svg)
        # Nemenyi CD whiskers drawn as lines.
        self.assertIn("<line", svg)

    def test_no_cd(self):
        r = self._ranking()
        r["nemenyi_cd_05"] = None
        svg = rank_chart_svg(r)
        self.assert_contract(svg)
        self.assertIn("a", svg)

    def test_empty(self):
        svg = rank_chart_svg({"mean_ranks": []})
        self.assertIn("No ranking data", svg)


if __name__ == "__main__":
    unittest.main()


class TestCostScatterEdgeCases(unittest.TestCase):
    def test_all_zero_costs(self):
        # Regression: all-zero costs (free-tier local models) crashed
        # on math.log10(0.0). Must render without error.
        cost_data = {
            "rows": [
                {"adapter_name": "a", "total_cost_usd": 0.0, "mean_asr": 0.3, "n_eligible": 100},
                {"adapter_name": "b", "total_cost_usd": 0.0, "mean_asr": 0.5, "n_eligible": 100},
            ]
        }
        svg = cost_scatter_svg(cost_data)
        self.assertIn("<svg", svg)
        self.assertIn("a", svg)
        self.assertIn("b", svg)

    def test_mixed_zero_and_positive_costs(self):
        cost_data = {
            "rows": [
                {"adapter_name": "free", "total_cost_usd": 0.0, "mean_asr": 0.3, "n_eligible": 100},
                {"adapter_name": "paid", "total_cost_usd": 10.0, "mean_asr": 0.5, "n_eligible": 100},
            ]
        }
        svg = cost_scatter_svg(cost_data)
        self.assertIn("<svg", svg)
