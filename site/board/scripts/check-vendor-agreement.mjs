#!/usr/bin/env node
/**
 * Vendor agreement check. lib/vendor-data.json is the one
 * vendor table for the whole board; this script proves the
 * resolvers that read it agree on every payload row.
 *
 *   page marks    lib/vendor.ts vendorOf (executed for real,
 *                 through scripts/vendor-check-hooks.mjs)
 *   page colors   lib/vendorColors.ts vendorFamilyOf (same)
 *   share image   scripts/gen-og.mjs familyOf, resolved here
 *                 through the shared table
 *
 * It also proves the table is the only one. No family color
 * may appear in any resolver's or generator's source, gen-og
 * may carry no FAMILIES or MONO_LETTERS table of its own,
 * every logo slug the table names must exist in
 * lib/logoPaths.ts, and the table's design tokens, the ink
 * and the subject fill the share images resolve through it,
 * must be present and well formed.
 *
 * The last leg reads the share images as drawn. gen-og
 * writes .og/og-land.html and .og/og-port.html and
 * gen-social-preview writes .og/social.html. On each og
 * card the subject disc must carry the table's subject fill
 * and name the payload's headline result, the priciest
 * ranked plotted run, derived here by the generator's own
 * rule, and the social card's wordmark must carry the
 * table's ink. A generated file that is missing, or a mark
 * that is absent from one, fails this check. Nothing here
 * skips.
 *
 * Exit code is non-zero on any disagreement. Run after
 * node scripts/gen-og.mjs and node
 * scripts/gen-social-preview.mjs so the .og files are
 * current.
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
for (const rel of [
  "lib/vendor.ts",
  "lib/vendorColors.ts",
  "scripts/gen-og.mjs",
  "scripts/gen-social-preview.mjs",
]) {
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

/* The table's design tokens. Both generators resolve the
 * share images' ink and subject fill through them, so a
 * missing or malformed token fails here under its own name
 * rather than as a bare TypeError in a generator. */
const HEX_COLOR = /^#[0-9a-fA-F]{6}$/;
for (const key of ["ink", "subjectFill"]) {
  const value = data.design?.[key];
  if (typeof value !== "string" || !HEX_COLOR.test(value)) {
    fail(
      `lib/vendor-data.json design.${key} is missing or not a hex color, and the generators resolve the share image through it`,
    );
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

/* The share images as drawn. gen-og writes the two og
 * cards and gen-social-preview writes the social card into
 * .og/ before rasterizing them, and this leg reads those
 * generated files, never the generators' sources. It must
 * run. A missing file or an absent mark is a failure with
 * a name, never a skip, because a leg that can pass in
 * silence is how the pre-redesign cross-check against
 * .og/og.html died unnoticed once the generator stopped
 * writing that file. The headline result is derived from
 * the payload by the generator's own rule, ported here.
 * The full suite size is the largest case count among
 * ranked rows, the plotted population is the full suite
 * rows with a recorded cost above zero, and the headline
 * is the priciest ranking eligible run among them. */
const fullCases = Math.max(...payload.ranked.map((r) => r.n_cases));
const headline = [...payload.ranked, ...payload.unranked]
  .filter((r) => r.n_cases === fullCases)
  .filter((r) => r.total_cost_usd !== null && r.total_cost_usd > 0)
  .filter((r) => r.ranking_eligible)
  .sort((a, b) => a.total_cost_usd - b.total_cost_usd)
  .at(-1);
const subjectFill = data.design?.subjectFill;
const cardInk = data.design?.ink;
let shareFilesChecked = 0;
for (const kind of ["land", "port"]) {
  const rel = `.og/og-${kind}.html`;
  const file = path.join(root, ".og", `og-${kind}.html`);
  if (!existsSync(file)) {
    fail(
      `${rel} is missing, so the share image leg cannot run. Run node scripts/gen-og.mjs first`,
    );
    continue;
  }
  const html = readFileSync(file, "utf8");
  const disc = html.match(/<circle\b[^>]*\bdata-subject="[^"]+"[^>]*>/);
  if (!disc) {
    fail(`${rel} draws no subject disc, so the share image leg cannot run`);
    continue;
  }
  const fill = disc[0].match(/\bfill="([^"]+)"/)?.[1];
  const named = disc[0].match(/\bdata-subject="([^"]+)"/)[1];
  if (fill === undefined) {
    fail(
      `${rel} draws its subject disc with no fill, so the share image leg cannot run`,
    );
    continue;
  }
  if (
    typeof subjectFill === "string" &&
    fill.toLowerCase() !== subjectFill.toLowerCase()
  ) {
    fail(
      `${rel} draws the subject disc in ${fill}, not the table's subjectFill ${subjectFill}`,
    );
  }
  if (!headline) {
    fail("the payload names no headline result, so the share image leg cannot run");
  } else if (named !== headline.run_id) {
    fail(
      `${rel} names ${named} as its subject, not the payload's headline result ${headline.run_id}`,
    );
  }
  shareFilesChecked += 1;
}
const socialRel = ".og/social.html";
const socialFile = path.join(root, ".og", "social.html");
if (!existsSync(socialFile)) {
  fail(
    `${socialRel} is missing, so the share image leg cannot run. Run node scripts/gen-social-preview.mjs first`,
  );
} else {
  const html = readFileSync(socialFile, "utf8");
  const wordRule = html.match(/\.word\s*\{[^}]*\}/);
  const ink = wordRule?.[0].match(/\bcolor:\s*(#[0-9a-fA-F]{3,8})/)?.[1];
  if (ink === undefined) {
    fail(
      `${socialRel} carries no wordmark color, so the share image leg cannot run`,
    );
  } else {
    if (
      typeof cardInk === "string" &&
      ink.toLowerCase() !== cardInk.toLowerCase()
    ) {
      fail(
        `${socialRel} prints its wordmark in ${ink}, not the table's ink ${cardInk}`,
      );
    }
    shareFilesChecked += 1;
  }
}
if (shareFilesChecked > 0) {
  console.log(
    `share image cross-checked on ${shareFilesChecked} generated cards against the table`,
  );
}

if (failures.length > 0) {
  console.error(`\nvendor agreement FAILED (${failures.length}):`);
  for (const f of failures) console.error(`  - ${f}`);
  process.exit(1);
}
console.log(
  `\nvendor agreement: all ${rows.length} payload rows agree across page marks, page colors and the share image`,
);
