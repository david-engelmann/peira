---
version: alpha
name: Peira benchmark board
description: Design tokens and law for the peira benchmark board, an Operate surface where charts carry the page and every figure is evidence.
colors:
  ground: "#f6f8fd"
  ground-top: "#f6f8fd"
  ground-deep: "#f6f8fd"
  band: "#edf1fa"
  inset: "#f2f5fc"
  panel: "#ffffff"
  panel-2: "#edf1fa"
  lift: "#e1e9fa"
  hairline: "#b8c5dc"
  edge: "#d6deee"
  edge-soft: "#d6deee"
  ink-1: "#111931"
  ink-2: "#354661"
  ink-3: "#495d7c"
  accent: "#284cb3"
  amber: "#8b4b16"
  chart-grid: "#b8c5dc"
  chart-axis: "#b8c5dc"
  chart-tick: "#495d7c"
  chart-glyph-dark: "#0b0e12"
  chart-glyph-light: "#ffffff"
  chart-field: "#465e80"
  chart-subject: "#284cb3"
  seg-genuine: "#62729b"
  chart-series-anthropic: "#d97757"
  chart-series-openai: "#d7e0e8"
  chart-series-google: "#8ab8ff"
  chart-series-meta: "#4a7dff"
  chart-series-mistral: "#ff8a3d"
  chart-series-deepseek: "#6e7bff"
  chart-series-fallback: "#8b98a5"
typography:
  display:
    fontFamily: "Archivo, system-ui, sans-serif"
    fontSize: "clamp(42px, 4.8vw, 73px)"
    fontWeight: 650
    lineHeight: 1.015
    letterSpacing: "-0.055em"
  scene-head:
    fontFamily: "Archivo, system-ui, sans-serif"
    fontSize: "4.25rem"
    fontWeight: 800
    lineHeight: 0.98
    letterSpacing: "-0.055em"
  heading:
    fontFamily: "Archivo, system-ui, sans-serif"
    fontSize: "30px"
    fontWeight: 700
    lineHeight: 1.12
    letterSpacing: "-0.018em"
  body:
    fontFamily: "Archivo, system-ui, sans-serif"
    fontSize: "14.5px"
    fontWeight: 400
    lineHeight: 1.45
  caption:
    fontFamily: "Archivo, system-ui, sans-serif"
    fontSize: "12px"
  micro:
    fontFamily: "Archivo, system-ui, sans-serif"
    fontSize: "11.5px"
  mono:
    fontFamily: "JetBrains Mono, ui-monospace, monospace"
    fontSize: "11.5px"
    fontWeight: 400
    lineHeight: 1.45
    letterSpacing: "0.14em"
  data-figures:
    fontFamily: "Archivo, system-ui, sans-serif"
    fontFeature: "\"tnum\" 1"
rounded:
  ctl: "6px"
  panel: "12px"
  pill: "999px"
spacing:
  space-1: "4px"
  space-2: "8px"
  space-3: "12px"
  space-4: "16px"
  space-5: "24px"
  space-6: "32px"
  space-7: "48px"
  space-8: "64px"
  space-9: "96px"
