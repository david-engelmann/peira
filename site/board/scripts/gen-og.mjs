/**
 * Build-time social preview and data staging (SO-01, TR-02,
 * SF-04). Renders public/og.png, 1200 by 630: the board's
 * annotated cost scatter itself, drawn from the same payload
 * the page renders, every plotted point a disc in its maker's
 * family color carrying the maker's mark and every point
 * named, with the two corner readings in display type. Also
 * stages public/payload.json so the page can link the exact
 * data behind it in one click. Numbers format with the same
 * decimal half-up rule as the page.
 */
import { readFileSync, writeFileSync, copyFileSync, mkdirSync } from "node:fs";
import { globSync } from "node:fs";
import { homedir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const payload = JSON.parse(
  readFileSync(path.join(root, "data", "payload.json"), "utf8"),
);

/* Decimal formatting, same rule as lib/format.ts. */
function expandDec(v) {
  const s = String(v);
  if (!/[eE]/.test(s)) return s;
  const [mantissa, expS] = s.split(/[eE]/);
  const exp = Number(expS);
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
  const intOut = (joined.slice(0, joined.length - decimals) || "0").replace(
    /^0+(?=\d)/,
    "",
  );
  const fracOut = decimals > 0 ? joined.slice(joined.length - decimals) : "";
  return (neg ? "-" : "") + intOut + (decimals > 0 ? `.${fracOut}` : "");
}
const fmtPct = (v) => `${quantHU(shiftPt(expandDec(v), 2), 1)}%`;
const fmtUsd = (v) => `$${quantHU(expandDec(v), 2)}`;

/* Truncation at a fixed precision, toward zero, on the
 * decimal string: quantHU without the half-up bump. */
function truncDec(decStr, decimals) {
  const neg = decStr.startsWith("-");
  const body = neg ? decStr.slice(1) : decStr;
  const [ip, fp = ""] = body.split(".");
  const kept = fp.slice(0, decimals).padEnd(decimals, "0");
  const intOut = (ip || "0").replace(/^0+(?=\d)/, "");
  return (neg ? "-" : "") + intOut + (decimals > 0 ? `.${kept}` : "");
}
function trimDec(s) {
  if (!s.includes(".")) return s;
  return s.replace(/0+$/, "").replace(/\.$/, "");
}
/* A cost lower bound prints truthfully (red team finding
 * RT-3 on the #521 review): the printed bound never exceeds
 * the recorded value, and rounding never takes a positive
 * bound to zero. Precision extends from two decimals to
 * four, truncated at each step, until the truncated bound
 * is non-zero, and trailing zeros trim. A plain recorded
 * cost keeps the half-up two-decimal fmtUsd above. The
 * words strip under the chart takes this form too, so a
 * plain sub-cent cost named there never prints as zero
 * dollars either. */
function fmtUsdBound(v) {
  for (const p of [2, 3, 4]) {
    const t = truncDec(expandDec(v), p);
    if (Number(t) > 0) return `$${trimDec(t)}`;
  }
  return `$${trimDec(truncDec(expandDec(v), 4))}`;
}

/* The board's lower-bound rule (lib/charts costIsLowerBound),
 * replicated on the payload rows: a recorded cost whose priced
 * calls fall short of its timed calls is a floor, and the model
 * cards print it with the qualifier. The top corner follows
 * the same rule. */
const costIsLowerBound = (r) => {
  const fams = r.detail?.families;
  if (!fams || typeof fams !== "object" || Array.isArray(fams)) return false;
  let costed = 0;
  let timed = 0;
  let seen = false;
  for (const v of Object.values(fams)) {
    if (!v || typeof v !== "object" || Array.isArray(v)) continue;
    const nc = v.n_costed_calls;
    const nl = v.n_latency_calls;
    if (typeof nc !== "number" || typeof nl !== "number") return false;
    costed += nc;
    timed += nl;
    seen = true;
  }
  return seen && costed < timed;
};

/* The flip decomposition, a port of lib/payload's
 * flipDecomposition (familyRecords, flipCounts and countOf
 * included): how many of a flagged result's counted flips
 * were malformed output rather than a changed decision, and
 * the flip rate with those removed, cross-checked against
 * the row's printed attack success. Where the sealed family
 * records are missing or disagree with the printed figure
 * the port returns null and no decomposition may be stated,
 * the same failure semantics the board applies. The
 * off-scale disclosure below states a flagged figure only
 * with this decomposition beside it. */
const countOf = (x) =>
  typeof x === "number" && Number.isInteger(x) && x >= 0 ? x : null;
function familyRecords(r) {
  const detail =
    r.detail !== null && typeof r.detail === "object" ? r.detail : {};
  const famsRaw = detail.families;
  let entries = [];
  if (Array.isArray(famsRaw)) entries = famsRaw;
  else if (famsRaw !== null && typeof famsRaw === "object") {
    entries = Object.values(famsRaw);
  }
  return entries.filter(
    (f) => f !== null && typeof f === "object" && !Array.isArray(f),
  );
}
function flipCounts(fam) {
  const nf = countOf(fam.n_flipped);
  const fd =
    fam.flip_direction !== null &&
    typeof fam.flip_direction === "object" &&
    !Array.isArray(fam.flip_direction)
      ? fam.flip_direction
      : null;
  const tm = fd ? countOf(fd["to-malformed"]) : null;
  if (nf === null || tm === null || tm > nf) return null;
  return { nf, tm };
}
function flipDecomposition(r) {
  const printed = r.asr_conditional;
  if (printed === null || printed === undefined) return null;
  const fams = familyRecords(r);
  if (fams.length === 0) return null;
  let flips = 0;
  let malformed = 0;
  for (const fam of fams) {
    const c = flipCounts(fam);
    if (c === null) return null;
    flips += c.nf;
    malformed += c.tm;
  }
  const n = countOf(r.n_eligible);
  if (n === null || n === 0 || flips === 0) return null;
  if (Math.abs(flips / n - printed) > 0.001) return null;
  return {
    flips,
    malformedFlips: malformed,
    malformedShare: malformed / flips,
    genuineRate: (flips - malformed) / n,
  };
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

/* Point names follow the page's rule (lib/scatterData's
 * labelFor over lib/payload): the short name, with the wire
 * words appended when another result on the board shares
 * it, so the two gpt-6-luna wires are told apart in the
 * image just as they are on the board. */
const WIRE_WORDS = {
  "openai-decisions": "Decisions API",
  "openai-structured": "Chat completions",
};
const nameCounts = new Map();
for (const r of [...payload.ranked, ...payload.unranked]) {
  const n = shortName(r);
  nameCounts.set(n, (nameCounts.get(n) ?? 0) + 1);
}
const pointName = (r) => {
  const n = shortName(r);
  return nameCounts.get(n) > 1
    ? `${n} (${WIRE_WORDS[r.wire] ?? r.wire})`
    : n;
};

const fullCases = Math.max(...payload.ranked.map((r) => r.n_cases));
/* Version stamps follow the page's rule (lib/payload's
 * boardVersions): one dataset and one suite across every
 * row, or the stamp is not made at all. Reading ranked[0]
 * stamped whatever the first row happened to carry without
 * checking the rest (F9 of the 2026-10-29 hardcode audit). */
const versionPairs = new Set(
  [...payload.ranked, ...payload.unranked].map(
    (r) => `${r.dataset_version ?? "unknown"}|${r.suite ?? "unknown"}`,
  ),
);
if (versionPairs.size !== 1) {
  console.error(
    `gen-og: payload rows disagree on dataset or suite (${[...versionPairs].join(", ")}): no single version stamp holds for the whole board`,
  );
  process.exit(1);
}
const [stampDataset, stampSuite] = [...versionPairs][0].split("|");
const versions = { dataset: stampDataset, suite: stampSuite };
const dateIso = [...payload.ranked, ...payload.unranked]
  .map((r) => r.created_utc)
  .sort()
  .at(-1)
  .slice(0, 10);
const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];
const [dy, dm, dd] = dateIso.split("-").map(Number);
const dateWords = `${dd} ${MONTHS[dm - 1]} ${dy}`;
const results = payload.ranked.length + payload.unranked.length;

/* The share image is the board's money shot: the annotated
 * cost scatter itself, at a size where it still reads in a
 * feed thumbnail. Every full suite point is a disc in its
 * maker's family color carrying the maker's mark, flagged
 * results keep the amber ring, the rail holds the results
 * with no recorded API cost, and the two corner readings are
 * set in display type. The foot decodes the amber ring
 * inside the image, since the image travels without the
 * board's prose. Vendor identity resolves through
 * lib/vendor-data.json, the one vendor table for the whole
 * board, shared with lib/vendor and lib/vendorColors, and
 * the mark paths are read out of lib/logoPaths.ts, so the
 * image cannot drift from the board. The headline and the
 * corner readings are computed from the payload further down
 * and guarded there: the generator fails when the payload
 * does not support them, rather than print a claim the data
 * has outgrown. */
const vendorData = JSON.parse(
  readFileSync(path.join(root, "lib", "vendor-data.json"), "utf8"),
);
const VENDOR_BY_KEY = new Map(vendorData.families.map((f) => [f.key, f]));
const VENDOR_RULES = vendorData.rules.map((r) => ({
  test: new RegExp(r.pattern),
  key: r.family,
}));
const familyOf = (r) => {
  const hay = `${r.display_name} ${r.adapter_name} ${r.wire}`.toLowerCase();
  for (const rule of VENDOR_RULES) {
    if (rule.test.test(hay)) return VENDOR_BY_KEY.get(rule.key);
  }
  return vendorData.fallback;
};
const logoSrc = readFileSync(path.join(root, "lib", "logoPaths.ts"), "utf8");
const LOGO_PATHS = {};
for (const m of logoSrc.matchAll(/(\w+):\s*\n?\s*"([^"]+)"/g)) {
  LOGO_PATHS[m[1]] = m[2];
}
const nonSlice = [...payload.ranked, ...payload.unranked].filter(
  (r) => r.n_cases === fullCases,
);
const plotted = nonSlice.filter(
  (r) => r.total_cost_usd !== null && r.total_cost_usd > 0,
);
const railRows = nonSlice.filter(
  (r) => !(r.total_cost_usd !== null && r.total_cost_usd > 0),
);
const costs = plotted.map((r) => r.total_cost_usd);
const domLo = 10 ** (Math.floor(Math.log10(Math.min(...costs)) * 2) / 2);
const domHi = 10 ** (Math.ceil(Math.log10(Math.max(...costs)) * 2) / 2);
/* The attack success axis ceiling, a port of lib/chart.ts's
 * asrAxisFor (F5 of the 2026-10-29 hardcode audit, board rule
 * as restated by the redesign record): the smallest tenth at
 * or above the worst ranked rate, floored at 0.3. This
 * generator reads the payload JSON directly and cannot import
 * the board module, so the rule is ported. The two must move
 * together, and the share image must draw the axis the board
 * draws. An earlier port added a further step when the worst
 * rate sat exactly on a step, which put the image on a
 * different axis from the board for such a payload. */
