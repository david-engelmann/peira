"""Parity: Rust-via-PyO3 vs the pure-Python reference implementation.

Compares ``peira._rust`` (the compiled ``peira._peira_core`` extension)
against the pure-Python functions in ``python/peira/metrics.py`` loaded
directly from source with the Rust override disabled (``PEIRA_PURE_PYTHON=1``
+ a distinct module name, so the already-imported ``peira.metrics`` is
undisturbed).

Skips entirely when the extension isn't built — pure-Python CI stays green.

The claim under test is bit-exactness: IEEE-754 double ops in the same
order, so randomized comparisons assert ``==``, not approximate equality.
"""

import hashlib
import importlib.util
import math
import os
import random
import sys
from pathlib import Path

import pytest

from peira import _rust

if not _rust.available:
    pytest.skip("Rust extension not built (peira._peira_core missing)",
                allow_module_level=True)


def _load_pure_metrics():
    """Load metrics.py from source with the Rust override force-disabled."""
    os.environ["PEIRA_PURE_PYTHON"] = "1"
    try:
        path = (
            Path(__file__).resolve().parents[1]
            / "python"
            / "peira"
            / "metrics.py"
        )
        spec = importlib.util.spec_from_file_location("_peira_metrics_pure", path)
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        sys.modules["_peira_metrics_pure"] = mod
        spec.loader.exec_module(mod)
        return mod
    finally:
        os.environ.pop("PEIRA_PURE_PYTHON", None)


pure = _load_pure_metrics()


# --- Fixed vectors (also covered by the Rust-side parity tests) ------------

def test_wilson_ci_fixed():
    assert _rust.wilson_ci(80, 100) == pure.wilson_ci(80, 100)
    assert _rust.wilson_ci(80, 100) == (0.7111690380734977, 0.8666340774409013)
    assert _rust.wilson_ci(0, 0) == pure.wilson_ci(0, 0) == (0.0, 0.0)
    assert _rust.wilson_ci(100, 100) == pure.wilson_ci(100, 100)
    assert _rust.wilson_ci(0, 100) == pure.wilson_ci(0, 100)
    assert _rust.wilson_ci(1, 1) == pure.wilson_ci(1, 1)


def test_mcnemar_fixed():
    assert _rust.mcnemar(10, 5) == pure.mcnemar(10, 5) == 1.6666666666666667
    assert _rust.mcnemar(0, 0) == pure.mcnemar(0, 0) == 0.0
    assert _rust.mcnemar(0, 7) == pure.mcnemar(0, 7)


def test_brier_score_fixed():
    assert _rust.brier_score([0.5, 0.5], [0, 1]) == pure.brier_score([0.5, 0.5], [0, 1]) == 0.25
    assert _rust.brier_score([0.0, 1.0], [0, 1]) == pure.brier_score([0.0, 1.0], [0, 1]) == 0.0


def test_ece_fixed():
    assert _rust.ece([0.0, 0.0, 1.0, 1.0], [0, 0, 1, 1]) == 0.0
    # p = 1/15 sits exactly on a bin edge -> lower bin (bin 0, closed left)
    assert _rust.ece([1.0 / 15.0], [1]) == pure.ece([1.0 / 15.0], [1])
    # out-of-range probs are dropped by both implementations
    assert _rust.ece([-0.5, 1.5, 0.5], [0, 1, 1]) == pure.ece([-0.5, 1.5, 0.5], [0, 1, 1])


def test_sha256_hex_fixed():
    assert _rust.sha256_hex(b"") == hashlib.sha256(b"").hexdigest()
    assert _rust.sha256_hex(b"hello") == hashlib.sha256(b"hello").hexdigest()
    assert _rust.sha256_hex(b"\x00\xff" * 100) == hashlib.sha256(b"\x00\xff" * 100).hexdigest()


# --- Randomized bit-exact cross-checks --------------------------------------

def _rand_probs_labels(rng, n):
    probs = [rng.random() for _ in range(n)]
    # sprinkle edge values: exact 0.0, 1.0, and bin edges
    for i in range(0, n, 7):
        probs[i] = rng.choice([0.0, 1.0, 1 / 15, 7 / 15, 14 / 15])
    labels = [rng.choice([0, 1]) for _ in range(n)]
    return probs, labels


def test_wilson_ci_randomized():
    rng = random.Random(20260924)
    for _ in range(300):
        n = rng.randint(0, 100000)
        hits = rng.randint(0, n) if n else 0
        assert _rust.wilson_ci(hits, n) == pure.wilson_ci(hits, n)
        # non-default z exercises the default-arg plumbing too
        assert _rust.wilson_ci(hits, n, 2.58) == pure.wilson_ci(hits, n, 2.58)


def test_mcnemar_randomized():
    rng = random.Random(20260924)
    for _ in range(300):
        b, c = rng.randint(0, 5000), rng.randint(0, 5000)
        assert _rust.mcnemar(b, c) == pure.mcnemar(b, c)


def test_brier_score_randomized():
    rng = random.Random(20260924)
    for _ in range(200):
        probs, labels = _rand_probs_labels(rng, rng.randint(1, 500))
        assert _rust.brier_score(probs, labels) == pure.brier_score(probs, labels)


def test_ece_randomized():
    rng = random.Random(20260924)
    for _ in range(200):
        probs, labels = _rand_probs_labels(rng, rng.randint(1, 500))
        assert _rust.ece(probs, labels) == pure.ece(probs, labels)
        bins = rng.choice([5, 10, 15, 20])
        assert _rust.ece(probs, labels, bins) == pure.ece(probs, labels, bins)


