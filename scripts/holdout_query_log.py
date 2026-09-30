#!/usr/bin/env python3
"""Manage the public blind-holdout query counter.

The counter lives in docs/Holdout-Query-Log.md. It records how many
blind re-executions each adapter line has used, never case details.
See docs/Holdout-Query-Budget.md for the policy.

Usage:
    python3 scripts/holdout_query_log.py log --adapter "name v1.2.3"
    python3 scripts/holdout_query_log.py log --adapter "name v1.2.3" --date 2026-09-29
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
    r"^-\s+(\d{4}-\d{2}-\d{2})\s+\|\s+(.+?)\s+\|\s+execution\s+(\d+)\s+of\s+"
    + str(BUDGET_PER_YEAR) + r"\s+in\s+(\d{4})\s*$")
ROTATION_RE = re.compile(r"^-\s+(\d{4}-\d{2}-\d{2})\s+\|\s+ROTATION\s+\|\s+(.+?)\s*$")


def _read_entries():
    """Parse log entries. Returns (entries, rotations)."""
    text = LOG_PATH.read_text(encoding="utf-8")
    # Strip the HTML comment block: it holds format examples that must
    # not parse as real entries.
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    entries = []  # (date, adapter, n, year, lineno)
    rotations = []  # (date, kind, lineno)
    for lineno, line in enumerate(text.splitlines()):
        m = ENTRY_RE.match(line)
        if m:
            entries.append((m.group(1), m.group(2), int(m.group(3)),
                            int(m.group(4)), lineno))
            continue
        m = ROTATION_RE.match(line)
        if m:
            rotations.append((m.group(1), m.group(2), lineno))
    return entries, rotations


def _used_this_year(entries, adapter, year):
    return sum(1 for _, a, _, y, _ in entries if a == adapter and y == year)


def _post_rotation(entries, rotations):
    """Entries logged after the most recent rotation.

    A rotation resets every adapter line's yearly budget (policy: after
    a rotation, further blind runs do not wait for next year). The log
    is append-only, so entries physically after the rotation line were
    logged after it. Backdated entries from before the rotation are
    rejected at log time in cmd_log, so the positional filter here is
    a second layer, not the only one.
    """
    if not rotations:
        return entries
    cutoff_lineno = max(lineno for _, _, lineno in rotations)
    return [e for e in entries if e[4] > cutoff_lineno]


def _parse_date(s: str):
    """Parse a YYYY-MM-DD date, rejecting invalid and future dates."""
    try:
        when = date.fromisoformat(s)
    except ValueError:
        return None
    if when > date.today():
        return None
    return when


def _insert_log_line(text: str, line: str, year: int) -> str:
    """Insert a log line under its ## YYYY section.

    Creates the year heading when missing and drops the empty-log
    placeholder paragraph on the first real entry. The HTML comment
    block (format documentation) stays at the end.
    """
    marker = "<!--"
    if marker in text:
        head, tail = text.split(marker, 1)
        tail = marker + tail
    else:
        head, tail = text, ""

    lines = head.splitlines()
    out: list[str] = []
    skipping = False
    for ln in lines:
        if "No blind re-executions have been run yet." in ln:
            skipping = True
            continue
        if skipping:
            if not ln.strip() or ln.startswith("## "):
                skipping = False
            else:
                continue
        out.append(ln)

    heading = f"## {year}"
    idx = next((i for i, ln in enumerate(out)
                if ln.strip() == heading), None)
    entry = line.rstrip("\n")
    if idx is None:
        while out and not out[-1].strip():
            out.pop()
        out.extend(["", heading, entry])
    else:
        j = idx + 1
        while j < len(out) and not out[j].startswith("## "):
            j += 1
        k = j
        while k > idx + 1 and not out[k - 1].strip():
            k -= 1
        out.insert(k, entry)
    return "\n".join(out).rstrip("\n") + "\n" + tail


def _write_log_atomically(new_text: str) -> None:
    # Atomic replace for the write itself. A concurrent process can
    # still interleave read-modify-write; this script is single-user and
    # runs are infrequent, so that residual race is accepted.
    tmp = LOG_PATH.with_suffix(".md.tmp")
    tmp.write_text(new_text, encoding="utf-8")
    tmp.replace(LOG_PATH)


def cmd_log(args) -> int:
    when = _parse_date(args.date)
    if when is None:
        print(f"error: bad --date {args.date!r}: want a real "
              f"YYYY-MM-DD date, not in the future", file=sys.stderr)
        return 1
    name = args.adapter.strip()
    if not name:
        print("error: --adapter must not be empty", file=sys.stderr)
        return 1
    if "\n" in name or "\r" in name:
        print("error: --adapter must be a single line", file=sys.stderr)
        return 1
    if "|" in name:
        print("error: --adapter must not contain '|'", file=sys.stderr)
        return 1
    if "<" in name or ">" in name:
        print("error: --adapter must not contain '<' or '>'", file=sys.stderr)
        return 1
    entries, rotations = _read_entries()
    # Reject backdated entries from before the most recent rotation:
    # they would evade the post-rotation budget (cross-year backdates
    # land under a different ## YYYY heading, before the rotation line).
    if rotations:
        latest_rotation = max(rd for rd, _, _ in rotations)
        if when.isoformat() < latest_rotation:
            print(f"error: --date {when.isoformat()} is before the most "
                  f"recent rotation ({latest_rotation}); backdated entries "
                  f"from before a rotation are not allowed",
                  file=sys.stderr)
            return 1
    entries = _post_rotation(entries, rotations)
    year = when.year
    used = _used_this_year(entries, name, year)
    if used >= BUDGET_PER_YEAR:
        print(f"error: {name} exhausted its {BUDGET_PER_YEAR} "
              f"executions for {year} ({used} used). "
              f"Further blind runs wait for next year or a rotation. "
              f"See docs/Holdout-Query-Budget.md.",
              file=sys.stderr)
        return 1
    n = used + 1
    line = (f"- {when.isoformat()} | {name} | execution {n} of "
            f"{BUDGET_PER_YEAR} in {year}\n")
    text = LOG_PATH.read_text(encoding="utf-8")
    _write_log_atomically(_insert_log_line(text, line, year))
    print(f"logged: {name} execution {n} of {BUDGET_PER_YEAR} in {year}")
    return 0


def cmd_rotation(args) -> int:
    when = _parse_date(args.date)
    if when is None:
        print(f"error: bad --date {args.date!r}: want a real "
              f"YYYY-MM-DD date, not in the future", file=sys.stderr)
        return 1
    day = when.isoformat()
    line = f"- {day} | ROTATION | {args.kind} rotation announced\n"
    text = LOG_PATH.read_text(encoding="utf-8")
    _write_log_atomically(
        _insert_log_line(text, line, when.year))
    print(f"logged rotation: {args.kind}")
    return 0


def cmd_status(args) -> int:
    entries, rotations = _read_entries()
    entries = _post_rotation(entries, rotations)
    year = args.year if args.year is not None else date.today().year
    if args.adapter:
        name = args.adapter.strip()
        used = _used_this_year(entries, name, year)
        print(f"{name}: {used} of {BUDGET_PER_YEAR} used in {year} "
              f"({BUDGET_PER_YEAR - used} remaining)")
    else:
        by_adapter: dict[str, int] = {}
        for _, a, _, y, _ in entries:
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
    p.add_argument("--date", default=date.today().isoformat(),
                   help="rotation date YYYY-MM-DD (default: today)")

    p = sub.add_parser("status", help="show budget usage")
    p.add_argument("--adapter", default=None,
                   help="adapter line (default: all)")
    p.add_argument("--year", type=int, default=None,
                   help="budget year to report (default: current year)")

    args = ap.parse_args()
    if args.cmd == "log":
        return cmd_log(args)
    if args.cmd == "rotation":
        return cmd_rotation(args)
    return cmd_status(args)


if __name__ == "__main__":
    sys.exit(main())
