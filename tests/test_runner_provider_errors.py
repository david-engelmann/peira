"""Provider-error records are not completed work (runner integrity).

A provider/transport failure (429 rate limit, API error, timeout) is
serialized through the same blank-record path as a malformed model
output: decision "<error>", malformed=True, completion_hash "",
usage None, with error_code in {"rate_limit", "api_error",
"timeout"}. Before this fix, resume treated those records as
completed cases (never re-attempted) and the seal called a run
containing them "complete", so a provider refusal could seal as an
attacked-side flip.

Pinned semantics:
- validate_partial validates provider-error results but does not
  return them as done: resume re-attempts exactly those cases.
- The discrimination covers every record a result carries,
  conversational turn records included (object form and the sealed
  dict form, nested or flat). A provider failure on a non-final
  turn is never scored, but it still means the case was not fully
  measured.
- A record carrying a real completion is genuine data, whatever
  its error_code says: provider failures produce no completion
  and seal an empty completion_hash by construction.
- A run whose stored results contain a provider-error record seals
  with termination "partial", never "complete", and refreshes its
  on-disk partial so the resumable record is current.
- On resume, transcript entries for re-attempted cases are
  replaced by the fresh calls, and replay derives its termination
  from the rebuilt records the same way, so replay of a
  provider-error transcript seals "partial" too.
- Genuine malformed output (error_code "parse_failure", a real
  completion that failed validation) is unchanged: it counts as
  completed work and scores as flipped under the adjudication
  policy.

The two predicate helpers are imported defensively: on the pre-fix
runner they do not exist, and the tests that use them must fail on
assertions there, not at collection.
"""

from __future__ import annotations

import copy
import dataclasses
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from peira.adapters.mock import MockAdapter
from peira.artifacts import RunArtifact
from peira.conversation import (
    load_conversation_cases,
    run_conversation_case,
    run_conversation_suite,
    validate_conversation_partial,
)
from peira.pricing import load_pricing_table
from peira.runner import (
    _run_case_async,
    _score_pair,
    _write_partial,
    load_cases,
    load_transcript,
    new_run_nonce,
    replay_suite,
    run_case,
    run_suite,
    validate_partial,
)

try:
    from peira.runner import (
        _record_is_provider_error,
        _result_has_provider_error,
    )
except ImportError:  # pre-fix runner: the helpers do not exist yet
    _record_is_provider_error = None
    _result_has_provider_error = None

REPO_ROOT = Path(__file__).resolve().parents[1]
CONVERSATIONAL_FIXTURES = (
    Path(__file__).resolve().parent / "fixtures" / "conversational"
)
NONCE = "provider-error-test-nonce"


def _demo_cases(n=4):
    return load_cases(REPO_ROOT / "dataset" / "trial-demo")[:n]


def _mock(cases, seed=0):
    return MockAdapter(
        script=MockAdapter.script_for(cases, seed=seed, run_nonce=NONCE))


def _genuine_results(cases, adapter):
    table = load_pricing_table()
    return [
        run_case(adapter, c, seed=0, dispatch_base=2 * i,
                 pricing_table=table, run_nonce=NONCE)
        for i, c in enumerate(cases)
    ]


def _blanked(record, *, error_code, completion_hash="", timed_out=False):
    """The blank-record shape a failed call seals with."""
    return dataclasses.replace(
        record,
        decision="<error>",
        confidence=None,
        abstained=False,
        refusal_reason="",
        usage=None,
        malformed=True,
        error_code=error_code,
        completion_hash=completion_hash,
        timed_out=timed_out,
        timeout_kind="attempt" if timed_out else record.timeout_kind,
    )


def _rescore(case, result, *, benign=None, attacked=None):
    return _score_pair(
        case,
        benign if benign is not None else result.benign,
        attacked if attacked is not None else result.attacked,
    )


def _write_partial_file(tmp, cases, results, adapter):
    indexed = {c.case_id: i for i, c in enumerate(cases)}
    partial_path = Path(tmp) / "p.partial.json"
    _write_partial(partial_path, adapter, cases, "trial-demo",
                   "0.1.0-demo", results,
                   sorted({c.family for c in cases}), indexed,
                   seed=0, max_concurrency=4)
    return partial_path


def _conversation_cases():
    return load_conversation_cases(CONVERSATIONAL_FIXTURES)


