"""Tests for score primitive contract: expected_score in schema."""
import pytest
from peira.schema import (
    BenignVariant,
    Case,
    validate_case_dict,
    CASE_JSON_SCHEMA,
)


def test_benign_variant_with_expected_score():
    """BenignVariant accepts expected_score for score primitives."""
    bv = BenignVariant(
        input={"prompt": "test"},
        expected_decision="approve",
        expected_score=0.75,
    )
    assert bv.expected_score == 0.75


def test_benign_variant_without_expected_score():
    """BenignVariant defaults expected_score to None (choice/noul)."""
    bv = BenignVariant(
        input={"prompt": "test"},
        expected_decision="approve",
    )
    assert bv.expected_score is None


def test_case_roundtrip_preserves_expected_score():
    """Case.to_dict/from_dict preserves expected_score."""
    case = Case(
        case_id="test-001",
        family="score_anchoring",
        primitive="score",
        severity="critical",
        benign=BenignVariant(
            input={"prompt": "test"},
            expected_decision="approve",
            expected_score=0.82,
        ),
        attacked=None,  # Will be set below
        notes="",
    )
    # Need attacked variant for valid Case
    from peira.schema import AttackedVariant
    case = Case(
        case_id="test-001",
        family="score_anchoring",
        primitive="score",
        severity="critical",
        benign=BenignVariant(
            input={"prompt": "test"},
            expected_decision="approve",
            expected_score=0.82,
        ),
        attacked=AttackedVariant(
            input={"prompt": "test attacked"},
            target_decision="deny",
        ),
        notes="",
    )
    d = case.to_dict()
    assert d["benign"]["expected_score"] == 0.82
    
    case2 = Case.from_dict(d)
    assert case2.benign.expected_score == 0.82


def test_case_roundtrip_without_expected_score():
    """Choice cases don't have expected_score in dict."""
    from peira.schema import AttackedVariant
    case = Case(
        case_id="test-002",
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
        notes="",
    )
    d = case.to_dict()
    assert "expected_score" not in d["benign"]
    
    case2 = Case.from_dict(d)
    assert case2.benign.expected_score is None


def test_validate_score_case_requires_expected_score():
    """Score primitive must have expected_score in 0..1."""
    # Missing expected_score
    d = {
        "case_id": "test-003",
        "family": "score_anchoring",
        "primitive": "score",
        "severity": "critical",
        "benign": {
            "input": {"prompt": "test"},
            "expected_decision": "approve",
        },
        "attacked": {
            "input": {"prompt": "test"},
            "target_decision": "deny",
        },
    }
    errors = validate_case_dict(d)
    assert any("expected_score" in e for e in errors)
    
    # Out of range
    d["benign"]["expected_score"] = 1.5
    errors = validate_case_dict(d)
    assert any("0..1" in e for e in errors)
    
    # Valid
    d["benign"]["expected_score"] = 0.75
    errors = validate_case_dict(d)
    assert errors == []


def test_validate_choice_case_no_expected_score_needed():
    """Choice primitive doesn't require expected_score."""
    d = {
        "case_id": "test-004",
        "family": "state_poisoning",
        "primitive": "choice",
        "severity": "critical",
        "benign": {
            "input": {"prompt": "test"},
            "expected_decision": "approve",
        },
        "attacked": {
            "input": {"prompt": "test"},
            "target_decision": "deny",
        },
    }
    errors = validate_case_dict(d)
    assert errors == []


def test_schema_documents_expected_score():
    """CASE_JSON_SCHEMA includes expected_score."""
    benign_props = CASE_JSON_SCHEMA["properties"]["benign"]["properties"]
    assert "expected_score" in benign_props
