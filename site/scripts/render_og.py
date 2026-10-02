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
        [--out site/public/og/og-leaderboard] [--top-n 8] [--suite public]
        [--division guardrail] [--peira-version 0.1.0]

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

sys.path.insert(0, str(REPO_ROOT / "python"))

from peira.divisions import DIVISION_KEYS, division_label  # noqa: E402

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


# (moved to python/peira/divisions.py: single source of truth)


def load_runs(path: Path, suite: str, division: str) -> tuple[dict, list[dict]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"cannot read {path}: {exc}")
    # The headline ranking never mixes divisions: the social image charts
    # one division only, labeled as such.
    runs = [
        r for r in data.get("runs", [])
        if r.get("suite") == suite and r.get("division") == division
    ]
    scored = []
    for r in runs:
        m = r.get("metrics") or {}
        asr = m.get("asr_conditional")
        ci = m.get("asr_ci95") or [None, None]
        if asr is None:
            continue  # no headline metric, skip rather than invent one
        bacc = m.get("benign_accuracy")
        bacc_ci = m.get("benign_accuracy_ci95") or [None, None]
        cal = (m.get("calibration") or {}).get("attacked") or {}
        ece = cal.get("ece")
        ece_ci = cal.get("ece_ci95") or [None, None]
        scored.append(
            {
                "adapter_name": str(r.get("adapter_name", "unknown")),
                "adapter_version": str(r.get("adapter_version", "")),
                "model_class": str(r.get("model_class", "")),
                "division": str(r.get("division", "")),
                "asr": float(asr),
                "ci_lo": float(ci[0]) if ci[0] is not None else None,
                "ci_hi": float(ci[1]) if ci[1] is not None else None,
                "n_eligible": m.get("n_eligible"),
                "benign_accuracy": float(bacc) if bacc is not None else None,
                "benign_accuracy_ci_lo": float(bacc_ci[0]) if bacc_ci[0] is not None else None,
                "benign_accuracy_ci_hi": float(bacc_ci[1]) if bacc_ci[1] is not None else None,
                "ece": float(ece) if ece is not None else None,
                "ece_ci_lo": float(ece_ci[0]) if ece_ci[0] is not None else None,
                "ece_ci_hi": float(ece_ci[1]) if ece_ci[1] is not None else None,
            }
        )
    scored.sort(key=lambda s: s["asr"])
    return data, scored


def esc(s: str) -> str:
    return html.escape(s, quote=True)


def render(data: dict, scored: list[dict], top_n: int, division: str,
           peira_version_override: str | None = None) -> str:
    top = scored[:top_n]
    mock = bool(data.get("mock_data"))
    # The repo carries 0.0.0 per the tag-is-version policy (docs/Release.md);
    # the tag is the source of truth and no tag exists pre-launch. A public
    # OG image showing "peira 0.0.0" reads as broken, so the caller may pass
    # an explicit display version. The site-data value is never mutated.
    peira_version = (peira_version_override
                     if peira_version_override is not None
                     else str(data.get("peira_version", "")))
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
  <text x="64" y="148" font-family="{FONT}" font-size="22" fill="{MUTED}">{esc(division_label(division))}</text>
  <text x="64" y="174" font-family="{FONT}" font-size="19" fill="{MUTED}">{esc(subtitle)}</text>
  <text x="{WIDTH - 64}" y="112" text-anchor="end" font-family="{FONT}" font-size="20" fill="{MUTED}">top {len(top)} adapters</text>
  <text x="{WIDTH - 64}" y="140" text-anchor="end" font-family="{FONT}" font-size="15" fill="{MUTED}">whiskers show 95 percent confidence intervals</text>
{chr(10).join(grid)}
{chr(10).join(rows)}
  <text x="64" y="{HEIGHT - 44}" font-family="{FONT}" font-size="15" fill="{MUTED}">peiratrial.dev</text>
  <text x="{WIDTH - 64}" y="{HEIGHT - 44}" text-anchor="end" font-family="{FONT}" font-size="15" fill="{MUTED}">{esc(footer_right)}</text>
