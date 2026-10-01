"""R-11 per-run calibration artifact: reliability diagrams and risk-coverage curves.

Display layer only. The numbers (ECE, Brier, Murphy decomposition,
selective risk, per-bin reliability data) are computed in
:mod:`peira.metrics` and sealed into the run artifact; this module turns
the already-recorded per-bin data into inline SVG diagrams for the HTML
report. No new data capture, no statistics here, just rendering.

Every user-visible label says "self-reported confidence", never bare
"confidence": the adapter-emitted number is uncalibrated until measured
against outcomes, and the diagram is the measurement.
"""

import html

# M-2: confidence-elicitation metadata per adapter. The canonical source
# of truth is the ``confidence_source`` class attribute on the adapter
# classes (see ``peira.adapters.base.BaseAdapter``); this static mapping
# mirrors it for the report, which only sees the adapter name string.
# A test pins the two together, so drift fails loudly.
_ADAPTER_CONFIDENCE_SOURCES = {
    # Guardrails: |2p - 1| boundary distance (D-23).
    "shieldstral": "guardrail-score",
    "protectai-prompt-injection": "guardrail-score",
    "llama-prompt-guard-2": "guardrail-score",
    "qwen3guard-gen": "guardrail-score",
    "granite-guardian": "guardrail-score",
    "shieldgemma": "guardrail-score",
    "wildguard": "guardrail-score",
    "lakera": "guardrail-score",
    "harmbench": "guardrail-score",
    "granite-guardian-hap": "guardrail-score",
    "openai-moderation": "guardrail-score",
    "model-armor": "guardrail-score",
    "azure-prompt-shields": "guardrail-score",
    "cloudflare-workers-ai": "guardrail-score",
    # Structured LLM baselines: verbalized confidence (D-23).
    "openai-structured": "verbalized",
    "moonshot-structured": "verbalized",
    "openrouter-structured": "verbalized",
    "anthropic-structured": "verbalized",
    "google-structured": "verbalized",
    # API per-answer / choice probabilities (D-23).
    "jev": "token-logprob",
    "local-systemone": "token-logprob",
    "kev": "token-logprob",
    "openjev-sglang": "token-logprob",
    "laya": "token-logprob",
    "semif": "token-logprob",
    # Test harness: synthetic confidences.
    "mock": "none",
}

_CONFIDENCE_SOURCE_LABELS = {
    "verbalized": (
        "verbalized: the model states its confidence in words or JSON. "
        "Uncalibrated until measured; peira reports it, it does not vouch "
        "for it."
    ),
    "token-logprob": (
        "model-output probability: token logprobs or the API's per-answer "
        "probabilities. A stated probability, not a verbalization, but "
        "still uncalibrated until measured against outcomes."
    ),
    "guardrail-score": (
        "guardrail score: distance from the detector's decision boundary "
        "(|2p - 1|), not a probability of being correct. Do not read it "
        "as calibration."
    ),
    "none": (
        "no real confidence signal (e.g. synthetic test-harness values). "
        "Calibration numbers on this adapter are meaningless."
    ),
}


def confidence_source_label(adapter_name: str) -> str:
    """Human-readable confidence-elicitation label for a report.

    Returns the honest description of what the named adapter's
    ``confidence`` numbers are (M-2). Unknown names degrade to a plain
    "unreported" note, never a traceback.
    """
    try:
        source = _ADAPTER_CONFIDENCE_SOURCES.get(str(adapter_name))
    except Exception:
        source = None
    if source is None:
        return (
            "unreported: this adapter does not declare how its confidence "
            "numbers are elicited; treat them as uncalibrated."
        )
    return _CONFIDENCE_SOURCE_LABELS[source]

