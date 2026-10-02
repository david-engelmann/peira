"""Static HTML transcript viewer (R-18).

Renders a JSONL run transcript (written by ``peira run --transcript``)
as a single self-contained HTML file: no external CSS, no JavaScript,
no third-party dependencies, stdlib only. Rows are collapsible via
native <details> elements so no script is needed at all.

Every dynamic value is HTML-escaped, including the pretty-printed
raw entry JSON, so hostile transcript content (a crafted case input
containing ``</script>`` or similar) can never break out of the page.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

_CSS = """\
body{font-family:system-ui,sans-serif;max-width:1100px;margin:2em auto;
padding:0 1em;color:#1a1a1a}
table{border-collapse:collapse;width:100%;margin-top:1em}
th,td{border:1px solid #ccc;padding:.35em .6em;text-align:left;
font-size:.85em;vertical-align:top}
th{background:#f4f4f4}
.badge{display:inline-block;padding:.1em .5em;border-radius:1em;
font-size:.8em;font-weight:bold}
.ok{background:#e6f4ea;color:#137333}
.err{background:#fce8e6;color:#a50e0e}
.warn{background:#fef7e0;color:#b06000}
details{margin-top:.3em}
pre{background:#f8f8f8;padding:.6em;overflow-x:auto;font-size:.8em}
.summary li{margin:.2em 0}
"""


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _badge(text: str, kind: str) -> str:
    return f'<span class="badge {kind}">{_esc(text)}</span>'


def _decision(entry: dict) -> str:
    response = entry.get("response") or {}
    if response.get("kind") == "error":
        return response.get("error", "error")
    output = response.get("output") or {}
    return output.get("decision", "")


def _flags(entry: dict) -> list[str]:
    flags = []
    if entry.get("timed_out"):
        flags.append("timeout")
    if entry.get("token_limit_exceeded"):
        flags.append("token-limit")
    if entry.get("cached"):
        flags.append("cached")
    return flags


def load_entries(path: str | Path) -> tuple[list[dict], int]:
    """Read a JSONL transcript. Returns (entries, bad_lines)."""
    entries: list[dict] = []
    bad = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                bad += 1
    return entries, bad


def render(path: str | Path) -> str:
    """Render the transcript at ``path`` as a standalone HTML page."""
    entries, bad = load_entries(path)
    n_output = sum(
        1 for e in entries
        if (e.get("response") or {}).get("kind") == "output"
    )
    n_error = sum(
        1 for e in entries
        if (e.get("response") or {}).get("kind") == "error"
    )
    n_timeout = sum(1 for e in entries if e.get("timed_out"))
    n_token = sum(1 for e in entries if e.get("token_limit_exceeded"))
    n_cached = sum(1 for e in entries if e.get("cached"))

    rows = []
    for e in entries:
        response = e.get("response") or {}
        kind = response.get("kind", "?")
        status = _badge(kind, "ok" if kind == "output" else "err")
        flags = " ".join(
            _badge(f, "warn" if f != "cached" else "ok") for f in _flags(e)
        )
        full = _esc(json.dumps(e, indent=2, ensure_ascii=False,
                               default=str))
        rows.append(
            "<tr>"
            f"<td>{_esc(e.get('dispatch_index', ''))}</td>"
            f"<td>{_esc(e.get('case_id', ''))}</td>"
            f"<td>{_esc(e.get('variant', ''))}</td>"
            f"<td>{_esc(e.get('primitive', ''))}</td>"
            f"<td>{status}<br>{_esc(_decision(e))}</td>"
            f"<td>{_esc(e.get('latency_ms_total', e.get('latency_ms', '')))}</td>"
            f"<td>{_esc(e.get('attempts', ''))}</td>"
            f"<td>{flags}</td>"
            "<td><details><summary>full entry</summary>"
            f"<pre>{full}</pre></details></td>"
            "</tr>"
        )

    summary_items = [
        f"entries: {len(entries)}",
        f"outputs: {n_output}",
        f"errors: {n_error}",
        f"timeouts: {n_timeout}",
        f"token-limit violations: {n_token}",
        f"cache hits: {n_cached}",
    ]
    if bad:
        summary_items.append(f"unparseable lines skipped: {bad}")
    summary = "".join(f"<li>{_esc(item)}</li>" for item in summary_items)

    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Peira transcript: {_esc(Path(path).name)}</title>
<style>{_CSS}</style>
</head>
<body>
<h1>Peira run transcript</h1>
<p>source file: {_esc(str(path))}</p>
<ul class="summary">{summary}</ul>
<table>
<tr><th>#</th><th>case</th><th>variant</th><th>primitive</th>
<th>response</th><th>latency ms</th><th>attempts</th><th>flags</th>
<th>detail</th></tr>
{''.join(rows)}
</table>
</body>
</html>
"""


def write_html(transcript_path: str | Path, out_path: str | Path) -> None:
    Path(out_path).write_text(render(transcript_path), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Render a peira JSONL transcript as static HTML.")
    parser.add_argument("--transcript", required=True,
                        help="transcript JSONL written by peira run")
    parser.add_argument("--out", required=True,
                        help="output HTML path")
    args = parser.parse_args(argv)
    write_html(args.transcript, args.out)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