</svg>
"""


def alt_text(data: dict, scored: list[dict], top_n: int, division: str) -> str:
    mock = bool(data.get("mock_data"))
    lines = [
        "OG social image for the peira leaderboard page.",
        "A dark card titled peira leaderboard with a horizontal bar chart "
        "of conditional attack success rate for the top adapters in the "
        f"{division_label(division)}. Lower is better.",
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


# ---------------------------------------------------------------------------
# Per-view renderers (Program B B5: every data view gets its own social
# image instead of sharing the leaderboard one). Each renderer draws only
# numbers taken straight from the site-data JSON it was given; nothing is
# invented. Mock-data builds carry the mock banner, same as the leaderboard.
# ---------------------------------------------------------------------------

def _frame(title: str, subtitle: str, top_right: list[str], body: str,
           mock: bool, aria: str, footer_right: str) -> str:
    mock_banner = ""
    if mock:
        mock_banner = (
            f'  <rect x="0" y="0" width="{WIDTH}" height="46" fill="{WARN}"/>\n'
            f'<text x="{WIDTH / 2}" y="31" text-anchor="middle" '
            f'font-family="{FONT}" font-size="22" font-weight="bold" fill="#3a2b00">'
            f'MOCK DATA, NOT REAL RESULTS</text>\n'
        )
    top_right_svg = "\n".join(
        f'  <text x="{WIDTH - 64}" y="{112 + 28 * i}" text-anchor="end" '
        f'font-family="{FONT}" font-size="{20 if i == 0 else 15}" '
        f'fill="{MUTED}">{esc(line)}</text>'
        for i, line in enumerate(top_right)
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-label="{esc(aria)}">
  <rect width="{WIDTH}" height="{HEIGHT}" fill="{BG}"/>
  <rect x="24" y="24" width="{WIDTH - 48}" height="{HEIGHT - 48}" rx="12" fill="{CARD}"/>
{mock_banner}  <text x="64" y="112" font-family="{FONT}" font-size="44" font-weight="bold" fill="{TEXT}">{esc(title)}</text>
  <text x="64" y="148" font-family="{FONT}" font-size="22" fill="{MUTED}">{esc(subtitle)}</text>
{top_right_svg}
{body}  <text x="64" y="{HEIGHT - 44}" font-family="{FONT}" font-size="15" fill="{MUTED}">peiratrial.dev</text>
  <text x="{WIDTH - 64}" y="{HEIGHT - 44}" text-anchor="end" font-family="{FONT}" font-size="15" fill="{MUTED}">{esc(footer_right)}</text>
</svg>
"""


def _footer_bits(data: dict, peira_version_override: str | None) -> tuple[str, str, bool]:
    mock = bool(data.get("mock_data"))
    peira_version = (peira_version_override
                     if peira_version_override is not None
                     else str(data.get("peira_version", "")))
    dataset_version = str((data.get("dataset") or {}).get("version", ""))
    footer_right = "generated from sealed run artifacts"
    if peira_version:
        footer_right = f"peira {peira_version} \u00b7 " + footer_right
    return footer_right, dataset_version, mock


def _bar_rows(items: list[dict], chart_x: int, chart_w: int, chart_y0: int,
              row_h: int, label_fn) -> str:
    """Shared horizontal-bar rows with 95 percent CI whiskers.

    items: dicts with asr, ci_lo, ci_hi. label_fn(item) returns
    (name, sublabel or None). Values are proportions in [0, 1].
    """
    bar_h = 18

    def x_for(v: float) -> float:
        return chart_x + max(0.0, min(1.0, v)) * chart_w

    rows = []
    for i, s in enumerate(items):
        y = chart_y0 + i * row_h
        cy = y + row_h / 2
        name, sub = label_fn(s)
        rows.append(
            f'    <text x="{chart_x - 16}" y="{cy + 5}" text-anchor="end" '
            f'font-family="{FONT}" font-size="20" fill="{TEXT}">{esc(name)}</text>'
        )
        if sub:
            rows.append(
                f'    <text x="{chart_x - 16}" y="{cy + 24}" text-anchor="end" '
                f'font-family="{FONT}" font-size="14" fill="{MUTED}">{esc(sub)}</text>'
            )
        bx = x_for(s["asr"])
        rows.append(
            f'    <rect x="{chart_x}" y="{cy - bar_h / 2}" '
            f'width="{max(bx - chart_x, 2):.1f}" height="{bar_h}" rx="4" fill="{ACCENT}"/>'
        )
        ci_hi_x = None
        if s["ci_lo"] is not None and s["ci_hi"] is not None:
            lo, hi = x_for(s["ci_lo"]), x_for(s["ci_hi"])
            ci_hi_x = hi
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
    grid = []
    for q in (0.0, 0.25, 0.5, 0.75, 1.0):
        gx = x_for(q)
        grid.append(
            f'    <line x1="{gx:.1f}" y1="{chart_y0 - 8}" '
            f'x2="{gx:.1f}" y2="{chart_y0 + len(items) * row_h}" '
            f'stroke="{GRID}" stroke-width="1"/>'
            f'<text x="{gx:.1f}" y="{chart_y0 - 16}" text-anchor="middle" '
            f'font-family="{FONT}" font-size="14" fill="{MUTED}">{pct(q)}</text>'
        )
    return "\n".join(grid) + "\n" + "\n".join(rows)


