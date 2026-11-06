/**
 * Inspector data shaping. Runs on the server only, like
 * lib/compare and lib/scatterData. The inspector is the one
 * reading every surface gives a selected result (the ranking
 * zone, the models index, and the per-model pages' summary),
 * so its figures are shaped once here from the payload and
 * handed to the islands as plain data. Every value is a
 * payload field, a lib/format rendering of one, or one of
 * the decompositions and disclosure notes lib/payload
 * derives, carried so a flagged figure never travels alone
 * (C-5) and a no-answer disclosure never gets left behind.
 */

import {
  boardGroups,
  displayCi,
  duplicateShortNames,
  flipDecomposition,
  familyFlipDecomposition,
  modelSlug,
  shortName,
  singleCallErrorNote,
  taxBenchmarks,
  unansweredNote,
  wireWords,
  type BoardGroups,
  type BoardRow,
  type RankedRow,
} from "@/lib/payload";
import { fmtCi, fmtEce, fmtMs, fmtPct, fmtTax, fmtUsd } from "@/lib/format";
import { familiesOf, familyFullName, familyOrder } from "@/lib/charts";
import { axisPct } from "@/lib/chart";
import { costStateOf } from "@/lib/cards";
import { vendorOf } from "@/lib/vendor";
import { vendorFamilyOf } from "@/lib/vendorColors";

export type InspectorKind = "full" | "slice" | "flagged";

export interface InspectorMark {
  kind: "logo" | "mono";
  /** Sprite symbol key when the vendor publishes a mark. */
  slug: string | null;
  /** Monogram letter when it does not. */
  letter: string | null;
  /** The vendor label, the chip's accessible name. */
  label: string;
  /** The vendor family color, the chip's tint. */
  color: string;
}

export interface InspectorDatum {
  runId: string;
  slug: string;
  /** Short name, the name every board surface prints. */
  name: string;
  /** Wire words, present only when another result shares the short name. */
  wire: string | null;
  kind: InspectorKind;
  rank: number | null;
  /** The rank statement, stated once in the inspector's rank line. */
  rankLine: string;
  mark: InspectorMark;
  /** Vendor label plus the wire clause the sub line carries. */
  subLine: string;
  /**
   * The headline attack success figure. Null when the figure
   * is not stated on this surface: a flagged result whose
   * sealed records derive no decomposition (C-5 suppression).
   */
  asr: number | null;
  /**
   * True when this row is a flagged result whose counted rate
   * stands suppressed because its records derive no
   * decomposition. Carriers print the suppression marker where
   * the rate would stand, never a bare figure or a blank.
   */
  suppressed: boolean;
  asrText: string | null;
  /** The figure's label: counted, for a flagged result. */
  asrLabel: string;
  ci: [number, number] | null;
  ciText: string | null;
  /** Whisker geometry on the shared axis, percents of the track. */
  whisker: { lo: number; hi: number; pt: number } | null;
  benign: number | null;
  benignText: string | null;
  /** Benign bar geometry, percent of the 0 to 100 track. */
  benignPct: number | null;
  /** The field's best benign accuracy and who set it, when another result did. */
  benignBest: { name: string; text: string; pct: number } | null;
  malformed: number | null;
  malformedText: string | null;
  ece: number | null;
  eceText: string | null;
  tax: number | null;
  taxText: string | null;
  /** Median latency under attack, the payload's p50 figure. */
  latency: number | null;
  latencyText: string | null;
  /** The cost figure and its state words, from lib/cards' cost state. */
  costText: string;
  costSub: string | null;
  /** The flagged reason, with the decomposition clauses (C-5). */
  flaggedReason: string | null;
  /** The decomposition clauses alone, for carriers that state them apart. */
  decompText: string | null;
  /** The slice standing note. */
  sliceNote: string | null;
  /** The no-answer disclosures, verbatim from lib/payload. */
  unanswered: string | null;
  singleCall: string | null;
  /**
   * The weakest measured family, named with its rate. Null
   * when no family figure may print: no measured family, or
   * a flagged family whose decomposition does not derive.
   */
  weakestFamily: { name: string; text: string } | null;
  /** The result's own page. */
  href: string;
}

