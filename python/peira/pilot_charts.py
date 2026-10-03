"""Pilot-run SVG charts: stdlib-only, no JavaScript, no external resources.

Follows the ``report_html`` contract: every chart is an inline ``<svg>``
computed server-side, every interpolated value HTML-escaped, no
``<script>`` elements. Charts take the analysis dicts from
``pilot_analysis`` and return SVG strings.

Charts:
- ``family_heatmap_svg``: per-model x per-family ASR heatmap.
- ``cost_scatter_svg``: total cost vs mean ASR, bubble size = n eligible.
- ``attack_bars_svg``: mean ASR per family across models (attack
  effectiveness ranking).
- ``rank_chart_svg``: mean Friedman ranks with Nemenyi CD whiskers.
"""

from __future__ import annotations

import html
import math
from typing import Any


def _esc(x: Any) -> str:
    return html.escape(str(x), quote=True)


def _num(x: Any) -> float | None:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    f = float(x)
    return f if math.isfinite(f) else None


def _asr_color(v: float) -> str:
    """Green (low ASR, robust) to red (high ASR, vulnerable)."""
    v = max(0.0, min(1.0, v))
    r = int(47 + (185 - 47) * v)
    g = int(111 + (60 - 111) * v)
    b = int(79 + (60 - 79) * v)
    return f"#{r:02x}{g:02x}{b:02x}"


def family_heatmap_svg(matrix: dict[str, Any]) -> str:
    """Per-model x per-family ASR heatmap with values in cells."""
    families: list[str] = matrix.get("families", [])
    rows: list[dict[str, Any]] = matrix.get("rows", [])
    if not families or not rows:
        return '<p class="muted">No family matrix data.</p>'
    cell_w, cell_h = 64, 28
    pad_l, pad_t = 170, 30
    W = pad_l + len(families) * cell_w + 20
    H = pad_t + len(rows) * cell_h + 20
    parts = [
        f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
        'role="img" aria-label="Per-model per-family attack success rate heatmap">'
    ]
    # Column headers (rotated family names).
    for j, fam in enumerate(families):
        x = pad_l + j * cell_w + cell_w / 2
        parts.append(
            f'<text x="{x:.1f}" y="{pad_t - 8}" font-size="9" '
            f'text-anchor="end" fill="#333" transform="rotate(-45 {x:.1f} {pad_t - 8})">'
            f'{_esc(fam[:22])}</text>'
        )
    for i, row in enumerate(rows):
        y = pad_t + i * cell_h
        name = _esc(str(row.get("adapter_name", "?"))[:24])
        parts.append(
            f'<text x="{pad_l - 8}" y="{y + cell_h / 2 + 4}" font-size="10" '
            f'text-anchor="end" fill="#222">{name}</text>'
        )
        for j, fam in enumerate(families):
            cell = row.get("cells", {}).get(fam, {})
            asr = _num(cell.get("asr"))
            x = pad_l + j * cell_w
            if asr is None:
                fill, label = "#eee", "n/a"
            else:
                fill, label = _asr_color(asr), f"{asr:.2f}"
            parts.append(
                f'<rect x="{x:.1f}" y="{y}" width="{cell_w}" height="{cell_h}" '
                f'fill="{fill}" stroke="#fff"/>'
                f'<text x="{x + cell_w / 2:.1f}" y="{y + cell_h / 2 + 4}" '
                f'font-size="9" text-anchor="middle" '
                f'fill="{"#fff" if asr is not None and asr > 0.55 else "#222"}">'
                f'{label}</text>'
            )
    # Legend.
    lx = pad_l
    ly = H - 12
    parts.append(
        f'<text x="{lx}" y="{ly}" font-size="9" fill="#666">'
        'Low ASR (robust)</text>'
    )
    for k in range(5):
        v = k / 4.0
        parts.append(
            f'<rect x="{lx + 110 + k * 18}" y="{ly - 10}" width="18" '
            f'height="10" fill="{_asr_color(v)}" stroke="#fff"/>'
        )
    parts.append(
        f'<text x="{lx + 210}" y="{ly}" font-size="9" fill="#666">'
        'High ASR (vulnerable)</text>'
    )
    parts.append("</svg>")
    return "\n".join(parts)


