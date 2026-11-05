/* The share images, generated from data/payload.json: the
 * landscape card (public/og.png, 1200x630) and the portrait
 * card (public/og-portrait.png, 1080x1350), one derivation
 * feeding both. The design is the instrument panel's share
 * grammar: the headline claim the payload must support or
 * the build fails, the cost scatter with its headline
 * subject singled out in white, a numeral stack of three
 * readings beside it, the points the plot cannot name
 * carried in words under it, and the no-cost rail as a
 * ladder that lives inside a stated pixel budget. Every
 * figure derives from the payload at generation time; a
 * flagged figure never prints without its malformed
 * decomposition on the same card. */

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
  const [mant, expS] = s.split(/[eE]/);
  const exp = parseInt(expS, 10);
  const neg = mant.startsWith("-");
  const body = neg ? mant.slice(1) : mant;
  const [ip, fp = ""] = body.split(".");
  const digits = ip + fp;
  const point = ip.length + exp;
  let out;
  if (point <= 0) out = "0." + "0".repeat(-point) + digits;
  else if (point >= digits.length) out = digits + "0".repeat(point - digits.length);
  else out = digits.slice(0, point) + "." + digits.slice(point);
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
 * words under the plot take this form too, so a plain
 * sub-cent cost named there never prints as zero dollars
 * either. */
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
 * cards print it with the qualifier. The subject line follows
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
/* The cost as the card's words carry it, the page's rule
 * (lib/topData's costWords): no recorded cost, a lower bound
 * with its qualifier, or the rounded figure. */
const costWords = (r) => {
  if (r.total_cost_usd === null || r.total_cost_usd === undefined) {
    return "no recorded cost";
  }
  return costIsLowerBound(r)
    ? `at least ${fmtUsdBound(r.total_cost_usd)}`
    : fmtUsd(r.total_cost_usd);
};

/* The flip decomposition, a port of lib/payload's
 * flipDecomposition (familyRecords, flipCounts and countOf
 * included): how many of a flagged result's counted flips
 * were malformed output rather than a changed decision, and
 * the flip rate with those removed, cross-checked against
 * the row's printed attack success. Where the sealed family
 * records are missing or disagree with the printed figure
 * the port returns null and no decomposition may be stated,
 * the same failure semantics the board applies. The flagged
 * reading below states a flagged figure only with this
 * decomposition beside it. */
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
const esc = (t) =>
  String(t)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");

/* Populations. The plot carries every full suite result
 * with a recorded cost above zero; the ladder carries the
 * rest of the full suite, the results with no recorded API
 * cost. Slices stand apart from both, as on the board. */
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
 * asrAxisFor: the smallest tenth at or above the worst
 * ranked rate, floored at 0.3. */
function asrAxisCeiling(maxRate) {
  const stepped = Math.ceil((maxRate - 1e-9) / 0.1) * 0.1;
  return Math.round(Math.max(0.3, stepped) * 10) / 10;
}
const axisMax = asrAxisCeiling(
  Math.max(0, ...payload.ranked.map((r) => r.asr_conditional ?? 0)),
);
/* A plotted point above the derived ceiling is not drawn:
 * no position is ever clamped to the axis. What the card
 * does with each such point is decided in the claims below,
 * and a point no surface of the card can carry honestly
 * fails the build rather than drop in silence. */
const offScalePlotted = plotted.filter(
  (r) => (r.asr_conditional ?? 0) > axisMax,
);
const offScaleIds = new Set(offScalePlotted.map((r) => r.run_id));
const plottedDrawn = plotted.filter((r) => !offScaleIds.has(r.run_id));

/* The claims. The headline stands on the ranked plotted
 * population: the priciest ranked plotted run must carry
 * that population's highest attack success, or the card's
 * first sentence would be false and the build fails. */
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
    "gen-og: headline claim broken on this payload: the priciest ranked plotted run does not carry the highest attack success among the ranked plotted runs, so the headline would be false",
  );
  process.exit(1);
}
const subject = priciest;
const subjectSub = `${costIsLowerBound(subject) ? `At least ${fmtUsdBound(subject.total_cost_usd)}` : fmtUsd(subject.total_cost_usd)} a run, ${fmtPct(subject.asr_conditional)}`;

/* The flagged reading. Its subject is the flagged result
 * the card must answer for: an off-scale flagged result
 * first (the plot cannot draw it), else the flagged result
 * with the highest counted rate. Its figure prints only
 * with its decomposition; a flagged result above the axis
 * ceiling whose decomposition does not derive fails the
 * build, because no surface of the card could state its
 * figure honestly. */
const flaggedRows = nonSlice.filter((r) => !r.ranking_eligible);
const flaggedLead = (() => {
  const off = flaggedRows
    .filter((r) => (r.asr_conditional ?? 0) > axisMax)
    .sort((a, b) => (b.asr_conditional ?? 0) - (a.asr_conditional ?? 0));
  for (const r of off) {
    if (flipDecomposition(r) === null) {
      console.error(
        `gen-og: ${pointName(r)} is flagged and sits above the chart's axis ceiling, but its sealed family records do not derive the malformed decomposition its figure must travel with, so the card cannot state it and the build fails`,
      );
      process.exit(1);
    }
  }
  if (off.length > 0) return { row: off[0], offScale: true };
  const rest = [...flaggedRows].sort(
    (a, b) => (b.asr_conditional ?? 0) - (a.asr_conditional ?? 0),
  );
  for (const r of rest) {
    if (flipDecomposition(r) !== null) return { row: r, offScale: false };
  }
  return null;
})();
/* Any other off-scale plotted point has no surface on this
 * card: the plot cannot draw it, the readings carry the
 * toughest, the flagged lead, and the rail's top, and the
 * words under the plot name points the plot drew. Rather
 * than drop it in silence, the build fails. */