/* The wire clause for a result measured through an agent
 * harness: the sub line states the harness because the
 * harness is part of the measurement, the same fact the
 * point titles on the scatter state. Keyed by the recorded
 * wire, so a new harness wire earns its clause here rather
 * than at a render site. */
const WIRE_CLAUSE: Record<string, string> = {
  "cursor-harness": "measured through the Cursor agent harness",
};

export function markOf(row: BoardRow): InspectorMark {
  const vendor = vendorOf(row);
  const family = vendorFamilyOf(row);
  return {
    kind: vendor.kind,
    slug: vendor.kind === "logo" ? vendor.slug : null,
    letter: vendor.kind === "mono" ? vendor.letter : null,
    label: vendor.label,
    color: family.color,
  };
}

export function inspectorDatum(
  row: BoardRow,
  kind: InspectorKind,
  rank: number | null,
  groups: BoardGroups,
  allRows: BoardRow[],
  dupes: Set<string>,
  axisMax: number,
): InspectorDatum {
  const name = shortName(row);
  const dup = dupes.has(name);
  const mark = markOf(row);
  const clause = WIRE_CLAUSE[row.wire];
  const subLine = dup
    ? `${mark.label}, ${wireWords(row.wire)}`
    : clause
      ? `${mark.label}, ${clause}`
      : mark.label;
  const decomp = kind === "flagged" ? flipDecomposition(row) : null;
  const suppressed =
    kind === "flagged" && row.asr_conditional !== null && decomp === null;
  const asr = suppressed ? null : (row.asr_conditional ?? null);
  const ci = asr !== null ? displayCi(row) : null;
  const benchmarks = taxBenchmarks(groups);
  const isBestBenign =
    row.benign_accuracy !== null &&
    row.benign_accuracy !== undefined &&
    Math.abs(row.benign_accuracy - benchmarks.benignValue) < 1e-12 &&
    benchmarks.benignSetter === name;
  const cost = costStateOf(row);
  const costText =
    cost.kind === "amount"
      ? fmtUsd(cost.value)
      : cost.kind === "lower-bound"
        ? `≥ ${fmtUsd(cost.value)}`
        : cost.kind === "local"
          ? fmtUsd(0)
          : "·";
  /* A recorded zero is a run with no per-call API charge.
   * Its gloss follows the wire. A run measured through an
   * agent harness records zero because the harness's seat
   * carries no per-run charge, not because anything was
   * served locally, and the gloss must not claim it was. */
  const costSub =
    cost.kind === "lower-bound"
      ? "a lower bound, some calls went unpriced"
      : cost.kind === "local"
        ? clause
          ? `no per-run API charge, ${clause}`
          : "served locally, no API cost"
        : cost.kind === "unrecorded"
          ? "no cost recorded"
          : null;
  /* The weakest family, from the run's own family records.
   * A flagged result's family figures travel with their own
   * decompositions (C-5): a family whose records derive none
   * prints no figure here either, and cannot be named the
   * weakest. */
  const fams = familiesOf(row);
  const famDecomp =
    kind === "flagged" ? familyFlipDecomposition(row) : null;
  let weakest: { name: string; text: string } | null = null;
  let worst = -1;
  for (const key of familyOrder(allRows)) {
    const fam = fams.get(key);
    if (!fam || fam.asr === null) continue;
    if (famDecomp !== null && (famDecomp.get(key) ?? null) === null) continue;
    if (fam.asr > worst) {
      worst = fam.asr;
      weakest = { name: familyFullName(key), text: fmtPct(fam.asr) };
    }
  }
  const rankLine =
    kind === "flagged"
      ? "Flagged, not ranked"
      : kind === "slice"
        ? `Guard rank ${rank} of ${groups.slices.length}, abstain subset`
        : `Full-suite rank ${rank} of ${groups.full.length}`;
  return {
    runId: row.run_id,
    slug: modelSlug(row, allRows),
    name,
    wire: dup ? wireWords(row.wire) : null,
    kind,
    rank,
    rankLine,
    mark,
    subLine,
    asr,
    suppressed,
    asrText: asr !== null ? fmtPct(asr) : null,
    asrLabel:
      kind === "flagged" ? "Counted attack success" : "Attack success",
    ci,
    ciText: ci !== null ? fmtCi(ci) : null,
    whisker:
      asr !== null && ci !== null
        ? {
            lo: axisPct(ci[0], axisMax),
            hi: axisPct(ci[1], axisMax),
            pt: axisPct(asr, axisMax),
          }
        : null,
    benign: row.benign_accuracy ?? null,
    benignText:
      row.benign_accuracy != null ? fmtPct(row.benign_accuracy) : null,
    benignPct:
      row.benign_accuracy != null ? row.benign_accuracy * 100 : null,
    benignBest:
      row.benign_accuracy != null && !isBestBenign
        ? {
            name: benchmarks.benignSetter,
            text: fmtPct(benchmarks.benignValue),
            pct: benchmarks.benignValue * 100,
          }
        : null,
    malformed: row.malformed_rate ?? null,
    malformedText:
      row.malformed_rate != null ? fmtPct(row.malformed_rate) : null,
    ece: row.ece_attacked ?? null,
    eceText: row.ece_attacked != null ? fmtEce(row.ece_attacked) : null,
    tax: row.robustness_tax ?? null,
    taxText: row.robustness_tax != null ? fmtTax(row.robustness_tax) : null,
    latency: row.latency_ms_p50_attacked ?? null,
    latencyText:
      row.latency_ms_p50_attacked != null
        ? fmtMs(row.latency_ms_p50_attacked)
        : null,
    costText,
    costSub,
    flaggedReason:
      kind === "flagged" && row.malformed_rate != null
        ? `Its malformed response rate of ${fmtPct(row.malformed_rate)} is over the 5 percent admission limit, so it keeps every number and is not ranked.${
            decomp !== null
              ? ` Genuine flip rate ${fmtPct(decomp.genuineRate)}, with ${fmtPct(decomp.malformedShare)} of counted flips to malformed output.`
              : ""
          }`
        : null,
    decompText:
      kind === "flagged" && decomp !== null
        ? `genuine flip rate ${fmtPct(decomp.genuineRate)}, with ${fmtPct(decomp.malformedShare)} of counted flips to malformed output`
        : null,
    sliceNote:
      kind === "slice"
        ? "A guardrail slice result, measured on the abstain subset rather than the full suite, so its rates are not comparable to full suite results."
        : null,
    unanswered: unansweredNote(row),
    singleCall: singleCallErrorNote(row),
    weakestFamily: weakest,
    href: `/models/${modelSlug(row, allRows)}/`,
  };
}

/** Every result's inspector datum, keyed by run id. */
export function inspectorDataAll(axisMax: number): {
  groups: BoardGroups;
  allRows: BoardRow[];
  byRunId: Map<string, InspectorDatum>;
} {
  const groups = boardGroups();
  const allRows: BoardRow[] = [
    ...groups.full,
    ...groups.slices,
    ...groups.flagged,
  ];
  const dupes = duplicateShortNames(allRows);
  const byRunId = new Map<string, InspectorDatum>();
  for (const row of groups.full as RankedRow[]) {
    byRunId.set(
      row.run_id,
      inspectorDatum(row, "full", row.rank, groups, allRows, dupes, axisMax),
    );
  }
  for (const row of groups.slices as RankedRow[]) {
    byRunId.set(
      row.run_id,
      inspectorDatum(row, "slice", row.rank, groups, allRows, dupes, axisMax),
    );
  }
  for (const row of groups.flagged) {
    byRunId.set(
      row.run_id,
      inspectorDatum(row, "flagged", null, groups, allRows, dupes, axisMax),
    );
  }
  return { groups, allRows, byRunId };
}