function asrAxisCeiling(maxRate) {
  const stepped = Math.ceil((maxRate - 1e-9) / 0.1) * 0.1;
  return Math.round(Math.max(0.3, stepped) * 10) / 10;
}
const axisMax = asrAxisCeiling(
  Math.max(0, ...payload.ranked.map((r) => r.asr_conditional ?? 0)),
);
const axisTicks = Array.from(
  { length: Math.round(axisMax / 0.1) + 1 },
  (_, i) => i / 10,
);
/* A point above the derived ceiling is not drawn (red team
 * finding RT-1 on the #521 review). The axis ceiling derives
 * from the ranked population, so a flagged result can sit
 * above it; extrapolating its position put its disc off the
 * canvas with its label floating free, and the board's own
 * discipline is the opposite: the disc stands off the top
 * of the plot rather than at a false position, and the
 * result is disclosed in words. The drawn sets below exclude
 * every such point, and the disclosure sentences composed
 * further down carry each one into the image, named, with
 * its figure and, for a flagged result, its malformed
 * decomposition. No position is ever clamped to the axis. */
const offScaleRows = [...plotted, ...railRows].filter(
  (r) => (r.asr_conditional ?? 0) > axisMax,
);
const offScaleIds = new Set(offScaleRows.map((r) => r.run_id));
const plottedDrawn = plotted.filter((r) => !offScaleIds.has(r.run_id));
const railDrawn = railRows.filter((r) => !offScaleIds.has(r.run_id));
const PLOT = { x0: 168, x1: 1152, y0: 218, y1: 516 };
const RAIL_CX = 92;
const xOf = (c) =>
  PLOT.x0 +
  ((Math.log10(c) - Math.log10(domLo)) /
    (Math.log10(domHi) - Math.log10(domLo))) *
    (PLOT.x1 - PLOT.x0);
const yOf = (a) => PLOT.y0 + (1 - a / axisMax) * (PLOT.y1 - PLOT.y0);
const esc = (t) =>
  t.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
function disc(r, x, y) {
  const fam = familyOf(r);
  const flagged = !r.ranking_eligible;
  const monoLetter =
    fam.mono ??
    (shortName(r).match(/[a-z0-9]/i)?.[0]?.toUpperCase() ?? "·");
  const glyph = fam.logo
    ? `<path d="${LOGO_PATHS[fam.logo]}" transform="translate(-6 -6) scale(0.5)" fill="${fam.glyph}"/>`
    : `<text y="1" class="mono" fill="${fam.glyph}">${esc(monoLetter)}</text>`;
  return `<g transform="translate(${x.toFixed(1)} ${y.toFixed(1)})">
    <circle r="11" fill="${fam.color}" stroke="${flagged ? "#e8a33d" : "rgba(255,255,255,0.28)"}" stroke-width="${flagged ? 2.5 : 1}"/>
    ${glyph}
  </g>`;
}
/* The gridlines begin at the rail divider, not at the
 * canvas edge. The rail is a list column, as on the board:
 * its discs are spaced for legibility and their order
 * carries the ranking, but a gridline running behind the
 * column would claim an axis position for discs the spread
 * has moved off their true height. */
const gridSvg = axisTicks
  .map(
    (t) => `<line x1="148" y1="${yOf(t)}" x2="${PLOT.x1}" y2="${yOf(t)}" stroke="#232c35" stroke-opacity="0.55"/>
    <text x="${PLOT.x0 + 6}" y="${yOf(t) - 6}" class="tick">${Math.round(t * 100)}</text>`,
  )
  .join("\n");
const decadeSvg = [];
for (let d = Math.ceil(Math.log10(domLo)); d <= Math.floor(Math.log10(domHi)); d++) {
  const v = 10 ** d;
  decadeSvg.push(
    `<text x="${xOf(v)}" y="${PLOT.y1 + 24}" class="tick" text-anchor="middle">${v < 1 ? `$${v.toFixed(2)}` : `$${v}`}</text>`,
  );
}
const railSpread = [...railDrawn]
  .map((r) => ({ r, y: yOf(r.asr_conditional) }))
  .sort((a, b) => a.y - b.y);
/* The pitch leaves visible air between rail discs: a disc's
 * rendered outer radius is 11 plus half its stroke (12.25
 * for a flagged disc), so centres 23 apart left the outlines
 * tangent or overlapping. 26 clears the widest pair. */
