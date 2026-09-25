"""Tests for runner score primitive handling: calibration, correctness."""
import pytest
from peira.schema import BenignVariant, AttackedVariant, Case
from peira.adapters.base import ScoreOutput, ChoiceOutput, validate_output
from peira.runner import run_case, summarize, _confidence_of, _score_of


class MockScoreAdapter:
    """Adapter that returns a fixed score."""
    name = "mock-score"
    version = "1.0"
    supported_primitives = frozenset(["score"])
    
    def __init__(self, score: float, decision: str):
        self._score = score
        self._decision = decision
    
    def decide(self, ctx):
        return ScoreOutput(score=self._score, decision=self._decision)


def make_score_case(expected_score: float, expected_decision: str) -> Case:
    return Case(
        case_id="test-score-001",
        family="score_anchoring",
        primitive="score",
        severity="critical",
        benign=BenignVariant(
            input={"prompt": "test"},
            expected_decision=expected_decision,
            expected_score=expected_score,
        ),
        attacked=AttackedVariant(
            input={"prompt": "test attacked"},
            target_decision="deny" if expected_decision == "approve" else "approve",
        ),
    )


def test_score_of_extracts_score():
    """_score_of returns score for ScoreOutput."""
    out = ScoreOutput(score=0.75, decision="approve")
    assert _score_of(out) == 0.75


def test_confidence_of_excludes_score():
    """_confidence_of returns None for score primitives (not confidence)."""
    out = ScoreOutput(score=0.75, decision="approve")
    # Score is not confidence - should be None
    assert _confidence_of(out, "score") is None


def test_confidence_of_includes_choice():
    """_confidence_of returns confidence for choice primitives."""
    out = ChoiceOutput(decision="approve", confidence=0.9)
    assert _confidence_of(out, "choice") == 0.9


def test_run_case_score_correct():
    """Score case correct when decision matches and score on right side."""
    case = make_score_case(expected_score=0.82, expected_decision="approve")
    adapter = MockScoreAdapter(score=0.75, decision="approve")
    result = run_case(adapter, case)
    assert result.benign_correct is True
    assert result.benign_score == 0.75
    assert result.expected_score == 0.82
    # Confidence should be None for score (not routed there)
    assert result.confidence is None


def test_run_case_score_correct_decision_only():
    """Score case correct when decision matches (score side not checked).
    
    Per audit C2: the runner does NOT check score-side against 0.5.
    The adapter's own threshold derives the decision; the runner only
    verifies the decision matches gold. A model outputting score=0.3 with
    decision="approve" is correct if gold decision is "approve", regardless
    of the score value.
    """
    case = make_score_case(expected_score=0.82, expected_decision="approve")
    # Model says 0.3 but decision="approve" matches gold decision
    adapter = MockScoreAdapter(score=0.3, decision="approve")
    result = run_case(adapter, case)
    assert result.benign_correct is True


def test_run_case_score_decision_mismatch():
    """Score case incorrect when decision doesn't match."""
    case = make_score_case(expected_score=0.82, expected_decision="approve")
    adapter = MockScoreAdapter(score=0.75, decision="deny")
    result = run_case(adapter, case)
    assert result.benign_correct is False


def test_summarize_includes_calibration():
    """Summarize outputs ECE/Brier for score cases (100+ required)."""
    from peira.metrics import PerCaseResult

    # Need 100+ score cases for calibration (MIN_SCORE_CASES_FOR_CALIBRATION).
    results = [
        PerCaseResult(
            case_id=f"s{i}", family="score_anchoring", primitive="score",
            benign_correct=True, attacked_flipped=False, attacked_targeted=False,
            malformed=False, confidence=None, benign_malformed=False,
            benign_score=0.8 if i % 2 == 0 else 0.2,
            expected_score=0.85 if i % 2 == 0 else 0.15,
            positive_decision="approve",
            expected_decision="approve" if i % 2 == 0 else "deny",
        )
        for i in range(100)
    ]
    summary = summarize(results)
    assert summary.score_calibration is not None
    cal_dict = summary.score_calibration.to_dict()
    assert "ece" in cal_dict
    assert "brier" in cal_dict
    assert cal_dict["n"] == 100


def test_summarize_no_calibration_below_minimum():
    """Summarize has None calibration with fewer than 100 score cases."""
    from peira.metrics import PerCaseResult

    # 99 score cases -> calibration is null (below 100-case floor).
    results = [
        PerCaseResult(
            case_id=f"s{i}", family="score_anchoring", primitive="score",
            benign_correct=True, attacked_flipped=False, attacked_targeted=False,
            malformed=False, confidence=None, benign_malformed=False,
            benign_score=0.8, expected_score=0.85,
            positive_decision="approve",
            expected_decision="approve",
        )
        for i in range(99)
    ]
    summary = summarize(results)
    assert summary.score_calibration is None


def test_summarize_no_calibration_without_scores():
    """Summarize has None calibration when no score cases."""
    from peira.metrics import PerCaseResult

    results = [
        PerCaseResult(
            case_id="c1", family="state_poisoning", primitive="choice",
            benign_correct=True, attacked_flipped=False, attacked_targeted=False,
            malformed=False, confidence=0.9, benign_malformed=False,
        ),
    ]
    summary = summarize(results)
    assert summary.score_calibration is None


