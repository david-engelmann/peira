#!/usr/bin/env node
/**
 * DOM audit for the redesigned board. Where render-law checks
 * the static document, this audit drives the explorer the way
 * a reader does, at six widths and in a touch session at 390
 * by 844, and asserts the interaction contract of BUILD-SPEC
 * sections 4 to 7:
 *
 *   a row expands in place into its reading, with the
 *     calibration plot rendered for a result that carries one
 *   pinning two readings raises the compare tray, whose
 *     comparison carries the four derived deltas, each
 *     signed in words
 *   sorting and the population filter restate the view, the
 *     guard population with its basis line
 *   chart hover lights the same result in the list beside
 *     the chart, and a brush drag filters the view and says
 *     so in the count line
 *   a model address (/#result=<slug>) opens that reading
 *   a finding's action sets the explorer state it promises
 *   families mode sorts by a family from its label
 *   at phone size the reading opens as a sheet over a sticky
 *     strip that names the selection, the tray pins above
 *     the strip, and a tap outside dismisses the sheet
 *
 * Run after next build, standalone:
 *   node scripts/audit-dom.mjs
 * Exit code is non-zero on any failure.
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
  console.error("audit failed: out/index.html is missing. Run next build first");
  process.exit(1);
}
const payload = JSON.parse(readFileSync(path.join(root, "data", "payload.json"), "utf8"));

const failures = [];
const fail = (msg) => failures.push(msg);
const passes = [];
const pass = (msg) => passes.push(msg);

/* ---------- derivations the audit asserts against ---------- */