for (const r of offScalePlotted) {
  if (flaggedLead && r.run_id === flaggedLead.row.run_id) continue;
  console.error(
    `gen-og: ${pointName(r)} sits above the chart's 0 to ${Math.round(axisMax * 100)} percent scale and no surface of the share card carries it, so the build fails rather than drop it in silence`,
  );
  process.exit(1);
}
/* The rail reading: the ranked no-cost run with the highest
 * rate, named with the reason it stands apart from the cost
 * story the headline tells. */
const railRanked = railRows
  .filter((r) => r.ranking_eligible)
  .sort((a, b) => (b.asr_conditional ?? 0) - (a.asr_conditional ?? 0));
const railTop = railRanked[0] ?? null;
const railTopWho = railTop
  ? railTop.asr_conditional > subject.asr_conditional
    ? `${pointName(railTop)}, no recorded cost. It flipped past every ranked costed run.`
    : `${pointName(railTop)}, no recorded cost, the highest rate on the rail.`
  : null;

/* The ladder: every rail result in rate order, worst first.
 * The landscape card sets it in two columns inside a rows
 * area allotted 170px at 22px a row; past 14 rows the area
 * takes slack from the middle of the card, and the build
 * fails when the rows outgrow the allotment and the slack
 * together. The portrait sets one column at 26px a row
 * inside 286px on the same rule. */
const ladderRows = [...railRows].sort(
  (a, b) =>
    (b.asr_conditional ?? 0) - (a.asr_conditional ?? 0) ||
    (a.run_id < b.run_id ? -1 : 1),
);
const LADDER = {
  land: { allot: 170, pitch: 22, slack: 66, columns: 2 },
  port: { allot: 286, pitch: 26, slack: 160, columns: 1 },
};
function ladderBudget(kind) {
  const spec = LADDER[kind];
  const perColumn = Math.ceil(ladderRows.length / spec.columns);
  const spent = perColumn * spec.pitch;
  const slackUsed = Math.max(0, spent - spec.allot);
  if (slackUsed > spec.slack) {
    console.error(
      `gen-og: the no-cost rail carries ${ladderRows.length} rows and its ladder needs ${spent}px of rows area on the ${kind === "land" ? "landscape" : "portrait"} card, past the ${spec.allot}px allotted and the ${spec.slack}px of slack the middle can give, so the card does not print with its ladder cut`,
    );
    process.exit(1);
  }
  return { rows: ladderRows.length, perColumn, spent, allot: spec.allot, slackUsed };
}
const ladderLand = ladderBudget("land");
const ladderPort = ladderBudget("port");
/* Extra plot narrowing the render pass asks for when a
   card's fixed furniture (its readings stack, its words)
   runs taller than the mock's static copy did: the plot
   funds the overflow the same way it funds ladder slack,
   by rendered width at the plot's own aspect, so the
   card's total height holds without moving a single
   internal coordinate. Set by the fit retry below. */
const plotShrink = { land: 0, port: 0 };
const fitTight = { land: false, port: false };

/* Plot geometry for the two cards. The x scale is a fixed
 * number of pixels per cost decade from the derived domain
 * floor, so the whole decades inside the domain carry the
 * labels; the y scale runs from the derived ceiling at the
 * top gridline to zero at the bottom one, with the middle
 * gridline at half the ceiling. Positions are the mock's,
 * restated as derivations over the payload's own domain. */
const GEOMS = {
  land: {
    viewBox: "0 6 700 272",
    width: 620,
    x0: 56,
    decadePx: 144.15,
    yTop: 16,
    yBot: 252,
    discR: 5,
    flagR: 5.5,
    subjR: 7,
    tickX: 46,
    decadeY: 270,
    canvas: { x: 0, y: 6, w: 700, h: 272 },
  },
  port: {
    viewBox: "0 0 976 568",
    width: 976,
    x0: 64,
    decadePx: 174.4,
    yTop: 44,
    yBot: 520,
    discR: 6,
    flagR: 6.5,
    subjR: 8.4,
    tickX: 54,
    decadeY: 552,
    canvas: { x: 0, y: 0, w: 976, h: 568 },
  },
};
function geomFor(kind) {
  const g = GEOMS[kind];
  const xOf = (c) =>
    g.x0 + (Math.log10(c) - Math.log10(domLo)) * g.decadePx;
  const yOf = (a) => g.yBot - (a / axisMax) * (g.yBot - g.yTop);
  return { ...g, xOf, yOf };
}
function decadesFor(g) {
  const out = [];
  for (
    let e = Math.ceil(Math.log10(domLo));
    e <= Math.floor(Math.log10(domHi));
    e++
  ) {
    const v = 10 ** e;
    out.push({ x: g.xOf(v), label: v < 1 ? `$${v.toFixed(2)}` : `$${v}` });
  }
  return out;
}
function plotSvg(kind, placedLabels, subjectSeat, widthOverride) {
  const g = geomFor(kind);
  const svgWidth = widthOverride ?? g.width;
  const ticks = [axisMax, axisMax / 2, 0];
  const grid = ticks
    .map(
      (t) =>
        `<line x1="${g.x0}" y1="${g.yOf(t)}" x2="${g.canvas.w}" y2="${g.yOf(t)}" stroke="#161d25" stroke-width="1"/>\n<text x="${g.tickX}" y="${g.yOf(t) + 4}" text-anchor="end" class="gtick">${Math.round(t * 100)}</text>`,
    )
    .join("\n");
  const decades = decadesFor(g)
    .map(
      (d) =>
        `<text x="${d.x}" y="${g.decadeY}" text-anchor="middle" class="gtick decade">${d.label}</text>`,
    )
    .join("\n");
  const disc = (r) => {
    const x = g.xOf(r.total_cost_usd);
    const y = g.yOf(r.asr_conditional);
    if (r.run_id === subject.run_id) return "";
    if (!r.ranking_eligible) {
      return `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${g.flagR}" fill="#0c1015" stroke="#e8a33d" stroke-width="2"/>`;
    }
    return `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${g.discR}" fill="#aeb7c2" fill-opacity="0.45"/>`;
  };
  const discs = plottedDrawn.map(disc).join("\n");
  const sx = g.xOf(subject.total_cost_usd);
  const sy = g.yOf(subject.asr_conditional);
  const subj = `<circle cx="${sx.toFixed(1)}" cy="${sy.toFixed(1)}" r="${g.subjR}" fill="#ffffff" data-subject="${subject.run_id}"/>`;
  const labels = placedLabels
    .map(
      (l) =>
        `<text x="${l.x}" y="${l.y}" text-anchor="${l.anchor}" class="plab" data-run-id="${l.runId}">${esc(l.name)}</text>`,
    )
    .join("\n");
  const seat = subjectSeat ?? { x: sx - 15, y: sy - 24, anchor: "end" };
  return `<svg viewBox="${g.viewBox}" width="${svgWidth}" class="chart" role="img" aria-label="Scatter of attack success against recorded cost">
<g>${grid}</g>
<g>${discs}
${subj}</g>
<text x="${seat.x}" y="${seat.y}" text-anchor="${seat.anchor}" class="subj-name" id="subj-name">${esc(pointName(subject))}</text>
<text x="${seat.x}" y="${seat.y + 19}" text-anchor="${seat.anchor}" class="subj-sub" id="subj-sub">${esc(subjectSub)}</text>
<g id="og-labels">${labels}</g>
<g>${decades}</g>
</svg>`;
}

