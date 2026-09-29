#!/usr/bin/env python3
"""Enforce Contributing.md checklist item 5: dataset changes must bump the
dataset version and add a CHANGELOG entry.

Usage: python3 scripts/check_dataset_version_bump.py <base-sha> [head-sha]

When any dataset case file changed between base and head, this fails
unless (a) that dataset's manifest.json carries a bumped dataset_version
and (b) CHANGELOG.md was touched in the same range. Case-file-only PRs
that skip both merge red instead of green.

Exits 0 when no case files changed (nothing to enforce).
"""

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Dataset root -> manifest carrying its dataset_version.
DATASETS = {
    "dataset/trial": "dataset/trial/manifest.json",
    "dataset/v1": "dataset/v1/cases/manifest.json",
    "dataset/v2": "dataset/v2/cases/manifest.json",
    "dataset/safety-policy": "dataset/safety-policy/cases/manifest.json",
}

# Case-file globs per dataset (relative to repo root).
CASE_PATTERNS = {
    "dataset/trial": ["dataset/trial/cases.jsonl"],
    "dataset/v1": ["dataset/v1/cases/"],
    "dataset/v2": ["dataset/v2/cases/"],
    "dataset/safety-policy": ["dataset/safety-policy/cases/"],
}


def git(*args):
    return subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout


def changed_files(base, head):
    out = git("diff", "--name-only", f"{base}...{head}")
    return [line for line in out.splitlines() if line.strip()]


def is_case_file(dataset, path):
    for pattern in CASE_PATTERNS[dataset]:
        if pattern.endswith("/"):
            if path.startswith(pattern) and path.endswith(".jsonl"):
                return True
        elif path == pattern:
            return True
    return False


def manifest_version_at(ref, rel):
    try:
        out = git("show", f"{ref}:{rel}")
    except subprocess.CalledProcessError:
        return None  # manifest is new in this range: counts as a bump
    try:
        return json.loads(out).get("dataset_version")
    except (json.JSONDecodeError, AttributeError):
        return None


def main():
    if len(sys.argv) < 2:
        print("usage: check_dataset_version_bump.py <base-sha> [head-sha]")
        return 2
    base = sys.argv[1]
    head = sys.argv[2] if len(sys.argv) > 2 else "HEAD"

    files = changed_files(base, head)
    touched = {
        name for name in DATASETS if any(is_case_file(name, f) for f in files)
    }
    if not touched:
        print("no dataset case files changed - version-bump check skipped")
        return 0

    ok = True
    for name in sorted(touched):
        manifest_rel = DATASETS[name]
        old = manifest_version_at(base, manifest_rel)
        new_path = REPO / manifest_rel
        new = None
        if new_path.exists():
            try:
                new = json.loads(new_path.read_text()).get("dataset_version")
            except (json.JSONDecodeError, AttributeError):
                new = None
        if old is None:
            print(f"ok: {name} manifest is new in this range")
        elif old != new:
            print(f"ok: {name} dataset_version bumped {old!r} -> {new!r}")
        else:
            print(
                f"FAIL: {name} case files changed but {manifest_rel} "
                f"dataset_version not bumped (still {new!r})"
            )
            ok = False

    if "CHANGELOG.md" not in files:
        print(
            f"FAIL: dataset case files changed in {sorted(touched)} "
            "but CHANGELOG.md has no entry in this range"
        )
        ok = False
    else:
        print("ok: CHANGELOG.md touched in this range")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
