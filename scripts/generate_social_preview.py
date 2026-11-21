#!/usr/bin/env python3
"""Generate the repo social-preview SVG (1280x640).

Uses the same Peira signature as the repository README and the same
palette as the board's share cards.

    python3 scripts/generate_social_preview.py            # writes assets/social-preview.svg
    python3 scripts/generate_social_preview.py --out /tmp/x.svg

Stdlib only.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

W, H = 1280, 640
ROOT = Path(__file__).resolve().parents[1]


def build() -> str:
    signature = (ROOT / ".github/board/peira-dark.svg").read_text(encoding="utf-8").strip()
    vendor_data = (ROOT / "site/board/lib/vendor-data.json").read_text(encoding="utf-8")
    palette = json.loads(vendor_data)["design"]
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="peira-title peira-description">
  <title id="peira-title">Peira</title>
  <desc id="peira-description">An open-source benchmark for decision robustness. peiratrial.dev</desc>
  <defs>
    <linearGradient id="navy" x2="100%" y2="100%">
      <stop offset="0" stop-color="{palette["ground"]}"/>
      <stop offset="1" stop-color="{palette["panel"]}"/>
    </linearGradient>
  </defs>
  <rect width="{W}" height="{H}" fill="url(#navy)"/>
  <rect width="{W}" height="6" fill="{palette["subjectFill"]}"/>
  <g transform="translate(96 106) scale(2.4)" aria-hidden="true">
    {signature}
  </g>
  <text x="103" y="320" font-family="Arial, sans-serif" font-weight="700" font-size="60" fill="{palette["ink"]}">
    <tspan x="103">An open-source benchmark</tspan>
    <tspan x="103" dy="71">for decision robustness.</tspan>
  </text>
  <path d="M103 461H1177" fill="none" stroke="{palette["rule"]}" stroke-width="2"/>
  <text x="103" y="530" font-family="Arial, sans-serif" font-size="29" fill="{palette["quiet"]}">peiratrial.dev</text>
</svg>
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="assets/social-preview.svg")
    args = ap.parse_args()
    Path(args.out).write_text(build(), encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
