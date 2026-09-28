#!/usr/bin/env python3
"""Manage the public blind-holdout query counter.

The counter lives in docs/Holdout-Query-Log.md. It records how many
blind re-executions each adapter line has used, never case details.
See docs/Holdout-Query-Budget.md for the policy.

Usage:
    python3 scripts/holdout_query_log.py log --adapter "name v1.2.3"
    python3 scripts/holdout_query_log.py log --adapter "name v1.2.3" --date 2026-10-15
    python3 scripts/holdout_query_log.py rotation --kind scheduled
    python3 scripts/holdout_query_log.py status --adapter "name v1.2.3"

The log is append-only. Entries are never edited or deleted.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

BUDGET_PER_YEAR = 12
LOG_PATH = Path(__file__).parent.parent / "docs" / "Holdout-Query-Log.md"
ENTRY_RE = re.compile(
    r"^-\s+(\d{4}-\d{2}-\d{2})\s+\|\s+(.+?)\s+\|\s+execution\s+(\d+)\s+of\s+12\s+in\s+(\d{4})\s*$")
ROTATION_RE = re.compile(r"^-\s+(\d{4}-\d{2}-\d{2})\s+\|\s+ROTATION\s+\|\s+(.+?)\s*$")


def _read_entries():
    """Parse log entries. Returns (entries, rotations)."""
    text = LOG_PATH.read_text(encoding="utf-8")
    # Strip the HTML comment block: it holds format examples that must
    # not parse as real entries.
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    entries = []  # (date, adapter, n, year)
    rotations = []  # (date, kind)
    for line in text.splitlines():
        m = ENTRY_RE.match(line)
        if m:
            entries.append((m.group(1), m.group(2), int(m.group(3)),
                            int(m.group(4))))
            continue
        m = ROTATION_RE.match(line)
        if m:
            rotations.append((m.group(1), m.group(2)))
    return entries, rotations


def _used_this_year(entries, adapter, year):
    return sum(1 for _, a, _, y in entries if a == adapter and y == year)


def cmd_log(args) -> int:
    entries, _ = _read_entries()
    year = int(args.date[:4])
    used = _used_this_year(entries, args.adapter, year)
    if used >= BUDGET_PER_YEAR:
        print(f"error: {args.adapter} exhausted its {BUDGET_PER_YEAR} "
              f"executions for {year} ({used} used). "
              f"Further blind runs wait for next year or a rotation. "
              f"See docs/Holdout-Query-Budget.md.",
              file=sys.stderr)
        return 1
    n = used + 1
    line = f"- {args.date} | {args.adapter} | execution {n} of 12 in {year}\n"
    # Append after the last entry line, before the HTML comment if present.
    text = LOG_PATH.read_text(encoding="utf-8")
    marker = "<!--"
    if marker in text:
        head, tail = text.split(marker, 1)
        head = head.rstrip("\n") + "\n"
        text = head + line + "\n" + marker + tail
    else:
        text = text.rstrip("\n") + "\n\n" + line
    LOG_PATH.write_text(text, encoding="utf-8")
    print(f"logged: {args.adapter} execution {n} of 12 in {year}")
    return 0


def cmd_rotation(args) -> int:
    today = date.today().isoformat()
    line = f"- {today} | ROTATION | {args.kind} rotation announced\n"
    text = LOG_PATH.read_text(encoding="utf-8")
    marker = "<!--"
    if marker in text:
        head, tail = text.split(marker, 1)
        head = head.rstrip("\n") + "\n"
        text = head + line + "\n" + marker + tail
    else:
        text = text.rstrip("\n") + "\n\n" + line
    LOG_PATH.write_text(text, encoding="utf-8")
    print(f"logged rotation: {args.kind}")
    return 0


def cmd_status(args) -> int:
    entries, rotations = _read_entries()
    year = date.today().year
    if args.adapter:
        used = _used_this_year(entries, args.adapter, year)
        print(f"{args.adapter}: {used} of {BUDGET_PER_YEAR} used in {year} "
              f"({BUDGET_PER_YEAR - used} remaining)")
    else:
        by_adapter: dict[str, int] = {}
        for _, a, _, y in entries:
            if y == year:
                by_adapter[a] = by_adapter.get(a, 0) + 1
        total = sum(by_adapter.values())
        print(f"{year}: {total} total executions, "
              f"{len(rotations)} rotations logged")
        for a, n in sorted(by_adapter.items()):
            print(f"  {a}: {n} of {BUDGET_PER_YEAR} used")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("log", help="record a blind re-execution")
    p.add_argument("--adapter", required=True,
                   help="adapter line, e.g. 'shieldstral 1.0'")
    p.add_argument("--date", default=date.today().isoformat(),
                   help="execution date YYYY-MM-DD (default: today)")

    p = sub.add_parser("rotation", help="record a holdout rotation")
    p.add_argument("--kind", required=True,
                   choices=["scheduled", "budget", "compromise"],
                   help="rotation trigger")

    p = sub.add_parser("status", help="show budget usage")
    p.add_argument("--adapter", default=None,
                   help="adapter line (default: all)")

    args = ap.parse_args()
    if args.cmd == "log":
        return cmd_log(args)
    if args.cmd == "rotation":
        return cmd_rotation(args)
    return cmd_status(args)


if __name__ == "__main__":
    sys.exit(main())
