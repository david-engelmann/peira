#!/usr/bin/env node
/**
 * DOM audit for the redesigned board. Where render-law checks
 * the static document, this audit drives the explorer the way
 * a reader does, at six widths and in a touch session at 390
 * by 844, and asserts the interaction contract of BUILD-SPEC
 * sections 4 to 7.
 *
 *   a row expands in place into its reading, with the
 *     calibration plot rendered for a result that carries one
 *   pinning two readings raises the compare tray, whose
 *     comparison carries the five derived deltas
 *   sorting and the population filter restate the view, the
 *     guard population with its basis line
 *   chart hover lights the same result in the list beside
 *     the chart, and a brush drag filters the view and says
 *     so in the count line
 *   a model address (/#result=<slug>) opens that reading
 *   model filters intersect, keep standing ranks, and remove hidden readings
 *   a finding's action sets the explorer state it promises
 *   finding actions followed in sequence each land where
 *     they promise, with unnamed state back at its default
 *   the rank header's labels stand over their columns
 *   families mode sorts by a family from the Sort by control, and
 *     carries exactly one reading for an expanded row
 *   rankings re-sort with a FLIP transition and honor reduced motion
 *   at phone size the reading opens as a sheet over a sticky
 *     strip that names the selection and has a close control
 *
 * Run after next build, standalone.
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
/* Settle wait for input dispatch (owner-authorized harness fix,
 * 2026-11-06). The page glides under the global smooth scroll,
 * so a target measured before a click or a tap can sit one row
 * off by dispatch time; looped evidence runs showed the app
 * state never wrong, only the harness input landing mid-glide.
 * Poll the target's full bounding box until it holds still
 * across two samples, then let the caller dispatch. This is
 * the audit's one settle mechanism. No assertion changes;
 * only the timing of the input does. */
const settleOn = async (handle, tries = 80) => {
  let prev = null;
  for (let i = 0; i < tries; i += 1) {
    const box = await handle.boundingBox().catch(() => null);
    if (
      box &&
      prev &&
      Math.abs(box.x - prev.x) < 1 &&
      Math.abs(box.y - prev.y) < 1 &&
      Math.abs(box.width - prev.width) < 1 &&
      Math.abs(box.height - prev.height) < 1
    ) {
      return;
    }
    prev = box;
    await new Promise((r) => setTimeout(r, 75));
  }
};
/* ---------- six widths, static ---------- */

for (const width of [360, 480, 768, 1024, 1280, 1600]) {
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.setViewport({ width, height: 900 });
  await page.goto(`${base}/`, { waitUntil: "networkidle0" });
  const state = await page.evaluate(() => ({
    findings: document.querySelectorAll("#findings a[href^='#explorer?']").length,
    overflow: document.documentElement.scrollWidth - window.innerWidth,
    explorer: document.querySelector(".explorer") !== null,
    method: document.querySelector("#method") !== null,
  }));
  if (errors.length > 0) fail(`at ${width}px: page error ${errors[0]}`);
  if (state.findings !== 2) fail(`at ${width}px: ${state.findings} analysis links, expected 2`);
  if (!state.explorer || !state.method) fail(`at ${width}px: explorer or Method missing`);
  if (state.overflow > 1) fail(`at ${width}px: horizontal overflow of ${state.overflow}px`);
  await page.close();
}
pass("six widths render both analyses, the explorer and Method, with no overflow");

/* Inspecting the field with a keyboard must update the same record link as the step controls. */
const overview = await browser.newPage();
await overview.emulateMediaFeatures([{ name: "prefers-reduced-motion", value: "reduce" }]);
await overview.goto(base, { waitUntil: "networkidle0" });
const bars = await overview.$$(".distribution-bar");
const overviewMeta = await overview.evaluate(() => {
  const edition = document.querySelector(".plate-dateline time");
  const marks = [...document.querySelectorAll(".field-plate ol .xmark")];
  return {
    day: edition?.dateTime,
    label: edition?.textContent,
    marksResolved: marks.every(mark => {
      const symbol = mark.querySelector("use")?.getAttribute("href");
      return symbol ? !!document.getElementById(symbol.slice(1)) : !!mark.textContent.trim();
    }),
    count: marks.length,
    repo: document.querySelector('.study-footer a[href*="github.com"]')?.href,
  };
});
const newest = rows.map(row => row.created_utc).sort().at(-1).slice(0, 10);
if (overviewMeta.day !== newest || !overviewMeta.label?.includes("Latest run")) fail("overview date must identify the latest run");
if (overviewMeta.repo !== "https://github.com/david-engelmann/peira") fail("the footer must link to Peira's repository");
const rankedRates = full.filter(row => row.asr_conditional !== null);
if (!overviewMeta.marksResolved || overviewMeta.count !== Math.min(3, rankedRates.length)) fail("featured models must show their provider marks");
else pass("featured provider marks resolve, and the overview identifies its latest run and repository");
if (bars.length !== rankedRates.length) fail("the interactive field omits a ranked rate");
if (bars.length > 1) {
  await bars[0].focus();
  await overview.keyboard.press("End");
  const href = await overview.$eval(".distribution-link", el => el.getAttribute("href"));
  if (href !== `#result=${modelSlug(rankedRates.at(-1))}`) fail("the last bar opens the wrong result");
  await overview.click('.distribution-actions button[aria-label="Next result"]');
  const first = await overview.$eval(".distribution-link", el => el.getAttribute("href"));
  if (first !== `#result=${modelSlug(rankedRates[0])}`) fail("stepping past the last bar opens the wrong result");
  if (await overview.$eval(".field-plane svg", el => getComputedStyle(el).animationName) !== "none") {
    fail("the cover animates under reduced motion");
  }
  if (href === `#result=${modelSlug(rankedRates.at(-1))}` && first === `#result=${modelSlug(rankedRates[0])}`) {
    pass("keyboard and step controls link the inspected field result to its record");
  }
}
const costMarks = await overview.$$eval(".study-scatter-point", (points) => points.map(point => {
  const badge = point.querySelector(".study-scatter-badge");
  const use = badge?.querySelector("use");
  const symbol = use?.getAttribute("href");
  return Boolean(symbol
    ? document.getElementById(symbol.slice(1)) && use.getBBox().width > 0
    : badge?.querySelector(".xmark-letter")?.textContent.trim());
}));
if (!costMarks.length || costMarks.some(mark => !mark)) fail("every cost point must display its provider mark");
else pass("the cost points display their shared provider marks");
await overview.select(".study-scatter-coverage select", "complete");
await overview.click(".study-scatter-controls button");
const costRows = await overview.$$eval(".study-cost-data tbody tr", entries =>
  entries.map(entry => entry.querySelector("td").textContent));