def _family_rows(data: dict, suite: str, division: str, top_n: int) -> list[dict]:
    """Top families by max per-family ASR across the division's runs.

    Every number comes from the runs' per_family blocks. Families with no
    ASR anywhere are skipped rather than invented.
    """
    best: dict[str, dict] = {}
    for r in data.get("runs", []):
        if r.get("suite") != suite or r.get("division") != division:
            continue
        for fam, fm in ((r.get("metrics") or {}).get("per_family") or {}).items():
            asr = (fm or {}).get("asr")
            if asr is None:
                continue
            cur = best.get(fam)
            if cur is None or float(asr) > cur["asr"]:
                ci = (fm or {}).get("asr_ci95") or [None, None]
                best[fam] = {
                    "asr": float(asr),
                    "ci_lo": float(ci[0]) if ci[0] is not None else None,
                    "ci_hi": float(ci[1]) if ci[1] is not None else None,
                    "family": str(fam),
                }
    ranked = sorted(best.values(), key=lambda s: s["asr"], reverse=True)
    return ranked[:top_n]


def render_families(data: dict, suite: str, division: str, top_n: int,
                    peira_version_override: str | None = None) -> str:
    items = _family_rows(data, suite, division, top_n)
    if not items:
        fail(f"no per-family ASR in the site-data JSON for suite={suite} division={division}")
    footer_right, dataset_version, mock = _footer_bits(data, peira_version_override)
    subtitle_bits = ["max conditional attack success rate per family", "lower is better"]
    if dataset_version:
        subtitle_bits.append(f"dataset {dataset_version}")
    body = _bar_rows(items, 360, 740, 210, 46,
                     lambda s: (s["family"].replace("_", " "), None))
    return _frame(
        "peira attack families",
        " \u00b7 ".join(subtitle_bits),
        [f"top {len(items)} families", division_label(division),
         "whiskers show 95 percent confidence intervals"],
        body, mock,
        "peira attack families OG image, " + ("mock data" if mock else "benchmark results"),
        footer_right,
    )


def alt_text_families(data: dict, suite: str, division: str, top_n: int) -> str:
    mock = bool(data.get("mock_data"))
    lines = [
        "OG social image for the peira attack families page.",
        "A dark card titled peira attack families with a horizontal bar chart "
        "of the highest conditional attack success rate per family in the "
        f"{division_label(division)}. Lower is better.",
        f"Data status is {'MOCK DATA, not real results' if mock else 'real benchmark results'}.",
    ]
    for i, s in enumerate(_family_rows(data, suite, division, top_n), 1):
        lines.append(f"{i}. {s['family']} at {pct(s['asr'])}.")
    return "\n".join(lines) + "\n"


def _ece_rows(scored: list[dict]) -> list[dict]:
    """Per-adapter expected calibration error, best (lowest) first.

    ECE is the calibration page's headline metric: the average gap
    between stated confidence and observed accuracy. Lower is better.
    """
    rows = []
    for s in scored:
        if s.get("ece") is None:
            continue
        rows.append({
            "asr": float(s["ece"]),
            "ci_lo": s["ece_ci_lo"],
            "ci_hi": s["ece_ci_hi"],
            "adapter_name": s["adapter_name"],
            "adapter_version": s["adapter_version"],
        })
    rows.sort(key=lambda r: r["asr"])
    return rows


