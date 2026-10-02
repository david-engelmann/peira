"""Tests for the per-view OG/social renderers in site/scripts/render_og.py.

Program B B5: every data view gets its own social image instead of sharing
the leaderboard one. These tests lock in the honesty contract: every number
on every image comes straight from the site-data JSON, mock builds carry
the mock banner, and rendering is deterministic.
"""

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "python"))
sys.path.insert(0, str(REPO / "site" / "scripts"))

import render_og


def make_data(mock=True, n_runs=3):
    """Minimal site-data payload: n_runs guardrail runs in the public suite,
    each with per-family blocks and benign accuracy."""
    runs = []
    families = ["negation_games", "distractor_flooding", "policy_paraphrase"]
    for i in range(n_runs):
        per_family = {}
        for j, fam in enumerate(families):
            asr = round(0.1 * (i + 1) + 0.05 * j, 4)
            per_family[fam] = {"asr": asr, "asr_ci95": [asr - 0.02, asr + 0.02]}
        runs.append({
            "adapter_name": f"mock-{i}",
            "adapter_version": "1",
            "suite": "public",
            "division": "guardrail",
            "metrics": {
                "asr_conditional": round(0.2 + 0.1 * i, 4),
                "asr_ci95": [0.15 + 0.1 * i, 0.25 + 0.1 * i],
                "benign_accuracy": round(0.9 - 0.02 * i, 4),
                "benign_accuracy_ci95": [0.88 - 0.02 * i, 0.92 - 0.02 * i],
                "n_eligible": 100,
                "per_family": per_family,
            },
        })
    return {
        "mock_data": mock,
        "peira_version": "0.1.0",
        "dataset": {"version": "9.9.9-test"},
        "runs": runs,
    }


def scored_for(data):
    """Run the real load_runs loader against a temp site-data file so the
    tests exercise the same filtering the CLI uses."""
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        path = Path(f.name)
    try:
        _, scored = render_og.load_runs(path, "public", "guardrail")
    finally:
        path.unlink()
    return scored


class RenderOgViewsTest(unittest.TestCase):
    def test_all_views_render(self):
        data = make_data()
        scored = scored_for(data)
        for view in sorted(render_og.VIEWS):
            if view == "leaderboard":
                continue  # covered by the pre-existing leaderboard path
            svg, alt = render_og.render_view(view, data, scored, 8, "public",
                                             "guardrail", "0.1.0")
            self.assertTrue(svg.startswith("<svg"), view)
            self.assertIn("</svg>", svg, view)
            self.assertTrue(alt.strip(), view)

    def test_deterministic(self):
        data = make_data()
        scored = scored_for(data)
        for view in ("families", "calibration", "frontier", "compare",
                     "cases", "methodology"):
            a, _ = render_og.render_view(view, data, scored, 8, "public",
                                         "guardrail", "0.1.0")
            b, _ = render_og.render_view(view, data, scored, 8, "public",
                                         "guardrail", "0.1.0")
            self.assertEqual(a, b, view)

    def test_mock_banner_present_when_mock(self):
        data = make_data(mock=True)
        scored = scored_for(data)
        for view in ("families", "methodology", "cases"):
            svg, alt = render_og.render_view(view, data, scored, 8, "public",
                                             "guardrail", "0.1.0")
            self.assertIn("MOCK DATA, NOT REAL RESULTS", svg, view)
            self.assertIn("MOCK DATA", alt, view)

    def test_no_mock_banner_when_real(self):
        data = make_data(mock=False)
        scored = scored_for(data)
        svg, _ = render_og.render_view("families", data, scored, 8, "public",
                                       "guardrail", "0.1.0")
        self.assertNotIn("MOCK DATA", svg)

    def test_families_numbers_traceable(self):
        # Every data percentage on the families image must match a
        # per-family ASR from the input JSON. Nothing may be invented.
        # (Gridline axis labels are excluded: they are the 0-100 scale,
        # not data claims.)
        data = make_data()
        scored = scored_for(data)
        svg, _ = render_og.render_view("families", data, scored, 8, "public",
                                       "guardrail", "0.1.0")
        known = set()
        for r in data["runs"]:
            for fm in r["metrics"]["per_family"].values():
                known.add(f"{fm['asr'] * 100:.1f}%")
        # Bold labels are the bar values; gridlines are font-size 14.
        shown = set(re.findall(r'font-weight="bold"[^>]*>(\d+\.\d%)<', svg))
        self.assertTrue(shown, "families image should show percentages")
        self.assertLessEqual(shown, known,
                             f"invented numbers on families image: {shown - known}")

    def test_compare_needs_two_adapters(self):
        data = make_data(n_runs=1)
        scored = scored_for(data)
        with self.assertRaises(SystemExit):
            render_og.render_view("compare", data, scored, 8, "public",
                                  "guardrail", "0.1.0")

    def test_unknown_view_fails(self):
        data = make_data()
        with self.assertRaises(SystemExit):
            render_og.render_view("nope", data, [], 8, "public",
                                  "guardrail", "0.1.0")

    def test_methodology_makes_no_data_claims(self):
        # The methodology card is a text card: no invented percentages.
        data = make_data()
        svg, _ = render_og.render_view("methodology", data, [], 8, "public",
                                       "guardrail", "0.1.0")
        self.assertNotRegex(svg, r"\d+\.\d%")

    def test_views_registry_covers_all_data_pages(self):
        # Every data page must have a corresponding OG view, and the
        # leaderboard keeps its existing image name.
        self.assertEqual(render_og.VIEWS["leaderboard"], "og-leaderboard")
        for view in ("families", "calibration", "frontier", "compare",
                     "cases", "methodology"):
            self.assertIn(view, render_og.VIEWS)
            self.assertTrue(render_og.VIEWS[view].startswith("og-"))


if __name__ == "__main__":
    unittest.main()
