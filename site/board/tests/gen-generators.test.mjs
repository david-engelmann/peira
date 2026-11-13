/**
 * Generator behaviour tests for the share image scripts.
 *
 * Restored on PR 536 in reduced form. The suite pins the
 * fail-closed laws and the kept behaviours of the two
 * generators the repo still runs, gen-og.mjs (the prebuild)
 * and gen-social-preview.mjs. The laws are the point. A
 * pooled decomposition that does not derive fails the
 * build, a flagged figure whose decomposition does not
 * derive fails the build, a headline claim that breaks on
 * the payload fails the build, and a sub-cent lower bound
 * prints at extended precision and never as zero.
 *
 * The retired assertions are named in the PR body. They
 * pinned the share grammar of the design this PR replaces
 * (the ladder fit funding, the label placement geometry,
 * the axis and stack geometry, the fixture micro label
 * words, and the ceiling naming words) and they leave
 * with that grammar. What stands below is every assertion
 * that exercises machinery the shipped board still runs.
 *
 * One fixture stands apart from the standing payload.
 * tests/fixtures/payload-46.json is the 46-row dry-run
 * payload generated on 2026-10-30 for the publish
 * population, frozen as the population the publish gate
 * will meet. It is not the live payload, which is the
 * standing data/payload.json, and this suite never
 * regenerates it. The tests that pin its exact figures
 * hold only because the fixture is frozen.
 *
 * The og card headline is the split, and its guard needs
 * the flagged pool to flip mostly to malformed output, so
 * the fixture tests that exercise machinery behind the
 * guard first seat the population into the claim domain
 * (seatSplitDomain below).
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

function scratchBoard(mutate, payloadPath) {
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
    path.join(boardRoot, "scripts", "gen-social-preview.mjs"),
    path.join(board, "scripts", "gen-social-preview.mjs"),
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
    readFileSync(
      payloadPath ?? path.join(boardRoot, "data", "payload.json"),
      "utf8",
    ),
  );
  mutate(payload);
  writeFileSync(
    path.join(board, "data", "payload.json"),
    JSON.stringify(payload, null, 1),
  );
  return { scratch, board };
}

function runGenOg(board, env) {
  const res = spawnSync("node", ["scripts/gen-og.mjs"], {
    cwd: board,
    encoding: "utf8",
    timeout: 240000,
    env: { ...process.env, ...env },
  });
  const read = (name) =>
    existsSync(path.join(board, ".og", name))
      ? readFileSync(path.join(board, ".og", name), "utf8")
      : "";
  return {
    status: res.status,
    out: `${res.stdout ?? ""}\n${res.stderr ?? ""}`,
    htmlLand: read("og-land.html"),
    htmlPort: read("og-port.html"),
    probe: existsSync(path.join(board, ".og", "probe.json"))
      ? JSON.parse(readFileSync(path.join(board, ".og", "probe.json"), "utf8"))
      : null,
  };
}

function runGenSocial(board) {
  const res = spawnSync("node", ["scripts/gen-social-preview.mjs"], {
    cwd: board,
    encoding: "utf8",
    timeout: 240000,
  });
  return {
    status: res.status,
    out: `${res.stdout ?? ""}\n${res.stderr ?? ""}`,
    html: existsSync(path.join(board, ".og", "social.html"))
      ? readFileSync(path.join(board, ".og", "social.html"), "utf8")
      : "",
  };
}

const allRows = (payload) => [...payload.ranked, ...payload.unranked];

/* The flip decomposition and the pooled split, ported for
 * expectations the way the board's tests port them: a row
 * whose family records do not cross-check against its
 * printed rate derives nothing. */
