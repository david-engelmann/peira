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
 *  Calibration (C-01 to C-08). Panels render for every
 *        result the payload carries reliability bins for,
 *        in attacked ECE order, at every width. Tick
 *        numerals render at 10 px or larger (C-01). On the
 *        phone the rail entries never share a line (C-02).
 *        A wrapped panel name breaks only after a hyphen
 *        or a space and never strands its final segment
 *        (C-04). Rail names stay inside the section bounds
 *        and unclipped (C-05). Every tick numeral's box
 *        stays inside the viewBox (C-06). The coincidence
 *        fact stands in the lede, never on a panel (C-07).
 *        And the panels showing each axis are exactly the
 *        array's edge panels for the layout in force, at
 *        every width (C-08).
 *  Heatmap. Family headers neither wrap nor clip, and row
 *        names render unclipped, at every width.
 *  Scatter clearance. On the wide panel, in-plot label
 *        boxes intersect neither each other nor any disc,
 *        and every rail name keeps clear of its rate figure.
 *  Section bar. The nine links match their targets and
 *        labels exactly and stand at least 24 px in both
 *        dimensions. At phone widths every link scrolls
 *        fully into the strip untruncated. At desktop a
 *        keyboard walk finds every link inside the viewport,
 *        uncovered at its centre, with its focus outline
 *        showing. Keyboard activation lands each section
 *        under the bar rule with the address following. And
 *        the scrollspy marks exactly the section in view,
 *        with aria-current, shifting no layout.
 *  Phone. A touch session at 390x844. The inspector stands
 *        above the scatter panel, taps on mini-rows and
 *        rail rows load their readings, and the section bar
 *        lands its taps.
 *
 * The audit this replaces served the card grid board. Its
 * checks tied to surfaces the redesign deleted stay
 * retired with those surfaces, namely the card grid's field
 * assertions (which live on, per surface, in
 * check-integrity), the fitted scatter list, the corner
 * readings, and the card anchor and expansion probes. Its
 * checks with counterparts on retained surfaces are
 * restored here in the new grammar, namely the calibration
 * battery C-01 to C-08, the heatmap and scatter name
 * checks, and the section bar's scrollspy and activation
 * checks, as the redesign record states.
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
/* The calibration panel order: attacked ECE ascending, the
 * display name breaking ties, the order the section states. */
const eceOfA = (r) => {
  const cal = r.detail && typeof r.detail === "object" ? r.detail.calibration : null;
  const ece = cal && cal.attacked ? cal.attacked.ece : null;
  return ece ?? r.ece_attacked ?? Infinity;
};
const calOrderA = [...calibrationRowsA]
  .sort((a, b) => {
    const ea = eceOfA(a);
    const eb = eceOfA(b);
    if (ea !== eb) return ea - eb;
    return a.display_name < b.display_name ? -1 : 1;
  })
  .map((r) => r.run_id);
/* C-07: the slice panels whose bins coincide, derived from
 * the payload alone. A slice row whose attacked bins span at
 * most a tenth of stated confidence with every bin mean in
 * the top tenth. Mirrors the component's rule. */
const coincidentSliceIdsA = new Set(
  allRowsA
    .filter((r) => r.n_cases !== fullCasesA)
    .filter((r) => {
      const bins =
        r.detail?.calibration?.reliability_bins?.attacked?.bins ?? [];
      if (bins.length === 0) return false;
      const fs = bins.map((b) => b.mean_forecast);
      return Math.max(...fs) - Math.min(...fs) <= 0.1 && Math.min(...fs) >= 0.9;
    })
    .map((r) => r.run_id),
);
/* The section bar's nine links, id and label, in bar order. */
const NAV_A = [
  ["cost", "Scatter"],
  ["ranking", "Ranking"],
  ["flagged", "Flagged"],
  ["malformed", "Malformed"],
  ["families", "Families"],
  ["calibration", "Calibration"],
  ["compare", "Compare"],
  ["models", "Models"],
  ["method", "Method"],
];
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
}

/* ---------- calibration battery, heatmap names, section bar ---------- */

