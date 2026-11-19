#!/usr/bin/env node
/* Prototype capture. Serves the static export in ../out,
 * captures the three audited widths (1440, 1280, 390), the
 * explorer mid scroll, and an open reading, and prints
 * computed style evidence that the ground system is live.
 *
 * Env:
 *   PUPPETEER_EXECUTABLE_PATH  path to a Chromium or Chrome
 *   CAPTURE_DIR                output directory (default ./captures)
 */
import { createServer } from "node:http";
import { readFileSync, existsSync, statSync, mkdirSync } from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const boardDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const outDir = path.join(boardDir, "out");
const capDir = process.env.CAPTURE_DIR ?? path.join(boardDir, "captures");
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
const shot = async (name, opts = {}) => {
  const file = path.join(capDir, name);
  await page.screenshot({ path: file, ...opts });
  console.log("shot", name);
};
const settle = (ms = 900) => new Promise((r) => setTimeout(r, ms));

// Desktop 1440
await page.setViewport({ width: 1440, height: 1000 });
await page.goto(`${base}/`, { waitUntil: "networkidle0" });
await settle();
const evidence = await page.evaluate(() => {
  const cs = getComputedStyle(document.body);
  const band = document.querySelector(".scene.band");
  const wrap = document.querySelector(".chartwrap");
  const finding = document.querySelector(".finding");
  return {
    bodyBackgroundImage: cs.backgroundImage.slice(0, 160),
    bodyBackgroundColor: cs.backgroundColor,
    bandClass: band ? band.className : null,
    chartwrapBackground: wrap ? getComputedStyle(wrap).backgroundColor : null,
    findingShadow: finding ? getComputedStyle(finding).boxShadow.slice(0, 120) : null,
    h1: document.querySelector("h1")?.textContent ?? null,
  };
});
console.log("EVIDENCE", JSON.stringify(evidence, null, 2));
await shot("w1440-top.png");
await shot("w1440-full.png", { fullPage: true });

// Explorer band mid scroll at 1440
await page.evaluate(() => {
  document.querySelector("#explorer")?.scrollIntoView({ block: "start" });
});
await settle(500);
await shot("w1440-explorer.png");

// Reading open at 1440 in rank mode
await page.goto(`${base}/#explorer?pop=all&mode=rank&sort=asr`, { waitUntil: "networkidle0" });
await settle();
await page.evaluate(() => {
  document.querySelector("#explorer")?.scrollIntoView({ block: "start" });
});
await settle(400);
const clicked = await page.evaluate(() => {
  const head = document.querySelector(".xrow-head");
  if (!head) return false;
  head.click();
  return true;
});
console.log("row clicked:", clicked);
await settle(1200);
const readingInfo = await page.evaluate(() => {
  const r = document.querySelector(".reading.open") ?? document.querySelector(".belowreading .reading");
  if (!r) return null;
  const rect = r.getBoundingClientRect();
  return { top: rect.top + window.scrollY, height: rect.height, text: r.textContent.slice(0, 120) };
});
console.log("READING", JSON.stringify(readingInfo));
if (readingInfo) {
  await page.evaluate((y) => window.scrollTo(0, Math.max(0, y - 70)), readingInfo.top);
  await settle(500);
  await shot("w1440-reading.png");
  const famY = await page.evaluate(() => {
    const heads = [...document.querySelectorAll(".rdata-head")];
    const fam = heads.find((h) => h.textContent.includes("Attack families"));
    if (!fam) return null;
    const y = fam.getBoundingClientRect().top + window.scrollY;
    return y;
  });
  console.log("families block y:", famY);
  if (famY !== null) {
    await page.evaluate((y) => window.scrollTo(0, Math.max(0, y - 90)), famY);
    await settle(500);
    await shot("w1440-record.png");
  }
}

// Laptop 1280
await page.setViewport({ width: 1280, height: 900 });
await page.goto(`${base}/`, { waitUntil: "networkidle0" });
await settle();
await shot("w1280-top.png");
await shot("w1280-full.png", { fullPage: true });

// Phone 390
await page.setViewport({ width: 390, height: 844, hasTouch: true, isMobile: true });
await page.goto(`${base}/`, { waitUntil: "networkidle0" });
await settle();
await shot("w390-top.png");
await shot("w390-full.png", { fullPage: true });

// Phone reading as the bottom sheet
await page.goto(`${base}/#explorer?pop=all&mode=rank&sort=asr`, { waitUntil: "networkidle0" });
await settle();
await page.evaluate(() => {
  document.querySelector("#explorer")?.scrollIntoView({ block: "start" });
});
await settle(400);
await page.evaluate(() => {
  document.querySelector(".xrow-head")?.click();
});
await settle(1200);
const sheetInfo = await page.evaluate(() => {
  const r = document.querySelector(".reading.open");
  if (!r) return null;
  const rect = r.getBoundingClientRect();
  return { top: rect.top, height: rect.height, position: getComputedStyle(r).position };
});
console.log("SHEET", JSON.stringify(sheetInfo));
await shot("w390-reading.png");

await browser.close();
server.close();
console.log("capture complete");
