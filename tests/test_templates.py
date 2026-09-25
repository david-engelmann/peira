"""Unit tests for generator templates (run with: python -m unittest discover tests)."""

import json
import unittest

from peira.gates import gate_families, gate_paired_variants, gate_schema
from peira.schema import CANONICAL_FAMILIES, validate_case_dict
from peira.templates import TEMPLATES, render_template, template_help


def _as_valid_triples(cases):
    return [(None, 1, c) for c in cases]


class TestTemplates(unittest.TestCase):
    def test_covers_all_canonical_families(self):
        self.assertEqual(set(TEMPLATES), set(CANONICAL_FAMILIES))

    def test_every_template_renders_valid_skeleton(self):
        for family in TEMPLATES:
            with self.subTest(family=family):
                case = render_template(family, f"{family[:2]}-001")
                self.assertEqual(validate_case_dict(case), [])
                self.assertEqual(
                    gate_schema([(None, 1, case, None)]).errors, [])
                self.assertEqual(
                    gate_families(_as_valid_triples([case])).errors, [])
                # benign and attacked differ out of the box (G2)
                self.assertEqual(
                    gate_paired_variants(_as_valid_triples([case])).errors,
                    [])

    def test_skeletons_contain_placeholders(self):
        for family in TEMPLATES:
            with self.subTest(family=family):
                text = json.dumps(render_template(family, "x-1"))
                self.assertIn("{{", text, f"{family} has no placeholders")

    def test_severity_and_primitive_overrides(self):
        case = render_template("state_poisoning", "sp-1", severity="critical",
                               primitive="score")
        self.assertEqual(case["severity"], "critical")
        self.assertEqual(case["primitive"], "score")

    def test_default_primitives(self):
        self.assertEqual(render_template("score_anchoring", "x")["primitive"],
                         "score")
        self.assertEqual(render_template("negation_games", "x")["primitive"],
                         "abstain")
        self.assertEqual(render_template("state_poisoning", "x")["primitive"],
                         "choice")

    def test_unknown_family_raises(self):
        with self.assertRaises(KeyError):
            render_template("prompt_injection", "x")

    def test_template_help(self):
        for family in TEMPLATES:
            with self.subTest(family=family):
                h = template_help(family)
                for key in ("pattern", "primitive", "severity_hint",
                            "notes_prompt"):
                    self.assertTrue(h[key], f"{family} missing {key}")


if __name__ == "__main__":
    unittest.main()