/* The words under the plot. The clauses follow the board's
 * own composition (lib/topData's named-in-words line): the
 * flagged points the plot drew, in rate order, then the
 * points no label could seat. A clause item states the
 * point's rate and its cost in the page's words. */
function namelineHtml(crowded) {
  const clauses = [];
  const flaggedDrawn = plottedDrawn
    .filter((r) => !r.ranking_eligible)
    .sort((a, b) => a.asr_conditional - b.asr_conditional);
  if (flaggedDrawn.length > 0) {
    clauses.push({
      lead: "Amber-ringed in the plot",
      items: flaggedDrawn.map(
        (r) => `<b>${esc(pointName(r))}</b> at ${fmtPct(r.asr_conditional)} and ${esc(costWords(r))}`,
      ),
    });
  }
  if (crowded.length > 0) {
    clauses.push({
      lead:
        crowded.length === 1
          ? "Too crowded at its disc"
          : "Too crowded at their discs",
      items: crowded.map(
        (p) => `<b>${esc(p.name)}</b> at ${fmtPct(p.row.asr_conditional)} and ${esc(costWords(p.row))}`,
      ),
    });
  }
  if (clauses.length === 0) return "";
  const body = clauses
    .map((c) => `${c.lead}, ${c.items.join(", ")}`)
    .join(". ");
  return `<b>Named in words</b> &middot; ${body}.`;
}

/* The ladder markup. The landscape card splits the rows
 * into two columns at the midpoint; the portrait keeps one
 * column. The toughest result, when it stands on the rail,
 * carries the selection ring, the one green the ladder
 * holds. A flagged rail row rings its disc in amber. */
function ladderRowHtml(r) {
  const sel = toughest && r.run_id === toughest.run_id;
  const cls = `lrow${sel ? " sel" : ""}${r.ranking_eligible ? "" : " flag"}`;
  return `<div class="${cls}"><span class="ld"></span><span class="ln">${esc(pointName(r))}</span><span class="lr">${fmtPct(r.asr_conditional)}</span></div>`;
}
function ladderHtml(kind) {
  const head = `<div class="micro lhead">No API cost &middot; the rail, in rate order</div>`;
  if (kind === "port") {
    return `<div class="ladder">${head}${ladderRows.map(ladderRowHtml).join("\n")}</div>`;
  }
  const mid = Math.ceil(ladderRows.length / 2);
  const col1 = ladderRows.slice(0, mid).map(ladderRowHtml).join("\n");
  const col2 = ladderRows.slice(mid).map(ladderRowHtml).join("\n");
  const cols =
    ladderRows.length > 1
      ? `<div class="cols"><div>${col1}</div><div class="col2">${col2}</div></div>`
      : `<div class="cols"><div>${col1}</div></div>`;
  return `<div class="ladder">${head}${cols}</div>`;
}

/* The readings. Three blocks at most: the toughest on the
 * chart, the flagged lead with its decomposition in its
 * words, and the rail's top. A block the payload cannot
 * fill is omitted, never padded. */
function readouts() {
  const blocks = [];
  if (toughest) {
    blocks.push({
      micro: `<span class="tick g"></span>Toughest on the chart`,
      num: fmtPct(toughest.asr_conditional),
      who: `${pointName(toughest)}, flipped least of all`,
    });
  }
  if (flaggedLead) {
    const d = flipDecomposition(flaggedLead.row);
    blocks.push({
      micro: `<span class="tick a"></span>${flaggedLead.offScale ? "Flagged, off the scale" : "Flagged, on the plot"}`,
      num: fmtPct(flaggedLead.row.asr_conditional),
      who: `${pointName(flaggedLead.row)}, counted attack success. ${fmtPct(d.malformedShare)} of counted flips to malformed output, genuine flip rate ${fmtPct(d.genuineRate)}.`,
    });
  }
  if (railTop) {
    blocks.push({
      micro: `On the rail`,
      num: fmtPct(railTop.asr_conditional),
      who: railTopWho,
      faint: true,
    });
  }
  return blocks;
}
const FOOT_L = () =>
  `Peira decision robustness board. Dataset ${versions.dataset}, suite ${versions.suite}, updated ${dateWords}.`;
