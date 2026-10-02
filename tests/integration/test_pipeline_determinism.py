"""Pipeline determinism: the same logical run computes the same sealed
answers regardless of execution shape.

This extends the determinism contract (tests/test_determinism.py,
trial-demo) to the multi-family v1 sample and to rerun stability:
two runs with the same seed and the same nonce but different
concurrency levels produce identical normalized results and metrics.
Concurrency is a performance parameter, never a measurement input.
"""

from ._helpers import (
    make_nonce,
    normalize_metrics,
    normalize_result,
    run_mock,
    sample_v1_cases,
    summarize_results,
)

SEED = 20261002


def _normalized_run(cases, seed, nonce, max_concurrency):
    artifact = run_mock(cases, seed=seed, nonce=nonce, max_concurrency=max_concurrency)
    assert artifact.verify()
    return (
        [normalize_result(d) for d in artifact.results],
        normalize_metrics(summarize_results(artifact)),
    )


def test_same_seed_same_answers_across_concurrency():
    cases = sample_v1_cases(2)
    nonce = make_nonce()
    results_1, metrics_1 = _normalized_run(cases, SEED, nonce, max_concurrency=1)
    results_8, metrics_8 = _normalized_run(cases, SEED, nonce, max_concurrency=8)
    assert results_1 == results_8
    assert metrics_1 == metrics_8


def test_rerun_with_fresh_nonce_reproduces_metrics():
    """A fresh nonce re-derives the same mock script (the script is a
    pure function of seed + nonce + suite positions), so the headline
    metrics reproduce even though the call ids differ."""
    cases = sample_v1_cases(2)
    _, metrics_1 = _normalized_run(cases, SEED, make_nonce(), max_concurrency=4)
    _, metrics_2 = _normalized_run(cases, SEED, make_nonce(), max_concurrency=4)
    assert metrics_1["asr_conditional"] == metrics_2["asr_conditional"]
    assert metrics_1["benign_accuracy"] == metrics_2["benign_accuracy"]
    assert metrics_1["n_eligible"] == metrics_2["n_eligible"]
