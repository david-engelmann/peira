#!/usr/bin/env node
/**
 * DOM acceptance audit for the ranking prototype. Drives a
 * Chromium from the Playwright cache through puppeteer-core
 * against the static out/ directory, measures the built page at
 * 1440, 1280, 900, and 390, and checks the census and spec tests that
 * need a live layout:
 *
 *  F-03  no two visible text boxes in the ranking come within
 *        2 px of each other (bounding-box intersection test over
 *        text node ranges).
 *  F-05  no name is clipped (every name element's scroll width
 *        fits its client width) and every rendered short name
 *        equals the payload-derived short name.
 *  F-08  ranking containment (cycle 2, doctrine D8): at phone
 *        widths nothing inside the ranking extends past the
 *        section's own box; at desktop widths the rows' designed
 *        14 px bleed into the page padding is pinned at 15 px,
 *        and at each audited width (1440, 1280 and 390)
 *        nothing crosses the viewport.
 *  F-01  the rank column holds exactly one number per ranked row
 *        (the group-local rank) and none on flagged rows.
 *  Amber appears only inside the flagged strip.
 *  The slice group header states the slice case base, the full
 *  group caption states the suite size.
 *  Page height is reported for the F-12 scroll budget.
 *
 * Round 9 extensions (chart suite):
 *  Tiles. The counts line equals the display_name rule counts
 *        computed here, at every width.
 *  Scatter. The visible variant's point set equals the payload
 *        population (28 plotted, 5 railed); every point centre
 *        sits on the payload position recomputed from the SVG's
 *        own geometry attributes (nudged points get the spec's
 *        one marker width of slack in y); at every width every
 *        point carries its name in place, every label rect is
 *        pairwise clear of every other label and of every
 *        point centre, and no numbered badge exists (redesign
 *        rule). No leader line exists either:
 *        the scatter carries no line element outside its grid
 *        lines, rail divider, axis lines and the points' own
 *        lower-bound ticks, at any width (correction rule:
 *        labels sit beside their points or in a disc-carrying
 *        stack row, never tied by a drawn line).
 *  Heatmap. Headers measure one line; every cell's text equals
 *        the payload rate under the cell format; the not
 *        measured cells carry the -- mark (doctrine D13); every
 *        cell's text to background contrast is at least 4.5; no
 *        cell background is accent green; with the panel
 *        scrolled fully right the sticky name column stays at
 *        the container's left on an opaque ground background
 *        and its text never meets a visible cell's text (F-06).
 *        Design cycle 5 adds H-01: every header and every cell
 *        sits inside the section's horizontal bounds at every
 *        width (no column off the section's edge at desktop,
 *        no family off canvas on the phone, where the matrix
 *        restacks into labeled chips).
 *  Calibration. Panel order and rail order equal the attacked
 *        ECE order computed here; panel headers state the
 *        payload ECE; sampled bin circles sit on the payload
 *        coordinates inside the panel's own plot bounds, read
 *        from its diagonal; rail names are not clipped (F-16).
 *        Design cycle 5 adds: no panel carries the coincidence
 *        note and the lede states it with the derived count
 *        (C-07 revised); tick numerals render at 10 px or
 *        larger at every width (C-01) and inside the viewBox
 *        (C-06); the panels showing each axis are exactly the
 *        array's edge panels for the layout in force (C-08);
 *        the heatmap lede names its groups with their counts
 *        (H-02); on the phone no two
 *        rail entries share a line (C-02) and a wrapped panel
 *        name breaks only after a hyphen or a space (C-04);
 *        rail names stay inside the section's bounds (C-05).
 *  Amber. The confinement rule is the round 9 rule: amber is
 *        allowed in the ranking's flagged strip, on scatter
 *        marks whose row is flagged, and on heatmap flag tags
 *        of flagged rows, and nowhere else.
 *
 * Round 10 extensions (malformed, cards, model pages):
 *  Malformed. Bar rows equal the payload rows whose printed
 *        rate is not 0.0 percent, worst first; each value
 *        equals the payload rate; each bar's width sits on the
 *        0 to 15 percent axis; the single admission line stands
 *        at the 5 percent position of the first row's track;
 *        flagged values are amber and ranked values are not;
 *        the fold line states the folded count.
 *  Cards. The index holds 36 items in the ranking's groups;
 *        summary rows are at least 44 px tall with no
 *        horizontal overflow; opening one card per group works;
 *        a card anchor lands on the card header inside its
 *        scroll margin; a card's back link lands on the top of
 *        the index.
 *  Model pages. A sample (one per group plus the two-wire
 *        model) renders its card article under its own address.
 *  Amber gains two contexts: the flagged rows of the
 *        malformed chart and the flagged cards of the model
 *        index, both keyed to the row's flagged status.
 *
 * Round 11 extensions (section nav, compare, ranking links):
 *  Nav. The sticky bar renders at every width with its eight
 *        links in page order; every link measures at least
 *        24 px in both dimensions (WCAG 2.2 target size,
 *        2.5.8). At desktop a keyboard walk tabs to each nav
 *        link in turn and proves the focused link sits inside
 *        the viewport, uncovered, with its focus outline
 *        showing; activating each link lands its section at or
 *        below the bar's bottom edge and no more than 40 px
 *        past it, the focus-not-obscured rule (2.4.11) the
 *        64 px scroll margin builds in. The scrollspy marks
 *        exactly the section in view and changes neither the
 *        bar's height nor the document's.
 *  Anchor rule, revised. The card and back link landings
 *        follow the same bar rule: at or below the bar's
 *        bottom, no more than 40 px past it. The round 10
 *        rule (within 40 px of the viewport top) predates the
 *        sticky bar; a landing there would sit under the bar.
 *  Compare. The rendered default pair's deltas equal the
 *        payload differences; driving picker B to a slice
 *        raises the population banner naming both populations
 *        and moves the pair into the address; naming one
 *        model on both sides raises the same-model banner,
 *        clears the winner dots, and prints the deltas
 *        under the not measured mark.
 *  Ranking links. Every row's name link points at the row's
 *        own model page under the slug rule. The links' own
 *        heights are measured against the 24 px floor
 *        (2.5.8) and gated: the round 11 build recorded them
 *        at 17 px under the inline case, and the convergence
 *        round measured the line and found the link standing
 *        alone on it, so the exception does not apply and
 *        the size is a gate, not a note (round 12).
 *  Controls. The compare pickers, the swap button, and the
 *        card controls measure at least 24 px in both
 *        dimensions.
 *
 * Convergence extensions (round 12):
 *  Coincidence notes (C-07). A calibration panel whose bins
 *        coincide carries the sentence on the panel. The
 *        expected panels are derived here from the payload:
 *        slice rows whose 15 attacked bins span at most a
 *        tenth of stated confidence. The note must appear on
 *        exactly those panels and on no other.
 *  Text spacing (AX-04). After the width loop, the WCAG
 *        1.4.12 overrides the adversarial lane applied
 *        (line height 1.5, letter spacing 0.12 em, word
 *        spacing 0.16 em, paragraph spacing 2 em) go onto the
 *        1440 page, and no calibration rail name may clip:
 *        the rail wraps its names at hyphens now, where it
 *        once held them under nowrap and cut the longest.
 *
 * Live-fix extensions (2026-10-23, post-freeze):
 *  Malformed bar geometry. Each bar's right edge is measured
 *        against the axis element's own span and must land
 *        within 1.5 percent of the span of where its payload
 *        value falls on the 0 to 15 axis. The round 10 check
 *        compared each fill with its own track only, a ratio
 *        that stays correct even if the track and the axis
 *        ever disagree; this assertion reads the bar on the
 *        scale the reader reads.
 *  Phone nav reachability (R-1). At phone widths the document
 *        scroll width must equal the viewport width (the nav
 *        never widens the page), and every nav link must come
 *        fully into the strip's own box when the strip is
 *        scrolled to it, its text untruncated. The round 11
 *        checks walked the links by keyboard, which reveals a
 *        focused link; touch reachability was unmeasured
 *        until the convergence re-audit found Models, Compare,
 *        and Method off-screen at 390.
 *
 * Round 40 extensions (landing):
 *  Panel name wrap. A calibration panel name that wraps may
 *        not strand its final hyphen segment alone on the last
 *        line (a last line of five characters or fewer, holding
 *        no hyphen, under a line that ends with one). The
 *        Qwen3Guard-Gen-4B and granite-guardian-hap-125m
 *        headers did exactly this before the balanced wrap;
 *        the check reads the name's own line boxes, so a
 *        regression in the wrap rule fails here.
 *
 * Mobile-fix extensions (2026-10-26, phone pass):
 *  Rail coverage. The phone scatter carries no rail column;
 *        its rail population stands in the list under the
 *        plot, each entry with the point's own disc. The
 *        population assertion accepts either form and fails
 *        a rail point missing from both; entry discs carry
 *        the same amber rule as point discs.
 *  Disc clearance. A scatter label rect may not intersect
 *        any point's disc rect at any width. The centre test
 *        it extends could not see a label resting on a disc.
 *  Type floor. Scatter label, entry-value and corner-sub
 *        text, at its computed size times the chart's own
 *        scale, may not render under 10 px (doctrine D17).
 *        The pre-fix phone chart rendered them at 9.2 and
 *        8.7 px; this check fails there and passes now.
 *  Corner containment. Every corner reading's rect must sit
 *        inside the chart's own box.
 *  Phone interaction block. A touch session at 390x844
 *        after the width loop: the Cost landing by tap read
 *        against the bar's layout height, an occlusion probe
 *        with the chart scrolled to the screen top, and the
 *        scatter card's tap contract end to end. Each new
 *        check was proven against the pre-fix build, where
 *        the tap contract and the occlusion probe fail.
 *
 * Design cycle 3 extensions (scatter, wide form):
 *  Gated widths. The width loop gains 900 (parent decision
 *        after cycle 5's red team found the band between the
 *        phone breakpoint and the page cap unmeasured). Every
 *        check that ran at 1440/1280/390 runs at 900 too.
 *  Scatter type floor, extended. The mobile-fix floor check
 *        sampled the label, entry-value and corner-sub sizes;
 *        every scatter text class is drawn at the same 11.5
 *        units, so the sample now covers the grid numerals,
 *        tick labels, rail head and axis captions as well.
 *        On the pre-fix build the wide chart scales to 0.726
 *        at 900 and every class renders at 8.4 px.
 *  Card motion (S-01, S-02). A post-loop block at 1440 reads
 *        the disc grow's computed transition (it must equal
 *        the motion tokens: 120 ms on the entrance curve) and,
 *        with a point focused so its card stands open, the
 *        card motion layer's computed transition (opacity and
 *        transform on token durations). On the pre-fix build
 *        the grow reads 160 ms on the default curve and the
 *        card has no motion layer at all.
 *  Reduced motion (S-03). The same block under an emulated
 *        prefers-reduced-motion: the active disc's computed
 *        transform must carry no scale (M19 disables it) and
 *        the card's motion layer must transition opacity
 *        only. On the pre-fix build the disc still scales,
 *        snapped on by the global kill block.
 *  Heatmap at the new gate. H-01 and the header check, run
 *        at 900 for the first time, caught the band heatmap
 *        as cycle 5 left it: the last family sat off canvas
 *        in the band scroller (39 cells and one header past
 *        the section edge) and two headers clipped mid-word
 *        at scroll 61 against client 56. The fix refits the
 *        grid (content-floored columns, a stepped-down name
 *        column) so it fits the section at 900. The header
 *        check is calibrated to its contract in the same
 *        cycle: clipping on either axis fails at every
 *        width, and the 30 px ceiling applies only where
 *        the heads are nowrap, since the band design wraps
 *        multi-word headers between words by design. On the
 *        pre-fix build the calibrated check still fails at
 *        900 on the two clipped heads.
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
/* Group-local ranks, mirroring lib/payload boardGroups: the full
 * suite group runs 1..N and the slice group 1..M, each in payload
 * rank order. */
const fullCasesRankA = Math.max(...payload.ranked.map((r) => r.n_cases));
let fullRankA = 0;
let sliceRankA = 0;
const ranked = payload.ranked.map((r) => ({
  ...r,
  rank: r.n_cases === fullCasesRankA ? ++fullRankA : ++sliceRankA,
}));
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

/* ---------- round 9 derivations ---------- */

const allRowsA = [...ranked, ...payload.unranked];
const fullCasesA = Math.max(...ranked.map((r) => r.n_cases));
const displayCountsA = {
  results: allRowsA.length,
  tested: new Set(allRowsA.map((r) => r.display_name)).size,
  ranked: new Set(ranked.map((r) => r.display_name)).size,
  flagged: new Set(payload.unranked.map((r) => r.display_name)).size,
};
const nonSliceA = allRowsA.filter((r) => r.n_cases === fullCasesA);

