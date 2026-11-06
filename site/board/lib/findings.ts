/**
 * Findings derivations for the redesign opening.
 *
 * Every figure the findings state derives here from the payload,
 * through the same decomposition core the board trusts
 * (lib/payload flipDecomposition). The design-time proof of these
 * derivations is the findings layer derivation record. This module
 * is the build-time form of the same arithmetic. Failure semantics
 * are fail closed, as the findings spec requires. Where a
 * decomposition a finding needs comes back empty, or a population
 * the finding names is not the shape the finding describes, this
 * module throws and the build fails rather than printing a finding
 * without its evidence.
 */

import {
  boardGroups,
  countOf,
  familyRecords,
  flipDecomposition,
  measuredAsr,
  shortName,
  unansweredCount,
  wireWords,
  type BoardRow,
} from "@/lib/payload";
import { vendorOf } from "@/lib/vendor";

/**
 * The harness wording for a leader measured through an agent
 * harness, keyed by the recorded wire. The finding states the
 * harness because the harness is part of the measurement, and
 * the words come from the leader row's own wire, so a leader
 * measured another way fails the build here rather than
 * borrowing this wording.
 */
const HARNESS_WORDS: Record<string, string> = {
  "cursor-harness": "Cursor agent harness",
};

/** The dense rank of one row among a population, by measured
 *  attack success. Computed from the values themselves, so
 *  the payload's row order cannot misstate it. */
function denseRankOf(rows: BoardRow[], target: BoardRow): number {
  const targetAsr = measuredAsr(target);
  if (targetAsr === null) {
    throw new Error("findings: a rank was asked of a row with no measured rate");
  }
  const below = new Set<number>();
  for (const row of rows) {
    const v = measuredAsr(row);
    if (v !== null && v < targetAsr) below.add(v);
  }
  return below.size + 1;
}

export interface PooledDecomp {
  rows: number;
  flips: number;
  malformed: number;
  /** Malformed flips as a share of counted flips. */
  share: number;
  /** Counted flips with the malformed ones removed, over eligible cases. */
  genuineRate: number;
}

/** Pool the decomposition over a population, or null when any
 *  row in it derives none. */
export function pooledDecomp(rows: BoardRow[]): PooledDecomp | null {
  let flips = 0;
  let malformed = 0;
  let eligible = 0;
  for (const row of rows) {
    const d = flipDecomposition(row);
    if (d === null) return null;
    flips += d.flips;
    malformed += d.malformedFlips;
    eligible += row.n_eligible;
  }
  if (flips === 0 || eligible === 0) return null;
  return {
    rows: rows.length,
    flips,
    malformed,
    share: malformed / flips,
    genuineRate: (flips - malformed) / eligible,
  };
}

/** Spearman rank correlation, with tie averaged ranks. */
export function spearman(xs: number[], ys: number[]): number {
  const ranks = (vs: number[]): number[] => {
    const order = vs
      .map((v, i) => ({ v, i }))
      .sort((a, b) => a.v - b.v);
    const out = new Array<number>(vs.length);
    let i = 0;
    while (i < order.length) {
      let j = i;
      while (j + 1 < order.length && order[j + 1].v === order[i].v) j += 1;
      const avg = (i + j) / 2 + 1;
      for (let k = i; k <= j; k += 1) out[order[k].i] = avg;
      i = j + 1;
    }
    return out;
  };
  const rx = ranks(xs);
  const ry = ranks(ys);
  const n = xs.length;
  const mx = rx.reduce((a, b) => a + b, 0) / n;
  const my = ry.reduce((a, b) => a + b, 0) / n;
  let cov = 0;
  let vx = 0;
  let vy = 0;
  for (let i = 0; i < n; i += 1) {
    cov += (rx[i] - mx) * (ry[i] - my);
    vx += (rx[i] - mx) ** 2;
    vy += (ry[i] - my) ** 2;
  }
  return cov / Math.sqrt(vx * vy);
}

