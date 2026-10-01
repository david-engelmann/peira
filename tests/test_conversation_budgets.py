"""EB-15 attacker budgets + EB-16/EB-60 conversational metric blocks.

Exercises the attacker budgets end to end on tiny offline fixtures:
round and token truncation (attacked arm only), budget validation,
config sealing in the suite artifact, resume mismatch rejection,
``attack_budget_exhausted`` serialization, and the new summary
blocks (rounds-to-first-flip, attacker tokens, exhaustion rate,
confidence erosion, refusal taxonomy, per-turn diagnostics). Also
pins the CLI flags' validation errors. All offline and xdist-safe
(no shared mutable state).
"""

import contextlib
import io
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from peira.adapters.base import CallUsage, ChoiceOutput
from peira.adapters.mock import MockAdapter
from peira.cli import (
    EXIT_OK,
    EXIT_USER_ERROR,
    build_parser,
    cmd_run,
)
from peira.conversation import (
    CONVERSATION_DISPATCH_STRIDE,
    ConversationResult,
    load_conversation_cases,
    run_conversation_case,
    run_conversation_suite,
    validate_conversation_partial,
)
from peira.conversation_metrics import (
    attacked_arm_tokens,
    erosion_class,
    per_turn_diagnostics,
    refusal_quality,
    rounds_to_first_flip,
    summarize_conversation,
    turn_refusal_class,
)
from peira.runner import new_run_nonce

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "conversational"


def _load_fixture_cases():
    return load_conversation_cases(FIXTURES)


def _mock(cases, seed=0, flip_rate=0.0, nonce=None):
    nonce = nonce or new_run_nonce()
    adapter = MockAdapter(
        seed="test",
        flip_rate=flip_rate,
        script=MockAdapter.script_for_conversation(
            cases, seed=seed, run_nonce=nonce
        ),
    )
    return adapter, nonce


class _UsageAdapter:
    """Adapter reporting fixed per-turn usage (for token budgets)."""

    def __init__(self, decision="approve", tokens_in=100, tokens_out=50,
                 confidence=0.9):
        self.name = "usage"
        self.decision = decision
        self.tokens_in = tokens_in
        self.tokens_out = tokens_out
        self.confidence = confidence

    def decide_turn(self, turn_input, primitive, context=None):
        return ChoiceOutput(
            decision=self.decision,
            confidence=self.confidence,
            usage=CallUsage(
                model="test-model",
                tokens_in=self.tokens_in,
                tokens_out=self.tokens_out,
                latency_ms=1.0,
                cost_usd=0.0,
            ),
        )


class TestAttackBudgetValidation(unittest.TestCase):
    def test_rejects_non_positive_and_non_int(self):
        cases = _load_fixture_cases()
        adapter, nonce = _mock(cases)
        for bad in (0, -1, -100, True, False, "3", 1.5):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    run_conversation_case(
                        adapter, cases[0], seed=0, run_nonce=nonce,
                        max_attacker_rounds=bad,
                    )
                with self.assertRaises(ValueError):
                    run_conversation_case(
                        adapter, cases[0], seed=0, run_nonce=nonce,
                        attacker_token_budget=bad,
                    )

    def test_accepts_positive_int(self):
        cases = _load_fixture_cases()
        adapter, nonce = _mock(cases)
        result = run_conversation_case(
            adapter, cases[0], seed=0, run_nonce=nonce,
            max_attacker_rounds=5, attacker_token_budget=10_000,
        )
        # Budgets above the authored trajectory: full run, no flag.
        self.assertFalse(result.attack_budget_exhausted)
        self.assertEqual(len(result.attacked_turns), 2)
        self.assertEqual(len(result.benign_turns), 2)


