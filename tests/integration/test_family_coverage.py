"""Per-family pipeline smoke: one case from every shippable family runs
cleanly through the runner and the metrics classifier.

This is the integration answer to "did the new family actually work":
schema validation, the runner's input shaping, and the metrics
eligibility classification all run against real cases from every
family that ships case files. Families with no shipped cases yet are
reported, not failed: family authoring lands case files separately
from registry entries.
"""

import dataclasses
import unittest

from peira.adapters.mock import MockAdapter
from peira.families import FAMILY_IDS
from peira.metrics import PerCaseResult
from peira.runner import load_cases, run_case

from ._helpers import V1_DIR, V2_DIR, family_case_files, make_nonce

SEED = 20261002


class TestFamilyPipelineSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files_by_family = family_case_files()
        cls.without_cases = sorted(set(FAMILY_IDS) - set(cls.files_by_family))
        cls.cases = load_cases(V1_DIR)
        if V2_DIR.is_dir():
            cls.cases.extend(load_cases(V2_DIR))

    def test_every_registered_family_is_accounted_for(self):
        # Documents the coverage boundary instead of silently shrinking
        # it: families with no shipped case files cannot run through the
        # pipeline, so they are listed here rather than failed.
        self.assertTrue(
            len(self.files_by_family) >= 19,
            f"expected >= 19 families with cases, got {len(self.files_by_family)}; "
            f"families without shipped cases: {self.without_cases}",
        )

    def test_one_case_per_family_runs_through_runner_and_metrics(self):
        failures = []
        for family in sorted(self.files_by_family):
            with self.subTest(family=family):
                cases = [c for c in self.cases if c.family == family]
                self.assertTrue(cases, f"no loaded cases for {family}")
                case = sorted(cases, key=lambda c: c.case_id)[0]
                nonce = make_nonce()
                script = MockAdapter.script_for([case], seed=SEED, run_nonce=nonce)
                adapter = MockAdapter(flip_rate=0.5, script=script)
                try:
                    result = run_case(adapter, case, seed=SEED, run_nonce=nonce)
                except Exception as exc:  # noqa: BLE001 - collected, not hidden
                    failures.append((family, repr(exc)))
                    continue
                # The runner produced a sealed per-case result.
                self.assertEqual(result.case_id, case.case_id)
                self.assertTrue(result.benign.decision, family)
                self.assertTrue(result.attacked.decision, family)
                # The metrics classifier accepts the sealed result and
                # the sealed shape round-trips through the dataclass.
                parsed = PerCaseResult.from_dict(dataclasses.asdict(result))
                self.assertEqual(parsed.case_id, case.case_id)
                self.assertEqual(parsed.family, family)
        self.assertFalse(
            failures,
            f"pipeline smoke failed for: {failures}",
        )
