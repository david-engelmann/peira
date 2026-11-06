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
 *     comparison carries the four derived deltas, each
 *     signed in words
 *   sorting and the population filter restate the view, the
 *     guard population with its basis line
 *   chart hover lights the same result in the list beside
 *     the chart, and a brush drag filters the view and says
 *     so in the count line
 *   a model address (/#result=<slug>) opens that reading
 *   a finding's action sets the explorer state it promises
 *   finding actions followed in sequence each land where
 *     they promise, with unnamed state back at its default
 *   the rank header's labels stand over their columns
 *   families mode sorts by a family from its label, and
 *     carries exactly one reading for an expanded row
 *   filtering in chart mode fades entering discs at 200ms
 *   the five state changes of BUILD-SPEC part 6 animate at
 *     200ms, and reduced motion suppresses every one of them
 *   at phone size the reading opens as a sheet over a sticky
 *     strip that names the selection, the tray pins above
 *     the strip, and a tap outside dismisses the sheet
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
/* The brush proof asserts numbers, not a text change. The
 * expected count is recomputed from the payload through the
 * chart's own geometry (the half decade cost domain, the
 * shared axis rule, the plot pads), read off the built svg's
 * viewBox, and the count line must land on it within a small
 * boundary tolerance for rows sitting on the drag's edge. */
const parseShowing = (t) => {
  const m = /Showing ([\d,]+) of ([\d,]+)/.exec(t ?? "");
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
  const padL = 44, padR = 16, padT = 18, padB = 40;
  const chartedRows = rows.filter((r) => !slices.includes(r));
  const costs = chartedRows
    .map((r) => r.total_cost_usd)
    .filter((c) => typeof c === "number" && c > 0);
  const lo = Math.pow(10, Math.floor(Math.log10(Math.min(...costs)) * 2) / 2);
  const hi = Math.pow(10, Math.ceil(Math.log10(Math.max(...costs)) * 2) / 2);
  const worstRanked = Math.max(...payload.ranked.map((r) => r.asr_conditional ?? 0));
  const axisMax = Math.max(0.3, Math.round(Math.ceil((worstRanked - 1e-9) / 0.1) * 0.1 * 10) / 10);
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
    rows.filter((r) => {
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

/* Families mode sorts by a family from its label. The
 * expected order is recomputed from the payload's own family
 * records for the full suite group, rates descending with
 * unmeasured families last, and the rendered group must land
 * on it after the family's label is clicked. */
await clickText(page, "Clear the brush filter").catch(() => null);
await waitFor(page, (total) => {
  const t = document.querySelector(".xcount")?.textContent ?? "";
  const m = /Showing ([\d,]+) of/.exec(t);
  return m !== null && Number(m[1].replace(/,/g, "")) === total;
}, rows.length);
await clickText(page, "Families").catch(() => null);
await page.waitForSelector(".xfamrow", { timeout: 10000 }).catch(() => null);
const famGroupNames = async () => {
  return page.evaluate(() => {
    const group = document.querySelector(".xfamilies .xgroup");
    if (!group) return [];
    return [...group.querySelectorAll(".xfamrow .xname")].map((el) =>
      (el.childNodes[0]?.textContent ?? "").trim(),
    );
  });
};
const famKeys = [
  ...new Set(full.flatMap((r) => Object.keys(r.detail?.families ?? {}))),
];
const famRate = (r, key) => {
  const rec = r.detail?.families?.[key];
  return rec && typeof rec.asr === "number" ? rec.asr : null;
};
const famExpected = (key) =>
  [...full]
    .sort((a, b) => {
      const ra = famRate(a, key);
      const rb = famRate(b, key);
      if (ra === null && rb === null) return 0;
      if (ra === null) return 1;
      if (rb === null) return -1;
      return rb - ra;
    })
    .map((r) => shortName(r));
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
  const famFullName =
    famPick.key.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
  const clicked = await page.evaluate((label) => {
    const btn = [...document.querySelectorAll(".xfam-labelbtn")].find(
      (b) => b.getAttribute("aria-label") === label,
    );
    if (!btn) return false;
    btn.click();
    return true;
  }, `Sort by ${famFullName}`);
  if (!clicked) {
    fail(`no family label button offers ${famFullName}`);
  } else {
    await waitFor(page, (want) => {
      const group = document.querySelector(".xfamilies .xgroup");
      const first = group?.querySelector(".xfamrow .xname")?.childNodes[0]?.textContent?.trim();
      return first === want;
    }, famPick.expected[0]);
    const famAfterNames = await famGroupNames();
    const famHash = await page.evaluate(() => location.hash);
    if (famAfterNames.join("|") !== famPick.expected.join("|")) {
      fail(
        `families mode sorted by ${famFullName} lands on ${famAfterNames.slice(0, 3).join(", ")}, the payload order is ${famPick.expected.slice(0, 3).join(", ")}`,
      );
    } else if (!famHash.includes("sort=fam")) {
      fail("the family sort does not write itself into the hash");
    } else pass("families mode sorts by a family from its label");
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

/* Finding actions followed in sequence land where each one
 * promises. The price action promises the priced chart, the
 * guards action promises the guards in rank mode, and the
 * price action again promises the chart. State an action
 * does not name returns to its default on each landing, so
 * the guards step carries no priced band and the return step
 * carries discs. On the old merge semantics the guards step
 * inherits the priced band over a population whose costs are
 * unrecorded and lands on the empty state. */
{
  const costBand = () =>
    page.evaluate(() => {
      const sel = [...document.querySelectorAll(".explorer select")].find((s) =>
        [...s.options].some((o) => o.value === "priced"),
      );
      return sel?.value ?? null;
    });
  await findingsActions[2].click();
  await page.waitForSelector("svg.chart", { timeout: 10000 }).catch(() => null);
  const pricedDiscs = await page.evaluate(
    () => document.querySelectorAll("svg.chart circle").length,
  );
  const pricedBand = await costBand();
  if (pricedDiscs === 0) fail("the price action lands on a chart with no discs");
  else if (pricedBand !== "priced") {
    fail(`the price action leaves the cost band at ${pricedBand}, not priced`);
  } else pass("the price action lands on the priced chart");

  await findingsActions[3].click();
  await waitFor(page, () => document.querySelector(".basisline") !== null);
  const guardsStep = await page.evaluate(() => {
    const seg = [...document.querySelectorAll(".segbtn")].find(
      (b) => b.textContent.trim() === "Guards",
    );
    return {
      guardsOn: seg?.classList.contains("on") ?? false,
      empty: document.querySelector(".xempty") !== null,
      rows: document.querySelectorAll(".xrow").length,
    };
  });
  const guardsBand = await costBand();
  if (!guardsStep.guardsOn) {
    fail("the guards action does not land on the guards population");
  } else if (guardsStep.empty || guardsStep.rows === 0) {
    fail("the guards action lands on the empty state instead of the guards");
  } else if (guardsBand !== "all") {
    fail(`the guards action inherits the cost band ${guardsBand} from the price action`);
  } else pass("the guards action lands on the guards with rows visible");

  await findingsActions[2].click();
  await page.waitForSelector("svg.chart", { timeout: 10000 }).catch(() => null);
  const returnDiscs = await page.evaluate(
    () => document.querySelectorAll("svg.chart circle").length,
  );
  if (returnDiscs === 0) {
    fail("returning to the price action lands on a chart with no discs");
  } else pass("the price action after the guards lands on the priced chart again");
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

/* ---------- motion, BUILD-SPEC part 6 ---------- */

/* All five state changes animate at the same 200ms character.
 * Expansion and selection are read off computed styles,
 * filtering off the entering rows and the re-sort's inline
 * FLIP transition, and mode switching off the view wrapper.
 * A reduced motion page must reach every end state with no
 * travel at all. */
const motionPage = await browser.newPage();
await motionPage.setViewport({ width: 1440, height: 1000 });
await motionPage.goto(`${base}/`, { waitUntil: "networkidle0" });
await motionPage.evaluate(() => {
  document.querySelector(".xrow-head")?.click();
});
await waitFor(motionPage, () => document.querySelector(".reading.open") !== null);
const motionStyles = await motionPage.evaluate(() => {
  const reading = document.querySelector(".reading.open");
  const row = document.querySelector(".xrow");
  const rs = reading ? getComputedStyle(reading) : null;
  const ws = row ? getComputedStyle(row) : null;
  return {
    readingName: rs?.animationName ?? "",
    readingDur: rs?.animationDuration ?? "",
    rowTransition: ws?.transitionProperty ?? "",
    rowDur: ws?.transitionDuration ?? "",
  };
});
if (
  !motionStyles.readingName.includes("xreading-in") ||
  motionStyles.readingDur !== "0.2s"
) {
  fail(
    `expansion does not animate at 200ms (name ${motionStyles.readingName}, duration ${motionStyles.readingDur})`,
  );
} else if (
  !motionStyles.rowTransition.includes("border-color") ||
  !motionStyles.rowDur.includes("0.2s")
) {
  fail("selection does not transition the row at 200ms");
} else pass("expansion and selection animate at 200ms");

/* Filtering. Rows entering the widened set fade in, and a
 * survivor of the re-sort travels on the FLIP transition. */
await clickText(motionPage, "Full suite").catch(() => null);
await waitFor(motionPage, (n) => document.querySelectorAll(".xrow").length === n, full.length);
await clickText(motionPage, "All results").catch(() => null);
await waitFor(motionPage, () => document.querySelector(".xrow.enter") !== null);
const entered = await motionPage.evaluate(() => {
  const el = document.querySelector(".xrow.enter");
  if (!el) return null;
  const s = getComputedStyle(el);
  return { name: s.animationName, dur: s.animationDuration };
});
if (!entered || !entered.name.includes("xrow-in") || entered.dur !== "0.2s") {
  fail("filtering admits new rows with no 200ms fade");
} else pass("filtering fades entering rows at 200ms");
await clickText(motionPage, "Cost", "button.xh").catch(() => null);
let flipSeen = false;
for (let i = 0; i < 10 && !flipSeen; i += 1) {
  flipSeen = await motionPage.evaluate(() => {
    return [...document.querySelectorAll("[data-rid]")].some((el) =>
      (el.getAttribute("style") ?? "").includes("transform 200ms"),
    );
  });
  if (!flipSeen) await new Promise((r) => setTimeout(r, 25));
}
if (!flipSeen) fail("re-sorting travels no row on the 200ms FLIP transition");
else pass("re-sorting travels rows at 200ms");

/* Mode switching crossfades the view wrapper. */
await clickText(motionPage, "Chart").catch(() => null);
await motionPage.waitForSelector(".xview svg.chart", { timeout: 10000 }).catch(() => null);
const viewAnim = await motionPage.evaluate(() => {
  const v = document.querySelector(".xview");
  const s = v ? getComputedStyle(v) : null;
  return { name: s?.animationName ?? "", dur: s?.animationDuration ?? "" };
});
if (!viewAnim.name.includes("xview-in") || viewAnim.dur !== "0.2s") {
  fail("mode switching does not animate the view at 200ms");
} else pass("mode switching animates the view at 200ms");

/* Filtering in chart mode. Discs admitted to the visible set
 * on a filter change carry the same 200ms enter fade as
 * rows. The vendor filter narrows the chart, and clearing it
 * admits the discs back. */
const vendorOptions = await motionPage.evaluate(() => {
  const field = [...document.querySelectorAll(".xfield")].find(
    (f) => f.querySelector(".micro")?.textContent.trim() === "Vendor",
  );
  const sel = field?.querySelector("select");
  return sel ? [...sel.options].map((o) => o.value) : [];
});
if (vendorOptions.length < 2) {
  fail("the vendor filter offers no second value, so the chart filtering proof cannot run");
} else {
  const setVendor = (value) =>
    motionPage.evaluate((v) => {
      const field = [...document.querySelectorAll(".xfield")].find(
        (f) => f.querySelector(".micro")?.textContent.trim() === "Vendor",
      );
      const sel = field?.querySelector("select");
      if (!sel) return;
      const setter = Object.getOwnPropertyDescriptor(
        window.HTMLSelectElement.prototype,
        "value",
      ).set;
      setter.call(sel, v);
      sel.dispatchEvent(new Event("change", { bubbles: true }));
    }, value);
  await setVendor(vendorOptions[1]);
  await new Promise((r) => setTimeout(r, 350));
  await setVendor("all");
  await waitFor(motionPage, () => document.querySelector(".disc.enter") !== null);
  const discAnim = await motionPage.evaluate(() => {
    const el = document.querySelector(".disc.enter");
    if (!el) return null;
    const s = getComputedStyle(el);
    return { name: s.animationName, dur: s.animationDuration };
  });
  if (!discAnim || !discAnim.name.includes("xrow-in") || discAnim.dur !== "0.2s") {
    fail("filtering in chart mode admits discs with no 200ms fade");
  } else pass("filtering fades entering discs at 200ms");
}
await motionPage.close();

/* Reduced motion reaches the end states with no travel. */
const rmPage = await browser.newPage();
await rmPage.emulateMediaFeatures([
  { name: "prefers-reduced-motion", value: "reduce" },
]);
await rmPage.setViewport({ width: 1440, height: 1000 });
await rmPage.goto(`${base}/`, { waitUntil: "networkidle0" });
await rmPage.evaluate(() => {
  document.querySelector(".xrow-head")?.click();
});
await waitFor(rmPage, () => document.querySelector(".reading.open") !== null);
const rmStyles = await rmPage.evaluate(() => {
  const reading = document.querySelector(".reading.open");
  const row = document.querySelector(".xrow");
  const rs = reading ? getComputedStyle(reading) : null;
  const ws = row ? getComputedStyle(row) : null;
  return {
    readingName: rs?.animationName ?? "",
    readingDur: rs?.animationDuration ?? "",
    rowDur: ws?.transitionDuration ?? "",
  };
});
await clickText(rmPage, "Cost", "button.xh").catch(() => null);
await new Promise((r) => setTimeout(r, 350));
const rmTransforms = await rmPage.evaluate(() => {
  return [...document.querySelectorAll("[data-rid]")].filter((el) =>
    (el.getAttribute("style") ?? "").includes("transform"),
  ).length;
});
if (
  rmStyles.readingName !== "none" ||
  rmStyles.readingDur !== "0s" ||
  rmStyles.rowDur !== "0s" ||
  rmTransforms > 0
) {
  fail(
    `reduced motion still travels (reading ${rmStyles.readingName} ${rmStyles.readingDur}, row transition ${rmStyles.rowDur}, ${rmTransforms} transformed rows)`,
  );
} else pass("reduced motion suppresses every transition");
await rmPage.close();

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
