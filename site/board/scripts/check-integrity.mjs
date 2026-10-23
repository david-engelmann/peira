#!/usr/bin/env node
/**
 * Build-time integrity gate. Runs after `next build` and fails
 * the build when the rendered page disagrees with the payload.
 *
 * Every check here is an independent reimplementation from the
 * payload JSON and the built HTML. Nothing is imported from the
 * app, so a bug in the app's formatting, counting, grouping, or
 * benchmark derivation cannot rubber-stamp itself.
 *
 * Checks
 *  1. Counts. The masthead counts equal the count of distinct
 *     models the board displays, keyed by display_name, the rule
 *     the data audit and the census converged on. The checker
 *     also computes the two neighbouring rules (adapter_version
 *     alone, and the (adapter_name, adapter_version) pair) and
 *     proves the printed numbers are neither: this payload
 *     carries both collisions (three models share version
 *     "1.0"; one model was measured on two wires), so the three
 *     rules give three different triples and only the display
 *     rule may match the page. All 36 pair-rows must still
 *     render (check 2).
 *  2. Rows. Each payload row renders exactly once, inside the
 *     group the payload's case base assigns it to, with its
 *     short name, its attack success value, and its compact
 *     interval as printed from the payload.
 *  3. Group sizes match the payload split (full, flagged,
 *     slices), all derived, none hard-coded here.
 *  4. Tax. Benchmarks derived from the full suite ranked cohort
 *     only; every taxed row in that cohort recomputes from those
 *     benchmarks within 0.0002; the page states both setters.
 *  5. Ties. The word tied appears exactly once in prose plus
 *     once per bracket; bracket count equals the independently
 *     recomputed within-group band count.
 *  6. Copy. Visible text holds no em dash, no semicolon, no
 *     colon, and never calls the flagged status by another name.
 *  7. The suite size appears on the page. No revision hash
 *     appears anywhere in the rendered text.
 *  8. Charts (round 9). The scatter section accounts for the
 *     whole board: plotted points equal the non-slice rows with
 *     a cost above zero, rail points equal the non-slice rows
 *     without one, no slice row appears, and every point's data
 *     attributes equal its payload cost and rate. The heatmap
 *     holds one cell per row and family, the not measured cells
 *     equal the payload's missing family pairs, the column
 *     order equals the descending mean rule computed here, and
 *     every printed cell value equals the payload rate under
 *     the cell format rule. The calibration panels render in
 *     attacked ECE order, rail and grid in the same order.
 */

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const payload = JSON.parse(readFileSync(join(root, "data/payload.json"), "utf8"));
const html = readFileSync(join(root, "out/index.html"), "utf8");

const failures = [];
const fail = (msg) => failures.push(msg);

/* ---------- independent derivations from the payload ---------- */

const key = (r) => `${r.adapter_name}${r.adapter_version}`;

/* Decimal-string formatting, ported independently. Percentages
 * are the value's decimal string scaled by 100 and rounded half
 * up at one decimal, the published board's formatting rule. */
