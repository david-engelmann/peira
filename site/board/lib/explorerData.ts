/**
 * Explorer data shaping, server side. The explorer island receives
 * one plain record per result, shaped once here from the payload
 * through the board's own data layer, so the browser never
 * re-derives a metric differently from the server surfaces. Every
 * value is a payload field, a lib/format rendering of one, or one
 * of the decompositions and disclosure notes lib/payload derives.
 */

import {
  boardGroups,
  familyFlipDecomposition,
  flipDecomposition,
  taxBenchmarks,
  type BoardRow,
} from "@/lib/payload";
import { fmtEce, fmtInt, fmtPct } from "@/lib/format";
import { vendorFamilyOf } from "@/lib/vendorColors";
import { asrAxisFor } from "@/lib/chart";
import {
  calibrationOf,
  familiesOf,
  familyFullName,
  familyOrder,
  FAMILY_SHORT,
} from "@/lib/charts";
import { provenanceOf, runDateWords, severitiesOf } from "@/lib/cards";
import { inspectorDataAll, type InspectorDatum } from "@/lib/inspectorData";

export interface XFamily {
  key: string;
  short: string;
  full: string;
  asr: number | null;
  /**
   * The family's own flip decomposition, for a flagged result
   * whose records derive one (C-5 at family scope). A flagged
   * family whose records derive none is suppressed instead, and
   * prints no figure on any surface.
   */
  decomp: { genuineText: string; shareText: string } | null;
  suppressed: boolean;
}

export interface XRow {
  runId: string;
  slug: string;
  name: string;
  /** Wire in words, present only when another result shares the name. */
  wire: string | null;
  wireRaw: string;
  kind: "full" | "slice" | "flagged";
  /** Rank within the row's own population, null on flagged rows. */
  popRank: number | null;
  /** A flagged row whose counted rate stands suppressed (C-5). */
  suppressed: boolean;
  /** The counted flips line, composed here so every surface
   *  and the prose census read the same words. */
  decompLine: string | null;
  /** The weakest family sentence, composed here on the same rule. */
  weakestLine: string | null;
  /** The benign benchmark sub-line, composed here on the same rule. */
  benignBestLine: string | null;
  mark: InspectorDatum["mark"] & { glyph: string };
  subLine: string;
  rankLine: string;
  asr: number | null;
  asrText: string | null;
  asrLabel: string;
  ciText: string | null;
  ci: [number, number] | null;
  /** Whisker geometry as percents of the shared axis track. */
  whisker: { lo: number; hi: number; pt: number } | null;
  benign: number | null;
  benignText: string | null;
  /** The benign benchmark that frames the figure, when another result set it. */
  benignBest: { name: string; text: string } | null;
  malformed: number | null;
  malformedText: string | null;
  ece: number | null;
  eceText: string | null;
  taxText: string | null;
  /** The tax benchmarks sentence, on full suite rows that carry a tax. */
  taxBenchLine: string | null;
  latencyText: string | null;
  costValue: number | null;
  costText: string;
  costSub: string | null;
  vendorKey: string;
  vendorLabel: string;
  /** Counted flips and their split, where the records derive one. */
  decomp: {
    flips: number;
    malformedFlips: number;
    malformedShare: number;
    genuineRate: number;
  } | null;
  families: XFamily[];
  weakestFamily: { name: string; text: string } | null;
  severities: Array<{ label: string; flipText: string | null; baseText: string | null }>;
  calibration: {
    eceText: string;
    brierText: string;
    bins: Array<{ x: number; y: number; n: number }>;
  } | null;
  provenanceLine: string;
  rerunText: string | null;
  flaggedReason: string | null;
  sliceNote: string | null;
  unanswered: string | null;
  singleCall: string | null;
  nCases: number;
  nEligible: number;
}

export interface ExplorerData {
  rows: XRow[];
  familyKeys: string[];
  familyNames: Record<string, string>;
  axisMax: number;
  /** The shared axis top for every family bar on the board. */
  familiesAxis: number;
  fullCount: number;
  guardCount: number;
  flaggedCount: number;
  guardCases: number;
  /** The full suite's case count, the guard subset's base. */
  fullCases: number;
  /** The guard basis statement, composed once here. */
  guardBasis: string;
  /**
   * The flag line for the chart's malformed measure. The
   * highest malformed rate among the ranked rows, full suite
   * and slices alike. Every flagged result stands past it.
   */
  flagLine: number;
  /** Vendor filter options, in payload order of first appearance. */
  vendors: Array<{ key: string; label: string }>;
}

/** The guard basis statement (BUILD-SPEC part 4), composed
 *  once here so the surface and the prose census read the
 *  same words. */