/* ---------- round 12 derivations ---------- */

/* C-07 (round 12, revised in design cycle 5): the slice
 * panels whose bins coincide, derived from the payload alone:
 * a slice row whose 15 attacked bins span at most a tenth of
 * stated confidence with every bin mean in the top tenth (the
 * lede claims the right edge, so the set requires the
 * position as well as the span). On this payload two qualify
 * (forecast spreads 0.014 and 0.089); the other slice panels
 * spread past half the axis. Round 12 stated the fact on the panels
 * themselves; cycle 5 (doctrine D9) moves it to the section
 * lede, stated once with this set's size, so no panel carries
 * a note and the array's apparatus stays uniform. */
const coincidentSliceIdsA = new Set(
  allRowsA
    .filter((r) => r.n_cases !== fullCasesA)
    .filter((r) => {
      const bins =
        r.detail?.calibration?.reliability_bins?.attacked?.bins ?? [];
      if (bins.length === 0) return false;
      const fs = bins.map((b) => b.mean_forecast);
      /* The lede claims the right edge, so the set requires
       * the position too: span at most a tenth and every bin
       * mean in the top tenth. Mirrors the component's rule;
       * derived here from the payload alone. */
      return Math.max(...fs) - Math.min(...fs) <= 0.1 && Math.min(...fs) >= 0.9;
    })
    .map((r) => r.run_id),
);
const plottedIdsA = new Set(
  nonSliceA
    .filter((r) => r.total_cost_usd !== null && r.total_cost_usd > 0)
    .map((r) => r.run_id),
);
const railIdsA = new Set(
  nonSliceA.filter((r) => !plottedIdsA.has(r.run_id)).map((r) => r.run_id),
);
const byAsrA = [...nonSliceA].sort(
  (a, b) => (a.asr_conditional ?? 0) - (b.asr_conditional ?? 0),
);
const indexByIdA = new Map(byAsrA.map((r, i) => [r.run_id, i + 1]));
const WIRE_WORDS_A = {
  "openai-decisions": "Decisions API",
  "openai-structured": "Chat completions",
};
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
const flaggedIdsA = new Set(payload.unranked.map((r) => r.run_id));

const famEntriesA = (r) =>
  r.detail && typeof r.detail === "object" && r.detail.families
    ? Object.entries(r.detail.families)
    : [];
const famSumsA = new Map();
for (const r of allRowsA) {
  for (const [k, f] of famEntriesA(r)) {
    if (f.asr === null || f.asr === undefined) continue;
    const acc = famSumsA.get(k) ?? { total: 0, n: 0 };
    acc.total += f.asr;
    acc.n += 1;
    famSumsA.set(k, acc);
  }
}
const familyOrderA = [...famSumsA.entries()]
  .map(([k, acc]) => ({ k, mean: acc.total / acc.n }))
  .sort((a, b) => b.mean - a.mean || (a.k < b.k ? -1 : 1))
  .map((e) => e.k);
const fmtCellA = (v) => {
  const shifted = shiftDecA(String(v), 2);
  if (v > 0 && Number(shifted) < 0.5) return "<1";
  return quantA(Number(shifted), 0).replace(/\.$/, "");
};
const cellExpectedA = new Map();
for (const r of allRowsA) {
  const carried = new Map(famEntriesA(r));
  for (const k of familyOrderA) {
    const f = carried.get(k);
    cellExpectedA.set(
      `${r.run_id}|${k}`,
      !f || f.asr === null || f.asr === undefined ? "--" : fmtCellA(f.asr),
    );
  }
}

function quantA(v, dec) {
  const s = String(v);
  const neg = s.startsWith("-");
  const body = neg ? s.slice(1) : s;
  const [ip, fp = ""] = body.split(".");
  const kept = fp.slice(0, dec).padEnd(dec, "0");
  const dropped = fp.slice(dec);
  const digits = (ip.replace(/^0+(?=\d)/, "") + kept).split("").map(Number);
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
  return `${neg ? "-" : ""}${joined.slice(0, joined.length - dec) || "0"}.${joined.slice(joined.length - dec)}`;
}
const eceOfA = (r) => {
  const cal = r.detail && typeof r.detail === "object" ? r.detail.calibration : null;
  const ece = cal && cal.attacked ? cal.attacked.ece : null;
  return ece ?? r.ece_attacked ?? Infinity;
};
const calOrderA = [...allRowsA]
  .sort((a, b) => {
    const ea = eceOfA(a);
    const eb = eceOfA(b);
    if (ea !== eb) return ea - eb;
    return a.display_name < b.display_name ? -1 : 1;
  })
  .map((r) => r.run_id);

/* ---------- round 10 derivations ---------- */

function shiftDecA(decStr, places) {
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
const fmtPctA = (v) => `${quantA(Number(shiftDecA(String(v), 2)), 1)}%`;
const slugOfA = (r) => {
  const base = shortName(r);
  const slugify = (s) =>
    s
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "");
  const shared = allRowsA.some(
    (o) => o.run_id !== r.run_id && shortName(o) === base,
  );
  const withWire = slugify(shared ? `${base}-${r.wire}` : base);
  const clash = allRowsA.some(
    (o) =>
      o.run_id !== r.run_id && shortName(o) === base && o.wire === r.wire,
  );
  return clash ? `${withWire}-${slugify(r.run_id).slice(0, 8)}` : withWire;
};
const sortedMalA = [...allRowsA].sort((a, b) => {
  const d = (b.malformed_rate ?? 0) - (a.malformed_rate ?? 0);
  if (d !== 0) return d;
  return a.display_name < b.display_name ? -1 : 1;
});
const printedMalA = sortedMalA.filter(
  (r) => r.malformed_rate !== null && fmtPctA(r.malformed_rate) !== "0.0%",
);
const foldedMalA = sortedMalA.length - printedMalA.length;

function lumA([r, g, b]) {
  const f = (c) => {
    const s = c / 255;
    return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
}
function contrastA(fg, bg) {
  const la = lumA(fg);
  const lb = lumA(bg);
  const [hi, lo] = la >= lb ? [la, lb] : [lb, la];
  return (hi + 0.05) / (lo + 0.05);
}
const parseRgbA = (s) => {
  const m = s.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
  return m ? [Number(m[1]), Number(m[2]), Number(m[3])] : null;
};

/* Browser discovery and environment (round 10, 2026-10-23).
 * After the overnight runtime restarts, the headless shell in
 * the Playwright cache dies at launch in this sandbox (mmap
 * denied, then SIGILL) and the full Chrome in the Puppeteer
 * cache dies with it; the full Chromium in the Playwright
 * cache launches. Discovery prefers it and falls back to the
 * headless shell. The browser also gets a proxy-free
 * environment: the sandbox proxy variables make single-process
 * Chrome fail on its V8 proxy resolver, and every page this
 * audit loads is served from 127.0.0.1. The launch runs
 * single-process for the same reason; the engine and its
 * measurements are the same. */
const chromeOverrideA =
  process.env.PUPPETEER_EXECUTABLE_PATH ?? process.env.CHROME_PATH;
const chromeHits = chromeOverrideA
  ? [chromeOverrideA]
  : [
      ...globSync(
        join(homedir(), ".cache/ms-playwright/chromium-*/chrome-linux64/chrome"),
      ),
      ...globSync(
        join(
          homedir(),
          ".cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell",
        ),
      ),
    ];
if (chromeHits.length === 0) {
  console.error(
    "no Chromium found in the Playwright cache and no PUPPETEER_EXECUTABLE_PATH or CHROME_PATH set",
  );
  process.exit(2);
}
const browserEnv = { ...process.env };
for (const k of Object.keys(browserEnv)) {
  if (/proxy/i.test(k)) delete browserEnv[k];
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
  env: browserEnv,
  /* The launch timeout is load tolerance for the shared box
   * (round 10): under the trial lanes the browser can take
   * well over the 30 s default to come up. It changes no
   * measurement. Round 11 raised it after launches stalled
   * past 180 s with three lanes on the box, then settled it
   * at 300 s with the gate runner retrying a launch failure
   * rather than one attempt waiting out the whole load peak. */
  timeout: 300000,
  /* Round 11: the protocol timeout gets the same tolerance.
   * A mouse dispatch on the loaded box stalled past the
   * default in the first round 11 run and killed the audit
   * mid-block; the round 11 probes also activate links from
   * the keyboard rather than the mouse where they can. */
  protocolTimeout: 600000,
  args: ["--no-sandbox", "--no-zygote", "--single-process", "--force-device-scale-factor=1"],
});
const page = await browser.newPage();
await page.goto(pageUrl, { waitUntil: "networkidle0" });

const failures = [];
const notes = [];

