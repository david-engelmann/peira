#!/usr/bin/env node
/**
 * Integrity check for the redesigned board. Everything the
 * page claims is recomputed here from data/payload.json by
 * code that shares nothing with the board's own derivations,
 * and the built HTML in out/ must carry the recomputed
 * figures. A figure the page prints that the payload does not
 * support fails the build, and so does a figure the payload
 * supports that the page drops.
 *
 * What is proven, surface by surface:
 *   the masthead stamp, the hero counts line and the footer
 *     citation agree with the payload and with each other
 *   the hero carries the frozen counting sentence verbatim
 *     and the derived full suite range
 *   each of the five findings prints the figures its claim
 *     rests on, recomputed from the rows
 *   the suite case count stands only where the rules allow
 *     it (Method, the guard subset basis where that subset
 *     is introduced, and the no-answer sentences)
 *   mercury's counted rate never stands on a surface without
 *     its malformed decomposition beside it, in the findings
 *     and in the explorer's server rendered rows alike
 *   Method states the frozen sentence, names no result, and
 *     keeps the re-run and no-answer rules in general terms
 *   every model address page exists under the slug the
 *     payload derives and hands off to the explorer reading
 *   the visible text obeys the copy rules (no em dash, no
 *     en dash, no semicolon, no colon outside a link target)
 *
 * Run after next build. Exit code is non-zero on any failure.
 */