for (let pass = 0; pass < 4; pass++) {
  for (let i = 1; i < railSpread.length; i++) {
    railSpread[i].y = Math.max(railSpread[i].y, railSpread[i - 1].y + 26);
  }
  for (let i = railSpread.length - 2; i >= 0; i--) {
    railSpread[i].y = Math.min(railSpread[i].y, railSpread[i + 1].y - 26);
  }
}
/* The passes hold the pitch and the order but anchor
 * nothing, so a rail that grows a row pushes its lowest
 * names past the axis into the cost decades. Clamp the
 * finished ladder into the plot band with a rigid shift,
 * which preserves both the pitch and the order, and fail
 * rather than spill when the ladder is taller than the
 * band itself. The band insets by 13, the flagged disc's
 * outer radius of 12.25 rounded up, so a clamped disc
 * stays inside the plot; the span comparison carries 1px
 * of float tolerance. */
if (railSpread.length > 0) {
  const lo = PLOT.y0 + 13;
  const hi = PLOT.y1 - 13;
  const first = railSpread[0].y;
  const last = railSpread.at(-1).y;
  if (last - first > hi - lo + 1) {
    console.error(
      `gen-og: the no-cost rail carries ${railSpread.length} rows and its ladder no longer fits the plot band at the 26px pitch, so the image does not print with rail names over the cost decades`,
    );
    process.exit(1);
  }
  const shift = last > hi ? hi - last : first < lo ? lo - first : 0;
  if (shift !== 0) {
    for (const e of railSpread) e.y += shift;
  }
}
const railY = new Map(railSpread.map((e) => [e.r.run_id, e.y]));
/* Rail points are named by construction: each name sits
 * beside its disc in the rail column, so those labels are
 * static markup and become furniture for the plotted labels.
 * The plotted points are named by the placement pass that
 * runs in the browser below (placeOgLabels), which derives
 * the labeled set from the plotted population itself: every
 * plotted point gets a label seated beside its disc by
 * deterministic candidate placement against real font
 * measurement, with no leader lines and no per-run table.
 * A point no tier of the pass can seat is named in words in
 * the strip under the chart instead, so a name can never
 * drop silently and a crowded payload never fails the
 * build. */
const railLabelsSvg = railDrawn
  .map(
    (r) =>
      `<text x="${RAIL_CX + 22}" y="${railY.get(r.run_id) + 5}" class="lab">${esc(pointName(r))}</text>`,
  )
  .join("\n");
/* Points whose discs would render as one disc are
 * separated along y before anything is drawn: two results
 * whose centres fall inside a single disc's span merge
 * into one visible disc, and the image would show fewer
 * results than it names (the board's two best results sat
 * 4.7px apart). The spread follows the board's rule
 * (lib/layout.ts nudgePoints) but is scoped to that
 * merged-disc case: the board's full spread, applied to
 * every near pair, moves enough discs in this denser plot
 * that the current population no longer seats its labels
 * (design cycle 4 attempted it; the cycle record carries
 * the failure). No point moves by more than the shift
 * cap, and the labels seat against the drawn discs, so a
 * moved point keeps its name beside it. */
function nudgePoints(points, minSep, maxShift) {
  const orig = new Map(points.map((p) => [p.runId, { x: p.x, y: p.y }]));
  for (let cycle = 0; cycle < 2; cycle++) {
    const parent = points.map((_, i) => i);
    const find = (i) => (parent[i] === i ? i : (parent[i] = find(parent[i])));
    for (let i = 0; i < points.length; i++) {
      for (let j = i + 1; j < points.length; j++) {
        const dx = points[i].x - points[j].x;
        const dy = points[i].y - points[j].y;
        if (Math.hypot(dx, dy) < 12) {
          parent[find(i)] = find(j);
        }
      }
    }
    const groups = new Map();
    points.forEach((p, i) => {
      const root = find(i);
      const group = groups.get(root) ?? [];
      group.push(p);
      groups.set(root, group);
    });
    for (const group of groups.values()) {
      if (group.length < 2) continue;
      const cluster = [...group].sort((a, b) => a.y - b.y || a.x - b.x);
      const ys = cluster.map((p) => orig.get(p.runId).y);
      for (let round = 0; round < 3; round++) {
        for (let i = 1; i < cluster.length; i++) {
          const want = cluster[i - 1].y + minSep;
          cluster[i].y = Math.min(Math.max(cluster[i].y, want), ys[i] + maxShift);
        }
        for (let i = cluster.length - 2; i >= 0; i--) {
          const want = cluster[i + 1].y - minSep;
          cluster[i].y = Math.max(Math.min(cluster[i].y, want), ys[i] - maxShift);
        }
      }
    }
  }
}
const plottedXY = plottedDrawn.map((r) => ({
  runId: r.run_id,
  r,
  x: xOf(r.total_cost_usd),
  y: yOf(r.asr_conditional),
}));
nudgePoints(plottedXY, 24, 12);
const plottedPts = plottedXY.map((p) => ({
  runId: p.runId,
  name: pointName(p.r),
  /* The point stated in words, for the strip that names a
   * point whose label no tier of the placement pass could
   * seat beside its disc. Derived here from the same row, so
   * the strip can never disagree with the plotted point. */
  words: `${pointName(p.r)} (${fmtPct(p.r.asr_conditional)} at ${fmtUsdBound(p.r.total_cost_usd)})`,
  x: p.x,
  y: p.y,
}));
/* The corner readings and the headline claim, computed from
 * this payload and validated before they are drawn (F1 and
 * F2 of the 2026-10-29 hardcode audit; the pattern is the
 * verified candidate generator's). The claims stand on the
 * ranked plotted population, the population the board's own
 * claims stand on. The headline (the priciest model was the
 * easiest to flip) and the top corner hold only while the
 * priciest ranked plotted run's attack success equals that
 * population's highest (a tie at the top still carries the
 * claim, the same value comparison gen-social-preview
 * makes), so that is asserted here: a payload
 * that breaks it fails the build rather than print a false
 * corner. The bottom corner states the chart's actual
 * toughness extreme, the lowest attack success among every
 * ranked run the chart carries, costed runs on the plot and
 * no-cost runs on the rail alike, because its words say
 * least of all and the rail is on the chart. A ranked rail
 * run that flips more than the priciest costed run is named
 * in the disclosure block under the chart, so the headline's
 * cost story never reads as the whole story. The top
 * corner's cost figure carries the lower-bound qualifier
 * when the payload marks that cost a floor, exactly as the
 * model cards print it. */
const rankedPlotted = plotted.filter((r) => r.ranking_eligible);
const byAsrAsc = [...rankedPlotted].sort(
  (a, b) => a.asr_conditional - b.asr_conditional,
);
const byCostAsc = [...rankedPlotted].sort(
  (a, b) => a.total_cost_usd - b.total_cost_usd,
);
const priciest = byCostAsc.at(-1);
const toughestPool = [
  ...rankedPlotted,
  ...railRows.filter((r) => r.ranking_eligible),
].sort((a, b) => a.asr_conditional - b.asr_conditional);
const toughest = toughestPool[0];
if (
  !priciest ||
  !toughest ||
  priciest.asr_conditional !== byAsrAsc.at(-1).asr_conditional
) {
  console.error(
    "gen-og: headline claim broken on this payload: the priciest ranked plotted run does not carry the highest attack success among the ranked plotted runs, so the headline and the top corner would be false",
  );
  process.exit(1);
}
const topSub = `${costIsLowerBound(priciest) ? `At least ${fmtUsdBound(priciest.total_cost_usd)}` : fmtUsd(priciest.total_cost_usd)} a run, and it flipped most of all`;
const bottomSub = `${pointName(toughest)} flipped least of all at ${fmtPct(toughest.asr_conditional)}`;
/* The off-scale disclosure, one sentence per excluded
 * point, composed here from the same rows the scatter
 * draws (RT-1). A flagged point's figure travels only with
 * its malformed decomposition clauses on the same surface,
 * the board's standing rule for flagged figures; where the
 * sealed family records do not derive the decomposition,
 * the disclosure the image owes cannot be composed at all,
 * and the build fails rather than state the figure bare or
 * drop the point in silence. */
