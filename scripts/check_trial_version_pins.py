#!/usr/bin/env python3
"""Fail if any docs pin of the Trial manifest version disagrees with the manifest.

The branded Trial's dataset_version lives in dataset/trial/manifest.json.
Several docs files pin that version in prose; a manifest bump must update
every pin or the docs lie. PR #201 missed dataset/README.md:7, so this
check diffs the pins against the manifest mechanically.

Each entry in PINS is a (file, regex) pair whose capture group 1 must equal
the manifest's dataset_version, and must appear at least once per file.
Files that legitimately mention old versions (CHANGELOG.md, the historical
D-records in docs/Decisions.md, CLI examples, error-string docs) are
deliberately not registered.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

VERSION_RE = r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?"

# (relative path, regex with capture group 1 = the pinned version)
PINS: list[tuple[str, str]] = [
    ("dataset/README.md", rf"manifest `({VERSION_RE})`"),
    ("dataset/trial/README.md", rf"per-primitive counts\), version ({VERSION_RE})"),
    ("docs/Dataset.md", rf"manifest sealed at ({VERSION_RE})"),
    ("docs/Glossary.md", rf"Manifest `({VERSION_RE})`"),
    ("docs/Troubleshooting.md", rf"sealed `({VERSION_RE})`"),
]


def manifest_path() -> pathlib.Path:
    return REPO_ROOT / "dataset" / "trial" / "manifest.json"


def manifest_version() -> str:
    try:
        data = json.loads(manifest_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read trial manifest: {exc}") from exc
    version = data.get("dataset_version")
    if not isinstance(version, str) or not re.fullmatch(VERSION_RE, version):
        raise ValueError(
            f"{manifest_path()} has no valid dataset_version: {version!r}"
        )
    return version


def check() -> tuple[str, list[str]]:
    """Return (manifest version, problem strings); empty problems means in sync."""
    try:
        expected = manifest_version()
    except ValueError as exc:
        return "", [str(exc)]
    problems: list[str] = []
    for rel, pattern in PINS:
        path = REPO_ROOT / rel
        if not path.is_file():
            problems.append(f"{rel}: file missing")
            continue
        text = path.read_text(encoding="utf-8")
        hits = re.findall(pattern, text)
        if not hits:
            problems.append(
                f"{rel}: no trial-manifest version pin found "
                f"(pattern {pattern!r} did not match)"
            )
            continue
        for hit in hits:
            if hit != expected:
                problems.append(
                    f"{rel}: pins trial version {hit}, "
                    f"manifest says {expected}"
                )
    return expected, problems


def main() -> int:
    expected, problems = check()
    for problem in problems:
        print(f"trial-pin-lint: {problem}", file=sys.stderr)
    if problems:
        print(
            f"trial-pin-lint: {len(problems)} stale trial version pin(s); "
            "update the docs pins to match dataset/trial/manifest.json",
            file=sys.stderr,
        )
        return 1
    print(f"trial-pin-lint: all pins match manifest ({expected})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
