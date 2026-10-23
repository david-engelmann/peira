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

const rowsHtml = top
  .map((r) => {
    const pct = (r.asr_conditional / 0.3) * 100;
    return `<div class="row">
      <span class="name">${shortName(r)}</span>
      <span class="track"><span class="bar" style="width:${pct.toFixed(2)}%"></span></span>
      <span class="val">${fmtPct(r.asr_conditional)}</span>
    </div>`;
  })
  .join("\n");

const html = `<!doctype html>
<html><head><meta charset="utf-8"><style>
@font-face { font-family: "Archivo"; src: url("../public/fonts/archivo.woff2") format("woff2"); }
* { margin: 0; box-sizing: border-box; }
body { width: 1200px; height: 630px; background: #0A0C0F; color: #E9EEF3;
  font-family: "Archivo", system-ui, sans-serif; padding: 56px 64px; }
.word { font-size: 30px; font-weight: 700; letter-spacing: 0.04em; color: #2FBF71; }
h1 { font-size: 54px; font-weight: 700; margin-top: 10px; }
.sub { font-size: 25px; color: #AEBCC7; margin-top: 14px; }
.rows { margin-top: 40px; display: flex; flex-direction: column; gap: 17px; }
.row { display: flex; align-items: center; gap: 20px; }
.name { width: 330px; font-size: 23px; color: #E9EEF3; text-align: right;
  white-space: nowrap; overflow: hidden; }
.track { flex: 1; height: 20px; background: #10141A; position: relative; }
.bar { position: absolute; inset: 0 auto 0 0; background: #171D24;
  border-right: 3px solid #E9EEF3; }
.val { width: 90px; font-size: 23px; font-variant-numeric: tabular-nums; }
.foot { margin-top: 40px; font-size: 21px; color: #71808F; }
</style></head><body>
<div class="word">PEIRA</div>
<h1>Decision robustness board</h1>
<p class="sub">Attack success on ${fmtInt(fullCases)} paired cases. ${results} results, ${payload.ranked.length} ranked, ${payload.unranked.length} flagged.</p>
<div class="rows">${rowsHtml}</div>
<p class="foot">Top of the full suite ranking, lower is harder to flip. Dataset ${versions.dataset}, suite ${versions.suite}, updated ${dateWords}. peiratrial.dev</p>
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
const chromeHits = [
  ...globSync(
    ".cache/ms-playwright/chromium-*/chrome-linux64/chrome",
    { cwd: homedir() },
  ),
  ...globSync(
    ".cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell",
    { cwd: homedir() },
  ),
];
if (chromeHits.length === 0) {
  console.error("gen-og: no Chromium found in the Playwright cache");
  process.exit(1);
}
const browserEnv = { ...process.env };
for (const k of Object.keys(browserEnv)) {
  if (/proxy/i.test(k)) delete browserEnv[k];
}
const browser = await puppeteer.launch({
  executablePath: path.join(homedir(), chromeHits[0]),
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
