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
 *     attributes equal its payload cost and rate. A rail point
 *     is covered once per variant, as a marker on the wide
 *     chart and as a list entry on the phone, which carries no
 *     rail column (mobile fix, 2026-10-26). The heatmap
 *     holds one cell per row and family, the not measured cells
 *     equal the payload's missing family pairs, the column
 *     order equals the descending mean rule computed here, and
 *     every printed cell value equals the payload rate under
 *     the cell format rule. The calibration panels render in
 *     attacked ECE order, rail and grid in the same order.
 *  9. Malformed (round 10). Bar rows equal the payload rows
 *     whose printed rate is not 0.0 percent, in worst first
 *     order, each printing its payload rate; the folded count
 *     in the summary line equals the payload's zero group; the
 *     admission line is labelled.
 * 10. Cards and model pages (round 10). Every card in the
 *     index and every per-model page is asserted field by
 *     field against the payload (headline figures, cost state
 *     words, latency, both calibration arms and the confidence
 *     coverage, severity rates and bases, spark bar data
 *     attributes in column order, the tax figure with both
 *     benchmark setters named or the untaxed statement, and
 *     the short provenance, with the ellipsis cut marker on
 *     every shortened hash, F-05), plus the rank statement, the
 *     own-page link, and the copy rules on every model page.
 * 11. Nav, compare, and ranking links (round 11). The section
 *     bar carries the eight labels in page order and every
 *     target id exists. The compare island's dataset, printed
 *     beside its section as a JSON script element, equals the
 *     payload on every row and every metric field, families
 *     included. The server-rendered default pair is the
 *     design's pair (the strongest full suite row against
 *     the first full suite row on the jev wire, the same
 *     reference rule lib/compare uses); its printed values equal the payload, its
 *     delta cells equal A minus B recomputed here and print
 *     under the delta format rules ported below, its winner
 *     dots sit on the stronger side, its family bars carry
 *     the payload rates in the column order, and no guard
 *     banner renders for it. Every ranking row carries the
 *     name link to its own model page.
 * 12. Cycle 7 surfaces. The eight Method subsection anchors
 *     exist on the rendered page. Every flagged model page's
 *     head description carries its flagged standing, and
 *     prints no attack success figure unless the payload's
 *     own family records derive a malformed majority for it,
 *     in which case the printed figure must be the payload's.
 *     Every slice page's head description names the abstain
 *     subset it was measured on. The built CSS carries the
 *     nav overflow cue's end-clearing rule and the Method
 *     subsection scroll-margin rule.
 * 13. C-5 companion surfaces. On the cost scatter, every
 *     flagged point's title and accessible name carry the
 *     figure's malformed decomposition beside the figure, or,
 *     where the payload's records do not derive one, state
 *     the flagged standing and no figure; a flagged entry row
 *     prints no figure. On the heatmap, every flagged cell
 *     title carries its family's decomposition, a flagged
 *     family without a derivable decomposition prints
 *     suppressed, and the notes under the grid state each
 *     flagged result's whole-row decomposition or that its
 *     figures are not stated.
 */

import { readFileSync, readdirSync } from "node:fs";
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

/* The flip decomposition derivation, ported independently
 * under the rules the app states for its own: null when the
 * row prints no attack success figure, when the records are
 * missing or unusable (a family whose malformed flips exceed
 * its flips included), or when the derived flips disagree
 * with the printed figure. Otherwise the malformed share of
 * the counted flips and the genuine flip rate over the row's
 * eligible cases. */
function familyRecordsI(row) {
  const detail = row.detail && typeof row.detail === "object" ? row.detail : {};
  const famsRaw = detail.families;
  let entries = [];
  if (Array.isArray(famsRaw)) entries = famsRaw;
  else if (famsRaw && typeof famsRaw === "object") entries = Object.values(famsRaw);
  return entries.filter(
    (f) => f !== null && typeof f === "object" && !Array.isArray(f),
  );
}
function decompI(row) {
  if (row.asr_conditional === null || row.asr_conditional === undefined) {
    return null;
  }
  const fams = familyRecordsI(row);
  if (fams.length === 0) return null;
  let flips = 0;
  let malformed = 0;
  for (const fam of fams) {
    const nf = countI(fam.n_flipped);
    const fd =
      fam.flip_direction !== null &&
      typeof fam.flip_direction === "object" &&
      !Array.isArray(fam.flip_direction)
        ? fam.flip_direction
        : null;
    const tm = fd ? countI(fd["to-malformed"]) : null;
    if (nf === null || tm === null) return null;
    if (tm > nf) return null;
    flips += nf;
    malformed += tm;
  }
  const n = countI(row.n_eligible);
  if (n === null || n === 0 || flips === 0) return null;
  if (Math.abs(flips / n - row.asr_conditional) > 0.001) return null;
  return { share: malformed / flips, genuine: (flips - malformed) / n };
}
/* The same derivation one family at a time, keyed by family
 * id: null for a family whose records are missing or unusable
 * or whose derived flips disagree with its printed attack
 * success, and zeros for a family with no counted flips. */
