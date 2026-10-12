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

    def test_family_breakdown_renders_mapping_shape(self):
        # The data layer emits per-run families as a mapping keyed by
        # family name, with the case count under "n". The detail view
        # must render those rows, not an empty table.
        payload = _payload()
        payload["ranked"][0]["detail"] = {
            "families": {
                "retrieval_poisoning": {
                    "family": "retrieval_poisoning",
                    "asr": 0.7672,
                    "asr_ci95": [0.726, 0.804],
                    "n": 470,
                },
            },
            "calibration": {},
        }
        page = leaderboard_to_html(payload)
        self.assertIn("retrieval_poisoning", page)
        self.assertIn("0.7672", page)
        self.assertIn("<td>470</td>", page)

    def test_provenance_falls_back_to_row_fields(self):
        # An unfiltered payload carries no suite or dataset version at
        # the top level. The block must read them from the rows rather
        # than rendering n/a, and its date range must cover unranked
        # rows too.
        payload = _payload()
        payload["ranked"][0]["suite"] = "v2"
        payload["ranked"][0]["dataset_version"] = "2.6.0"
        payload["ranked"][0]["created_utc"] = "2026-10-07T00:00:00+00:00"
        payload["unranked"][0]["created_utc"] = "2026-10-12T00:00:00+00:00"
        page = leaderboard_to_html(payload)
        self.assertIn("<dt>Suite</dt><dd>v2</dd>", page)
        self.assertIn("<dt>Dataset</dt><dd>2.6.0</dd>", page)
        self.assertIn("2026-10-07 to 2026-10-12", page)

    def test_run_notes_absent_for_unaffected_models(self):
        page = leaderboard_to_html(_payload())
        self.assertNotIn("Run notes", page)
        self.assertNotIn("thinking mode", page)

    def test_run_notes_disclose_mixed_config_runs(self):
        payload = _payload()
        payload["ranked"].append({
            "adapter_name": "moonshot-structured",
            "adapter_version": "kimi-k3",
            "asr_conditional": 0.30,
            "asr_ci95": [0.25, 0.35],
            "benign_accuracy": 0.95,
            "n_eligible": 400,
            "total_cost_usd": 1.00,
            "latency_ms_p50_attacked": 100.0,
            "ece_attacked": 0.05,
        })
        payload["unranked"].append({
            "adapter_name": "google-structured",
            "adapter_version": "gemini-3.8-flash",
            "reason": "benign accuracy below ranking floor",
        })
        page = leaderboard_to_html(payload)
        self.assertIn("Run notes", page)
        self.assertIn("Moonshot run (kimi-k3)", page)
        self.assertIn("first 3,274 cases", page)
        self.assertIn("Google run (gemini-3.8-flash)", page)
        self.assertIn("first 1,610 cases", page)

    def test_charts_are_inline_svg(self):
        page = leaderboard_to_html(_payload())
        self.assertIn("<svg", page)
        # CI whiskers render as line elements inside the chart svg.
        # The page header carries a small logo svg before the chart, so
        # select the chart by its class rather than the first svg.
        chart_start = page.index('<svg class="chart"')
        svg = page[chart_start:page.index("</svg>", chart_start)]
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
        self.assertIn("No ranked models with ASR data", page)
        self.assertIn("MOCK DATA", page)

    def test_is_one_file(self):
        page = leaderboard_to_html(_payload())
        self.assertTrue(page.startswith("<!DOCTYPE html>"))
        self.assertTrue(page.rstrip().endswith("</html>"))


if __name__ == "__main__":
    unittest.main()
