"""Optional Rust acceleration for peira hot paths (via PyO3).

The compiled extension ``peira._peira_core`` is built from
``crates/peira-core`` (see its README for the build). When the extension
is absent — e.g. a pure-Python install — everything falls back to the
pure-Python reference implementation. Either way ``peira`` keeps zero
third-party *runtime* dependencies: PyO3 is a build-time dependency of
the Rust crate only.

Exposed names (only when ``available`` is True):
    wilson_ci(hits, n, z=1.96) -> (lo, hi)
    mcnemar(b, c) -> float
    brier_score(probs, labels) -> float
    ece(probs, labels, bins=15) -> float
    sha256_hex(data: bytes) -> str

All are bit-exact replacements for ``peira.metrics`` / ``hashlib``;
see ``tests/test_rust_parity.py``. One deliberate difference: the Rust
``ece``/``brier_score`` raise ``ValueError`` on empty or mismatched input
where the pure-Python reference raises ``AssertionError`` (bare assert).
"""

from __future__ import annotations

__all__ = ["available"]

available: bool = False

try:
    from peira._peira_core import (  # type: ignore[import-not-found]
        brier_score,
        ece,
        mcnemar,
        sha256_hex,
        wilson_ci,
    )

    available = True
    __all__ += ["brier_score", "ece", "mcnemar", "sha256_hex", "wilson_ci"]
except ImportError:
    # Extension not built — callers use the pure-Python reference.
    pass
