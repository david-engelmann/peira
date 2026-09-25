"""Tests for Lane C: Python runner hardening.

- Up-front adapter interface validation (fail fast, not mid-run)
- Timeout value validation (reject nan/inf/negative/zero)
- Orphaned worker tracking (timed-out threads can't be killed; warn on concurrency)
"""
import math
import time

import pytest

from peira.adapters.base import ChoiceOutput
from peira.runner import (
    AdapterTimeoutError,
    _decide_with_timeout,
    _live_orphans,
    run_case,
    run_suite,
    validate_adapter,
    validate_timeout_value,
)
from peira.schema import AttackedVariant, BenignVariant, Case


class GoodAdapter:
    name = "good"
    version = "1.0"
    supported_primitives = frozenset({"choice"})

    def decide(self, case_input, primitive):
        return ChoiceOutput(decision="approve", confidence=0.9)


class NoDecideAdapter:
    name = "nodecide"
    version = "1.0"


class BadNameAdapter:
    name = ""
    version = "1.0"

    def decide(self, case_input, primitive):
        return ChoiceOutput(decision="approve", confidence=0.9)


class BadVersionAdapter:
    name = "badver"
    version = 123  # not a string

    def decide(self, case_input, primitive):
        return ChoiceOutput(decision="approve", confidence=0.9)


class BadPrimitivesAdapter:
    name = "badprim"
    version = "1.0"
    supported_primitives = frozenset({"choice", "telepathy"})  # unknown

    def decide(self, case_input, primitive):
        return ChoiceOutput(decision="approve", confidence=0.9)


class ListPrimitivesAdapter:
    name = "listprim"
    version = "1.0"
    supported_primitives = ["choice"]  # list, not frozenset/set

    def decide(self, case_input, primitive):
        return ChoiceOutput(decision="approve", confidence=0.9)


def make_choice_case(case_id: str = "test-harden-001") -> Case:
    return Case(
        case_id=case_id,
        family="state_poisoning",
        primitive="choice",
        severity="high",
        benign=BenignVariant(input={"prompt": "test"}, expected_decision="approve"),
        attacked=AttackedVariant(input={"prompt": "test attacked"}, target_decision="deny"),
    )


# --- validate_adapter ---

def test_validate_adapter_accepts_good_adapter():
    assert validate_adapter(GoodAdapter()) == []


def test_validate_adapter_accepts_minimal_adapter():
    # supported_primitives is optional; version may be empty string.
    class Minimal:
        name = "min"
        version = ""
        def decide(self, case_input, primitive):
            return ChoiceOutput(decision="approve", confidence=0.9)
    assert validate_adapter(Minimal()) == []


def test_validate_adapter_rejects_missing_decide():
    errors = validate_adapter(NoDecideAdapter())
    assert any("decide" in e for e in errors)


def test_validate_adapter_rejects_empty_name():
    errors = validate_adapter(BadNameAdapter())
    assert any("name" in e for e in errors)


def test_validate_adapter_rejects_non_string_version():
    errors = validate_adapter(BadVersionAdapter())
    assert any("version" in e for e in errors)


def test_validate_adapter_rejects_unknown_primitives():
    errors = validate_adapter(BadPrimitivesAdapter())
    assert any("telepathy" in e for e in errors)


def test_validate_adapter_rejects_list_primitives():
    errors = validate_adapter(ListPrimitivesAdapter())
    assert any("supported_primitives" in e for e in errors)


# --- validate_timeout_value ---

def test_validate_timeout_accepts_none():
    assert validate_timeout_value(None) == []


def test_validate_timeout_accepts_positive():
    assert validate_timeout_value(30.0) == []
    assert validate_timeout_value(0.1) == []
    assert validate_timeout_value(1) == []  # int is fine


def test_validate_timeout_rejects_nan():
    errors = validate_timeout_value(float("nan"))
    assert errors, "NaN must be rejected"
    assert any("finite" in e for e in errors)


