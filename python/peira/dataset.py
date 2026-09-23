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
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from peira.schema import validate_case_dict

MANIFEST_NAME = "manifest.json"
CANARY_NAME = "CANARY.txt"
CASE_SUFFIX = ".jsonl"


def _is_case_file(path: Path) -> bool:
    """The canonical case-file predicate.

    A case file is a regular file (following symlinks) whose name ends
    in ``.jsonl``. This ONE predicate is the security invariant behind
    manifest completeness: the runner, ``build_manifest``, and the
    manifest sweep must all agree on what a case file is, or an
    unlisted file could be scored but never flagged. (``Path.suffix``
    is the wrong test here: a file named exactly ``.jsonl`` has an
    empty suffix yet is matched by the runner's old ``*.jsonl`` glob;
    ``name.endswith`` matches glob semantics for every sane name.)
    """
    return path.name.endswith(CASE_SUFFIX) and path.is_file()


def sha256_file(path: Path) -> str:
    """SHA-256 hex digest of a file's bytes."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> Path:
    """Write text to `path` atomically (stdlib only).

    The bytes go to a temp file in the same directory first, then
    `os.replace` swaps it into place: a reader never sees a half-written
    file, even if the process dies mid-write. The temp file must live in
    the same directory — that keeps the replace on one filesystem, which
    is what makes it atomic on POSIX and Windows.

    No locking: concurrent writers race and the last one wins. That is
    the documented contract — callers needing exclusion must lock around
    their own read-modify-write.
    """
    path = Path(path)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent),
                                    prefix=path.name + ".",
                                    suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return path


def _parse_case_line(name: str, lineno: int, line: str) -> dict[str, Any]:
    """Parse and validate one JSONL case line.

    The single home of the parse+validate step, shared by `iter_cases`
    and `_summarize_bytes` so the parse/validate logic is never
    re-implemented per caller. Raises ValueError with a
    `name:lineno:`-prefixed message on invalid JSON or schema
    violations.
    """
    try:
        case = json.loads(line)
    except json.JSONDecodeError as e:
        raise ValueError(f"{name}:{lineno}: invalid JSON ({e})") from e
    errors = validate_case_dict(case)
    if errors:
        raise ValueError(f"{name}:{lineno}: {'; '.join(errors)}") from None
    return case


def iter_cases(dataset_dir: Path):
    """Yield (path, lineno, case_dict) for every valid case in a dataset
    directory.

    The shared case-file walk: open, enumerate, parse, validate — in one
    place instead of re-implemented per caller. Raises ValueError naming
    file and line on the first invalid line (bad JSON or schema
    violation). Callers that must collect *every* error instead of
    failing fast (gates G1) use `iter_case_lines`.
    """
    for path in sorted(dataset_dir.glob(f"*{CASE_SUFFIX}")):
        # Explicit UTF-8: the platform default (e.g. cp1252 on Windows)
        # would silently mojibake non-ASCII case content.
        with open(path, encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                if not line.strip():
                    continue
                yield path, lineno, _parse_case_line(path.name, lineno, line)


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
        # Shared parse+validate (see _parse_case_line): the manifest
        # builder reports per-line problems instead of failing fast.
        try:
            case = _parse_case_line(name, lineno, line)
        except ValueError as e:
            problems.append(str(e))
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
        if _is_case_file(path):
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
    files = manifest["files"]
    if not isinstance(files, dict):
        raise ValueError(
            f"{MANIFEST_NAME} has a malformed 'files' section "
            f"(expected an object, got {type(files).__name__})"
        )
    for name, entry in files.items():
        if not isinstance(entry, dict):
            raise ValueError(
                f"{MANIFEST_NAME}: entry for {name!r} is malformed "
                f"(expected an object, got {type(entry).__name__})"
            )
    return manifest, digest


def read_manifest(dataset_dir: Path) -> dict[str, Any]:
    """Read and minimally validate manifest.json. Raises FileNotFoundError
    when absent and ValueError when unreadable."""
    manifest, _digest = _read_manifest_sealed(dataset_dir)
    return manifest


def _verify_manifest_dict(
    manifest: dict[str, Any], dataset_dir: Path
) -> list[str]:
    """Per-file verification of an already-read manifest, plus a
    directory sweep for unlisted files.

    Every file is read exactly once: the digest and (for case files) the
    parse share the same bytes, so verification can never hash one
    version of a file and summarize another. After the per-entry loop,
    any file on disk that `build_manifest` would include (*.jsonl,
    CANARY.txt) but that the manifest does not list is reported — the
    sweep is what makes "the directory matches the manifest exactly"
    true.
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
    # P0: files build_manifest() would include (*.jsonl case files,
    # CANARY.txt) that are on disk but not listed must be flagged —
    # otherwise unlisted case files would be silently unscored, and the
    # "directory matches the manifest exactly" guarantee would be false.
    # Names are compared as strings only; unlisted files are never
    # opened, so unsafe on-disk names cannot escape the directory.
    listed = set(manifest.get("files", {}).keys())
    for path in sorted(dataset_dir.iterdir()):
        if path.name == MANIFEST_NAME or not path.is_file():
            continue
        if not _is_case_file(path) and path.name != CANARY_NAME:
            continue
        if path.name not in listed:
            errors.append(f"{path.name}: on disk but not listed in manifest")
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
