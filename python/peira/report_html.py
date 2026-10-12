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


def _fmt_latency(v: Any) -> str:
    """Human-scale latency: whole milliseconds, or seconds past 1 s.

    A p50 of 1309.9805 ms reads as "1.31 s". Four decimal places on
    milliseconds is noise, never signal.
    """
    n = _num(v)
    if n is None:
        return "n/a"
    if n >= 1000:
        return f"{n / 1000:.2f} s"
    return f"{n:.0f} ms"


def _name(r: dict[str, Any]) -> str:
    """Display name for a leaderboard row.

    The data layer sets ``display_name`` to the model ID on every row
    it emits; fall back to the raw adapter name for payloads that do
    not carry one.
    """
    name = r.get("display_name") or r.get("adapter_name", "?")
    return _esc(str(name)[:40])


def _version(r: dict[str, Any]) -> str:
    """Display version for a leaderboard row.

    Strips a vendor prefix (``upstage/solar-pro4`` renders as
    ``solar-pro4``) so version strings read consistently across rows.
    The full model ID, prefix included, is in the Model column.
    """
    raw = str(r.get("adapter_version", ""))
    if "/" in raw:
        raw = raw.rsplit("/", 1)[-1]
    return _esc(raw)


# Machine-generated unranked reasons, mapped to human sentences.
# Anything unmapped falls through to _humanize_reason's generic
# cleanup (strip the machine prefix, underscores to spaces).
_KNOWN_REASONS = {
    "ranking-ineligible: malformed_rate above 5%":
        "Malformed response rate above 5%",
}


def _humanize_reason(reason: Any) -> str:
    """Turn a machine unranked-reason string into a human sentence."""
    text = str(reason) if reason else ""
    if text in _KNOWN_REASONS:
        return _KNOWN_REASONS[text]
    transformed = False
    if text.startswith("ranking-ineligible:"):
        text = text[len("ranking-ineligible:"):].strip()
        transformed = True
    if "_" in text:
        text = text.replace("_", " ")
        transformed = True
    text = text.strip()
    if transformed and text:
        text = text[0].upper() + text[1:]
    return text or "No reason recorded"


def _nice_ceiling(v: float) -> float:
    """Round ``v`` up to a clean axis max (1/2/2.5/5 x 10^k).

    A bar chart whose axis ends at 0.19 has an ugly final tick.
    Snapping the max to a round number gives clean ticks for free.
    """
    if not math.isfinite(v) or v <= 0:
        return 0.05
    exp = math.floor(math.log10(v))
    base = v / (10 ** exp)
    for step in (1.0, 2.0, 2.5, 5.0, 10.0):
        if base <= step:
            return step * (10 ** exp)
    return 10.0 * (10 ** exp)


def _asr_chart_svg(rows: list[dict[str, Any]]) -> str:
    """Horizontal bars of ASR per model with Wilson CI whiskers.

    Rows the caller annotated with ``_ranked`` False draw in grey:
    the model is on the chart with its number, and the color says it
    carries no rank. Unannotated rows draw in the standard green.
    """
    # The chart caps at 25 rows to keep the SVG readable; every row
    # still appears in the table below, chart or not.
    shown = [r for r in rows if _num(r.get("asr_conditional")) is not None][:25]
    if not shown:
        return '<p class="muted">No ranked models with ASR data.</p>'
    W, bar_h, gap, pad_l, pad_r = 640, 18, 10, 200, 60
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
    top = _nice_ceiling(top * 1.02)

    def x(v: float) -> float:
        return pad_l + (v / top) * plot_w

    parts = [f'<svg class="chart" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
             f'role="img" aria-label="ASR by model with 95 percent confidence intervals">']
    # x-axis ticks at 0, 25, 50, 75, 100 percent of the scale
    for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
        tx = x(top * frac)
        label = f"{top * frac:.2f}".rstrip("0").rstrip(".")
        parts.append(
            f'<line x1="{tx:.1f}" y1="10" x2="{tx:.1f}" y2="{H - 24}" '
            f'stroke="#ddd"/>'
            f'<text x="{tx:.1f}" y="{H - 8}" font-size="10" '
            f'text-anchor="middle" fill="#666">{label}</text>')
    for i, r in enumerate(shown):
        y = 14 + i * (bar_h + gap)
        name = _name(r)
        asr = _num(r.get("asr_conditional"))
        ci = r.get("asr_ci95")
        lo = hi = None
        if isinstance(ci, (list, tuple)) and len(ci) == 2:
            lo, hi = _num(ci[0]), _num(ci[1])
        fill = "#2f6f4f" if r.get("_ranked", True) else "#9aa0a6"
        parts.append(
            f'<text x="{pad_l - 8}" y="{y + bar_h - 4}" font-size="11" '
            f'text-anchor="end" fill="#222">{name}</text>'
            f'<rect x="{x(0):.1f}" y="{y}" width="{x(asr) - x(0):.1f}" '
            f'height="{bar_h}" fill="{fill}"/>')
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


