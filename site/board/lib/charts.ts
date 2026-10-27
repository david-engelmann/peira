/**
 * Chart derivations for the round 9 chart suite (scatter,
 * heatmap, calibration). Layout facts only: populations, column
 * orderings, label placements, colour ramps. Every printed
 * number still comes straight from a payload field through
 * lib/format; nothing here recomputes a metric. The one
 * statistic computed is the family mean attack success used to
 * ORDER heatmap columns, which is the design spec's standing
 * ordering rule and is printed nowhere.
 */

import type { BoardRow } from "@/lib/payload";
import { isSliceRow, fullCaseCount } from "@/lib/payload";
import { fmtPctCell } from "@/lib/format";

/* ---------------- typed detail access ---------------- */

export interface FamilyStat {
  asr: number | null;
  asrCi95: [number, number] | null;
  nEligible: number | null;
  nCostedCalls: number | null;
  nLatencyCalls: number | null;
}

function detailOf(row: BoardRow): Record<string, unknown> {
  return row.detail !== null && typeof row.detail === "object"
    ? (row.detail as Record<string, unknown>)
    : {};
}

function numOrNull(x: unknown): number | null {
  return typeof x === "number" && Number.isFinite(x) ? x : null;
}

function pairOrNull(x: unknown): [number, number] | null {
  if (
    Array.isArray(x) &&
    x.length === 2 &&
    typeof x[0] === "number" &&
    typeof x[1] === "number"
  ) {
    return [x[0], x[1]];
  }
  return null;
}

/** Family records keyed by family id, in payload key order. */
export function familiesOf(row: BoardRow): Map<string, FamilyStat> {
  const out = new Map<string, FamilyStat>();
  const raw = detailOf(row).families;
  if (raw === null || typeof raw !== "object" || Array.isArray(raw)) {
    return out;
  }
  for (const [key, value] of Object.entries(raw)) {
    if (value === null || typeof value !== "object" || Array.isArray(value)) {
      continue;
    }
    const f = value as Record<string, unknown>;
    out.set(key, {
      asr: numOrNull(f.asr),
      asrCi95: pairOrNull(f.asr_ci95),
      nEligible: numOrNull(f.n_eligible),
      nCostedCalls: numOrNull(f.n_costed_calls),
      nLatencyCalls: numOrNull(f.n_latency_calls),
    });
  }
  return out;
}

export interface ReliabilityBin {
  meanForecast: number;
  meanOutcome: number;
  n: number;
}

export interface CalibrationData {
  ece: number | null;
  brier: number | null;
  n: number | null;
  sufficient: boolean;
  bins: ReliabilityBin[];
}

/** The attacked arm's calibration block for one row. */
export function calibrationOf(row: BoardRow): CalibrationData | null {
  const raw = detailOf(row).calibration;
  if (raw === null || typeof raw !== "object" || Array.isArray(raw)) {
    return null;
  }
  const cal = raw as Record<string, unknown>;
  const attacked =
    cal.attacked !== null && typeof cal.attacked === "object"
      ? (cal.attacked as Record<string, unknown>)
      : {};
  const binsRaw =
    cal.reliability_bins !== null && typeof cal.reliability_bins === "object"
      ? ((cal.reliability_bins as Record<string, unknown>)
          .attacked as Record<string, unknown> | undefined)
      : undefined;
  const bins: ReliabilityBin[] = [];
  const binList = binsRaw && Array.isArray(binsRaw.bins) ? binsRaw.bins : [];
  for (const b of binList) {
    if (b === null || typeof b !== "object") continue;
    const bin = b as Record<string, unknown>;
    const mf = numOrNull(bin.mean_forecast);
    const mo = numOrNull(bin.mean_outcome);
    const n = numOrNull(bin.n);
    if (mf === null || mo === null || n === null) continue;
    bins.push({ meanForecast: mf, meanOutcome: mo, n });
  }
  return {
    ece: numOrNull(attacked.ece),
    brier: numOrNull(attacked.brier),
    n: numOrNull(attacked.n),
    sufficient: attacked.sufficient === true,
    bins,
  };
}

export interface CalibrationArm {
  ece: number | null;
  brier: number | null;
  n: number | null;
  sufficient: boolean;
}

export interface CalibrationArms {
  attacked: CalibrationArm;
  benign: CalibrationArm;
  /** Share of eligible cases that reported a confidence, per arm. */
  coverageAttacked: number | null;
  coverageBenign: number | null;
}

/**
 * Both calibration arms plus the confidence coverage, for the
 * detail card's stat grid (design 4.5). The calibration section
 * plots the attacked arm only; the card carries both arms in
 * numbers, which is where the benign arm lives on this page.
 */