function expandDec(value) {
  const s = String(value);
  if (!/[eE]/.test(s)) return s;
  const [mantissa, expStr] = s.split(/[eE]/);
  const exp = parseInt(expStr, 10);
  const neg = mantissa.startsWith("-");
  const body = neg ? mantissa.slice(1) : mantissa;
  const [ip, fp = ""] = body.split(".");
  const digits = ip + fp;
  const point = ip.length + exp;
  let out;
  if (point <= 0) out = "0." + "0".repeat(-point) + digits;
  else if (point >= digits.length) out = digits + "0".repeat(point - digits.length);
  else out = `${digits.slice(0, point)}.${digits.slice(point)}`;
  return (neg ? "-" : "") + out;
}
function shiftPt(decStr, places) {
  const neg = decStr.startsWith("-");
  const body = neg ? decStr.slice(1) : decStr;
  const [ip, fp = ""] = body.split(".");
  let digits = ip + fp;
  let point = ip.length + places;
  /* Leading zeros in the digit string shift the effective point;
   * strip them and move the point with them (0.0055 x100 is 0.55,
   * never 000.55). */
  let lead = 0;
  while (lead < digits.length - 1 && digits[lead] === "0") lead += 1;
  if (lead > 0) {
    digits = digits.slice(lead);
    point -= lead;
  }
  let out;
  if (point <= 0) out = "0." + "0".repeat(-point) + digits;
  else if (point >= digits.length) out = digits + "0".repeat(point - digits.length);
  else out = `${digits.slice(0, point)}.${digits.slice(point)}`;
  return (neg ? "-" : "") + out;
}
function quantHU(decStr, decimals) {
  const neg = decStr.startsWith("-");
  const body = neg ? decStr.slice(1) : decStr;
  const [ip, fp = ""] = body.split(".");
  const kept = fp.slice(0, decimals).padEnd(decimals, "0");
  const dropped = fp.slice(decimals);
  const digits = (ip + kept).split("").map(Number);
  if (dropped.length > 0 && dropped[0] >= "5") {
    let i = digits.length - 1;
    while (i >= 0 && digits[i] === 9) {
      digits[i] = 0;
      i -= 1;
    }
    if (i < 0) digits.unshift(1);
    else digits[i] += 1;
  }
  const joined = digits.join("");
  const intRaw = joined.slice(0, joined.length - decimals) || "0";
  const intOut = intRaw.replace(/^0+(?=\d)/, "");
  const fracOut = decimals > 0 ? joined.slice(joined.length - decimals) : "";
  return (neg ? "-" : "") + intOut + (decimals > 0 ? `.${fracOut}` : "");
}
const fmtPct = (v) => `${quantHU(shiftPt(expandDec(v), 2), 1)}%`;
const fmtPctFigure = (v) => quantHU(shiftPt(expandDec(v), 2), 1);
const fmtCiCompact = (ci) => `[${fmtPctFigure(ci[0])}, ${fmtPctFigure(ci[1])}]`;

/* The display interval derivation, ported independently from
 * the published renderer's rule: exact Wilson over the family
 * flipped counts when it rounds to the stored pair at four
 * decimals, else the stored pair. */
function wilsonI(hits, n) {
  if (n === 0) return [0, 0];
  const z = 1.96;
  const p = hits / n;
  const denom = 1 + (z * z) / n;
  const center = (p + (z * z) / (2 * n)) / denom;
  const half = (z * Math.sqrt((p * (1 - p)) / n + (z * z) / (4 * n * n))) / denom;
  return [Math.max(0, center - half), Math.min(1, center + half)];
}
const countI = (x) =>
  typeof x === "number" && Number.isInteger(x) && x >= 0 ? x : null;
function displayCiI(row) {
  const pair = row.asr_ci95;
  if (!pair) return null;
  const detail = row.detail && typeof row.detail === "object" ? row.detail : {};
  const famsRaw = detail.families;
  let entries = [];
  if (Array.isArray(famsRaw)) entries = famsRaw;
  else if (famsRaw && typeof famsRaw === "object") entries = Object.values(famsRaw);
  const fams = entries.filter(
    (f) => f !== null && typeof f === "object" && !Array.isArray(f),
  );
  if (fams.length === 0) return pair;
  let total = 0;
  for (const fam of fams) {
    const nf = countI(fam.n_flipped);
    if (nf === null) return pair;
    total += nf;
  }
  const n = countI(row.n_eligible);
  if (n === null || n === 0) return pair;
  const [lo, hi] = wilsonI(total, n);
  const q = (v) => quantHU(expandDec(v), 4);
  if (q(lo) === q(pair[0]) && q(hi) === q(pair[1])) return [lo, hi];
  return pair;
}

/* Formatter fixtures from the published board. These pin the
 * boundary behavior the naive float formatter gets wrong. */
