"""Unit tests for dataset validation gates (run with: python -m unittest discover tests)."""

import json
import tempfile
import unittest
from pathlib import Path

from peira.gates import run_gates


def _case(case_id, family="state_poisoning", benign_prompt="p",
          attacked_prompt="p!", target="b", expected="a"):
    return {
        "case_id": case_id,
        "family": family,
        "primitive": "choice",
        "severity": "high",
        "benign": {"input": {"prompt": benign_prompt, "options": ["a", "b"]},
                   "expected_decision": expected},
        "attacked": {"input": {"prompt": attacked_prompt, "options": ["a", "b"]},
                     "target_decision": target},
        "notes": "",
    }


class TestGates(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, name="cases.jsonl", lines=None):
        path = self.dir / name
        path.write_text("\n".join(lines or []) + "\n")
        return path

    def _write_cases(self, cases):
        return self._write(lines=[json.dumps(c) for c in cases])

    def _results(self):
        return {r.gate_id: r for r in run_gates(self.dir)}

    def _errors(self):
        return [e for r in run_gates(self.dir) for e in r.errors]

    def test_all_gates_pass(self):
        self._write_cases([_case("c1"), _case("c2", family="indirection",
                                               benign_prompt="q",
                                               attacked_prompt="q!")])
        results = self._results()
        self.assertEqual(len(results), 6)
        self.assertEqual(self._errors(), [])
        self.assertTrue(all(r.passed for r in results.values()))

    def test_g1_bad_json(self):
        self._write(lines=['{"case_id": "c1"'])
        r = self._results()["G1"]
        self.assertFalse(r.passed)
        self.assertTrue(any("invalid JSON" in e for e in r.errors))

    def test_g1_schema_violation(self):
        bad = _case("c1")
        del bad["severity"]
        self._write_cases([bad])
        r = self._results()["G1"]
        self.assertFalse(r.passed)
        self.assertTrue(any("cases.jsonl:1" in e for e in r.errors))

    def test_g2_identical_variants(self):
        self._write_cases([_case("c1", benign_prompt="same",
                                 attacked_prompt="same")])
        r = self._results()["G2"]
        self.assertFalse(r.passed)
        self.assertTrue(any("identical to benign" in e for e in r.errors))

    def test_g2_empty_input(self):
        c = _case("c1")
        c["attacked"]["input"] = {}
        self._write_cases([c])
        r = self._results()["G2"]
        self.assertTrue(any("attacked input is empty" in e for e in r.errors))

    def test_g3_duplicate_case_id(self):
        self._write_cases([_case("c1"), _case("c1", benign_prompt="q",
                                              attacked_prompt="q!")])
        r = self._results()["G3"]
        self.assertTrue(any("duplicate case_id 'c1'" in e for e in r.errors))

    def test_g3_duplicate_content_pair(self):
        self._write_cases([_case("c1"), _case("c2")])
        r = self._results()["G3"]
        self.assertTrue(any("duplicate content pair" in e for e in r.errors))

    def test_g4_unknown_family(self):
        self._write_cases([_case("c1", family="prompt_injection")])
        r = self._results()["G4"]
        self.assertTrue(any("unknown family" in e for e in r.errors))

    def test_g5_target_equals_expected(self):
        self._write_cases([_case("c1", target="a", expected="a")])
        r = self._results()["G5"]
        self.assertTrue(any("equals the benign expected decision" in e
                            for e in r.errors))

    def test_g5_untargeted_ok(self):
        c = _case("c1")
        c["attacked"]["target_decision"] = None
        self._write_cases([c])
        self.assertTrue(self._results()["G5"].passed)

    def test_g6_pii_is_warning_not_error(self):
        c = _case("c1", attacked_prompt="contact alice@example.com now")
        self._write_cases([c])
        r = self._results()["G6"]
        self.assertTrue(r.passed)  # warnings don't fail the gate
        self.assertTrue(any("possible email address in attacked input" in w
                            for w in r.warnings))
        self.assertEqual(self._errors(), [])

    def test_gates_skip_schema_invalid_cases(self):
        # G2..G6 must not cascade noise onto cases G1 already rejected.
        bad = _case("c1")
        del bad["severity"]
        self._write_cases([bad])
        for gid in ("G2", "G3", "G4", "G5", "G6"):
            self.assertEqual(self._results()[gid].errors, [])

    def test_each_case_validated_once(self):
        # run_gates used to validate every case twice (once in G1, once
        # when filtering the valid subset). One validation per parsed
        # line is the contract now.
        from unittest import mock
        import peira.gates
        real_validate = peira.gates.validate_case_dict
        bad = _case("c2")
        del bad["severity"]
        self._write(lines=[json.dumps(_case("c1")),
                           "{not json}",
                           json.dumps(bad),
                           ""])
        with mock.patch.object(peira.gates, "validate_case_dict",
                               wraps=real_validate) as spy:
            run_gates(self.dir)
        # Two parsed lines (the bad-JSON line never reaches validation,
        # the blank line is skipped).
        self.assertEqual(spy.call_count, 2)

    def test_g1_reports_each_bad_line_once(self):
        bad = _case("c1")
        del bad["severity"]
        self._write(lines=[json.dumps(bad), "{not json}"])
        g1 = self._results()["G1"]
        self.assertFalse(g1.passed)
        self.assertEqual(len(g1.errors), 2)
        self.assertTrue(any("cases.jsonl:1:" in e for e in g1.errors))
        self.assertTrue(any("cases.jsonl:2: invalid JSON" in e
                            for e in g1.errors))


if __name__ == "__main__":
    unittest.main()
