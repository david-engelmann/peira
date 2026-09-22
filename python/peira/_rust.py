"""Optional Rust accelerator.

`peira._core` is the PyO3 extension built from `crates/peira-python`
(see `scripts/build_core_ext.py`). It is never required: import it here,
and every hot path in `peira.metrics` / `peira.schema` dispatches to it
when present and falls back to the pure-Python reference implementation
otherwise. Both backends compute the same values up to ~1 ulp of float
summation order (see `peira.metrics`); the one larger documented exception
is `paired_bootstrap_ci`, which the Python side never auto-dispatches
because the two PRNGs differ.

Set `PEIRA_NO_RUST=1` to force the pure-Python backend even when the
extension is installed — used by the backend-parity tests.
"""

from __future__ import annotations

import os

try:
    if os.environ.get("PEIRA_NO_RUST"):
        raise ImportError("PEIRA_NO_RUST is set")
    from peira import _core as _impl
except ImportError:
    _impl = None

#: True when the compiled Rust core is importable in this environment.
RUST_AVAILABLE: bool = _impl is not None
