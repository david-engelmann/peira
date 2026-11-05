/**
 * DOM acceptance audit for the instrument panel board.
 * Drives a Chromium from the Playwright cache through
 * puppeteer-core against the built static export and holds
 * the rendered page to the board's rules, every expectation
 * derived from the payload at run time:
 *
 *  Structure. Nine numbered sections in page order and a
 *        nine item section bar whose targets all exist. The
 *        hero states the frozen definition verbatim, then
 *        the derived full suite range, then the derived
 *        counts.
 *  Ranking. One rail row per ranked result with its figures
 *        in its accessible name; the fold line states the
 *        count it hides and hides exactly that many; tie
 *        brackets ride the rows the independent band
 *        derivation brackets.
 *  Inspector. The default reading is a ranked result whose
 *        figures recompute from the payload. Selecting a
 *        rail row, a scatter disc, or a phone mini-row loads
 *        that result's reading, at desktop widths and in
 *        the phone touch session alike; the models index
 *        rail selects into its own inspector the same way.
 *  Flagged (C-5). The band's lead states its figure with
 *        its decomposition in the split bar and its words;
 *        every other flagged row states its figure only
 *        with the genuine flip rate and the malformed share
 *        beside it, or states the suppression instead.
 *  Malformed. Rows equal the payload's printed population
 *        in worst first order, the flag line is drawn and
 *        labelled, and amber bars mark exactly the flagged
 *        rows.
 *  Scatter. The wide panel draws every costed full suite
 *        point under the derived ceiling and ladders the
 *        no-cost rail inside it; the phone panel names its
 *        rail rows beneath the plot. Flagged points are
 *        named in words under each panel.
 *  Confinement. The suite case count stands in Method and
 *        nowhere else, outside the sanctioned carriers: the
 *        no-answer sentences that state a result's own case
 *        base, and the guard caption that introduces the
 *        subset base. Visible copy holds no em dash and no
 *        semicolon.
 *  Calibration (C-08). Panels render for every result the
 *        payload carries reliability bins for, at desktop
 *        widths and at 1100 alike.
 *  Phone. A touch session at 390x844: the inspector stands
 *        above the scatter panel, taps on mini-rows and
 *        rail rows load their readings, and the section bar
 *        lands its taps.
 *
 * The audit this replaces served the card grid board; its
 * rules with counterparts here keep their force, and its
 * checks tied to deleted surfaces (the card grid, the
 * fitted scatter list, the corner readings) are retired
 * with those surfaces, as the redesign record states.
 *
 * Screenshots land in the directory given as argv[3].
 */

import { readFileSync, mkdirSync } from "node:fs";
import { dirname, join, resolve, extname } from "node:path";
import { fileURLToPath } from "node:url";
import { globSync } from "node:fs";
import { homedir } from "node:os";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import puppeteer from "puppeteer-core";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const outDir = resolve(process.argv[2] ?? join(root, "out"));
const shotsDir = process.argv[3];
if (shotsDir) mkdirSync(shotsDir, { recursive: true });

const payload = JSON.parse(readFileSync(join(root, "data/payload.json"), "utf8"));

const failures = [];
const fail = (msg) => failures.push(msg);
const note = (msg) => console.log(`audit-dom: ${msg}`);

/* ---------- independent derivations from the payload ---------- */

const shortName = (r) => {
  let name = r.display_name;
  const at = name.lastIndexOf("@");
  if (at > 0 && /^[0-9a-f]{32,}$/.test(name.slice(at + 1))) {
    name = name.slice(0, at);
  }
  const slash = name.lastIndexOf("/");
  return slash >= 0 ? name.slice(slash + 1) : name;
};
const WIRE_WORDS_A = {
  "openai-decisions": "Decisions API",
  "openai-structured": "Chat completions",
};
const allRowsA = [...payload.ranked, ...payload.unranked];
const shortCountsA = new Map();
for (const r of allRowsA) {
  const s = shortName(r);
  shortCountsA.set(s, (shortCountsA.get(s) ?? 0) + 1);
}
const labelA = (r) => {
  const s = shortName(r);
  return shortCountsA.get(s) > 1
    ? `${s} (${WIRE_WORDS_A[r.wire] ?? r.wire})`
    : s;
};
const fullCasesA = Math.max(...payload.ranked.map((r) => r.n_cases));
const groupsA = {
  full: payload.ranked.filter((r) => r.n_cases === fullCasesA),
  slices: payload.ranked.filter((r) => r.n_cases !== fullCasesA),
  flagged: payload.unranked,
};
const countsA = {
  results: allRowsA.length,
  tested: new Set(allRowsA.map((r) => r.display_name)).size,
  ranked: new Set(payload.ranked.map((r) => r.display_name)).size,
  flagged: new Set(payload.unranked.map((r) => r.display_name)).size,
};
const byRunIdA = new Map(allRowsA.map((r) => [r.run_id, r]));