def test_sha256_hex_randomized():
    rng = random.Random(20260924)
    for _ in range(100):
        data = bytes(rng.randint(0, 255) for _ in range(rng.randint(0, 2000)))
        assert _rust.sha256_hex(data) == hashlib.sha256(data).hexdigest()


# --- Error behavior ----------------------------------------------------------

def test_empty_input_errors():
    # Deliberate, documented difference: Rust raises ValueError, the
    # pure-Python reference raises AssertionError (bare assert). Both
    # signal programmer error; ValueError is the better-behaved one.
    with pytest.raises(ValueError):
        _rust.ece([], [])
    with pytest.raises(ValueError):
        _rust.brier_score([0.5], [0, 1])
    with pytest.raises(AssertionError):
        pure.ece([], [])
    with pytest.raises(AssertionError):
        pure.brier_score([0.5], [0, 1])


# --- Wiring: metrics.py actually uses the Rust functions ---------------------

def test_metrics_module_uses_rust_when_available():
    import peira.metrics as m

    assert m.wilson_ci is _rust.wilson_ci
    assert m.ece is _rust.ece
    assert m.brier_score is _rust.brier_score
    assert m.mcnemar is _rust.mcnemar


def test_artifact_lock_uses_rust_sha256():
    """RunArtifact.compute_lock must match the pre-Rust golden value."""
    from peira.artifacts import RunArtifact

    a = RunArtifact(adapter_name="mock", suite="trial-demo")
    a.config = {"k": "v"}
    a.results = [{"case_id": "x"}]
    lock = a.compute_lock()
    # Golden value from hashlib (verified before the Rust wiring landed).
    # metrics and adapter_version are lock-covered (P0-1, P1-5b):
    # a.metrics defaults to {}, a.adapter_version defaults to "", both in
    # the payload. Old artifacts (neither in lock) will fail verify().
    expected = hashlib.sha256(
        '{"adapter_name": "mock", "adapter_version": "", '
        '"config": {"k": "v"}, '
        '"dataset_version": "0.1.0-demo", "metrics": {}, '
        '"peira_version": "0.1.0", '
        '"results": [{"case_id": "x"}], "suite": "trial-demo"}'.encode()
    ).hexdigest()
    assert lock == expected


def test_artifact_lock_detects_metric_tampering():
    """P0-1 regression: rewriting metrics must invalidate the lock."""
    from peira.artifacts import RunArtifact

    a = RunArtifact(adapter_name="mock", suite="trial-demo")
    a.results = [{"case_id": "x"}]
    a.metrics = {"benign_accuracy": 0.5, "asr_conditional": 0.25}
    a.seal()
    assert a.verify()
    # Forged headline numbers, exactly the P0-1 attack:
    a.metrics = {"benign_accuracy": 1.0, "asr_conditional": 0.0}
    assert not a.verify()


# ---------------------------------------------------------------------------
# Edge cases: adversarial summation, bin edges, special values


def test_brier_score_adversarial_cancellation():
    """Catastrophic-cancellation-prone inputs: Rust must match math.fsum bit-exactly."""
    pytest.importorskip("peira._peira_core", reason="extension not built")
    from peira import _rust
    rng = random.Random(777)
    for trial in range(100):
        n = rng.randint(1, 300)
        scale = 10 ** rng.randint(-8, 8)
        probs = [min(1.0, max(0.0, (rng.random() - 0.5) * scale)) for _ in range(n)]
        labels = [rng.choice([0, 1]) for _ in range(n)]
        assert _rust.brier_score(probs, labels) == pure.brier_score(probs, labels)


def test_ece_bin_edge_doubles():
    """Probabilities exactly on edge doubles must land in the lower bin, like Python."""
    pytest.importorskip("peira._peira_core", reason="extension not built")
    from peira import _rust
    for bins in (5, 10, 15, 20):
        probs = [k / bins for k in range(bins + 1)]  # exact edge doubles
        labels = [k % 2 for k in range(bins + 1)]
        assert _rust.ece(probs, labels, bins) == pure.ece(probs, labels, bins)
        # plus jittered copies just inside each edge
        eps = 1e-12
        probs2 = [k / bins + eps for k in range(bins)]
        labels2 = [0] * bins
        assert _rust.ece(probs2, labels2, bins) == pure.ece(probs2, labels2, bins)


def test_ece_out_of_range_and_signed_zero():
    """Out-of-range probs are dropped but counted; -0.0 behaves like 0.0."""
    pytest.importorskip("peira._peira_core", reason="extension not built")
    from peira import _rust
    probs = [-0.5, -0.0, 0.0, 0.5, 1.0, 1.5, float("nan")]
    labels = [0, 0, 1, 1, 0, 1, 0]
    assert _rust.ece(probs, labels, 15) == pure.ece(probs, labels, 15)


def test_brier_ece_special_floats():
    """NaN/inf policy matches the reference (no crash, same value)."""
    pytest.importorskip("peira._peira_core", reason="extension not built")
    from peira import _rust
    for probs in ([float("nan"), 0.5], [float("inf"), 0.5]):
        labels = [0] * len(probs)
        r, p = _rust.brier_score(probs, labels), pure.brier_score(probs, labels)
        assert (r == p) or (math.isnan(r) and math.isnan(p)), (probs, r, p)
        r, p = _rust.ece(probs, labels, 15), pure.ece(probs, labels, 15)
        assert (r == p) or (math.isnan(r) and math.isnan(p)), (probs, r, p)
    # Squared-term overflow: Python's `(p - y) ** 2` raises OverflowError;
    # the Rust binding raises OverflowError too (not a silent inf).
    with pytest.raises(OverflowError):
        pure.brier_score([1e308, 1e308, 1e308], [0, 0, 0])
    with pytest.raises(OverflowError):
        _rust.brier_score([1e308, 1e308, 1e308], [0, 0, 0])