if (!costRows.length || costRows.some(cell => !cell.includes("Fully priced") || parseFloat(cell.slice(1)) >= 1)) {
  fail("the price zoom and coverage filter must restrict the visible data table");
}
await overview.click(".study-scatter-toggle input");
if (await overview.$(".study-scatter-whisker")) fail("the interval control must hide the whiskers");
await overview.focus('.study-scatter-point[tabindex="0"]');
await overview.keyboard.press("End");
const lastCostSlug = await overview.$eval(".study-cost-data tbody tr:last-child a", link => link.pathname.split("/")[2]);
if (await overview.$eval(".study-scatter-readout a", link => link.hash) !== `#result=${lastCostSlug}`) {
  fail("keyboard inspection must open the highest-cost visible run");
} else pass("the study cost plot filters, zooms, toggles intervals and opens the inspected result");
await overview.goto(base + "/#explorer?pop=full&mode=chart", { waitUntil: "networkidle0" });
await clickText(overview, "Benign accuracy", ".chart-presets button");
await overview.waitForFunction(() => new URLSearchParams(location.hash.split("?")[1]).get("axis") === "benign");
await overview.reload({waitUntil: "networkidle0"});
const preset = await overview.$eval('.chart-presets [aria-pressed="true"]', button => button.textContent);
if (preset !== "Benign accuracy") fail("the accuracy axis must survive a shared-link reload");
else pass("the accuracy plot can be selected and restored from its URL");
await overview.close();

/* The chart and its linked selections must agree on their population and median. */
const cohortPage = await browser.newPage();
await cohortPage.emulateMediaFeatures([{ name: "prefers-reduced-motion", value: "reduce" }]);
await cohortPage.goto(base + "/#explorer?pop=full&mode=rank&kind=general", { waitUntil: "networkidle0" });
const initialExplorerTop = await cohortPage.$eval("#explorer", el => el.getBoundingClientRect().top);
const explorerFocused = await cohortPage.evaluate(() => document.activeElement?.id === "explorer");
if (!explorerFocused || initialExplorerTop < 0 || initialExplorerTop > 150) fail("a shared Explorer view opened outside the viewport");
else pass("a fresh filtered link lands at the Explorer");

const fullRates = new Map(full.filter(r => r.asr_conditional != null).map(r => [r.run_id, r.asr_conditional]));
for (const dimension of ["kind", "interface", "serving", "weights", "tier"]) {
  await cohortPage.select("#model-groups select", dimension);
  const chartRows = await cohortPage.$$eval(".group-row", elements => elements.map(el => ({
    link: el.querySelector("a").getAttribute("href"),
    ticks: el.querySelectorAll(".group-track i").length,
    median: parseFloat(el.querySelector(".group-median").textContent),
  })));
  const seen = new Set();
  for (const { link, ticks, median } of chartRows) {
    await cohortPage.$eval(`.group-name a[href="${link}"]`, anchor => anchor.click());
    await cohortPage.waitForFunction(n => document.querySelectorAll(".xlist [data-rid]").length === n, {}, ticks);
    const ids = await cohortPage.$$eval(".xlist [data-rid]", els => els.map(el => el.dataset.rid));
    const rates = ids.map(id => fullRates.get(id)).sort((a, b) => a - b);
    if (rates.some(rate => rate == null) || ids.some(id => seen.has(id))) fail(`Unexpected cohort membership for ${link}`);
    ids.forEach(id => seen.add(id));
    const middle = (rates[Math.floor((rates.length - 1) / 2)] + rates[Math.floor(rates.length / 2)]) / 2;
    if (!Number.isFinite(median) || !Number.isFinite(middle) || Math.abs(100 * middle - median) > 0.05001) fail(`Incorrect median for ${link}`);
  }
  if (seen.size !== fullRates.size) fail(`Incomplete full-suite coverage for ${dimension}`);
}
await cohortPage.close();
pass("all five group comparisons link to the full-suite results used in each median");

/* ---------- desktop interactions ---------- */

const page = await browser.newPage();
await page.setViewport({ width: 1280, height: 950 });
await page.goto(`${base}/`, { waitUntil: "networkidle0" });
await page.evaluate(() => document.querySelector(".explorer")?.scrollIntoView({ behavior: "instant" }));