_RANK_BADGES = (
    '<span class="rank rank-1">1</span>',
    '<span class="rank rank-2">2</span>',
    '<span class="rank rank-3">3</span>',
)


def _rank_cell(i: int) -> str:
    if 1 <= i <= 3:
        return _RANK_BADGES[i - 1]
    return str(i)


def _main_table(entries: list[dict[str, Any]]) -> str:
    """One table for every model on the page, in ASR order.

    Each entry is ``{"row": row, "rank": int | None}``. A ranked row
    shows its rank number; a row without a rank shows the Not ranked
    marker in the rank cell and the disqualification reason under
    the model name, so the row itself says why it carries no rank.
    Every row prints the full stat set, malformed rate included.
    """
    body = []
    for pos, entry in enumerate(entries, 1):
        r = entry["row"]
        zebra = ' class="alt"' if pos % 2 == 0 else ""
        if entry["rank"] is not None:
            rank_html = _rank_cell(entry["rank"])
            name_html = _name(r)
        else:
            rank_html = '<span class="nr">Not ranked</span>'
            reason = _esc(_humanize_reason(r.get("reason")))
            name_html = f"{_name(r)}<br><span class=\"muted\">{reason}</span>"
        body.append(
            f"<tr{zebra}>"
            f"<td>{rank_html}</td>"
            f"<td>{name_html}</td>"
            f"<td>{_version(r)}</td>"
            f"<td>{_fmt(r.get('asr_conditional'))}</td>"
            f"<td>{_fmt_ci(r.get('asr_ci95'))}</td>"
            f"<td>{_fmt(r.get('benign_accuracy'))}</td>"
            f"<td>{_esc(r.get('n_eligible', 'n/a'))}</td>"
            f"<td>{_fmt(r.get('total_cost_usd'))}</td>"
            f"<td>{_fmt_latency(r.get('latency_ms_p50_attacked'))}</td>"
            f"<td>{_fmt(r.get('ece_attacked'))}</td>"
            f"<td>{_fmt(r.get('malformed_rate'))}</td>"
            "</tr>"
        )
    return (
        '<div class="table-wrap"><table class="board"><thead><tr><th>Rank</th><th>Model</th><th>Version</th>'
        "<th>ASR</th><th>ASR 95% CI</th><th>Benign accuracy</th>"
        "<th>Eligible n</th><th>Cost USD</th><th>Latency p50</th>"
        "<th>ECE</th><th>Malformed rate</th></tr></thead><tbody>\n"
        + "\n".join(body)
        + "\n</tbody></table></div>"
    )


_NOT_RANKED_NOTE = (
    "<p>Models marked Not ranked ran the full benchmark but did not "
    "qualify for a rank under the published admission rules, and the "
    "reason is printed with each name. One of those rules caps the "
    "malformed response rate at 5 percent, because a score built only "
    "on the cases a model managed to answer can flatter it. Every "
    "number is shown either way.</p>"
)


_BANNER_OFFICIAL = (
    '<div class="banner official">Official results. Produced from a '
    "frozen dataset tag under the published methodology. The methodology "
    "is pre-registered and awaiting independent replication. Treat these "
    "as the current best measurement, not as settled fact.</div>"
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
    "the Analytics Methodology document, the canonical home for what "
    "each number means and what it must not be read as.</li>"
    "<li>This file is self-contained: no JavaScript, no external "
    "resources, charts as inline SVG. Save it, cite it, screenshot it. "
    "It will still render.</li>"
    "</ul>"
)

