/**
 * Scatter data shaping (redesign). Runs on the server only,
 * like lib/compare. The client island receives this compact
 * point set as props, so the payload JSON never enters a
 * client bundle; every value is a payload field copied across
 * or a label derived from one by the standing name rules.
 */

import {
  boardGroups,
  boardDateWords,
  boardVersions,
  shortName,
  wireWords,
  displayCi,
  flipDecomposition,
  duplicateShortNames,
  type BoardRow,
  type FlipDecomposition,
} from "@/lib/payload";
import { fmtPct, fmtUsdExact } from "@/lib/format";
import {
  scatterSets,
  costIsLowerBound,
  railCostState,
  costDomain,
} from "@/lib/charts";
import { vendorOf, type VendorMark } from "@/lib/vendor";
import { vendorFamilyOf } from "@/lib/vendorColors";

export interface ScatterDatum {
  runId: string;
  /** The in-place label, with the wire words when the name is shared. */
  label: string;
  /** The point's full title, for the native tooltip and aria label. */
  title: string;
  asr: number;
  ci: [number, number] | null;
  benign: number | null;
  /** Recorded cost, null when no cost was recorded. */
  cost: number | null;
  lowerBound: boolean;
  rail: boolean;
  flagged: boolean;
  /**
   * The C-5 decomposition of a flagged point's figure, derived
   * by lib/payload's flipDecomposition; null for ranked points
   * and for flagged points whose sealed records do not derive
   * one, whose figures then print nowhere on the scatter.
   */
  decomp: FlipDecomposition | null;
  /** The row's malformed response rate, for the detail card of
   *  a flagged point whose figure is not stated. */
  malformedRate: number | null;
  /** Vendor family color and the ink that reads on it. */
  color: string;
  glyph: string;
  /** Brand mark path key, or null when the vendor publishes none. */
  logoSlug: string | null;
  /** Monogram letter when there is no brand mark. */
  monoLetter: string | null;
}

export interface ScatterData {
  plotted: ScatterDatum[];
  rail: ScatterDatum[];
  domain: [number, number];
  populationCount: number;
  plottedCount: number;
  railCount: number;
  sliceCount: number;
  zeroNames: string[];
  noneNames: string[];
  dataset: string;
  updated: string;
}

function labelFor(row: BoardRow, dupes: Set<string>): string {
  const name = shortName(row);
  return dupes.has(name) ? `${name} (${wireWords(row.wire)})` : name;
}

function costClause(row: BoardRow, rail: boolean): string {
  if (rail) {
    return railCostState(row) === "recorded-zero"
      ? "recorded cost $0.00"
      : "no cost recorded";
  }
  const cost = fmtUsdExact(row.total_cost_usd!);
  return costIsLowerBound(row)
    ? `recorded cost ${cost} per run, a lower bound`
    : `recorded cost ${cost} per run`;
}

function pointTitle(
  row: BoardRow,
  rail: boolean,
  decomp: FlipDecomposition | null,
): string {
  const name = shortName(row);
  const cost = costClause(row, rail);
  if (!row.ranking_eligible) {
    /* A flagged point's figure travels only with its
     * decomposition (C-5); where the sealed records do not
     * derive one, the title states the standing and no figure. */
    if (decomp) {
      return `${name}, attack success ${fmtPct(row.asr_conditional!)}, genuine flip rate ${fmtPct(decomp.genuineRate)}, with ${fmtPct(decomp.malformedShare)} of counted flips to malformed output, ${cost}`;
    }
    return `${name}, flagged and not ranked, ${cost}`;
  }
  return `${name}, attack success ${fmtPct(row.asr_conditional!)}, ${cost}`;
}

function shape(row: BoardRow, rail: boolean, dupes: Set<string>): ScatterDatum {
  const family = vendorFamilyOf(row);
  const vendor: VendorMark = vendorOf(row);
  const decomp = row.ranking_eligible ? null : flipDecomposition(row);
  return {
    runId: row.run_id,
    label: labelFor(row, dupes),
    title: pointTitle(row, rail, decomp),
    asr: row.asr_conditional!,
    ci: displayCi(row),
    benign: row.benign_accuracy ?? null,
    cost: row.total_cost_usd ?? null,
    lowerBound: rail ? false : costIsLowerBound(row),
    rail,
    flagged: !row.ranking_eligible,
    decomp,
    malformedRate: row.malformed_rate ?? null,
    color: family.color,
    glyph: family.glyph,
    logoSlug: vendor.kind === "logo" ? vendor.slug : null,
    monoLetter: vendor.kind === "mono" ? vendor.letter : null,
  };
}

export function scatterData(): ScatterData {
  const groups = boardGroups();
  const allRows = [...groups.full, ...groups.slices, ...groups.flagged];
  const dupes = duplicateShortNames(allRows);
  const sets = scatterSets(allRows);
  const versions = boardVersions();
  return {
    plotted: sets.plotted.map((r) => shape(r, false, dupes)),
    rail: sets.rail.map((r) => shape(r, true, dupes)),
    domain: costDomain(sets.plotted.map((r) => r.total_cost_usd!)),
    populationCount: sets.population.length,
    plottedCount: sets.plotted.length,
    railCount: sets.rail.length,
    sliceCount: sets.slices.length,
    zeroNames: sets.rail
      .filter((r) => railCostState(r) === "recorded-zero")
      .map((r) => shortName(r)),
    noneNames: sets.rail
      .filter((r) => railCostState(r) === "unrecorded")
      .map((r) => shortName(r)),
    dataset: versions.dataset,
    updated: boardDateWords(),
  };
}