for (const [v, expected] of [
  [0.0055, "0.6%"],
  [0.1095, "11.0%"],
  [0.0245, "2.5%"],
  [0.1065, "10.7%"],
]) {
  if (fmtPct(v) !== expected) {
    fail(`formatter fixture: fmtPct(${v}) is ${fmtPct(v)}, published ${expected}`);
  }
}
const shortName = (r) => {
  let name = r.display_name;
  const at = name.lastIndexOf("@");
  if (at > 0 && /^[0-9a-f]{32,}$/i.test(name.slice(at + 1))) {
    name = name.slice(0, at);
  }
  const slash = name.lastIndexOf("/");
  return slash >= 0 ? name.slice(slash + 1) : name;
};

const ranked = payload.ranked;
const unranked = payload.unranked;
const fullCases = Math.max(...ranked.map((r) => r.n_cases));
const fullCohort = ranked.filter((r) => r.n_cases === fullCases);
const sliceCohort = ranked.filter((r) => r.n_cases < fullCases);

const counts = {
  results: ranked.length + unranked.length,
  tested: new Set([...ranked, ...unranked].map((r) => r.display_name)).size,
  ranked: new Set(ranked.map((r) => r.display_name)).size,
  flagged: new Set(unranked.map((r) => r.display_name)).size,
};
/* The two neighbouring identity rules, computed only to prove
 * the printed counts follow neither of them. */
const versionCounts = {
  tested: new Set([...ranked, ...unranked].map((r) => r.adapter_version)).size,
  ranked: new Set(ranked.map((r) => r.adapter_version)).size,
  flagged: new Set(unranked.map((r) => r.adapter_version)).size,
};
const pairCounts = {
  tested: new Set([...ranked, ...unranked].map(key)).size,
  ranked: new Set(ranked.map(key)).size,
  flagged: new Set(unranked.map(key)).size,
};

/** Greedy common-intersection bands, ported independently. */
function bandsOf(rows) {
  const bands = [];
  let band = [];
  let lo = 0;
  let hi = 0;
  const close = () => {
    if (band.length >= 2) bands.push(band.map((r) => r));
    band = [];
  };
  for (const row of rows) {
    if (row.asr_conditional === null || !row.asr_ci95) {
      close();
      continue;
    }
    const [rlo, rhi] = row.asr_ci95;
    if (band.length > 0 && (rlo > hi || lo > rhi)) close();
    if (band.length > 0) {
      lo = Math.max(lo, rlo);
      hi = Math.min(hi, rhi);
    } else {
      lo = rlo;
      hi = rhi;
    }
    band.push(row);
  }
  close();
  return bands;
}
const expectedBands =
  bandsOf(fullCohort).length + bandsOf(sliceCohort).length;

/* ---------- visible text extraction ---------- */

