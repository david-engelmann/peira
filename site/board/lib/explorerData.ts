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
  splitDisplayName,
  type BoardRow,
} from "@/lib/payload";
import {
  fmtCi,
  fmtDelta3,
  fmtEce,
  fmtInt,
  fmtMs,
  fmtPct,
  fmtUsdExact,
} from "@/lib/format";
import { vendorFamilyOf } from "@/lib/vendorColors";
import { modelProfile } from "@/lib/modelProfile";
import { asrAxisFor, axisPct } from "@/lib/chart";
import {
  calibrationOf,
  familiesOf,
  familyFullName,
  familyOrder,
  FAMILY_SHORT,
} from "@/lib/charts";
import { provenanceOf, runDateWords, severitiesOf } from "@/lib/cards";
import {
  familyDecompText,
  inspectorDataAll,
  type InspectorDatum,
} from "@/lib/inspectorData";

export interface XFamily {
  key: string;
  short: string;
  full: string;
  asr: number | null;
  /**
   * The family's decomposition sentence, in the words the
   * weakest family sentence uses, built by the inspector
   * layer's one per-family construction. Null where the
   * family's records derive no decomposition. The families
   * view prints no family rate without this sentence
   * standing under its bar (C-5, per-family scope).
   */
  decompText: string | null;
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
  profile: ReturnType<typeof modelProfile>;
  /** Counted flips and their split, where the records derive one. */
  decomp: {
    flips: number;
    malformedFlips: number;
    malformedShare: number;
    genuineRate: number;
  } | null;
  families: XFamily[];
  weakestFamily: {
    name: string;
    text: string;
    baseText: string | null;
    decompText: string | null;
  } | null;
  severities: Array<{ label: string; flipText: string | null; baseText: string | null }>;
  calibration: {
    eceText: string;
    brierText: string;
    bins: Array<{ x: number; y: number; n: number }>;
  } | null;
  provenanceLine: string;
  /** The full record behind the reading's summary lines. */
  record: XRecord;
  rerunText: string | null;
  flaggedReason: string | null;
  sliceNote: string | null;
  unanswered: string | null;
  singleCall: string | null;
  nCases: number;
  nEligible: number;
}

/**
 * The full record (iteration 12). Everything the payload
 * carries for one result that the reading did not already
 * state, shaped as printable lines. The family rows carry
 * every family's rate with its interval, its case counts,
 * its flip directions, its recorded cost, its mean latency,
 * and its refusal rate. The severity rows carry the rate
 * with its interval, the flipped and eligible counts, the
 * recorded cost, and the summed latency. The calibration
 * block carries both arms with their intervals, the Murphy
 * components, the confidence coverage, the change under
 * attack, and both arms' reliability bins. The run facts
 * carry the provenance and the run's own tallies. A field
 * the payload does not carry for a result stays absent.
 * Nothing here is computed beyond the board's own format
 * renderings of the sealed fields.
 */
export interface XFamilyDetail {
  key: string;
  full: string;
  asrText: string | null;
  ciText: string | null;
  countsText: string | null;
  directionsText: string | null;
  metaText: string | null;
}

export interface XSeverityDetail {
  label: string;
  flipText: string | null;
  ciText: string | null;
  /** The count statements as separate segments, so the
   * reading can hold each one unbroken on its own line
   * span, the severity segments' standing no split rule. */
  segments: string[];
  metaText: string | null;
}

export interface XCalArm {
  eceText: string | null;
  brierText: string | null;
  murphyText: string | null;
  coverageText: string | null;
  bins: Array<{ x: number; y: number; n: number }>;
}

export interface XRecord {
  families: XFamilyDetail[];
  severities: XSeverityDetail[];
  calibration: {
    benign: XCalArm;
    attacked: XCalArm;
    deltaText: string | null;
  } | null;
  runFacts: Array<{ label: string; value: string }>;
}

function numOrNull(x: unknown): number | null {
  return typeof x === "number" && Number.isFinite(x) ? x : null;
}