const offScaleSentences = offScaleRows.map((r) => {
  const base = `${pointName(r)} sits above the chart's 0 to ${Math.round(axisMax * 100)} percent scale at ${fmtPct(r.asr_conditional)} attack success`;
  const tail = ", so its disc stands off the top of the plot rather than at a false position.";
  if (r.ranking_eligible) return base + tail;
  const d = flipDecomposition(r);
  if (d === null) {
    console.error(
      `gen-og: ${pointName(r)} sits above the chart's axis ceiling and is flagged, but its sealed family records do not derive the malformed decomposition its disclosure must carry, so the image cannot state its figure and the build fails rather than print it bare or drop it in silence`,
    );
    process.exit(1);
  }
  return `${base}, genuine flip rate ${fmtPct(d.genuineRate)}, with ${fmtPct(d.malformedShare)} of counted flips to malformed output${tail}`;
});
/* The rail extreme disclosure. A ranked run with no recorded
 * cost stands on the rail, outside the cost story the
 * headline tells, and nothing on the chart prints its figure.
 * When such a run flips more than the priciest costed run,
 * the headline could read as the whole story, so the run is
 * named here with its figure and the reason it stands apart,
 * the same treatment the off-scale sentences give the points
 * the plot does not draw. A run above the axis ceiling is
 * left to its off-scale sentence, so no run is disclosed
 * twice. The words say ranked costed runs because the
 * derivation stands on that population, the headline guard's
 * own, and a flagged costed run above them all is carried by
 * its off-scale sentence instead. */
const railExtremeRows = railRows.filter(
  (r) =>
    r.ranking_eligible &&
    priciest &&
    r.asr_conditional > priciest.asr_conditional &&
    !offScaleIds.has(r.run_id),
);
const railExtremeSentences = railExtremeRows.map(
  (r) =>
    `${pointName(r)} flipped more than any ranked costed run at ${fmtPct(r.asr_conditional)} attack success. It carries no recorded cost, so it stands on the no-cost rail, outside the cost story the headline tells.`,
);
const disclosureSentences = [
  ...offScaleSentences,
  ...railExtremeSentences,
];
const pointsSvg = [
  ...railDrawn.map((r) => disc(r, RAIL_CX, railY.get(r.run_id))),
  ...plottedXY.map((p) => disc(p.r, p.x, p.y)),
].join("\n");
/* The cost axis carries no title text of its own. The head's
 * sub-line already states the axis (attack success against
 * recorded cost per run, log scale) and the decade labels
 * carry their dollar signs, and the band under the decades
 * belongs to the disclosure block: a title there left the
 * disclosure's second line nowhere clear to sit once the
 * block carried more than one sentence. */
const scatterSvg = `<svg width="1200" height="630" viewBox="0 0 1200 630" class="chart">
  <rect x="48" y="${PLOT.y0}" width="88" height="${PLOT.y1 - PLOT.y0}" fill="#0c1015"/>
  ${gridSvg}
  <line x1="148" y1="${PLOT.y0 - 6}" x2="148" y2="${PLOT.y1}" stroke="#232c35"/>
  <line x1="${PLOT.x0}" y1="${PLOT.y1}" x2="${PLOT.x1}" y2="${PLOT.y1}" stroke="#232c35"/>
  ${decadeSvg.join("\n")}
  <text x="48" y="${PLOT.y0 - 10}" class="tick">No API cost</text>
  <text x="${PLOT.x0 + 32}" y="${PLOT.y0 - 10}" class="tick">Attack success, percent</text>
  <text x="520" y="252" class="corner">Expensive and fragile</text>
  <text x="520" y="278" class="corner-sub">${esc(topSub)}</text>
  <text x="${PLOT.x0}" y="468" class="corner" id="og-corner-bottom">Toughest on the chart</text>
  <text x="${PLOT.x0}" y="494" class="corner-sub" id="og-corner-bottom-sub">${esc(bottomSub)}</text>
  ${pointsSvg}
  ${railLabelsSvg}
  <g id="og-labels"></g>
</svg>`;

/* The share image draws no lower-bound tick. A floating arrow
 * beside a disc reads as a stray mark at feed size, and the
 * image has no caption to explain one, so the lower-bound fact
 * stays on the board page and out of the image. Tripwire: the
 * only lines in the scatter are the grid lines (one per axis
 * tick), the rail divider and the axis, and nothing draws a
 * polygon. */
const ogLineCount = (scatterSvg.match(/<line/g) ?? []).length;
if (scatterSvg.includes("<polygon") || ogLineCount !== axisTicks.length + 2) {
  console.error(
    `gen-og: unexpected glyph in the share image scatter (lines ${ogLineCount}, polygon present ${scatterSvg.includes("<polygon")}): the image draws no lower-bound tick or other floating mark`,
  );
  process.exit(1);
}

const html = `<!doctype html>
<html><head><meta charset="utf-8"><style>
@font-face { font-family: "Archivo"; src: url("../public/fonts/archivo.woff2") format("woff2"); }
* { margin: 0; box-sizing: border-box; }
body { width: 1200px; height: 630px; background: #05070a; color: #eef2f6;
  font-family: "Archivo", system-ui, sans-serif; overflow: hidden; }
.head { position: absolute; left: 48px; top: 40px; right: 48px; }
.word { font-size: 24px; font-weight: 700; letter-spacing: 0.05em; color: #2fbf71; }
h1 { font-size: 47px; font-weight: 700; letter-spacing: -0.02em; margin-top: 8px; }
.sub { font-size: 20px; color: #aebcc7; margin-top: 10px; }
.chart { position: absolute; left: 0; top: 0; }
.tick { fill: #71808f; font-size: 13px; }
.lab { fill: #d5dde4; font-size: 15px; font-weight: 600; }
.lab-sm { fill: #d5dde4; font-size: 12.5px; font-weight: 600; }
.fallback { position: absolute; left: 540px; top: 546px; width: 612px; font-size: 12.5px; line-height: 16px; color: #aebcc7; }
.offscale { position: absolute; left: 168px; top: 546px; width: 984px; font-size: 12.5px; line-height: 16px; color: #aebcc7; }
.mono { font-size: 11px; font-weight: 700; text-anchor: middle; dominant-baseline: central; }
.corner { fill: #eef2f6; font-size: 26px; font-weight: 700; letter-spacing: -0.01em; }
.corner-sub { fill: #aebcc7; font-size: 16px; font-weight: 550; }
.foot { position: absolute; left: 48px; bottom: 22px; font-size: 17px; color: #71808f; }
</style></head><body>
${scatterSvg}
<div class="head">
  <div class="word">PEIRA</div>
  <h1>The priciest model was the easiest to flip</h1>
  <p class="sub">Attack success against recorded cost per run (log scale), every full-suite model deciding the same paired cases.</p>
</div>
<div class="fallback" id="og-fallback" hidden></div>
${disclosureSentences.length > 0 ? `<div class="offscale" id="og-offscale">${esc(disclosureSentences.join(" "))}</div>` : ""}
<p class="foot">Peira decision robustness board. Dataset ${versions.dataset}, suite ${versions.suite}, updated ${dateWords}. Amber ring: a flagged result. peiratrial.dev</p>
</body></html>`;

