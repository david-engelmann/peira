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
 *  1. Counts. The masthead counts equal the pair-rule count of
 *     the payload, identity (adapter_name, adapter_version).
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
  /board holds ([\d,]+) results from ([\d,]+) models, counted by adapter and version\. ([\d,]+) are ranked and ([\d,]+) are flagged\./,
);
if (!countsMatch) {
  fail("masthead counts sentence not found in rendered text");
} else {
  const printed = countsMatch.slice(1).map((s) => Number(s.replace(/,/g, "")));
  const expected = [counts.results, counts.tested, counts.ranked, counts.flagged];
  if (JSON.stringify(printed) !== JSON.stringify(expected)) {
    fail(
      `counts mismatch: page prints ${printed.join("/")}, pair-rule count of payload is ${expected.join("/")}`,
    );
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
const blocks = groupBlocks(html);
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
const totalRendered = [...html.matchAll(/data-run-id="/g)].length;
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

/* ---------- verdict ---------- */

if (failures.length > 0) {
  console.error(`integrity check FAILED with ${failures.length} problem(s):`);
  for (const f of failures) console.error(`  - ${f}`);
  process.exit(1);
}
console.log(
  `integrity check passed: ${counts.results} rows, counts ${counts.tested}/${counts.ranked}/${counts.flagged}, ${taxChecked} taxes recomputed (max deviation ${taxMaxDev.toFixed(5)}), ${expectedBands} tie brackets`,
);
