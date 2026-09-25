"""Unit tests for A1: async runner, AIMD controller, retry, cache,
transcripts, replay, and cancellation (run with: python -m unittest
discover tests)."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import random
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from peira.adapters.base import ChoiceOutput, ProviderError
from peira.adapters.mock import MockAdapter
from peira.artifacts import RunArtifact, results_to_dicts
from peira.concurrency import (
    MAX_RETRY_AFTER_S,
    AdaptiveConcurrency,
    ResponseCache,
    backoff_delay,
    cache_key,
    classify_exception,
    load_transcript,
    validate_transcript_entry,
)
from peira.metrics import CallRecord, PerCaseResult
from peira.runner import (
    _run_suite_async,
    load_cases,
    replay_suite,
    run_case,
    run_suite,
)
from peira.pricing import load_pricing_table
from peira.schema import Case

REPO_ROOT = Path(__file__).resolve().parents[1]


def _demo_cases(n=6):
    return load_cases(REPO_ROOT / "dataset" / "trial-demo")[:n]


# One nonce for the whole module: every scripted mock and every run in
# these tests must share the same run namespace, or scripts match
# nothing. (Cross-run unlinkability is covered in test_mock.py.)
_CONC_NONCE = "concurrency-test-nonce"


def _mock(cases, seed=0):
    """MockAdapter with a harness-built script under the shared nonce."""
    return MockAdapter(
        script=MockAdapter.script_for(cases, seed=seed,
                                      run_nonce=_CONC_NONCE))


def _run(cases, seed=0, **kw):
    """run_suite with a scripted mock under the shared nonce."""
    kw.setdefault("run_nonce", _CONC_NONCE)
    return run_suite(_mock(cases, seed=seed), cases, "trial-demo",
                     "0.1.0-demo", seed=seed, **kw)


def _counting(cases, seed=0, **kw):
    """CountingAdapter with a harness-built script under the shared nonce."""
    return CountingAdapter(
        script=MockAdapter.script_for(cases, seed=seed,
                                      run_nonce=_CONC_NONCE),
        **kw,
    )


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


class TestAdaptiveConcurrency(unittest.TestCase):
    def test_slow_start_doubling(self):
        c = AdaptiveConcurrency(8, time_fn=FakeClock())
        self.assertEqual(c.limit, 1)
        self.assertTrue(c.in_slow_start)
        c.on_success()
        self.assertEqual(c.limit, 2)
        c.on_success()
        self.assertEqual(c.limit, 4)
        c.on_success()
        self.assertEqual(c.limit, 8)
        c.on_success()
        self.assertEqual(c.limit, 8)  # capped at max

    def test_multiplicative_decrease_on_congestion(self):
        clock = FakeClock()
        c = AdaptiveConcurrency(8, time_fn=clock)
        for _ in range(3):
            c.on_success()
        self.assertEqual(c.limit, 8)
        self.assertTrue(c.on_congestion())
        self.assertEqual(c.limit, 6)  # floor(8 * 0.8)
        self.assertFalse(c.in_slow_start)

    def test_floor_is_one(self):
        clock = FakeClock()
        c = AdaptiveConcurrency(8, time_fn=clock)
        c.on_success()  # limit 2
        self.assertTrue(c.on_congestion())
        self.assertEqual(c.limit, 1)  # floor(2 * 0.8) = 1
        clock.advance(16)
        self.assertTrue(c.on_congestion())
        self.assertEqual(c.limit, 1)  # never below 1

    def test_debounce(self):
        clock = FakeClock()
        c = AdaptiveConcurrency(16, time_fn=clock)
        for _ in range(4):
            c.on_success()
        self.assertEqual(c.limit, 16)
        self.assertTrue(c.on_congestion())
        self.assertEqual(c.limit, 12)
        clock.advance(5)
        self.assertFalse(c.on_congestion())  # debounced
        self.assertEqual(c.limit, 12)  # unchanged
        clock.advance(10)  # 15s total
        self.assertTrue(c.on_congestion())
        self.assertEqual(c.limit, 9)  # floor(12 * 0.8)

    def test_no_permanent_ceiling_after_cut(self):
        # A cut backs the limit off; saturated additive growth
        # recovers it once congestion clears — the controller must not
        # ratchet down permanently after transient 429 bursts.
        async def go():
            clock = FakeClock()
            c = AdaptiveConcurrency(16, time_fn=clock)
            for _ in range(4):
                c.on_success()
            self.assertTrue(c.on_congestion())  # 16 -> 12
            self.assertEqual(c.limit, 12)

            # Sustained saturated demand: 14 concurrent holders keeps
            # the peak above 0.8 * limit all the way back to the cap.
            async def holder():
                async with c.slot():
                    for _ in range(10):
                        c.on_success()
                        await asyncio.sleep(0)

            await asyncio.gather(*[holder() for _ in range(14)])
            return c.limit

        self.assertEqual(asyncio.run(go()), 16)

    def test_saturation_gate_blocks_idle_growth(self):
        # Steady-state growth requires observed demand: without any
        # in-flight saturation the limit stays put.
        clock = FakeClock()
        c = AdaptiveConcurrency(100, time_fn=clock)
        c.on_congestion()  # leave slow start; limit stays 1
        self.assertEqual(c.limit, 1)
        c.on_success()  # peak in-flight 0 < 0.8 * 1: no growth
        self.assertEqual(c.limit, 1)
        self.assertAlmostEqual(c._limit, 1.0)

    def test_saturation_gate_allows_growth_under_load(self):
        async def go():
            clock = FakeClock()
            c = AdaptiveConcurrency(100, time_fn=clock)
            c.on_congestion()  # leave slow start; limit 1
            async with c.slot():  # peak in-flight 1 >= 0.8 * 1
                pass
            before = c._limit
            c.on_success()
            return before, c._limit

        before, after = asyncio.run(go())
        self.assertGreater(after, before)
        self.assertLess(after, before * 1.5)  # additive, not doubling

    def test_peak_decays_with_demand(self):
        # After a busy spell, a quiet spell closes the gate again.
        async def go():
            clock = FakeClock()
            c = AdaptiveConcurrency(100, time_fn=clock)
            c.on_congestion()
            async with c.slot():
                pass
            c.on_success()  # saturated -> grows
            grown = c._limit
            c.on_success()  # idle now -> no growth
            return grown, c._limit

        grown, after = asyncio.run(go())
        self.assertGreater(grown, 1.0)
        self.assertEqual(after, grown)

    def test_invalid_max_limit(self):
        with self.assertRaises(ValueError):
            AdaptiveConcurrency(0)

    def test_slot_bounds_in_flight(self):
        async def go():
            c = AdaptiveConcurrency(8, initial=3, time_fn=FakeClock())
            peak = 0
            current = 0

            async def worker():
                nonlocal peak, current
                async with c.slot():
                    current += 1
                    peak = max(peak, current)
                    await asyncio.sleep(0.001)
                    current -= 1

            await asyncio.gather(*[worker() for _ in range(12)])
            return peak

        self.assertLessEqual(asyncio.run(go()), 3)

    def test_slot_tracks_limit_growth(self):
        # Slow start grows the limit as calls succeed: later calls may
        # overlap more. Just assert it never exceeds the max.
        async def go():
            c = AdaptiveConcurrency(4, time_fn=FakeClock())
            peak = 0
            current = 0

            async def worker():
                nonlocal peak, current
                async with c.slot():
                    current += 1
                    peak = max(peak, current)
                    await asyncio.sleep(0)
                c.on_success()
                current -= 1

            await asyncio.gather(*[worker() for _ in range(8)])
            return peak

        self.assertLessEqual(asyncio.run(go()), 4)


class TestClassifyException(unittest.TestCase):
    def test_transient_statuses(self):
        for status in (408, 409, 429, 500, 502, 503, 599):
            retryable, cut, _ = classify_exception(
                ProviderError("x", status_code=status))
            self.assertTrue(retryable, status)

    def test_congestion_cut_only_on_429_503(self):
        _, cut, _ = classify_exception(ProviderError("x", status_code=429))
        self.assertTrue(cut)
        _, cut, _ = classify_exception(ProviderError("x", status_code=503))
        self.assertTrue(cut)
        _, cut, _ = classify_exception(ProviderError("x", status_code=500))
        self.assertFalse(cut)

    def test_permanent_statuses_never_retry(self):
        for status in (400, 401, 403, 404, 422):
            retryable, cut, _ = classify_exception(
                ProviderError("x", status_code=status))
            self.assertFalse(retryable, status)
            self.assertFalse(cut)

    def test_unknown_status_not_retried(self):
        retryable, _, _ = classify_exception(
            ProviderError("x", status_code=418))
        self.assertFalse(retryable)

    def test_timeouts_retryable(self):
        for exc in (TimeoutError("t"), asyncio.TimeoutError("t")):
            retryable, cut, _ = classify_exception(exc)
            self.assertTrue(retryable)
            self.assertFalse(cut)

    def test_connection_error_retryable(self):
        retryable, _, _ = classify_exception(
            ConnectionResetError("dropped"))
        self.assertTrue(retryable)

    def test_plain_exception_not_retryable(self):
        retryable, _, _ = classify_exception(RuntimeError("bug"))
        self.assertFalse(retryable)

    def test_retry_after_honored_and_flagged(self):
        retryable, cut, delay = classify_exception(
            ProviderError("slow", status_code=429, retry_after=5))
        self.assertTrue(retryable)
        self.assertTrue(cut)
        self.assertEqual(delay, 5)

    def test_retry_after_without_status(self):
        retryable, cut, delay = classify_exception(
            ProviderError("slow", retry_after=2))
        self.assertTrue(retryable)
        self.assertTrue(cut)
        self.assertEqual(delay, 2)

    def test_negative_retry_after_ignored(self):
        _, _, delay = classify_exception(
            ProviderError("x", status_code=500, retry_after=-1))
        self.assertIsNone(delay)


class TestBackoff(unittest.TestCase):
    def test_bounds(self):
        rng = random.Random(7)
        for attempt in range(6):
            d = backoff_delay(attempt, rng)
            self.assertGreaterEqual(d, 0.0)
            self.assertLessEqual(d, min(60.0, 2.0 ** attempt))

    def test_deterministic_for_seed(self):
        seq = lambda: [backoff_delay(a, random.Random(42)) for a in range(4)]
        self.assertEqual(seq(), seq())

    def test_cap(self):
        d = backoff_delay(100, random.Random(1))
        self.assertLessEqual(d, 60.0)


class CountingAdapter(MockAdapter):
    """Mock that counts decide() calls and can fail on demand."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.calls = 0
        self.failures: list = []  # exceptions to raise, in order

    def decide(self, case_input, primitive, context):
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return super().decide(case_input, primitive, context)