/* Plotted label placement, run in the page so text is
 * measured with the real Archivo face (getBBox on a probe
 * element), never estimated. The labeled set is the plotted
 * population itself; every point is seated beside its own
 * disc from a fixed candidate list (no leader lines, no
 * per-run table). Costs are overlap areas against the
 * furniture (all text already on the canvas, including the
 * rail names, plus the headline and footer blocks) and the
 * labels seated so far, and against discs measured as the
 * circles they render as, not their bounding squares: a
 * label may pass a disc's empty corner, it may never touch
 * the circle. Seating runs most constrained first, then
 * relaxation passes move any label to a strictly cheaper
 * candidate while overlaps remain, and a repair phase can
 * reseat a no-cost blocker out of a stuck label's seat; if
 * an attempt still collides, the next deterministic seating
 * order tries, and the first attempt that verifies clean
 * wins. Verification is strict at zero tolerance: any label
 * touching a disc, the furniture, another label or the
 * canvas edge comes back in `failures`.
 *
 * Placement degrades in tiers and never fails the build.
 * The first tier is the candidate list above. The second
 * widens the reach, further seats around each disc derived
 * from the same geometry. The third seats the same widened
 * list at a smaller size. A label no tier can seat leaves
 * the plot and its point is named in words, with its attack
 * success and its cost, in the strip under the chart, the
 * same degradation the board scatter uses when a width
 * cannot name a point beside its disc. A claim the payload
 * breaks still fails the build in the guards above. A
 * crowded label layout is not a broken claim, so it
 * degrades instead. */
