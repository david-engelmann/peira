"""Tests for restart-surviving seal checkpointing.

Covers :mod:`peira.seal_checkpoint`, the ``checkpoint_dir``
parameter on :func:`peira.metrics.summarize` /
:func:`peira.runner._summarize_artifact`, and the
``seal_checkpoint_dir`` snapshot machinery on
:func:`peira.runner.run_suite`. Three properties, each able to
fail for a real reason:

1. Exactness: the checkpointed path returns bit-identical results
   to the monolithic path, per primitive and for full summaries.
   A single divergent RNG draw anywhere fails these.
2. Kill/resume: a summarize killed mid-bootstrap resumes from the
   sidecar, executes strictly fewer bootstrap reps than a fresh
   run (banked work is reused, not recomputed), and lands on the
   monolithic summary exactly.
3. Default-off: without the opt-in (or with the
   ``PEIRA_SEAL_MONOLITHIC`` kill switch set), no checkpoint
   files are written and behaviour is unchanged.
"""

import json
import os
import random
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from peira import eb_analysis, metrics, runner, seal_checkpoint
from peira.adapters.base import CallUsage
from peira.adapters.mock import MockAdapter
from peira.metrics import CallRecord, PerCaseResult
from peira.schema import AttackedVariant, BenignVariant, Case


def _rec(decision="approve", confidence=0.9, tokens_out=None):
    usage = None
    if tokens_out is not None:
        usage = CallUsage(
            model="m", tokens_in=100, tokens_out=tokens_out,
            latency_ms=5.0, cost_usd=0.001,
        )
    return CallRecord(
        decision=decision, confidence=confidence, abstained=False,
        refusal_reason="", usage=usage, seed=0, dispatch_index=0,
        malformed=False,
    )


def _result(case_id, family, flipped, conf_b, conf_a, tok_b, tok_a,
            severity="high"):
    return PerCaseResult(
        case_id=case_id, family=family, severity=severity,
        primitive="choice",
        benign=_rec("approve", conf_b, tok_b),
        attacked=_rec("deny" if flipped else "approve", conf_a, tok_a),
        flipped=flipped, eligible=True, ineligibility_reason="",
    )


def _population(per_family=40, families=("fam0", "fam1"), seed=7):
    """Deterministic varied population: flips, confidences,
    severities, and attacked/benign token lengths all vary, so the
    summary's bootstrap paths (paired deltas, case CIs, and the EB
    length diagnostics, which need >= 30 length cases per family)
    genuinely engage."""
    rng = random.Random(seed)
    out = []
    for fam in families:
        for i in range(per_family):
            flipped = rng.random() < 0.3
            tok_b = rng.randrange(50, 400)
            tok_a = tok_b + rng.randrange(-30, 220 if flipped else 60)
            out.append(_result(
                f"{fam}-{i}", fam, flipped,
                round(rng.uniform(0.55, 0.99), 3),
                round(rng.uniform(0.5, 0.99), 3),
                tok_b, max(1, tok_a),
                severity=rng.choice(
                    ["critical", "high", "medium", "low"]),
            ))
    return out


class _ChunkSecondsZero:
    """Force a checkpoint save every 16 reps for the test's duration."""

    def __enter__(self):
        self._old = seal_checkpoint._CHUNK_SECONDS
        seal_checkpoint._CHUNK_SECONDS = 0.0
        return self

    def __exit__(self, *exc):
        seal_checkpoint._CHUNK_SECONDS = self._old
        return False


def _fresh_store(tmp):
    return seal_checkpoint.SealCheckpointStore(
        Path(tmp) / seal_checkpoint.SIDECAR_FILENAME, "test-run-fp"
    )


