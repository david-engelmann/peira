/**
 * Top board data shaping. Runs on the server only. The
 * instrument panel's first two sections, the cost scatter
 * (01) and the ranking rail with its inspector (02), share
 * one selection state, so they render from one island fed
 * by this bundle: scatter geometry for both viewports with
 * its labels seated by the standing placement solver, the
 * rail rows in their groups and tie segments, and every
 * result's inspector datum. Every value derives from the
 * payload through the standing modules; no name, price or
 * claim is written into this file.
 */

import {
  boardGroups,
  displayCi,
  duplicateShortNames,
  flipDecomposition,
  shortName,
  tieBands,
  wireWords,
  type BoardRow,
  type RankedRow,
} from "@/lib/payload";
import { fmtEce, fmtInt, fmtPct, fmtTax, fmtUsd } from "@/lib/format";
import { asrAxisFor } from "@/lib/chart";
import { scatterData, type ScatterDatum } from "@/lib/scatterData";
import {
  estimateLabelWidth,
  nudgePoints,
  placeLabels,
  type PlacedLabel,
  type Rect,
} from "@/lib/layout";
import { inspectorDataAll, type InspectorDatum } from "@/lib/inspectorData";
import { costStateOf } from "@/lib/cards";

/* ---------------- shared words ---------------- */