const FOOT_R = "Amber marks a flagged result &middot; peiratrial.dev";
const MAST_R = `Decision models under attack &middot; ${results} results`;

/* The label candidates beside the subject: the two priciest
 * unflagged plotted results after the subject itself, by
 * cost, ties by run. Their labels are the plot's small gray
 * names; a candidate no seat can hold joins the words under
 * the plot as a crowded point. */
const labelCandidates = plottedDrawn
  .filter((r) => r.ranking_eligible && r.run_id !== subject.run_id)
  .sort(
    (a, b) =>
      b.total_cost_usd - a.total_cost_usd ||
      (a.run_id < b.run_id ? -1 : 1),
  )
  .slice(0, 2);

/* The card documents. The landscape card sets the readings
 * as a numeral stack beside the plot; the portrait stacks
 * them across the top and gives the plot the full width.
 * Type is the system sans and mono of the render host, the
 * stacks the design's mocks carry. */
const CARD_CSS_BASE = `
  :root{
    --ground:#05070a; --panel:#0c1015; --ink:#ffffff; --body:#c3cad3;
    --gray:#8d97a3; --faint:#5d6773; --hair:#1d242e; --hair2:#262f3a;
    --accent:#2fbf71; --amber:#e8a33d; --disc:#aeb7c2;
    --sans:"Liberation Sans","DejaVu Sans",Arial,sans-serif;
    --mono:"Liberation Mono","DejaVu Sans Mono",monospace;
  }
  *{margin:0;padding:0;box-sizing:border-box}
  body{background:var(--ground);color:var(--body);font-family:var(--sans);
    font-variant-numeric:tabular-nums;-webkit-font-smoothing:antialiased}
  .micro{font-family:var(--mono);font-size:11px;font-weight:600;letter-spacing:.055em;color:var(--gray);text-transform:uppercase}
  .micro.faint{color:var(--faint)}
  .mast{display:flex;align-items:baseline;justify-content:space-between;padding-bottom:9px;border-bottom:1px solid var(--hair)}
  .wordmark{font-size:15px;font-weight:700;letter-spacing:.34em;color:var(--ink)}
  h1{font-weight:700;letter-spacing:-.01em;color:var(--ink)}
  .ro .tick{display:inline-block;width:8px;height:8px;margin-right:8px}
  .ro .tick.g{background:var(--accent)} .ro .tick.a{background:var(--amber)}
  .ro .num{font-family:var(--sans);font-weight:700;color:var(--ink);line-height:1.15}
  .ladder{margin-top:auto;border-top:1px solid var(--hair);padding-top:8px}
  .ladder .lhead{padding-bottom:6px;border-bottom:1px solid var(--hair)}
  .lrow{display:flex;align-items:center;gap:10px}
  .lrow .ld{border-radius:50%;background:var(--disc);flex:none}
  .lrow .ln{color:var(--body)}
  .lrow .lr{margin-left:auto;font-family:var(--mono);color:var(--gray)}
  .lrow.sel{box-shadow:inset 3px 0 0 var(--accent)}
  .lrow.sel .ld{background:var(--panel);border:2.5px solid var(--accent)}
  .lrow.sel .ln{color:#fff;font-weight:600}
  .lrow.sel .lr{color:#fff}
  .lrow.flag .ld{background:var(--panel);border:2px solid var(--amber)}
  .nameline{color:var(--gray);line-height:1.55}
  .nameline b{color:#e9edf2;font-weight:600}
  footer{display:flex;justify-content:space-between;color:var(--faint)}
  .gtick{font-family:var(--mono);font-size:10px;fill:#5d6773}
  .gtick.decade{font-size:10.5px;fill:#8d97a3}
  .subj-name{font-family:var(--sans);font-size:15px;font-weight:700;fill:#ffffff}
  .subj-sub{font-family:var(--sans);font-size:12.5px;fill:#c3cad3}
  .plab{font-family:var(--sans);font-size:11px;fill:#8d97a3}
`;
const CARD_CSS_LAND = `
  .card{width:1200px;height:630px;padding:18px 44px 14px;display:flex;flex-direction:column;overflow:hidden}
  h1{font-size:34px;line-height:1.12;margin-top:11px}
  .middle{display:flex;gap:28px;margin-top:8px}
  .scattercol{flex:none}
  .plotmicro{margin-bottom:6px}
  .readouts{flex:1;display:flex;flex-direction:column}
  .ro{padding:9px 0 10px}
  .ro + .ro{border-top:1px solid var(--hair)}
  .ro .num{font-size:30px;margin-top:5px}
  .card.tight .ro{padding:3px 0 4px}
  .card.tight .ro .num{margin-top:2px}
  .ro .who{font-size:13px;color:var(--body);line-height:1.45;margin-top:4px}
  .nameline{font-size:12px;margin-top:6px}
  .ladder .cols{display:grid;grid-template-columns:1fr 1fr;column-gap:0}
  .ladder .col2{border-left:1px solid var(--hair);padding-left:24px;margin-left:24px}
  .lrow{height:22px}
  .lrow .ld{width:11px;height:11px}
  .lrow .ln{font-size:13.5px}
  .lrow .lr{font-size:12.5px}
  .lrow.sel{padding-left:9px;margin-left:-9px}
  footer{margin-top:7px;padding-top:7px;border-top:1px solid var(--hair);font-size:12px}
`;
const CARD_CSS_PORT = `
  .card{width:1080px;height:1350px;padding:34px 52px 34px;display:flex;flex-direction:column;overflow:hidden}
  .mast{padding-bottom:12px}
  .wordmark{font-size:19px}
  .micro{font-size:12px}
  h1{font-size:52px;line-height:1.1;margin-top:16px}
  .nums{display:grid;grid-template-columns:1fr 1fr 1fr;gap:30px;margin-top:20px}
  .ro{border-top:1px solid var(--hair);padding-top:13px}
  .card.tight .ro{padding-top:6px}
  .ro .tick{width:9px;height:9px;margin-right:9px}
  .ro .num{font-size:40px;margin-top:7px}
  .ro .who{font-size:13.5px;color:var(--body);line-height:1.5;margin-top:6px}
  .plotblock{margin-top:12px}
  .plotblock .micro{display:block;margin-bottom:8px}
  .nameline{font-size:13.5px;margin-top:10px}
  .ladder .lhead{padding-bottom:7px}
  .lrow{height:26px;gap:13px;border-bottom:1px solid var(--hair)}
  .lrow:last-child{border-bottom:none}
  .lrow .ld{width:13px;height:13px}
  .lrow .ln{font-size:16px}
  .lrow .lr{font-size:14.5px}
  .lrow.sel{padding-left:11px;margin-left:-11px}
  .lrow.sel .ld{border-width:3px}
  footer{margin-top:8px;padding-top:8px;border-top:1px solid var(--hair);font-size:13px}
  .gtick{font-size:12px}
  .gtick.decade{font-size:12.5px}
  .subj-name{font-size:20px}
  .subj-sub{font-size:15px}
  .plab{font-size:13px}
`;
function cardHtml(kind) {
  /* When the ladder takes slack, the middle of the card
   * funds it. The svg narrows by the width whose height, at
   * the plot's own aspect, equals the slack the rows area
   * took (the plot's internal geometry is untouched, the
   * placement passes work in its units, only its rendered
   * size changes); on the landscape card the narrower plot
   * also widens the readings column beside it, whose lines
   * unwrap as it widens. What narrowing cannot recover the
   * tight class trims from the readings stack's own
   * padding, the roughly 40px of slack the middle carries;
   * the fit pass below can also engage it when a card whose
   * ladder takes no slack still measures tall, as a long
   * rail inside the allotment can. A card that fits as
   * drawn renders exactly as the mock does. */
  const budget = kind === "land" ? ladderLand : ladderPort;
  const tight = budget.slackUsed > 0 || fitTight[kind];
  const g0 = GEOMS[kind];
  const svgW = Math.round(
    g0.width -
      budget.slackUsed * (g0.canvas.w / g0.canvas.h) -
      (plotShrink[kind] ?? 0),
  );
  const ros = readouts();
  const roHtml = (b) =>
    `<div class="ro"><div class="micro${b.faint ? " faint" : ""}">${b.micro}</div><div class="num">${esc(b.num)}</div><div class="who">${esc(b.who)}</div></div>`;
  const mast = `<div class="mast"><div class="wordmark">PEIRA</div><div class="micro faint">${MAST_R}</div></div>`;
  const foot = `<footer><span>${esc(FOOT_L())}</span><span>${FOOT_R}</span></footer>`;
  const nameline = `<p class="nameline" id="nameline"></p>`;
  if (kind === "port") {
    return `<!doctype html>
<html><head><meta charset="utf-8"><style>${CARD_CSS_BASE}${CARD_CSS_PORT}</style></head><body>
<div class="card${tight ? " tight" : ""}">
${mast}
<h1>The priciest model was the easiest to flip</h1>
<div class="nums">
${ros.map(roHtml).join("\n")}
</div>
<div class="plotblock">
<span class="micro">Attack success, percent, against cost per run in dollars, log scale</span>
${plotSvg("port", [], null, svgW)}
</div>
${nameline}
${ladderHtml("port")}
${foot}
</div>
</body></html>`;
  }
  return `<!doctype html>
<html><head><meta charset="utf-8"><style>${CARD_CSS_BASE}${CARD_CSS_LAND}</style></head><body>
<div class="card${tight ? " tight" : ""}">
${mast}
<h1>The priciest model was the easiest to flip</h1>
<div class="middle">
<div class="scattercol">
<div class="micro plotmicro">Attack success, percent, against cost per run in dollars, log scale</div>
${plotSvg("land", [], null, svgW)}
</div>
<div class="readouts">
${ros.map(roHtml).join("\n")}
</div>
</div>
${nameline}
${ladderHtml("land")}
${foot}
</div>
</body></html>`;
}