class TestPrimitiveExactness(unittest.TestCase):
    """Each checkpointed wrapper must equal its original exactly,
    with chunk boundaries every 16 reps (maximally fragmented)."""

    def _check(self, tmp, original, wrapped_call):
        expected = original()
        store = _fresh_store(tmp)
        with _ChunkSecondsZero(), \
                seal_checkpoint.seal_checkpoints(store):
            got = wrapped_call()
        self.assertEqual(got, expected)
        # The wrapper must actually have run: a silently
        # uninstalled wrapper would compare the original against
        # itself and pass vacuously. Every primitive banks a done
        # entry for its call (length_confound_diagnostics banks
        # done entries for its tail slope calls).
        self.assertTrue(
            (Path(tmp) / seal_checkpoint.SIDECAR_FILENAME).exists(),
            "checkpointed call wrote no sidecar",
        )
        self.assertTrue(
            any(
                isinstance(e, dict) and e.get("done")
                for e in store._calls.values()
            ),
            "checkpointed call banked no done entry in the sidecar",
        )

    def test_paired_bootstrap_ci(self):
        xs = [float((i * 7) % 13) / 4 for i in range(40)]
        ys = [float((i * 5) % 11) / 4 for i in range(40)]
        with tempfile.TemporaryDirectory() as tmp:
            self._check(
                tmp,
                lambda: metrics.paired_bootstrap_ci(
                    xs, ys, n_boot=500, seed=3),
                lambda: metrics.paired_bootstrap_ci(
                    xs, ys, n_boot=500, seed=3),
            )

    def test_unpaired_bootstrap_ci(self):
        xs = [float((i * 3) % 7) / 2 for i in range(30)]
        ys = [float((i * 2) % 5) / 2 for i in range(45)]
        with tempfile.TemporaryDirectory() as tmp:
            self._check(
                tmp,
                lambda: metrics._unpaired_bootstrap_ci(
                    xs, ys, n_boot=500, seed=4),
                lambda: metrics._unpaired_bootstrap_ci(
                    xs, ys, n_boot=500, seed=4),
            )

    def test_paired_bootstrap_se(self):
        xs = [float((i * 7) % 13) / 4 for i in range(40)]
        ys = [float((i * 5) % 11) / 4 for i in range(40)]
        with tempfile.TemporaryDirectory() as tmp:
            self._check(
                tmp,
                lambda: metrics.paired_bootstrap_se(
                    xs, ys, n_boot=500, seed=5),
                lambda: metrics.paired_bootstrap_se(
                    xs, ys, n_boot=500, seed=5),
            )

    def test_paired_bootstrap_weighted_ci_with_degenerate_redraws(self):
        # Sparse weights: most resamples draw only zero-weight
        # indices on some draws, so the redraw loop consumes a
        # variable number of RNG draws per rep. The checkpointed
        # wrapper must reproduce that stream exactly.
        n = 40
        xs = [float(i % 9) / 3 for i in range(n)]
        ys = [float(i % 7) / 3 for i in range(n)]
        w = [0.0] * n
        w[3] = 1.0
        w[17] = 2.0
        w[29] = 0.5
        with tempfile.TemporaryDirectory() as tmp:
            self._check(
                tmp,
                lambda: metrics.paired_bootstrap_weighted_ci(
                    w, xs, w, ys, n_boot=300, seed=6),
                lambda: metrics.paired_bootstrap_weighted_ci(
                    w, xs, w, ys, n_boot=300, seed=6),
            )

    def test_bootstrap_case_ci_floats(self):
        items = [float((i * 11) % 17) / 5 for i in range(35)]
        stat = lambda xs: sum(xs) / len(xs)  # noqa: E731
        with tempfile.TemporaryDirectory() as tmp:
            self._check(
                tmp,
                lambda: metrics._bootstrap_case_ci(
                    items, stat, 400, 8),
                lambda: metrics._bootstrap_case_ci(
                    items, stat, 400, 8),
            )

    def test_bootstrap_case_ci_results(self):
        items = _population(per_family=20, families=("fam0",))
        stat = lambda rs: sum(1 for r in rs if r.flipped) / len(rs)  # noqa: E731
        with tempfile.TemporaryDirectory() as tmp:
            self._check(
                tmp,
                lambda: metrics._bootstrap_case_ci(
                    items, stat, 400, 9),
                lambda: metrics._bootstrap_case_ci(
                    items, stat, 400, 9),
            )

    def test_slope_ci(self):
        xs = [float(20 + (i * 37) % 300) for i in range(40)]
        ys = [1 if (i * 37) % 300 > 150 else 0 for i in range(40)]
        with tempfile.TemporaryDirectory() as tmp:
            self._check(
                tmp,
                lambda: eb_analysis._slope_ci(xs, ys, 300, 10),
                lambda: eb_analysis._slope_ci(xs, ys, 300, 10),
            )

    def test_adjusted_slope_ci(self):
        xs_len = [float(20 + (i * 37) % 300) for i in range(40)]
        xs_delta = [float((i * 13) % 80 - 20) for i in range(40)]
        ys = [1 if (i * 37) % 300 > 150 else 0 for i in range(40)]
        with tempfile.TemporaryDirectory() as tmp:
            self._check(
                tmp,
                lambda: eb_analysis._adjusted_slope_ci(
                    xs_len, xs_delta, ys, 300, 11),
                lambda: eb_analysis._adjusted_slope_ci(
                    xs_len, xs_delta, ys, 300, 11),
            )

    def test_length_confound_diagnostics(self):
        # One family with >= MIN_OBSERVATIONS length cases per
        # predictor, so the coupled single-stream loop runs.
        results = _population(per_family=40, families=("fam0",))
        with tempfile.TemporaryDirectory() as tmp:
            self._check(
                tmp,
                lambda: eb_analysis.length_confound_diagnostics(
                    results, n_boot=300, seed=12),
                lambda: eb_analysis.length_confound_diagnostics(
                    results, n_boot=300, seed=12),
            )


