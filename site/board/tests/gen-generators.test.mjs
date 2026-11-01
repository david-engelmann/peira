/**
 * Generator behaviour tests for the share image scripts.
 *
 * These run gen-og.mjs and gen-social-preview.mjs against
 * mutated copies of the standing payload in a scratch board
 * tree, so the placer tiers, the axis port, the claim guards
 * and the off-scale disclosure are held by an automated gate
 * instead of only by the manual mutation runs recorded in
 * the lane reports. Each test asserts on the generator's
 * exit code, its log line, and the HTML or probe geometry
 * it wrote, all of which a regression in the tier logic,
 * the axis rule or a guard would change.
 *
 * One fixture stands apart from the standing payload.
 * tests/fixtures/payload-46.json is the 46-row dry-run
 * payload generated on 2026-10-30 for the publish
 * population, frozen as the population the publish gate
 * will meet. It is not the live payload, which is the
 * standing data/payload.json, and this suite never
 * regenerates it. The tests that pin its exact figures
 * hold only because the fixture is frozen.
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
  return {
    status: res.status,
    out: `${res.stdout ?? ""}\n${res.stderr ?? ""}`,
    html: existsSync(path.join(board, ".og", "og.html"))
      ? readFileSync(path.join(board, ".og", "og.html"), "utf8")
      : "",
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
        run.out.includes("mercury-decide (12.6% at $0.2)"),
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
      /* The worst ranked rate is derived from the payload
       * under test, the way the generator derives it, and
       * the population is then moved so that rate sits
       * exactly on the tenth. Ranked rows above the step
       * come down onto it, and when every ranked row sits
       * below it the row carrying the maximum goes up onto
       * it. Either way the maximum the generator derives
       * is exactly 0.30, whatever row carried it into the
       * test. The earlier shape named the carrier outright
       * and assumed it already held the maximum, which held
       * only until a tougher uncosted result took the
       * maximum off the named row and the generator's
       * correct 0.4 axis failed the test on a population
       * the publish is about to install. */
      const ranked = payload.ranked;
      const worst = Math.max(
        ...ranked.map((r) => r.asr_conditional ?? 0),
      );
      for (const r of ranked) {
        if ((r.asr_conditional ?? 0) > 0.3) r.asr_conditional = 0.3;
      }
      if (worst < 0.3) {
        const carrier = ranked.find(
          (r) => (r.asr_conditional ?? 0) === worst,
        );
        carrier.asr_conditional = 0.3;
      }
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

/* The guard-breaking shape from the #521 post-hoc audit:
 * gpt-5.6-terra repriced to $4,200 with its attack success
 * unchanged. Terra becomes the priciest ranked plotted run
 * while the population maximum stays with fable, so the
 * headline claim (the priciest model was the easiest to
 * flip) breaks, and each generator must fail closed on it
 * rather than print the claim. These are the tests RT-4 of
 * the review found missing: neutralising either guard must
 * turn the matching test red. */
function repriceTerra(payload) {
  const rows = new Map(
    [...payload.ranked, ...payload.unranked].map((r) => [r.run_id, r]),
  );
  rows.get("openai-terra56-v2-trial").total_cost_usd = 4200;
}

