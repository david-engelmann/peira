#!/usr/bin/env node
/**
 * The prose census (BUILD-SPEC part 8 and part 10). The
 * redesign's prose budget is a set of numbers, and this script
 * measures the board against the budgets named below, each
 * measured where the prose actually stands.
 *
 * A token counts as a word when it contains a letter. Pure
 * numerals and punctuation ("8.9%", "4,700", "$0.29") are the
 * figures the budget exempts. Spelled out numbers and names
 * count as words.
 *
 * What is measured, and where.
 *   The static legs read out/index.html as built. They cover
 *     the whole main element outside Method, the findings
 *     blocks, every block caption, every static paragraph
 *     outside Method and the findings, and Method itself.
 *   The explorer's result rows are the page's data surface.
 *     Their text is names and figures rather than prose, and
 *     the main total excludes them, on the accounting stated
 *     in the dated amendment to BUILD-SPEC part 8 (fix round,
 *     2026-11-05). Integrity and the duplication audit police
 *     the rows themselves.
 *   Prose that renders only under a non-default state never
 *     reaches the static document, so the client states leg
 *     measures it at its source. The strings are the composers
 *     in lib/explorerData.ts, imported live and rendered by
 *     the explorer itself, never a copied string in this file.
 *     The leg covers the guard basis line, the filter count
 *     line in its fullest form, the two group dividers, the
 *     two empty states, the chart's rail note in both forms,
 *     the off scale note, the flag note, and the flag line's
 *     label.
 *   Each detail reading is measured on the explorer data the
 *     page renders from, counting every prose field the
 *     reading renders. The fields are the flagged reason, the
 *     slice note, the robustness tax line, the counted flips
 *     line, the weakest family line, the rank line, the benign
 *     benchmark sub-line, and the re-run note. Figures and the
 *     payload disclosures (the provenance line and the
 *     no-answer and single-call sentences) stay excluded by
 *     the budget's own terms.
 *   The chart's annotation cap is measured where the chart
 *     renders, in tests/render-law.mjs, because the chart is
 *     client rendered. The client states leg below measures
 *     the same strings at their source as a second reading.
 *
 * The caps.
 *   The main element outside Method, at most 650 words.
 *   Any block caption (class cap), one sentence at most and
 *     at most 20 words.
 *   Any paragraph outside Method and the findings, at most
 *     30 words. The guard basis line stands as its own
 *     paragraph and is held to this cap.
 *   The filter count line, held to the caption cap of one
 *     sentence and at most 20 words.
 *   Each findings block, at most 45 words beyond numerals
 *     and its action. Finding 5 carries the named exception
 *     below.
 *   Method, at most 550 words in total and no paragraph
 *     over 80.
 *   Each detail reading, at most 90 words of prose.
 *   Each chart annotation, at most 25 words.
 *
 * Finding 5 exception. The block carries disclosures the
 * record requires verbatim or near verbatim (the sanctioned
 * no-answer sentence and the provider refusal account), plus
 * the accounting of the blocked case, and the findings spec
 * eyebrow and title in their full forms. Compressed to their
 * floor they still exceed 45 words. The bound below is the
 * measured count on the current payload plus two words of
 * headroom, and it is re-pinned to that rule whenever the
 * sanctioned text changes, with the re-pin recorded here and
 * in BUILD-SPEC. The current pin was measured on 2026-11-05
 * in the fix round, when the eyebrow and title were restored
 * and the leader sentence began deriving its harness wording
 * from the leader row. Any growth past the bound fails like
 * any other breach, and the deviation is named in the pull
 * request.
 */
import { readFileSync } from "node:fs";
import { register } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

register("./vendor-check-hooks.mjs", import.meta.url);

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const FINDING5_BOUND = 102;

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
 * same way. Method is found by its anchor id. Its section
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
 * on the accounting the header states. */
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

/* ---------- the explorer data the page renders from ---------- */

const {
  explorerData,
  countLineText,
  GUARD_DIVIDER,
  FLAGGED_DIVIDER,
  EMPTY_RANK_TEXT,
  EMPTY_CHART_TEXT,
  railNoteText,
  offScaleNoteText,
  flagNoteText,
  flagLineLabelText,
} = await import(path.join(root, "lib", "explorerData.ts"));
const data = explorerData();

/* ---------- client states, measured at their source ---------- */

{
  const check = (label, text, cap) => {
    const w = words(text);
    report.push(`${label} ${w} words (cap ${cap})`);
    if (w > cap) fail(`${label} runs ${w} words, cap ${cap}: ${text.slice(0, 60)}`);
    return w;
  };

  /* The guard basis line stands as its own paragraph under a
   * guards population state, so it is held to the paragraph
   * cap and its sentence count is reported beside it. */
  const basisWords = check("guard basis line", data.guardBasis, 30);
  report.push(
    `guard basis line carries ${sentences(data.guardBasis)} sentences in ${basisWords} words`,
  );

  /* The filter count line in its fullest form, with results
   * hidden and a brush filter both standing. */
  const countText = countLineText(1, data.rows.length, data.rows.length - 1, true);
  check("filter count line", countText, 20);
  if (sentences(countText) > 1) {
    fail(`the filter count line runs past one sentence: ${countText}`);
  }

  check("guard divider", GUARD_DIVIDER, 30);
  check("flagged divider", FLAGGED_DIVIDER, 30);
  check("rank empty state", EMPTY_RANK_TEXT, 30);
  check("chart empty state", EMPTY_CHART_TEXT, 30);
  check("rail note with guards", railNoteText(true), 25);
  check("rail note without guards", railNoteText(false), 25);
  check("flag line label", flagLineLabelText(data.flagLine), 25);

  /* The off scale note for every charted result past the
   * shared axis, composed exactly as the chart renders it. */
  for (const row of data.rows) {
    if (row.kind === "slice") continue;
    if (row.asr !== null && row.asr > data.axisMax) {
      check(`off scale note for ${row.name}`, offScaleNoteText(row), 25);
    }
  }

  /* The flag note for the extreme flagged result on the
   * malformed measure, when it stands past the flag line. */
  const extreme = data.rows
    .filter((r) => r.kind === "flagged" && r.malformed !== null)
    .sort((a, b) => (b.malformed ?? 0) - (a.malformed ?? 0))[0];
  if (extreme && extreme.malformed !== null && extreme.malformed > data.flagLine) {
    const note = flagNoteText(extreme);
    if (note !== null) check(`flag note for ${extreme.name}`, note, 25);
  }
}

/* ---------- readings, from the data the page renders ---------- */

let worst = { name: "", words: 0 };
for (const row of data.rows) {
  /* Every prose field the reading renders counts. Figures
   * (the rate and count strings in the figure grid) and the
   * payload disclosures (the provenance line, the no-answer
   * and single-call sentences, the family decompositions in
   * the chart of the reading) stay excluded by the budget's
   * own terms. */
  const prose = [
    row.flaggedReason ?? "",
    row.sliceNote ?? "",
    row.taxBenchLine ?? "",
    row.decompLine ?? "",
    row.weakestLine ?? "",
    row.rankLine,
    row.benignBestLine ?? "",
    row.rerunText ?? "",
  ].join(" ");
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