class TestRunnerRetry(unittest.TestCase):
    def test_permanent_error_not_retried(self):
        cases = _demo_cases(2)
        adapter = _counting(cases, seed=0)
        adapter.failures = [ProviderError("bad", status_code=400)] * 10
        art = run_suite(adapter, cases, "trial-demo", "0.1.0-demo",
                        max_attempts=3, seed=0, run_nonce=_CONC_NONCE)
        # 2 cases x 2 variants, one try each: permanent errors never retry.
        self.assertEqual(adapter.calls, 4)
        for r in art.results:
            self.assertTrue(r["benign"]["malformed"])

    def test_transient_then_success(self):
        cases = _demo_cases(1)
        adapter = _counting(cases, seed=0)
        adapter.failures = [ProviderError("busy", status_code=503),
                            ProviderError("busy", status_code=503)]
        art = run_suite(adapter, cases, "trial-demo", "0.1.0-demo",
                        max_attempts=3, seed=0, run_nonce=_CONC_NONCE)
        # Benign: fail, fail, succeed. Attacked: no failures left.
        self.assertEqual(adapter.calls, 4)
        attacked = art.results[0]["attacked"]
        self.assertFalse(attacked["malformed"])

    def test_retries_exhausted(self):
        cases = _demo_cases(1)
        adapter = _counting(cases, seed=0)
        adapter.failures = [ProviderError("down", status_code=500)] * 10
        art = run_suite(adapter, cases, "trial-demo", "0.1.0-demo",
                        max_attempts=3, seed=0, run_nonce=_CONC_NONCE)
        # benign: 3 attempts; attacked: 3 attempts
        self.assertEqual(adapter.calls, 6)
        self.assertTrue(art.results[0]["benign"]["malformed"])

    def test_retry_after_capped_at_60s(self):
        from unittest import mock
        delays = []

        async def fake_sleep(d):
            delays.append(d)

        adapter = _counting(_demo_cases(1), seed=0)
        adapter.failures = [ProviderError("slow", status_code=429,
                                          retry_after=3600),
                            ProviderError("ok-now", status_code=500)]
        with mock.patch("asyncio.sleep", fake_sleep):
            run_suite(adapter, _demo_cases(1), "trial-demo", "0.1.0-demo",
                      max_attempts=3, seed=0, run_nonce=_CONC_NONCE)
        self.assertIn(60.0, delays)
        self.assertTrue(all(d <= MAX_RETRY_AFTER_S for d in delays))

    def test_jitter_deterministic_across_runs(self):
        from unittest import mock
        runs = []

        async def fake_sleep(d):
            runs.append(d)

        for _ in range(2):
            cases = _demo_cases(2)
            adapter = _counting(cases, seed=99)
            # Plenty of failures: every variant fails its first attempt
            # (whatever order it runs in), retries once, then succeeds.
            adapter.failures = [ProviderError("x", status_code=500)] * 100
            with mock.patch("asyncio.sleep", fake_sleep):
                run_suite(adapter, cases, "trial-demo",
                          "0.1.0-demo", max_attempts=2, seed=99,
                          max_concurrency=2, run_nonce=_CONC_NONCE)
        # 2 cases x 2 variants x 1 retry each = 4 delays per run. The
        # jitter seed is (run seed, dispatch index, attempt), so the
        # delay *set* is identical across runs even though completion
        # order may interleave the appends differently.
        self.assertEqual(len(runs), 8)
        self.assertEqual(sorted(runs[:4]), sorted(runs[4:]))

    def test_invalid_options_rejected(self):
        cases = _demo_cases(1)
        with self.assertRaises(ValueError):
            run_suite(MockAdapter(), cases, "trial-demo", "0.1.0-demo",
                      max_concurrency=0)
        with self.assertRaises(ValueError):
            run_suite(MockAdapter(), cases, "trial-demo", "0.1.0-demo",
                      max_attempts=0)
        with self.assertRaises(ValueError):
            run_suite(MockAdapter(), cases, "trial-demo", "0.1.0-demo",
                      call_timeout=-1)

    def test_call_timeout_is_transient(self):
        class SlowAdapter(MockAdapter):
            def decide(self, case_input, primitive, context):
                import time as _t
                _t.sleep(0.3)
                return super().decide(case_input, primitive, context)

        art = run_suite(
            SlowAdapter(
                script=MockAdapter.script_for(
                    _demo_cases(1), seed=0, run_nonce=_CONC_NONCE)),
            _demo_cases(1), "trial-demo",
            "0.1.0-demo", call_timeout=0.05, max_attempts=2,
            seed=0, run_nonce=_CONC_NONCE)
        # Every attempt times out -> malformed after 2 attempts x 2 variants.
        self.assertTrue(art.results[0]["benign"]["malformed"])
        self.assertTrue(art.results[0]["attacked"]["malformed"])


