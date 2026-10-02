"""Unit tests for runner resume validation and progress (run with: python -m pytest tests)."""

import dataclasses
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from peira.adapters.base import ChoiceOutput, ProviderError, ScoreOutput, CallContext
from peira.adapters.mock import MockAdapter
from peira.artifacts import (
    RunArtifact,
    error_log_from_results,
    results_to_dicts,
)
from peira.metrics import CallRecord, PerCaseResult
from peira.pricing import load_pricing_table
from peira.runner import (
    _TrialInfo,
    _completion_hash,
    _content_hash,
    _record_from_transcript_entry,
    _record_from_transcript_entry_py,
    _replay_call_sidecars,
    _transcript_entry,
    _v3_artifact_blocks,
    _validate_and_record,
    load_cases,
    replay_suite,
    run_suite,
    validate_partial,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _rec(**kw):
    base = dict(decision="approve", confidence=0.9, abstained=False,
                refusal_reason="", usage=None, seed=0, dispatch_index=0,
                malformed=False)
    base.update(kw)
    return CallRecord(**base)


def _r(case_id="c1", **kw):
    benign_kw = {k[7:]: v for k, v in kw.items() if k.startswith("benign_")}
    attacked_kw = {k[9:]: v for k, v in kw.items() if k.startswith("attacked_")}
    rest = {k: v for k, v in kw.items()
            if not (k.startswith("benign_") or k.startswith("attacked_"))}
    base = dict(case_id=case_id, family="f", severity="high",
                primitive="choice",
                benign=_rec(**benign_kw), attacked=_rec(**attacked_kw),
                flipped=False, eligible=True, ineligibility_reason="")
    base.update(rest)
    return PerCaseResult(**base)


def _partial(results, adapter=None, suite="trial-demo",
             dataset_version="0.1.0-demo"):
    adapter = adapter or MockAdapter()
    return RunArtifact(
        adapter_name=adapter.name,
        adapter_version=getattr(adapter, "version", ""),
        suite=suite,
        dataset_version=dataset_version,
        config={"cache_enabled": False},
        pricing_version=load_pricing_table().get("pricing_version", ""),
        results=results_to_dicts(results),
    ).seal()


def _cases(*ids):
    return [SimpleNamespace(case_id=i) for i in ids]


class TestValidatePartial(unittest.TestCase):
    def test_ok(self):
        p = _partial([_r("c1"), _r("c2")])
        done, prior = validate_partial(p, MockAdapter(), _cases("c1", "c2", "c3"),
                                       "trial-demo", "0.1.0-demo")
        self.assertEqual(done, {"c1", "c2"})
        self.assertEqual([r.case_id for r in prior], ["c1", "c2"])

    def test_wrong_adapter(self):
        p = _partial([_r("c1")])
        other = SimpleNamespace(name="other", version="9.9")
        with self.assertRaises(ValueError):
            validate_partial(p, other, _cases("c1"), "trial-demo", "0.1.0-demo")

    def test_wrong_adapter_version(self):
        p = _partial([_r("c1")])
        other = SimpleNamespace(name=MockAdapter().name, version="9.9")
        with self.assertRaises(ValueError):
            validate_partial(p, other, _cases("c1"), "trial-demo", "0.1.0-demo")

    def test_wrong_suite(self):
        p = _partial([_r("c1")], suite="trial")
        with self.assertRaises(ValueError):
            validate_partial(p, MockAdapter(), _cases("c1"),
                             "trial-demo", "0.1.0-demo")

    def test_wrong_dataset_version(self):
        p = _partial([_r("c1")], dataset_version="9.9")
        with self.assertRaises(ValueError):
            validate_partial(p, MockAdapter(), _cases("c1"),
                             "trial-demo", "0.1.0-demo")

    def test_tampered_lock(self):
        p = _partial([_r("c1")])
        p.results[0]["flipped"] = True  # modify after sealing
        with self.assertRaises(ValueError):
            validate_partial(p, MockAdapter(), _cases("c1"),
                             "trial-demo", "0.1.0-demo")

    def test_unknown_case_id(self):
        p = _partial([_r("zzz")])
        with self.assertRaises(ValueError):
            validate_partial(p, MockAdapter(), _cases("c1"),
                             "trial-demo", "0.1.0-demo")

    def test_duplicate_case_id(self):
        p = _partial([_r("c1"), _r("c1")])
        with self.assertRaises(ValueError):
            validate_partial(p, MockAdapter(), _cases("c1"),
                             "trial-demo", "0.1.0-demo")

    def test_scalar_result_entry_is_value_error(self):
        # A hand-edited partial with a scalar entry used to die in
        # AttributeError on r.get; it is now a clear ValueError.
        p = _partial([_r("c1")])
        p.results.append("bogus")
        p.seal()  # re-seal so the lock passes and the entry is reached
        with self.assertRaisesRegex(
            ValueError, "partial run has malformed result entry at index 1"
        ):
            validate_partial(p, MockAdapter(), _cases("c1"),
                             "trial-demo", "0.1.0-demo")

    def test_wrong_shaped_result_dict_is_value_error(self):
        # A dict entry that PerCaseResult rejects is hostile input too:
        # TypeError becomes ValueError with the entry's position.
        p = _partial([_r("c1")])
        p.results.append({"case_id": "c2", "bogus_key": 1})
        p.seal()
        with self.assertRaisesRegex(
            ValueError, "partial run has malformed result entry at index 1"
        ):
            validate_partial(p, MockAdapter(), _cases("c1", "c2"),
                             "trial-demo", "0.1.0-demo")

    def test_seed_mismatch_rejected(self):
        # Resume with a different seed would silently re-score nothing
        # (dispatch indices and per-call seeds are seed-derived): the
        # partial is rejected with a clear message instead.
        p = _partial([_r("c1")])
        p.seed = 7
        p.seal()
        with self.assertRaisesRegex(ValueError, "recorded with seed 7"):
            validate_partial(p, MockAdapter(), _cases("c1", "c2"),
                             "trial-demo", "0.1.0-demo", seed=8)
        # Same seed resumes fine.
        done, prior = validate_partial(
            p, MockAdapter(), _cases("c1", "c2"),
            "trial-demo", "0.1.0-demo", seed=7)
        self.assertEqual(done, {"c1"})


class TestResumeProgress(unittest.TestCase):
    def test_progress_counts_completed_not_index(self):
        cases = load_cases(REPO_ROOT / "dataset" / "trial-demo")
        done_ids = {cases[0].case_id}
        seen = []
        run_suite(MockAdapter(), cases, "trial-demo", "0.1.0-demo",
                  progress=lambda d, t: seen.append((d, t)),
                  already_done=done_ids)
        total = len(cases)
        # One case skipped: progress must run 1..total-1, not jump the index.
        self.assertEqual([d for d, _ in seen], list(range(1, total)))
        self.assertTrue(all(t == total for _, t in seen))

    def test_dispatch_indices_are_suite_positioned_across_resume(self):
        # Dispatch indices derive from the case's suite position
        # (benign = 2i, attacked = 2i+1), not run order: a resumed run
        # must record the same indices as an uninterrupted one.
        from peira.runner import run_case

        cases = load_cases(REPO_ROOT / "dataset" / "trial-demo")
        half = len(cases) // 2
        adapter = MockAdapter()
        prior = [run_case(adapter, cases[i], seed=3, dispatch_base=2 * i)
                 for i in range(half)]
        resumed = run_suite(
            adapter, cases, "trial-demo", "0.1.0-demo",
            already_done={cases[i].case_id for i in range(half)},
            prior_results=prior,
            seed=3,
        )
        self.assertEqual(len(resumed.results), len(cases))
        for i, entry in enumerate(resumed.results):
            self.assertEqual(entry["benign"]["dispatch_index"], 2 * i,
                             f"case {i} benign index")
            self.assertEqual(entry["attacked"]["dispatch_index"], 2 * i + 1,
                             f"case {i} attacked index")
            self.assertEqual(entry["benign"]["seed"], 3)
            self.assertEqual(entry["attacked"]["seed"], 3)


class TestScorePlumbing(unittest.TestCase):
    """A3 S6: the score signal survives record/transcript/artifact."""

    def test_score_output_recorded(self):
        out = ScoreOutput(score=0.73, decision="pay")
        rec = _validate_and_record(out, [], 1.0, 0, 0, {}, 1)
        self.assertEqual(rec.score, 0.73)

    def test_choice_output_score_none(self):
        out = ChoiceOutput(decision="pay")
        rec = _validate_and_record(out, [], 1.0, 0, 0, {}, 1)
        self.assertIsNone(rec.score)

    def test_error_record_score_none(self):
        rec = _validate_and_record(None, ["adapter raised"], 1.0, 0, 0,
                                  {}, 1)
        self.assertIsNone(rec.score)

    def test_score_round_trips_record_dict(self):
        rec = _rec(score=0.42)
        d = dataclasses.asdict(rec)  # what the artifact seals
        self.assertEqual(d["score"], 0.42)
        self.assertEqual(CallRecord.from_dict(d).score, 0.42)

    def test_score_absent_in_old_dicts(self):
        # Artifacts sealed before S6 have no "score" key: from_dict
        # must not break on them.
        rec = _rec()
        d = dataclasses.asdict(rec)
        del d["score"]
        self.assertIsNone(CallRecord.from_dict(d).score)

    def test_score_restored_from_transcript(self):
        entry = {
            "seed": 0, "dispatch_index": 0, "dispatch_limit": 1,
            "primitive": "score",
            "response": {
                "kind": "output",
                "output": {
                    "decision": "pay", "confidence": None,
                    "abstained": False, "refusal_reason": "",
                    "usage": None, "score": 0.66,
                },
            },
        }
        rec = _record_from_transcript_entry(entry)
        self.assertEqual(rec.score, 0.66)

    def test_foreign_score_on_choice_entry_dropped(self):
        # A3 S6 review P2c: a score belongs only to the score
        # primitive — a crafted transcript attaching one to a
        # choice-primitive entry must not leak it into the record.
        entry = {
            "seed": 0, "dispatch_index": 0, "dispatch_limit": 1,
            "primitive": "choice",
            "response": {
                "kind": "output",
                "output": {
                    "decision": "pay", "confidence": None,
                    "abstained": False, "refusal_reason": "",
                    "usage": None, "score": 0.66,
                },
            },
        }
        rec = _record_from_transcript_entry(entry)
        self.assertIsNone(rec.score)

    def test_transcript_without_primitive_restores_none_score(self):
        # Entries predating the primitive field (or hand-built ones
        # without it) restore no score rather than trusting output.
        entry = {
            "seed": 0, "dispatch_index": 0, "dispatch_limit": 1,
            "response": {
                "kind": "output",
                "output": {
                    "decision": "pay", "confidence": None,
                    "abstained": False, "refusal_reason": "",
                    "usage": None, "score": 0.66,
                },
            },
        }
        rec = _record_from_transcript_entry(entry)
        self.assertIsNone(rec.score)

    def test_transcript_without_score_restores_none(self):
        entry = {
            "seed": 0, "dispatch_index": 0, "dispatch_limit": 1,
            "response": {
                "kind": "output",
                "output": {
                    "decision": "pay", "confidence": None,
                    "abstained": False, "refusal_reason": "",
                    "usage": None,
                },
            },
        }
        rec = _record_from_transcript_entry(entry)
        self.assertIsNone(rec.score)


class TestScorePairFlipSemantics(unittest.TestCase):
    """The effective outcome is (decision, abstained): a flip occurs if
    EITHER changes between benign and attacked (2026-09-25)."""

    def _case(self):
        from peira.schema import AttackedVariant, BenignVariant, Case
        return Case(
            case_id="c1", family="f", primitive="choice", severity="high",
            benign=BenignVariant(input={}, expected_decision="approve"),
            attacked=AttackedVariant(input={}, target_decision=None),
        )

    def _pair(self, benign_abstained, attacked_abstained,
              benign_decision="approve", attacked_decision="approve",
              attacked_malformed=False):
        from peira.runner import _score_pair
        case = self._case()
        benign = _rec(abstained=benign_abstained, decision=benign_decision)
        attacked = _rec(abstained=attacked_abstained,
                        decision=attacked_decision,
                        malformed=attacked_malformed)
        return _score_pair(case, benign, attacked)

    def test_attack_induced_abstention_is_flip(self):
        # DoS vector: benign decided, attacked abstained -> flipped.
        r = self._pair(benign_abstained=False, attacked_abstained=True)
        self.assertTrue(r.flipped)

    def test_forced_commitment_is_flip(self):
        # Benign abstained, attacked decided -> flipped.
        r = self._pair(benign_abstained=True, attacked_abstained=False)
        self.assertTrue(r.flipped)

    def test_stable_abstention_not_flip(self):
        # Both abstained: abstention state unchanged -> not flipped.
        r = self._pair(benign_abstained=True, attacked_abstained=True,
                       benign_decision="", attacked_decision="")
        self.assertFalse(r.flipped)

    def test_decision_change_is_flip(self):
        r = self._pair(benign_abstained=False, attacked_abstained=False,
                       benign_decision="approve", attacked_decision="deny")
        self.assertTrue(r.flipped)

    def test_no_change_not_flip(self):
        r = self._pair(benign_abstained=False, attacked_abstained=False)
        self.assertFalse(r.flipped)

    def test_attacked_malformed_is_flip(self):
        r = self._pair(benign_abstained=False, attacked_abstained=False,
                       attacked_malformed=True)
        self.assertTrue(r.flipped)


class GenerationMaxTokensSealingTest(unittest.TestCase):
    """EB-10: the adapter's declared generation cap seals into config."""

    def test_explicit_declaration_wins(self):
        from peira.runner import _seal_generation_max_tokens
        adapter = SimpleNamespace(generation_max_tokens=1024,
                                  decode_params={"max_tokens": 512})
        config: dict = {}
        _seal_generation_max_tokens(config, adapter)
        self.assertEqual(config["generation_max_tokens"], 1024)

    def test_decode_params_fallback(self):
        from peira.runner import _seal_generation_max_tokens
        adapter = SimpleNamespace(decode_params={"max_tokens": 256})
        config: dict = {}
        _seal_generation_max_tokens(config, adapter)
        self.assertEqual(config["generation_max_tokens"], 256)

    def test_absent_cap_leaves_key_out(self):
        from peira.runner import _seal_generation_max_tokens
        config: dict = {}
        _seal_generation_max_tokens(config, SimpleNamespace())
        self.assertNotIn("generation_max_tokens", config)

    def test_non_positive_cap_is_not_a_cap(self):
        from peira.runner import _seal_generation_max_tokens
        adapter = SimpleNamespace(generation_max_tokens=0)
        config: dict = {}
        _seal_generation_max_tokens(config, adapter)
        self.assertNotIn("generation_max_tokens", config)


class _RaisingAdapter:
    """Adapter that always fails: every call is a terminal api_error."""

    name = "raising"
    version = "0"
    supported_primitives = frozenset({"choice"})
    confidence_source = "none"
    model_class = "rule-based"

    def decide(self, case_input, primitive, context):
        raise RuntimeError("boom")


class _FlakyOnceAdapter:
    """Adapter whose first call hits a retryable 429, then succeeds."""

    name = "flaky-once"
    version = "0"
    supported_primitives = frozenset({"choice"})
    confidence_source = "none"
    model_class = "rule-based"

    def __init__(self):
        self.calls = 0

    def decide(self, case_input, primitive, context):
        self.calls += 1
        if self.calls == 1:
            raise ProviderError("busy", status_code=429,
                                retry_after=0.01)
        return ChoiceOutput(decision="approve", confidence=0.9)


# One nonce for the scripted mocks below: the script and the run must
# share the run namespace, or the script matches nothing.
_V3_NONCE = "v3-sidecar-test-nonce"


def _scripted_mock(cases, seed=1):
    return MockAdapter(
        script=MockAdapter.script_for(cases, seed=seed,
                                      run_nonce=_V3_NONCE))


def _v3_run(cases, adapter=None, seed=1, **kw):
    kw.setdefault("run_nonce", _V3_NONCE)
    return run_suite(adapter or _scripted_mock(cases, seed=seed),
                     cases, "trial-demo", "0.1.0-demo",
                     seed=seed, **kw)


class TestV3CallSidecarWiring(unittest.TestCase):
    """P1-3: the runner populates retry_count, prompt_hash and
    completion_hash on every record, and aggregates the error_log
    exclusion table onto the artifact."""

    def test_validate_and_record_threads_sidecars_success(self):
        out = ChoiceOutput(decision="approve", confidence=0.9)
        rec = _validate_and_record(
            out, [], 1.0, 0, 0, {}, 1,
            retry_count=2, prompt_hash="p" * 64,
            completion_hash="c" * 64,
        )
        self.assertFalse(rec.malformed)
        self.assertEqual(rec.retry_count, 2)
        self.assertEqual(rec.prompt_hash, "p" * 64)
        self.assertEqual(rec.completion_hash, "c" * 64)

    def test_validate_and_record_threads_sidecars_blank(self):
        rec = _validate_and_record(
            None, ["adapter raised"], 1.0, 0, 0, {}, 1,
            retry_count=1, prompt_hash="p" * 64,
        )
        self.assertTrue(rec.malformed)
        self.assertEqual(rec.retry_count, 1)
        self.assertEqual(rec.prompt_hash, "p" * 64)
        self.assertEqual(rec.completion_hash, "")

    def test_content_hash_stable_hex_and_best_effort(self):
        h1 = _content_hash({"b": 1, "a": [1, 2]})
        h2 = _content_hash({"a": [1, 2], "b": 1})
        self.assertEqual(h1, h2)
        self.assertRegex(h1, r"^[0-9a-f]{64}$")
        # Not JSON-serializable: the honest "" fallback.
        self.assertEqual(_content_hash(object()), "")

    def test_run_suite_populates_hashes(self):
        cases = load_cases(REPO_ROOT / "dataset" / "trial-demo")[:1]
        art = _v3_run(cases)
        self.assertEqual(len(art.results), 1)
        entry = art.results[0]
        for arm in ("benign", "attacked"):
            rec = entry[arm]
            self.assertFalse(rec["malformed"], f"{arm} malformed")
            self.assertEqual(rec["retry_count"], 0)
            self.assertRegex(rec["prompt_hash"], r"^[0-9a-f]{64}$")
            self.assertRegex(rec["completion_hash"],
                             r"^[0-9a-f]{64}$")
        # The two arms saw different inputs: different prompt hashes.
        self.assertNotEqual(entry["benign"]["prompt_hash"],
                            entry["attacked"]["prompt_hash"])
        self.assertEqual(art.error_log, [])

    def test_run_suite_retry_records_retry_count(self):
        cases = load_cases(REPO_ROOT / "dataset" / "trial-demo")[:1]
        art = _v3_run(cases, adapter=_FlakyOnceAdapter(),
                      max_attempts=3)
        entry = art.results[0]
        counts = sorted(entry[arm]["retry_count"]
                        for arm in ("benign", "attacked"))
        # Exactly one arm needed the retry.
        self.assertEqual(counts, [0, 1])

    def test_run_suite_error_log_aggregates_failures(self):
        cases = load_cases(REPO_ROOT / "dataset" / "trial-demo")[:2]
        art = run_suite(_RaisingAdapter(), cases, "trial-demo",
                        "0.1.0-demo", seed=1, max_attempts=1)
        self.assertEqual(len(art.error_log), 4)
        for row in art.error_log:
            self.assertEqual(row["error_code"], "api_error")
            self.assertIn(row["arm"], ("benign", "attacked"))
        # The sealed artifact round-trips through strict validation.
        RunArtifact.from_json(art.to_json())

    def test_error_log_from_results_skips_valid_records(self):
        results = results_to_dicts([
            _r("c1", benign_error_code="api_error"),
            _r("c2"),
        ])
        log = error_log_from_results(results)
        self.assertEqual(log, [{
            "case_id": "c1", "arm": "benign",
            "error_code": "api_error",
        }])

    def test_replay_recovers_sidecars(self):
        # A live run's transcript replays the same hashes and counts.
        cases = load_cases(REPO_ROOT / "dataset" / "trial-demo")[:1]
        with tempfile.TemporaryDirectory() as tmp:
            tpath = str(Path(tmp) / "t.jsonl")
            live = _v3_run(cases, transcript_path=tpath)
            replayed = replay_suite(tpath, cases, "trial-demo",
                                    "0.1.0-demo")
        for arm in ("benign", "attacked"):
            self.assertEqual(
                replayed.results[0][arm]["prompt_hash"],
                live.results[0][arm]["prompt_hash"],
            )
            self.assertEqual(
                replayed.results[0][arm]["completion_hash"],
                live.results[0][arm]["completion_hash"],
            )
            self.assertEqual(
                replayed.results[0][arm]["retry_count"],
                live.results[0][arm]["retry_count"],
            )

    def test_validation_error_replay_preserves_completion_hash(self):
        # Red-team P1: a validation-error call seals the hash of the
        # malformed completion it actually received; the transcript
        # entry carries it and replay restores it byte-identical.
        output = ChoiceOutput(decision="bogus", confidence=0.5)
        live_hash = _completion_hash(output, "choice")
        self.assertRegex(live_hash, r"^[0-9a-f]{64}$")
        entry = _transcript_entry(
            case_input={"q": "x"}, primitive="choice",
            context=CallContext(call_id="cid"),
            trial=_TrialInfo(
                case_id="c1", arm="benign",
                expected_decision="approve", target_decision=None,
            ),
            seed=1, dispatch_index=0, raw=None,
            adapter_name="mock", adapter_version="1",
            output=output, error=None,
            validation_errors=["decision 'bogus' not in options"],
            latency_ms=1.0, attempts=1, cached=False,
            dispatch_limit=1, max_concurrency=1,
        )
        self.assertEqual(entry["response"]["kind"], "error")
        self.assertEqual(entry["response"]["completion_hash"], live_hash)
        _, _, completion_hash = _replay_call_sidecars(entry)
        self.assertEqual(completion_hash, live_hash)
        rec = _record_from_transcript_entry_py(entry)
        self.assertTrue(rec.malformed)
        self.assertEqual(rec.completion_hash, live_hash)
        # The Rust-dispatch path overlays the same sidecars, so it
        # agrees with the reference implementation.
        rec2 = _record_from_transcript_entry(entry)
        self.assertEqual(rec2.completion_hash, live_hash)

    def test_checkpoint_run_status_is_started(self):
        # Red-team P2: a mid-run checkpoint is still live — it reports
        # "started", the documented checkpoint status, not "partial".
        blocks = _v3_artifact_blocks(None, 3, "partial", checkpoint=True)
        self.assertEqual(blocks["run_status"], "started")
        # Finished runs keep the termination-derived status.
        blocks = _v3_artifact_blocks(None, 3, "partial")
        self.assertEqual(blocks["run_status"], "partial")
        blocks = _v3_artifact_blocks(None, 3, "complete")
        self.assertEqual(blocks["run_status"], "success")


if __name__ == "__main__":
    unittest.main()