/* The calibration battery (C-01 to C-08), restored from the
 * card grid board's audit onto the retained panels. One
 * measurement pass per width, then the assertions. */
async function calibrationChecks(page, width) {
  const cal = await page.evaluate(() => {
    const csec = document.querySelector('[data-section="calibration"]');
    if (!csec) return null;
    const cSecRect = csec.getBoundingClientRect();
    return {
      lede: (csec.querySelector(".sechead .cap")?.textContent ?? "")
        .replace(/\s+/g, " ")
        .trim(),
      secL: cSecRect.left,
      secR: cSecRect.right,
      gridCols: getComputedStyle(
        csec.querySelector(".cal-grid"),
      ).gridTemplateColumns.split(" ").filter(Boolean).length,
      panels: [...csec.querySelectorAll(".cal-panel")].map((p) => {
        const meta = p.querySelector(".cal-meta")?.textContent ?? "";
        const m = meta.match(/ECE ([\d.]+)/);
        const nameEl = p.querySelector(".cal-name");
        const metaEl = p.querySelector(".cal-meta");
        const noteEl = p.querySelector(".cal-note");
        const svgEl = p.querySelector(".cal-svg");
        const tickEl = p.querySelector(".tk-y text, .tk-x text");
        const tick =
          svgEl && tickEl
            ? {
                font: parseFloat(getComputedStyle(tickEl).fontSize),
                svgW: svgEl.getBoundingClientRect().width,
              }
            : null;
        const tickBoxes = [
          ...p.querySelectorAll(".tk-y text, .tk-x text"),
        ].map((t) => {
          const b = t.getBBox();
          return { x0: b.x, y0: b.y, x1: b.x + b.width, y1: b.y + b.height };
        });
        const tkY = p.querySelector(".tk-y");
        const tkX = p.querySelector(".tk-x");
        const tkShown = {
          y: tkY ? getComputedStyle(tkY).display !== "none" : false,
          x: tkX ? getComputedStyle(tkX).display !== "none" : false,
        };
        const nameTextEl = p.querySelector(".cal-name-text");
        const nameNode = nameTextEl ? nameTextEl.firstChild : null;
        const lineMap = new Map();
        if (nameNode) {
          for (let i = 0; i < nameNode.length; i++) {
            const range = document.createRange();
            range.setStart(nameNode, i);
            range.setEnd(nameNode, i + 1);
            const rect = range.getClientRects()[0];
            if (!rect) continue;
            const key = Math.round(rect.top);
            lineMap.set(key, (lineMap.get(key) ?? "") + nameNode.textContent[i]);
          }
        }
        const nameLines = [...lineMap.entries()]
          .sort((a, b) => a[0] - b[0])
          .map(([, t]) => t);
        return {
          id: p.getAttribute("data-run-id"),
          nameLines,
          tick,
          tickBoxes,
          tkShown,
          note: noteEl
            ? noteEl.textContent.replace(/\s+/g, " ").trim()
            : null,
          ece: m ? m[1] : null,
          nameClip: nameEl
            ? nameEl.scrollWidth > nameEl.clientWidth + 1
            : null,
          metaClip: metaEl
            ? metaEl.scrollWidth > metaEl.clientWidth + 1
            : null,
        };
      }),
      rail: [...csec.querySelectorAll(".cal-rail-link")].map((a) =>
        a.getAttribute("data-rail-for"),
      ),
      railLinks: [...csec.querySelectorAll(".cal-rail-link")].map((a) => {
        const r = a.getBoundingClientRect();
        return { t: r.top, b: r.bottom };
      }),
      railNames: [...csec.querySelectorAll(".cal-rail-name")].map((n) => {
        const r = n.getBoundingClientRect();
        return {
          sw: n.scrollWidth,
          cw: n.clientWidth,
          text: n.textContent.trim(),
          l: r.left,
          r: r.right,
        };
      }),
    };
  });
  if (!cal) {
    fail(`width ${width}: calibration section not rendered`);
    return;
  }
  /* Population and order: every panel the payload carries
   * bins for, in the order the section states (C-08's base
   * fact, from which the edge rule below is read). */
  const panelIds = cal.panels.map((p) => p.id);
  if (JSON.stringify(panelIds) !== JSON.stringify(calOrderA)) {
    fail(
      `width ${width}: calibration panels stand in order ${panelIds.join(", ")}, expected attacked ECE order ${calOrderA.join(", ")}`,
    );
  }
  const railIds = cal.rail;
  if (JSON.stringify(railIds) !== JSON.stringify(calOrderA)) {
    fail(`width ${width}: calibration rail order is not the panel order`);
  }
  for (const p of cal.panels) {
    const row = byRunIdA.get(p.id);
    if (!row) continue;
    const expectedEce = quantA(expandDecA(eceOfA(row)), 3);
    if (p.ece !== expectedEce) {
      fail(
        `width ${width}: calibration panel ${p.id} header ECE ${p.ece}, payload gives ${expectedEce}`,
      );
    }
    if (p.nameClip) {
      fail(`width ${width}: calibration panel name clipped on ${p.id}`);
    }
    if (p.metaClip) {
      fail(`width ${width}: calibration panel meta clipped on ${p.id}`);
    }
  }
  /* C-07: no panel carries the coincidence note; the lede
   * states the fact once, with the derived coincident set. */
  for (const p of cal.panels) {
    if (p.note !== null) {
      fail(
        `width ${width}: calibration panel ${p.id} carries a coincidence note ("${p.note}"); the fact belongs in the lede (C-07)`,
      );
    }
  }
  const nCoincident = coincidentSliceIdsA.size;
  if (nCoincident > 0) {
    const coincidentNames = calOrderA
      .filter((id) => coincidentSliceIdsA.has(id))
      .map((id) => shortName(byRunIdA.get(id)));
    const list =
      coincidentNames.length > 1
        ? `${coincidentNames.slice(0, -1).join(", ")} and ${coincidentNames[coincidentNames.length - 1]}`
        : (coincidentNames[0] ?? "");
    const want = `${nCoincident} slice result${nCoincident === 1 ? "" : "s"}, ${list}, state${nCoincident === 1 ? "s" : ""} nearly the same confidence from bin to bin, so their bins pile up at the right edge of their panels`;
    if (!cal.lede.includes(want)) {
      fail(
        `width ${width}: calibration lede does not state the coincidence ("${want}") (C-07)`,
      );
    }
  } else if (cal.lede.includes("pile up at the right edge")) {
    fail(
      `width ${width}: calibration lede states a coincidence the payload does not hold (C-07)`,
    );
  }
  /* C-01: tick numerals render at the 10 px floor. */
  let worstTick = Infinity;
  for (const p of cal.panels) {
    if (!p.tick || !(p.tick.svgW > 0)) continue;
    worstTick = Math.min(worstTick, (p.tick.font * p.tick.svgW) / 300);
  }
  if (worstTick !== Infinity) {
    note(
      `width ${width}: calibration tick numerals render at ${worstTick.toFixed(1)} px at their smallest (floor 10 px, C-01)`,
    );
    if (worstTick < 9.9) {
      fail(
        `width ${width}: calibration tick numerals render at ${worstTick.toFixed(1)} px, under the 10 px legibility floor (C-01)`,
      );
    }
  }
  /* C-06: every tick numeral's box stays inside the viewBox
   * (tolerance 2 units for font bearing slack). */
  for (const p of cal.panels) {
    for (const b of p.tickBoxes ?? []) {
      if (b.x0 < -2 || b.x1 > 302 || b.y0 < -2 || b.y1 > 168) {
        fail(
          `width ${width}: calibration panel ${p.id} tick numeral box ${b.x0.toFixed(0)}..${b.x1.toFixed(0)} x ${b.y0.toFixed(0)}..${b.y1.toFixed(0)} escapes the 300 x 166 viewBox (C-06)`,
        );
      }
    }
  }
  /* C-08, asserted literally at every width. The panels
   * showing each axis are exactly the array's edge panels
   * for the layout in force. On desktop the first column
   * shows y ticks and the last row shows x ticks. On the
   * phone (one across) every panel shows both. */
  {
    const panels = cal.panels;
    const cols = cal.gridCols || 4;
    const n = panels.length;
    const lastRow = n % cols === 0 ? cols : n % cols;
    panels.forEach((p, i) => {
      if (!p.tick || !p.tkShown) return;
      const wantY = width <= 760 ? true : i % cols === 0;
      const wantX = width <= 760 ? true : i >= n - lastRow;
      if (p.tkShown.y !== wantY || p.tkShown.x !== wantX) {
        fail(
          `width ${width}: calibration panel ${p.id} tick visibility (y ${p.tkShown.y}, x ${p.tkShown.x}) breaks the array's edge rule (want y ${wantY}, x ${wantX}) (C-08)`,
        );
      }
    });
  }
  /* C-02: on the phone the rail is a list, one entry per line. */
  if (width <= 760 && cal.railLinks) {
    let shared = 0;
    const links = cal.railLinks;
    for (let i = 0; i < links.length; i++) {
      for (let j = i + 1; j < links.length; j++) {
        if (links[i].t < links[j].b - 2 && links[j].t < links[i].b - 2) {
          shared++;
        }
      }
    }
    if (shared > 0) {
      fail(
        `width ${width}: ${shared} calibration rail entry pairs share a line (C-02)`,
      );
    }
  }
  /* C-04: a wrapped panel name breaks only after a hyphen
   * or a space, and never strands its final hyphen segment
   * alone on the last line. */
  for (const p of cal.panels) {
    const lines = p.nameLines ?? [];
    for (let i = 0; i < lines.length - 1; i++) {
      const legal = /[-\s]$/.test(lines[i]) || /^\s/.test(lines[i + 1]);
      if (!legal) {
        fail(
          `width ${width}: calibration panel ${p.id} name breaks mid-token ("${lines[i]} | ${lines[i + 1]}") (C-04)`,
        );
      }
    }
    if (lines.length >= 2) {
      const last = lines[lines.length - 1].trim();
      const prev = lines[lines.length - 2].trimEnd();
      if (last.length <= 5 && !last.includes("-") && prev.endsWith("-")) {
        fail(
          `width ${width}: calibration panel ${p.id} name strands its final segment "${last}" alone on the last line (C-04)`,
        );
      }
    }
  }
  /* C-05: rail names stay inside the section's horizontal
   * bounds, and unclipped. */
  for (const rn of cal.railNames) {
    if (rn.l < cal.secL - 1 || rn.r > cal.secR + 1) {
      fail(
        `width ${width}: calibration rail name "${rn.text}" sits outside the section bounds (C-05)`,
      );
    }
    if (rn.sw > rn.cw + 1) {
      fail(
        `width ${width}: calibration rail name "${rn.text}" is clipped (C-05)`,
      );
    }
  }
}