const rankedDefault = await page.evaluate(() => ({
  pop: document.querySelector("#explorer-pop")?.value,
  chart: Boolean(document.querySelector("svg.chart")),
  flagged: document.querySelectorAll(".disc.flagged, .sync-row .xstate").length,
  offScale: document.querySelectorAll(".offscale-note p").length,
  count: document.querySelector(".xcount")?.textContent ?? "",
}));
if (rankedDefault.pop !== "full" || !rankedDefault.chart || rankedDefault.flagged ||
    !rankedDefault.count.includes(`${full.length} of ${full.length} results`)) {
  fail(`the Explorer does not open with the full-suite chart: ${JSON.stringify(rankedDefault)}`);
} else pass("the Explorer opens with the full-suite chart");

const pricedFull = full.filter(r => r.total_cost_usd > 0);
if (pricedFull.length && rankedDefault.offScale !== 0) {
  fail("the opening chart labels a result outside the priced full-suite axis");
}

const setMode = async (targetPage, label) => {
  await targetPage.evaluate((text) => {
    [...document.querySelectorAll(".explorer-views button")]
      .find((button) => button.textContent.trim() === text)?.click();
  }, label);
  await waitFor(targetPage, (text) =>
    document.querySelector('.explorer-views button[aria-pressed="true"]')?.textContent.trim() === text, label);
};
const setPopulation = (targetPage, pop) => targetPage.select("#explorer-pop", pop);

const chartReadingOpener = await page.$(".sync-row.sel");
await chartReadingOpener.focus();
await page.keyboard.press("Enter");
await waitFor(page, () => document.activeElement?.classList.contains("belowreading"));
if (!(await page.evaluate(() => document.activeElement?.classList.contains("belowreading")))) {
  fail("keyboard activation did not focus the chart reading");
}
await page.focus(".chart-reading-head button");
await page.keyboard.press("Enter");
await waitFor(page, () => !document.querySelector(".belowreading"));
if (!(await chartReadingOpener.evaluate(el => document.activeElement === el))) {
  fail("closing the chart reading did not restore the opener's focus");
} else pass("keyboard opening and closing chart details returns focus to the result");

await setMode(page, "Rankings");

/* The rank header's labels stand over their columns. Each
 * figure label's center is compared with the center of the
 * same figure cell in the first row, so a header missing a
 * track throws every label one column off and fails here. */
{
  const aligned = await page.evaluate(() => {
    const heads = [...document.querySelectorAll(".xhead .xh.fig")];
    const cells = [...document.querySelectorAll(".xrow .xfig")];
    if (heads.length === 0 || cells.length < heads.length) return null;
    return heads.map((h, i) => {
      const hr = h.getBoundingClientRect();
      const cr = cells[i].getBoundingClientRect();
      return Math.abs(hr.x + hr.width / 2 - (cr.x + cr.width / 2));
    });
  });
  if (aligned === null) {
    fail("the rank header or the first row is missing, so header alignment has no evidence");
  } else if (aligned.some((d) => d > 2)) {
    fail(`the rank header's labels sit off their columns by ${aligned.map((d) => Math.round(d)).join(", ")}px`);
  } else pass("the rank header's labels stand over their columns");
}

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
    hasCalib: Boolean(el?.querySelector(".calstrip")),
    hasTax: /tax/i.test(el?.textContent ?? ""),
    text: el?.textContent ?? "",
  };
}, leader.run_id);
if (!reading.open) fail("the leader's row does not expand into its reading in place");
else {
  pass("a row expands in place into its reading");
  if (!reading.hasCalib) fail("the leader's reading does not render its calibration plot");
  else pass("the calibration plot renders inside the reading");
  if (reading.hasTax !== (leader.robustness_tax != null)) {
    fail("the leader's reading disagrees with the payload on whether robustness tax was measured");
  }
}

const taxRow = full.find((r) => r.run_id !== leader.run_id && r.robustness_tax != null);
if (taxRow) {
  await page.evaluate((rid) => {
    document.querySelector(`[data-rid="${rid}"] .xrow-head`)?.click();
  }, taxRow.run_id);
  await waitFor(page, () => /robustness tax/i.test(document.querySelector(".reading.open")?.textContent ?? ""));
  const measured = await page.evaluate(() => /robustness tax/i.test(document.querySelector(".reading.open")?.textContent ?? ""));
  if (!measured) fail("the reading omits a measured robustness tax");
  else pass("the reading prints robustness tax when measured");
}

/* Pin to compare and open the five-metric comparison. */
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
await page.evaluate(() => {
  document.querySelector(".tray .segbtn")?.click();
});
await waitFor(page, () => document.querySelectorAll(".delta-row").length === 5);
const deltas = await page.evaluate(() => {
  const rows = [...document.querySelectorAll(".delta-row")];
  return { count: rows.length, text: rows.map((r) => r.textContent ?? "").join(" ") };
});
if (deltas.count !== 5) fail(`the compare reading carries ${deltas.count} delta rows, expected five`);
else pass("the compare reading carries five metrics");
if (!/[-−+]\d/.test(deltas.text)) fail("the compare deltas carry no signed figures");
else pass("the compare deltas show signed differences");
await page.evaluate(() => {
  document.querySelector(".tray .ghostbtn")?.click();
});

