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
const versions = {
  dataset: payload.ranked[0].dataset_version,
  suite: payload.ranked[0].suite,
};
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
 * image cannot drift from the board. The headline is a fact
 * of this payload: the priciest run (claude-fable-5-1,
 * $130.31) also carries the highest attack success on the
 * board. */
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
const PLOT = { x0: 168, x1: 1152, y0: 218, y1: 516 };
const RAIL_CX = 92;
const xOf = (c) =>
  PLOT.x0 +
  ((Math.log10(c) - Math.log10(domLo)) /
    (Math.log10(domHi) - Math.log10(domLo))) *
    (PLOT.x1 - PLOT.x0);
const yOf = (a) => PLOT.y0 + (1 - a / 0.3) * (PLOT.y1 - PLOT.y0);
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
const gridSvg = [0, 0.1, 0.2, 0.3]
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
const railSpread = [...railRows]
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
 * A point the pass cannot seat fails the build, so a name
 * can never drop silently. */
const railLabelsSvg = railRows
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
const plottedXY = plotted.map((r) => ({
  runId: r.run_id,
  r,
  x: xOf(r.total_cost_usd),
  y: yOf(r.asr_conditional),
}));
nudgePoints(plottedXY, 24, 12);
const plottedPts = plottedXY.map((p) => ({
  runId: p.runId,
  name: pointName(p.r),
  x: p.x,
  y: p.y,
}));
const pointsSvg = [
  ...railRows.map((r) => disc(r, RAIL_CX, railY.get(r.run_id))),
  ...plottedXY.map((p) => disc(p.r, p.x, p.y)),
].join("\n");
const scatterSvg = `<svg width="1200" height="630" viewBox="0 0 1200 630" class="chart">
  <rect x="48" y="${PLOT.y0}" width="88" height="${PLOT.y1 - PLOT.y0}" fill="#0c1015"/>
  ${gridSvg}
  <line x1="148" y1="${PLOT.y0 - 6}" x2="148" y2="${PLOT.y1}" stroke="#232c35"/>
  <line x1="${PLOT.x0}" y1="${PLOT.y1}" x2="${PLOT.x1}" y2="${PLOT.y1}" stroke="#232c35"/>
  ${decadeSvg.join("\n")}
  <text x="48" y="${PLOT.y0 - 10}" class="tick">No API cost</text>
  <text x="${PLOT.x0 + 32}" y="${PLOT.y0 - 10}" class="tick">Attack success, percent</text>
  <text x="520" y="252" class="corner">Expensive and fragile</text>
  <text x="520" y="278" class="corner-sub">The priciest run flipped most of all</text>
  <text x="${PLOT.x0}" y="468" class="corner">Near-free and tough</text>
  <text x="${PLOT.x0}" y="494" class="corner-sub">Jev 1.14 held at twenty cents a run</text>
  ${pointsSvg}
  ${railLabelsSvg}
  <g id="og-labels"></g>
  <text x="${PLOT.x0}" y="572" class="tick">Recorded cost per run, US dollars, log scale</text>
</svg>`;

/* The share image draws no lower-bound tick. A floating arrow
 * beside a disc reads as a stray mark at feed size, and the
 * image has no caption to explain one, so the lower-bound fact
 * stays on the board page and out of the image. Tripwire: the
 * only lines in the scatter are the four grid lines, the rail
 * divider and the axis, and nothing draws a polygon. */
const ogLineCount = (scatterSvg.match(/<line/g) ?? []).length;
if (scatterSvg.includes("<polygon") || ogLineCount !== 6) {
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
 * wins. Verification
 * is strict at zero tolerance: any label touching a disc,
 * the furniture, another label or the canvas edge comes
 * back in `failures` and the generator exits non-zero
 * rather than ship an image with a name missing or struck. */
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
  const discs = [...svg.querySelectorAll("circle")].map((c) => {
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
  const inCanvas = (box) =>
    box.x >= 4 && box.y >= 4 && box.x + box.w <= 1196 && box.y + box.h <= 626;
  const probe = document.createElementNS(NS, "text");
  probe.setAttribute("class", "lab");
  group.appendChild(probe);
  const boxFor = (p, cand) => {
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
    if (placed.length !== pts.length) bad.push("count");
    return bad;
  };
  const attempt = (order) => {
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
      el.setAttribute("class", "lab");
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
  const freeCounts = new Map(
    pts.map((p) => [
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
    [...pts].sort(
      (a, b) => freeCounts.get(a.runId) - freeCounts.get(b.runId) || byRunId(a, b),
    ),
    [...pts].sort(
      (a, b) => freeCounts.get(a.runId) - freeCounts.get(b.runId) || byRunId(b, a),
    ),
    [...pts].sort((a, b) => a.y - b.y || a.x - b.x),
    [...pts].sort((a, b) => a.x - b.x || a.y - b.y),
    [...pts].sort((a, b) => b.y - a.y || b.x - a.x),
    [...pts].sort((a, b) => b.x - a.x || b.y - a.y),
    [...pts].sort(
      (a, b) => freeCounts.get(b.runId) - freeCounts.get(a.runId) || a.y - b.y,
    ),
    [...pts].sort(
      (a, b) => freeCounts.get(a.runId) - freeCounts.get(b.runId) || b.y - a.y,
    ),
  ];
  let bestBad = null;
  for (const order of orders) {
    const { placed, bad } = attempt(order);
    if (bad.length === 0) {
      probe.remove();
      return { ok: true, placed: placed.length };
    }
    if (bestBad === null || bad.length < bestBad.length) bestBad = bad;
  }
  probe.remove();
  return { ok: false, failures: bestBad };
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
if (!placement.ok) {
  console.error(
    `gen-og: label placement failed for ${placement.failures.join(", ")}: every plotted point must be named in the share image`,
  );
  await browser.close();
  process.exit(1);
}
await page.screenshot({ path: path.join(root, "public", "og.png") });
await browser.close();

copyFileSync(
  path.join(root, "data", "payload.json"),
  path.join(root, "public", "payload.json"),
);
console.log(
  `gen-og: wrote public/og.png (1200x630) and public/payload.json from ${results} results, board date ${dateWords}; labelled ${placement.placed} of ${plottedPts.length} plotted points and all ${railRows.length} rail points`,
);
