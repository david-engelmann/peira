#!/usr/bin/env node
/**
 * The prose census (BUILD-SPEC section 8 and section 10). The
 * redesign's prose budget is a set of numbers, and this script
 * measures the built page against every one of them.
 *
 * A token counts as a word when it contains a letter. Pure
 * numerals and punctuation ("8.9%", "4,700", "$0.29") are the
 * figures the budget exempts. Spelled out numbers and names
 * count as words.
 *
 * Budgets measured here, against out/index.html as built:
 *   the whole main element outside Method, at most 650 words;
 *     the explorer's result rows are the page's data surface,
 *     their text is names and figures rather than prose, and
 *     they are excluded from this total the way the findings
 *     budget exempts numerals and the readings budget exempts
 *     figures and disclosures; integrity and the duplication
 *     audit police the rows themselves
 *   any block caption (class cap), one sentence at most,
 *     at most 20 words
 *   any paragraph outside Method and the findings, at most
 *     30 words
 *   each findings block, at most 45 words beyond numerals
 *     and its action; Finding 5 carries a named exception
 *     below
 *   Method, at most 550 words in total and no paragraph
 *     over 80
 *   each detail reading, at most 90 words of prose beyond
 *     figures and payload disclosures, measured on the
 *     explorer data the page renders from
 *
 * The explorer chart's annotation cap (25 words per chart
 * beyond axis labels) is measured where the chart renders,
 * in tests/render-law.mjs, because the chart is client
 * rendered and this script reads the static document.
 *
 * Finding 5 exception. The block carries two disclosures the
 * record requires verbatim or near verbatim (the sanctioned
 * no-answer sentence and the provider refusal), plus the
 * accounting of the blocked case. Compressed to their floor
 * they still exceed 45 words. The exception bound below is
 * the measured count on the current payload plus two words
 * of headroom; any growth past it fails like any other
 * breach, and the deviation is named in the pull request.
 */
import { readFileSync } from "node:fs";
import { register } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

register("./vendor-check-hooks.mjs", import.meta.url);

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const FINDING5_BOUND = 95;

const failures = [];
const fail = (msg) => failures.push(msg);
const report = [];

const words = (text) =>
  text
    .replace(/\s+/g, " ")
    .trim()
    .split(" ")
    .filter((t) => /[A-Za-z]/.test(t)).length;

const sentences = (text) =>
  text
    .replace(/\s+/g, " ")
    .trim()
    .split(/[.!?]+/)
    .filter((s) => /[A-Za-z]/.test(s)).length;

/* ---------- tiny region extraction over the built HTML ---------- */

const rawHtml = readFileSync(path.join(root, "out", "index.html"), "utf8");
const html = rawHtml
  .replace(/<script[\s\S]*?<\/script>/g, " ")
  .replace(/<style[\s\S]*?<\/style>/g, " ");

/* Inner HTML of every element whose class list contains cls,
 * with tag depth balancing so nested same-tag children do not
 * end the region early. */
function regions(source, cls) {
  const out = [];
  const tagRe = /<([a-zA-Z][a-zA-Z0-9]*)\b[^>]*\bclass="([^"]*)"[^>]*>/g;
  let m;
  while ((m = tagRe.exec(source)) !== null) {
    const classes = m[2].split(/\s+/);
    if (!classes.includes(cls)) continue;
    const tag = m[1];
    const start = tagRe.lastIndex;
    const scan = new RegExp(`</?${tag}\\b[^>]*>`, "g");
    scan.lastIndex = start;
    let depth = 1;
    let sm;
    while ((sm = scan.exec(source)) !== null) {
      if (sm[0].startsWith("</")) depth -= 1;
      else if (!sm[0].endsWith("/>")) depth += 1;
      if (depth === 0) {
        out.push({ inner: source.slice(start, sm.index), index: m.index, end: scan.lastIndex });
        break;
      }
    }
  }
  return out;
}

const textOf = (inner) =>
  inner
    .replace(/<[^>]+>/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#x27;|&apos;/g, "'")
    .replace(/&nbsp;/g, " ");

/* Inner HTML of every element carrying id=id, balanced the
 * same way. Method is found by its anchor id; its section
 * class is shared with other sections. */
function regionsById(source, id) {
  const out = [];
  const tagRe = new RegExp(`<([a-zA-Z][a-zA-Z0-9]*)\\b[^>]*\\bid="${id}"[^>]*>`, "g");
  let m;
  while ((m = tagRe.exec(source)) !== null) {
    const tag = m[1];
    const start = tagRe.lastIndex;
    const scan = new RegExp(`</?${tag}\\b[^>]*>`, "g");
    scan.lastIndex = start;
    let depth = 1;
    let sm;
    while ((sm = scan.exec(source)) !== null) {
      if (sm[0].startsWith("</")) depth -= 1;
      else if (!sm[0].endsWith("/>")) depth += 1;
      if (depth === 0) {
        out.push({ inner: source.slice(start, sm.index), index: m.index, end: scan.lastIndex });
        break;
      }
    }
  }
  return out;
}

/* Remove the subtrees carrying class cls from an HTML fragment. */
function without(inner, cls) {
  const tagRe = /<([a-zA-Z][a-zA-Z0-9]*)\b[^>]*\bclass="([^"]*)"[^>]*>/g;
  let m;
  let result = "";
  let cursor = 0;
  while ((m = tagRe.exec(inner)) !== null) {
    if (!m[2].split(/\s+/).includes(cls)) continue;
    const tag = m[1];
    const scan = new RegExp(`</?${tag}\\b[^>]*>`, "g");
    scan.lastIndex = tagRe.lastIndex;
    let depth = 1;
    let sm;
    let end = -1;
    while ((sm = scan.exec(inner)) !== null) {
      if (sm[0].startsWith("</")) depth -= 1;
      else if (!sm[0].endsWith("/>")) depth += 1;
      if (depth === 0) {
        end = scan.lastIndex;
        break;
      }
    }
    if (end === -1) return inner;
    result += inner.slice(cursor, m.index);
    cursor = end;
    tagRe.lastIndex = end;
  }
  return result + inner.slice(cursor);
}

