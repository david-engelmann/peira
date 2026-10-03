"""Pilot report HTML: self-contained analysis report for the v2 pilot run.

Renders the full ``pilot_analysis.analyze_pilot`` report as a single
HTML file with inline SVG charts. Follows the ``report_html`` contract:
no <script>, no external resources, everything server-side rendered.

Usage:
    python -m peira.pilot_report --runs-dir runs --output pilot-report.html
"""

from __future__ import annotations

import argparse
import html
import sys
from pathlib import Path
from typing import Any


def _esc(x: Any) -> str:
    return html.escape(str(x), quote=True)


_CSS = """
body { font-family: system-ui, -apple-system, sans-serif; max-width: 1100px;
       margin: 0 auto; padding: 24px; color: #1a1a1a; line-height: 1.5; }
h1 { font-size: 28px; border-bottom: 2px solid #2f6f4f; padding-bottom: 8px; }
h2 { font-size: 20px; margin-top: 36px; color: #2f6f4f; }
table { border-collapse: collapse; width: 100%; margin: 16px 0; font-size: 13px; }
th, td { border: 1px solid #ddd; padding: 6px 10px; text-align: left; }
th { background: #f5f5f5; font-weight: 600; }
.muted { color: #666; font-style: italic; }
.banner { background: #fff3cd; border: 1px solid #ffc107; padding: 12px;
          border-radius: 4px; margin: 16px 0; }
.sig { color: #b71c1c; font-weight: 600; }
.nonsig { color: #666; }
"""


def _models_table(report: dict[str, Any]) -> str:
    rows = []
    for m in report.get("models", []):
        rows.append(
            f"<tr><td>{_esc(m.get('adapter_name', '?'))}</td>"
            f"<td>{_esc(m.get('adapter_version', ''))}</td>"
            f"<td><code>{_esc(m.get('run_id', ''))}</code></td></tr>"
        )
    return (
        "<table><thead><tr><th>Adapter</th><th>Version</th><th>Run ID</th>"
        "</tr></thead><tbody>\n" + "\n".join(rows) + "\n</tbody></table>"
    )


def _pairwise_table(pairwise: dict[str, Any]) -> str:
    rows = []
    for p in pairwise.get("pairs", []):
        sig = p.get("significant_at_05")
        cls = "sig" if sig else "nonsig"
        sig_txt = "yes" if sig else ("no" if sig is not None else "n/a")
        pv = p.get("p_value")
        pv_adj = p.get("p_value_adjusted")
        rows.append(
            f"<tr><td>{_esc(p.get('adapter_a', '?'))}</td>"
            f"<td>{_esc(p.get('adapter_b', '?'))}</td>"
            f"<td>{_esc(p.get('n_paired', 'n/a'))}</td>"
            f"<td>{pv:.4f}</td>" if isinstance(pv, float) else "<td>n/a</td>"
            f"<td>{pv_adj:.4f}</td>" if isinstance(pv_adj, float) else "<td>n/a</td>"
            f'<td class="{cls}">{sig_txt}</td></tr>'
        )
    return (
        "<table><thead><tr><th>Adapter A</th><th>Adapter B</th>"
        "<th>Paired n</th><th>McNemar p</th><th>BH-adjusted p</th>"
        "<th>Significant at 0.05</th></tr></thead><tbody>\n"
        + "\n".join(rows) + "\n</tbody></table>"
    )


def _cost_table(cost: dict[str, Any]) -> str:
    rows = []
    for r in cost.get("rows", []):
        def _f(v: Any) -> str:
            return f"{v:.4f}" if isinstance(v, (int, float)) else "n/a"
        rows.append(
            f"<tr><td>{_esc(r.get('adapter_name', '?'))}</td>"
            f"<td>{_f(r.get('total_cost_usd'))}</td>"
            f"<td>{_f(r.get('cost_per_decision'))}</td>"
            f"<td>{_f(r.get('cost_per_correct'))}</td>"
            f"<td>{_f(r.get('mean_asr'))}</td></tr>"
        )
    return (
        "<table><thead><tr><th>Adapter</th><th>Total USD</th>"
        "<th>USD/decision</th><th>USD/correct</th><th>Mean ASR</th>"
        "</tr></thead><tbody>\n" + "\n".join(rows) + "\n</tbody></table>"
    )


def render_pilot_report(report: dict[str, Any]) -> str:
    """Render the full pilot analysis report as self-contained HTML."""
    from peira.pilot_charts import (
        family_heatmap_svg,
        cost_scatter_svg,
        attack_bars_svg,
        rank_chart_svg,
    )

    n = report.get("n_models", 0)
    parts = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<title>Peira v2 Pilot Analysis</title>"
        f"<style>{_CSS}</style></head><body>",
        "<h1>Peira v2 Pilot Analysis</h1>",
        f"<p>{n} models evaluated on the sealed v2 dataset. "
        "All numbers computed from sealed run artifacts; "
        "confidence intervals are Wilson 95%.</p>",
        '<div class="banner">Pilot results. Official measurements pending '
        "the full evaluation run.</div>",
        "<h2>Models</h2>",
        _models_table(report),
        "<h2>Per-Model x Per-Family ASR</h2>",
        "<p>Attack success rate by model and family. Green is robust "
        "(low ASR), red is vulnerable (high ASR).</p>",
        family_heatmap_svg(report.get("family_matrix", {})),
        "<h2>Most Effective Attacks</h2>",
        "<p>Families ranked by mean ASR across all models.</p>",
        attack_bars_svg(report.get("attack_effectiveness", {})),
        "<h2>Model Ranking</h2>",
    ]
    ranking = report.get("ranking", {})
    if "error" in ranking:
        parts.append(f'<p class="muted">{_esc(ranking["error"])}</p>')
    else:
        fp = ranking.get("friedman_p_value")
        fp_txt = f"{fp:.4f}" if isinstance(fp, float) else "n/a"
        parts.append(
            f"<p>Friedman test p-value: <strong>{fp_txt}</strong>. "
            "Mean ranks across families (lower is better); whiskers show "
            "the Nemenyi critical difference.</p>"
        )
        parts.append(rank_chart_svg(ranking))
    parts.append("<h2>Pairwise Significance</h2>")
    parts.append(
        "<p>McNemar tests on paired per-case outcomes, "
        "Benjamini-Hochberg FDR correction across all pairs.</p>"
    )
    parts.append(_pairwise_table(report.get("pairwise_significance", {})))
    parts.append("<h2>Cost Effectiveness</h2>")
    parts.append(cost_scatter_svg(report.get("cost_effectiveness", {})))
    parts.append(_cost_table(report.get("cost_effectiveness", {})))
    parts.append("</body></html>")
    return "\n".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate the v2 pilot HTML report.")
    ap.add_argument("--runs-dir", default="runs")
    ap.add_argument("--output", default="pilot-report.html")
    args = ap.parse_args()

    from peira.pilot_analysis import analyze_pilot

    report = analyze_pilot(args.runs_dir)
    html_out = render_pilot_report(report)
    Path(args.output).write_text(html_out, encoding="utf-8")
    print(f"Wrote {args.output} ({report.get('n_models', 0)} models)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