def test_validate_timeout_rejects_inf():
    for v in (float("inf"), float("-inf")):
        errors = validate_timeout_value(v)
        assert errors, f"{v} must be rejected"
        assert any("finite" in e for e in errors)


def test_validate_timeout_rejects_zero_and_negative():
    for v in (0.0, -1.0, -0.5):
        errors = validate_timeout_value(v)
        assert errors, f"{v} must be rejected"
        assert any("positive" in e for e in errors)


def test_validate_timeout_rejects_bool():
    errors = validate_timeout_value(True)
    assert errors, "bool must be rejected (True == 1 would silently pass)"


def test_validate_timeout_rejects_wrong_type():
    errors = validate_timeout_value("30")
    assert errors


# --- up-front validation in run_case / run_suite ---

def test_run_case_rejects_broken_adapter_immediately():
    # Must fail before scoring anything, not mid-run.
    with pytest.raises(ValueError, match="invalid adapter"):
        run_case(NoDecideAdapter(), make_choice_case(), timeout=5.0)


def test_run_case_rejects_invalid_timeout():
    with pytest.raises(ValueError, match="invalid timeout"):
        run_case(GoodAdapter(), make_choice_case(), timeout=float("nan"))


def test_run_suite_rejects_broken_adapter_immediately():
    cases = [make_choice_case()]
    with pytest.raises(ValueError, match="invalid adapter"):
        run_suite(BadNameAdapter(), cases, "trial-demo", "0.1.0-demo", timeout=5.0)


def test_run_suite_rejects_invalid_timeout():
    cases = [make_choice_case()]
    with pytest.raises(ValueError, match="invalid timeout"):
        run_suite(GoodAdapter(), cases, "trial-demo", "0.1.0-demo",
                  timeout=float("inf"))


def test_decide_with_timeout_rejects_invalid_timeout():
    with pytest.raises(ValueError, match="invalid timeout"):
        _decide_with_timeout(GoodAdapter(), {}, "choice", float("nan"))


# --- orphan tracking ---

class HangAdapter:
    """Adapter that hangs forever on decide()."""
    name = "hang"
    version = "1.0"

    def decide(self, case_input, primitive):
        time.sleep(3600)
        return ChoiceOutput(decision="approve", confidence=0.9)


def test_timeout_registers_orphan(capsys):
    adapter = HangAdapter()
    assert _live_orphans(adapter) == []
    with pytest.raises(AdapterTimeoutError):
        _decide_with_timeout(adapter, {}, "choice", 0.2)
    orphans = _live_orphans(adapter)
    assert len(orphans) == 1
    _, _, primitive = orphans[0]
    assert primitive == "choice"


def test_orphan_warning_on_next_call(capsys):
    """A new call while an orphan is alive warns about concurrency."""
    adapter = HangAdapter()
    with pytest.raises(AdapterTimeoutError):
        _decide_with_timeout(adapter, {}, "choice", 0.2)
    # Second call: orphan from the first is still alive → warning.
    with pytest.raises(AdapterTimeoutError):
        _decide_with_timeout(adapter, {}, "choice", 0.2)
    err = capsys.readouterr().err
    assert "timed-out adapter worker" in err
    assert "still running" in err


def test_orphan_cannot_corrupt_next_result():
    """Each call has its own result box: an orphan can't write into a later call."""
    adapter = HangAdapter()
    with pytest.raises(AdapterTimeoutError):
        _decide_with_timeout(adapter, {}, "choice", 0.2)
    # The orphan is still sleeping; the next call times out independently
    # and raises its own AdapterTimeoutError (not a corrupted result).
    with pytest.raises(AdapterTimeoutError):
        _decide_with_timeout(adapter, {}, "choice", 0.2)
    assert len(_live_orphans(adapter)) == 2


def test_no_orphan_warning_when_clean(capsys):
    """Fast adapters produce no orphan warnings."""
    out = _decide_with_timeout(GoodAdapter(), {}, "choice", 5.0)
    assert out.decision == "approve"
    err = capsys.readouterr().err
    assert "timed-out adapter worker" not in err
