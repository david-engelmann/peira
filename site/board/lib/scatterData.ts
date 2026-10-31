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
import { asrAxisFor, type AsrAxis } from "@/lib/chart";

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

/** One derived reading for the section's summary strip. */
export interface ScatterReading {
  label: string;
  asr: number | null;
  /** The cost clause in words, from the row's own cost state. */
  costText: string;
  /**
   * The cost clause phrased to follow a name in a sentence
   * ("at $12.34 per run", "with no cost recorded"). Structured
   * here, from the row's cost state, never re-derived from
   * costText by string surgery at the render site.
   */
  costPhrase: string;
}

export interface ScatterData {
  plotted: ScatterDatum[];
  rail: ScatterDatum[];
  domain: [number, number];
  /** The shared axis, derived from the ranked population. */
  axis: AsrAxis;
  populationCount: number;
  plottedCount: number;
  railCount: number;
  sliceCount: number;
  zeroNames: string[];
  noneNames: string[];
  /** Labels of charted results whose rate sits above the axis. */
  aboveScaleNames: string[];
  /**
   * The section's two readings, computed from the payload at
   * build time (hardcode audit F1, F2): the priciest run and
   * whether it is also the ranked result that flipped most,
   * the toughest ranked result, and the cheapest charted run.
   * No name, price or claim is written into the section's
   * source; the strip prints only what these carry.
   */
  readings: {
    priciest: ScatterReading;
    mostFlippedRanked: ScatterReading;
    toughestRanked: ScatterReading;
    cheapest: ScatterReading;
    priciestIsMostFlipped: boolean;
    /**
     * The scope phrase for the ranked superlatives ("on the
     * full suite"), assembled at the derivation site from
     * the groups the ranked derivation consumed. The strip
     * prints it inside each ranked claim, so a claim never
     * reads board-wide while its figures derive over one
     * population.
     */
    rankedScope: string;
  };
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
  /* The shared axis derives from the ranked population:
   * the worst ranked rate across the full suite and the
   * slices, rounded up a step (lib/chart). */
  const rankedRates = [...groups.full, ...groups.slices]
    .map((r) => r.asr_conditional)
    .filter((v): v is number => v !== null && v !== undefined);
  const axis = asrAxisFor(rankedRates.length ? Math.max(...rankedRates) : 0);
  const railIds = new Set(sets.rail.map((r) => r.run_id));
  const costPhrase = (row: BoardRow, rail: boolean): string => {
    if (rail) {
      return railCostState(row) === "recorded-zero"
        ? "with a recorded cost of $0.00"
        : "with no cost recorded";
    }
    const cost = fmtUsdExact(row.total_cost_usd!);
    return costIsLowerBound(row)
      ? `at ${cost} per run, a lower bound`
      : `at ${cost} per run`;
  };
  const reading = (row: BoardRow): ScatterReading => ({
    label: labelFor(row, dupes),
    asr: row.asr_conditional ?? null,
    costText: costClause(row, railIds.has(row.run_id)),
    costPhrase: costPhrase(row, railIds.has(row.run_id)),
  });
  const byAsr = (a: BoardRow, b: BoardRow) =>
    (a.asr_conditional ?? 0) - (b.asr_conditional ?? 0);
  /* The ranked derivation's input, named segment by
   * segment. The ranked superlatives below derive over
   * these segments and nothing else, while ranked
   * guardrail slices sit lower on this payload, so the
   * printed claims are scoped to the population the
   * derivation consumed. The scope phrase reads the
   * segments back, each named by its standing group
   * words, so the words track the derivation if its
   * population ever grows. No group key is written at
   * the phrase's call site. */
  const rankedSegments: Array<{
    group: "full" | "slices";
    rows: BoardRow[];
  }> = [{ group: "full", rows: groups.full }];
  const fullRanked = rankedSegments.flatMap((s) => s.rows).sort(byAsr);
  const scopePhraseFor = (consumed: Array<"full" | "slices">): string => {
    const words = consumed.map((g) =>
      g === "full" ? "the full suite" : "the guardrail slices",
    );
    return `on ${words.join(" and ")}`;
  };
  const rankedScope = scopePhraseFor(rankedSegments.map((s) => s.group));
  const priciestRow = sets.plotted.reduce((a, b) =>
    (b.total_cost_usd ?? 0) > (a.total_cost_usd ?? 0) ? b : a,
  );
  const cheapestRow = sets.plotted.reduce((a, b) =>
    (b.total_cost_usd ?? Infinity) < (a.total_cost_usd ?? Infinity) ? b : a,
  );
  const mostFlippedRankedRow = fullRanked[fullRanked.length - 1];
  const readings = {
    priciest: reading(priciestRow),
    mostFlippedRanked: reading(mostFlippedRankedRow),
    toughestRanked: reading(fullRanked[0]),
    cheapest: reading(cheapestRow),
    priciestIsMostFlipped: priciestRow.run_id === mostFlippedRankedRow.run_id,
    rankedScope,
  };
  const aboveScaleNames = sets.population
    .filter((r) => (r.asr_conditional ?? 0) > axis.max)
    .map((r) => labelFor(r, dupes));
  return {
    plotted: sets.plotted.map((r) => shape(r, false, dupes)),
    rail: sets.rail.map((r) => shape(r, true, dupes)),
    domain: costDomain(sets.plotted.map((r) => r.total_cost_usd!)),
    axis,
    aboveScaleNames,
    readings,
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