/* Subject seating, run in the page so the label is measured
 * with the real face: the subject's name and its figure line
 * try their seats in a fixed order (left of the disc, right,
 * then below) and take the first that sits inside the canvas
 * clear of every disc and every other text. A subject no
 * seat can hold fails the build, since the card's subject
 * cannot print unnamed. */
function seatSubject(cfg) {
  const svg = document.querySelector("svg.chart");
  const name = document.getElementById("subj-name");
  const sub = document.getElementById("subj-sub");
  const boxOf = (el) => {
    const b = el.getBBox();
    return { x: b.x, y: b.y, w: b.width, h: b.height };
  };
  const overlap = (a, b) =>
    a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
  const distToDisc = (box, d) => {
    const dx = Math.max(box.x - d.cx, 0, d.cx - (box.x + box.w));
    const dy = Math.max(box.y - d.cy, 0, d.cy - (box.y + box.h));
    return Math.hypot(dx, dy);
  };
  const discs = [...svg.querySelectorAll("circle")].map((c) => ({
    cx: Number(c.getAttribute("cx")),
    cy: Number(c.getAttribute("cy")),
    r: Number(c.getAttribute("r")),
  }));
  const subjDisc = discs.find(
    (d) => Math.abs(d.cx - cfg.sx) < 0.2 && Math.abs(d.cy - cfg.sy) < 0.2,
  );
  const furniture = [...svg.querySelectorAll("text")]
    .filter((el) => el !== name && el !== sub)
    .map(boxOf);
  const inCanvas = (box) =>
    box.x >= cfg.canvas.x + 2 &&
    box.y >= cfg.canvas.y + 2 &&
    box.x + box.w <= cfg.canvas.x + cfg.canvas.w - 2 &&
    box.y + box.h <= cfg.canvas.y + cfg.canvas.h - 2;
  const seats = [
    { anchor: "end", x: cfg.sx - 15, y: cfg.sy - 24 },
    { anchor: "start", x: cfg.sx + 15, y: cfg.sy - 24 },
    /* Beside the disc, the mock's own seat: the name at the
       disc's height with its figure line under it. A subject
       near the top of the scale has no room above, and the
       row below can be crowded; beside is its seat then. */
    { anchor: "end", x: cfg.sx - 15, y: cfg.sy + 4 },
    { anchor: "start", x: cfg.sx + 15, y: cfg.sy + 4 },
    { anchor: "end", x: cfg.sx - 15, y: cfg.sy + 40 },
    { anchor: "start", x: cfg.sx + 15, y: cfg.sy + 40 },
    { anchor: "end", x: cfg.sx - 15, y: cfg.sy + 66 },
    { anchor: "start", x: cfg.sx + 15, y: cfg.sy + 66 },
    { anchor: "middle", x: cfg.sx, y: cfg.sy - 30 },
  ];
  for (const s of seats) {
    name.setAttribute("x", String(s.x));
    name.setAttribute("y", String(s.y));
    name.setAttribute("text-anchor", s.anchor);
    sub.setAttribute("x", String(s.x));
    sub.setAttribute("y", String(s.y + 19));
    sub.setAttribute("text-anchor", s.anchor);
    const nb = boxOf(name);
    const sb = boxOf(sub);
    const clear = (box) =>
      inCanvas(box) &&
      discs.every(
        (d) => d === subjDisc || distToDisc(box, d) >= d.r - 0.01,
      ) &&
      furniture.every((f) => !overlap(box, f));
    if (clear(nb) && clear(sb)) {
      return { ok: true, seat: s, nameBox: nb, subBox: sb };
    }
  }
  return { ok: false };
}

