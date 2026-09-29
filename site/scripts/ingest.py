#!/usr/bin/env python3
"""Ingest sealed peira run artifacts into site-data JSON.

Reads v2 ``RunArtifact`` files, verifies each analysis lock, and emits
the site-data JSON described in ``site/SITE_DATA_SCHEMA.md``.

Mock discipline (mechanical, not conventional): ``--mock`` ingests ONLY
artifacts whose ``config.mock`` is true; without ``--mock`` any mock
artifact is rejected. Real and mock never mix in one build.

Usage:
    python3 site/scripts/ingest.py [--mock] <artifacts_dir> --out <results.json>
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "python"))

from peira import __version__ as peira_version  # noqa: E402
from peira.artifacts import RunArtifact  # noqa: E402

SCHEMA_VERSION = "1"


def fail(msg: str) -> "NoReturn":
    print(f"ingest: error: {msg}", file=sys.stderr)
    raise SystemExit(1)


def load_artifact(path: Path, allow_mock: bool) -> RunArtifact:
    try:
        artifact = RunArtifact.from_json(path.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"{path.name}: cannot parse as RunArtifact: {exc}")
    if artifact.artifact_version != "2":
        fail(f"{path.name}: artifact_version {artifact.artifact_version!r} != '2'")
    if not artifact.verify():
        fail(f"{path.name}: analysis lock does NOT verify (tampered or hand-edited?)")
    is_mock = bool(artifact.config.get("mock"))
    if allow_mock and not is_mock:
        fail(f"{path.name}: --mock given but artifact is not marked mock")
    if not allow_mock and is_mock:
        fail(f"{path.name}: mock artifact rejected without --mock")
    if artifact.suite not in ("public", "holdout"):
        fail(f"{path.name}: suite {artifact.suite!r} must be 'public' or 'holdout'")
    if not isinstance(artifact.metrics, dict) or not artifact.metrics:
        fail(f"{path.name}: artifact carries no sealed metrics")
    return artifact


def trim_case(entry: dict) -> dict:
    return {
        "case_id": entry["case_id"],
        "family": entry["family"],
        "severity": entry["severity"],
        "primitive": entry["primitive"],
        "benign_decision": entry["benign"]["decision"],
        "attacked_decision": entry["attacked"]["decision"],
        "flipped": entry["flipped"],
        "eligible": entry["eligible"],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest peira artifacts into site data.")
    ap.add_argument("artifacts_dir", help="directory of RunArtifact JSON files")
    ap.add_argument("--out", required=True, help="output site-data JSON path")
    ap.add_argument("--mock", action="store_true", help="ingest mock artifacts only")
    args = ap.parse_args()

    adir = Path(args.artifacts_dir)
    if not adir.is_dir():
        fail(f"not a directory: {adir}")
    files = sorted(adir.glob("*.json"))
    if not files:
        fail(f"no artifact JSON files in {adir}")

    runs = []
    dataset_versions = set()
    manifest_shas = set()
    for path in files:
        a = load_artifact(path, args.mock)
        dataset_versions.add(a.dataset_version)
        manifest_shas.add(a.manifest_sha256)
        runs.append(
            {
                "adapter_name": a.adapter_name,
                "adapter_version": a.adapter_version,
                "model_class": a.model_class,
                "suite": a.suite,
                "dataset_version": a.dataset_version,
                "created_utc": a.created_utc,
                "analysis_lock": a.analysis_lock,
                "ranking_eligible": bool(a.metrics.get("ranking_eligible", False)),
                "eligibility_notes": list(a.metrics.get("eligibility_notes", [])),
                "metrics": a.metrics,
                "cases": [trim_case(e) for e in a.results],
            }
        )

    if len(dataset_versions) != 1:
        fail(f"runs disagree on dataset_version: {sorted(dataset_versions)}")
    runs.sort(key=lambda r: (r["suite"], r["adapter_name"]))

    site_data = {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "mock_data": bool(args.mock),
        "peira_version": peira_version,
        "dataset": {
            "name": "peira-v1",
            "version": next(iter(dataset_versions)),
            "manifest_sha256": next(iter(manifest_shas)),
        },
        "runs": runs,
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(site_data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"ingest: {len(runs)} run(s), mock={args.mock}, "
        f"dataset={site_data['dataset']['version']} -> {out}"
    )


if __name__ == "__main__":
    main()
