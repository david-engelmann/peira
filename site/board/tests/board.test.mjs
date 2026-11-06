/**
 * Board data tests. Every figure the redesigned board prints
 * is recomputed here from data/payload.json by code written
 * for these tests, and the board's own data modules must
 * agree. The derivations under test are lib/findings.ts (the
 * five findings) and lib/explorerData.ts (the explorer's
 * rows), including the corners the production build had to
 * close. The calibration panel data, the robustness tax and
 * its benchmarks, the shared family axis, and the per-family
 * decompositions for flagged rows.
 *
 * No population literal appears below. Every expectation is
 * derived from the payload's own fields, so the suite runs
 * unchanged on the next payload.
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { register } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

register("../scripts/vendor-check-hooks.mjs", import.meta.url);

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const payload = JSON.parse(readFileSync(path.join(root, "data", "payload.json"), "utf8"));

const { findingsData } = await import(path.join(root, "lib", "findings.ts"));
const { explorerData } = await import(path.join(root, "lib", "explorerData.ts"));
const { modelSlug, denseRanks } = await import(path.join(root, "lib", "payload.ts"));

/* ---------- independent derivations ---------- */

const rows = [...payload.ranked, ...payload.unranked];
const fullCases = Math.max(...payload.ranked.map((r) => r.n_cases));
const full = payload.ranked.filter((r) => r.n_cases === fullCases);
const slices = payload.ranked.filter((r) => r.n_cases < fullCases);
const flagged = payload.unranked;

