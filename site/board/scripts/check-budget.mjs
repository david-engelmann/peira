/**
 * The weight budget (PF-02). Stated here, checked on every
 * build. Initial transfer for the board page means the
 * document, the scripts and styles it references, and the
 * font files, at wire weight. Fonts travel as files, never
 * base64 inside the HTML (the old page inlined them into an
 * 806 KB document).
 *
 * Budget: total at or under 500 KB. Fonts at or under 120 KB.
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { gzipSync } from "node:zlib";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const out = path.join(root, "out");
const TOTAL_BUDGET = 500 * 1024;
const FONT_BUDGET = 120 * 1024;

function walk(dir) {
  let total = 0;
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, entry.name);
    if (entry.isDirectory()) total += walk(p);
    else total += statSync(p).size;
  }
  return total;
}

/* Transfer weight is wire weight. Text assets are measured
 * gzipped, as any static host serves them; font files are
 * already compressed and count at face size. */
const wireSize = (p) => {
  const buf = readFileSync(p);
  return /\.(html|js|css|json|svg)$/.test(p) ? gzipSync(buf).length : buf.length;
};

const failures = [];
const htmlBuf = readFileSync(path.join(out, "index.html"));
const html = htmlBuf.toString("utf8");
const htmlBytes = gzipSync(htmlBuf).length;
/* Initial transfer means what a browser fetches for this page:
 * the document, the scripts and styles it references, and the
 * font files. Other routes' chunks in out/_next are not part
 * of this page's transfer and are not counted. */
const refs = new Set();
for (const m of html.matchAll(/(?:src|href)="(\/_next\/[^"]+)"/g)) {
  refs.add(m[1]);
}
let nextBytes = 0;
for (const ref of refs) {
  nextBytes += wireSize(path.join(out, ref));
}
const fontBytes = walk(path.join(out, "fonts"));
const total = htmlBytes + nextBytes + fontBytes;

if (/data:font|base64,/.test(html)) {
  failures.push("index.html inlines a font as base64 (PF-02)");
}
if (fontBytes > FONT_BUDGET) {
  failures.push(`fonts weigh ${fontBytes} bytes, budget ${FONT_BUDGET}`);
}
if (total > TOTAL_BUDGET) {
  failures.push(`initial transfer ${total} bytes, budget ${TOTAL_BUDGET}`);
}
const kb = (n) => `${(n / 1024).toFixed(1)} KB`;
if (failures.length > 0) {
  for (const f of failures) console.error(`budget check failed: ${f}`);
  process.exit(1);
}
console.log(
  `budget check passed: initial transfer ${kb(total)} of ${kb(TOTAL_BUDGET)} (html ${kb(htmlBytes)}, scripts and styles ${kb(nextBytes)}, fonts ${kb(fontBytes)} of ${kb(FONT_BUDGET)})`,
);