def render_calibration(data: dict, scored: list[dict],
                       peira_version_override: str | None = None) -> str:
    ece = _ece_rows(scored)
    if not ece:
        fail("no calibration.attacked.ece in the site-data JSON for the selected suite/division")
    footer_right, dataset_version, mock = _footer_bits(data, peira_version_override)
    subtitle_bits = ["expected calibration error per adapter", "lower is better"]
    if dataset_version:
        subtitle_bits.append(f"dataset {dataset_version}")
    body = _bar_rows(
        ece, 360, 740, 210, 52,
        lambda s: (s["adapter_name"] + (f" {s['adapter_version']}" if s["adapter_version"] else ""), None),
    )
    return _frame(
        "peira calibration",
        " \u00b7 ".join(subtitle_bits),
        [f"{len(ece)} adapters", "whiskers show 95 percent confidence intervals"],
        body, mock,
        "peira calibration OG image, " + ("mock data" if mock else "benchmark results"),
        footer_right,
    )


def alt_text_calibration(data: dict, scored: list[dict]) -> str:
    mock = bool(data.get("mock_data"))
    lines = [
        "OG social image for the peira calibration page.",
        "A dark card titled peira calibration with a horizontal bar chart of "
        "expected calibration error per adapter, the average gap between "
        "stated confidence and observed accuracy. Lower is better.",
        f"Data status is {'MOCK DATA, not real results' if mock else 'real benchmark results'}.",
    ]
    for i, s in enumerate(_ece_rows(scored), 1):
        lines.append(f"{i}. {s['adapter_name']} at {pct(s['asr'])}.")
    return "\n".join(lines) + "\n"


def render_frontier(data: dict, scored: list[dict],
                    peira_version_override: str | None = None) -> str:
    pts = [s for s in scored
           if s.get("benign_accuracy") is not None and s.get("asr") is not None]
    if not pts:
        fail("no asr plus benign_accuracy pairs in the site-data JSON for the selected suite/division")
    footer_right, dataset_version, mock = _footer_bits(data, peira_version_override)
    x0, x1, y0, y1 = 200, 1040, 170, 520

    def x_for(v: float) -> float:
        return x0 + max(0.0, min(1.0, v)) * (x1 - x0)

    def y_for(v: float) -> float:
        return y1 - max(0.0, min(1.0, v)) * (y1 - y0)

    dots = []
    for s in pts:
        cx, cy = x_for(s["benign_accuracy"]), y_for(s["asr"])
        label = s["adapter_name"] + (f" {s['adapter_version']}" if s["adapter_version"] else "")
        dots.append(
            f'    <circle cx="{cx:.1f}" cy="{cy:.1f}" r="11" fill="{ACCENT}" '
            f'fill-opacity="0.85" stroke="{TEXT}" stroke-width="2"/>'
            f'<text x="{cx + 16:.1f}" y="{cy + 5:.1f}" '
            f'font-family="{FONT}" font-size="16" fill="{TEXT}">{esc(label)}</text>'
        )
    axes = []
    for q in (0.0, 0.25, 0.5, 0.75, 1.0):
        gx = x_for(q)
        axes.append(
            f'    <line x1="{gx:.1f}" y1="{y0}" x2="{gx:.1f}" y2="{y1}" stroke="{GRID}" stroke-width="1"/>'
            f'<text x="{gx:.1f}" y="{y1 + 26}" text-anchor="middle" '
            f'font-family="{FONT}" font-size="14" fill="{MUTED}">{pct(q)}</text>'
        )
        gy = y_for(q)
        axes.append(
            f'    <line x1="{x0}" y1="{gy:.1f}" x2="{x1}" y2="{gy:.1f}" stroke="{GRID}" stroke-width="1"/>'
            f'<text x="{x0 - 14}" y="{gy + 5:.1f}" text-anchor="end" '
            f'font-family="{FONT}" font-size="14" fill="{MUTED}">{pct(q)}</text>'
        )
    body = (
        "\n".join(axes) + "\n" + "\n".join(dots)
        + f'\n    <text x="{(x0 + x1) / 2:.1f}" y="{y1 + 52}" text-anchor="middle" '
        f'font-family="{FONT}" font-size="16" fill="{MUTED}">benign accuracy, higher is better</text>'
        f'\n    <text x="60" y="{(y0 + y1) / 2:.1f}" text-anchor="middle" '
        f'font-family="{FONT}" font-size="16" fill="{MUTED}" '
        f'transform="rotate(-90 60 {(y0 + y1) / 2:.1f})">attack success rate, lower is better</text>'
    )
    subtitle_bits = ["attack success rate versus benign accuracy", f"{len(pts)} adapters"]
    if dataset_version:
        subtitle_bits.append(f"dataset {dataset_version}")
    return _frame(
        "peira robustness frontier",
        " \u00b7 ".join(subtitle_bits),
        ["bottom right is safest"],
        body, mock,
        "peira robustness frontier OG image, " + ("mock data" if mock else "benchmark results"),
        footer_right,
    )


