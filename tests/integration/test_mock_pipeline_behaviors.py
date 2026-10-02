"""Adapter behaviors through the full pipeline.

The mock's flip_rate is a behavioral knob with exact pipeline-level
consequences: 0.0 means the attacked arm never moves (ASR 0), 1.0 means
it always moves to the target (ASR 1, because every shipped case has
target != expected). These assertions are behavioral, not
tautological: they would fail if the runner stopped feeding the mock
the right inputs, if the flip taxonomy changed meaning, or if the
metrics layer misclassified outcomes.

The abstain adapter proves a third behavior class flows through the
same pipeline and lands in the right metric buckets (refusal rate 1.0,
and ASR 1.0 per the documented flip taxonomy: an attacked abstain is
an effective outcome change).
"""

from peira.adapters.base import AbstainOutput
from peira.metrics import PerCaseResult

from ._helpers import (
    TestAdapterBase,
    make_nonce,
    run_mock,
    sample_v1_cases,
    summarize_results,
)

SEED = 20261002


class _ScriptedAdapter(TestAdapterBase):
    """A call_id-scripted test adapter: the harness (which may know the
    gold labels) scripts benign/attacked behavior per pseudonymous call
    id, exactly like MockAdapter.script_for. The adapter itself stays
    blind: it sees only the input dict and the opaque CallContext."""

    name = "scripted-test"
    version = "0.0.1-test"
    cache_namespace = "test:scripted"

    def __init__(self, cases, seed, nonce, attacked_behavior):
        # Build the call-id script through MockAdapter.script_for (the
        # public harness mechanism), then re-map each scripted call to
        # this adapter's behaviors. No private runner imports, no
        # hardcoded dispatch layout.
        from peira.adapters.mock import MockAdapter

        base = MockAdapter.script_for(cases, seed=seed, run_nonce=nonce)
        self._script = {}
        for call_id, sim in base.items():
            if sim.arm == "benign":
                self._script[call_id] = ("decide", sim.expected_decision)
            else:
                self._script[call_id] = attacked_behavior

    def decide(self, case_input, primitive, context=None):
        # Primitive-aware exactly like MockAdapter._output_for: each
        # primitive has its own output contract (base.validate_output).
        from peira.adapters.base import ChoiceOutput, ScoreOutput

        kind, payload = self._script[context.call_id]
        if kind == "abstain":
            if primitive == "choice":
                return ChoiceOutput(
                    decision="", abstained=True, refusal_reason="test-abstain"
                )
            if primitive == "score":
                return ScoreOutput(
                    score=0.0, decision="", abstained=True,
                    refusal_reason="test-abstain",
                )
            return AbstainOutput(
                decision="", abstained=True, refusal_reason="test-abstain"
            )
        if primitive == "choice":
            return ChoiceOutput(decision=payload, confidence=1.0)
        if primitive == "score":
            score = 0.85 if payload == "approve" else 0.15
            return ScoreOutput(
                score=score,
                decision=payload,
                confidence=score if payload == "approve" else 1.0 - score,
            )
        return AbstainOutput(decision=payload, confidence=1.0)

    # decide_turn inherited from TestAdapterBase (single-shot only).


def _choice(decision):
    from peira.adapters.base import ChoiceOutput

    return ChoiceOutput(decision=decision, confidence=1.0)


def _asr(cases, flip_rate, seed=SEED):
    artifact = run_mock(cases, seed=seed, nonce=make_nonce(), flip_rate=flip_rate)
    results = [PerCaseResult.from_dict(d) for d in artifact.results]
    assert artifact.verify()
    return summarize_results(artifact), results


def test_flip_rate_zero_means_no_attack_success():
    cases = sample_v1_cases(2)
    metrics, _ = _asr(cases, flip_rate=0.0)
    assert metrics["asr_conditional"] == 0.0
    assert metrics["benign_accuracy"] == 1.0
    assert metrics["n_eligible"] == len(cases)


def test_flip_rate_one_means_total_attack_success():
    cases = sample_v1_cases(2)
    metrics, _ = _asr(cases, flip_rate=1.0)
    # Every shipped case has target != expected, so every eligible case
    # flips and the conditional ASR is exactly 1.
    assert metrics["asr_conditional"] == 1.0
    assert metrics["benign_accuracy"] == 1.0
    assert metrics["n_eligible"] == len(cases)
    # The flip taxonomy saw real flips, not the "none" bucket.
    counts = metrics["per_family"]
    flipped_anywhere = any(
        row["flip_direction_counts"].get("none", 0) < row["n_eligible"]
        for row in counts.values()
    )
    assert flipped_anywhere


def test_partial_flip_rate_is_deterministic():
    cases = sample_v1_cases(2)
    m1, _ = _asr(cases, flip_rate=0.5, seed=SEED)
    m2, _ = _asr(cases, flip_rate=0.5, seed=SEED)
    assert 0.0 < m1["asr_conditional"] < 1.0
    assert m1["asr_conditional"] == m2["asr_conditional"]


def test_abstain_adapter_flows_through_pipeline():
    from peira.runner import run_suite
    from ._helpers import SUITE, dataset_version

    cases = sample_v1_cases(2)
    nonce = make_nonce()
    adapter = _ScriptedAdapter(cases, SEED, nonce, ("abstain", None))
    artifact = run_suite(
        adapter, cases, SUITE, dataset_version(),
        seed=SEED, max_concurrency=4, run_nonce=nonce,
    )
    assert artifact.verify()
    metrics = summarize_results(artifact)
    # Abstentions on the attacked arm are measured as refusals.
    assert metrics["refusal_rate"] == 1.0
    # The benign arm still decided correctly: abstention is an
    # attacked-arm behavior, not a broken adapter.
    assert metrics["benign_accuracy"] == 1.0
    # The flip taxonomy counts an attacked abstain as an effective
    # outcome change (PerCaseResult.flipped includes attacked
    # abstains by documented design), so conditional ASR is 1.0 here.
    # This pins the cross-layer semantic: abstain != benign-correct,
    # abstain == behavior change under attack.
    assert metrics["asr_conditional"] == 1.0
