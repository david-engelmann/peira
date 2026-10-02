"""Optional Rust accelerator.

`peira._core` is the PyO3 extension built from `crates/peira-python`
(maturin is the PEP 517 build backend; `maturin develop` rebuilds it). It is never required: import it here,
and every hot path in `peira.metrics` / `peira.schema` / `peira.gates`
/ `peira.compare` / `peira.runner` / `peira.concurrency` dispatches to it
when present and falls back to the pure-Python reference implementation
otherwise. Both backends compute the same values up to ~1 ulp of float
summation order (see `peira.metrics`); the one larger documented exception
is `paired_bootstrap_ci`, which the Python side never auto-dispatches
because the two PRNGs differ.

Set `PEIRA_NO_RUST=1` to force the pure-Python backend even when the
extension is installed  -  used by the backend-parity tests.

Set `PEIRA_STRICT_RUST=1` to disable the silent fallback for manual
debugging: if the Rust core raises an exception that the dispatch site
would otherwise swallow (typically TypeError/ValueError/OverflowError,
but varies by site), the exception propagates instead of falling back
to Python. This is a debugging tool, not a CI gate: the test suite
intentionally pins fallback behavior for inputs that cannot cross the
PyO3 boundary (e.g. non-JSON values), so the full suite does not pass
under this flag.
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

#: When True, Rust dispatch sites re-raise exceptions instead of silently
#: falling back to the pure-Python reference. Set via PEIRA_STRICT_RUST=1.
#: Manual debugging tool only; the test suite intentionally pins fallback
#: behavior, so CI does not use this flag.
STRICT_RUST: bool = os.environ.get("PEIRA_STRICT_RUST") == "1"