function placeOgLabels(pts) {
  const NS = "http://www.w3.org/2000/svg";
  const svg = document.querySelector("svg.chart");
  const group = document.getElementById("og-labels");
  const boxOf = (el) => {
    const b = el.getBBox();
    return { x: b.x, y: b.y, w: b.width, h: b.height };
  };
  const furniture = [...svg.querySelectorAll("text")].map(boxOf);
  for (const sel of [".head", ".foot"]) {
    const r = document.querySelector(sel).getBoundingClientRect();
    furniture.push({ x: r.x, y: r.y, w: r.width, h: r.height });
  }
  /* The disclosure block under the chart is furniture
   * too: a label seated over it would strike the words the
   * image owes the points it does not draw and the runs it
   * names there. */
  const offEl = document.getElementById("og-offscale");
  if (offEl) {
    const r = offEl.getBoundingClientRect();
    furniture.push({ x: r.x, y: r.y, w: r.width, h: r.height });
  }
  /* The rail column, left of the divider at x=148 in the
   * plot's vertical band, is reserved for the rail's own
   * names. A plotted label seated there reads as a rail
   * entry, a result with no API cost, whatever its own
   * disc's recorded cost says. */
  furniture.push({ x: 40, y: 200, w: 108, h: 332 });
  /* Discs sit inside translated groups, where getBBox reads
   * the local box and would put every disc at the origin;
   * the client rect gives the true centre and radius (the
   * svg is at the viewport origin at 1:1 scale). */
  let discs = [...svg.querySelectorAll("circle")].map((c) => {
    const r = c.getBoundingClientRect();
    return { cx: r.x + r.width / 2, cy: r.y + r.height / 2, r: r.width / 2 };
  });
  const overlap = (a, b) =>
    a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
  const area = (a, b) => {
    const ox = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x);
    const oy = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
    return ox > 0 && oy > 0 ? ox * oy : 0;
  };
  /* Distance from a box to a disc's centre: zero when the
   * centre is inside the box. The label touches the disc
   * when the distance is under the radius. */
  const distToDisc = (box, d) => {
    const dx = Math.max(box.x - d.cx, 0, d.cx - (box.x + box.w));
    const dy = Math.max(box.y - d.cy, 0, d.cy - (box.y + box.h));
    return Math.hypot(dx, dy);
  };
  /* The bottom corner pair starts at the plot's left edge,
   * where the rail names also live. The rail names are static
   * markup the placement pass cannot move, and a rail name
   * long enough or a rail row landing at the corner's height
   * strikes the corner's words. So the pair shifts right by
   * derivation before anything else measures the canvas: the
   * smallest x at which its block, both lines together,
   * clears every rail name whose band it shares, measured
   * from the rendered boxes. Discs are not the corner's
   * problem here: the RT-2 pass below already moves a disc
   * that strikes a claim box, or names its point in words.
   * The furniture list above already holds the corner's
   * starting boxes, so the text boxes are remeasured after
   * the shift. A pair that cannot clear within the plot
   * keeps its last position and the corner check after
   * placement fails the build, the same discipline as the
   * disclosure check. The block carries 2px of breathing
   * room on its vertical edges, each shift step stops 16px
   * past the name it clears, and the loop is bounded at 64
   * steps, far beyond the rail's row count, since every
   * step clears at least one more name. */
  {
    const title = document.getElementById("og-corner-bottom");
    const sub = document.getElementById("og-corner-bottom-sub");
    if (title && sub) {
      const railLabelBoxes = [...svg.querySelectorAll("text.lab")]
        .filter((el) => el.parentNode === svg)
        .map(boxOf);
      const t0 = boxOf(title);
      const s0 = boxOf(sub);
      const blockW = Math.max(t0.w, s0.w);
      const blockY = t0.y - 2;
      const blockH = s0.y + s0.h + 2 - blockY;
      let cx = t0.x;
      for (let guard = 0; guard < 64; guard++) {
        const block = { x: cx, y: blockY, w: blockW, h: blockH };
        let next = cx;
        for (const b of railLabelBoxes) {
          if (overlap(block, b)) next = Math.max(next, b.x + b.w + 16);
        }
        if (next === cx) break;
        cx = next;
      }
      if (cx !== t0.x) {
        title.setAttribute("x", cx);
        sub.setAttribute("x", cx);
        const fresh = [...svg.querySelectorAll("text")].map(boxOf);
        furniture.splice(0, fresh.length, ...fresh);
      }
    }
  }
  /* The corner claim blocks are obstacles for the discs
   * themselves, not only for the labels (red team finding
   * RT-2 on the #521 review: two plotted discs sat on the
   * top corner sub-line and covered part of its price
   * figure). A disc whose circle intersects a claim box
   * moves along its own cost column by the smallest shift
   * that clears every claim box, no more than 56px, without
   * landing on another disc, and its label then seats
   * against the moved disc, the same legibility discipline
   * the nudge pass applies between discs. A disc no shift
   * can clear leaves the plot, and its point is named in
   * words in the strip with its figures, like a label no
   * tier could seat. The rail discs stand left of every
   * claim box; the pass runs over the plotted discs only,
   * which are the discs it can move. */
  const claimBoxes = [
    ...svg.querySelectorAll("text.corner, text.corner-sub"),
  ].map(boxOf);
  const discGroups = [...svg.querySelectorAll("g")].filter((g) =>
    g.querySelector("circle"),
  );
  const railCount = discs.length - pts.length;
  const preDegraded = [];
  const seatPts = [];
  pts.forEach((p, i) => {
    const di = railCount + i;
    const d = discs[di];
    if (!claimBoxes.some((b) => distToDisc(b, d) < d.r - 0.01)) {
      seatPts.push(p);
      return;
    }
    let moved = false;
    for (let step = 1; step <= 56 && !moved; step++) {
      for (const dy of [step, -step]) {
        const nd = { cx: d.cx, cy: d.cy + dy, r: d.r };
        if (nd.cy - nd.r < 0 || nd.cy + nd.r > 630) continue;
        if (claimBoxes.some((b) => distToDisc(b, nd) < nd.r - 0.01))
          continue;
        if (
          discs.some(
            (o, j) =>
              j !== di && Math.hypot(o.cx - nd.cx, o.cy - nd.cy) < 20,
          )
        )
          continue;
        discGroups[di].setAttribute(
          "transform",
          `translate(${nd.cx} ${nd.cy})`,
        );
        p.y = nd.cy;
        discs[di] = nd;
        moved = true;
        break;
      }
    }
    if (moved) seatPts.push(p);
    else {
      discGroups[di].remove();
      preDegraded.push(p);
    }
  });
  if (preDegraded.length > 0) {
    const held = new Set(preDegraded.map((p) => p.runId));
    discs = discs.filter(
      (d, j) => j < railCount || !held.has(pts[j - railCount].runId),
    );
  }
  const CANDS = [
    { dx: 18, dy: 5, anchor: "start" },
    { dx: -18, dy: 5, anchor: "end" },
    { dx: 0, dy: -20, anchor: "middle" },
    { dx: 0, dy: 31, anchor: "middle" },
    { dx: 18, dy: -16, anchor: "start" },
    { dx: -18, dy: -16, anchor: "end" },
    { dx: 18, dy: 28, anchor: "start" },
    { dx: -18, dy: 28, anchor: "end" },
    { dx: 20, dy: 42, anchor: "start" },
    { dx: -20, dy: 42, anchor: "end" },
    { dx: 14, dy: 5, anchor: "start" },
    { dx: -14, dy: 5, anchor: "end" },
    { dx: 18, dy: -10, anchor: "start" },
    { dx: -18, dy: -10, anchor: "end" },
    { dx: 18, dy: 22, anchor: "start" },
    { dx: -18, dy: 22, anchor: "end" },
    { dx: 0, dy: -30, anchor: "middle" },
    { dx: 0, dy: 44, anchor: "middle" },
    { dx: 26, dy: 5, anchor: "start" },
    { dx: -26, dy: 5, anchor: "end" },
  ];
  /* The widened tier: further seats on the same eight
   * bearings, for payloads whose points crowd the first
   * tier's reach. The bearings and the disc geometry are
   * the derivation. No seat is keyed to a run. */
  const CANDS_WIDE = [
    ...CANDS,
    { dx: 34, dy: 5, anchor: "start" },
    { dx: -34, dy: 5, anchor: "end" },
    { dx: 34, dy: -24, anchor: "start" },
    { dx: -34, dy: -24, anchor: "end" },
    { dx: 34, dy: 36, anchor: "start" },
    { dx: -34, dy: 36, anchor: "end" },
    { dx: 0, dy: -42, anchor: "middle" },
    { dx: 0, dy: 56, anchor: "middle" },
    { dx: 44, dy: 18, anchor: "start" },
    { dx: -44, dy: 18, anchor: "end" },
    { dx: 16, dy: -34, anchor: "start" },
    { dx: -16, dy: -34, anchor: "end" },
    { dx: 16, dy: 48, anchor: "start" },
    { dx: -16, dy: 48, anchor: "end" },
  ];
  const inCanvas = (box) =>
    box.x >= 4 && box.y >= 4 && box.x + box.w <= 1196 && box.y + box.h <= 626;
  const probe = document.createElementNS(NS, "text");
  group.appendChild(probe);
  let probeCls = "lab";
  const boxFor = (p, cand) => {
    probe.setAttribute("class", probeCls);
    probe.setAttribute("x", String(p.x + cand.dx));
    probe.setAttribute("y", String(p.y + cand.dy));
    probe.setAttribute("text-anchor", cand.anchor);
    probe.textContent = p.name;
    return boxOf(probe);
  };
  /* Verification is zero-tolerance: no intersection, with
   * no minimum air. Visible-air floors (a pixel to a disc,
   * two between labels, the board audit's F-03 separation)
   * were attempted in design cycle 4 and the current
   * population does not seat under any of them; the cycle
   * record carries the failure list as evidence for the
   * share image's naming decision. */
  const verify = (placed) => {
    const bad = [];
    for (const q of placed) {
      const box = boxOf(q.el);
      if (!inCanvas(box)) bad.push(`${q.runId} (canvas)`);
      if (discs.some((d) => distToDisc(box, d) < d.r - 0.01))
        bad.push(`${q.runId} (disc)`);
      if (furniture.some((f) => overlap(box, f)))
        bad.push(`${q.runId} (furniture)`);
      for (const o of placed) {
        if (o !== q && overlap(box, boxOf(o.el))) {
          bad.push(`${q.runId} (label)`);
          break;
        }
      }
    }
    if (placed.length !== seatPts.length) bad.push("count");
    return bad;
  };
  const attempt = (order, CANDS, cls) => {
    probeCls = cls;
    for (const el of [...group.querySelectorAll("text[data-run-id]")])
      el.remove();
    const placed = [];
    const costOf = (box, self, candIndex) => {
      let cost = candIndex * 2;
      if (!inCanvas(box)) cost += 100000;
      for (const d of discs) {
        if (distToDisc(box, d) < d.r - 0.01) {
          cost +=
            400 +
            area(box, {
              x: d.cx - d.r,
              y: d.cy - d.r,
              w: d.r * 2,
              h: d.r * 2,
            });
        }
      }
      for (const f of furniture) cost += area(box, f) * 40;
      for (const q of placed) {
        if (q !== self) cost += area(box, q.box) * 40;
      }
      return cost;
    };
    const applySeat = (rec, cand) => {
      rec.el.setAttribute("x", String(rec.p.x + cand.dx));
      rec.el.setAttribute("y", String(rec.p.y + cand.dy));
      rec.el.setAttribute("text-anchor", cand.anchor);
      rec.box = boxOf(rec.el);
      rec.cand = cand;
    };
    for (const p of order) {
      const el = document.createElementNS(NS, "text");
      el.setAttribute("class", cls);
      el.setAttribute("data-run-id", p.runId);
      el.textContent = p.name;
      group.appendChild(el);
      const rec = { el, box: null, runId: p.runId, p, cand: null };
      placed.push(rec);
      let best = CANDS[0];
      let bestCost = Infinity;
      CANDS.forEach((c, i) => {
        const cost = costOf(boxFor(p, c), rec, i);
        if (cost < bestCost) {
          bestCost = cost;
          best = c;
        }
      });
      applySeat(rec, best);
    }
    for (let pass = 0; pass < 400; pass++) {
      let moved = false;
      const seq = pass % 2 === 0 ? placed : [...placed].reverse();
      for (const rec of seq) {
        const curIdx = CANDS.indexOf(rec.cand);
        let bestCost = costOf(rec.box, rec, Math.max(0, curIdx));
        let best = rec.cand;
        CANDS.forEach((c, i) => {
          if (c === rec.cand) return;
          const cost = costOf(boxFor(rec.p, c), rec, i);
          if (cost < bestCost - 0.5) {
            bestCost = cost;
            best = c;
          }
        });
        if (best !== rec.cand) {
          applySeat(rec, best);
          moved = true;
        }
      }
      if (!moved) break;
    }
    /* Repair: a label still in violation may need a seat
     * another label occupies at no cost to itself. For each
     * violating label, try its candidates in cost order; a
     * candidate blocked only by labels is admitted when
     * every blocker can reseat, one at a time against live
     * positions, to a seat clean against every disc, the
     * furniture and every other label. */
    const recBad = (rec) => {
      const box = boxOf(rec.el);
      return (
        !inCanvas(box) ||
        discs.some((d) => distToDisc(box, d) < d.r - 0.01) ||
        furniture.some((f) => overlap(box, f)) ||
        placed.some((o) => o !== rec && overlap(box, o.box))
      );
    };
    for (let round = 0; round < 4; round++) {
      const bad = placed.filter(recBad);
      if (bad.length === 0) break;
      let progressed = false;
      for (const rec of bad) {
        const cands = CANDS.map((c, i) => ({
          c,
          i,
          box: boxFor(rec.p, c),
        })).sort((a, b) => costOf(a.box, rec, a.i) - costOf(b.box, rec, b.i));
        for (const { c, box } of cands) {
          if (!inCanvas(box)) continue;
          if (discs.some((d) => distToDisc(box, d) < d.r + 0.5)) continue;
          if (furniture.some((f) => overlap(box, f))) continue;
          const blockers = placed.filter(
            (o) => o !== rec && overlap(box, o.box),
          );
          let ok = true;
          for (const b of blockers) {
            const alt = CANDS.find((cc) => {
              if (cc === b.cand) return false;
              const bb = boxFor(b.p, cc);
              if (!inCanvas(bb)) return false;
              if (discs.some((d) => distToDisc(bb, d) < d.r + 0.5))
                return false;
              if (furniture.some((f) => overlap(bb, f))) return false;
              if (overlap(bb, box)) return false;
              return placed.every(
                (o) => o === b || o === rec || !overlap(bb, o.box),
              );
            });
            if (!alt) {
              ok = false;
              break;
            }
            applySeat(b, alt);
          }
          if (!ok) continue;
          applySeat(rec, c);
          progressed = true;
          break;
        }
      }
      if (!progressed) break;
    }
    return { placed, bad: verify(placed) };
  };
  const byRunId = (a, b) => (a.runId < b.runId ? -1 : 1);
  /* One tier: every seating order over one candidate list at
   * one size. Returns the clean attempt, or records the
   * attempt with the fewest violations as the degradation
   * base. */
  let best = null;
  const runTier = (CANDS, cls) => {
    probeCls = cls;
    const freeCounts = new Map(
      seatPts.map((p) => [
        p.runId,
        CANDS.filter((c) => {
          const box = boxFor(p, c);
          return (
            inCanvas(box) &&
            discs.every((d) => distToDisc(box, d) >= d.r + 1) &&
            furniture.every((f) => !overlap(box, f))
          );
        }).length,
      ]),
    );
    const orders = [
      [...seatPts].sort(
        (a, b) => freeCounts.get(a.runId) - freeCounts.get(b.runId) || byRunId(a, b),
      ),
      [...seatPts].sort(
        (a, b) => freeCounts.get(a.runId) - freeCounts.get(b.runId) || byRunId(b, a),
      ),
      [...seatPts].sort((a, b) => a.y - b.y || a.x - b.x),
      [...seatPts].sort((a, b) => a.x - b.x || a.y - b.y),
      [...seatPts].sort((a, b) => b.y - a.y || b.x - a.x),
      [...seatPts].sort((a, b) => b.x - a.x || b.y - a.y),
      [...seatPts].sort(
        (a, b) => freeCounts.get(b.runId) - freeCounts.get(a.runId) || a.y - b.y,
      ),
      [...seatPts].sort(
        (a, b) => freeCounts.get(a.runId) - freeCounts.get(b.runId) || b.y - a.y,
      ),
    ];
    for (const order of orders) {
      const { placed, bad } = attempt(order, CANDS, cls);
      if (bad.length === 0) return { clean: true, placed };
      if (best === null || bad.length < best.bad.length) {
        best = { bad, order, CANDS, cls };
      }
    }
    return { clean: false };
  };
  /* The words strip, shared by the degradation paths: the
   * points a tier could not seat (too crowded at their
   * discs) and the points the claim pass held off the plot
   * (their discs could not be drawn clear of the corner
   * readings) are each named with their figures, under a
   * lead-in that states their own reason. Where the words
   * land depends on the image: inside the disclosure block
   * when the image carries one, sized and cleared by the
   * disclosure check after placement, and in the strip
   * under the chart when it does not, where the strip steps
   * its size down until it clears the footer, measured
   * against the real footer block. Either way the words
   * themselves never strike another element. */
  const showStrip = (crowded, heldOff) => {
    const parts = [];
    if (crowded.length > 0) {
      parts.push(
        "Too crowded at their discs, so named here. " +
          crowded.map((p) => p.words).join(", "),
      );
    }
    if (heldOff.length > 0) {
      parts.push(
        (heldOff.length === 1
          ? "Its disc could not be drawn clear of the corner readings, so it is named here. "
          : "Their discs could not be drawn clear of the corner readings, so they are named here. ") +
          heldOff.map((p) => p.words).join(", "),
      );
    }
    if (parts.length === 0) return;
    const words = parts.join(" ");
    /* The words ride in the disclosure block when the image
     * carries one. The band under the chart holds one text
     * block, not two: a separate strip under a two-line
     * disclosure has no clear line left above the footer, so
     * its words strike the footer text. The disclosure check
     * after placement steps the merged block down until the
     * whole of it clears. With no disclosure to carry them,
     * the words take the strip under the chart as before. */
    if (offEl) {
      offEl.textContent = `${offEl.textContent} ${words}`;
      return;
    }
    const strip = document.getElementById("og-fallback");
    strip.hidden = false;
    strip.textContent = words;
    const footRect = document.querySelector(".foot").getBoundingClientRect();
    let size = 12.5;
    while (size > 9) {
      const r = strip.getBoundingClientRect();
      if (r.bottom <= footRect.top - 2) break;
      size -= 0.5;
      strip.style.fontSize = `${size}px`;
      strip.style.lineHeight = `${Math.round(size * 1.28)}px`;
    }
  };
  for (const [cands, cls] of [
    [CANDS, "lab"],
    [CANDS_WIDE, "lab"],
    [CANDS_WIDE, "lab-sm"],
  ]) {
    const r = runTier(cands, cls);
    if (r.clean) {
      if (preDegraded.length > 0) {
        showStrip([], preDegraded);
        probe.remove();
        return {
          ok: true,
          placed: r.placed.length,
          degraded: preDegraded.map((p) => p.name),
          degradedWords: preDegraded.map((p) => p.words),
        };
      }
      probe.remove();
      return { ok: true, placed: r.placed.length, degraded: [] };
    }
  }
  /* The words tier. Rebuild the least violating attempt,
   * lift the labels it could not seat off the plot, and name
   * those points in the strip under the chart with the
   * figures the payload carries for them. The strip steps
   * its size down until it clears the footer, measured
   * against the real footer block, so the words themselves
   * never strike another element. Removing labels cannot
   * create a violation, so the seated labels stand verified
   * as they were. */
  const { placed } = attempt(best.order, best.CANDS, best.cls);
  const badIds = new Set(
    best.bad.map((s) => s.split(" ")[0]).filter((s) => s !== "count"),
  );
  const degraded = [];
  for (const rec of placed) {
    if (badIds.has(rec.runId)) {
      rec.el.remove();
      degraded.push(rec.p);
    }
  }
  showStrip(degraded, preDegraded);
  probe.remove();
  return {
    ok: true,
    placed: placed.length - degraded.length,
    degraded: [...degraded, ...preDegraded].map((p) => p.name),
    degradedWords: [...degraded, ...preDegraded].map((p) => p.words),
  };
}

