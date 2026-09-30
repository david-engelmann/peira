#!/usr/bin/env python3
"""Record a dataset release in the immutable tag registry.

Release procedure (docs/Provenance.md, "Cutting a dataset release"):
  1. Cut the annotated tag on the sealed manifest commit, e.g.
     ``git tag -a dataset-v1-1.0.0 -m "peira-v1 1.0.0"``
  2. Run this script to append the tag's manifest/croissant digests to
     data/dataset-releases.json. It resolves the tag, reads the manifest
     AT THE TAG, and verifies the dataset version matches.
  3. Commit the registry update and push the tag plus the commit.

The registry is append-only: this script refuses to overwrite an
already-registered tag. A correction ships as a new tag and a new
entry.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "python"))

from peira.provenance import (  # noqa: E402
    manifest_digest_at_tag,
    record_release,
    registry_path,
)


def _tag_commit(repo: Path, tag: str) -> str:
    return subprocess.run(
        ["git", "rev-parse", "--verify", f"{tag}^{{commit}}"],
        cwd=str(repo), capture_output=True, text=True, check=True,
    ).stdout.strip()


def _is_annotated(repo: Path, tag: str) -> bool:
    out = subprocess.run(
        ["git", "cat-file", "-t", tag],
        cwd=str(repo), capture_output=True, text=True, check=True,
    ).stdout.strip()
    return out == "tag"


def _manifest_at_tag(repo: Path, commit: str,
                     manifest_path: str) -> dict:
    # Pinned to the resolved commit SHA, not the tag name: the tag
    # cannot move under the read.
    blob = subprocess.run(
        ["git", "show", f"{commit}:{manifest_path}"],
        cwd=str(repo), capture_output=True, check=True,
    ).stdout
    data = json.loads(blob.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{commit}:{manifest_path} is not a JSON object")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Record a dataset release in the immutable tag "
                    "registry.")
    parser.add_argument("--tag", required=True,
                        help="annotated tag just cut, e.g. dataset-v1-1.0.0")
    parser.add_argument("--dataset", required=True,
                        help="dataset label, e.g. peira-v1")
    parser.add_argument("--manifest-path", required=True,
                        help="manifest path in the repo, e.g. "
                             "dataset/v1/cases/manifest.json")
    parser.add_argument("--repo", default=str(REPO_ROOT),
                        help="repo checkout (default: this repo)")
    args = parser.parse_args()

    repo = Path(args.repo)
    try:
        commit = _tag_commit(repo, args.tag)
    except subprocess.CalledProcessError:
        print(f"error: tag {args.tag!r} does not resolve in {repo}",
              file=sys.stderr)
        return 1
    try:
        if not _is_annotated(repo, args.tag):
            print(f"error: tag {args.tag!r} is not annotated; cut it "
                  f"with git tag -a", file=sys.stderr)
            return 1
    except subprocess.CalledProcessError as e:
        print(f"error: cannot inspect tag: {e}", file=sys.stderr)
        return 1
    try:
        manifest = _manifest_at_tag(repo, commit, args.manifest_path)
    except (subprocess.CalledProcessError, ValueError) as e:
        print(f"error: cannot read manifest at tag: {e}", file=sys.stderr)
        return 1
    version = str(manifest.get("dataset_version", ""))
    if manifest.get("dataset") != args.dataset:
        print(f"error: manifest at tag names dataset "
              f"{manifest.get('dataset')!r}, expected {args.dataset!r}",
              file=sys.stderr)
        return 1
    try:
        manifest_sha256, croissant_sha256 = manifest_digest_at_tag(
            repo, args.tag, args.manifest_path, commit=commit)
    except subprocess.CalledProcessError as e:
        print(f"error: cannot read files at tag: {e}", file=sys.stderr)
        return 1
    try:
        record_release(registry_path(repo), {
            "tag": args.tag,
            "dataset": args.dataset,
            "dataset_version": version,
            "manifest_path": args.manifest_path,
            "manifest_sha256": manifest_sha256,
            "croissant_sha256": croissant_sha256,
            "commit": commit,
        })
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"recorded {args.tag} ({args.dataset} {version}) at commit "
          f"{commit[:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
