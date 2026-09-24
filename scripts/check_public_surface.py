#!/usr/bin/env python3
"""CI public-surface check: fail if banned strategic phrases appear in the repo.

The repo is the product's public face. Strategy (dominance intent, speed
language, vendor plays, internal memos) must never be committed. Approved
factual uses go in .public-surface-allowlist (one regex per line); only the
maintainer edits that file.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

BANNED = [
    r"premier product",
    r"\bdominat\w*",
    r"own the category",
    r"category leader",
    r"market leader",
    r"\blargest\b",
    r"ship fast",
    r"as quickly as possible",
    r"vendor pre-?brief",
    r"just ship",
    r"master plan",
    r"peira-master-plan",
    r"plan-audit",
    r"peira-holdout",
    r"peira-private",
    r"\baudits\b",
    r"policy memos",
    r"handoff prompt",
]

# Files that are allowed to mention the banned list itself.
SELF = {"scripts/check_public_surface.py", ".public-surface-allowlist"}

SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "target", "node_modules"}
SKIP_SUFFIXES = (".png", ".svg", ".gif", ".ico", ".woff2")


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    allow_path = root / ".public-surface-allowlist"
    allowed = []
    if allow_path.exists():
        allowed = [re.compile(line.strip()) for line in allow_path.read_text().splitlines()
                   if line.strip() and not line.startswith("#")]

    patterns = [(p, re.compile(p, re.IGNORECASE)) for p in BANNED]
    hits: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if str(rel) in SELF or path.suffix in SKIP_SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="strict")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for raw, rx in patterns:
                if rx.search(line):
                    # The allowlist covers factual uses of the "audits" pattern
                    # only; it must never exempt any other banned phrase that
                    # happens to share the line (e.g. "accuracy audits of
                    # peira-holdout" must still fail on peira-holdout).
                    if raw == r"\baudits\b" and any(a.search(line) for a in allowed):
                        continue
                    hits.append(f"{rel}:{lineno}: banned phrase {raw!r}")
    if hits:
        print("public-surface check FAILED:")
        for h in hits:
            print(f"  {h}")
        print("\nStrategy language must not be committed. See "
              "docs/Contributing.md (public-content boundary).")
        return 1
    print("public-surface check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
