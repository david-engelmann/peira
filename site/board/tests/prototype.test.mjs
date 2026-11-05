/**
 * Prototype fact tests. These recompute the figures the
 * redesign states, straight from data/payload.json with no
 * shared code, so a derivation drift in the prototype's data
 * layer fails here rather than printing on the page.
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const payload = JSON.parse(
  readFileSync(join(here, "..", "data", "payload.json"), "utf8"),
);
const rows = [...payload.ranked, ...payload.unranked];

function detailOf(row) {
  return row.detail && typeof row.detail === "object" ? row.detail : {};
}
function familyRecords(row) {
  const raw = detailOf(row).families;
  if (Array.isArray(raw)) return raw;
  if (raw && typeof raw === "object") return Object.values(raw);
  return [];
}
function isCount(x) {
  return typeof x === "number" && Number.isInteger(x) && x >= 0;
}
function decomp(row) {
  const fams = familyRecords(row);
  if (fams.length === 0) return null;
  let flips = 0;
  let malformed = 0;
  for (const fam of fams) {
    const fd =
      fam.flip_direction && typeof fam.flip_direction === "object"
        ? fam.flip_direction
        : {};
    const tm = fd["to-malformed"];
    if (!isCount(fam.n_flipped) || !isCount(tm)) return null;
    flips += fam.n_flipped;
    malformed += tm;
  }
  return { flips, malformed };
}
const fullCases = Math.max(...payload.ranked.map((r) => r.n_cases));
const full = payload.ranked
  .filter((r) => r.n_cases === fullCases)
  .sort((a, b) => a.asr_conditional - b.asr_conditional);
const slices = payload.ranked.filter((r) => r.n_cases < fullCases);
const flagged = payload.unranked;

test("the payload holds the published board's shape", () => {
  assert.equal(rows.length, 52);
  assert.equal(full.length, 41);
  assert.equal(slices.length, 6);
  assert.equal(flagged.length, 5);
  assert.equal(full[0].n_cases, 4701);
});

test("the leader is the cursor harness grok run", () => {
  const leader = full[0];
  assert.match(leader.display_name, /grok/i);
  assert.ok(Math.abs(leader.asr_conditional - 0.0891) < 0.0006);
  const d = decomp(leader);
  assert.equal(d.flips, 403);
  assert.equal(d.malformed, 0);
  assert.equal(leader.unanswered_cases, 1);
});

test("mercury carries its malformed decomposition", () => {
  const mercury = flagged.reduce((a, b) =>
    b.asr_conditional > a.asr_conditional ? b : a,
  );
  const d = decomp(mercury);
  assert.ok(Math.abs(d.malformed / d.flips - 0.856) < 0.002);
  const genuine = (d.flips - d.malformed) / mercury.n_eligible;
  assert.ok(Math.abs(genuine - 0.075) < 0.002);
  assert.ok(Math.abs(mercury.malformed_rate - 0.608) < 0.002);
});

test("the split pools as the derivation record states", () => {
  const pool = (list) => {
    let flips = 0;
    let malformed = 0;
    for (const row of list) {
      const d = decomp(row);
      assert.notEqual(d, null);
      flips += d.flips;
      malformed += d.malformed;
    }
    return { flips, malformed };
  };
  const ranked = pool(full);
  assert.equal(ranked.flips, 31944);
  assert.equal(ranked.malformed, 400);
  const flaggedPool = pool(flagged);
  assert.equal(flaggedPool.flips, 5757);
  assert.equal(flaggedPool.malformed, 3465);
});

test("exactly one model stands on two wires", () => {
  const byName = new Map();
  for (const row of full) {
    byName.set(row.display_name, [...(byName.get(row.display_name) ?? []), row]);
  }
  const pairs = [...byName.values()].filter((l) => l.length === 2);
  assert.equal(pairs.length, 1);
  const [a, b] = pairs[0];
  assert.notEqual(a.wire, b.wire);
  const gap = Math.abs(a.asr_conditional - b.asr_conditional);
  assert.ok(Math.abs(gap - 0.016) < 0.002);
  const costs = [a.total_cost_usd, b.total_cost_usd].sort((x, y) => x - y);
  assert.ok(Math.abs(costs[0] - 0.2922) < 0.001);
  assert.ok(Math.abs(costs[1] - 0.7537) < 0.001);
});

test("price carries no useful relationship with robustness", () => {
  const priced = full.filter((r) => r.total_cost_usd !== null && r.total_cost_usd > 0);
  assert.equal(priced.length, 31);
  const ranks = (vs) => {
    const order = vs.map((v, i) => ({ v, i })).sort((a, b) => a.v - b.v);
    const out = new Array(vs.length);
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
  const rx = ranks(priced.map((r) => r.total_cost_usd));
  const ry = ranks(priced.map((r) => r.asr_conditional));
  const n = priced.length;
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
  const rho = cov / Math.sqrt(vx * vy);
  assert.ok(Math.abs(rho - -0.15) < 0.01, `spearman ${rho}`);
});

test("the guards' counted flips hold no reversal", () => {
  const totals = {};
  let flips = 0;
  for (const row of slices) {
    for (const fam of familyRecords(row)) {
      if (isCount(fam.n_flipped)) flips += fam.n_flipped;
      const fd = fam.flip_direction ?? {};
      for (const [key, value] of Object.entries(fd)) {
        if (isCount(value)) totals[key] = (totals[key] ?? 0) + value;
      }
    }
  }
  assert.equal(flips, 121);
  assert.equal(totals["approve-to-deny"] ?? 0, 0);
  assert.equal(totals["deny-to-approve"] ?? 0, 0);
  assert.equal(totals["to-abstain"], 62);
  assert.equal(totals["other"], 59);
  assert.ok(slices.every((r) => r.benign_accuracy === 1));
});

test("the hero range derives from the ranked rows", () => {
  const asrs = full.map((r) => r.asr_conditional);
  assert.ok(Math.abs(Math.min(...asrs) - 0.0891) < 0.0006);
  assert.ok(Math.abs(Math.max(...asrs) - 0.3378) < 0.0006);
});