class TestRoundBudget(unittest.TestCase):
    def test_truncates_attacked_arm_only(self):
        cases = _load_fixture_cases()
        adapter, nonce = _mock(cases, flip_rate=0.0)
        result = run_conversation_case(
            adapter, cases[0], seed=0, run_nonce=nonce,
            max_attacker_rounds=1,
        )
        # Attacked arm stops after round 1; the benign control always
        # runs the full authored trajectory.
        self.assertEqual(len(result.attacked_turns), 1)
        self.assertEqual(len(result.benign_turns), 2)
        self.assertTrue(result.attack_budget_exhausted)
        # The turn that reached the budget is kept, not dropped.
        self.assertEqual(result.attacked_turns[0].decision, "deny")
        # Scoring falls back to the last executed attacked turn.
        self.assertEqual(result.attacked.decision, "deny")
        self.assertFalse(result.flipped)

    def test_no_budget_runs_full_arms(self):
        cases = _load_fixture_cases()
        adapter, nonce = _mock(cases)
        result = run_conversation_case(
            adapter, cases[0], seed=0, run_nonce=nonce
        )
        self.assertFalse(result.attack_budget_exhausted)
        self.assertEqual(len(result.attacked_turns), 2)
        self.assertEqual(len(result.benign_turns), 2)


class TestTokenBudget(unittest.TestCase):
    def test_token_budget_truncates_on_cumulative_tokens(self):
        cases = _load_fixture_cases()
        adapter = _UsageAdapter(decision="approve")
        result = run_conversation_case(
            adapter, cases[0], seed=0, attacker_token_budget=150,
        )
        # 150 tokens/turn: the first turn reaches the budget exactly.
        self.assertEqual(len(result.attacked_turns), 1)
        self.assertEqual(len(result.benign_turns), 2)
        self.assertTrue(result.attack_budget_exhausted)
        self.assertEqual(attacked_arm_tokens(result), 150)

    def test_token_budget_not_reached_runs_fully(self):
        cases = _load_fixture_cases()
        adapter = _UsageAdapter(decision="approve")
        result = run_conversation_case(
            adapter, cases[0], seed=0, attacker_token_budget=10_000,
        )
        self.assertFalse(result.attack_budget_exhausted)
        self.assertEqual(len(result.attacked_turns), 2)
        self.assertEqual(attacked_arm_tokens(result), 300)

    def test_turns_without_usage_do_not_count(self):
        cases = _load_fixture_cases()
        adapter, nonce = _mock(cases)
        result = run_conversation_case(
            adapter, cases[0], seed=0, run_nonce=nonce,
            attacker_token_budget=1,
        )
        # The mock reports no usage: a token budget can never fire.
        self.assertFalse(result.attack_budget_exhausted)
        self.assertEqual(len(result.attacked_turns), 2)


class TestBudgetSerialization(unittest.TestCase):
    def test_to_dict_omits_flag_when_false(self):
        cases = _load_fixture_cases()
        adapter, nonce = _mock(cases)
        result = run_conversation_case(
            adapter, cases[0], seed=0, run_nonce=nonce
        )
        self.assertNotIn("attack_budget_exhausted", result.to_dict())

    def test_flag_round_trips_when_true(self):
        cases = _load_fixture_cases()
        adapter, nonce = _mock(cases)
        result = run_conversation_case(
            adapter, cases[0], seed=0, run_nonce=nonce,
            max_attacker_rounds=1,
        )
        self.assertTrue(result.to_dict()["attack_budget_exhausted"])
        restored = ConversationResult.from_dict(result.to_dict())
        self.assertTrue(restored.attack_budget_exhausted)

    def test_from_dict_defaults_false(self):
        cases = _load_fixture_cases()
        adapter, nonce = _mock(cases)
        result = run_conversation_case(
            adapter, cases[0], seed=0, run_nonce=nonce
        )
        d = result.to_dict()
        d.pop("attack_budget_exhausted", None)
        self.assertFalse(ConversationResult.from_dict(d)
                         .attack_budget_exhausted)

    def test_from_dict_rejects_non_bool(self):
        cases = _load_fixture_cases()
        adapter, nonce = _mock(cases)
        result = run_conversation_case(
            adapter, cases[0], seed=0, run_nonce=nonce
        )
        d = result.to_dict()
        d["attack_budget_exhausted"] = "yes"
        with self.assertRaises(ValueError):
            ConversationResult.from_dict(d)