function famDecompI(row) {
  const out = new Map();
  for (const fam of familyRecordsI(row)) {
    if (typeof fam.family !== "string") continue;
    const nf = countI(fam.n_flipped);
    const fd =
      fam.flip_direction !== null &&
      typeof fam.flip_direction === "object" &&
      !Array.isArray(fam.flip_direction)
        ? fam.flip_direction
        : null;
    const tm = fd ? countI(fd["to-malformed"]) : null;
    const n = countI(fam.n_eligible);
    if (nf === null || tm === null || n === null || n === 0 || tm > nf) {
      out.set(fam.family, null);
      continue;
    }
    if (typeof fam.asr === "number" && Math.abs(nf / n - fam.asr) > 0.001) {
      out.set(fam.family, null);
      continue;
    }
    out.set(fam.family, {
      flips: nf,
      share: nf === 0 ? 0 : tm / nf,
      genuine: (nf - tm) / n,
    });
  }
  return out;
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
/* The ranking checks scope to the top of the page only. The
 * sections below it carry their own data-run-id carriers
 * (malformed rows, cells, points, panels, cards) and are
 * checked as checks 8 to 10. */
const malformedStart = html.indexOf('data-section="malformed"');
const heatmapStart = html.indexOf('data-section="heatmap"');
const rankingEnd =
  malformedStart >= 0 ? malformedStart : heatmapStart;
const rankingHtml = rankingEnd >= 0 ? html.slice(0, rankingEnd) : html;
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
/* Hash rule. Outside the model detail section, no revision
 * hash appears in rendered text at all: charts, tiles, and
 * prose never carry one (the name policy). Inside the model
 * detail section, the full display name stands on the card, so
 * a long hex run may appear there, but only as part of a row's
 * own display name. Any other long hex run in the page text
 * (a provenance hash printed in full, a hash borrowed into a
 * label) fails here. */
const modelsStart = html.indexOf('data-section="models"');
const methodStart = html.indexOf('data-section="method"');
const outsideModelsText =
  modelsStart >= 0 && methodStart > modelsStart
    ? visibleText(html.slice(0, modelsStart) + html.slice(methodStart))
    : text;
if (/[0-9a-f]{40}/.test(outsideModelsText)) {
  fail("a 40 character revision hash appears in rendered text outside the model cards");
}
for (const m of text.matchAll(/[0-9a-f]{40,}/g)) {
  if (![...ranked, ...unranked].some((r) => r.display_name.includes(m[0]))) {
    fail(
      `a long hex run in the page text is not part of any display name: ${m[0].slice(0, 16)}`,
    );
  }
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
const unrankedIds = new Set(unranked.map((r) => r.run_id));

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
  const entryTags = [...scatterHtml.matchAll(/<g[^>]*>/g)]
    .map((m) => m[0])
    .filter((t) => t.includes('class="scatter-entry"'));
  const entrySeen = new Map();
  for (const tag of entryTags) {
    const id = attr(tag, "data-entry-for");
    if (!id) {
      fail(`scatter entry with missing data attributes: ${tag.slice(0, 80)}`);
      continue;
    }
    entrySeen.set(id, (entrySeen.get(id) ?? 0) + 1);
    if (!plottedIds.has(id) && !railIds.has(id)) {
      fail(`scatter entry holds unexpected row ${id}`);
    }
  }
  for (const [kind, ids] of [
    ["plot", plottedIds],
    ["rail", railIds],
  ]) {
    for (const id of ids) {
      /* Both the wide and the phone variant render the point.
       * A plotted point stands as a marker in both variants.
       * A rail point stands as a marker on the wide chart and
       * as a list entry on the phone, which carries no rail
       * column (mobile fix, 2026-10-26): coverage is markers
       * plus entries, with at least the wide marker present. */
      const markers = seen[kind].get(id) ?? 0;
      if (kind === "plot") {
        if (markers !== 2) {
          fail(
            `scatter plot point ${id} rendered ${markers} times, expected 2 (wide and phone)`,
          );
        }
      } else {
        const covered = markers + (entrySeen.get(id) ?? 0);
        if (covered !== 2 || markers < 1) {
          fail(
            `scatter rail point ${id} covered ${covered} times (markers ${markers}, entries ${entrySeen.get(id) ?? 0}), expected 2 (wide marker and phone entry)`,
          );
        }
      }
    }
    for (const id of seen[kind].keys()) {
      if (!ids.has(id)) fail(`scatter ${kind} holds unexpected row ${id}`);
    }
  }
  for (const row of sliceCohort) {
    if (
      scatterHtml.includes(`data-run-id="${row.run_id}"`) ||
      scatterHtml.includes(`data-entry-for="${row.run_id}"`)
    ) {
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
    const shifted = shiftPt(expandDec(v), 2);
    if (v > 0 && Number(shifted) < 0.5) return "<1";
    return quantHU(shifted, 0);
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
      /* The not measured mark is "--" (design cycle 5, doctrine
       * D13: a bare glyph speck at cell size vanishes). */
      if (attr(tag, "data-na") !== "true" || printed !== "--") {
        fail(`heatmap cell ${id}/${famKey} should be a not measured cell printing --`);
      }
    } else if (unrankedIds.has(id) && (famDecompI(row).get(famKey) ?? null) === null) {
      /* A flagged family whose records do not derive its
       * decomposition prints no figure (C-5): the cell stands
       * suppressed, and its title says so. */
      if (
        attr(tag, "data-suppressed") !== "true" ||
        printed !== "--" ||
        attr(tag, "data-asr") !== null ||
        attr(tag, "data-na") !== null
      ) {
        fail(
          `heatmap cell ${id}/${famKey}: flagged family without a derivable decomposition must print suppressed (--) with no figure`,
        );
      }
      if (!(attr(tag, "title") ?? "").includes("attack success not stated")) {
        fail(
          `heatmap cell ${id}/${famKey}: suppressed cell title does not state that its figure is not stated`,
        );
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
      if (unrankedIds.has(id)) {
        /* A flagged cell that does print carries its family's
         * decomposition in its title (C-5). */
        const fd = famDecompI(row).get(famKey);
        const title = attr(tag, "title") ?? "";
        if (fd.flips === 0) {
          if (!title.includes("no counted flips")) {
            fail(
              `heatmap cell ${id}/${famKey}: flagged cell title does not state that the family counted no flips`,
            );
          }
        } else if (
          !title.includes(`genuine flip rate ${fmtPct(fd.genuine)}`) ||
          !title.includes(`${fmtPct(fd.share)} of counted flips to malformed output`)
        ) {
          fail(
            `heatmap cell ${id}/${famKey}: flagged cell title does not carry the family's decomposition (genuine ${fmtPct(fd.genuine)}, malformed share ${fmtPct(fd.share)})`,
          );
        }
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
const calHtml = sectionSlice("calibration", "models");
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

/* ---------- 9. malformed (round 10) ---------- */

const fmtIntC = (v) => v.toLocaleString("en-US");
const malHtml = sectionSlice("malformed", "heatmap");
if (!malHtml) {
  fail("malformed section missing from rendered page");
} else {
  const malText = visibleText(malHtml);
  const sortedMal = [...allRows].sort((a, b) => {
    const d = (b.malformed_rate ?? 0) - (a.malformed_rate ?? 0);
    if (d !== 0) return d;
    return a.display_name < b.display_name ? -1 : 1;
  });
  const printedMal = sortedMal.filter(
    (r) => r.malformed_rate !== null && fmtPct(r.malformed_rate) !== "0.0%",
  );
  const foldedMal = sortedMal.length - printedMal.length;
  const malTags = [
    ...malHtml.matchAll(/data-run-id="([^"]+)" data-malformed="([^"]*)"/g),
  ];
  if (malTags.length !== printedMal.length) {
    fail(
      `malformed chart holds ${malTags.length} bar rows, payload implies ${printedMal.length} printed rows`,
    );
  }
  malTags.forEach((m, i) => {
    const row = printedMal[i];
    if (!row) return;
    if (m[1] !== row.run_id) {
      fail(
        `malformed row ${i + 1} is ${m[1]}, worst-first order expects ${row.run_id}`,
      );
    }
    if (Number(m[2]) !== row.malformed_rate) {
      fail(`malformed row ${row.run_id}: data-malformed disagrees with the payload`);
    }
    const start = malHtml.indexOf(m[0]);
    const next = malHtml.indexOf('data-run-id="', start + m[0].length);
    const blockText = visibleText(
      malHtml.slice(start, next < 0 ? undefined : next),
    );
    if (!blockText.includes(fmtPct(row.malformed_rate))) {
      fail(
        `malformed row ${row.run_id}: printed rate ${fmtPct(row.malformed_rate)} not in its block`,
      );
    }
    const isFlagged = unranked.some((r) => r.run_id === row.run_id);
    if (isFlagged && !blockText.includes("Flagged")) {
      fail(`malformed row ${row.run_id}: flagged row carries no flagged tag`);
    }
    if (!isFlagged && blockText.includes("Flagged")) {
      fail(`malformed row ${row.run_id}: ranked row carries a flagged tag`);
    }
  });
  if (!malText.includes("admission limit")) {
    fail("malformed section does not label its admission line");
  }
  if (
    foldedMal > 0 &&
    !malText.includes(`${foldedMal} results printed a malformed rate of 0.0`)
  ) {
    fail(
      `malformed fold line does not state the folded count ${foldedMal}`,
    );
  }
  if (!malHtml.includes("Peira decision robustness board")) {
    fail("malformed section carries no identification line (SF-01)");
  }
}

/* ---------- 10. cards and model pages (round 10) ---------- */

const fmtEceC = (v) => quantHU(expandDec(v), 3);
const fmtTaxC = (v) =>
  (v < 0 ? "-" : "+") + quantHU(expandDec(Math.abs(v)), 3);
const fmtUsdC = (v) => `$${quantHU(expandDec(v), 2)}`;
const fmtMsC = (v) => `${quantHU(expandDec(v), 0)}ms`;
const fmtCiFullC = (ci) => `${fmtPct(ci[0])} to ${fmtPct(ci[1])}`;
const fmtCellC = (v) => {
  const shifted = shiftPt(expandDec(v), 2);
  if (v > 0 && Number(shifted) < 0.5) return "<1";
  return quantHU(shifted, 0);
};
const famEntriesC = (r) =>
  r.detail && typeof r.detail === "object" && r.detail.families
    ? Object.entries(r.detail.families)
    : [];
const lowerBoundC = (row) => {
  let costed = 0;
  let timed = 0;
  let seen = false;
  for (const [, f] of famEntriesC(row)) {
    if (f.n_costed_calls === null || f.n_costed_calls === undefined) return false;
    if (f.n_latency_calls === null || f.n_latency_calls === undefined) return false;
    costed += f.n_costed_calls;
    timed += f.n_latency_calls;
    seen = true;
  }
  return seen && costed < timed;
};
const slugOfC = (r, rows) => {
  const base = shortName(r);
  const slugify = (s) =>
    s
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "");
  const shared = rows.some(
    (o) => o.run_id !== r.run_id && shortName(o) === base,
  );
  const withWire = slugify(shared ? `${base}-${r.wire}` : base);
  const clash = rows.some(
    (o) =>
      o.run_id !== r.run_id && shortName(o) === base && o.wire === r.wire,
  );
  return clash ? `${withWire}-${slugify(r.run_id).slice(0, 8)}` : withWire;
};
/* The heatmap column order rule, recomputed for the spark bars. */
const famSumsC = new Map();
for (const r of allRows) {
  for (const [k, f] of famEntriesC(r)) {
    if (f.asr === null || f.asr === undefined) continue;
    const acc = famSumsC.get(k) ?? { total: 0, n: 0 };
    acc.total += f.asr;
    acc.n += 1;
    famSumsC.set(k, acc);
  }
}
const familyOrderC = [...famSumsC.entries()]
  .map(([k, acc]) => ({ k, mean: acc.total / acc.n }))
  .sort((a, b) => b.mean - a.mean || (a.k < b.k ? -1 : 1))
  .map((e) => e.k);

/**
 * The field-by-field card assertions, shared by the board's
 * index cards and the per-model pages so the two surfaces are
 * held to the same payload strings.
 */
function assertCardText(blockText, row, where) {
  const need = (s, what) => {
    if (s !== null && s !== undefined && s !== "" && !blockText.includes(s)) {
      fail(`${where} ${row.run_id}: ${what} "${s}" not in the card text`);
    }
  };
  need(shortName(row), "short name");
  need(row.display_name, "full display name");
  const dci = displayCiI(row);
  if (row.asr_conditional !== null) need(fmtPct(row.asr_conditional), "attack success");
  if (dci) need(fmtCiFullC(dci), "full interval");
  if (row.benign_accuracy !== null) need(fmtPct(row.benign_accuracy), "benign accuracy");
  if (row.malformed_rate !== null) need(fmtPct(row.malformed_rate), "malformed rate");
  /* The card prints no case counts: the suite's size is stated
   * once, in the method section (owner, 2026-10-25). Eligibility
   * still reaches the card through the rates themselves and the
   * severity bases below. */
  /* Cost state, in the words the card prints. */
  if (row.total_cost_usd === null || row.total_cost_usd === undefined) {
    need("no cost recorded", "unrecorded cost state");
  } else if (row.total_cost_usd === 0) {
    need("served locally", "local cost state");
  } else if (lowerBoundC(row)) {
    need(`≥ ${fmtUsdC(row.total_cost_usd)}`, "lower bound cost");
    need("a lower bound", "lower bound words");
  } else {
    need(fmtUsdC(row.total_cost_usd), "cost");
  }
  if (row.latency_ms_p50_attacked !== null) {
    need(fmtMsC(row.latency_ms_p50_attacked), "latency p50");
  }
  if (row.latency_ms_p95_attacked !== null) {
    need(fmtMsC(row.latency_ms_p95_attacked), "latency p95");
  }
  const cal =
    row.detail && typeof row.detail === "object" ? row.detail.calibration : null;
  if (cal) {
    if (cal.attacked?.ece !== null && cal.attacked?.ece !== undefined) {
      need(fmtEceC(cal.attacked.ece), "attacked ECE");
    }
    if (cal.attacked?.brier !== null && cal.attacked?.brier !== undefined) {
      need(fmtEceC(cal.attacked.brier), "attacked Brier");
    }
    if (cal.benign?.ece !== null && cal.benign?.ece !== undefined) {
      need(fmtEceC(cal.benign.ece), "benign ECE");
    }
    if (cal.benign?.brier !== null && cal.benign?.brier !== undefined) {
      need(fmtEceC(cal.benign.brier), "benign Brier");
    }
    const cov = cal.confidence_coverage?.attacked;
    if (cov !== null && cov !== undefined) need(fmtPct(cov), "confidence coverage");
  }
  const sevs =
    row.detail && typeof row.detail === "object" ? row.detail.severities : null;
  if (sevs) {
    for (const level of ["critical", "high", "medium"]) {
      const s = sevs[level];
      if (!s) continue;
      if (s.flip_rate_raw !== null && s.flip_rate_raw !== undefined) {
        need(fmtPct(s.flip_rate_raw), `${level} flip rate`);
      }
      if (s.n_eligible !== null && s.n_eligible !== undefined) {
        need(`of ${fmtIntC(s.n_eligible)} eligible`, `${level} base`);
      }
    }
  }
  /* Tax. A taxed card names both benchmark setters, from the
   * same full cohort derivation as check 4; an untaxed card
   * states that it carries none. */
  if (row.robustness_tax !== null && row.robustness_tax !== undefined) {
    need(fmtTaxC(row.robustness_tax), "robustness tax");
    need(shortName(benignSetter), "benign benchmark setter");
    need(shortName(eceSetter), "ECE benchmark setter");
  } else {
    need("No robustness tax", "untaxed statement");
  }
  /* Provenance, short form. */
  need(row.run_id, "run id");
  const prov = row.provenance ?? {};
  if (prov.pricing_version) need(prov.pricing_version, "pricing version");
  /* F-05 (convergence round 12): a shortened hash carries the
   * ellipsis cut marker, here and in the version line, whose
   * long hex runs truncate under the same rule ported below.
   * The full hash never prints (check 7 holds). */
  const provVersion = row.adapter_version.replace(
    /[0-9a-f]{13,}/g,
    (m) => `${m.slice(0, 12)}…`,
  );
  need(provVersion, "provenance version, cut marker on any cut");
  if (prov.manifest_sha256) {
    /* Cycle 6 (C6-14): the card provenance no longer prints the
     * manifest hash in any form. A truncated hash serves no
     * reader; the full hash never prints either. The check keys
     * on the hash's first eight hex digits, so the full value
     * and every truncation of eight or more digits fail on the
     * one test (red team RT-06: the earlier pair of exact-string
     * checks let variant truncations through). */
    if (blockText.includes(prov.manifest_sha256.slice(0, 8))) {
      fail(`${where} ${row.run_id}: manifest hash printed on the card`);
    }
  }
}

function assertCardAttrs(blockHtml, row, where) {
  /* Spark bars: every family the row carries renders with its
   * payload rate as a data attribute, in the heatmap's column
   * order; every family it does not carry renders as the
   * dotted not measured slot. */
  const carried = new Map(famEntriesC(row));
  const sparkTags = [
    ...blockHtml.matchAll(/data-family="([^"]+)"(?: data-asr="([^"]*)")?(?: data-na="true")?/g),
  ].map((m) => ({ fam: m[1], whole: m[0] }));
  const seenFams = sparkTags.map((t) => t.fam);
  if (JSON.stringify(seenFams) !== JSON.stringify(familyOrderC)) {
    fail(
      `${where} ${row.run_id}: spark families ${seenFams.join(",")} differ from the column order ${familyOrderC.join(",")}`,
    );
  }
  for (const tag of sparkTags) {
    const fam = carried.get(tag.fam);
    if (!fam || fam.asr === null || fam.asr === undefined) {
      if (!tag.whole.includes('data-na="true"')) {
        fail(`${where} ${row.run_id}: family ${tag.fam} should render as not measured`);
      }
    } else if (!tag.whole.includes(`data-asr="${fam.asr}"`)) {
      fail(`${where} ${row.run_id}: family ${tag.fam} data-asr disagrees with the payload`);
    }
  }
  /* Severities as data attributes. */
  for (const m of blockHtml.matchAll(
    /data-severity="([^"]+)" data-flip="([^"]*)" data-base="([^"]*)"/g,
  )) {
    const s = row.detail?.severities?.[m[1]];
    if (!s) {
      fail(`${where} ${row.run_id}: severity ${m[1]} not in the payload`);
      continue;
    }
    if (Number(m[2]) !== s.flip_rate_raw || Number(m[3]) !== s.n_eligible) {
      fail(`${where} ${row.run_id}: severity ${m[1]} attributes disagree with the payload`);
    }
  }
}

const modelsHtml = sectionSlice("models", "method");
if (!modelsHtml) {
  fail("models section missing from rendered page");
} else {
  const cardChunks = modelsHtml.split('data-card-for="').slice(1);
  if (cardChunks.length !== allRows.length) {
    fail(
      `models section holds ${cardChunks.length} cards, payload holds ${allRows.length} rows`,
    );
  }
  /* Ranks are dense within each group (admission rules, section
   * 4.1): the full suite group runs 1..N over fullCohort and the
   * slice group 1..M over sliceCohort, mirroring boardGroups(). */
  const rankOf = new Map();
  fullCohort.forEach((r, i) => rankOf.set(r.run_id, i + 1));
  sliceCohort.forEach((r, i) => rankOf.set(r.run_id, i + 1));
  for (const chunk of cardChunks) {
    const id = chunk.slice(0, chunk.indexOf('"'));
    const row = rowById.get(id);
    if (!row) {
      fail(`card for unknown row ${id}`);
      continue;
    }
    const blockText = visibleText(chunk);
    assertCardText(blockText, row, "card");
    assertCardAttrs(chunk, row, "card");
    /* The rank statement and the index summary figures. */
    const isFlagged = unranked.some((r) => r.run_id === id);
    const isSlice = !isFlagged && row.n_cases < fullCases;
    if (isFlagged) {
      if (!blockText.includes("Flagged")) {
        fail(`card ${id}: flagged card states no flagged statement`);
      }
    } else {
      const stmt = isSlice
        ? `Rank ${rankOf.get(id)} of ${sliceCohort.length} on the guardrail slice`
        : `Rank ${rankOf.get(id)} of ${fullCohort.length} in the full suite`;
      if (!blockText.includes(stmt)) {
        fail(`card ${id}: rank statement "${stmt}" not in the card text`);
      }
      if (isSlice && !blockText.includes("guardrail slice")) {
        fail(`card ${id}: slice card states no slice population`);
      }
    }
    const dci = displayCiI(row);
    if (dci && !blockText.includes(fmtCiCompact(dci))) {
      fail(`card ${id}: index summary compact interval ${fmtCiCompact(dci)} missing`);
    }
    const slug = slugOfC(row, allRows);
    if (!chunk.includes(`href="/models/${slug}/"`)) {
      fail(`card ${id}: no link to its own page at /models/${slug}/`);
    }
  }
  if (!modelsHtml.includes("Peira decision robustness board")) {
    fail("models section carries no identification line (SF-01)");
  }
}

/* Per-model pages. Same card, same payload strings, own head. */
import { existsSync } from "node:fs";
for (const row of allRows) {
  const slug = slugOfC(row, allRows);
  const pagePath = join(root, "out", "models", slug, "index.html");
  if (!existsSync(pagePath)) {
    fail(`model page missing at out/models/${slug}/index.html`);
    continue;
  }
  const pageHtml = readFileSync(pagePath, "utf8");
  const pageText = visibleText(pageHtml);
  assertCardText(pageText, row, "model page");
  assertCardAttrs(pageHtml, row, "model page");
  const title = pageHtml.match(/<title>([^<]*)<\/title>/)?.[1] ?? "";
  if (!title.includes(shortName(row))) {
    fail(`model page ${slug}: title does not name the model`);
  }
  if (pageText.includes("—")) fail(`model page ${slug}: visible text contains an em dash`);
  if (pageText.includes(";")) fail(`model page ${slug}: visible text contains a semicolon`);
  if (pageText.includes(":")) fail(`model page ${slug}: visible text contains a colon`);
  if (/[0-9a-f]{40,}/.test(pageText.replace(row.display_name, ""))) {
    fail(`model page ${slug}: a long hex run appears outside the display name`);
  }
}

/* ---------- 11. nav, compare, ranking links (round 11) ---------- */

/* Delta formats, ported independently from the same decimal
 * primitives as the value formats. A delta's sign prints only
 * when the rounded magnitude is not zero. */
function deltaSignC(value, magnitude) {
  if (/^0(\.0+)?$/.test(magnitude)) return "";
  return value < 0 ? "-" : "+";
}
const fmtDeltaPctC = (v) => {
  const mag = quantHU(shiftPt(expandDec(Math.abs(v)), 2), 1);
  return deltaSignC(v, mag) + mag;
};
const fmtDelta3C = (v) => {
  const mag = quantHU(expandDec(Math.abs(v)), 3);
  return deltaSignC(v, mag) + mag;
};
const fmtDeltaUsdC = (v) => {
  const mag = quantHU(expandDec(Math.abs(v)), 2);
  return `${deltaSignC(v, mag)}$${mag}`;
};
const fmtDeltaMsC = (v) => {
  const mag = quantHU(expandDec(Math.abs(v)), 0);
  return `${deltaSignC(v, mag)}${mag}ms`;
};
const WIRE_WORDS_C = {
  "openai-decisions": "Decisions API",
  "openai-structured": "Chat completions",
};
const wireWordsC = (w) => WIRE_WORDS_C[w] ?? w;
const nulC = (x) => (x === undefined || x === null ? null : x);

/* The compare row the payload implies for one result, field
 * by field, derived here so the island's shaped dataset and
 * its rendered arithmetic are both held to the payload. */
const CMP_METRIC_DEFS = [
  { key: "asr", better: "low", val: (r) => nulC(r.asr_conditional), vfmt: fmtPct, dfmt: fmtDeltaPctC },
  { key: "benign", better: "high", val: (r) => nulC(r.benign_accuracy), vfmt: fmtPct, dfmt: fmtDeltaPctC },
  { key: "malformed", better: "low", val: (r) => nulC(r.malformed_rate), vfmt: fmtPct, dfmt: fmtDeltaPctC },
  { key: "atkEce", better: "low", val: (r) => nulC(r.detail?.calibration?.attacked?.ece ?? r.ece_attacked), vfmt: fmtEceC, dfmt: fmtDelta3C },
  { key: "atkBrier", better: "low", val: (r) => nulC(r.detail?.calibration?.attacked?.brier), vfmt: fmtEceC, dfmt: fmtDelta3C },
  { key: "benEce", better: "low", val: (r) => nulC(r.detail?.calibration?.benign?.ece), vfmt: fmtEceC, dfmt: fmtDelta3C },
  { key: "benBrier", better: "low", val: (r) => nulC(r.detail?.calibration?.benign?.brier), vfmt: fmtEceC, dfmt: fmtDelta3C },
  { key: "tax", better: "low", val: (r) => nulC(r.robustness_tax), vfmt: fmtTaxC, dfmt: fmtDelta3C },
  { key: "cost", better: "low", val: (r) => nulC(r.total_cost_usd), vfmt: null, dfmt: fmtDeltaUsdC },
  { key: "latP50", better: "low", val: (r) => nulC(r.latency_ms_p50_attacked), vfmt: fmtMsC, dfmt: fmtDeltaMsC },
  { key: "latP95", better: "low", val: (r) => nulC(r.latency_ms_p95_attacked), vfmt: fmtMsC, dfmt: fmtDeltaMsC },
];
function cmpExpectedC(row) {
  const values = {};
  for (const def of CMP_METRIC_DEFS) values[def.key] = def.val(row);
  const carried = new Map(famEntriesC(row));
  return {
    slug: slugOfC(row, allRows),
    runId: row.run_id,
    name: shortName(row),
    group: fullCohort.includes(row)
      ? "full"
      : unranked.includes(row)
        ? "flagged"
        : "slice",
    nCases: row.n_cases,
    values,
    costLowerBound:
      row.total_cost_usd !== null &&
      row.total_cost_usd !== undefined &&
      row.total_cost_usd > 0 &&
      lowerBoundC(row),
    families: familyOrderC.map((k) => {
      const f = carried.get(k);
      return f && f.asr !== null && f.asr !== undefined ? f.asr : null;
    }),
  };
}
const cmpExpectedById = new Map(allRows.map((r) => [r.run_id, cmpExpectedC(r)]));

/* 11a. The section bar. */
const NAV_EXPECTED = [
  ["ranking", "Ranking"],
  ["malformed", "Malformed"],
  ["families", "Families"],
  ["cost", "Cost"],
  ["calibration", "Calibration"],
  ["models", "Models"],
  ["compare", "Compare"],
  ["method", "Method"],
];
const navMatch = html.match(/<nav class="section-nav"[\s\S]*?<\/nav>/);
if (!navMatch) {
  fail("section nav missing from rendered page");
} else {
  const navLinks = [
    ...navMatch[0].matchAll(
      /<a class="section-nav-link" href="#([^"]+)" data-nav-target="([^"]+)">([^<]*)<\/a>/g,
    ),
  ].map((m) => ({ href: m[1], target: m[2], label: m[3] }));
  if (navLinks.length !== NAV_EXPECTED.length) {
    fail(`section nav holds ${navLinks.length} links, expected ${NAV_EXPECTED.length}`);
  }
  navLinks.forEach((link, i) => {
    const [id, label] = NAV_EXPECTED[i] ?? [];
    if (link.href !== id || link.target !== id || link.label !== label) {
      fail(
        `nav link ${i + 1} is "${link.label}" to #${link.href} (target ${link.target}), expected "${label}" to #${id}`,
      );
    }
  });
  for (const [id] of NAV_EXPECTED) {
    if (!new RegExp(` id="${id}"`).test(html)) {
      fail(`nav target #${id} has no element with that id on the page`);
    }
  }
}

/* 11b. The compare dataset printed beside the section. */
const cmpDataMatch = html.match(
  /<script type="application\/json" data-compare-rows="(\d+)">([\s\S]*?)<\/script>/,
);
let cmpDataset = null;
if (!cmpDataMatch) {
  fail("compare dataset script element missing from rendered page");
} else {
  if (Number(cmpDataMatch[1]) !== allRows.length) {
    fail(
      `compare dataset declares ${cmpDataMatch[1]} rows, payload holds ${allRows.length}`,
    );
  }
  try {
    cmpDataset = JSON.parse(cmpDataMatch[2]);
  } catch {
    fail("compare dataset script element does not parse as JSON");
  }
}
if (Array.isArray(cmpDataset)) {
  if (cmpDataset.length !== allRows.length) {
    fail(`compare dataset holds ${cmpDataset.length} rows, payload holds ${allRows.length}`);
  }
  const dupNames = new Set(
    allRows
      .map((r) => shortName(r))
      .filter((n, i, arr) => arr.indexOf(n) !== i),
  );
  for (const crow of cmpDataset) {
    const row = rowById.get(crow.runId);
    if (!row) {
      fail(`compare dataset row for unknown run ${crow.runId}`);
      continue;
    }
    const exp = cmpExpectedById.get(row.run_id);
    const eq = (got, want, what) => {
      if (nulC(got) !== want) {
        fail(`compare dataset ${row.run_id}: ${what} is ${got}, payload gives ${want}`);
      }
    };
    eq(crow.slug, exp.slug, "slug");
    eq(crow.name, exp.name, "name");
    eq(
      crow.wire,
      dupNames.has(shortName(row)) ? wireWordsC(row.wire) : null,
      "wire",
    );
    eq(crow.group, exp.group, "group");
    eq(crow.nCases, exp.nCases, "case base");
    for (const def of CMP_METRIC_DEFS) {
      eq(crow[def.key], exp.values[def.key], `metric ${def.key}`);
    }
    eq(crow.costLowerBound, exp.costLowerBound, "cost lower bound flag");
    if (!Array.isArray(crow.families) || crow.families.length !== familyOrderC.length) {
      fail(`compare dataset ${row.run_id}: family array does not match the column order`);
    } else {
      crow.families.forEach((v, i) => {
        if (nulC(v) !== exp.families[i]) {
          fail(
            `compare dataset ${row.run_id}: family ${familyOrderC[i]} is ${v}, payload gives ${exp.families[i]}`,
          );
        }
      });
    }
  }
}

/* 11c. The rendered default pair, its deltas, dots, and bars. */
const cmpHtml = sectionSlice("compare", "method");
let cmpPairsChecked = 0;
if (!cmpHtml) {
  fail("compare section missing from rendered page");
} else {
  if (cmpHtml.includes("data-cmp-banner")) {
    fail("compare section renders a guard banner for its default pair");
  }
  const optionValues = [...cmpHtml.matchAll(/<option value="([^"]+)"/g)].map(
    (m) => m[1],
  );
  const expectedSlugs = allRows.map((r) => slugOfC(r, allRows));
  if (optionValues.length !== expectedSlugs.length * 2) {
    fail(
      `compare pickers hold ${optionValues.length} options, expected two per result (${expectedSlugs.length * 2})`,
    );
  }
  for (const slug of expectedSlugs) {
    if (optionValues.filter((v) => v === slug).length !== 2) {
      fail(`compare pickers do not both offer ${slug}`);
    }
  }
  /* The rendered pair, read from its value cells. */
  const cellRaw = (chunk, side) => {
    const tag = chunk.match(
      new RegExp(`<td[^>]*data-cmp-side="${side}"[^>]*>`),
    )?.[0];
    return tag ? attr(tag, "data-cmp-raw") : null;
  };
  const rowChunks = cmpHtml.split('<tr data-cmp-row="').slice(1);
  const rendered = new Map();
  const cellTextAfter = (chunk, tagRe) => {
    const tag = chunk.match(tagRe)?.[0];
    if (!tag) return null;
    const end = chunk.indexOf(tag) + tag.length;
    return visibleText(chunk.slice(end, chunk.indexOf("</td>", end))).trim();
  };
  for (const chunk of rowChunks) {
    const metricKey = chunk.slice(0, chunk.indexOf('"'));
    const deltaTag = chunk.match(/<td[^>]*data-cmp-delta[^>]*>/)?.[0];
    const deltaEnd = deltaTag
      ? chunk.indexOf(deltaTag) + deltaTag.length
      : -1;
    rendered.set(metricKey, {
      a: cellRaw(chunk, "a"),
      b: cellRaw(chunk, "b"),
      aText: cellTextAfter(chunk, /<td[^>]*data-cmp-side="a"[^>]*>/),
      bText: cellTextAfter(chunk, /<td[^>]*data-cmp-side="b"[^>]*>/),
      deltaRaw: deltaTag ? attr(deltaTag, "data-cmp-raw") : null,
      deltaText:
        deltaEnd >= 0
          ? visibleText(chunk.slice(deltaEnd, chunk.indexOf("</td>", deltaEnd))).trim()
          : null,
      win: chunk.match(/data-cmp-win="([ab])"/)?.[1] ?? null,
    });
  }
  /* Identify the pair. A rendered side matches a payload row
   * when every metric raw equals the row's value (empty for
   * null). The design's default pair must be the match. */
  const matchSide = (side) => {
    const hits = allRows.filter((row) => {
      const exp = cmpExpectedById.get(row.run_id);
      return CMP_METRIC_DEFS.every((def) => {
        const cell = rendered.get(def.key)?.[side];
        if (cell === undefined || cell === null) return false;
        const want = exp.values[def.key];
        return want === null ? cell === "" : Number(cell) === want;
      });
    });
    return hits;
  };
  const aHits = rendered.size > 0 ? matchSide("a") : [];
  const bHits = rendered.size > 0 ? matchSide("b") : [];
  if (aHits.length !== 1 || bHits.length !== 1) {
    fail(
      `compare default pair does not resolve to one payload row per side (a ${aHits.length}, b ${bHits.length})`,
    );
  } else {
    const [rowA, rowB] = [aHits[0], bHits[0]];
    if (rowA !== fullCohort[0]) {
      fail(
        `compare default model A is ${rowA.run_id}, the design's default is the strongest full suite row ${fullCohort[0].run_id}`,
      );
    }
    const jevRow = fullCohort.find((r) => r.wire === "jev");
    if (jevRow && rowB !== jevRow) {
      fail(
        `compare default model B is ${rowB.run_id}, the design's default is the first full suite row on the jev wire (${jevRow.run_id})`,
      );
    }
    const expA = cmpExpectedById.get(rowA.run_id);
    const expB = cmpExpectedById.get(rowB.run_id);
    for (const def of CMP_METRIC_DEFS) {
      const cell = rendered.get(def.key);
      if (!cell) {
        fail(`compare table has no row for metric ${def.key}`);
        continue;
      }
      const va = expA.values[def.key];
      const vb = expB.values[def.key];
      /* The printed values beside the deltas. */
      const wantValText = (v, exp) => {
        if (v === null) return "·";
        if (def.key === "cost") {
          return `${exp.costLowerBound ? "≥ " : ""}${fmtUsdC(v)}`;
        }
        return def.vfmt(v);
      };
      if (cell.aText !== wantValText(va, expA)) {
        fail(
          `compare value ${def.key} side a: printed "${cell.aText}", the payload prints "${wantValText(va, expA)}"`,
        );
      }
      if (cell.bText !== wantValText(vb, expB)) {
        fail(
          `compare value ${def.key} side b: printed "${cell.bText}", the payload prints "${wantValText(vb, expB)}"`,
        );
      }
      if (va === null || vb === null) {
        if (cell.deltaRaw !== "" || cell.deltaText !== "·") {
          fail(
            `compare delta ${def.key}: a side carries no value, so the delta must be the not measured mark, got raw "${cell.deltaRaw}" text "${cell.deltaText}"`,
          );
        }
      } else {
        const d = va - vb;
        if (cell.deltaRaw === "" || Math.abs(Number(cell.deltaRaw) - d) > 1e-12) {
          fail(
            `compare delta ${def.key}: rendered raw ${cell.deltaRaw}, payload difference is ${d}`,
          );
        }
        const wantText = def.dfmt(d);
        if (cell.deltaText !== wantText) {
          fail(
            `compare delta ${def.key}: printed "${cell.deltaText}", the delta rule prints "${wantText}"`,
          );
        }
        cmpPairsChecked += 1;
      }
      const wantWin =
        va !== null && vb !== null && va !== vb
          ? def.better === "low"
            ? va < vb
              ? "a"
              : "b"
            : va > vb
              ? "a"
              : "b"
          : null;
      if (cell.win !== wantWin) {
        fail(
          `compare winner dot ${def.key}: rendered on ${cell.win}, the stronger side is ${wantWin}`,
        );
      }
    }
    /* The paired family bars for the rendered pair. */
    const famLines = [...cmpHtml.matchAll(/<div class="cmp-fam-line"[^>]*>/g)].map(
      (m) => m[0],
    );
    if (famLines.length !== familyOrderC.length * 2) {
      fail(
        `compare family bars hold ${famLines.length} lines, expected ${familyOrderC.length * 2}`,
      );
    }
    famLines.forEach((tag, i) => {
      const famKey = familyOrderC[Math.floor(i / 2)];
      const side = i % 2 === 0 ? "a" : "b";
      if (attr(tag, "data-cmpfamily") !== famKey || attr(tag, "data-cmpside") !== side) {
        fail(`compare family line ${i + 1} is out of order or side`);
        return;
      }
      const want = (side === "a" ? expA : expB).families[Math.floor(i / 2)];
      const got = attr(tag, "data-cmpasr");
      if (want === null) {
        if (!tag.includes('data-na="true"') || got !== null) {
          fail(`compare family ${famKey} side ${side}: should render as not measured`);
        }
      } else if (got === null || Number(got) !== want) {
        fail(
          `compare family ${famKey} side ${side}: data-cmpasr ${got}, payload gives ${want}`,
        );
      }
    });
  }
  if (!cmpHtml.includes("Peira decision robustness board")) {
    fail("compare section carries no identification line (SF-01)");
  }
}

/* 11d. Every ranking row names its model page. */
for (const [id, rows] of Object.entries(expectedGroups)) {
  const block = blocks[id];
  if (!block) continue;
  for (const row of rows) {
    const marker = `data-run-id="${row.run_id}"`;
    const start = block.indexOf(marker);
    if (start < 0) continue;
    const next = block.indexOf('data-run-id="', start + marker.length);
    const slice = block.slice(start, next < 0 ? undefined : next);
    const want = `href="/models/${slugOfC(row, allRows)}/"`;
    if (!slice.includes(want) || !slice.includes('class="name-link"')) {
      fail(`ranking row ${row.run_id}: name does not link to its model page (${want})`);
    }
  }
}

/* ---------- 12. cycle 7 surfaces ---------- */

/* The malformed share of a row's counted flips, under the
 * derivation ported with the other independent derivations
 * above (decompI); check 12b reads the share from it. */
function malformedShareI(row) {
  const d = decompI(row);
  return d === null ? null : d.share;
}

function metaDescription(pageHtml) {
  const m = pageHtml.match(/<meta name="description" content="([^"]*)"/);
  if (!m) return null;
  return m[1]
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&#x27;|&apos;/g, "'")
    .replace(/&quot;/g, '"');
}