class TestChunkSecondsParse(unittest.TestCase):
    def test_invalid_negative_and_nonfinite_fall_back(self):
        for raw in ("abc", "-1", "-0.5", "inf", "-inf", "nan", ""):
            with self.subTest(raw=raw), mock.patch.dict(
                os.environ,
                {seal_checkpoint.CHUNK_SECONDS_ENV: raw},
            ):
                self.assertEqual(
                    seal_checkpoint._read_chunk_seconds(), 45.0)

    def test_valid_values_parse(self):
        for raw, want in (("2.5", 2.5), ("0", 0.0), ("45", 45.0)):
            with self.subTest(raw=raw), mock.patch.dict(
                os.environ,
                {seal_checkpoint.CHUNK_SECONDS_ENV: raw},
            ):
                self.assertEqual(
                    seal_checkpoint._read_chunk_seconds(), want)

    def test_unset_falls_back(self):
        env = dict(os.environ)
        env.pop(seal_checkpoint.CHUNK_SECONDS_ENV, None)
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(
                seal_checkpoint._read_chunk_seconds(), 45.0)


class TestFlushRetry(unittest.TestCase):
    def test_flush_succeeds_after_injected_permission_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _fresh_store(tmp)
            orig_write = Path.write_text
            attempts = [0]

            def flaky(self_path, *a, **k):
                attempts[0] += 1
                if attempts[0] <= 3:
                    raise PermissionError("injected EPERM burst")
                return orig_write(self_path, *a, **k)

            begun = store.begin("flush-probe-fp", 0)
            self.assertEqual(begun[0], "run")
            with mock.patch.object(Path, "write_text", flaky):
                store.finish(1.5, "float")
            self.assertEqual(attempts[0], 4)
            calls = json.loads(
                (Path(tmp) / seal_checkpoint.SIDECAR_FILENAME)
                .read_text(encoding="utf-8"))["calls"]
            self.assertTrue(
                any(e.get("done") for e in calls.values()))


class TestLengthConfoundKillResume(unittest.TestCase):
    def test_kill_mid_coupled_loop_resumes_to_monolithic(self):
        results = _population(per_family=40, families=("fam0",))
        expected = eb_analysis.length_confound_diagnostics(
            results, n_boot=300, seed=12)
        with tempfile.TemporaryDirectory() as tmp:
            orig_flush = seal_checkpoint.SealCheckpointStore._flush
            flushes = [0]

            def bomb(self):
                flushes[0] += 1
                if flushes[0] > 3:
                    raise _SimulatedKill()
                return orig_flush(self)

            with _ChunkSecondsZero(), mock.patch.object(
                seal_checkpoint.SealCheckpointStore, "_flush", bomb,
            ):
                with seal_checkpoint.seal_checkpoints(
                    _fresh_store(tmp)
                ):
                    with self.assertRaises(_SimulatedKill):
                        eb_analysis.length_confound_diagnostics(
                            results, n_boot=300, seed=12)
            with _ChunkSecondsZero(), seal_checkpoint.seal_checkpoints(
                _fresh_store(tmp)
            ):
                got = eb_analysis.length_confound_diagnostics(
                    results, n_boot=300, seed=12)
        self.assertEqual(got, expected)


