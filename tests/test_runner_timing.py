"""Unit tests for R-12: decomposed per-call timing, the three-layer
timeout budget, and the timing statistical policy.

All timing tests use mocked or injected time only: a step clock stands
in for ``time.perf_counter`` in the decomposition tests (exact,
deterministic component values), and the timeout tests use tiny real
ceilings against adapters that block on an event (the ceiling firing
is the behavior under test, not a sleep-based assertion). No test
sleeps to measure wall time.
"""

from __future__ import annotations

import asyncio
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from peira.adapters.base import (
    CallContext,
    ChoiceOutput,
    ProviderError,
)
from peira.adapters.mock import MockAdapter
from peira.artifacts import RunArtifact
from peira.concurrency import AdaptiveConcurrency
from peira.metrics import CallRecord, CallTiming, timing_summary
from peira.pricing import load_pricing_table
from peira.runner import (
    _record_call,
    _record_call_async,
    _record_from_transcript_entry,
    _TrialInfo,
    _write_partial,
    load_cases,
    replay_suite,
    run_case,
    run_suite,
    validate_partial,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

_R12_NONCE = "r12-timing-test-nonce"


def _demo_cases(n=6):
    return load_cases(REPO_ROOT / "dataset" / "trial-demo")[:n]


class StepClock:
    """Fake clock: every call returns the current time, then advances
    by exactly ``step``. Deltas between consecutive calls are exact,
    so decomposed components assert to exact values."""

    def __init__(self, step=0.001):
        self._t = 1000.0
        self._step = step
        self._lock = threading.Lock()

    def __call__(self):
        with self._lock:
            t = self._t
            self._t += self._step
            return t


class _PatchedClock:
    """Patch ``peira.runner.time`` so every ``time.perf_counter()`` in
    the runner (including inside worker threads) reads the step clock.
    ``asyncio`` internals use ``time.monotonic`` via their own module
    reference and are unaffected."""

    def __init__(self, clock):
        self._clock = clock
        self._patcher = None

    def __enter__(self):
        import peira.runner as R

        fake_time = mock.MagicMock()
        fake_time.perf_counter = self._clock
        self._patcher = mock.patch.object(R, "time", fake_time)
        self._patcher.__enter__()
        return self._clock

    def __exit__(self, *exc):
        self._patcher.__exit__(*exc)
        return False


class InstantAdapter:
    """Adapter that decides immediately with a fixed output."""

    name = "instant"
    version = "1"

    def decide(self, case_input, primitive, context):
        return ChoiceOutput(decision="allow", confidence=0.9)


class FlakyOnceAdapter(InstantAdapter):
    """Fails transiently on the first call, then succeeds."""

    name = "flaky-once"

    def __init__(self):
        self.calls = 0

    def decide(self, case_input, primitive, context):
        self.calls += 1
        if self.calls == 1:
            raise ProviderError("busy", status_code=503)
        return super().decide(case_input, primitive, context)


class BlockingAdapter(InstantAdapter):
    """Blocks on an event until the test releases it (backstop 10s so
    a bug can never hang the suite on a non-daemon worker thread)."""

    name = "blocking"

    def __init__(self, event):
        self.event = event

    def decide(self, case_input, primitive, context):
        self.event.wait(10)
        return super().decide(case_input, primitive, context)


class BenignInstantAttackedBlockingAdapter(InstantAdapter):
    """Benign arm decides instantly; the attacked arm blocks on an
    event (backstop 10s). Arms run sequentially (benign first), so the
    first decide() is the benign one."""

    name = "benign-instant-attacked-blocking"

    def __init__(self, event):
        self.event = event
        self.calls = 0

    def decide(self, case_input, primitive, context):
        from peira.adapters.base import ChoiceOutput
        self.calls += 1
        if self.calls > 1:
            self.event.wait(10)
        # The demo case expects "deny": the benign baseline is usable.
        return ChoiceOutput(decision="deny", confidence=0.9)


class FailFastRetryableAdapter(InstantAdapter):
    """Fails immediately on every call with a retryable error carrying
    a deterministic retry_after, so the arm parks in backoff between
    attempts (the worker is never in flight when the item budget
    fires). Used by the worker_in_flight regression test."""

    name = "fail-fast-retryable"

    def __init__(self, retry_after):
        self.retry_after = retry_after

    def decide(self, case_input, primitive, context):
        raise ProviderError(
            "busy", status_code=429, retry_after=self.retry_after)


class SlotContendedAdapter(InstantAdapter):
    """Two-role adapter for the slot-wait regression test. The FIRST
    decide() call is the victim's attempt 1 (it wins the initial slot:
    dispatched first, and the AIMD controller starts at limit 1) and
    fails immediately with a retryable 429. Every later call is a
    blocker that sleeps ``block_delay`` holding its slot. The victim's
    attempt 2 then slot-waits behind the blocker while the item budget
    fires — with a stale worker_start from attempt 1 and the worker
    NOT in flight."""

    name = "slot-contended"

    def __init__(self, retry_after=0.05, block_delay=2.0):
        self.retry_after = retry_after
        self.block_delay = block_delay
        self.calls = 0
        self._lock = threading.Lock()

    def decide(self, case_input, primitive, context):
        with self._lock:
            self.calls += 1
            call_no = self.calls
        if call_no == 1:
            raise ProviderError(
                "busy", status_code=429, retry_after=self.retry_after)
        time.sleep(self.block_delay)
        return super().decide(case_input, primitive, context)


class SlowAdapter(InstantAdapter):
    """Sleeps ``delay`` seconds in decide(), then decides."""

    name = "slow"

    def __init__(self, delay):
        self.delay = delay

    def decide(self, case_input, primitive, context):
        time.sleep(self.delay)
        return super().decide(case_input, primitive, context)


def _trial(arm="benign"):
    return _TrialInfo(
        case_id="c1", arm=arm, expected_decision="allow",
        target_decision=None,
    )


class TestCallTimingModel(unittest.TestCase):
    def test_round_trip(self):
        t = CallTiming(
            admission_wait_ms=1.5, adapter_execution_ms=120.25,
            harness_overhead_ms=3.75, backoff_ms=0.0,
        )
        self.assertEqual(CallTiming.from_dict(t.to_dict()), t)

    def test_from_dict_none_is_zero_breakdown(self):
        t = CallTiming.from_dict(None)
        self.assertEqual(
            (t.admission_wait_ms, t.adapter_execution_ms,
             t.harness_overhead_ms, t.backoff_ms),
            (0.0, 0.0, 0.0, 0.0),
        )

    def test_from_dict_rejects_hostile(self):
        good = {
            "admission_wait_ms": 1.0, "adapter_execution_ms": 2.0,
            "harness_overhead_ms": 3.0, "backoff_ms": 0.0,
        }
        for key in good:
            bad = dict(good, **{key: -1.0})
            with self.assertRaises(ValueError, msg=key):
                CallTiming.from_dict(bad)
            bad = dict(good, **{key: True})
            with self.assertRaises(ValueError, msg=key):
                CallTiming.from_dict(bad)
            bad = dict(good, **{key: "1.0"})
            with self.assertRaises(ValueError, msg=key):
                CallTiming.from_dict(bad)
            bad = dict(good, **{key: float("nan")})
            with self.assertRaises(ValueError, msg=key):
                CallTiming.from_dict(bad)
            bad = dict(good, **{key: float("inf")})
            with self.assertRaises(ValueError, msg=key):
                CallTiming.from_dict(bad)
        with self.assertRaises(ValueError):
            CallTiming.from_dict({"admission_wait_ms": 1.0})
        with self.assertRaises(ValueError):
            CallTiming.from_dict([1.0, 2.0, 3.0, 0.0])

    def test_call_record_default_is_zero_breakdown(self):
        rec = CallRecord(
            decision="allow", confidence=0.9, abstained=False,
            refusal_reason="", usage=None, seed=0, dispatch_index=0,
            malformed=False,
        )
        self.assertEqual(rec.timing_ms, CallTiming.from_dict(None))

    def test_call_record_from_dict_recovers_timing(self):
        import dataclasses

        t = CallTiming(
            admission_wait_ms=1.0, adapter_execution_ms=2.0,
            harness_overhead_ms=3.0, backoff_ms=4.0,
        )
        rec = CallRecord(
            decision="allow", confidence=0.9, abstained=False,
            refusal_reason="", usage=None, seed=0, dispatch_index=0,
            malformed=False, timing_ms=t,
        )
        d = dataclasses.asdict(rec)
        self.assertEqual(d["timing_ms"], t.to_dict())
        back = CallRecord.from_dict(d)
        self.assertEqual(back.timing_ms, t)

    def test_call_record_from_dict_pre_r12_defaults(self):
        import dataclasses

        rec = CallRecord(
            decision="allow", confidence=0.9, abstained=False,
            refusal_reason="", usage=None, seed=0, dispatch_index=0,
            malformed=False,
        )
        d = dataclasses.asdict(rec)
        del d["timing_ms"]
        back = CallRecord.from_dict(d)
        self.assertEqual(back.timing_ms, CallTiming.from_dict(None))


class TestDecompositionWithFakeClock(unittest.TestCase):
    def test_sync_decomposition_exact(self):
        clock = StepClock(step=0.001)
        table = load_pricing_table()
        with _PatchedClock(clock):
            rec = _record_call(
                InstantAdapter(), {"input": "x"}, "choice",
                CallContext(call_id="c"), 0, 0, table,
            )
        t = rec.timing_ms
        # Trace (1ms per clock call): t_call_start, start,
        # t_done (adapter=1ms), latency stamp, assembly stamp
        # (total=4ms, harness=4-0-1-0=3ms). assertAlmostEqual absorbs
        # the float dust from the 0.001s step (not dyadic).
        self.assertAlmostEqual(t.admission_wait_ms, 0.0, places=9)
        self.assertAlmostEqual(t.adapter_execution_ms, 1.0, places=9)
        self.assertAlmostEqual(t.backoff_ms, 0.0, places=9)
        self.assertAlmostEqual(t.harness_overhead_ms, 3.0, places=9)

    def test_async_decomposition_exact(self):
        async def go():
            controller = AdaptiveConcurrency(1)
            return await _record_call_async(
                InstantAdapter(), "1", {"input": "x"}, "choice",
                CallContext(call_id="c"), _trial(), 0, 0,
                load_pricing_table(),
                controller=controller, max_attempts=1, max_concurrency=1,
                call_timeout=None, cache=None, cache_key_str=None,
                transcript=None,
            )

        clock = StepClock(step=0.001)
        with _PatchedClock(clock):
            rec = asyncio.run(go())
        t = rec.timing_ms
        # Trace (1ms per clock call): t_call_start, t_submit, t_slot
        # (admission=1ms), start, t_dispatch, worker _exec_start stamp,
        # worker t0, worker stamp (adapter=1ms), latency stamp, assembly
        # stamp (total=9ms, harness=9-1-1-0=7ms).
        self.assertAlmostEqual(t.admission_wait_ms, 1.0, places=9)
        self.assertAlmostEqual(t.adapter_execution_ms, 1.0, places=9)
        self.assertAlmostEqual(t.backoff_ms, 0.0, places=9)
        self.assertAlmostEqual(t.harness_overhead_ms, 7.0, places=9)

    def test_backoff_attribution(self):
        async def go():
            controller = AdaptiveConcurrency(1)
            return await _record_call_async(
                FlakyOnceAdapter(), "1", {"input": "x"}, "choice",
                CallContext(call_id="c"), _trial(), 0, 0,
                load_pricing_table(),
                controller=controller, max_attempts=2, max_concurrency=1,
                call_timeout=None, cache=None, cache_key_str=None,
                transcript=None,
            )

        clock = StepClock(step=0.001)
        with _PatchedClock(clock), mock.patch(
            "asyncio.sleep", new=mock.AsyncMock()
        ):
            rec = asyncio.run(go())
        t = rec.timing_ms
        # Two attempts (admission 1ms each, adapter 1ms each), one
        # backoff sleep measured as 1ms with the sleep mocked out.
        # Total 19 clock calls (one extra _exec_start stamp per
        # attempt): harness = 19-2-2-1 = 14ms.
        self.assertFalse(rec.malformed)
        self.assertAlmostEqual(t.admission_wait_ms, 2.0, places=9)
        self.assertAlmostEqual(t.adapter_execution_ms, 2.0, places=9)
        self.assertAlmostEqual(t.backoff_ms, 1.0, places=9)
        self.assertAlmostEqual(t.harness_overhead_ms, 14.0, places=9)

    def test_cache_hit_is_harness_only(self):
        cases = _demo_cases(1)
        adapter = MockAdapter(
            script=MockAdapter.script_for(
                cases, seed=0, run_nonce=_R12_NONCE))
        with TemporaryDirectory() as tmp:
            cache_dir = str(Path(tmp) / "cache")
            run_suite(adapter, cases, "trial-demo", "0.1.0-demo", seed=0,
                      cache_dir=cache_dir, run_nonce=_R12_NONCE)
            art = run_suite(adapter, cases, "trial-demo", "0.1.0-demo",
                            seed=0, cache_dir=cache_dir,
                            run_nonce=_R12_NONCE)
        for r in art.results:
            for arm in ("benign", "attacked"):
                rec = r[arm]
                self.assertTrue(rec["cached"])
                t = rec["timing_ms"]
                self.assertEqual(t["admission_wait_ms"], 0.0)
                self.assertEqual(t["adapter_execution_ms"], 0.0)
                self.assertEqual(t["backoff_ms"], 0.0)
                self.assertGreater(t["harness_overhead_ms"], 0.0)


class TestItemTimeout(unittest.TestCase):
    def test_item_timeout_seals_case_as_timeout_failure(self):
        cases = _demo_cases(1)
        event = threading.Event()
        try:
            art = run_suite(
                BlockingAdapter(event), cases, "trial-demo",
                "0.1.0-demo", seed=0, item_timeout=0.2,
                max_concurrency=1, run_nonce=_R12_NONCE)
        finally:
            event.set()
        self.assertEqual(len(art.results), 1)
        self.assertEqual(art.termination, "complete")
        # The budget fired during the benign arm: benign is an
        # explicitly typed item timeout with honest partial timing
        # (only elapsed adapter execution attributed, never the whole
        # budget); the attacked arm never started, so its record is a
        # typed item timeout with zero timing (nothing was measured).
        benign = art.results[0]["benign"]
        self.assertTrue(benign["malformed"])
        self.assertTrue(benign["timed_out"])
        self.assertEqual(benign["timeout_kind"], "item")
        exec_ms = benign["timing_ms"]["adapter_execution_ms"]
        self.assertGreater(exec_ms, 0.0)
        self.assertLess(exec_ms, 200.0)
        # Latency is the arm's actual wall time (budget plus event-loop
        # scheduling), not the budget ceiling assigned as a constant.
        self.assertGreater(benign["latency_ms_total"], 0.0)
        self.assertLess(benign["latency_ms_total"], 400.0)
        attacked = art.results[0]["attacked"]
        self.assertTrue(attacked["malformed"])
        self.assertTrue(attacked["timed_out"])
        self.assertEqual(attacked["timeout_kind"], "item")
        self.assertEqual(attacked["latency_ms_total"], 0.0)
        for comp in ("admission_wait_ms", "adapter_execution_ms",
                     "harness_overhead_ms", "backoff_ms"):
            self.assertEqual(attacked["timing_ms"][comp], 0.0)

    def test_item_timeout_preserves_completed_benign_arm(self):
        # Benign completes instantly; the attacked arm blocks past the
        # item budget. The sealed case retains the real benign record
        # and creates only an attacked item-timeout record.
        cases = _demo_cases(1)
        event = threading.Event()
        adapter = BenignInstantAttackedBlockingAdapter(event)
        try:
            art = run_suite(
                adapter, cases, "trial-demo",
                "0.1.0-demo", seed=0, item_timeout=0.2,
                max_concurrency=1, run_nonce=_R12_NONCE)
        finally:
            event.set()
        self.assertEqual(len(art.results), 1)
        benign = art.results[0]["benign"]
        self.assertFalse(benign["malformed"])
        self.assertFalse(benign["timed_out"])
        self.assertIsNone(benign["timeout_kind"])
        attacked = art.results[0]["attacked"]
        self.assertTrue(attacked["malformed"])
        self.assertTrue(attacked["timed_out"])
        self.assertEqual(attacked["timeout_kind"], "item")
        # Honest attribution: only elapsed execution, not the budget.
        exec_ms = attacked["timing_ms"]["adapter_execution_ms"]
        self.assertGreater(exec_ms, 0.0)
        self.assertLess(exec_ms, 200.0)
        # D-11 conservative rule: attacked item timeout counts as
        # flipped; eligibility keys off the usable benign baseline.
        self.assertTrue(art.results[0]["flipped"])
        self.assertTrue(art.results[0]["eligible"])

    def test_item_timeout_mid_backoff_attributes_no_execution(self):
        # Regression test for the worker_in_flight P1 (R-12 red-team
        # delta review, 2026-09-30): attempt 1 fails immediately with
        # a retryable error carrying a deterministic 30s retry_after,
        # so the 0.5s item budget expires while the benign arm is
        # parked in backoff between attempts — the worker is NOT in
        # flight. adapter_execution_ms must stay near zero (only
        # attempt 1's instantaneous failure counts). Without the
        # in-flight guard, the stale attempt-1 worker_start makes the
        # handler attribute (deadline - worker_start), laundering
        # ~440ms of backoff into adapter execution (the pre-fix
        # control measured 436.46ms against 0.01ms fixed).
        cases = _demo_cases(1)
        art = run_suite(
            FailFastRetryableAdapter(retry_after=30.0), cases,
            "trial-demo", "0.1.0-demo", seed=0, item_timeout=0.5,
            max_concurrency=1, run_nonce=_R12_NONCE)
        self.assertEqual(len(art.results), 1)
        benign = art.results[0]["benign"]
        self.assertTrue(benign["timed_out"])
        self.assertEqual(benign["timeout_kind"], "item")
        exec_ms = benign["timing_ms"]["adapter_execution_ms"]
        self.assertLess(exec_ms, 50.0)
        # The budget expired mid-backoff: the interrupted backoff
        # sleep never completes, so its elapsed time is not added to
        # backoff_ms — it lands in the harness-overhead residual
        # instead. What matters for the P1 is that none of it is
        # laundered into adapter execution.
        self.assertGreater(
            benign["timing_ms"]["harness_overhead_ms"], 400.0)
        self.assertGreater(benign["latency_ms_total"], 400.0)
        # The case-level budget was exhausted by the benign arm, so
        # the attacked arm never started: still a typed item timeout,
        # with zero timing (nothing was measured).
        attacked = art.results[0]["attacked"]
        self.assertTrue(attacked["timed_out"])
        self.assertEqual(attacked["timeout_kind"], "item")
        self.assertEqual(attacked["latency_ms_total"], 0.0)
        for comp in ("admission_wait_ms", "adapter_execution_ms",
                     "harness_overhead_ms", "backoff_ms"):
            self.assertEqual(attacked["timing_ms"][comp], 0.0)

    def test_item_timeout_mid_slot_wait_attributes_no_execution(self):
        # Regression test for the worker_in_flight P1, slot-wait
        # variant (R-12 red-team delta review close-out, 2026-09-30):
        # with max_concurrency=2, the victim case's attempt 1 wins the
        # initial slot (dispatched first; AIMD starts at limit 1),
        # fails immediately with a retryable 429, and backs off 0.3s.
        # The blocker case then holds the only slot, so the victim's
        # attempt 2 parks in slot-wait — worker_start stale from
        # attempt 1, worker NOT in flight — when the 1.0s item budget
        # fires. adapter_execution_ms must stay near zero. Without the
        # in-flight guard, the stale worker_start makes the handler
        # attribute (deadline - worker_start), laundering ~700ms of
        # slot-wait into adapter execution.
        #
        # Timing margins: the 0.3s backoff gives the blocker ample time
        # to win the slot under xdist load (vs 0.05s originally); the
        # 1.0s budget fires 0.7s into the slot-wait, well before the
        # 2.0s blocker sleep ends.
        cases = _demo_cases(2)
        adapter = SlotContendedAdapter(retry_after=0.3, block_delay=2.0)
        art = run_suite(
            adapter, cases,
            "trial-demo", "0.1.0-demo", seed=0, item_timeout=1.0,
            max_concurrency=2, run_nonce=_R12_NONCE)
        self.assertEqual(len(art.results), 2)
        # Both adapter roles ran: the victim's attempt 1 (the 429) and
        # the blocker's sleep. If the blocker had won the initial slot
        # race, the victim would never have called decide().
        self.assertEqual(adapter.calls, 2)
        victim = art.results[0]["benign"]
        self.assertTrue(victim["timed_out"])
        self.assertEqual(victim["timeout_kind"], "item")
        exec_ms = victim["timing_ms"]["adapter_execution_ms"]
        self.assertLess(exec_ms, 50.0)
        self.assertGreater(victim["latency_ms_total"], 700.0)
        # The case-level budget was exhausted by the benign arm, so
        # the attacked arm never started: still a typed item timeout,
        # with zero timing (nothing was measured).
        attacked = art.results[0]["attacked"]
        self.assertTrue(attacked["timed_out"])
        self.assertEqual(attacked["timeout_kind"], "item")
        self.assertEqual(attacked["latency_ms_total"], 0.0)

    def test_run_suite_rejects_bad_timeouts(self):
        cases = _demo_cases(1)
        adapter = MockAdapter(
            script=MockAdapter.script_for(
                cases, seed=0, run_nonce=_R12_NONCE))
        for bad in (0, -1, float("nan"), True):
            with self.assertRaises(ValueError, msg=repr(bad)):
                run_suite(adapter, cases, "trial-demo", "0.1.0-demo",
                          seed=0, item_timeout=bad,
                          run_nonce=_R12_NONCE)
            with self.assertRaises(ValueError, msg=repr(bad)):
                run_suite(adapter, cases, "trial-demo", "0.1.0-demo",
                          seed=0, run_timeout=bad,
                          run_nonce=_R12_NONCE)


class TestTimeoutKind(unittest.TestCase):
    def test_from_dict_infers_attempt_for_legacy_timeout(self):
        # Records sealed before the kind existed: a timed_out record
        # without a kind is a per-attempt timeout (the item budget did
        # not exist then).
        import dataclasses

        rec = CallRecord(
            decision="<error>", confidence=None, abstained=False,
            refusal_reason="", usage=None, seed=0, dispatch_index=0,
            malformed=True, timed_out=True,
        )
        d = dataclasses.asdict(rec)
        del d["timeout_kind"]
        back = CallRecord.from_dict(d)
        self.assertEqual(back.timeout_kind, "attempt")

    def test_from_dict_rejects_bad_kind(self):
        import dataclasses

        rec = CallRecord(
            decision="<error>", confidence=None, abstained=False,
            refusal_reason="", usage=None, seed=0, dispatch_index=0,
            malformed=True, timed_out=True, timeout_kind="item",
        )
        d = dataclasses.asdict(rec)
        # Unknown kind string.
        d["timeout_kind"] = "bogus"
        with self.assertRaises(ValueError):
            CallRecord.from_dict(d)
        # Kind on a non-timed-out record.
        d["timeout_kind"] = "attempt"
        d["timed_out"] = False
        with self.assertRaises(ValueError):
            CallRecord.from_dict(d)

    def test_per_attempt_timeout_typed_attempt(self):
        # A call_timeout exhaustion seals with timeout_kind="attempt".
        async def go():
            controller = AdaptiveConcurrency(1)
            event = threading.Event()
            return await _record_call_async(
                BlockingAdapter(event), "1", {"input": "x"}, "choice",
                CallContext(call_id="c"), _trial(), 0, 0,
                load_pricing_table(),
                controller=controller, max_attempts=1, max_concurrency=1,
                call_timeout=0.05, cache=None, cache_key_str=None,
                transcript=None,
            )

        rec = asyncio.run(go())
        self.assertTrue(rec.timed_out)
        self.assertEqual(rec.timeout_kind, "attempt")
        self.assertTrue(rec.malformed)

    def test_transcript_round_trips_timeout_kind(self):
        # The kind rides the transcript entry; replay preserves it.
        import peira.runner as R

        for kind in ("attempt", "item"):
            entry = {
                "dispatch_index": 0,
                "dispatch_limit": 1,
                "seed": 0,
                "response": {"kind": "error", "error": "timeout"},
                "primitive": "choice",
                "latency_ms_total": 50.0,
                "timed_out": True,
                "timeout_kind": kind,
            }
            with mock.patch.object(R, "_rust", None):
                py_rec = R._record_from_transcript_entry(entry)
            rust_rec = R._record_from_transcript_entry(entry)
            self.assertEqual(py_rec.timeout_kind, kind)
            self.assertEqual(rust_rec.timeout_kind, kind)

    def test_transcript_rejects_corrupt_kind(self):
        entry = {
            "dispatch_index": 0,
            "dispatch_limit": 1,
            "seed": 0,
            "response": {"kind": "error", "error": "timeout"},
            "primitive": "choice",
            "latency_ms_total": 50.0,
            "timed_out": True,
            "timeout_kind": "bogus",
        }
        with self.assertRaises(ValueError):
            _record_from_transcript_entry(entry)


class TestRunTimeout(unittest.TestCase):
    def test_run_timeout_stops_dispatch_drains_and_checkpoints(self):
        # Event-gated adapter: blocks until released. The run budget
        # fires while two cases are in-flight; dispatch stops, the two
        # drain to completion when released (honest records, not
        # cancelled); the remaining cases never dispatch. The sealed
        # artifact carries termination="timeout" and the partial is
        # preserved as resumable. No wall-clock timing assumptions:
        # the gate ensures exactly two cases are in-flight when the
        # budget fires.
        cases = _demo_cases(4)
        gate = threading.Event()
        in_flight_count = [0]
        count_lock = threading.Lock()

        base = MockAdapter(
            script=MockAdapter.script_for(
                cases, seed=0, run_nonce=_R12_NONCE))

        class GatedAdapter(MockAdapter):
            def decide(self, case_input, primitive, context):
                with count_lock:
                    in_flight_count[0] += 1
                try:
                    gate.wait(timeout=10.0)
                    return base.decide(case_input, primitive, context)
                finally:
                    with count_lock:
                        in_flight_count[0] -= 1

        with TemporaryDirectory() as tmp:
            partial_path = Path(tmp) / "partial.json"
            # Run in a thread so the test can gate on in-flight count.
            result = {}
            def run():
                result["art"] = run_suite(
                    GatedAdapter(), cases, "trial-demo",
                    "0.1.0-demo", seed=0, run_timeout=0.05,
                    max_concurrency=2, partial_path=partial_path,
                    run_nonce=_R12_NONCE)
            t = threading.Thread(target=run)
            t.start()
            # Wait until two cases are in-flight (dispatched and
            # blocked on the gate).
            deadline = time.time() + 10.0
            while time.time() < deadline:
                with count_lock:
                    if in_flight_count[0] >= 2:
                        break
                time.sleep(0.01)
            # The run budget (0.05s) has fired by now: dispatch has
            # stopped. Release the gate so the in-flight cases drain.
            gate.set()
            t.join(timeout=30.0)
            art = result["art"]
            self.assertEqual(art.termination, "timeout")
            # Never presented as ranking eligible.
            self.assertFalse(art.metrics["ranking_eligible"])
            # The two in-flight cases drained (completed honestly);
            # the other two never dispatched.
            self.assertEqual(len(art.results), 2)
            for r in art.results:
                self.assertFalse(r["benign"]["malformed"])
                self.assertFalse(r["attacked"]["malformed"])
            # Completed cases were checkpointed; the partial is
            # resumable and holds fewer than the planned cases.
            self.assertTrue(partial_path.exists())
            partial = RunArtifact.from_json(partial_path.read_text())
            self.assertLess(partial.cases_completed, len(cases))
            self.assertEqual(partial.termination, "partial")

    def test_resume_validates_timeout_budgets(self):
        from peira.runner import run_case

        cases = _demo_cases(4)
        adapter = MockAdapter(
            script=MockAdapter.script_for(
                cases, seed=0, run_nonce=_R12_NONCE))
        table = load_pricing_table()
        indexed = {c.case_id: i for i, c in enumerate(cases)}
        results = [
            run_case(adapter, c, seed=0,
                     dispatch_base=2 * indexed[c.case_id],
                     pricing_table=table, run_nonce=_R12_NONCE)
            for c in cases[:2]
        ]
        with TemporaryDirectory() as tmp:
            partial_path = Path(tmp) / "p.partial.json"
            _write_partial(
                partial_path, adapter, cases, "trial-demo",
                "0.1.0-demo", results,
                sorted({c.family for c in cases}), indexed, seed=0,
                item_timeout=10.0, run_timeout=20.0)
            partial = RunArtifact.from_json(partial_path.read_text())
            # Matching budgets validate fine.
            done, _ = validate_partial(
                partial, adapter, cases, "trial-demo", "0.1.0-demo",
                seed=0, item_timeout=10.0, run_timeout=20.0)
            self.assertEqual(len(done), 2)
            # A changed ceiling is a changed measurement: refuse.
            with self.assertRaises(ValueError):
                validate_partial(
                    partial, adapter, cases, "trial-demo",
                    "0.1.0-demo", seed=0, item_timeout=30.0,
                    run_timeout=20.0)
            with self.assertRaises(ValueError):
                validate_partial(
                    partial, adapter, cases, "trial-demo",
                    "0.1.0-demo", seed=0, item_timeout=10.0,
                    run_timeout=None)

    def test_cli_rejects_nonpositive_timeouts(self):
        from peira.cli import EXIT_USER_ERROR, build_parser, cmd_run

        with TemporaryDirectory() as tmp:
            for flag in ("--item-timeout", "--run-timeout"):
                args = build_parser().parse_args([
                    "run", "--adapter", "mock", "--suite", "trial-demo",
                    "--out", tmp, "--seed", "42", flag, "0",
                ])
                with mock.patch("sys.stderr"):
                    rc = cmd_run(args)
                self.assertEqual(rc, EXIT_USER_ERROR, flag)


class TestReplayTiming(unittest.TestCase):
    def test_replay_preserves_timing(self):
        cases = _demo_cases(2)
        adapter = MockAdapter(
            script=MockAdapter.script_for(
                cases, seed=0, run_nonce=_R12_NONCE))
        with TemporaryDirectory() as tmp:
            tpath = str(Path(tmp) / "t.jsonl")
            art = run_suite(
                adapter, cases, "trial-demo", "0.1.0-demo", seed=0,
                transcript_path=tpath, run_nonce=_R12_NONCE)
            replayed = replay_suite(
                tpath, cases, "trial-demo", "0.1.0-demo")
        for orig, new in zip(art.results, replayed.results):
            for arm in ("benign", "attacked"):
                self.assertEqual(
                    orig[arm]["timing_ms"], new[arm]["timing_ms"],
                    f"timing lost on replay for {arm}")

    def test_replay_timing_rust_python_parity(self):
        # The dispatched replay path must agree with the pure-Python
        # reference whether or not the Rust core is active.
        import peira.runner as R

        entry = {
            "dispatch_index": 0,
            "dispatch_limit": 1,
            "seed": 0,
            "response": {
                "kind": "output",
                "output": {
                    "decision": "allow", "confidence": 0.9,
                    "abstained": False, "refusal_reason": "",
                    "usage": None,
                },
            },
            "primitive": "choice",
            "latency_ms_total": 12.0,
            "timing_ms": {
                "admission_wait_ms": 1.0,
                "adapter_execution_ms": 9.0,
                "harness_overhead_ms": 2.0,
                "backoff_ms": 0.0,
            },
        }
        with mock.patch.object(R, "_rust", None):
            py_rec = R._record_from_transcript_entry(entry)
        rust_rec = R._record_from_transcript_entry(entry)
        self.assertEqual(py_rec.timing_ms, rust_rec.timing_ms)
        self.assertEqual(rust_rec.timing_ms.adapter_execution_ms, 9.0)

    def test_pre_r12_entry_replays_to_zero_breakdown(self):
        entry = {
            "dispatch_index": 0,
            "dispatch_limit": 1,
            "seed": 0,
            "response": {
                "kind": "output",
                "output": {
                    "decision": "allow", "confidence": 0.9,
                    "abstained": False, "refusal_reason": "",
                    "usage": None,
                },
            },
            "primitive": "choice",
            "latency_ms_total": 12.0,
        }
        rec = _record_from_transcript_entry(entry)
        self.assertEqual(rec.timing_ms, CallTiming.from_dict(None))


class TestTimingSummaryPolicy(unittest.TestCase):
    def _results(self, family, exec_ms_values):
        from peira.metrics import PerCaseResult

        out = []
        for i, v in enumerate(exec_ms_values):
            timing = CallTiming(
                admission_wait_ms=1.0, adapter_execution_ms=v,
                harness_overhead_ms=2.0, backoff_ms=0.0)
            benign = CallRecord(
                decision="allow", confidence=0.9, abstained=False,
                refusal_reason="", usage=None, seed=0,
                dispatch_index=2 * i, malformed=False, timing_ms=timing)
            attacked = CallRecord(
                decision="allow", confidence=0.9, abstained=False,
                refusal_reason="", usage=None, seed=0,
                dispatch_index=2 * i + 1, malformed=False,
                timing_ms=timing)
            out.append(PerCaseResult(
                case_id=f"c{i}", family=family, severity="high",
                primitive="choice", benign=benign, attacked=attacked,
                flipped=False, eligible=True,
                ineligibility_reason=""))
        return out

    def test_per_family_components_and_thresholds(self):
        # 4 samples per record-pair arm: 8 observations per component.
        # p95 is published whenever n > 0; p99 needs >= 100 (withheld).
        results = self._results("f1", [10.0, 20.0, 30.0, 40.0])
        s = timing_summary(results)
        comp = s["f1"]["components"]["adapter_execution_ms"]
        self.assertEqual(comp["n"], 8)
        self.assertEqual(comp["min"], 10.0)
        self.assertEqual(comp["p50"], 25.0)
        self.assertIsNotNone(comp["p95"])
        self.assertIsNone(comp["p99"])
        self.assertEqual(len(comp["samples"]), 8)

    def test_p95_published_for_single_observation(self):
        # p95 has no minimum-observation gate: n is always reported
        # alongside, so a high quantile on a tiny sample is
        # inspectable, not misleading.
        results = self._results("f1", [42.0])
        s = timing_summary(results)
        comp = s["f1"]["components"]["adapter_execution_ms"]
        self.assertEqual(comp["n"], 2)
        self.assertEqual(comp["p95"], 42.0)
        self.assertEqual(comp["p50"], 42.0)
        self.assertEqual(comp["min"], 42.0)

    def test_residual_clamp_against_float_dust(self):
        # _assemble_timing clamps a dust-level negative residual to
        # zero: the components are nested sub-windows of one monotonic
        # clock, so only float rounding can push the residual negative.
        from peira.runner import _assemble_timing

        with mock.patch(
            "peira.runner.time.perf_counter", return_value=1000.0
        ):
            # total = 0ms; components sum to 2e-9ms (dust-level
            # negative residual) -> clamped to 0.0, not negative.
            timing = _assemble_timing(1000.0, 1e-9, 1e-9, 0.0)
        self.assertEqual(timing.harness_overhead_ms, 0.0)

    def test_raw_samples_retain_full_precision(self):
        # Raw samples are never rounded: a value with precision beyond
        # four decimals must survive verbatim; rounding is presentation
        # only (applied to the derived statistics).
        precise = 12.345678901234
        results = self._results("f1", [precise])
        s = timing_summary(results)
        comp = s["f1"]["components"]["adapter_execution_ms"]
        self.assertIn(precise, comp["samples"])
        self.assertEqual(comp["samples"][0], precise)
        # The derived statistics ARE rounded to four decimals.
        self.assertEqual(comp["min"], round(precise, 4))

    def test_p99_published_at_100_observations(self):
        results = self._results("f1", [float(i) for i in range(50)])
        s = timing_summary(results)
        comp = s["f1"]["components"]["adapter_execution_ms"]
        self.assertEqual(comp["n"], 100)
        self.assertIsNotNone(comp["p99"])

    def test_no_silent_trimming_of_extremes(self):
        # One extreme sample must survive verbatim in the retained
        # samples: no trimming, no winsorizing.
        results = self._results("f1", [10.0, 10.0, 10.0, 10000.0])
        s = timing_summary(results)
        comp = s["f1"]["components"]["adapter_execution_ms"]
        self.assertIn(10000.0, comp["samples"])
        self.assertEqual(comp["n"], 8)

    def test_cv_and_investigate_flag(self):
        # Constant component: cv 0, no flag. Wild component: cv > 5%,
        # flag set.
        results = self._results("f1", [10.0, 10.0, 1000.0, 1000.0])
        s = timing_summary(results)
        adm = s["f1"]["components"]["admission_wait_ms"]
        self.assertEqual(adm["cv"], 0.0)
        self.assertFalse(adm["investigate"])
        exe = s["f1"]["components"]["adapter_execution_ms"]
        self.assertGreater(exe["cv"], 0.05)
        self.assertTrue(exe["investigate"])

    def test_cache_and_timeout_excluded_but_counted(self):
        results = self._results("f1", [10.0, 20.0])
        cached = CallRecord(
            decision="allow", confidence=0.9, abstained=False,
            refusal_reason="", usage=None, seed=0, dispatch_index=99,
            malformed=False, cached=True,
            timing_ms=CallTiming(
                admission_wait_ms=0.0, adapter_execution_ms=0.0,
                harness_overhead_ms=5.0, backoff_ms=0.0))
        timed_out = CallRecord(
            decision="<error>", confidence=None, abstained=False,
            refusal_reason="", usage=None, seed=0, dispatch_index=100,
            malformed=True, timed_out=True, latency_ms_total=50.0,
            timing_ms=CallTiming(
                admission_wait_ms=0.0, adapter_execution_ms=50.0,
                harness_overhead_ms=0.0, backoff_ms=0.0))
        results[0] = results[0].__class__(
            **{**results[0].__dict__, "benign": cached,
               "attacked": timed_out})
        s = timing_summary(results)
        fam = s["f1"]
        self.assertEqual(fam["n_cached"], 1)
        self.assertEqual(fam["n_timeouts"], 1)
        # 2 records x 2 arms = 4 calls; one cached + one timed out
        # excluded from the percentile inputs.
        comp = fam["components"]["adapter_execution_ms"]
        self.assertEqual(comp["n"], 2)

    def test_families_never_averaged(self):
        r1 = self._results("f1", [10.0])
        r2 = self._results("f2", [1000.0])
        s = timing_summary(r1 + r2)
        self.assertEqual(
            s["f1"]["components"]["adapter_execution_ms"]["p50"], 10.0)
        self.assertEqual(
            s["f2"]["components"]["adapter_execution_ms"]["p50"],
            1000.0)
        self.assertNotIn("overall", s)


if __name__ == "__main__":
    unittest.main()