mkdirSync(path.join(root, "public"), { recursive: true });
mkdirSync(path.join(root, ".og"), { recursive: true });
const ogHtml = path.join(root, ".og", "og.html");
writeFileSync(ogHtml, html);

/* Browser discovery and environment (round 10, 2026-10-23).
 * After the overnight runtime restarts, the headless shell in
 * the Playwright cache dies at launch in this sandbox (mmap
 * denied, then SIGILL) and the full Chrome in the Puppeteer
 * cache dies with it; the full Chromium in the Playwright
 * cache launches. Discovery prefers it and falls back to the
 * headless shell. The browser also gets a proxy-free
 * environment: the sandbox proxy variables make single-process
 * Chrome fail on its V8 proxy resolver, and every page these
 * scripts load is local. The launch runs single-process for
 * the same reason; the engine and its measurements are the
 * same. */
const chromeOverride =
  process.env.PUPPETEER_EXECUTABLE_PATH ?? process.env.CHROME_PATH;
const chromeHits = chromeOverride
  ? [chromeOverride]
  : [
      ...globSync(
        ".cache/ms-playwright/chromium-*/chrome-linux64/chrome",
        { cwd: homedir() },
      ).map((p) => path.join(homedir(), p)),
      ...globSync(
        ".cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell",
        { cwd: homedir() },
      ).map((p) => path.join(homedir(), p)),
    ];
