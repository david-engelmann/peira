"""Contract tests for self-contained HTML report artifacts (P-13).

The contract: no JavaScript, no external resources, charts as inline
SVG, every interpolated value escaped, data source bannered. These
tests pin the contract so a future edit cannot silently break it.

Run with: PYTHONPATH=python python3 -m pytest tests/test_report_html_contract.py
"""

import re
import unittest

from peira.report_html import leaderboard_to_html


def _payload():
    return {
        "ranked": [
            {
                "adapter_name": "shieldstral-1.0",
                "adapter_version": "1.0",
                "asr_conditional": 0.20,
                "asr_ci95": [0.15, 0.26],
                "benign_accuracy": 0.97,
                "n_eligible": 400,
                "total_cost_usd": 1.23,
                "latency_ms_p50_attacked": 210.5,
                "ece_attacked": 0.04,
            },
            {
                # Hostile name: markup must land inert.
                "adapter_name": "<script>alert('x')</script>",
                "adapter_version": "9.9",
                "asr_conditional": 0.60,
                "asr_ci95": [0.55, 0.65],
                "benign_accuracy": 0.90,
                "n_eligible": 400,
                "total_cost_usd": 0.50,
                "latency_ms_p50_attacked": 100.0,
                "ece_attacked": 0.10,
            },
        ],
        "unranked": [
            {
                "adapter_name": "broken-adapter",
                "adapter_version": "0.1",
                "reason": "benign accuracy below ranking floor",
            }
        ],
    }


class ContractTest(unittest.TestCase):
    def test_no_javascript(self):
        page = leaderboard_to_html(_payload())
        self.assertNotIn("<script", page.lower())

    def test_no_external_resources(self):
        page = leaderboard_to_html(_payload())
        self.assertNotIn("<link", page.lower())
        self.assertNotIn("<img", page.lower())
        for m in re.finditer(r'(src|href)\s*=\s*"([^"]*)"', page):
            self.assertFalse(m.group(2).startswith(("http://", "https://", "//")),
                             f"external resource: {m.group(0)}")

    def test_charts_are_inline_svg(self):
        page = leaderboard_to_html(_payload())
        self.assertIn("<svg", page)
        # CI whiskers render as line elements inside the svg.
        svg = page[page.index("<svg"):page.index("</svg>")]
        self.assertIn("<line", svg)
        self.assertIn("<rect", svg)

    def test_hostile_names_are_escaped(self):
        page = leaderboard_to_html(_payload())
        self.assertNotIn("<script>alert", page)
        self.assertIn("&lt;script&gt;", page)

    def test_mock_banner_is_default(self):
        page = leaderboard_to_html(_payload())
        self.assertIn("MOCK DATA", page)
        self.assertNotIn("Official results", page)

    def test_official_banner_when_declared(self):
        page = leaderboard_to_html(_payload(), data_source="official")
        self.assertIn("Official results", page)
        self.assertNotIn("MOCK DATA", page)

    def test_unranked_reasons_shown(self):
        page = leaderboard_to_html(_payload())
        self.assertIn("Not ranked", page)
        self.assertIn("benign accuracy below ranking floor", page)

    def test_ranking_content(self):
        page = leaderboard_to_html(_payload())
        self.assertIn("shieldstral-1.0", page)
        self.assertIn("0.2000", page)
        self.assertIn("0.1500 to 0.2600", page)

    def test_empty_payload_renders(self):
        page = leaderboard_to_html({"ranked": [], "unranked": []})
        # Chart degrades to a text note, never a broken page.
        self.assertIn("No ranked adapters with ASR data", page)
        self.assertIn("MOCK DATA", page)

    def test_is_one_file(self):
        page = leaderboard_to_html(_payload())
        self.assertTrue(page.startswith("<!DOCTYPE html>"))
        self.assertTrue(page.rstrip().endswith("</html>"))


if __name__ == "__main__":
    unittest.main()