function modelPageDescription(row, where) {
  const slug = slugOfC(row, allRows);
  const pagePath = join(root, "out", "models", slug, "index.html");
  /* A missing page already failed in check 10. */
  if (!existsSync(pagePath)) return null;
  const desc = metaDescription(readFileSync(pagePath, "utf8"));
  if (desc === null) {
    fail(`${where} ${slug}: no meta description in the built page`);
  }
  return desc;
}

/* 12a. The Method subsection anchors. The chained-run anchor
 * is the one conditional subsection: the section renders only
 * when a payload row carries chained-run provenance (the
 * rerun record the pipeline builds from the standing
 * artifact's parent_run_id chain), so its expectation is
 * keyed to the payload the same way the section is, in both
 * directions. */
const METHOD_ANCHORS = [
  "method-case",
  "method-suite",
  "method-intervals",
  "method-admission",
  "method-tax",
  "method-costs",
  "method-standing",
];
for (const id of METHOD_ANCHORS) {
  if (!html.includes(`id="${id}"`)) {
    fail(`Method subsection anchor #${id} missing from the rendered page`);
  }
}
const payloadHasRerun = allRows.some((r) => r.rerun);
if (payloadHasRerun !== html.includes(`id="method-reruns"`)) {
  fail(
    `Method chained-run anchor: the payload ${payloadHasRerun ? "carries" : "carries no"} chained-run records but the rendered page ${payloadHasRerun ? "omits" : "prints"} the chained-run section`,
  );
}