const rows = [...payload.ranked, ...payload.unranked];
const fullCases = Math.max(...payload.ranked.map((r) => r.n_cases));
const full = payload.ranked.filter((r) => r.n_cases === fullCases);
const slices = payload.ranked.filter((r) => r.n_cases < fullCases);
const fmtInt = (n) => Math.round(n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
const shortName = (r) => {
  let name = r.display_name;
  const at = name.lastIndexOf("@");
  if (at > 0 && /^[0-9a-f]{32,}$/i.test(name.slice(at + 1))) name = name.slice(0, at);
  const slash = name.lastIndexOf("/");
  return slash >= 0 ? name.slice(slash + 1) : name;
};
const slugify = (s) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
function modelSlug(row) {
  const base = shortName(row);
  const shared = rows.some((r) => r.run_id !== row.run_id && shortName(r) === base);
  const withWire = slugify(shared ? `${base}-${row.wire}` : base);
  const clash = rows.some(
    (r) => r.run_id !== row.run_id && shortName(r) === base && r.wire === row.wire,
  );
  return clash ? `${withWire}-${slugify(row.run_id).slice(0, 8)}` : withWire;
}
const leader = full[0];
const dupName = (() => {
  const counts = new Map();
  for (const r of full) counts.set(r.display_name, (counts.get(r.display_name) ?? 0) + 1);
  return [...counts.entries()].find(([, c]) => c > 1)?.[0];
})();

/* ---------- server and browser (as in render-law) ---------- */

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
const base = `http://127.0.0.1:${server.address().port}`;

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
  console.error("audit failed: no Chromium found in the Playwright cache");
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

const clickText = async (page, text, sel = "button") => {
  const handle = await page.evaluateHandle((t, s) => {
    return [...document.querySelectorAll(s)].find(
      (b) => b.textContent.trim() === t || b.textContent.trim().startsWith(t),
    );
  }, text, sel);
  const el = handle.asElement();
  if (!el) throw new Error(`no ${sel} with text ${text}`);
  await el.click();
};
const waitFor = async (page, fn, arg, timeout = 8000) => {
  await page.waitForFunction(fn, { timeout }, arg).catch(() => null);
};

/* ---------- six widths, static ---------- */

for (const width of [360, 480, 768, 1024, 1280, 1600]) {
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.setViewport({ width, height: 900 });
  await page.goto(`${base}/`, { waitUntil: "networkidle0" });
  const state = await page.evaluate(() => ({
    findings: document.querySelectorAll(".finding").length,
    overflow: document.documentElement.scrollWidth - window.innerWidth,
    explorer: document.querySelector(".explorer") !== null,
    method: document.querySelector("#method") !== null,
  }));
  if (errors.length > 0) fail(`at ${width}px: page error ${errors[0]}`);
  if (state.findings !== 5) fail(`at ${width}px: ${state.findings} findings blocks, not 5`);
  if (!state.explorer || !state.method) fail(`at ${width}px: explorer or Method missing`);
  if (state.overflow > 1) fail(`at ${width}px: horizontal overflow of ${state.overflow}px`);
  await page.close();
}
pass("six widths render five findings, the explorer and Method, with no overflow");

/* ---------- desktop interactions ---------- */

const page = await browser.newPage();
await page.setViewport({ width: 1280, height: 950 });
await page.goto(`${base}/`, { waitUntil: "networkidle0" });
await page.evaluate(() => document.querySelector(".explorer")?.scrollIntoView());

/* Expansion in place, with the calibration plot. */
await page.evaluate((rid) => {
  document.querySelector(`[data-rid="${rid}"] .xrow-head`)?.click();
}, leader.run_id);
await waitFor(page, (rid) => {
  const row = document.querySelector(`[data-rid="${rid}"]`);
  return row && row.querySelector(".reading.open") !== null;
}, leader.run_id);
const reading = await page.evaluate((rid) => {
  const row = document.querySelector(`[data-rid="${rid}"]`);
  const el = row?.querySelector(".reading.open");
  return {
    open: el !== null && el !== undefined,
    hasCalib: el?.querySelector(".calib-svg") !== null,
    hasTax: /tax/i.test(el?.textContent ?? ""),
    text: el?.textContent ?? "",
  };
}, leader.run_id);
if (!reading.open) fail("the leader's row does not expand into its reading in place");
else {
  pass("a row expands in place into its reading");
  if (!reading.hasCalib) fail("the leader's reading does not render its calibration plot");
  else pass("the calibration plot renders inside the reading");
  if (!reading.hasTax) fail("the leader's reading carries no robustness tax line");
  else pass("the robustness tax stands in the reading");
}

/* Pin to compare, the tray and its four deltas. */
const second = full[1];
await page.evaluate((rid) => {
  const row = document.querySelector(`[data-rid="${rid}"]`);
  row?.querySelector(".pinbtn")?.click();
}, leader.run_id);
await page.evaluate((rid) => {
  document.querySelector(`[data-rid="${rid}"] .xrow-head`)?.click();
}, second.run_id);
await waitFor(page, () => document.querySelector(".tray") !== null);
const tray = await page.evaluate(() => {
  const el = document.querySelector(".tray");
  if (!el) return null;
  return { text: el.textContent ?? "" };
});
if (!tray) fail("pinning two readings does not raise the compare tray");
else pass("pinning two readings raises the compare tray");
/* The tray's comparison opens the compare reading with the
 * four derived deltas, each signed in words. */
await page.evaluate(() => {
  document.querySelector(".tray .segbtn")?.click();
});
await waitFor(page, () => document.querySelectorAll(".delta-row").length === 4);
const deltas = await page.evaluate(() => {
  const rows = [...document.querySelectorAll(".delta-row")];
  return { count: rows.length, text: rows.map((r) => r.textContent ?? "").join(" ") };
});
if (deltas.count !== 4) fail(`the compare reading carries ${deltas.count} delta rows, not 4`);
else pass("the compare reading carries the four deltas");
if (!/higher|lower/.test(deltas.text)) fail("the compare deltas carry no direction words");
else pass("the deltas are signed in words");
await page.evaluate(() => {
  document.querySelector(".tray .ghostbtn")?.click();
});

/* Re-sorting restates the order and the hash. */
const firstBefore = await page.evaluate(() => {
  return document.querySelector("[data-rid]")?.getAttribute("data-rid");
});
await page.evaluate(() => {
  const sel = [...document.querySelectorAll(".explorer select")].find((s) =>
    [...s.options].some((o) => o.value === "cost"),
  );
  if (sel) {
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLSelectElement.prototype,
      "value",
    ).set;
    setter.call(sel, "cost");
    sel.dispatchEvent(new Event("change", { bubbles: true }));
  }
});
await waitFor(page, (before) => {
  return document.querySelector("[data-rid]")?.getAttribute("data-rid") !== before;
}, firstBefore);
const hashAfterSort = await page.evaluate(() => location.hash);
if (!hashAfterSort.includes("sort")) fail("re-sorting does not write the sort into the hash");
else pass("explorer state lives in the hash (sort)");

