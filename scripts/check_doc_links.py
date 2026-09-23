#!/usr/bin/env python3
"""CI docs check: fail on dead internal links (stdlib only).

Scans README.md and docs/*.md for relative markdown links and checks:
  - the target file exists, and
  - any #anchor resolves to a heading in the target file.

Both inline [text](target) and reference-style [text][label] links (with
[label]: target definitions) are checked; bare [label] shortcuts are
skipped — they are indistinguishable from prose in brackets.

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
# Reference-style links: [text][label], [text][] (collapsed), defined by
# [label]: target elsewhere in the page. Bare [label] shortcuts are
# deliberately not matched — they are indistinguishable from prose in
# brackets.
REF_DEF_RE = re.compile(r"^\s{0,3}\[([^\]]+)\]:\s*(\S+)")
REF_LINK_RE = re.compile(r"\[([^\]]*)\]\[([^\]]*)\]")


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


def _check_target(page: Path, target: str, lineno: int, root: Path,
                  problems: list[str],
                  anchor_cache: dict[Path, set[str]]) -> None:
    """Verify one link target: the file exists and any #anchor resolves."""
    if target.startswith(("http://", "https://", "mailto:")):
        return
    if target.startswith("#"):
        file_part, anchor = page, target[1:]
    elif "#" in target:
        file_str, anchor = target.split("#", 1)
        file_part = (page.parent / file_str).resolve()
    else:
        file_part, anchor = (page.parent / target).resolve(), None
    if file_part != page:
        if file_part.is_dir():
            return  # directory links render on GitHub
        if not file_part.is_file():
            problems.append(
                f"{page.relative_to(root)}:{lineno}: "
                f"dead link to {target}")
            return
    if anchor:
        if file_part not in anchor_cache:
            anchor_cache[file_part] = anchors(file_part)
        if slugify(anchor) not in anchor_cache[file_part]:
            problems.append(
                f"{page.relative_to(root)}:{lineno}: "
                f"dead anchor #{anchor} in {target}")


def check(root: Path) -> list[str]:
    problems: list[str] = []
    pages = [root / "README.md"] + sorted((root / "docs").glob("*.md"))
    anchor_cache: dict[Path, set[str]] = {}
    for page in pages:
        if not page.is_file():
            problems.append(f"{page.name}: page missing")
            continue
        lines = page.read_text(encoding="utf-8").splitlines()
        # Pass 1: inline [text](target) links.
        for lineno, line in enumerate(lines, 1):
            for target in LINK_RE.findall(line):
                _check_target(page, target, lineno, root, problems,
                              anchor_cache)
        # Pass 2: reference-style links. Collect [label]: target
        # definitions, then verify every [text][label] / [text][]
        # resolves to a defined label with a live target.
        definitions: dict[str, str] = {}
        for line in lines:
            m = REF_DEF_RE.match(line)
            if m:
                definitions[m.group(1).strip().lower()] = m.group(2)
        for lineno, line in enumerate(lines, 1):
            if REF_DEF_RE.match(line):
                continue  # the definition itself, not a link
            for text, label in REF_LINK_RE.findall(line):
                key = (label or text).strip().lower()
                if key not in definitions:
                    problems.append(
                        f"{page.relative_to(root)}:{lineno}: "
                        f"undefined reference [{label or text}]")
                    continue
                _check_target(page, definitions[key], lineno, root,
                              problems, anchor_cache)
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
