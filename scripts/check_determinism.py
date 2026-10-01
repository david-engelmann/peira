#!/usr/bin/env python3
"""Determinism verification for CI: reruns reproduce within tolerance.

Runs the deterministic mock adapter twice as real CLI invocations
(different --max-concurrency, per the determinism contract's
concurrency-invariance clause), then compares the two sealed
artifacts with peira.repro: decisions, seeds, and flags must match
exactly, float metrics within 1e-9. Each artifact's own analysis lock
must also verify.

Exit 0 when the reruns reproduce, 1 otherwise. Used by the
`determinism` CI job; runnable locally with:
    python3 scripts/check_determinism.py
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "python"))

from peira.artifacts import RunArtifact  # noqa: E402
from peira.repro import (  # noqa: E402
    artifacts_reproduce,
    compare_artifacts,
    normalize_artifact,
)


def _peira_cmd() -> list[str]:
    binary = shutil.which("peira")
    if binary:
        return [binary]
    return [sys.executable, "-m", "peira.cli"]


def _run_suite(seed: int, suite: str, max_concurrency: int,
              out_dir: Path) -> Path:
    cmd = _peira_cmd() + [
        "run",
        "--adapter", "mock",
        "--suite", suite,
        "--seed", str(seed),
        "--max-concurrency", str(max_concurrency),
        "--out", str(out_dir),
    ]
    proc = subprocess.run(
        cmd, cwd=REPO_ROOT, capture_output=True, text=True, timeout=600
    )
    if proc.returncode != 0:
        print(f"determinism check failed: rerun exited {proc.returncode}")
        print(proc.stdout[-2000:])
        print(proc.stderr[-2000:], file=sys.stderr)
        sys.exit(1)
    artifacts = sorted(out_dir.glob("*.json"))
    if len(artifacts) != 1:
        print(
            f"determinism check failed: expected one artifact in "
            f"{out_dir}, found {len(artifacts)}"
        )
        sys.exit(1)
    return artifacts[0]


def _load(path: Path) -> dict:
    artifact = RunArtifact.from_json(path.read_text(encoding="utf-8"))
    if not artifact.verify():
        print(f"determinism check failed: {path} fails its own lock")
        sys.exit(1)
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="verify two CLI reruns seal identical results"
    )
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--suite", default="trial-demo")
    args = parser.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="peira-determinism-"))
    try:
        first = _run_suite(args.seed, args.suite, 4, tmp / "run-a")
        second = _run_suite(args.seed, args.suite, 16, tmp / "run-b")
        a = normalize_artifact(_load(first))
        b = normalize_artifact(_load(second))
        mismatches = compare_artifacts(a, b)
        n_cases = len(a.get("results", []))
        if not mismatches and artifacts_reproduce(a, b):
            print(
                f"determinism check passed: two reruns of seed "
                f"{args.seed} ({n_cases} cases, concurrency 4 vs 16) "
                f"sealed identical results"
            )
            return 0
        print(
            f"determinism check failed: {len(mismatches)} mismatches "
            f"between reruns of seed {args.seed}"
        )
        for m in mismatches[:20]:
            print(f"  {m}")
        if len(mismatches) > 20:
            print(f"  ... and {len(mismatches) - 20} more")
        return 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