_CSS = (
    "body{font-family:system-ui,-apple-system,sans-serif;max-width:960px;"
    "margin:2rem auto;padding:0 1rem;color:#1a1a1a;line-height:1.5}"
    ".brand{display:flex;align-items:center;gap:10px;margin-bottom:4px}"
    ".brand svg{flex:none}"
    ".brand .wordmark{font-size:22px;font-weight:700;letter-spacing:.5px}"
    ".brand .wordmark .leaf{color:#2f6f4f}"
    "h1{font-size:28px;margin:.4rem 0 .2rem}"
    "h2{font-size:19px;margin-top:2rem}"
    ".chart-wrap{max-width:100%;overflow-x:auto}"
    "svg.chart{display:block;width:100%;height:auto;max-width:640px}"
    ".table-wrap{max-width:100%;overflow-x:auto}"
    "table{border-collapse:collapse;width:100%;margin:1rem 0;font-size:13px}"
    "table.board th,table.board td{padding:6px 6px}"
    "th,td{border:1px solid #ccc;padding:6px 8px;text-align:left}"
    "th{background:#f4f4f4;white-space:nowrap}"
    "tr.alt td{background:#fafafa}"
    ".banner{padding:12px 16px;border-radius:6px;"
    "font-weight:600;margin:1rem 0}"
    ".banner.mock{background:#fde8e8;border:2px solid #c0392b;color:#7a1f14}"
    ".banner.official{background:#e8f5e9;border:2px solid #2f6f4f;color:#1d4a33}"
    ".rank{display:inline-block;min-width:22px;height:22px;line-height:22px;"
    "border-radius:11px;text-align:center;font-weight:700;font-size:12px;color:#fff}"
    ".rank-1{background:#b8860b}.rank-2{background:#8a8d93}.rank-3{background:#a06a35}"
    ".nr{color:#666;font-weight:700;white-space:nowrap}"
    ".muted{color:#666}code{background:#f4f4f4;padding:2px 4px}"
    ".provenance{background:#f8f9fa;border:1px solid #dee2e6;border-radius:6px;"
    "padding:12px 16px;margin:1rem 0}"
    ".provenance h2{margin:0 0 8px 0;font-size:16px}"
    ".provenance dl{display:grid;grid-template-columns:auto 1fr;gap:4px 16px;margin:0}"
    ".provenance dt{font-weight:600;color:#495057}"
    ".provenance dd{margin:0}"
    "@media (max-width:640px){"
    "body{margin:1rem auto}"
    "h1{font-size:23px}"
    "table{font-size:11px}"
    "th,td{padding:4px 6px}"
    "}"
    ".run-detail{border:1px solid #dee2e6;border-radius:6px;padding:12px 16px;"
    "margin:1.5rem 0;background:#fff}"
    ".run-detail h3{margin:0 0 8px 0;font-size:18px;border-bottom:2px solid #dee2e6;"
    "padding-bottom:6px}"
    ".run-detail h4{margin:12px 0 6px 0;font-size:14px;color:#495057}"
    ".run-detail dl{display:grid;grid-template-columns:auto 1fr;gap:4px 16px}"
    ".run-detail dt{font-weight:600}.run-detail dd{margin:0}"
)

_BRAND = (
    '<div class="brand" role="img" aria-label="peira">'
    '<svg width="30" height="30" viewBox="0 0 32 32" aria-hidden="true">'
    '<rect x="2" y="2" width="28" height="28" rx="6" fill="#2f6f4f"/>'
    '<path d="M9 22 L16 9 L23 22" stroke="#fff" stroke-width="3" '
    'fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
    '<circle cx="16" cy="22" r="2.2" fill="#fff"/>'
    "</svg>"
    '<span class="wordmark">peira<span class="leaf">.</span></span></div>'
)


# Runs whose adapter configuration changed partway through the run.
# Keyed by adapter_version, the model identity the page displays. The
# case counts are provenance facts about these specific sealed runs,
# recorded in the trial log when each adapter fix landed. The page
# discloses the split rather than presenting either run as a single
# configuration.
_MIXED_CONFIG_RUNS = {
    "gemini-3.8-flash": ("Google", 1610),
    "kimi-k3": ("Moonshot", 3274),
}