class TestAtomicTranscriptCapture(unittest.TestCase):
    def test_raw_captured_per_call_from_output(self):
        # Provider-native payloads ride the output's `transcript` field,
        # so they are captured atomically with the call by construction:
        # each concurrent call's payloads land on the right transcript
        # entry with no hook and no thread-local bookkeeping — even with
        # 8 concurrent calls sharing one adapter instance.
        class TranscriptAdapter(MockAdapter):
            def decide(self, case_input, primitive, context):
                out = super().decide(case_input, primitive, context)
                # B2: the context is opaque — the adapter only ever sees
                # the pseudonymous call id, so that is all it can echo.
                return dataclasses.replace(
                    out,
                    transcript={"call_id": context.call_id},
                )

        with TemporaryDirectory() as tmp:
            tpath = str(Path(tmp) / "t.jsonl")
            cases = _demo_cases(8)
            run_suite(
                TranscriptAdapter(
                    script=MockAdapter.script_for(
                        cases, seed=3, run_nonce=_CONC_NONCE)),
                cases, "trial-demo", "0.1.0-demo", max_concurrency=8,
                seed=3, transcript_path=tpath, run_nonce=_CONC_NONCE,
            )
            entries = [
                json.loads(line) for line in open(tpath, encoding="utf-8")
            ]
        self.assertEqual(len(entries), 16)  # 8 cases x 2 variants
        for entry in entries:
            self.assertIsNotNone(entry["raw"])
            # The raw payload the adapter attached landed on the entry
            # for the exact call the adapter saw — no cross-talk between
            # concurrent calls sharing one adapter instance.
            self.assertEqual(entry["raw"]["call_id"], entry["call_id"])

    def test_non_dict_transcript_is_malformed(self):
        # A transcript that is not a dict (or None) is an adapter bug:
        # the output is malformed, but the transcript read itself never
        # fails the run.
        class BadTranscriptAdapter(MockAdapter):
            def decide(self, case_input, primitive, context):
                out = super().decide(case_input, primitive, context)
                return dataclasses.replace(out, transcript="oops")

        with TemporaryDirectory() as tmp:
            tpath = str(Path(tmp) / "t.jsonl")
            cases = _demo_cases(1)
            art = run_suite(
                BadTranscriptAdapter(
                    script=MockAdapter.script_for(
                        cases, seed=0, run_nonce=_CONC_NONCE)),
                cases, "trial-demo", "0.1.0-demo", seed=0,
                transcript_path=tpath, run_nonce=_CONC_NONCE,
            )
            entries = [
                json.loads(line) for line in open(tpath, encoding="utf-8")
            ]
        self.assertTrue(art.results[0]["benign"]["malformed"])
        self.assertTrue(art.results[0]["attacked"]["malformed"])
        for entry in entries:
            self.assertIsNone(entry["raw"])

    def test_raw_none_on_error_path(self):
        # A failed call has no completed provider call to attribute raw
        # payloads to — the transcript must say None, never guess.
        class ExplodingAdapter(MockAdapter):
            def decide(self, case_input, primitive, context):
                raise RuntimeError("kaput")

        with TemporaryDirectory() as tmp:
            tpath = str(Path(tmp) / "t.jsonl")
            run_suite(
                ExplodingAdapter(), _demo_cases(2), "trial-demo",
                "0.1.0-demo", max_concurrency=2, transcript_path=tpath,
            )
            entries = [
                json.loads(line) for line in open(tpath, encoding="utf-8")
            ]
        self.assertTrue(entries)
        for entry in entries:
            self.assertEqual(entry["response"]["kind"], "error")
            self.assertIsNone(entry["raw"])