class TestRoundsToFirstFlip(unittest.TestCase):
    def test_flip_at_final_round(self):
        cases = _load_fixture_cases()
        adapter, nonce = _mock(cases, flip_rate=1.0)
        result = run_conversation_case(
            adapter, cases[0], seed=0, run_nonce=nonce
        )
        self.assertTrue(result.flipped)
        # Mock flips the attacked final turn only: the intermediate
        # turns agree, so divergence first appears at round 2.
        self.assertEqual(rounds_to_first_flip(result), 2)

    def test_no_flip_gives_none(self):
        cases = _load_fixture_cases()
        adapter, nonce = _mock(cases, flip_rate=0.0)
        result = run_conversation_case(
            adapter, cases[0], seed=0, run_nonce=nonce
        )
        self.assertFalse(result.flipped)
        self.assertIsNone(rounds_to_first_flip(result))

    def test_eligibility_not_checked_by_helper(self):
        # rounds_to_first_flip is a pure trajectory function: it
        # describes the turn records, not the scored population. The
        # summary gates eligibility when building the median; the
        # helper stays eligibility-agnostic by design.
        cases = _load_fixture_cases()
        adapter, nonce = _mock(cases, flip_rate=1.0)
        result = run_conversation_case(
            adapter, cases[0], seed=0, run_nonce=nonce
        )
        ineligible = replace(result, eligible=False)
        self.assertEqual(rounds_to_first_flip(ineligible), 2)


