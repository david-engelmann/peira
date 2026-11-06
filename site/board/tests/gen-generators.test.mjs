/**
 * Generator behaviour tests for the share image scripts.
 *
 * These run gen-og.mjs and gen-social-preview.mjs against
 * mutated copies of the standing payload in a scratch board
 * tree, so the claim guards, the label placement tiers, the
 * ladder budget and the flagged decomposition discipline
 * are held by an automated gate instead of only by the
 * manual mutation runs recorded in the lane reports. Each
 * test asserts on the generator's exit code, its log lines,
 * and the probe geometry it writes, all of which a
 * regression in the derivations would change.
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
 * The og card's headline is the board's lead finding, the
 * split, and its guard needs the flagged pool to flip
 * mostly to malformed output. On the frozen fixture that
 * pool sits at 49.2 percent, just under the majority, so
 * the fixture tests that exercise machinery behind the
 * guard first seat the population into the claim's domain
 * (seatSplitDomain below), the same discipline the older
 * mutations applied to the headline guard they lived
 * behind. The social card keeps the owner's two-extremes
 * design and its own guarded claim, unchanged.
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

/* The generators' own name rule, restated for expectations:
 * the short name, with the wire words appended when another
 * result shares it. */
const WIRE_WORDS = {
  "openai-decisions": "Decisions API",
  "openai-structured": "Chat completions",
};
function shortNameOf(r) {
  let name = r.display_name;
  const at = name.lastIndexOf("@");
  if (at > 0 && /^[0-9a-f]{32,}$/i.test(name.slice(at + 1))) {
    name = name.slice(0, at);
  }
  const slash = name.lastIndexOf("/");
  return slash >= 0 ? name.slice(slash + 1) : name;
}
function pointNameOf(payload, r) {
  const n = shortNameOf(r);
  const count = [...payload.ranked, ...payload.unranked].filter(
    (x) => shortNameOf(x) === n,
  ).length;
  return count > 1 ? `${n} (${WIRE_WORDS[r.wire] ?? r.wire})` : n;
}
const fmtPctOf = (v) => `${(v * 100).toFixed(1)}%`;
const fmtIntOf = (n) =>
  Math.round(n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
const allRows = (payload) => [...payload.ranked, ...payload.unranked];
const fullCasesOf = (payload) =>
  Math.max(...payload.ranked.map((r) => r.n_cases));
const nonSliceOf = (payload) =>
  allRows(payload).filter((r) => r.n_cases === fullCasesOf(payload));

const distToDisc = (box, d) => {
  const dx = Math.max(box.x - d.cx, 0, d.cx - (box.x + box.w));
  const dy = Math.max(box.y - d.cy, 0, d.cy - (box.y + box.h));
  return Math.hypot(dx, dy);
};
const boxesOverlap = (a, b) =>
  a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

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
function poolOf(rows) {
  let flips = 0;
  let malformed = 0;
  for (const r of rows) {
    const d = decompOf(r);
    if (d === null) return null;
    flips += d.flips;
    malformed += d.malformed;
  }
  if (flips === 0) return null;
  return { flips, malformed, share: malformed / flips };
}
/* Seat a payload into the og card's claim domain: the
 * flagged row with the most counted flips after the lead
 * has every counted flip land on malformed output, which
 * lifts the flagged pool over its majority without
 * touching the lead's own pinned decomposition. */
function seatSplitDomain(payload) {
  const lead = payload.unranked.reduce((a, b) =>
    (a.asr_conditional ?? 0) > (b.asr_conditional ?? 0) ? a : b,
  );
  const rest = payload.unranked
    .filter((r) => r.run_id !== lead.run_id)
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

test(
  "a worst ranked rate of exactly 0.30 draws the axis to 0.3 and not 0.4",
  { timeout: 300000 },
  () => {
    const { scratch, board } = scratchBoard((payload) => {
      /* The worst ranked rate is derived from the payload
       * under test, the way the generator derives it, and
       * the population is then moved so that rate sits
       * exactly on the tenth. A moved row's family records
       * are reseated on its new rate, so its decomposition
       * still derives for the pooled split. */
      const ranked = payload.ranked;
      const worst = Math.max(...ranked.map((r) => r.asr_conditional ?? 0));
      for (const r of ranked) {
        if ((r.asr_conditional ?? 0) > 0.3) {
          r.asr_conditional = 0.3;
          seatFlips(r, Math.round(0.3 * r.n_eligible), 0);
        }
      }
      if (worst < 0.3) {
        const carrier = ranked.find(
          (r) => (r.asr_conditional ?? 0) === worst,
        );
        carrier.asr_conditional = 0.3;
        seatFlips(carrier, Math.round(0.3 * carrier.n_eligible), 0);
      }
    });
    try {
      const run = runGenOg(board);
      assert.equal(run.status, 0, run.out);
      assert.ok(
        /class="gtick">30</.test(run.htmlLand),
        "the axis does not draw its ceiling tick at 30",
      );
      assert.ok(
        /class="gtick">15</.test(run.htmlLand),
        "the axis does not draw its middle tick at 15",
      );
      assert.ok(
        !/class="gtick">40</.test(run.htmlLand),
        "the axis draws a tick at 40 for a worst rate of exactly 0.30, so the port added a step on an exact tenth",
      );
    } finally {
      rmSync(scratch, { recursive: true, force: true });
    }
  },
);

test(
  "the 46-row payload: the split stack reads beside the plot, the off-scale flagged result reads in it with its decomposition and is never drawn, and no label strikes a disc or the subject",
  { timeout: 300000 },
  () => {
    const fixture = path.join(
      boardRoot,
      "tests",
      "fixtures",
      "payload-46.json",
    );
    const fixturePayload = JSON.parse(readFileSync(fixture, "utf8"));
    seatSplitDomain(fixturePayload);
    const { scratch, board } = scratchBoard((payload) => {
      seatSplitDomain(payload);
    }, fixture);
    try {
      const run = runGenOg(board, { PEIRA_OG_PROBE: "1" });
      assert.equal(run.status, 0, run.out);
      assert.ok(run.probe, "the probe geometry was not written");
      const land = run.probe.land;
      assert.equal(
        land.headline,
        "The ranked board flips on decisions. The flagged band flips on broken output.",
      );
      /* The pools the probe carries are the pools this port
       * derives from the seated fixture. */
      const rankedPool = poolOf(
        fixturePayload.ranked.filter(
          (r) => r.n_cases === fullCasesOf(fixturePayload),
        ),
      );
      const flaggedPool = poolOf(fixturePayload.unranked);
      assert.deepEqual(land.pools, {
        ranked: {
          flips: rankedPool.flips,
          malformed: rankedPool.malformed,
          share: rankedPool.share,
        },
        flagged: {
          flips: flaggedPool.flips,
          malformed: flaggedPool.malformed,
          share: flaggedPool.share,
        },
      });
      /* The stack is the two splits and the flagged lead. */
      assert.equal(land.readouts.length, 3);
      const [rankedBlock, flaggedBlock, leadBlock] = land.readouts;
      assert.equal(rankedBlock.micro, "Ranked, the full suite");
      assert.equal(rankedBlock.num, fmtPctOf(1 - rankedPool.share));
      assert.ok(
        rankedBlock.who.includes(
          `${fmtIntOf(rankedPool.flips)} counted flips`,
        ) &&
          rankedBlock.who.includes(
            `${fmtIntOf(rankedPool.malformed)} (${fmtPctOf(rankedPool.share)}) were malformed output`,
          ),
        `the ranked split does not state its pool: ${rankedBlock.who}`,
      );
      assert.ok(rankedBlock.bar, "the ranked split carries no bar");
      const genuineWidth = parseFloat(
        rankedBlock.bar
          .find((s) => s.cls.includes("genuine"))
          .width.match(/width:([\d.]+)%/)[1],
      );
      assert.ok(
        Math.abs(genuineWidth - (1 - rankedPool.share) * 100) < 0.02,
        `the ranked split bar draws ${genuineWidth} against a pooled genuine share of ${(1 - rankedPool.share) * 100}`,
      );
      assert.equal(flaggedBlock.micro, "Flagged, over the gate");
      assert.equal(flaggedBlock.num, fmtPctOf(flaggedPool.share));
      assert.ok(
        flaggedBlock.who.includes(
          `of ${fmtIntOf(flaggedPool.flips)} counted flips in the flagged band were malformed output`,
        ),
        `the flagged split does not state its pool: ${flaggedBlock.who}`,
      );
      /* The flagged lead carries mercury's figure only with
       * its decomposition. The figures are the frozen
       * fixture's, pinned as literals. */
      assert.equal(leadBlock.micro, "Flagged, off the scale");
      assert.equal(leadBlock.num, "52.3%");
      for (const needle of [
        "mercury-3",
        "counted attack success",
        "85.6% of counted flips to malformed output",
        "genuine flip rate 7.5%",
      ]) {
        assert.ok(
          leadBlock.who.includes(needle),
          `the flagged reading does not state "${needle}": ${leadBlock.who}`,
        );
      }
      /* The subject is the priciest ranked costed run of the
       * fixture, singled out with its figure line. */
      const rankedCosted = nonSliceOf(fixturePayload)
        .filter((r) => r.ranking_eligible && (r.total_cost_usd ?? 0) > 0)
        .sort((a, b) => a.total_cost_usd - b.total_cost_usd);
      const subjectRow = rankedCosted.at(-1);
      assert.equal(land.subject.name, pointNameOf(fixturePayload, subjectRow));
      assert.equal(land.subjectRunId, subjectRow.run_id);
      /* The figure line states a lower bound when the
       * subject's own family records show uncosted calls,
       * the generator's RT-3 rule, derived here from the
       * fixture's families. */
      const subjectBound = (() => {
        const fams = Object.values(subjectRow.detail?.families ?? {});
        let costed = 0;
        let timed = 0;
        let seen = false;
        for (const f of fams) {
          if (f.n_costed_calls == null || f.n_latency_calls == null) {
            return false;
          }
          costed += f.n_costed_calls;
          timed += f.n_latency_calls;
          seen = true;
        }
        return seen && costed < timed;
      })();
      assert.equal(
        land.subject.sub,
        `${subjectBound ? "At least " : ""}$${subjectRow.total_cost_usd.toFixed(2)} a run, ${fmtPctOf(subjectRow.asr_conditional)}`,
      );
      /* The drawn discs are exactly the costed full suite
       * at or under the derived ceiling: mercury is not
       * among them. */
      const axisMax = Math.max(
        0.3,
        Math.ceil(
          (Math.max(
            ...fixturePayload.ranked.map((r) => r.asr_conditional ?? 0),
          ) -
            1e-9) /
            0.1,
        ) * 0.1,
      );
      const drawn = nonSliceOf(fixturePayload).filter(
        (r) =>
          (r.total_cost_usd ?? 0) > 0 && (r.asr_conditional ?? 0) <= axisMax,
      );
      assert.equal(land.discs.length, drawn.length);
      assert.equal(land.discs.filter((d) => d.subject).length, 1);
      /* No seated label strikes a disc, the subject's lines,
       * or the canvas edge of the plot. */
      for (const l of land.labels) {
        for (const d of land.discs) {
          assert.ok(
            distToDisc(l.box, d) >= d.r - 0.01,
            `the label "${l.name}" strikes a disc`,
          );
        }
        assert.ok(
          !boxesOverlap(l.box, land.subject.nameBox),
          `the label "${l.name}" strikes the subject's name`,
        );
        assert.ok(
          !boxesOverlap(l.box, land.subject.subBox),
          `the label "${l.name}" strikes the subject's figure line`,
        );
      }
      /* The footer stands in the share grammar's two parts,
       * stamped from the fixture's own versions and date. */
      const maxDate = allRows(fixturePayload)
        .map((r) => r.created_utc)
        .sort()
        .at(-1)
        .slice(0, 10);
      const [yy, mm, dd] = maxDate.split("-").map(Number);
      const MONTHS = [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
      ];
      assert.deepEqual(land.footer, [
        `Peira decision robustness board. Dataset ${fixturePayload.ranked[0].dataset_version}, suite ${fixturePayload.ranked[0].suite}, updated ${dd} ${MONTHS[mm - 1]} ${yy}.`,
        "Amber marks a flagged result · peiratrial.dev",
      ]);
      /* The portrait card carries the same readings. */
      assert.deepEqual(run.probe.port.readouts, land.readouts);
      assert.deepEqual(run.probe.port.ladder, land.ladder);
    } finally {
      rmSync(scratch, { recursive: true, force: true });
    }
  },
);

test(
  "the 46-row payload with a tougher and a wilder rail: the stack stays the split, and the ladder selects the toughest run",
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
      const rows = new Map(allRows(payload).map((r) => [r.run_id, r]));
      /* The long-named rail run becomes the toughest run on
       * the chart. Its family records reseat on the new
       * rate, so its decomposition still derives. */
      const strands = rows.get("strands-v2-trial");
      strands.asr_conditional = 0.05;
      seatFlips(strands, Math.round(0.05 * strands.n_eligible), 0);
      /* A second rail run flips more than the priciest costed
       * run while staying under the axis ceiling. */
      const kev = rows.get("kev-4b-v2-trial");
      kev.asr_conditional = 0.29;
      seatFlips(kev, Math.round(0.29 * kev.n_eligible), 0);
    }, fixture);
    try {
      const run = runGenOg(board, { PEIRA_OG_PROBE: "1" });
      assert.equal(run.status, 0, run.out);
      assert.ok(run.probe, "the probe geometry was not written");
      const land = run.probe.land;
      assert.deepEqual(
        land.readouts.map((b) => b.micro),
        ["Ranked, the full suite", "Flagged, over the gate", "Flagged, off the scale"],
      );
      const sel = land.ladder.filter((r) => r.sel);
      assert.equal(sel.length, 1);
      assert.equal(sel[0].name, "strands-decider-2B-hobson-v21");
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

/* The crowded-candidates shape: the two label candidates
 * are repriced onto the plot's left side and a grid of
 * synthetic discs is packed around them at disc spacing, so
 * no seat beside either disc is clear. Both candidates must
 * leave the plot's labels and be named in words under it,
 * with their figures, while the build still succeeds. Every
 * moved row's family records are reseated on its new rate,
 * so the pooled split still derives. */
test(
  "label candidates no seat can hold are named in words under the plot with their figures",
  { timeout: 300000 },
  () => {
    let candA;
    let candB;
    const { scratch, board } = scratchBoard((payload) => {
      const full = fullCasesOf(payload);
      const rankedCosted = nonSliceOf(payload)
        .filter((r) => r.ranking_eligible && (r.total_cost_usd ?? 0) > 0)
        .sort((a, b) => b.total_cost_usd - a.total_cost_usd);
      const subjectRow = rankedCosted[0];
      const others = rankedCosted.slice(1);
      candA = others[0];
      candB = others[1];
      /* The candidates stay the two priciest unflagged
       * plotted runs after the subject, seated beside it at
       * the top right. Every other ranked costed run drops
       * below them. */
      candA.total_cost_usd = 120;
      candA.asr_conditional = 0.28;
      seatFlips(candA, Math.round(0.28 * candA.n_eligible), 0);
      candB.total_cost_usd = 110;
      candB.asr_conditional = 0.26;
      seatFlips(candB, Math.round(0.26 * candB.n_eligible), 0);
      for (const r of others.slice(2)) r.total_cost_usd = 0.03;
      /* The blocker grid, in the plot's own landscape units
       * (domain floor 0.01, axis 0.4 from the payload's worst
       * ranked rate): discs at 11.9 unit spacing over the
       * whole seat reach of both candidates. A label box is
       * taller than the spacing, so every seat a candidate
       * tries holds a disc. Blocker costs stay under the
       * candidates' (never candidates themselves) and at or
       * over the domain floor (the domain does not move).
       * Cells whose rate would sit under one percent are
       * skipped: a counted flip total has to stay a
       * nonnegative integer for the decomposition to derive,
       * and the seat reach of the candidates, up at the
       * plot's top right, never reaches those cells. */
      const template = payload.ranked.find((r) => r.n_cases === full);
      const costAtX = (x) => 10 ** ((x - 56) / 144.15 - 2);
      const asrAtY = (y) => (0.4 * (252 - y)) / 236;
      const xOf = (c) => 56 + (Math.log10(c) + 2) * 144.15;
      const yOf = (a) => 252 - (a / 0.4) * 236;
      const centers = [
        { x: xOf(subjectRow.total_cost_usd), y: yOf(subjectRow.asr_conditional) },
        { x: xOf(120), y: yOf(0.28) },
        { x: xOf(110), y: yOf(0.26) },
      ];
      let n = 0;
      for (let gx = 56; gx <= 632; gx += 11.9) {
        for (let gy = 90; gy <= 260; gy += 11.9) {
          if (
            centers.some(
              (c) => Math.hypot(c.x - gx, c.y - gy) < 9,
            )
          ) {
            continue;
          }
          const rate = asrAtY(gy);
          if (rate < 0.01) continue;
          n += 1;
          const row = JSON.parse(JSON.stringify(template));
          row.run_id = `blocker-${n}-v2-trial`;
          row.display_name = `blocker-${n}`;
          row.total_cost_usd = costAtX(gx);
          row.asr_conditional = rate;
          seatFlips(row, Math.round(rate * row.n_eligible), 0);
          payload.ranked.push(row);
        }
      }
      assert.ok(subjectRow, "the standing payload has a subject");
    });
    try {
      const run = runGenOg(board, { PEIRA_OG_PROBE: "1" });
      assert.equal(run.status, 0, run.out);
      assert.ok(run.probe, "the probe geometry was not written");
      const land = run.probe.land;
      assert.equal(
        land.labels.length,
        0,
        `labels seated in the blocker grid: ${JSON.stringify(land.labels)}`,
      );
      assert.ok(land.nameline, "no words line under the plot");
      assert.ok(
        land.nameline.includes("Too crowded at their discs"),
        `the words line does not carry the crowded clause: ${land.nameline}`,
      );
      assert.ok(
        land.nameline.includes("at 28.0% and $120.00"),
        `candidate A is not named with its figures: ${land.nameline}`,
      );
      assert.ok(
        land.nameline.includes("at 26.0% and $110.00"),
        `candidate B is not named with its figures: ${land.nameline}`,
      );
    } finally {
      rmSync(scratch, { recursive: true, force: true });
    }
  },
);

/* The ladder budget. The rail rows of the mutated payload
 * are counted in the test the way the generator counts
 * them, then costed runs are moved onto the rail until the
 * rail carries the target count. At 14 rows the landscape
 * ladder spends 154px of its 170px rows area and takes no
 * slack; at 15 it spends 176px and takes 6px of slack from
 * the plot. At 19 it outgrows the allotment and the 40px of
 * slack together and the build fails rather than cut the
 * ladder. */
function railCountOf(payload) {
  return nonSliceOf(payload).filter(
    (r) => !(r.total_cost_usd !== null && r.total_cost_usd > 0),
  ).length;
}
function moveToRail(payload, target) {
  let count = railCountOf(payload);
  const rankedCosted = nonSliceOf(payload)
    .filter((r) => r.ranking_eligible && (r.total_cost_usd ?? 0) > 0)
    .sort((a, b) => a.total_cost_usd - b.total_cost_usd);
  /* Cheapest first, and never the priciest (the plot's
   * subject must stay on the plot). */
  for (const r of rankedCosted.slice(0, -1)) {
    if (count >= target) break;
    r.total_cost_usd = null;
    count += 1;
  }
  assert.equal(count, target, "the mutation could not seat the rail count");
}

test(
  "the ladder at 14 rail rows spends inside its rows area and takes no slack",
  { timeout: 300000 },
  () => {
    const { scratch, board } = scratchBoard((payload) =>
      moveToRail(payload, 14),
    );
    try {
      const run = runGenOg(board, { PEIRA_OG_PROBE: "1" });
      assert.equal(run.status, 0, run.out);
      assert.match(
        run.out,
        /ladder budget \(landscape\): spent 154px of the 170px rows area on 14 rail rows in 2 columns, slack used 0px/,
      );
      assert.ok(run.probe, "the probe geometry was not written");
      assert.equal(run.probe.land.ladder.length, 14);
      assert.deepEqual(run.probe.land.ladderBudget, {
        rows: 14,
        perColumn: 7,
        spent: 154,
        allot: 170,
        slackUsed: 0,
      });
      assert.deepEqual(run.probe.port.ladderBudget, {
        rows: 14,
        perColumn: 14,
        spent: 364,
        allot: 286,
        slackUsed: 78,
      });
    } finally {
      rmSync(scratch, { recursive: true, force: true });
    }
  },
);

test(
  "the ladder at 15 rail rows takes slack from the plot and still prints",
  { timeout: 300000 },
  () => {
    const { scratch, board } = scratchBoard((payload) =>
      moveToRail(payload, 15),
    );
    try {
      const run = runGenOg(board, { PEIRA_OG_PROBE: "1" });
      assert.equal(run.status, 0, run.out);
      assert.match(
        run.out,
        /ladder budget \(landscape\): spent 176px of the 170px rows area on 15 rail rows in 2 columns, slack used 6px/,
      );
      assert.ok(run.probe, "the probe geometry was not written");
      assert.equal(run.probe.land.ladder.length, 15);
      assert.deepEqual(run.probe.land.ladderBudget, {
        rows: 15,
        perColumn: 8,
        spent: 176,
        allot: 170,
        slackUsed: 6,
      });
      assert.deepEqual(run.probe.port.ladderBudget, {
        rows: 15,
        perColumn: 15,
        spent: 390,
        allot: 286,
        slackUsed: 104,
      });
    } finally {
      rmSync(scratch, { recursive: true, force: true });
    }
  },
);

test(
  "the ladder past its allotment and slack fails the build rather than print cut",
  { timeout: 300000 },
  () => {
    const { scratch, board } = scratchBoard((payload) =>
      moveToRail(payload, 19),
    );
    try {
      const run = runGenOg(board);
      assert.equal(run.status, 1, run.out);
      assert.match(run.out, /past the 170px allotted and the 40px of slack/);
    } finally {
      rmSync(scratch, { recursive: true, force: true });
    }
  },
);

/* The ceiling case (red team, PR 527). A flagged plotted
 * result sitting exactly at the axis ceiling escapes the
 * off-scale discipline. It is drawn, riding the plot's top
 * edge, and the words under the plot are its naming surface.
 * There its figure must travel with its decomposition, and
 * a ceiling point whose decomposition does not derive fails
 * the build closed. The mutation seats ling-3.1-flash at
 * exactly the frozen fixture's 30 percent ceiling, its
 * family records re-seated so the counted flips sum to the
 * printed rate. */
function seatFlips(row, flips, malformed) {
  Object.values(row.detail.families).forEach((f, i) => {
    f.n_flipped = i === 0 ? flips : 0;
    f.flip_direction["to-malformed"] = i === 0 ? malformed : 0;
  });
}

test(
  "a flagged point exactly at the axis ceiling is named in words with its decomposition",
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
      seatFlips(row, 1339, 800);
    }, fixture);
    try {
      const run = runGenOg(board, { PEIRA_OG_PROBE: "1" });
      assert.equal(run.status, 0, run.out);
      const nameline = run.probe.land.nameline;
      assert.ok(nameline, "no words line under the plot");
      assert.ok(
        nameline.includes("ling-3.1-flash") &&
          nameline.includes("at 30.0%"),
        `the ceiling point is not named with its rate: ${nameline}`,
      );
      assert.ok(
        nameline.includes("genuine flip rate") &&
          nameline.includes("of counted flips to malformed output"),
        `the ceiling point's figure travels without its decomposition: ${nameline}`,
      );
    } finally {
      rmSync(scratch, { recursive: true, force: true });
    }
  },
);

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
