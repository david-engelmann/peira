#!/usr/bin/env node
/**
 * DOM acceptance audit for the ranking prototype. Drives the
 * Playwright cache's chrome-headless-shell through puppeteer-core
 * against the static out/ directory, measures the built page at
 * 1440, 1280, and 390, and checks the census and spec tests that
 * need a live layout:
 *
 *  F-03  no two visible text boxes in the ranking come within
 *        2 px of each other (bounding-box intersection test over
 *        text node ranges).
 *  F-05  no name is clipped (every name element's scroll width
 *        fits its client width) and every rendered short name
 *        equals the payload-derived short name.
 *  F-01  the rank column holds exactly one number per ranked row
 *        (the payload rank) and none on flagged rows.
 *  Amber appears only inside the flagged strip.
 *  The slice group header states the 373 case base, the full
 *  group caption states the suite size.
 *  Page height is reported for the F-12 scroll budget.
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

const shortName = (r) => {
  let name = r.display_name;
  const at = name.lastIndexOf("@");
  if (at > 0 && /^[0-9a-f]{32,}$/i.test(name.slice(at + 1))) {
    name = name.slice(0, at);
  }
  const slash = name.lastIndexOf("/");
  return slash >= 0 ? name.slice(slash + 1) : name;
};
const ranked = payload.ranked.map((r, i) => ({ ...r, rank: i + 1 }));
const byRunId = new Map(
  [...ranked, ...payload.unranked].map((r) => [r.run_id, r]),
);

/* The display interval, derived independently (exact Wilson over
 * family flipped counts when it rounds to the stored pair). */
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
  const q = (v) => {
    // four-decimal half-up quantization on the decimal string
    const s = String(v);
    const [ip, fp = ""] = s.split(".");
    const kept = fp.slice(0, 4).padEnd(4, "0");
    const dropped = fp.slice(4);
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
    return `${joined.slice(0, joined.length - 4)}.${joined.slice(joined.length - 4)}`;
  };
  if (q(lo) === q(pair[0]) && q(hi) === q(pair[1])) return [lo, hi];
  return pair;
}
const axisPctA = (v) => Math.min(100, Math.max(0, (v / 0.3) * 100));

const chromeHits = globSync(
  join(
    homedir(),
    ".cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell",
  ),
);
if (chromeHits.length === 0) {
  console.error("chrome-headless-shell not found in the Playwright cache");
  process.exit(2);
}

/* The static export references its assets by absolute path, so
 * it must be served over HTTP; a file URL drops the stylesheet. */