def cost_scatter_svg(cost_data: dict[str, Any]) -> str:
    """Total cost (x, log scale) vs mean ASR (y). Bubble size = n eligible."""
    rows: list[dict[str, Any]] = cost_data.get("rows", [])
    pts = [
        r for r in rows
        if _num(r.get("total_cost_usd")) is not None
        and _num(r.get("mean_asr")) is not None
    ]
    if not pts:
        return '<p class="muted">No cost data.</p>'
    W, H = 640, 420
    pad_l, pad_r, pad_t, pad_b = 60, 30, 20, 50
    plot_w, plot_h = W - pad_l - pad_r, H - pad_t - pad_b
    costs = [_num(p["total_cost_usd"]) for p in pts]
    lo_c, hi_c = min(costs), max(costs)
    if lo_c <= 0:
        lo_c = min(c for c in costs if c > 0) if any(c > 0 for c in costs) else 1e-6
    lo_l, hi_l = math.log10(lo_c), math.log10(hi_c)
    if hi_l == lo_l:
        hi_l = lo_l + 1.0

    def x(c: float) -> float:
        return pad_l + (math.log10(max(c, 1e-9)) - lo_l) / (hi_l - lo_l) * plot_w

    def y(a: float) -> float:
        return pad_t + (1.0 - a) * plot_h

    max_n = max((_num(p.get("n_eligible")) or 0 for p in pts), default=1) or 1
    parts = [
        f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
        'role="img" aria-label="Cost versus attack success rate scatter plot">'
    ]
    # Gridlines and log-scale x ticks.
    import math as _m
    tick = _m.floor(lo_l)
    while tick <= hi_l + 1:
        tx = x(10 ** tick)
        if pad_l <= tx <= pad_l + plot_w:
            parts.append(
                f'<line x1="{tx:.1f}" y1="{pad_t}" x2="{tx:.1f}" '
                f'y2="{H - pad_b}" stroke="#ddd"/>'
                f'<text x="{tx:.1f}" y="{H - pad_b + 16}" font-size="9" '
                f'text-anchor="middle" fill="#666">${10 ** tick:g}</text>'
            )
        tick += 1
    for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
        ty = y(frac)
        parts.append(
            f'<line x1="{pad_l}" y1="{ty:.1f}" x2="{W - pad_r}" '
            f'y2="{ty:.1f}" stroke="#eee"/>'
            f'<text x="{pad_l - 8}" y="{ty + 4:.1f}" font-size="9" '
            f'text-anchor="end" fill="#666">{frac:.2f}</text>'
        )
    parts.append(
        f'<text x="{pad_l + plot_w / 2:.1f}" y="{H - 8}" font-size="11" '
        f'text-anchor="middle" fill="#333">Total run cost (USD, log scale)</text>'
        f'<text x="14" y="{pad_t + plot_h / 2:.1f}" font-size="11" '
        f'text-anchor="middle" fill="#333" '
        f'transform="rotate(-90 14 {pad_t + plot_h / 2:.1f})">Mean ASR (lower is better)</text>'
    )
    for p in pts:
        c, a = _num(p["total_cost_usd"]), _num(p["mean_asr"])
        n = _num(p.get("n_eligible")) or 0
        r = 4 + 10 * math.sqrt(n / max_n)
        name = _esc(str(p.get("adapter_name", "?"))[:20])
        parts.append(
            f'<circle cx="{x(c):.1f}" cy="{y(a):.1f}" r="{r:.1f}" '
            f'fill="#2f6f4f" fill-opacity="0.55" stroke="#2f6f4f"/>'
            f'<text x="{x(c) + r + 3:.1f}" y="{y(a) + 4:.1f}" font-size="9" '
            f'fill="#222">{name}</text>'
        )
    parts.append("</svg>")
    return "\n".join(parts)


