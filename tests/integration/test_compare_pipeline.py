"""Compare pipeline: two sealed runs pair up for head-to-head analysis.

The compare layer (peira.compare) is only as honest as the artifacts
it pairs. This test runs the pipeline twice with different seeds,
round-trips both artifacts through JSON (the ingest path), and asserts
check_comparable passes, every case pairs, and the comparison carries
real paired counts. It also pins artifact version compatibility: two
v3 artifacts from different runs are mutually comparable, and a
tampered case set is flagged.
"""

import dataclasses
import json

from peira.artifacts import RunArtifact
from peira.compare import check_comparable, compare_artifacts, pair_results

from ._helpers import make_nonce, run_mock, sample_v1_cases

SEED_A = 20261002
SEED_B = 20261003


def _sealed_artifact(seed):
    cases = sample_v1_cases(2)
    artifact = run_mock(cases, seed=seed, nonce=make_nonce())
    assert artifact.verify()
    # The ingest path: JSON round-trip before comparison.
    return RunArtifact.from_json(artifact.to_json())


def test_two_runs_pair_and_compare():
    a = _sealed_artifact(SEED_A)
    b = _sealed_artifact(SEED_B)

    problems = check_comparable(a, b)
    assert problems == [], f"v3 artifacts should be comparable: {problems}"

    pairs, warnings = pair_results(a, b)
    assert warnings == [], f"unexpected pairing warnings: {warnings}"
    assert len(pairs) == 20
    assert all(p.a is not None and p.b is not None for p in pairs)

    comparison = compare_artifacts(a, b, seed=SEED_A)
    assert comparison.n_paired == 20
    assert comparison.n_a == 20 and comparison.n_b == 20
    # The head-to-head table accounts for every pair exactly once.
    h2h = comparison.head_to_head
    assert h2h.both_right + h2h.a_only + h2h.b_only + h2h.both_wrong == 20


def test_compare_rejects_mismatched_case_sets():
    a = _sealed_artifact(SEED_A)
    b = _sealed_artifact(SEED_B)
    # check_comparable guards config-level comparability: a different
    # suite is meaningless to pair.
    other_suite = dataclasses.replace(b, suite="trial-demo")
    problems = check_comparable(a, other_suite)
    assert any("suite" in p for p in problems)
    # Case-set asymmetry is pair_results' job: dropping one result
    # pairs the intersection and reports the asymmetry.
    doc = json.loads(b.to_json())
    doc["results"] = doc["results"][:-1]
    short_b = RunArtifact.from_json(json.dumps(doc))
    pairs, warnings = pair_results(a, short_b)
    assert len(pairs) == 19
    assert warnings, "coverage asymmetry must be reported"
