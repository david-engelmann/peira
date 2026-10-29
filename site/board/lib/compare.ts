/**
 * Compare data shaping (design system section 4.6). Runs on
 * the server only. The compare island receives this compact
 * row set as props, so the 1.2 MB payload JSON never enters a
 * client bundle; every value in it is a payload field copied
 * across untouched. Deltas are not computed here. The island
 * subtracts these unrounded values at render time, which is
 * the published delta rule (method notes: derived figures are
 * computed from unrounded values), and integrity check 11
 * proves this row set equals the payload on every row.
 */

import type { BoardRow } from "@/lib/payload";
import {
  boardGroups,
  duplicateShortNames,
  modelSlug,
  shortName,
  wireWords,
} from "@/lib/payload";
import { calibrationArmsOf, familiesOf, familyFullName, familyOrder } from "@/lib/charts";
import { costStateOf } from "@/lib/cards";
import { vendorColorOf } from "@/lib/vendorColors";
import { vendorOf } from "@/lib/vendor";

export type CompareGroup = "full" | "flagged" | "slice";

export interface CompareRow {
  slug: string;
  runId: string;
  /** Short name, per the name policy. Hash carrying names never appear. */
  name: string;
  /** Wire in plain words, present only when the short name is shared. */
  wire: string | null;
  group: CompareGroup;
  nCases: number;
  asr: number | null;
  benign: number | null;
  malformed: number | null;
  atkEce: number | null;
  atkBrier: number | null;
  benEce: number | null;
  benBrier: number | null;
  tax: number | null;
  /** Recorded cost total, or null when no cost was recorded. */
  cost: number | null;
  costLowerBound: boolean;
  latP50: number | null;
  latP95: number | null;
  /** Family attack success in the heatmap's fixed order, null where a family was not faced. */
  families: Array<number | null>;
  /** The model's vendor family color, for the paired family bars. */
  vendorColor: string;
  /** The model's vendor mark, shaped flat like the scatter's:
   * the logo path key or the monogram letter, plus the label. */
  logoSlug: string | null;
  monoLetter: string | null;
  markLabel: string;
}

export interface CompareData {
  rows: CompareRow[];
  /** Family full names in the same fixed order as each row's family array. */
  familyNames: string[];
  familyKeys: string[];
  defaultA: string;
  defaultB: string;
  fullCases: number;
  sliceCases: number;
}

function shapeRow(
  row: BoardRow,
  group: CompareGroup,
  allRows: BoardRow[],
  dupes: Set<string>,
  famKeys: string[],
): CompareRow {
  const arms = calibrationArmsOf(row);
  const cost = costStateOf(row);
  const fams = familiesOf(row);
  const vendor = vendorOf(row);
  return {
    slug: modelSlug(row, allRows),
    runId: row.run_id,
    name: shortName(row),
    wire: dupes.has(shortName(row)) ? wireWords(row.wire) : null,
    group,
    nCases: row.n_cases,
    asr: row.asr_conditional ?? null,
    benign: row.benign_accuracy ?? null,
    malformed: row.malformed_rate ?? null,
    atkEce: arms?.attacked.ece ?? row.ece_attacked ?? null,
    atkBrier: arms?.attacked.brier ?? null,
    benEce: arms?.benign.ece ?? null,
    benBrier: arms?.benign.brier ?? null,
    tax: row.robustness_tax ?? null,
    cost: cost.kind === "unrecorded" ? null : cost.value,
    costLowerBound: cost.kind === "lower-bound",
    latP50: row.latency_ms_p50_attacked ?? null,
    latP95: row.latency_ms_p95_attacked ?? null,
    families: famKeys.map((k) => fams.get(k)?.asr ?? null),
    vendorColor: vendorColorOf(row),
    logoSlug: vendor.kind === "logo" ? vendor.slug : null,
    monoLetter: vendor.kind === "mono" ? vendor.letter : null,
    markLabel: vendor.label,
  };
}

export function compareData(): CompareData {
  const groups = boardGroups();
  const allRows: BoardRow[] = [
    ...groups.full,
    ...groups.slices,
    ...groups.flagged,
  ];
  const dupes = duplicateShortNames(allRows);
  const famKeys = familyOrder(allRows);
  const rows: CompareRow[] = [
    ...groups.full.map((r) => shapeRow(r, "full", allRows, dupes, famKeys)),
    ...groups.flagged.map((r) => shapeRow(r, "flagged", allRows, dupes, famKeys)),
    ...groups.slices.map((r) => shapeRow(r, "slice", allRows, dupes, famKeys)),
  ];
  /* Default pair (design 4.6): the strongest full suite row
   * against the reference model of the programme. The full
   * group is in rank order, so its head is the strongest full
   * suite result. The reference is keyed on the wire that
   * measured it, not on its display name: the name is
   * versioned (jev-1.14.0 today) and changes as the model is
   * re-measured, while the measuring wire is a property of
   * the run itself and does not (F7 of the 2026-10-29
   * hardcode audit). The fallbacks stand when no row carries
   * that wire. */
  const REFERENCE_WIRE = "jev";
  const referenceRow = groups.full.find((r) => r.wire === REFERENCE_WIRE);
  const defaultA = rows.find((r) => r.group === "full") ?? rows[0];
  const defaultB =
    (referenceRow
      ? rows.find((r) => r.runId === referenceRow.run_id)
      : undefined) ??
    rows.find((r) => r.group === "full" && r.slug !== defaultA.slug) ??
    rows[1];
  return {
    rows,
    familyNames: famKeys.map((k) => familyFullName(k)),
    familyKeys: famKeys,
    defaultA: defaultA.slug,
    defaultB: defaultB.slug,
    fullCases: groups.fullCases,
    sliceCases: groups.slices[0]?.n_cases ?? 0,
  };
}
