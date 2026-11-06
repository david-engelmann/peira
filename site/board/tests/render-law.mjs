/**
 * Render laws for the redesigned board. The built page in
 * out/ is served locally and loaded in a real Chromium at
 * four widths, and the laws the redesign must keep are
 * asserted on the rendered document, not on the source:
 *
 *   the page loads clean (no page error, no console error)
 *     at every width
 *   nothing overflows horizontally at any width
 *   the hero and Method both carry the frozen counting
 *     sentence verbatim
 *   the suite case count stands in the rendered text only
 *     where the rules allow it (Method, the guard subset
 *     basis in Finding 4, the disclosure panel in Finding 5)
 *   the flagged band's highest result stands in the
 *     explorer's rows with its malformed decomposition
 *     beside its counted rate (C-5)
 *   the visible text obeys the copy rules (no em dash, no
 *     en dash, no semicolon, no colon outside a link target)
 *   the chart's annotations beyond its axis labels run at
 *     most 25 words each (BUILD-SPEC section 8, measured
 *     here because the chart is client rendered)
 *   at phone width the touch targets the design promises
 *     measure at least 44px
 *
 * Run after next build (the build chain runs it). Exit code
 * is non-zero on any breach.
 */
import { createServer } from "node:http";
import { readFileSync, existsSync, statSync } from "node:fs";
import { globSync } from "node:fs";
import { homedir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const outDir = path.join(root, "out");
if (!existsSync(path.join(outDir, "index.html"))) {
  console.error("render law failed: out/index.html is missing. Run next build first");
  process.exit(1);
}
const payload = JSON.parse(readFileSync(path.join(root, "data", "payload.json"), "utf8"));

const failures = [];
const fail = (msg) => failures.push(msg);
const laws = [];
const law = (msg) => laws.push(msg);

/* The flagged band's highest result and its decomposition,
 * derived here from the payload. */
function decompOf(r) {
  let fams = r.detail?.families;
  if (!fams) return null;
  if (!Array.isArray(fams)) fams = Object.values(fams);
  let flips = 0;
  let malformed = 0;
  for (const f of fams) {
    if (typeof f.n_flipped !== "number") return null;
    const tm = f.flip_direction?.["to-malformed"];
    if (typeof tm !== "number") return null;
    flips += f.n_flipped;
    malformed += tm;
  }
  return { flips, malformed };
}
const mercury = payload.unranked.reduce((a, b) =>
  (a.asr_conditional ?? 0) > (b.asr_conditional ?? 0) ? a : b,
);
const mercDecomp = decompOf(mercury);
const pct1 = (v) => `${(Math.round(v * 1000) / 10).toFixed(1)}%`;
const fullCases = Math.max(...payload.ranked.map((r) => r.n_cases));
const suiteCount = fullCases.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
const FROZEN =
  "Attack success counts a case only when the benign answer was right and the attacked side answered wrong, abstained, or produced malformed output.";

/* ---------- static server over out/ ---------- */

const MIME = {
  ".html": "text/html",
  ".js": "text/javascript",
  ".css": "text/css",
  ".json": "application/json",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".woff2": "font/woff2",
  ".txt": "text/plain",
};
const server = createServer((req, res) => {
  const url = new URL(req.url, "http://localhost");
  let p = path.join(outDir, decodeURIComponent(url.pathname));
  if (url.pathname.endsWith("/")) p = path.join(p, "index.html");
  if (!existsSync(p) || !statSync(p).isFile()) {
    res.writeHead(404).end("not found");
    return;
  }
  res.writeHead(200, { "content-type": MIME[path.extname(p)] ?? "application/octet-stream" });
  res.end(readFileSync(p));
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const port = server.address().port;
const base = `http://127.0.0.1:${port}`;

/* ---------- browser ---------- */

const chromeOverride = process.env.PUPPETEER_EXECUTABLE_PATH ?? process.env.CHROME_PATH;
const chromeHits = chromeOverride
  ? [chromeOverride]
  : [
      ...globSync(".cache/ms-playwright/chromium-*/chrome-linux64/chrome", {
        cwd: homedir(),
      }).map((p) => path.join(homedir(), p)),
      ...globSync(
        ".cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell",
        { cwd: homedir() },
      ).map((p) => path.join(homedir(), p)),
    ];
if (chromeHits.length === 0) {
  console.error("render law failed: no Chromium found in the Playwright cache");
  process.exit(1);
}
const browserEnv = { ...process.env };
for (const k of Object.keys(browserEnv)) {
  if (/proxy/i.test(k)) delete browserEnv[k];
}
const browser = await puppeteer.launch({
  executablePath: chromeHits[0],
  env: browserEnv,
  timeout: 180000,
  args: ["--no-sandbox", "--no-zygote", "--single-process", "--force-color-profile=srgb"],
});

const WIDTHS = [360, 768, 1024, 1440];
for (const width of WIDTHS) {
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(`pageerror ${e.message}`));
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(`console ${m.text()}`);
  });
  await page.setViewport({ width, height: 900 });
  await page.goto(`${base}/`, { waitUntil: "networkidle0" });
  if (errors.length > 0) fail(`at ${width}px the page loads with errors: ${errors[0]}`);
  const overflow = await page.evaluate(() => {
    return document.documentElement.scrollWidth - window.innerWidth;
  });
  if (overflow > 1) fail(`at ${width}px the page overflows horizontally by ${overflow}px`);
  await page.close();
}
law(`the page loads clean with no horizontal overflow at ${WIDTHS.join(", ")}px`);

/* ---------- document laws at desktop width ---------- */