/* Re-sorting restates the order and the hash. */
const firstBefore = await page.evaluate(() => {
  return document.querySelector("[data-rid]")?.getAttribute("data-rid");
});
await page.select("#explorer-sort", "cost");
await waitFor(page, (before) => {
  return document.querySelector("[data-rid]")?.getAttribute("data-rid") !== before;
}, firstBefore);
const hashAfterSort = await page.evaluate(() => location.hash);
if (!hashAfterSort.includes("sort")) fail("re-sorting does not write the sort into the hash");
else pass("explorer state lives in the hash (sort)");
if (await page.$eval("[data-rid]", (el) => el.dataset.rid) === firstBefore) {
  fail("re-sorting did not change the first ranked result");
}

/* The guard population and its basis line. */
await setPopulation(page, "guards");
await waitFor(page, () => document.querySelector(".basisline") !== null);
const basis = await page.evaluate(() => {
  return document.querySelector(".basisline")?.textContent ?? "";
});
if (!basis.includes(fmtInt(slices[0].n_cases)) || !basis.includes("separate ranking")) {
  fail(`the guard basis line does not state its subset basis: ${basis.slice(0, 80)}`);
} else pass("the guard population states its basis");
await setPopulation(page, "full");

/* Chart mode: hover cross-highlight, then a brush. */
await setMode(page, "Chart");
await page.waitForSelector("svg.chart", { timeout: 10000 }).catch(() => null);
const chartEl = await page.$("svg.chart");
if (chartEl) {
  await chartEl.evaluate((svg) => svg.scrollIntoView({ behavior: "instant", block: "center" }));
  await waitFor(page, () => {
    const bounds = document.querySelector("svg.chart")?.getBoundingClientRect();
    return bounds && bounds.top > 80 && bounds.bottom < window.innerHeight;
  });
}
const discCount = await page.evaluate(() => {
  return document.querySelectorAll("svg.chart circle").length;
});
if (discCount === 0) fail("chart mode draws no discs");
else pass(`chart mode draws ${discCount} discs`);
await page.mouse.move(0, 0);
if (chartEl) await settleOn(chartEl);
const hover = await page.evaluate(() => {
  for (const disc of document.querySelectorAll("svg.chart .disc-face")) {
    const r = disc.getBoundingClientRect();
    const x = r.x + r.width / 2;
    const y = r.y + r.height / 2;
    if (document.elementFromPoint(x, y) === disc) return { x, y, id: disc.closest("[data-disc]").dataset.disc };
  }
  return null;
});
if (hover) {
  await page.mouse.move(hover.x, hover.y);
  await waitFor(page, () => document.querySelector(".chip") && document.querySelector(".chartsync .hot"));
  const lit = await page.evaluate(() => {
    return {
      chip: document.querySelector(".chip") !== null,
      hot: document.querySelector(".chartsync .hot, .sync-row.hot") !== null,
    };
  });
  if (!lit.chip) fail(`chart hover on ${hover.id} raises no reading chip`);
  if (!lit.hot) fail(`chart hover on ${hover.id} does not light the result in the list`);
  if (lit.chip && lit.hot) pass("chart hover cross-highlights the list row");
} else {
  fail("the chart exposes no visible disc center to hover");
}
/* The brush proof asserts numbers, not a text change. The
 * expected count is recomputed from the payload through the
 * chart's own geometry (the half decade cost domain, the
 * shared axis rule, the plot pads), read off the built svg's
 * viewBox, and the count line must land on it within a small
 * boundary tolerance for rows sitting on the drag's edge. */