/* Decimal formatting ports, the board's half-up rule. */
function expandDecA(v) {
  const s = String(v);
  if (!/[eE]/.test(s)) return s;
  const [mant, expS] = s.split(/[eE]/);
  const exp = Number(expS);
  const neg = mant.startsWith("-");
  const body = neg ? mant.slice(1) : mant;
  const [ip, fp = ""] = body.split(".");
  const digits = ip + fp;
  const point = ip.length + exp;
  let out;
  if (point <= 0) out = "0." + "0".repeat(-point) + digits;
  else if (point >= digits.length) out = digits + "0".repeat(point - digits.length);
  else out = `${digits.slice(0, point)}.${digits.slice(point)}`;
  return (neg ? "-" : "") + out;
}
function shiftPtA(decStr, places) {
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
function quantA(decStr, decimals) {
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
const fmtPctA = (v) => `${quantA(shiftPtA(expandDecA(v), 2), 1)}%`;
const fmtIntA = (v) => v.toLocaleString("en-US");

function wilsonA(hits, n) {
  if (n === 0) return [0, 0];
  const z = 1.96;
  const p = hits / n;
  const denom = 1 + (z * z) / n;
  const center = (p + (z * z) / (2 * n)) / denom;
  const half = (z * Math.sqrt((p * (1 - p)) / n + (z * z) / (4 * n * n))) / denom;
  return [Math.max(0, center - half), Math.min(1, center + half)];
}
function displayCiA(row) {
  const pair = row.asr_ci95;
  if (!pair) return null;
  const detail = row.detail && typeof row.detail === "object" ? row.detail : {};
  const famsRaw = detail.families;
  let entries = [];
  if (Array.isArray(famsRaw)) entries = famsRaw;
  else if (famsRaw && typeof famsRaw === "object") entries = Object.values(famsRaw);
  const fams = entries.filter(
    (f) => f !== null && typeof f === "object" && !Array.isArray(f),
  );
  if (fams.length === 0) return pair;
  let total = 0;
  for (const fam of fams) {
    const nf = fam.n_flipped;
    if (typeof nf !== "number" || !Number.isInteger(nf) || nf < 0) return pair;
    total += nf;
  }
  const n = row.n_eligible;
  if (typeof n !== "number" || !Number.isInteger(n) || n === 0) return pair;
  const [lo, hi] = wilsonA(total, n);
  const q = (v) => quantA(expandDecA(v), 4);
  if (q(lo) === q(pair[0]) && q(hi) === q(pair[1])) return [lo, hi];
  return pair;
}
const axisMaxA = (() => {
  const worst = Math.max(0, ...payload.ranked.map((r) => r.asr_conditional ?? 0));
  const stepped = Math.ceil((worst - 1e-9) / 0.1) * 0.1;
  return Math.round(Math.max(0.3, stepped) * 10) / 10;
})();

/* The flip decomposition, derived the board's way. */
const countOfA = (x) =>
  typeof x === "number" && Number.isInteger(x) && x >= 0 ? x : null;
function flipDecompositionA(r) {
  const printed = r.asr_conditional;
  if (printed === null || printed === undefined) return null;
  const detail = r.detail && typeof r.detail === "object" ? r.detail : {};
  const famsRaw = detail.families;
  let entries = [];
  if (Array.isArray(famsRaw)) entries = famsRaw;
  else if (famsRaw && typeof famsRaw === "object") entries = Object.values(famsRaw);
  const fams = entries.filter(
    (f) => f !== null && typeof f === "object" && !Array.isArray(f),
  );
  if (fams.length === 0) return null;
  let flips = 0;
  let malformed = 0;
  for (const fam of fams) {
    const nf = countOfA(fam.n_flipped);
    const fd =
      fam.flip_direction !== null &&
      typeof fam.flip_direction === "object" &&
      !Array.isArray(fam.flip_direction)
        ? fam.flip_direction
        : null;
    const tm = fd ? countOfA(fd["to-malformed"]) : null;
    if (nf === null || tm === null || tm > nf) return null;
    flips += nf;
    malformed += tm;
  }
  const n = countOfA(r.n_eligible);
  if (n === null || n === 0 || flips === 0) return null;
  if (Math.abs(flips / n - printed) > 0.001) return null;
  return {
    malformedShare: malformed / flips,
    genuineRate: (flips - malformed) / n,
  };
}

const nonSliceA = allRowsA.filter((r) => r.n_cases === fullCasesA);
const plottedA = nonSliceA.filter(
  (r) => r.total_cost_usd !== null && r.total_cost_usd > 0,
);
const railA = nonSliceA.filter(
  (r) => !(r.total_cost_usd !== null && r.total_cost_usd > 0),
);
const plottedDrawnA = plottedA.filter(
  (r) => (r.asr_conditional ?? 0) <= axisMaxA,
);
const railDrawnA = railA.filter((r) => (r.asr_conditional ?? 0) <= axisMaxA);
const malformedPrintedA = [...allRowsA]
  .filter((r) => r.malformed_rate !== null && fmtPctA(r.malformed_rate) !== "0.0%")
  .sort((a, b) => {
    const d = (b.malformed_rate ?? 0) - (a.malformed_rate ?? 0);
    if (d !== 0) return d;
    return a.display_name < b.display_name ? -1 : 1;
  });
const calibrationRowsA = allRowsA.filter(
  (r) =>
    (r.detail?.calibration?.reliability_bins?.attacked?.bins?.length ?? 0) > 0 ||
    (r.detail?.calibration?.reliability_bins?.benign?.bins?.length ?? 0) > 0,
);
const FROZEN =
  "Attack success counts a case only when the benign answer was right and the attacked side answered wrong, abstained, or produced malformed output.";

/* ---------- static server for the export ---------- */

const MIME = {
  ".html": "text/html",
  ".js": "text/javascript",
  ".css": "text/css",
  ".json": "application/json",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".woff2": "font/woff2",
  ".ico": "image/x-icon",
  ".txt": "text/plain",
};
const server = createServer(async (req, res) => {
  try {
    let p = decodeURIComponent(new URL(req.url, "http://x").pathname);
    if (p.endsWith("/")) p += "index.html";
    let file = join(outDir, p);
    let data = await readFile(file).catch(() => null);
    if (data === null && !extname(p)) {
      file = join(outDir, p, "index.html");
      data = await readFile(file).catch(() => null);
    }
    if (data === null) {
      res.writeHead(404);
      res.end("not found");
      return;
    }
    res.writeHead(200, { "content-type": MIME[extname(file)] ?? "application/octet-stream" });
    res.end(data);
  } catch {
    res.writeHead(500);
    res.end("error");
  }
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const base = `http://127.0.0.1:${server.address().port}`;

/* Browser discovery and environment (round 10, 2026-10-23):
 * the full Chromium in the Playwright cache launches in
 * this sandbox where the headless shell and the Puppeteer
 * cache's Chrome die; discovery prefers it. The browser
 * gets a proxy-free environment and launches single-process
 * for the same reasons gen-og records. */
const chromeOverride =
  process.env.PUPPETEER_EXECUTABLE_PATH ?? process.env.CHROME_PATH;
const chromeHits = chromeOverride
  ? [chromeOverride]
  : [
      ...globSync(".cache/ms-playwright/chromium-*/chrome-linux64/chrome", {
        cwd: homedir(),
      }).map((p) => join(homedir(), p)),
      ...globSync(
        ".cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell",
        { cwd: homedir() },
      ).map((p) => join(homedir(), p)),
    ];
if (chromeHits.length === 0) {
  console.error("audit-dom: no Chromium found in the Playwright cache");
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

const pageErrors = [];
async function load(width, height = 900) {
  const page = await browser.newPage();
  page.on("pageerror", (e) => pageErrors.push(`width ${width}: ${e.message}`));
  page.on("console", (m) => {
    if (m.type() === "error") {
      pageErrors.push(`width ${width}: console: ${m.text()}`);
    }
  });
  await page.setViewport({ width, height });
  await page.goto(`${base}/`, { waitUntil: "networkidle0", timeout: 120000 });
  await page.evaluate(() => document.fonts.ready);
  return page;
}
const text = (page, sel) =>
  page.evaluate(
    (s) => document.querySelector(s)?.textContent?.replace(/\s+/g, " ").trim() ?? null,
    sel,
  );
const allText = (page, sel) =>
  page.evaluate(
    (s) =>
      [...document.querySelectorAll(s)].map((el) =>
        el.textContent.replace(/\s+/g, " ").trim(),
      ),
    sel,
  );

/* ---------- shared structure, run at every width ---------- */

const SECTION_ORDER = [
  "scatter",
  "ranking",
  "flagged",
  "malformed",
  "heatmap",
  "calibration",
  "compare",
  "models",
  "method",
];
async function structureChecks(page, width) {
  const order = await page.evaluate(() =>
    [...document.querySelectorAll("[data-section]")].map((el) =>
      el.getAttribute("data-section"),
    ),
  );
  if (JSON.stringify(order) !== JSON.stringify(SECTION_ORDER)) {
    fail(`width ${width}: section order is ${order.join(", ")}, expected ${SECTION_ORDER.join(", ")}`);
  }
  const nav = await page.evaluate(() =>
    [...document.querySelectorAll(".section-nav a")].map((a) => ({
      href: a.getAttribute("href"),
      label: a.textContent.trim(),
    })),
  );
  if (nav.length !== SECTION_ORDER.length + 0 && nav.length !== 9) {
    fail(`width ${width}: the section bar carries ${nav.length} items, expected 9`);
  }
  const ids = await page.evaluate(() =>
    [...document.querySelectorAll("section[id]")].map((el) => el.id),
  );
  for (const item of nav) {
    if (!ids.includes(item.href.replace("#", ""))) {
      fail(`width ${width}: nav target ${item.href} has no section`);
    }
  }
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  );
  if (overflow > 1) {
    fail(`width ${width}: horizontal overflow of ${overflow}px`);
  }
  const h1 = await text(page, "h1");
  if (!h1 || !h1.startsWith(FROZEN)) {
    fail(`width ${width}: the hero does not open with the frozen definition`);
  }
  const full = groupsA.full;
  const range = `On the full suite, attack success runs from ${fmtPctA(full[0].asr_conditional)} to ${fmtPctA(full.at(-1).asr_conditional)}.`;
  if (h1 && !h1.includes(range)) {
    fail(`width ${width}: the hero range is not the derived range (${range})`);
  }
  const counts = await text(page, ".counts-line");
  for (const needle of [
    `${fmtIntA(countsA.tested)} models`,
    `${fmtIntA(countsA.ranked)} models`,
    `${fmtIntA(countsA.flagged)}`,
  ]) {
    if (!counts || !counts.includes(needle)) {
      fail(`width ${width}: the counts line does not state "${needle}"`);
    }
  }
}

/* ---------- desktop derivations at 1440 ---------- */

async function desktopChecks(page) {
  /* Ranking rail population and figures. */
  const railRows = await page.evaluate(() => {
    const ghead = document.querySelector('[data-section="ranking"] .ghead');
    return [...document.querySelectorAll('[data-section="ranking"] .rrow')].map(
      (el) => ({
        id: el.getAttribute("data-run-id"),
        aria: el.getAttribute("aria-label") ?? "",
        atk: el.querySelector(".atk")?.textContent ?? "",
        hidden: el.hidden,
        /* Rows after the guard group head are the slice
         * group; the fold lines are per group, so the fold
         * arithmetic is too. */
        slice: ghead
          ? (el.compareDocumentPosition(ghead) &
              Node.DOCUMENT_POSITION_PRECEDING) !==
            0
          : false,
      }),
    );
  });
  if (railRows.length !== payload.ranked.length) {
    fail(`ranking rail carries ${railRows.length} rows, expected ${payload.ranked.length}`);
  }
  for (const row of railRows) {
    const src = byRunIdA.get(row.id);
    if (!src) {
      fail(`ranking rail row ${row.id} is not a payload row`);
      continue;
    }
    if (row.atk !== fmtPctA(src.asr_conditional)) {
      fail(`ranking row ${labelA(src)} prints attack success ${row.atk}, expected ${fmtPctA(src.asr_conditional)}`);
    }
    const ci = displayCiA(src);
    if (ci && !row.aria.includes(`${fmtPctA(ci[0])}`)) {
      fail(`ranking row ${labelA(src)} accessible name lacks its interval`);
    }
  }
  const foldTexts = await page.evaluate(() =>
    [...document.querySelectorAll('[data-section="ranking"] .foldline')].map(
      (el) => el.textContent.trim(),
    ),
  );
  const foldGroups = [
    { name: "full-suite", rows: railRows.filter((r) => !r.slice), fold: foldTexts[0] },
    { name: "guard", rows: railRows.filter((r) => r.slice), fold: foldTexts[1] },
  ];
  for (const g of foldGroups) {
    const hiddenCount = g.rows.filter((r) => r.hidden).length;
    if (hiddenCount > 0) {
      if (!g.fold || !g.fold.startsWith(`${hiddenCount} further`)) {
        fail(`the ${g.name} fold line states "${g.fold}", hiding ${hiddenCount} rows`);
      }
    }
  }
  /* The default inspector reading recomputes. */
  const insp = await page.evaluate(() => {
    const el = document.querySelector('[data-section="ranking"] [data-inspector-for]');
    return el
      ? { id: el.getAttribute("data-inspector-for"), text: el.textContent.replace(/\s+/g, " ") }
      : null;
  });
  if (!insp) {
    fail("the ranking zone carries no inspector");
  } else {
    const src = byRunIdA.get(insp.id);
    if (!src || !payload.ranked.some((r) => r.run_id === insp.id)) {
      fail(`the default inspector reading is ${insp.id}, not a ranked result`);
    } else if (!insp.text.includes(fmtPctA(src.asr_conditional))) {
      fail(`the default inspector does not state ${labelA(src)}'s attack success`);
    }
  }
  /* Selection: a rail row click loads its reading. */
  const target = railRows.find((r) => !r.hidden && r.id !== insp?.id) ?? railRows[1];
  if (target) {
    await page.click(`[data-section="ranking"] .rrow[data-run-id="${target.id}"]`);
    const now = await page.evaluate(
      () =>
        document
          .querySelector('[data-section="ranking"] [data-inspector-for]')
          ?.getAttribute("data-inspector-for") ?? null,
    );
    if (now !== target.id) {
      fail(`selecting rail row ${target.id} left the inspector on ${now}`);
    }
  }
  /* Selection from the scatter: clicking a disc loads it. */
  const disc = await page.evaluate(() => {
    const el = document.querySelector(
      '[data-section="scatter"] .scatter-wide [data-point-for]',
    );
    return el?.getAttribute("data-point-for") ?? null;
  });
  if (disc) {
    await page.click(
      `[data-section="scatter"] .scatter-wide [data-point-for="${disc}"]`,
    );
    const now = await page.evaluate(
      () =>
        document
          .querySelector('[data-section="ranking"] [data-inspector-for]')
          ?.getAttribute("data-inspector-for") ?? null,
    );
    if (now !== disc) {
      fail(`selecting scatter disc ${disc} left the inspector on ${now}`);
    }
  }
  /* Flagged band (C-5). */
  const flaggedSorted = [...groupsA.flagged].sort(
    (a, b) => (b.asr_conditional ?? 0) - (a.asr_conditional ?? 0),
  );
  const lead = flaggedSorted[0];
  const leadDecomp = lead ? flipDecompositionA(lead) : null;
  if (lead && leadDecomp) {
    const big = await text(page, '[data-section="flagged"] .big');
    if (big !== fmtPctA(lead.asr_conditional)) {
      fail(`the flagged lead prints ${big}, expected ${fmtPctA(lead.asr_conditional)}`);
    }
    const splitnum = await text(page, '[data-section="flagged"] .splitnum');
    if (splitnum !== fmtPctA(leadDecomp.malformedShare)) {
      fail(`the split bar prints ${splitnum} inside, expected ${fmtPctA(leadDecomp.malformedShare)}`);
    }
  }
  const flagRows = await page.evaluate(() =>
    [...document.querySelectorAll('[data-section="flagged"] .flagrow')].map(
      (el) => ({
        id: el.getAttribute("data-run-id"),
        text: el.textContent.replace(/\s+/g, " "),
      }),
    ),
  );
  if (flagRows.length !== Math.max(0, flaggedSorted.length - 1)) {
    fail(`the flagged band lists ${flagRows.length} rows under its lead, expected ${Math.max(0, flaggedSorted.length - 1)}`);
  }
  for (const row of flagRows) {
    const src = byRunIdA.get(row.id);
    const d = src ? flipDecompositionA(src) : null;
    if (d) {
      if (
        !row.text.includes(`genuine flip rate ${fmtPctA(d.genuineRate)}`) ||
        !row.text.includes(`${fmtPctA(d.malformedShare)} of counted flips to malformed output`)
      ) {
        fail(`flagged row ${labelA(src)} states its figure without its decomposition`);
      }
    } else if (!row.text.includes("not stated")) {
      fail(`flagged row ${row.id} neither decomposes nor states its suppression`);
    }
  }
  /* Malformed rail. */
  const malf = await page.evaluate(() =>
    [...document.querySelectorAll('[data-section="malformed"] .mrow')].map(
      (el) => ({
        id: el.getAttribute("data-run-id"),
        rate: el.querySelector(".mrate")?.textContent ?? "",
        amber: el.querySelector(".mbar")?.classList.contains("amber") ?? false,
      }),
    ),
  );
  if (malf.length !== malformedPrintedA.length) {
    fail(`the malformed rail prints ${malf.length} rows, expected ${malformedPrintedA.length}`);
  }
  malf.forEach((row, i) => {
    const src = malformedPrintedA[i];
    if (!src || row.id !== src.run_id || row.rate !== fmtPctA(src.malformed_rate)) {
      fail(`malformed row ${i} is ${row.id} at ${row.rate}, expected ${src?.run_id} at ${src ? fmtPctA(src.malformed_rate) : "?"}`);
    }
    const flagged = groupsA.flagged.some((r) => r.run_id === row.id);
    if (row.amber !== flagged) {
      fail(`malformed row ${row.id} amber is ${row.amber}, flagged is ${flagged}`);
    }
  });
  const flagline = await page.evaluate(() =>
    Boolean(document.querySelector('[data-section="malformed"] .flagline')),
  );
  if (!flagline) fail("the malformed rail draws no flag line");
  const flagTag = await text(page, '[data-section="malformed"] .malfhead');
  if (!flagTag || !flagTag.includes("5 percent")) {
    fail("the malformed flag line is not labelled with its 5 percent");
  }
  /* Scatter populations. */
  const scatter = await page.evaluate(() => ({
    widePoints: document.querySelectorAll(
      '[data-section="scatter"] .scatter-wide [data-point-for]',
    ).length,
    wideRail: document.querySelectorAll(
      '[data-section="scatter"] .scatter-wide [data-rail-for]',
    ).length,
    phonePoints: document.querySelectorAll(
      '[data-section="scatter"] .scatter-phone [data-point-for]',
    ).length,
    miniRows: document.querySelectorAll(
      '[data-section="scatter"] .scatter-phone .srow',
    ).length,
    nameline: [...document.querySelectorAll('[data-section="scatter"] .nameline')]
      .map((el) => el.textContent.replace(/\s+/g, " "))
      .join(" "),
  }));
  if (scatter.widePoints !== plottedDrawnA.length) {
    fail(`the wide scatter draws ${scatter.widePoints} points, expected ${plottedDrawnA.length}`);
  }
  if (scatter.wideRail !== railDrawnA.length) {
    fail(`the wide scatter ladders ${scatter.wideRail} rail rows, expected ${railDrawnA.length}`);
  }
  if (scatter.phonePoints !== plottedDrawnA.length) {
    fail(`the phone scatter draws ${scatter.phonePoints} points, expected ${plottedDrawnA.length}`);
  }
  if (scatter.miniRows !== railA.length) {
    fail(`the phone rail names ${scatter.miniRows} rows, expected ${railA.length}`);
  }
  for (const r of plottedDrawnA.filter((x) => !x.ranking_eligible)) {
    if (!scatter.nameline.includes(labelA(r))) {
      fail(`flagged point ${labelA(r)} is not named in words under the scatter`);
    }
  }
  /* Models index selection. */
  const idxFirst = await page.evaluate(() => {
    const inspEl = document.querySelector('[data-section="models"] [data-inspector-for]');
    const rows = [...document.querySelectorAll('[data-section="models"] .irow')];
    return {
      insp: inspEl?.getAttribute("data-inspector-for") ?? null,
      rows: rows.length,
      second: rows[1]?.getAttribute("data-index-for") ?? null,
    };
  });
  if (idxFirst.rows !== allRowsA.length) {
    fail(`the models index lists ${idxFirst.rows} rows, expected ${allRowsA.length}`);
  }
  if (idxFirst.second) {
    await page.click(
      `[data-section="models"] .irow[data-index-for="${idxFirst.second}"]`,
    );
    const now = await page.evaluate(
      () =>
        document
          .querySelector('[data-section="models"] [data-inspector-for]')
          ?.getAttribute("data-inspector-for") ?? null,
    );
    if (now !== idxFirst.second) {
      fail(`selecting index row ${idxFirst.second} left its inspector on ${now}`);
    }
  }
  /* Confinement of the suite case count. */
  const caseStr = fmtIntA(fullCasesA);
  const stray = await page.evaluate((needle) => {
    const clone = document.body.cloneNode(true);
    clone.querySelectorAll("script, style, noscript").forEach((el) => el.remove());
    const method = clone.querySelector("#method");
    const hits = [];
    const walk = (node) => {
      for (const child of node.childNodes) {
        if (child.nodeType === 3) {
          if (child.textContent.includes(needle)) {
            hits.push({
              text: child.textContent.replace(/\s+/g, " ").trim().slice(0, 120),
              sanctioned: Boolean(
                child.parentElement?.closest(
                  ".flaglead, .disc, .ghead, .mal-fold",
                ),
              ),
            });
          }
        } else if (child.nodeType === 1 && child !== method && !method?.contains(child)) {
          walk(child);
        }
      }
    };
    walk(clone);
    return hits;
  }, caseStr);
  for (const hit of stray) {
    if (!hit.sanctioned) {
      fail(`the suite case count stands outside Method in "${hit.text}"`);
    }
  }
  /* Copy bars on visible text. */
  const visibleTextAll = await page.evaluate(() => {
    const clone = document.body.cloneNode(true);
    clone.querySelectorAll("script, style, noscript").forEach((el) => el.remove());
    return clone.textContent;
  });
  if (visibleTextAll.includes("—")) fail("visible copy carries an em dash");
  if (visibleTextAll.includes(";")) fail("visible copy carries a semicolon");
  /* Calibration population (C-08) at desktop. */
  const calPanels = await page.evaluate(
    () => document.querySelectorAll('[data-section="calibration"] .cal-panel').length,
  );
  if (calPanels !== calibrationRowsA.length) {
    fail(`calibration renders ${calPanels} panels, expected ${calibrationRowsA.length}`);
  }
}

/* ---------- the width loop ---------- */

for (const width of [1440, 1280, 1100, 900, 760, 500]) {
  const page = await load(width);
  await structureChecks(page, width);
  if (width === 1440) await desktopChecks(page);
  if (width === 1100) {
    const calPanels = await page.evaluate(
      () => document.querySelectorAll('[data-section="calibration"] .cal-panel').length,
    );
    if (calPanels !== calibrationRowsA.length) {
      fail(`width 1100: calibration renders ${calPanels} panels, expected ${calibrationRowsA.length} (C-08)`);
    }
  }
  if (width === 1440 && shotsDir) {
    await page.screenshot({
      path: join(shotsDir, "desktop-top.png"),
      clip: { x: 0, y: 0, width: 1440, height: 1600 },
    });
    const band = await page.evaluate(() => {
      const el = document.querySelector('[data-section="flagged"]');
      const r = el.getBoundingClientRect();
      return { y: r.top + window.scrollY, h: Math.min(r.height, 1600) };
    });
    await page.screenshot({
      path: join(shotsDir, "band.png"),
      clip: { x: 0, y: Math.max(0, band.y), width: 1440, height: band.h },
    });
  }
  await page.close();
}

/* ---------- the phone touch session at 390x844 ---------- */

{
  const page = await load(390, 844);
  await page.evaluate(() => document.fonts.ready);
  await structureChecks(page, 390);
  /* The inspector stands above the scatter panel. */
  const order = await page.evaluate(() => {
    const inspEl = document.querySelector('[data-section="ranking"] .insp');
    const panel = document.querySelector('[data-section="scatter"] .spanel');
    if (!inspEl || !panel) return null;
    return {
      inspTop: inspEl.getBoundingClientRect().top + window.scrollY,
      panelTop: panel.getBoundingClientRect().top + window.scrollY,
    };
  });
  if (!order) {
    fail("phone: inspector or scatter panel missing");
  } else if (!(order.inspTop < order.panelTop)) {
    fail("phone: the inspector does not stand above the scatter panel");
  }
  /* A tap on a mini-row loads its reading. */
  const mini = await page.evaluate(() =>
    [...document.querySelectorAll('[data-section="scatter"] .srow')].map(
      (el) => el.getAttribute("data-rail-for"),
    ),
  );
  if (mini.length === 0) {
    fail("phone: no mini-rows under the plot");
  } else {
    const target = mini[1] ?? mini[0];
    await page.tap(`[data-section="scatter"] .srow[data-rail-for="${target}"]`);
    const now = await page.evaluate(
      () =>
        document
          .querySelector('[data-section="ranking"] [data-inspector-for]')
          ?.getAttribute("data-inspector-for") ?? null,
    );
    if (now !== target) {
      fail(`phone: tapping mini-row ${target} left the inspector on ${now}`);
    }
    /* A tap on a rail row loads its reading too. */
    const railTarget = await page.evaluate(() => {
      const el = [...document.querySelectorAll('[data-section="ranking"] .rrow')].find(
        (r) => !r.hidden,
      );
      return el?.getAttribute("data-run-id") ?? null;
    });
    if (railTarget && railTarget !== target) {
      await page.tap(
        `[data-section="ranking"] .rrow[data-run-id="${railTarget}"]`,
      );
      const after = await page.evaluate(
        () =>
          document
            .querySelector('[data-section="ranking"] [data-inspector-for]')
            ?.getAttribute("data-inspector-for") ?? null,
      );
      if (after !== railTarget) {
        fail(`phone: tapping rail row ${railTarget} left the inspector on ${after}`);
      }
    }
  }
  /* The section bar lands a tap on its target. The bar is
   * a horizontal strip and Method is its last item, off
   * the strip's right edge at phone width, so the item is
   * scrolled into the strip first, the way a thumb does. */
  await page.evaluate(() => {
    document
      .querySelector('.section-nav a[href="#method"]')
      ?.scrollIntoView({ block: "nearest", inline: "center" });
  });
  await new Promise((r) => setTimeout(r, 300));
  await page.tap('.section-nav a[href="#method"]');
  await new Promise((r) => setTimeout(r, 1400));
  const landed = await page.evaluate(() => ({
    hash: window.location.hash,
    methodTop: Math.abs(
      document.querySelector("#method").getBoundingClientRect().top,
    ),
  }));
  if (landed.hash !== "#method" || landed.methodTop > 220) {
    fail(`phone: the section bar tap did not land on Method (hash ${landed.hash}, offset ${Math.round(landed.methodTop)})`);
  }
  if (shotsDir) {
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: join(shotsDir, "phone.png") });
  }
  await page.close();
}

for (const e of pageErrors) fail(`page error: ${e}`);

await browser.close();
server.close();
if (failures.length > 0) {
  console.error(`audit-dom: ${failures.length} failure(s)`);
  for (const f of failures) console.error(`  FAIL ${f}`);
  process.exit(1);
}
note(`all checks passed at 1440, 1280, 1100, 900, 760, 500 and the 390 touch session over ${countsA.results} results`);
