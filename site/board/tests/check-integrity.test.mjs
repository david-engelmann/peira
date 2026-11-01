/* The integrity check's re-run disclosure port, guarded end
 * to end. Check 12e re-derives the Method disclosure from the
 * payload and compares it against the rendered page, and the
 * derivation has to replicate the board's own order exactly:
 * board groups first (full suite, then slices, then flagged),
 * flagged results in attack success order. The publish dress
 * rehearsal put a same-day group on the board whose attack
 * success order differs from its payload order, and the port
 * written in payload order failed the build on a page that
 * was rendering the reviewed behavior. This test builds the
 * whole board in a scratch tree on a payload carrying exactly
 * that shape, three records on one day, one full suite result
 * and two flagged results whose attack success order reverses
 * their payload order, and holds two things: the build passes
 * end to end, integrity check included, and the rendered
 * sentence names the flagged pair in attack success order.
 * With the port in payload order the build fails at 12e and
 * this test fails with it.
 *
 * The build is the slow way to guard a sentence, and it is
 * the only honest one: 12e reads the rendered page, so
 * nothing short of a build puts the two derivations face to
 * face. The scratch tree stays in place when the test fails,
 * so the failing build can be inspected where it stopped. */

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import {
  cpSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const boardRoot = path.dirname(path.dirname(fileURLToPath(import.meta.url)));

const SKIP = new Set(["node_modules", ".next", "out", ".og"]);

function scratchBoard(mutate) {
  /* The scratch tree is a sibling of the board, not a child:
   * a tree cannot be copied into its own subdirectory. */
  const scratch = mkdtempSync(
    path.join(path.dirname(boardRoot), ".test-tmp-check-integrity-"),
  );
  cpSync(boardRoot, scratch, {
    recursive: true,
    filter: (src) => {
      const rel = path.relative(boardRoot, src);
      if (rel === "") return true;
      const top = rel.split(path.sep)[0];
      if (SKIP.has(top)) return false;
      if (top.startsWith(".test-tmp-")) return false;
      return true;
    },
  });
  symlinkSync(
    path.join(boardRoot, "node_modules"),
    path.join(scratch, "node_modules"),
    "dir",
  );
  const payloadFile = path.join(scratch, "data", "payload.json");
  const payload = JSON.parse(readFileSync(payloadFile, "utf8"));
  mutate(payload);
  writeFileSync(payloadFile, JSON.stringify(payload, null, 1));
  return scratch;
}

test(
  "the build passes with a same-day re-run group whose attack success order reverses its payload order, and the page names the pair in attack success order",
  { timeout: 1500000 },
  () => {
    const scratch = scratchBoard((payload) => {
      const rows = new Map(
        [...payload.ranked, ...payload.unranked].map((r) => [r.run_id, r]),
      );
      /* The injected group stands alone, so the rendered
       * paragraph is the group's own sentence whatever
       * records the installed payload already carries. */
      for (const r of rows.values()) delete r.rerun;
      const day = "2026-10-31";
      rows.get("openai-terra56-v2-trial").rerun = {
        date: day,
        parent_run_id: "11111111111111111111111111111111",
      };
      /* The flagged pair. In payload order ling-3.0-flash
       * stands before ling-3.0-flash-vl; in attack success
       * order the vl result (0.2089) stands before the flash
       * result (0.2284), and the board renders flagged
       * results in attack success order. */
      rows.get("or-ling-v2-trial").rerun = {
        date: day,
        parent_run_id: "22222222222222222222222222222222",
      };
      rows.get("or-lingvl-v2-trial").rerun = {
        date: day,
        parent_run_id: "33333333333333333333333333333333",
      };
    });
    let ok = false;
    try {
      const res = spawnSync("npm", ["run", "build"], {
        cwd: scratch,
        encoding: "utf8",
        timeout: 1440000,
      });
      const out = `${res.stdout ?? ""}\n${res.stderr ?? ""}`;
      assert.equal(
        res.status,
        0,
        `the scratch build failed\n${out.slice(-4000)}`,
      );
      assert.match(out, /integrity check passed/);
      const html = readFileSync(path.join(scratch, "out", "index.html"), "utf8");
      const text = html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");
      assert.ok(
        text.includes(
          "The gpt-5.6-terra, ling-3.0-flash-vl and ling-3.0-flash results were re-run on 31 October 2026.",
        ),
        "the rendered disclosure does not name the group in board order",
      );
      assert.ok(
        !text.includes(
          "The gpt-5.6-terra, ling-3.0-flash and ling-3.0-flash-vl results were re-run",
        ),
        "the rendered disclosure names the flagged pair in payload order",
      );
      ok = true;
    } finally {
      if (ok) rmSync(scratch, { recursive: true, force: true });
    }
  },
);