const parseShowing = (t) => {
  const m = /([\d,]+) of ([\d,]+) results/.exec(t ?? "");
  return m ? Number(m[1].replace(/,/g, "")) : null;
};
const countBefore = await page.evaluate(() => {
  return document.querySelector(".xcount")?.textContent ?? "";
});
const showingBefore = parseShowing(countBefore);
if (showingBefore === null) {
  fail("the count line is missing or unparseable before the brush");
}
const plotBox = await page.evaluate(() => {
  const svg = document.querySelector("svg.chart");
  const r = svg?.getBoundingClientRect();
  const vb = svg?.viewBox?.baseVal;
  return r && vb ? { x: r.x, y: r.y, w: r.width, h: r.height, W: vb.width, H: vb.height } : null;
});
if (!plotBox) {
  fail("the brush proof has no chart to drag on");
} else if (showingBefore !== null) {
  const { W, H } = plotBox;
  const padL = 44, padR = 30, padT = 18, padB = 40;
  const chartedRows = full;
  const costs = chartedRows
    .map((r) => r.total_cost_usd)
    .filter((c) => typeof c === "number" && c > 0);
  const lo = Math.pow(10, Math.floor(Math.log10(Math.min(...costs)) * 2) / 2);
  const hi = Math.max(lo * Math.sqrt(10), Math.pow(10, Math.ceil(Math.log10(Math.max(...costs)) * 2) / 2));
  const worstRanked = Math.max(...full.filter((r) => r.total_cost_usd > 0).map((r) => r.asr_conditional ?? 0));
  const axisMax = Math.max(0.1, Math.round(Math.ceil((worstRanked - 1e-9) / 0.05) * 5) / 100);
  const invX = (px) =>
    Math.pow(10, Math.log10(lo) + ((px - padL) / (W - padL - padR)) * (Math.log10(hi) - Math.log10(lo)));
  const invY = (px) => ((padT + (H - padT - padB) - px) / (H - padT - padB)) * axisMax;
  const rectFor = (fx0, fy0, fx1, fy1) => ({
    costLo: invX(fx0 * W),
    costHi: invX(fx1 * W),
    vLo: Math.max(0, invY(fy1 * H)),
    vHi: invY(fy0 * H),
  });
  const countIn = (rect) =>
    chartedRows.filter((r) => {
      const c = r.total_cost_usd;
      const v = r.asr_conditional;
      if (typeof c !== "number" || !(c > 0) || typeof v !== "number") return false;
      return c >= rect.costLo && c <= rect.costHi && v >= rect.vLo && v <= rect.vHi;
    }).length;
  const rect = rectFor(0.3, 0.3, 0.55, 0.6);
  const expected = countIn(rect);
  const expectedLo = countIn(rectFor(0.31, 0.31, 0.54, 0.59));
  const expectedHi = countIn(rectFor(0.29, 0.29, 0.56, 0.61));
  const extreme = chartedRows
    .filter((r) => typeof r.asr_conditional === "number")
    .sort((a, b) => b.asr_conditional - a.asr_conditional)[0];
  await page.mouse.move(plotBox.x + plotBox.w * 0.3, plotBox.y + plotBox.h * 0.3);
  await page.mouse.down();
  await page.mouse.move(plotBox.x + plotBox.w * 0.55, plotBox.y + plotBox.h * 0.6, { steps: 12 });
  await page.mouse.up();
  await new Promise((r) => setTimeout(r, 400));
  const after = await page.evaluate(() => {
    return {
      count: document.querySelector(".xcount")?.textContent ?? "",
      sync: document.querySelectorAll(".sync-row").length,
      syncNames: [...document.querySelectorAll(".sync-row .sync-name")].map((el) =>
        el.textContent.trim(),
      ),
    };
  });
  const showingAfter = parseShowing(after.count);
  if (showingAfter === null) {
    fail("the count line is missing or unparseable after the brush");
  } else if (showingAfter >= showingBefore) {
    fail(`a brush drag does not drop the filtered count (${showingBefore} to ${showingAfter})`);
  } else if (!after.count.includes("area selected")) {
    fail("the count line does not identify the area selection");
  } else if (showingAfter !== after.sync) {
    fail(`the count line says ${showingAfter} but the chart list carries ${after.sync} rows`);
  } else if (showingAfter < expectedLo || showingAfter > expectedHi) {
    fail(
      `the brush keeps ${showingAfter} results, the payload puts ${expected} in the dragged region (tolerance ${expectedLo} to ${expectedHi})`,
    );
  } else if (extreme && extreme.asr_conditional > rect.vHi &&
    after.syncNames.some((n) => n.startsWith(shortName(extreme)))) {
    fail("the brush leaves the highest rate result in the list though it sits above the dragged region");
  } else pass("a brush drag filters to the dragged region and the count line states it");
}

/* Recompute family sort order from the payload and verify the rendered full suite. */
await clickText(page, "Clear area selection").catch(() => null);
await waitFor(page, (total) => {
  const t = document.querySelector(".xcount")?.textContent ?? "";
  const m = /([\d,]+) of/.exec(t);
  return m !== null && Number(m[1].replace(/,/g, "")) === total;
}, full.length);
if (chartEl) {
  await chartEl.evaluate(svg => svg.scrollIntoView({ behavior: "instant", block: "center" }));
  const bounds = await chartEl.boundingBox();
  const beforeResize = await chartEl.evaluate(svg => svg.viewBox.baseVal.width);
  await page.mouse.move(bounds.x + 0.3 * bounds.width, bounds.y + 0.3 * bounds.height);
  await page.mouse.down();
  await page.mouse.move(bounds.x + 0.55 * bounds.width, bounds.y + 0.6 * bounds.height);
  await page.waitForSelector(".brush-rect");
  await page.setViewport({ width: 1024, height: 950 });
  await page.waitForFunction(width => document.querySelector("svg.chart")?.viewBox.baseVal.width !== width, {}, beforeResize);
  const dragCanceled = !await page.$(".brush-rect");
  await page.mouse.up();
  if (!dragCanceled || await page.$(".brush-clear")) {
    fail("resizing the chart during a drag left a stale brush or applied a filter");
  } else pass("resizing the chart cancels an in-progress area selection");
  await page.setViewport({ width: 1280, height: 950 });
}
await setMode(page, "Families");
await page.waitForSelector(".xfamrow", { timeout: 10000 }).catch(() => null);
const famGroupNames = async () => {
  return page.evaluate(() => {
    const group = document.querySelector(".xfamilies .xgroup");
    if (!group) return [];
    return [...group.querySelectorAll(".xfamrow")].map((el) => el.dataset.rid);
  });
};
const famKeys = [
  ...new Set(full.flatMap((r) => Object.keys(r.detail?.families ?? {}))),
];
const famRate = (r, key) => {
  const rec = r.detail?.families?.[key];
  if (!rec || typeof rec.asr !== "number") return null;
  const { n_flipped: hits, n_eligible: eligible } = rec;
  if (!Number.isInteger(hits) || !Number.isInteger(eligible) || eligible <= 0 || hits < 0 || hits > eligible) return rec.asr;
  const exact = hits / eligible;
  return Math.round(exact * 10000) === Math.round(rec.asr * 10000) ? exact : rec.asr;
};
const famExpected = (key) =>
  [...full]
    .sort((a, b) => {
      const ra = famRate(a, key);
      const rb = famRate(b, key);
      if (ra === null && rb === null) return 0;
      if (ra === null) return 1;
      if (rb === null) return -1;
      return ra - rb;
    })
    .map((r) => r.run_id);