for (const width of [1440, 1280, 900, 390]) {
  await page.setViewport({ width, height: 900 });
  await new Promise((r) => setTimeout(r, 350));

  if (shotsDir) {
    await page.screenshot({
      path: join(shotsDir, `ranking-${width}.png`),
      fullPage: true,
    });
    await page.screenshot({
      path: join(shotsDir, `page-${width}.png`),
      fullPage: true,
    });
    for (const name of ["heatmap", "scatter", "calibration", "malformed", "models", "compare", "method"]) {
      const el = await page.$(`[data-section="${name}"]`);
      if (el) {
        await el.screenshot({ path: join(shotsDir, `${name}-${width}.png`) });
      }
    }
  }

  const report = await page.evaluate(() => {
    const out = {
      height: document.documentElement.scrollHeight,
      names: [],
      rankCells: [],
      geometry: [],
      sectionOverflow: null,
      textBoxes: [],
      amberOutside: [],
      amberUses: [],
      sectionBoxes: {},
      groupHeads: {},
      tiedCount: 0,
    };
    const vis = (el) => {
      const s = getComputedStyle(el);
      if (s.display === "none" || s.visibility === "hidden") return false;
      /* Content of a closed <details> is not rendered, whatever
       * its computed style says; only the summary shows. (Round
       * 10: the model index lives in closed details, and range
       * rects inside them report would-be geometry for content
       * that painted nothing, which read as thousands of false
       * text overlaps.) */
      const det = el.closest("details");
      if (det && !det.open && !el.closest("summary")) return false;
      return true;
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
        linkHref: row.querySelector(".name-link")
          ? row.querySelector(".name-link").getAttribute("href")
          : null,
        linkH: row.querySelector(".name-link")
          ? row.querySelector(".name-link").getBoundingClientRect().height
          : null,
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
    // Ranking containment (F-08). How far the ranking's rendered
    // content extends past the section's own box on each side,
    // and whether anything crosses the viewport edge.
    {
      const sec = document.querySelector("#ranking");
      if (sec) {
        const sr = sec.getBoundingClientRect();
        let overR = 0;
        let overL = 0;
        let pastViewport = 0;
        sec.querySelectorAll("*").forEach((el) => {
          const r = el.getBoundingClientRect();
          if (r.width === 0 || r.height === 0) return;
          overR = Math.max(overR, r.right - sr.right);
          overL = Math.max(overL, sr.left - r.left);
          if (r.right > innerWidth + 0.5 || r.left < -0.5) pastViewport++;
        });
        out.sectionOverflow = {
          overR: Math.round(overR * 10) / 10,
          overL: Math.round(overL * 10) / 10,
          pastViewport,
        };
      }
    }
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
    // Text boxes per chart section (the F-03 test extended).
    document.querySelectorAll("[data-section]").forEach((sec) => {
      const boxes = [];
      const walker = document.createTreeWalker(sec, NodeFilter.SHOW_TEXT, {
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
            boxes.push({
              text: node.textContent.trim().slice(0, 28),
              x0: rect.x,
              y0: rect.y,
              x1: rect.x + rect.width,
              y1: rect.y + rect.height,
            });
          }
        }
      }
      out.sectionBoxes[sec.getAttribute("data-section")] = boxes;
    });
    // Amber confinement (round 9 rule). Record every amber use
    // with its context; the Node side decides which contexts
    // are allowed.
    const AMBER = "rgb(232, 163, 61)";
    document.querySelectorAll("body *").forEach((el) => {
      if (!vis(el)) return;
      const s = getComputedStyle(el);
      const uses = [s.color, s.borderTopColor, s.backgroundColor].includes(AMBER);
      if (uses) {
        out.amberUses.push({
          desc: `${el.tagName}.${el.className} "${el.textContent.trim().slice(0, 24)}"`,
          inFlaggedStrip: !!el.closest('[data-group="flagged"]'),
          heatNameId:
            el.closest('[data-section="heatmap"]') &&
            el.closest(".heat-name")
              ? el.closest(".heat-name").getAttribute("data-run-id")
              : null,
          malId:
            el.closest('[data-section="malformed"]') &&
            el.closest(".mal-row")
              ? el.closest(".mal-row").getAttribute("data-run-id")
              : null,
          modelId:
            el.closest('[data-section="models"]') &&
            el.closest("[data-card-for]")
              ? el.closest("[data-card-for]").getAttribute("data-card-for")
              : null,
        });
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
    const msec = document.querySelector('[data-section="malformed"]');
    if (msec) {
      const axis = msec.querySelector(".mal-axis");
      const ar = axis ? axis.getBoundingClientRect() : null;
      const rows = [...msec.querySelectorAll(".mal-row")].map((r) => {
        const track = r.querySelector(".mal-track");
        const fill = r.querySelector(".mal-fill");
        const val = r.querySelector(".mal-value");
        const tr = track.getBoundingClientRect();
        const fr = fill.getBoundingClientRect();
        return {
          id: r.getAttribute("data-run-id"),
          value: val ? val.textContent.trim() : "",
          valueColor: val ? getComputedStyle(val).color : "",
          fillPct: tr.width > 0 ? (fr.width / tr.width) * 100 : null,
          fillRight: fr.right,
          trackLeft: tr.left,
          trackWidth: tr.width,
          flagged: !!r.querySelector(".flag-tag"),
        };
      });
      const line = msec.querySelector(".mal-line");
      const lr = line ? line.getBoundingClientRect() : null;
      const first = rows[0];
      out.mal = {
        rows,
        axisLeft: ar ? ar.left : null,
        axisWidth: ar ? ar.width : null,
        lineXPct:
          lr && first
            ? ((lr.left - first.trackLeft) / first.trackWidth) * 100
            : null,
        fold: msec.querySelector(".mal-fold")
          ? msec.querySelector(".mal-fold").textContent.replace(/\s+/g, " ").trim()
          : null,
      };
    }
    const modelsSec = document.querySelector('[data-section="models"]');
    if (modelsSec) {
      out.cards = {
        items: [...modelsSec.querySelectorAll("details.model-item")].map((d) => {
          const summary = d.querySelector("summary");
          const sr = summary.getBoundingClientRect();
          return {
            id: d.getAttribute("data-card-for"),
            anchorId: d.id,
            summaryH: sr.height,
            summarySW: summary.scrollWidth,
            summaryCW: summary.clientWidth,
          };
        }),
        groups: [...modelsSec.querySelectorAll("[data-mgroup]")].map((g) =>
          g.getAttribute("data-mgroup"),
        ),
      };
    }
    // Section bar and round 11 controls (sizes only; the
    // behaviour probes run in the desktop interaction block).
    const navEl = document.querySelector(".section-nav");
    if (navEl) {
      out.nav = {
        position: getComputedStyle(navEl).position,
        height: navEl.getBoundingClientRect().height,
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
      };
      /* Live-fix round (R-1). At phone widths the strip must be
       * the only horizontal scroller: the document stays at the
       * viewport width, and every link must come fully into the
       * strip's own box when the strip is scrolled to it, with
       * its text untruncated. Measured in-page by scrolling the
       * strip link by link; the strip is left back at its start. */
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
              inStrip:
                lr.left >= ir.left - 0.5 && lr.right <= ir.right + 0.5,
              untruncated: a.scrollWidth <= a.clientWidth + 1,
            });
          }
          inner.scrollLeft = 0;
        }
        out.nav.phone = {
          docScrollWidth: document.documentElement.scrollWidth,
          viewportWidth: window.innerWidth,
          reach,
        };
      }
    }
    const boxOf = (el) =>
      el
        ? { w: el.getBoundingClientRect().width, h: el.getBoundingClientRect().height }
        : null;
    out.controls = {
      swap: boxOf(document.querySelector(".cmp-swap")),
      pickers: [...document.querySelectorAll(".cmp-picker select")].map(boxOf),
      cardButtons: [...document.querySelectorAll(".card-controls button")].map(boxOf),
    };
    return out;
  });

  /* ---------- round 9 chart measurements ---------- */
  const chart = await page.evaluate(() => {
    const out = { countsLine: null, scatter: null, heat: null, cal: null };
    const countsEl = document.querySelector(".counts-line");
    out.countsLine = countsEl
      ? countsEl.textContent.replace(/\s+/g, " ").trim()
      : null;
    const sec = document.querySelector('[data-section="scatter"]');
    if (sec) {
      const svg = [...sec.querySelectorAll("svg")].find(
        (s) => s.getClientRects().length > 0,
      );
      if (svg) {
        const sr = svg.getBoundingClientRect();
        const pts = [];
        svg.querySelectorAll(".scatter-point").forEach((g) => {
          const c = g.querySelector("circle");
          if (!c) return;
          const cr = c.getBoundingClientRect();
          pts.push({
            id: g.getAttribute("data-run-id"),
            kind: g.getAttribute("data-scatter"),
            nudged: g.getAttribute("data-nudged") === "true",
            cx: cr.left + cr.width / 2,
            cy: cr.top + cr.height / 2,
            r: cr.width / 2,
          });
        });
        const fsOf = (sel) => {
          const el = svg.querySelector(sel);
          return el ? parseFloat(getComputedStyle(el).fontSize) : null;
        };
        out.scatter = {
          typeScale: {
            scale: sr.width / svg.viewBox.baseVal.width,
            label: fsOf(".scatter-label"),
            entry: fsOf(".scatter-entry-values"),
            cornerSub: fsOf(".corner-sub"),
            grid: fsOf(".grid-label"),
            tick: fsOf(".tick-label"),
            railHead: fsOf(".rail-head"),
            caption: fsOf(".axis-caption"),
          },
          entries: [...svg.querySelectorAll(".scatter-entry")].map((e) => {
            const c = e.querySelector("circle");
            return {
              id: e.getAttribute("data-entry-for"),
              stroke: c ? getComputedStyle(c).stroke : null,
            };
          }),
          corners: [...svg.querySelectorAll(".corner-note text")].map(
            (t) => {
              const r = t.getBoundingClientRect();
              return {
                text: t.textContent.trim().slice(0, 24),
                x0: r.left,
                y0: r.top,
                x1: r.right,
                y1: r.bottom,
              };
            },
          ),
          svgRect: {
            left: sr.left,
            top: sr.top,
            width: sr.width,
            height: sr.height,
          },
          vbW: svg.viewBox.baseVal.width,
          domainLo: Number(svg.getAttribute("data-domain-lo")),
          domainHi: Number(svg.getAttribute("data-domain-hi")),
          plot: svg.getAttribute("data-plot").split(",").map(Number),
          railCx: Number(svg.getAttribute("data-rail-cx")),
          points: pts,
          labels: [...svg.querySelectorAll("[data-label-for]")].map((t) => {
            const r = t.getBoundingClientRect();
            return {
              id: t.getAttribute("data-label-for"),
              x0: r.left,
              y0: r.top,
              x1: r.right,
              y1: r.bottom,
            };
          }),
          badges: [...svg.querySelectorAll(".pt-badge")].map((b) => ({
            id: b.closest(".scatter-point")?.getAttribute("data-run-id"),
            num: Number(b.querySelector("text")?.textContent),
          })),
          strokes: [...svg.querySelectorAll(".scatter-point")].map((g) => {
            const c = g.querySelector("circle");
            return {
              id: g.getAttribute("data-run-id"),
              stroke: c ? getComputedStyle(c).stroke : null,
            };
          }),
          leaders: svg.querySelectorAll(".leader").length,
          strayLines: [...svg.querySelectorAll("line")].filter(
            (ln) =>
              !ln.classList.contains("grid-line") &&
              !ln.classList.contains("rail-divider") &&
              !ln.classList.contains("axis-line"),
          ).length,
        };
      }
    }
    const hsec = document.querySelector('[data-section="heatmap"]');
    if (hsec) {
      const hSecRect = hsec.getBoundingClientRect();
      out.heat = {
        secL: hSecRect.left,
        secR: hSecRect.right,
        lede: (hsec.querySelector(".section-lede")?.textContent ?? "")
          .replace(/\s+/g, " ")
          .trim(),
        flagTags: hsec.querySelectorAll(".heat-name .flag-tag").length,
        heads: [...hsec.querySelectorAll(".heat-head")].map((h) => {
          const r = h.getBoundingClientRect();
          return {
            fam: h.getAttribute("data-family"),
            h: r.height,
            sw: h.scrollWidth,
            cw: h.clientWidth,
            sh: h.scrollHeight,
            ch: h.clientHeight,
            ws: getComputedStyle(h).whiteSpace,
            x0: r.left,
            x1: r.right,
          };
        }),
        cells: [...hsec.querySelectorAll(".heat-cell")].map((c) => {
          const s = getComputedStyle(c);
          const r = c.getBoundingClientRect();
          return {
            id: c.getAttribute("data-run-id"),
            fam: c.getAttribute("data-family"),
            text: c.textContent.trim(),
            bg: s.backgroundColor,
            color: s.color,
            x0: r.left,
            x1: r.right,
          };
        }),
        names: [...hsec.querySelectorAll(".heat-name")].map((n) => ({
          id: n.getAttribute("data-run-id"),
          sw: n.scrollWidth,
          cw: n.clientWidth,
        })),
      };
      const scroller = hsec.querySelector(".heat-scroll");
      const firstName = hsec.querySelector(".heat-name");
      if (scroller && firstName) {
        scroller.scrollLeft = scroller.scrollWidth;
        const cRect = scroller.getBoundingClientRect();
        const nRect = firstName.getBoundingClientRect();
        const nt = firstName
          .querySelector(".heat-name-text")
          .getBoundingClientRect();
        const rowId = firstName.getAttribute("data-run-id");
        const rowCells = [
          ...hsec.querySelectorAll(`.heat-cell[data-run-id="${rowId}"]`),
        ].map((c) => {
          const range = document.createRange();
          range.selectNodeContents(c);
          const tr = range.getClientRects()[0];
          return {
            fam: c.getAttribute("data-family"),
            textRect: tr ? { x0: tr.left, x1: tr.right } : null,
          };
        });
        out.heatProbe = {
          nameLeft: nRect.left - cRect.left,
          nameRight: nRect.right,
          nameBg: getComputedStyle(firstName).backgroundColor,
          groundBg: getComputedStyle(document.body).backgroundColor,
          nameTextRect: { x0: nt.left, x1: nt.right },
          rowCells,
        };
        scroller.scrollLeft = 0;
      }
    }
    const csec = document.querySelector('[data-section="calibration"]');
    if (csec) {
      const cSecRect = csec.getBoundingClientRect();
      out.cal = {
        lede: (csec.querySelector(".section-lede")?.textContent ?? "")
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
          const bin = p.querySelector("circle.cal-dot");
          const diag = p.querySelector(".cal-diag");
          const noteEl = p.querySelector(".cal-note");
          /* Cycle 5 (C-01): the tick numeral's size as the
           * reader meets it, the viewBox font size scaled by
           * the rendered SVG width over the 300-unit viewBox. */
          const svgEl = p.querySelector(".cal-svg");
          const tickEl = p.querySelector(".tk-y text, .tk-x text");
          const tick =
            svgEl && tickEl
              ? {
                  font: parseFloat(getComputedStyle(tickEl).fontSize),
                  svgW: svgEl.getBoundingClientRect().width,
                }
              : null;
          /* C-06: every tick numeral's own box, in viewBox
           * units (getBBox is geometry, so hidden groups
           * measure the same as shown ones). */
          const tickBoxes = [...p.querySelectorAll(".tk-y text, .tk-x text")].map(
            (t) => {
              const b = t.getBBox();
              return { x0: b.x, y0: b.y, x1: b.x + b.width, y1: b.y + b.height };
            },
          );
          /* C-08: which tick groups this panel actually
           * shows, from the rendered style. */
          const tkY = p.querySelector(".tk-y");
          const tkX = p.querySelector(".tk-x");
          const tkShown = {
            y: tkY ? getComputedStyle(tkY).display !== "none" : false,
            x: tkX ? getComputedStyle(tkX).display !== "none" : false,
          };
          /* Round 40: the panel name's own lines, read by
           * bucketing its text node's characters by line top,
           * so the wrap rule is measured rather than eyeballed. */
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
            bin: bin
              ? {
                  cx: Number(bin.getAttribute("cx")),
                  cy: Number(bin.getAttribute("cy")),
                  f: Number(bin.getAttribute("data-f")),
                  o: Number(bin.getAttribute("data-o")),
                }
              : null,
            diag: diag
              ? [diag.x1.baseVal.value, diag.y1.baseVal.value, diag.x2.baseVal.value, diag.y2.baseVal.value]
              : null,
          };
        }),
        rail: [...csec.querySelectorAll("[data-rail-for]")].map((a) =>
          a.getAttribute("data-rail-for"),
        ),
        railLinks: [...csec.querySelectorAll(".cal-rail-link")].map(
          (a) => {
            const r = a.getBoundingClientRect();
            return { t: r.top, b: r.bottom };
          },
        ),
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
    }
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
  // Round 11: every ranking name links to its model page.
  let minLinkH = Infinity;
  for (const n of report.names) {
    const row = byRunId.get(n.runId);
    if (!row) continue;
    const want = `/models/${slugOfA(row)}/`;
    if (n.linkHref !== want) {
      failures.push(
        `width ${width}: row ${n.runId} name links to "${n.linkHref}", the slug rule gives "${want}"`,
      );
    }
    if (n.linkH !== null) minLinkH = Math.min(minLinkH, n.linkH);
  }
  if (minLinkH !== Infinity) {
    notes.push(
      `width ${width}: ranking name links measured, smallest height ${minLinkH.toFixed(1)} px (WCAG 2.5.8 floor is 24 px; gated since the convergence round found the inline case does not apply)`,
    );
    if (minLinkH < 23.9) {
      failures.push(
        `width ${width}: ranking name link height ${minLinkH.toFixed(1)} px is under the 24 px target floor (2.5.8)`,
      );
    }
  }
  // F-01: rank column.
  for (const cell of report.rankCells) {    const row = byRunId.get(cell.runId);
    if (cell.group === "flagged") {
      if (cell.text !== "") {
        failures.push(
          `width ${width}: flagged row ${cell.runId} rank cell holds "${cell.text}"`,
        );
      }
    } else if (cell.text !== String(row.rank)) {
      failures.push(
        `width ${width}: row ${cell.runId} rank cell holds "${cell.text}", group rank is ${row.rank}`,
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
  // Amber confinement (round 9 rule, extended in round 10 with
  // the malformed flagged rows and the flagged index cards).
  for (const use of report.amberUses) {
    const allowed =
      use.inFlaggedStrip ||
      (use.heatNameId !== null && flaggedIdsA.has(use.heatNameId)) ||
      (use.malId !== null && flaggedIdsA.has(use.malId)) ||
      (use.modelId !== null && flaggedIdsA.has(use.modelId));
    if (!allowed) {
      failures.push(`width ${width}: amber outside its allowed contexts on ${use.desc}`);
    }
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
  // Ranking containment (F-08, cycle 2, doctrine D8). Phone rows
  // re-flow inside the section box, so the limit there is the
  // box itself. At desktop widths the rows bleed a designed
  // 14 px into the page padding; the limit pins that bleed so
  // it cannot grow silently toward the viewport.
  if (report.sectionOverflow) {
    const o = report.sectionOverflow;
    const limit = width <= 760 ? 1 : 15;
    if (o.overR > limit || o.overL > limit) {
      failures.push(
        `width ${width}: ranking content extends ${Math.max(o.overR, o.overL)}px past the section edge (F-08 limit ${limit}px)`,
      );
    }
    if (o.pastViewport > 0) {
      failures.push(
        `width ${width}: ${o.pastViewport} ranking elements extend past the viewport (F-08)`,
      );
    }
  }
  // Group head facts. The headers name their populations in
  // words; the suite's size is stated once, in the method
  // section, and is not repeated in group headers (owner,
  // 2026-10-25). The assertions check the population words.
  if (!report.groupHeads.slices?.toLowerCase().includes("abstain subset")) {
    failures.push(
      `width ${width}: slice group header does not name the abstain subset (${report.groupHeads.slices})`,
    );
  }
  if (!report.groupHeads.full?.toLowerCase().includes("full suite")) {
    failures.push(
      `width ${width}: full group header does not name the full suite (${report.groupHeads.full})`,
    );
  }
  /* ---------- round 9 assertions ---------- */
  // Tiles per width.
  const cm = chart.countsLine?.match(
    /board holds ([\d,]+) results from ([\d,]+) models\. ([\d,]+) models are ranked and ([\d,]+) are flagged\./,
  );
  if (!cm) {
    failures.push(`width ${width}: counts line not found for the tile check`);
  } else {
    const printed = cm.slice(1).map((s) => Number(s.replace(/,/g, "")));
    const expected = [
      displayCountsA.results,
      displayCountsA.tested,
      displayCountsA.ranked,
      displayCountsA.flagged,
    ];
    if (JSON.stringify(printed) !== JSON.stringify(expected)) {
      failures.push(
        `width ${width}: tiles print ${printed.join("/")}, display rule gives ${expected.join("/")}`,
      );
    }
  }
  // Per-section text overlap (F-03 extended).
  for (const [secName, secBoxes] of Object.entries(report.sectionBoxes)) {
    for (let i = 0; i < secBoxes.length; i++) {
      for (let j = i + 1; j < secBoxes.length; j++) {
        const a = secBoxes[i];
        const b = secBoxes[j];
        const ox = Math.min(a.x1, b.x1) - Math.max(a.x0, b.x0);
        const oy = Math.min(a.y1, b.y1) - Math.max(a.y0, b.y0);
        if (ox > 0.5 && oy > 0.5) {
          failures.push(
            `width ${width}: text overlap in ${secName}: "${a.text}" x "${b.text}" by ${ox.toFixed(1)}x${oy.toFixed(1)} px`,
          );
        }
      }
    }
  }
  // Scatter.
  if (!chart.scatter) {
    failures.push(`width ${width}: no visible scatter SVG`);
  } else {
    const sc = chart.scatter;
    const scale = sc.svgRect.width / sc.vbW;
    const [px0, py0, px1, py1] = sc.plot;
    const logLo = Math.log10(sc.domainLo);
    const logSpan = Math.log10(sc.domainHi) - logLo;
    const seenPlot = new Set();
    const seenRail = new Set();
    for (const p of sc.points) {
      const row = byRunId.get(p.id);
      if (!row) {
        failures.push(`width ${width}: scatter point for unknown row ${p.id}`);
        continue;
      }
      (p.kind === "plot" ? seenPlot : seenRail).add(p.id);
      const vx =
        p.kind === "plot"
          ? px0 + ((Math.log10(row.total_cost_usd) - logLo) / logSpan) * (px1 - px0)
          : sc.railCx;
      const vy = py0 + (1 - row.asr_conditional / 0.3) * (py1 - py0);
      const expCx = sc.svgRect.left + vx * scale;
      const expCy = sc.svgRect.top + vy * scale;
      if (Math.abs(p.cx - expCx) > 2) {
        failures.push(
          `width ${width}: scatter point ${p.id} centre x off by ${(p.cx - expCx).toFixed(1)} px`,
        );
      }
      const yTol = p.nudged ? (width > 760 ? 13.5 : 19.5) : 2;
      if (Math.abs(p.cy - expCy) > yTol) {
        failures.push(
          `width ${width}: scatter point ${p.id} centre y off by ${(p.cy - expCy).toFixed(1)} px (nudged ${p.nudged})`,
        );
      }
    }
    if (JSON.stringify([...seenPlot].sort()) !== JSON.stringify([...plottedIdsA].sort())) {
      failures.push(`width ${width}: plotted point set differs from the payload population`);
    }
    /* Rail coverage (mobile-fix amendment). The wide variant
     * stands its rail points in the plot as markers; the
     * phone variant carries no rail column, and its rail
     * population stands in the list under the plot, each
     * entry carrying the point's own disc. Either form covers
     * the population; a rail point missing from both fails. */
    const railCovered = new Set([
      ...seenRail,
      ...sc.entries.map((e) => e.id).filter((id) => railIdsA.has(id)),
    ]);
    if (JSON.stringify([...railCovered].sort()) !== JSON.stringify([...railIdsA].sort())) {
      failures.push(`width ${width}: rail point set differs from the payload population`);
    }
    for (const s of sc.strokes) {
      const isAmber = s.stroke === "rgb(232, 163, 61)";
      if (flaggedIdsA.has(s.id) && !isAmber) {
        failures.push(`width ${width}: flagged scatter point ${s.id} lacks its amber ring`);
      }
      if (!flaggedIdsA.has(s.id) && isAmber) {
        failures.push(`width ${width}: ranked scatter point ${s.id} carries amber`);
      }
    }
    for (const e of sc.entries) {
      if (!e.id) continue;
      const isAmber = e.stroke === "rgb(232, 163, 61)";
      if (flaggedIdsA.has(e.id) && !isAmber) {
        failures.push(`width ${width}: flagged scatter entry ${e.id} lacks its amber ring`);
      }
      if (!flaggedIdsA.has(e.id) && isAmber) {
        failures.push(`width ${width}: ranked scatter entry ${e.id} carries amber`);
      }
    }
    /* Disc clearance (mobile-fix). The centre test below
     * cannot see a label resting on a disc's body, which is
     * what the phone cluster shipped: a label rect may not
     * intersect any point's disc rect, its own point's
     * included, at any width. */
    for (const l of sc.labels) {
      for (const p of sc.points) {
        const ox =
          Math.min(l.x1, p.cx + p.r) - Math.max(l.x0, p.cx - p.r);
        const oy =
          Math.min(l.y1, p.cy + p.r) - Math.max(l.y0, p.cy - p.r);
        if (ox > 1 && oy > 1) {
          failures.push(
            `width ${width}: scatter label ${l.id} rests on disc ${p.id} by ${ox.toFixed(1)}x${oy.toFixed(1)} px`,
          );
        }
      }
    }
    /* Type floor (mobile-fix). Scatter data text renders at
     * its computed size times the chart's own scale (the
     * ratio of the SVG's rendered width to its viewBox
     * width); nothing may render under the doctrine's 10 px
     * floor. The pre-fix phone chart set labels at 10 units
     * in a 358-unit viewBox squeezed into 328 px, with entry
     * values and corner subs at 9.5: 9.2 and 8.7 px rendered. */
    /* Presence is part of the floor (cycle 3 red team,
     * RT-6): a class the design guarantees may not vanish
     * and take its measurement with it. Labels, grid
     * numerals, tick labels, captions and the corner sub
     * stand at every width; the rail head stands wherever
     * the wide island does. Entry values ride the overflow
     * stack, whose population is the solver's choice, so
     * they are measured when present, not required. */
    const floorRequired = ["label", "grid", "tick", "caption", "cornerSub"];
    if (width > 760) floorRequired.push("railHead");
    for (const [kind, fs] of Object.entries(sc.typeScale)) {
      if (kind === "scale") continue;
      if (fs === null) {
        if (floorRequired.includes(kind)) {
          failures.push(
            `width ${width}: scatter ${kind} text is absent, so the type floor has nothing to measure`,
          );
        }
        continue;
      }
      const rendered = fs * sc.typeScale.scale;
      if (rendered < 9.95) {
        failures.push(
          `width ${width}: scatter ${kind} text renders at ${rendered.toFixed(1)} px, under the 10 px floor`,
        );
      }
    }
    /* Corner containment (mobile-fix). The corner readings
     * sit inside the panel by construction; a reading whose
     * rect escapes the SVG's box is the clipped reading the
     * phone render shipped. */
    for (const c of sc.corners) {
      if (
        c.x0 < sc.svgRect.left - 1 ||
        c.y0 < sc.svgRect.top - 1 ||
        c.x1 > sc.svgRect.left + sc.svgRect.width + 1 ||
        c.y1 > sc.svgRect.top + sc.svgRect.height + 1
      ) {
        failures.push(
          `width ${width}: corner reading "${c.text}" escapes the chart panel`,
        );
      }
    }
    // Every point carries its name at every width (redesign
    // rule). Labels never overlap each other and never cover a
    // point centre, and the numbered badges of the old design
    // are gone entirely. The label population equality above
    // is the live guard that every point is named.
    {
      const labels = sc.labels;
      for (let i = 0; i < labels.length; i++) {
        for (let j = i + 1; j < labels.length; j++) {
          const a = labels[i];
          const b = labels[j];
          const ox = Math.min(a.x1, b.x1) - Math.max(a.x0, b.x0);
          const oy = Math.min(a.y1, b.y1) - Math.max(a.y0, b.y0);
          if (ox > 0.5 && oy > 0.5) {
            failures.push(
              `width ${width}: scatter labels overlap: ${a.id} x ${b.id} by ${ox.toFixed(1)}x${oy.toFixed(1)} px`,
            );
          }
        }
        for (const p of sc.points) {
          if (
            p.cx > labels[i].x0 - 1 &&
            p.cx < labels[i].x1 + 1 &&
            p.cy > labels[i].y0 - 1 &&
            p.cy < labels[i].y1 + 1
          ) {
            failures.push(
              `width ${width}: scatter label ${labels[i].id} covers point ${p.id}`,
            );
          }
        }
      }
      const labelledIds = labels.map((l) => l.id).sort();
      const populationIds = [...plottedIdsA, ...railIdsA].sort();
      if (JSON.stringify(labelledIds) !== JSON.stringify(populationIds)) {
        failures.push(
          `width ${width}: scatter labels cover ${labelledIds.length} points, population is ${populationIds.length} (missing ${populationIds.filter((id) => !labelledIds.includes(id)).join(",")})`,
        );
      }
      if (sc.badges.length > 0) {
        failures.push(
          `width ${width}: scatter still carries ${sc.badges.length} numbered badges`,
        );
      }
      if (sc.leaders > 0) {
        failures.push(
          `width ${width}: scatter carries ${sc.leaders} leader lines (the no-leader-line rule)`,
        );
      }
      if (sc.strayLines > 0) {
        failures.push(
          `width ${width}: scatter carries ${sc.strayLines} lines outside its grid, divider, axes and lower-bound ticks (the no-leader-line rule)`,
        );
      }
    }
  }
  // Heatmap.
  if (!chart.heat) {
    failures.push(`width ${width}: heatmap not measured`);
  } else {
    /* The header contract is clipping, on both axes, at
     * every width (design cycle 3 calibration): a header
     * fails when its content overflows its box horizontally
     * or vertically. The 30 px height ceiling is the
     * one-line contract and applies only where the heads
     * are nowrap; in the 761-953 band the design wraps
     * multi-word headers between words, where two lines at
     * the board's sizes measure 32 px and nothing is
     * clipped. The pre-fix build at the new 900 gate failed
     * both forms: two heads read scroll 61 against client
     * 56, and the whole row stood 32 tall under nowrap
     * assumptions the band never had. */
    for (const h of chart.heat.heads) {
      if (
        h.sw > h.cw + 1 ||
        h.sh > h.ch + 1 ||
        (h.ws === "nowrap" && h.h > 30)
      ) {
        failures.push(
          `width ${width}: heatmap header ${h.fam} wraps or clips (height ${h.h.toFixed(0)}, scroll ${h.sw}x${h.sh} vs client ${h.cw}x${h.ch})`,
        );
      }
    }
    if (chart.heat.heads.map((h) => h.fam).join() !== familyOrderA.join()) {
      failures.push(`width ${width}: heatmap column order differs from the payload rule`);
    }
    if (chart.heat.cells.length !== cellExpectedA.size) {
      failures.push(
        `width ${width}: heatmap holds ${chart.heat.cells.length} cells, expected ${cellExpectedA.size}`,
      );
    }
    for (const c of chart.heat.cells) {
      const expected = cellExpectedA.get(`${c.id}|${c.fam}`);
      if (c.text !== expected) {
        failures.push(
          `width ${width}: heatmap cell ${c.id}/${c.fam} prints "${c.text}", payload gives "${expected}"`,
        );
      }
      const bg = parseRgbA(c.bg);
      const fg = parseRgbA(c.color);
      if (bg && fg) {
        const ratio = contrastA(fg, bg);
        if (ratio < 4.49) {
          failures.push(
            `width ${width}: heatmap cell ${c.id}/${c.fam} text contrast ${ratio.toFixed(2)} is under 4.5`,
          );
        }
        if (bg[1] > bg[0] + 40 && bg[1] > bg[2] + 40) {
          failures.push(
            `width ${width}: heatmap cell ${c.id}/${c.fam} background is green dominant (${c.bg})`,
          );
        }
      }
    }
    for (const n of chart.heat.names) {
      if (n.sw > n.cw + 1) {
        failures.push(`width ${width}: heatmap name for ${n.id} is clipped`);
      }
    }
    /* H-01 (design cycle 5, doctrine D8): every header and
     * every cell sits inside the section's horizontal bounds.
     * The pre-fix grid ran 28 px past the section at desktop
     * (its last column's header cut mid-word) and 802 px past
     * it on the phone, where ten families sat off canvas in a
     * horizontal scroller cued only by a prose line. On the
     * phone the hidden headers measure zero width at the
     * section's left and pass trivially; the cells are the
     * substance there. */
    for (const h of chart.heat.heads) {
      if (h.x1 - h.x0 < 1) continue; // display:none (phone restack)
      if (h.x0 < chart.heat.secL - 1 || h.x1 > chart.heat.secR + 1) {
        failures.push(
          `width ${width}: heatmap header ${h.fam} sits outside the section bounds (${h.x0.toFixed(0)}..${h.x1.toFixed(0)} vs ${chart.heat.secL.toFixed(0)}..${chart.heat.secR.toFixed(0)}) (H-01)`,
        );
      }
    }
    let cellsOut = 0;
    for (const c of chart.heat.cells) {
      if (c.x0 < chart.heat.secL - 1 || c.x1 > chart.heat.secR + 1) cellsOut++;
    }
    if (cellsOut > 0) {
      failures.push(
        `width ${width}: ${cellsOut} heatmap cells sit outside the section's horizontal bounds (H-01)`,
      );
    }
    /* H-02 (design cycle 5, red team F2): the lede names the
     * three groups with their counts, so a phone reader who
     * meets the section's head knows the flagged results and
     * the slices stand further down the list. Counts derive
     * from the payload: slices are the partial-case rows, the
     * flagged count is read off the rendered flag tags, and
     * the full suite is the remainder. */
    {
      const sliceCount = allRowsA.filter(
        (r) => r.n_cases !== fullCasesA,
      ).length;
      const fullCount =
        allRowsA.length - sliceCount - chart.heat.flagTags;
      const want = `${fullCount} full suite results, ${chart.heat.flagTags} flagged results, and ${sliceCount} guardrail slices`;
      if (!chart.heat.lede.includes(want)) {
        failures.push(
          `width ${width}: heatmap lede does not name the groups with their counts ("${want}") (H-02)`,
        );
      }
    }
    if (chart.heatProbe) {
      const probe = chart.heatProbe;
      if (Math.abs(probe.nameLeft) > 1.5) {
        failures.push(
          `width ${width}: sticky name column drifted ${probe.nameLeft.toFixed(1)} px from the container left at full scroll`,
        );
      }
      /* The sticky column must sit on the page ground itself,
       * read from the rendered body rather than a literal, so
       * the check follows the --ground token when it moves
       * (the redesign retokened the ground and a stale literal
       * failed every width until 2026-10-25). */
      if (probe.nameBg !== probe.groundBg) {
        failures.push(
          `width ${width}: sticky name column background is ${probe.nameBg}, not opaque ground (${probe.groundBg})`,
        );
      }
      for (const cell of probe.rowCells) {
        if (!cell.textRect) continue;
        if (cell.textRect.x0 >= probe.nameRight - 1) {
          const ox =
            Math.min(cell.textRect.x1, probe.nameTextRect.x1) -
            Math.max(cell.textRect.x0, probe.nameTextRect.x0);
          if (ox > 0.5) {
            failures.push(
              `width ${width}: name text overlaps visible cell text in family ${cell.fam} by ${ox.toFixed(1)} px (F-06)`,
            );
          }
        }
      }
    }
  }
  // Calibration.
  if (!chart.cal) {
    failures.push(`width ${width}: calibration not measured`);
  } else {
    const panelIds = chart.cal.panels.map((p) => p.id);
    if (JSON.stringify(panelIds) !== JSON.stringify(calOrderA)) {
      failures.push(`width ${width}: calibration panel order is not attacked ECE order`);
    }
    if (JSON.stringify(chart.cal.rail) !== JSON.stringify(calOrderA)) {
      failures.push(`width ${width}: calibration rail order differs from panel order`);
    }
    for (const p of chart.cal.panels) {
      const row = byRunId.get(p.id);
      if (!row) continue;
      const expectedEce = quantA(eceOfA(row), 3);
      if (p.ece !== expectedEce) {
        failures.push(
          `width ${width}: calibration panel ${p.id} header ECE ${p.ece}, payload gives ${expectedEce}`,
        );
      }
      if (p.nameClip) {
        failures.push(`width ${width}: calibration panel name clipped on ${p.id}`);
      }
      if (p.metaClip) {
        failures.push(`width ${width}: calibration panel meta clipped on ${p.id}`);
      }
    }
    /* C-07 (round 12, revised in design cycle 5): no panel
     * carries the coincidence note; the lede states the fact
     * once, with the count of the derived coincident set. */
    for (const p of chart.cal.panels) {
      if (p.note !== null) {
        failures.push(
          `width ${width}: calibration panel ${p.id} carries a coincidence note ("${p.note}"); the fact belongs in the lede (C-07)`,
        );
      }
    }
    const nCoincident = coincidentSliceIdsA.size;
    if (nCoincident > 0) {
      const coincidentNames = calOrderA
        .filter((id) => coincidentSliceIdsA.has(id))
        .map((id) => shortName(byRunId.get(id)));
      const list =
        coincidentNames.length > 1
          ? `${coincidentNames.slice(0, -1).join(", ")} and ${coincidentNames[coincidentNames.length - 1]}`
          : (coincidentNames[0] ?? "");
      const want = `${nCoincident} slice result${nCoincident === 1 ? "" : "s"}, ${list}, state${nCoincident === 1 ? "s" : ""} nearly the same confidence from bin to bin, so their bins pile up at the right edge of their panels`;
      if (!chart.cal.lede.includes(want)) {
        failures.push(
          `width ${width}: calibration lede does not state the coincidence ("${want}") (C-07)`,
        );
      }
    } else if (chart.cal.lede.includes("pile up at the right edge")) {
      failures.push(
        `width ${width}: calibration lede states a coincidence the payload does not hold (C-07)`,
      );
    }
    /* C-01 (design cycle 5, doctrine D17): tick numerals
     * render at the legibility floor. The pre-fix size
     * rendered at 6.3 px on desktop and 5.2 px on the phone. */
    let worstTick = Infinity;
    for (const p of chart.cal.panels) {
      if (!p.tick || !(p.tick.svgW > 0)) continue;
      worstTick = Math.min(worstTick, (p.tick.font * p.tick.svgW) / 300);
    }
    if (worstTick !== Infinity) {
      notes.push(
        `width ${width}: calibration tick numerals render at ${worstTick.toFixed(1)} px at their smallest (floor 10 px, C-01)`,
      );
      if (worstTick < 9.9) {
        failures.push(
          `width ${width}: calibration tick numerals render at ${worstTick.toFixed(1)} px, under the 10 px legibility floor (C-01)`,
        );
      }
    }
    /* C-06 (design cycle 5): every tick numeral's box stays
     * inside the viewBox. Enlarging the numerals for C-01
     * pushed the centered "100" x tick past the right edge
     * (278..306 in a 300-wide viewBox) until the last tick
     * was end-anchored; this check is the pin. Tolerance 2
     * units for font bearing slack. */
    for (const p of chart.cal.panels) {
      for (const b of p.tickBoxes ?? []) {
        if (b.x0 < -2 || b.x1 > 302 || b.y0 < -2 || b.y1 > 168) {
          failures.push(
            `width ${width}: calibration panel ${p.id} tick numeral box ${b.x0.toFixed(0)}..${b.x1.toFixed(0)} x ${b.y0.toFixed(0)}..${b.y1.toFixed(0)} escapes the 300 x 166 viewBox (C-06)`,
          );
        }
      }
    }
    /* C-08 (design cycle 5): the panels showing each axis are
     * exactly the array's edge panels for the layout in
     * force. Desktop: the first column shows y ticks and the
     * last row shows x ticks. Phone (one across): every panel
     * shows both, since a phone panel travels alone (D23).
     * The pre-fix desktop rule lit x ticks on the last four
     * children, one panel too many (kev-4b, mid-array). */
    {
      const panels = chart.cal.panels;
      const cols = chart.cal.gridCols || 4;
      const n = panels.length;
      const lastRow = n % cols === 0 ? cols : n % cols;
      panels.forEach((p, i) => {
        if (!p.tick || !p.tkShown) return;
        const wantY = width <= 760 ? true : i % cols === 0;
        const wantX = width <= 760 ? true : i >= n - lastRow;
        if (p.tkShown.y !== wantY || p.tkShown.x !== wantX) {
          failures.push(
            `width ${width}: calibration panel ${p.id} tick visibility (y ${p.tkShown.y}, x ${p.tkShown.x}) breaks the array's edge rule (want y ${wantY}, x ${wantX}) (C-08)`,
          );
        }
      });
    }
    /* C-02 (design cycle 5): on the phone the rail is a list,
     * one entry per line. The pre-fix flex-wrap packing put
     * 24 pairs of entries on shared lines (census L-32). */
    if (width <= 760 && chart.cal.railLinks) {
      let shared = 0;
      const links = chart.cal.railLinks;
      for (let i = 0; i < links.length; i++) {
        for (let j = i + 1; j < links.length; j++) {
          if (links[i].t < links[j].b - 2 && links[j].t < links[i].b - 2) {
            shared++;
          }
        }
      }
      if (shared > 0) {
        failures.push(
          `width ${width}: ${shared} calibration rail entry pairs share a line (C-02)`,
        );
      }
    }
    /* C-04 (design cycle 5, doctrine D18): a wrapped panel
     * name breaks only after a hyphen or a space, never
     * mid-token and never stranding a hyphen at a line's
     * head. The pre-fix phone build broke Qwen3Guard-Gen-4B
     * as "Qwen3Gua / rd-Gen-4B" and Shieldstral-1.0-3B as
     * "Shieldstral / -1.0-3B". */
    for (const p of chart.cal.panels) {
      const lines = p.nameLines ?? [];
      for (let i = 0; i < lines.length - 1; i++) {
        const legal =
          /[-\s]$/.test(lines[i]) || /^\s/.test(lines[i + 1]);
        if (!legal) {
          failures.push(
            `width ${width}: calibration panel ${p.id} name breaks mid-token ("${lines[i]} | ${lines[i + 1]}") (C-04)`,
          );
        }
      }
    }
    /* C-05 (design cycle 5): rail names stay inside the
     * section's horizontal bounds. Census R-23 reported the
     * rail past the section's left edge; on the cycle 5
     * baseline build the names measure inside at rest, and
     * this check pins that so a real regression fails. */
    for (const rn of chart.cal.railNames) {
      if (rn.l < chart.cal.secL - 1 || rn.r > chart.cal.secR + 1) {
        failures.push(
          `width ${width}: calibration rail name "${rn.text}" sits outside the section bounds (C-05)`,
        );
      }
    }
    /* Round 40: a wrapped panel name may not strand its final
     * hyphen segment alone on the last line. The defect form is
     * precise: at least two lines, a last line of five
     * characters or fewer holding no hyphen, under a line that
     * ends with one. */
    for (const p of chart.cal.panels) {
      const lines = p.nameLines ?? [];
      if (lines.length < 2) continue;
      const last = lines[lines.length - 1].trim();
      const prev = lines[lines.length - 2].trimEnd();
      if (last.length <= 5 && !last.includes("-") && prev.endsWith("-")) {
        failures.push(
          `width ${width}: calibration panel ${p.id} name strands its final segment "${last}" alone on the last line`,
        );
      }
    }
    for (const rn of chart.cal.railNames) {
      if (rn.sw > rn.cw + 1) {
        failures.push(
          `width ${width}: calibration rail name "${rn.text}" is clipped (F-16)`,
        );
      }
    }
    const sampleIdx = [0, Math.floor(chart.cal.panels.length / 2), chart.cal.panels.length - 1];
    for (const idx of sampleIdx) {
      const p = chart.cal.panels[idx];
      if (!p || !p.bin || !p.diag) continue;
      const row = byRunId.get(p.id);
      const bins = row?.detail?.calibration?.reliability_bins?.attacked?.bins;
      if (!bins || bins.length === 0) continue;
      const b0 = bins[0];
      if (p.bin.f !== b0.mean_forecast || p.bin.o !== b0.mean_outcome) {
        failures.push(`width ${width}: panel ${p.id} first bin data attrs disagree with the payload`);
        continue;
      }
      const [dx1, dy1, dx2, dy2] = p.diag;
      const expCx = dx1 + b0.mean_forecast * (dx2 - dx1);
      const expCy = dy1 + b0.mean_outcome * (dy2 - dy1);
      if (Math.abs(p.bin.cx - expCx) > 0.6 || Math.abs(p.bin.cy - expCy) > 0.6) {
        failures.push(
          `width ${width}: panel ${p.id} first bin at ${p.bin.cx},${p.bin.cy}, payload position is ${expCx.toFixed(1)},${expCy.toFixed(1)}`,
        );
      }
    }
  }
  /* ---------- round 10 assertions ---------- */
  // Malformed.
  if (!report.mal) {
    failures.push(`width ${width}: malformed section not measured`);
  } else {
    const mal = report.mal;
    if (mal.rows.length !== printedMalA.length) {
      failures.push(
        `width ${width}: malformed holds ${mal.rows.length} bar rows, payload implies ${printedMalA.length}`,
      );
    }
    mal.rows.forEach((mr, i) => {
      const row = printedMalA[i];
      if (!row) return;
      if (mr.id !== row.run_id) {
        failures.push(
          `width ${width}: malformed row ${i + 1} is ${mr.id}, worst-first order expects ${row.run_id}`,
        );
      }
      if (mr.value !== fmtPctA(row.malformed_rate)) {
        failures.push(
          `width ${width}: malformed row ${mr.id} prints "${mr.value}", payload gives "${fmtPctA(row.malformed_rate)}"`,
        );
      }
      const expPct = (row.malformed_rate / 0.15) * 100;
      if (mr.fillPct === null || Math.abs(mr.fillPct - expPct) > 1.6) {
        failures.push(
          `width ${width}: malformed bar ${mr.id} fills ${mr.fillPct?.toFixed(1)} percent of its track, the 0 to 15 axis expects ${expPct.toFixed(1)}`,
        );
      }
      /* Live-fix round (2026-10-23). The fill-versus-track check
       * above cannot see a track that disagrees with the axis:
       * both are percentages of the same track. This assertion
       * measures the bar's right edge against the AXIS element's
       * own span, the scale the ticks and the admission line are
       * read on, so a bar that ends short of (or past) its value
       * on the printed axis fails the audit. Tolerance is 1.5
       * percent of the axis span. */
      const endAxisPct =
        mal.axisWidth && mal.axisWidth > 0
          ? ((mr.fillRight - mal.axisLeft) / mal.axisWidth) * 100
          : null;
      if (endAxisPct === null || Math.abs(endAxisPct - expPct) > 1.5) {
        failures.push(
          `width ${width}: malformed bar ${mr.id} ends at ${endAxisPct?.toFixed(1)} percent of the axis span, its value on the 0 to 15 axis expects ${expPct.toFixed(1)}`,
        );
      }
      const isFlagged = flaggedIdsA.has(mr.id);
      if (mr.flagged !== isFlagged) {
        failures.push(
          `width ${width}: malformed row ${mr.id} flagged tag presence is ${mr.flagged}, payload says ${isFlagged}`,
        );
      }
      const amberVal = mr.valueColor === "rgb(232, 163, 61)";
      if (isFlagged && !amberVal) {
        failures.push(`width ${width}: flagged malformed value ${mr.id} is not amber`);
      }
      if (!isFlagged && amberVal) {
        failures.push(`width ${width}: ranked malformed value ${mr.id} carries amber`);
      }
    });
    if (mal.lineXPct === null || Math.abs(mal.lineXPct - 100 / 3) > 0.6) {
      failures.push(
        `width ${width}: admission line stands at ${mal.lineXPct?.toFixed(2)} percent of the track, the 5 percent mark on a 0 to 15 axis is 33.33`,
      );
    }
    if (
      foldedMalA > 0 &&
      (!mal.fold ||
        !mal.fold.includes(`${foldedMalA} results printed a malformed rate of 0.0`))
    ) {
      failures.push(
        `width ${width}: malformed fold line does not state the folded count ${foldedMalA} (${mal.fold})`,
      );
    }
  }
  // Cards.
  if (!report.cards) {
    failures.push(`width ${width}: model index not measured`);
  } else {
    const cards = report.cards;
    if (cards.items.length !== allRowsA.length) {
      failures.push(
        `width ${width}: model index holds ${cards.items.length} items, payload holds ${allRowsA.length}`,
      );
    }
    if (JSON.stringify(cards.groups) !== JSON.stringify(["full", "flagged", "slices"])) {
      failures.push(
        `width ${width}: model index groups are ${cards.groups.join(",")}, expected full,flagged,slices`,
      );
    }
    for (const item of cards.items) {
      const row = byRunId.get(item.id);
      if (!row) {
        failures.push(`width ${width}: index item for unknown row ${item.id}`);
        continue;
      }
      if (item.anchorId !== `model-${slugOfA(row)}`) {
        failures.push(
          `width ${width}: index item ${item.id} anchors at "${item.anchorId}", slug rule gives "model-${slugOfA(row)}"`,
        );
      }
      if (item.summaryH < 43.5) {
        failures.push(
          `width ${width}: index summary for ${item.id} is ${item.summaryH.toFixed(1)} px tall, under the 44 px tap target`,
        );
      }
      if (item.summarySW > item.summaryCW + 1) {
        failures.push(
          `width ${width}: index summary for ${item.id} overflows horizontally (${item.summarySW} vs ${item.summaryCW})`,
        );
      }
    }
  }
  // Round 11: section bar presence, order, and target sizes;
  // control sizes (WCAG 2.5.8, 24 px floor for block controls).
  const NAV_EXPECTED_A = [
    ["ranking", "Ranking"],
    ["malformed", "Malformed"],
    ["families", "Families"],
    ["cost", "Cost"],
    ["calibration", "Calibration"],
    ["models", "Models"],
    ["compare", "Compare"],
    ["method", "Method"],
  ];
  if (!report.nav) {
    failures.push(`width ${width}: section nav not rendered`);
  } else {
    if (report.nav.position !== "sticky") {
      failures.push(
        `width ${width}: section nav computes position ${report.nav.position}, not sticky`,
      );
    }
    if (report.nav.links.length !== NAV_EXPECTED_A.length) {
      failures.push(
        `width ${width}: section nav holds ${report.nav.links.length} links, expected ${NAV_EXPECTED_A.length}`,
      );
    }
    report.nav.links.forEach((link, i) => {
      const [id, label] = NAV_EXPECTED_A[i] ?? [];
      if (link.target !== id || link.href !== `#${id}` || link.label !== label) {
        failures.push(
          `width ${width}: nav link ${i + 1} is "${link.label}" to ${link.href} (target ${link.target}), expected "${label}" to #${id}`,
        );
      }
      if (link.w < 24 || link.h < 24) {
        failures.push(
          `width ${width}: nav link "${link.label}" measures ${link.w.toFixed(1)}x${link.h.toFixed(1)} px, under the 24 px target floor`,
        );
      }
    });
    /* Live-fix round (R-1): phone reachability, measured in the
     * page at widths the phone rules govern. */
    if (width <= 760) {
      const phone = report.nav.phone;
      if (!phone) {
        failures.push(`width ${width}: phone nav reachability not measured`);
      } else {
        if (phone.docScrollWidth !== phone.viewportWidth) {
          failures.push(
            `width ${width}: document scroll width is ${phone.docScrollWidth}, the viewport is ${phone.viewportWidth} (the nav must not widen the document)`,
          );
        }
        for (const r of phone.reach) {
          if (!r.inStrip) {
            failures.push(
              `width ${width}: nav link "${r.target}" cannot be scrolled fully into the nav strip`,
            );
          }
          if (!r.untruncated) {
            failures.push(
              `width ${width}: nav link "${r.target}" text is truncated inside the strip`,
            );
          }
        }
      }
    }
  }
  const ctl = report.controls ?? {};
  const ctlBoxes = [
    ["compare swap button", ctl.swap],
    ...((ctl.pickers ?? []).map((b, i) => [`compare picker ${i + 1}`, b])),
    ...((ctl.cardButtons ?? []).map((b, i) => [`card control button ${i + 1}`, b])),
  ];
  for (const [what, box] of ctlBoxes) {
    if (!box) {
      failures.push(`width ${width}: ${what} not rendered`);
    } else if (box.w < 24 || box.h < 24) {
      failures.push(
        `width ${width}: ${what} measures ${box.w.toFixed(1)}x${box.h.toFixed(1)} px, under the 24 px target floor`,
      );
    }
  }
  // Anchor and expansion behaviour, once, at desktop width.
  if (width === 1440) {
    const groupsA = {
      full: ranked.filter((r) => r.n_cases === fullCasesA),
      flagged: payload.unranked,
      slices: ranked.filter((r) => r.n_cases < fullCasesA),
    };
    const samples = [groupsA.full[0], groupsA.flagged[0], groupsA.slices[0]];
    for (const row of samples) {
      await page.click(`details[data-card-for="${row.run_id}"] > summary`);
      const opened = await page.evaluate(
        (id) => document.querySelector(`details[data-card-for="${id}"]`)?.open === true,
        row.run_id,
      );
      if (!opened) {
        failures.push(`card ${row.run_id} did not open on a summary click`);
      }
    }
    const anchorRow = groupsA.full[0];
    const anchorSlug = slugOfA(anchorRow);
    /* Round 11 landing rule. With the sticky bar in place, an
     * anchor landing is correct when the target's top sits at
     * or below the bar's bottom edge and no more than 40 px
     * past it (the 64 px scroll margin against the bar's
     * height). The round 10 rule, within 40 px of the viewport
     * top, would put the heading under the bar. */
    const checkLanding = (what, top, navBottom) => {
      if (
        top === undefined ||
        navBottom === undefined ||
        top < navBottom - 1 ||
        top > navBottom + 40
      ) {
        failures.push(
          `${what} lands with its top at ${top} px against a bar bottom of ${navBottom} px, outside the bar rule`,
        );
      }
    };
    await page.evaluate((slug) => {
      location.hash = `model-${slug}`;
    }, anchorSlug);
    await new Promise((r) => setTimeout(r, 250));
    const cardLand = await page.evaluate(
      (slug) => ({
        top: document.getElementById(`model-${slug}`)?.getBoundingClientRect().top,
        navBottom: document
          .querySelector(".section-nav")
          ?.getBoundingClientRect().bottom,
      }),
      anchorSlug,
    );
    checkLanding(
      `card anchor for ${anchorRow.run_id}`,
      cardLand.top,
      cardLand.navBottom,
    );
    await page.click(
      `details[data-card-for="${anchorRow.run_id}"] a[href="#models"]`,
    );
    await new Promise((r) => setTimeout(r, 250));
    const indexLand = await page.evaluate(() => ({
      top: document.getElementById("models")?.getBoundingClientRect().top,
      navBottom: document
        .querySelector(".section-nav")
        ?.getBoundingClientRect().bottom,
    }));
    const hash = await page.evaluate(() => location.hash);
    if (hash !== "#models") {
      failures.push(`back link inside a card sets the hash to ${hash}, not #models`);
    }
    checkLanding("back link", indexLand.top, indexLand.navBottom);
    /* ---------- round 11 probes: nav and compare ---------- */
    const NAV_IDS_A = NAV_EXPECTED_A.map(([id]) => id);
    /* Keyboard walk. Tab from the top of the page until every
     * nav link has held focus; each focused link must sit
     * inside the viewport, uncovered at its centre, with the
     * focus outline showing (WCAG 2.4.11, focus not obscured,
     * probed the way a keyboard reader meets it). The walk
     * starts by focusing the skip link, the page's first tab
     * stop: sequential navigation in Chrome starts from the
     * last clicked point in the document, and the probes
     * above clicked inside the model index, so a plain blur
     * would start the walk there instead of at the top (the
     * first instrumented run's trail proved exactly that,
     * opening on the card controls). */
    await page.evaluate(() => {
      window.scrollTo(0, 0);
      document.querySelector(".skip")?.focus();
    });
    await new Promise((r) => setTimeout(r, 250));
    const seenNav = new Map();
    const walkTrail = [];
    let focusShot = false;
    for (let i = 0; i < 48 && seenNav.size < NAV_IDS_A.length; i++) {
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
        if (!focusShot && shotsDir) {
          await page.screenshot({
            path: join(shotsDir, "nav-focus-1440.png"),
          });
          focusShot = true;
        }
      }
    }
    if (seenNav.size !== NAV_IDS_A.length) {
      failures.push(
        `tab walk reached ${seenNav.size} of ${NAV_IDS_A.length} nav links (${[...seenNav.keys()].join(",")}); the walk saw: ${walkTrail.join(" | ")}`,
      );
    }
    for (const [id, info] of seenNav) {
      if (info.top < -1 || info.bottom > 901) {
        failures.push(
          `focused nav link ${id} sits at ${info.top.toFixed(1)} to ${info.bottom.toFixed(1)} px, outside the viewport`,
        );
      }
      if (info.covered) {
        failures.push(`focused nav link ${id} is covered at its centre`);
      }
      if (info.outlineStyle === "none" || info.outlineWidth === "0px") {
        failures.push(
          `focused nav link ${id} shows no focus outline (${info.outlineStyle} ${info.outlineWidth})`,
        );
      }
    }
    /* Anchor landings. Each nav link, focused and activated
     * from the keyboard (the mouse path is the flaky one on
     * this box), takes its section to the bar rule, and the
     * address follows. */
    for (const id of NAV_IDS_A) {
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
        failures.push(`nav activation ${id} leaves the address at ${land.hash}`);
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
      failures.push(
        `scrollspy marks ${spy.count} link(s), target ${spy.target}, with calibration in view`,
      );
    }
    if (spy.aria !== "true") {
      failures.push(`scrollspy's active link carries aria-current ${spy.aria}`);
    }
    if (spy.navH !== spyBefore.navH || spy.docH !== spyBefore.docH) {
      failures.push(
        `scrollspy shifted layout: bar ${spyBefore.navH} to ${spy.navH} px, document ${spyBefore.docH} to ${spy.docH} px`,
      );
    }
    if (shotsDir) {
      await page.screenshot({ path: join(shotsDir, "nav-scrolled-1440.png") });
    }
    /* Compare driving. The default pair's deltas come from
     * the payload; a slice on side B raises the population
     * banner naming both populations and moves the pair into
     * the address; one model on both sides raises the same-model
     * banner, clears the dots, and prints the deltas
     * under the not measured mark. */
    const cmpFull = ranked.find((r) => r.n_cases === fullCasesA);
    const cmpJev = allRowsA.find((r) => shortName(r) === "jev-1.14.0");
    const cmpSlice = ranked.find((r) => r.n_cases < fullCasesA);
    const readCmp = () =>
      page.evaluate(() => ({
        bannerPop:
          document
            .querySelector('[data-cmp-banner="population"]')
            ?.textContent.replace(/\s+/g, " ")
            .trim() ?? null,
        bannerSame: !!document.querySelector('[data-cmp-banner="same"]'),
        asrDelta:
          document
            .querySelector('[data-cmp-delta="asr"]')
            ?.getAttribute("data-cmp-raw") ?? null,
        asrDeltaText:
          document
            .querySelector('[data-cmp-delta="asr"]')
            ?.textContent.trim() ?? null,
        wins: document.querySelectorAll("[data-cmp-win]").length,
        hash: location.hash,
      }));
    const deltaClose = (got, want, what) => {
      if (got === null || got === "" || Math.abs(Number(got) - want) > 1e-12) {
        failures.push(`compare drive: ${what} delta raw is ${got}, payload difference is ${want}`);
      }
    };
    let cmpNow = await readCmp();
    deltaClose(
      cmpNow.asrDelta,
      cmpFull.asr_conditional - cmpJev.asr_conditional,
      "default pair",
    );
    await page.select("#cmp-picker-b", slugOfA(cmpSlice));
    await new Promise((r) => setTimeout(r, 450));
    cmpNow = await readCmp();
    if (
      !cmpNow.bannerPop ||
      !cmpNow.bannerPop.includes("full suite") ||
      !cmpNow.bannerPop.includes("abstain subset")
    ) {
      failures.push(
        `compare drive: slice against full suite raises banner "${cmpNow.bannerPop}", which must name both populations`,
      );
    }
    deltaClose(
      cmpNow.asrDelta,
      cmpFull.asr_conditional - cmpSlice.asr_conditional,
      "cross-base pair",
    );
    if (cmpNow.hash !== `#compare=${slugOfA(cmpFull)},${slugOfA(cmpSlice)}`) {
      failures.push(
        `compare drive: address is ${cmpNow.hash}, the pair should ride in it`,
      );
    }
    if (shotsDir) {
      const cmpEl = await page.$('[data-section="compare"]');
      if (cmpEl) {
        await cmpEl.screenshot({
          path: join(shotsDir, "compare-crossbase-1440.png"),
        });
      }
    }
    await page.select("#cmp-picker-a", slugOfA(cmpSlice));
    await new Promise((r) => setTimeout(r, 450));
    cmpNow = await readCmp();
    if (!cmpNow.bannerSame) {
      failures.push("compare drive: one model on both sides raises no banner");
    }
    if (cmpNow.wins !== 0) {
      failures.push(
        `compare drive: same-model pair still renders ${cmpNow.wins} winner dots`,
      );
    }
    if (cmpNow.asrDelta !== "0" || cmpNow.asrDeltaText !== "·") {
      failures.push(
        `compare drive: same-model delta prints raw "${cmpNow.asrDelta}" text "${cmpNow.asrDeltaText}", expected the zero difference under the not measured mark`,
      );
    }
    await page.select("#cmp-picker-a", slugOfA(cmpFull));
    await page.select("#cmp-picker-b", slugOfA(cmpJev));
    await new Promise((r) => setTimeout(r, 350));
    /* Restore the pristine page: the widths measured after
     * this one must see the index as a reader first does, with
     * every card closed. */
    await page.evaluate(() => {
      document
        .querySelectorAll("details[open]")
        .forEach((d) => d.removeAttribute("open"));
      window.scrollTo(0, 0);
    });
  }
  notes.push(
    `width ${width}: ${report.names.length} names checked, ${boxes.length} text boxes, tied count (innerText) ${report.tiedCount}`,
  );
}

/* ---------- mobile-fix phone interaction block ----------
 * A touch session at 390x844 against the index page. The
 * width loop measures the phone statically and the desktop
 * block drives the mouse and keyboard; neither exercises
 * what a phone reader does, which is how the hover-driven
 * card and the nav-over-chart state shipped. These probes
 * tap (page.tap dispatches touch), and they pin three
 * behaviours: the nav landing at phone width, the bar never
 * sitting on the chart's top band once the reader has
 * scrolled to it, and the scatter card's full tap contract
 * (open on the tapped point, switch, close control,
 * tap-again toggle, empty-area dismiss). */
await page.setViewport({
  width: 390,
  height: 844,
  hasTouch: true,
  isMobile: true,
  deviceScaleFactor: 1,
});
await page.goto(pageUrl, { waitUntil: "networkidle0" });
await new Promise((r) => setTimeout(r, 400));
/* Nav landing by tap. The bar may legitimately be hidden
 * after its own tap (it steps aside), so the rule is read
 * against the bar's layout height: the heading must clear
 * the full band the bar can occupy, and land within the
 * scroll margin's reach of it. */
await page.tap('.section-nav-link[data-nav-target="cost"]');
await new Promise((r) => setTimeout(r, 700));
{
  const land = await page.evaluate(() => {
    const nav = document.querySelector(".section-nav");
    const head = document.querySelector("#cost .section-title");
    return {
      hash: location.hash,
      navH: nav ? nav.offsetHeight : null,
      headTop: head ? head.getBoundingClientRect().top : null,
    };
  });
  if (
    land.hash !== "#cost" ||
    land.navH === null ||
    land.headTop === null ||
    land.headTop < land.navH - 1 ||
    land.headTop > 124
  ) {
    failures.push(
      `phone tap: Cost landing puts the heading at ${land.headTop} px against a bar of ${land.navH} px (hash ${land.hash})`,
    );
  }
}
/* Occlusion probe. Scroll the chart well to the very top
 * of the screen in one jump, the state a reader creates to
 * read the chart's top band, and let the bar's scroll logic
 * settle. The bar's rect may not then cover the corner
 * reading or the axis caption. */
await page.evaluate(() => {
  const wrap = [...document.querySelectorAll(".scatter-wrap")].find(
    (w) => w.getClientRects().length > 0,
  );
  if (wrap) {
    const top =
      wrap.getBoundingClientRect().top + window.scrollY;
    window.scrollTo(0, top);
  }
});
await new Promise((r) => setTimeout(r, 650));
{
  const occ = await page.evaluate(() => {
    const nav = document.querySelector(".section-nav");
    const sec = document.querySelector('[data-section="scatter"]');
    const svg = [...sec.querySelectorAll("svg")].find(
      (s) => s.getClientRects().length > 0,
    );
    const corner = svg.querySelector(".corner-note text");
    const caption = svg.querySelector(".axis-caption");
    const nr = nav ? nav.getBoundingClientRect() : null;
    const cover = (el) => {
      if (!el || !nr) return null;
      const r = el.getBoundingClientRect();
      const ox =
        Math.min(r.right, nr.right) - Math.max(r.left, nr.left);
      const oy =
        Math.min(r.bottom, nr.bottom) - Math.max(r.top, nr.top);
      return ox > 0 && oy > 0 ? ox * oy : 0;
    };
    return { corner: cover(corner), caption: cover(caption) };
  });
  if (occ.corner === null || occ.corner > 0) {
    failures.push(
      `phone scroll: the bar covers the scatter corner reading (${occ.corner} px2)`,
    );
  }
  if (occ.caption === null || occ.caption > 0) {
    failures.push(
      `phone scroll: the bar covers the scatter axis caption (${occ.caption} px2)`,
    );
  }
}
/* The tap contract. */
{
  const readPts = () =>
    page.evaluate(() => {
      const sec = document.querySelector('[data-section="scatter"]');
      const svg = [...sec.querySelectorAll("svg")].find(
        (s) => s.getClientRects().length > 0,
      );
      return [...svg.querySelectorAll(".scatter-point")].map((g) => {
        const c = g.querySelector("circle");
        const r = c.getBoundingClientRect();
        const label = svg.querySelector(
          `[data-label-for="${g.getAttribute("data-run-id")}"]`,
        );
        return {
          id: g.getAttribute("data-run-id"),
          cost: Number(g.getAttribute("data-cost") || "0"),
          name: label ? label.textContent.trim() : null,
          cx: r.left + r.width / 2,
          cy: r.top + r.height / 2,
        };
      });
    });
  const readCard = () =>
    page.evaluate(() => {
      const card = document.querySelector(".scatter-card");
      if (!card || card.getClientRects().length === 0) return null;
      const close = card.querySelector(".sc-close");
      const cr = close ? close.getBoundingClientRect() : null;
      return {
        name: card.querySelector(".sc-name")?.textContent.trim() ?? null,
        close: cr
          ? { cx: cr.left + cr.width / 2, cy: cr.top + cr.height / 2 }
          : null,
      };
    });
  const pts = await readPts();
  const cheap = [...pts]
    .filter((p) => p.cost > 0 && p.cost < 1)
    .sort((a, b) => a.cost - b.cost)[0];
  const pricey = [...pts].sort((a, b) => b.cost - a.cost)[0];
  if (!cheap || !pricey) {
    failures.push("phone tap: scatter points not found for the tap contract");
  } else {
    const tapPoint = async (p) => {
      await page.touchscreen.tap(p.cx, p.cy);
      await new Promise((r) => setTimeout(r, 400));
    };
    await tapPoint(cheap);
    let card = await readCard();
    if (!card || card.name !== cheap.name) {
      failures.push(
        `phone tap: tapping ${cheap.id} opens ${card ? `the card for "${card.name}"` : "no card"}, expected "${cheap.name}"`,
      );
    }
    if (card && !card.close) {
      failures.push("phone tap: the opened card carries no close control");
    }
    await tapPoint(pricey);
    card = await readCard();
    if (!card || card.name !== pricey.name) {
      failures.push(
        `phone tap: tapping ${pricey.id} does not switch the card (now "${card?.name ?? "none"}")`,
      );
    }
    if (card?.close) {
      await page.touchscreen.tap(card.close.cx, card.close.cy);
      await new Promise((r) => setTimeout(r, 400));
      card = await readCard();
      if (card !== null) {
        failures.push("phone tap: the close control does not dismiss the card");
      }
    }
    await tapPoint(cheap);
    card = await readCard();
    if (!card) {
      failures.push("phone tap: the card does not reopen after closing");
    } else {
      await tapPoint(cheap);
      card = await readCard();
      if (card !== null) {
        failures.push(
          "phone tap: tapping the open point again does not toggle it shut",
        );
      }
      /* Empty-area dismiss: reopen, then tap a spot inside
       * the plot that clears every point by more than the
       * touch radius and lands on no list entry and not on
       * the open card itself, both of which legitimately
       * take a tap of their own. */
      await tapPoint(cheap);
      const spot = await page.evaluate((ids) => {
        const sec = document.querySelector('[data-section="scatter"]');
        const svg = [...sec.querySelectorAll("svg")].find(
          (s) => s.getClientRects().length > 0,
        );
        const sr = svg.getBoundingClientRect();
        const centres = ids.map(({ cx, cy }) => ({ cx, cy }));
        const blocked = [...sec.querySelectorAll(".scatter-entry, .scatter-card")]
          .map((e) => e.getBoundingClientRect())
          .filter((r) => r.width > 0);
        const inRect = (x, y, r, m) =>
          x > r.left - m && x < r.right + m && y > r.top - m && y < r.bottom + m;
        for (let y = sr.top + 20; y < Math.min(sr.bottom - 16, 832); y += 10) {
          for (let x = sr.left + 16; x < sr.right - 16; x += 10) {
            if (
              centres.every((p) => Math.hypot(p.cx - x, p.cy - y) > 48) &&
              !blocked.some((r) => inRect(x, y, r, 6))
            ) {
              return { x, y };
            }
          }
        }
        return null;
      }, pts);
      if (!spot) {
        failures.push("phone tap: no empty chart area found for the dismiss probe");
      } else {
        await page.touchscreen.tap(spot.x, spot.y);
        await new Promise((r) => setTimeout(r, 400));
        card = await readCard();
        if (card !== null) {
          failures.push("phone tap: tapping empty chart does not dismiss the card");
        }
      }
    }
  }
}
notes.push("phone interaction block: nav landing, occlusion probe, tap contract run at 390x844");

/* ---------- round 10 model page samples ---------- */
const pageSamples = [
  ranked.find((r) => r.n_cases === fullCasesA),
  payload.unranked[0],
  ranked.find((r) => r.n_cases < fullCasesA),
  allRowsA.find((r) => r.run_id.includes("structured")),
]
  .filter(Boolean)
  .filter((r, i, a) => a.indexOf(r) === i);
for (const row of pageSamples) {
  const slug = slugOfA(row);
  await page.goto(
    `http://127.0.0.1:${server.address().port}/models/${slug}/index.html`,
    { waitUntil: "networkidle0" },
  );
  const res = await page.evaluate(() => {
    const art = document.querySelector("article[data-card-for]");
    const h1 = document.querySelector("h1");
    return {
      found: !!art,
      id: art ? art.getAttribute("data-card-for") : null,
      h1: h1 ? h1.textContent.replace(/\s+/g, " ").trim() : "",
      h1Clip: h1 ? h1.scrollWidth > h1.clientWidth + 1 : null,
      height: document.documentElement.scrollHeight,
    };
  });
  if (!res.found || res.id !== row.run_id) {
    failures.push(
      `model page /models/${slug}/ does not render its card article`,
    );
  }
  if (!res.h1.includes(shortName(row))) {
    failures.push(
      `model page /models/${slug}/ H1 "${res.h1}" does not name the model`,
    );
  }
  if (res.h1Clip) {
    failures.push(`model page /models/${slug}/ H1 is clipped`);
  }
  notes.push(`model page /models/${slug}/ height ${res.height}`);
}

/* ---------- design cycle 3: scatter card motion ---------- */
/* S-01 (the disc grow runs on the motion tokens), S-02 (the
 * card's motion layer transitions opacity and transform on
 * token durations), S-03 (under reduced motion the disc does
 * not scale and the card's layer transitions opacity only).
 * The page reloads pristine: the phone block left a pinned
 * card and a scrolled strip behind. Focus, not hover, opens
 * the measured card, so the block is keyboard-true as well. */
await page.setViewport({ width: 1440, height: 1200 });
await page.goto(pageUrl, { waitUntil: "networkidle0" });
await new Promise((r) => setTimeout(r, 350));
const motionBase = await page.evaluate(() => {
  const wide = document.querySelector(".scatter-wide");
  const mark = wide ? wide.querySelector(".pt-mark") : null;
  const pt = wide
    ? wide.querySelector('.scatter-point[data-scatter="plot"]')
    : null;
  if (pt) pt.focus();
  const ms = mark ? getComputedStyle(mark) : null;
  return {
    markTransition: ms
      ? {
          property: ms.transitionProperty,
          duration: ms.transitionDuration,
          timing: ms.transitionTimingFunction,
        }
      : null,
  };
});
await new Promise((r) => setTimeout(r, 300));
const motionCard = await page.evaluate(() => {
  const inner = document.querySelector(".scatter-wide .scatter-card-inner");
  if (!inner) return null;
  const cs = getComputedStyle(inner);
  return {
    property: cs.transitionProperty,
    duration: cs.transitionDuration,
    timing: cs.transitionTimingFunction,
  };
});
if (
  !motionBase.markTransition ||
  motionBase.markTransition.duration !== "0.12s" ||
  motionBase.markTransition.timing !== "cubic-bezier(0.23, 1, 0.32, 1)"
) {
  failures.push(
    `S-01: scatter disc grow transition is ${motionBase.markTransition ? `${motionBase.markTransition.duration} ${motionBase.markTransition.timing}` : "missing"}, expected the token values 0.12s cubic-bezier(0.23, 1, 0.32, 1)`,
  );
}
/* S-02 is an exact contract, not a set membership (cycle
 * 3 red team, RT-3): the layer must transition opacity on
 * the micro token with the fade curve and transform on
 * the state token with the move curve, in that pairing.
 * The looser predicate passed a layer with the durations
 * swapped and both curves replaced by M3-banned ones. */
if (
  !motionCard ||
  motionCard.property !== "opacity, transform" ||
  motionCard.duration !== "0.12s, 0.2s" ||
  motionCard.timing !== "ease, cubic-bezier(0.77, 0, 0.175, 1)"
) {
  failures.push(
    `S-02: scatter card motion layer is ${motionCard ? `${motionCard.property} / ${motionCard.duration} / ${motionCard.timing}` : "absent"}, expected "opacity, transform / 0.12s, 0.2s / ease, cubic-bezier(0.77, 0, 0.175, 1)" (opacity on the micro token and fade curve, transform on the state token and move curve)`,
  );
}
await page.emulateMediaFeatures([
  { name: "prefers-reduced-motion", value: "reduce" },
]);
await page.goto(pageUrl, { waitUntil: "networkidle0" });
await new Promise((r) => setTimeout(r, 350));
const reduced = await page.evaluate(() => {
  const wide = document.querySelector(".scatter-wide");
  const pt = wide
    ? wide.querySelector('.scatter-point[data-scatter="plot"]')
    : null;
  if (pt) pt.focus();
  return pt ? pt.getAttribute("data-run-id") : null;
});
await new Promise((r) => setTimeout(r, 300));
const reducedStyles = await page.evaluate(() => {
  const active = document.querySelector(
    '.scatter-wide .scatter-point[data-active="true"] .pt-mark',
  );
  const inner = document.querySelector(".scatter-wide .scatter-card-inner");
  const as = active ? getComputedStyle(active) : null;
  const is = inner ? getComputedStyle(inner) : null;
  return {
    transform: as ? as.transform : null,
    innerProperty: is ? is.transitionProperty : null,
    innerDuration: is ? is.transitionDuration : null,
  };
});
await page.emulateMediaFeatures([]);
{
  const t = reducedStyles.transform;
  const m = t ? t.match(/matrix\(([^)]+)\)/) : null;
  /* The whole matrix is the contract (cycle 3 red team,
   * RT-7): no scale on the diagonal, and no shear,
   * rotation or drift in the other four components
   * either. Reading only the diagonal passed a sheared
   * disc. */
  const scaled = m
    ? (() => {
        const p = m[1].split(",").map((v) => parseFloat(v));
        return (
          Math.abs(p[0] - 1) > 0.01 ||
          Math.abs(p[3] - 1) > 0.01 ||
          Math.abs(p[1]) > 0.01 ||
          Math.abs(p[2]) > 0.01 ||
          Math.abs(p[4]) > 0.5 ||
          Math.abs(p[5]) > 0.5
        );
      })()
    : false;
  if (!reduced || t === null || scaled) {
    failures.push(
      `S-03: under reduced motion the active scatter disc transform is ${t}, expected no scale (M19 disables the grow)`,
    );
  }
  if (
    reducedStyles.innerProperty !== "opacity" ||
    reducedStyles.innerDuration !== "0.12s"
  ) {
    failures.push(
      `S-03: under reduced motion the scatter card motion layer transitions ${reducedStyles.innerProperty} / ${reducedStyles.innerDuration}, expected opacity only at 0.12s (M19 cross-fade)`,
    );
  }
}
notes.push("cycle 3 card motion block: S-01 disc tokens, S-02 card layer, S-03 reduced-motion branch");

/* ---------- round 12 text spacing (AX-04) ---------- */
/* The WCAG 1.4.12 overrides, the adversarial lane's style tag
 * verbatim, on the 1440 board. No calibration rail name may
 * clip under them: the rail wraps its names at hyphens now.
 * Before the fix exactly one name clipped here, the 35 char
 * deberta-v3-base-prompt-injection-v2 at 241 against 210. */
await page.setViewport({ width: 1440, height: 1200 });
await page.goto(pageUrl, { waitUntil: "networkidle0" });
await page.addStyleTag({
  content: `* { line-height: 1.5 !important; letter-spacing: 0.12em !important; word-spacing: 0.16em !important; } p { margin-bottom: 2em !important; }`,
});
await new Promise((r) => setTimeout(r, 300));
const spacingClip = await page.evaluate(() =>
  [...document.querySelectorAll(".cal-rail-name")]
    .filter((n) => n.scrollWidth > n.clientWidth + 1)
    .map((n) => n.textContent.trim()),
);
if (spacingClip.length > 0) {
  failures.push(
    `text spacing: calibration rail names clip under the 1.4.12 overrides: ${spacingClip.join(", ")}`,
  );
}
notes.push(
  `text spacing (1440, 1.4.12 overrides): ${spacingClip.length} calibration rail names clipped`,
);

await browser.close();
server.close();
for (const n of notes) console.log(`  ${n}`);
if (failures.length > 0) {
  console.error(`DOM audit FAILED with ${failures.length} problem(s):`);
  for (const f of failures.slice(0, 40)) console.error(`  - ${f}`);
  process.exit(1);
}
console.log("DOM audit passed");