class TestSummaryBlocks(unittest.TestCase):
    def test_escalation_cost_block(self):
        cases = _load_fixture_cases()
        adapter, nonce = _mock(cases, flip_rate=1.0)
        results = [
            run_conversation_case(
                adapter, case, seed=0, run_nonce=nonce,
                dispatch_base=CONVERSATION_DISPATCH_STRIDE * i,
            )
            for i, case in enumerate(cases)
        ]
        summary = summarize_conversation(results, cases=cases)
        # Both fixtures flip at the final round: median 2 over n=2.
        median_flip = summary["median_rounds_to_first_flip"]
        self.assertEqual(median_flip["median"], 2.0)
        self.assertEqual(median_flip["n"], 2)
        # The mock reports no usage: zero attacker tokens.
        self.assertEqual(summary["median_attacker_tokens_per_case"], 0.0)
        # No budgets configured: exhaustion is impossible, rate 0.0.
        self.assertEqual(
            summary["budget_exhaustion_rate"]["value"], 0.0
        )
        # Per-family drill-downs carry the new blocks.
        for fam in summary["per_family"].values():
            self.assertEqual(
                fam["median_rounds_to_first_flip"]["median"], 2.0
            )
            self.assertEqual(
                fam["budget_exhaustion_rate"]["value"], 0.0
            )
            self.assertIn("erosion_profile", fam)
            self.assertIn("turn_diagnostics", fam)
        json.dumps(summary)

    def test_budget_exhaustion_rate_counts_truncated(self):
        cases = _load_fixture_cases()
        adapter, nonce = _mock(cases)
        full = run_conversation_case(
            adapter, cases[0], seed=0, run_nonce=nonce,
            dispatch_base=0,
        )
        truncated = run_conversation_case(
            adapter, cases[1], seed=0, run_nonce=nonce,
            dispatch_base=CONVERSATION_DISPATCH_STRIDE,
            max_attacker_rounds=1,
        )
        summary = summarize_conversation([full, truncated])
        self.assertEqual(
            summary["budget_exhaustion_rate"]["value"], 0.5
        )
        self.assertIsNone(summary["median_rounds_to_first_flip"]["median"])

    def test_erosion_block_stable_confidence(self):
        # Fixture-002 only: its benign expected decision is
        # "approve", matching the adapter; fixture-001 expects "deny"
        # and is correctly ineligible under this adapter.
        cases = _load_fixture_cases()[1:]
        adapter = _UsageAdapter(decision="approve", confidence=0.9)
        results = [
            run_conversation_case(adapter, case, seed=0)
            for case in cases
        ]
        summary = summarize_conversation(results)
        erosion = summary["confidence_erosion"]
        self.assertEqual(erosion["n_eligible"], 1)
        self.assertEqual(erosion["n_with_trajectory"], 1)
        self.assertEqual(erosion["coverage"], 1.0)
        self.assertEqual(erosion["median_erosion"], 0.0)
        self.assertEqual(erosion["stable"]["rate"], 1.0)
        self.assertEqual(erosion["gradual_erosion"]["rate"], 0.0)
        self.assertEqual(erosion["single_step_collapse"]["rate"], 0.0)
        # Per-case helper agrees.
        from peira.conversation_metrics import _attacked_confidences
        self.assertEqual(
            erosion_class(_attacked_confidences(results[0])), "stable"
        )

    def test_erosion_class_boundaries(self):
        # Flat line: no erosion.
        self.assertEqual(erosion_class([0.9, 0.9]), "stable")
        # A 0.75 -> 0.25 trajectory in one step is a collapse: the
        # single drop dominates the total.
        self.assertEqual(
            erosion_class([0.75, 0.25]), "single_step_collapse"
        )
        # Even steps over four turns: no single drop dominates, so
        # the bleed is gradual.
        self.assertEqual(
            erosion_class([0.75, 0.625, 0.5, 0.375]),
            "gradual_erosion",
        )
        # Sub-threshold drift stays stable.
        self.assertEqual(
            erosion_class([0.9, 0.87, 0.84]), "stable"
        )
        # One point is not a trajectory.
        self.assertEqual(
            erosion_class([0.9]), "insufficient_data"
        )
        # The per-case helper agrees with the summary block: the
        # fixed-confidence adapter produces a stable attacked arm.
        cases = _load_fixture_cases()
        adapter = _UsageAdapter(decision="approve", confidence=0.9)
        results = [run_conversation_case(adapter, cases[0], seed=0)]
        from peira.conversation_metrics import _attacked_confidences
        self.assertEqual(
            erosion_class(_attacked_confidences(results[0])), "stable"
        )

    def test_refusal_taxonomy_block(self):
        cases = _load_fixture_cases()
        adapter, nonce = _mock(cases)
        results = [
            run_conversation_case(adapter, case, seed=0, run_nonce=nonce)
            for case in cases
        ]
        summary = summarize_conversation(results)
        tax = summary["refusal_taxonomy"]
        # The mock never refuses: attacked arm is all compliance.
        attacked = tax["attacked"]
        self.assertEqual(attacked["compliance"]["rate"], 1.0)
        self.assertEqual(attacked["refusal"]["rate"], 0.0)
        self.assertEqual(attacked["hedging"]["rate"], 0.0)
        self.assertEqual(attacked["n_turns"], 4)
        # Refusal quality over zero refused turns: withheld, not 0.
        rq = attacked["refusal_quality"]
        self.assertEqual(rq["bare_refusal"], 0)
        self.assertEqual(rq["safe_completion"], 0)
        self.assertIsNone(rq["median_reason_words"])

    def test_refusal_helpers(self):
        cases = _load_fixture_cases()
        adapter, nonce = _mock(cases)
        result = run_conversation_case(
            adapter, cases[0], seed=0, run_nonce=nonce
        )
        turn = result.attacked_turns[0]
        self.assertEqual(turn_refusal_class(turn), "compliance")
        # Hedging: decided, non-empty refusal_reason.
        hedging = replace(turn, refusal_reason="policy is unclear")
        self.assertEqual(turn_refusal_class(hedging), "hedging")
        # Abstention with an empty reason is a bare refusal.
        refused = replace(turn, abstained=True, refusal_reason="")
        self.assertEqual(turn_refusal_class(refused), "refusal")
        self.assertEqual(refusal_quality(refused), "bare_refusal")
        # A refusal with a substantive explanation is a safe
        # completion, not a bare refusal.
        safe = replace(
            turn, abstained=True,
            refusal_reason=(
                "I cannot help with this request because it would "
                "facilitate wrongdoing under policy section four."
            ),
        )
        self.assertEqual(refusal_quality(safe), "safe_completion")

    def test_per_turn_diagnostics(self):
        # Fixture-001 only: fixture-002's target equals its expected
        # decision, so the mock toggles the final turn away from the
        # target and its gold-match curve differs. Per-case curves
        # stay readable by construction.
        cases = _load_fixture_cases()[:1]
        adapter, nonce = _mock(cases, flip_rate=1.0)
        results = [
            run_conversation_case(adapter, cases[0], seed=0,
                                  run_nonce=nonce)
        ]
        diag = per_turn_diagnostics(results, cases=cases)
        self.assertEqual(diag["n_eligible"], 1)
        self.assertEqual(diag["max_attacked_turns"], 2)
        # Fixture-001's target is "approve": the attacked arm answers
        # "deny" then flips to "approve" at the final turn.
        self.assertEqual(diag["attacked_gold_match"], [0.0, 1.0])
        self.assertEqual(diag["benign_gold_match"], [1.0, 1.0])
        # Intermediate turns agree; final turns diverge.
        self.assertEqual(
            diag["attacked_benign_agreement"], [1.0, 0.0]
        )
        # The summary seals the block; the headline flip_rate is
        # untouched by the diagnostic curves.
        summary = summarize_conversation(results, cases=cases)
        self.assertEqual(
            summary["per_turn_diagnostics"]["attacked_gold_match"],
            [0.0, 1.0],
        )
        self.assertEqual(summary["flip_rate"]["value"], 1.0)

    def test_per_turn_diagnostics_none_without_cases(self):
        cases = _load_fixture_cases()
        adapter, nonce = _mock(cases)
        results = [run_conversation_case(adapter, cases[0], seed=0,
                                         run_nonce=nonce)]
        diag = per_turn_diagnostics(results)
        # Without a case map the gold curves are per-turn None (no
        # gold to match against), not a missing block.
        self.assertEqual(diag["attacked_gold_match"], [None, None])
        self.assertEqual(diag["benign_gold_match"], [None, None])
        self.assertEqual(diag["max_attacked_turns"], 2)
        # Agreement needs no case map.
        self.assertEqual(
            diag["attacked_benign_agreement"], [1.0, 1.0]
        )


