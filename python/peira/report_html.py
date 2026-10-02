"""Zero-JavaScript self-contained HTML report artifacts.

``leaderboard_to_html`` renders a leaderboard payload as a single HTML
file with no JavaScript, no external resources, and charts as inline
SVG. A public benchmark's reports get saved, cited, and screenshotted
years later. A JS-dependent page rots. A self-contained file is forever.

Contract (pinned by ``tests/test_report_html_contract.py``):

- no ``<script>`` elements anywhere
- no external resource references (no http/https ``src``/``href``, no
  ``<link>``, no ``<img>``)
- every chart is an inline ``<svg>`` computed server-side
- every interpolated value is HTML-escaped
- the data source (official vs mock) is bannered, never implied

Everything here is stdlib only. The renderer is pure: payload in,
string out.
"""

from __future__ import annotations

import html
import math
from datetime import datetime, timezone
from typing import Any


def _esc(x: Any) -> str:
    return html.escape(str(x), quote=True)


def _num(x: Any) -> float | None:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    f = float(x)
    # Non-finite values render as "nan"/"inf" text and can poison SVG
    # width arithmetic; treat them as missing data instead.
    return f if math.isfinite(f) else None


def _fmt(v: Any) -> str:
    n = _num(v)
    return f"{n:.4f}" if n is not None else "n/a"


def _fmt_ci(ci: Any) -> str:
    if not isinstance(ci, (list, tuple)) or len(ci) != 2:
        return "n/a"
    lo, hi = _num(ci[0]), _num(ci[1])
    if lo is None or hi is None:
        return "n/a"
    return f"{lo:.4f} to {hi:.4f}"


def _asr_chart_svg(rows: list[dict[str, Any]]) -> str:
    """Horizontal bars of ASR per adapter with Wilson CI whiskers."""
    # The chart caps at 25 rows to keep the SVG readable; every ranked
    # row still appears in the table below, chart or not.
    shown = [r for r in rows if _num(r.get("asr_conditional")) is not None][:25]
    if not shown:
        return '<p class="muted">No ranked adapters with ASR data.</p>'
    W, bar_h, gap, pad_l, pad_r = 640, 18, 10, 180, 60
    H = len(shown) * (bar_h + gap) + 40
    plot_w = W - pad_l - pad_r
    def _row_top(r: dict[str, Any]) -> float:
        ci = r.get("asr_ci95")
        if isinstance(ci, (list, tuple)) and len(ci) == 2:
            hi = _num(ci[1])
            if hi is not None:
                return hi
        return _num(r.get("asr_conditional")) or 0.0

    top = max((_row_top(r) for r in shown), default=0.0)
    top = max(top * 1.05, 0.05)

    def x(v: float) -> float:
        return pad_l + (v / top) * plot_w

    parts = [f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
             f'role="img" aria-label="ASR by adapter with 95 percent confidence intervals">']
    # x-axis ticks at 0, 25, 50, 75, 100 percent of the scale
    for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
        tx = x(top * frac)
        parts.append(
            f'<line x1="{tx:.1f}" y1="10" x2="{tx:.1f}" y2="{H - 24}" '
            f'stroke="#ddd"/>'
            f'<text x="{tx:.1f}" y="{H - 8}" font-size="10" '
            f'text-anchor="middle" fill="#666">{top * frac:.2f}</text>')
    for i, r in enumerate(shown):
        y = 14 + i * (bar_h + gap)
        name = _esc(str(r.get("adapter_name", "?"))[:28])
        asr = _num(r.get("asr_conditional"))
        ci = r.get("asr_ci95")
        lo = hi = None
        if isinstance(ci, (list, tuple)) and len(ci) == 2:
            lo, hi = _num(ci[0]), _num(ci[1])
        parts.append(
            f'<text x="{pad_l - 8}" y="{y + bar_h - 4}" font-size="11" '
            f'text-anchor="end" fill="#222">{name}</text>'
            f'<rect x="{x(0):.1f}" y="{y}" width="{x(asr) - x(0):.1f}" '
            f'height="{bar_h}" fill="#2f6f4f"/>')
        if lo is not None and hi is not None:
            cy = y + bar_h / 2
            parts.append(
                f'<line x1="{x(lo):.1f}" y1="{cy:.1f}" x2="{x(hi):.1f}" '
                f'y2="{cy:.1f}" stroke="#111" stroke-width="2"/>'
                f'<line x1="{x(lo):.1f}" y1="{cy - 5:.1f}" x2="{x(lo):.1f}" '
                f'y2="{cy + 5:.1f}" stroke="#111" stroke-width="2"/>'
                f'<line x1="{x(hi):.1f}" y1="{cy - 5:.1f}" x2="{x(hi):.1f}" '
                f'y2="{cy + 5:.1f}" stroke="#111" stroke-width="2"/>')
    parts.append("</svg>")
    return "\n".join(parts)


