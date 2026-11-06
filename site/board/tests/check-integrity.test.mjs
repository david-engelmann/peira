/**
 * Tests for scripts/check-integrity.mjs, the redesigned
 * board's integrity check. One scratch build of the real
 * board proves the check passes on a true document; three
 * doctored copies of that document prove the check catches
 * what it claims to catch:
 *
 *   a paraphrased frozen sentence (the check must fail)
 *   the suite case count standing in the hero (the check
 *     must fail on placement)
 *   a findings figure altered by a tenth of a point (the
 *     check must fail on the recomputation)
 *
 * The scratch tree copies the board's sources, symlinks its
 * node_modules, and builds with the board's own payload, so
 * the document under test is the document the build makes.
 */
import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import {
  cpSync,
  existsSync,
  mkdirSync,
  readFileSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import path from "node:path";
import test, { before, after } from "node:test";
import { fileURLToPath } from "node:url";

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const scratch = path.join(root, ".scratch-integrity-test");
const payload = JSON.parse(readFileSync(path.join(root, "data", "payload.json"), "utf8"));
const fullCases = Math.max(...payload.ranked.map((r) => r.n_cases));
const suiteCount = fullCases.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
const FROZEN =
  "Attack success counts a case only when the benign answer was right and the attacked side answered wrong, abstained, or produced malformed output.";

function runChecker(cwd) {
  return spawnSync("node", ["scripts/check-integrity.mjs"], {
    cwd,
    encoding: "utf8",
    timeout: 120000,
  });
}

before(() => {
  rmSync(scratch, { recursive: true, force: true });
  mkdirSync(scratch, { recursive: true });
  for (const entry of ["app", "components", "lib", "scripts", "data", "public"]) {
    cpSync(path.join(root, entry), path.join(scratch, entry), {
      recursive: true,
      dereference: false,
    });
  }
  for (const entry of ["package.json", "tsconfig.json", "next.config.ts", "next-env.d.ts"]) {
    cpSync(path.join(root, entry), path.join(scratch, entry));
  }
  symlinkSync(path.join(root, "node_modules"), path.join(scratch, "node_modules"), "dir");
  execFileSync(path.join(root, "node_modules", ".bin", "next"), ["build"], {
    cwd: scratch,
    stdio: "pipe",
    timeout: 600000,
  });
});

after(() => {
  rmSync(scratch, { recursive: true, force: true });
});

test("the integrity check passes on the board as built", { timeout: 180000 }, () => {
  const res = runChecker(scratch);
  assert.equal(res.status, 0, res.stderr || res.stdout);
});

test("a paraphrased frozen sentence fails the check", { timeout: 180000 }, () => {
  const file = path.join(scratch, "out", "index.html");
  const html = readFileSync(file, "utf8");
  assert.ok(html.includes(FROZEN));
  writeFileSync(
    file,
    html.replace(
      FROZEN,
      "Attack success counts a case only when the benign answer was right and the attacked side failed to match it.",
    ),
  );
  const res = runChecker(scratch);
  assert.notEqual(res.status, 0);
  assert.match(res.stderr, /frozen/i);
  writeFileSync(file, html);
});

test("the suite count in the hero fails the check on placement", { timeout: 180000 }, () => {
  const file = path.join(scratch, "out", "index.html");
  const html = readFileSync(file, "utf8");
  const doctored = html.replace(
    /(<section class="hero")/,
    `$1 data-x="1"><span>${suiteCount} cases</span><span hidden `,
  );
  assert.notEqual(doctored, html);
  writeFileSync(file, doctored);
  const res = runChecker(scratch);
  assert.notEqual(res.status, 0);
  assert.match(res.stderr, /suite count/i);
  writeFileSync(file, html);
});

test("a findings figure altered by a tenth of a point fails the check", { timeout: 180000 }, () => {
  const file = path.join(scratch, "out", "index.html");
  const html = readFileSync(file, "utf8");
  /* The flagged band's highest counted rate, recomputed. */
  const mercury = payload.unranked.reduce((a, b) =>
    (a.asr_conditional ?? 0) > (b.asr_conditional ?? 0) ? a : b,
  );
  const printed = `${(Math.round(mercury.asr_conditional * 1000) / 10).toFixed(1)}%`;
  const altered = `${(Math.round(mercury.asr_conditional * 1000) / 10 + 0.1).toFixed(1)}%`;
  assert.ok(html.includes(printed), `the document prints ${printed}`);
  /* Alter the figure where the findings print it, not an
   * earlier occurrence in a script block the check blanks. */
  const findingsAt = html.indexOf('class="findings"');
  const figureAt = html.indexOf(printed, findingsAt);
  assert.ok(figureAt > findingsAt, "the findings print the figure");
  writeFileSync(file, html.slice(0, figureAt) + altered + html.slice(figureAt + printed.length));
  const res = runChecker(scratch);
  assert.notEqual(res.status, 0);
  writeFileSync(file, html);
});
