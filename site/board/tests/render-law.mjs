/**
 * The board's design law as render tests (Maidan transfer 1).
 *
 * Maidan governs its UI with a written law enforced by
 * Playwright specs on real-shaped data. This script does the
 * same for the board: it serves the built static export,
 * loads it in a real chromium at the audited widths on the
 * real staged payload, and asserts the law as measurements,
 * not impressions:
 *
 *  1. No page error at any width. (The 43 result publish
 *     died here: the scatter's label solver threw at fitted
 *     widths and the exception unmounted the whole page.)
 *  2. No horizontal overflow at any width (doctrine D8).
 *  3. Every charted result is named exactly once in the
 *     visible scatter variant: beside its disc, in an
 *     overflow row, or in the fitted list (doctrine D1, D3,
 *     D5). Named nowhere fails; named twice fails.
 *  4. The suite case count appears only inside Method.
 *  5. A flagged result's figure never prints alone (C-5).
 *     The figures and the decompositions are both derived
 *     from the payload at run time, the decompositions by
 *     the same operation lib/payload derives them with,
 *     never written into this file. Inside every carrier
 *     attributed to a flagged result (its ranking row, its
 *     heat cells, its scatter entry or label group, its
 *     model card, its model index summary, a heatmap
 *     caption paragraph), a printed
 *     conditional or unconditional figure must stand with
 *     both decomposition clauses, the genuine flip rate
 *     and the malformed share of counted flips, in the
 *     carrier's text or its titles. Where the sealed
 *     records derive no decomposition for a result, its
 *     figure must not print in those carriers at all. The
 *     card's per-family spark list is judged as its own
 *     carrier (data-spark-for), family by family. A family
 *     figure must carry its own decomposition in the spark
 *     row's title, and a family whose records derive no
 *     decomposition must print suppressed there, dashes
 *     for its value and no figure attribute. A separate
 *     interaction pass then drives both compare
 *     pickers, a flagged result on side A and a second
 *     flagged result on side B, and holds the compare
 *     section to the same pairing on each side, the
 *     headline figure and the family figures alike.
 *     check-integrity enforces the pairing on the
 *     server-rendered page and remains the gate of
 *     record. This law is its rendered companion.
 *  6. At phone width under a coarse pointer, every control
 *     stands at least 44px tall (WCAG 2.5.5, Maidan's touch
 *     law). The candidate set is derived from the rendered
 *     DOM (interactive tags and roles, control-like
 *     display), never a class list, so a new control class
 *     cannot escape the measurement silently.
 *  7. Every printed heat cell's text contrasts at least
 *     4.5 to 1 against its ramp colour (the ramp's step
 *     exists for this; the test is what proves it). The
 *     pass fails when it finds no printed heat cells at
 *     all, so an empty measurement cannot pass in silence.
 *  8. At most one filled accent control per view. The one
 *     signal colour is spent like it costs money. The accent
 *     is read from the rendered page's own --accent token
 *     and parsed the way the browser parses it, so the law
 *     follows the token wherever it moves. A token that
 *     cannot be parsed into a colour fails the law loudly,
 *     naming the token, rather than zeroing the count.
 *  9. No horizontal overflow during a resize either: a
 *     continuous sweep across the full range and back,
 *     measured at every step, not only at resting widths.
 *     (RT-F1: a shrink-proof flex cell sized by its
 *     max-content overflowed a mid band in states the
 *     fresh-load widths never sampled.)
 * 10. The compare table's header names are never cut at
 *     phone widths. Each model name, its text, the vendor
 *     chip, the wire line, and the flagged tag must sit
 *     inside the header cell that carries them, at the
 *     resting pair and at the longest named pair the
 *     pickers hold. The name span, the name text, and the
 *     vendor chip stand in every header, so their absence
 *     on either side fails the law rather than skipping
 *     the part; the wire line and the flagged tag render
 *     only where the row carries them and stay conditional.
 *     (Repair round 2: the restacked head anchored each
 *     name in a cell one column wide, the names ran left
 *     past the cell and the section edge, and no document
 *     overflow grew for Law 2 or the sweep to see, so the
 *     clipping shipped unseen.)
 *
 * Transport is raw CDP over the built-in WebSocket client:
 * the repo's puppeteer-core major no longer speaks the
 * cached chromium's protocol (its navigations fail with
 * ERR_inSUFFICIENT_RESOURCES while the browser itself loads
 * the page fine), so the harness drives the DevTools
 * protocol directly and depends on nothing but node.
 *
 * Usage: node tests/render-law.mjs [--shots]
 * Expects the static export in ../out (run next build first).
 * The build chain runs it: package.json wires it as
 * check:render and chains it at the end of build, after the
 * static export and the other checks. Direct invocation is
 * for iteration.
 * --shots also writes the screenshot set for design review.
 */