# Canvas geometry shared by both diagrams. Fixed viewBox so the SVG
# scales with the report layout; all coordinates are deterministic
# (4-decimal formatting) so identical inputs give byte-identical output.
_WIDTH = 460
_HEIGHT = 340
_ML = 56  # left margin (y-axis labels)
_MR = 16  # right margin
_MT = 26  # top margin (title)
_MB = 54  # bottom margin (x-axis labels)
_PLOT_W = _WIDTH - _ML - _MR
_PLOT_H = _HEIGHT - _MT - _MB


def _x(f: float) -> float:
    return _ML + f * _PLOT_W


def _y(v: float) -> float:
    return _MT + _PLOT_H - v * _PLOT_H


def _f4(x: float) -> str:
    return f"{x:.4f}"


def _gridlines() -> str:
    parts = []
    for t in (0.0, 0.25, 0.5, 0.75, 1.0):
        gx, gy = _x(t), _y(t)
        parts.append(
            f'<line x1="{_f4(_ML)}" y1="{_f4(gy)}" x2="{_f4(_ML + _PLOT_W)}"'
            f' y2="{_f4(gy)}" stroke="#e0e0e0" stroke-width="1"/>'
        )
        parts.append(
            f'<line x1="{_f4(gx)}" y1="{_f4(_MT)}" x2="{_f4(gx)}"'
            f' y2="{_f4(_MT + _PLOT_H)}" stroke="#e0e0e0" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{_f4(_ML - 8)}" y="{_f4(gy + 4)}" text-anchor="end"'
            f' font-size="10" fill="#555">{t:g}</text>'
        )
        parts.append(
            f'<text x="{_f4(gx)}" y="{_f4(_MT + _PLOT_H + 16)}"'
            f' text-anchor="middle" font-size="10" fill="#555">{t:g}</text>'
        )
    # Axes on top of the grid.
    parts.append(
        f'<line x1="{_f4(_ML)}" y1="{_f4(_MT)}" x2="{_f4(_ML)}"'
        f' y2="{_f4(_MT + _PLOT_H)}" stroke="#333" stroke-width="1.5"/>'
    )
    parts.append(
        f'<line x1="{_f4(_ML)}" y1="{_f4(_MT + _PLOT_H)}"'
        f' x2="{_f4(_ML + _PLOT_W)}" y2="{_f4(_MT + _PLOT_H)}" stroke="#333"'
        f' stroke-width="1.5"/>'
    )
    return "".join(parts)


def _frame(title: str, xlabel: str, ylabel: str, body: str) -> str:
    cx = _ML + _PLOT_W / 2
    return (
        f'<svg viewBox="0 0 {_WIDTH} {_HEIGHT}" role="img"'
        f' xmlns="http://www.w3.org/2000/svg"'
        f' style="max-width:460px;width:100%;height:auto">'
        f"<title>{html.escape(title)}</title>"
        f'<text x="{_f4(cx)}" y="16" text-anchor="middle" font-size="13"'
        f' fill="#222">{html.escape(title)}</text>'
        f"{_gridlines()}{body}"
        f'<text x="{_f4(cx)}" y="{_f4(_HEIGHT - 8)}" text-anchor="middle"'
        f' font-size="11" fill="#333">{html.escape(xlabel)}</text>'
        f'<text x="14" y="{_f4(_MT + _PLOT_H / 2)}" text-anchor="middle"'
        f' font-size="11" fill="#333"'
        f' transform="rotate(-90 14 {_f4(_MT + _PLOT_H / 2)})">'
        f"{html.escape(ylabel)}</text>"
        "</svg>"
    )


def _withheld_html(what: str, n: int) -> str:
    return (
        f"<p><em>{html.escape(what)} diagram withheld:</em> insufficient"
        f" data (n={int(n)}; 30 observations required).</p>"
    )


