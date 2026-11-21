---
version: alpha
name: Peira benchmark board
description: Design tokens and law for the peira benchmark board, an Operate surface where charts carry the page and every figure is evidence.
colors:
  ground: "#faf9f5"
  ground-top: "#faf9f5"
  ground-deep: "#faf9f5"
  band: "#f2f3ec"
  inset: "#f6f7f1"
  panel: "#fffefa"
  panel-2: "#f1f3ed"
  lift: "#e4ebe1"
  hairline: "#c3ccc1"
  edge: "#c2cbbf"
  edge-soft: "#dce2d9"
  ink-1: "#172e2b"
  ink-2: "#415650"
  ink-3: "#52665e"
  accent: "#006957"
  amber: "#905023"
  chart-grid: "#c3ccc1"
  chart-axis: "#c3ccc1"
  chart-tick: "#52665e"
  chart-glyph-dark: "#0b0e12"
  chart-glyph-light: "#fffefa"
  chart-field: "#526f65"
  chart-subject: "#006957"
  seg-genuine: "#668475"
  chart-series-anthropic: "#d97757"
  chart-series-openai: "#d7e0e8"
  chart-series-google: "#8ab8ff"
  chart-series-meta: "#4a7dff"
  chart-series-mistral: "#ff8a3d"
  chart-series-deepseek: "#6e7bff"
  chart-series-fallback: "#8b98a5"
typography:
  display:
    fontFamily: "Georgia, serif"
    fontSize: "5.625rem"
    fontWeight: 500
    lineHeight: 0.98
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
  panel: "4px"
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

Georgia introduces the research question. Archivo and tabular figures carry the data. The dark green overview figure uses a shared zero baseline. Its three highlighted bars correspond to the three named results directly below it. On phones the figure follows the question in reading order.

The light palette above uses warm paper and dark green ink. The dark palette uses evergreen ground, pale ink and a mint accent. Both palettes use fine rules, and each gives chart markers, labels and focus outlines their own contrast against the surrounding surface. The paired color tokens in `app/study.css` and the section stylesheets define the rendered palettes. The board follows the system color preference until the reader selects Light or Dark in the masthead. That choice persists on the device.

The analysis uses aligned labels and position on a common scale, following William Cleveland and Robert McGill’s graphical perception work. Case counts and denominators sit beside the corresponding family rates. Use a logarithmic scale for positive costs and label the currency. Keep missing prices and subset runs identifiable.

## Interaction

Keep the chart, rankings and families views addressable by URL. Model links open their records. Maintain keyboard access, visible focus, touch targets and reduced-motion support. Values and chart geometry stay still while the reader compares results.
