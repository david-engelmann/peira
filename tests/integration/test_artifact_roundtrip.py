"""Artifact round-trip: a sealed run survives serialization and detects
tampering.

The artifact is the unit the leaderboard ingests and the lock is the
trust model. These tests prove: (1) to_json -> from_json -> verify is
lossless for everything the pipeline promises; (2) any post-hoc edit
breaks the seal; (3) old schema versions are rejected with a clear
error instead of silently misread; (4) the analysis lock binds the
seed, so two runs with different seeds cannot share a lock.
"""

import json

from peira.artifacts import RunArtifact

from ._helpers import make_nonce, run_mock, sample_v1_cases

SEED = 20261002


def _artifact(seed=SEED, nonce=None):
    cases = sample_v1_cases(2)
    return run_mock(cases, seed=seed, nonce=nonce or make_nonce())


def test_roundtrip_is_lossless():
    art = _artifact()
    restored = RunArtifact.from_json(art.to_json())
    assert restored.verify()
    assert restored.results == art.results
    assert restored.compute_lock() == art.compute_lock()
    assert restored.seed == SEED


def test_write_to_disk_and_read_back():
    """The actual ingest path: the artifact is written to a file and
    read back, not just round-tripped in memory."""
    import tempfile
    from pathlib import Path

    art = _artifact()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "run.json"
        path.write_text(art.to_json())
        restored = RunArtifact.from_json(path.read_text())
    assert restored.verify()
    assert restored.results == art.results
    assert restored.compute_lock() == art.compute_lock()


def test_tampered_artifact_fails_verification():
    art = _artifact()
    doc = json.loads(art.to_json())
    # Flip one decision in one record: a post-hoc edit.
    doc["results"][0]["attacked"]["decision"] = "tampered-decision"
    tampered = RunArtifact.from_json(json.dumps(doc))
    assert not tampered.verify()


def test_old_schema_versions_rejected():
    art = _artifact()
    for old_version in ("1", "2"):
        doc = json.loads(art.to_json())
        doc["artifact_version"] = old_version
        try:
            RunArtifact.from_json(json.dumps(doc))
        except Exception as exc:
            assert "version" in str(exc).lower(), f"v{old_version}: {exc}"
        else:
            raise AssertionError(f"artifact_version {old_version} was accepted")


def test_lock_binds_seed():
    import dataclasses

    # Pin run_id so the comparison isolates the seed: the lock covers
    # both seed (artifacts.py) and run_id (uuid4 per run), so without
    # pinning, a seed-vs-seed+1 comparison differs in both inputs and
    # cannot prove the seed is bound.
    a = dataclasses.replace(_artifact(seed=SEED), run_id="pinned-run-id")
    b = dataclasses.replace(_artifact(seed=SEED + 1), run_id="pinned-run-id")
    assert a.compute_lock() != b.compute_lock()
    # The lock also binds the run identity: two runs with identical
    # inputs get distinct run_ids (uuid4) and therefore distinct locks.
    # A lock is the fingerprint of one specific sealed run, not of a
    # seed value. Same content -> same lock is covered by
    # test_roundtrip_is_lossless (from_json recomputes the identical
    # lock over identical content).
    c = _artifact(seed=SEED)
    assert a.compute_lock() != c.compute_lock()