def attack_bars_svg(effectiveness: dict[str, Any], top_n: int = 15) -> str:
    """Horizontal bars of mean ASR per family (most effective attacks first)."""
    items: list[dict[str, Any]] = effectiveness.get("most_effective_attacks", [])
    shown = [it for it in items if _num(it.get("mean_asr")) is not None][:top_n]
    if not shown:
        return '<p class="muted">No attack effectiveness data.</p>'
    W, bar_h, gap, pad_l, pad_r = 640, 16, 8, 200, 60
    H = len(shown) * (bar_h + gap) + 40
    plot_w = W - pad_l - pad_r
    top = max((_num(it["mean_asr"]) or 0.0 for it in shown), default=0.0)
    top = max(top * 1.05, 0.05)

    def x(v: float) -> float:
        return pad_l + (v / top) * plot_w

    parts = [
        f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
        'role="img" aria-label="Most effective attack families by mean attack success rate">'
    ]
    for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
        tx = x(top * frac)
        parts.append(
            f'<line x1="{tx:.1f}" y1="10" x2="{tx:.1f}" y2="{H - 24}" stroke="#ddd"/>'
            f'<text x="{tx:.1f}" y="{H - 8}" font-size="10" '
            f'text-anchor="middle" fill="#666">{top * frac:.2f}</text>'
        )
    for i, it in enumerate(shown):
        yy = 14 + i * (bar_h + gap)
        fam = _esc(str(it.get("family", "?"))[:30])
        asr = _num(it.get("mean_asr")) or 0.0
        parts.append(
            f'<text x="{pad_l - 8}" y="{yy + bar_h - 3}" font-size="10" '
            f'text-anchor="end" fill="#222">{fam}</text>'
            f'<rect x="{x(0):.1f}" y="{yy}" width="{x(asr) - x(0):.1f}" '
            f'height="{bar_h}" fill="{_asr_color(asr)}"/>'
            f'<text x="{x(asr) + 4:.1f}" y="{yy + bar_h - 3}" font-size="10" '
            f'fill="#333">{asr:.3f}</text>'
        )
    parts.append("</svg>")
    return "\n".join(parts)


def rank_chart_svg(ranking: dict[str, Any]) -> str:
    """Mean Friedman ranks with Nemenyi critical-difference whiskers."""
    mean_ranks: list[dict[str, Any]] = ranking.get("mean_ranks", [])
    cd = _num(ranking.get("nemenyi_cd_05"))
    shown = [m for m in mean_ranks if _num(m.get("mean_rank")) is not None]
    if not shown:
        return '<p class="muted">No ranking data.</p>'
    shown.sort(key=lambda m: _num(m["mean_rank"]) or 0.0)
    W, bar_h, gap, pad_l, pad_r = 640, 16, 8, 200, 60
    H = len(shown) * (bar_h + gap) + 40
    plot_w = W - pad_l - pad_r
    max_rank = max((_num(m["mean_rank"]) or 0.0 for m in shown), default=1.0)
    top = max_rank * 1.1 + (cd or 0.0)

    def x(v: float) -> float:
        return pad_l + (v / top) * plot_w

    parts = [
        f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
        'role="img" aria-label="Mean Friedman ranks with Nemenyi critical difference">'
    ]
    for i, m in enumerate(shown):
        yy = 14 + i * (bar_h + gap)
        name = _esc(str(m.get("adapter_name", "?"))[:28])
        mr = _num(m.get("mean_rank")) or 0.0
        parts.append(
            f'<text x="{pad_l - 8}" y="{yy + bar_h - 3}" font-size="10" '
            f'text-anchor="end" fill="#222">{name}</text>'
            f'<rect x="{x(0):.1f}" y="{yy}" width="{x(mr) - x(0):.1f}" '
            f'height="{bar_h}" fill="#4a6fa5"/>'
        )
        if cd is not None:
            lo, hi = max(0.0, mr - cd), mr + cd
            cy = yy + bar_h / 2
            parts.append(
                f'<line x1="{x(lo):.1f}" y1="{cy:.1f}" x2="{x(hi):.1f}" '
                f'y2="{cy:.1f}" stroke="#111" stroke-width="2"/>'
            )
        parts.append(
            f'<text x="{x(mr) + 4:.1f}" y="{yy + bar_h - 3}" font-size="10" '
            f'fill="#333">{mr:.2f}</text>'
        )
    if cd is not None:
        parts.append(
            f'<text x="{pad_l}" y="{H - 8}" font-size="9" fill="#666">'
            f'Whiskers show the Nemenyi critical difference ({cd:.2f}); '
            'non-overlapping whiskers differ significantly at alpha 0.05.</text>'
        )
    parts.append("</svg>")
    return "\n".join(parts)