function strOrNull(x: unknown): string | null {
  return typeof x === "string" && x !== "" ? x : null;
}

function pairOrNull(x: unknown): [number, number] | null {
  return Array.isArray(x) &&
    x.length === 2 &&
    typeof x[0] === "number" &&
    typeof x[1] === "number"
    ? [x[0], x[1]]
    : null;
}

function recOrEmpty(x: unknown): Record<string, unknown> {
  return x !== null && typeof x === "object" && !Array.isArray(x)
    ? (x as Record<string, unknown>)
    : {};
}

function shortHash(v: string): string {
  return v.length > 12 ? `${v.slice(0, 12)}…` : v;
}

const DIRECTION_LABELS: Array<[string, string]> = [
  ["approve-to-deny", "approve to deny"],
  ["deny-to-approve", "deny to approve"],
  ["score-shifted", "score shifted"],
  ["to-abstain", "to abstain"],
  ["to-malformed", "to malformed"],
  ["other", "other"],
];

function familyDetailOf(
  row: BoardRow,
  famOrder: string[],
): XFamilyDetail[] {
  const fams = recOrEmpty(recOrEmpty(row.detail).families);
  const out: XFamilyDetail[] = [];
  for (const key of famOrder) {
    const f = recOrEmpty(fams[key]);
    if (Object.keys(f).length === 0) continue;
    const asr = numOrNull(f.asr);
    const ci = pairOrNull(f.asr_ci95);
    const n = numOrNull(f.n);
    const nFlipped = numOrNull(f.n_flipped);
    const nEligible = numOrNull(f.n_eligible);
    const counts: string[] = [];
    if (n !== null) counts.push(`${fmtInt(n)} cases`);
    if (nFlipped !== null && nEligible !== null)
      counts.push(
        `${fmtInt(nFlipped)} flipped of ${fmtInt(nEligible)} eligible`,
      );
    const dirs = recOrEmpty(f.flip_direction);
    const dirParts: string[] = [];
    for (const [k, label] of DIRECTION_LABELS) {
      const c = numOrNull(dirs[k]);
      if (c !== null && c > 0) dirParts.push(`${fmtInt(c)} ${label}`);
    }
    const meta: string[] = [];
    const cost = numOrNull(f.cost_usd);
    if (cost !== null && cost > 0) meta.push(fmtUsdExact(cost));
    const latMean = numOrNull(f.latency_ms_mean);
    if (latMean !== null) meta.push(`mean latency ${fmtMs(latMean)}`);
    const refusal = numOrNull(f.refusal_rate);
    if (refusal !== null) meta.push(`refusals ${fmtPct(refusal)}`);
    out.push({
      key,
      full: familyFullName(key),
      asrText: asr !== null ? fmtPct(asr) : null,
      ciText: ci !== null ? fmtCi(ci) : null,
      countsText: counts.length > 0 ? counts.join(" · ") : null,
      directionsText: dirParts.length > 0 ? dirParts.join(" · ") : null,
      metaText: meta.length > 0 ? meta.join(" · ") : null,
    });
  }
  return out;
}

const SEVERITY_KEYS: Array<[string, string]> = [
  ["critical", "Critical"],
  ["high", "High"],
  ["medium", "Medium"],
];

