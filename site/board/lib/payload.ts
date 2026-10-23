/**
 * Payload data layer.
 *
 * The board renders the payload JSON produced by the Python
 * pipeline and nothing else. Every number shown comes from a
 * payload field, formatted for display. No metric is recomputed
 * here. Derived layout (rank position, tie band geometry) is
 * computed from the payload at build time, following the same
 * definitions the previous renderer used.
 *
 * Publish flow: the pipeline writes a fresh payload JSON and the
 * publish step replaces data/payload.json with it, then rebuilds.
 * The development fixture is the preserved payload-publish26.json.
 */

import payloadData from "@/data/payload.json";
import { quantizeHalfUp } from "@/lib/format";

/** Expand a number to a plain decimal string (no exponent). */
function decimalString(value: number): string {
  const s = String(value);
  if (!/[eE]/.test(s)) return s;
  const [mantissa, expStr] = s.split(/[eE]/);
  const exp = parseInt(expStr, 10);
  const negative = mantissa.startsWith("-");
  const body = negative ? mantissa.slice(1) : mantissa;
  const [intPart, fracPart = ""] = body.split(".");
  const digits = intPart + fracPart;
  const point = intPart.length + exp;
  let out: string;
  if (point <= 0) out = "0." + "0".repeat(-point) + digits;
  else if (point >= digits.length) out = digits + "0".repeat(point - digits.length);
  else out = `${digits.slice(0, point)}.${digits.slice(point)}`;
  return (negative ? "-" : "") + out;
}

/** A payload count as an exact integer, or null (the _count rule). */
function countOf(x: unknown): number | null {
  if (typeof x !== "number" || !Number.isInteger(x) || x < 0) return null;
  return x;
}

/** Wilson 95 percent interval, z = 1.96, operation for operation
 *  with peira.metrics._wilson_ci_py. */
function wilson(hits: number, n: number): [number, number] {
  if (n === 0) return [0, 0];
  const z = 1.96;
  const p = hits / n;
  const denom = 1 + (z * z) / n;
  const center = (p + (z * z) / (2 * n)) / denom;
  const half =
    (z * Math.sqrt((p * (1 - p)) / n + (z * z) / (4 * n * n))) / denom;
  return [Math.max(0, center - half), Math.min(1, center + half)];
}

/**
 * The interval a row displays, ported from the previous
 * renderer's _row_ci. The stored asr_ci95 pair is the pipeline's
 * Wilson interval over the run's counts, rounded to four
 * decimals; printing it at one decimal double-rounds the bounds
 * sitting just under a boundary (743 of 4,621 gives a 15.0
 * percent lower bound, not the 15.1 the stored 0.1505 formats
 * to). When every family record carries its flipped count and
 * the recomputed interval rounds to both stored bounds at four
 * decimals, the exact interval serves the display and the
 * whisker geometry; otherwise the stored pair serves. Ranking
 * logic (tie bands, the axis) always reads the stored pair.
 */
export function displayCi(row: BoardRow): [number, number] | null {
  const pair = row.asr_ci95;
  if (pair === null) return null;
  const detail =
    row.detail !== null && typeof row.detail === "object"
      ? (row.detail as Record<string, unknown>)
      : {};
  const famsRaw = detail.families;
  let entries: unknown[] = [];
  if (Array.isArray(famsRaw)) entries = famsRaw;
  else if (famsRaw !== null && typeof famsRaw === "object") {
    entries = Object.values(famsRaw);
  }
  const fams = entries.filter(
    (f): f is Record<string, unknown> =>
      f !== null && typeof f === "object" && !Array.isArray(f),
  );
  if (fams.length === 0) return pair;
  let total = 0;
  for (const fam of fams) {
    const nf = countOf(fam.n_flipped);
    if (nf === null) return pair;
    total += nf;
  }
  const n = countOf(row.n_eligible);
  if (n === null || n === 0) return pair;
  const [lo, hi] = wilson(total, n);
  const q = (v: number) => quantizeHalfUp(decimalString(v), 4);
  if (q(lo) === q(pair[0]) && q(hi) === q(pair[1])) return [lo, hi];
  return pair;
}

export interface BoardRow {
  adapter_name: string;
  adapter_version: string;
  wire: string;
  display_name: string;
  run_id: string;
  created_utc: string;
  dataset_version: string | null;
  suite: string | null;
  ranking_eligible: boolean;
  /** Present on unranked rows only. Pipeline wording, shown verbatim. */
  reason?: string;
  asr_conditional: number | null;
  /** [low, high] 95 percent interval for asr_conditional. */
  asr_ci95: [number, number] | null;
  benign_accuracy: number | null;
  ece_attacked: number | null;
  malformed_rate: number | null;
  n_cases: number;
  n_eligible: number;
  /** Null on slice rows and absent on unranked rows. */
  robustness_tax: number | null;
  /** Null for runs with no recorded serving cost. */
  total_cost_usd: number | null;
  latency_ms_p50_attacked: number | null;
  latency_ms_p95_attacked: number | null;
  provenance: unknown;
  detail: unknown;
}