export function guardBasisLine(guardCases: number, fullCases: number): string {
  return (
    `Guard results ran the ${fmtInt(guardCases)} case abstain subset ` +
    `of the suite's ${fmtInt(fullCases)} cases. They are ranked among ` +
    `themselves on that basis, and their rates do not compare with ` +
    `full suite rates.`
  );
}

/** The filter count line, composed once here on the same rule. */
export function countLineText(
  showing: number,
  total: number,
  hidden: number,
  brushOn: boolean,
): string {
  return (
    `Showing ${fmtInt(showing)} of ${fmtInt(total)} results` +
    (hidden > 0 ? ` · ${fmtInt(hidden)} hidden by filters` : "") +
    (brushOn ? " · brush filter on" : "")
  );
}

/** The group dividers inside the all results view. */
export const GUARD_DIVIDER =
  "Guard results · ranked among themselves on the abstain subset basis";
export const FLAGGED_DIVIDER = "Flagged results · held off the ranking";

/** The empty states of the rank and chart views. */
export const EMPTY_RANK_TEXT =
  "No result matches these filters. Loosen one and the board comes back.";
export const EMPTY_CHART_TEXT =
  "No result matches these filters, so the chart has nothing to show.";

/** The chart's rail note, in its two forms. */
export function railNoteText(hasGuards: boolean): string {
  return hasGuards
    ? "Guard results stand here on their abstain subset basis. The rest carry no recorded cost and stand off the axis, not at zero."
    : "These results carry no recorded serving cost, so they stand off the axis rather than at zero.";
}

/** The off scale note for one result past the shared axis,
 *  with its decomposition in the same unit where one derives. */
export function offScaleNoteText(row: XRow): string {
  return (
    `▲ ${row.name} plots above the shared axis at ${row.asrText} counted.` +
    (row.decomp
      ? ` Malformed output is ${fmtPct(row.decomp.malformedShare)} of its counted flips, and its genuine flip rate is ${fmtPct(row.decomp.genuineRate)}.`
      : "")
  );
}

/** The flag line's label on the chart's malformed measure. */
export function flagLineLabelText(value: number): string {
  return `Flag line · the ranked board's highest malformed rate ${fmtPct(value)}`;
}

/** The note standing under the malformed measure for the
 *  extreme flagged result, its decomposition in the same unit.
 *  Null where the result derives no decomposition, in which
 *  case no note may stand for it. */
export function flagNoteText(row: XRow): string | null {
  if (row.decomp === null) return null;
  return (
    `▲ ${row.name} stands past the flag line at ${row.malformedText} ` +
    `malformed output. Malformed output is ${fmtPct(row.decomp.malformedShare)} ` +
    `of its counted flips, and its genuine flip rate is ${fmtPct(row.decomp.genuineRate)}.`
  );
}