function decompOf(r) {
  let fams = r.detail?.families;
  if (!fams) return null;
  if (!Array.isArray(fams)) fams = Object.values(fams);
  let flips = 0;
  let malformed = 0;
  for (const f of fams) {
    if (typeof f.n_flipped !== "number") return null;
    const tm = f.flip_direction?.["to-malformed"];
    if (typeof tm !== "number" || tm > f.n_flipped) return null;
    flips += f.n_flipped;
    malformed += tm;
  }
  const n = r.n_eligible;
  if (!n || flips === 0) return null;
  if (Math.abs(flips / n - r.asr_conditional) > 0.001) return null;
  return { flips, malformed, share: malformed / flips };
}

/* Seat a payload into the og card's claim domain: the
 * flagged row with the most counted flips after the lead
 * has every counted flip land on malformed output, which
 * lifts the flagged pool over its majority without
 * touching the lead's own pinned decomposition. */
function seatSplitDomain(payload, exclude = []) {
  const lead = payload.unranked.reduce((a, b) =>
    (a.asr_conditional ?? 0) > (b.asr_conditional ?? 0) ? a : b,
  );
  const rest = payload.unranked
    .filter((r) => r.run_id !== lead.run_id && !exclude.includes(r.run_id))
    .sort((a, b) => (decompOf(b)?.flips ?? 0) - (decompOf(a)?.flips ?? 0));
  const row = rest[0];
  let fams = row.detail.families;
  if (!Array.isArray(fams)) fams = Object.values(fams);
  for (const f of fams) f.flip_direction["to-malformed"] = f.n_flipped;
}

/* The guard-breaking shape from the #521 post-hoc audit:
 * gpt-5.6-terra repriced to $4,200 with its attack success
 * unchanged. Under the instrument grammar this broke the
 * headline, because terra became the priciest ranked
 * plotted run while the population maximum stayed with
 * fable. Under the split grammar cost carries no claim:
 * gen-og must build the card with terra as its subject, and
 * gen-social-preview, whose headline still stands on the
 * two drawn points, must still fail closed on it. */
function repriceTerra(payload) {
  const rows = new Map(allRows(payload).map((r) => [r.run_id, r]));
  rows.get("openai-terra56-v2-trial").total_cost_usd = 4200;
}

test(
  "gen-og fails the build when the split breaks on a payload whose flagged pool stops flipping to malformed output",
  { timeout: 300000 },
  () => {
    const { scratch, board } = scratchBoard((payload) => {
      for (const r of payload.unranked) {
        let fams = r.detail.families;
        if (!Array.isArray(fams)) fams = Object.values(fams);
        for (const f of fams) f.flip_direction["to-malformed"] = 0;
      }
    });
    try {
      const run = runGenOg(board);
      assert.equal(run.status, 1, run.out);
      assert.match(run.out, /headline claim broken on this payload/);
    } finally {
      rmSync(scratch, { recursive: true, force: true });
    }
  },
);

test(
  "gen-og fails the build when a pooled decomposition does not derive",
  { timeout: 300000 },
  () => {
    const { scratch, board } = scratchBoard((payload) => {
      const row = payload.unranked[0];
      let fams = row.detail.families;
      if (!Array.isArray(fams)) fams = Object.values(fams);
      delete fams[0].flip_direction;
    });
    try {
      const run = runGenOg(board);
      assert.equal(run.status, 1, run.out);
      assert.match(run.out, /a pooled decomposition does not derive/);
    } finally {
      rmSync(scratch, { recursive: true, force: true });
    }
  },
);

test(
  "gen-og builds a repriced payload with the repriced run as its subject and no claim on it",
  { timeout: 300000 },
  () => {
    const { scratch, board } = scratchBoard(repriceTerra);
    try {
      const run = runGenOg(board, { PEIRA_OG_PROBE: "1" });
      assert.equal(run.status, 0, run.out);
      assert.ok(run.probe, "the probe geometry was not written");
      assert.equal(run.probe.land.subjectRunId, "openai-terra56-v2-trial");
      assert.equal(
        run.probe.land.headline,
        "The ranked board flips on decisions. The flagged band flips on broken output.",
      );
    } finally {
      rmSync(scratch, { recursive: true, force: true });
    }
  },
);