/* Heatmap names: family headers neither wrap nor clip, and
 * row names render unclipped, at every width. */
async function heatmapChecks(page, width) {
  const heat = await page.evaluate(() => {
    const sec = document.querySelector('[data-section="heatmap"]');
    if (!sec) return null;
    return {
      heads: [...sec.querySelectorAll(".heat-head")].map((h) => ({
        family: h.getAttribute("data-family"),
        sw: h.scrollWidth,
        cw: h.clientWidth,
        sh: h.scrollHeight,
        ch: h.clientHeight,
      })),
      names: [...sec.querySelectorAll(".heat-name")].map((n) => ({
        id: n.getAttribute("data-run-id"),
        sw: n.scrollWidth,
        cw: n.clientWidth,
      })),
    };
  });
  if (!heat) {
    fail(`width ${width}: heatmap section not rendered`);
    return;
  }
  for (const h of heat.heads) {
    if (h.sw > h.cw + 1 || h.sh > h.ch + 1) {
      fail(
        `width ${width}: heatmap family header "${h.family}" wraps or clips (${h.sw}x${h.sh} in ${h.cw}x${h.ch})`,
      );
    }
  }
  for (const n of heat.names) {
    if (n.sw > n.cw + 1) {
      fail(`width ${width}: heatmap row name for ${n.id} is clipped`);
    }
  }
}

