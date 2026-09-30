#!/usr/bin/env python3
"""CI gate: verify the immutable dataset-release tag registry.

For every entry in data/dataset-releases.json this checks that
- the tag resolves in the local clone,
- the tag still points at the recorded commit (tags are never moved),
- the manifest bytes AT THE TAG hash to the recorded manifest_sha256,
- the croissant.json bytes AT THE TAG hash to the recorded
  croissant_sha256,
- the manifest's dataset_version at the tag matches the registry.

Any failure exits nonzero with the problem printed. History must be
complete for tag resolution, so the CI job checks out with
fetch-depth: 0 and fetches tags.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "python"))

from peira.provenance import (  # noqa: E402
    check_append_only,
    load_releases,
    registry_path,
    verify_releases,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify the immutable dataset-release tag registry.")
    parser.add_argument(
        "--repo", default=str(REPO_ROOT),
        help="repo checkout to verify (default: this repo)")
    parser.add_argument(
        "--check-append-only", metavar="BASE", default=None,
        help="also require registry entries to be append-only since "
             "commit BASE (the PR merge base): entries present at BASE "
             "must be byte-identical now")
    args = parser.parse_args()

    reg = registry_path(args.repo)
    if not reg.is_file():
        print(f"no registry at {reg}; nothing to verify")
        return 0
    try:
        problems = verify_releases(args.repo, reg)
    except ValueError as e:
        print(f"release registry malformed: {e}", file=sys.stderr)
        return 1
    if args.check_append_only:
        problems += check_append_only(args.repo, args.check_append_only,
                                      reg)
    if problems:
        print(f"{len(problems)} release-registry problem(s):")
        for p in problems:
            print(f"  - {p}")
        return 1
    try:
        n = len(load_releases(reg))
    except ValueError as e:
        print(f"release registry malformed: {e}", file=sys.stderr)
        return 1
    print(f"release registry OK: {n} release(s) verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