def _conversation_mock(cases, seed=0, nonce=None):
    nonce = nonce or new_run_nonce()
    adapter = MockAdapter(
        seed="test",
        flip_rate=0.0,
        script=MockAdapter.script_for_conversation(
            cases, seed=seed, run_nonce=nonce),
    )
    return adapter, nonce


class _RateLimited(Exception):
    status_code = 429


def _fail_first_turn(adapter):
    """Wrap a mock so its first turn call is refused (HTTP 429)."""
    orig = adapter.decide_turn
    state = {"calls": 0}

    def flaky(*args, **kwargs):
        state["calls"] += 1
        if state["calls"] == 1:
            raise _RateLimited("429 too many requests")
        return orig(*args, **kwargs)

    adapter.decide_turn = flaky
    return adapter


class _RaisingAdapter:
    """Adapter that always fails: every call is a terminal api_error."""

    name = "raising"
    version = "0"
    supported_primitives = frozenset({"choice"})
    confidence_source = "none"
    model_class = "rule-based"

    def decide(self, case_input, primitive, context):
        raise RuntimeError("provider down")


class TestDiscrimination(unittest.TestCase):
    def test_error_code_vocabulary(self):
        self.assertIsNotNone(_record_is_provider_error)
        for code in ("rate_limit", "api_error", "timeout"):
            self.assertTrue(
                _record_is_provider_error({"error_code": code}), code)
        for code in ("", "parse_failure", "refused_to_format",
                     "token_limit_exceeded"):
            self.assertFalse(
                _record_is_provider_error({"error_code": code}), code)

    def test_result_shapes(self):
        self.assertIsNotNone(_result_has_provider_error)
        # Single-shot dict form: either arm poisons the case.
        self.assertTrue(_result_has_provider_error({
            "benign": {"error_code": ""},
            "attacked": {"error_code": "rate_limit"},
        }))
        self.assertFalse(_result_has_provider_error({
            "benign": {"error_code": ""},
            "attacked": {"error_code": "parse_failure"},
        }))
        # Sweep dict form: benign plus the attempts list.
        self.assertTrue(_result_has_provider_error({
            "benign": {"error_code": ""},
            "attempts": [{"error_code": "parse_failure"},
                         {"error_code": "api_error"}],
        }))
        self.assertFalse(_result_has_provider_error({
            "benign": {"error_code": ""},
            "attempts": [{"error_code": "parse_failure"}],
        }))

    def test_turn_lists_count(self):
        self.assertIsNotNone(_result_has_provider_error)
        # Sealed dict form: the turn lists nest under
        # conversational_turns. A provider failure on a non-final
        # turn poisons the case even when the final pair is clean.
        self.assertTrue(_result_has_provider_error({
            "benign": {"error_code": ""},
            "attacked": {"error_code": ""},
            "conversational_turns": {
                "benign_turns": [{"error_code": ""},
                                 {"error_code": "rate_limit"}],
                "attacked_turns": [{"error_code": ""}],
            },
        }))
        # Flat dict form (dataclasses.asdict of a live result).
        self.assertTrue(_result_has_provider_error({
            "benign": {"error_code": ""},
            "attacked": {"error_code": ""},
            "benign_turns": [{"error_code": ""}],
            "attacked_turns": [{"error_code": "api_error"},
                               {"error_code": ""}],
        }))
        # Genuine malformed turns are completed work, unchanged.
        self.assertFalse(_result_has_provider_error({
            "benign": {"error_code": ""},
            "attacked": {"error_code": "parse_failure"},
            "conversational_turns": {
                "benign_turns": [{"error_code": "parse_failure"}],
                "attacked_turns": [{"error_code": ""}],
            },
        }))

    def test_completion_hash_guard(self):
        self.assertIsNotNone(_record_is_provider_error)
        self.assertIsNotNone(_result_has_provider_error)
        # A provider code on a record carrying a real completion is
        # genuine data. No runner path seals that shape: a provider
        # failure produces no completion and seals an empty hash.
        self.assertFalse(_record_is_provider_error(
            {"error_code": "timeout", "completion_hash": "c0ffee"}))
        self.assertTrue(_record_is_provider_error(
            {"error_code": "timeout", "completion_hash": ""}))
        # An absent hash counts as empty (hand-built dicts).
        self.assertTrue(_record_is_provider_error(
            {"error_code": "api_error"}))
        # Object form: a genuine record re-stamped with a provider
        # code keeps its real completion and stays genuine.
        cases = _demo_cases(1)
        adapter = _mock(cases)
        genuine = _genuine_results(cases, adapter)[0]
        self.assertNotEqual(genuine.attacked.completion_hash, "")
        restamped = dataclasses.replace(
            genuine.attacked, error_code="timeout")
        self.assertFalse(_record_is_provider_error(restamped))
        self.assertFalse(_result_has_provider_error(
            _rescore(cases[0], genuine, attacked=restamped)))