export interface BoardPayload {
  dataset_version: string | null;
  suite: string | null;
  n_ranked: number;
  n_unranked: number;
  ranked: BoardRow[];
  unranked: BoardRow[];
}

export const payload = payloadData as unknown as BoardPayload;

/** A ranked row with its rank. Rank is the payload array position. */
export interface RankedRow extends BoardRow {
  rank: number;
}

export function rankedRows(): RankedRow[] {
  return payload.ranked.map((row, i) => ({ ...row, rank: i + 1 }));
}

export function unrankedRows(): BoardRow[] {
  return payload.unranked;
}

/**
 * Tie bands over the ranked rows, ported from the previous
 * renderer (report_html _data.py, _tied_bands).
 *
 * A band is a run of consecutive ranked rows whose ASR intervals
 * share a common intersection, built greedily in rank order. A row
 * joins the open band only while its interval still crosses the
 * intersection of every interval already in the band, so every
 * band printed is mutually overlapping. A row with no interval
 * breaks the run. Returns rank to [lowest rank, highest rank] for
 * every row in a band of two or more.
 */
export function tieBands(rows: RankedRow[]): Map<number, [number, number]> {
  const out = new Map<number, [number, number]>();
  let band: RankedRow[] = [];
  let bandLo = 0;
  let bandHi = 0;

  const close = () => {
    if (band.length >= 2) {
      const ranks = band.map((r) => r.rank);
      const range: [number, number] = [Math.min(...ranks), Math.max(...ranks)];
      for (const r of band) out.set(r.rank, range);
    }
  };

  for (const row of rows) {
    const pair =
      row.asr_conditional !== null && row.asr_ci95 !== null
        ? row.asr_ci95
        : null;
    if (pair === null) {
      close();
      band = [];
      continue;
    }
    const [lo, hi] = pair;
    if (band.length > 0 && (lo > bandHi || bandLo > hi)) {
      close();
      band = [];
    }
    if (band.length > 0) {
      bandLo = Math.max(bandLo, lo);
      bandHi = Math.min(bandHi, hi);
    } else {
      bandLo = lo;
      bandHi = hi;
    }
    band.push(row);
  }
  close();
  return out;
}

/**
 * Split a display name into its model id and pinned revision.
 * Pinned local models carry the revision after an at sign, for
 * example Mapika/decider-0.8b@a0a01d6f8135298f400a8c856b355793012ae971.
 * The split is presentational only.
 */
export function splitDisplayName(displayName: string): {
  name: string;
  revision: string | null;
} {
  const at = displayName.lastIndexOf("@");
  if (at > 0 && /^[0-9a-f]{32,}$/i.test(displayName.slice(at + 1))) {
    return { name: displayName.slice(0, at), revision: displayName.slice(at + 1) };
  }
  return { name: displayName, revision: null };
}

/**
 * The chart label for a row, per the design name policy. The
 * organisation prefix drops, any revision hash moves out of the
 * label, and what remains is the model id a reader recognises.
 * The full display name appears only on detail cards and in the
 * run register, never in a chart.
 */
export function shortName(row: BoardRow): string {
  const { name } = splitDisplayName(row.display_name);
  const slash = name.lastIndexOf("/");
  return slash >= 0 ? name.slice(slash + 1) : name;
}

/** Wire identifiers in plain words, for duplicate short names. */
const WIRE_WORDS: Record<string, string> = {
  "openai-decisions": "Decisions API",
  "openai-structured": "Chat completions",
};

export function wireWords(wire: string): string {
  return WIRE_WORDS[wire] ?? wire;
}

/**
 * The rows whose short name is shared with another row in the
 * payload. Only those rows carry a wire line in the ranking, per
 * the name policy.
 */
export function duplicateShortNames(rows: BoardRow[]): Set<string> {
  const seen = new Map<string, number>();
  for (const row of rows) {
    const name = shortName(row);
    seen.set(name, (seen.get(name) ?? 0) + 1);
  }
  const dupes = new Set<string>();
  for (const [name, count] of seen) if (count > 1) dupes.add(name);
  return dupes;
}

/** A row measured on the abstain slice rather than the full suite. */
export function isSliceRow(row: BoardRow, fullCases: number): boolean {
  return row.n_cases < fullCases;
}

export function fullCaseCount(rows: BoardRow[]): number {
  return rows.reduce((max, r) => Math.max(max, r.n_cases), 0);
}

/**
 * Model identity. A model is the pair (adapter_name,
 * adapter_version), never either field alone, per the admission
 * rules. Three unrelated models in this payload carry the
 * adapter_version "1.0", and keying on the version alone
 * collapses them into one counted model, the defect the data
 * audit found in the previous renderer's tiles.
 */
