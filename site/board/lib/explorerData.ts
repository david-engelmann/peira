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
  splitDisplayName,
  type BoardRow,
} from "@/lib/payload";
import { fmtEce, fmtPct } from "@/lib/format";
import { vendorFamilyOf } from "@/lib/vendorColors";
import { asrAxisFor, axisPct } from "@/lib/chart";
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
  /** The full display name, organisation prefix kept, only the
   * pinned revision hash split out. The ladder prints this. */
  fullName: string;
  /** Wire in words, present only when another result shares the name. */
  wire: string | null;
  wireRaw: string;
  kind: "full" | "slice" | "flagged";
  /** Rank within the row's own population, null on flagged rows. */
  popRank: number | null;
  mark: InspectorDatum["mark"] & { glyph: string };
  subLine: string;
  rankLine: string;
  asr: number | null;
  asrText: string | null;
  asrLabel: string;
  ciText: string | null;
  ci: [number, number] | null;
  /** Whisker geometry as percents of the row's axis track.
   * Ranked rows (full suite and guards) stand on an axis
   * fitted to the ranked population's interval tops, so
   * their intervals read as bars rather than dots. Flagged
   * rows keep the shared axis, the frame their off-scale
   * figures are stated against. */
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
  costKind: InspectorDatum["costKind"];
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
  weakestFamily: { name: string; text: string; baseText: string | null } | null;
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

/* The ranked interval axis. The ranked populations' own
 * interval tops set the frame, rounded up to the next two
 * and a half percent step, with the board's standing 0.3
 * floor. It is derived from the payload on every build, so
 * a tougher ranked population grows the frame a step and
 * every interval still sits at its true position. Flagged
 * intervals stay on the shared axis in lib/inspectorData,
 * which is computed once over all three populations. */
const RANKED_AXIS_STEP = 0.025;
const RANKED_AXIS_FLOOR = 0.3;

export function rankedIntervalAxisMax(
  datums: Iterable<InspectorDatum>,
): number {
  let top = 0;
  for (const d of datums) {
    if (d.kind === "flagged" || d.ci === null) continue;
    top = Math.max(top, d.ci[1]);
  }
  const stepped =
    Math.ceil((top - 1e-9) / RANKED_AXIS_STEP) * RANKED_AXIS_STEP;
  return Math.max(RANKED_AXIS_FLOOR, Math.round(stepped * 1000) / 1000);
}

function shapeRow(
  row: BoardRow,
  datum: InspectorDatum,
  famOrder: string[],
  rankedAxisMax: number,
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
    fullName: splitDisplayName(row.display_name).name,
    wire: datum.wire,
    wireRaw: row.wire,
    kind: datum.kind,
    popRank: datum.rank,
    mark: { ...datum.mark, glyph: vendorFamilyOf(row).glyph },
    subLine: datum.subLine,
    rankLine: datum.rankLine,
    asr: datum.asr,
    asrText: datum.asrText,
    asrLabel: datum.asrLabel,
    ciText: datum.ciText,
    ci: datum.ci,
    whisker:
      datum.kind !== "flagged" && datum.ci !== null && datum.asr !== null
        ? {
            lo: axisPct(datum.ci[0], rankedAxisMax),
            hi: axisPct(datum.ci[1], rankedAxisMax),
            pt: axisPct(datum.asr, rankedAxisMax),
          }
        : datum.whisker,
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
    costKind: datum.costKind,
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
        ? `This result was recorded again after an earlier run, on ${row.rerun.date}. Its figures are the later recording's own.`
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
  const rankedAxisMax = rankedIntervalAxisMax(byRunId.values());
  const famOrder = familyOrder(allRows);
  const byId = new Map(allRows.map((r) => [r.run_id, r]));
  const rows = allRows.map((row) =>
    shapeRow(
      row,
      byRunId.get(row.run_id) as InspectorDatum,
      famOrder,
      rankedAxisMax,
    ),
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
