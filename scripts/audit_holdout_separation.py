#!/usr/bin/env python3
"""Audit that no holdout material appears in the public repository.

Takes a holdout directory (private) and a public directory (the repo).
Computes fingerprints of holdout case IDs and prompt text, then scans
every text file under the public directory for those fingerprints AND
for the raw IDs/text (catching accidental pastes).

Detection floors: prompts under 32 chars get no text fingerprints (only
the case ID is needled); pasted fragments under 20 chars are not caught.
These floors keep the needle set small; they are documented here so the
"catches partial pastes" claim is not overstated.

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

# Directories to skip in the public tree (build artifacts, history).
SKIP_DIRS = {".git", "target", "__pycache__", ".venv", "node_modules"}


def _fingerprints(holdout_dir: Path):
    """Return (id_hashes, text_hashes, raw_needles, n_cases, n_canaries).

    raw_needles are the literal IDs and prompt snippets to search for
    (accidental paste detection). They are kept in memory only and never
    printed. n_cases / n_canaries let the caller reject an empty holdout
    instead of reporting a vacuous clean.
    """
    id_hashes: set[str] = set()
    text_hashes: set[str] = set()
    raw_needles: set[str] = set()
    n_cases = 0
    n_canaries = 0
    for fp in sorted(holdout_dir.rglob("*.jsonl")):
        for lineno, line in enumerate(fp.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                case = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(case, dict):
                # Structurally malformed row: fail closed, don't crash.
                print(f"warning: {fp}:{lineno}: row is not a JSON object, "
                      f"skipping", file=sys.stderr)
                continue
            n_cases += 1
            cid = str(case.get("case_id", ""))
            if cid:
                id_hashes.add(hashlib.sha256(cid.encode()).hexdigest())
                raw_needles.add(cid)
            for variant in ("benign", "attacked"):
                v = case.get(variant)
                if not isinstance(v, dict):
                    # Structurally malformed row: fail closed, don't crash.
                    print(f"warning: {fp}:{lineno}: {variant} is not a dict, "
                          f"skipping row", file=sys.stderr)
                    continue
                prompt = (v.get("input", {}).get("prompt", "")
                          if isinstance(v.get("input"), dict) else "")
                if prompt and len(prompt) >= 32:
                    # Fingerprint normalized chunks: catches pastes even
                    # with minor whitespace reformatting. Stride 40-char
                    # needles across the whole prompt (not just the head)
                    # so mid-prompt and tail pastes are caught.
                    norm = " ".join(prompt.split())
                    # Hash 200-char chunks across the full text.
                    for j in range(0, len(norm), 200):
                        chunk = norm[j:j + 200]
                        if len(chunk) >= 32:
                            text_hashes.add(
                                hashlib.sha256(chunk.encode()).hexdigest())
                    # Short needles catch partial pastes: 40-char windows
                    # strided across the entire normalized prompt. The
                    # stride (10) is much smaller than the window (40),
                    # so any pasted span of 50+ chars contains a full
                    # window regardless of alignment. A non-overlapping
                    # stride would miss pastes that straddle window
                    # boundaries (e.g. prompt[20:70] contains no full
                    # 40-char window at stride 40).
                    for i in range(0, len(norm), 10):
                        window = norm[i:i + 40]
                        if len(window) >= 32:
                            raw_needles.add(window)
                    # Shorter 20-char windows (stride 5) catch fragments
                    # of 25+ chars that fit inside a single 40-char
                    # window. Detection floors: pastes under 20 chars
                    # and prompts under 32 chars are not fingerprinted.
                    for i in range(0, len(norm), 5):
                        window = norm[i:i + 20]
                        if len(window) >= 20:
                            raw_needles.add(window)
    # Also fingerprint any CANARY.txt-style GUIDs in the holdout dir.
    for fp in holdout_dir.rglob("CANARY.txt"):
        guid = fp.read_text(encoding="utf-8").strip()
        if guid:
            n_canaries += 1
            id_hashes.add(hashlib.sha256(guid.encode()).hexdigest())
            raw_needles.add(guid)
    return id_hashes, text_hashes, raw_needles, n_cases, n_canaries


def _public_files(public_dir: Path):
    # Every readable file is in scope, regardless of suffix: a holdout
    # ID pasted into a .sh file or an extensionless script must not be
    # missed because of an allowlist. Only build-artifact and history
    # directories are skipped.
    for fp in public_dir.rglob("*"):
        if not fp.is_file():
            continue
        if any(part in SKIP_DIRS for part in fp.parts):
            continue
        yield fp


# Files larger than this are skipped (reported as unreadable-style) to
# avoid OOM on multi-GB artifacts. 100MB is generous for source/docs.
MAX_FILE_BYTES = 100 * 1024 * 1024


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

    id_hashes, text_hashes, raw_needles, n_cases, n_canaries = \
        _fingerprints(holdout_dir)
    if n_cases == 0 and n_canaries == 0:
        print(f"error: no holdout cases or canaries found under "
              f"{holdout_dir}; refusing a vacuous clean audit",
              file=sys.stderr)
        return 2
    print(f"holdout fingerprints: {len(id_hashes)} id hashes, "
          f"{len(text_hashes)} text hashes", file=sys.stderr)

    violations: dict[str, int] = {}  # public file -> match count
    unreadable: list[str] = []
    files_scanned = 0
    needle_bytes = [n.encode("utf-8") for n in raw_needles if n]
    hash_bytes = [h.encode("ascii") for h in id_hashes | text_hashes]
    for fp in _public_files(public_dir):
        files_scanned += 1
        try:
            if fp.stat().st_size > MAX_FILE_BYTES:
                unreadable.append(f"{fp.relative_to(public_dir)} "
                                  f"(over {MAX_FILE_BYTES} bytes, skipped)")
                continue
            data = fp.read_bytes()
        except OSError as e:
            unreadable.append(f"{fp.relative_to(public_dir)} ({e})")
            continue
        hits = 0
        # Raw byte search: catches IDs, hashes, and verbatim pastes in
        # any encoding-compatible file. Never skipped on decode errors;
        # undecodable bytes simply do not match.
        for nb in needle_bytes:
            if nb in data:
                hits += 1
        for hb in hash_bytes:
            if hb in data:
                hits += 1
        # Normalized text search: the prompt needles are whitespace-
        # normalized, so normalize the scanned text the same way before
        # comparing. A paste with line breaks inside a 40-char window
        # still matches.
        pub_norm = " ".join(
            data.decode("utf-8", errors="replace").split())
        for needle in raw_needles:
            if needle and needle in pub_norm:
                hits += 1
        if hits:
            # Report the FILE, never the matched content.
            violations[str(fp.relative_to(public_dir))] = hits

    print(f"scanned {files_scanned} public files", file=sys.stderr)
    if unreadable:
        print(f"\nINCOMPLETE AUDIT: {len(unreadable)} public file(s) "
              f"could not be read and were NOT checked:",
              file=sys.stderr)
        for fname in sorted(unreadable):
            print(f"  - {fname}", file=sys.stderr)
        return 2
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