def alt_text_frontier(data: dict, scored: list[dict]) -> str:
    mock = bool(data.get("mock_data"))
    pts = [s for s in scored
           if s.get("benign_accuracy") is not None and s.get("asr") is not None]
    lines = [
        "OG social image for the peira robustness frontier page.",
        "A dark card titled peira robustness frontier with a scatter plot of "
        "attack success rate against benign accuracy, one dot per adapter. "
        "Bottom right is safest.",
        f"Data status is {'MOCK DATA, not real results' if mock else 'real benchmark results'}.",
    ]
    for s in pts:
        lines.append(
            f"{s['adapter_name']} at attack success rate {pct(s['asr'])} "
            f"and benign accuracy {pct(s['benign_accuracy'])}."
        )
    return "\n".join(lines) + "\n"


def render_compare(data: dict, scored: list[dict],
                   peira_version_override: str | None = None) -> str:
    top = sorted(scored, key=lambda s: s["asr"])[:2]
    if len(top) < 2:
        fail("need at least 2 adapters with asr_conditional for the compare view")
    footer_right, dataset_version, mock = _footer_bits(data, peira_version_override)
    chart_x, chart_w, y0 = 420, 680, 230
    row_h, bar_h = 120, 34

    def x_for(v: float) -> float:
        return chart_x + max(0.0, min(1.0, v)) * chart_w

    rows = []
    for i, s in enumerate(top):
        y = y0 + i * row_h
        cy = y + row_h / 2
        label = s["adapter_name"] + (f" {s['adapter_version']}" if s["adapter_version"] else "")
        rows.append(
            f'    <text x="{chart_x - 16}" y="{cy - 8}" text-anchor="end" '
            f'font-family="{FONT}" font-size="24" font-weight="bold" fill="{TEXT}">{esc(label)}</text>'
        )
        rows.append(
            f'    <text x="{chart_x - 16}" y="{cy + 18}" text-anchor="end" '
            f'font-family="{FONT}" font-size="16" fill="{MUTED}">rank {i + 1} by attack success rate</text>'
        )
        bx = x_for(s["asr"])
        rows.append(
            f'    <rect x="{chart_x}" y="{cy - bar_h / 2}" '
            f'width="{max(bx - chart_x, 2):.1f}" height="{bar_h}" rx="6" fill="{ACCENT}"/>'
        )
        rows.append(
            f'    <text x="{bx + 14:.1f}" y="{cy + 8}" '
            f'font-family="{FONT}" font-size="24" font-weight="bold" fill="{TEXT}">'
            f'{pct(s["asr"])}</text>'
        )
    grid = []
    for q in (0.0, 0.25, 0.5, 0.75, 1.0):
        gx = x_for(q)
        grid.append(
            f'    <line x1="{gx:.1f}" y1="{y0 - 8}" x2="{gx:.1f}" y2="{y0 + 2 * row_h}" '
            f'stroke="{GRID}" stroke-width="1"/>'
            f'<text x="{gx:.1f}" y="{y0 - 16}" text-anchor="middle" '
            f'font-family="{FONT}" font-size="14" fill="{MUTED}">{pct(q)}</text>'
        )
    body = "\n".join(grid) + "\n" + "\n".join(rows)
    subtitle_bits = ["head to head on conditional attack success rate", "lower is better"]
    if dataset_version:
        subtitle_bits.append(f"dataset {dataset_version}")
    return _frame(
        "peira adapter compare",
        " \u00b7 ".join(subtitle_bits),
        ["top 2 adapters"],
        body, mock,
        "peira adapter compare OG image, " + ("mock data" if mock else "benchmark results"),
        footer_right,
    )