class TestSummarizeSignatureParity(unittest.TestCase):
    def test_summarize_params_match_monolithic_except_checkpoint(self):
        import inspect

        def names_defaults(fn):
            return [
                (name, p.default)
                for name, p in
                inspect.signature(fn).parameters.items()
            ]

        wrapped = [
            pair for pair in names_defaults(metrics.summarize)
            if pair[0] != "checkpoint_dir"
        ]
        self.assertEqual(
            wrapped, names_defaults(metrics._summarize_monolithic))


class _SimulatedKill(Exception):
    """Raised by a bombed store flush to simulate process death."""


def _counting_chunk_loop(counter):
    orig = seal_checkpoint._chunk_loop

    def wrapper(store, rng, values, reps, n_boot, rep_fn):
        def counting_rep(v):
            counter[0] += 1
            rep_fn(v)

        return orig(store, rng, values, reps, n_boot, counting_rep)

    return wrapper


class TestSummarizeCheckpointing(unittest.TestCase):
    def setUp(self):
        self.pop = _population()
        self.expected = metrics.summarize(
            self.pop, n_boot=400, seed=0)

    def test_checkpointed_equals_monolithic(self):
        with tempfile.TemporaryDirectory() as tmp, _ChunkSecondsZero():
            got = metrics.summarize(
                self.pop, n_boot=400, seed=0, checkpoint_dir=tmp)
            sidecar = Path(tmp) / seal_checkpoint.SIDECAR_FILENAME
            self.assertTrue(sidecar.exists())
            calls = json.loads(
                sidecar.read_text(encoding="utf-8"))["calls"]
            self.assertTrue(
                any(e.get("done") for e in calls.values()),
                "sidecar banked no completed bootstrap calls",
            )
        self.assertEqual(got, self.expected)

    def test_kill_resume_reuses_banked_work(self):
        with tempfile.TemporaryDirectory() as dir_a, \
                tempfile.TemporaryDirectory() as dir_b, \
                _ChunkSecondsZero():
            # Fresh checkpointed run, counting executed reps.
            fresh_reps = [0]
            with mock.patch.object(
                    seal_checkpoint, "_chunk_loop",
                    _counting_chunk_loop(fresh_reps)):
                fresh = metrics.summarize(
                    self.pop, n_boot=400, seed=0, checkpoint_dir=dir_a)
            self.assertEqual(fresh, self.expected)
            self.assertGreater(fresh_reps[0], 0)

            # Killed run: the store's flush dies after 40 saves.
            # At n_boot=400 with a save every 16 reps, the first
            # bootstrap call completes in 26 flushes (25 saves + the
            # finish), so the kill lands inside the second call,
            # leaving one banked call and one partial call.
            orig_flush = seal_checkpoint.SealCheckpointStore._flush
            flushes = [0]

            def bomb(self):
                flushes[0] += 1
                if flushes[0] > 40:
                    raise _SimulatedKill()
                return orig_flush(self)

            with mock.patch.object(
                    seal_checkpoint.SealCheckpointStore, "_flush", bomb):
                with self.assertRaises(_SimulatedKill):
                    metrics.summarize(
                        self.pop, n_boot=400, seed=0,
                        checkpoint_dir=dir_b)
            sidecar = Path(dir_b) / seal_checkpoint.SIDECAR_FILENAME
            calls = json.loads(
                sidecar.read_text(encoding="utf-8"))["calls"]
            self.assertTrue(
                any(e.get("done") for e in calls.values()),
                "kill left no completed calls banked",
            )
            self.assertTrue(
                any(not e.get("done") and "values" in e
                    for e in calls.values()),
                "kill left no partial call to resume",
            )

            # Resume: same inputs, same directory. Must land on the
            # monolithic summary having executed strictly fewer reps
            # than the fresh run (banked calls replay from cache).
            resumed_reps = [0]
            with mock.patch.object(
                    seal_checkpoint, "_chunk_loop",
                    _counting_chunk_loop(resumed_reps)):
                resumed = metrics.summarize(
                    self.pop, n_boot=400, seed=0, checkpoint_dir=dir_b)
            self.assertEqual(resumed, self.expected)
            self.assertLess(resumed_reps[0], fresh_reps[0])

    def test_sidecar_for_other_inputs_is_ignored(self):
        other = _population(seed=99)
        other_expected = metrics.summarize(other, n_boot=400, seed=0)
        self.assertNotEqual(other_expected, self.expected)
        with tempfile.TemporaryDirectory() as tmp, _ChunkSecondsZero():
            metrics.summarize(
                self.pop, n_boot=400, seed=0, checkpoint_dir=tmp)
            got = metrics.summarize(
                other, n_boot=400, seed=0, checkpoint_dir=tmp)
        self.assertEqual(got, other_expected)

    def test_default_off_constructs_no_store(self):
        with mock.patch.object(
                seal_checkpoint, "SealCheckpointStore",
                side_effect=AssertionError("store constructed")):
            got = metrics.summarize(self.pop, n_boot=100, seed=0)
        self.assertEqual(
            got, metrics.summarize(self.pop, n_boot=100, seed=0))

    def test_kill_switch_forces_monolithic_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(
                    os.environ,
                    {seal_checkpoint.KILL_SWITCH_ENV: "1"}):
            got = metrics.summarize(
                self.pop, n_boot=100, seed=0, checkpoint_dir=tmp)
            self.assertEqual(os.listdir(tmp), [])
        self.assertEqual(
            got, metrics.summarize(self.pop, n_boot=100, seed=0))


