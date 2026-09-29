#!/usr/bin/env python3
"""Render the peira leaderboard OG/social image from site-data JSON.

Reads the site-data JSON (the same artifact the dashboard consumes),
draws a top-N horizontal bar chart of ``asr_conditional`` with 95% CI
whiskers, and writes a 1200x630 SVG plus a PNG rasterization.

The SVG is generated with pure Python (stdlib only). Rasterization uses
``cairosvg`` when it is importable; otherwise only the SVG is written and
a TODO is printed. Nothing here fakes a PNG: if no rasterizer exists,
no PNG file is produced.

Every number on the image comes straight from the site-data JSON. The
script never invents data. When ``mock_data`` is true the image carries
a "mock data" banner, because the same discipline that keeps mock
artifacts out of real builds applies to shared images.

Usage:
    python3 site/scripts/render_og.py [--in site/src/data/results.json]
        [--out site/assets/og/og-leaderboard] [--top-n 8] [--suite public]

Output files:
    <out>.svg        the source image
    <out>.png        rasterized 1200x630 PNG (only when cairosvg imports)
    <out>.alt.txt    alt text sidecar for the PNG
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path
from typing import NoReturn

REPO_ROOT = Path(__file__).resolve().parents[2]
SITE_ROOT = REPO_ROOT / "site"

WIDTH, HEIGHT = 1200, 630
TOP_N_DEFAULT = 8

BG = "#0f1a14"
CARD = "#16241c"
GRID = "#2a3b31"
TEXT = "#eef4ee"
MUTED = "#a8bcb0"
ACCENT = "#7fd79a"
ACCENT_DIM = "#3e6b4e"
WARN = "#e8b34b"
FONT = "DejaVu Sans, Verdana, sans-serif"


def fail(msg: str) -> "NoReturn":
    print(f"render_og: error: {msg}", file=sys.stderr)
    raise SystemExit(1)


def pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def load_runs(path: Path, suite: str) -> tuple[dict, list[dict]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"cannot read {path}: {exc}")
    runs = [r for r in data.get("runs", []) if r.get("suite") == suite]
    scored = []
    for r in runs:
        m = r.get("metrics") or {}
        asr = m.get("asr_conditional")
        ci = m.get("asr_ci95") or [None, None]
        if asr is None:
            continue  # no headline metric, skip rather than invent one
        scored.append(
            {
                "adapter_name": str(r.get("adapter_name", "unknown")),
                "adapter_version": str(r.get("adapter_version", "")),
                "model_class": str(r.get("model_class", "")),
                "asr": float(asr),
                "ci_lo": float(ci[0]) if ci[0] is not None else None,
                "ci_hi": float(ci[1]) if ci[1] is not None else None,
                "n_eligible": m.get("n_eligible"),
            }
        )
    scored.sort(key=lambda s: s["asr"])
    return data, scored


def esc(s: str) -> str:
    return html.escape(s, quote=True)


def render(data: dict, scored: list[dict], top_n: int) -> str:
    top = scored[:top_n]
    mock = bool(data.get("mock_data"))
    peira_version = str(data.get("peira_version", ""))
    dataset_version = str((data.get("dataset") or {}).get("version", ""))

    chart_x, chart_w = 320, 780
    row_h = 44
    chart_y0 = 196
    grid_label_y = chart_y0 - 16
    bar_h = 18

    def x_for(v: float) -> float:
        return chart_x + v * chart_w  # asr is in [0, 1]

    rows = []
    for i, s in enumerate(top):
        y = chart_y0 + i * row_h
        cy = y + row_h / 2
        bx = x_for(s["asr"])
        label = s["adapter_name"]
        if s["adapter_version"]:
            label += " " + s["adapter_version"]
        rows.append(
            f'    <text x="{chart_x - 16}" y="{cy + 5}" text-anchor="end" '
            f'font-family="{FONT}" font-size="20" fill="{TEXT}">{esc(label)}</text>'
        )
        if s["n_eligible"] is not None:
            rows.append(
                f'    <text x="{chart_x - 16}" y="{cy + 24}" text-anchor="end" '
                f'font-family="{FONT}" font-size="14" fill="{MUTED}">'
                f'n equals {int(s["n_eligible"])} eligible</text>'
            )
        rows.append(
            f'    <rect x="{chart_x}" y="{cy - bar_h / 2}" '
            f'width="{max(bx - chart_x, 2):.1f}" height="{bar_h}" rx="4" fill="{ACCENT}"/>'
        )
        ci_lo_x = ci_hi_x = None
        if s["ci_lo"] is not None and s["ci_hi"] is not None:
            lo, hi = x_for(s["ci_lo"]), x_for(s["ci_hi"])
            ci_lo_x, ci_hi_x = lo, hi
            rows.append(
                f'    <line x1="{lo:.1f}" y1="{cy}" x2="{hi:.1f}" y2="{cy}" '
                f'stroke="{TEXT}" stroke-width="3"/>'
                f'<line x1="{lo:.1f}" y1="{cy - 10}" x2="{lo:.1f}" y2="{cy + 10}" '
                f'stroke="{TEXT}" stroke-width="3"/>'
                f'<line x1="{hi:.1f}" y1="{cy - 10}" x2="{hi:.1f}" y2="{cy + 10}" '
                f'stroke="{TEXT}" stroke-width="3"/>'
            )
        val_x = (ci_hi_x + 14) if ci_hi_x is not None else max(bx + 14, chart_x + 8)
        rows.append(
            f'    <text x="{val_x:.1f}" y="{cy + 7}" '
            f'font-family="{FONT}" font-size="20" font-weight="bold" fill="{TEXT}">'
            f'{pct(s["asr"])}</text>'
        )

    # Gridlines at 0/25/50/75/100 percent.
    grid = []
    for q in (0.0, 0.25, 0.5, 0.75, 1.0):
        gx = x_for(q)
        grid.append(
            f'    <line x1="{gx:.1f}" y1="{chart_y0 - 8}" '
            f'x2="{gx:.1f}" y2="{chart_y0 + len(top) * row_h}" '
            f'stroke="{GRID}" stroke-width="1"/>'
            f'<text x="{gx:.1f}" y="{grid_label_y}" text-anchor="middle" '
            f'font-family="{FONT}" font-size="14" fill="{MUTED}">{pct(q)}</text>'
        )

    mock_banner = ""
    if mock:
        mock_banner = (
            f'  <rect x="0" y="0" width="{WIDTH}" height="46" fill="{WARN}"/>'
            f'<text x="{WIDTH / 2}" y="31" text-anchor="middle" '
            f'font-family="{FONT}" font-size="22" font-weight="bold" fill="#3a2b00">'
            f'MOCK DATA, NOT REAL RESULTS</text>'
        )

    subtitle_bits = ["conditional attack success rate", "lower is better"]
    if dataset_version:
        subtitle_bits.append(f"dataset {dataset_version}")
    subtitle = " \u00b7 ".join(subtitle_bits)
    footer_right = "generated from sealed run artifacts"
    if peira_version:
        footer_right = f"peira {peira_version} \u00b7 " + footer_right

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-label="{esc('peira leaderboard OG image, ' + ('mock data' if mock else 'benchmark results'))}">
  <rect width="{WIDTH}" height="{HEIGHT}" fill="{BG}"/>
  <rect x="24" y="24" width="{WIDTH - 48}" height="{HEIGHT - 48}" rx="12" fill="{CARD}"/>
{mock_banner}
  <text x="64" y="112" font-family="{FONT}" font-size="44" font-weight="bold" fill="{TEXT}">peira leaderboard</text>
  <text x="64" y="146" font-family="{FONT}" font-size="19" fill="{MUTED}">{esc(subtitle)}</text>
  <text x="{WIDTH - 64}" y="112" text-anchor="end" font-family="{FONT}" font-size="20" fill="{MUTED}">top {len(top)} adapters</text>
  <text x="{WIDTH - 64}" y="140" text-anchor="end" font-family="{FONT}" font-size="15" fill="{MUTED}">whiskers show 95 percent confidence intervals</text>
{chr(10).join(grid)}
{chr(10).join(rows)}
  <text x="64" y="{HEIGHT - 44}" font-family="{FONT}" font-size="15" fill="{MUTED}">peiratrial.dev</text>
  <text x="{WIDTH - 64}" y="{HEIGHT - 44}" text-anchor="end" font-family="{FONT}" font-size="15" fill="{MUTED}">{esc(footer_right)}</text>
</svg>
"""


