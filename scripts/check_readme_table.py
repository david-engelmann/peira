#!/usr/bin/env python3
"""Fail unless the README's committed "Trial in action" sample table is
byte-identical to scripts/gen_readme_table.py output for a given run
artifact.

The README says the table is "generated, never hand-edited" — this makes
that a build failure instead of an honor system. Usage:

    python3 scripts/check_readme_table.py README.md path/to/mock-trial.json

Stdlib only.
"""

from __future__ import annotations

import difflib
import subprocess
import sys


ANCHOR = "generated, never hand-edited"


def committed_table(readme: str) -> list[str]:
    """Pull the sample table lines out of the README, starting at the
    section anchored by the "generated, never hand-edited" note."""
    lines = readme.splitlines()
    start = next(i for i, line in enumerate(lines) if ANCHOR in line)
    i = start
    while i < len(lines) and not lines[i].startswith("|"):
        i += 1
    table = []
    while i < len(lines) and lines[i].startswith("|"):
        table.append(lines[i])
        i += 1
    if not table:
        raise SystemExit(f"error: no table found after {ANCHOR!r} anchor in README")
    return table


def generated_table(artifact_path: str) -> list[str]:
    proc = subprocess.run(
        [sys.executable, "scripts/gen_readme_table.py", artifact_path],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise SystemExit(f"error: gen_readme_table.py failed:\n{proc.stderr}")
    return proc.stdout.splitlines()


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(f"usage: {argv[0]} README.md <run-artifact.json>", file=sys.stderr)
        return 2
    with open(argv[1]) as fh:
        readme = fh.read()
    committed = committed_table(readme)
    generated = generated_table(argv[2])
    if committed != generated:
        diff = "\n".join(
            difflib.unified_diff(
                committed, generated, "README committed", "generator output"
            )
        )
        print("error: README sample table does not match generator output:", file=sys.stderr)
        print(diff, file=sys.stderr)
        print(
            "\nRegenerate the table from a fresh run artifact and paste it in — "
            "the README copy is generated, never hand-edited.",
            file=sys.stderr,
        )
        return 1
    print(f"ok: README table matches generator output ({len(generated)} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