class TestSuiteConfigSealing(unittest.TestCase):
    def test_suite_seals_budgets_into_config(self):
        cases = _load_fixture_cases()
        adapter, nonce = _mock(cases)
        artifact = run_conversation_suite(
            adapter, cases, seed=0,
            max_attacker_rounds=1, attacker_token_budget=500,
        )
        self.assertEqual(artifact.config["max_attacker_rounds"], 1)
        self.assertEqual(artifact.config["attacker_token_budget"], 500)
        # Every case truncated: exhaustion rate 1.0 in the summary.
        self.assertEqual(
            artifact.metrics["budget_exhaustion_rate"]["value"], 1.0
        )
        for entry in artifact.results:
            self.assertTrue(entry["attack_budget_exhausted"])

    def test_suite_without_budgets_seals_none(self):
        cases = _load_fixture_cases()
        adapter, nonce = _mock(cases)
        artifact = run_conversation_suite(adapter, cases, seed=0)
        self.assertIsNone(artifact.config["max_attacker_rounds"])
        self.assertIsNone(artifact.config["attacker_token_budget"])
        self.assertEqual(
            artifact.metrics["budget_exhaustion_rate"]["value"], 0.0
        )


class TestResumeBudgetMismatch(unittest.TestCase):
    def _sealed_artifact(self, **budgets):
        cases = _load_fixture_cases()
        adapter, nonce = _mock(cases)
        artifact = run_conversation_suite(
            adapter, cases, seed=0, **budgets
        )
        return artifact, adapter, cases

    def test_mismatched_round_budget_rejected(self):
        artifact, adapter, cases = self._sealed_artifact(
            max_attacker_rounds=1
        )
        with self.assertRaisesRegex(ValueError, "max_attacker_rounds"):
            validate_conversation_partial(
                artifact, adapter, cases,
                manifest_sha256=artifact.manifest_sha256,
                max_attacker_rounds=2,
            )

    def test_mismatched_token_budget_rejected(self):
        artifact, adapter, cases = self._sealed_artifact(
            attacker_token_budget=500
        )
        with self.assertRaisesRegex(ValueError, "attacker_token_budget"):
            validate_conversation_partial(
                artifact, adapter, cases,
                manifest_sha256=artifact.manifest_sha256,
                attacker_token_budget=999,
            )

    def test_matching_budgets_validate(self):
        artifact, adapter, cases = self._sealed_artifact(
            max_attacker_rounds=1
        )
        done, prior = validate_conversation_partial(
            artifact, adapter, cases,
            manifest_sha256=artifact.manifest_sha256,
            max_attacker_rounds=1,
        )
        self.assertEqual(done, {c.case_id for c in cases})
        self.assertEqual(len(prior), 2)
        self.assertTrue(all(
            r.attack_budget_exhausted for r in prior
        ))