export function modelKey(row: BoardRow): string {
  return `${row.adapter_name}${row.adapter_version}`;
}

export interface ModelCounts {
  tested: number;
  ranked: number;
  flagged: number;
}

/** Distinct model counts under the pair identity rule. */
export function modelCounts(): ModelCounts {
  const all = new Set([...payload.ranked, ...payload.unranked].map(modelKey));
  const ranked = new Set(payload.ranked.map(modelKey));
  const flagged = new Set(payload.unranked.map(modelKey));
  return { tested: all.size, ranked: ranked.size, flagged: flagged.size };
}

export interface TaxBenchmarks {
  /** Short name of the row setting the benign accuracy frontier. */
  benignSetter: string;
  benignValue: number;
  /** Short name of the row setting the attacked ECE frontier. */
  eceSetter: string;
  eceValue: number;
  /** Size of the full suite cohort the frontier is taken over. */
  cohortSize: number;
}

/**
 * The robustness tax benchmarks, derived from the payload's
 * full suite ranked cohort only. The generation layer computes
 * each tax against the best benign accuracy and the best
 * attacked ECE inside that cohort; slice rows are excluded, so
 * a slice holding benign accuracy 1.0 never sets the frontier.
 * Deriving the setters here, from the same cohort definition,
 * makes it impossible for the page to name a benchmark the tax
 * was not computed against.
 */
export function taxBenchmarks(groups: BoardGroups): TaxBenchmarks {
  const cohort = groups.full;
  let benignBest = cohort[0];
  let eceBest = cohort[0];
  for (const row of cohort) {
    if (
      row.benign_accuracy !== null &&
      (benignBest.benign_accuracy === null ||
        row.benign_accuracy > benignBest.benign_accuracy)
    ) {
      benignBest = row;
    }
    if (
      row.ece_attacked !== null &&
      (eceBest.ece_attacked === null || row.ece_attacked < eceBest.ece_attacked)
    ) {
      eceBest = row;
    }
  }
  return {
    benignSetter: shortName(benignBest),
    benignValue: benignBest.benign_accuracy ?? 0,
    eceSetter: shortName(eceBest),
    eceValue: eceBest.ece_attacked ?? 0,
    cohortSize: cohort.length,
  };
}

/** One row's tax recomputed from the benchmark values. */
export function recomputeTax(
  row: BoardRow,
  benchmarks: TaxBenchmarks,
): number | null {
  if (row.benign_accuracy === null || row.ece_attacked === null) return null;
  return (
    benchmarks.benignValue -
    row.benign_accuracy +
    (row.ece_attacked - benchmarks.eceValue)
  );
}

export interface BoardGroups {
  /** Ranked rows on the full case base, in payload rank order. */
  full: RankedRow[];
  /** Ranked rows on the slice base, in payload rank order. */
  slices: RankedRow[];
  /** Flagged rows with no rank, in attack success order. */
  flagged: BoardRow[];
  /** The full case base the two ranked groups split on. */
  fullCases: number;
}

/**
 * The ranking groups of the design system, section 4.1. The
 * ranked array splits on its case base into the full suite group
 * and the abstain slice group, each keeping payload rank order
 * and payload rank numbers. Flagged rows carry no rank and order
 * by attack success. Tie bands are computed inside each ranked
 * group, because a band cannot be drawn across the flagged strip
 * that separates the groups.
 */
export function boardGroups(): BoardGroups {
  const ranked = rankedRows();
  const fullCases = fullCaseCount(ranked);
  const full = ranked.filter((r) => r.n_cases === fullCases);
  const slices = ranked.filter((r) => r.n_cases < fullCases);
  const flagged = [...payload.unranked].sort(
    (a, b) => (a.asr_conditional ?? 0) - (b.asr_conditional ?? 0),
  );
  return { full, slices, flagged, fullCases };
}

/**
 * The board date. The payload carries no single generation stamp,
 * so the date is the newest run timestamp it does carry, taken
 * over every row. Trust furniture, the social preview, and the
 * chart identification lines all read this one derivation, so
 * the representations cannot drift apart (SF-04).
 */
export function boardDateIso(): string {
  const stamps = [...payload.ranked, ...payload.unranked].map(
    (r) => r.created_utc,
  );
  return stamps.sort().at(-1)!.slice(0, 10);
}

const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

/** The board date in words, for example 22 October 2026. */
export function boardDateWords(): string {
  const [y, m, d] = boardDateIso().split("-").map(Number);
  return `${d} ${MONTHS[m - 1]} ${y}`;
}

/** Dataset and suite versions, read from the rows that carry them. */
export function boardVersions(): { dataset: string; suite: string } {
  const row = payload.ranked[0];
  return {
    dataset: row.dataset_version ?? "unknown",
    suite: row.suite ?? "unknown",
  };
}
