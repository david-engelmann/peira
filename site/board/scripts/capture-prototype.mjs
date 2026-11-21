#!/usr/bin/env node
/* Prototype capture. Serves the static export in ../out,
 * captures the three audited widths (1440, 1280, 390), the
 * explorer mid scroll, and an open reading, and both analytical figures.
 *
 * Env:
 *   PUPPETEER_EXECUTABLE_PATH  path to a Chromium or Chrome
 *   CAPTURE_DIR                output directory (default ./captures)
 */
import { createServer } from "node:http";
import { readFileSync, existsSync, statSync, mkdirSync, copyFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const boardDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const outDir = path.join(boardDir, "out");
const readmeOnly = process.argv.includes("--readme");
const capDir = process.env.CAPTURE_DIR ?? (readmeOnly
  ? path.resolve(boardDir, "../../.github/board")
  : path.join(boardDir, "captures"));
if (!existsSync(path.join(outDir, "index.html"))) {
  console.error("capture failed: out/index.html missing, run npm run build first");
  process.exit(1);
}
mkdirSync(capDir, { recursive: true });

const MIME = {
  ".html": "text/html", ".js": "text/javascript", ".css": "text/css",
  ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png",
  ".woff2": "font/woff2", ".txt": "text/plain",
};
const server = createServer((req, res) => {
  const url = new URL(req.url, "http://localhost");
  let p = path.join(outDir, decodeURIComponent(url.pathname));
  if (url.pathname.endsWith("/")) p = path.join(p, "index.html");
  if (!existsSync(p) || !statSync(p).isFile()) { res.writeHead(404).end("not found"); return; }
  res.writeHead(200, { "content-type": MIME[path.extname(p)] ?? "application/octet-stream" });
  res.end(readFileSync(p));
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const base = `http://127.0.0.1:${server.address().port}`;

const require2 = createRequire(path.join(boardDir, "package.json"));
const pupMod = require2("puppeteer-core");
const pup = pupMod?.launch ? pupMod : pupMod?.default;
if (!pup?.launch) { console.error("capture failed: puppeteer-core not resolvable"); process.exit(1); }

const chromePath = process.env.PUPPETEER_EXECUTABLE_PATH;
const browserEnv = { ...process.env };
for (const k of Object.keys(browserEnv)) if (/proxy/i.test(k)) delete browserEnv[k];

let browser;
try {
  browser = await pup.launch({
    ...(chromePath ? { executablePath: chromePath } : {}),
    env: browserEnv,
    timeout: 180000,
    args: ["--no-sandbox", "--no-zygote", "--single-process", "--force-color-profile=srgb"],
  });
} catch (e) {
  console.error(`CHROMIUM LAUNCH FAILED: ${e.message}`);
  process.exit(2);
}
console.log("chromium launched");

const page = await browser.newPage();
if (readmeOnly) {
  try {
    await page.setViewport({ width: 1200, height: 880, deviceScaleFactor: 1.5 });
    for (const theme of ["light", "dark"]) {
      await page.goto("about:blank");
      await page.emulateMediaFeatures([
        { name: "prefers-color-scheme", value: theme },
        { name: "prefers-reduced-motion", value: "reduce" },
      ]);
      await page.goto(base, { waitUntil: "networkidle0" });
      await page.evaluate(() => document.fonts.ready);
      const signature = await page.$eval(".brand .peira-signature", async el => {
        const image = el.querySelector("img");
        const response = await fetch(image.src);
        if (!response.ok) throw Error("Unable to load the Peira symbol");
        const symbol = new DOMParser().parseFromString(await response.text(), "image/svg+xml").documentElement;
        const letters = el.querySelector("svg").cloneNode(true);
        const { width, height } = el.getBoundingClientRect();
        const bounds = el.querySelector("svg").getBoundingClientRect();
        const frame = el.getBoundingClientRect();
        symbol.setAttribute("width", image.width);
        symbol.setAttribute("height", image.height);
        letters.setAttribute("x", bounds.x - frame.x);
        letters.setAttribute("y", bounds.y - frame.y);
        letters.setAttribute("fill", getComputedStyle(el).color);
        return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}"><title>Peira</title>${symbol.outerHTML}${letters.outerHTML}</svg>\n`;
      });
      writeFileSync(path.join(capDir, `peira-${theme}.svg`), signature);
      const bottom = await page.$eval("#results", el => el.getBoundingClientRect().bottom);
      await page.screenshot({
        path: path.join(capDir, `overview-${theme}.webp`), quality: 92,
        clip: { x: 0, y: 0, width: 1200, height: Math.ceil(bottom) },
      });
      const costFigure = await page.$(".study-finding-cost .study-finding-figure");
      await costFigure.evaluate(el => window.scrollBy({ top: el.getBoundingClientRect().top - 90, behavior: "instant" }));
      await costFigure.screenshot({ path: path.join(capDir, `cost-${theme}.webp`), quality: 92 });
      await page.evaluate(() => { location.hash = "explorer?pop=full&mode=chart&kind=general&serving=hosted"; });
      await page.waitForFunction(() => document.querySelector("#explorer-kind")?.value === "general"
        && document.querySelector("#explorer-serving")?.value === "hosted");
      const chart = await page.waitForSelector(".chartlayout svg.chart");
      await page.$eval("#explorer", el => el.blur());
      await chart.evaluate(() => window.scrollBy({ top: document.querySelector(".chart-presets").getBoundingClientRect().top - 96, behavior: "instant" }));
      const clip = await page.evaluate(() => {
        const figure = document.querySelector(".chartlayout").getBoundingClientRect();
        const top = document.querySelector(".chart-presets").getBoundingClientRect().top;
        const margin = 16;
        return { x: figure.left - margin, y: top + scrollY - margin,
          width: figure.width + 2 * margin, height: figure.bottom - top + margin * 2 };
      });
      await page.screenshot({ path: path.join(capDir, `explorer-${theme}.webp`), quality: 92, clip });
    }
    if (!process.env.CAPTURE_DIR) {
      copyFileSync(path.join(outDir, "opengraph-image"), path.resolve(capDir, "../social-preview.png"));
    }
  } finally {
    await browser.close();
    server.close();
  }
  process.exit(0);
}

const shot = async (name, opts = {}) => {
  const file = path.join(capDir, name);
  await page.screenshot({ path: file, ...opts });
  console.log("shot", name);
};
const settle = (ms = 900) => new Promise((r) => setTimeout(r, ms));
// Leave room for both the masthead and the sticky ranking header.
const recordInset = 140;
const scrollToExplorer = async () => {
  await page.$eval("#explorer", (el) => el.scrollIntoView({ block: "start" }));
  await settle(500);
};
const openRankedReading = async () => {
  await page.goto(`${base}/#explorer?pop=all&mode=rank&sort=asr`, { waitUntil: "networkidle0" });
  await settle();
  await scrollToExplorer();
  await page.$eval(".xrow-head", (el) => el.click());
  const reading = await page.waitForSelector(".reading.open", { visible: true });
  await settle();
  return reading;
};

// Desktop 1440
await page.setViewport({ width: 1440, height: 1000 });
await page.goto(`${base}/`, { waitUntil: "networkidle0" });
await settle();
await shot("w1440-top.png");
await shot("w1440-full.png", { fullPage: true });
for (const [id, name] of [["study-families-heading", "families"], ["study-cost-heading", "cost"]]) {
  await page.$eval(`#${id}`, (el) => window.scrollBy({ top: el.getBoundingClientRect().top - 110, behavior: "instant" }));
  await shot(`w1440-${name}.png`);
}

// Explorer band mid scroll at 1440
await scrollToExplorer();
await shot("w1440-explorer.png");

// Reading open at 1440 in rank mode
const desktopReading = await openRankedReading();
const readingInfo = await desktopReading.evaluate((r) => {
  const rect = r.getBoundingClientRect();
  return { top: rect.top + window.scrollY, height: rect.height, text: r.textContent.slice(0, 120) };
});
console.log("READING", JSON.stringify(readingInfo));
await page.evaluate((top, inset) => window.scrollTo(0, Math.max(0, top - inset)), readingInfo.top, recordInset);
await settle(500);
await shot("w1440-reading.png");
const famY = await page.evaluate(() => {
  const heads = [...document.querySelectorAll(".rdata-head")];
  const fam = heads.find((h) => h.textContent.includes("Attack families"));
  return fam ? fam.getBoundingClientRect().top + window.scrollY : null;
});
console.log("families block y:", famY);
if (famY !== null) {
  await page.evaluate((top, inset) => window.scrollTo(0, Math.max(0, top - inset)), famY, recordInset);
  await settle(500);
  await shot("w1440-record.png");
}

// Laptop 1280
await page.setViewport({ width: 1280, height: 900 });
await page.goto(`${base}/`, { waitUntil: "networkidle0" });
await settle();
await shot("w1280-top.png");
await shot("w1280-full.png", { fullPage: true });
await scrollToExplorer();
await shot("w1280-explorer.png");
const laptopReading = await openRankedReading();
await laptopReading.evaluate((r, inset) => window.scrollBy(0, r.getBoundingClientRect().top - inset), recordInset);
await settle(500);
await shot("w1280-reading.png");

// Phone 390
await page.setViewport({ width: 390, height: 844, hasTouch: true, isMobile: true });
await page.goto(`${base}/`, { waitUntil: "networkidle0" });
await settle();
await shot("w390-top.png");
await shot("w390-full.png", { fullPage: true });
await scrollToExplorer();
await shot("w390-explorer.png");

// Phone reading as the bottom sheet
const phoneReading = await openRankedReading();
const sheetInfo = await phoneReading.evaluate((r) => {
  const rect = r.getBoundingClientRect();
  return { top: rect.top, height: rect.height, position: getComputedStyle(r).position };
});
console.log("SHEET", JSON.stringify(sheetInfo));
await shot("w390-reading.png");

await browser.close();
server.close();
console.log("capture complete");
