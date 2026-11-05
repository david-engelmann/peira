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
  flipDecomposition,
  type BoardRow,
} from "@/lib/payload";
import { fmtEce, fmtPct } from "@/lib/format";
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
  mark: InspectorDatum["mark"];
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
  malformed: number | null;
  malformedText: string | null;
  ece: number | null;
  eceText: string | null;
  taxText: string | null;
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
  fullCount: number;
  guardCount: number;
  flaggedCount: number;
  guardCases: number;
  /** Vendor filter options, in payload order of first appearance. */
  vendors: Array<{ key: string; label: string }>;
}

function shapeRow(
  row: BoardRow,
  datum: InspectorDatum,
  famOrder: string[],
): XRow {
  const fams = familiesOf(row);
  const decomp = flipDecomposition(row);
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
    mark: datum.mark,
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
    malformed: datum.malformed,
    malformedText: datum.malformedText,
    ece: datum.ece,
    eceText: datum.eceText,
    taxText: datum.taxText,
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
    families: famOrder.map((key) => ({
      key,
      short: FAMILY_SHORT[key] ?? familyFullName(key),
      full: familyFullName(key),
      asr: fams.get(key)?.asr ?? null,
    })),
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
  const byId = new Map(allRows.map((r) => [r.run_id, r]));
  const rows = allRows.map((row) =>
    shapeRow(row, byRunId.get(row.run_id) as InspectorDatum, famOrder),
  );
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
    fullCount: groups.full.length,
    guardCount: groups.slices.length,
    flaggedCount: groups.flagged.length,
    guardCases: groups.slices[0]?.n_cases ?? 0,
    vendors,
  };
}