def _run_notes_block(ranked: list[dict[str, Any]],
                     unranked: list[dict[str, Any]]) -> str:
    """Disclose runs that changed configuration partway through.

    Two of the v2 trial runs began with the model thinking mode on and
    finished with it off, because an adapter fix landed while each run
    was under way. The note names each affected run and how many of
    its cases ran in the first configuration. It renders only when an
    affected run is on the page.
    """
    present = {r.get("adapter_version") for r in ranked + unranked}
    matched = [
        (version, vendor, n_first)
        for version, (vendor, n_first) in _MIXED_CONFIG_RUNS.items()
        if version in present
    ]
    if not matched:
        return ""
    parts = ['<div class="run-notes"><h2>Run notes</h2>']
    for version, vendor, n_first in matched:
        parts.append(
            f"<p>In the {_esc(vendor)} run ({_esc(version)}), the first "
            f"{n_first:,} cases ran with the model thinking mode on and "
            "the remaining cases ran with it off. A fix to the adapter "
            "software landed partway through the run and turned "
            "thinking off. Every case was run once and scored the same "
            "way in both parts, and the complete record of the run is "
            "sealed in its artifact.</p>"
        )
    parts.append("</div>")
    return "".join(parts)


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
    # One display order for the whole page: every model by ASR, with
    # unusable ASRs last. Rank numbers count only the ranked rows in
    # order, so a model without a rank slotting between two ranked
    # ones never renumbers them.
    combined = [(r, True) for r in ranked] + [(r, False) for r in unranked]
    combined.sort(key=_display_sort_key)
    entries: list[dict[str, Any]] = []
    chart_rows: list[dict[str, Any]] = []
    rank_no = 0
    for r, is_ranked in combined:
        if is_ranked:
            rank_no += 1
            entries.append({"row": r, "rank": rank_no})
        else:
            entries.append({"row": r, "rank": None})
        chart_rows.append(dict(r, _ranked=is_ranked))
    chart_caption = (
        '<p class="muted">Grey bars are models shown without a rank.</p>'
        if unranked else ""
    )
    note_html = _NOT_RANKED_NOTE if unranked else ""
    # P1.2: provenance block. The payload carries suite, dataset_version,
    # and each ranked row carries n_cases and created_utc. Render them so
    # a reader can see what dataset, how many cases, and when the runs
    # happened without opening the JSON.
    provenance_html = _provenance_block(payload, ranked, unranked)
    notes_html = _run_notes_block(ranked, unranked)
    return (
        "<!DOCTYPE html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{_esc(title)}</title>"
        f"<style>{_CSS}</style></head><body>"
        f"{_BRAND}"
        f"<h1>{_esc(title)}</h1>"
        f'<p class="muted">Generated {_esc(stamp)}. '
        f"{len(ranked) + len(unranked)} models, {len(ranked)} ranked, "
        f"{len(unranked)} not ranked.</p>"
        f"{banner}"
        f"{provenance_html}"
        f"{notes_html}"
        "<h2>Attack success rate by model</h2>"
        '<div class="chart-wrap">'
        f"{_asr_chart_svg(chart_rows)}"
        f"{chart_caption}"
        "</div>"
        "<h2>Rankings</h2>"
        f"{_main_table(entries)}"
        f"{note_html}"
        f"{_run_details([e['row'] for e in entries])}"
        f"{_FOOTER}"
        "</body></html>\n"
    )


def _display_sort_key(item: tuple[dict[str, Any], bool]) -> tuple[bool, float]:
    """ASR ascending for the combined table; unusable ASRs last.

    Mirrors the data layer's ranked sort, so the merged display
    order never disagrees with the payload's own ranking order.
    """
    v = _num(item[0].get("asr_conditional"))
    if v is None:
        return (True, 0.0)
    return (False, v)


def _run_details(rows: list[dict[str, Any]]) -> str:
    """P1.3: per-run detail sections with family breakdown and calibration.

    Each row carries a ``detail`` dict from the sealed artifact,
    ranked and not ranked alike; this view renders its family
    breakdown and its calibration. Rendered as static sections
    (no JavaScript per the HTML contract) below the main table.
    """
    if not rows:
        return ""
    parts = ['<h2>Per-run detail</h2>']
    for r in rows:
        detail = r.get("detail") or {}
        parts.append(f'<div class="run-detail"><h3>{_name(r)}</h3>')
        parts.append(_families_table(detail.get("families") or []))
        parts.append(_calibration_block(detail.get("calibration") or {}))
        parts.append('</div>')
    return "\n".join(parts)