def alt_text(data: dict, scored: list[dict], top_n: int) -> str:
    mock = bool(data.get("mock_data"))
    lines = [
        "OG social image for the peira leaderboard page.",
        "A dark card titled peira leaderboard with a horizontal bar chart "
        "of conditional attack success rate for the top adapters. Lower is better.",
        f"Data status is {'MOCK DATA, not real results' if mock else 'real benchmark results'}.",
    ]
    for i, s in enumerate(scored[:top_n], 1):
        ci = ""
        if s["ci_lo"] is not None and s["ci_hi"] is not None:
            ci = f" with 95 percent CI {pct(s['ci_lo'])} to {pct(s['ci_hi'])}"
        n = (
            f" and n equals {int(s['n_eligible'])} eligible cases"
            if s["n_eligible"] is not None
            else ""
        )
        lines.append(f"{i}. {s['adapter_name']} at {pct(s['asr'])}{ci}{n}.")
    return "\n".join(lines) + "\n"


def rasterize(svg: str, png_path: Path) -> bool:
    try:
        import cairosvg  # noqa: PLC0415
    except ImportError:
        return False
    cairosvg.svg2png(
        bytestring=svg.encode("utf-8"),
        write_to=str(png_path),
        output_width=WIDTH,
        output_height=HEIGHT,
    )
    return True