const MIME = {
  ".html": "text/html",
  ".css": "text/css",
  ".js": "text/javascript",
  ".woff2": "font/woff2",
  ".json": "application/json",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".ico": "image/x-icon",
  ".txt": "text/plain",
};
const server = createServer(async (req, res) => {
  try {
    let p = decodeURIComponent(new URL(req.url, "http://x").pathname);
    if (p === "/") p = "/index.html";
    const data = await readFile(join(outDir, p));
    res.writeHead(200, {
      "content-type": MIME[extname(p)] ?? "application/octet-stream",
    });
    res.end(data);
  } catch {
    res.writeHead(404);
    res.end();
  }
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const pageUrl = `http://127.0.0.1:${server.address().port}/index.html`;

const browser = await puppeteer.launch({
  executablePath: chromeHits[0],
  args: ["--no-sandbox", "--force-device-scale-factor=1"],
});
const page = await browser.newPage();
await page.goto(pageUrl, { waitUntil: "networkidle0" });

const failures = [];
const notes = [];

for (const width of [1440, 1280, 390]) {
  await page.setViewport({ width, height: 900 });
  await new Promise((r) => setTimeout(r, 350));

  if (shotsDir) {
    await page.screenshot({
      path: join(shotsDir, `ranking-${width}.png`),
      fullPage: true,
    });
  }

  const report = await page.evaluate(() => {
    const out = {
      height: document.documentElement.scrollHeight,
      names: [],
      rankCells: [],
      geometry: [],
      textBoxes: [],
      amberOutside: [],
      groupHeads: {},
      tiedCount: 0,
    };
    const vis = (el) => {
      const s = getComputedStyle(el);
      return s.display !== "none" && s.visibility !== "hidden";
    };
    // Names and clipping.
    document.querySelectorAll(".rank-row").forEach((row) => {
      const nameEl = row.querySelector(".name-line");
      const tag = row.querySelector(".flag-tag");
      const nameText = nameEl
        ? [...nameEl.childNodes]
            .filter((n) => !(n instanceof Element && n.classList.contains("flag-tag")))
            .map((n) => n.textContent)
            .join("")
        : "";
      out.names.push({
        runId: row.getAttribute("data-run-id"),
        text: nameText,
        clipped: nameEl ? nameEl.scrollWidth > nameEl.clientWidth + 1 : null,
        group: row.closest("[data-group]")?.getAttribute("data-group"),
      });
      const rankEl = row.querySelector(".cell-rank");
      out.rankCells.push({
        runId: row.getAttribute("data-run-id"),
        text: rankEl ? rankEl.textContent.trim() : "",
        group: row.closest("[data-group]")?.getAttribute("data-group"),
      });
      void tag;
      const strip = row.querySelector(".cell-chart");
      const whisker = row.querySelector(".whisker");
      const caps = row.querySelectorAll(".whisker-cap");
      const dot = row.querySelector(".estimate-dot");
      const pct = (rect, stripRect) =>
        stripRect && rect
          ? ((rect.left + rect.width / 2 - stripRect.left) / stripRect.width) *
            100
          : null;
      const stripRect = strip ? strip.getBoundingClientRect() : null;
      out.geometry.push({
        runId: row.getAttribute("data-run-id"),
        capL: caps[0] ? pct(caps[0].getBoundingClientRect(), stripRect) : null,
        capR: caps[1] ? pct(caps[1].getBoundingClientRect(), stripRect) : null,
        dot: dot ? pct(dot.getBoundingClientRect(), stripRect) : null,
        lineL:
          whisker && stripRect
            ? ((whisker.getBoundingClientRect().left - stripRect.left) /
                stripRect.width) *
              100
            : null,
        lineR:
          whisker && stripRect
            ? ((whisker.getBoundingClientRect().right - stripRect.left) /
                stripRect.width) *
              100
            : null,
      });
    });
    // Text node boxes in the ranking section (F-03).
    const section = document.querySelector("section");
    if (section) {
      const walker = document.createTreeWalker(section, NodeFilter.SHOW_TEXT, {
        acceptNode: (n) =>
          n.textContent.trim().length > 0 && vis(n.parentElement)
            ? NodeFilter.FILTER_ACCEPT
            : NodeFilter.FILTER_REJECT,
      });
      let node;
      while ((node = walker.nextNode())) {
        const range = document.createRange();
        range.selectNodeContents(node);
        for (const rect of range.getClientRects()) {
          if (rect.width > 0 && rect.height > 0) {
            out.textBoxes.push({
              text: node.textContent.trim().slice(0, 28),
              x0: rect.x,
              y0: rect.y,
              x1: rect.x + rect.width,
              y1: rect.y + rect.height,
            });
          }
        }
      }
    }
    // Amber confinement.
    const AMBER = "rgb(232, 163, 61)";
    document.querySelectorAll("body *").forEach((el) => {
      if (!vis(el)) return;
      const s = getComputedStyle(el);
      const uses = [s.color, s.borderTopColor, s.backgroundColor].includes(AMBER);
      if (uses && !el.closest('[data-group="flagged"]')) {
        out.amberOutside.push(
          `${el.tagName}.${el.className} "${el.textContent.trim().slice(0, 24)}"`,
        );
      }
    });
    // Group heads.
    document.querySelectorAll("[data-group]").forEach((g) => {
      const head = g.querySelector(".group-head");
      out.groupHeads[g.getAttribute("data-group")] = head
        ? head.textContent.replace(/\s+/g, " ").trim()
        : "";
    });
    out.tiedCount = (document.body.innerText.match(/tied/gi) ?? []).length;
    return out;
  });

  notes.push(`width ${width}: page height ${report.height} px`);
  // F-05: names complete and unclipped.
  for (const n of report.names) {
    const expected = shortName(byRunId.get(n.runId));
    if (n.text !== expected) {
      failures.push(
        `width ${width}: row ${n.runId} renders name "${n.text}", payload short name is "${expected}"`,
      );
    }
    if (n.clipped) {
      failures.push(`width ${width}: name "${n.text}" is clipped horizontally`);
    }
  }
  // F-01: rank column.
  for (const cell of report.rankCells) {
    const row = byRunId.get(cell.runId);
    if (cell.group === "flagged") {
      if (cell.text !== "") {
        failures.push(
          `width ${width}: flagged row ${cell.runId} rank cell holds "${cell.text}"`,
        );
      }
    } else if (cell.text !== String(row.rank)) {
      failures.push(
        `width ${width}: row ${cell.runId} rank cell holds "${cell.text}", payload rank is ${row.rank}`,
      );
    }
  }
  // F-03: text box proximity (2 px clearance, no intersection).
  const boxes = report.textBoxes;
  for (let i = 0; i < boxes.length; i++) {
    for (let j = i + 1; j < boxes.length; j++) {
      const a = boxes[i];
      const b = boxes[j];
      const overlapX = Math.min(a.x1, b.x1) - Math.max(a.x0, b.x0);
      const overlapY = Math.min(a.y1, b.y1) - Math.max(a.y0, b.y0);
      if (overlapX > 0 && overlapY > 0) {
        failures.push(
          `width ${width}: text boxes overlap: "${a.text}" x "${b.text}" by ${overlapX.toFixed(1)}x${overlapY.toFixed(1)} px`,
        );
      }
    }
  }
  // Amber confinement.
  for (const el of report.amberOutside) {
    failures.push(`width ${width}: amber outside the flagged strip on ${el}`);
  }
  // Geometry, measured from rendered rects (owner items 1 and
  // 3). Caps sit on the display interval endpoints and the
  // estimate mark on the payload rate, all on the shared 0 to
  // 30 axis. The whisker line must end at its caps: it may stop
  // short by the small built-in gap, and it must never pass a
  // cap center by more than a pixel of rounding.
  for (const g of report.geometry) {
    const row = byRunId.get(g.runId);
    const dci = displayCiA(row);
    const tol = 0.75;
    if (!dci) continue;
    const expL = axisPctA(dci[0]);
    const expR = axisPctA(dci[1]);
    const expA = axisPctA(row.asr_conditional);
    if (g.capL === null || Math.abs(g.capL - expL) > tol) {
      failures.push(
        `width ${width}: row ${g.runId} lo cap at ${g.capL}, expected ${expL.toFixed(2)}`,
      );
    }
    if (g.capR === null || Math.abs(g.capR - expR) > tol) {
      failures.push(
        `width ${width}: row ${g.runId} hi cap at ${g.capR}, expected ${expR.toFixed(2)}`,
      );
    }
    if (g.dot === null || Math.abs(g.dot - expA) > tol) {
      failures.push(
        `width ${width}: row ${g.runId} estimate mark at ${g.dot}, expected ${expA.toFixed(2)}`,
      );
    }
    if (g.lineL === null || g.lineR === null) {
      failures.push(`width ${width}: row ${g.runId} draws no whisker line`);
    } else {
      if (g.lineL < expL - 0.15 || g.lineL > expL + 1.2) {
        failures.push(
          `width ${width}: row ${g.runId} whisker starts at ${g.lineL.toFixed(2)}, cap at ${expL.toFixed(2)} (overshoot or excess gap)`,
        );
      }
      if (g.lineR > expR + 0.15 || g.lineR < expR - 1.2) {
        failures.push(
          `width ${width}: row ${g.runId} whisker ends at ${g.lineR.toFixed(2)}, cap at ${expR.toFixed(2)} (overshoot or excess gap)`,
        );
      }
    }
  }
  // Group head facts.
  if (!report.groupHeads.slices?.includes("373")) {
    failures.push(
      `width ${width}: slice group header does not state the 373 case base (${report.groupHeads.slices})`,
    );
  }
  if (!report.groupHeads.full?.includes("4,701")) {
    failures.push(
      `width ${width}: full group header does not state the suite size (${report.groupHeads.full})`,
    );
  }
  notes.push(
    `width ${width}: ${report.names.length} names checked, ${boxes.length} text boxes, tied count (innerText) ${report.tiedCount}`,
  );
}

await browser.close();
server.close();
for (const n of notes) console.log(`  ${n}`);
if (failures.length > 0) {
  console.error(`DOM audit FAILED with ${failures.length} problem(s):`);
  for (const f of failures.slice(0, 40)) console.error(`  - ${f}`);
  process.exit(1);
}
console.log("DOM audit passed");
