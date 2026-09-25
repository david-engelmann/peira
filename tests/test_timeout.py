"""Tests for adapter timeout enforcement.

Security audit: adapter.decide() had no timeout — a hung adapter would hang
the whole run. Each decide() call now gets a wall-clock timeout; timed-out
variants are marked malformed and the run continues.
"""
import threading
import time

import pytest

from peira.adapters.base import ChoiceOutput
from peira.runner import (
    AdapterTimeoutError,
    _decide_with_timeout,
    run_case,
    run_suite,
)
from peira.schema import AttackedVariant, BenignVariant, Case


class SleepAdapter:
    """Adapter that sleeps `delay` seconds on selected variants, then answers."""

    name = "sleep"
    version = "1.0"
    supported_primitives = frozenset({"choice"})

    def __init__(self, delay: float, sleep_on: str = "both"):
        assert sleep_on in ("benign", "attacked", "both")
        self.delay = delay
        self.sleep_on = sleep_on

    def decide(self, case_input, primitive):
        is_attacked = bool(case_input.get("attacked"))
        wants_sleep = (
            self.sleep_on == "both"
            or (self.sleep_on == "attacked" and is_attacked)
            or (self.sleep_on == "benign" and not is_attacked)
        )
        if wants_sleep:
            time.sleep(self.delay)
        return ChoiceOutput(decision="approve", confidence=0.9)


def make_choice_case(case_id: str = "test-timeout-001") -> Case:
    return Case(
        case_id=case_id,
        family="state_poisoning",
        primitive="choice",
        severity="high",
        benign=BenignVariant(
            input={"prompt": "test"},
            expected_decision="approve",
        ),
        attacked=AttackedVariant(
            input={"prompt": "test attacked"},
            target_decision="deny",
        ),
    )


def test_decide_with_timeout_raises_on_slow_adapter():
    """A decide() slower than the timeout raises AdapterTimeoutError, fast."""
    adapter = SleepAdapter(delay=60.0)
    start = time.monotonic()
    with pytest.raises(AdapterTimeoutError):
        _decide_with_timeout(adapter, {}, "choice", 0.2)
    elapsed = time.monotonic() - start
    assert elapsed < 5.0, f"timeout did not fire promptly: {elapsed:.1f}s"


def test_decide_with_timeout_passes_through_fast_adapter():
    """A decide() within the timeout returns its output unchanged."""
    adapter = SleepAdapter(delay=0.01)
    out = _decide_with_timeout(adapter, {}, "choice", 5.0)
    assert isinstance(out, ChoiceOutput)
    assert out.decision == "approve"


def test_decide_with_timeout_none_disables():
    """timeout=None calls decide() directly with no timeout."""
    adapter = SleepAdapter(delay=0.3)
    start = time.monotonic()
    out = _decide_with_timeout(adapter, {}, "choice", None)
    elapsed = time.monotonic() - start
    assert out.decision == "approve"
    assert elapsed >= 0.3  # actually waited — no shortcut


def test_decide_with_timeout_propagates_adapter_errors():
    """Adapter exceptions (not timeouts) propagate unchanged."""
    class BoomAdapter:
        def decide(self, case_input, primitive):
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        _decide_with_timeout(BoomAdapter(), {}, "choice", 5.0)


def test_run_case_benign_timeout_marked_malformed(capsys):
    """A benign-variant timeout marks the case malformed, doesn't hang."""
    case = make_choice_case()
    adapter = SleepAdapter(delay=60.0, sleep_on="benign")
    start = time.monotonic()
    result = run_case(adapter, case, timeout=0.2)
    elapsed = time.monotonic() - start
    assert elapsed < 5.0
    assert result.malformed is True
    assert result.benign_malformed is True
    assert result.benign_correct is False  # "<timeout>" != gold
    err = capsys.readouterr().err
    assert "timeout" in err
    assert case.case_id in err
    assert "benign variant" in err


def test_run_case_attacked_timeout_marked_malformed(capsys):
    """An attacked-variant timeout marks malformed; conservative flip rule applies."""
    case = make_choice_case()
    adapter = SleepAdapter(delay=60.0, sleep_on="attacked")
    result = run_case(adapter, case, timeout=0.2)
    assert result.malformed is True
    assert result.benign_malformed is False
    assert result.benign_correct is True  # benign answered fine
    # Conservative rule: malformed attacked output counts as flipped.
    assert result.attacked_flipped is True
    err = capsys.readouterr().err
    assert "attacked variant" in err


def test_run_case_no_timeout_when_fast():
    """Fast adapters are unaffected by the timeout wrapper."""
    case = make_choice_case()
    adapter = SleepAdapter(delay=0.01)
    result = run_case(adapter, case, timeout=5.0)
    assert result.malformed is False
    assert result.benign_correct is True


def test_run_suite_timeout_continues_past_hung_cases():
    """run_suite marks hung cases malformed and finishes the suite."""
    cases = [make_choice_case(f"test-timeout-{i:03d}") for i in range(3)]
    adapter = SleepAdapter(delay=60.0)  # hangs on every variant
    start = time.monotonic()
    artifact = run_suite(adapter, cases, "trial-demo", "0.1.0-demo", timeout=0.2)
    elapsed = time.monotonic() - start
    assert elapsed < 10.0, f"suite hung: {elapsed:.1f}s"
    assert len(artifact.results) == 3
    assert all(r["malformed"] for r in artifact.results)
    assert artifact.verify()


def test_timeout_leaves_no_non_daemon_threads():
    """Timed-out worker threads are daemon: they can never block exit.

    (ThreadPoolExecutor workers are non-daemon and hang the interpreter's
    atexit join — the reason this uses raw daemon threads instead.)
    """
    adapter = SleepAdapter(delay=60.0)
    before = {
        t.name for t in threading.enumerate() if not t.daemon
    }
    with pytest.raises(AdapterTimeoutError):
        _decide_with_timeout(adapter, {}, "choice", 0.2)
    # Give the (daemon) orphan a moment; it must not appear as non-daemon.
    time.sleep(0.1)
    after = {
        t.name for t in threading.enumerate() if not t.daemon
    }
    leaked = {n for n in after - before if n == "peira-decide"}
    assert not leaked, f"non-daemon worker threads leaked: {leaked}"


def test_run_case_timeout_none_disables():
    """run_case(timeout=None) preserves the old unbounded behavior."""
    case = make_choice_case()
    adapter = SleepAdapter(delay=0.3)
    result = run_case(adapter, case, timeout=None)
    assert result.malformed is False
    assert result.benign_correct is True