def reliability_diagram_svg(block: dict, title: str) -> str:
    """Inline SVG reliability diagram from a ``reliability_bins`` block.

    ``block`` is one arm of ``artifact["metrics"]["calibration"]
    ["reliability_bins"]``: ``{"bins": [...], "n": n, "sufficient": bool}``.
    Each bin plots mean self-reported confidence (x) against observed
    accuracy (y); the dashed diagonal is perfect calibration; circle
    area scales with bin count. Withheld (or malformed) blocks render a
    short placeholder paragraph, never a traceback.
    """
    if not isinstance(block, dict):
        return _withheld_html("Reliability", 0)
    try:
        n = int(block.get("n", 0))
    except (TypeError, ValueError):
        n = 0
    bins = block.get("bins")
    if not block.get("sufficient") or not bins:
        return _withheld_html("Reliability", n)
    try:
        # Zero-count (or negative-count) bins carry no data: skip them so
        # max_n below can never be zero. Malformed bin counts raise here
        # and are caught like any other malformed block.
        pts = [
            (float(b["mean_forecast"]), float(b["mean_outcome"]), int(b["n"]))
            for b in bins
            if int(b["n"]) > 0
        ]
    except (TypeError, ValueError, KeyError):
        return _withheld_html("Reliability", n)
    if not pts or any(
        not (0.0 <= f <= 1.0 and 0.0 <= o <= 1.0) for f, o, _ in pts
    ):
        return _withheld_html("Reliability", n)
    max_n = max(c for _, _, c in pts)
    body = (
        f'<line x1="{_f4(_x(0.0))}" y1="{_f4(_y(0.0))}"'
        f' x2="{_f4(_x(1.0))}" y2="{_f4(_y(1.0))}" stroke="#999"'
        f' stroke-width="1.5" stroke-dasharray="6,4"/>'
    )
    for f, o, c in pts:
        r = 3.0 + 5.0 * (c / max_n) ** 0.5
        body += (
            f'<circle cx="{_f4(_x(f))}" cy="{_f4(_y(o))}" r="{_f4(r)}"'
            f' fill="#1f77b4" fill-opacity="0.75" stroke="#0d4a75"'
            f' stroke-width="1"><title>self-reported confidence'
            f" {_f4(f)}, observed {_f4(o)}, n={c}</title></circle>"
        )
    return _frame(
        title, "mean self-reported confidence", "observed accuracy", body
    )


def risk_coverage_diagram_svg(sp: dict, title: str) -> str:
    """Inline SVG selective-risk curve from a ``selective_prediction`` block.

    ``sp`` carries ``risk_coverage_curve`` ([[coverage, risk], ...]),
    ``n`` and ``sufficient``. The curve shows selective risk (error rate
    on the retained set) as coverage shrinks toward the highest
    self-reported-confidence predictions. Withheld (or malformed) blocks
    render a placeholder.
    """
    if not isinstance(sp, dict):
        return _withheld_html("Selective-risk", 0)
    try:
        n = int(sp.get("n", 0))
    except (TypeError, ValueError):
        n = 0
    curve = sp.get("risk_coverage_curve")
    if not sp.get("sufficient") or not curve:
        return _withheld_html("Selective-risk", n)
    try:
        pts = [(float(c), float(r)) for c, r in curve]
    except (TypeError, ValueError):
        return _withheld_html("Selective-risk", n)
    if not pts or any(
        not (0.0 <= c <= 1.0 and 0.0 <= r <= 1.0) for c, r in pts
    ):
        return _withheld_html("Selective-risk", n)
    line = " ".join(f"{_f4(_x(c))},{_f4(_y(r))}" for c, r in pts)
    body = (
        f'<polyline points="{line}" fill="none" stroke="#1f77b4"'
        f' stroke-width="2"/>'
    )
    for c, r in pts:
        body += (
            f'<circle cx="{_f4(_x(c))}" cy="{_f4(_y(r))}" r="2.5"'
            f' fill="#1f77b4"><title>coverage {_f4(c)}, selective risk'
            f" {_f4(r)}</title></circle>"
        )
    return _frame(title, "coverage", "selective risk", body)