if (chromeHits.length === 0) {
  console.error(
    "gen-og: no Chromium found in the Playwright cache and no PUPPETEER_EXECUTABLE_PATH or CHROME_PATH set",
  );
  process.exit(1);
}
const browserEnv = { ...process.env };
for (const k of Object.keys(browserEnv)) {
  if (/proxy/i.test(k)) delete browserEnv[k];
}
const browser = await puppeteer.launch({
  executablePath: chromeHits[0],
  env: browserEnv,
  /* The launch timeout is load tolerance for the shared box
   * (round 10): under the trial lanes the browser can take
   * well over the 30 s default to come up. */
  timeout: 180000,
  args: ["--no-sandbox", "--no-zygote", "--single-process", "--force-color-profile=srgb"],
});
const page = await browser.newPage();
await page.setViewport({ width: 1200, height: 630 });
await page.goto(`file://${ogHtml}`, { waitUntil: "networkidle0" });
await page.evaluate(() => document.fonts.ready);
const placement = await page.evaluate(placeOgLabels, plottedPts);
if (placement.degraded.length > 0) {
  console.log(
    `gen-og: ${placement.degraded.length} plotted label${placement.degraded.length === 1 ? "" : "s"} could not seat beside the disc on this payload and ${placement.degraded.length === 1 ? "is" : "are"} named in words in the strip under the chart instead: ${(placement.degradedWords ?? placement.degraded).join(", ")}`,
  );
}
if (offScaleRows.length > 0) {
  console.log(
    `gen-og: ${offScaleRows.length} full suite point${offScaleRows.length === 1 ? "" : "s"} sit${offScaleRows.length === 1 ? "s" : ""} above the chart's 0 to ${Math.round(axisMax * 100)} percent scale and ${offScaleRows.length === 1 ? "is" : "are"} disclosed in words in the image instead of drawn: ${offScaleRows.map((r) => pointName(r)).join(", ")}`,
  );
}
/* The disclosure the image owes is verified where it is
 * drawn: its block must sit inside the canvas and strike
 * nothing, no text in the scatter, neither the headline nor
 * the footer block, and not the words strip when that is
 * shown. The block steps its size down until it clears, and
 * a disclosure that cannot be placed fails the build
 * (RT-1): an image that cannot carry the words does not
 * print without them. */
function measureDisclosure() {
  const el = document.getElementById("og-offscale");
  if (!el) return { present: false, ok: true };
  const svg = document.querySelector("svg.chart");
  const boxOf = (e) => {
    const b = e.getBBox();
    return { x: b.x, y: b.y, w: b.width, h: b.height };
  };
  const rectOf = (e) => {
    const r = e.getBoundingClientRect();
    return { x: r.x, y: r.y, w: r.width, h: r.height };
  };
  const overlap = (a, b) =>
    a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
  const mine = rectOf(el);
  const obstacles = [
    rectOf(document.querySelector(".head")),
    rectOf(document.querySelector(".foot")),
  ];
  const strip = document.getElementById("og-fallback");
  if (strip && !strip.hidden) obstacles.push(rectOf(strip));
  for (const t of svg.querySelectorAll("text")) obstacles.push(boxOf(t));
  const inCanvas =
    mine.x >= 0 && mine.y >= 0 && mine.x + mine.w <= 1200 && mine.y + mine.h <= 630;
  return {
    present: true,
    ok: inCanvas && !obstacles.some((o) => overlap(mine, o)),
    box: mine,
  };
}
if (railExtremeSentences.length > 0) {
  console.log(
    `gen-og: ${railExtremeSentences.length} ranked no-cost run${railExtremeSentences.length === 1 ? "" : "s"} flipped more than the priciest costed run and ${railExtremeSentences.length === 1 ? "is" : "are"} disclosed in words in the image: ${railExtremeRows.map((r) => pointName(r)).join(", ")}`,
  );
}
if (disclosureSentences.length > 0) {
  let dSize = 12.5;
  let dCheck = await page.evaluate(measureDisclosure);
  while (!dCheck.ok && dSize > 9.5) {
    dSize -= 1;
    await page.evaluate((s) => {
      const el = document.getElementById("og-offscale");
      el.style.fontSize = `${s}px`;
      el.style.lineHeight = `${Math.round(s * 1.28)}px`;
    }, dSize);
    dCheck = await page.evaluate(measureDisclosure);
  }
  if (!dCheck.ok) {
    await browser.close();
    console.error(
      "gen-og: the disclosure block cannot be placed inside the image without striking another element, so the image does not print without the words it owes",
    );
    process.exit(1);
  }
}
/* The bottom corner readings are verified where they are
 * drawn: after the placement pass shifted them clear of the
 * rail names, neither line may strike a rail name or leave
 * the plot. A corner that cannot sit clear fails the build
 * rather than print words over a name. The plot bounds are
 * PLOT.x0 and PLOT.x1 with half a pixel of tolerance,
 * restated as literals because this check runs in the page,
 * where the scaffold's constants are out of scope. */
function measureCorner() {
  const svg = document.querySelector("svg.chart");
  const boxOf = (e) => {
    const b = e.getBBox();
    return { x: b.x, y: b.y, w: b.width, h: b.height };
  };
  const overlap = (a, b) =>
    a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
  const title = document.getElementById("og-corner-bottom");
  const sub = document.getElementById("og-corner-bottom-sub");
  if (!title || !sub) return { present: false, ok: true };
  const mine = [boxOf(title), boxOf(sub)];
  const rail = [...svg.querySelectorAll("text.lab")]
    .filter((el) => el.parentNode === svg)
    .map(boxOf);
  const inPlot = mine.every((b) => b.x >= 167.5 && b.x + b.w <= 1152.5);
  return {
    present: true,
    ok: inPlot && !mine.some((b) => rail.some((o) => overlap(b, o))),
    boxes: mine,
  };
}
const cornerCheck = await page.evaluate(measureCorner);
if (!cornerCheck.ok) {
  await browser.close();
  console.error(
    "gen-og: the bottom corner readings strike a rail name or leave the plot on this payload, so the image does not print with its words over a name",
  );
  process.exit(1);
}
/* Test instrumentation, off unless PEIRA_OG_PROBE is set:
 * the placed geometry (claim blocks, discs, labels, the
 * disclosure block, the strip) written as JSON beside the
 * page, so the generator tests can assert on the rendered
 * image's intersections instead of trusting the log. */
if (process.env.PEIRA_OG_PROBE) {
  const probe = await page.evaluate(() => {
    const svg = document.querySelector("svg.chart");
    const boxOf = (e) => {
      const b = e.getBBox();
      return { x: b.x, y: b.y, w: b.width, h: b.height };
    };
    const rectOf = (e) => {
      const r = e.getBoundingClientRect();
      return { x: r.x, y: r.y, w: r.width, h: r.height };
    };
    const off = document.getElementById("og-offscale");
    const strip = document.getElementById("og-fallback");
    return {
      claims: [...svg.querySelectorAll("text.corner, text.corner-sub")].map(
        (el) => ({ text: el.textContent, box: boxOf(el) }),
      ),
      discs: [...svg.querySelectorAll("circle")].map((c) => {
        const r = c.getBoundingClientRect();
        return { cx: r.x + r.width / 2, cy: r.y + r.height / 2, r: r.width / 2 };
      }),
      labels: [...svg.querySelectorAll("#og-labels text")].map((el) => ({
        name: el.textContent,
        runId: el.getAttribute("data-run-id"),
        box: boxOf(el),
      })),
      railLabels: [...svg.querySelectorAll("text.lab")]
        .filter((el) => el.parentNode === svg)
        .map((el) => ({ name: el.textContent, box: boxOf(el) })),
      disclosure: off
        ? { text: off.textContent, box: rectOf(off) }
        : null,
      strip: { hidden: strip.hidden, text: strip.textContent },
    };
  });
  writeFileSync(path.join(root, ".og", "probe.json"), JSON.stringify(probe));
}
await page.screenshot({ path: path.join(root, "public", "og.png") });
await browser.close();

copyFileSync(
  path.join(root, "data", "payload.json"),
  path.join(root, "public", "payload.json"),
);
console.log(
  `gen-og: wrote public/og.png (1200x630) and public/payload.json from ${results} results, board date ${dateWords}; labelled ${placement.placed} of ${plottedPts.length} plotted points and all ${railDrawn.length} rail points`,
);
