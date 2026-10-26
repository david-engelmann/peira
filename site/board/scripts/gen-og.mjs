/**
 * Build-time social preview and data staging (SO-01, TR-02,
 * SF-04). Renders public/og.png, 1200 by 630, from the same
 * payload the page renders, carrying the board name, the
 * headline counts, the top of the full suite ranking, and the
 * board date. Also stages public/payload.json so the page can
 * link the exact data behind it in one click. Numbers format
 * with the same decimal half-up rule as the page.
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
const fmtInt = (n) => String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ",");

const shortName = (r) => {
  let name = r.display_name;
  const at = name.lastIndexOf("@");
  if (at > 0 && /^[0-9a-f]{32,}$/i.test(name.slice(at + 1))) {
    name = name.slice(0, at);
  }
  const slash = name.lastIndexOf("/");
  return slash >= 0 ? name.slice(slash + 1) : name;
};

const fullCases = Math.max(...payload.ranked.map((r) => r.n_cases));
const full = payload.ranked.filter((r) => r.n_cases === fullCases);
const top = full.slice(0, 7);
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
/* Headline counts follow the masthead's rule (lib/payload.ts
 * modelCounts): distinct served model names, so the share
 * image never contradicts the page. Results stays the entry
 * count the masthead leads with; ranked and flagged count
 * models, which on a two-wire payload is one less than the
 * ranked entry count (live-fix round, R-2, 2026-10-23). */
const rankedModels = new Set(payload.ranked.map((r) => r.display_name)).size;
const flaggedModels = new Set(payload.unranked.map((r) => r.display_name)).size;

/* The share image is the board's money shot: the annotated
 * cost scatter itself, at a size where it still reads in a
 * feed thumbnail. Every full suite point is a disc in its
 * maker's family color carrying the maker's mark, flagged
 * results keep the amber ring, the rail holds the results
 * with no recorded API cost, and the two corner readings are
 * set in display type. The family table below mirrors
 * lib/vendorColors.ts and the mark paths are read out of
 * lib/logoPaths.ts, so the image cannot drift from the board.
 * The headline is a fact of this payload: the priciest run
 * (claude-fable-5-1, $130.31) also carries the highest attack
 * success on the board. */
const FAMILIES = [
  [/gpt-|openai/, "#d7e0e8", "#0b0e12", "openai"],
  [/claude|anthropic/, "#d97757", "#f4f7fa", "anthropic"],
  [/gemini|google/, "#8ab8ff", "#0b0e12", "googlegemini"],
  [/llama|prompt-guard|meta/, "#4a7dff", "#f4f7fa", "meta"],
  [/granite|ibm/, "#4fb3e3", "#0b0e12", "ibm"],
  [/mistral|shieldstral/, "#ff8a3d", "#0b0e12", "mistralai"],
  [/clef|cloudflare/, "#f0b429", "#0b0e12", "cloudflare"],
  [/deepseek/, "#6e7bff", "#f4f7fa", "deepseek"],
  [/qwen/, "#a78bfa", "#0b0e12", "qwen"],
  [/pplx|perplexity/, "#2ec4b6", "#0b0e12", "perplexity"],
  [/minimax/, "#f24e7e", "#f4f7fa", "minimax"],
  [/kimi|moonshot/, "#9fb4c7", "#0b0e12", "moonshotai"],
  [/microsoft/, "#7bc950", "#0b0e12", "microsoft"],
  [/cursor/, "#b8bdc7", "#0b0e12", "cursor"],
  [/grok|xai/, "#ffffff", "#0b0e12", "xai"],
  [/glm|zai/, "#126ef6", "#f4f7fa", "zhipu"],
  [/jev/, "#e551ba", "#0b0e12", "typesafe"],
  [/kev/, "#e879f9", "#0b0e12", null],
  [/laya/, "#5eead4", "#0b0e12", null],
  [/decider-0|mapika/, "#e5c15c", "#0b0e12", null],
  [/strands/, "#2aa198", "#0b0e12", null],
  [/celeris/, "#7dd3fc", "#0b0e12", "celeris"],
  [/mercury|inception/, "#6f9aa5", "#0b0e12", "inception"],
  [/solar|upstage/, "#805cfb", "#f4f7fa", "upstage"],
  [/ling|inclusionai/, "#c4b5fd", "#0b0e12", null],
  [/protectai|deberta/, "#5f31cd", "#f4f7fa", "protectai"],
];
/* Monogram letters for the providers that publish no usable
 * mark, mirroring lib/vendor.ts so the image cannot drift. */