export interface SplitFinding {
  ranked: PooledDecomp;
  flagged: PooledDecomp;
  /** Ranked rows whose counted flips are majority malformed. */
  rankedMajorityMalformed: number;
  /** The highest malformed rate on the ranked board. */
  rankedMaxMalformedRate: number;
  /** Flagged rows whose counted flips are majority malformed. */
  flaggedMajorityMalformed: number;
  mercury: {
    row: BoardRow;
    counted: number;
    malformedShare: number;
    genuineShare: number;
    genuineRate: number;
  };
}

export interface WireFinding {
  name: string;
  /** The vendor both wires belong to, read off the rows. */
  vendor: string;
  tracks: Array<{
    row: BoardRow;
    wire: string;
    asr: number;
    ci: [number, number];
    malformed: number;
    cost: number | null;
  }>;
  gap: number;
}

export interface PriceFinding {
  pricedCount: number;
  correlation: number;
  jev: { row: BoardRow; rank: number; cost: number; asr: number };
  priciest: { row: BoardRow; cost: number; asr: number };
  multiple: number;
  hundredFold: { count: number; flippedMore: number; flippedLess: Array<{ name: string; cost: number; asr: number }> };
  cheapest: { row: BoardRow; cost: number; asr: number };
}

export interface GuardFinding {
  rows: BoardRow[];
  subsetCases: number;
  fullCases: number;
  subsetShare: number;
  flips: number;
  reversals: number;
  toAbstain: number;
  untyped: number;
  allBenignPerfect: boolean;
  minAsr: number;
  maxAsr: number;
}

export interface LeaderFinding {
  row: BoardRow;
  /** The harness the leader was measured through, in words. */
  harness: string;
  rank: number;
  population: number;
  ci: [number, number];
  flips: number;
  malformedFlips: number;
  unanswered: number;
  decidedBenign: number;
  benign: number;
}

export interface FindingsData {
  split: SplitFinding;
  wire: WireFinding;
  price: PriceFinding;
  guards: GuardFinding;
  leader: LeaderFinding;
}