class TestMalformedSidecarEntries(unittest.TestCase):
    """Valid-JSON but malformed sidecar entries must degrade to
    a recompute, never crash the summarize."""

    def setUp(self):
        # 40 results in one family is enough to engage the
        # summary's bootstrap paths (the sidecar banks ~20 calls);
        # a smaller population is gated off most of them.
        self.pop = _population(per_family=40, families=("fam0",))
        self.expected = metrics.summarize(
            self.pop, n_boot=60, seed=0)

    def _run_with_mutation(self, mutate):
        with tempfile.TemporaryDirectory() as tmp, \
                _ChunkSecondsZero():
            metrics.summarize(
                self.pop, n_boot=60, seed=0, checkpoint_dir=tmp)
            sidecar = Path(tmp) / seal_checkpoint.SIDECAR_FILENAME
            data = json.loads(sidecar.read_text(encoding="utf-8"))
            self.assertGreater(len(data["calls"]), 10)
            mutate(data)
            sidecar.write_text(json.dumps(data), encoding="utf-8")
            got = metrics.summarize(
                self.pop, n_boot=60, seed=0, checkpoint_dir=tmp)
        self.assertEqual(got, self.expected)

    def test_non_dict_entry(self):
        def mutate(data):
            data["calls"]["0"] = 123

        self._run_with_mutation(mutate)

    def test_done_entry_without_result(self):
        def mutate(data):
            done_keys = [
                k for k, e in data["calls"].items()
                if isinstance(e, dict) and e.get("done")
            ]
            self.assertTrue(done_keys, "sidecar banked no done entry")
            del data["calls"][done_keys[0]]["result"]

        self._run_with_mutation(mutate)

    def test_partial_entry_with_truncated_rng(self):
        def mutate(data):
            fp = data["calls"]["0"]["fp"]
            data["calls"]["0"] = {
                "fp": fp, "done": False, "values": [], "reps": 0,
                "rng": [3, [1, 2], None],
            }

        self._run_with_mutation(mutate)

    def test_non_numeric_key_with_mismatch_prune(self):
        def mutate(data):
            data["calls"]["x"] = 123
            data["calls"]["0"]["fp"] = "stale-fp"

        self._run_with_mutation(mutate)