class TestDeterministicOrdering(unittest.TestCase):
    def test_results_in_suite_order(self):
        class JitterAdapter(MockAdapter):
            def decide(self, case_input, primitive, context):
                import time as _t
                rng = random.Random(context.case_id)
                _t.sleep(rng.uniform(0, 0.005))
                return super().decide(case_input, primitive, context)

        cases = _demo_cases(8)
        art = run_suite(JitterAdapter(), cases, "trial-demo", "0.1.0-demo",
                        max_concurrency=8, seed=3)
        self.assertEqual([r["case_id"] for r in art.results],
                         [c.case_id for c in cases])
        for i, r in enumerate(art.results):
            self.assertEqual(r["benign"]["dispatch_index"], 2 * i)
            self.assertEqual(r["attacked"]["dispatch_index"], 2 * i + 1)

    def test_identical_records_across_concurrency_levels(self):
        def scrubbed(concurrency):
            art = _run(_demo_cases(6), seed=5, max_concurrency=concurrency)
            results = json.loads(json.dumps(art.results))
            for r in results:
                for variant in ("benign", "attacked"):
                    # Normalize provenance that legitimately varies with
                    # concurrency: wall-clock latency, and the dispatch
                    # limit actually used (1 vs up to 8). The measured
                    # outputs must be identical.
                    r[variant]["dispatch_limit"] = 0
                    usage = r[variant]["usage"]
                    if usage:
                        usage["latency_ms"] = 0.0
            return results

        self.assertEqual(scrubbed(1), scrubbed(8))


