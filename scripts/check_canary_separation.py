#!/usr/bin/env python3
"""Assert the two canary tiers never mix (see CANARY.md).

Tier 1 (case canary): each suite's CANARY.txt GUID must appear in every
case row of that suite, and must never appear in documentation.
Tier 2 (doc canary): the CANARY.md GUID must appear only in CANARY.md
and DATASHEET.md, and never in dataset case files.

The doc scan covers docs/ recursively and root-level files; a GUID
pasted into other subdirectories (e.g. dataset/trial/README.md) is not
caught. This is a known limitation, not a guarantee of absence.

Usage:
    python3 scripts/check_canary_separation.py
    python3 scripts/check_canary_separation.py --root /path/to/repo

Exit 0 when the tiers are cleanly separated, 1 with a report otherwise.
Suites without a CANARY.txt yet (canary embedding is a seal-time step)
are reported as unsealed, not as failures.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Documentation files allowed to carry the tier-2 doc canary. Everywhere
# else is a separation violation.
DOC_CANARY_FILES = {"CANARY.md", "DATASHEET.md"}

# Suites whose case files must carry the tier-1 case canary once sealed.
CASE_SUITES = ("dataset/trial", "dataset/v1/cases")

# File types scanned for stray canary strings in documentation.
DOC_EXTENSIONS = {".md", ".txt", ".rst", ".py", ".rs", ".toml", ".yaml",
                  ".yml", ".json"}


def _read_guid(path: Path) -> str | None:
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8").strip()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".",
                    help="repository root (default: current directory)")
    args = ap.parse_args()
    root = Path(args.root).resolve()

    errors: list[str] = []
    infos: list[str] = []

    # Tier 2: doc canary GUID from CANARY.md.
    doc_canary_path = root / "CANARY.md"
    if not doc_canary_path.is_file():
        errors.append("CANARY.md is missing; cannot verify the doc canary")
        doc_guid = None
    else:
        m = re.search(r"peira-doc-canary:([0-9a-f]{32})",
                      doc_canary_path.read_text(encoding="utf-8"))
        if not m:
            errors.append("CANARY.md does not contain a peira-doc-canary GUID")
            doc_guid = None
        else:
            doc_guid = m.group(1)

    # Tier 1: case canary GUIDs from each suite's CANARY.txt.
    case_guids: dict[str, str] = {}
    for suite in CASE_SUITES:
        guid = _read_guid(root / suite / "CANARY.txt")
        if guid:
            case_guids[suite] = guid
        else:
            infos.append(f"{suite}: no CANARY.txt yet (not sealed)")

    # 1. Every case row in a sealed suite must carry its tier-1 GUID in
    # the `canary` field (either as the bare GUID or inside the prefixed
    # `peira-<suite>-canary:` string form), and both training-exclusion
    # flags must be boolean true. A sealed suite went through
    # embed_canary, which sets them; a false or missing flag means the
    # seal is broken.
    for suite, guid in case_guids.items():
        suite_dir = root / suite
        rows = 0
        for fp in sorted(suite_dir.glob("*.jsonl")):
            for lineno, line in enumerate(fp.read_text(
                    encoding="utf-8").splitlines(), 1):
                if not line.strip():
                    continue
                rows += 1
                try:
                    case = json.loads(line)
                except json.JSONDecodeError:
                    continue  # G1 owns malformed JSON
                if guid not in str(case.get("canary", "")):
                    errors.append(
                        f"{suite}/{fp.name}:{lineno}: case "
                        f"{case.get('case_id', '?')} missing tier-1 "
                        f"canary")
                for flag in ("evaluation_only", "do_not_train"):
                    if case.get(flag) is not True:
                        errors.append(
                            f"{suite}/{fp.name}:{lineno}: case "
                            f"{case.get('case_id', '?')} has {flag}="
                            f"{case.get(flag)!r}, want boolean true")
        infos.append(f"{suite}: checked {rows} case rows for tier-1 canary")

    # 2. Tier-1 GUIDs must never appear in documentation. That means
    # docs/ (recursive) and every documentation-type file at the repo
    # root, not just the three named ones. The suites' own CANARY.txt
    # files live under dataset/, so they are never in this set.
    doc_files: list[Path] = []
    docs_dir = root / "docs"
    if docs_dir.is_dir():
        doc_files.extend(p for p in docs_dir.rglob("*")
                         if p.is_file() and p.suffix in DOC_EXTENSIONS)
    doc_files.extend(p for p in root.iterdir()
                     if p.is_file() and p.suffix in DOC_EXTENSIONS)
    # De-duplicate (CANARY.md / DATASHEET.md / README.md are covered by
    # the root scan) while keeping deterministic order.
    seen: set[Path] = set()
    uniq_doc_files = []
    for p in doc_files:
        if p not in seen:
            seen.add(p)
            uniq_doc_files.append(p)
    for suite, guid in case_guids.items():
        for fp in sorted(uniq_doc_files):
            try:
                text = fp.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if guid in text:
                errors.append(
                    f"tier-1 canary for {suite} appears in "
                    f"documentation: {fp.relative_to(root)}")

    # 3. Tier-2 doc GUID must appear only in CANARY.md / DATASHEET.md.
    # Scan case files, documentation, source, and fixtures: any other
    # file holding the GUID is a separation violation.
    if doc_guid:
        allowed = {root / fname for fname in DOC_CANARY_FILES}
        skip_parts = {".git", "target", "__pycache__", ".venv",
                      "node_modules"}
        scan_suffixes = DOC_EXTENSIONS | {".jsonl"}
        for fp in sorted(root.rglob("*")):
            if not fp.is_file():
                continue
            if fp in allowed:
                continue
            if any(part in skip_parts for part in fp.parts):
                continue
            if fp.suffix not in scan_suffixes:
                continue
            try:
                text = fp.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if doc_guid in text:
                errors.append(
                    f"tier-2 doc canary appears outside "
                    f"CANARY.md/DATASHEET.md: {fp.relative_to(root)}")
        # And it must actually be present where it belongs.
        for fname in DOC_CANARY_FILES:
            fp = root / fname
            if not fp.is_file() or doc_guid not in fp.read_text(
                    encoding="utf-8"):
                errors.append(f"tier-2 doc canary missing from {fname}")

    for info in infos:
        print(f"info: {info}")
    if errors:
        print(f"\n{len(errors)} separation violation(s):")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("\ncanary tiers cleanly separated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
