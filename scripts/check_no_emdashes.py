#!/usr/bin/env python3
"""Fail if any U+2014 (em dash) appears in the public Markdown surface.

Scans README.md and every Markdown file under docs/. Reports each hit
with file, line, and column, then exits nonzero if any are found.

Public prose must read like a human engineer wrote it, and em dashes
are the number-one AI-writing tell, so this gate keeps them out.
"""

from __future__ import annotations

import pathlib
import sys

EM_DASH = "\u2014"
ROOT = pathlib.Path(__file__).resolve().parent.parent


def find_hits() -> list[tuple[str, int, int, str]]:
    """Return (path, line, column, line_text) for every em dash hit."""
    targets: list[pathlib.Path] = [ROOT / "README.md"]
    targets.extend(sorted((ROOT / "docs").rglob("*.md")))

    hits: list[tuple[str, int, int, str]] = []
    for path in targets:
        if not path.is_file():
            continue
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            col = line.find(EM_DASH)
            while col != -1:
                hits.append((str(path.relative_to(ROOT)), lineno, col + 1, line.strip()))
                col = line.find(EM_DASH, col + 1)
    return hits


def main() -> int:
    hits = find_hits()
    for path, lineno, col, line_text in hits:
        print(f"{path}:{lineno}:{col}: em dash found: {line_text}", file=sys.stderr)
    if hits:
        n = len(hits)
        print(
            f"\n{n} em dash{'es' if n != 1 else ''} in public Markdown; "
            "rewrite without U+2014.",
            file=sys.stderr,
        )
        return 1
    print("No em dashes in README.md or docs/.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