/* Scatter clearance (the mock's standard, measured on the
 * rendered wide panel). In-plot label boxes intersect
 * neither each other nor any disc, and every rail name
 * keeps at least 4 units clear of its rate figure. */
async function scatterClearanceChecks(page) {
  const geo = await page.evaluate(() => {
    const svg = document.querySelector(
      '[data-section="scatter"] .scatter-wide svg',
    );
    if (!svg) return null;
    const box = (el) => {
      const b = el.getBBox();
      return { x0: b.x, y0: b.y, x1: b.x + b.width, y1: b.y + b.height };
    };
    return {
      labels: [...svg.querySelectorAll(".svg-label")].map((t) => ({
        id: t.getAttribute("data-label-for"),
        box: box(t),
      })),
      discs: [...svg.querySelectorAll("g.svg-point")].map((g) => {
        const c = g.querySelector("circle.disc");
        return {
          id: g.getAttribute("data-point-for"),
          cx: Number(c.getAttribute("cx")),
          cy: Number(c.getAttribute("cy")),
          r: Number(c.getAttribute("r")),
        };
      }),
      rail: [...svg.querySelectorAll(".svg-rail-row")].map((g) => {
        const n = g.querySelector(".svg-rail-name");
        const r = g.querySelector(".svg-rail-rate");
        return {
          name: n?.textContent ?? "",
          nameBox: n ? box(n) : null,
          rateBox: r ? box(r) : null,
        };
      }),
    };
  });
  if (!geo) {
    fail("scatter clearance: the wide scatter panel is not rendered");
    return;
  }
  const hit = (a, b, pad) =>
    a.x0 < b.x1 - pad && b.x0 < a.x1 - pad && a.y0 < b.y1 - pad && b.y0 < a.y1 - pad;
  for (let i = 0; i < geo.labels.length; i++) {
    for (let j = i + 1; j < geo.labels.length; j++) {
      if (hit(geo.labels[i].box, geo.labels[j].box, 1)) {
        fail(
          `scatter label for ${geo.labels[i].id} intersects the label for ${geo.labels[j].id}`,
        );
      }
    }
    for (const d of geo.discs) {
      const db = { x0: d.cx - d.r, y0: d.cy - d.r, x1: d.cx + d.r, y1: d.cy + d.r };
      if (hit(geo.labels[i].box, db, 0.5)) {
        fail(
          `scatter label for ${geo.labels[i].id} intersects the disc for ${d.id}`,
        );
      }
    }
  }
  for (const row of geo.rail) {
    if (row.nameBox && row.rateBox && row.nameBox.x1 > row.rateBox.x0 - 4) {
      fail(
        `scatter rail name "${row.name}" reaches ${row.nameBox.x1.toFixed(0)} against its rate figure at ${row.rateBox.x0.toFixed(0)}, leaving no clearance`,
      );
    }
  }
  note(
    `scatter clearance measured over ${geo.labels.length} labels, ${geo.discs.length} discs, ${geo.rail.length} rail rows`,
  );
}