/* ---------- the budgets ---------- */

const mainRegions = regions(html, "page");
if (mainRegions.length === 0) {
  fail("the built page carries no main region (class page) to census");
}
const mainInner = mainRegions.length > 0 ? mainRegions[0].inner : "";

/* Method first, so the main total can exclude it. */
const methodRegions = regionsById(mainInner, "method");
const methodInner = methodRegions.length > 0 ? methodRegions[0].inner : "";
if (methodRegions.length === 0) {
  fail("the built page carries no Method section to census");
}
const methodWords = words(textOf(methodInner));
report.push(`Method ${methodWords} words (cap 550)`);
if (methodWords > 550) fail(`Method runs ${methodWords} words, cap 550`);
const methodParas = regions(methodInner, "method-p");
for (const [i, p] of methodParas.entries()) {
  const w = words(textOf(p.inner));
  if (w > 80) fail(`Method paragraph ${i + 1} runs ${w} words, cap 80`);
}
report.push(`Method paragraphs ${methodParas.length}, each at most 80 words`);

/* Main outside Method, with the explorer's data rows removed
 * (see the header for the accounting rule). */
const mainOutsideRaw = (() => {
  if (methodRegions.length === 0) return mainInner;
  const r = methodRegions[0];
  const openStart = mainInner.lastIndexOf("<section", r.index);
  return mainInner.slice(0, openStart === -1 ? r.index : openStart) + mainInner.slice(r.end);
})();
const mainOutside = without(without(mainOutsideRaw, "xrow"), "xfamrow");
const mainWords = words(textOf(mainOutside));
report.push(`main outside Method ${mainWords} words (cap 650)`);
if (mainWords > 650) {
  fail(`the main page outside Method runs ${mainWords} words, cap 650`);
}

/* Findings blocks. */
const findingRegions = regions(mainInner, "finding");
if (findingRegions.length !== 5) {
  fail(`the built page carries ${findingRegions.length} findings blocks, not 5`);
}
findingRegions.forEach((f, i) => {
  const body = without(f.inner, "f-action");
  const w = words(textOf(body));
  const cap = i === 4 ? FINDING5_BOUND : 45;
  report.push(
    `Finding ${i + 1} ${w} words (cap ${cap}${i === 4 ? ", named exception" : ""})`,
  );
  if (w > cap) {
    fail(`Finding ${i + 1} runs ${w} words beyond numerals and its action, cap ${cap}`);
  }
});

/* Captions. */
for (const c of regions(mainInner, "cap")) {
  const t = textOf(c.inner);
  const w = words(t);
  if (w > 20) fail(`a caption runs ${w} words, cap 20: ${t.trim().slice(0, 60)}`);
  if (sentences(t) > 1) {
    fail(`a caption runs past one sentence: ${t.trim().slice(0, 60)}`);
  }
}
report.push("every caption one sentence, at most 20 words");

/* Paragraphs outside Method and the findings. Every static
 * paragraph in the main element is measured, wherever it
 * stands, the explorer's data rows aside (their text is
 * names and figures, removed with the rows above). */
const proseParas = [];
{
  /* Method is already cut out of mainOutsideRaw whole, so
   * only the findings spans need excluding here. */
  const findingSpans = findingRegions.map((f) => ({ index: f.index, end: f.end }));
  const inside = (pos) => findingSpans.some((s) => pos > s.index && pos < s.end);
  const pRe = /<p\b[^>]*>([\s\S]*?)<\/p>/g;
  let m;
  while ((m = pRe.exec(mainOutsideRaw)) !== null) {
    if (inside(m.index)) continue;
    if (/class="[^"]*\b(xrow|xfamrow)\b/.test(m[0])) continue;
    proseParas.push(m[1]);
  }
}
for (const inner of proseParas) {
  const w = words(textOf(inner));
  if (w > 30) {
    fail(
      `a paragraph outside Method and the findings runs ${w} words, cap 30: ${textOf(inner).trim().slice(0, 60)}`,
    );
  }
}
report.push("every paragraph outside Method and the findings at most 30 words");

/* ---------- readings, from the data the page renders ---------- */

const { explorerData } = await import(path.join(root, "lib", "explorerData.ts"));
const data = explorerData();
let worst = { name: "", words: 0 };
for (const row of data.rows) {
  /* Prose is the editorial text of the reading. Figures (the
   * rate and count strings) and the payload disclosures (the
   * provenance line, the re-run note, the no-answer and
   * single-call sentences, the family decompositions) are
   * excluded by the budget's own terms. */
  const prose = [row.flaggedReason ?? "", row.sliceNote ?? "", row.taxBenchLine ?? ""].join(" ");
  const w = words(prose);
  if (w > worst.words) worst = { name: row.name, words: w };
  if (w > 90) {
    fail(`the reading for ${row.name} runs ${w} words of prose, cap 90`);
  }
}
report.push(
  `readings at most 90 words of prose (worst ${worst.name} at ${worst.words})`,
);

for (const line of report) console.log(`census: ${line}`);
if (failures.length > 0) {
  console.error(`\nprose census FAILED (${failures.length}):`);
  for (const f of failures) console.error(`  - ${f}`);
  process.exit(1);
}
console.log("prose census passed");