function severityDetailOf(row: BoardRow): XSeverityDetail[] {
  const sevs = recOrEmpty(recOrEmpty(row.detail).severities);
  const out: XSeverityDetail[] = [];
  for (const [key, label] of SEVERITY_KEYS) {
    const s = recOrEmpty(sevs[key]);
    if (Object.keys(s).length === 0) continue;
    const rate = numOrNull(s.flip_rate_raw);
    const ci = pairOrNull(s.flip_rate_ci95);
    const n = numOrNull(s.n);
    const nFlipped = numOrNull(s.n_flipped);
    const nEligible = numOrNull(s.n_eligible);
    const segments: string[] = [];
    if (nFlipped !== null && nEligible !== null)
      segments.push(
        `${fmtInt(nFlipped)} flipped of ${fmtInt(nEligible)} eligible`,
      );
    if (n !== null) segments.push(`${fmtInt(n)} cases`);
    const meta: string[] = [];
    const cost = numOrNull(s.cost_usd);
    if (cost !== null && cost > 0) meta.push(fmtUsdExact(cost));
    const latTotal = numOrNull(s.latency_ms_total);
    if (latTotal !== null)
      meta.push(`summed latency ${fmtInt(Math.round(latTotal / 1000))}s`);
    out.push({
      label,
      flipText: rate !== null ? fmtPct(rate) : null,
      ciText: ci !== null ? fmtCi(ci) : null,
      segments,
      metaText: meta.length > 0 ? meta.join(" · ") : null,
    });
  }
  return out;
}

function calArmOf(
  cal: Record<string, unknown>,
  armKey: string,
  coverage: number | null,
): XCalArm {
  const arm = recOrEmpty(cal[armKey]);
  const ece = numOrNull(arm.ece);
  const eceCi = pairOrNull(arm.ece_ci95);
  const brier = numOrNull(arm.brier);
  const brierCi = pairOrNull(arm.brier_ci95);
  const murphy = recOrEmpty(arm.murphy);
  const murphyParts: string[] = [];
  for (const [k, label] of [
    ["reliability", "reliability"],
    ["resolution", "resolution"],
    ["uncertainty", "uncertainty"],
    ["residual", "residual"],
  ] as Array<[string, string]>) {
    const v = numOrNull(murphy[k]);
    if (v !== null) murphyParts.push(`${label} ${fmtEce(v)}`);
  }
  const binsRaw = recOrEmpty(
    recOrEmpty(cal.reliability_bins)[armKey],
  ).bins;
  const bins: XCalArm["bins"] = [];
  if (Array.isArray(binsRaw)) {
    for (const b of binsRaw) {
      const bin = recOrEmpty(b);
      const mf = numOrNull(bin.mean_forecast);
      const mo = numOrNull(bin.mean_outcome);
      const bn = numOrNull(bin.n);
      if (mf !== null && mo !== null && bn !== null)
        bins.push({ x: mf, y: mo, n: bn });
    }
  }
  const withCi = (
    v: number | null,
    ci: [number, number] | null,
  ): string | null =>
    v === null
      ? null
      : ci !== null
        ? `${fmtEce(v)} [${fmtEce(ci[0])}, ${fmtEce(ci[1])}]`
        : fmtEce(v);
  return {
    eceText: withCi(ece, eceCi),
    brierText: withCi(brier, brierCi),
    murphyText:
      murphyParts.length > 0 ? `Murphy ${murphyParts.join(" · ")}` : null,
    coverageText:
      coverage !== null ? `confidence coverage ${fmtPct(coverage)}` : null,
    bins,
  };
}

function calibrationDetailOf(row: BoardRow): XRecord["calibration"] {
  const cal = recOrEmpty(recOrEmpty(row.detail).calibration);
  if (Object.keys(cal).length === 0) return null;
  const coverage = recOrEmpty(cal.confidence_coverage);
  const benign = calArmOf(cal, "benign", numOrNull(coverage.benign));
  const attacked = calArmOf(
    cal,
    "attacked",
    numOrNull(coverage.attacked),
  );
  const dEce = recOrEmpty(cal.delta_ece);
  const dBrier = recOrEmpty(cal.delta_brier);
  const deltaParts: string[] = [];
  for (const [d, label] of [
    [dEce, "ECE"],
    [dBrier, "Brier"],
  ] as Array<[Record<string, unknown>, string]>) {
    const dv = numOrNull(d.delta);
    const ci = pairOrNull(d.ci95);
    if (dv !== null)
      deltaParts.push(
        ci !== null
          ? `${label} ${fmtDelta3(dv)} [${fmtDelta3(ci[0])}, ${fmtDelta3(ci[1])}]`
          : `${label} ${fmtDelta3(dv)}`,
      );
  }
  return {
    benign,
    attacked,
    deltaText:
      deltaParts.length > 0
        ? `Change under attack · ${deltaParts.join(" · ")}`
        : null,
  };
}