def alt_text_compare(data: dict, scored: list[dict]) -> str:
    mock = bool(data.get("mock_data"))
    top = sorted(scored, key=lambda s: s["asr"])[:2]
    lines = [
        "OG social image for the peira adapter compare page.",
        "A dark card titled peira adapter compare with the two best adapters "
        "side by side on conditional attack success rate. Lower is better.",
        f"Data status is {'MOCK DATA, not real results' if mock else 'real benchmark results'}.",
    ]
    for i, s in enumerate(top, 1):
        lines.append(f"{i}. {s['adapter_name']} at {pct(s['asr'])}.")
    return "\n".join(lines) + "\n"


def render_cases(data: dict, scored: list[dict], suite: str, division: str,
                 peira_version_override: str | None = None) -> str:
    footer_right, dataset_version, mock = _footer_bits(data, peira_version_override)
    # Never blend suites or divisions: count only the selected slice, same
    # as every other view.
    families: set[str] = set()
    n_eligible_total = 0
    for r in data.get("runs", []):
        if r.get("suite") != suite or r.get("division") != division:
            continue
        for fam in ((r.get("metrics") or {}).get("per_family") or {}):
            families.add(str(fam))
        n = ((r.get("metrics") or {}).get("n_eligible"))
        if isinstance(n, int):
            n_eligible_total += n
    stats = [
        (f"{len(scored)}", "sealed runs charted"),
        (f"{len(families)}", "attack families"),
        (f"{n_eligible_total}", "eligible case runs"),
    ]
    if dataset_version:
        stats.append((dataset_version, "dataset version"))
    cards = []
    cw, gap = 240, 40
    x_start = (WIDTH - (len(stats) * cw + (len(stats) - 1) * gap)) / 2
    for i, (num, label) in enumerate(stats):
        x = x_start + i * (cw + gap)
        cards.append(
            f'    <rect x="{x:.1f}" y="240" width="{cw}" height="180" rx="12" fill="{BG}"/>'
            f'<text x="{x + cw / 2:.1f}" y="330" text-anchor="middle" '
            f'font-family="{FONT}" font-size="52" font-weight="bold" fill="{ACCENT}">{esc(num)}</text>'
            f'<text x="{x + cw / 2:.1f}" y="368" text-anchor="middle" '
            f'font-family="{FONT}" font-size="18" fill="{MUTED}">{esc(label)}</text>'
        )
    body = "\n".join(cards)
    return _frame(
        "peira case corpus",
        "every number below comes from sealed run artifacts",
        [],
        body, mock,
        "peira case corpus OG image, " + ("mock data" if mock else "benchmark results"),
        footer_right,
    )


def alt_text_cases(data: dict, scored: list[dict], suite: str, division: str) -> str:
    mock = bool(data.get("mock_data"))
    families: set[str] = set()
    for r in data.get("runs", []):
        if r.get("suite") != suite or r.get("division") != division:
            continue
        for fam in ((r.get("metrics") or {}).get("per_family") or {}):
            families.add(str(fam))
    return "\n".join([
        "OG social image for the peira cases page.",
        "A dark card titled peira case corpus with headline corpus statistics "
        f"of {len(scored)} sealed runs charted and {len(families)} attack families. "
        "Every number comes from sealed run artifacts.",
        f"Data status is {'MOCK DATA, not real results' if mock else 'real benchmark results'}.",
    ]) + "\n"


def render_methodology(data: dict,
                       peira_version_override: str | None = None) -> str:
    footer_right, dataset_version, mock = _footer_bits(data, peira_version_override)
    points = [
        "Paired benign and attacked cases for every decision",
        "95 percent confidence intervals on every number",
        "Public and holdout suites are never blended",
    ]
    if dataset_version:
        points.append(f"Dataset version {dataset_version}")
    bullets = []
    for i, p in enumerate(points):
        y = 260 + i * 64
        bullets.append(
            f'    <circle cx="110" cy="{y - 8}" r="8" fill="{ACCENT}"/>'
            f'<text x="140" y="{y}" font-family="{FONT}" font-size="26" fill="{TEXT}">{esc(p)}</text>'
        )
    body = "\n".join(bullets)
    return _frame(
        "peira methodology",
        "how the benchmark measures robustness",
        ["read the full contract", "on the methodology page"],
        body, mock,
        "peira methodology OG image, " + ("mock data" if mock else "benchmark results"),
        footer_right,
    )