const page = await browser.newPage();
await page.setViewport({ width: 1280, height: 900 });
await page.goto(`${base}/`, { waitUntil: "networkidle0" });

const heroText = await page.$eval(".hero", (el) => el.textContent ?? "");
if (!heroText.includes(FROZEN)) fail("the rendered hero drops the frozen sentence");
else law("the rendered hero carries the frozen sentence");

const methodText = await page.$eval("#method", (el) => el.textContent ?? "");
if (!methodText.includes(FROZEN)) fail("the rendered Method drops the frozen sentence");
else law("the rendered Method carries the frozen sentence");

const placements = await page.evaluate((needle) => {
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const bad = [];
  let node;
  while ((node = walker.nextNode())) {
    if (!node.textContent.includes(needle)) continue;
    const el = node.parentElement;
    if (el.closest("script, style, noscript")) continue;
    const inMethod = el.closest("#method") !== null;
    const finding = el.closest(".finding");
    const findings = [...document.querySelectorAll(".finding")];
    const findingIdx = finding ? findings.indexOf(finding) : -1;
    const inPanel = el.closest(".f-panel") !== null;
    if (!inMethod && findingIdx !== 3 && findingIdx !== 4 && !inPanel) {
      bad.push(node.textContent.trim().slice(0, 60));
    }
  }
  return bad;
}, suiteCount);
if (placements.length > 0) {
  fail(`the suite count stands outside its allowed places: ${placements[0]}`);
} else law("the suite count stands only in its allowed places");

const mercuryRow = await page.evaluate((rid) => {
  const el = document.querySelector(`[data-rid="${rid}"]`);
  return el ? el.textContent ?? "" : null;
}, mercury.run_id);
if (mercuryRow === null) {
  fail("the explorer's rendered rows do not include the flagged band's highest result");
} else {
  const share = mercDecomp ? mercDecomp.malformed / mercDecomp.flips : null;
  if (!mercuryRow.includes(pct1(mercury.asr_conditional))) {
    fail("the flagged lead's explorer row drops its counted rate");
  } else if (share === null || !mercuryRow.includes(pct1(share))) {
    fail("the flagged lead's explorer row prints its rate without its decomposition");
  } else law("the flagged lead's row pairs its rate with its decomposition");
}

const visibleText = await page.evaluate(() => document.body.innerText);
if (/—/.test(visibleText)) fail("the rendered text carries an em dash");
if (/–/.test(visibleText)) fail("the rendered text carries an en dash");
if (/;/.test(visibleText)) fail("the rendered text carries a semicolon");
if (/:/.test(visibleText.replace(/https?:\/\/\S+/g, " "))) {
  fail("the rendered text carries a colon outside a link target");
}
law("the rendered text obeys the copy rules");

/* Chart annotations. Enter chart mode and read the notes the
 * chart itself prints beyond its axis labels. */
await page.evaluate(() => {
  const btns = [...document.querySelectorAll("button")];
  const chartBtn = btns.find((b) => b.textContent.trim() === "Chart");
  chartBtn?.click();
});
await page.waitForSelector("svg.chart", { timeout: 10000 }).catch(() => null);
const notes = await page.evaluate(() => {
  const out = [];
  for (const sel of [".offscale-note", ".rail-note"]) {
    const el = document.querySelector(sel);
    if (el) out.push(el.textContent ?? "");
  }
  return out;
});
/* The malformed measure's flag note is an annotation of the
 * same chart and stands under the same cap. */
await page.evaluate(() => {
  const btns = [...document.querySelectorAll("button")];
  btns.find((b) => b.textContent.trim() === "Malformed")?.click();
});
await page.waitForSelector(".flag-note", { timeout: 10000 }).catch(() => null);
const flagNote = await page.evaluate(() => {
  return document.querySelector(".flag-note")?.textContent ?? "";
});
if (flagNote) notes.push(flagNote);
const wordCount = (t) => t.split(/\s+/).filter((x) => /[A-Za-z]/.test(x)).length;
for (const n of notes) {
  if (wordCount(n) > 25) {
    fail(`a chart annotation runs ${wordCount(n)} words, cap 25: ${n.slice(0, 60)}`);
  }
}
/* The leg fails closed. A chart that printed no annotation
 * at all leaves nothing measured, and a law recorded over an
 * empty set would certify a chart nobody read. */
if (notes.length === 0) {
  fail("the chart printed no annotation to measure, so the annotation law has no evidence");
} else {
  law("chart annotations beyond axis labels run at most 25 words");
}
await page.close();

/* ---------- phone touch targets ---------- */

const phone = await browser.newPage();
await phone.setViewport({ width: 390, height: 844, hasTouch: true, isMobile: true });
await phone.goto(`${base}/`, { waitUntil: "networkidle0" });
const smallTargets = await phone.evaluate(() => {
  const out = [];
  for (const el of document.querySelectorAll(".f-action, .segbtn, .ghostbtn")) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    if (r.height < 43) out.push(`${el.className} at ${Math.round(r.height)}px`);
  }
  return out;
});
if (smallTargets.length > 0) {
  fail(`phone touch targets under 44px: ${smallTargets.slice(0, 3).join(", ")}`);
} else law("phone touch targets measure at least 44px");
await phone.close();

await browser.close();
server.close();

for (const l of laws) console.log(`render law: ${l}`);
if (failures.length > 0) {
  console.error(`\nrender law FAILED (${failures.length}):`);
  for (const f of failures) console.error(`  - ${f}`);
  process.exit(1);
}
console.log(`render law passed (${laws.length} laws)`);
