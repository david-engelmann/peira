/**
 * Repo social preview generator. Renders .github/social-preview.png,
 * 1280 by 640 (the size GitHub asks for), from the board payload.
 * The image is the two-extremes design the owner picked on
 * 2026-10-26 after rejecting a first design that drew the full
 * cost scatter: at the sizes a social card is actually seen
 * (about 600px wide in a feed, about 300px in lists and chats),
 * that card's 33 in-place names collapsed into illegible
 * texture. This design draws exactly two points, the two ends
 * of the board's cost story, large on the board's own scales:
 * the cheapest and the priciest costed runs of the ranked
 * full suite population, picked by the derivation further
 * down, never by name. Every number on the card is a drawn
 * point, so the card claims nothing it does not show; the
 * headline is a fact of the drawn points, since the priciest
 * run on the card also carries the highest attack success in
 * that population, which the validation below asserts on
 * every build.
 * Vendor identity resolves through lib/vendor-data.json and
 * the mark paths are read out of lib/logoPaths.ts, the same
 * sources the board itself uses, and the figures come from
 * data/payload.json. No suite case total appears on the card.
 * Run from site/board with:
 *   node scripts/gen-social-preview.mjs
 * The upload itself is manual: repo Settings, Social preview.
 */
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { globSync } from "node:fs";
import { homedir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const payload = JSON.parse(
  readFileSync(path.join(root, "data", "payload.json"), "utf8"),
);
const fontB64 = readFileSync(
  path.join(root, "public", "fonts", "archivo.woff2"),
).toString("base64");

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
const fmtMoney = (v) => `$${quantHU(expandDec(v), 2)}`;

/* The board's lower-bound rule (lib/charts costIsLowerBound),
 * replicated on the payload rows: a recorded cost whose priced
 * calls fall short of its timed calls is a floor, and the model
 * cards print it with the qualifier. The social card follows
 * the same rule, as gen-og's top corner does. */
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
 * it. Neither drawn point needs the suffix on this payload,
 * but the rule is the board's and stays. */
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
    `gen-social-preview: payload rows disagree on dataset or suite (${[...versionPairs].join(", ")}): no single version stamp holds for the whole board`,
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
const credit = `Peira decision robustness board. Dataset ${versions.dataset}, suite ${versions.suite}, updated ${dateWords}. peiratrial.dev`;
const results = payload.ranked.length + payload.unranked.length;

/* The two drawn points, derived from the validator
 * population: the ranked full suite rows, the population
 * the board's claims stand on. They are the board's two
 * corner readings made literal: the cheapest costed run of
 * that population and its priciest, picked by cost, never
 * by name (F6 of the 2026-10-29 hardcode audit; the picks
 * were display-name literals, and the old validation
 * population let a flagged run take the max attack success
 * slot and fail the build). The validation further down
 * keeps the headline honest on future payloads. */
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
const validator = payload.ranked.filter((r) => r.n_cases === fullCases);
const costed = validator.filter(
  (r) => r.total_cost_usd !== null && r.total_cost_usd > 0 && r.asr_conditional !== null,
);
const byCostAsc = [...costed].sort(
  (a, b) => a.total_cost_usd - b.total_cost_usd,
);
const cheap = byCostAsc[0];
const priciest = byCostAsc.at(-1);
if (!cheap || !priciest || cheap.run_id === priciest.run_id) {
  console.error(
    "gen-social-preview: the ranked full suite population does not hold two distinct costed runs: the card draws the two ends of its cost story and cannot be built without both",
  );
  process.exit(1);
}
const esc = (t) =>
  t.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
function bigDisc(r, x, y, R) {
  const fam = familyOf(r);
  const s = ((2 * R * 0.55) / 24).toFixed(3);
  const glyph = fam.logo
    ? `<path d="${LOGO_PATHS[fam.logo]}" transform="translate(${-12 * s} ${-12 * s}) scale(${s})" fill="${fam.glyph}"/>`
    : `<text y="1" class="mono" fill="${fam.glyph}">${esc(shortName(r).match(/[a-z0-9]/i)?.[0]?.toUpperCase() ?? "·")}</text>`;
  return `<g transform="translate(${x.toFixed(1)} ${y.toFixed(1)})">
    <circle r="${R}" fill="${fam.color}" stroke="rgba(255,255,255,0.28)" stroke-width="1.5"/>
    ${glyph}
  </g>`;
}

/* The plot: one panel on the board's own scales, the attack
 * success axis on the board's shared scale (the derived
 * ceiling below) and the cost axis on the
 * log scale, with the keys inside the figure. The middle of
 * the plot is visibly empty; that emptiness is the selection
 * showing, and the sub-line states the selection in words. */
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
/* The cost domain, derived from the costed population under
 * the same rule family as gen-og's domain: the half-decade
 * steps that bracket the plotted costs, so a legitimate cost
 * outside the old literal domain rescales the card instead
 * of aborting it. BX.lo and BX.hi are log10 bounds. */
const costedCosts = costed.map((r) => r.total_cost_usd);
const domLogLo = Math.floor(Math.log10(Math.min(...costedCosts)) * 2) / 2;
let domLogHi = Math.ceil(Math.log10(Math.max(...costedCosts)) * 2) / 2;
if (domLogHi <= domLogLo) domLogHi = domLogLo + 1;
const BX = { x0: 150, x1: 1200, yTop: 236, yBot: 500, lo: domLogLo, hi: domLogHi };
const bxOf = (c) =>
  BX.x0 +
  ((Math.log10(c) - BX.lo) / (BX.hi - BX.lo)) * (BX.x1 - BX.x0);
const byOf = (a) => BX.yBot - (a / axisMax) * (BX.yBot - BX.yTop);
/* The headline is a claim about the payload, and this
 * generator is what keeps it true: both drawn points must
 * sit inside the plot domains, the priciest drawn point
 * must still be the highest attack success among the
 * validator population's costed rows, and the cheap drawn
 * point must have flipped less than the priciest, which is
 * all the two micro labels claim of the pair. A payload
 * refresh that breaks any of this fails the build instead
 * of producing a misleading card. */
const inPlot = (r) =>
  r.total_cost_usd >= 10 ** BX.lo &&
  r.total_cost_usd <= 10 ** BX.hi &&
  r.asr_conditional >= 0 &&
  r.asr_conditional <= axisMax;
const maxAsr = Math.max(...costed.map((r) => r.asr_conditional));
if (
  ![cheap, priciest].every((r) => inPlot(r)) ||
  priciest.asr_conditional !== maxAsr ||
  cheap.asr_conditional >= priciest.asr_conditional
) {
  console.error(
    "gen-social-preview: a drawn point sits outside the plot domains, or the headline (the priciest run carries the highest attack success, and the cheapest flipped less) no longer holds on this payload",
  );
  process.exit(1);
}
const gridB = axisTicks
  .map(
    (t) => `<line x1="${BX.x0}" y1="${byOf(t)}" x2="${BX.x1}" y2="${byOf(t)}" stroke="#232c35" stroke-opacity="0.55"/>
    <text x="${BX.x0 - 14}" y="${byOf(t) + 5}" class="tick" text-anchor="end">${Math.round(t * 100)}</text>`,
  )
  .join("\n");
const decadeSteps = [];
for (let dgt = Math.ceil(BX.lo); dgt <= Math.floor(BX.hi); dgt++) decadeSteps.push(dgt);
const decadesB = decadeSteps
  .map((dgt) => {
    const v = 10 ** dgt;
    return `<text x="${bxOf(v)}" y="${BX.yBot + 30}" class="tick" text-anchor="middle">${v < 1 ? `$${v.toFixed(2)}` : `$${v}`}</text>`;
  })
  .join("\n");
const jx = bxOf(cheap.total_cost_usd);
const jy = byOf(cheap.asr_conditional);
const fx = bxOf(priciest.total_cost_usd);
const fy = byOf(priciest.asr_conditional);
const R = 36;
/* The micro labels, derived. Each word a label may print is
 * chosen by a stated rule over derived quantities, never
 * written as a literal. The cost words read the point's
 * position in the derived log cost domain above: NEAR-FREE
 * holds when the cheap point's cost sits in the lowest
 * quarter of that domain, EXPENSIVE when the priciest point's
 * cost sits in the highest quarter. The toughness words read
 * the point's attack success against the costed population:
 * TOUGH holds when the cheap point's rate is at or below the
 * population's first quartile rate (the sorted rate at index
 * floor((n - 1) / 4)), FRAGILE when the priciest point's rate
 * is the population maximum. A word whose rule fails does not
 * print. When no word holds for a point the micro label is
 * empty and the block stands on its factual form alone, the
 * derived name and figures. The guard under the composition
 * recomputes the expected label from the same predicates and
 * fails the build on any disagreement, so a printed
 * characterization cannot contradict its rule inputs. */
const costPos = (r) =>
  (Math.log10(r.total_cost_usd) - BX.lo) / (BX.hi - BX.lo);
const sortedCostedAsr = [...costed]
  .map((r) => r.asr_conditional)
  .sort((a, b) => a - b);
const q1Asr = sortedCostedAsr[Math.floor((sortedCostedAsr.length - 1) / 4)];
const microParts = (r, side) =>
  side === "cheap"
    ? [
        ["NEAR-FREE", costPos(r) <= 0.25],
        ["TOUGH", r.asr_conditional <= q1Asr],
      ]
    : [
        ["EXPENSIVE", costPos(r) >= 0.75],
        ["FRAGILE", r.asr_conditional === maxAsr],
      ];
const microLabel = (r, side) =>
  microParts(r, side)
    .filter(([, holds]) => holds)
    .map(([word]) => word)
    .join(" AND ");
const cheapMicro = microLabel(cheap, "cheap");
const priciestMicro = microLabel(priciest, "priciest");
for (const [label, r, side] of [
  [cheapMicro, cheap, "cheap"],
  [priciestMicro, priciest, "priciest"],
]) {
  const expected = microParts(r, side)
    .filter(([, holds]) => holds)
    .map(([word]) => word)
    .join(" AND ");
  const contradicted = microParts(r, side).some(
    ([word, holds]) => label.includes(word) && !holds,
  );
  if (label !== expected || contradicted) {
    console.error(
      `gen-social-preview: the ${side} micro label "${label}" contradicts its derivation rule on this payload (cost position ${costPos(r).toFixed(3)}, attack success ${r.asr_conditional}, first quartile ${q1Asr}, population maximum ${maxAsr})`,
    );
    process.exit(1);
  }
}
const costLine = (r) =>
  `Cost ${costIsLowerBound(r) ? "at least " : ""}${fmtMoney(r.total_cost_usd)} per run`;
const pointWords = (r) =>
  `${pointName(r)} (${fmtPct(r.asr_conditional)}, ${costIsLowerBound(r) ? "at least " : ""}${fmtMoney(r.total_cost_usd)} per run)`;
const bSvg = `<svg width="1280" height="640" viewBox="0 0 1280 640" class="chart">
  <rect x="48" y="196" width="1184" height="376" fill="#0c1015" stroke="#232c35"/>
  ${gridB}
  <line x1="${BX.x0}" y1="${BX.yBot}" x2="${BX.x1}" y2="${BX.yBot}" stroke="#232c35"/>
  ${decadesB}
  <text x="${BX.x0 + 6}" y="226" class="tick">Attack success, percent</text>
  <text x="${BX.x0}" y="560" class="tick">Recorded cost per run, US dollars, log scale</text>
  <g id="social-cheap" class="label-block">
  ${cheapMicro ? `<text x="${jx + R + 20}" y="${jy - 38}" class="micro2">${cheapMicro}</text>` : ""}
  <text x="${jx + R + 20}" y="${jy}" class="pname">${esc(pointName(cheap))}</text>
  <text x="${jx + R + 20}" y="${jy + 36}" class="pfig">Attack success ${fmtPct(cheap.asr_conditional)}</text>
  <text x="${jx + R + 20}" y="${jy + 68}" class="pfig">${costLine(cheap)}</text>
  </g>
  <g id="social-priciest" class="label-block">
  ${priciestMicro ? `<text x="${fx - R - 20}" y="${fy - 30}" class="micro2" text-anchor="end">${priciestMicro}</text>` : ""}
  <text x="${fx - R - 20}" y="${fy + 10}" class="pname" text-anchor="end">${esc(pointName(priciest))}</text>
  <text x="${fx - R - 20}" y="${fy + 46}" class="pfig" text-anchor="end">Attack success ${fmtPct(priciest.asr_conditional)}</text>
  <text x="${fx - R - 20}" y="${fy + 78}" class="pfig" text-anchor="end">${costLine(priciest)}</text>
  </g>
  ${bigDisc(cheap, jx, jy, R)}
  ${bigDisc(priciest, fx, fy, R)}
</svg>`;

/* Tripwire: the card draws exactly two points and nothing
 * else in the plot. The lines are the grid lines, one per
 * axis tick, and the cost axis; a third disc or any extra
 * line means
 * the selection has silently grown, and the build fails
 * rather than let the card drift back toward the full
 * scatter the owner rejected. */
const bCircleCount = (bSvg.match(/<circle/g) ?? []).length;
const bLineCount = (bSvg.match(/<line/g) ?? []).length;
if (bCircleCount !== 2 || bLineCount !== axisTicks.length + 1) {
  console.error(
    `gen-social-preview: unexpected plot contents (circles ${bCircleCount}, lines ${bLineCount}): the card draws exactly the two cost extremes`,
  );
  process.exit(1);
}

const html = `<!doctype html>
<html><head><meta charset="utf-8"><style>
@font-face { font-family: "Archivo"; src: url("data:font/woff2;base64,${fontB64}") format("woff2"); }
* { margin: 0; box-sizing: border-box; }
body { width: 1280px; height: 640px; background: #05070a; color: #eef2f6;
  font-family: "Archivo", system-ui, sans-serif; overflow: hidden; }
.word { font-size: 26px; font-weight: 700; letter-spacing: 0.05em; color: #2fbf71; }
.eyebrow { font-size: 15px; font-weight: 600; letter-spacing: 0.14em; color: #71808f; margin-left: 16px; }
.foot { position: absolute; left: 48px; bottom: 22px; font-size: 17px; color: #71808f; }
.mono { font-weight: 700; text-anchor: middle; dominant-baseline: central; }
.head { position: absolute; left: 48px; top: 36px; right: 48px; }
h1 { font-size: 52px; font-weight: 700; letter-spacing: -0.02em; margin-top: 10px; }
.sub { font-size: 20px; color: #aebcc7; margin-top: 8px; }
.chart { position: absolute; left: 0; top: 0; }
.tick { fill: #71808f; font-size: 15px; }
.micro2 { fill: #71808f; font-size: 16px; font-weight: 600; letter-spacing: 0.14em; }
.pname { fill: #eef2f6; font-size: 34px; font-weight: 700; }
.pfig { fill: #aebcc7; font-size: 24px; font-weight: 550; }
.sm .micro2 { font-size: 13px; }
.sm .pname { font-size: 26px; }
.sm .pfig { font-size: 19px; }
.fallback { position: absolute; left: 150px; top: 578px; width: 1082px; font-size: 16px; line-height: 20px; color: #aebcc7; }
</style></head><body>
${bSvg}
<div class="fallback" id="social-fallback" hidden></div>
<div class="head">
  <div><span class="word">PEIRA</span><span class="eyebrow">DECISION MODELS UNDER ATTACK</span></div>
  <h1>The priciest model was the easiest to flip</h1>
  <p class="sub">The two ends of the cost story, each a full run of the suite.</p>
</div>
<p class="foot">${credit}</p>
</body></html>`;

mkdirSync(path.join(root, ".og"), { recursive: true });
const outPng = path.join(root, "..", "..", ".github", "social-preview.png");
mkdirSync(path.dirname(outPng), { recursive: true });
const ogHtml = path.join(root, ".og", "social.html");
writeFileSync(ogHtml, html);

const labelBlocks = [
  {
    id: "social-cheap",
    name: pointName(cheap),
    words: pointWords(cheap),
    discX: jx,
    discY: jy,
    defDx: R + 20,
    defAnchor: "start",
    radius: R,
  },
  {
    id: "social-priciest",
    name: pointName(priciest),
    words: pointWords(priciest),
    discX: fx,
    discY: fy,
    defDx: -(R + 20),
    defAnchor: "end",
    radius: R,
  },
];

/* Label placement for the two drawn blocks, run in the page
 * so text is measured with the real Archivo face, in the
 * same spirit as gen-og's placer. Each block tries seats
 * around its own disc (its standing side first, then the
 * other side, then above and below the disc), then wider
 * seats on the same bearings, then the wider seats at a
 * smaller size. Verification is zero tolerance against the
 * discs, every other text on the card, the headline and
 * footer blocks, the other label block and the canvas edge.
 * A block no tier can seat leaves the plot and its point is
 * named in words, with its figures, in the strip under the
 * plot. A collision no tier and no words strip can resolve
 * returns not ok and the generator fails loudly rather than
 * print a struck-through card. */
function placeSocialLabels(blocks) {
  const svg = document.querySelector("svg.chart");
  const boxOf = (el) => {
    const b = el.getBBox();
    return { x: b.x, y: b.y, w: b.width, h: b.height };
  };
  const groups = new Map(
    blocks.map((b) => [b.id, document.getElementById(b.id)]),
  );
  const inBlock = (el) => blocks.some((b) => groups.get(b.id).contains(el));
  const furniture = [...svg.querySelectorAll("text")]
    .filter((el) => !inBlock(el))
    .map(boxOf);
  for (const sel of [".head", ".foot"]) {
    const r = document.querySelector(sel).getBoundingClientRect();
    furniture.push({ x: r.x, y: r.y, w: r.width, h: r.height });
  }
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
  const distToDisc = (box, d) => {
    const dx = Math.max(box.x - d.cx, 0, d.cx - (box.x + box.w));
    const dy = Math.max(box.y - d.cy, 0, d.cy - (box.y + box.h));
    return Math.hypot(dx, dy);
  };
  const inCanvas = (box) =>
    box.x >= 4 && box.y >= 4 && box.x + box.w <= 1276 && box.y + box.h <= 636;
  const orig = new Map(
    blocks.map((b) => [
      b.id,
      [...groups.get(b.id).querySelectorAll("text")].map((el) => ({
        el,
        dy: Number(el.getAttribute("y")) - b.discY,
      })),
    ]),
  );
  const setBlock = (b, cand) => {
    const items = orig.get(b.id);
    const apply = (shift) => {
      for (const { el, dy } of items) {
        el.setAttribute("x", String(b.discX + cand.dx));
        el.setAttribute("y", String(b.discY + shift + dy));
        el.setAttribute("text-anchor", cand.anchor);
      }
    };
    apply(cand.dy ?? 0);
    if (cand.kind === "above" || cand.kind === "below") {
      const box = boxOf(groups.get(b.id));
      const target =
        cand.kind === "above"
          ? b.discY - b.radius - 14 - (box.y + box.h)
          : b.discY + b.radius + 14 - box.y;
      apply(target);
    }
    return boxOf(groups.get(b.id));
  };
  const side = (dx, dy, anchor) => ({ kind: "side", dx, dy, anchor });
  const candsFor = (b, wide) => {
    const opp = b.defAnchor === "start" ? "end" : "start";
    const list = [
      side(b.defDx, 0, b.defAnchor),
      side(-b.defDx, 0, opp),
      side(b.defDx, -52, b.defAnchor),
      side(-b.defDx, -52, opp),
      side(b.defDx, 52, b.defAnchor),
      side(-b.defDx, 52, opp),
      { kind: "above", dx: 0, anchor: "middle" },
      { kind: "below", dx: 0, anchor: "middle" },
    ];
    if (wide) {
      const far = b.radius + 58;
      const farther = b.radius + 96;
      list.push(
        side(far, 0, "start"),
        side(-far, 0, "end"),
        side(far, -52, "start"),
        side(-far, -52, "end"),
        side(far, 52, "start"),
        side(-far, 52, "end"),
        side(farther, 0, "start"),
        side(-farther, 0, "end"),
      );
    }
    return list;
  };
  const blockBad = (b, box, placedBoxes) =>
    !inCanvas(box) ||
    discs.some((d) => distToDisc(box, d) < d.r - 0.01) ||
    furniture.some((f) => overlap(box, f)) ||
    placedBoxes.some((o) => o.id !== b.id && overlap(box, o.box));
  const attempt = (order, wide) => {
    const placedBoxes = [];
    const recs = [];
    const costOf = (box, selfId, idx) => {
      let cost = idx * 2;
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
      for (const o of placedBoxes) {
        if (o.id !== selfId) cost += area(box, o.box) * 40;
      }
      return cost;
    };
    for (const b of order) {
      const cands = candsFor(b, wide);
      let best = cands[0];
      let bestCost = Infinity;
      let bestBox = null;
      cands.forEach((c, i) => {
        const box = setBlock(b, c);
        const cost = costOf(box, b.id, i);
        if (cost < bestCost) {
          bestCost = cost;
          best = c;
          bestBox = box;
        }
      });
      setBlock(b, best);
      const rec = { b, cand: best, box: bestBox };
      recs.push(rec);
      placedBoxes.push({ id: b.id, box: bestBox });
    }
    for (let pass = 0; pass < 60; pass++) {
      let moved = false;
      for (const rec of recs) {
        const cands = candsFor(rec.b, wide);
        let best = rec.cand;
        let bestCost = costOf(rec.box, rec.b.id, Math.max(0, cands.indexOf(rec.cand)));
        let bestBox = rec.box;
        cands.forEach((c, i) => {
          if (c === rec.cand) return;
          const box = setBlock(rec.b, c);
          const cost = costOf(box, rec.b.id, i);
          if (cost < bestCost - 0.5) {
            bestCost = cost;
            best = c;
            bestBox = box;
          }
        });
        if (best !== rec.cand) moved = true;
        setBlock(rec.b, best);
        rec.cand = best;
        rec.box = bestBox;
        const slot = placedBoxes.find((o) => o.id === rec.b.id);
        if (slot) slot.box = bestBox;
      }
      if (!moved) break;
    }
    const bad = recs
      .filter((rec) => blockBad(rec.b, boxOf(groups.get(rec.b.id)), placedBoxes))
      .map((rec) => rec.b.id);
    return { recs, bad };
  };
  let best = null;
  const runTier = (wide, sm) => {
    for (const b of blocks) {
      groups.get(b.id).classList.toggle("sm", sm);
    }
    for (const order of [blocks, [...blocks].reverse()]) {
      const r = attempt(order, wide);
      if (r.bad.length === 0) return { clean: true };
      if (best === null || r.bad.length < best.bad.length) {
        best = { bad: r.bad, order, wide, sm };
      }
    }
    return { clean: false };
  };
  for (const [wide, sm] of [
    [false, false],
    [true, false],
    [true, true],
  ]) {
    if (runTier(wide, sm).clean) {
      return { ok: true, placed: blocks.length, degraded: [] };
    }
  }
  /* The words tier. Rebuild the least violating attempt,
   * lift the blocks it could not seat off the plot, and name
   * those points in the strip under the plot with the
   * figures the payload carries for them. The strip steps
   * its size down until it clears the footer. If a seated
   * block still violates after the lift, or the strip itself
   * cannot clear the footer, the collision is unresolvable
   * and the caller fails the build. */
  for (const b of blocks) groups.get(b.id).classList.toggle("sm", best.sm);
  const { recs } = attempt(best.order, best.wide);
  const badIds = new Set(best.bad);
  const degraded = [];
  for (const rec of recs) {
    if (badIds.has(rec.b.id)) {
      groups.get(rec.b.id).remove();
      degraded.push(rec.b);
    }
  }
  const remaining = recs.filter((rec) => !badIds.has(rec.b.id));
  const remainingBoxes = remaining.map((rec) => ({
    id: rec.b.id,
    box: boxOf(groups.get(rec.b.id)),
  }));
  if (
    remaining.some((rec) =>
      blockBad(rec.b, boxOf(groups.get(rec.b.id)), remainingBoxes),
    )
  ) {
    return { ok: false, failures: remaining.map((r) => r.b.name) };
  }
  const strip = document.getElementById("social-fallback");
  strip.hidden = false;
  strip.textContent =
    "Too crowded at their discs, so named here. " +
    degraded.map((b) => b.words).join(", ");
  const footRect = document.querySelector(".foot").getBoundingClientRect();
  let size = 16;
  while (size > 10) {
    const r = strip.getBoundingClientRect();
    if (r.bottom <= footRect.top - 2) break;
    size -= 1;
    strip.style.fontSize = `${size}px`;
    strip.style.lineHeight = `${Math.round(size * 1.25)}px`;
  }
  const stripRect = strip.getBoundingClientRect();
  if (stripRect.bottom > footRect.top - 2) {
    return { ok: false, failures: degraded.map((b) => b.name) };
  }
  return {
    ok: true,
    placed: blocks.length - degraded.length,
    degraded: degraded.map((b) => b.name),
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
    "gen-social-preview: no Chromium found in the Playwright cache and no PUPPETEER_EXECUTABLE_PATH or CHROME_PATH set",
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
await page.setViewport({ width: 1280, height: 640 });
await page.goto(`file://${ogHtml}`, { waitUntil: "networkidle0" });
await page.evaluate(() => document.fonts.ready);
const placement = await page.evaluate(placeSocialLabels, labelBlocks);
if (!placement.ok) {
  await browser.close();
  console.error(
    `gen-social-preview: label placement failed for ${placement.failures.join(", ")}: no tier and no words strip could seat the drawn labels without a collision, so no card is printed`,
  );
  process.exit(1);
}
if (placement.degraded.length > 0) {
  console.log(
    `gen-social-preview: ${placement.degraded.length} drawn label block${placement.degraded.length === 1 ? "" : "s"} could not seat beside the disc on this payload and ${placement.degraded.length === 1 ? "is" : "are"} named in words in the strip under the plot instead: ${placement.degraded.join(", ")}`,
  );
}
await page.screenshot({ path: outPng });
await browser.close();

console.log(
  `gen-social-preview: wrote .github/social-preview.png (1280x640), the two ends of the cost story (${pointName(cheap)} and ${pointName(priciest)}) drawn from ${results} results, board date ${dateWords}`,
);