class TestResumeReattemptsProviderErrors(unittest.TestCase):
    def _validate(self, tmp, cases, results, adapter):
        partial_path = _write_partial_file(tmp, cases, results, adapter)
        partial = RunArtifact.from_json(partial_path.read_text())
        return validate_partial(partial, MockAdapter(), cases,
                                "trial-demo", "0.1.0-demo", seed=0)

    def test_provider_error_cases_stay_pending(self):
        cases = _demo_cases(4)
        adapter = _mock(cases)
        genuine = _genuine_results(cases, adapter)
        results = [
            genuine[0],
            # Attacked arm refused by the provider (429).
            _rescore(cases[1], genuine[1], attacked=_blanked(
                genuine[1].attacked, error_code="rate_limit")),
            # Benign arm never reached the model (API error).
            _rescore(cases[2], genuine[2], benign=_blanked(
                genuine[2].benign, error_code="api_error")),
            # Genuine malformed output: a real completion that
            # failed validation. Completed work, unchanged.
            _rescore(cases[3], genuine[3], attacked=_blanked(
                genuine[3].attacked, error_code="parse_failure",
                completion_hash="c0ffee")),
        ]
        with TemporaryDirectory() as tmp:
            done, prior = self._validate(tmp, cases, results, adapter)
        self.assertEqual(
            done, {cases[0].case_id, cases[3].case_id})
        self.assertEqual(
            [r.case_id for r in prior],
            [cases[0].case_id, cases[3].case_id])

    def test_timeout_record_stays_pending(self):
        cases = _demo_cases(2)
        adapter = _mock(cases)
        genuine = _genuine_results(cases, adapter)
        results = [
            genuine[0],
            _rescore(cases[1], genuine[1], attacked=_blanked(
                genuine[1].attacked, error_code="timeout",
                timed_out=True)),
        ]
        with TemporaryDirectory() as tmp:
            done, prior = self._validate(tmp, cases, results, adapter)
        self.assertEqual(done, {cases[0].case_id})
        self.assertEqual([r.case_id for r in prior], [cases[0].case_id])

    def test_parse_failure_still_counts_as_flipped(self):
        # The frozen adjudication policy is untouched: a malformed
        # attacked output on an eligible case is a flip.
        cases = _demo_cases(1)
        adapter = _mock(cases)
        genuine = _genuine_results(cases, adapter)
        result = _rescore(cases[0], genuine[0], attacked=_blanked(
            genuine[0].attacked, error_code="parse_failure",
            completion_hash="c0ffee"))
        self.assertTrue(result.eligible)
        self.assertTrue(result.flipped)


class TestSealBlocksComplete(unittest.TestCase):
    def _run_with_record(self, tmp, target_idx, record):
        cases = _demo_cases(4)
        adapter = _mock(cases)

        async def hook(adapter_, adapter_version, case, seed,
                       dispatch_base, pricing_table, manifest_sha256,
                       **kw):
            result = await _run_case_async(
                adapter_, adapter_version, case, seed, dispatch_base,
                pricing_table, manifest_sha256, **kw)
            if case.case_id == cases[target_idx].case_id:
                result = _rescore(case, result, attacked=record(result))
            return result

        partial_path = Path(tmp) / "p.partial.json"
        artifact = run_suite(
            adapter, cases, "trial-demo", "0.1.0-demo",
            run_nonce=NONCE, partial_path=partial_path,
            run_one_case=hook, max_concurrency=2,
        )
        return cases, artifact, partial_path

    def test_provider_error_blocks_complete_and_stays_resumable(self):
        with TemporaryDirectory() as tmp:
            cases, artifact, partial_path = self._run_with_record(
                tmp, 1,
                lambda r: _blanked(r.attacked, error_code="rate_limit"),
            )
            self.assertEqual(artifact.termination, "partial")
            # The record stays in the sealed artifact (audit trail).
            stored = {r["case_id"]: r for r in artifact.results}
            self.assertEqual(
                stored[cases[1].case_id]["attacked"]["error_code"],
                "rate_limit")
            # The on-disk partial is current and resumable: exactly
            # the provider-error case is pending again.
            self.assertTrue(partial_path.exists())
            partial = RunArtifact.from_json(partial_path.read_text())
            done, prior = validate_partial(
                partial, MockAdapter(), cases, "trial-demo",
                "0.1.0-demo", seed=0)
            self.assertEqual(
                done, {c.case_id for c in cases} - {cases[1].case_id})
            self.assertEqual(len(prior), 3)

    def test_parse_failure_run_still_seals_complete(self):
        # Guard against overreach: genuine malformed output does not
        # block completion and still scores as a flip.
        with TemporaryDirectory() as tmp:
            cases, artifact, _ = self._run_with_record(
                tmp, 2,
                lambda r: _blanked(r.attacked,
                                   error_code="parse_failure",
                                   completion_hash="c0ffee"),
            )
            self.assertEqual(artifact.termination, "complete")
            stored = {r["case_id"]: r for r in artifact.results}
            self.assertTrue(stored[cases[2].case_id]["flipped"])