/* The section bar: exact links, target sizes, and phone
 * reachability, at every width. */
async function navChecks(page, width) {
  const nav = await page.evaluate(() => {
    const navEl = document.querySelector(".section-nav");
    if (!navEl) return null;
    const out = {
      position: getComputedStyle(navEl).position,
      links: [...navEl.querySelectorAll(".section-nav-link")].map((a) => {
        const r = a.getBoundingClientRect();
        return {
          target: a.getAttribute("data-nav-target"),
          label: a.textContent.trim(),
          href: a.getAttribute("href"),
          w: r.width,
          h: r.height,
        };
      }),
      phone: null,
    };
    if (window.innerWidth <= 760) {
      const inner = navEl.querySelector(".section-nav-inner");
      const reach = [];
      if (inner) {
        for (const a of inner.querySelectorAll(".section-nav-link")) {
          const ir0 = inner.getBoundingClientRect();
          const lr0 = a.getBoundingClientRect();
          inner.scrollLeft += lr0.left - ir0.left;
          const ir = inner.getBoundingClientRect();
          const lr = a.getBoundingClientRect();
          reach.push({
            target: a.getAttribute("data-nav-target"),
            inStrip: lr.left >= ir.left - 0.5 && lr.right <= ir.right + 0.5,
            untruncated: a.scrollWidth <= a.clientWidth + 1,
          });
        }
        inner.scrollLeft = 0;
      }
      out.phone = {
        docScrollWidth: document.documentElement.scrollWidth,
        viewportWidth: window.innerWidth,
        reach,
      };
    }
    return out;
  });
  if (!nav) {
    fail(`width ${width}: section nav not rendered`);
    return;
  }
  if (nav.position !== "sticky") {
    fail(`width ${width}: section nav computes position ${nav.position}, not sticky`);
  }
  if (nav.links.length !== NAV_A.length) {
    fail(
      `width ${width}: section nav holds ${nav.links.length} links, expected ${NAV_A.length}`,
    );
  }
  nav.links.forEach((link, i) => {
    const [id, label] = NAV_A[i] ?? [];
    if (link.target !== id || link.href !== `#${id}` || link.label !== label) {
      fail(
        `width ${width}: nav link ${i + 1} is "${link.label}" to ${link.href} (target ${link.target}), expected "${label}" to #${id}`,
      );
    }
    if (link.w < 24 || link.h < 24) {
      fail(
        `width ${width}: nav link "${link.label}" measures ${link.w.toFixed(1)}x${link.h.toFixed(1)} px, under the 24 px target floor`,
      );
    }
  });
  if (width <= 760) {
    const phone = nav.phone;
    if (!phone) {
      fail(`width ${width}: phone nav reachability not measured`);
    } else {
      if (phone.docScrollWidth !== phone.viewportWidth) {
        fail(
          `width ${width}: document scroll width is ${phone.docScrollWidth}, the viewport is ${phone.viewportWidth} (the nav must not widen the document)`,
        );
      }
      for (const r of phone.reach) {
        if (!r.inStrip) {
          fail(
            `width ${width}: nav link "${r.target}" cannot be scrolled fully into the nav strip`,
          );
        }
        if (!r.untruncated) {
          fail(`width ${width}: nav link "${r.target}" text is truncated inside the strip`);
        }
      }
    }
  }
}