test(
  "gen-og fails the build when the headline claim breaks on a repriced payload",
  { timeout: 300000 },
  () => {
    const { scratch, board } = scratchBoard(repriceTerra);
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
      const rows = new Map(
        [...payload.ranked, ...payload.unranked].map((r) => [r.run_id, r]),
      );
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

const distToDisc = (box, d) => {
  const dx = Math.max(box.x - d.cx, 0, d.cx - (box.x + box.w));
  const dy = Math.max(box.y - d.cy, 0, d.cy - (box.y + box.h));
  return Math.hypot(dx, dy);
};
const boxesOverlap = (a, b) =>
  a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

test(
  "the 46-row payload: the off-scale flagged point is disclosed in words, never drawn, and no disc or label strikes a corner claim",
  { timeout: 300000 },
  () => {
    const fixture = path.join(
      boardRoot,
      "tests",
      "fixtures",
      "payload-46.json",
    );
    const { scratch, board } = scratchBoard(() => {}, fixture);
    try {
      const run = runGenOg(board, { PEIRA_OG_PROBE: "1" });
      assert.equal(run.status, 0, run.out);
      assert.match(
        run.out,
        /disclosed in words in the image instead of drawn: mercury-3/,
      );
      assert.match(run.out, /labelled 33 of 33 plotted points/);
      assert.ok(run.probe, "the probe geometry was not written");
      /* Every drawn disc sits on the canvas. */
      for (const d of run.probe.discs) {
        assert.ok(
          d.cy - d.r >= 0 && d.cy + d.r <= 630,
          `a disc sits off the canvas at cy ${d.cy}`,
        );
      }
      /* No disc and no label intersects a corner claim box. */
      for (const d of run.probe.discs) {
        for (const c of run.probe.claims) {
          assert.ok(
            distToDisc(c.box, d) >= d.r - 0.01,
            `a disc at ${d.cx}, ${d.cy} intersects the claim "${c.text}"`,
          );
        }
      }
      for (const l of run.probe.labels) {
        for (const c of run.probe.claims) {
          assert.ok(
            !boxesOverlap(l.box, c.box),
            `the label "${l.name}" intersects the claim "${c.text}"`,
          );
        }
      }
      /* The disclosure names the point and carries its
       * figure with the decomposition clauses. */
      assert.ok(run.probe.disclosure, "no disclosure block in the image");
      for (const needle of [
        "mercury-3",
        "52.3%",
        "genuine flip rate 7.5%",
        "85.6% of counted flips to malformed output",
      ]) {
        assert.ok(
          run.probe.disclosure.text.includes(needle),
          `the disclosure does not state "${needle}": ${run.probe.disclosure.text}`,
        );
      }
      assert.ok(
        !run.probe.labels.some((l) => l.name === "mercury-3"),
        "the off-scale point carries a plotted label",
      );
    } finally {
      rmSync(scratch, { recursive: true, force: true });
    }
  },
);

test(
  "gen-og fails rather than state an off-scale flagged figure whose decomposition does not derive",
  { timeout: 300000 },
  () => {
    const fixture = path.join(
      boardRoot,
      "tests",
      "fixtures",
      "payload-46.json",
    );
    const { scratch, board } = scratchBoard((payload) => {
      const mercury = [...payload.ranked, ...payload.unranked].find(
        (r) => r.display_name === "mercury-3",
      );
      const fams = mercury.detail.families;
      const first = Array.isArray(fams) ? fams[0] : Object.values(fams)[0];
      delete first.flip_direction;
    }, fixture);
    try {
      const run = runGenOg(board);
      assert.equal(run.status, 1, run.out);
      assert.match(run.out, /do not derive the malformed decomposition/);
    } finally {
      rmSync(scratch, { recursive: true, force: true });
    }
  },
);

/* The micro labels, pinned as literals. The generator's own
 * guard recomputes the expected label from the same
 * predicates that compose it, so no payload can make the
 * guard disagree with the print, and a suite that only
 * drives payloads proves nothing about the words. This
 * test states the expected words outright, computed from
 * the fixture by hand. On the frozen 46-row fixture the
 * cheapest costed run is pplx-decider-flash-v1.2 at
 * $0.0287, sitting at 0.10 of the derived log cost domain,
 * inside the lowest quarter, while its rate of 21.0% sits
 * above the costed population's first quartile rate of
 * 11.3%, so its label is NEAR-FREE alone. The priciest
 * costed run is claude-fable-5-1 at $130.3128, sitting at
 * 0.91 of the domain, inside the highest quarter, and its
 * rate of 28.5% is the costed population maximum, so its
 * label is EXPENSIVE AND FRAGILE. A predicate change that
 * alters either printed word turns this test red while
 * the generator's own guard stays green. */
test(
  "gen-social-preview prints the fixture population's micro labels, pinned as literals",
  { timeout: 300000 },
  () => {
    const fixture = path.join(
      boardRoot,
      "tests",
      "fixtures",
      "payload-46.json",
    );
    const { scratch, board } = scratchBoard(() => {}, fixture);
    try {
      const run = runGenSocial(board);
      assert.equal(run.status, 0, run.out);
      const micros = [
        ...run.html.matchAll(/class="micro2"[^>]*>([^<]*)<\/text>/g),
      ].map((m) => m[1]);
      assert.deepEqual(
        micros,
        ["NEAR-FREE", "EXPENSIVE AND FRAGILE"],
        `the printed micro labels are not the pinned words: ${micros.join(" | ")}`,
      );
    } finally {
      rmSync(scratch, { recursive: true, force: true });
    }
  },
);
