#!/usr/bin/env python3
"""Rebuild the test-fixture manifest skeleton (tests/fixtures/manifest.json).

Walks tests/fixtures for every fixture file and emits one manifest entry
per file. Hand-written fields (purpose, family, expected_gate_outcome,
loaded_via_dir) are preserved from the existing manifest; the
referenced_by lists are recomputed from the test suite with the same
detection rule used by tests/test_fixture_manifest.py.

New fixtures get "TBD" placeholders: fill in purpose/family/outcome by
hand (read the fixture and the test that references it), then run the
pinning test to confirm the manifest matches reality.

Usage:
    python3 scripts/regen_fixture_manifest.py           # rewrite manifest
    python3 scripts/regen_fixture_manifest.py --check   # exit 1 if stale
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = ROOT / "tests" / "fixtures"
MANIFEST_PATH = FIXTURES_DIR / "manifest.json"
SELF_TEST = "test_fixture_manifest.py"

# Path separators / string delimiters that can appear between the path
# segments of a fixture reference in test source.
_SEP = r"[\s\"'(),/\\\\]+"

TBD = "TBD - fill in by hand (read the fixture and its referencing test)"


def iter_fixture_files() -> list[Path]:
    """Every fixture file, repo-relative to tests/fixtures, sorted."""
    return sorted(
        (p.relative_to(FIXTURES_DIR) for p in FIXTURES_DIR.rglob("*")
         if p.is_file() and p.name != "manifest.json"),
        key=str,
    )


def _reference_patterns(rel: Path) -> tuple[re.Pattern, re.Pattern | None]:
    """Regexes matching a fixture reference in test source.

    Full form matches the whole fixture path written as adjacent segments,
    e.g. ``Path(...) / "fixtures" / "g9_paraphrase_pairs.jsonl"`` or
    ``os.path.join(..., "fixtures", "g9_paraphrase_pairs.jsonl")``.

    Directory form (only for fixtures nested in a subdirectory) matches a
    mention of the fixture's parent directory, e.g.
    ``Path(...) / "fixtures" / "conversational"``; such directories are
    consumed whole by loaders that glob ``*.jsonl``
    (load_conversation_cases, run_conversation_gates), so the mention
    counts as a reference to every fixture file inside.
    """
    parts = ["fixtures", *rel.parts]
    full = re.compile(_SEP.join(re.escape(p) for p in parts))
    dir_pat = None
    if len(parts) > 2:
        dir_pat = re.compile(_SEP.join(re.escape(p) for p in parts[:-1]))
    return full, dir_pat


def detect_references() -> dict[str, list[str]]:
    """Map fixture relpath -> sorted list of referencing test files.

    A tests/test_*.py file (excluding the manifest-pinning test itself,
    which is not a fixture consumer) counts as referencing a fixture when
    its source matches the fixture's full path pattern or, for
    subdirectory fixtures, the parent-directory pattern.
    """
    refs: dict[str, set[str]] = {}
    fixtures = iter_fixture_files()
    patterns = {f: _reference_patterns(f) for f in fixtures}
    test_files = sorted((ROOT / "tests").glob("test_*.py"))
    for test_path in test_files:
        if test_path.name == SELF_TEST:
            continue
        try:
            src = test_path.read_text(encoding="utf-8")
        except OSError:
            continue
        rel_test = str(test_path.relative_to(ROOT))
        for fixture, (full, dir_pat) in patterns.items():
            if full.search(src) or (dir_pat is not None and dir_pat.search(src)):
                refs.setdefault(str(fixture), set()).add(rel_test)
    return {k: sorted(v) for k, v in refs.items()}


def build_manifest(old: dict | None) -> dict:
    """Build the manifest skeleton, preserving hand-written fields."""
    old_entries = (old or {}).get("fixtures", {})
    refs = detect_references()
    entries: dict[str, dict] = {}
    for rel in iter_fixture_files():
        key = str(rel)
        prev = old_entries.get(key, {})
        entries[key] = {
            "purpose": prev.get("purpose", TBD),
            "family": prev.get("family", TBD),
            "expected_gate_outcome": prev.get("expected_gate_outcome", TBD),
            "loaded_via_dir": prev.get("loaded_via_dir", False),
            "referenced_by": refs.get(key, []),
        }
    return {"version": 1, "fixtures": entries}


def load_manifest() -> dict | None:
    if not MANIFEST_PATH.is_file():
        return None
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if the manifest is stale, without writing")
    args = parser.parse_args(argv)

    old = load_manifest()
    new = build_manifest(old)
    new_text = json.dumps(new, indent=2, sort_keys=True) + "\n"

    if args.check:
        current = (MANIFEST_PATH.read_text(encoding="utf-8")
                   if MANIFEST_PATH.is_file() else "")
        if current != new_text:
            print("fixture manifest is stale: run "
                  "scripts/regen_fixture_manifest.py", file=sys.stderr)
            return 1
        print("fixture manifest is current")
        return 0

    old_keys = set((old or {}).get("fixtures", {}))
    new_keys = set(new["fixtures"])
    for key in sorted(new_keys - old_keys):
        print(f"added: {key}")
    for key in sorted(old_keys - new_keys):
        print(f"removed: {key}")
    MANIFEST_PATH.write_text(new_text, encoding="utf-8")
    print(f"wrote {MANIFEST_PATH.relative_to(ROOT)} "
          f"({len(new_keys)} fixtures)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