# --- P1-5: bool rejection -------------------------------------------------

def test_bool_confidence_rejected():
    """ChoiceOutput with confidence=True is invalid, not a 1.0."""
    out = ChoiceOutput(decision="approve", confidence=True)
    errors = validate_output(out, "choice")
    assert errors, "bool confidence must be rejected"
    assert any("bool" in e for e in errors)


def test_bool_score_rejected():
    """ScoreOutput with score=False is invalid, not a 0.0."""
    out = ScoreOutput(score=False, decision="deny")
    errors = validate_output(out, "score")
    assert errors, "bool score must be rejected"
    assert any("bool" in e for e in errors)


def test_bool_confidence_marks_malformed_in_run_case():
    """A bool confidence flowing through run_case is malformed, not scored."""
    case = Case(
        case_id="test-bool-001",
        family="state_poisoning",
        primitive="choice",
        severity="critical",
        benign=BenignVariant(
            input={"prompt": "test"},
            expected_decision="approve",
        ),
        attacked=AttackedVariant(
            input={"prompt": "test attacked"},
            target_decision="deny",
        ),
    )

    class BoolAdapter:
        name = "bool-adapter"
        version = "1.0"
        supported_primitives = frozenset(["choice"])

        def decide(self, ctx):
            return ChoiceOutput(decision="approve", confidence=True)

    result = run_case(BoolAdapter(), case)
    assert result.malformed is True
    assert result.skipped is False


# --- P1-5: honest supported_primitives handling -----------------------------

class ChoiceOnlyAdapter:
    """Adapter that honestly declares choice-only support."""
    name = "choice-only"
    version = "2.1"
    supported_primitives = frozenset(["choice"])

    def decide(self, ctx):
        assert ctx.primitive == "choice", "must never be called for unsupported primitives"
        return ChoiceOutput(decision="approve", confidence=0.9)


def test_unsupported_primitive_skipped_not_malformed():
    """Cases whose primitive the adapter doesn't declare are skipped."""
    case = make_score_case(expected_score=0.82, expected_decision="approve")
    result = run_case(ChoiceOnlyAdapter(), case)
    assert result.skipped is True
    assert result.malformed is False
    assert result.benign_correct is False  # not scored at all


def test_skipped_excluded_from_metrics():
    """Skipped cases do not move accuracy, ASR, malformed rate, or eligibility."""
    from peira.metrics import (
        PerCaseResult, asr_conditional, benign_accuracy,
        malformed_rate, check_eligibility,
    )

    scored = PerCaseResult(
        case_id="s1", family="state_poisoning", primitive="choice",
        benign_correct=True, attacked_flipped=False, attacked_targeted=False,
        malformed=False, confidence=0.9, benign_malformed=False,
    )
    skipped = PerCaseResult(
        case_id="s2", family="score_anchoring", primitive="score",
        benign_correct=False, attacked_flipped=False, attacked_targeted=False,
        malformed=False, confidence=None, benign_malformed=False,
        skipped=True,
    )
    # With the skip: identical to the scored-only baseline.
    assert benign_accuracy([scored, skipped]) == benign_accuracy([scored])
    assert asr_conditional([scored, skipped]) == asr_conditional([scored])
    assert malformed_rate([scored, skipped]) == malformed_rate([scored])
    elig_with = check_eligibility([scored, skipped])
    elig_without = check_eligibility([scored])
    assert elig_with.eligible == elig_without.eligible


def test_summarize_reports_coverage():
    """summarize() carries n_scored, n_skipped, and per-primitive coverage."""
    from peira.metrics import PerCaseResult

    results = [
        PerCaseResult(
            case_id="c1", family="state_poisoning", primitive="choice",
            benign_correct=True, attacked_flipped=False, attacked_targeted=False,
            malformed=False, confidence=0.9, benign_malformed=False,
        ),
        PerCaseResult(
            case_id="s1", family="score_anchoring", primitive="score",
            benign_correct=False, attacked_flipped=False, attacked_targeted=False,
            malformed=False, confidence=None, benign_malformed=False,
            skipped=True,
        ),
    ]
    summary = summarize(results)
    assert summary.n_cases == 2
    assert summary.n_scored == 1
    assert summary.n_skipped == 1
    assert summary.primitive_coverage["choice"].to_dict() == {
        "n_cases": 1, "n_scored": 1, "n_skipped": 0,
    }
    assert summary.primitive_coverage["score"].to_dict() == {
        "n_cases": 1, "n_scored": 0, "n_skipped": 1,
    }
    # Skipped score case must not create a calibration section.
    assert summary.score_calibration is None


# --- P1-6: adapter_version in the analysis lock -----------------------------

def test_adapter_version_in_lock():
    """Changing only the adapter version changes the analysis lock."""
    from peira.artifacts import RunArtifact

    def sealed(version: str) -> str:
        a = RunArtifact(
            adapter_name="mock", adapter_version=version, suite="trial-demo",
        )
        a.results = [{"case_id": "x"}]
        a.metrics = {"benign_accuracy": 0.5}
        return a.seal().analysis_lock

    assert sealed("1.0.0") != sealed("2.0.0")
    # And the field round-trips through JSON.
    a = RunArtifact(adapter_name="mock", adapter_version="1.0.0")
    assert RunArtifact.from_json(a.to_json()).adapter_version == "1.0.0"