const famBeforeNames = await famGroupNames();
const famPick = famKeys
  .map((key) => ({ key, expected: famExpected(key) }))
  .find(
    ({ expected }) =>
      expected.length === famBeforeNames.length &&
      expected[0] !== famBeforeNames[0],
  );
if (!famPick) {
  fail("no family in the payload reorders the full suite group, so the families proof cannot run");
} else {
  const selected = await page.select("#explorer-sort", `fam:${famPick.key}`);
  if (selected.length === 0) {
    fail(`the Sort by control does not offer ${famPick.key}`);
  } else {
    await waitFor(page, (want) => {
      const group = document.querySelector(".xfamilies .xgroup");
      const first = group?.querySelector(".xfamrow")?.dataset.rid;
      return first === want;
    }, famPick.expected[0]);
    const famAfterNames = await famGroupNames();
    const famHash = await page.evaluate(() => location.hash);
    if (famAfterNames.join("|") !== famPick.expected.join("|")) {
      fail(
        `families mode sorted by ${famPick.key} lands on ${famAfterNames.slice(0, 3).join(", ")}, the payload order is ${famPick.expected.slice(0, 3).join(", ")}`,
      );
    } else if (!famHash.includes("sort=fam")) {
      fail("the family sort does not write itself into the hash");
    } else pass("families mode sorts by a family from the Sort by control");
  }
}

/* Families mode carries exactly one reading for an expanded
 * row, the copy inside its own row and no second copy in the
 * block below the view. */
await page.evaluate(() => {
  document.querySelector(".xfamrow .xfam-head")?.click();
});
await waitFor(page, () => document.querySelector(".xfamilies .reading.open") !== null);
{
  const copies = await page.evaluate(() => ({
    inline: document.querySelectorAll(".xfamilies .reading").length,
    below: document.querySelectorAll(".belowreading").length,
  }));
  if (copies.inline !== 1) {
    fail(`families mode carries ${copies.inline} readings for the expanded row, not 1`);
  } else if (copies.below !== 0) {
    fail("families mode renders the expanded reading again below the view");
  } else pass("families mode carries exactly one reading for an expanded row");
}

/* Follow each analysis into the relevant full-suite view, then switch back. */
for (const mode of ["families", "chart", "families"]) {
  const link = await page.$(`#findings a[href*="mode=${mode}"]`);
  if (!link) {
    fail(`missing analysis link for ${mode}`);
    continue;
  }
  await settleOn(link);
  await link.click();
  const selector = mode === "chart" ? "svg.chart .disc" : ".xfamrow.full";
  if (!await page.waitForSelector(selector, { timeout: 5000 }).catch(() => null)) {
    fail(`analysis link did not display ${mode} results`);
  } else pass(`analysis opened ${mode} results`);
}

/* Static model addresses and previously shared Explorer hashes. */
for (const [row, pop] of [[leader, "full"], [slices[0], "guards"], [payload.unranked[0], "flagged"]]) {
  const slug = modelSlug(row);
  await page.goto(`${base}/models/${slug}/`, { waitUntil: "networkidle0" });
  await waitFor(page, () => document.querySelector(".reading.open") !== null);
  const deep = await page.evaluate((name) => ({
    pop: document.querySelector("#explorer-pop")?.value,
    open: Boolean(document.querySelector(".reading.open")),
    named: document.querySelector(".belowreading")?.textContent.includes(name)
      || document.querySelector(".xrow.open .xname")?.textContent.includes(name),
  }), shortName(row));
  if (deep.pop !== pop || !deep.open || !deep.named) {
    fail(`model address ${slug} did not open its reading in the ${pop} results`);
  } else pass(`model address ${slug} opens its reading in the ${pop} results`);
  if (pop === "full") {
    await page.focus(".chart-reading-head button");
    await page.keyboard.press("Enter");
    await waitFor(page, () => document.activeElement?.matches(".sync-row.sel"));
    if (!(await page.evaluate(() => document.activeElement?.matches(".sync-row.sel")))) {
      fail("closing a permalink's chart reading did not focus the selected result");
    } else pass("a chart reading opened from a permalink returns focus to the selected result");
  }
}
await page.goto(`${base}/#explorer?mode=rank`, { waitUntil: "networkidle0" });
await waitFor(page, () => document.querySelector("#explorer-pop")?.value === "all");
const legacyCount = await page.$$eval(".xrow", (results) => results.length);
if (legacyCount !== rows.length) fail("a legacy Explorer link lost the original All results scope");
else pass("a legacy Explorer link keeps the original All results scope");
const vendorSelect = '#explorer select:has(option[value="google"])';
await page.goto(`${base}/#explorer?pop=full&vendor=google`, { waitUntil: "networkidle0" });
await page.waitForSelector(".sync-row.sel");
if (!(await page.$eval(".sync-row.sel", el => el.textContent.includes("gemini-4-argon")))) {
  fail("a legacy Explorer link without sel did not select the default opener");
}
await page.select(vendorSelect, "all");
const alternate = await page.$eval(".sync-row:not(.sel)", el => {
  el.click();
  return el.textContent;
});
await page.select(vendorSelect, "google");
await waitFor(page, () => new URLSearchParams(location.hash.split("?")[1]).get("sel") === "");
await page.reload({ waitUntil: "networkidle0" });
const restored = await page.evaluate(() => {
  const params = new URLSearchParams(location.hash.split("?")[1]);
  return params.get("vendor") === "google" && params.get("sel") === "" &&
    Boolean(document.querySelector(".sync-row")) && !document.querySelector(".sync-row.sel, .belowreading");
});
if (!restored) fail(`reloading a filter that excluded ${alternate} restored a selection`);
else pass("an explicitly cleared chart selection survives a reload with the default opener visible");

