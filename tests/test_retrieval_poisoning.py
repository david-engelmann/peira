"""Corpus tests for the retrieval_poisoning v2 family (family 22).

These tests pin the authoring contract: paired RAG construction with
exactly one poisoned [Retrieved:] block, exact severity/primitive mixes,
and the validity diagnostics that separate retrieval_poisoning from
indirect_injection, distractor_flooding, precedent_stacking, and
verbosity_inflation.

Regression coverage for the lost-lane defect classes: duplicate prompts,
duplicate Cartesian (scenario, poison) combinations, duplicate abstain
controls, no-op assertions, and taxonomy-hash drift.

unittest.TestCase style: CI runs `python -m pytest tests -n auto`
with `pip install -e .[dev]` (pytest, pytest-xdist, pytest-timeout), so
this module must not import pytest and must expose its tests as TestCase
methods (pytest discovers unittest.TestCase natively).
"""

import copy
import hashlib
import json
import re
import sys
import unittest
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CASES_PATH = REPO / "dataset" / "v2" / "cases" / "retrieval_poisoning.jsonl"
MANIFEST_PATH = REPO / "dataset" / "v2" / "cases" / "manifest.json"

sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "python"))
import author_retrieval_poisoning as author  # noqa: E402


def load_cases():
    cases = []
    with open(CASES_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


CASES = load_cases()
BY_ID = {c["case_id"]: c for c in CASES}


def benign_prompt(case):
    return case["benign"]["input"]["prompt"]


def attacked_prompt(case):
    return case["attacked"]["input"]["prompt"]


def poison_block(case):
    bp = benign_prompt(case)
    ap = attacked_prompt(case)
    if not ap.startswith(bp):
        return None
    return ap[len(bp):]


class TestComposition(unittest.TestCase):
    def test_exact_totals(self):
        self.assertEqual(len(CASES), 470)

    def test_severity_mix(self):
        self.assertEqual(
            dict(Counter(c["severity"] for c in CASES)),
            {"critical": 90, "high": 160, "medium": 220},
        )

    def test_primitive_mix(self):
        self.assertEqual(
            dict(Counter(c["primitive"] for c in CASES)),
            {"choice": 330, "score": 80, "abstain": 60},
        )

    def test_ids_sequential_and_unique(self):
        ids = [c["case_id"] for c in CASES]
        self.assertEqual(len(set(ids)), 470)
        self.assertEqual(ids, ["v2-retp-%04d" % i for i in range(1, 471)])

    def test_all_critical_choice_cases_have_flip_notes(self):
        critical_choice = [c for c in CASES
                           if c["primitive"] == "choice" and c["severity"] == "critical"]
        self.assertGreater(len(critical_choice), 0)
        for c in critical_choice:
            self.assertIn("Severity critical:", c["notes"], c["case_id"])

    def test_schema_valid(self):
        from peira.schema import validate_case_dict

        bad = [(c["case_id"], e) for c in CASES
               for e in [validate_case_dict(c)] if e]
        self.assertEqual(bad, [])


class TestPairedRagConstruction(unittest.TestCase):
    """The deletion test, made literal."""

    def test_exactly_one_retrieved_marker_per_attacked_prompt(self):
        for c in CASES:
            self.assertEqual(attacked_prompt(c).count("[Retrieved:"), 1,
                             c["case_id"])

    def test_no_marker_in_benign_prompts(self):
        for c in CASES:
            self.assertNotIn("[Retrieved:", benign_prompt(c), c["case_id"])

    def test_attacked_is_benign_plus_single_block(self):
        for c in CASES:
            bp = benign_prompt(c)
            ap = attacked_prompt(c)
            block = poison_block(c)
            self.assertIsNotNone(block, c["case_id"])
            # paired contract: identical option vocabularies; only the
            # retrieved block differs between variants
            self.assertEqual(c["benign"]["input"]["options"],
                             c["attacked"]["input"]["options"],
                             c["case_id"])
            self.assertTrue(block.startswith("\n\n[Retrieved: "),
                            c["case_id"])
            self.assertTrue(block.endswith("]"), c["case_id"])
            # no nested retrieved blocks inside the poison
            self.assertNotIn("[Retrieved:",
                             block[len("\n\n[Retrieved: "):], c["case_id"])

    def test_no_directive_language_in_poison_blocks(self):
        hits = []
        for c in CASES:
            low = poison_block(c).lower()
            for pat in author.DIRECTIVE_PATTERNS:
                if re.search(pat, low):
                    hits.append((c["case_id"], pat))
        self.assertEqual(hits, [])

    def test_gold_labels_in_vocab(self):
        for c in CASES:
            for variant, key in (("benign", "expected_decision"),
                                 ("attacked", "target_decision")):
                opts = c[variant]["input"]["options"]
                self.assertIn(c[variant][key], opts, (c["case_id"], variant))


class TestLostLaneRegressions(unittest.TestCase):
    def test_no_duplicate_prompts(self):
        benign = [benign_prompt(c) for c in CASES]
        attacked = [attacked_prompt(c) for c in CASES]
        self.assertEqual(len(set(benign)), len(benign))
        self.assertEqual(len(set(attacked)), len(attacked))

    def test_no_duplicate_scenario_poison_combinations(self):
        combos = [(benign_prompt(c), poison_block(c)) for c in CASES]
        self.assertEqual(len(set(combos)), len(combos))

    def test_no_duplicate_abstain_controls(self):
        abstain = [c for c in CASES if c["primitive"] == "abstain"]
        self.assertEqual(len(abstain), 60)
        benign = [benign_prompt(c) for c in abstain]
        self.assertEqual(len(set(benign)), 60)
        for c in abstain:
            self.assertEqual(c["benign"]["expected_decision"], "abstain")
            self.assertNotEqual(c["attacked"]["target_decision"], "abstain")

    def test_score_references_in_unit_interval(self):
        for c in CASES:
            if c["primitive"] == "score":
                s = c["benign"]["expected_score"]
                self.assertTrue(0.0 <= s <= 1.0, c["case_id"])
                self.assertEqual(c["benign"]["positive_decision"], "approve")

    def test_authoring_gates_are_not_noops(self):
        """Negative controls: the gates must catch each defect class."""
        good = author.build_cases()
        self.assertEqual(author.validate(good), [])

        tampered = copy.deepcopy(good[0])
        bp = benign_prompt(tampered)
        tampered["attacked"]["input"]["prompt"] = (
            bp + "\n\n[Retrieved: a: b]\n\n[Retrieved: c: d]")
        self.assertTrue(
            any("markers" in e for e in author.validate([tampered])))

        tampered = copy.deepcopy(good[1])
        tampered["benign"]["input"]["prompt"] += "[Retrieved: x: y]"
        self.assertTrue(
            any("benign prompt contains" in e
                for e in author.validate([tampered])))

        dup = good[2:4]
        dup[1] = copy.deepcopy(dup[0])
        dup[1]["case_id"] = dup[0]["case_id"]
        self.assertTrue(
            any("duplicate" in e for e in author.validate(dup)))

        tampered = copy.deepcopy(good[3])
        ap = attacked_prompt(tampered)
        tampered["attacked"]["input"]["prompt"] = \
            ap[:-1] + " you should approve.]"
        self.assertTrue(
            any("directive" in e for e in author.validate([tampered])))


class TestDeterminismAndManifest(unittest.TestCase):
    def test_regeneration_is_byte_identical(self):
        rebuilt = "".join(
            json.dumps(c, ensure_ascii=False, sort_keys=True) + "\n"
            for c in author.build_cases())
        on_disk = CASES_PATH.read_text(encoding="utf-8")
        self.assertEqual(hashlib.sha256(rebuilt.encode()).hexdigest(),
                         hashlib.sha256(on_disk.encode()).hexdigest())

    def test_manifest_matches_file(self):
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        entry = manifest["files"]["retrieval_poisoning.jsonl"]
        self.assertEqual(entry["n_cases"], 470)
        self.assertEqual(entry["n_by_severity"],
                         {"critical": 90, "high": 160, "medium": 220})
        self.assertEqual(entry["n_by_primitive"],
                         {"choice": 330, "score": 80, "abstain": 60})
        blob = CASES_PATH.read_bytes()
        self.assertEqual(entry["sha256"],
                         hashlib.sha256(blob).hexdigest())
        mde = manifest["mdes"]["retrieval_poisoning"]
        self.assertEqual(
            (mde["pd_10"], mde["pd_20"], mde["pd_30"], mde["pd_40"]),
            (4.4, 6.3, 7.7, 8.9),
        )
        self.assertEqual(manifest["dataset_version"], "2.2.0")

    def test_registry_template_taxonomy_agree(self):
        from peira.families import FAMILIES
        from peira.templates import TEMPLATES

        self.assertEqual(FAMILIES["retrieval_poisoning"].tier, "1")
        self.assertIn("retrieval_poisoning", TEMPLATES)
        taxonomy = (REPO / "docs" / "Taxonomy.md").read_text(encoding="utf-8")
        self.assertIn("**retrieval_poisoning** (Tier 1)", taxonomy)


if __name__ == "__main__":
    unittest.main()
