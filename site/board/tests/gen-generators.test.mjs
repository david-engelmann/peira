/**
 * Generator behaviour tests for the share image scripts.
 *
 * These run gen-og.mjs against mutated copies of the standing
 * payload in a scratch board tree, so the placer tiers and the
 * axis port are held by an automated gate instead of only by
 * the manual mutation runs recorded in the lane reports.
 * Each test asserts on the generator's exit code, its log
 * line, and the HTML it wrote, all of which a regression in
 * the tier logic or the axis rule would change.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  cpSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const boardRoot = path.dirname(path.dirname(fileURLToPath(import.meta.url)));

function scratchBoard(mutate) {
  const scratch = mkdtempSync(path.join(boardRoot, ".test-tmp-"));
  const board = path.join(scratch, "site", "board");
  mkdirSync(path.join(board, "scripts"), { recursive: true });
  mkdirSync(path.join(board, "data"), { recursive: true });
  mkdirSync(path.join(board, "lib"), { recursive: true });
  mkdirSync(path.join(board, "public", "fonts"), { recursive: true });
  cpSync(
    path.join(boardRoot, "scripts", "gen-og.mjs"),
    path.join(board, "scripts", "gen-og.mjs"),
  );
  cpSync(
    path.join(boardRoot, "lib", "vendor-data.json"),
    path.join(board, "lib", "vendor-data.json"),
  );
  cpSync(
    path.join(boardRoot, "lib", "logoPaths.ts"),
    path.join(board, "lib", "logoPaths.ts"),
  );
  cpSync(
    path.join(boardRoot, "public", "fonts", "archivo.woff2"),
    path.join(board, "public", "fonts", "archivo.woff2"),
  );
  symlinkSync(
    path.join(boardRoot, "node_modules"),
    path.join(board, "node_modules"),
    "dir",
  );
  const payload = JSON.parse(
    readFileSync(path.join(boardRoot, "data", "payload.json"), "utf8"),
  );
  mutate(payload);
  writeFileSync(
    path.join(board, "data", "payload.json"),
    JSON.stringify(payload, null, 1),
  );
  return { scratch, board };
}

function runGenOg(board) {
  const res = spawnSync("node", ["scripts/gen-og.mjs"], {
    cwd: board,
    encoding: "utf8",
    timeout: 240000,
  });
  return {
    status: res.status,
    out: `${res.stdout ?? ""}\n${res.stderr ?? ""}`,
    html: existsSync(path.join(board, ".og", "og.html"))
      ? readFileSync(path.join(board, ".og", "og.html"), "utf8")
      : "",
  };
}

/* The cluster fixture: six cheap runs moved onto one identical
 * cost and rate, the crowd that drove the words tier in the
 * manual proofs. One of the six cannot seat beside its disc,
 * and the strip must name it with its own figures. */
const CLUSTER_IDS = [
  "mercury-decide-v2-trial",
  "pplx-decider-v2-trial",
  "celeris-v2-trial",
  "clef-flash-v2-trial",
  "jev-v2-trial",
  "jev-114-v2-trial",
];

test(
  "the OG placer completes on a clustered payload and names the unseated point in words with its figures",
  { timeout: 300000 },
  () => {
    const { scratch, board } = scratchBoard((payload) => {
      const rows = new Map(
        [...payload.ranked, ...payload.unranked].map((r) => [r.run_id, r]),
      );
      for (const id of CLUSTER_IDS) {
        rows.get(id).total_cost_usd = 0.2;
        rows.get(id).asr_conditional = 0.1263;
      }
    });
    try {
      const run = runGenOg(board);
      assert.equal(run.status, 0, run.out);
      assert.match(run.out, /named in words in the strip under the chart/);
      assert.ok(
        run.out.includes("mercury-decide (12.6% at $0.20)"),
        `the words tier does not name mercury-decide with its mutated figures: ${run.out}`,
      );
    } finally {
      rmSync(scratch, { recursive: true, force: true });
    }
  },
);

test(
  "a worst ranked rate of exactly 0.30 draws the axis to 0.3 and not 0.4",
  { timeout: 300000 },
  () => {
    const { scratch, board } = scratchBoard((payload) => {
      const rows = new Map(
        [...payload.ranked, ...payload.unranked].map((r) => [r.run_id, r]),
      );
      /* The priciest run already carries the population maximum,
       * so raising it to the exact tenth keeps the headline
       * guard true while it moves the worst ranked rate onto
       * the step the old port mishandled. */
      rows.get("anthropic-fable-v2-trial").asr_conditional = 0.3;
    });
    try {
      const run = runGenOg(board);
      assert.equal(run.status, 0, run.out);
      assert.ok(
        /class="tick">30</.test(run.html),
        "the axis does not draw a tick at 30",
      );
      assert.ok(
        !/class="tick">40</.test(run.html),
        "the axis draws a tick at 40 for a worst rate of exactly 0.30, so the port added a step on an exact tenth",
      );
    } finally {
      rmSync(scratch, { recursive: true, force: true });
    }
  },
);