export function calibrationArmsOf(row: BoardRow): CalibrationArms | null {
  const raw = detailOf(row).calibration;
  if (raw === null || typeof raw !== "object" || Array.isArray(raw)) {
    return null;
  }
  const cal = raw as Record<string, unknown>;
  const arm = (key: string): CalibrationArm => {
    const a =
      cal[key] !== null && typeof cal[key] === "object"
        ? (cal[key] as Record<string, unknown>)
        : {};
    return {
      ece: numOrNull(a.ece),
      brier: numOrNull(a.brier),
      n: numOrNull(a.n),
      sufficient: a.sufficient === true,
    };
  };
  const cov =
    cal.confidence_coverage !== null &&
    typeof cal.confidence_coverage === "object"
      ? (cal.confidence_coverage as Record<string, unknown>)
      : {};
  return {
    attacked: arm("attacked"),
    benign: arm("benign"),
    coverageAttacked: numOrNull(cov.attacked),
    coverageBenign: numOrNull(cov.benign),
  };
}

/* ---------------- scatter population ---------------- */

export interface ScatterSets {
  /** Non-slice rows with a recorded cost above zero. They plot. */
  plotted: BoardRow[];
  /** Non-slice rows with no chartable cost. They take the rail. */
  rail: BoardRow[];
  /** Slice rows. Excluded from this chart by population. */
  slices: BoardRow[];
  /** Every row in the chart's population, plotted plus rail. */
  population: BoardRow[];
}

export function scatterSets(rows: BoardRow[]): ScatterSets {
  const full = fullCaseCount(rows);
  const slices = rows.filter((r) => isSliceRow(r, full));
  const nonSlice = rows.filter((r) => !isSliceRow(r, full));
  const plotted = nonSlice.filter(
    (r) => r.total_cost_usd !== null && r.total_cost_usd > 0,
  );
  const plottedSet = new Set(plotted.map((r) => r.run_id));
  const rail = nonSlice.filter((r) => !plottedSet.has(r.run_id));
  return { plotted, rail, slices, population: [...plotted, ...rail] };
}

/**
 * Whether a row's recorded cost is a lower bound. A run whose
 * family records priced fewer calls than they timed has
 * unpriced calls, so the recorded total understates the true
 * cost. Derived from the payload's own call counts; the old
 * board's cost spread carried the same fact as a greater-than
 * sign.
 */
export function costIsLowerBound(row: BoardRow): boolean {
  let costed = 0;
  let timed = 0;
  let seen = false;
  for (const fam of familiesOf(row).values()) {
    if (fam.nCostedCalls === null || fam.nLatencyCalls === null) {
      return false;
    }
    costed += fam.nCostedCalls;
    timed += fam.nLatencyCalls;
    seen = true;
  }
  return seen && costed < timed;
}

/** The cost state of a rail row, in the words the chart uses. */
export function railCostState(row: BoardRow): "recorded-zero" | "unrecorded" {
  return row.total_cost_usd !== null ? "recorded-zero" : "unrecorded";
}

/**
 * The log cost domain, snapped outward to the nearest half
 * decade of the plotted costs so the axis hugs the data
 * (census V-04, criteria DV-05). Returns [lo, hi] in dollars.
 */
export function costDomain(costs: number[]): [number, number] {
  const lo = Math.min(...costs);
  const hi = Math.max(...costs);
  const loD = Math.floor(Math.log10(lo) * 2) / 2;
  const hiD = Math.ceil(Math.log10(hi) * 2) / 2;
  return [10 ** loD, 10 ** hiD];
}

/* The label layout solvers live in lib/layout (pure, no
 * payload access) and are re-exported here for the server
 * components that have always imported them from this module. */
export {
  estimateLabelWidth,
  placeLabels,
  nudgePoints,
  type Rect,
  type LayoutPoint,
  type PlacedLabel,
} from "./layout";

/* ---------------- heatmap ---------------- */

/** Short column names, one line each (design spec 4.3). */
/* The phone heat chips carry their own label form (design
 * cycle 5, red team F5): a chip is wide enough for the fuller
 * "Crypto payload", so the noun the desktop header had to drop
 * is restored where space allows. Every other family uses its
 * header form. */
export const FAMILY_CHIP: Record<string, string> = {
  cryptographic_payload: "Crypto payload",
};

export const FAMILY_SHORT: Record<string, string> = {
  crosslingual_shift: "Crosslingual",
  cryptographic_payload: "Crypto",
  evidence_positioning: "Evidence",
  frequency_salience: "Frequency",
  question_pair_incoherence: "Question pair",
  retrieval_poisoning: "Retrieval",
  verbosity_inflation: "Verbosity",
  canary_leakage: "Canary",
  history_leakage: "History",
  judge_sycophancy: "Sycophancy",
  threshold_edge_hunting: "Threshold",
};

