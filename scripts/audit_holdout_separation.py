#!/usr/bin/env python3
"""Audit that no holdout material appears in the public repository.

Takes a holdout directory (private) and a public directory (the repo).
Computes fingerprints of holdout case IDs and prompt text, then scans
every text file under the public directory for those fingerprints AND
for the raw IDs/text (catching accidental pastes).

Output is counts only. Holdout IDs, text, and fingerprints are NEVER
printed, even on violation. A violation report says how many matches
were found and in which public files, not what matched.

Usage:
    python3 scripts/audit_holdout_separation.py \
        --holdout-dir /path/to/private/holdout \
        --public-dir /path/to/peira

Exit 0 when clean, 1 when any holdout material is found in public.
Exit 2 on usage errors.

This script is for the maintainer's machine only. It reads the private
holdout. Never run it in public CI.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

# File types to scan in the public directory.
SCAN_EXTENSIONS = {".md", ".txt", ".rst", ".py", ".rs", ".toml", ".yaml",
                   ".yml", ".json", ".jsonl", ".csv", ".html"}

# Directories to skip in the public tree (build artifacts, history).
SKIP_DIRS = {".git", "target", "__pycache__", ".venv", "node_modules"}


def _fingerprints(holdout_dir: Path):
    """Return (id_hashes, text_hashes, raw_needles).

    raw_needles are the literal IDs and prompt snippets to search for
    (accidental paste detection). They are kept in memory only and never
    printed.
    """
    id_hashes: set[str] = set()
    text_hashes: set[str] = set()
    raw_needles: set[str] = set()
    for fp in sorted(holdout_dir.rglob("*.jsonl")):
        for line in fp.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                case = json.loads(line)
            except json.JSONDecodeError:
                continue
            cid = str(case.get("case_id", ""))
            if cid:
                id_hashes.add(hashlib.sha256(cid.encode()).hexdigest())
                raw_needles.add(cid)
            for variant in ("benign", "attacked"):
                prompt = (case.get(variant, {}).get("input", {})
                          .get("prompt", ""))
                if prompt and len(prompt) >= 32:
                    # Fingerprint a normalized prefix: catches pastes even
                    # with minor reformatting.
                    norm = " ".join(prompt.split())[:200]
                    text_hashes.add(hashlib.sha256(norm.encode())
                                    .hexdigest())
                    # Short needles catch partial pastes: any 40-char
                    # window of the prompt is distinctive enough.
                    for i in range(0, min(len(norm), 120), 40):
                        raw_needles.add(norm[i:i + 40])
    # Also fingerprint any CANARY.txt-style GUIDs in the holdout dir.
    for fp in holdout_dir.rglob("CANARY.txt"):
        guid = fp.read_text(encoding="utf-8").strip()
        if guid:
            id_hashes.add(hashlib.sha256(guid.encode()).hexdigest())
            raw_needles.add(guid)
    return id_hashes, text_hashes, raw_needles


def _public_files(public_dir: Path):
    for fp in public_dir.rglob("*"):
        if not fp.is_file():
            continue
        if fp.suffix not in SCAN_EXTENSIONS:
            continue
        if any(part in SKIP_DIRS for part in fp.parts):
            continue
        yield fp


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--holdout-dir", required=True,
                    help="private holdout directory")
    ap.add_argument("--public-dir", required=True,
                    help="public repository directory")
    args = ap.parse_args()

    holdout_dir = Path(args.holdout_dir)
    public_dir = Path(args.public_dir)
    if not holdout_dir.is_dir():
        print(f"error: holdout dir not found: {holdout_dir}", file=sys.stderr)
        return 2
    if not public_dir.is_dir():
        print(f"error: public dir not found: {public_dir}", file=sys.stderr)
        return 2

    id_hashes, text_hashes, raw_needles = _fingerprints(holdout_dir)
    print(f"holdout fingerprints: {len(id_hashes)} id hashes, "
          f"{len(text_hashes)} text hashes", file=sys.stderr)

    violations: dict[str, int] = {}  # public file -> match count
    files_scanned = 0
    for fp in _public_files(public_dir):
        files_scanned += 1
        try:
            text = fp.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        hits = 0
        # Check raw needles (accidental paste of IDs or prompt text).
        for needle in raw_needles:
            if needle and needle in text:
                hits += 1
        # Check hash fingerprints (in case IDs were hashed into the repo,
        # e.g. a manifest that should not exist).
        for h in id_hashes | text_hashes:
            if h in text:
                hits += 1
        if hits:
            # Report the FILE, never the matched content.
            violations[str(fp.relative_to(public_dir))] = hits

    print(f"scanned {files_scanned} public files", file=sys.stderr)
    if violations:
        total = sum(violations.values())
        print(f"\nSEPARATION VIOLATION: {total} holdout match(es) in "
              f"{len(violations)} public file(s):")
        for fname in sorted(violations):
            print(f"  - {fname}: {violations[fname]} match(es)")
        print("\nMatched holdout content is NOT shown. Rotate the affected "
              "holdout shard per docs/Holdout-OpSec.md.")
        return 1
    print("\nclean: no holdout material found in the public directory")
    return 0


if __name__ == "__main__":
    sys.exit(main())
