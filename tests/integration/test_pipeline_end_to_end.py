"""End-to-end pipeline test: dataset -> runner -> metrics -> artifact -> report.

One cohesive run exercises every production stage in sequence on a real
dataset sample (2 cases x 10 v1 families). This is the test that fails
first when the stages stop agreeing with each other: a renamed metrics
key, a report column reading a field the artifact no longer seals, a
runner record the metrics layer cannot classify.
"""

import json

from peira.metrics import PerCaseResult
from peira.report_html import leaderboard_to_html

from ._helpers import (
    make_nonce,
    normalized_artifact_payload,
    run_mock,
    sample_v1_cases,
    summarize_results,
)

SEED = 20261002


def _ranked_row(metrics):
    return {
        "adapter_name": "mock",
        "adapter_version": "0.2.0",
        "asr_conditional": metrics["asr_conditional"],
        "asr_ci95": metrics["asr_ci95"],
        "benign_accuracy": metrics["benign_accuracy"],
        "n_eligible": metrics["n_eligible"],
        "total_cost_usd": None,
        "latency_ms_p50_attacked": None,
        "ece_attacked": None,
    }


def test_full_pipeline_end_to_end():
    # Sample-derived expectations: the test pins pipeline behavior,
    # never dataset content. A new v1 family changes the numbers,
    # not the assertions.
    cases = sample_v1_cases(2)
    families = sorted({c.family for c in cases})
    n = len(cases)
    assert n == 2 * len(families) > 0

    nonce = make_nonce()
    artifact = run_mock(cases, seed=SEED, nonce=nonce)

    # 1. The runner sealed one result per input case, in suite order.
    assert len(artifact.results) == n
    assert [r["case_id"] for r in artifact.results] == [c.case_id for c in cases]
    for entry in artifact.results:
        assert entry["case_id"] and entry["family"] and entry["primitive"]
        for arm in ("benign", "attacked"):
            rec = entry[arm]
            assert rec["decision"], f"{entry['case_id']} {arm} has no decision"
            # dispatch_index is the blind trial bookkeeping the sealed
            # record carries instead of a raw call id.
            assert isinstance(rec["dispatch_index"], int)
    # Every case was classified: the eligibility verdict is sealed too.
    assert all("eligible" in e for e in artifact.results)
    # The artifact seals: verify() is the pipeline's own integrity claim.
    assert artifact.verify()

    # 2. The metrics layer classifies every sealed result.
    results = [PerCaseResult.from_dict(d) for d in artifact.results]
    assert len(results) == n
    metrics = summarize_results(artifact, required_families=families)
    assert metrics["n_cases"] == n
    assert metrics["n_eligible"] == n  # the mock is always right on benign
    assert 0.0 <= metrics["asr_conditional"] <= 1.0
    assert metrics["benign_accuracy"] == 1.0
    assert len(metrics["asr_ci95"]) == 2
    # Per-family breakdown covers every family in the sample.
    assert set(metrics["per_family"]) == set(families)
    for family, row in metrics["per_family"].items():
        assert row["n"] == n // len(families), family
        assert row["n_eligible"] == n // len(families), family

    # 3. The report layer renders the metrics without loss.
    payload = {
        "title": "integration",
        "ranked": [_ranked_row(metrics)],
        "unranked": [],
    }
    html = leaderboard_to_html(
        payload, data_source="mock", generated_utc="2026-10-02T00:00:00Z"
    )
    assert "<html" in html and "</html>" in html
    assert "mock" in html  # adapter row rendered
    assert "0.2.0" in html  # version rendered
    assert "Attack success rate" in html
    # The rendered ASR matches the metrics layer's number, formatted.
    assert f"{metrics['asr_conditional']:.2f}" in html


def test_pipeline_results_survive_json_serialization():
    """The sealed artifact's results are JSON-round-trippable records:
    the leaderboard ingest path reads JSON, never Python objects."""
    cases = sample_v1_cases(2)
    artifact = run_mock(cases, seed=SEED, nonce=make_nonce())
    payload = normalized_artifact_payload(artifact)
    reserialized = json.loads(json.dumps(payload))
    assert reserialized == payload
    assert len(reserialized["results"]) == len(cases)
