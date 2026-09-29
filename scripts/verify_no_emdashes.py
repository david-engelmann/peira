#!/usr/bin/env python3
"""Verify no em dashes (U+2014) remain in public prose files.

PR-2 docs-remainder: reproducing verification script for the em-dash sweep.
Uses Python codepoint scan, NOT grep (grep lies silently on Unicode).

Usage: python3 scripts/verify_no_emdashes.py
Exit 0 if clean, exit 1 if any hits found.
"""

import os
import sys

# Files in scope for the PR-2 sweep (public-facing prose outside docs//README,
# which were already clean). docs/ and README.md are covered by the
# public-surface check; they are included here for completeness.
SCOPE = [
    "CHANGELOG.md",
    "CLAUDE.md",
    "AGENTS.md",
    "adapters/README.md",
    "assets/README.md",
    "dataset/README.md",
    "dataset/trial/README.md",
    "dataset/v1/README.md",
    "dataset/safety-policy/README.md",
    "dataset/safety-policy/SPEC.md",
    "paper/README.md",
    "README.md",
]

# Also scan all of docs/ to prove it stays clean.
DOCS_DIR = "docs"


def scan_file(path):
    """Return count of U+2014 in file, or None if unreadable."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read().count("\u2014")
    except (OSError, UnicodeDecodeError):
        return None


def main():
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(repo)

    total = 0
    bad_files = []

    for fp in SCOPE:
        count = scan_file(fp)
        if count is None:
            print(f"SKIP (unreadable): {fp}")
            continue
        if count > 0:
            bad_files.append((fp, count))
            total += count

    # Scan docs/ recursively.
    docs_dir = os.path.join(repo, DOCS_DIR)
    for root, _dirs, files in os.walk(docs_dir):
        for f in files:
            if f.endswith(".md"):
                fp = os.path.join(root, f)
                rel = os.path.relpath(fp, repo)
                count = scan_file(fp)
                if count and count > 0:
                    bad_files.append((rel, count))
                    total += count

    if bad_files:
        print(f"FAIL: {total} em dash (U+2014) hits in {len(bad_files)} files:")
        for fp, count in sorted(bad_files, key=lambda x: -x[1]):
            print(f"  {count:4d}  {fp}")
        return 1

    print(f"OK: zero em dash (U+2014) hits in {len(SCOPE)} scoped files + docs/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