class TestResumeConcurrency(unittest.TestCase):
    def _partial_first_n(self, cases, n, tmp):
        adapter = _mock(cases, seed=0)
        table = load_pricing_table()
        from peira.runner import _write_partial, run_case
        indexed = {c.case_id: i for i, c in enumerate(cases)}
        results = [run_case(adapter, c, seed=0, dispatch_base=2 * indexed[c.case_id],
                            pricing_table=table, run_nonce=_CONC_NONCE)
                   for c in cases[:n]]
        partial_path = Path(tmp) / "p.partial.json"
        _write_partial(partial_path, adapter, cases, "trial-demo",
                       "0.1.0-demo", results, sorted({c.family for c in cases}),
                       indexed, seed=0, max_concurrency=4)
        return partial_path

    def test_resume_no_duplicates_and_sorted(self):
        cases = _demo_cases(6)
        with TemporaryDirectory() as tmp:
            partial_path = self._partial_first_n(cases, 3, tmp)
            partial = RunArtifact.from_json(partial_path.read_text())
            # Shuffle the partial's results: resume must still seal in
            # suite order.
            import random as _r
            shuffled = list(partial.results)
            _r.Random(1).shuffle(shuffled)
            partial.results = shuffled
            partial.seal()
            partial_path.write_text(partial.to_json())
            partial = RunArtifact.from_json(partial_path.read_text())

            from peira.runner import validate_partial
            done, prior = validate_partial(partial, MockAdapter(), cases,
                                           "trial-demo", "0.1.0-demo", seed=0)
            art = _run(cases, seed=0, already_done=done,
                       prior_results=prior, max_concurrency=4)
            ids = [r["case_id"] for r in art.results]
            self.assertEqual(ids, [c.case_id for c in cases])
            self.assertEqual(len(set(ids)), len(ids))
            for i, r in enumerate(art.results):
                self.assertEqual(r["benign"]["dispatch_index"], 2 * i)

    def test_resume_ignores_max_concurrency_change(self):
        # Concurrency is a performance parameter: resuming with a
        # different limit is safe and keeps the original records.
        cases = _demo_cases(4)
        with TemporaryDirectory() as tmp:
            partial_path = self._partial_first_n(cases, 2, tmp)
            partial = RunArtifact.from_json(partial_path.read_text())
            from peira.runner import validate_partial
            done, prior = validate_partial(partial, MockAdapter(), cases,
                                           "trial-demo", "0.1.0-demo", seed=0)
            art = _run(cases, seed=0, already_done=done,
                       prior_results=prior, max_concurrency=1)
            self.assertEqual(art.max_concurrency, 1)
            self.assertEqual(len(art.results), 4)