function decomp(r) {
  let fams = r.detail?.families;
  if (!fams) return null;
  if (!Array.isArray(fams)) fams = Object.values(fams);
  let flips = 0;
  let malformed = 0;
  for (const f of fams) {
    if (typeof f.n_flipped !== "number") return null;
    const tm = f.flip_direction?.["to-malformed"];
    if (typeof tm !== "number") return null;
    flips += f.n_flipped;
    malformed += tm;
  }
  return { flips, malformed };
}
function pool(rs) {
  let flips = 0;
  let malformed = 0;
  for (const r of rs) {
    const d = decomp(r);
    assert.notEqual(d, null, "a decomposition must derive");
    flips += d.flips;
    malformed += d.malformed;
  }
  return { flips, malformed };
}
function spearman(xs, ys) {
  const rank = (vs) => {
    const order = vs.map((v, i) => [v, i]).sort((a, b) => a[0] - b[0]);
    const out = new Array(vs.length);
    let i = 0;
    while (i < order.length) {
      let j = i;
      while (j + 1 < order.length && order[j + 1][0] === order[i][0]) j += 1;
      const avg = (i + j) / 2 + 1;
      for (let k = i; k <= j; k += 1) out[order[k][1]] = avg;
      i = j + 1;
    }
    return out;
  };
  const rx = rank(xs);
  const ry = rank(ys);
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

const findings = findingsData();
const explorer = explorerData();

/* ---------- Finding 1, the split ---------- */

test("finding 1 pools match an independent pooling of the rows", () => {
  const fp = pool(full);
  const gp = pool(flagged);
  assert.equal(findings.split.ranked.flips, fp.flips);
  assert.equal(findings.split.ranked.malformed, fp.malformed);
  assert.equal(findings.split.flagged.flips, gp.flips);
  assert.equal(findings.split.flagged.malformed, gp.malformed);
});

test("finding 1's framing holds on the payload: no ranked result flips mostly to malformed", () => {
  for (const r of full) {
    const d = decomp(r);
    assert.ok(d.flips === 0 || d.malformed / d.flips < 0.5, r.display_name);
  }
  const fp = pool(full);
  const gp = pool(flagged);
  assert.ok(gp.malformed / gp.flips > fp.malformed / fp.flips);
});

test("mercury's decomposition in finding 1 matches its rows", () => {
  const mercury = flagged.reduce((a, b) =>
    (a.asr_conditional ?? 0) > (b.asr_conditional ?? 0) ? a : b,
  );
  const d = decomp(mercury);
  assert.equal(findings.split.mercury.row.run_id, mercury.run_id);
  assert.equal(findings.split.mercury.counted, mercury.asr_conditional);
  assert.ok(
    Math.abs(findings.split.mercury.malformedShare - d.malformed / d.flips) < 1e-12,
  );
  assert.ok(
    Math.abs(
      findings.split.mercury.genuineRate - (d.flips - d.malformed) / mercury.n_eligible,
    ) < 1e-12,
  );
});

/* ---------- Finding 2, the wire ---------- */

test("finding 2 is the one duplicated model, with the derived gap", () => {
  const counts = new Map();
  for (const r of full) counts.set(r.display_name, (counts.get(r.display_name) ?? 0) + 1);
  const dupes = [...counts.entries()].filter(([, c]) => c > 1);
  assert.equal(dupes.length, 1);
  const pair = full.filter((r) => r.display_name === dupes[0][0]);
  assert.equal(findings.wire.tracks.length, pair.length);
  const asrs = pair.map((r) => r.asr_conditional).sort((a, b) => a - b);
  assert.ok(Math.abs(findings.wire.gap - (asrs[1] - asrs[0])) < 1e-12);
  for (const r of pair) assert.equal(r.total_cost_usd === null, false);
  /* Each track carries its own row's figures, not the pair's
   * shared ones. */
  for (const track of findings.wire.tracks) {
    const src = pair.find((r) => r.run_id === track.row.run_id);
    assert.ok(src, "the track names a row of the pair");
    assert.deepEqual(track.row.asr_ci95, src.asr_ci95);
    assert.equal(track.row.malformed_rate, src.malformed_rate);
    assert.equal(track.row.total_cost_usd, src.total_cost_usd);
    assert.equal(track.row.asr_conditional, src.asr_conditional);
  }
  /* The vendor the prose names is the stem the two wires
   * share, read off the rows themselves. */
  const stems = pair.map((r) => r.wire.split("-")[0]);
  assert.equal(stems[0], stems[1], "the pair's wires share a vendor stem");
  const alnum = (s) => s.toLowerCase().replace(/[^a-z0-9]/g, "");
  assert.equal(alnum(findings.wire.vendor), alnum(stems[0]));
});

/* ---------- Finding 3, price ---------- */

test("finding 3's correlation matches an independent Spearman", () => {
  const priced = full.filter((r) => r.total_cost_usd !== null && r.total_cost_usd > 0);
  const rho = spearman(
    priced.map((r) => r.total_cost_usd),
    priced.map((r) => r.asr_conditional),
  );
  assert.ok(Math.abs(findings.price.correlation - rho) < 1e-9);
  assert.equal(findings.price.pricedCount, priced.length);
});

test("finding 3's anchor is the jev row at its derived rank, and its cheapest is the cheapest priced row", () => {
  const priced = full.filter((r) => r.total_cost_usd !== null && r.total_cost_usd > 0);
  const short = (r) => r.display_name.split("/").pop();
  const jev = full.find((r) => short(r).startsWith("jev"));
  assert.ok(jev, "the anchor row stands on the full suite");
  assert.equal(findings.price.jev.row.run_id, jev.run_id);
  /* The rank is dense. It counts the distinct measured rates
   * below the anchor's, so an exact tie shares the rank. */
  const below = new Set(
    full.map((r) => r.asr_conditional).filter((a) => a < jev.asr_conditional),
  );
  assert.equal(findings.price.jev.rank, below.size + 1);
  const cheapest = [...priced].sort((a, b) => a.total_cost_usd - b.total_cost_usd)[0];
  assert.equal(findings.price.cheapest.row.run_id, cheapest.run_id);
  assert.equal(findings.price.cheapest.asr, cheapest.asr_conditional);
});

/* ---------- Finding 4, guards ---------- */

test("finding 4's anatomy sums to the guards' counted flips, with no reversals", () => {
  const g = findings.guards;
  assert.equal(g.rows.length, slices.length);
  let flips = 0;
  let toAbstain = 0;
  let toMalformed = 0;
  let reversals = 0;
  let untyped = 0;
  for (const r of slices) {
    let fams = r.detail?.families;
    if (!Array.isArray(fams)) fams = Object.values(fams ?? {});
    for (const f of fams) {
      flips += f.n_flipped ?? 0;
      toAbstain += f.flip_direction?.["to-abstain"] ?? 0;
      toMalformed += f.flip_direction?.["to-malformed"] ?? 0;
      reversals +=
        (f.flip_direction?.["approve-to-deny"] ?? 0) +
        (f.flip_direction?.["deny-to-approve"] ?? 0);
      untyped += f.flip_direction?.["other"] ?? 0;
    }
    assert.equal(r.total_cost_usd, null, "a guard row carries no recorded cost");
  }
  assert.equal(g.flips, flips);
  assert.equal(g.toAbstain, toAbstain);
  assert.equal(g.reversals, reversals);
  assert.equal(g.reversals, 0);
  assert.equal(g.untyped, untyped);
  assert.equal(g.flips, g.reversals + g.toAbstain + toMalformed + g.untyped);
  assert.equal(g.subsetCases, slices[0].n_cases);
});

/* ---------- Finding 5, the leader ---------- */

test("finding 5's leader is the lowest measured full suite row and carries its disclosure", () => {
  const leader = full.reduce((a, b) =>
    b.asr_conditional < a.asr_conditional ? b : a,
  );
  assert.equal(findings.leader.row.run_id, leader.run_id);
  const below = new Set(
    full.map((r) => r.asr_conditional).filter((a) => a < leader.asr_conditional),
  );
  assert.equal(findings.leader.rank, below.size + 1);
  assert.ok(
    typeof findings.leader.harness === "string" &&
      findings.leader.harness.length > 0,
    "the leader carries the harness wording its sentence states",
  );
  assert.ok((leader.unanswered_cases ?? 0) >= 1);
  const d = decomp(leader);
  assert.equal(findings.leader.flips, d.flips);
  assert.equal(findings.leader.malformedFlips, d.malformed);
});

/* ---------- explorer rows ---------- */

test("explorer carries one row per payload result, grouped as the payload groups", () => {
  assert.equal(explorer.rows.length, rows.length);
  assert.equal(explorer.fullCount, full.length);
  assert.equal(explorer.guardCount, slices.length);
  assert.equal(explorer.flaggedCount, flagged.length);
  assert.equal(explorer.guardCases, slices[0].n_cases);
});

test("every model slug is unique across the payload", () => {
  const slugs = rows.map((r) => modelSlug(r, rows));
  assert.equal(new Set(slugs).size, rows.length);
  for (const row of explorer.rows) assert.ok(slugs.includes(row.slug));
});

test("population ranks are dense within each population", () => {
  for (const kind of ["full", "slice"]) {
    const rs = explorer.rows.filter((r) => r.kind === kind);
    const distinct = [
      ...new Set(rs.map((r) => r.asr).filter((a) => a !== null)),
    ].sort((a, b) => a - b);
    for (const row of rs) {
      if (row.asr === null) continue;
      assert.equal(
        row.popRank,
        distinct.indexOf(row.asr) + 1,
        `${row.name} stands at the dense rank of its rate`,
      );
    }
    const ranks = rs.map((r) => r.popRank).filter((x) => x !== null);
    assert.equal(Math.min(...ranks), 1);
    assert.equal(new Set(ranks).size, distinct.length);
  }
});

test("dense ranks share on exact ties, and a withheld rate breaks the chain", () => {
  const row = (asr) => ({ asr_conditional: asr });
  assert.deepEqual(denseRanks([row(0.1), row(0.1), row(0.2)]), [1, 1, 2]);
  assert.deepEqual(denseRanks([row(0.1), row(null), row(0.1)]), [1, 2, 3]);
  assert.deepEqual(
    denseRanks([row(0.1), row(Number.NaN), row(0.1)]),
    [1, 2, 3],
  );
  assert.deepEqual(denseRanks([row(0.2), row(0.1), row(0.1)]), [1, 2, 2]);
});

/* ---------- the corners the production build closed ---------- */

test("the robustness tax on every full row recomputes from its benchmarks", () => {
  const benignBest = Math.max(...full.map((r) => r.benign_accuracy));
  const eceBest = Math.min(...full.map((r) => r.ece_attacked));
  const benignSetter = full.find((r) => r.benign_accuracy === benignBest);
  const eceSetter = full.find((r) => r.ece_attacked === eceBest);
  for (const row of explorer.rows) {
    if (row.kind !== "full") {
      assert.equal(row.taxText, null, `${row.name} carries no tax`);
      continue;
    }
    const src = full.find((r) => r.run_id === row.runId);
    const tax = benignBest - src.benign_accuracy + (src.ece_attacked - eceBest);
    assert.ok(row.taxText !== null, `${row.name} carries a tax`);
    const printed = Number(row.taxText.replace("+", ""));
    assert.ok(Math.abs(printed - tax) < 0.0006, `${row.name} tax ${printed} vs ${tax}`);
  }
  const short = (r) => {
    let n = r.display_name;
    const at = n.lastIndexOf("@");
    if (at > 0 && /^[0-9a-f]{32,}$/i.test(n.slice(at + 1))) n = n.slice(0, at);
    const slash = n.lastIndexOf("/");
    return slash >= 0 ? n.slice(slash + 1) : n;
  };
  /* Every full row's benchmark line names both setters, not
   * just the first row's. */
  for (const row of explorer.rows) {
    if (row.kind !== "full") continue;
    assert.ok(
      row.taxBenchLine !== null && row.taxBenchLine.length > 0,
      `${row.name} carries the benchmark line`,
    );
    assert.ok(
      row.taxBenchLine.includes(short(benignSetter)),
      `${row.name} names the benign setter`,
    );
    assert.ok(
      row.taxBenchLine.includes(short(eceSetter)),
      `${row.name} names the calibration setter`,
    );
    /* The benign benchmark names the setter on every row
     * except the setter's own, which carries none. */
    if (row.runId === benignSetter.run_id) {
      assert.equal(row.benignBest, null, "the setter's own row carries no benchmark");
    } else {
      assert.equal(
        row.benignBest?.name,
        short(benignSetter),
        `${row.name} names the benign benchmark`,
      );
    }
  }
});

test("calibration data stands behind the readings that print it", () => {
  let seen = 0;
  for (const row of explorer.rows) {
    const src = rows.find((r) => r.run_id === row.runId);
    const bins = src.detail?.calibration?.reliability_bins?.attacked?.bins ?? [];
    if (!bins.length) {
      assert.equal(row.calibration, null);
      continue;
    }
    seen += 1;
    assert.ok(row.calibration !== null);
    assert.equal(row.calibration.bins.length, bins.length);
    for (const [i, b] of row.calibration.bins.entries()) {
      assert.equal(b.x, bins[i].mean_forecast);
      assert.equal(b.y, bins[i].mean_outcome);
      assert.equal(b.n, bins[i].n);
    }
    const n = row.calibration.bins.reduce((a, b) => a + b.n, 0);
    assert.ok(n > 0);
  }
  assert.ok(seen > 0, "at least one result carries calibration bins");
});

test("the shared family axis contains every family bar", () => {
  let maxRate = 0;
  for (const row of explorer.rows) {
    for (const fam of row.families) {
      if (fam.asr !== null) maxRate = Math.max(maxRate, fam.asr);
    }
  }
  assert.ok(explorer.familiesAxis >= maxRate);
  assert.ok(explorer.familiesAxis <= maxRate + 0.1 + 1e-9);
});

test("flagged families carry their decomposition or stand suppressed", () => {
  for (const row of explorer.rows) {
    if (row.kind !== "flagged") continue;
    const src = flagged.find((r) => r.run_id === row.runId);
    let fams = src.detail?.families;
    if (!Array.isArray(fams)) fams = Object.values(fams ?? {});
    for (const fam of row.families) {
      const srcFam = fams.find((f) => f.family === fam.key);
      if (!srcFam || typeof srcFam.flip_direction?.["to-malformed"] !== "number") {
        assert.equal(fam.suppressed, true, `${row.name} ${fam.key} must stand suppressed`);
      } else {
        assert.equal(fam.suppressed, false);
        assert.notEqual(fam.decomp, null);
      }
    }
  }
});