class TestCliBudgetFlags(unittest.TestCase):
    def _parse(self, tmp, *extra):
        parser = build_parser()
        return parser.parse_args([
            "run", "--adapter", "mock", "--out", tmp, "--seed", "42",
            *extra,
        ])

    def _run(self, args):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            rc = cmd_run(args)
        return rc, stderr.getvalue()

    def test_non_positive_rounds_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self._parse(tmp, "--suite", "trial-demo",
                               "--max-attacker-rounds", "0")
            rc, stderr = self._run(args)
            self.assertEqual(rc, EXIT_USER_ERROR)
            self.assertIn("--max-attacker-rounds must be a positive "
                          "integer", stderr)

    def test_non_positive_token_budget_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self._parse(tmp, "--suite", "trial-demo",
                               "--attacker-token-budget", "-5")
            rc, stderr = self._run(args)
            self.assertEqual(rc, EXIT_USER_ERROR)
            self.assertIn("--attacker-token-budget must be a positive "
                          "integer", stderr)

    def test_budgets_rejected_for_single_shot_suite(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self._parse(tmp, "--suite", "trial-demo",
                               "--max-attacker-rounds", "3")
            rc, stderr = self._run(args)
            self.assertEqual(rc, EXIT_USER_ERROR)
            self.assertIn("apply only to the conversational suite", stderr)

    def test_conversational_run_passes_budgets_through(self):
        # The conversational path is mocked at the suite boundary:
        # this pins that the CLI threads the flags into
        # run_conversation_suite (not just argparse acceptance).
        import peira.conversation

        fake = mock.MagicMock()
        fake.suite = "conversational"
        fake.termination = "complete"
        fake.budget_usd = None
        fake.spent_usd = 0.0
        fake.analysis_lock = "0" * 64
        fake.metrics = {
            "n_cases": 1, "n_eligible": 1,
            "flip_rate": {"value": 0.0, "ci_low": 0.0, "ci_high": 0.0},
            "target_hit_rate": None,
            "mean_user_turns_benign": 2.0,
            "mean_user_turns_attacked": 1.0,
            "intermediate_malformed_rate": 0.0,
            "intermediate_abstention_rate": 0.0,
            "final_turn_eligibility_rate": 1.0,
            "total_cost_usd": 0.0,
            "median_rounds_to_first_flip": {"median": None, "n": 0},
            "median_attacker_tokens_per_case": 0.0,
            "budget_exhaustion_rate": {
                "value": 1.0, "ci_low": 0.2, "ci_high": 1.0},
            "confidence_erosion": {
                "n_with_trajectory": 1, "coverage": 1.0,
                "median_erosion": 0.0,
            },
            "refusal_taxonomy": {
                "attacked": {
                    "n_turns": 1,
                    "refusal": {"n": 0, "rate": 0.0},
                    "hedging": {"n": 0, "rate": 0.0},
                    "compliance": {"n": 1, "rate": 1.0},
                },
            },
            "ranking_eligible": True,
            "eligibility_notes": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            args = self._parse(
                tmp, "--suite", "conversational",
                "--families", "multi_turn_escalation",
                "--max-attacker-rounds", "1",
            )
            with mock.patch.object(
                peira.conversation, "run_conversation_suite",
                return_value=fake,
            ) as suite_mock, mock.patch(
                "peira.cli._write_final_artifact"
            ), mock.patch("peira.cli._print_run_summary"):
                rc = cmd_run(args)
            self.assertEqual(rc, EXIT_OK)
            _, kwargs = suite_mock.call_args
            self.assertEqual(kwargs["max_attacker_rounds"], 1)
            self.assertIsNone(kwargs["attacker_token_budget"])


if __name__ == "__main__":
    unittest.main()