/* Model profile filters preserve the board's ranks and combine in every view. */
const openFrontierRuns = full.filter((r) =>
  ["kimi-k3", "deepseek-flash", "MiniMax-M3"].includes(r.adapter_version),
);
const selectedFrontier = openFrontierRuns[0];
const profileHash = new URLSearchParams({
  pop: "full", mode: "rank", kind: "general", interface: "structured", serving: "hosted", weights: "open",
  tier: "frontier", frontier: "1", sel: modelSlug(selectedFrontier), pin: modelSlug(leader), open: "1",
});
await page.goto(`${base}/#explorer?${profileHash}`, { waitUntil: "networkidle0" });
await waitFor(page, () => document.querySelector(".reading-profile") !== null);
const filteredRankings = await page.evaluate(() => ({
  ranks: [...document.querySelectorAll(".xrow")].map((row) => [
    row.dataset.rid, Number(row.querySelector(".xrank")?.textContent),
  ]),
  profile: document.querySelector(".reading-profile")?.textContent ?? "",
  tray: Boolean(document.querySelector(".tray")),
  controls: document.querySelector(".model-filters summary")?.textContent ?? "",
}));
const expectedRanks = openFrontierRuns.map((r) => [r.run_id, r.rank]);
const expectedProfileLabels = ["General-purpose", "Structured generation", "Hosted inference", "Documented open weights", "Frontier baselines"];
if (JSON.stringify(filteredRankings.ranks) !== JSON.stringify(expectedRanks) ||
    !expectedProfileLabels.every((label) => filteredRankings.controls.includes(label))) {
  fail(`the combined model filters changed ranks or returned unexpected rows: ${JSON.stringify(filteredRankings)}`);
} else pass("combined model filter links preserve the full-suite ranks");
if (filteredRankings.tray ||
    !expectedProfileLabels.every((label) => filteredRankings.profile.includes(label))) {
  fail("a filtered reading omitted its model profile or included a hidden pin");
} else pass("a filtered reading shows its profile and omits the hidden pin");

await setMode(page, "Chart");
const chartProfile = await page.evaluate(() => ({
  results: document.querySelectorAll(".sync-row").length,
  costFrontier: [...document.querySelectorAll(".xcheck")]
    .find((label) => label.textContent.trim() === "Cost frontier")?.querySelector("input")?.checked,
}));
if (chartProfile.results !== expectedRanks.length || !chartProfile.costFrontier) {
  fail("the model cohort and the cost frontier overlay do not work independently");
} else pass("the model cohort and cost frontier overlay coexist on the chart");
await page.$eval(".model-filters summary", (el) => el.click());
await page.select("#explorer-serving", "local");
await waitFor(page, () => location.hash.includes("serving=local"));
const hiddenSelection = await page.evaluate(() => {
  const params = new URLSearchParams(location.hash.split("?")[1]);
  return params.get("serving") === "local" && params.get("sel") === "" && !params.has("pin") && !params.has("open") &&
    !document.querySelector(".belowreading, .tray, .footstrip-name");
});
if (!hiddenSelection) fail("filters retain a hidden selected reading or pin in the view or URL");
else pass("an incompatible model filter clears the hidden reading and its link state");
await setMode(page, "Families");
if (!await page.$(".xfamilies .xempty")) {
  fail("the family view does not explain an empty filter intersection");
}
await page.$eval(".model-filters button", (el) => el.click());
await setMode(page, "Rankings");
const cleared = await page.evaluate(() => ({
  results: document.querySelectorAll(".xrow").length,
  reading: Boolean(document.querySelector(".reading.open")),
  filterKeys: [...new URLSearchParams(location.hash.split("?")[1]).keys()]
    .filter((key) => ["kind", "interface", "serving", "weights", "tier"].includes(key)),
}));
if (cleared.results !== full.length || cleared.reading || cleared.filterKeys.length !== 0) {
  fail("clearing the model filters did not restore the full suite without reopening a stale reading");
} else pass("clearing model filters restores the full suite without a stale reading");

const luna = (adapter) => full.find((row) => row.adapter_name === adapter && row.adapter_version === "gpt-6-luna");
const lunaCompare = new URLSearchParams({
  pop: "full", mode: "rank", kind: "general", open: "1",
  sel: modelSlug(luna("openai-decisions")), pin: modelSlug(luna("openai-structured")),
});
await page.goto(`${base}/#explorer?${lunaCompare}`, { waitUntil: "networkidle0" });
await waitFor(page, () => document.querySelectorAll(".compare-side .reading-profile").length === 2);
const lunaProfiles = await page.$$eval(".compare-side .reading-profile", (profiles) =>
  profiles.map((profile) => Object.fromEntries([...profile.querySelectorAll("div")].map((field) => [
    field.querySelector("dt").textContent, field.querySelector("dd").textContent,
  ]))),
);
if (lunaProfiles[0]["Decision interface"] !== "Typed decision questions" ||
    lunaProfiles[1]["Decision interface"] !== "Structured generation" ||
    lunaProfiles.some((profile) => profile["Model role"] !== "General-purpose models")) {
  fail(`the Luna comparison misclassified a run: ${JSON.stringify(lunaProfiles)}`);
} else pass("the Luna comparison shows the same model role and two different interfaces");
const mixedCompare = new URLSearchParams({
  pop: "all", mode: "rank", open: "1", sel: modelSlug(leader), pin: modelSlug(slices[0]),
});
await page.goto(`${base}/#explorer?${mixedCompare}`, { waitUntil: "networkidle0" });
await waitFor(page, () => document.querySelector(".compare-deltas")?.textContent.includes("different case sets"));
if (await page.$(".delta-row") || !(await page.$eval(".tray-delta", el => el.textContent)).includes("not comparable")) {
  fail("guard and full-suite results displayed a cross-population difference");
} else pass("a mixed-population comparison keeps the two readings without subtracting their rates");
await page.close();