/* The section bar's behaviour at desktop: the keyboard
 * walk, keyboard activation landings, and the scrollspy. */
async function navSession(page) {
  const checkLanding = (what, top, navBottom) => {
    if (
      top === undefined ||
      navBottom === undefined ||
      top < navBottom - 1 ||
      top > navBottom + 40
    ) {
      fail(
        `${what} lands with its top at ${top} px against a bar bottom of ${navBottom} px, outside the bar rule`,
      );
    }
  };
  /* Keyboard walk. Tab from the top of the page until every
   * nav link has held focus. Each focused link must sit
   * inside the viewport, uncovered at its centre, with the
   * focus outline showing. The walk starts from the skip
   * link, the page's first tab stop. */
  await page.evaluate(() => {
    window.scrollTo(0, 0);
    document.querySelector(".skip")?.focus();
  });
  await new Promise((r) => setTimeout(r, 250));
  const seenNav = new Map();
  const walkTrail = [];
  for (let i = 0; i < 64 && seenNav.size < NAV_A.length; i++) {
    await page.keyboard.press("Tab");
    await new Promise((r) => setTimeout(r, 70));
    const info = await page.evaluate(() => {
      const el = document.activeElement;
      if (!el || el === document.body || !el.getAttribute) return null;
      const desc = `${el.tagName}.${(el.getAttribute("class") ?? "").split(" ")[0]} ${el.getAttribute("href") ?? ""} ${(el.textContent ?? "").trim().slice(0, 24)}`;
      const target = el.getAttribute("data-nav-target");
      if (!target) return { desc };
      const r = el.getBoundingClientRect();
      const cs = getComputedStyle(el);
      const topEl = document.elementFromPoint(
        r.left + r.width / 2,
        r.top + r.height / 2,
      );
      return {
        desc,
        target,
        top: r.top,
        bottom: r.bottom,
        outlineStyle: cs.outlineStyle,
        outlineWidth: cs.outlineWidth,
        covered: !(topEl === el || el.contains(topEl)),
      };
    });
    if (info && walkTrail.length < 16) walkTrail.push(info.desc);
    if (info?.target && !seenNav.has(info.target)) {
      seenNav.set(info.target, info);
    }
  }
  if (seenNav.size !== NAV_A.length) {
    fail(
      `tab walk reached ${seenNav.size} of ${NAV_A.length} nav links (${[...seenNav.keys()].join(",")}); the walk saw: ${walkTrail.join(" | ")}`,
    );
  }
  for (const [id, info] of seenNav) {
    if (info.top < -1 || info.bottom > 901) {
      fail(
        `focused nav link ${id} sits at ${info.top.toFixed(1)} to ${info.bottom.toFixed(1)} px, outside the viewport`,
      );
    }
    if (info.covered) {
      fail(`focused nav link ${id} is covered at its centre`);
    }
    if (info.outlineStyle === "none" || info.outlineWidth === "0px") {
      fail(
        `focused nav link ${id} shows no focus outline (${info.outlineStyle} ${info.outlineWidth})`,
      );
    }
  }
  /* Anchor landings. Each nav link, focused and activated
   * from the keyboard, takes its section to the bar rule,
   * and the address follows. */
  for (const [id] of NAV_A) {
    await page.evaluate((tid) => {
      document
        .querySelector(`.section-nav-link[data-nav-target="${tid}"]`)
        ?.focus();
    }, id);
    await page.keyboard.press("Enter");
    await new Promise((r) => setTimeout(r, 400));
    const land = await page.evaluate((tid) => ({
      top: document.getElementById(tid)?.getBoundingClientRect().top,
      navBottom: document
        .querySelector(".section-nav")
        ?.getBoundingClientRect().bottom,
      hash: location.hash,
    }), id);
    if (land.hash !== `#${id}`) {
      fail(`nav activation ${id} leaves the address at ${land.hash}`);
    }
    checkLanding(`nav activation #${id}`, land.top, land.navBottom);
  }
  /* Scrollspy. Scroll the calibration section into view and
   * prove the spy marks it, with the bar's height and the
   * document's height unchanged by the marking. */
  const spyBefore = await page.evaluate(() => ({
    navH: document.querySelector(".section-nav")?.getBoundingClientRect().height,
    docH: document.documentElement.scrollHeight,
  }));
  await page.evaluate(() => {
    document.getElementById("calibration")?.scrollIntoView();
  });
  await new Promise((r) => setTimeout(r, 650));
  const spy = await page.evaluate(() => {
    const act = [...document.querySelectorAll(".section-nav-link.active")];
    return {
      count: act.length,
      target: act[0]?.getAttribute("data-nav-target") ?? null,
      aria: act[0]?.getAttribute("aria-current") ?? null,
      navH: document.querySelector(".section-nav")?.getBoundingClientRect().height,
      docH: document.documentElement.scrollHeight,
    };
  });
  if (spy.count !== 1 || spy.target !== "calibration") {
    fail(
      `scrollspy marks ${spy.count} link(s), target ${spy.target}, with calibration in view`,
    );
  }
  if (spy.aria !== "true") {
    fail(`scrollspy's active link carries aria-current ${spy.aria}`);
  }
  if (spy.navH !== spyBefore.navH || spy.docH !== spyBefore.docH) {
    fail(
      `scrollspy shifted layout: bar ${spyBefore.navH} to ${spy.navH} px, document ${spyBefore.docH} to ${spy.docH} px`,
    );
  }
  if (shotsDir) {
    await page.screenshot({ path: join(shotsDir, "nav-scrolled-1440.png") });
  }
}

/* ---------- the width loop ---------- */

for (const width of [1440, 1280, 1100, 900, 760, 500]) {
  const page = await load(width);
  await structureChecks(page, width);
  await calibrationChecks(page, width);
  await heatmapChecks(page, width);
  await navChecks(page, width);
  if (width === 1440) {
    await desktopChecks(page);
    await scatterClearanceChecks(page);
    await navSession(page);
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
  await calibrationChecks(page, 390);
  await heatmapChecks(page, 390);
  await navChecks(page, 390);
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