class TestTranscriptAndReplay(unittest.TestCase):
    def _run_with_transcript(self, tmp, n=4, seed=11):
        cases = _demo_cases(n)
        tpath = Path(tmp) / "t.jsonl"
        art = _run(cases, seed=seed, max_concurrency=4,
                   transcript_path=tpath)
        return cases, art, tpath

    def test_transcript_entries_validate(self):
        with TemporaryDirectory() as tmp:
            cases, _, tpath = self._run_with_transcript(tmp)
            lines = tpath.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2 * len(cases))
            for i, line in enumerate(lines, 1):
                entry = validate_transcript_entry(json.loads(line), i)
                self.assertEqual(entry["response"]["kind"], "output")
                self.assertIn(entry["variant"], ("benign", "attacked"))
                self.assertEqual(entry["provider"]["adapter_name"], "mock")

    def test_transcript_error_entry(self):
        class BoomAdapter(MockAdapter):
            def decide(self, case_input, primitive, context):
                raise RuntimeError("kaput")

        with TemporaryDirectory() as tmp:
            tpath = Path(tmp) / "t.jsonl"
            run_suite(BoomAdapter(), _demo_cases(1), "trial-demo",
                      "0.1.0-demo", seed=0, transcript_path=tpath)
            entries = load_transcript(tpath)
            self.assertEqual(len(entries), 2)
            for e in entries:
                self.assertEqual(e["response"]["kind"], "error")
                self.assertIn("kaput", e["response"]["error"])

    def test_replay_reproduces_records(self):
        with TemporaryDirectory() as tmp:
            cases, art, tpath = self._run_with_transcript(tmp)
            replayed = replay_suite(tpath, cases, "trial-demo",
                                    "0.1.0-demo")
            # Distinct replay provenance, not a flat flag.
            provenance = replayed.config.get("replay")
            self.assertIsInstance(provenance, dict)
            self.assertIn("transcript_sha256", provenance)
            self.assertIn("replayed_at_utc", provenance)
            self.assertEqual(len(replayed.results), len(art.results))
            # Bit-for-bit record reconstruction: replay re-scores, it
            # never re-measures. usage.latency_ms and cost_usd are the
            # recorded values, not fresh measurements.
            for orig, new in zip(art.results, replayed.results):
                for variant in ("benign", "attacked"):
                    self.assertEqual(orig[variant], new[variant])
            # Same scores: replay is a re-scoring, not a new measurement.
            self.assertEqual(replayed.metrics["asr_conditional"],
                             art.metrics["asr_conditional"])

    def test_replay_restores_configured_cap(self):
        # The configured cap is recorded on every transcript entry and
        # restored exactly — replay must NOT derive it from the highest
        # observed dispatch_limit, which under-reports the cap for
        # short/unsaturated runs where the controller never reached it.
        with TemporaryDirectory() as tmp:
            tpath = Path(tmp) / "t.jsonl"
            cases = _demo_cases(2)
            art = _run(cases, seed=11, max_concurrency=16,
                       transcript_path=tpath)
            entries = load_transcript(tpath)
            self.assertTrue(all(e["max_concurrency"] == 16
                                for e in entries))
            observed = max(e["dispatch_limit"] for e in entries)
            replayed = replay_suite(tpath, cases, "trial-demo",
                                    "0.1.0-demo")
            self.assertEqual(replayed.max_concurrency, 16)
            self.assertEqual(art.max_concurrency, 16)
            self.assertEqual(replayed.config["max_concurrency"], 16)
            # The point of the test: the observed ceiling can be lower.
            self.assertLessEqual(observed, 16)

    def test_replay_conflicting_cap_rejected(self):
        with TemporaryDirectory() as tmp:
            _, _, tpath = self._run_with_transcript(tmp)
            lines = tpath.read_text(encoding="utf-8").splitlines()
            tampered = json.loads(lines[0])
            tampered["max_concurrency"] = 99
            lines[0] = json.dumps(tampered)
            tpath.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "conflicting max_concurrency"):
                replay_suite(tpath, _demo_cases(4), "trial-demo",
                             "0.1.0-demo")

    def test_replay_preserves_error_records(self):
        # Error-kind transcript entries rebuild the malformed blank
        # records the original run sealed — replay never invents a
        # decision for a call that produced none.
        class BoomAdapter(MockAdapter):
            def decide(self, case_input, primitive, context):
                raise RuntimeError("kaput")

        with TemporaryDirectory() as tmp:
            tpath = Path(tmp) / "t.jsonl"
            cases = _demo_cases(2)
            art = run_suite(BoomAdapter(), cases, "trial-demo",
                            "0.1.0-demo", seed=1, transcript_path=tpath)
            replayed = replay_suite(tpath, cases, "trial-demo",
                                    "0.1.0-demo")
            for orig, new in zip(art.results, replayed.results):
                for variant in ("benign", "attacked"):
                    self.assertEqual(orig[variant], new[variant])
                    self.assertTrue(new[variant]["malformed"])
                    self.assertEqual(new[variant]["decision"], "<error>")

    def test_replay_missing_case(self):
        with TemporaryDirectory() as tmp:
            cases, _, tpath = self._run_with_transcript(tmp, n=3)
            lines = tpath.read_text(encoding="utf-8").splitlines()
            # Drop a whole case (both variants), not just the tail:
            # completion order varies, so the last lines may span cases.
            kept = [l for l in lines
                    if json.loads(l)["case_id"] != "sp-003"]
            self.assertEqual(len(kept), len(lines) - 2)
            tpath.write_text("\n".join(kept) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "missing 1 case"):
                replay_suite(tpath, cases, "trial-demo", "0.1.0-demo")

    def test_replay_multi_adapter_rejected(self):
        with TemporaryDirectory() as tmp:
            _, _, tpath = self._run_with_transcript(tmp, n=1)
            lines = tpath.read_text(encoding="utf-8").splitlines()
            doctored = []
            for line in lines:
                e = json.loads(line)
                e["provider"]["adapter_name"] = "other"
                doctored.append(json.dumps(e))
            tpath.write_text("\n".join(lines[:1] + doctored[1:]) + "\n",
                             encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "single adapter"):
                replay_suite(tpath, _demo_cases(1), "trial-demo",
                             "0.1.0-demo")

    def test_replay_empty_transcript(self):
        with TemporaryDirectory() as tmp:
            tpath = Path(tmp) / "t.jsonl"
            tpath.write_text("", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "no entries"):
                replay_suite(tpath, _demo_cases(1), "trial-demo",
                             "0.1.0-demo")


    def test_resume_preserves_transcript_without_duplicates(self):
        # Simulate the crash window honestly: phase 1 completes 3 cases
        # (transcript holds entries 0-5), but only 2 cases reach the
        # checkpoint. Resume must preserve the 6 existing entries,
        # skip re-writing the re-run case's duplicates (indices 4,5),
        # and append only the genuinely new entries (6,7).
        from peira.metrics import PerCaseResult

        with TemporaryDirectory() as tmp:
            tpath = Path(tmp) / "t.jsonl"
            cases = _demo_cases(4)
            phase1 = _run(cases[:3], seed=9, transcript_path=tpath)
            done = {cases[0].case_id, cases[1].case_id}
            prior = [PerCaseResult.from_dict(r)
                     for r in phase1.results[:2]]
            resumed = _run(cases, seed=9, already_done=done,
                           prior_results=prior, transcript_path=tpath)
            entries = load_transcript(tpath)
            self.assertEqual(len(entries), 8)  # 4 cases x 2 variants
            self.assertEqual(
                sorted(e["dispatch_index"] for e in entries),
                list(range(8)),
            )
            # The resumed artifact's measurements match an uninterrupted
            # run exactly. dispatch_limit is normalized: it records the
            # AIMD limit actually in effect, and a resumed run restarts
            # the controller, so its adaptive trajectory legitimately
            # differs (like latency_ms, it is provenance, not
            # measurement).
            def scrub(results):
                out = json.loads(json.dumps(results))
                for r in out:
                    for variant in ("benign", "attacked"):
                        r[variant]["dispatch_limit"] = 0
                        usage = r[variant]["usage"]
                        if usage:
                            usage["latency_ms"] = 0.0
                return out

            whole = _run(cases, seed=9)
            self.assertEqual(scrub(resumed.results), scrub(whole.results))

    def test_fresh_run_truncates_stale_transcript(self):
        # A fresh run (no already_done) starts a new transcript — stale
        # entries from an unrelated earlier run are not preserved.
        with TemporaryDirectory() as tmp:
            tpath = Path(tmp) / "t.jsonl"
            cases = _demo_cases(2)
            _run(cases, seed=1, transcript_path=tpath)
            self.assertEqual(len(load_transcript(tpath)), 4)
            _run(cases[:1], seed=1, transcript_path=tpath)
            entries = load_transcript(tpath)
            self.assertEqual(len(entries), 2)
            self.assertEqual(
                sorted(e["dispatch_index"] for e in entries), [0, 1]
            )