def _cases(n=6):
    return [
        Case(
            case_id=f"c{i}", family="f", primitive="choice",
            severity="high",
            benign=BenignVariant(
                input={}, expected_decision="approve"),
            attacked=AttackedVariant(input={}, target_decision=None),
        )
        for i in range(n)
    ]


_RUN_SEED = 1
_RUN_NONCE = "seal-checkpoint-test-nonce"


def _scripted_mock(cases, cls=MockAdapter):
    return cls(
        script=MockAdapter.script_for(
            cases, seed=_RUN_SEED, run_nonce=_RUN_NONCE))


class TestSweepSignatureParity(unittest.TestCase):
    """run_sweep_suite mirrors run_suite's signature (the parity
    regression in test_sweep.py): the new kwarg must exist there too.
    The sweep substitutes its own summarizer, whose summary has no
    bootstrap, so a non-None value is refused loudly instead of
    being silently ignored."""

    def test_sweep_accepts_and_refuses_checkpoint_dir(self) -> None:
        import inspect

        from peira.sweep import run_sweep_suite

        self.assertIn(
            "seal_checkpoint_dir",
            inspect.signature(run_sweep_suite).parameters,
        )
        with self.assertRaisesRegex(ValueError, "does not apply"):
            run_sweep_suite(
                None,
                [],
                "trial",
                "v2",
                [1],
                seal_checkpoint_dir="/nonexistent/ckpt",
            )

    def test_sweep_kill_switch_makes_checkpoint_dir_inert(self) -> None:
        from peira.sweep import run_sweep_suite

        # With the kill switch set the seal refusal must not fire:
        # the call proceeds to the next validation, which rejects
        # the empty budget grid with its own message.
        with mock.patch.dict(
            os.environ, {seal_checkpoint.KILL_SWITCH_ENV: "1"}
        ):
            with self.assertRaisesRegex(
                ValueError, "budget_grid must not be empty"
            ):
                run_sweep_suite(
                    None,
                    [],
                    "trial",
                    "v2",
                    [],
                    seal_checkpoint_dir="/nonexistent/ckpt",
                )