/** Full family names for tooltips and the method key. */
export function familyFullName(key: string): string {
  const words = key.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/**
 * Column order: descending mean family attack success across
 * the rows that carry the family, the spec's standing rule.
 * Ties break on the family key so the order is deterministic.
 */
export function familyOrder(rows: BoardRow[]): string[] {
  const sums = new Map<string, { total: number; n: number }>();
  for (const row of rows) {
    for (const [key, fam] of familiesOf(row)) {
      if (fam.asr === null) continue;
      const acc = sums.get(key) ?? { total: 0, n: 0 };
      acc.total += fam.asr;
      acc.n += 1;
      sums.set(key, acc);
    }
  }
  return [...sums.entries()]
    .map(([key, acc]) => ({ key, mean: acc.total / acc.n }))
    .sort((a, b) => b.mean - a.mean || (a.key < b.key ? -1 : 1))
    .map((e) => e.key);
}

/* The heat ramp. Single hue heat from ground to ember through
 * deep amber (design 4.3), interpolated in linear RGB between
 * stops, driven by a power curve of 0.65 so the low range where
 * the information lives separates. Green appears nowhere in it.
 * The final stop bends toward the semantic red because the
 * colour budget reserves red for the hottest cells.
 *
 * The stops carry one deliberate step, at the text flip. Cell
 * text is ground or ink-1, and those two tones are close
 * enough in luminance that a background exists (near 0.17)
 * against which neither reaches the 4.5 to 1 contrast floor
 * the criteria set as a blocker (CO-03). A continuous ramp
 * must pass through that band, so this ramp steps over it:
 * the stop at 0.55 holds luminance at 0.145 (ink-1 text clears
 * 4.6 to 1) and the second stop at the same parameter resumes
 * at 0.203 (ground text clears 4.7 to 1). Hue and ordering are
 * untouched, the step is a small brightness edge at mid scale,
 * and no cell colour lands in the band between. */
const RAMP_STOPS: [number, [number, number, number]][] = [
  [0.0, [0x16, 0x12, 0x0e]],
  [0.3, [0x57, 0x2a, 0x0e]],
  [0.55, [0x9e, 0x58, 0x16]],
  [0.55, [0xb2, 0x6b, 0x20]],
  [0.8, [0xd9, 0x8a, 0x26]],
  [1.0, [0xff, 0x8a, 0x3d]],
];

function srgbToLinear(c: number): number {
  const s = c / 255;
  return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
}
function linearToSrgb(l: number): number {
  const s = l <= 0.0031308 ? l * 12.92 : 1.055 * l ** (1 / 2.4) - 0.055;
  return Math.round(Math.min(1, Math.max(0, s)) * 255);
}
function luminance(rgb: [number, number, number]): number {
  return (
    0.2126 * srgbToLinear(rgb[0]) +
    0.7152 * srgbToLinear(rgb[1]) +
    0.0722 * srgbToLinear(rgb[2])
  );
}

export function rampRgb(value: number): [number, number, number] {
  const t = Math.pow(Math.min(1, Math.max(0, value)), 0.65);
  let i = 0;
  while (i < RAMP_STOPS.length - 2 && t > RAMP_STOPS[i + 1][0]) i++;
  const [t0, c0] = RAMP_STOPS[i];
  const [t1, c1] = RAMP_STOPS[i + 1];
  const f = t1 > t0 ? (t - t0) / (t1 - t0) : 0;
  return [0, 1, 2].map((ch) => {
    const a = srgbToLinear(c0[ch]);
    const b = srgbToLinear(c1[ch]);
    return linearToSrgb(a + (b - a) * f);
  }) as [number, number, number];
}

export function rampCss(value: number): string {
  const [r, g, b] = rampRgb(value);
  return `rgb(${r}, ${g}, ${b})`;
}

const INK: [number, number, number] = [0xe9, 0xee, 0xf3];
const GROUND: [number, number, number] = [0x0a, 0x0c, 0x0f];

export function contrastRatio(
  a: [number, number, number],
  b: [number, number, number],
): number {
  const la = luminance(a);
  const lb = luminance(b);
  const [hi, lo] = la >= lb ? [la, lb] : [lb, la];
  return (hi + 0.05) / (lo + 0.05);
}

/**
 * Cell text colour by the contrast rule. Design 3.3 flips cell
 * text between ground and ink-1 across the ramp; each cell
 * takes whichever of the two contrasts more against its ramp
 * colour. With the ramp's step at the flip (see RAMP_STOPS),
 * the better of the two always clears the 4.5 to 1 floor.
 */
export function rampTextIsGround(value: number): boolean {
  const bg = rampRgb(value);
  return contrastRatio(GROUND, bg) >= contrastRatio(INK, bg);
}

/**
 * A family rate as the heatmap prints it: whole percent, with
 * values above zero and below half a percent printing as <1.
 */
export function fmtCellPct(value: number): string {
  return fmtPctCell(value);
}

/* ---------------- calibration ---------------- */

export interface CalibRow {
  row: BoardRow;
  data: CalibrationData | null;
  isSlice: boolean;
}

/** All rows in attacked ECE order, the calibration order. */
export function calibrationRows(rows: BoardRow[]): CalibRow[] {
  const full = fullCaseCount(rows);
  return [...rows]
    .map((row) => ({
      row,
      data: calibrationOf(row),
      isSlice: isSliceRow(row, full),
    }))
    .sort((a, b) => {
      const ea = a.data?.ece ?? a.row.ece_attacked ?? Infinity;
      const eb = b.data?.ece ?? b.row.ece_attacked ?? Infinity;
      if (ea !== eb) return ea - eb;
      return a.row.display_name < b.row.display_name ? -1 : 1;
    });
}
