#!/usr/bin/env python3
"""CI docs check: fail on dead internal links (stdlib only).

Scans README.md and docs/*.md for relative markdown links and checks:
  - the target file exists, and
  - any #anchor resolves to a heading in the target file.

External (http) links are not checked — they rot for reasons outside
this repo. Anchor slugification follows GitHub's rules closely enough
for our headings (lowercase, spaces to '-', strip punctuation).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")


def slugify(heading: str) -> str:
    # Strip inline markdown formatting before slugifying.
    heading = re.sub(r"[*_`~]", "", heading)
    slug = heading.lower().strip()
    slug = re.sub(r"\s+", "-", slug)
    slug = re.sub(r"[^\w\-]", "", slug, flags=re.UNICODE)
    return slug


def anchors(path: Path) -> set[str]:
    found = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        m = HEADING_RE.match(line)
        if m:
            found.add(slugify(m.group(2)))
    return found


def check(root: Path) -> list[str]:
    problems: list[str] = []
    pages = [root / "README.md"] + sorted((root / "docs").glob("*.md"))
    anchor_cache: dict[Path, set[str]] = {}
    for page in pages:
        if not page.is_file():
            problems.append(f"{page.name}: page missing")
            continue
        for lineno, line in enumerate(page.read_text(encoding="utf-8").splitlines(), 1):
            for target in LINK_RE.findall(line):
                if target.startswith(("http://", "https://", "mailto:")):
                    continue
                if target.startswith("#"):
                    file_part, anchor = page, target[1:]
                elif "#" in target:
                    file_str, anchor = target.split("#", 1)
                    file_part = (page.parent / file_str).resolve()
                else:
                    file_part, anchor = (page.parent / target).resolve(), None
                if isinstance(file_part, Path) and file_part != page:
                    if file_part.is_dir():
                        continue  # directory links render on GitHub
                    if not file_part.is_file():
                        problems.append(
                            f"{page.relative_to(root)}:{lineno}: "
                            f"dead link to {target}")
                        continue
                check_file = file_part if isinstance(file_part, Path) else page
                if anchor:
                    if check_file not in anchor_cache:
                        anchor_cache[check_file] = anchors(check_file)
                    if slugify(anchor) not in anchor_cache[check_file]:
                        problems.append(
                            f"{page.relative_to(root)}:{lineno}: "
                            f"dead anchor #{anchor} in {target}")
    return problems


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    problems = check(root)
    for p in problems:
        print(f"docs: {p}")
    if problems:
        print(f"docs: {len(problems)} dead internal link(s)", file=sys.stderr)
        return 1
    print("docs: internal links ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