export function findingsData(): FindingsData {
  const groups = boardGroups();
  const full = groups.full;
  const flagged = groups.flagged;

  /* Finding 1, the split. */
  const rankedPool = pooledDecomp(full);
  const flaggedPool = pooledDecomp(flagged);
  if (rankedPool === null || flaggedPool === null) {
    throw new Error("findings: a pooled decomposition did not derive");
  }
  let rankedMajority = 0;
  let rankedMaxMalformed = 0;
  for (const row of full) {
    const d = flipDecomposition(row);
    if (d !== null && d.malformedShare >= 0.5) rankedMajority += 1;
    if (row.malformed_rate !== null) {
      rankedMaxMalformed = Math.max(rankedMaxMalformed, row.malformed_rate);
    }
  }
  if (rankedMajority !== 0) {
    throw new Error(
      "findings: a ranked result's counted flips are majority malformed, so the split claim does not hold on this payload",
    );
  }
  let flaggedMajority = 0;
  let mercuryRow: BoardRow | null = null;
  for (const row of flagged) {
    const d = flipDecomposition(row);
    if (d !== null && d.malformedShare >= 0.5) flaggedMajority += 1;
    if (
      mercuryRow === null ||
      (row.asr_conditional ?? 0) > (mercuryRow.asr_conditional ?? 0)
    ) {
      mercuryRow = row;
    }
  }
  if (mercuryRow === null || mercuryRow.asr_conditional === null) {
    throw new Error("findings: no flagged extreme row");
  }
  const mercuryDecomp = flipDecomposition(mercuryRow);
  if (mercuryDecomp === null) {
    throw new Error("findings: the extreme flagged row derives no decomposition");
  }

  /* Finding 2, the wire. The one model measured on two wires. */
  const byName = new Map<string, BoardRow[]>();
  for (const row of full) {
    const list = byName.get(row.display_name) ?? [];
    list.push(row);
    byName.set(row.display_name, list);
  }
  const pairs = [...byName.values()].filter(
    (list) => list.length === 2 && list[0].wire !== list[1].wire,
  );
  if (pairs.length !== 1) {
    throw new Error("findings: the two wire population is not exactly one model");
  }
  const wireRows = [...pairs[0]].sort(
    (a, b) => (a.asr_conditional ?? 0) - (b.asr_conditional ?? 0),
  );
  const wireVendor = vendorOf(wireRows[0]).label;
  if (vendorOf(wireRows[1]).label !== wireVendor) {
    throw new Error("findings: the two wire rows carry different vendors");
  }
  const wireTracks = wireRows.map((row) => {
    if (
      row.asr_conditional === null ||
      row.asr_ci95 === null ||
      row.malformed_rate === null
    ) {
      throw new Error("findings: a wire track is missing its figures");
    }
    return {
      row,
      wire: wireWords(row.wire),
      asr: row.asr_conditional,
      ci: row.asr_ci95,
      malformed: row.malformed_rate,
      cost: row.total_cost_usd,
    };
  });
  const gap = Math.abs(wireTracks[1].asr - wireTracks[0].asr);
  /* The finding's prose states the intervals overlap, so the
   * build asserts it rather than letting a separated pair
   * print the sentence. */
  if (wireTracks[0].ci[1] < wireTracks[1].ci[0]) {
    throw new Error(
      "findings: the two wire intervals do not overlap, so the harness wording does not hold on this payload",
    );
  }

  /* Finding 3, price. */
  const priced = full.filter(
    (r) => r.total_cost_usd !== null && r.total_cost_usd > 0,
  );
  const correlation = spearman(
    priced.map((r) => r.total_cost_usd as number),
    priced.map((r) => r.asr_conditional as number),
  );
  const priciest = priced.reduce((a, b) =>
    (b.total_cost_usd as number) > (a.total_cost_usd as number) ? b : a,
  );
  const cheapest = priced.reduce((a, b) =>
    (b.total_cost_usd as number) < (a.total_cost_usd as number) ? b : a,
  );
  const jev = full.find((r) => shortName(r).startsWith("jev"));
  if (jev === undefined) {
    throw new Error("findings: the price anchor row is not on the full suite");
  }
  /* The hundred fold set and the multiple are ratios against
   * the anchor's cost, so the anchor must carry a recorded
   * positive cost before either is computed. */
  if (jev.total_cost_usd === null || jev.total_cost_usd <= 0) {
    throw new Error(
      "findings: the price anchor carries no recorded cost, so the price finding does not hold on this payload",
    );
  }
  const jevCost = jev.total_cost_usd;
  const hundred = priced.filter(
    (r) => (r.total_cost_usd as number) >= 100 * jevCost,
  );
  const hundredLess = hundred
    .filter((r) => (r.asr_conditional as number) <= (jev.asr_conditional as number))
    .map((r) => ({
      name: shortName(r),
      cost: r.total_cost_usd as number,
      asr: r.asr_conditional as number,
    }));

  /* Finding 4, the guards. Direction totals pool over the slice
   * rows' per family flip direction records, the taxonomy's own
   * classes, as the derivation record pools them. */
  const slices = groups.slices;
  const dirTotals = new Map<string, number>();
  let guardFlips = 0;
  for (const row of slices) {
    for (const fam of familyRecords(row)) {
      const nf = countOf(fam.n_flipped);
      if (nf !== null) guardFlips += nf;
      const fd =
        fam.flip_direction !== null &&
        typeof fam.flip_direction === "object" &&
        !Array.isArray(fam.flip_direction)
          ? (fam.flip_direction as Record<string, unknown>)
          : {};
      for (const [key, value] of Object.entries(fd)) {
        const c = countOf(value);
        if (c !== null) dirTotals.set(key, (dirTotals.get(key) ?? 0) + c);
      }
    }
  }
  const reversals =
    (dirTotals.get("approve-to-deny") ?? 0) +
    (dirTotals.get("deny-to-approve") ?? 0);
  const subsetCases = slices[0]?.n_cases ?? 0;
  if (slices.some((r) => r.total_cost_usd !== null)) {
    throw new Error(
      "findings: a guard result carries a recorded cost, so the guard claim does not hold on this payload",
    );
  }

  /* Finding 5, the leader, chosen by the lowest measured rate
   * among the ranked full suite rows rather than by position,
   * so the payload's row order cannot misstate it. The finding
   * is the leader's disclosed case, and its sanctioned account
   * describes exactly one case, so a leader carrying any
   * other count leaves the finding printing an account that
   * is not its own and the build fails. */
  const measured = full.filter((r) => measuredAsr(r) !== null);
  if (measured.length === 0) {
    throw new Error("findings: no full suite row carries a measured rate");
  }
  const leader = measured.reduce((a, b) =>
    (measuredAsr(b) as number) < (measuredAsr(a) as number) ? b : a,
  );
  const harness = HARNESS_WORDS[leader.wire];
  if (harness === undefined) {
    throw new Error(
      "findings: the leader's wire carries no harness wording the finding may state",
    );
  }
  const leaderDecomp = flipDecomposition(leader);
  if (leaderDecomp === null || leader.asr_ci95 === null || leader.benign_accuracy === null) {
    throw new Error("findings: the leader derives no decomposition");
  }
  const leaderUnanswered = unansweredCount(leader);
  if (leaderUnanswered !== 1) {
    throw new Error(
      `findings: the leader carries ${leaderUnanswered} cases that produced no answer, and the disclosure account describes exactly one, so the disclosure finding does not hold on this payload`,
    );
  }

  return {
    split: {
      ranked: rankedPool,
      flagged: flaggedPool,
      rankedMajorityMalformed: rankedMajority,
      rankedMaxMalformedRate: rankedMaxMalformed,
      flaggedMajorityMalformed: flaggedMajority,
      mercury: {
        row: mercuryRow,
        counted: mercuryRow.asr_conditional,
        malformedShare: mercuryDecomp.malformedShare,
        genuineShare: 1 - mercuryDecomp.malformedShare,
        genuineRate: mercuryDecomp.genuineRate,
      },
    },
    wire: { name: shortName(wireRows[0]), vendor: wireVendor, tracks: wireTracks, gap },
    price: {
      pricedCount: priced.length,
      correlation,
      jev: {
        row: jev,
        rank: denseRankOf(full, jev),
        cost: jevCost,
        asr: jev.asr_conditional as number,
      },
      priciest: {
        row: priciest,
        cost: priciest.total_cost_usd as number,
        asr: priciest.asr_conditional as number,
      },
      multiple: (priciest.total_cost_usd as number) / jevCost,
      hundredFold: {
        count: hundred.length,
        flippedMore: hundred.length - hundredLess.length,
        flippedLess: hundredLess,
      },
      cheapest: {
        row: cheapest,
        cost: cheapest.total_cost_usd as number,
        asr: cheapest.asr_conditional as number,
      },
    },
    guards: {
      rows: slices,
      subsetCases,
      fullCases: groups.fullCases,
      subsetShare: subsetCases / groups.fullCases,
      flips: guardFlips,
      reversals,
      toAbstain: dirTotals.get("to-abstain") ?? 0,
      untyped: dirTotals.get("other") ?? 0,
      allBenignPerfect: slices.every((r) => r.benign_accuracy === 1),
      minAsr: Math.min(...slices.map((r) => r.asr_conditional ?? 0)),
      maxAsr: Math.max(...slices.map((r) => r.asr_conditional ?? 0)),
    },
    leader: {
      row: leader,
      harness,
      rank: denseRankOf(full, leader),
      population: full.length,
      ci: leader.asr_ci95,
      flips: leaderDecomp.flips,
      malformedFlips: leaderDecomp.malformedFlips,
      unanswered: leaderUnanswered,
      decidedBenign: leader.n_cases - leaderUnanswered,
      benign: leader.benign_accuracy,
    },
  };
}