def _ranked_table(rows: list[dict[str, Any]]) -> str:
    body = []
    for i, r in enumerate(rows, 1):
        body.append(
            "<tr>"
            f"<td>{i}</td>"
            f"<td>{_esc(r.get('adapter_name', '?'))}</td>"
            f"<td>{_esc(r.get('adapter_version', ''))}</td>"
            f"<td>{_fmt(r.get('asr_conditional'))}</td>"
            f"<td>{_fmt_ci(r.get('asr_ci95'))}</td>"
            f"<td>{_fmt(r.get('benign_accuracy'))}</td>"
            f"<td>{_esc(r.get('n_eligible', 'n/a'))}</td>"
            f"<td>{_fmt(r.get('total_cost_usd'))}</td>"
            f"<td>{_fmt(r.get('latency_ms_p50_attacked'))}</td>"
            f"<td>{_fmt(r.get('ece_attacked'))}</td>"
            "</tr>"
        )
    return (
        '<table><thead><tr><th>Rank</th><th>Adapter</th><th>Version</th>'
        "<th>ASR</th><th>ASR 95% CI</th><th>Benign acc.</th>"
        "<th>Eligible n</th><th>Cost USD</th><th>Latency p50 ms</th>"
        "<th>ECE</th></tr></thead><tbody>\n"
        + "\n".join(body)
        + "\n</tbody></table>"
    )


def _unranked_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    body = "\n".join(
        "<tr>"
        f"<td>{_esc(r.get('adapter_name', '?'))}</td>"
        f"<td>{_esc(r.get('adapter_version', ''))}</td>"
        f"<td>{_esc(r.get('reason', 'no reason recorded'))}</td>"
        "</tr>"
        for r in rows if isinstance(r, dict)
    )
    return (
        "<h2>Not ranked</h2>"
        "<p>Omission never improves a rank. These adapters ran but did "
        "not qualify, and the reason is shown.</p>"
        '<table><thead><tr><th>Adapter</th><th>Version</th>'
        "<th>Reason</th></tr></thead><tbody>\n"
        + body + "\n</tbody></table>"
    )


_BANNER_OFFICIAL = (
    '<div class="banner official">Official results. Produced from a '
    "frozen dataset tag under the published methodology. The methodology "
    "is pre-registered and field-untested: treat these as the current "
    "best measurement, not as settled fact.</div>"
)
_BANNER_MOCK = (
    '<div class="banner mock">MOCK DATA. This report was rendered from '
    "placeholder data, not an official evaluation. Do not cite, rank, or "
    "publish these numbers.</div>"
)

_FOOTER = (
    "<h2>Reading this report</h2>"
    "<ul>"
    "<li>ASR is the attack success rate: the fraction of eligible cases "
    "where the attacked-arm decision differs from the benign-arm decision. "
    "Lower is more robust.</li>"
    "<li>Every ASR carries a Wilson 95 percent confidence interval. "
    "Overlapping intervals are not ties, and a difference smaller than "
    "the per-family minimum detectable effect is not resolvable at this "
    "sample size. Do not claim a win the data cannot support.</li>"
    "<li>Metric definitions and per-metric anti-misuse statements live in "
    "docs/Analytics-Methodology.md, which is the canonical home for what "
    "each number means and what it must not be read as.</li>"
    "<li>This file is self-contained: no JavaScript, no external "
    "resources, charts as inline SVG. Save it, cite it, screenshot it. "
    "It will still render.</li>"
    "</ul>"
)

_CSS = (
    "body{font-family:system-ui,-apple-system,sans-serif;max-width:960px;"
    "margin:2rem auto;padding:0 1rem;color:#1a1a1a;line-height:1.5}"
    "table{border-collapse:collapse;width:100%;margin:1rem 0;font-size:13px}"
    "th,td{border:1px solid #ccc;padding:6px 8px;text-align:left}"
    "th{background:#f4f4f4}.banner{padding:12px 16px;border-radius:6px;"
    "font-weight:600;margin:1rem 0}"
    ".banner.mock{background:#fde8e8;border:2px solid #c0392b;color:#7a1f14}"
    ".banner.official{background:#e8f5e9;border:2px solid #2f6f4f;color:#1d4a33}"
    ".muted{color:#666}code{background:#f4f4f4;padding:2px 4px}"
)


def leaderboard_to_html(payload: dict[str, Any],
                        data_source: str = "mock",
                        generated_utc: str | None = None,
                        title: str = "peira leaderboard") -> str:
    """Render a leaderboard payload as self-contained HTML.

    ``data_source`` is ``"official"`` or anything else (bannered as
    mock). It defaults to mock: a report must never present itself as
    official unless the caller says so explicitly.
    """
    ranked = payload.get("ranked")
    ranked = [r for r in ranked if isinstance(r, dict)] if isinstance(ranked, list) else []
    unranked = payload.get("unranked")
    unranked = [r for r in unranked if isinstance(r, dict)] if isinstance(unranked, list) else []
    banner = _BANNER_OFFICIAL if data_source == "official" else _BANNER_MOCK
    stamp = generated_utc or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return (
        "<!DOCTYPE html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
        f"<title>{_esc(title)}</title>"
        f"<style>{_CSS}</style></head><body>"
        f"<h1>{_esc(title)}</h1>"
        f'<p class="muted">Generated {_esc(stamp)}. '
        f"{len(ranked)} ranked, {len(unranked)} not ranked.</p>"
        f"{banner}"
        "<h2>Attack success rate by adapter</h2>"
        f"{_asr_chart_svg(ranked)}"
        "<h2>Rankings</h2>"
        f"{_ranked_table(ranked)}"
        f"{_unranked_table(unranked)}"
        f"{_FOOTER}"
        "</body></html>\n"
    )