def _families_table(families: Any) -> str:
    """Render per-family ASR breakdown table.

    The data layer emits families as a mapping keyed by family name
    (each value carries its own ``family`` field); accept that shape
    as well as a plain list. The case count rides under ``n`` in the
    metrics layer and ``n_cases`` in older payloads, so read both.
    """
    if isinstance(families, dict):
        families = list(families.values())
    if not isinstance(families, list) or not families:
        return '<p class="muted">No family breakdown available.</p>'
    rows = []
    for f in families:
        if not isinstance(f, dict):
            continue
        fam = _esc(f.get("family", "n/a"))
        asr = _fmt(f.get("asr"))
        ci = _fmt_ci(f.get("asr_ci95"))
        n = f.get("n_cases", f.get("n", "n/a"))
        rows.append(
            f"<tr><td>{fam}</td><td>{asr}</td><td>{ci}</td><td>{_esc(n)}</td></tr>"
        )
    return (
        "<h4>Family breakdown</h4>"
        '<table><thead><tr><th>Family</th><th>ASR</th>'
        "<th>95% CI</th><th>Cases</th></tr></thead>"
        "<tbody>" + "".join(rows) + "</tbody></table>"
    )


def _calibration_block(calibration: dict[str, Any]) -> str:
    """Render calibration summary (ECE per arm)."""
    if not calibration:
        return ""
    parts = ["<h4>Calibration</h4><dl>"]
    for arm in ("benign", "attacked"):
        arm_cal = calibration.get(arm) or {}
        ece = _fmt(arm_cal.get("ece"))
        parts.append(f"<dt>{_esc(arm)} ECE</dt><dd>{ece}</dd>")
    parts.append("</dl>")
    return "".join(parts)


def _provenance_block(payload: dict[str, Any],
                      ranked: list[dict[str, Any]],
                      unranked: list[dict[str, Any]] | None = None) -> str:
    """Render dataset provenance: suite, dataset version, case count, dates."""
    # The payload-level suite and dataset version echo the caller's
    # filters and are empty on an unfiltered build. Fall back to the
    # rows themselves, which carry both fields from their artifacts.
    all_rows = list(ranked) + list(unranked or [])
    suite = payload.get("suite")
    if not suite:
        suite = next(
            (r.get("suite") for r in all_rows if r.get("suite")), None)
    suite = suite or "n/a"
    dataset_version = payload.get("dataset_version")
    if not dataset_version:
        dataset_version = next(
            (r.get("dataset_version") for r in all_rows
             if r.get("dataset_version")), None)
    dataset_version = dataset_version or "n/a"
    # n_cases should be uniform across ranked rows; take the max as the
    # representative count and note if rows disagree.
    n_cases_vals = [r.get("n_cases") for r in ranked
                    if isinstance(r.get("n_cases"), int)]
    if n_cases_vals:
        n_cases = max(n_cases_vals)
        cases_note = ("" if len(set(n_cases_vals)) == 1
                      else " (varies by run)")
    else:
        n_cases, cases_note = "n/a", ""
    # Run dates: min/max created_utc across every row on the page,
    # ranked and not ranked alike. A range drawn only from ranked
    # rows understates when the run finished.
    dates = sorted(r.get("created_utc", "") for r in all_rows if r.get("created_utc"))
    if dates:
        date_range = _esc(dates[0][:10])
        if dates[-1][:10] != dates[0][:10]:
            date_range += " to " + _esc(dates[-1][:10])
    else:
        date_range = "n/a"
    return (
        '<div class="provenance">'
        "<h2>Provenance</h2>"
        "<dl>"
        f"<dt>Suite</dt><dd>{_esc(suite)}</dd>"
        f"<dt>Dataset</dt><dd>{_esc(dataset_version)}</dd>"
        f"<dt>Cases per run</dt><dd>{_esc(n_cases)}{cases_note}</dd>"
        f"<dt>Run dates</dt><dd>{date_range}</dd>"
        "</dl></div>"
    )
