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
- A run whose stored results contain a provider-error record seals
  with termination "partial", never "complete", and refreshes its
  on-disk partial so the resumable record is current.
- Genuine malformed output (error_code "parse_failure", a real
  completion that failed validation) is unchanged: it counts as
  completed work and scores as flipped under the adjudication
  policy.
"""

from __future__ import annotations

import dataclasses
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from peira.adapters.mock import MockAdapter
from peira.artifacts import RunArtifact
from peira.pricing import load_pricing_table
from peira.runner import (
    _record_is_provider_error,
    _result_has_provider_error,
    _run_case_async,
    _score_pair,
    _write_partial,
    load_cases,
    run_case,
    run_suite,
    validate_partial,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
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


class TestDiscrimination(unittest.TestCase):
    def test_error_code_vocabulary(self):
        for code in ("rate_limit", "api_error", "timeout"):
            self.assertTrue(
                _record_is_provider_error({"error_code": code}), code)
        for code in ("", "parse_failure", "refused_to_format",
                     "token_limit_exceeded"):
            self.assertFalse(
                _record_is_provider_error({"error_code": code}), code)

    def test_result_shapes(self):
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


if __name__ == "__main__":
    unittest.main()