def main() -> None:
    ap = argparse.ArgumentParser(description="Render the peira OG image.")
    ap.add_argument(
        "--in",
        dest="inp",
        default=str(SITE_ROOT / "src" / "data" / "results.json"),
        help="site-data JSON path",
    )
    ap.add_argument(
        "--out",
        default=str(SITE_ROOT / "assets" / "og" / "og-leaderboard"),
        help="output base path (no extension)",
    )
    ap.add_argument("--top-n", type=int, default=TOP_N_DEFAULT)
    ap.add_argument("--suite", default="public", choices=("public", "holdout"))
    args = ap.parse_args()
    if not 1 <= args.top_n <= TOP_N_DEFAULT:
        fail(f"--top-n must be between 1 and {TOP_N_DEFAULT} (chart capacity)")

    data, scored = load_runs(Path(args.inp), args.suite)
    if not scored:
        fail("no runs with asr_conditional in the site-data JSON")

    out_base = Path(args.out)
    out_base.parent.mkdir(parents=True, exist_ok=True)
    svg = render(data, scored, args.top_n)
    svg_path = out_base.with_suffix(".svg")
    svg_path.write_text(svg, encoding="utf-8")
    print(f"render_og: wrote {svg_path} ({len(scored[: args.top_n])} bars)")

    alt_path = out_base.with_suffix(".alt.txt")
    alt_path.write_text(alt_text(data, scored, args.top_n), encoding="utf-8")
    print(f"render_og: wrote {alt_path}")

    png_path = out_base.with_suffix(".png")
    if rasterize(svg, png_path):
        print(f"render_og: wrote {png_path} via cairosvg (1200x630)")
    else:
        # Never leave a stale PNG next to fresh SVG/alt text: it could
        # show different numbers or a different mock-data status.
        if png_path.exists():
            png_path.unlink()
            print(f"render_og: removed stale {png_path}")
        print(
            "render_og: TODO: no SVG rasterizer installed "
            "(cairosvg not importable), so no PNG was produced. "
            "Install cairosvg (pip install cairosvg) or rsvg-convert/inkscape "
            "and re-run to get the PNG. The SVG is the source of truth."
        )


if __name__ == "__main__":
    main()