/* 12b. Flagged heads: the standing always, a figure only on a
 * payload-derived malformed majority. */
for (const row of unranked) {
  const desc = modelPageDescription(row, "flagged model page");
  if (desc === null) continue;
  const slug = slugOfC(row, allRows);
  if (!desc.includes("Flagged and not ranked.")) {
    fail(
      `flagged model page ${slug}: head description does not carry its flagged standing (reads: ${desc.slice(0, 120)})`,
    );
  }
  const share = malformedShareI(row);
  const figure =
    row.asr_conditional !== null
      ? `Attack success ${fmtPct(row.asr_conditional)}`
      : null;
  if (share === null || share <= 0.5) {
    if (/Attack success [0-9]/.test(desc) || (figure && desc.includes(figure))) {
      fail(
        `flagged model page ${slug}: head description prints an attack success figure although the payload's malformed share is ${share === null ? "not derivable" : share.toFixed(3)}, not a majority`,
      );
    }
  } else if (figure && !desc.includes(figure)) {
    fail(
      `flagged model page ${slug}: the payload's malformed share ${share.toFixed(3)} is a majority but the head description does not print ${figure} inside its decomposition`,
    );
  }
}

/* 12c. Slice heads name the sub-population they rest on. */
for (const row of sliceCohort) {
  const desc = modelPageDescription(row, "slice model page");
  if (desc === null) continue;
  if (
    !desc.includes(
      "Measured on the guardrail abstain subset, not the full suite.",
    )
  ) {
    fail(
      `slice model page ${slugOfC(row, allRows)}: head description does not name the guardrail abstain subset (reads: ${desc.slice(0, 120)})`,
    );
  }
}