const MONO_LETTERS = [
  [/mapika/, "M"],
  [/kev/, "K"],
  [/laya/, "L"],
  [/strands/, "S"],
  [/ling|inclusionai/, "L"],
];
const familyOf = (r) => {
  const hay = `${r.display_name} ${r.adapter_name} ${r.wire}`.toLowerCase();
  for (const f of FAMILIES) if (f[0].test(hay)) return f;
  return [null, "#8b98a5", "#0b0e12", null];
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
  const monoRule = MONO_LETTERS.find(([re]) =>
    re.test(`${r.display_name} ${r.adapter_name} ${r.wire}`.toLowerCase()),
  );
  const monoLetter =
    monoRule?.[1] ??
    (shortName(r).match(/[a-z0-9]/i)?.[0]?.toUpperCase() ?? "·");
  const glyph = fam[3]
    ? `<path d="${LOGO_PATHS[fam[3]]}" transform="translate(-6 -6) scale(0.5)" fill="${fam[2]}"/>`
    : `<text y="1" class="mono" fill="${fam[2]}">${esc(monoLetter)}</text>`;
  return `<g transform="translate(${x.toFixed(1)} ${y.toFixed(1)})">
    <circle r="11" fill="${fam[1]}" stroke="${flagged ? "#e8a33d" : "rgba(255,255,255,0.28)"}" stroke-width="${flagged ? 2.5 : 1}"/>
    ${glyph}
  </g>`;
}
/* Label placements for the named points, as offsets from the
 * point. Chosen against the payload positions so no two
 * labels meet and no disc strikes a label; every other point
 * still carries its disc and mark, and the rail names all
 * five of its points. The ling label sits right of both ling
 * discs (the vl disc struck its old below-right seat), and
 * the qwen label sits above-left of its disc, clear of the
 * corner readings and the MiniMax label. */
const LABELS = {
  "anthropic-fable-v2-trial": { dx: -18, dy: 5, anchor: "end" },
  "anthropic-opus-v2-trial": { dx: -18, dy: -16, anchor: "end" },
  "or-qwen-v2-trial": { dx: -18, dy: -16, anchor: "end" },
  "or-ling-v2-trial": { dx: 24, dy: 2, anchor: "start" },
  "anthropic-v2-trial": { dx: 0, dy: 31, anchor: "middle" },
  "minimax-v2-trial": { dx: -18, dy: 5, anchor: "end" },
  "xai-v2-trial": { dx: 18, dy: 5, anchor: "start" },
  "moonshot-v2-trial": { dx: 18, dy: 5, anchor: "start" },
  "jev-114-v2-trial": { dx: 0, dy: 30, anchor: "middle" },
  "mercury-decide-v2-trial": { dx: 20, dy: 40, anchor: "start" },
  "pplx-decider-v2-trial": { dx: -16, dy: 8, anchor: "end" },
  "openai-terra56-v2-trial": { dx: 0, dy: -20, anchor: "middle" },
};
const gridSvg = [0, 0.1, 0.2, 0.3]
  .map(
    (t) => `<line x1="48" y1="${yOf(t)}" x2="${PLOT.x1}" y2="${yOf(t)}" stroke="#232c35" stroke-opacity="0.55"/>
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
for (let pass = 0; pass < 4; pass++) {
  for (let i = 1; i < railSpread.length; i++) {
    railSpread[i].y = Math.max(railSpread[i].y, railSpread[i - 1].y + 21);
  }
  for (let i = railSpread.length - 2; i >= 0; i--) {
    railSpread[i].y = Math.min(railSpread[i].y, railSpread[i + 1].y - 21);
  }
}
const railY = new Map(railSpread.map((e) => [e.r.run_id, e.y]));
const pointsSvg = [
  ...railRows.map((r) => disc(r, RAIL_CX, railY.get(r.run_id))),
  ...plotted.map((r) => disc(r, xOf(r.total_cost_usd), yOf(r.asr_conditional))),
].join("\n");
const labelsSvg = [
  ...railRows.map(
    (r) =>
      `<text x="${RAIL_CX + 22}" y="${railY.get(r.run_id) + 5}" class="lab">${esc(shortName(r))}</text>`,
  ),
  ...plotted
    .filter((r) => LABELS[r.run_id])
    .map((r) => {
      const l = LABELS[r.run_id];
      return `<text x="${xOf(r.total_cost_usd) + l.dx}" y="${yOf(r.asr_conditional) + l.dy}" class="lab" text-anchor="${l.anchor}">${esc(shortName(r))}</text>`;
    }),
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
  ${labelsSvg}
  <text x="${PLOT.x0}" y="572" class="tick">Recorded cost per run, US dollars, log scale</text>
</svg>`;

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
  <p class="sub">Attack success against recorded cost per run, every model deciding the same paired cases.</p>
</div>
<p class="foot">Peira decision robustness board. Dataset ${versions.dataset}, suite ${versions.suite}, updated ${dateWords}. peiratrial.dev</p>
</body></html>`;

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
await page.screenshot({ path: path.join(root, "public", "og.png") });
await browser.close();

copyFileSync(
  path.join(root, "data", "payload.json"),
  path.join(root, "public", "payload.json"),
);
console.log(
  `gen-og: wrote public/og.png (1200x630) and public/payload.json from ${results} results, board date ${dateWords}`,
);