/* ---------- ranking transitions ---------- */

for (const reduced of [false, true]) {
  const motionPage = await browser.newPage();
  await motionPage.setViewport({ width: 1440, height: 1000 });
  await motionPage.emulateMediaFeatures([
    { name: "prefers-reduced-motion", value: reduced ? "reduce" : "no-preference" },
  ]);
  await motionPage.goto(`${base}/#explorer?mode=rank&pop=full`, { waitUntil: "networkidle0" });
  await motionPage.waitForSelector(".xrow");
  const state = await motionPage.evaluate(async () => {
    const first = () => document.querySelector(".xrow")?.dataset.rid;
    const before = first();
    const sort = document.querySelector("#explorer-sort");
    sort.value = "cost";
    sort.dispatchEvent(new Event("change", { bubbles: true }));
    let jump = false;
    let transition = false;
    for (let i = 0; i < 10; i += 1) {
      await new Promise(requestAnimationFrame);
      for (const row of document.querySelectorAll(".xrow")) {
        const style = getComputedStyle(row);
        jump ||= style.transform !== "none";
        transition ||= style.transitionProperty === "transform" && style.transitionDuration === "0.2s";
      }
    }
    return { changed: first() !== before, jump, transition };
  });
  if (!state.changed || state.jump === reduced || state.transition === reduced) {
    fail(`ranking re-sort fails under ${reduced ? "reduced" : "normal"} motion: ${JSON.stringify(state)}`);
  } else pass(reduced ? "reduced motion re-sorts without moving rows" : "re-sorting moves rows with a 200ms transition");
  await motionPage.close();
}

/* ---------- the phone touch session ---------- */

const phone = await browser.newPage();
await phone.setViewport({ width: 390, height: 844, hasTouch: true, isMobile: true });
await phone.goto(`${base}/`, { waitUntil: "networkidle0" });
const ordered = await phone.evaluate(() => {
  const offsets = ["#results", "#findings", "#explorer", "#method"].map(id =>
    document.querySelector(id)?.getBoundingClientRect().top);
  return offsets.every((y, i) => Number.isFinite(y) && (!i || y > offsets[i - 1]));
});
if (!ordered) fail("phone section order differs from the desktop study");
else pass("phone preserves the study reading order");
const costPlot = await phone.$(".study-scatter-plot");
await costPlot.evaluate(el => el.scrollIntoView({ block: "center", behavior: "instant" }));
await settleOn(costPlot);
const costTap = await costPlot.evaluate(plot => {
  const centers = [...plot.querySelectorAll(".study-scatter-point")].map(point => {
    const { x, y, width, height } = point.getBoundingClientRect();
    return { x: x + width / 2, y: y + height / 2 };
  });
  return centers.find((a, index) => centers.some((b, other) =>
    index !== other && Math.hypot(a.x - b.x, a.y - b.y) < 10));
});
if (costTap) {
  await phone.touchscreen.tap(costTap.x, costTap.y);
  const firstCost = await phone.$eval(".study-scatter-readout a", link => link.hash);
  await phone.touchscreen.tap(costTap.x, costTap.y);
  const secondCost = await phone.$eval(".study-scatter-readout a", link => link.hash);
  if (firstCost === secondCost) fail("repeating a tap must inspect an overlapping cost result");
  else pass("repeated taps inspect overlapping cost results on the phone");
} else fail("the phone cost chart lacks a pair of overlapping points for the touch check");
await phone.evaluate(() => document.querySelector(".explorer")?.scrollIntoView({ behavior: "instant" }));
const phoneChart = await phone.evaluate(() => {
  const chart = document.querySelector("svg.chart");
  const rect = chart?.getBoundingClientRect();
  const plate = chart?.querySelector(".label-plate")?.getBoundingClientRect();
  return Boolean(rect && plate && rect.width >= 300 && plate.left >= rect.left && plate.right <= rect.right);
});
if (!phoneChart) fail("the phone chart clips its selected result label");
else pass("the phone chart fits its selected result label");
await setMode(phone, "Rankings");
const head = await phone.$(`[data-rid="${leader.run_id}"] .xrow-head`);
if (head) {
  await settleOn(head);
  await head.tap();
}
await waitFor(phone, (rid) => {
  const row = document.querySelector(`[data-rid="${rid}"]`);
  return row && row.querySelector(".reading.open") !== null;
}, leader.run_id);
// The reading updates during the tap. The footer also waits for the
// IntersectionObserver delivery that marks the explorer as on screen.
await waitFor(phone, () => document.querySelector('.footstrip[aria-hidden="false"]'));
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
const closeReading = await phone.$(".reading-close");
if (closeReading) await closeReading.tap();
await waitFor(phone, () => document.querySelector(".reading.open") === null);
const dismissed = await phone.evaluate(() => {
  return document.querySelector(".reading.open") === null;
});
if (!dismissed) fail("the phone sheet's close control does not dismiss it");
else pass("the phone sheet's close control dismisses it");
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
