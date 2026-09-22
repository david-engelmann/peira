"""Dataset build tooling: manifests, content hashes, versioning.

A peira dataset directory holds versioned case files plus a manifest.json
that locks their exact contents. The manifest is the dataset's build
receipt: any case added, changed, or removed produces a new dataset version
with a new manifest — manifests are never edited in place.

Only the standard library is used, keeping the base package
dependency-free.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from peira.schema import validate_case_dict

MANIFEST_NAME = "manifest.json"
CANARY_NAME = "CANARY.txt"
CASE_SUFFIX = ".jsonl"


def sha256_file(path: Path) -> str:
    """SHA-256 hex digest of a file's bytes."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def iter_case_lines(dataset_dir: Path):
    """Yield (path, lineno, case_dict_or_None, json_error_or_None) for
    every non-blank line of every ``*.jsonl`` file in the dataset
    directory root."""
    for path in sorted(dataset_dir.glob(f"*{CASE_SUFFIX}")):
        with open(path, encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                if not line.strip():
                    continue
                try:
                    yield path, lineno, json.loads(line), None
                except json.JSONDecodeError as e:
                    yield path, lineno, None, f"invalid JSON ({e})"


def summarize_cases(path: Path) -> dict[str, Any]:
    """Validate a JSONL case file and count its cases.

    Returns the manifest entry for the file. Raises ValueError listing
    every invalid line — a dataset never builds on invalid cases.
    """
    n_cases = 0
    by_family: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    by_primitive: dict[str, int] = {}
    problems: list[str] = []
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            if not line.strip():
                continue
            n_cases += 1
            try:
                case = json.loads(line)
            except json.JSONDecodeError as e:
                problems.append(f"{path.name}:{lineno}: invalid JSON ({e})")
                continue
            errors = validate_case_dict(case)
            if errors:
                problems.append(f"{path.name}:{lineno}: {'; '.join(errors)}")
                continue
            by_family[case["family"]] = by_family.get(case["family"], 0) + 1
            by_severity[case["severity"]] = by_severity.get(case["severity"], 0) + 1
            by_primitive[case["primitive"]] = by_primitive.get(case["primitive"], 0) + 1
    if problems:
        raise ValueError("\n".join(problems))
    return {
        "kind": "cases",
        "sha256": sha256_file(path),
        "n_cases": n_cases,
        "n_by_family": dict(sorted(by_family.items())),
        "n_by_severity": dict(sorted(by_severity.items())),
        "n_by_primitive": dict(sorted(by_primitive.items())),
    }


def build_manifest(dataset_dir: Path, dataset_version: str,
                   dataset_name: str = "peira-v1",
                   peira_version: str = "") -> dict[str, Any]:
    """Build the manifest dict for a dataset directory.

    Every ``*.jsonl`` file in the directory root is treated as a case file
    (validated and counted); ``CANARY.txt`` is hashed as an artifact.
    ``manifest.json`` itself is never included. Raises FileNotFoundError
    when the directory is missing and ValueError on invalid cases.
    """
    if not dataset_dir.is_dir():
        raise FileNotFoundError(f"dataset directory {dataset_dir} not found")
    files: dict[str, Any] = {}
    for path in sorted(dataset_dir.iterdir()):
        if path.name == MANIFEST_NAME or not path.is_file():
            continue
        if path.suffix == CASE_SUFFIX:
            files[path.name] = summarize_cases(path)
        elif path.name == CANARY_NAME:
            files[path.name] = {"kind": "artifact", "sha256": sha256_file(path)}
    generator = f"peira {peira_version}".strip() if peira_version else "peira"
    return {
        "dataset": dataset_name,
        "dataset_version": dataset_version,
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "generator": generator,
        "files": files,
    }


def write_manifest(dataset_dir: Path, manifest: dict[str, Any]) -> Path:
    """Write manifest.json deterministically (sorted keys)."""
    out = dataset_dir / MANIFEST_NAME
    out.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    return out


def read_manifest(dataset_dir: Path) -> dict[str, Any]:
    """Read and minimally validate manifest.json. Raises FileNotFoundError
    when absent and ValueError when unreadable."""
    path = dataset_dir / MANIFEST_NAME
    if not path.is_file():
        raise FileNotFoundError(f"no {MANIFEST_NAME} in {dataset_dir}")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"{MANIFEST_NAME} is not valid JSON ({e})")
    if not isinstance(manifest, dict) or "files" not in manifest:
        raise ValueError(f"{MANIFEST_NAME} is missing the 'files' section")
    return manifest


def verify_manifest(dataset_dir: Path) -> list[str]:
    """Check a dataset directory against its manifest.json.

    Returns a list of mismatch descriptions; empty means the directory
    matches the manifest exactly.
    """
    manifest = read_manifest(dataset_dir)
    errors: list[str] = []
    for name, entry in manifest.get("files", {}).items():
        path = dataset_dir / name
        if not path.is_file():
            errors.append(f"{name}: listed in manifest but missing on disk")
            continue
        actual = sha256_file(path)
        if actual != entry.get("sha256"):
            errors.append(f"{name}: sha256 mismatch "
                          f"(manifest {str(entry.get('sha256'))[:12]}…, "
                          f"disk {actual[:12]}…)")
            continue
        if entry.get("kind") == "cases":
            try:
                summary = summarize_cases(path)
            except ValueError as e:
                errors.append(f"{name}: {e}")
                continue
            for key in ("n_cases", "n_by_family", "n_by_severity",
                        "n_by_primitive"):
                if summary[key] != entry.get(key):
                    errors.append(
                        f"{name}: {key} changed "
                        f"(manifest {entry.get(key)}, disk {summary[key]})")
    return errors
