#!/usr/bin/env node
/**
 * Vendor agreement check. lib/vendor-data.json is the one
 * vendor table for the whole board; this script proves the
 * three resolvers that read it agree on every payload row:
 *
 *   page marks    lib/vendor.ts vendorOf (executed for real,
 *                 through scripts/vendor-check-hooks.mjs)
 *   page colors   lib/vendorColors.ts vendorFamilyOf (same)
 *   share image   scripts/gen-og.mjs familyOf, resolved here
 *                 through the shared table, and cross-checked
 *                 against the discs actually drawn in the
 *                 generated .og/og.html when one is present
 *
 * It also proves the table is the only one: no family color
 * may appear in any resolver's source, gen-og may carry no
 * FAMILIES or MONO_LETTERS table of its own, and every logo
 * slug the table names must exist in lib/logoPaths.ts.
 * Exit code is non-zero on any disagreement. Run after a
 * build (npm run build) so .og/og.html is current.
 */
import { existsSync, readFileSync } from "node:fs";
import { register } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

register("./vendor-check-hooks.mjs", import.meta.url);

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const read = (rel) => readFileSync(path.join(root, rel), "utf8");
const data = JSON.parse(read("lib/vendor-data.json"));
const payload = JSON.parse(read("data/payload.json"));
const rows = [...payload.ranked, ...payload.unranked];

const failures = [];
const fail = (msg) => failures.push(msg);

/* The logo slugs the board can draw. */
const LOGO_PATHS = {};
for (const m of read("lib/logoPaths.ts").matchAll(/(\w+):\s*\n?\s*"([^"]+)"/g)) {
  LOGO_PATHS[m[1]] = m[2];
}

/* One table only: resolvers hold no palette of their own. */
const palette = [
  ...data.families.map((f) => f.color),
  data.fallback.color,
];
for (const rel of ["lib/vendor.ts", "lib/vendorColors.ts", "scripts/gen-og.mjs"]) {
  const src = read(rel);
  for (const hex of palette) {
    if (src.includes(hex)) {
      fail(`${rel} hardcodes family color ${hex}; the table is not the only source`);
    }
  }
}
if (!read("lib/vendorColors.ts").includes("vendor-data.json")) {
  fail("lib/vendorColors.ts does not read lib/vendor-data.json");
}
if (!read("lib/vendor.ts").includes("vendorMatchOf")) {
  fail("lib/vendor.ts does not resolve through lib/vendorColors");
}
const ogSrc = read("scripts/gen-og.mjs");
if (!ogSrc.includes("vendor-data.json")) {
  fail("scripts/gen-og.mjs does not read lib/vendor-data.json");
}
if (/\bFAMILIES\b|\bMONO_LETTERS\b/.test(ogSrc)) {
  fail("scripts/gen-og.mjs still carries its own family table");
}
for (const fam of [...data.families, data.fallback]) {
  if (fam.logo !== null && !(fam.logo in LOGO_PATHS)) {
    fail(`family ${fam.key} names logo ${fam.logo}, absent from lib/logoPaths.ts`);
  }
}

/* The shared table's own resolution (gen-og's algorithm). */
const BY_KEY = new Map(data.families.map((f) => [f.key, f]));
const RULES = data.rules.map((r) => ({ test: new RegExp(r.pattern), key: r.family }));
const shortName = (r) => {
  let name = r.display_name;
  const at = name.lastIndexOf("@");
  if (at > 0 && /^[0-9a-f]{32,}$/i.test(name.slice(at + 1))) {
    name = name.slice(0, at);
  }
  const slash = name.lastIndexOf("/");
  return slash >= 0 ? name.slice(slash + 1) : name;
};
function ogFamily(row) {
  const hay = `${row.display_name} ${row.adapter_name} ${row.wire}`.toLowerCase();
  for (const rule of RULES) {
    if (rule.test.test(hay)) return BY_KEY.get(rule.key);
  }
  return data.fallback;
}