import { createServer } from "node:http";
import { spawn } from "node:child_process";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { existsSync } from "node:fs";
import { extname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const BOARD = resolve(fileURLToPath(new URL("..", import.meta.url)));
const OUT = join(BOARD, "out");
const WITH_SHOTS = process.argv.includes("--shots");
const SHOTS = resolve(
  process.env.SHOTS_DIR ??
    join(BOARD, "..", "..", "..", "peira-design-perfection", "redesign-maidan-led", "shots"),
);

const CHROME = `${process.env.HOME}/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell`;
if (!existsSync(CHROME)) {
  console.error("cached chromium headless shell not found");
  process.exit(2);
}

const payload = JSON.parse(
  await readFile(join(BOARD, "data", "payload.json"), "utf8"),
);
const allRows = [...payload.ranked, ...payload.unranked];
const fullCases = Math.max(...allRows.map((r) => r.n_cases));
const charted = allRows.filter((r) => r.n_cases === fullCases);
const chartedIds = charted.map((r) => r.run_id);
const caseCountText = fullCases.toLocaleString("en-US");
/* Law 5's figures and decompositions, derived from the
 * payload's flagged rows at run time (lib/format's fmtPct:
 * percent, one decimal, half up). The decompositions follow
 * lib/payload's flipDecomposition and
 * familyFlipDecomposition operation for operation, so the
 * law expects exactly what the board derives. A whole-row
 * decomposition exists only where the sealed per-family
 * records agree with the printed figure, and a family
 * decomposition only where that family's records agree
 * with its own printed rate. */
const pctText = (v) => `${(Math.round(v * 1000) / 10).toFixed(1)}%`;
const countOf = (x) =>
  typeof x === "number" && Number.isInteger(x) && x >= 0 ? x : null;
const familyRecordsOf = (row) => {
  const detail =
    row.detail !== null && typeof row.detail === "object" ? row.detail : {};
  const raw = detail.families;
  const entries = Array.isArray(raw)
    ? raw
    : raw !== null && typeof raw === "object"
      ? Object.values(raw)
      : [];
  return entries.filter(
    (f) => f !== null && typeof f === "object" && !Array.isArray(f),
  );
};
const flipCountsOf = (fam) => {
  const nf = countOf(fam.n_flipped);
  const fd =
    fam.flip_direction !== null &&
    typeof fam.flip_direction === "object" &&
    !Array.isArray(fam.flip_direction)
      ? fam.flip_direction
      : null;
  const tm = fd ? countOf(fd["to-malformed"]) : null;
  if (nf === null || tm === null || tm > nf) return null;
  return { nf, tm };
};
const decompOf = (row) => {
  const printed = row.asr_conditional;
  if (printed == null) return null;
  const fams = familyRecordsOf(row);
  if (!fams.length) return null;
  let flips = 0;
  let malformed = 0;
  for (const fam of fams) {
    const c = flipCountsOf(fam);
    if (c === null) return null;
    flips += c.nf;
    malformed += c.tm;
  }
  const n = countOf(row.n_eligible);
  if (n === null || n === 0 || flips === 0) return null;
  if (Math.abs(flips / n - printed) > 0.001) return null;
  return {
    genuine: pctText((flips - malformed) / n),
    share: pctText(malformed / flips),
  };
};
const familyDecompsOf = (row) => {
  const out = {};
  for (const fam of familyRecordsOf(row)) {
    if (typeof fam.family !== "string") continue;
    const c = flipCountsOf(fam);
    const n = countOf(fam.n_eligible);
    if (c === null || n === null || n === 0) {
      out[fam.family] = null;
      continue;
    }
    if (typeof fam.asr === "number" && Math.abs(c.nf / n - fam.asr) > 0.001) {
      out[fam.family] = null;
      continue;
    }
    out[fam.family] = {
      flips: c.nf,
      genuine: pctText(c.nf === 0 ? 0 : (c.nf - c.tm) / n),
      share: pctText(c.nf === 0 ? 0 : c.tm / c.nf),
    };
  }
  return out;
};
const familyAsrOf = (row) => {
  const out = {};
  for (const fam of familyRecordsOf(row)) {
    if (typeof fam.family === "string") out[fam.family] = fam.asr ?? null;
  }
  return out;
};
const flaggedFigures = charted
  .filter((r) => r.ranking_eligible === false)
  .map((r) => ({
    runId: r.run_id,
    name: r.display_name,
    figures: [
      r.asr_conditional != null ? pctText(r.asr_conditional) : null,
      r.asr_unconditional != null ? pctText(r.asr_unconditional) : null,
    ].filter(Boolean),
    decomp: decompOf(r),
    families: familyDecompsOf(r),
    familyAsr: familyAsrOf(r),
  }))
  .filter((f) => f.figures.length);

/* ---------- static server for the export ---------- */
const MIME = {
  ".html": "text/html",
  ".js": "text/javascript",
  ".css": "text/css",
  ".json": "application/json",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".woff2": "font/woff2",
  ".txt": "text/plain",
  ".ico": "image/x-icon",
};
const server = createServer(async (req, res) => {
  try {
    let path = decodeURIComponent(new URL(req.url, "http://x").pathname);
    if (path.endsWith("/")) path += "index.html";
    let file = join(OUT, path);
    if (!existsSync(file) && existsSync(file + ".html")) file += ".html";
    if (!existsSync(file)) {
      res.writeHead(404).end("nf");
      return;
    }
    res.writeHead(200, { "content-type": MIME[extname(file)] ?? "application/octet-stream" });
    res.end(await readFile(file));
  } catch {
    res.writeHead(500).end("err");
  }
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const base = `http://127.0.0.1:${server.address().port}/`;

/* ---------- minimal CDP client ---------- */
const DEBUG_PORT = 19331 + Math.floor(Math.random() * 400);
const chrome = spawn(
  CHROME,
  [
    "--no-sandbox",
    "--disable-gpu",
    "--disable-dev-shm-usage",
    "--no-zygote",
    `--remote-debugging-port=${DEBUG_PORT}`,
    "about:blank",
  ],
  { stdio: ["ignore", "ignore", "pipe"] },
);
let version = null;
for (let i = 0; i < 60 && !version; i++) {
  try {
    const resp = await fetch(`http://127.0.0.1:${DEBUG_PORT}/json/version`);
    if (resp.ok) version = await resp.json();
  } catch {
    await new Promise((r) => setTimeout(r, 500));
  }
}
if (!version) {
  /* A startup failure must not leak what is already
   * running: the browser process and the static server
   * both die with this exit. */
  console.error("chromium debugging endpoint never came up");
  chrome.kill();
  server.close();
  process.exit(2);
}
const ws = new WebSocket(version.webSocketDebuggerUrl);
await new Promise((res, rej) => {
  ws.addEventListener("open", res, { once: true });
  ws.addEventListener("error", rej, { once: true });
}).catch((e) => {
  console.error("chromium websocket never opened: " + String(e).slice(0, 120));
  chrome.kill();
  server.close();
  process.exit(2);
});
let msgId = 0;
const pending = new Map();
const eventWaiters = [];
const eventHandlers = new Map();
ws.addEventListener("message", (ev) => {
  const msg = JSON.parse(ev.data);
  if (msg.id !== undefined && pending.has(msg.id)) {
    const { res, rej } = pending.get(msg.id);
    pending.delete(msg.id);
    if (msg.error) rej(new Error(JSON.stringify(msg.error)));
    else res(msg.result);
    return;
  }
  if (msg.method) {
    for (let i = eventWaiters.length - 1; i >= 0; i--) {
      const w = eventWaiters[i];
      if (w.method === msg.method && w.sessionId === msg.sessionId) {
        eventWaiters.splice(i, 1);
        w.res(msg.params);
      }
    }
    const hs = eventHandlers.get(msg.method + "|" + (msg.sessionId ?? "")) ?? [];
    for (const h of hs) h(msg.params);
  }
});
function send(method, params = {}, sessionId) {
  const id = ++msgId;
  return new Promise((res, rej) => {
    pending.set(id, { res, rej });
    ws.send(JSON.stringify({ id, method, params, sessionId }));
  });
}
function waitEvent(method, sessionId, timeout = 90000) {
  return new Promise((res, rej) => {
    const w = { method, sessionId, res };
    eventWaiters.push(w);
    setTimeout(() => {
      const i = eventWaiters.indexOf(w);
      if (i >= 0) {
        eventWaiters.splice(i, 1);
        rej(new Error(`timeout waiting for ${method}`));
      }
    }, timeout);
  });
}
function onEvent(method, sessionId, handler) {
  const key = method + "|" + (sessionId ?? "");
  if (!eventHandlers.has(key)) eventHandlers.set(key, []);
  eventHandlers.get(key).push(handler);
}

const { targetId } = await send("Target.createTarget", { url: "about:blank" });
const { sessionId } = await send("Target.attachToTarget", {
  targetId,
  flatten: true,
});
await send("Page.enable", {}, sessionId);
await send("Runtime.enable", {}, sessionId);
await send("Fetch.enable", { patterns: [{ urlPattern: "*/models/*", requestStage: "Request" }] }, sessionId);
onEvent("Fetch.requestPaused", sessionId, (p) => {
  send("Fetch.failRequest", { requestId: p.requestId, errorReason: "Aborted" }, sessionId).catch(() => {});
});
const pageErrors = [];
onEvent("Runtime.exceptionThrown", sessionId, (p) => {
  pageErrors.push(p.exceptionDetails?.exception?.description ?? p.exceptionDetails?.text ?? "exception");
});

async function evaluate(expression) {
  const r = await send(
    "Runtime.evaluate",
    { expression, returnByValue: true, awaitPromise: true },
    sessionId,
  );
  if (r.exceptionDetails) {
    throw new Error("evaluate failed: " + (r.exceptionDetails.exception?.description ?? r.exceptionDetails.text));
  }
  return r.result.value;
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function loadBoard(width, { coarse = false } = {}) {
  pageErrors.length = 0;
  await send(
    "Emulation.setDeviceMetricsOverride",
    {
      width,
      height: width <= 500 ? 844 : 900,
      deviceScaleFactor: 1,
      mobile: width <= 500,
    },
    sessionId,
  );
  if (coarse) {
    await send("Emulation.setTouchEmulationEnabled", { enabled: true }, sessionId);
    await send(
      "Emulation.setEmulatedMedia",
      {
        media: "",
        features: [
          { name: "pointer", value: "coarse" },
          { name: "hover", value: "none" },
        ],
      },
      sessionId,
    );
  } else {
    await send("Emulation.setEmulatedMedia", { media: "", features: [] }, sessionId).catch(() => {});
  }
  const loaded = waitEvent("Page.loadEventFired", sessionId, 240000).catch(
    () => "timeout",
  );
  await send("Page.navigate", { url: base }, sessionId);
  /* The load event is the contract, but on a contended box
   * it can lag far behind a usable page; a readyState poll
   * races it so a slow load is measured, not fatal. */
  const polled = (async () => {
    for (let i = 0; i < 120; i++) {
      await sleep(2000);
      try {
        const ready = await evaluate(
          `document.readyState === "complete" && !!document.querySelector('[data-section="scatter"]')`,
        );
        if (ready) return "polled";
      } catch {}
    }
    return "timeout";
  })();
  await Promise.race([loaded, polled]);
  if (process.env.LAW_DEBUG) {
    const dbg = await evaluate(
      `location.href + " | labels=" + document.querySelectorAll("[data-label-for]").length + " | sections=" + document.querySelectorAll("[data-section]").length`,
    ).catch((e) => "debug-eval-failed " + String(e).slice(0, 100));
    console.log(`debug width ${width}: ${dbg}`);
  }
  await sleep(700);
  await evaluate(`(async () => {
    const step = Math.round(window.innerHeight * 0.8);
    for (let y = 0; y < document.body.scrollHeight; y += step) {
      window.scrollTo(0, y);
      await new Promise((r) => setTimeout(r, 60));
    }
    window.scrollTo(0, 0);
  })()`);
  await sleep(500);
  return { errors: [...pageErrors] };
}

async function screenshot(path, clip) {
  const params = { format: "png" };
  if (clip) {
    params.clip = { ...clip, scale: 1 };
    params.captureBeyondViewport = true;
  }
  const { data } = await send("Page.captureScreenshot", params, sessionId);
  await writeFile(path, Buffer.from(data, "base64"));
}

/* ---------- the law ---------- */
const failures = [];
const notes = [];
const fail = (msg) => failures.push(msg);
const WIDTHS = [390, 500, 700, 800, 900, 1000, 1280, 1440];

const MEASURE = `(chartedIds, caseCountText, flaggedFigures) => {
  const out = {};
  const vw = window.innerWidth;
  out.overflow =
    Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) - vw;
  out.pastEdge = [];
  for (const el of document.querySelectorAll("body *")) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    if (el.closest(".section-nav-inner")) continue;
    /* The skip link lives off-screen by design until it is
     * focused; that is the accessibility pattern, not an
     * overflow. */
    if (el.classList && el.classList.contains("skip")) continue;
    const style = getComputedStyle(el);
    if (style.position === "fixed") continue;
    /* Content inside a section's own clipping or scrolling
     * container (the heatmap's family scroller, the compare
     * table's) is governed by that container, not the page
     * edge: the page level law is that the document itself
     * never scrolls sideways, measured above. */
    let clipped = false;
    for (let a = el.parentElement; a && a !== document.body; a = a.parentElement) {
      const ox = getComputedStyle(a).overflowX;
      if (ox === "hidden" || ox === "auto" || ox === "scroll") {
        clipped = true;
        break;
      }
    }
    if (clipped) continue;
    if (r.right > vw + 1.5 || r.left < -1.5) {
      out.pastEdge.push(
        el.tagName.toLowerCase() + "." + (el.getAttribute("class") || "").split(" ")[0] +
        " right=" + Math.round(r.right) + " left=" + Math.round(r.left),
      );
      if (out.pastEdge.length >= 4) break;
    }
  }
  const wide = document.querySelector(".scatter-wide");
  const phone = document.querySelector(".scatter-phone");
  const vis = (el) =>
    el && el.getBoundingClientRect().height > 0 && getComputedStyle(el).display !== "none";
  const variant = vis(wide) ? wide : phone;
  out.variant = vis(wide) ? "wide" : "phone";
  const named = new Map();
  if (variant) {
    /* A point's naming carrier is its label text: a placed
     * label, a rail label, or an overflow row's name text
     * (the row group also carries data-entry-for, which is
     * the container, not a second naming). The fitted
     * list's rows are the one carrier keyed by data-entry-for
     * alone. Count those two, never the SVG row groups. */
    variant.querySelectorAll("[data-label-for]").forEach((el) => {
      const id = el.getAttribute("data-label-for");
      named.set(id, (named.get(id) ?? 0) + 1);
    });
    variant.querySelectorAll(".scatter-list-row[data-entry-for]").forEach((el) => {
      const id = el.getAttribute("data-entry-for");
      named.set(id, (named.get(id) ?? 0) + 1);
    });
  }
  out.unnamed = chartedIds.filter((id) => !named.has(id));
  out.duplicated = [...named.entries()].filter(([, n]) => n > 1).map(([id]) => id);
  out.namedCount = named.size;
  out.caseCountOutsideMethod = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = walker.nextNode())) {
    /* Visible text only: the framework's serialized stream
     * repeats the page's strings inside script elements,
     * which no reader ever sees. */
    if (node.parentElement && node.parentElement.closest("script, style")) continue;
    if (node.textContent.includes(caseCountText)) {
      const inMethod = node.parentElement && node.parentElement.closest("#method");
      if (!inMethod) {
        const sec = node.parentElement ? node.parentElement.closest("[data-section], section, footer, header") : null;
        out.caseCountOutsideMethod.push(
          ((sec && (sec.getAttribute("data-section") || sec.id || sec.tagName)) || "?") +
            ": " + node.textContent.trim().slice(0, 60),
        );
      }
    }
  }
  /* C-5 pairing. The carrier is the result's own block,
   * attributed to the result: its ranking row or heat cell
   * (data-run-id), its scatter entry or label group
   * (data-entry-for, data-label-for), the model card that
   * names it, its model index summary (data-index-for,
   * judged as its own carrier, because the summary is the
   * line a scanning reader sees while the card body sits
   * collapsed beneath it), or a heatmap caption paragraph.
   * Attribution
   * matters. A per-family figure inside another result's
   * card can equal a flagged figure as a bare string, and
   * it is not the flagged result's figure. Method prints
   * the case count, Malformed prints malformed rates and
   * Calibration prints calibration errors. Those are other
   * quantities, and their sections are out of scope.
   * Where a carrier prints a flagged figure, the pairing
   * demands the decomposition's substance in the carrier's
   * text or in a title the carrier or one of its parts
   * carries, which is where the heatmap cells keep it. The
   * substance is both clauses with the payload-derived
   * figures, the genuine flip rate and the malformed
   * share of counted flips. The words genuine and
   * malformed standing somewhere in the block prove
   * nothing. Where the sealed records derive no
   * decomposition for the result, the figure must not
   * print in its carriers at all. */
  out.flagOrphans = [];
  const EXCLUDED_SECTIONS = ["method", "malformed", "calibration"];
  const inScope = (el) => {
    const s = el.closest("section");
    return !s || !EXCLUDED_SECTIONS.includes(s.getAttribute("data-section"));
  };
  const decompTravels = (block, decomp) => {
    const texts = [block.textContent || "", block.getAttribute("title") || ""];
    block.querySelectorAll("[title]").forEach((t) =>
      texts.push(t.getAttribute("title") || ""),
    );
    return texts.some((t) => {
      const low = t.toLowerCase();
      return (
        low.includes("genuine flip rate " + decomp.genuine) &&
        low.includes(decomp.share + " of counted flips to malformed output")
      );
    });
  };
  for (const { runId, figures, name, decomp } of flaggedFigures) {
    const blocks = new Set();
    document
      .querySelectorAll(
        '[data-run-id="' + runId + '"], [data-entry-for="' + runId +
          '"], [data-label-for="' + runId + '"], [data-index-for="' + runId + '"]',
      )
      .forEach((b) => {
        if (inScope(b)) blocks.add(b);
      });
    document.querySelectorAll("details.model-item").forEach((card) => {
      const idEl = card.querySelector(".card-model-id");
      if (idEl && idEl.textContent.trim() === name && inScope(card)) {
        blocks.add(card);
      }
    });
    const heat = document.querySelector('[data-section="heatmap"]');
    if (heat) {
      heat.querySelectorAll("p").forEach((p) => {
        if (figures.some((f) => (p.textContent || "").includes(f))) {
          blocks.add(p);
        }
      });
    }
    for (const block of blocks) {
      for (const fig of figures) {
        let found = false;
        const candidates = [block, ...block.querySelectorAll("*")];
        for (const el of candidates) {
          if (!el.textContent || !el.textContent.includes(fig)) continue;
          let deepest = true;
          for (const child of el.children) {
            if (child.textContent && child.textContent.includes(fig)) {
              deepest = false;
              break;
            }
          }
          if (deepest) {
            found = true;
            break;
          }
        }
        if (found && decomp === null) {
          out.flagOrphans.push(
            runId + " figure " + fig + " in its " +
              block.tagName.toLowerCase() +
              " carrier although the sealed records derive no decomposition for it",
          );
        } else if (found && !decompTravels(block, decomp)) {
          out.flagOrphans.push(
            runId + " figure " + fig + " in its " +
              block.tagName.toLowerCase() +
              " carrier without its decomposition",
          );
        }
      }
    }
  }
  /* The spark carrier, judged per family the way the
   * compare family lines are judged below. The whole-row
   * pass above cannot see these figures, since a family
   * rate is not the result's headline figure, so this pass
   * reads each flagged result's spark list on its own. */
  out.sparkOrphans = [];
  for (const fig of flaggedFigures) {
    const list = document.querySelector(
      '[data-spark-for="' + fig.runId + '"]',
    );
    if (!list) {
      out.sparkOrphans.push(fig.runId + " has no spark list carrier");
      continue;
    }
    list.querySelectorAll("[data-family]").forEach((rowEl) => {
      const famKey = rowEl.getAttribute("data-family");
      const famAsr = fig.familyAsr[famKey];
      if (famAsr === null || famAsr === undefined) return;
      const fd = fig.families[famKey] ?? null;
      const valEl = rowEl.querySelector(".spark-value");
      const valText = valEl ? (valEl.textContent || "").trim() : null;
      const title = (rowEl.getAttribute("title") || "").toLowerCase();
      if (fd === null) {
        if (
          !rowEl.hasAttribute("data-suppressed") ||
          rowEl.hasAttribute("data-asr") ||
          valText !== "--"
        ) {
          out.sparkOrphans.push(
            fig.runId + " prints its " + famKey +
              " figure in its spark carrier although that family's decomposition does not derive",
          );
        } else if (
          !title.includes("attack success not stated") ||
          !title.includes("does not derive from the sealed records")
        ) {
          out.sparkOrphans.push(
            fig.runId + " suppresses its " + famKey +
              " figure in its spark carrier without stating in the row title that the figure is not stated",
          );
        }
      } else if (
        rowEl.hasAttribute("data-suppressed") ||
        valText === "--" ||
        valText === null
      ) {
        out.sparkOrphans.push(
          fig.runId + " withholds its " + famKey +
            " figure in its spark carrier although its decomposition derives",
        );
      } else {
        const travels =
          fd.flips === 0
            ? title.includes("no counted flips")
            : title.includes("genuine flip rate " + fd.genuine) &&
              title.includes(
                fd.share + " of counted flips to malformed output",
              );
        if (!travels) {
          out.sparkOrphans.push(
            fig.runId + " figure for " + famKey +
              " in its spark carrier without that family's decomposition",
          );
        }
      }
    });
  }
  /* The filled accent is the page's own token, read from
   * the rendered root. The law follows --accent, so a token
   * change cannot leave it asserting a stale colour. The
   * token is parsed the way the browser parses it. A probe
   * element first takes a sentinel colour no real token
   * would carry, and the sentinel's own computed form is
   * captured before the token is applied, because the
   * browser serialises the colour back at its own
   * precision and a comparison against the literal that
   * was assigned can never match. The token then replaces
   * the sentinel only if it parses. An unparseable token
   * leaves the captured sentinel standing, and the law
   * fails loudly and names the token instead of counting
   * zero forever. */
  const accentRaw = getComputedStyle(document.documentElement)
    .getPropertyValue("--accent")
    .trim();
  const probe = document.createElement("div");
  probe.style.color = "rgba(9, 8, 7, 0.123)";
  document.body.appendChild(probe);
  const sentinelRgb = getComputedStyle(probe).color;
  if (accentRaw) probe.style.color = accentRaw;
  const accentRgb = getComputedStyle(probe).color;
  probe.remove();
  out.accentError =
    accentRaw && accentRgb !== sentinelRgb && /^rgba?\\(/.test(accentRgb)
      ? null
      : accentRaw || "(empty)";
  out.accentRgb = accentRgb;
  out.filledAccent = 0;
  for (const el of document.querySelectorAll("a, button")) {
    const r = el.getBoundingClientRect();
    if (r.height === 0 || r.top > window.innerHeight || r.bottom < 0) continue;
    if (getComputedStyle(el).backgroundColor === accentRgb) out.filledAccent++;
  }
  return out;
}`;

for (const width of WIDTHS) {
  const { errors } = await loadBoard(width);
  if (errors.length) {
    fail(`width ${width}: page errors: ${errors.slice(0, 2).join(" | ")}`);
  }
  const m = await evaluate(
    `(${MEASURE})(${JSON.stringify(chartedIds)}, ${JSON.stringify(caseCountText)}, ${JSON.stringify(flaggedFigures)})`,
  );
  if (m.overflow > 1) fail(`width ${width}: document overflow ${m.overflow}px`);
  if (m.pastEdge.length) {
    fail(`width ${width}: elements past edge: ${m.pastEdge.join("; ")}`);
  }
  if (m.unnamed.length) {
    fail(`width ${width} (${m.variant}): ${m.unnamed.length} charted results unnamed, e.g. ${m.unnamed.slice(0, 3).join(", ")}`);
  }
  if (m.duplicated.length) {
    fail(`width ${width} (${m.variant}): named more than once: ${m.duplicated.slice(0, 3).join(", ")}`);
  }
  if (m.caseCountOutsideMethod.length) {
    fail(`width ${width}: case count outside Method: ${m.caseCountOutsideMethod.slice(0, 2).join("; ")}`);
  }
  if (m.flagOrphans.length) {
    fail(
      `width ${width}: flagged figure without decomposition: ${m.flagOrphans.slice(0, 3).join("; ")}`,
    );
  }
  if (m.sparkOrphans.length) {
    fail(
      `width ${width}: flagged family figure in its spark carrier without its decomposition: ${m.sparkOrphans.slice(0, 3).join("; ")}`,
    );
  }
  if (m.filledAccent > 1) {
    fail(`width ${width}: ${m.filledAccent} filled accent controls in view`);
  }
  if (m.accentError !== null && m.accentError !== undefined) {
    fail(
      `width ${width}: the --accent token "${m.accentError}" cannot be parsed into a colour, so the accent budget cannot be measured`,
    );
  }
  notes.push(`width ${width}: variant=${m.variant} named=${m.namedCount}/${chartedIds.length} overflow=${m.overflow} filledAccent=${m.filledAccent}`);
}

/* 6. Touch targets at phone width under a coarse pointer. */
{
  const { errors } = await loadBoard(390, { coarse: true });
  if (errors.length) fail(`touch pass: page errors: ${errors[0]}`);
  const small = await evaluate(`(() => {
    const out = [];
    /* Candidates are derived, not listed: every element the
     * DOM exposes as interactive (tag or role), minus prose
     * links (an anchor rendered inline is text, not a
     * control; this board's control anchors are styled
     * inline-flex or block) and the off-screen skip link. A
     * future control class is measured automatically. */
    const sel = 'a[href], button, select, input, summary, [role="button"], [data-entry-for]';
    for (const el of document.querySelectorAll(sel)) {
      if (el.classList && el.classList.contains("skip")) continue;
      const r = el.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) continue;
      const cs = getComputedStyle(el);
      if (cs.visibility === "hidden" || cs.display === "none") continue;
      if (el.tagName === "A" && cs.display === "inline") continue;
      if (r.height < 43.5) {
        out.push(el.tagName.toLowerCase() + "." + (el.getAttribute("class") || "").split(" ")[0] +
          " h=" + Math.round(r.height) + " \\"" + (el.textContent || "").trim().slice(0, 24) + "\\"");
      }
    }
    return out;
  })()`);
  if (small.length) {
    fail(`touch targets under 44px at 390 coarse: ${small.slice(0, 6).join("; ")}${small.length > 6 ? ` (+${small.length - 6} more)` : ""}`);
  } else {
    notes.push("touch pass: every measured control at 390 coarse stands 44px or taller");
  }
}

/* 7. Heat cell contrast. The pass counts the cells it
 * measures and fails when it finds none, so a heatmap
 * that stops printing cells cannot pass on an empty set. */
{
  await loadBoard(1440);
  const heat = await evaluate(`(() => {
    const parse = (s) => s.match(/[\\d.]+/g).map(Number).slice(0, 3);
    const lum = ([r, g, b]) => {
      const f = (c) => {
        const s = c / 255;
        return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
      };
      return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
    };
    const out = [];
    let examined = 0;
    for (const el of document.querySelectorAll(".heat-cell")) {
      if (!el.textContent.trim() || el.classList.contains("na")) continue;
      examined++;
      const cs = getComputedStyle(el);
      const la = lum(parse(cs.color));
      const lb = lum(parse(cs.backgroundColor));
      const ratio = (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
      if (ratio < 4.5) {
        out.push(el.textContent.trim() + " ratio=" + ratio.toFixed(2) + " bg=" + cs.backgroundColor + " fg=" + cs.color);
      }
    }
    return { bad: out, examined };
  })()`);
  if (heat.examined === 0) {
    fail("heat pass: no printed heat cells were found to measure");
  } else if (heat.bad.length) {
    fail(`heat cells under 4.5:1 contrast: ${heat.bad.slice(0, 5).join("; ")}${heat.bad.length > 5 ? ` (+${heat.bad.length - 5} more)` : ""}`);
  } else {
    notes.push(`heat pass: every printed heat cell clears 4.5:1 (${heat.examined} cells measured)`);
  }
}

/* Law 5, the compare interaction. The width loop measures
 * the page as it loads, and the compare island loads with
 * its default ranked pair, so no resting measurement ever
 * sees a flagged figure in that section. This pass drives
 * the section's own pickers instead. It binds flagged
 * results to the selections through the compare dataset
 * the page itself prints, gives model A one flagged
 * selection and model B a second one, and holds the
 * rendered section to the same pairing the carriers are
 * held to, on each side alike. The headline figure must
 * stand with its flagged standing and both decomposition
 * clauses in the section's text, and on each side in that
 * side's own flagged note element, so a note that goes
 * missing on one side cannot hide behind the other side's
 * text. One parameterised driver drives and asserts each
 * side, so the two sides' coverage cannot drift apart.
 * Every printed family figure must carry its own
 * decomposition in the family line's title. A family
 * whose records derive no decomposition must print no
 * figure, and where the whole-row decomposition itself
 * does not derive, the headline figure must not print at
 * all. */
{
  await loadBoard(1440);
  const binding = await evaluate(`(() => {
    const script = document.querySelector("script[data-compare-rows]");
    if (!script) return null;
    return JSON.parse(script.textContent).map((r) => ({
      slug: r.slug,
      runId: r.runId,
      group: r.group,
    }));
  })()`);
  const bound = (f) =>
    binding !== null &&
    binding.some((b) => b.runId === f.runId && b.group === "flagged");
  const target =
    flaggedFigures.find((f) => f.decomp !== null && bound(f)) ??
    flaggedFigures.find((f) => bound(f));
  const targetSlug = target
    ? binding.find((b) => b.runId === target.runId).slug
    : null;
  const partnerSlug =
    binding !== null
      ? (binding.find((b) => b.group === "full" && b.slug !== targetSlug)
          ?.slug ?? null)
      : null;
  /* The second drive's flagged target. The vision and
   * language flagged result is preferred, as the pair the
   * phone observation was made on, and any other bound
   * flagged result serves when it is absent. A drive that
   * only ever exercised side A left side B's carriers
   * unmeasured, and a missing side B note passed unseen,
   * so this pass binds both sides before it starts. */
  const targetB =
    flaggedFigures.find(
      (f) =>
        f.runId === "or-lingvl-v2-trial" &&
        f.runId !== target?.runId &&
        bound(f),
    ) ??
    flaggedFigures.find(
      (f) => f.decomp !== null && f.runId !== target?.runId && bound(f),
    ) ??
    flaggedFigures.find((f) => f.runId !== target?.runId && bound(f));
  const targetBSlug = targetB
    ? binding.find((b) => b.runId === targetB.runId).slug
    : null;
  if (!target || !targetSlug || !partnerSlug || !targetB || !targetBSlug) {
    fail(
      "compare interaction: no flagged result could be bound to a picker selection",
    );
  } else {
    /* One drive-and-assert routine per side, parameterised
     * by the side it drives. Side A and side B run the same
     * code, so their coverage cannot drift apart. Each side
     * is held to the headline figure, the standing, and
     * both decomposition clauses in the section text and
     * in its own flagged note element read directly, and
     * to every family line's suppression and title
     * pairing. (The two sides once carried near-verbatim
     * copies of this routine, and they drifted. Only side
     * B read its note element, so side A's note was never
     * held to the pairing.) */
    const driveFlaggedSide = async (side, fig, slug) => {
      const failuresBeforeSide = failures.length;
      const took = await evaluate(`(() => {
        const sel = document.querySelector("#cmp-picker-${side}");
        if (!sel) return false;
        const setter = Object.getOwnPropertyDescriptor(
          window.HTMLSelectElement.prototype,
          "value",
        ).set;
        setter.call(sel, ${JSON.stringify(slug)});
        sel.dispatchEvent(new Event("change", { bubbles: true }));
        sel.dispatchEvent(new Event("input", { bubbles: true }));
        return sel.value === ${JSON.stringify(slug)};
      })()`);
      await sleep(600);
      const view = await evaluate(`(() => {
        const section = document.querySelector('[data-section="compare"]');
        if (!section) return null;
        const cell = section.querySelector(
          '[data-cmp-value="asr"][data-cmp-side="${side}"]',
        );
        const note = section.querySelector(
          '[data-cmp-flagged-note="${side}"]',
        );
        const families = [];
        section
          .querySelectorAll('[data-cmpfamily][data-cmpside="${side}"]')
          .forEach((line) => {
            const val = line.querySelector(".cmp-fam-val");
            families.push({
              key: line.getAttribute("data-cmpfamily"),
              suppressed: line.hasAttribute("data-suppressed"),
              valText: val ? val.textContent.trim() : null,
              title: line.getAttribute("title") || "",
            });
          });
        return {
          text: section.textContent || "",
          noteText: note ? note.textContent || "" : null,
          asrCell: cell ? cell.textContent.trim() : null,
          families,
        };
      })()`);
      const figRow = charted.find((r) => r.run_id === fig.runId);
      const figText = pctText(figRow.asr_conditional);
      const sideName = `side ${side.toUpperCase()}`;
      if (!took || !view) {
        fail(
          `compare interaction: picker ${side.toUpperCase()} did not take the flagged selection`,
        );
        return;
      }
      const sectionText = view.text.toLowerCase();
      if (fig.decomp !== null) {
        if (!view.asrCell || !view.asrCell.includes(figText)) {
          fail(
            `compare interaction: the flagged headline figure ${figText} is missing from ${sideName} of the compare table`,
          );
        }
        if (!sectionText.includes("flagged and not ranked")) {
          fail(
            `compare interaction: ${fig.runId} is selected on ${sideName} of compare without its flagged standing stated`,
          );
        }
        if (
          !sectionText.includes(
            `genuine flip rate ${fig.decomp.genuine}`,
          ) ||
          !sectionText.includes(
            `${fig.decomp.share} of counted flips to malformed output`,
          )
        ) {
          fail(
            `compare interaction: ${fig.runId} is selected on ${sideName} of compare without its decomposition in the section`,
          );
        }
        const noteText =
          view.noteText === null ? null : view.noteText.toLowerCase();
        if (
          noteText === null ||
          !noteText.includes("flagged and not ranked") ||
          !noteText.includes(
            `genuine flip rate ${fig.decomp.genuine}`,
          ) ||
          !noteText.includes(
            `${fig.decomp.share} of counted flips to malformed output`,
          )
        ) {
          fail(
            `compare interaction: ${fig.runId} is selected on ${sideName} of compare without its decomposition in ${sideName}'s own flagged note`,
          );
        }
      } else if (view.asrCell && view.asrCell.includes(figText)) {
        fail(
          `compare interaction: ${fig.runId} prints its figure ${figText} on ${sideName} of compare although no decomposition derives for it`,
        );
      }
      for (const line of view.families) {
        const famAsr = fig.familyAsr[line.key];
        if (famAsr === null || famAsr === undefined) continue;
        const fd = fig.families[line.key] ?? null;
        if (fd === null) {
          if (!line.suppressed || line.valText !== "--") {
            fail(
              `compare interaction: ${fig.runId} prints its ${line.key} figure on ${sideName} of compare although that family's decomposition does not derive`,
            );
          }
        } else if (line.valText === "--" || line.valText === null) {
          fail(
            `compare interaction: ${fig.runId} withholds its ${line.key} figure on ${sideName} of compare although its decomposition derives`,
          );
        } else {
          const title = line.title.toLowerCase();
          const travels =
            fd.flips === 0
              ? title.includes("no counted flips")
              : title.includes(`genuine flip rate ${fd.genuine}`) &&
                title.includes(
                  `${fd.share} of counted flips to malformed output`,
                );
          if (!travels) {
            fail(
              `compare interaction: ${fig.runId} prints its ${line.key} figure on ${sideName} of compare without that family's decomposition in the line title`,
            );
          }
        }
      }
      if (failures.length === failuresBeforeSide) {
        notes.push(
          `compare interaction: flagged selection ${fig.runId} held to the C-5 pairing on ${sideName} of the compare section`,
        );
      }
    };
    await driveFlaggedSide("a", target, targetSlug);
    await driveFlaggedSide("b", targetB, targetBSlug);
  }
}

/* Law 10, the compare header at phone widths. The width
 * loop and the sweep measure the document, and a header
 * name that runs left past its cell grows neither, so
 * this pass measures the header itself. At each phone
 * width it reads the compare table's two header cells on
 * the resting pair, then drives both pickers to the two
 * longest names the compare dataset holds and reads the
 * cells again. The name span, the name's own text, the
 * vendor chip, the wire line, and the flagged tag must
 * each sit inside their cell, and no part may start left
 * of the viewport. */
{
  const headerWidths = [360, 390, 480, 640];
  let longestPair = null;
  const measureHeader = () =>
    evaluate(`(() => {
      const section = document.querySelector('[data-section="compare"]');
      if (!section) return null;
      const rect = (el) => {
        if (!el) return null;
        const r = el.getBoundingClientRect();
        return { left: r.left, right: r.right };
      };
      const sides = {};
      for (const side of ["a", "b"]) {
        const th = section.querySelector(
          'th.cmp-th-model[data-cmp-side="' + side + '"]',
        );
        if (!th) {
          sides[side] = null;
          continue;
        }
        const nameSpan = th.querySelector(".cmp-th-name");
        let textRect = null;
        if (nameSpan) {
          const tn = [...nameSpan.childNodes].find(
            (n) => n.nodeType === 3 && n.textContent.trim(),
          );
          if (tn) {
            const rg = document.createRange();
            rg.selectNodeContents(tn);
            textRect = rect(rg);
          }
        }
        sides[side] = {
          cell: rect(th),
          /* The third field marks a part every header
           * carries. An absent required part fails in the
           * checker below instead of being skipped, so a
           * renamed class cannot vacate the measurement.
           * The wire line and the flagged tag render only
           * where the row carries them and stay optional. */
          parts: [
            ["name span", rect(nameSpan), true],
            ["name text", textRect, true],
            ["vendor chip", rect(th.querySelector(".vendor-chip")), true],
            ["wire line", rect(th.querySelector(".cmp-th-wire")), false],
            ["flagged tag", rect(th.querySelector(".flag-tag")), false],
          ],
        };
      }
      return sides;
    })()`);
  const checkHeader = (sides, width, state) => {
    if (!sides) {
      fail(
        `compare header at width ${width} (${state}): the compare section is missing`,
      );
      return;
    }
    for (const side of ["a", "b"]) {
      const s = sides[side];
      if (!s || !s.cell) {
        fail(
          `compare header at width ${width} (${state}): side ${side} has no header cell`,
        );
        continue;
      }
      for (const [label, r, required] of s.parts) {
        if (!r) {
          if (required) {
            fail(
              `compare header at width ${width} (${state}): side ${side} ${label} is missing from its header cell`,
            );
          }
          continue;
        }
        if (
          r.left < s.cell.left - 0.6 ||
          r.right > s.cell.right + 0.6 ||
          r.left < -0.6
        ) {
          fail(
            `compare header at width ${width} (${state}): side ${side} ${label} [${Math.round(r.left)}, ${Math.round(r.right)}] escapes its header cell [${Math.round(s.cell.left)}, ${Math.round(s.cell.right)}]`,
          );
        }
      }
    }
  };
  for (const width of headerWidths) {
    const failuresBefore = failures.length;
    await loadBoard(width);
    if (longestPair === null) {
      const rows = await evaluate(`(() => {
        const script = document.querySelector("script[data-compare-rows]");
        if (!script) return null;
        return JSON.parse(script.textContent).map((r) => ({
          slug: r.slug,
          name: r.name,
        }));
      })()`);
      if (rows) {
        const sorted = [...rows].sort(
          (x, y) => y.name.length - x.name.length,
        );
        longestPair = [sorted[0]?.slug ?? null, sorted[1]?.slug ?? null];
      }
    }
    checkHeader(await measureHeader(), width, "resting pair");
    if (longestPair && longestPair[0] && longestPair[1]) {
      const drove = await evaluate(`(() => {
        const set = (id, slug) => {
          const sel = document.querySelector(id);
          if (!sel) return false;
          const setter = Object.getOwnPropertyDescriptor(
            window.HTMLSelectElement.prototype,
            "value",
          ).set;
          setter.call(sel, slug);
          sel.dispatchEvent(new Event("change", { bubbles: true }));
          sel.dispatchEvent(new Event("input", { bubbles: true }));
          return sel.value === slug;
        };
        return (
          set("#cmp-picker-a", ${JSON.stringify(longestPair?.[0] ?? "")}) &&
          set("#cmp-picker-b", ${JSON.stringify(longestPair?.[1] ?? "")})
        );
      })()`);
      await sleep(600);
      if (!drove) {
        fail(
          `compare header at width ${width}: the pickers did not take the longest named pair`,
        );
      } else {
        checkHeader(await measureHeader(), width, "longest named pair");
      }
    }
    if (failures.length === failuresBefore) {
      notes.push(
        `compare header at width ${width}: every header name, chip, wire line, and tag sits inside its cell`,
      );
    }
  }
}

/* Law 9, the resize sweep. Resting widths cannot see a
 * layout that only exists between widths: the page is
 * loaded wide, then the viewport steps down to 360 and
 * back up in 15px steps (5px steps across the 500 to 660
 * band RT-F1 named), measuring the document's horizontal
 * overflow at every step after a frame to settle. The
 * metrics are set without the mobile flag so every width
 * is a literal CSS width. */
{
  await loadBoard(1440);
  const steps = [];
  for (let w = 1440; w >= 360; w -= 15) steps.push(w);
  for (let w = 365; w <= 1440; w += 15) steps.push(w);
  for (let w = 660; w >= 500; w -= 5) steps.push(w);
  let worst = { overflow: 0, width: 0, widest: "" };
  const offenders = [];
  for (const w of steps) {
    await send(
      "Emulation.setDeviceMetricsOverride",
      { width: w, height: 900, deviceScaleFactor: 1, mobile: false },
      sessionId,
    );
    await new Promise((r) => setTimeout(r, 45));
    const m = await evaluate(`(() => {
      const vw = window.innerWidth;
      const overflow = Math.max(
        document.documentElement.scrollWidth,
        document.body.scrollWidth,
      ) - vw;
      let widest = "";
      if (overflow > 0) {
        /* The widest element that actually reaches the
         * document: content inside a scroller is clipped
         * by it and does not count, however far it runs. */
        const clipped = (el) => {
          let n = el.parentElement;
          while (n && n !== document.body) {
            const ox = getComputedStyle(n).overflowX;
            if (ox === "auto" || ox === "scroll" || ox === "hidden" || ox === "clip") {
              return true;
            }
            n = n.parentElement;
          }
          return false;
        };
        let best = vw;
        for (const el of document.querySelectorAll("*")) {
          const r = el.getBoundingClientRect();
          if (r.width > 0 && r.right > best) {
            const cs = getComputedStyle(el);
            if (cs.position === "fixed") continue;
            if (clipped(el)) continue;
            best = r.right;
            widest =
              el.tagName.toLowerCase() +
              "." +
              (el.getAttribute("class") || "").slice(0, 40) +
              " right " +
              Math.round(r.right);
          }
        }
      }
      return { overflow, vw, widest };
    })()`);
    if (m.overflow > 0) {
      offenders.push(`width ${m.vw}: +${m.overflow}px (${m.widest})`);
      if (m.overflow > worst.overflow) {
        worst = { overflow: m.overflow, width: m.vw, widest: m.widest };
      }
    }
  }
  if (worst.overflow > 0) {
    fail(
      `resize sweep: horizontal overflow at ${offenders.length} steps, worst +${worst.overflow}px at width ${worst.width} (${worst.widest}); first steps: ${offenders.slice(0, 3).join("; ")}`,
    );
  } else {
    notes.push(
      `resize sweep: no horizontal overflow at any of ${steps.length} steps, 1440 down to 360 and back`,
    );
  }
  await loadBoard(1440);
}

/* Screenshots for the design verdict. */
if (WITH_SHOTS) {
  await mkdir(SHOTS, { recursive: true });
  const sections = [
    ["masthead", ".masthead"],
    ["ranking", "#ranking"],
    ["malformed", "#malformed"],
    ["families", "#families"],
    ["cost", "#cost"],
    ["calibration", "#calibration"],
    ["models", "#models"],
    ["compare", "#compare"],
    ["method", "#method"],
    ["footer", ".board-footer"],
  ];
  for (const width of [1440, 390]) {
    await loadBoard(width);
    const metrics = await send("Page.getLayoutMetrics", {}, sessionId);
    const { width: cw, height: ch } = metrics.cssContentSize ?? metrics.contentSize;
    await screenshot(join(SHOTS, `board-full-${width}.png`), { x: 0, y: 0, width: cw, height: ch });
    for (const [name, sel] of sections) {
      const rect = await evaluate(`(() => {
        const el = document.querySelector(${JSON.stringify(sel)});
        if (!el) return null;
        const r = el.getBoundingClientRect();
        return { x: r.left + window.scrollX, y: r.top + window.scrollY, width: r.width, height: r.height };
      })()`);
      if (rect && rect.height > 0) {
        await screenshot(join(SHOTS, `${name}-${width}.png`), rect);
      }
    }
  }
  for (const width of [800, 900]) {
    await loadBoard(width);
    const rect = await evaluate(`(() => {
      const el = document.querySelector("#cost");
      const r = el.getBoundingClientRect();
      return { x: r.left + window.scrollX, y: r.top + window.scrollY, width: r.width, height: r.height };
    })()`);
    if (rect) await screenshot(join(SHOTS, `cost-${width}.png`), rect);
  }
  notes.push(`screenshots written to ${SHOTS}`);
}

try {
  await send("Target.closeTarget", { targetId });
} catch {}
ws.close();
chrome.kill();
server.close();

for (const n of notes) console.log(`ok  ${n}`);
if (failures.length) {
  for (const f of failures) console.log(`FAIL ${f}`);
  process.exit(1);
}
console.log("render law: all assertions passed");
/* Exit explicitly: server.close() waits on the browser's
 * keep-alive connections, and a success that lingers keeps
 * the build chain that runs this law waiting with it. */
process.exit(0);