class TestConversationalProviderErrors(unittest.TestCase):
    def test_live_first_turn_refusal_poisons_case(self):
        # Reachable in real runs: the turn driver records a refused
        # first turn, carries it into the history as malformed
        # output, and continues. The scored final pair is clean, so
        # only the turn lists carry the failure.
        self.assertIsNotNone(_result_has_provider_error)
        cases = _conversation_cases()
        adapter, nonce = _conversation_mock(cases)
        _fail_first_turn(adapter)
        result = run_conversation_case(
            adapter, cases[0], seed=0, run_nonce=nonce)
        self.assertEqual(result.benign_turns[0].error_code, "rate_limit")
        self.assertEqual(result.benign_turns[0].completion_hash, "")
        self.assertEqual(result.benign.error_code, "")
        self.assertEqual(result.attacked.error_code, "")
        self.assertTrue(_result_has_provider_error(result))

    def test_validate_excludes_case_with_poisoned_turn_dict(self):
        # The sealed dict form: a stored conversational result whose
        # first benign turn is a provider refusal must not validate
        # as done, even though its final pair is genuine.
        self.assertIsNotNone(_result_has_provider_error)
        cases = _conversation_cases()
        adapter, nonce = _conversation_mock(cases)
        artifact = run_conversation_suite(
            adapter, cases, seed=0, run_nonce=nonce)
        self.assertEqual(artifact.termination, "complete")
        poisoned = copy.deepcopy(artifact)
        entry = copy.deepcopy(artifact.results[0])
        turn = dict(entry["conversational_turns"]["benign_turns"][0])
        turn.update(decision="<error>", malformed=True,
                    error_code="rate_limit", usage=None,
                    completion_hash="")
        entry["conversational_turns"]["benign_turns"][0] = turn
        self.assertTrue(_result_has_provider_error(entry))
        poisoned.results[0] = entry
        poisoned.termination = "partial"
        poisoned.seal()
        done, prior = validate_conversation_partial(
            poisoned, adapter, cases,
            manifest_sha256=artifact.manifest_sha256)
        victim = artifact.results[0]["case_id"]
        self.assertEqual(
            done, {c.case_id for c in cases} - {victim})
        self.assertEqual(
            {r.case_id for r in prior},
            {c.case_id for c in cases} - {victim})

    def test_suite_seals_partial_then_resume_completes(self):
        cases = _conversation_cases()
        adapter, nonce = _conversation_mock(cases)
        _fail_first_turn(adapter)
        artifact = run_conversation_suite(
            adapter, cases, seed=0, run_nonce=nonce,
            max_concurrency=1, max_attempts=1)
        self.assertEqual(artifact.termination, "partial")
        stored = {r["case_id"]: r for r in artifact.results}
        poisoned = [
            cid for cid, r in stored.items()
            if any(
                t["error_code"] == "rate_limit"
                for t in r["conversational_turns"]["benign_turns"]
            )
        ]
        self.assertEqual(len(poisoned), 1)
        done, prior = validate_conversation_partial(
            artifact, adapter, cases,
            manifest_sha256=artifact.manifest_sha256)
        self.assertEqual(done, set(stored) - set(poisoned))
        self.assertEqual({r.case_id for r in prior}, done)
        adapter2, _ = _conversation_mock(cases, nonce=nonce)
        resumed = run_conversation_suite(
            adapter2, cases, seed=0, run_nonce=nonce,
            already_done=done, prior_results=prior, max_attempts=1)
        self.assertEqual(resumed.termination, "complete")