function joinNames(names: string[]): string {
  if (names.length <= 1) return names.join("");
  if (names.length === 2) return `${names[0]} and ${names[1]}`;
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

/* Truncation toward zero at a fixed precision, the
 * lower-bound printing rule the share image's words tier
 * follows (a printed floor never exceeds the recorded
 * value, and precision extends until a positive bound
 * prints as non-zero). */
function truncDec(v: number, decimals: number): string {
  const s = String(v);
  const neg = s.startsWith("-");
  const body = neg ? s.slice(1) : s;
  const [ip, fp = ""] = body.split(".");
  const kept = fp.slice(0, decimals).padEnd(decimals, "0");
  const intOut = (ip || "0").replace(/^0+(?=\d)/, "");
  return (neg ? "-" : "") + intOut + (decimals > 0 ? `.${kept}` : "");
}
function fmtUsdBound(v: number): string {
  for (const p of [2, 3, 4]) {
    const t = truncDec(v, p);
    if (Number(t) > 0) return `$${t.replace(/\.?0+$/, "")}`;
  }
  return `$${truncDec(v, 4).replace(/\.?0+$/, "")}`;
}

/** The cost words a named-in-words clause carries. */
function costWords(d: ScatterDatum): string {
  if (d.cost === null) return "no recorded cost";
  return d.lowerBound
    ? `at least ${fmtUsdBound(d.cost)}`
    : fmtUsd(d.cost);
}

/* ---------------- scatter geometry ---------------- */

export interface PlotPoint {
  runId: string;
  x: number;
  y: number;
  flagged: boolean;
  /** The point's full title, the native tooltip and accessible name. */
  title: string;
  /** The in-place label text, or null when the point is named in words. */
  label: string | null;
}

export interface PlotLabel {
  runId: string;
  x: number;
  y: number;
  text: string;
}

export interface RailBandRow {
  runId: string;
  name: string;
  asrText: string;
  cy: number;
}

export interface WordsClause {
  lead: string;
  items: Array<{ runId: string; name: string; rest: string }>;
}

export interface ScatterView {
  viewBox: string;
  width: number;
  height: number;
  gridLines: Array<{ y: number; label: string }>;
  decades: Array<{ x: number; label: string }>;
  points: PlotPoint[];
  labels: PlotLabel[];
  railRows: RailBandRow[];
  railDividerX: number | null;
  /** The off-scale annotation for a plotted point above the axis. */
  offScale: {
    runId: string;
    name: string;
    line1: string;
    line2: string;
    line3: string;
    caretX: number;
    textX: number;
    textY: number;
  } | null;
  words: WordsClause[];
}

interface ViewSpec {
  width: number;
  height: number;
  plotX0: number;
  plotX1: number;
  plotY0: number;
  plotY1: number;
  railCx: number | null;
  railNameX: number | null;
  railRateX: number | null;
  railDividerX: number | null;
  railTop: number;
  railBottom: number;
  marker: number;
}

const DESKTOP: ViewSpec = {
  width: 1280,
  height: 470,
  plotX0: 260,
  plotX1: 1240,
  plotY0: 30,
  plotY1: 410,
  railCx: 18,
  railNameX: 34,
  railRateX: 212,
  railDividerX: 224,
  railTop: 62,
  railBottom: 440,
  marker: 6.5,
};

const PHONE: ViewSpec = {
  width: 358,
  height: 292,
  plotX0: 34,
  plotX1: 350,
  plotY0: 24,
  plotY1: 252,
  railCx: null,
  railNameX: null,
  railRateX: null,
  railDividerX: null,
  railTop: 0,
  railBottom: 0,
  marker: 5,
};

function buildView(
  spec: ViewSpec,
  plotted: ScatterDatum[],
  rail: ScatterDatum[],
  domain: [number, number],
  axisMax: number,
  annotate: boolean,
): ScatterView {
  const [lo, hi] = domain;
  const xOf = (c: number) =>
    spec.plotX0 +
    ((Math.log10(c) - Math.log10(lo)) / (Math.log10(hi) - Math.log10(lo))) *
      (spec.plotX1 - spec.plotX0);
  const yOf = (a: number) =>
    spec.plotY0 + (1 - a / axisMax) * (spec.plotY1 - spec.plotY0);
  const drawn = plotted.filter((d) => d.asr <= axisMax);
  const offScalePlotted = plotted.filter((d) => d.asr > axisMax);
  const pts = drawn.map((d) => ({
    runId: d.runId,
    x: xOf(d.cost!),
    y: yOf(d.asr),
    flagged: d.flagged,
    title: d.title,
    label: d.label,
    datum: d,
  }));
  nudgePoints(pts, spec.marker * 2 + 2, spec.marker * 2);
  /* Labels seat for the unflagged points only. A flagged
   * point is named in words under the panel, on the page as
   * on the share card, so its figure always travels with
   * the clause that names it. */
  const labelPts = pts
    .filter((p) => !p.flagged)
    .map((p) => ({
      runId: p.runId,
      x: p.x,
      y: p.y,
      marker: spec.marker,
      label: p.label,
    }));
  const furniture: Rect[] = [];
  /* Gridline labels and the axis decade labels are furniture. */
  for (const t of [0, axisMax / 2, axisMax]) {
    furniture.push({
      x: spec.plotX0 - 44,
      y: yOf(t) - 8,
      w: 34,
      h: 16,
    });
  }
  /* The off-scale annotation block, when a point needs it.
   * The wide plot carries the annotation inside the plot at
   * the point's true cost; the phone plot has no room for it,
   * so there the point is named in words under the panel
   * instead, with its decomposition when it is flagged. */
  let offScale: ScatterView["offScale"] = null;
  if (offScalePlotted.length > 0 && annotate) {
    const d = offScalePlotted.reduce((a, b) => (b.asr > a.asr ? b : a));
    const row = d;
    const decomp = row.flagged ? flipDecompositionById(row.runId) : null;
    const line2 = !row.flagged
      ? `${row.label} at ${fmtPct(row.asr)}, above the top of this scale,`
      : decomp !== null
        ? `${row.label} counted ${fmtPct(row.asr)}, ${
            decomp.malformedShare > 0.5
              ? "mostly malformed output,"
              : "mostly changed decisions,"
          }`
        : `${row.label}, flagged and not ranked,`;
    offScale = {
      runId: row.runId,
      name: row.label,
      line1: "Off this scale",
      line2,
      line3: row.flagged
        ? "and reads in the flagged band below."
        : "and reads in the ranking below.",
      caretX: xOf(row.cost!),
      textX: spec.plotX0 + 24,
      textY: spec.plotY0 + 88,
    };
    furniture.push({
      x: offScale.textX - 6,
      y: offScale.textY - 16,
      w: Math.min(430, spec.plotX1 - offScale.textX),
      h: 76,
    });
  }
  const bounds: Rect = {
    x: spec.plotX0 - 6,
    y: 6,
    w: spec.plotX1 - spec.plotX0 + 12,
    h: spec.height - 40,
  };
  const { placed, keyed } = placeLabels(labelPts, furniture, bounds);
  const placedById = new Map<string, PlacedLabel>(
    placed.map((p) => [p.runId, p]),
  );
  const labels: PlotLabel[] = placed.map((p) => ({
    runId: p.runId,
    x: p.x,
    y: p.y + 11,
    text: labelPts.find((l) => l.runId === p.runId)!.label!,
  }));
  const keyedSet = new Set(keyed);
  /* The rail band (desktop only): rows at their true rate
   * height until the pitch would crowd them, then spread at
   * a compressed pitch inside the band, in rate order. */
  const railDrawn = rail.filter((d) => d.asr <= axisMax);
  const railSorted = [...railDrawn].sort(
    (a, b) => b.asr - a.asr || a.label.localeCompare(b.label),
  );
  const railRows: RailBandRow[] = [];
  if (spec.railCx !== null) {
    const n = railSorted.length;
    const span = spec.railBottom - spec.railTop;
    const pitch = n > 1 ? Math.min(34, span / (n - 1)) : 34;
    /* True heights first; a spread pass then holds the pitch
     * where neighbours would collide, anchored at the top. */
    const ys = railSorted.map((d) => Math.max(spec.railTop, yOf(d.asr)));
    for (let i = 1; i < ys.length; i++) {
      ys[i] = Math.max(ys[i], ys[i - 1] + Math.min(pitch, 34));
    }
    const overflow = ys.length ? ys[ys.length - 1] - spec.railBottom : 0;
    if (overflow > 0) {
      for (let i = 0; i < ys.length; i++) ys[i] -= overflow;
    }
    railSorted.forEach((d, i) => {
      railRows.push({
        runId: d.runId,
        name: d.label,
        asrText: fmtPct(d.asr),
        cy: Math.round(ys[i] * 10) / 10,
      });
    });
  }
  /* Named in words: the flagged plotted points first, in
   * rate order, then the points no label could seat, then
   * any rail result above the scale. */
  const words: WordsClause[] = [];
  const flaggedPlotted = drawn
    .filter((d) => d.flagged)
    .sort((a, b) => a.asr - b.asr);
  if (flaggedPlotted.length > 0) {
    words.push({
      lead: "Amber-ringed in the plot",
      items: flaggedPlotted.map((d) => ({
        runId: d.runId,
        name: d.label,
        rest: `at ${fmtPct(d.asr)} and ${costWords(d)}`,
      })),
    });
  }
  const crowded = pts.filter((p) => !p.flagged && keyedSet.has(p.runId));
  if (crowded.length > 0) {
    words.push({
      lead:
        crowded.length === 1
          ? "Too crowded at its disc"
          : "Too crowded at their discs",
      items: crowded.map((p) => ({
        runId: p.runId,
        name: p.label!,
        rest: `at ${fmtPct(p.datum.asr)} and ${costWords(p.datum)}`,
      })),
    });
  }
  const railAbove = rail.filter((d) => d.asr > axisMax);
  if (railAbove.length > 0) {
    words.push({
      lead: "Above the scale, on the rail",
      items: railAbove.map((d) => ({
        runId: d.runId,
        name: d.label,
        rest: `at ${fmtPct(d.asr)}`,
      })),
    });
  }
  if (!annotate && offScalePlotted.length > 0) {
    words.push({
      lead: "Off this scale",
      items: offScalePlotted.map((d) => {
        const decomp = d.flagged ? flipDecompositionById(d.runId) : null;
        return {
          runId: d.runId,
          name: d.label,
          rest: !d.flagged
            ? `at ${fmtPct(d.asr)} and ${costWords(d)}`
            : decomp !== null
              ? `counted ${fmtPct(d.asr)}, genuine flip rate ${fmtPct(decomp.genuineRate)}, with ${fmtPct(decomp.malformedShare)} of counted flips to malformed output, and ${costWords(d)}`
              : "flagged and not ranked",
        };
      }),
    });
  }
  const decades: Array<{ x: number; label: string }> = [];
  for (
    let e = Math.ceil(Math.log10(lo));
    e <= Math.floor(Math.log10(hi));
    e++
  ) {
    const v = 10 ** e;
    decades.push({
      x: Math.round(xOf(v) * 10) / 10,
      label: v < 1 ? `$${v.toFixed(2)}` : `$${v}`,
    });
  }
  return {
    viewBox: `0 0 ${spec.width} ${spec.height}`,
    width: spec.width,
    height: spec.height,
    gridLines: [0, axisMax / 2, axisMax].map((t) => ({
      y: Math.round(yOf(t) * 10) / 10,
      label: `${Math.round(t * 100)}`,
    })),
    decades,
    points: pts.map((p) => ({
      runId: p.runId,
      x: Math.round(p.x * 10) / 10,
      y: Math.round(p.y * 10) / 10,
      flagged: p.flagged,
      title: p.title,
      label: placedById.has(p.runId) ? p.label : null,
    })),
    labels,
    railRows,
    railDividerX: spec.railDividerX,
    offScale,
    words,
  };
}

/* The decomposition lookup for the off-scale annotation,
 * keyed by run id over the payload's flagged rows. */
let decompCache: Map<string, ReturnType<typeof flipDecomposition>> | null =
  null;
function flipDecompositionById(
  runId: string,
): ReturnType<typeof flipDecomposition> {
  if (decompCache === null) {
    decompCache = new Map();
    for (const row of boardGroups().flagged) {
      decompCache.set(row.run_id, flipDecomposition(row));
    }
  }
  return decompCache.get(runId) ?? null;
}

/* ---------------- ranking rail ---------------- */

export interface RailRow {
  runId: string;
  kind: "full" | "slice";
  rank: number;
  name: string;
  wire: string | null;
  mark: InspectorDatum["mark"];
  ariaLabel: string;
  asrText: string;
  whisker: { lo: number; hi: number; pt: number } | null;
  benignText: string | null;
  eceText: string | null;
  taxText: string | null;
  costText: string;
}

export type RailSegment =
  | { kind: "band"; rows: RailRow[] }
  | { kind: "single"; row: RailRow };

function railAriaLabel(row: RankedRow, name: string, wire: string | null): string {
  const parts = [name];
  if (wire) parts.push(wire);
  parts.push(`rank ${row.rank}`);
  if (row.asr_conditional != null) {
    parts.push(`attack success ${fmtPct(row.asr_conditional)}`);
  }
  const ci = displayCi(row);
  if (ci) parts.push(`95% CI ${fmtPct(ci[0])} to ${fmtPct(ci[1])}`);
  if (row.benign_accuracy != null) {
    parts.push(`benign accuracy ${fmtPct(row.benign_accuracy)}`);
  }
  if (row.ece_attacked != null) {
    parts.push(`attacked ECE ${fmtEce(row.ece_attacked)}`);
  }
  if (row.robustness_tax != null) {
    parts.push(`robustness tax ${fmtTax(row.robustness_tax)}`);
  }
  if (row.malformed_rate != null) {
    parts.push(`malformed ${fmtPct(row.malformed_rate)}`);
  }
  return parts.join(", ");
}

function railRow(
  row: RankedRow,
  kind: "full" | "slice",
  dupes: Set<string>,
  axisMax: number,
  mark: InspectorDatum["mark"],
): RailRow {
  const name = shortName(row);
  const wire = dupes.has(name) ? wireWords(row.wire) : null;
  const cost = costStateOf(row);
  return {
    runId: row.run_id,
    kind,
    rank: row.rank,
    name,
    wire,
    mark,
    ariaLabel: railAriaLabel(row, name, wire),
    asrText: row.asr_conditional != null ? fmtPct(row.asr_conditional) : "·",
    whisker:
      row.asr_conditional != null && displayCi(row)
        ? {
            lo: axisPctOf(displayCi(row)![0], axisMax),
            hi: axisPctOf(displayCi(row)![1], axisMax),
            pt: axisPctOf(row.asr_conditional, axisMax),
          }
        : null,
    benignText: row.benign_accuracy != null ? fmtPct(row.benign_accuracy) : null,
    eceText: row.ece_attacked != null ? fmtEce(row.ece_attacked) : null,
    taxText: row.robustness_tax != null ? fmtTax(row.robustness_tax) : null,
    costText:
      cost.kind === "amount"
        ? fmtUsd(cost.value)
        : cost.kind === "lower-bound"
          ? `≥ ${fmtUsd(cost.value)}`
          : cost.kind === "local"
            ? fmtUsd(0)
            : "·",
  };
}

function axisPctOf(v: number, axisMax: number): number {
  return Math.min(100, Math.max(0, (v / axisMax) * 100));
}

function segments(
  rows: RailRow[],
  bands: Map<number, [number, number]>,
): RailSegment[] {
  const out: RailSegment[] = [];
  let i = 0;
  while (i < rows.length) {
    const band = bands.get(rows[i].rank);
    if (band && band[0] === rows[i].rank) {
      const members = rows.filter((r) => r.rank >= band[0] && r.rank <= band[1]);
      out.push({ kind: "band", rows: members });
      i += members.length;
    } else {
      out.push({ kind: "single", row: rows[i] });
      i += 1;
    }
  }
  return out;
}

/* The rows a fold hides, counted the way the rail renders:
   a tie segment stands or folds whole, so the hidden count
   is the sum over segments that start at or past the fold
   line, never the raw difference of counts, which a band
   straddling the line would falsify. */
function foldedOf(segs: RailSegment[], foldAfter: number): number {
  let start = 0;
  let hidden = 0;
  for (const seg of segs) {
    const size = seg.kind === "band" ? seg.rows.length : 1;
    if (start >= foldAfter) hidden += size;
    start += size;
  }
  return hidden;
}

/* ---------------- the bundle ---------------- */

export interface TopData {
  axisMax: number;
  scatter: {
    titleText: string;
    titleClaim: boolean;
    caption: string;
    wide: ScatterView;
    phone: ScatterView;
    readings: string[];
    captions: string[];
    chartId: string;
    phoneRail: Array<{ runId: string; name: string; asrText: string }>;
  };
  rail: {
    fullSegments: RailSegment[];
    fullCount: number;
    foldAfter: number;
    foldedCount: number;
    sliceSegments: RailSegment[];
    sliceCount: number;
    sliceFoldAfter: number;
    sliceFoldedCount: number;
    guardCaption: string;
  };
  inspectors: Record<string, InspectorDatum>;
  defaultRunId: string;
}

export function topData(): TopData {
  const groups = boardGroups();
  const allRows: BoardRow[] = [
    ...groups.full,
    ...groups.slices,
    ...groups.flagged,
  ];
  const dupes = duplicateShortNames(allRows);
  const rankedRates = [...groups.full, ...groups.slices]
    .map((r) => r.asr_conditional)
    .filter((v): v is number => v !== null && v !== undefined);
  const axis = asrAxisFor(rankedRates.length ? Math.max(...rankedRates) : 0);
  const axisMax = axis.max;
  const sd = scatterData();
  const { byRunId } = inspectorDataAll(axisMax);
  const inspectors: Record<string, InspectorDatum> = {};
  for (const [id, d] of byRunId) inspectors[id] = d;

  /* The scatter title claim, the same derivation the share
   * card's headline guard computes: over the ranked plotted
   * population, the priciest run's attack success equals
   * that population's highest. When it does not hold, the
   * title falls back to the section's neutral name and the
   * readings below the panel state the two facts apart. */
  const plottedRows = sd.plotted;
  const rankedPlotted = plottedRows.filter((d) => !d.flagged);
  const priciest = rankedPlotted.reduce((a, b) =>
    (b.cost ?? 0) > (a.cost ?? 0) ? b : a,
  );
  const maxRankedAsr = Math.max(...rankedPlotted.map((d) => d.asr));
  const titleClaim = priciest.asr === maxRankedAsr;
  const titleText = titleClaim
    ? "The priciest run flipped most"
    : "What robustness costs per run";
  const caption = `Cost per run against attack success. Discs are every full suite result with a recorded cost, on the shared 0 to ${Math.round(axisMax * 100)} scale the ranking uses.`;

  const readings: string[] = [];
  const r = sd.readings;
  readings.push(
    r.priciestIsMostFlipped
      ? `The priciest run, ${r.priciest.label} ${r.priciest.costPhrase}, also flipped most of any ranked result ${r.rankedScope}, at ${r.mostFlippedRanked.asr !== null ? fmtPct(r.mostFlippedRanked.asr) : "·"}.`
      : `The priciest run is ${r.priciest.label} ${r.priciest.costPhrase}. The ranked result that flipped most ${r.rankedScope} is ${r.mostFlippedRanked.label} at ${r.mostFlippedRanked.asr !== null ? fmtPct(r.mostFlippedRanked.asr) : "·"}.`,
  );
  readings.push(
    `The toughest ranked result ${r.rankedScope}, ${r.toughestRanked.label}, flipped ${r.toughestRanked.asr !== null ? fmtPct(r.toughestRanked.asr) : "·"} ${r.toughestRanked.costPhrase}. The cheapest run on the chart is ${r.cheapest.label} ${r.cheapest.costPhrase}.`,
  );

  const captions: string[] = [];
  captions.push(
    "Cost is the recorded total for one full run, plotted on a log scale. Where some calls went unpriced, the recorded cost is a lower bound and the true cost sits higher than the point. The point's own reading says when it is a lower bound.",
  );
  captions.push(
    `${fmtInt(sd.railCount)} results hold no place on the cost axis, because their recorded cost is $0.00 or no cost was recorded at all, so they sit on the rail at the left of the wide chart at their attack success, and on a phone they stand as named rows under the plot, in attack success order. ${joinNames(sd.zeroNames)} recorded a cost of $0.00, while ${joinNames(sd.noneNames)} recorded no cost at all. A recorded zero and no recorded cost are different facts, and the rail keeps them apart in words.`,
  );
  if (sd.aboveScaleNames.length > 0) {
    captions.push(
      `${joinNames(sd.aboveScaleNames)} ${sd.aboveScaleNames.length === 1 ? "sits" : "sit"} above the chart's 0 to ${Math.round(axisMax * 100)} percent scale, so ${sd.aboveScaleNames.length === 1 ? "its disc stands off the top of the plot rather than at a false position, and the plot names it in the annotation at its true cost" : "their discs stand off the top of the plot rather than at false positions, and the plot names them in the annotation at their true costs"}.`,
    );
  }
  captions.push(
    `The chart plots ${fmtInt(sd.plottedCount)} of the board's ${fmtInt(sd.populationCount + sd.sliceCount)} results, with ${fmtInt(sd.railCount)} more on the rail. The ${fmtInt(sd.sliceCount)} guardrail slices are not plotted, since they ran on the abstain base and record no serving cost.`,
  );
  const chartId = `Peira decision robustness board, cost against attack success. ${fmtInt(sd.populationCount)} full suite results, ${fmtInt(sd.plottedCount)} plotted and ${fmtInt(sd.railCount)} on the rail. Dataset ${sd.dataset}, updated ${sd.updated}.`;

  const wide = buildView(DESKTOP, sd.plotted, sd.rail, sd.domain, axisMax, true);
  const phone = buildView(PHONE, sd.plotted, sd.rail, sd.domain, axisMax, false);
  const phoneRail = [...sd.rail]
    .sort((a, b) => b.asr - a.asr || a.label.localeCompare(b.label))
    .map((d) => ({ runId: d.runId, name: d.label, asrText: fmtPct(d.asr) }));

  const markFor = (row: BoardRow) => byRunId.get(row.run_id)!.mark;
  const fullRows = (groups.full as RankedRow[]).map((row) =>
    railRow(row, "full", dupes, axisMax, markFor(row)),
  );
  const sliceRows = (groups.slices as RankedRow[]).map((row) =>
    railRow(row, "slice", dupes, axisMax, markFor(row)),
  );
  const sliceCases = groups.slices[0]?.n_cases ?? 0;
  const foldAfter = 8;
  const sliceFoldAfter = 3;
  const fullSegments = segments(
    fullRows,
    tieBands(groups.full as RankedRow[]),
  );
  const sliceSegments = segments(
    sliceRows,
    tieBands(groups.slices as RankedRow[]),
  );
  return {
    axisMax,
    scatter: {
      titleText,
      titleClaim,
      caption,
      wide,
      phone,
      readings,
      captions,
      chartId,
      phoneRail,
    },
    rail: {
      fullSegments,
      fullCount: fullRows.length,
      foldAfter,
      foldedCount: foldedOf(fullSegments, foldAfter),
      sliceSegments,
      sliceCount: sliceRows.length,
      sliceFoldAfter,
      sliceFoldedCount: foldedOf(sliceSegments, sliceFoldAfter),
      guardCaption: `Abstention contract. Measured on the ${fmtInt(sliceCases)}-case guard subset, ranked apart.`,
    },
    inspectors,
    defaultRunId: groups.full[0].run_id,
  };
}

