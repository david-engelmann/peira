"""Pipeline-level backend parity: the Rust accelerator and the pure
Python reference compute identical sealed results and metrics.

Function-level parity tests already compare each dispatched function
against its ``_xxx_py`` twin. This test goes one level up: it runs the
entire pipeline (load -> run_suite -> metrics -> seal) twice in
separate processes -- once with the compiled backend, once with
``PEIRA_NO_RUST=1`` -- and asserts the normalized sealed payloads are
byte-identical. A backend that diverges anywhere in the pipeline
(a different summation order in metrics, a different hash in the
runner, a different default in the artifact) fails here even if every
unit-level parity test passes.

The subprocesses are the honest mechanism: ``PEIRA_NO_RUST`` is read
at import time, so one process cannot run both backends.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ._helpers import ROOT

SEED = 20261002

#: The driver is deliberately self-contained: it imports only peira and
#: the integration helpers, takes (out_path, seed, nonce), and writes
#: the normalized parity payload as JSON.
_DRIVER_TEMPLATE = """
import json, sys
sys.path.insert(0, {root!r})
from tests.integration._helpers import (
    normalized_artifact_payload, run_mock, sample_v1_cases,
)
out_path, seed, nonce = sys.argv[1], int(sys.argv[2]), sys.argv[3]
cases = sample_v1_cases(2)
artifact = run_mock(cases, seed=seed, nonce=nonce)
payload = normalized_artifact_payload(artifact)
with open(out_path, "w") as f:
    json.dump(payload, f, sort_keys=True)
"""

_DRIVER = _DRIVER_TEMPLATE.format(root=str(ROOT))


def _run_pipeline(env_extra: dict, seed: int, nonce: str) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        out_path = str(Path(tmp) / "payload.json")
        env = dict(os.environ)
        env.update(env_extra)
        proc = subprocess.run(
            [sys.executable, "-c", _DRIVER, out_path, str(seed), nonce],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert proc.returncode == 0, f"driver failed:\n{proc.stderr[-2000:]}"
        with open(out_path) as f:
            return json.load(f)


def test_pipeline_backend_parity():
    """Same seed, same cases, same nonce: Rust-active and PEIRA_NO_RUST=1
    produce identical sealed results and metrics."""
    from peira._rust import RUST_AVAILABLE

    if not RUST_AVAILABLE:
        raise unittest.SkipTest("Rust backend not built; nothing to compare")

    nonce = f"parity-{SEED}"
    rust_payload = _run_pipeline({}, SEED, nonce)
    py_payload = _run_pipeline({"PEIRA_NO_RUST": "1"}, SEED, nonce)

    assert rust_payload["verify"] and py_payload["verify"]
    assert rust_payload["results"] == py_payload["results"], (
        "sealed per-case results differ between backends"
    )
    assert rust_payload["metrics"] == py_payload["metrics"], (
        "metrics summaries differ between backends"
    )