test(
  "gen-og fails closed when the ladder's slack alone narrows the portrait plot under its floor",
  { timeout: 300000 },
  () => {
    const { scratch, board } = scratchBoard((payload) => {
      /* Six more no-cost full suite rows take the rail
       * to fifteen. The portrait ladder funds the rows
       * past its allotment from the plot, and fifteen
       * rows take enough slack to carry the plot under
       * its floor before the fit walk runs, so the build
       * must refuse on the floor guard and not on any
       * later measure. */
      const von = payload.ranked.find((r) => r.run_id === "von-v2-trial");
      for (let i = 0; i < 6; i++) {
        const clone = JSON.parse(JSON.stringify(von));
        clone.run_id = `synthetic-rail-${i}-v2-trial`;
        clone.display_name = `synthetic-rail-${i}`;
        payload.ranked.push(clone);
      }
    });
    try {
      const run = runGenOg(board);
      assert.equal(run.status, 1, run.out);
      assert.match(run.out, /portrait ladder's slack narrows its plot/);
      assert.match(run.out, /shrunk past the floor by the ladder/);
    } finally {
      rmSync(scratch, { recursive: true, force: true });
    }
  },
);

test(
  "gen-social-preview fails the build when its headline claim breaks on a repriced payload",
  { timeout: 300000 },
  () => {
    const { scratch, board } = scratchBoard(repriceTerra);
    try {
      const run = runGenSocial(board);
      assert.equal(run.status, 1, run.out);
      assert.match(
        run.out,
        /the headline \(the priciest run carries the highest attack success/,
      );
    } finally {
      rmSync(scratch, { recursive: true, force: true });
    }
  },
);

test(
  "gen-social-preview fails when the ranked full suite holds fewer than two distinct costed runs",
  { timeout: 300000 },
  () => {
    const { scratch, board } = scratchBoard((payload) => {
      const full = Math.max(...payload.ranked.map((r) => r.n_cases));
      for (const r of payload.ranked) {
        if (r.n_cases === full && r.run_id !== "anthropic-fable-v2-trial") {
          r.total_cost_usd = null;
        }
      }
    });
    try {
      const run = runGenSocial(board);
      assert.equal(run.status, 1, run.out);
      assert.match(run.out, /does not hold two distinct costed runs/);
    } finally {
      rmSync(scratch, { recursive: true, force: true });
    }
  },
);

test(
  "gen-social-preview builds the standing card",
  { timeout: 300000 },
  () => {
    const { scratch, board } = scratchBoard(() => {});
    try {
      const run = runGenSocial(board);
      assert.equal(run.status, 0, run.out);
      assert.match(run.out, /wrote .github\/social-preview.png/);
      assert.ok(
        existsSync(path.join(scratch, ".github", "social-preview.png")),
        "the card was not written",
      );
    } finally {
      rmSync(scratch, { recursive: true, force: true });
    }
  },
);

test(
  "gen-social-preview prints a sub-cent lower bound at extended precision, never as zero",
  { timeout: 300000 },
  () => {
    const fixture = path.join(
      boardRoot,
      "tests",
      "fixtures",
      "payload-46.json",
    );
    const { scratch, board } = scratchBoard((payload) => {
      const rows = new Map(allRows(payload).map((r) => [r.run_id, r]));
      /* The red team's stress shape: the toughest ranked run
       * repriced under a cent becomes the card's cheap end,
       * and its recorded cost is a lower bound. */
      const argon = [...rows.values()].find((r) =>
        r.display_name.includes("argon"),
      );
      argon.total_cost_usd = 0.0009;
    }, fixture);
    try {
      const run = runGenSocial(board);
      assert.equal(run.status, 0, run.out);
      assert.ok(
        run.html.includes("at least $0.0009 per run"),
        `the sub-cent bound does not print at extended precision: ${run.out}`,
      );
      assert.ok(
        !run.html.includes("at least $0.00 per run"),
        "the sub-cent bound prints as zero dollars",
      );
    } finally {
      rmSync(scratch, { recursive: true, force: true });
    }
  },
);

test(
  "gen-og fails rather than pool a flagged figure whose decomposition does not derive",
  { timeout: 300000 },
  () => {
    const fixture = path.join(
      boardRoot,
      "tests",
      "fixtures",
      "payload-46.json",
    );
    const { scratch, board } = scratchBoard((payload) => {
      seatSplitDomain(payload);
      const mercury = allRows(payload).find(
        (r) => r.display_name === "mercury-3",
      );
      const fams = mercury.detail.families;
      const first = Array.isArray(fams) ? fams[0] : Object.values(fams)[0];
      delete first.flip_direction;
    }, fixture);
    try {
      const run = runGenOg(board);
      assert.equal(run.status, 1, run.out);
      /* The pool guard fires before the off-scale guard by
       * construction: the lead stands in the flagged pool,
       * so its broken records take the pool down first. */
      assert.match(run.out, /a pooled decomposition does not derive/);
    } finally {
      rmSync(scratch, { recursive: true, force: true });
    }
  },
);

/* Reseat a row on an exact counted flip total, the way
 * the ceiling mutation below needs it. */
function seatFlips(row, flips, malformed) {
  Object.values(row.detail.families).forEach((f, i) => {
    f.n_flipped = i === 0 ? flips : 0;
    f.flip_direction["to-malformed"] = i === 0 ? malformed : 0;
  });
}

test(
  "a flagged point exactly at the axis ceiling whose decomposition does not derive fails the build",
  { timeout: 300000 },
  () => {
    const fixture = path.join(
      boardRoot,
      "tests",
      "fixtures",
      "payload-46.json",
    );
    const { scratch, board } = scratchBoard((payload) => {
      seatSplitDomain(payload);
      const row = payload.unranked.find(
        (r) => r.run_id === "or-ling31-v2-trial",
      );
      row.asr_conditional = 0.3;
      seatFlips(row, 0, 0);
    }, fixture);
    try {
      const run = runGenOg(board);
      assert.equal(run.status, 1, run.out);
      /* The build fails closed, as the ceiling discipline
       * demands. The message is the pool guard's: the
       * ceiling point stands in the flagged pool, so its
       * broken records take the pool down before the
       * ceiling guard behind it is reached. */
      assert.match(run.out, /a pooled decomposition does not derive/);
    } finally {
      rmSync(scratch, { recursive: true, force: true });
    }
  },
);

test(
  "gen-og builds both standing cards",
  { timeout: 300000 },
  () => {
    const { scratch, board } = scratchBoard(() => {});
    try {
      const run = runGenOg(board, { PEIRA_OG_PROBE: "1" });
      assert.equal(run.status, 0, run.out);
      assert.ok(
        existsSync(path.join(board, "public", "og.png")),
        "the landscape card was not written",
      );
      assert.ok(
        existsSync(path.join(board, "public", "og-portrait.png")),
        "the portrait card was not written",
      );
      /* The prebuild copies the payload into public, the
       * standing publish mechanism, and the copy is the
       * payload itself. */
      const copied = path.join(board, "public", "payload.json");
      assert.ok(existsSync(copied), "the payload was not copied into public");
      assert.deepEqual(
        JSON.parse(readFileSync(copied, "utf8")),
        JSON.parse(
          readFileSync(path.join(board, "data", "payload.json"), "utf8"),
        ),
        "the copied payload is not the payload under test",
      );
      assert.ok(run.probe, "the probe geometry was not written");
      assert.equal(
        run.probe.land.headline,
        "The ranked board flips on decisions. The flagged band flips on broken output.",
      );
      assert.equal(
        run.probe.land.mastRight,
        `Decision models under attack · ${allRows(JSON.parse(readFileSync(path.join(boardRoot, "data", "payload.json"), "utf8"))).length} results`,
      );
    } finally {
      rmSync(scratch, { recursive: true, force: true });
    }
  },
);