function visibleText(source) {
  return source
    .replace(/<script[\s\S]*?<\/script>/g, " ")
    .replace(/<style[\s\S]*?<\/style>/g, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&#x27;|&apos;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/\s+/g, " ");
}
const text = visibleText(html);

/* ---------- 1. counts ---------- */

const countsMatch = text.match(
  /board holds ([\d,]+) results from ([\d,]+) models\. ([\d,]+) models are ranked and ([\d,]+) are flagged\./,
);
if (!countsMatch) {
  fail("masthead counts sentence not found in rendered text");
} else {
  const printed = countsMatch.slice(1).map((s) => Number(s.replace(/,/g, "")));
  const expected = [counts.results, counts.tested, counts.ranked, counts.flagged];
  if (JSON.stringify(printed) !== JSON.stringify(expected)) {
    fail(
      `counts mismatch: page prints ${printed.join("/")}, display-name count of payload is ${expected.join("/")}`,
    );
  }
  /* Discrimination proof. The printed triple must not be the
   * version-only triple (the old renderer's collapse) nor the
   * pair triple (which counts the two-wire model twice). This
   * payload carries both collisions, so all three triples
   * differ; if a future payload removes a collision, this gate
   * fails loudly rather than letting the proof go silent. */
  const triple = (c) => [c.tested, c.ranked, c.flagged].join("/");
  const printedTriple = printed.slice(1).join("/");
  if (printedTriple === triple(versionCounts)) {
    fail(
      `counts follow the version-only rule (${printedTriple}); the three "1.0" models have collapsed into one`,
    );
  }
  if (printedTriple === triple(pairCounts)) {
    fail(
      `counts follow the pair rule (${printedTriple}); the two-wire model is counted twice`,
    );
  }
  if (triple(versionCounts) === triple(counts) || triple(pairCounts) === triple(counts)) {
    fail(
      "the payload no longer carries both identity collisions, so this gate cannot prove the counting rule from the numbers alone",
    );
  }
  /* The two-wire explainer must appear exactly when a model
   * carries more than one result. */
  const multi = new Map();
  for (const r of [...ranked, ...unranked]) {
    multi.set(r.display_name, (multi.get(r.display_name) ?? 0) + 1);
  }
  const multiCount = [...multi.values()].filter((n) => n > 1).length;
  const explains = /measured on two wires/.test(text);
  if (multiCount > 0 && !explains) {
    fail("a model carries two results but the two-wire explainer is missing");
  }
  if (multiCount === 0 && explains) {
    fail("the two-wire explainer prints but no model carries two results");
  }
}

/* ---------- 2 and 3. rows and groups ---------- */

function groupBlocks(source) {
  const blocks = {};
  const re = /data-group="(full|flagged|slices)"/g;
  const marks = [];
  let m;
  while ((m = re.exec(source)) !== null) marks.push([m[1], m.index]);
  marks.forEach(([id, start], i) => {
    const end = i + 1 < marks.length ? marks[i + 1][1] : source.length;
    blocks[id] = source.slice(start, end);
  });
  return blocks;
}
/* The ranking checks scope to the ranking section only. The
 * chart sections below it carry their own data-run-id carriers
 * (cells, points, panels) and are checked as check 8. */
const heatmapStart = html.indexOf('data-section="heatmap"');
const rankingHtml = heatmapStart >= 0 ? html.slice(0, heatmapStart) : html;
const blocks = groupBlocks(rankingHtml);
const expectedGroups = {
  full: fullCohort,
  flagged: unranked,
  slices: sliceCohort,
};
for (const [id, rows] of Object.entries(expectedGroups)) {
  const block = blocks[id];
  if (!block) {
    fail(`group ${id} missing from rendered page`);
    continue;
  }
  const renderedIds = [...block.matchAll(/data-run-id="([^"]+)"/g)].map(
    (m) => m[1],
  );
  if (renderedIds.length !== rows.length) {
    fail(
      `group ${id}: rendered ${renderedIds.length} rows, payload assigns ${rows.length}`,
    );
  }
  for (const row of rows) {
    if (!renderedIds.includes(row.run_id)) {
      fail(`group ${id}: payload row ${row.run_id} not rendered in its group`);
    }
  }
  // Per-row printed numbers, checked inside the group block with
  // a per-row slice of the text.
  for (const row of rows) {
    const marker = `data-run-id="${row.run_id}"`;
    const start = block.indexOf(marker);
    if (start < 0) continue;
    const next = block.indexOf('data-run-id="', start + marker.length);
    const slice = visibleText(block.slice(start, next < 0 ? undefined : next));
    if (!slice.includes(shortName(row))) {
      fail(`row ${row.run_id}: short name ${shortName(row)} not in its block`);
    }
    if (row.asr_conditional !== null && !slice.includes(fmtPct(row.asr_conditional))) {
      fail(
        `row ${row.run_id}: value ${fmtPct(row.asr_conditional)} not in its block (block reads: ${slice.slice(0, 120)})`,
      );
    }
    const dci = displayCiI(row);
    if (dci && !slice.includes(fmtCiCompact(dci))) {
      fail(`row ${row.run_id}: display interval ${fmtCiCompact(dci)} not in its block`);
    }
  }
}
const totalRendered = [...rankingHtml.matchAll(/data-run-id="/g)].length;
if (totalRendered !== counts.results) {
  fail(`rendered rows ${totalRendered}, payload rows ${counts.results}`);
}

/* ---------- 4. tax benchmarks ---------- */

let benignSetter = fullCohort[0];
let eceSetter = fullCohort[0];
for (const row of fullCohort) {
  if (row.benign_accuracy > benignSetter.benign_accuracy) benignSetter = row;
  if (row.ece_attacked < eceSetter.ece_attacked) eceSetter = row;
}
let taxChecked = 0;
let taxMaxDev = 0;
for (const row of fullCohort) {
  if (row.robustness_tax === null || row.robustness_tax === undefined) continue;
  const recomputed =
    benignSetter.benign_accuracy -
    row.benign_accuracy +
    (row.ece_attacked - eceSetter.ece_attacked);
  const dev = Math.abs(recomputed - row.robustness_tax);
  taxMaxDev = Math.max(taxMaxDev, dev);
  taxChecked += 1;
  if (dev > 0.0002) {
    fail(
      `tax mismatch on ${row.run_id}: payload ${row.robustness_tax}, recomputed ${recomputed.toFixed(4)} from full-cohort benchmarks`,
    );
  }
}
if (taxChecked < 3) {
  fail(`only ${taxChecked} taxed rows recomputed; the gate requires at least 3`);
}
for (const setter of [benignSetter, eceSetter]) {
  if (!text.includes(shortName(setter))) {
    fail(`tax benchmark setter ${shortName(setter)} not stated on the page`);
  }
}

/* ---------- 5. ties ---------- */

const railLabels = [...html.matchAll(/class="rail-label"/g)].length;
if (railLabels !== expectedBands) {
  fail(`bracket labels ${railLabels}, independently computed bands ${expectedBands}`);
}
const tiedCount = (text.match(/tied/g) ?? []).length;
if (tiedCount !== expectedBands + 1) {
  fail(
    `the word tied appears ${tiedCount} times in visible text; expected ${expectedBands} brackets plus one sentence`,
  );
}

/* ---------- 6. copy ---------- */

if (text.includes("—")) fail("visible text contains an em dash");
if (text.includes(";")) fail("visible text contains a semicolon");
if (text.includes(":")) fail("visible text contains a colon");
if (/unranked/i.test(text)) fail("visible text uses the status synonym unranked");
if (/no rank/i.test(text)) fail("visible text uses the status synonym no rank");
if (/NaN|undefined/.test(text)) {
  fail("visible text contains NaN or undefined (a missing payload field leaked)");
}

/* ---------- 7. suite size and hashes ---------- */

const suiteStr = fullCases.toLocaleString("en-US");
if (!text.includes(suiteStr)) {
  fail(`suite size ${suiteStr} does not appear on the page`);
}
if (/[0-9a-f]{40}/.test(text)) {
  fail("a 40 character revision hash appears in rendered text");
}

/* ---------- 8. charts ---------- */

function sectionSlice(name, nextName) {
  const start = html.indexOf(`data-section="${name}"`);
  if (start < 0) return null;
  const end = nextName
    ? html.indexOf(`data-section="${nextName}"`, start)
    : html.length;
  return html.slice(start, end < 0 ? html.length : end);
}
function attr(tag, name) {
  const m = tag.match(new RegExp(`${name}="([^"]*)"`));
  return m ? m[1] : null;
}
const allRows = [...ranked, ...unranked];
const rowById = new Map(allRows.map((r) => [r.run_id, r]));

/* Scatter accounting. */
const scatterHtml = sectionSlice("scatter", "calibration");
if (!scatterHtml) {
  fail("scatter section missing from rendered page");
} else {
  const nonSlice = allRows.filter((r) => r.n_cases === fullCases);
  const plottedRows = nonSlice.filter(
    (r) => r.total_cost_usd !== null && r.total_cost_usd > 0,
  );
  const plottedIds = new Set(plottedRows.map((r) => r.run_id));
  const railIds = new Set(
    nonSlice.filter((r) => !plottedIds.has(r.run_id)).map((r) => r.run_id),
  );
  const pointTags = [...scatterHtml.matchAll(/<g[^>]*>/g)]
    .map((m) => m[0])
    .filter((t) => t.includes('class="scatter-point"'));
  const seen = { plot: new Map(), rail: new Map() };
  for (const tag of pointTags) {
    const kind = attr(tag, "data-scatter");
    const id = attr(tag, "data-run-id");
    if (!kind || !id || !seen[kind]) {
      fail(`scatter point with missing data attributes: ${tag.slice(0, 80)}`);
      continue;
    }
    seen[kind].set(id, (seen[kind].get(id) ?? 0) + 1);
    const row = rowById.get(id);
    if (!row) {
      fail(`scatter point for unknown row ${id}`);
      continue;
    }
    if (Number(attr(tag, "data-asr")) !== row.asr_conditional) {
      fail(`scatter point ${id}: data-asr disagrees with the payload`);
    }
    const costAttr = attr(tag, "data-cost");
    const expectedCost = row.total_cost_usd === null ? "" : String(row.total_cost_usd);
    if (costAttr !== expectedCost) {
      fail(`scatter point ${id}: data-cost ${costAttr}, payload ${expectedCost}`);
    }
  }
  for (const [kind, ids] of [
    ["plot", plottedIds],
    ["rail", railIds],
  ]) {
    for (const id of ids) {
      /* Both the wide and the phone variant render the point. */
      if (seen[kind].get(id) !== 2) {
        fail(
          `scatter ${kind} point ${id} rendered ${seen[kind].get(id) ?? 0} times, expected 2 (wide and phone)`,
        );
      }
    }
    for (const id of seen[kind].keys()) {
      if (!ids.has(id)) fail(`scatter ${kind} holds unexpected row ${id}`);
    }
  }
  for (const row of sliceCohort) {
    if (scatterHtml.includes(`data-run-id="${row.run_id}"`)) {
      fail(`slice row ${row.run_id} appears in the scatter section`);
    }
  }
  if (!scatterHtml.includes("Peira decision robustness board")) {
    fail("scatter section carries no identification line (SF-01)");
  }
}

/* Heatmap accounting. */
const heatHtml = sectionSlice("heatmap", "scatter");
if (!heatHtml) {
  fail("heatmap section missing from rendered page");
} else {
  const famEntries = (r) =>
    r.detail && typeof r.detail === "object" && r.detail.families
      ? Object.entries(r.detail.families)
      : [];
  const sums = new Map();
  for (const r of allRows) {
    for (const [k, f] of famEntries(r)) {
      if (f.asr === null || f.asr === undefined) continue;
      const acc = sums.get(k) ?? { total: 0, n: 0 };
      acc.total += f.asr;
      acc.n += 1;
      sums.set(k, acc);
    }
  }
  const expectedOrder = [...sums.entries()]
    .map(([k, acc]) => ({ k, mean: acc.total / acc.n }))
    .sort((a, b) => b.mean - a.mean || (a.k < b.k ? -1 : 1))
    .map((e) => e.k);
  const headTags = [...heatHtml.matchAll(/<div[^>]*>/g)]
    .map((m) => m[0])
    .filter((t) => t.includes('class="heat-head"'));
  const renderedOrder = headTags.map((t) => attr(t, "data-family"));
  if (JSON.stringify(renderedOrder) !== JSON.stringify(expectedOrder)) {
    fail(
      `heatmap column order ${renderedOrder.join(",")} differs from the descending mean rule ${expectedOrder.join(",")}`,
    );
  }
  const fmtCell = (v) => {
    const pct = v * 100;
    if (pct > 0 && pct < 0.5) return "<1";
    return String(Math.round(pct));
  };
  const cellRe = /<div[^>]*class="heat-cell[^"]*"[^>]*>([^<]*)<\/div>/g;
  let cellCount = 0;
  let naCount = 0;
  for (const m of heatHtml.matchAll(cellRe)) {
    cellCount += 1;
    const tag = m[0].slice(0, m[0].indexOf(">") + 1);
    const id = attr(tag, "data-run-id");
    const famKey = attr(tag, "data-family");
    const row = rowById.get(id);
    if (!row) {
      fail(`heatmap cell for unknown row ${id}`);
      continue;
    }
    const fam = famEntries(row).find(([k]) => k === famKey)?.[1];
    const printed = m[1]
      .trim()
      .replace(/&lt;/g, "<")
      .replace(/&gt;/g, ">")
      .replace(/&amp;/g, "&");
    if (!fam || fam.asr === null || fam.asr === undefined) {
      naCount += 1;
      if (attr(tag, "data-na") !== "true" || printed !== "·") {
        fail(`heatmap cell ${id}/${famKey} should be a dotted not measured cell`);
      }
    } else {
      if (Number(attr(tag, "data-asr")) !== fam.asr) {
        fail(`heatmap cell ${id}/${famKey}: data-asr disagrees with the payload`);
      }
      if (printed !== fmtCell(fam.asr)) {
        fail(
          `heatmap cell ${id}/${famKey} prints ${printed}, the payload rate formats to ${fmtCell(fam.asr)}`,
        );
      }
    }
  }
  const expectedCells = allRows.length * expectedOrder.length;
  if (cellCount !== expectedCells) {
    fail(`heatmap holds ${cellCount} cells, expected ${expectedCells}`);
  }
  let expectedNa = 0;
  for (const r of allRows) {
    const carried = new Set(famEntries(r).map(([k]) => k));
    for (const k of expectedOrder) if (!carried.has(k)) expectedNa += 1;
  }
  if (naCount !== expectedNa) {
    fail(`heatmap holds ${naCount} not measured cells, payload implies ${expectedNa}`);
  }
  const nameCount = [...heatHtml.matchAll(/class="heat-name"/g)].length;
  if (nameCount !== allRows.length) {
    fail(`heatmap holds ${nameCount} row names, expected ${allRows.length}`);
  }
  if (!heatHtml.includes("Peira decision robustness board")) {
    fail("heatmap section carries no identification line (SF-01)");
  }
}

/* Calibration accounting. */
const calHtml = sectionSlice("calibration", null);
if (!calHtml) {
  fail("calibration section missing from rendered page");
} else {
  const eceOf = (r) => {
    const cal =
      r.detail && typeof r.detail === "object" ? r.detail.calibration : null;
    const ece = cal && cal.attacked ? cal.attacked.ece : null;
    return ece ?? r.ece_attacked ?? Infinity;
  };
  const expectedCalOrder = [...allRows]
    .sort((a, b) => {
      const ea = eceOf(a);
      const eb = eceOf(b);
      if (ea !== eb) return ea - eb;
      return a.display_name < b.display_name ? -1 : 1;
    })
    .map((r) => r.run_id);
  const panelTags = [...calHtml.matchAll(/<article[^>]*>/g)]
    .map((m) => m[0])
    .filter((t) => t.includes('class="cal-panel'));
  const panelOrder = panelTags.map((t) => attr(t, "data-run-id"));
  if (JSON.stringify(panelOrder) !== JSON.stringify(expectedCalOrder)) {
    fail("calibration panels are not in attacked ECE order");
  }
  const railOrder = [...calHtml.matchAll(/data-rail-for="([^"]+)"/g)].map(
    (m) => m[1],
  );
  if (JSON.stringify(railOrder) !== JSON.stringify(expectedCalOrder)) {
    fail("calibration rail order differs from the panel order");
  }
  if (!calHtml.includes("Peira decision robustness board")) {
    fail("calibration section carries no identification line (SF-01)");
  }
}

/* ---------- verdict ---------- */

if (failures.length > 0) {
  console.error(`integrity check FAILED with ${failures.length} problem(s):`);
  for (const f of failures) console.error(`  - ${f}`);
  process.exit(1);
}
console.log(
  `integrity check passed: ${counts.results} rows, counts ${counts.tested}/${counts.ranked}/${counts.flagged}, ${taxChecked} taxes recomputed (max deviation ${taxMaxDev.toFixed(5)}), ${expectedBands} tie brackets`,
);