function shapeRow(
  row: BoardRow,
  datum: InspectorDatum,
  famOrder: string[],
  taxBenchLine: string | null,
): XRow {
  const fams = familiesOf(row);
  const decomp = flipDecomposition(row);
  const famDecomp =
    datum.kind === "flagged" ? familyFlipDecomposition(row) : null;
  const cal = calibrationOf(row);
  const prov = provenanceOf(row);
  const provParts = [
    prov.adapterName,
    `run ${runDateWords(row)}`,
    prov.manifestSha256 ? `manifest ${prov.manifestSha256.slice(0, 12)}…` : null,
  ].filter((p): p is string => p !== null && p !== "");
  return {
    runId: row.run_id,
    slug: datum.slug,
    name: datum.name,
    wire: datum.wire,
    wireRaw: row.wire,
    kind: datum.kind,
    popRank: datum.rank,
    suppressed: datum.suppressed,
    decompLine:
      decomp === null
        ? null
        : `${fmtInt(decomp.flips)} counted flips · ${fmtInt(decomp.malformedFlips)} to malformed output · genuine flip rate ${fmtPct(decomp.genuineRate)}`,
    weakestLine:
      datum.weakestFamily === null
        ? null
        : `Weakest family ${datum.weakestFamily.name} at ${datum.weakestFamily.text}.`,
    benignBestLine:
      datum.benignBest === null
        ? null
        : `${datum.benignBest.name} marks the best at ${datum.benignBest.text}`,
    mark: { ...datum.mark, glyph: vendorFamilyOf(row).glyph },
    subLine: datum.subLine,
    rankLine: datum.rankLine,
    asr: datum.asr,
    asrText: datum.asrText,
    asrLabel: datum.asrLabel,
    ciText: datum.ciText,
    ci: datum.ci,
    whisker: datum.whisker,
    benign: datum.benign,
    benignText: datum.benignText,
    benignBest:
      datum.benignBest !== null
        ? { name: datum.benignBest.name, text: datum.benignBest.text }
        : null,
    malformed: datum.malformed,
    malformedText: datum.malformedText,
    ece: datum.ece,
    eceText: datum.eceText,
    taxText: datum.taxText,
    taxBenchLine: datum.kind === "full" && datum.taxText !== null ? taxBenchLine : null,
    latencyText: datum.latencyText,
    costValue: row.total_cost_usd,
    costText: datum.costText,
    costSub: datum.costSub,
    vendorKey: vendorFamilyOf(row).key,
    vendorLabel: vendorFamilyOf(row).label,
    decomp:
      decomp === null
        ? null
        : {
            flips: decomp.flips,
            malformedFlips: decomp.malformedFlips,
            malformedShare: decomp.malformedShare,
            genuineRate: decomp.genuineRate,
          },
    families: famOrder.map((key) => {
      const famAsr = fams.get(key)?.asr ?? null;
      const fd = famDecomp !== null ? (famDecomp.get(key) ?? null) : null;
      return {
        key,
        short: FAMILY_SHORT[key] ?? familyFullName(key),
        full: familyFullName(key),
        asr: famAsr,
        decomp:
          fd !== null
            ? {
                genuineText: fmtPct(fd.genuineRate),
                shareText: fmtPct(fd.malformedShare),
              }
            : null,
        suppressed: famDecomp !== null && famAsr !== null && fd === null,
      };
    }),
    weakestFamily: datum.weakestFamily,
    severities: severitiesOf(row).map((s) => ({
      label: s.label,
      flipText: s.flipRate !== null ? fmtPct(s.flipRate) : null,
      baseText:
        s.nEligible !== null ? `${s.nEligible.toLocaleString("en-US")} eligible` : null,
    })),
    calibration:
      cal === null || cal.bins.length === 0
        ? null
        : {
            eceText: cal.ece !== null ? fmtEce(cal.ece) : "·",
            brierText: cal.brier !== null ? fmtEce(cal.brier) : "·",
            bins: cal.bins.map((b) => ({
              x: b.meanForecast,
              y: b.meanOutcome,
              n: b.n,
            })),
          },
    provenanceLine: provParts.join(" · "),
    rerunText:
      row.rerun != null
        ? `This result rests on a re-run segment recorded on ${row.rerun.date}. Its figures are the segment's own.`
        : null,
    flaggedReason: datum.flaggedReason,
    sliceNote: datum.sliceNote,
    unanswered: datum.unanswered,
    singleCall: datum.singleCall,
    nCases: row.n_cases,
    nEligible: row.n_eligible,
  };
}

export function explorerData(): ExplorerData {
  const groups = boardGroups();
  const worst = Math.max(
    ...groups.full.map((r) => r.asr_conditional ?? 0),
    ...groups.slices.map((r) => r.asr_conditional ?? 0),
  );
  const axis = asrAxisFor(worst);
  const { allRows, byRunId } = inspectorDataAll(axis.max);
  const famOrder = familyOrder(allRows);
  const benchmarks = taxBenchmarks(groups);
  const taxBenchLine =
    `Tax benchmarks over the full suite. Benign accuracy ` +
    `${fmtPct(benchmarks.benignValue)} set by ${benchmarks.benignSetter}, ` +
    `attacked calibration error ${fmtEce(benchmarks.eceValue)} set by ` +
    `${benchmarks.eceSetter}.`;
  const rows = allRows.map((row) =>
    shapeRow(row, byRunId.get(row.run_id) as InspectorDatum, famOrder, taxBenchLine),
  );
  const maxFam = Math.max(
    0.05,
    ...rows.flatMap((r) => r.families.map((f) => f.asr ?? 0)),
  );
  const familiesAxis = Math.ceil(maxFam * 10) / 10;
  const vendors: Array<{ key: string; label: string }> = [];
  const seen = new Set<string>();
  for (const row of rows) {
    if (!seen.has(row.vendorKey)) {
      seen.add(row.vendorKey);
      vendors.push({ key: row.vendorKey, label: row.vendorLabel });
    }
  }
  return {
    rows,
    familyKeys: famOrder,
    familyNames: Object.fromEntries(
      famOrder.map((k) => [k, familyFullName(k)]),
    ),
    axisMax: axis.max,
    familiesAxis,
    fullCount: groups.full.length,
    guardCount: groups.slices.length,
    flaggedCount: groups.flagged.length,
    guardCases: groups.slices[0]?.n_cases ?? 0,
    fullCases: groups.fullCases,
    guardBasis: guardBasisLine(
      groups.slices[0]?.n_cases ?? 0,
      groups.fullCases,
    ),
    flagLine: Math.max(
      0,
      ...rows
        .filter((r) => r.kind !== "flagged")
        .map((r) => r.malformed ?? 0),
    ),
    vendors,
  };
}
