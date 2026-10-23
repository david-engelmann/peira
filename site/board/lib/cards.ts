/**
 * Detail card derivations (design system section 4.5). The
 * payload carries each run's provenance block and severity
 * detail as untyped JSON; this module gives them typed
 * accessors in the same style as lib/charts, plus the cost
 * state words the index row and the card share. Every printed
 * number still comes straight from a payload field through
 * lib/format; nothing here recomputes a metric.
 */

import type { BoardRow } from "@/lib/payload";
import { costIsLowerBound } from "@/lib/charts";

/* ---------------- provenance ---------------- */

export interface ProvenanceData {
  adapterName: string | null;
  adapterSpec: string | null;
  adapterVersion: string | null;
  contractVersion: string | null;
  datasetVersion: string | null;
  pricingVersion: string | null;
  pricingDate: string | null;
  seed: number | null;
  suite: string | null;
  /** The run manifest hash, full length as the payload carries it. */
  manifestSha256: string | null;
}

function strOrNull(x: unknown): string | null {
  return typeof x === "string" && x.length > 0 ? x : null;
}

function numOrNull(x: unknown): number | null {
  return typeof x === "number" && Number.isFinite(x) ? x : null;
}

/** The run's provenance block, typed. */
export function provenanceOf(row: BoardRow): ProvenanceData {
  const raw =
    row.provenance !== null && typeof row.provenance === "object"
      ? (row.provenance as Record<string, unknown>)
      : {};
  return {
    adapterName: strOrNull(raw.adapter_name),
    adapterSpec: strOrNull(raw.adapter_spec),
    adapterVersion: strOrNull(raw.adapter_version),
    contractVersion: strOrNull(raw.contract_version),
    datasetVersion: strOrNull(raw.dataset_version),
    pricingVersion: strOrNull(raw.pricing_version),
    pricingDate: strOrNull(raw.pricing_date),
    seed: numOrNull(raw.seed),
    suite: strOrNull(raw.suite),
    manifestSha256: strOrNull(raw.manifest_sha256),
  };
}

/**
 * The version as the provenance block prints it. A pinned
 * Hugging Face revision rides inside some versions as a full
 * 40 character hash. The provenance block truncates a long hex
 * run to its first 12 characters, the same treatment the
 * manifest hash gets, so a hash is never a headline fact. The
 * full display name, hash included, still stands untruncated
 * in the card head under the name policy.
 */
export function versionForProvenance(version: string): string {
  return version.replace(/[0-9a-f]{13,}/g, (m) => m.slice(0, 12));
}

/** The run date in words, from the row's creation stamp. */
export function runDateWords(row: BoardRow): string {
  const MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
  ];
  const [y, m, d] = row.created_utc.slice(0, 10).split("-").map(Number);
  if (!y || !m || !d) return row.created_utc.slice(0, 10);
  return `${d} ${MONTHS[m - 1]} ${y}`;
}

/* ---------------- severities ---------------- */

export interface SeverityStat {
  key: string;
  /** Critical, High, or Medium. */
  label: string;
  flipRate: number | null;
  flipCi95: [number, number] | null;
  nEligible: number | null;
}

const SEVERITY_ORDER: Array<[string, string]> = [
  ["critical", "Critical"],
  ["high", "High"],
  ["medium", "Medium"],
];

/**
 * Flip rates at the three severity levels, in the fixed order
 * the card prints (design 1.6 and 4.5 rule 5). Each carries its
 * own eligible base, because the levels rest on different case
 * counts and a rate without its base can mislead.
 */
export function severitiesOf(row: BoardRow): SeverityStat[] {
  const detail =
    row.detail !== null && typeof row.detail === "object"
      ? (row.detail as Record<string, unknown>)
      : {};
  const raw =
    detail.severities !== null && typeof detail.severities === "object"
      ? (detail.severities as Record<string, unknown>)
      : {};
  return SEVERITY_ORDER.map(([key, label]) => {
    const s =
      raw[key] !== null && typeof raw[key] === "object"
        ? (raw[key] as Record<string, unknown>)
        : {};
    const ci =
      Array.isArray(s.flip_rate_ci95) &&
      s.flip_rate_ci95.length === 2 &&
      typeof s.flip_rate_ci95[0] === "number" &&
      typeof s.flip_rate_ci95[1] === "number"
        ? (s.flip_rate_ci95 as [number, number])
        : null;
    return {
      key,
      label,
      flipRate: numOrNull(s.flip_rate_raw),
      flipCi95: ci,
      nEligible: numOrNull(s.n_eligible),
    };
  });
}

/* ---------------- cost state ---------------- */

export type CostState =
  | { kind: "amount"; value: number }
  | { kind: "lower-bound"; value: number }
  | { kind: "local"; value: 0 }
  | { kind: "unrecorded" };

/**
 * The cost state of one result, in the four states the page
 * distinguishes (design 4.5, census V-02). A recorded cost with
 * unpriced calls is a lower bound. A recorded zero is a locally
 * served run, which is a different fact from no cost recorded,
 * and the two never share words.
 */
export function costStateOf(row: BoardRow): CostState {
  if (row.total_cost_usd === null || row.total_cost_usd === undefined) {
    return { kind: "unrecorded" };
  }
  if (row.total_cost_usd === 0) return { kind: "local", value: 0 };
  if (costIsLowerBound(row)) {
    return { kind: "lower-bound", value: row.total_cost_usd };
  }
  return { kind: "amount", value: row.total_cost_usd };
}