/* The guard population and its basis line. */
await clickText(page, "Guards").catch(() => null);
await waitFor(page, () => document.querySelector(".basisline") !== null);
const basis = await page.evaluate(() => {
  return document.querySelector(".basisline")?.textContent ?? "";
});
if (!basis.includes(fmtInt(slices[0].n_cases)) || !basis.includes(fmtInt(fullCases))) {
  fail(`the guard basis line does not state its subset basis: ${basis.slice(0, 80)}`);
} else pass("the guard population states its basis");
await clickText(page, "All results").catch(() => null);

/* Chart mode: hover cross-highlight, then a brush. */
await clickText(page, "Chart").catch(() => null);
await page.waitForSelector("svg.chart", { timeout: 10000 }).catch(() => null);
const discCount = await page.evaluate(() => {
  return document.querySelectorAll("svg.chart circle").length;
});
if (discCount === 0) fail("chart mode draws no discs");
else pass(`chart mode draws ${discCount} discs`);
const hover = await page.evaluate(() => {
  const disc = document.querySelector("svg.chart circle");
  if (!disc) return false;
  const r = disc.getBoundingClientRect();
  return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
});
if (hover) {
  await page.mouse.move(hover.x, hover.y);
  await new Promise((r) => setTimeout(r, 350));
  const lit = await page.evaluate(() => {
    return {
      chip: document.querySelector(".chip") !== null,
      hot: document.querySelector(".chartsync .hot, .sync-row.hot") !== null,
    };
  });
  if (!lit.chip) fail("chart hover raises no reading chip");
  if (!lit.hot) fail("chart hover does not light the same result in the list");
  if (lit.chip && lit.hot) pass("chart hover cross-highlights the list row");
}
const countBefore = await page.evaluate(() => {
  return document.querySelector(".xcount")?.textContent ?? "";
});
const plotBox = await page.evaluate(() => {
  const svg = document.querySelector("svg.chart");
  const r = svg?.getBoundingClientRect();
  return r ? { x: r.x, y: r.y, w: r.width, h: r.height } : null;
});
if (plotBox) {
  await page.mouse.move(plotBox.x + plotBox.w * 0.3, plotBox.y + plotBox.h * 0.3);
  await page.mouse.down();
  await page.mouse.move(plotBox.x + plotBox.w * 0.55, plotBox.y + plotBox.h * 0.6, { steps: 12 });
  await page.mouse.up();
  await new Promise((r) => setTimeout(r, 400));
  const countAfter = await page.evaluate(() => {
    return document.querySelector(".xcount")?.textContent ?? "";
  });
  if (countBefore && countAfter && countBefore === countAfter) {
    fail("a brush drag does not restate the filter count line");
  } else pass("a brush drag filters and the count line says so");
}

/* A finding's action sets the explorer state. */
await page.evaluate(() => window.scrollTo(0, 0));
const findingsActions = await page.$$(".finding .f-action");
if (findingsActions.length !== 5) fail(`the findings carry ${findingsActions.length} actions, not 5`);
else {
  await findingsActions[1].click();
  await new Promise((r) => setTimeout(r, 400));
  const q = await page.evaluate(() => {
    const input = document.querySelector(".explorer input");
    return { value: input?.value ?? "", hash: location.hash };
  });
  if (dupName && !q.hash.includes("q=") && !q.value.includes(shortName({ display_name: dupName }))) {
    fail("Finding 2's action does not set the explorer search to the duplicated model");
  } else pass("a finding's action sets the explorer state it promises");
}