def alt_text_methodology(data: dict) -> str:
    mock = bool(data.get("mock_data"))
    return "\n".join([
        "OG social image for the peira methodology page.",
        "A dark card titled peira methodology listing the measurement contract: "
        "paired benign and attacked cases, 95 percent confidence intervals on "
        "every number, and public and holdout suites never blended.",
        f"Data status is {'MOCK DATA, not real results' if mock else 'real benchmark results'}.",
    ]) + "\n"


VIEWS = {
    "leaderboard": "og-leaderboard",
    "families": "og-families",
    "calibration": "og-calibration",
    "frontier": "og-frontier",
    "compare": "og-compare",
    "cases": "og-cases",
    "methodology": "og-methodology",
}


def render_view(view: str, data: dict, scored: list[dict], top_n: int,
                suite: str, division: str,
                peira_version_override: str | None) -> tuple[str, str]:
    """Render (svg, alt_text) for one view. scored may be empty for views
    that aggregate the raw runs themselves."""
    if view == "leaderboard":
        return (
            render(data, scored, top_n, division, peira_version_override),
            alt_text(data, scored, top_n, division),
        )
    if view == "families":
        return (
            render_families(data, suite, division, top_n, peira_version_override),
            alt_text_families(data, suite, division, top_n),
        )
    if view == "calibration":
        return (
            render_calibration(data, scored, peira_version_override),
            alt_text_calibration(data, scored),
        )
    if view == "frontier":
        return (
            render_frontier(data, scored, peira_version_override),
            alt_text_frontier(data, scored),
        )
    if view == "compare":
        return (
            render_compare(data, scored, peira_version_override),
            alt_text_compare(data, scored),
        )
    if view == "cases":
        return (
            render_cases(data, scored, suite, division, peira_version_override),
            alt_text_cases(data, scored, suite, division),
        )
    if view == "methodology":
        return (
            render_methodology(data, peira_version_override),
            alt_text_methodology(data),
        )
    fail(f"unknown view {view!r}")


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
        default=None,
        help="output base path (no extension). Default: the og/ directory "
        "plus the view's file name (e.g. og-calibration for --view "
        "calibration), or og-leaderboard for the default view.",
    )
    ap.add_argument("--top-n", type=int, default=TOP_N_DEFAULT)
    ap.add_argument("--suite", default="public", choices=("public", "holdout"))
    ap.add_argument(
        "--division",
        default="guardrail",
        choices=tuple(sorted(DIVISION_KEYS)),
        help="which division the image charts (the headline ranking never "
        "mixes divisions)",
    )
    ap.add_argument(
        "--peira-version",
        default=None,
        help="override the peira version shown in the footer (default: the "
        "site-data value; the repo carries 0.0.0 pre-launch per "
        "docs/Release.md, which reads as broken on a public image)",
    )
    ap.add_argument(
        "--view",
        default="leaderboard",
        choices=sorted(VIEWS),
        help="which site view the image is for (default: leaderboard)",
    )
    ap.add_argument(
        "--all-views",
        action="store_true",
        help="render every view in VIEWS, ignoring --view/--out "
        "(output paths are derived from the view names)",
    )
    args = ap.parse_args()
    if not 1 <= args.top_n <= TOP_N_DEFAULT:
        fail(f"--top-n must be between 1 and {TOP_N_DEFAULT} (chart capacity)")

    data, scored = load_runs(Path(args.inp), args.suite, args.division)
    if not scored:
        fail(
            "no runs with asr_conditional in the site-data JSON "
            f"for suite={args.suite} division={args.division}"
        )

    views = sorted(VIEWS) if args.all_views else [args.view]
    og_dir = SITE_ROOT / "public" / "og"
    for view in views:
        if args.out:
            out_base = Path(args.out)
        else:
            out_base = og_dir / VIEWS[view]
        out_base.parent.mkdir(parents=True, exist_ok=True)
        svg, alt = render_view(view, data, scored, args.top_n, args.suite,
                               args.division, args.peira_version)
        _write_outputs(view, out_base, svg, alt)


def _write_outputs(view: str, out_base: Path, svg: str, alt: str) -> None:
    svg_path = out_base.with_suffix(".svg")
    svg_path.write_text(svg, encoding="utf-8")
    print(f"render_og: wrote {svg_path} (view={view})")

    alt_path = out_base.with_suffix(".alt.txt")
    alt_path.write_text(alt, encoding="utf-8")
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
