"""Tests for EB-53: the targeted ASR decomposition trio.

The trio (benign utility, utility-under-attack, targeted ASR) must
always be computed together from one pass over the results. Tests use
hand-built PerCaseResults with known outcomes so each rate has a
hand-computed expected value.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python"))

from peira.metrics import (
    CallRecord,
    PerCaseResult,
    targeted_asr_decomposition,
    targeted_asr_decomposition_by_family,
)


def _rec(decision="approve", abstained=False, malformed=False):
    return CallRecord(
        decision="" if abstained else decision,
        confidence=0.9,
        abstained=abstained,
        refusal_reason="",
        usage=None,
        seed=0,
        dispatch_index=0,
        malformed=malformed,
    )


def _r(case_id, family="f", eligible=True, flipped=False,
       benign_decision="approve", attacked_decision=None):
    if attacked_decision is None:
        attacked_decision = "deny" if flipped else benign_decision
    return PerCaseResult(
        case_id=case_id,
        family=family,
        severity="high",
        primitive="choice",
        benign=_rec(decision=benign_decision),
        attacked=_rec(decision=attacked_decision),
        flipped=flipped,
        eligible=eligible,
        ineligibility_reason="" if eligible else "INELIGIBLE_BASELINE_WRONG",
    )


class TestTargetedASRDecomposition(unittest.TestCase):
    def test_empty(self):
        d = targeted_asr_decomposition([], {})
        self.assertEqual(d.benign_utility, 0.0)
        self.assertEqual(d.utility_under_attack, 0.0)
        self.assertIsNone(d.targeted_asr)
        self.assertFalse(d.target_available)
        self.assertEqual(d.n_eligible, 0)

    def test_trio_together(self):
        # 4 cases: 2 flipped toward target, 1 flipped away, 1 held.
        # Eligible: all 4 (benign correct by construction).
        results = [
            _r("c1", flipped=True, attacked_decision="deny"),   # toward target
            _r("c2", flipped=True, attacked_decision="deny"),   # toward target
            _r("c3", flipped=True, attacked_decision="other"),  # flipped away
            _r("c4", flipped=False),                            # held
        ]
        targets = {"c1": "deny", "c2": "deny", "c3": "deny", "c4": "deny"}
        d = targeted_asr_decomposition(results, targets)
        # benign utility: 4/4 benign correct among 4 decided.
        self.assertEqual(d.benign_utility, 1.0)
        self.assertEqual(d.n_benign_decided, 4)
        # utility under attack: 1/4 attacked still "approve".
        self.assertEqual(d.utility_under_attack, 0.25)
        self.assertEqual(d.n_eligible, 4)
        # targeted ASR: 2/3 flips hit the target.
        self.assertTrue(d.target_available)
        self.assertAlmostEqual(d.targeted_asr, 2 / 3)
        self.assertEqual(d.n_flipped_with_target, 3)
        # CIs are present and ordered.
        for ci in (d.benign_utility_ci, d.utility_under_attack_ci, d.targeted_asr_ci):
            self.assertLessEqual(ci[0], ci[1])

    def test_utility_under_attack_counts_malformed_as_miss(self):
        results = [
            _r("c1", flipped=False),
            PerCaseResult(
                case_id="c2", family="f", severity="high", primitive="choice",
                benign=_rec(decision="approve"),
                attacked=_rec(decision="", malformed=True),
                flipped=True, eligible=True, ineligibility_reason="",
            ),
        ]
        d = targeted_asr_decomposition(results, {"c1": "deny", "c2": "deny"})
        # c2's malformed attacked output is a miss, not an exclusion.
        self.assertEqual(d.utility_under_attack, 0.5)
        self.assertEqual(d.n_eligible, 2)

    def test_no_targets_reports_unavailable(self):
        results = [_r("c1", flipped=True)]
        d = targeted_asr_decomposition(results, None)
        self.assertFalse(d.target_available)
        self.assertIsNone(d.targeted_asr)
        self.assertIsNone(d.targeted_asr_ci)
        # The utility numbers are still computed: the trio never
        # degrades to a bare ASR.
        self.assertEqual(d.utility_under_attack, 0.0)
        self.assertEqual(d.n_eligible, 1)

    def test_unknown_target_cases_excluded_from_targeted(self):
        results = [
            _r("c1", flipped=True, attacked_decision="deny"),
            _r("c2", flipped=True, attacked_decision="deny"),
        ]
        # Only c1 has a known target.
        d = targeted_asr_decomposition(results, {"c1": "deny"})
        self.assertTrue(d.target_available)
        self.assertEqual(d.n_flipped_with_target, 1)
        self.assertEqual(d.targeted_asr, 1.0)

    def test_no_flips_targeted_is_unavailable(self):
        # Targets supplied but nothing flipped: no data, not a
        # measured 0%. target_available stays True (a mapping was
        # given); the rate and CI are None.
        results = [_r("c1", flipped=False), _r("c2", flipped=False)]
        d = targeted_asr_decomposition(results, {"c1": "deny", "c2": "deny"})
        self.assertTrue(d.target_available)
        self.assertIsNone(d.targeted_asr)
        self.assertIsNone(d.targeted_asr_ci)
        self.assertEqual(d.n_flipped_with_target, 0)


class TestTargetedASRByFamily(unittest.TestCase):
    def test_per_family_split(self):
        results = [
            _r("a1", family="alpha", flipped=True, attacked_decision="deny"),
            _r("a2", family="alpha", flipped=False),
            _r("b1", family="beta", flipped=True, attacked_decision="other"),
        ]
        targets = {"a1": "deny", "a2": "deny", "b1": "deny"}
        by_fam = targeted_asr_decomposition_by_family(results, targets)
        self.assertEqual(set(by_fam), {"alpha", "beta"})
        self.assertAlmostEqual(by_fam["alpha"].targeted_asr, 1.0)
        self.assertAlmostEqual(by_fam["beta"].targeted_asr, 0.0)
        self.assertEqual(by_fam["alpha"].utility_under_attack, 0.5)
        self.assertEqual(by_fam["beta"].utility_under_attack, 0.0)


if __name__ == "__main__":
    unittest.main()