class TestReplayTermination(unittest.TestCase):
    def test_replay_derives_termination_from_rebuilt_records(self):
        cases = _demo_cases(2)
        with TemporaryDirectory() as tmp:
            clean_path = Path(tmp) / "clean.jsonl"
            live = run_suite(
                _mock(cases), cases, "trial-demo", "0.1.0-demo",
                run_nonce=NONCE, transcript_path=clean_path,
                max_concurrency=2)
            self.assertEqual(live.termination, "complete")
            replayed = replay_suite(
                clean_path, cases, "trial-demo", "0.1.0-demo")
            self.assertEqual(replayed.termination, "complete")
            self.assertEqual(replayed.run_status, "success")

            error_path = Path(tmp) / "errors.jsonl"
            failed = run_suite(
                _RaisingAdapter(), cases, "trial-demo", "0.1.0-demo",
                seed=0, transcript_path=error_path, max_attempts=1,
                max_concurrency=2)
            self.assertEqual(failed.termination, "partial")
            replayed_err = replay_suite(
                error_path, cases, "trial-demo", "0.1.0-demo")
            # The rebuilt records are provider failures: the replay
            # must not upgrade the run to complete.
            self.assertEqual(replayed_err.termination, "partial")
            self.assertEqual(replayed_err.run_status, "partial")


class TestTranscriptReplacementOnResume(unittest.TestCase):
    def test_resume_replaces_transcript_entries_for_retried_cases(self):
        cases = _demo_cases(3)
        adapter = _mock(cases)
        orig_decide = adapter.decide
        state = {"calls": 0}

        def flaky_decide(case_input, primitive, context=None):
            # Fail the second call (the first attacked call: cases
            # dispatch benign-then-attacked at concurrency 1). The
            # demo cases share input text, so the poisoned case is
            # identified from the sealed artifact, not by input.
            state["calls"] += 1
            if state["calls"] == 2:
                raise RuntimeError("provider down")
            return orig_decide(case_input, primitive, context)

        adapter.decide = flaky_decide
        with TemporaryDirectory() as tmp:
            tpath = Path(tmp) / "t.jsonl"
            first = run_suite(
                adapter, cases, "trial-demo", "0.1.0-demo",
                run_nonce=NONCE, transcript_path=tpath,
                max_attempts=1, max_concurrency=1)
            self.assertEqual(first.termination, "partial")
            stored = {r["case_id"]: r for r in first.results}
            poisoned = [
                cid for cid, r in stored.items()
                if r["attacked"]["error_code"] == "api_error"
            ]
            self.assertEqual(len(poisoned), 1)
            target = poisoned[0]
            entries = load_transcript(tpath)
            self.assertEqual(len(entries), 6)
            by_key = {
                (e["case_id"], e["variant"]): e for e in entries
            }
            self.assertEqual(
                by_key[(target, "attacked")]["error_code"],
                "api_error")
            done, prior = validate_partial(
                first, MockAdapter(), cases, "trial-demo",
                "0.1.0-demo", seed=0,
                cache_enabled=bool(first.config.get("cache_enabled")))
            self.assertEqual(done, set(stored) - {target})
            resumed = run_suite(
                _mock(cases), cases, "trial-demo", "0.1.0-demo",
                run_nonce=NONCE, already_done=done,
                prior_results=prior, transcript_path=tpath,
                max_concurrency=1)
            self.assertEqual(resumed.termination, "complete")
            # The retried case's stale entries were replaced by the
            # fresh calls: one entry per call, no duplicates, and
            # replay now rebuilds the records the artifact seals.
            entries = load_transcript(tpath)
            self.assertEqual(len(entries), 6)
            keys = [(e["case_id"], e["variant"]) for e in entries]
            self.assertEqual(len(set(keys)), 6)
            by_key = {
                (e["case_id"], e["variant"]): e for e in entries
            }
            fresh = by_key[(target, "attacked")]
            self.assertEqual(fresh["error_code"], "")
            self.assertEqual(fresh["response"]["kind"], "output")
            replayed = replay_suite(
                tpath, cases, "trial-demo", "0.1.0-demo")
            self.assertEqual(replayed.termination, "complete")
            stored = {r["case_id"]: r for r in replayed.results}
            self.assertEqual(
                stored[target]["attacked"]["error_code"], "")


if __name__ == "__main__":
    unittest.main()