/* Plotted label placement, run in the page so text is
 * measured with the real face. The labeled set derives from
 * the payload (the priciest unflagged points after the
 * subject); every candidate is seated beside its own disc
 * from a fixed candidate list against the furniture (every
 * other text on the plot, the subject's two lines included)
 * and the discs measured as the circles they render as.
 * Placement degrades in tiers and never fails the build: a
 * candidate no tier can seat leaves the plot and is named
 * in words under it. Verification is strict at zero
 * tolerance. The machinery is the board generator's,
 * restated for a plot whose discs carry their own centres
 * as attributes, so every measurement lives in the plot's
 * own units at any render scale. */
function placeLabels(pts, cfg) {
  const NS = "http://www.w3.org/2000/svg";
  const svg = document.querySelector("svg.chart");
  const group = document.getElementById("og-labels");
  const boxOf = (el) => {
    const b = el.getBBox();
    return { x: b.x, y: b.y, w: b.width, h: b.height };
  };
  const furniture = [...svg.querySelectorAll("text")]
    .filter((el) => !group.contains(el))
    .map(boxOf);
  const discs = [...svg.querySelectorAll("circle")].map((c) => ({
    cx: Number(c.getAttribute("cx")),
    cy: Number(c.getAttribute("cy")),
    r: Number(c.getAttribute("r")),
  }));
  const overlap = (a, b) =>
    a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
  const area = (a, b) => {
    const ox = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x);
    const oy = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
    return ox > 0 && oy > 0 ? ox * oy : 0;
  };
  const distToDisc = (box, d) => {
    const dx = Math.max(box.x - d.cx, 0, d.cx - (box.x + box.w));
    const dy = Math.max(box.y - d.cy, 0, d.cy - (box.y + box.h));
    return Math.hypot(dx, dy);
  };
  const inCanvas = (box) =>
    box.x >= cfg.canvas.x + 4 &&
    box.y >= cfg.canvas.y + 4 &&
    box.x + box.w <= cfg.canvas.x + cfg.canvas.w - 4 &&
    box.y + box.h <= cfg.canvas.y + cfg.canvas.h - 4;
  const CANDS = [
    { dx: 14, dy: 4, anchor: "start" },
    { dx: -14, dy: 4, anchor: "end" },
    { dx: 0, dy: -14, anchor: "middle" },
    { dx: 0, dy: 22, anchor: "middle" },
    { dx: 14, dy: -11, anchor: "start" },
    { dx: -14, dy: -11, anchor: "end" },
    { dx: 14, dy: 19, anchor: "start" },
    { dx: -14, dy: 19, anchor: "end" },
    { dx: 16, dy: 30, anchor: "start" },
    { dx: -16, dy: 30, anchor: "end" },
    { dx: 11, dy: 4, anchor: "start" },
    { dx: -11, dy: 4, anchor: "end" },
    { dx: 20, dy: 4, anchor: "start" },
    { dx: -20, dy: 4, anchor: "end" },
    { dx: 0, dy: -22, anchor: "middle" },
    { dx: 0, dy: 32, anchor: "middle" },
  ];
  const CANDS_WIDE = [
    ...CANDS,
    { dx: 26, dy: 4, anchor: "start" },
    { dx: -26, dy: 4, anchor: "end" },
    { dx: 26, dy: -18, anchor: "start" },
    { dx: -26, dy: -18, anchor: "end" },
    { dx: 26, dy: 26, anchor: "start" },
    { dx: -26, dy: 26, anchor: "end" },
    { dx: 0, dy: -32, anchor: "middle" },
    { dx: 0, dy: 42, anchor: "middle" },
    { dx: 12, dy: -24, anchor: "start" },
    { dx: -12, dy: -24, anchor: "end" },
    { dx: 12, dy: 36, anchor: "start" },
    { dx: -12, dy: 36, anchor: "end" },
  ];
  const probe = document.createElementNS(NS, "text");
  probe.setAttribute("class", "plab");
  group.appendChild(probe);
  const boxFor = (p, cand) => {
    probe.setAttribute("x", String(p.x + cand.dx));
    probe.setAttribute("y", String(p.y + cand.dy));
    probe.setAttribute("text-anchor", cand.anchor);
    probe.textContent = p.name;
    return boxOf(probe);
  };
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
  const attempt = (order, CANDS) => {
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
      el.setAttribute("class", "plab");
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
  let best = null;
  const runTier = (CANDS) => {
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
    ];
    for (const order of orders) {
      const { placed, bad } = attempt(order, CANDS);
      if (bad.length === 0) return { clean: true, placed };
      if (best === null || bad.length < best.bad.length) {
        best = { bad, order, CANDS };
      }
    }
    return { clean: false };
  };
  for (const tier of [CANDS, CANDS_WIDE]) {
    const r = runTier(tier);
    if (r.clean) {
      probe.remove();
      return {
        ok: true,
        placed: r.placed.map((rec) => ({
          runId: rec.runId,
          box: boxOf(rec.el),
        })),
        degraded: [],
      };
    }
  }
  const { placed } = attempt(best.order, best.CANDS);
  const badIds = new Set(
    best.bad.map((s) => s.split(" ")[0]).filter((s) => s !== "count"),
  );
  const degraded = [];
  for (const rec of placed) {
    if (badIds.has(rec.runId)) {
      rec.el.remove();
      degraded.push(rec.runId);
    }
  }
  probe.remove();
  return {
    ok: true,
    placed: placed
      .filter((rec) => !badIds.has(rec.runId))
      .map((rec) => ({ runId: rec.runId, box: boxOf(rec.el) })),
    degraded,
  };
}

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
mkdirSync(path.join(root, "public"), { recursive: true });
mkdirSync(path.join(root, ".og"), { recursive: true });
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

