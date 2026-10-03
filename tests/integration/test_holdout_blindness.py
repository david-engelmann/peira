"""Adapter-boundary blindness: the executable form of D-25/D-28.

The blind-holdout protocol rests on one runtime invariant: ``case_id``,
arm, ``expected_decision``, and ``target_decision`` never cross the
adapter boundary. A snooping adapter records everything it receives
across a full pipeline run; the test then asserts none of the trial
bookkeeping appears in that record. If a future refactor leaks a
label into the input dict or the CallContext, this test fails.

The sealed artifact and the transcript legitimately carry case_ids
(they are harness-side measurement records, never adapter-visible),
so blindness is asserted at the boundary, not in the artifact.

Synthetic holdout-style case IDs are used throughout. This test never
touches the real holdout (AGENTS.md hard rule 2).
"""

import dataclasses
import json
import re

from peira.adapters.base import ChoiceOutput
from peira.runner import load_cases, run_suite
from peira.schema import Case

from ._helpers import (
    SUITE,
    V1_DIR,
    TestAdapterBase,
    dataset_version,
    make_nonce,
    summarize_results,
)

SEED = 20261002


class _SnoopingAdapter(TestAdapterBase):
    """Records every input dict and context it is given, then decides
    the first option. The recording is the assertion surface."""

    name = "snoop"
    version = "0.0.1-test"
    cache_namespace = "test:snoop"

    def __init__(self):
        self.seen_inputs = []
        self.seen_contexts = []

    def decide(self, case_input, primitive, context=None):
        self.seen_inputs.append(dict(case_input))
        self.seen_contexts.append(context)
        options = case_input.get("options") or ["x"]
        return ChoiceOutput(decision=options[0], confidence=1.0)

    # decide_turn inherited from TestAdapterBase (single-shot only).


def _holdout_like_cases():
    """Real v1 cases re-labeled with synthetic holdout-style IDs."""
    cases = load_cases(V1_DIR)[:6]
    relabeled = []
    for i, case in enumerate(cases):
        d = {
            "case_id": f"h-blind-{i:04d}",
            "family": case.family,
            "primitive": "choice",
            "severity": case.severity,
            "benign": {
                "input": {
                    "prompt": case.benign.input["prompt"],
                    "options": ["alpha", "beta"],
                },
                "expected_decision": "alpha",
            },
            "attacked": {
                "input": {
                    "prompt": case.attacked.input["prompt"],
                    "options": ["alpha", "beta"],
                },
                "target_decision": "beta",
            },
        }
        relabeled.append(Case.from_dict(d))
    return relabeled


def _run_snooped():
    cases = _holdout_like_cases()
    adapter = _SnoopingAdapter()
    artifact = run_suite(
        adapter, cases, SUITE, dataset_version(),
        seed=SEED, max_concurrency=4, run_nonce=make_nonce(),
    )
    assert artifact.verify()
    return cases, adapter


def test_adapter_never_sees_case_ids():
    cases, adapter = _run_snooped()
    # Two adapter calls per case (benign + attacked); derived from the
    # input, not pinned as a literal.
    assert len(adapter.seen_inputs) == 2 * len(cases)
    blob = json.dumps(adapter.seen_inputs)
    for case in cases:
        assert case.case_id not in blob, f"case id crossed the boundary: {case.case_id}"


def test_adapter_never_sees_trial_bookkeeping():
    cases, adapter = _run_snooped()
    blob = json.dumps(adapter.seen_inputs).lower()
    for forbidden in ("expected_decision", "target_decision", "benign", "attacked"):
        assert forbidden not in blob, f"{forbidden!r} crossed the adapter boundary"
    for case in cases:
        assert case.family not in blob, f"family leaked: {case.family}"
    # The contexts are opaque handles. Inspect every field, not just
    # call_id: a future bookkeeping field leaking trial metadata must
    # trip this test, not slip past a call_id-only check.
    for ctx in adapter.seen_contexts:
        assert ctx is not None
        # Pin the exact opaque call_id format: a degraded id (e.g.
        # leaking the dispatch index, which encodes the arm) must fail
        # here, not pass a loose check.
        assert re.fullmatch(r"call-[0-9a-f]{16}", ctx.call_id), (
            f"call_id format degraded: {ctx.call_id!r}"
        )
        ctx_blob = json.dumps(dataclasses.asdict(ctx), default=str)
        for case in cases:
            assert case.case_id not in ctx_blob, (
                f"case id leaked via context field: {case.case_id}"
            )
            assert case.family not in ctx_blob, (
                f"family leaked via context field: {case.family}"
            )


def test_public_report_path_carries_no_case_identity():
    from peira.adapters.mock import MockAdapter
    from peira.report_html import leaderboard_to_html

    cases = _holdout_like_cases()
    nonce = make_nonce()
    script = MockAdapter.script_for(cases, seed=SEED, run_nonce=nonce)
    artifact = run_suite(
        MockAdapter(flip_rate=0.5, script=script), cases, SUITE, dataset_version(),
        seed=SEED, max_concurrency=4, run_nonce=nonce,
    )
    metrics = summarize_results(artifact)
    html = leaderboard_to_html(
        {"title": "t", "ranked": [{
            "adapter_name": "mock", "adapter_version": "x",
            "asr_conditional": metrics["asr_conditional"],
            "asr_ci95": metrics["asr_ci95"],
            "benign_accuracy": metrics["benign_accuracy"],
            "n_eligible": metrics["n_eligible"],
        }], "unranked": []},
        data_source="mock",
        generated_utc="2026-10-02T00:00:00Z",
    )
    for case in cases:
        assert case.case_id not in html