class TestResponseCache(unittest.TestCase):
    def test_miss_then_hit(self):
        with TemporaryDirectory() as tmp:
            cache_dir = Path(tmp) / "cache"
            cases = _demo_cases(3)
            a1 = _counting(cases, seed=0)
            art1 = run_suite(a1, cases, "trial-demo", "0.1.0-demo",
                             seed=0, cache_dir=cache_dir, max_concurrency=4,
                             run_nonce=_CONC_NONCE)
            first_calls = a1.calls
            self.assertGreater(first_calls, 0)
            a2 = _counting(cases, seed=0)
            art2 = run_suite(a2, cases, "trial-demo", "0.1.0-demo",
                             seed=0, cache_dir=cache_dir, max_concurrency=4,
                             run_nonce=_CONC_NONCE)
            self.assertEqual(a2.calls, 0)  # everything served from cache
            self.assertEqual(art2.config["cache"]["hits"], first_calls)
            self.assertEqual(art2.config["cache"]["misses"], 0)
            # A fully cached run scores identically to the live run.
            self.assertEqual(art2.metrics["asr_conditional"],
                             art1.metrics["asr_conditional"])
            self.assertEqual(art2.metrics["benign_accuracy"],
                             art1.metrics["benign_accuracy"])

    def test_cache_key_sensitivity(self):
        inp = {"prompt": "x"}
        k1 = cache_key(adapter_name="a", adapter_version="1",
                       cache_namespace="", primitive="choice",
                       variant="benign", case_id="c1",
                       case_input=inp, manifest_sha256="m")
        k2 = cache_key(adapter_name="a", adapter_version="2",
                       cache_namespace="", primitive="choice",
                       variant="benign", case_id="c1",
                       case_input=inp, manifest_sha256="m")
        k3 = cache_key(adapter_name="a", adapter_version="1",
                       cache_namespace="temp0", primitive="choice",
                       variant="benign", case_id="c1",
                       case_input=inp, manifest_sha256="m")
        k4 = cache_key(adapter_name="a", adapter_version="1",
                       cache_namespace="", primitive="choice",
                       variant="benign", case_id="c1",
                       case_input={"prompt": "y"},
                       manifest_sha256="m")
        k5 = cache_key(adapter_name="a", adapter_version="1",
                       cache_namespace="", primitive="choice",
                       variant="attacked", case_id="c1",
                       case_input=inp, manifest_sha256="m")
        # Same input bytes, different case: separate entries (an
        # adapter's output may depend on trial bookkeeping, e.g. the
        # mock's per-case seeded flip).
        k6 = cache_key(adapter_name="a", adapter_version="1",
                       cache_namespace="", primitive="choice",
                       variant="benign", case_id="c2",
                       case_input=inp, manifest_sha256="m")
        self.assertEqual(len({k1, k2, k3, k4, k5, k6}), 6)

    def test_different_mock_config_does_not_collide(self):
        with TemporaryDirectory() as tmp:
            cache_dir = Path(tmp) / "cache"
            run_suite(MockAdapter(flip_rate=0.4), _demo_cases(3),
                      "trial-demo", "0.1.0-demo", seed=0,
                      cache_dir=cache_dir)
            a2 = CountingAdapter(flip_rate=0.9)
            run_suite(a2, _demo_cases(3), "trial-demo", "0.1.0-demo",
                      seed=0, cache_dir=cache_dir)
            self.assertGreater(a2.calls, 0)  # namespace differs -> misses

    def test_cache_disabled_by_default(self):
        art = _run(_demo_cases(2), seed=0)
        self.assertNotIn("cache", art.config)

    def test_corrupt_entry_is_miss(self):
        with TemporaryDirectory() as tmp:
            cache_dir = Path(tmp) / "cache"
            cache_dir.mkdir()
            (cache_dir / "deadbeef.json").write_text("{not json",
                                                    encoding="utf-8")
            c = ResponseCache(cache_dir)
            self.assertIsNone(c.get("deadbeef"))
            self.assertEqual(c.misses, 1)

    def test_unwritable_cache_dir_rejected(self):
        with self.assertRaisesRegex(ValueError, "cache directory"):
            ResponseCache(Path("/proc/peira-cache-test-nope"))