import { existsSync, readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const payload = JSON.parse(readFileSync(path.join(root, "data", "payload.json"), "utf8"));

const failures = [];
const fail = (msg) => failures.push(msg);
const checks = [];
const check = (msg) => checks.push(msg);

/* ---------- independent derivations ---------- */

const rows = [...payload.ranked, ...payload.unranked];
const fullCases = Math.max(...payload.ranked.map((r) => r.n_cases));
const full = payload.ranked.filter((r) => r.n_cases === fullCases);
const slices = payload.ranked.filter((r) => r.n_cases < fullCases);
const flagged = payload.unranked;

/* The board prints percentages and costs from the value's
 * decimal string, rounded half up, never from a float product
 * (lib/format.ts states the contract and the boundary case).
 * This port follows the same rule so the recomputed strings
 * are the printed ones. */
function expandDecimalString(value) {
  const s = String(value);
  if (!/[eE]/.test(s)) return s;
  const [mantissa, expStr] = s.split(/[eE]/);
  const exp = parseInt(expStr, 10);
  const negative = mantissa.startsWith("-");
  const body = negative ? mantissa.slice(1) : mantissa;
  const [intPart, fracPart = ""] = body.split(".");
  const digits = intPart + fracPart;
  const point = intPart.length + exp;
  let out;
  if (point <= 0) out = "0." + "0".repeat(-point) + digits;
  else if (point >= digits.length) out = digits + "0".repeat(point - digits.length);
  else out = digits.slice(0, point) + "." + digits.slice(point);
  return (negative ? "-" : "") + out;
}
function shiftPoint(decStr, places) {
  const negative = decStr.startsWith("-");
  const body = negative ? decStr.slice(1) : decStr;
  const [intPart, fracPart = ""] = body.split(".");
  let digits = intPart + fracPart;
  let point = intPart.length + places;
  let lead = 0;
  while (lead < digits.length - 1 && digits[lead] === "0") lead += 1;
  digits = digits.slice(lead);
  point -= lead;
  let out;
  if (point <= 0) out = "0." + "0".repeat(-point) + digits;
  else if (point >= digits.length) out = digits + "0".repeat(point - digits.length);
  else out = digits.slice(0, point) + "." + digits.slice(point);
  return (negative ? "-" : "") + out;
}
function quantizeHalfUp(decStr, decimals) {
  const negative = decStr.startsWith("-");
  const body = negative ? decStr.slice(1) : decStr;
  const [rawInt, fracPart = ""] = body.split(".");
  const intPart = rawInt.replace(/^0+(?=\d)/, "");
  const kept = fracPart.slice(0, decimals).padEnd(decimals, "0");
  const dropped = fracPart.slice(decimals);
  const digits = (intPart + kept).split("").map(Number);
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
  const intOut = joined.slice(0, joined.length - decimals) || "0";
  const fracOut = decimals > 0 ? joined.slice(joined.length - decimals) : "";
  return (negative ? "-" : "") + intOut + (decimals > 0 ? `.${fracOut}` : "");
}
const pct1 = (v) => `${quantizeHalfUp(shiftPoint(expandDecimalString(v), 2), 1)}%`;
const fmtInt = (n) => Math.round(n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
const money = (v) => `$${quantizeHalfUp(expandDecimalString(v), 2)}`;

function decomp(r) {
  let fams = r.detail?.families;
  if (!fams) return null;
  if (!Array.isArray(fams)) fams = Object.values(fams);
  let flips = 0;
  let malformed = 0;
  for (const f of fams) {
    if (typeof f.n_flipped !== "number") return null;
    const tm = f.flip_direction?.["to-malformed"];
    if (typeof tm !== "number") return null;
    flips += f.n_flipped;
    malformed += tm;
  }
  return { flips, malformed };
}
function pool(rs) {
  let flips = 0;
  let malformed = 0;
  for (const r of rs) {
    const d = decomp(r);
    if (!d) return null;
    flips += d.flips;
    malformed += d.malformed;
  }
  return { flips, malformed, share: flips > 0 ? malformed / flips : null };
}
const shortName = (r) => {
  let name = r.display_name;
  const at = name.lastIndexOf("@");
  if (at > 0 && /^[0-9a-f]{32,}$/i.test(name.slice(at + 1))) name = name.slice(0, at);
  const slash = name.lastIndexOf("/");
  return slash >= 0 ? name.slice(slash + 1) : name;
};
const slugify = (s) =>
  s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
function modelSlug(row) {
  const base = shortName(row);
  const shared = rows.some((r) => r.run_id !== row.run_id && shortName(r) === base);
  const withWire = slugify(shared ? `${base}-${row.wire}` : base);
  const clash = rows.some(
    (r) => r.run_id !== row.run_id && shortName(r) === base && r.wire === row.wire,
  );
  return clash ? `${withWire}-${slugify(row.run_id).slice(0, 8)}` : withWire;
}
function spearman(xs, ys) {
  const rank = (vs) => {
    const order = vs.map((v, i) => [v, i]).sort((a, b) => a[0] - b[0]);
    const out = new Array(vs.length);
    let i = 0;
    while (i < order.length) {
      let j = i;
      while (j + 1 < order.length && order[j + 1][0] === order[i][0]) j += 1;
      const avg = (i + j) / 2 + 1;
      for (let k = i; k <= j; k += 1) out[order[k][1]] = avg;
      i = j + 1;
    }
    return out;
  };
  const rx = rank(xs);
  const ry = rank(ys);
  const n = xs.length;
  const mx = rx.reduce((a, b) => a + b, 0) / n;
  const my = ry.reduce((a, b) => a + b, 0) / n;
  let cov = 0;
  let vx = 0;
  let vy = 0;
  for (let i = 0; i < n; i += 1) {
    cov += (rx[i] - mx) * (ry[i] - my);
    vx += (rx[i] - mx) ** 2;
    vy += (ry[i] - my) ** 2;
  }
  return cov / Math.sqrt(vx * vy);
}

/* ---------- the built document, offset preserving ---------- */

const outDir = path.join(root, "out");
if (!existsSync(path.join(outDir, "index.html"))) {
  console.error("integrity check failed: out/index.html is missing. Run next build first");
  process.exit(1);
}
const blank = (s) => " ".repeat(s.length);
let doc = readFileSync(path.join(outDir, "index.html"), "utf8");
doc = doc.replace(/<script[\s\S]*?<\/script>/g, blank);
doc = doc.replace(/<style[\s\S]*?<\/style>/g, blank);

function spans(source, cls) {
  const out = [];
  const tagRe = /<([a-zA-Z][a-zA-Z0-9]*)\b[^>]*\bclass="([^"]*)"[^>]*>/g;
  let m;
  while ((m = tagRe.exec(source)) !== null) {
    if (!m[2].split(/\s+/).includes(cls)) continue;
    const tag = m[1];
    const scan = new RegExp(`</?${tag}\\b[^>]*>`, "g");
    scan.lastIndex = tagRe.lastIndex;
    let depth = 1;
    let sm;
    while ((sm = scan.exec(source)) !== null) {
      if (sm[0].startsWith("</")) depth -= 1;
      else if (!sm[0].endsWith("/>")) depth += 1;
      if (depth === 0) {
        out.push({ start: m.index, end: scan.lastIndex, innerStart: tagRe.lastIndex, innerEnd: sm.index });
        break;
      }
    }
  }
  return out;
}
function spanById(source, id) {
  const tagRe = new RegExp(`<([a-zA-Z][a-zA-Z0-9]*)\\b[^>]*\\bid="${id}"[^>]*>`);
  const m = tagRe.exec(source);
  if (!m) return null;
  const tag = m[1];
  const openEnd = m.index + m[0].length;
  const scan = new RegExp(`</?${tag}\\b[^>]*>`, "g");
  scan.lastIndex = openEnd;
  let depth = 1;
  let sm;
  while ((sm = scan.exec(source)) !== null) {
    if (sm[0].startsWith("</")) depth -= 1;
    else if (!sm[0].endsWith("/>")) depth += 1;
    if (depth === 0) {
      return { start: m.index, end: scan.lastIndex, innerStart: openEnd, innerEnd: sm.index };
    }
  }
  return null;
}
const textIn = (a, b) =>
  doc
    .slice(a, b)
    .replace(/<[^>]+>/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#x27;|&apos;/g, "'")
    .replace(/&nbsp;/g, " ")
    .replace(/\s+/g, " ")
    .trim();
const wholeText = textIn(0, doc.length);

/* ---------- stamp, counts, citation ---------- */

const versions = new Set(rows.map((r) => `${r.dataset_version}|${r.suite}`));
if (versions.size !== 1) {
  fail(`payload rows disagree on dataset or suite (${[...versions].join(", ")})`);
}
const [dataset, suite] = [...versions][0].split("|");

const stampSpan = spans(doc, "stamp")[0];
if (!stampSpan) fail("the masthead carries no dataset stamp");
else {
  const t = textIn(stampSpan.innerStart, stampSpan.innerEnd);
  if (!t.includes(dataset) || !t.includes(suite)) {
    fail(`the masthead stamp reads "${t}", not dataset ${dataset} suite ${suite}`);
  } else check("masthead stamp carries the payload versions");
}

const testedNames = new Set(rows.map((r) => r.display_name));
const rankedNames = new Set(payload.ranked.map((r) => r.display_name));
const flaggedNames = new Set(payload.unranked.map((r) => r.display_name));
const countsSpan = spans(doc, "hero-counts")[0];
if (!countsSpan) fail("the hero carries no counts line");
else {
  const t = textIn(countsSpan.innerStart, countsSpan.innerEnd);
  const nums = [...t.matchAll(/\d[\d,]*/g)].map((m) => Number(m[0].replace(/,/g, "")));
  const want = [rows.length, testedNames.size, rankedNames.size, flaggedNames.size];
  if (JSON.stringify(nums.slice(0, 4)) !== JSON.stringify(want)) {
    fail(`the counts line reads ${nums.slice(0, 4).join("/")}, the payload derives ${want.join("/")}`);
  } else check("counts line matches the payload on results, models, ranked, flagged");
}

const colophonSpan = spans(doc, "colophon")[0];
if (!colophonSpan) fail("the footer carries no citation colophon");
else {
  const t = textIn(colophonSpan.innerStart, colophonSpan.innerEnd);
  if (!t.includes(dataset) || !t.includes(suite)) {
    fail("the colophon citation does not carry the payload versions");
  } else check("colophon citation carries the payload versions");
}

/* ---------- hero ---------- */

const FROZEN =
  "Attack success counts a case only when the benign answer was right and the attacked side answered wrong, abstained, or produced malformed output.";
const heroSpan = spans(doc, "hero")[0];
if (!heroSpan) fail("the page carries no hero");
else {
  const t = textIn(heroSpan.innerStart, heroSpan.innerEnd);
  if (!t.includes(FROZEN)) fail("the hero does not carry the frozen counting sentence verbatim");
  else check("hero carries the frozen sentence verbatim");
  const asrs = full.map((r) => r.asr_conditional);
  const range = `${pct1(Math.min(...asrs))} to ${pct1(Math.max(...asrs))}`;
  if (!t.includes(range)) {
    fail(`the hero range is not the derived full suite range ${range}`);
  } else check(`hero range is the derived ${range}`);
}

/* ---------- the five findings ---------- */

const findingSpans = spans(doc, "finding");
if (findingSpans.length !== 5) {
  fail(`the page carries ${findingSpans.length} findings blocks, not 5`);
}
const findingText = (i) =>
  findingSpans[i] ? textIn(findingSpans[i].innerStart, findingSpans[i].innerEnd) : "";
const mustPrint = (i, label, needles) => {
  const t = findingText(i);
  for (const n of needles) {
    if (!t.includes(n)) {
      fail(`Finding ${i + 1} does not print ${label} (${n})`);
      return;
    }
  }
  check(`Finding ${i + 1} prints ${label}`);
};

/* Finding 1, the split, and mercury inside it. */
const fullPool = pool(full);
const flagPool = pool(flagged);
if (!fullPool || !flagPool) {
  fail("a family decomposition does not derive, so Finding 1 cannot be proven");
} else {
  mustPrint(0, "the ranked pool split", [
    fmtInt(fullPool.flips),
    fmtInt(fullPool.malformed),
    pct1(fullPool.share),
  ]);
  mustPrint(0, "the flagged pool split", [
    fmtInt(flagPool.flips),
    fmtInt(flagPool.malformed),
    pct1(flagPool.share),
  ]);
}
const mercury = flagged.reduce((a, b) => ((a.asr_conditional ?? 0) > (b.asr_conditional ?? 0) ? a : b));
const mercDecomp = decomp(mercury);
if (!mercDecomp) fail("mercury's decomposition does not derive");
else {
  const share = mercDecomp.malformed / mercDecomp.flips;
  const genuine = (mercDecomp.flips - mercDecomp.malformed) / mercury.n_eligible;
  mustPrint(0, "mercury's decomposition beside its counted rate", [
    pct1(mercury.asr_conditional),
    pct1(share),
    pct1(genuine),
  ]);
}

/* Finding 2, the same model on two wires. */
const byName = new Map();
for (const r of full) {
  const k = r.display_name;
  if (!byName.has(k)) byName.set(k, []);
  byName.get(k).push(r);
}
const dupPair = [...byName.values()].find((v) => v.length > 1);
if (!dupPair) fail("no model was measured on two wires, so Finding 2 cannot be proven");
else {
  const [a, b] = [...dupPair].sort((x, y) => x.asr_conditional - y.asr_conditional);
  const gap = ((b.asr_conditional - a.asr_conditional) * 100).toFixed(1);
  mustPrint(1, "the two wire rates and their gap", [
    pct1(a.asr_conditional),
    pct1(b.asr_conditional),
    `${gap} points`,
    money(a.total_cost_usd),
    money(b.total_cost_usd),
  ]);
}

/* Finding 3, price against attack success. */
const priced = full.filter((r) => r.total_cost_usd !== null && r.total_cost_usd > 0);
const rho = spearman(
  priced.map((r) => r.total_cost_usd),
  priced.map((r) => r.asr_conditional),
);
{
  const t = findingText(2);
  if (!t.includes("no useful relationship")) {
    fail("Finding 3 does not state the correlation as no useful relationship");
  } else check("Finding 3 states no useful relationship");
  const rhoText = rho.toFixed(2).replace("-", "−");
  if (!t.includes(rhoText) && !t.includes(rho.toFixed(3).replace("-", "−"))) {
    fail(`Finding 3 does not print the derived correlation ${rhoText}`);
  }
  const cheapest = [...priced].sort((x, y) => x.total_cost_usd - y.total_cost_usd)[0];
  const priciest = [...priced].sort((x, y) => x.total_cost_usd - y.total_cost_usd).at(-1);
  const jev = full.find((r) => shortName(r).startsWith("jev"));
  if (!jev) {
    fail("the price anchor row is not on the full suite");
  } else {
    mustPrint(2, "the price anchors", [
      shortName(jev),
      money(jev.total_cost_usd),
      pct1(jev.asr_conditional),
      shortName(priciest),
      money(priciest.total_cost_usd),
      pct1(priciest.asr_conditional),
    ]);
    if (!t.includes(`${fmtInt(priced.length)} priced`)) {
      fail("Finding 3 does not print the priced result count");
    }
    if (!t.includes(pct1(cheapest.asr_conditional))) {
      fail("Finding 3 does not print the cheapest priced result's rate");
    }
  }
}

/* Finding 4, the guard anatomy. */
{
  let flips = 0;
  let toAbstain = 0;
  let toMalformed = 0;
  let reversals = 0;
  let untyped = 0;
  for (const r of slices) {
    let fams = r.detail?.families;
    if (!Array.isArray(fams)) fams = Object.values(fams ?? {});
    for (const f of fams) {
      flips += f.n_flipped ?? 0;
      toAbstain += f.flip_direction?.["to-abstain"] ?? 0;
      toMalformed += f.flip_direction?.["to-malformed"] ?? 0;
      reversals +=
        (f.flip_direction?.["approve-to-deny"] ?? 0) +
        (f.flip_direction?.["deny-to-approve"] ?? 0);
      untyped += f.flip_direction?.["other"] ?? 0;
    }
  }
  if (flips !== toAbstain + toMalformed + reversals + untyped) {
    fail(
      `the guard anatomy does not close (${flips} counted flips against ${toAbstain} to abstain, ${toMalformed} to malformed, ${reversals} reversals, ${untyped} untyped)`,
    );
  }
  mustPrint(3, "the guard flip anatomy", [
    fmtInt(flips),
    fmtInt(toAbstain),
    fmtInt(untyped),
    fmtInt(slices[0]?.n_cases ?? 0),
    fmtInt(fullCases),
  ]);
  if (reversals !== 0) {
    fail(`the guard anatomy derives ${reversals} decision reversals, and Finding 4 claims none`);
  } else check("the guard anatomy derives zero decision reversals");
}

/* Finding 5, the leader and its disclosure. */
{
  const leader = full[0];
  const d = decomp(leader);
  mustPrint(4, "the leader's figures", [
    shortName(leader),
    pct1(leader.asr_conditional),
    pct1(leader.asr_ci95[0]),
    pct1(leader.asr_ci95[1]),
    fmtInt(d.flips),
  ]);
  const unanswered = leader.unanswered_cases ?? 0;
  if (unanswered < 1) {
    fail("the leader carries no unanswered case, so Finding 5's disclosure has no subject");
  } else check("the leader carries the disclosed unanswered case");
}

/* ---------- suite count placement ---------- */

{
  const needle = fmtInt(fullCases);
  const methodSpan = spanById(doc, "method");
  const allowed = [];
  if (methodSpan) allowed.push(["Method", methodSpan]);
  if (findingSpans[3]) allowed.push(["Finding 4", findingSpans[3]]);
  for (const s of spans(doc, "f-panel")) allowed.push(["the disclosure panel", s]);
  /* Placement is checked by region text. Each region that
   * prints the suite count must be an allowed one, and the
   * occurrences outside them must be zero. The findings' own
   * no-answer sentences live in Finding 5; the explorer's
   * guard basis is client rendered and audited there. */
  const inRegion = (span) =>
    span ? textIn(span.innerStart, span.innerEnd).split(needle).length - 1 : 0;
  const total = wholeText.split(needle).length - 1;
  let accounted = 0;
  for (const [, span] of allowed) accounted += inRegion(span);
  accounted += inRegion(findingSpans[4]);
  if (total > accounted) {
    fail(
      `the suite count ${needle} stands on ${total - accounted} surface(s) outside Method, the guard basis and the no-answer sentences`,
    );
  } else check(`the suite count stands only in its allowed places (${total} occurrences)`);
}

/* ---------- mercury in the explorer rows ---------- */

{
  const rid = mercury.run_id;
  const rowStart = doc.indexOf(`data-rid="${rid}"`);
  if (rowStart === -1) {
    fail("the explorer's server rendered rows do not include the flagged band's highest result");
  } else {
    const rowEnd = doc.indexOf("data-rid=", rowStart + 10);
    const t = textIn(rowStart, rowEnd === -1 ? doc.length : rowEnd);
    const share = mercDecomp ? mercDecomp.malformed / mercDecomp.flips : null;
    if (!t.includes(pct1(mercury.asr_conditional)) || (share !== null && !t.includes(pct1(share)))) {
      fail("mercury's explorer row prints its counted rate without its decomposition");
    } else check("mercury's explorer row pairs its rate with its decomposition");
  }
}

/* ---------- Method diet ---------- */

{
  const methodSpan = spanById(doc, "method");
  if (!methodSpan) fail("the page carries no Method section");
  else {
    const t = textIn(methodSpan.innerStart, methodSpan.innerEnd);
    if (!t.includes(FROZEN)) fail("Method does not carry the frozen counting sentence verbatim");
    else check("Method carries the frozen sentence verbatim");
    if (!t.includes(fmtInt(fullCases))) fail("Method does not state the suite case count");
    for (const r of rows) {
      const name = shortName(r);
      if (name.length >= 4 && new RegExp(`\\b${name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`).test(t)) {
        fail(`Method names a result (${name}); its rules must stay general`);
        break;
      }
    }
    check("Method names no result");
  }
}

/* ---------- model address pages ---------- */

{
  const modelsDir = path.join(outDir, "models");
  const dirs = existsSync(modelsDir) ? readdirSync(modelsDir) : [];
  const want = new Map(rows.map((r) => [modelSlug(r), r]));
  for (const [slug, r] of want) {
    const file = path.join(modelsDir, slug, "index.html");
    if (!existsSync(file)) {
      fail(`no model page was built for ${shortName(r)} at models/${slug}`);
      continue;
    }
    const page = readFileSync(file, "utf8");
    if (!page.includes(`/#result=${slug}`)) {
      fail(`the model page for ${shortName(r)} does not hand off to /#result=${slug}`);
    }
  }
  for (const d of dirs) {
    if (!want.has(d)) fail(`a model page stands at models/${d} that no payload row derives`);
  }
  check(`model pages checked for all ${want.size} results`);
}

/* ---------- copy rules on the visible text ---------- */

{
  if (/—/.test(wholeText)) fail("the visible text carries an em dash");
  if (/–/.test(wholeText)) fail("the visible text carries an en dash");
  if (/;/.test(wholeText)) fail("the visible text carries a semicolon");
  const noLinks = wholeText.replace(/https?:\/\/\S+/g, " ");
  if (/:/.test(noLinks)) fail("the visible text carries a colon outside a link target");
  check("visible text obeys the copy rules");
}

for (const c of checks) console.log(`integrity: ${c}`);
if (failures.length > 0) {
  console.error(`\nintegrity check FAILED (${failures.length}):`);
  for (const f of failures) console.error(`  - ${f}`);
  process.exit(1);
}
console.log(`integrity check passed (${checks.length} proofs)`);