components:
  well:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.ink-1}"
    rounded: "{rounded.panel}"
    padding: "{spacing.space-5}"
  panel-row:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.ink-1}"
    rounded: "{rounded.panel}"
    padding: "{spacing.space-4}"
  detail-card:
    backgroundColor: "{colors.lift}"
    textColor: "{colors.ink-1}"
    rounded: "{rounded.panel}"
    padding: "{spacing.space-4}"
  chip:
    backgroundColor: "{colors.panel-2}"
    textColor: "{colors.ink-1}"
    rounded: "{rounded.ctl}"
    padding: "{spacing.space-2}"
  chart-gridline:
    backgroundColor: "{colors.chart-grid}"
    height: "1px"
  chart-axis-label:
    textColor: "{colors.chart-tick}"
    typography: "{typography.micro}"
  scatter-disc-field:
    backgroundColor: "{colors.chart-field}"
    rounded: "{rounded.pill}"
  scatter-disc-subject:
    backgroundColor: "{colors.chart-subject}"
    rounded: "{rounded.pill}"
  vendor-chip-anthropic:
    backgroundColor: "{colors.chart-series-anthropic}"
    textColor: "{colors.chart-glyph-dark}"
    rounded: "{rounded.ctl}"
  vendor-chip-openai:
    backgroundColor: "{colors.chart-series-openai}"
    textColor: "{colors.chart-glyph-dark}"
    rounded: "{rounded.ctl}"
  vendor-chip-google:
    backgroundColor: "{colors.chart-series-google}"
    textColor: "{colors.chart-glyph-dark}"
    rounded: "{rounded.ctl}"
  vendor-chip-meta:
    backgroundColor: "{colors.chart-series-meta}"
    textColor: "{colors.chart-glyph-dark}"
    rounded: "{rounded.ctl}"
  vendor-chip-mistral:
    backgroundColor: "{colors.chart-series-mistral}"
    textColor: "{colors.chart-glyph-dark}"
    rounded: "{rounded.ctl}"
  vendor-chip-deepseek:
    backgroundColor: "{colors.chart-series-deepseek}"
    textColor: "{colors.chart-glyph-dark}"
    rounded: "{rounded.ctl}"
  vendor-chip-fallback:
    backgroundColor: "{colors.chart-series-fallback}"
    textColor: "{colors.chart-glyph-dark}"
    rounded: "{rounded.ctl}"
  chart-axis-line:
    backgroundColor: "{colors.chart-axis}"
    height: "1px"
  primary-control:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.chart-glyph-light}"
    rounded: "{rounded.ctl}"
  finding-link:
    textColor: "{colors.ink-1}"
    typography: "{typography.body}"
  caption-note:
    textColor: "{colors.ink-3}"
    typography: "{typography.caption}"
  well-divider:
    backgroundColor: "{colors.edge-soft}"
    height: "1px"
  hairline-rule:
    backgroundColor: "{colors.hairline}"
    height: "1px"
  edge-strip:
    backgroundColor: "{colors.edge}"
    height: "1px"
  page:
    backgroundColor: "{colors.ground}"
    textColor: "{colors.ink-1}"
  page-field-top:
    backgroundColor: "{colors.ground-top}"
  page-depth:
    backgroundColor: "{colors.ground-deep}"
  scene-band:
    backgroundColor: "{colors.band}"
  chart-well:
    backgroundColor: "{colors.inset}"
    textColor: "{colors.ink-1}"
  scene-lede:
    textColor: "{colors.ink-2}"
    typography: "{typography.body}"
  flagged-divider:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.amber}"
    rounded: "{rounded.panel}"
  split-bar-genuine:
    backgroundColor: "{colors.seg-genuine}"
    rounded: "{rounded.pill}"
---

# Peira benchmark board

## Reading order

Open with the benchmark question beside the distribution of measured attack success. Give the leading rates with their confidence intervals. Put the two analyses before the interactive explorer. Scoring details and the paired case belong in Method. Readers can inspect excluded results through the explorer filter.

## Typography and surfaces

Archivo carries the question, model names and measurements. The overview plots each ranked run on the same zero-based scale. The cyan bars identify the three rows beneath the plot. Hovering or tapping a bar reveals the model, rate, interval and link to its record. Arrow keys and the two step buttons move between observations.

The light theme uses porcelain backgrounds and navy text. The dark theme uses midnight backgrounds and pale text. Violet highlights the attack-family finding and turquoise identifies the cost analysis. The paired tokens in `app/study.css` define both themes. The board follows the system preference until the reader chooses Light or Dark.

A decorative contour field sits behind the introduction. It settles after a short entrance and responds to pointer movement. With reduced motion enabled it stays still. Chart geometry stays fixed during inspection.

The analysis uses aligned labels and position on a common scale, following William Cleveland and Robert McGill’s graphical perception work. Case counts and denominators sit beside the corresponding family rates. Use a logarithmic scale for positive costs and label the currency. Keep missing prices and subset runs identifiable.

## Interaction

Keep the chart, rankings and families views addressable by URL. Model links open their records. Maintain keyboard access, visible focus, touch targets and reduced-motion support. Values and chart geometry stay still while the reader compares results.
