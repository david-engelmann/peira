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


def _summarize_bytes(name: str, data: bytes) -> dict[str, Any]:
    """Validate JSONL case bytes, count cases, and hash the bytes.

    The SHA-256 and the parse share the single buffer: callers that
    already hold the bytes (verification) never re-read the file.
    """
    digest = hashlib.sha256(data).hexdigest()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ValueError(f"cannot read {name}: {e}") from e
    n_cases = 0
    by_family: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    by_primitive: dict[str, int] = {}
    problems: list[str] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        n_cases += 1
        try:
            case = json.loads(line)
        except json.JSONDecodeError as e:
            problems.append(f"{name}:{lineno}: invalid JSON ({e})")
            continue
        errors = validate_case_dict(case)
        if errors:
            problems.append(f"{name}:{lineno}: {'; '.join(errors)}")
            continue
        by_family[case["family"]] = by_family.get(case["family"], 0) + 1
        by_severity[case["severity"]] = by_severity.get(case["severity"], 0) + 1
        by_primitive[case["primitive"]] = by_primitive.get(case["primitive"], 0) + 1
    if problems:
        raise ValueError("\n".join(problems))
    return {
        "kind": "cases",
        "sha256": digest,
        "n_cases": n_cases,
        "n_by_family": dict(sorted(by_family.items())),
        "n_by_severity": dict(sorted(by_severity.items())),
        "n_by_primitive": dict(sorted(by_primitive.items())),
    }


def summarize_cases(path: Path) -> dict[str, Any]:
    """Validate a JSONL case file and count its cases.

    Returns the manifest entry for the file. Raises ValueError listing
    every invalid line — a dataset never builds on invalid cases.

    The file is read exactly once: the SHA-256 and the parse share the
    single read instead of a hash pass plus a parse pass.
    """
    return _summarize_bytes(path.name, path.read_bytes())


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


def _is_unsafe_manifest_name(name: str) -> bool:
    """True when a manifest file name must not touch the filesystem.

    Manifest-controlled paths are a trust boundary: the manifest names
    files and verification hashes them. `..`, separators, and absolute
    paths would escape the dataset root via `dataset_dir / name`
    (verified: a `../` entry hashed a file outside the suite). This is
    conservative — a literally-on-disk `a..b.jsonl` trips it too — but
    case files are `<id>.jsonl` and never look like that.
    """
    return (
        not name
        or ".." in name
        or "/" in name
        or "\\" in name
        or Path(name).is_absolute()
    )


def _read_manifest_sealed(dataset_dir: Path) -> tuple[dict[str, Any], str]:
    """Read manifest.json once, returning (manifest, sha256_hex).

    The digest is computed over the same bytes that are parsed, so a
    manifest swapped between a verify pass and a re-read can never seal
    unverified bytes into an analysis lock.
    """
    path = dataset_dir / MANIFEST_NAME
    if not path.is_file():
        raise FileNotFoundError(f"no {MANIFEST_NAME} in {dataset_dir}")
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ValueError(f"{MANIFEST_NAME} is not valid UTF-8 ({e})") from e
    try:
        manifest = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"{MANIFEST_NAME} is not valid JSON ({e})") from e
    if not isinstance(manifest, dict) or "files" not in manifest:
        raise ValueError(f"{MANIFEST_NAME} is missing the 'files' section")
    return manifest, digest


def read_manifest(dataset_dir: Path) -> dict[str, Any]:
    """Read and minimally validate manifest.json. Raises FileNotFoundError
    when absent and ValueError when unreadable."""
    manifest, _digest = _read_manifest_sealed(dataset_dir)
    return manifest


def _verify_manifest_dict(
    manifest: dict[str, Any], dataset_dir: Path
) -> list[str]:
    """Per-file verification of an already-read manifest.

    Every file is read exactly once: the digest and (for case files) the
    parse share the same bytes, so verification can never hash one
    version of a file and summarize another.
    """
    errors: list[str] = []
    for name, entry in manifest.get("files", {}).items():
        if _is_unsafe_manifest_name(name):
            errors.append(
                f"{name}: unsafe file name in manifest "
                "(path separators, '..', and absolute paths are not allowed)"
            )
            continue
        path = dataset_dir / name
        if not path.is_file():
            errors.append(f"{name}: listed in manifest but missing on disk")
            continue
        # Single read: the digest and the parse below share these bytes.
        data = path.read_bytes()
        actual = hashlib.sha256(data).hexdigest()
        if actual != entry.get("sha256"):
            errors.append(f"{name}: sha256 mismatch "
                          f"(manifest {str(entry.get('sha256'))[:12]}…, "
                          f"disk {actual[:12]}…)")
            continue
        if entry.get("kind") == "cases":
            try:
                summary = _summarize_bytes(path.name, data)
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


def verify_manifest_sealed(
    dataset_dir: Path,
) -> tuple[dict[str, Any], str, list[str]]:
    """Verify the manifest, returning (manifest, manifest_sha256, errors).

    Single read: the manifest bytes are hashed and parsed from one read,
    so a digest sealed into a run's analysis lock is always the digest of
    the verified bytes — never of a re-read that raced a swap.
    """
    manifest, digest = _read_manifest_sealed(dataset_dir)
    return manifest, digest, _verify_manifest_dict(manifest, dataset_dir)


def verify_manifest(dataset_dir: Path) -> list[str]:
    """Check a dataset directory against its manifest.json.

    Returns a list of mismatch descriptions; empty means the directory
    matches the manifest exactly.
    """
    _manifest, _digest, errors = verify_manifest_sealed(dataset_dir)
    return errors