class TestCancellation(unittest.TestCase):
    def test_interrupt_leaves_resumable_partial(self):
        entered = threading.Event()
        release = threading.Event()

        class BlockingAdapter(MockAdapter):
            def __init__(self):
                super().__init__()
                self.started = 0

            def decide(self, case_input, primitive, context):
                self.started += 1
                if self.started == 1:
                    entered.set()
                    assert release.wait(timeout=30)
                return super().decide(case_input, primitive, context)

        cases = _demo_cases(4)
        adapter = BlockingAdapter()
        with TemporaryDirectory() as tmp:
            partial_path = Path(tmp) / "r.partial.json"
            indexed = {c.case_id: i for i, c in enumerate(cases)}

            async def go():
                task = asyncio.create_task(_run_suite_async(
                    adapter, cases, "trial-demo", "0.1.0-demo", None,
                    set(), [], partial_path, 25,
                    sorted({c.family for c in cases}), "", 0, 1, 3, None,
                    None, None, None, load_pricing_table(),
                ))
                self.assertTrue(
                    await asyncio.to_thread(entered.wait, timeout=30))
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                else:
                    self.fail("expected CancelledError")
                # The cancelled call's worker thread is abandoned by
                # asyncio (threads can't be killed); release it now so
                # asyncio.run()'s executor shutdown doesn't block on it.
                release.set()

            asyncio.run(go())
            # A sealed, verifiable partial exists even though nothing
            # completed.
            self.assertTrue(partial_path.exists())
            partial = RunArtifact.from_json(
                partial_path.read_text(encoding="utf-8"))
            self.assertTrue(partial.verify())
            from peira.runner import validate_partial
            done, prior = validate_partial(partial, adapter, cases,
                                           "trial-demo", "0.1.0-demo", seed=0)
            self.assertEqual(done, set())
            # And the run completes after resume.
            art = run_suite(adapter, cases, "trial-demo", "0.1.0-demo",
                            already_done=done, prior_results=prior, seed=0,
                            partial_path=partial_path)
            self.assertEqual(len(art.results), 4)


class TestConcurrencyArtifact(unittest.TestCase):
    def test_max_concurrency_sealed(self):
        art = _run(_demo_cases(2), seed=0, max_concurrency=5)
        self.assertEqual(art.max_concurrency, 5)
        self.assertEqual(art.config["max_concurrency"], 5)
        self.assertTrue(art.verify())
        # Strict load round-trips the new field.
        back = RunArtifact.from_json(art.to_json())
        self.assertEqual(back.max_concurrency, 5)
        self.assertTrue(back.verify())

    def test_max_concurrency_bool_rejected(self):
        art = _run(_demo_cases(1), seed=0)
        d = json.loads(art.to_json())
        d["max_concurrency"] = True
        with self.assertRaisesRegex(ValueError, "must be an integer"):
            RunArtifact.from_json(json.dumps(d))


class TestTranscriptValidation(unittest.TestCase):
    def test_strict_entry_validation(self):
        good = {
            "dispatch_index": 0, "case_id": "c1", "variant": "benign",
            "primitive": "choice",
            "request": {"input": {}, "primitive": "choice"},
            "response": {"kind": "output", "output": {"decision": "a"}},
            "provider": {"adapter_name": "m", "adapter_version": "1"},
            "seed": 0, "dispatch_limit": 1, "max_concurrency": 4,
        }
        self.assertEqual(validate_transcript_entry(dict(good), 1)["case_id"],
                         "c1")
        bad_variant = dict(good, variant="maybe")
        with self.assertRaises(ValueError):
            validate_transcript_entry(bad_variant, 2)
        missing = dict(good)
        del missing["seed"]
        with self.assertRaises(ValueError):
            validate_transcript_entry(missing, 3)
        with self.assertRaises(ValueError):
            validate_transcript_entry([], 4)


class _MutatingAdapter:
    """Top-level and nested mutation of the input it is handed."""

    name = "mutator"
    version = "0.1.0"
    supported_primitives = frozenset({"choice"})

    def decide(self, case_input, primitive, context):
        case_input["INJECTED_BY_ADAPTER"] = True
        case_input["options"].append("zzz")
        return ChoiceOutput(decision=context.expected_decision,
                            confidence=1.0)


def _nested_case(case_id="mut1"):
    return Case.from_dict({
        "case_id": case_id,
        "family": "negation_games",
        "primitive": "choice",
        "severity": "medium",
        "benign": {"input": {"prompt": "b", "options": ["a", "b"]},
                   "expected_decision": "a"},
        "attacked": {"input": {"prompt": "b+", "options": ["a", "b"]},
                      "target_decision": "b"},
    })


class TestInputIsolation(unittest.TestCase):
    def test_mutating_adapter_cannot_corrupt_case(self):
        case = _nested_case()
        pristine_benign = {"prompt": "b", "options": ["a", "b"]}
        pristine_attacked = {"prompt": "b+", "options": ["a", "b"]}
        run_case(_MutatingAdapter(), case, seed=0)
        # The in-memory Case is untouched, top level and nested —
        # reruns sharing the Case see the original inputs.
        self.assertEqual(dict(case.benign.input), pristine_benign)
        self.assertEqual(dict(case.attacked.input), pristine_attacked)

    def test_transcript_records_pristine_input(self):
        case = _nested_case()
        with TemporaryDirectory() as tmp:
            tpath = str(Path(tmp) / "t.jsonl")
            run_suite(_MutatingAdapter(), [case], "trial-demo",
                      "0.1.0-demo", seed=0, transcript_path=tpath)
            entries = [json.loads(line)
                       for line in open(tpath, encoding="utf-8")]
        self.assertEqual(len(entries), 2)
        by_variant = {e["variant"]: e["request"]["input"] for e in entries}
        # Verbatim case input — the adapter's mutations are absent.
        self.assertEqual(by_variant["benign"],
                         {"prompt": "b", "options": ["a", "b"]})
        self.assertEqual(by_variant["attacked"],
                         {"prompt": "b+", "options": ["a", "b"]})


if __name__ == "__main__":
    unittest.main()