/* 12d. The two chrome rules in the built CSS asset. */
const cssDir = join(root, "out", "_next", "static", "css");
if (!existsSync(cssDir)) {
  fail("built CSS directory missing at out/_next/static/css");
} else {
  let builtCss = "";
  for (const name of readdirSync(cssDir)
    .filter((f) => f.endsWith(".css"))
    .sort()) {
    builtCss += readFileSync(join(cssDir, name), "utf8");
  }
  if (!/\.nav-at-end[^{]*\{[^}]*display:\s*none/.test(builtCss)) {
    fail(
      "built CSS carries no .nav-at-end rule clearing the nav overflow cue at the strip's end",
    );
  }
  if (!/#method h3\[id\][^{]*\{[^}]*scroll-margin-top:\s*64px/.test(builtCss)) {
    fail("built CSS carries no #method h3[id] scroll-margin rule");
  }
}

/* ---------- 13. C-5 companion surfaces ---------- */

/* Attribute text in the built HTML is entity-escaped; the
 * figure strings asserted here carry none of the escaped
 * characters, but names may, so unescape before comparing. */
const unesc = (s) =>
  s === null
    ? null
    : s
        .replace(/&amp;/g, "&")
        .replace(/&lt;/g, "<")
        .replace(/&gt;/g, ">")
        .replace(/&#x27;|&apos;/g, "'")
        .replace(/&quot;/g, '"');

/* Does the text print the row's attack success figure in any
 * rendering: the exact printed form, or its whole-percent
 * rounding at a token boundary (so a benign 100.0% in the
 * same carrier cannot trip the whole-percent form of a 0%
 * figure)? */
function printsFigure(text, row) {
  if (typeof row.asr_conditional !== "number") return false;
  if (text.includes(fmtPct(row.asr_conditional))) return true;
  const whole = Math.round(row.asr_conditional * 100);
  return new RegExp(`(^|[^0-9.])${whole}%`).test(text);
}

/* A flagged figure's carrier text (a point title or an
 * accessible name) holds the figure only with its
 * decomposition beside it. Where the payload's records do
 * not derive one, the carrier states the flagged standing
 * and no figure: the words attack success never appear, and
 * the figure itself appears in no rendering. */
function assertFlaggedCarrier(carrier, row, where) {
  if (carrier === null) {
    fail(`${where} ${row.run_id}: carrier text missing`);
    return;
  }
  const d = decompI(row);
  if (d !== null) {
    for (const clause of [
      `attack success ${fmtPct(row.asr_conditional)}`,
      `genuine flip rate ${fmtPct(d.genuine)}`,
      `${fmtPct(d.share)} of counted flips to malformed output`,
    ]) {
      if (!carrier.includes(clause)) {
        fail(
          `${where} ${row.run_id}: flagged figure carrier does not state "${clause}"`,
        );
      }
    }
  } else {
    if (!carrier.includes("flagged and not ranked")) {
      fail(
        `${where} ${row.run_id}: carrier states neither a decomposition nor the flagged standing`,
      );
    }
    if (carrier.includes("attack success")) {
      fail(
        `${where} ${row.run_id}: carrier prints an attack success figure although the payload derives no decomposition for it`,
      );
    }
    if (printsFigure(carrier, row)) {
      fail(
        `${where} ${row.run_id}: carrier prints the attack success figure in some rendering although the payload derives no decomposition for it`,
      );
    }
  }
}

const scatter13 = sectionSlice("scatter", "calibration");
if (scatter13) {
  const pointMatches = [...scatter13.matchAll(/<g[^>]*>/g)].filter((m) =>
    m[0].includes('class="scatter-point"'),
  );
  for (const m of pointMatches) {
    const tag = m[0];
    const id = attr(tag, "data-run-id");
    const row = rowById.get(id);
    if (!row) continue;
    const close = scatter13.indexOf("</title>", m.index);
    const open = close >= 0 ? scatter13.lastIndexOf("<title>", close) : -1;
    const title =
      open >= 0 ? unesc(scatter13.slice(open + "<title>".length, close)) : null;
    const aria = unesc(attr(tag, "aria-label"));
    if (unrankedIds.has(id)) {
      assertFlaggedCarrier(title, row, "scatter point title");
      assertFlaggedCarrier(aria, row, "scatter point name");
    } else if (
      title === null ||
      !title.includes(`attack success ${fmtPct(row.asr_conditional)}`)
    ) {
      fail(`scatter point title ${id}: ranked title does not state its figure`);
    }
  }
  const entryMatches = [...scatter13.matchAll(/<g[^>]*>/g)].filter((m) =>
    m[0].includes('class="scatter-entry"'),
  );
  for (const m of entryMatches) {
    const id = attr(m[0], "data-entry-for");
    const row = rowById.get(id);
    if (!row || !unrankedIds.has(id)) continue;
    const vAt = scatter13.indexOf("scatter-entry-values", m.index);
    const vOpen = vAt >= 0 ? scatter13.indexOf(">", vAt) : -1;
    const vClose = vOpen >= 0 ? scatter13.indexOf("</text>", vOpen) : -1;
    const values =
      vClose >= 0 ? unesc(scatter13.slice(vOpen + 1, vClose)) : null;
    if (values === null || !values.startsWith("flagged")) {
      fail(`scatter entry ${id}: flagged entry does not state its standing`);
    } else if (printsFigure(values, row)) {
      fail(
        `scatter entry ${id}: flagged entry prints its attack success figure`,
      );
    }
    const aria = attr(m[0], "aria-label");
    if (aria !== null) {
      assertFlaggedCarrier(unesc(aria), row, "scatter entry name");
    }
  }
}

const heat13 = sectionSlice("heatmap", "scatter");
if (heat13) {
  const heatText13 = visibleText(heat13);
  const dupNames13 = new Set(
    allRows
      .map((r) => shortName(r))
      .filter((n, i, arr) => arr.indexOf(n) !== i),
  );
  for (const row of unranked) {
    const label = dupNames13.has(shortName(row))
      ? `${shortName(row)} (${wireWordsC(row.wire)})`
      : shortName(row);
    const d = decompI(row);
    const note =
      d !== null
        ? `${label}, flagged and not ranked, attack success ${fmtPct(row.asr_conditional)}, genuine flip rate ${fmtPct(d.genuine)}, with ${fmtPct(d.share)} of counted flips to malformed output.`
        : `${label}, flagged and not ranked. No whole-row figure is stated, because the sealed records do not derive its malformed decomposition. Any family figure in the grid carries its own decomposition in its title.`;
    if (!heatText13.includes(note)) {
      fail(
        `heatmap notes: the flagged decomposition line for ${row.run_id} is missing or misstated (expected "${note.slice(0, 110)}")`,
      );
    }
  }
}

/* ---------- verdict ---------- */

if (failures.length > 0) {
  console.error(`integrity check FAILED with ${failures.length} problem(s):`);
  for (const f of failures) console.error(`  - ${f}`);
  process.exit(1);
}
console.log(
  `integrity check passed: ${counts.results} rows, counts ${counts.tested}/${counts.ranked}/${counts.flagged}, ${taxChecked} taxes recomputed (max deviation ${taxMaxDev.toFixed(5)}), ${expectedBands} tie brackets, compare dataset and ${cmpPairsChecked} rendered deltas verified`,
);