/* The page's real resolvers, executed. */
const { vendorOf } = await import(path.join(root, "lib", "vendor.ts"));
const { vendorFamilyOf } = await import(
  path.join(root, "lib", "vendorColors.ts")
);

console.log(
  "run_id | page slug/mono | page family color | og slug/mono | og family color",
);
for (const row of rows) {
  const mark = vendorOf(row);
  const fam = vendorFamilyOf(row);
  const og = ogFamily(row);
  const pageSlug = mark.kind === "logo" ? mark.slug : null;
  const pageMono =
    mark.kind === "mono" ? mark.letter : null;
  const ogMono =
    og.logo !== null
      ? null
      : (og.mono ??
        (shortName(row).match(/[a-z0-9]/i)?.[0]?.toUpperCase() ?? "·"));
  console.log(
    `${row.run_id} | ${pageSlug ?? `mono ${pageMono}`} | ${fam.key} ${fam.color} | ${og.logo ?? `mono ${ogMono}`} | ${og.key} ${og.color}`,
  );
  if (pageSlug !== og.logo) {
    fail(`${row.run_id}: page logo ${pageSlug} != og logo ${og.logo}`);
  }
  if (og.logo === null && pageMono !== ogMono) {
    fail(`${row.run_id}: page mono ${pageMono} != og mono ${ogMono}`);
  }
  if (fam.key !== og.key || fam.color !== og.color || fam.glyph !== og.glyph) {
    fail(
      `${row.run_id}: page family ${fam.key}/${fam.color}/${fam.glyph} != og family ${og.key}/${og.color}/${og.glyph}`,
    );
  }
}

/* The share image's drawn discs, when a generated og.html
 * is present: rail points first, then plotted points, each
 * in payload order, exactly as gen-og emits them. */
const ogHtmlPath = path.join(root, ".og", "og.html");
if (existsSync(ogHtmlPath)) {
  const html = readFileSync(ogHtmlPath, "utf8");
  const fullCases = Math.max(...rows.map((r) => r.n_cases));
  const nonSlice = rows.filter((r) => r.n_cases === fullCases);
  const expected = [
    ...nonSlice.filter((r) => !(r.total_cost_usd !== null && r.total_cost_usd > 0)),
    ...nonSlice.filter((r) => r.total_cost_usd !== null && r.total_cost_usd > 0),
  ];
  const discs = [
    ...html.matchAll(
      /<g transform="translate\([-\d.]+ [-\d.]+\)">\s*<circle r="11" fill="([^"]+)"[^/]*\/>\s*(<path d="([^"]+)"|<text[^>]*>([^<])<\/text>)/g,
    ),
  ];
  if (discs.length !== expected.length) {
    fail(`og.html holds ${discs.length} discs, expected ${expected.length}`);
  }
  expected.forEach((row, i) => {
    const m = discs[i];
    if (!m) return;
    const og = ogFamily(row);
    const [, fill, , pathD, letter] = m;
    if (fill !== og.color) {
      fail(`${row.run_id}: og disc fill ${fill} != family color ${og.color}`);
    }
    if (og.logo !== null && pathD !== LOGO_PATHS[og.logo]) {
      fail(`${row.run_id}: og disc glyph is not the ${og.logo} mark`);
    }
    if (og.logo === null) {
      const want =
        og.mono ??
        (shortName(row).match(/[a-z0-9]/i)?.[0]?.toUpperCase() ?? "·");
      if (letter !== want) {
        fail(`${row.run_id}: og disc mono ${letter} != ${want}`);
      }
    }
  });
  console.log(
    `og.html discs cross-checked: ${discs.length} discs against the table`,
  );
} else {
  console.log("og.html discs cross-checked: skipped (no .og/og.html; run a build first)");
}

if (failures.length > 0) {
  console.error(`\nvendor agreement FAILED (${failures.length}):`);
  for (const f of failures) console.error(`  - ${f}`);
  process.exit(1);
}
console.log(
  `\nvendor agreement: all ${rows.length} payload rows agree across page marks, page colors and the share image`,
);
