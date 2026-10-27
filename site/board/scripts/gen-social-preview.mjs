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
 * jev-1.14.0, near-free and tough, and claude-fable-5-1,
 * expensive and fragile. Every number on the card is a drawn
 * point, so the card claims nothing it does not show; the
 * headline is a fact of the drawn points, since the priciest
 * run on the board also carries the highest attack success.
 * Vendor identity resolves through lib/vendor-data.json and
 * the mark paths are read out of lib/logoPaths.ts, the same
 * sources the board itself uses, and the figures come from
 * data/payload.json. No suite case total appears on the card.
 * Run from site/board with:
 *   node scripts/gen-social-preview.mjs
 * The upload itself is manual: repo Settings, Social preview.
 * The redo evidence lives in the design program records
 * (cycle-09/redo/INDEX.md).
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
const credit = `Peira decision robustness board. Dataset ${versions.dataset}, suite ${versions.suite}, updated ${dateWords}. peiratrial.dev`;
const results = payload.ranked.length + payload.unranked.length;

/* The two drawn points, picked out of the full suite
 * population by name. They are the board's two corner
 * readings made literal: jev-1.14.0 is the cheapest plotted
 * run that held, and claude-fable-5-1 is the priciest run
 * and the highest attack success on the board, so the
 * headline over the chart is a fact of these two points. */
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
const jev = nonSlice.find((r) => r.display_name === "jev-1.14.0");
const fable = nonSlice.find((r) => r.display_name === "claude-fable-5-1");
if (!jev || !fable) {
  console.error(
    "gen-social-preview: a drawn point is missing from the full suite population (jev-1.14.0 or claude-fable-5-1): the card draws the board's two cost extremes and cannot be built without both",
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
 * success axis at 0 to 30 percent and the cost axis on the
 * log scale, with the keys inside the figure. The middle of
 * the plot is visibly empty; that emptiness is the selection
 * showing, and the sub-line states the selection in words. */
const BX = { x0: 150, x1: 1200, yTop: 236, yBot: 500, lo: -1.6, hi: 2.55 };
const bxOf = (c) =>
  BX.x0 +
  ((Math.log10(c) - BX.lo) / (BX.hi - BX.lo)) * (BX.x1 - BX.x0);
const byOf = (a) => BX.yBot - (a / 0.3) * (BX.yBot - BX.yTop);
const gridB = [0, 0.1, 0.2, 0.3]
  .map(
    (t) => `<line x1="${BX.x0}" y1="${byOf(t)}" x2="${BX.x1}" y2="${byOf(t)}" stroke="#232c35" stroke-opacity="0.55"/>
    <text x="${BX.x0 - 14}" y="${byOf(t) + 5}" class="tick" text-anchor="end">${Math.round(t * 100)}</text>`,
  )
  .join("\n");
const decadesB = [-1, 0, 1, 2]
  .map((dgt) => {
    const v = 10 ** dgt;
    return `<text x="${bxOf(v)}" y="${BX.yBot + 30}" class="tick" text-anchor="middle">${v < 1 ? `$${v.toFixed(2)}` : `$${v}`}</text>`;
  })
  .join("\n");
const jx = bxOf(jev.total_cost_usd);
const jy = byOf(jev.asr_conditional);
const fx = bxOf(fable.total_cost_usd);
const fy = byOf(fable.asr_conditional);
const R = 36;
const bSvg = `<svg width="1280" height="640" viewBox="0 0 1280 640" class="chart">
  <rect x="48" y="196" width="1184" height="376" fill="#0c1015" stroke="#232c35"/>
  ${gridB}
  <line x1="${BX.x0}" y1="${BX.yBot}" x2="${BX.x1}" y2="${BX.yBot}" stroke="#232c35"/>
  ${decadesB}
  <text x="${BX.x0 + 6}" y="226" class="tick">Attack success, percent</text>
  <text x="${BX.x0}" y="560" class="tick">Recorded cost per run, US dollars, log scale</text>
  <text x="${jx + R + 20}" y="${jy - 38}" class="micro2">NEAR-FREE AND TOUGH</text>
  <text x="${jx + R + 20}" y="${jy}" class="pname">${esc(pointName(jev))}</text>
  <text x="${jx + R + 20}" y="${jy + 36}" class="pfig">Attack success ${fmtPct(jev.asr_conditional)}</text>
  <text x="${jx + R + 20}" y="${jy + 68}" class="pfig">Cost ${fmtMoney(jev.total_cost_usd)} per run</text>
  <text x="${fx - R - 20}" y="${fy - 30}" class="micro2" text-anchor="end">EXPENSIVE AND FRAGILE</text>
  <text x="${fx - R - 20}" y="${fy + 10}" class="pname" text-anchor="end">${esc(pointName(fable))}</text>
  <text x="${fx - R - 20}" y="${fy + 46}" class="pfig" text-anchor="end">Attack success ${fmtPct(fable.asr_conditional)}</text>
  <text x="${fx - R - 20}" y="${fy + 78}" class="pfig" text-anchor="end">Cost ${fmtMoney(fable.total_cost_usd)} per run</text>
  ${bigDisc(jev, jx, jy, R)}
  ${bigDisc(fable, fx, fy, R)}
</svg>`;

/* Tripwire: the card draws exactly two points and nothing
 * else in the plot. The five lines are the four grid lines
 * and the cost axis; a third disc or any extra line means
 * the selection has silently grown, and the build fails
 * rather than let the card drift back toward the full
 * scatter the owner rejected. */
const bCircleCount = (bSvg.match(/<circle/g) ?? []).length;
const bLineCount = (bSvg.match(/<line/g) ?? []).length;
if (bCircleCount !== 2 || bLineCount !== 5) {
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
</style></head><body>
${bSvg}
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
await page.screenshot({ path: outPng });
await browser.close();

console.log(
  `gen-social-preview: wrote .github/social-preview.png (1280x640), the two ends of the cost story (${pointName(jev)} and ${pointName(fable)}) drawn from ${results} results, board date ${dateWords}`,
);