function runFactsOf(row: BoardRow): XRecord["runFacts"] {
  const prov = recOrEmpty(row.provenance);
  const top = row as unknown as Record<string, unknown>;
  const facts: Array<{ label: string; value: string }> = [];
  const push = (label: string, value: string | null) => {
    if (value !== null && value !== "") facts.push({ label, value });
  };
  const adapterName = strOrNull(prov.adapter_name);
  const adapterVersion = strOrNull(prov.adapter_version);
  push(
    "Adapter",
    adapterName !== null
      ? adapterVersion !== null
        ? `${adapterName} · ${adapterVersion}`
        : adapterName
      : null,
  );
  push("Adapter spec", strOrNull(prov.adapter_spec));
  const revision = strOrNull(prov.adapter_revision);
  push("Adapter revision", revision !== null ? shortHash(revision) : null);
  push("Contract", strOrNull(prov.contract_version));
  const seed = numOrNull(prov.seed);
  push("Seed", seed !== null ? String(seed) : null);
  const pricingVersion = strOrNull(prov.pricing_version);
  const pricingDate = strOrNull(prov.pricing_date);
  push(
    "Pricing",
    pricingVersion !== null
      ? pricingDate !== null
        ? `${pricingVersion} · ${pricingDate}`
        : pricingVersion
      : null,
  );
  const manifest = strOrNull(prov.manifest_sha256);
  push("Manifest", manifest !== null ? shortHash(manifest) : null);
  const env = strOrNull(prov.env_sha256);
  push("Environment", env !== null ? shortHash(env) : null);
  push("Run", shortHash(row.run_id));
  push("Run date", runDateWords(row));
  push("Wire", row.wire);
  push(
    "Cases",
    `${fmtInt(row.n_cases)} · ${fmtInt(row.n_eligible)} eligible`,
  );
  const p50 = numOrNull(top.latency_ms_p50_attacked);
  const p95 = numOrNull(top.latency_ms_p95_attacked);
  push(
    "Latency, attacked",
    p50 !== null || p95 !== null
      ? [
          p50 !== null ? `p50 ${fmtMs(p50)}` : null,
          p95 !== null ? `p95 ${fmtMs(p95)}` : null,
        ]
          .filter((p): p is string => p !== null)
          .join(" · ")
      : null,
  );
  const errB = numOrNull(top.error_on_benign_cases);
  const errA = numOrNull(top.error_on_attacked_cases);
  push(
    "Calls with errors",
    errB !== null || errA !== null
      ? `benign ${errB !== null ? fmtInt(errB) : "·"} · attacked ${errA !== null ? fmtInt(errA) : "·"}`
      : null,
  );
  const unanswered = numOrNull(top.unanswered_cases);
  push(
    "Unanswered cases",
    unanswered !== null ? fmtInt(unanswered) : null,
  );
  return facts;
}

function recordOf(row: BoardRow, famOrder: string[]): XRecord {
  return {
    families: familyDetailOf(row, famOrder),
    severities: severityDetailOf(row),
    calibration: calibrationDetailOf(row),
    runFacts: runFactsOf(row),
  };
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
  const famDecomp = familyFlipDecomposition(row);
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
    profile: modelProfile(row),
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
      const famSplit = famDecomp.get(key) ?? null;
      return {
        key,
        short: FAMILY_SHORT[key] ?? familyFullName(key),
        full: familyFullName(key),
        asr: fams.get(key)?.asr ?? null,
        decompText:
          famSplit !== null ? familyDecompText(famSplit) : null,
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
    record: recordOf(row, famOrder),
    rerunText:
      row.rerun != null
        ? `This result is chained to an earlier run in its record, on ${row.rerun.date}. Its figures are its own standing figures.`
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
