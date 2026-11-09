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
import { costStateOf, type CostState } from "@/lib/cards";
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
  /** The cost state kind, so grouped surfaces keep the states apart. */
  costKind: CostState["kind"];
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

/* The short cost label for a harness run names the plan the
 * run drew on, and the long gloss states the billing fact in
 * full. A harness run is not chargeless. Its cost is billed
 * through the plan that carries the harness, so the board
 * prints the plan basis and never a figure for it. Keyed by
 * the recorded wire, beside the clause, so a new harness
 * wire earns both here rather than at a render site. */
const HARNESS_PLAN_LABEL: Record<string, string> = {
  "cursor-harness": "Cursor plan",
};

const HARNESS_COST_SUB: Record<string, string> = {
  "cursor-harness":
    "Measured through the Cursor agent harness. The run drew on a paid Cursor plan, so the cost is real and not metered per run.",
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
  /* A cost prints as a dollar figure only when it is a price.
   * A recorded zero is never one on this board. A harness run
   * prints the plan it drew on, a local run prints that it
   * carries no API cost, and an unrecorded cost prints as
   * unrecorded. No surface downstream of this derivation can
   * turn any of the three back into $0.00. */
  const costText =
    cost.kind === "amount"
      ? fmtUsd(cost.value)
      : cost.kind === "lower-bound"
        ? `≥ ${fmtUsd(cost.value)}`
        : cost.kind === "harness"
          ? (HARNESS_PLAN_LABEL[row.wire] ?? "Harness plan")
          : cost.kind === "local"
            ? "No API cost"
            : "No cost recorded";
  /* The harness gloss is the full sentence, stated once here
   * so the reading and every detail surface carry the same
   * words. It is keyed by the run's recorded wire, so the
   * harness and the plan named are the ones the payload
   * records for the run. */
  const costSub =
    cost.kind === "lower-bound"
      ? "a lower bound, some calls went unpriced"
      : cost.kind === "harness"
        ? (HARNESS_COST_SUB[row.wire] ??
          "Measured through an agent harness on a paid plan. The cost is real and not metered per run.")
        : cost.kind === "local"
          ? "served locally, no API cost"
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
    costKind: cost.kind,
    flaggedReason:
      kind === "flagged" && row.malformed_rate != null
        ? `Its malformed response rate of ${fmtPct(row.malformed_rate)} is over the 5 percent admission limit, so it keeps every number and is not ranked.${
            decomp !== null
              ? ` Its genuine flips are ${fmtPct(decomp.genuineRate)} of its eligible cases, and ${fmtPct(decomp.malformedShare)} of its counted flips are to malformed output.`
              : ""
          }`
        : null,
    decompText:
      kind === "flagged" && decomp !== null
        ? `genuine flips ${fmtPct(decomp.genuineRate)} of eligible cases, with ${fmtPct(decomp.malformedShare)} of counted flips to malformed output`
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
