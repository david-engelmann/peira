"""Corpus tests for the evidence_positioning v2 family (family 23).

These tests pin the authoring contract: paired evidence-reordering
construction with byte-identical fact multisets, exact severity/primitive
mixes, and the invariants that separate evidence_positioning from
retrieval_poisoning (no new facts) and verbosity_inflation (no
presentation change).

unittest.TestCase style: CI runs `python -m pytest tests -n auto`
with `pip install -e .[dev]` (pytest, pytest-xdist, pytest-timeout), so
this module must not import pytest and must expose its tests as TestCase
methods (pytest discovers unittest.TestCase natively).
"""

import json
import re
import unittest
from collections import Counter
from pathlib import Path

from peira.cli import _SEMVER_RE

REPO = Path(__file__).resolve().parents[1]
CASES_PATH = REPO / "dataset" / "v2" / "cases" / "evidence_positioning.jsonl"


def load_cases():
    cases = []
    with open(CASES_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


CASES = load_cases()


def benign_prompt(case):
    return case["benign"]["input"]["prompt"]


def attacked_prompt(case):
    return case["attacked"]["input"]["prompt"]


def evidence_lines(prompt):
    """Extract the numbered evidence lines from a prompt."""
    lines = []
    for line in prompt.splitlines():
        m = re.match(r"^\d+\.\s+(.*)$", line.strip())
        if m:
            lines.append(m.group(1))
    return lines


class TestComposition(unittest.TestCase):
    def test_exact_totals(self):
        self.assertEqual(len(CASES), 420)

    def test_severity_mix(self):
        self.assertEqual(
            dict(Counter(c["severity"] for c in CASES)),
            {"critical": 80, "high": 100, "medium": 240},
        )

    def test_primitive_mix(self):
        self.assertEqual(
            dict(Counter(c["primitive"] for c in CASES)),
            {"choice": 315, "abstain": 53, "score": 52},
        )

    def test_case_ids_sequential(self):
        expected = [f"v2-evpos-{i:04d}" for i in range(1, 421)]
        self.assertEqual([c["case_id"] for c in CASES], expected)

    def test_family_field(self):
        for c in CASES:
            self.assertEqual(c["family"], "evidence_positioning")


class TestPairing(unittest.TestCase):
    def test_byte_identical_fact_multisets(self):
        """Attacked and benign use the same six facts; only order differs."""
        for c in CASES:
            b_lines = evidence_lines(benign_prompt(c))
            a_lines = evidence_lines(attacked_prompt(c))
            self.assertEqual(len(b_lines), 6, c["case_id"])
            self.assertEqual(len(a_lines), 6, c["case_id"])
            self.assertEqual(
                Counter(b_lines), Counter(a_lines), c["case_id"]
            )

    def test_orders_differ(self):
        for c in CASES:
            b_lines = evidence_lines(benign_prompt(c))
            a_lines = evidence_lines(attacked_prompt(c))
            self.assertNotEqual(b_lines, a_lines, c["case_id"])

    def test_distinct_prompt_pairs(self):
        pairs = {(benign_prompt(c), attacked_prompt(c)) for c in CASES}
        self.assertEqual(len(pairs), 420)

    def test_options_identical_across_arms(self):
        for c in CASES:
            b_opts = c["benign"]["input"]["options"]
            a_opts = c["attacked"]["input"]["options"]
            self.assertEqual(b_opts, a_opts, c["case_id"])
            self.assertEqual(b_opts, sorted(b_opts), c["case_id"])

    def test_no_non_ascii_in_prompts(self):
        for c in CASES:
            for prompt in (benign_prompt(c), attacked_prompt(c)):
                self.assertTrue(
                    all(ord(ch) < 128 for ch in prompt), c["case_id"]
                )


class TestDecisions(unittest.TestCase):
    def test_expected_and_target_differ(self):
        for c in CASES:
            if c["primitive"] == "choice":
                exp = c["benign"]["expected_decision"]
                tgt = c["attacked"]["target_decision"]
                self.assertNotEqual(exp, tgt, c["case_id"])
                self.assertIn(exp, c["benign"]["input"]["options"])
                self.assertIn(tgt, c["attacked"]["input"]["options"])


class TestManifest(unittest.TestCase):
    def test_mde_row_pinned(self):
        manifest_path = REPO / "dataset" / "v2" / "cases" / "manifest.json"
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
        mde = manifest["mdes"]["evidence_positioning"]
        self.assertEqual(
            (mde["pd_10"], mde["pd_20"], mde["pd_30"], mde["pd_40"]),
            (4.4, 6.3, 7.7, 8.9),
        )
        # The version must be valid semver, using cli.py's canonical
        # semver regex as the definition; pinning a literal here rotted
        # on every dataset bump (it was still "2.2.0" at 2.3.x).
        self.assertIsNotNone(
            _SEMVER_RE.fullmatch(manifest["dataset_version"]))


if __name__ == "__main__":
    unittest.main()
