"""Tests for the pilot HTML report (python/peira/pilot_report.py).

Verifies the report_html contract: no <script>, no external resources,
HTML-escaped values. Regression tests for the pairwise table structure.
"""

import unittest

from peira.pilot_report import (
    _pairwise_table,
    _models_table,
    _cost_table,
    render_pilot_report,
)


def _pairwise():
    return {
        "pairs": [
            {
                "adapter_a": "alpha",
                "adapter_b": "beta",
                "n_paired": 100,
                "p_value": 0.0123,
                "p_value_adjusted": 0.0456,
                "significant_at_05": True,
            },
            {
                "adapter_a": "alpha",
                "adapter_b": "gamma",
                "n_paired": 95,
                "p_value": None,
                "p_value_adjusted": None,
                "significant_at_05": None,
            },
        ],
        "n_models": 3,
    }


class TestPairwiseTable(unittest.TestCase):
    def test_wellformed_with_floats(self):
        html = _pairwise_table(_pairwise())
        # Each row must have all 6 columns: A, B, n, p, p_adj, sig.
        # Regression: implicit-concat + conditional precedence once
        # dropped the p_adj and sig columns (malformed <tr>).
        self.assertIn("<td>0.0123</td>", html)
        self.assertIn("<td>0.0456</td>", html)
        self.assertIn('<td class="sig">yes</td></tr>', html)
        # Row count: 2 data rows.
        self.assertEqual(html.count("<tr><td>"), 2)

    def test_wellformed_with_nones(self):
        html = _pairwise_table(_pairwise())
        # None p-values render as n/a, row still well-formed.
        self.assertIn(
            "<tr><td>alpha</td><td>gamma</td><td>95</td>"
            "<td>n/a</td><td>n/a</td>"
            '<td class="nonsig">n/a</td></tr>',
            html,
        )

    def test_escapes_adapter_names(self):
        pw = {
            "pairs": [
                {
                    "adapter_a": "<script>alert(1)</script>",
                    "adapter_b": "beta",
                    "n_paired": 10,
                    "p_value": 0.5,
                    "p_value_adjusted": 0.5,
                    "significant_at_05": False,
                }
            ]
        }
        html = _pairwise_table(pw)
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_empty(self):
        html = _pairwise_table({"pairs": []})
        self.assertIn("<tbody>", html)
        self.assertNotIn("<tr><td>", html)


class TestReportContract(unittest.TestCase):
    def _report(self):
        return {
            "n_models": 2,
            "models": [
                {"adapter_name": "a", "adapter_version": "1", "run_id": "r1"},
                {"adapter_name": "b", "adapter_version": "1", "run_id": "r2"},
            ],
            "family_matrix": {"families": [], "rows": []},
            "attack_effectiveness": {"most_effective_attacks": [], "per_model": []},
            "pairwise_significance": _pairwise(),
            "ranking": {"error": "need at least 2 models and 1 family"},
            "cost_effectiveness": {"rows": [], "worst_mean_asr": None},
        }

    def test_no_script(self):
        html = render_pilot_report(self._report())
        self.assertNotIn("<script", html.lower())

    def test_sections_present(self):
        html = render_pilot_report(self._report())
        for section in [
            "Per-Model x Per-Family ASR",
            "Most Effective Attacks",
            "Model Ranking",
            "Pairwise Significance",
            "Cost Effectiveness",
        ]:
            self.assertIn(section, html)


if __name__ == "__main__":
    unittest.main()
