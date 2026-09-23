#!/usr/bin/env python3
"""Generate the repo social-preview SVG (1280x640).

Text wordmark only — peira has no locked logo yet (real logo design is a
separate future decision). Regenerable on demand; nothing here is
hand-drawn.

    python3 scripts/generate_social_preview.py            # writes assets/social-preview.svg
    python3 scripts/generate_social_preview.py --out /tmp/x.svg

GitHub wants a 1280x640 PNG for the social preview. Export with any SVG
rasterizer, e.g.:

    rsvg-convert -w 1280 -h 640 assets/social-preview.svg -o assets/social-preview.png

then upload the PNG once in repo Settings > General > Social preview.
Do not commit the PNG (it regenerates in seconds).

Stdlib only.
"""

from __future__ import annotations

import argparse
import html

W, H = 1280, 640

# Palette: light marble background, pine ink. Ochre reserved for accents
# and never used on a (future) mark.
MARBLE_1 = "#f5f1e8"
MARBLE_2 = "#ece5d3"
PINE = "#1e3a2b"
PINE_SOFT = "#3c5a47"
OCHRE = "#c58a2d"
LINE = "#d8cfb8"


def esc(s: str) -> str:
    return html.escape(s)


def build() -> str:
    rows = []
    # faint results-table motif: 5 bars at increasing widths
    widths = (180, 260, 330, 430, 520)
    y0 = 420
    for i, w in enumerate(widths):
        y = y0 + i * 34
        rows.append(
            f'<rect x="840" y="{y}" width="{w}" height="16" rx="8" '
            f'fill="{OCHRE}" opacity="0.28"/>'
        )
    bars = "\n    ".join(rows)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
  <defs>
    <linearGradient id="marble" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{MARBLE_1}"/>
      <stop offset="1" stop-color="{MARBLE_2}"/>
    </linearGradient>
  </defs>
  <rect width="{W}" height="{H}" fill="url(#marble)"/>
  <rect x="60" y="60" width="{W - 120}" height="{H - 120}" fill="none" stroke="{LINE}" stroke-width="2"/>
  <text x="120" y="300" font-family="Georgia, 'Times New Roman', serif" font-size="150" fill="{PINE}">peira</text>
  <text x="124" y="380" font-family="Georgia, 'Times New Roman', serif" font-size="40" font-style="italic" fill="{PINE_SOFT}">{esc("the empirical trial for decision models")}</text>
  <rect x="124" y="420" width="72" height="6" fill="{OCHRE}"/>
    {bars}
  <text x="120" y="{H - 96}" font-family="Verdana, sans-serif" font-size="22" fill="{PINE_SOFT}">{esc("adversarial-robustness benchmark for LLM guardrails · MIT / CC-BY-4.0")}</text>
</svg>
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="assets/social-preview.svg")
    args = ap.parse_args()
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(build() + "\n")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