class _CountingMock(MockAdapter):
    """MockAdapter that counts its calls; used to prove a resumed
    seal dispatches nothing."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.decide_calls = 0

    def decide(self, case_input, primitive, context):
        self.decide_calls += 1
        return super().decide(case_input, primitive, context)


class TestRunnerSealCheckpointing(unittest.TestCase):
    def _run(self, adapter, cases, **kw):
        kw.setdefault("run_nonce", _RUN_NONCE)
        kw.setdefault("seed", _RUN_SEED)
        return runner.run_suite(
            adapter, cases, "trial-demo", "0.1.0-demo", **kw)

    def test_snapshot_written_and_metrics_match_monolithic(self):
        cases = _cases()
        with tempfile.TemporaryDirectory() as tmp:
            artifact = self._run(
                _scripted_mock(cases), cases,
                seal_checkpoint_dir=tmp)
            self.assertTrue(artifact.verify())
            self.assertEqual(artifact.termination, "complete")
            self.assertTrue(
                (Path(tmp) / seal_checkpoint.SNAPSHOT_FILENAME)
                .exists())
            self.assertTrue(
                (Path(tmp) / seal_checkpoint.SIDECAR_FILENAME)
                .exists())
            results = [
                PerCaseResult.from_dict(r)
                if isinstance(r, dict) else r
                for r in artifact.results
            ]
            expected = runner._summarize_artifact(
                results, ["f"], cases, _RUN_SEED,
                termination="complete")
            self.assertEqual(artifact.metrics, expected)

    def test_killed_seal_resumes_without_rerunning_cases(self):
        cases = _cases()
        with tempfile.TemporaryDirectory() as tmp:
            calls = [0]

            def bomb(*a, **k):
                calls[0] += 1
                raise RuntimeError("simulated kill mid-seal")

            with mock.patch.object(
                    runner, "_summarize_artifact", bomb):
                with self.assertRaises(RuntimeError):
                    self._run(
                        _scripted_mock(cases), cases,
                        seal_checkpoint_dir=tmp)
            self.assertEqual(calls[0], 1)
            snap_path = Path(tmp) / seal_checkpoint.SNAPSHOT_FILENAME
            self.assertTrue(snap_path.exists())

            # Second attempt: the adapter must never be called; the
            # frozen snapshot supplies every result.
            adapter = _scripted_mock(cases, cls=_CountingMock)
            artifact = self._run(adapter, cases,
                                 seal_checkpoint_dir=tmp)
            self.assertEqual(adapter.decide_calls, 0)
            self.assertTrue(artifact.verify())
            snap = runner.RunArtifact.from_json(
                snap_path.read_text(encoding="utf-8"))
            snap_results = [
                PerCaseResult.from_dict(r)
                if isinstance(r, dict) else r
                for r in snap.results
            ]
            expected = runner._summarize_artifact(
                snap_results, ["f"], cases, _RUN_SEED,
                termination="complete")
            self.assertEqual(artifact.metrics, expected)

    def test_no_checkpoint_dir_writes_no_snapshot(self):
        cases = _cases()
        plain = self._run(_scripted_mock(cases), cases)
        self.assertTrue(plain.verify())
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(
                    os.environ,
                    {seal_checkpoint.KILL_SWITCH_ENV: "1"}):
            killed = self._run(
                _scripted_mock(cases), cases,
                seal_checkpoint_dir=tmp)
            self.assertEqual(os.listdir(tmp), [])
        self.assertTrue(killed.verify())
        # Default and kill-switched seals agree on every metric the
        # seal computes. The timing_ms block is excluded from the
        # cross-run comparison because it samples live wall-clock
        # timings, which differ between any two runs; each artifact
        # is separately checked in full against the monolithic
        # summary of its own results below.
        strip = (
            lambda m: {k: v for k, v in m.items() if k != "timing_ms"})
        self.assertEqual(strip(plain.metrics), strip(killed.metrics))
        for artifact in (plain, killed):
            results = [
                PerCaseResult.from_dict(r)
                if isinstance(r, dict) else r
                for r in artifact.results
            ]
            expected = runner._summarize_artifact(
                results, ["f"], cases, _RUN_SEED,
                termination="complete")
            self.assertEqual(artifact.metrics, expected)

    def test_snapshot_from_another_run_is_rejected(self):
        cases = _cases()
        with tempfile.TemporaryDirectory() as tmp:
            self._run(
                _scripted_mock(cases), cases,
                seal_checkpoint_dir=tmp)
            with self.assertRaises(ValueError):
                self._run(
                    _scripted_mock(cases), cases, seed=99,
                    seal_checkpoint_dir=tmp)

    def test_snapshot_with_different_case_ids_is_rejected(self):
        cases = _cases()
        other = [
            Case(
                case_id=f"other{i}", family="f", primitive="choice",
                severity="high",
                benign=BenignVariant(
                    input={}, expected_decision="approve"),
                attacked=AttackedVariant(
                    input={}, target_decision=None),
            )
            for i in range(len(cases))
        ]
        with tempfile.TemporaryDirectory() as tmp:
            self._run(
                _scripted_mock(cases), cases,
                seal_checkpoint_dir=tmp)
            with self.assertRaises(ValueError):
                self._run(
                    _scripted_mock(other), other,
                    seal_checkpoint_dir=tmp)

    def test_snapshot_with_different_adapter_version_is_rejected(
            self):
        cases = _cases()
        with tempfile.TemporaryDirectory() as tmp:
            self._run(
                _scripted_mock(cases), cases,
                seal_checkpoint_dir=tmp)
            adapter = _scripted_mock(cases)
            adapter.version = "9.9.9"
            with self.assertRaises(ValueError):
                self._run(adapter, cases, seal_checkpoint_dir=tmp)

    def test_snapshot_with_different_explicit_nonce_is_rejected(
            self):
        cases = _cases()
        with tempfile.TemporaryDirectory() as tmp:
            self._run(
                _scripted_mock(cases), cases,
                seal_checkpoint_dir=tmp)
            other_nonce = "a-different-explicit-nonce"
            adapter = MockAdapter(
                script=MockAdapter.script_for(
                    cases, seed=_RUN_SEED, run_nonce=other_nonce))
            with self.assertRaises(ValueError):
                self._run(
                    adapter, cases, run_nonce=other_nonce,
                    seal_checkpoint_dir=tmp)

    def test_corrupt_snapshot_recomputes_cleanly(self):
        cases = _cases()
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / seal_checkpoint.SNAPSHOT_FILENAME).write_text(
                "this is not a sealed artifact {{{", encoding="utf-8")
            adapter = _scripted_mock(cases, cls=_CountingMock)
            artifact = self._run(
                adapter, cases, seal_checkpoint_dir=tmp)
            self.assertEqual(adapter.decide_calls, 2 * len(cases))
            self.assertTrue(artifact.verify())
            self.assertEqual(artifact.termination, "complete")

    def test_killed_seal_resume_preserves_transcript(self):
        cases = _cases()
        with tempfile.TemporaryDirectory() as tmp:
            tpath = Path(tmp) / "transcript.jsonl"
            ckpt = str(Path(tmp) / "ckpt")

            def bomb(*a, **k):
                raise RuntimeError("simulated kill mid-seal")

            with mock.patch.object(
                    runner, "_summarize_artifact", bomb):
                with self.assertRaises(RuntimeError):
                    self._run(
                        _scripted_mock(cases), cases,
                        seal_checkpoint_dir=ckpt,
                        transcript_path=tpath)
            first_entries = runner.load_transcript(tpath)
            self.assertEqual(
                len(first_entries), 2 * len(cases))
            first_bytes = tpath.read_bytes()

            adapter = _scripted_mock(cases, cls=_CountingMock)
            artifact = self._run(
                adapter, cases, seal_checkpoint_dir=ckpt,
                transcript_path=tpath)
            self.assertEqual(adapter.decide_calls, 0)
            self.assertTrue(artifact.verify())
            self.assertEqual(tpath.read_bytes(), first_bytes)
            self.assertEqual(
                runner.load_transcript(tpath), first_entries)

    def test_corrupt_snapshot_starts_transcript_fresh(self):
        cases = _cases()
        with tempfile.TemporaryDirectory() as tmp:
            tpath = Path(tmp) / "transcript.jsonl"
            tpath.write_text(
                json.dumps({"dispatch_index": 999}) + "\n",
                encoding="utf-8")
            ckpt = Path(tmp) / "ckpt"
            ckpt.mkdir()
            (ckpt / seal_checkpoint.SNAPSHOT_FILENAME).write_text(
                "garbage {{{", encoding="utf-8")
            adapter = _scripted_mock(cases, cls=_CountingMock)
            artifact = self._run(
                adapter, cases, seal_checkpoint_dir=str(ckpt),
                transcript_path=tpath)
            self.assertEqual(adapter.decide_calls, 2 * len(cases))
            self.assertTrue(artifact.verify())
            entries = runner.load_transcript(tpath)
            self.assertEqual(len(entries), 2 * len(cases))
            self.assertTrue(
                all(e["dispatch_index"] != 999 for e in entries))

    def test_identity_mismatch_leaves_transcript_unchanged(self):
        cases = _cases()
        with tempfile.TemporaryDirectory() as tmp:
            tpath = Path(tmp) / "transcript.jsonl"
            ckpt = str(Path(tmp) / "ckpt")
            self._run(
                _scripted_mock(cases), cases,
                seal_checkpoint_dir=ckpt, transcript_path=tpath)
            before = tpath.read_bytes()
            self.assertTrue(before)
            with self.assertRaises(ValueError):
                self._run(
                    _scripted_mock(cases), cases, seed=99,
                    seal_checkpoint_dir=ckpt, transcript_path=tpath)
            self.assertEqual(tpath.read_bytes(), before)

    def test_summarize_override_conflict_is_rejected(self):
        cases = _cases()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                self._run(
                    _scripted_mock(cases), cases,
                    summarize_artifact=lambda *a, **k: {},
                    seal_checkpoint_dir=tmp)


if __name__ == "__main__":
    unittest.main()