const probes = {};
for (const kind of ["land", "port"]) {
  const g = geomFor(kind);
  const size =
    kind === "land" ? { width: 1200, height: 630 } : { width: 1080, height: 1350 };
  const htmlPath = path.join(root, ".og", `og-${kind}.html`);
  const candidatePts = labelCandidates.map((r) => ({
    runId: r.run_id,
    name: pointName(r),
    x: g.xOf(r.total_cost_usd),
    y: g.yOf(r.asr_conditional),
  }));
  let placement = null;
  let degradedRows = [];
  /* The card must fit its own height: measured where it is
   * drawn, the content may not run past the card, and the
   * footer must sit inside it. When the fixed furniture
   * runs tall on a live payload, the plot funds the
   * overflow by narrowing (its internal geometry is in its
   * own units and does not move), and the card renders
   * again; a card that still overflows after the retries
   * does not print. */
  for (let attemptN = 0; attemptN < 4; attemptN++) {
    writeFileSync(htmlPath, cardHtml(kind));
    await page.setViewport(size);
    await page.goto(`file://${htmlPath}`, { waitUntil: "networkidle0" });
    await page.evaluate(() => document.fonts.ready);
    const seat = await page.evaluate(seatSubject, {
      canvas: g.canvas,
      sx: g.xOf(subject.total_cost_usd),
      sy: g.yOf(subject.asr_conditional),
    });
    if (!seat.ok) {
      await browser.close();
      console.error(
        `gen-og: the subject's name and figure line cannot sit clear of the plot on the ${kind === "land" ? "landscape" : "portrait"} card, so the card does not print with its subject unnamed or struck`,
      );
      process.exit(1);
    }
    placement = await page.evaluate(placeLabels, candidatePts, {
      canvas: g.canvas,
    });
    degradedRows = labelCandidates.filter((r) =>
      placement.degraded.includes(r.run_id),
    );
    const nameline = namelineHtml(
      degradedRows.map((r) => ({ name: pointName(r), row: r })),
    );
    await page.evaluate((html) => {
      const el = document.getElementById("nameline");
      if (html === "") {
        el.remove();
        return;
      }
      el.innerHTML = html;
    }, nameline);
    const fit = await page.evaluate(() => {
      const card = document.querySelector(".card");
      const foot = document.querySelector("footer");
      const ladder = document.querySelector(".ladder");
      const cr = card.getBoundingClientRect();
      const fr = foot.getBoundingClientRect();
      const lr = ladder.getBoundingClientRect();
      return {
        cardH: cr.height,
        footBottom: fr.bottom - cr.top,
        ladderBottom: lr.bottom - cr.top,
        scrollOverflow: card.scrollHeight - card.clientHeight,
      };
    });
    if (process.env.GENOG_DEBUG_FIT) {
      console.error(
        `fit attempt ${attemptN} kind ${kind}: shrink ${plotShrink[kind]}, footBottom ${Math.round(fit.footBottom)}, ladderBottom ${Math.round(fit.ladderBottom)}, scrollOverflow ${Math.round(fit.scrollOverflow)}, cardH ${Math.round(fit.cardH)}`,
      );
    }
    /* The fit rule reads the footer and the ladder, the
     * furniture a tall card would cut. The card's
     * scrollHeight is not part of the rule: the plot's text
     * sits in the svg's own units, where the seating passes
     * already verify every label against the canvas at zero
     * tolerance, and the scroll measure conflates that
     * certified overflow with layout overflow (it read 32px
     * on a portrait whose footer stood 2px inside the card). */
    if (fit.footBottom <= fit.cardH + 0.5 && fit.ladderBottom <= fit.cardH + 0.5) {
      break;
    }
    if (attemptN === 3) {
      await browser.close();
      console.error(
        `gen-og: the ${kind === "land" ? "landscape" : "portrait"} card's content overflows its height (ladder bottom ${Math.round(fit.ladderBottom)} of ${Math.round(fit.cardH)}), so the card does not print with its ladder or footer cut`,
      );
      process.exit(1);
    }
    if (attemptN >= 1) {
      fitTight[kind] = true;
    }
    plotShrink[kind] += Math.ceil(
      (Math.max(fit.footBottom, fit.ladderBottom) - fit.cardH + 10) *
        (g.canvas.w / g.canvas.h),
    );
  }
  const budget = kind === "land" ? ladderLand : ladderPort;
  console.log(
    `gen-og: ladder budget (${kind === "land" ? "landscape" : "portrait"}): spent ${budget.spent}px of the ${budget.allot}px rows area on ${budget.rows} rail rows in ${LADDER[kind].columns} column${LADDER[kind].columns === 1 ? "" : "s"}, slack used ${budget.slackUsed}px`,
  );
  if (placement.degraded.length > 0) {
    console.log(
      `gen-og: ${placement.degraded.length} plotted label${placement.degraded.length === 1 ? "" : "s"} could not seat beside the disc on the ${kind === "land" ? "landscape" : "portrait"} card and ${placement.degraded.length === 1 ? "is" : "are"} named in words under the plot instead: ${degradedRows.map((r) => pointName(r)).join(", ")}`,
    );
  }
  /* Test instrumentation, off unless PEIRA_OG_PROBE is set:
   * the rendered card's claims, discs, labels, readings,
   * ladder and words, written as JSON beside the pages, so
   * the generator tests can assert on the rendered image's
   * contents instead of trusting the log. */
  if (process.env.PEIRA_OG_PROBE) {
    probes[kind] = await page.evaluate(() => {
      const svg = document.querySelector("svg.chart");
      const boxOf = (e) => {
        const b = e.getBBox();
        return { x: b.x, y: b.y, w: b.width, h: b.height };
      };
      const txt = (sel) => document.querySelector(sel)?.textContent ?? null;
      return {
        headline: txt("h1"),
        mastRight: txt(".mast .micro"),
        readouts: [...document.querySelectorAll(".ro")].map((el) => ({
          micro: el.querySelector(".micro")?.textContent ?? "",
          num: el.querySelector(".num")?.textContent ?? "",
          who: el.querySelector(".who")?.textContent ?? "",
        })),
        subject: {
          name: txt("#subj-name"),
          sub: txt("#subj-sub"),
          nameBox: boxOf(document.getElementById("subj-name")),
          subBox: boxOf(document.getElementById("subj-sub")),
        },
        discs: [...svg.querySelectorAll("circle")].map((c) => ({
          cx: Number(c.getAttribute("cx")),
          cy: Number(c.getAttribute("cy")),
          r: Number(c.getAttribute("r")),
          subject: c.hasAttribute("data-subject"),
        })),
        labels: [...svg.querySelectorAll("#og-labels text")].map((el) => ({
          name: el.textContent,
          runId: el.getAttribute("data-run-id"),
          box: boxOf(el),
        })),
        gridLines: svg.querySelectorAll("line").length,
        decades: [...svg.querySelectorAll(".gtick.decade")].map(
          (el) => el.textContent,
        ),
        nameline: document.getElementById("nameline")?.textContent ?? null,
        ladder: [...document.querySelectorAll(".lrow")].map((el) => ({
          name: el.querySelector(".ln")?.textContent ?? "",
          rate: el.querySelector(".lr")?.textContent ?? "",
          sel: el.classList.contains("sel"),
          flag: el.classList.contains("flag"),
        })),
        footer: [...document.querySelectorAll("footer span")].map(
          (el) => el.textContent,
        ),
      };
    });
    probes[kind].ladderBudget = budget;
  }
  await page.screenshot({
    path: path.join(
      root,
      "public",
      kind === "land" ? "og.png" : "og-portrait.png",
    ),
  });
  console.log(
    `gen-og: wrote public/${kind === "land" ? "og.png" : "og-portrait.png"} (${size.width}x${size.height}) from ${results} results, board date ${dateWords}; labelled ${placement.placed.length} of ${candidatePts.length} label candidates beside their discs and all ${ladderRows.length} rail rows in the ladder`,
  );
}
await browser.close();
if (process.env.PEIRA_OG_PROBE) {
  writeFileSync(
    path.join(root, ".og", "probe.json"),
    JSON.stringify(probes, null, 2),
  );
}
copyFileSync(
  path.join(root, "data", "payload.json"),
  path.join(root, "public", "payload.json"),
);
console.log("gen-og: copied data/payload.json to public/payload.json");