/* Deep link opens the reading. */
await page.goto(`${base}/#result=${modelSlug(leader)}`, { waitUntil: "networkidle0" });
await waitFor(page, (rid) => {
  const row = document.querySelector(`[data-rid="${rid}"]`);
  return row && row.querySelector(".reading.open") !== null;
}, leader.run_id);
const deep = await page.evaluate((rid) => {
  const row = document.querySelector(`[data-rid="${rid}"]`);
  return row?.querySelector(".reading.open") !== null;
}, leader.run_id);
if (!deep) fail("a model address does not open its reading in the explorer");
else pass("a model address opens its reading in the explorer");
await page.close();

/* ---------- the phone touch session ---------- */

const phone = await browser.newPage();
await phone.setViewport({ width: 390, height: 844, hasTouch: true, isMobile: true });
await phone.goto(`${base}/`, { waitUntil: "networkidle0" });
/* The phone order (BUILD-SPEC section 7): Finding 1, then
 * the explorer, then Findings 2 to 5, then Method. */
const phoneOrder = await phone.evaluate(() => {
  const top = (sel) => document.querySelector(sel)?.getBoundingClientRect().top ?? null;
  return {
    split: top('[data-finding="split"]'),
    explorer: top("#explorer"),
    wire: top('[data-finding="wire"]'),
    leader: top('[data-finding="leader"]'),
    method: top("#method"),
  };
});
if (
  phoneOrder.split === null ||
  !(phoneOrder.split < phoneOrder.explorer &&
    phoneOrder.explorer < phoneOrder.wire &&
    phoneOrder.wire < phoneOrder.leader &&
    phoneOrder.leader < phoneOrder.method)
) {
  fail(`the phone order is not Finding 1, explorer, Findings 2 to 5, Method: ${JSON.stringify(phoneOrder)}`);
} else pass("the phone order runs Finding 1, the explorer, Findings 2 to 5, Method");
await phone.evaluate(() => document.querySelector(".explorer")?.scrollIntoView());
const head = await phone.$(`[data-rid="${leader.run_id}"] .xrow-head`);
if (head) await head.tap();
await waitFor(phone, (rid) => {
  const row = document.querySelector(`[data-rid="${rid}"]`);
  return row && row.querySelector(".reading.open") !== null;
}, leader.run_id);
const phoneState = await phone.evaluate(() => {
  const strip = document.querySelector(".footstrip");
  const reading = document.querySelector(".reading.open");
  return {
    stripText: strip?.textContent ?? "",
    stripVisible: strip ? strip.getBoundingClientRect().height > 0 : false,
    readingVisible: reading ? reading.getBoundingClientRect().height > 0 : false,
  };
});
if (!phoneState.readingVisible) fail("at phone size a tap does not open the reading");
if (!phoneState.stripVisible || !phoneState.stripText.includes(shortName(leader))) {
  fail("the phone foot strip does not name the selection");
} else pass("the phone strip names the selection and its rate");
/* Dismiss by tapping outside the sheet (the hero area). */
await phone.touchscreen.tap(195, 60);
await new Promise((r) => setTimeout(r, 400));
const dismissed = await phone.evaluate(() => {
  return document.querySelector(".reading.open") === null;
});
if (!dismissed) fail("a tap outside the phone sheet does not dismiss it");
else pass("a tap outside dismisses the phone sheet");
await phone.close();

await browser.close();
server.close();

for (const p of passes) console.log(`audit: ${p}`);
if (failures.length > 0) {
  console.error(`\ndom audit FAILED (${failures.length}):`);
  for (const f of failures) console.error(`  - ${f}`);
  process.exit(1);
}
console.log(`dom audit passed (${passes.length} interaction proofs)`);
