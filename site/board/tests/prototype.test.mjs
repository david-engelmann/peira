/**
 * Prototype fact tests. These recompute the figures the
 * redesign states, straight from data/payload.json with no
 * shared code, so a derivation drift in the prototype's data
 * layer fails here rather than printing on the page.
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const payload = JSON.parse(
  readFileSync(join(here, "..", "data", "payload.json"), "utf8"),
);
const rows = [...payload.ranked, ...payload.unranked];

function detailOf(row) {
  return row.detail && typeof row.detail === "object" ? row.detail : {};
}
function familyRecords(row) {
  const raw = detailOf(row).families;
  if (Array.isArray(raw)) return raw;
  if (raw && typeof raw === "object") return Object.values(raw);
  return [];
}
function isCount(x) {
  return typeof x === "number" && Number.isInteger(x) && x >= 0;
}
function decomp(row) {
  const fams = familyRecords(row);
  if (fams.length === 0) return null;
  let flips = 0;
  let malformed = 0;
  for (const fam of fams) {
    const fd =
      fam.flip_direction && typeof fam.flip_direction === "object"
        ? fam.flip_direction
        : {};
    const tm = fd["to-malformed"];
    if (!isCount(fam.n_flipped) || !isCount(tm)) return null;
    flips += fam.n_flipped;
    malformed += tm;
  }
  return { flips, malformed };
}
const fullCases = Math.max(...payload.ranked.map((r) => r.n_cases));
const full = payload.ranked
  .filter((r) => r.n_cases === fullCases)
  .sort((a, b) => a.asr_conditional - b.asr_conditional);
const slices = payload.ranked.filter((r) => r.n_cases < fullCases);
const flagged = payload.unranked;

test("the payload holds the published board's shape", () => {
  assert.equal(rows.length, 52);
  assert.equal(full.length, 41);
  assert.equal(slices.length, 6);
  assert.equal(flagged.length, 5);
  assert.equal(full[0].n_cases, 4701);
});

test("the leader is the cursor harness grok run", () => {
  const leader = full[0];
  assert.match(leader.display_name, /grok/i);
  assert.ok(Math.abs(leader.asr_conditional - 0.0891) < 0.0006);
  const d = decomp(leader);
  assert.equal(d.flips, 403);
  assert.equal(d.malformed, 0);
  assert.equal(leader.unanswered_cases, 1);
});

test("mercury carries its malformed decomposition", () => {
  const mercury = flagged.reduce((a, b) =>
    b.asr_conditional > a.asr_conditional ? b : a,
  );
  const d = decomp(mercury);
  assert.ok(Math.abs(d.malformed / d.flips - 0.856) < 0.002);
  const genuine = (d.flips - d.malformed) / mercury.n_eligible;
  assert.ok(Math.abs(genuine - 0.075) < 0.002);
  assert.ok(Math.abs(mercury.malformed_rate - 0.608) < 0.002);
});

test("the split pools as the derivation record states", () => {
  const pool = (list) => {
    let flips = 0;
    let malformed = 0;
    for (const row of list) {
      const d = decomp(row);
      assert.notEqual(d, null);
      flips += d.flips;
      malformed += d.malformed;
    }
    return { flips, malformed };
  };
  const ranked = pool(full);
  assert.equal(ranked.flips, 31944);
  assert.equal(ranked.malformed, 400);
  const flaggedPool = pool(flagged);
  assert.equal(flaggedPool.flips, 5757);
  assert.equal(flaggedPool.malformed, 3465);
});

test("exactly one model stands on two wires", () => {
  const byName = new Map();
  for (const row of full) {
    byName.set(row.display_name, [...(byName.get(row.display_name) ?? []), row]);
  }
  const pairs = [...byName.values()].filter((l) => l.length === 2);
  assert.equal(pairs.length, 1);
  const [a, b] = pairs[0];
  assert.notEqual(a.wire, b.wire);
  const gap = Math.abs(a.asr_conditional - b.asr_conditional);
  assert.ok(Math.abs(gap - 0.016) < 0.002);
  const costs = [a.total_cost_usd, b.total_cost_usd].sort((x, y) => x - y);
  assert.ok(Math.abs(costs[0] - 0.2922) < 0.001);
  assert.ok(Math.abs(costs[1] - 0.7537) < 0.001);
});

test("price carries no useful relationship with robustness", () => {
  const priced = full.filter((r) => r.total_cost_usd !== null && r.total_cost_usd > 0);
  assert.equal(priced.length, 31);
  const ranks = (vs) => {
    const order = vs.map((v, i) => ({ v, i })).sort((a, b) => a.v - b.v);
    const out = new Array(vs.length);
    let i = 0;
    while (i < order.length) {
      let j = i;
      while (j + 1 < order.length && order[j + 1].v === order[i].v) j += 1;
      const avg = (i + j) / 2 + 1;
      for (let k = i; k <= j; k += 1) out[order[k].i] = avg;
      i = j + 1;
    }
    return out;
  };
  const rx = ranks(priced.map((r) => r.total_cost_usd));
  const ry = ranks(priced.map((r) => r.asr_conditional));
  const n = priced.length;
  const mx = rx.reduce((a, b) => a + b, 0) / n;
  const my = ry.reduce((a, b) => a + b, 0) / n;
  let cov = 0;
  let vx = 0;
  let vy = 0;
  for (let i = 0; i < n; i += 1) {
    cov += (rx[i] - mx) * (ry[i] - my);
    vx += (rx[i] - mx) ** 2;
    vy += (ry[i] - my) ** 2;
  }
  const rho = cov / Math.sqrt(vx * vy);
  assert.ok(Math.abs(rho - -0.15) < 0.01, `spearman ${rho}`);
});

test("the guards' counted flips hold no reversal", () => {
  const totals = {};
  let flips = 0;
  for (const row of slices) {
    for (const fam of familyRecords(row)) {
      if (isCount(fam.n_flipped)) flips += fam.n_flipped;
      const fd = fam.flip_direction ?? {};
      for (const [key, value] of Object.entries(fd)) {
        if (isCount(value)) totals[key] = (totals[key] ?? 0) + value;
      }
    }
  }
  assert.equal(flips, 121);
  assert.equal(totals["approve-to-deny"] ?? 0, 0);
  assert.equal(totals["deny-to-approve"] ?? 0, 0);
  assert.equal(totals["to-abstain"], 62);
  assert.equal(totals["other"], 59);
  assert.ok(slices.every((r) => r.benign_accuracy === 1));
});

test("the hero range derives from the ranked rows", () => {
  const asrs = full.map((r) => r.asr_conditional);
  assert.ok(Math.abs(Math.min(...asrs) - 0.0891) < 0.0006);
  assert.ok(Math.abs(Math.max(...asrs) - 0.3378) < 0.0006);
});

/**
 * Design law tests for the Maidan language rebuild. These
 * read the board's own sources and assert the law the
 * stylesheet and components carry, the way Maidan's UI specs
 * assert its design law. They are source level checks. They
 * do not render the page, and they do not stand in for a
 * rendered pass at any width.
 */

const css = readFileSync(join(here, "..", "app", "globals.css"), "utf8");
const read = (rel) => readFileSync(join(here, "..", rel), "utf8");

test("the page is numbered scenes with mono eyebrows", () => {
  const scenes = [
    ["components/Headline.tsx", "01", "Results"],
    ["components/Explorer.tsx", "02", "Explorer"],
    ["components/Findings.tsx", "03", "Findings"],
    ["components/MethodStub.tsx", "04", "Method"],
  ];
  for (const [file, num, name] of scenes) {
    const src = read(file);
    assert.match(src, /className="[^"]*scene/, `${file} carries the scene class`);
    assert.ok(
      src.includes(`<span className="eno">${num}</span> ${name}`),
      `${file} opens with eyebrow ${num} ${name}`,
    );
  }
  assert.match(css, /\.eyebrow \.eno \{ color: var\(--accent\); \}/);
  assert.match(css, /\.scene \{[^}]*border-top: 1px solid var\(--line\)/);
});

test("the top bar frosts on scroll in the landing pattern", () => {
  const bar = read("components/TopBar.tsx");
  assert.match(bar, /window\.scrollY > 8/);
  assert.match(css, /\.masthead \{[^}]*position: sticky/);
  assert.match(css, /\.masthead\.scrolled \{[^}]*backdrop-filter: blur\(24px\) saturate\(1\.8\)/);
  assert.match(css, /section\[id\] \{ scroll-margin-top: 84px; \}/);
});

test("display type runs on fluid clamps at tight tracking", () => {
  assert.match(css, /\.hero h1 \{[^}]*font-size: clamp\(3rem, 7\.5vw, 5\.25rem\)/);
  assert.match(css, /\.hero h1 \{[^}]*letter-spacing: -0\.055em/);
  assert.match(css, /\.sechead h2 \{[^}]*font-size: clamp\(2\.5rem, 5\.2vw, 4\.25rem\)/);
  assert.match(css, /\.sechead h2 \{[^}]*line-height: 0\.98/);
});

test("the chart is the explorer default so the white disc stands first", () => {
  const explorer = read("components/Explorer.tsx");
  const defaults = explorer.slice(
    explorer.indexOf("const DEFAULTS"),
    explorer.indexOf("};", explorer.indexOf("const DEFAULTS")),
  );
  assert.match(defaults, /mode: "chart"/);
  assert.match(css, /\.disc\.subject \{ opacity: 1; \}/);
  assert.match(css, /\.disc\.field \{ opacity: 0\.5; \}/);
  // The board leader records no per-call cost and stands in
  // the chart's rail, so the opening selection prefers the
  // best priced full suite result, and the chart falls back
  // to its best plotted disc when the selection is not one.
  const leader = full[0];
  assert.ok(leader.total_cost_usd === 0 || leader.total_cost_usd === null);
  assert.match(explorer, /r\.costValue !== null && r\.costValue > 0/);
  assert.match(explorer, /const subjectId = /);
});

test("flagged state is a word next to the name, not only a color", () => {
  const explorer = read("components/Explorer.tsx");
  const hits = explorer.match(/Flagged · not ranked/g) ?? [];
  assert.ok(hits.length >= 2, "ladder and families heads both carry the word");
  assert.match(css, /\.xstate \{ color: var\(--amber\)/);
});

test("the phone law is encoded in the stylesheet", () => {
  assert.match(css, /@media \(pointer: coarse\) \{[^}]*\.segbtn[^{]*\{ min-height: 44px; \}/s);
  assert.match(css, /\.stack-num \{[^}]*font-size: clamp\(44px, 10vw, 64px\)/);
  assert.match(css, /\.inbar-fig \{[^}]*font-size: clamp\(24px, 6vw, 30px\)/);
  assert.match(css, /env\(safe-area-inset-bottom\)/);
  assert.match(css, /body \{[^}]*overflow-x: clip/);
  assert.match(css, /@media \(max-width: 760px\) \{[\s\S]*?\.xrow-head \{[^}]*min-height: 56px/);
});

test("the rank grid gives every header and the pin their own columns", () => {
  const explorer = read("components/Explorer.tsx");
  // The header carries an empty mark cell, so each sort label
  // stands over its own figure column rather than one column
  // to the left of it.
  assert.ok(
    explorer.includes('<span className="xh mark"'),
    "the header carries the mark cell",
  );
  assert.match(
    css,
    /\.xhead, \.xrow-head \{\s*display: grid;\s*grid-template-columns: 40px 30px minmax\(132px, 1\.25fr\) minmax\(76px, 1fr\) 128px 70px 96px 116px 150px 68px;/,
  );
  // The sort buttons take the header size from the .xh rule.
  // A font shorthand on the button once reset them to body
  // size and pushed the labels over their neighbours.
  assert.match(css, /button\.xh \{[^}]*font-family: inherit/);
  assert.ok(!/button\.xh \{[^}]*font: inherit/.test(css));
  assert.match(css, /\.xh\.fig \{[^}]*white-space: nowrap/);
  // The pin stands in the grid's last column, in the row
  // head after the cost figure, never over it.
  assert.ok(!/\.pinbtn \{[^}]*position: absolute/.test(css));
  const costAt = explorer.indexOf('className="xfig cost rn"');
  const pinAt = explorer.indexOf("pinbtn", costAt);
  assert.ok(costAt >= 0 && pinAt > costAt && pinAt - costAt < 900);
  assert.equal(explorer.match(/className=\{`pinbtn/g)?.length, 1);
  // Below the collapse width the benign and calibration
  // columns leave the grid instead of squeezing.
  assert.match(css, /@media \(max-width: 1080px\) \{[\s\S]*?\.xh:nth-child\(6\), \.xh:nth-child\(8\) \{ display: none; \}/);
});

test("the chart discs carry their vendor marks at the field dim", () => {
  const explorer = read("components/Explorer.tsx");
  // The highlight filter dims a disc. It does not strip the
  // disc's mark and leave a bare circle or a letter behind.
  assert.ok(!explorer.includes("on && row.mark.kind"));
  assert.ok(
    explorer.includes('row.mark.kind === "logo" && row.mark.slug ? ('),
    "a logo disc renders the sprite mark unconditionally",
  );
  assert.match(css, /\.disc\.field \{ opacity: 0\.5; \}/);
});

test("the mercury split labels name their bases on both surfaces", () => {
  const headline = read("components/Headline.tsx");
  const findings = read("components/Findings.tsx");
  // The segment labels state shares of counted flips. The
  // genuine rate states its share of eligible cases. Side by
  // side the two numbers no longer read as one number wrong.
  assert.ok(
    headline.includes(
      "Genuine flips, ${fmtPct(mercury.genuineShare)} of counted flips",
    ),
  );
  assert.ok(headline.includes("of its eligible cases"));
  assert.ok(
    findings.includes(
      "Genuine flips, ${fmtPct(f.split.mercury.genuineShare)} of counted flips",
    ),
  );
  assert.ok(findings.includes("of its eligible cases"));
  assert.ok(!findings.includes("Genuine flip rate ${"));
  assert.ok(!headline.includes("genuine flip rate is"));
});

test("the explorer mercury surfaces state the genuine basis", () => {
  const explorer = read("components/Explorer.tsx");
  // The off-axis note, the flagged reading line, and the chart
  // chip each set the genuine figure beside a share of counted
  // flips. The genuine figure is a share of eligible cases,
  // and each surface now says so on the same line, so the two
  // numbers cannot be read on one basis.
  assert.ok(
    explorer.includes(
      "and its genuine flips are ${fmtPct(row.decomp.genuineRate)} of its eligible cases.",
    ),
  );
  assert.ok(
    explorer.includes(
      "genuine flips ${fmtPct(d.genuineRate)} of ${fmtInt(row.nEligible)} eligible cases",
    ),
  );
  assert.ok(
    explorer.includes(
      "{fmtPct(chipRow.decomp.genuineRate)} of eligible cases",
    ),
  );
  assert.ok(!explorer.includes("genuine flip rate is"));
  assert.ok(!explorer.includes("genuine flip rate ${"));
});

test("the flagged reading states both decomposition bases", () => {
  const inspector = read("lib/inspectorData.ts");
  // The flagged reason sets the genuine figure and the
  // malformed share in one sentence. The genuine figure is a
  // share of eligible cases and the malformed figure a share
  // of counted flips, and the sentence now names each basis
  // on its own figure, so the two numbers cannot be read on
  // one basis. The decomposition text, rendered by no
  // component today, carries the same two bases so no future
  // render inherits the ambiguity.
  assert.ok(
    inspector.includes(
      "Its genuine flips are ${fmtPct(decomp.genuineRate)} of its eligible cases, and ${fmtPct(decomp.malformedShare)} of its counted flips are to malformed output.",
    ),
  );
  assert.ok(
    inspector.includes(
      "genuine flips ${fmtPct(decomp.genuineRate)} of eligible cases, with ${fmtPct(decomp.malformedShare)} of counted flips to malformed output",
    ),
  );
  assert.ok(!inspector.includes("Genuine flip rate ${"));
  assert.ok(!inspector.includes("genuine flip rate ${"));
});

test("recorded zero splits by how the run was measured", () => {
  const zeroes = rows.filter((r) => r.total_cost_usd === 0);
  assert.equal(zeroes.length, 7);
  // Exactly one recorded zero is a harness run, the leader.
  const harness = zeroes.filter((r) => r.adapter_name === "cursor-harness");
  assert.equal(harness.length, 1);
  assert.match(harness[0].display_name, /grok/i);
  // The other six are locally served adapters.
  assert.deepEqual(
    zeroes
      .filter((r) => r.adapter_name !== "cursor-harness")
      .map((r) => r.adapter_name)
      .sort(),
    ["gliner-decide", "kev", "kev", "laya", "laya", "semif"],
  );
  // Nine rows carry no recorded cost. Every row carries the
  // field, so absence and null never split into two classes.
  const unrecorded = rows.filter((r) => r.total_cost_usd === null);
  assert.equal(unrecorded.length, 9);
  assert.ok(rows.every((r) => "total_cost_usd" in r));
});

test("a harness run never renders as a dollar figure", () => {
  const payloadLib = read("lib/payload.ts");
  const cards = read("lib/cards.ts");
  const inspector = read("lib/inspectorData.ts");
  // The classification splits recorded zero by the adapter,
  // keyed where the payload layer keeps the harness set.
  assert.ok(payloadLib.includes('"cursor-harness"'));
  assert.ok(payloadLib.includes("export function isHarnessRow"));
  assert.match(cards, /isHarnessRow\(row\)/);
  assert.match(cards, /kind: "harness"/);
  // No derivation turns a recorded zero into a dollar figure,
  // and each unpriced state prints as its own words.
  assert.ok(!inspector.includes("fmtUsd(0)"));
  assert.ok(inspector.includes('"Cursor plan"'));
  assert.ok(inspector.includes('"No API cost"'));
  assert.ok(inspector.includes('"No cost recorded"'));
  // The reading carries the full harness sentence, keyed by
  // the wire the payload records for the run. The sentence
  // states the billing truth, that the run drew on a paid
  // plan, so no surface calls the run chargeless.
  assert.ok(
    inspector.includes(
      "The run drew on a paid Cursor plan, so the cost is real and not metered per run.",
    ),
  );
  assert.ok(inspector.includes('"measured through the Cursor agent harness"'));
});

test("no source claims a run was chargeless", () => {
  // The chargeless wording is banned from every user-visible
  // source, comments included, so it cannot creep back in as
  // a label, a note, or a gloss. The same scan bans the em
  // dash from those sources outright, the copy bar rule the
  // flagged rank glyph broke until the fix pass on PR 536.
  const files = [];
  const walk = (dir) => {
    for (const entry of readdirSync(join(here, "..", dir), {
      withFileTypes: true,
    })) {
      const rel = `${dir}/${entry.name}`;
      if (entry.isDirectory()) walk(rel);
      else if (/\.(ts|tsx)$/.test(entry.name)) files.push(rel);
    }
  };
  for (const root of ["lib", "components", "app"]) walk(root);
  assert.ok(files.length > 0);
  for (const rel of files) {
    const src = read(rel);
    assert.ok(!/no per-run charge/i.test(src), `${rel} claims no per-run charge`);
    assert.ok(
      !/no per-run API charge/i.test(src),
      `${rel} claims no per-run API charge`,
    );
    assert.ok(!src.includes("\u2014"), `${rel} carries an em dash`);
  }
});

test("the harness rail group states the paid plan truth", () => {
  const explorer = read("components/Explorer.tsx");
  // The harness stands in the rail under its own heading,
  // apart from the local runs it used to share a group with.
  assert.ok(explorer.includes('head: "Measured through a harness"'));
  assert.ok(explorer.includes('head: "No API cost"'));
  assert.ok(
    explorer.includes(
      "measured through the Cursor agent harness on a paid plan",
    ),
  );
  assert.ok(
    explorer.includes(
      "Its cost is not metered per run, so it stands off the axis rather than at zero.",
    ),
  );
  // The rail splits its groups on the cost state kind the
  // data layer derives, not on the rendered words.
  assert.ok(explorer.includes('r.costKind === "harness"'));
  assert.ok(explorer.includes('r.costKind === "local"'));
});

test("the chart rail and the cost filter keep the cost states apart", () => {
  const explorer = read("components/Explorer.tsx");
  // The filter no longer lumps a recorded zero with no record.
  assert.ok(!explorer.includes("c === null || c === 0"));
  assert.ok(explorer.includes('label: "No recorded price", test: (c) => c === 0'));
  assert.ok(explorer.includes('label: "No cost recorded", test: (c) => c === null'));
  // The rail heads its groups with their own words.
  assert.ok(explorer.includes('head: "Measured through a harness"'));
  assert.ok(explorer.includes('head: "No recorded cost"'));
  // The comparison subtracts prices only, so an unpriced side
  // can never print as a dollar difference from zero.
  assert.ok(explorer.includes("sel.costValue > 0"));
  assert.ok(explorer.includes("pin.costValue > 0"));
});

test("the method costs passage states the harness case", () => {
  const method = read("components/MethodStub.tsx");
  // The passage states the billing truth, that a harness run
  // is billed through the plan that carries the harness and
  // its cost is real, and that the board names the plan basis
  // instead of printing a figure for it.
  assert.ok(method.includes("the plan that carries the harness"));
  assert.ok(method.includes("Its cost is real and not"));
  assert.ok(method.includes("metered per run, and the board names the plan basis"));
  assert.ok(method.includes("never as a figure"));
  assert.ok(method.includes("is always a recorded price"));
  assert.ok(!method.includes("0.00"));
});

test("the motion budget holds and reduced motion snaps the bar", () => {
  // The repo form of the motion pin, settled at the port.
  // The motion law in DESIGN.md names the three duration
  // tokens and their values, and caps every duration on
  // the board at 280ms. The pin reads the tokens from
  // :root and resolves every transition declaration in
  // the sheet against them, so a figure past the cap
  // fails here wherever it stands, in a token's value or
  // in a declaration. The literal extraction this pin
  // replaces read its only figure from the masthead's
  // hardcoded 300ms and went blind the day the F7 fix
  // spent the entrance token there.
  const root = css.slice(
    css.indexOf(":root"),
    css.indexOf("}", css.indexOf(":root")),
  );
  const tokens = {};
  for (const m of root.matchAll(/--(dur-[a-z]+):\s*(\d+)ms/g)) {
    tokens[m[1]] = Number(m[2]);
  }
  assert.deepEqual(tokens, {
    "dur-micro": 120,
    "dur-state": 200,
    "dur-enter": 280,
  });
  const cap = 280;
  const declarations = [
    ...css.matchAll(/transition(?:-duration)?:\s*([^;}]+)/g),
  ];
  assert.ok(declarations.length > 0);
  let resolved = 0;
  for (const [, decl] of declarations) {
    for (const m of decl.matchAll(
      /var\(--(dur-[a-z]+)\)|(\d+(?:\.\d+)?)(ms|s)\b/g,
    )) {
      const value = m[1]
        ? tokens[m[1]]
        : Number(m[2]) * (m[3] === "s" ? 1000 : 1);
      assert.ok(
        value !== undefined,
        `a transition spends the undefined duration token ${m[0]}`,
      );
      resolved += 1;
      assert.ok(
        value <= cap,
        `a transition resolves to ${value}ms, over the ${cap}ms cap`,
      );
    }
  }
  assert.ok(resolved > 0);
  const reduce = css.slice(css.indexOf("@media (prefers-reduced-motion: reduce)"));
  assert.match(reduce, /\.masthead \{ transition: none; \}/);
  assert.match(reduce, /\.disc \{ transition: none; \}/);
});

test("the chart ceiling derives from the results that seat on the plot", () => {
  // The frame is set by the highest rate among the ranked
  // results that stand as points, a recorded cost above
  // zero, rounded up to the next five percent step. The
  // ranked range's own top (von, no recorded price) stands
  // in the rail and never enters the derivation, the
  // flagged range never enters it either, and mercury
  // stands past the ceiling it derives.
  const seated = full.filter(
    (r) => r.total_cost_usd !== null && r.total_cost_usd > 0,
  );
  const plottedMax = Math.max(...seated.map((r) => r.asr_conditional));
  const ceiling = Math.max(
    0.1,
    Math.round(Math.ceil((plottedMax - 1e-9) / 0.05) * 5) / 100,
  );
  assert.equal(ceiling, 0.3);
  const rankedMax = Math.max(...full.map((r) => r.asr_conditional));
  assert.ok(rankedMax > ceiling);
  assert.ok(plottedMax < rankedMax);
  const mercury = flagged.reduce((a, b) =>
    a.asr_conditional > b.asr_conditional ? a : b,
  );
  assert.ok(mercury.asr_conditional > ceiling);
  // Seating agreement. Every point the chart seats, of any
  // population, sits inside the frame but for mercury,
  // which the off-scale note carries.
  const seatedAny = [...full, ...slices, ...flagged].filter(
    (r) =>
      r.total_cost_usd !== null &&
      r.total_cost_usd > 0 &&
      r.run_id !== mercury.run_id,
  );
  assert.ok(
    Math.max(...seatedAny.map((r) => r.asr_conditional)) <= ceiling,
  );
  const explorer = read("components/Explorer.tsx");
  assert.ok(explorer.includes("plottedCeiling"));
  assert.ok(explorer.includes("r.costValue !== null && r.costValue > 0"));
  assert.ok(explorer.includes("/ 0.05"));
  assert.ok(!explorer.includes("data.axisMax"));
});

test("the chart names the selection when the disc is not theirs", () => {
  const explorer = read("components/Explorer.tsx");
  // A selection the plot cannot carry still gets named,
  // with where it stands, beside the disc that stands in.
  assert.ok(explorer.includes("chart-selstand"));
  assert.ok(explorer.includes("The white disc singles out"));
  assert.ok(
    explorer.includes(
      "was measured through a harness and stands in the rail below",
    ),
  );
  assert.ok(
    explorer.includes("has no recorded cost and stands in the rail below"),
  );
  assert.ok(
    explorer.includes(
      "is a guard result, and guard results read in the rank and families modes",
    ),
  );
  assert.ok(explorer.includes("is hidden by the current filters"));
  assert.match(css, /\.chart-selstand \{/);
});

test("the plot pads its right edge and the discs read at floor size", () => {
  const explorer = read("components/Explorer.tsx");
  assert.ok(explorer.includes("const padR = 30;"));
  // The field disc floor and the ground separation stroke,
  // with the subject still the one large white disc and the
  // field dim untouched.
  assert.ok(explorer.includes("r={subject ? 17 : 15}"));
  assert.ok(explorer.includes('"#4a5763"'));
  assert.ok(explorer.includes('"#05070a"'));
  assert.match(css, /\.disc-letter \{ fill: #f4f7fa; font-size: 11\.5px;/);
  assert.match(css, /\.disc\.field \{ opacity: 0\.5; \}/);
  // The sync list fades at its foot instead of slicing a row.
  assert.match(
    css,
    /\.chartsync \{[\s\S]*?mask-image: linear-gradient\(to bottom, #000 calc\(100% - 28px\), transparent\);/,
  );
  assert.match(css, /\.chartsync ul \{[^}]*padding: 0 0 12px;/);
});

test("the rank header sticks and the interval axis fits the ranked rows", () => {
  assert.match(css, /\.xhead \{[^}]*position: sticky; top: 61px;/);
  // The ranked interval tops set the frame, at the next two
  // and a half percent step. The flagged range stands past
  // it, which is why flagged rows keep the shared axis.
  const rankedTop = Math.max(...payload.ranked.map((r) => r.asr_ci95[1]));
  const axis = Math.max(
    0.3,
    Math.round(Math.ceil((rankedTop - 1e-9) / 0.025) * 25) / 1000,
  );
  assert.equal(axis, 0.375);
  const flaggedTop = Math.max(...flagged.map((r) => r.asr_ci95[1]));
  assert.ok(flaggedTop > axis);
  const data = read("lib/explorerData.ts");
  assert.ok(data.includes("rankedIntervalAxisMax"));
  assert.ok(data.includes('d.kind === "flagged"'));
  const explorer = read("components/Explorer.tsx");
  assert.ok(explorer.includes("Interval on the ranked axis"));
  assert.ok(explorer.includes("held off the ranking · their"));
  assert.ok(explorer.includes("intervals stand on the shared axis"));
  assert.match(css, /\.xwhisker \{[^}]*height: 6px; background: var\(--ink-2\);/);
  assert.match(css, /\.xwhisker::before/);
});

test("the ranked interval cell prints its figures in full ink", () => {
  // The figures are the payload's own interval pair for
  // each ranked row, phrased as the readings phrase them.
  // Recompute the leader's pair from the payload and pin
  // the wording the cell must print.
  const pct = (v) => `${(Math.round(v * 1000) / 10).toFixed(1)}%`;
  const leader = full[0];
  assert.equal(
    `${pct(leader.asr_ci95[0])} to ${pct(leader.asr_ci95[1])}`,
    "8.1% to 9.8%",
  );
  for (const r of payload.ranked) {
    assert.ok(Array.isArray(r.asr_ci95) && r.asr_ci95.length === 2);
    assert.match(
      `${pct(r.asr_ci95[0])} to ${pct(r.asr_ci95[1])}`,
      /^\d+\.\d% to \d+\.\d%$/,
    );
  }
  const explorer = read("components/Explorer.tsx");
  // The cell prints the pair for ranked rows only, and the
  // fitted whisker for those rows is the one drawn bright.
  assert.ok(explorer.includes('className="xci"'));
  assert.ok(explorer.includes('row.kind !== "flagged" && row.ciText'));
  assert.ok(explorer.includes('? "" : " fitted"'));
  assert.match(css, /\.xwhisker\.fitted \{ background: var\(--ink\); \}/);
  assert.match(css, /\.xtrackline \{[^}]*position: relative;/);
});

test("names break at the slash and severity segments never split", () => {
  const explorer = read("components/Explorer.tsx");
  assert.ok(explorer.includes("function BreakName"));
  assert.ok(explorer.includes("<wbr />"));
  assert.ok(explorer.includes('className="sevseg"'));
  assert.match(css, /\.sevseg \{ white-space: nowrap; \}/);
});

test("the reading states the bases its figures rest on", () => {
  const explorer = read("components/Explorer.tsx");
  // The genuine-flips line carries its eligible total, the
  // calibration error its scale, and the latency its median
  // per attacked call, matching the payload's p50 field.
  assert.ok(
    explorer.includes("of ${fmtInt(row.nEligible)} eligible cases"),
  );
  assert.ok(explorer.includes("On a 0 to 1 scale"));
  assert.ok(explorer.includes("Median latency"));
  assert.ok(explorer.includes("Per attacked call"));
  // Every family record in the payload carries its own
  // eligible count, so the weakest-family denominator the
  // reading states is derived, never invented.
  let checked = 0;
  for (const row of rows) {
    for (const fam of familyRecords(row)) {
      assert.ok(
        isCount(fam.n_eligible),
        `${row.run_id} carries a family record without n_eligible`,
      );
      checked += 1;
    }
  }
  assert.ok(checked > 0);
  const inspector = read("lib/inspectorData.ts");
  assert.ok(inspector.includes("baseText"));
  assert.ok(inspector.includes("fam.nEligible"));
});

test("the families mode prints full names against a labelled scale", () => {
  const explorer = read("components/Explorer.tsx");
  assert.ok(explorer.includes("{fam.full}"));
  assert.ok(!explorer.includes("{fam.short}"));
  assert.ok(explorer.includes("Not measured"));
  assert.ok(explorer.includes("Overall attack success"));
  assert.ok(explorer.includes("[0, 0.25, 0.5, 0.75, 1]"));
  assert.match(
    css,
    /\.xfam-bar \{ display: grid; grid-template-columns: 172px 1fr 100px;/,
  );
  assert.match(css, /repeating-linear-gradient\(to right/);
});

test("the wire finding draws both intervals on one fitted window", () => {
  const luna = rows.filter((r) => r.display_name === "gpt-6-luna");
  assert.equal(luna.length, 2);
  const lo = Math.min(...luna.map((r) => r.asr_ci95[0]));
  const hi = Math.max(...luna.map((r) => r.asr_ci95[1]));
  const pad = (hi - lo) * 0.5;
  const winLo = Math.max(0, lo - pad);
  const winHi = hi + pad;
  // On the fitted window each interval spans a legible share
  // of the track, where the board axis left it a grey tick.
  for (const r of luna) {
    const share = (r.asr_ci95[1] - r.asr_ci95[0]) / (winHi - winLo);
    assert.ok(share > 0.2, `interval share ${share}`);
  }
  const findings = read("components/Findings.tsx");
  assert.ok(findings.includes("wireWin"));
  assert.ok(findings.includes("wiretrack-axis"));
  assert.ok(!findings.includes("axis.max"));
  assert.match(
    css,
    /\.wiretrack-line \.whisker \{[^}]*background: var\(--ink-2\);/,
  );
  assert.match(css, /\.wiretrack-line \.whisker::before/);
});

test("the findings split bars share one height and the card figure stands", () => {
  // One height system inside the findings. The taller
  // figured track stays the share card's own treatment.
  assert.match(
    css,
    /\.finding \.splitbar \.splitbar-track, \.finding \.splitbar\.figured \.splitbar-track \{ height: 36px;/,
  );
  assert.match(css, /\.splitbar\.figured \.splitbar-track \{ height: 48px;/);
});

test("the undecided case stands as a figure against the suite total", () => {
  const leader = full[0];
  assert.equal(leader.unanswered_cases, 1);
  assert.equal(leader.n_cases, 4701);
  const findings = read("components/Findings.tsx");
  assert.ok(findings.includes("leader-fig-num"));
  assert.ok(
    findings.includes(
      "{fmtInt(f.leader.unanswered)} of {fmtInt(f.leader.row.n_cases)}",
    ),
  );
  assert.ok(
    findings.includes("suite cases produced no answer on either call"),
  );
});

test("the footer carries the re-measurement note the method promises", () => {
  const reruns = rows.filter(
    (r) => r.rerun && typeof r.rerun.date === "string",
  );
  assert.equal(reruns.length, 16);
  const dates = reruns.map((r) => r.rerun.date).sort();
  assert.equal(dates[0], "2026-10-30");
  assert.equal(dates[dates.length - 1], "2026-11-01");
  const page = read("app/page.tsx");
  assert.ok(page.includes("Re-measurement note."));
  assert.ok(page.includes("r.rerun?.date"));
  assert.ok(page.includes("in place of the earlier run's"));
  const method = read("components/MethodStub.tsx");
  assert.ok(method.includes("recorded in the note at the foot of the page"));
});

test("the guards zero segment reads as measured, not missing", () => {
  const findings = read("components/Findings.tsx");
  assert.ok(findings.includes("flexGrow: f.guards.toAbstain"));
  assert.ok(findings.includes("flexGrow: f.guards.untyped"));
  assert.match(
    css,
    /\.anat-slot\.empty \{ border: 1px solid var\(--ink-3\);[^}]*flex: 0 0 148px;/,
  );
});

test("the detail card meets its keyboard contract", () => {
  const explorer = read("components/Explorer.tsx");
  // One dismissal path serves the close control and the
  // Escape key alike, so neither route can drift from the
  // other.
  assert.ok(explorer.includes("const dismissChip = useCallback("));
  assert.ok(explorer.includes('e.key !== "Escape"'));
  assert.ok(explorer.includes("dismissChip(fromCard || fromDisc)"));
  // The close control stands in the hover state and the
  // pinned state alike, never behind the pinned state
  // alone.
  assert.ok(!explorer.includes("{chipPinned && ("));
  const actions = explorer.slice(
    explorer.indexOf('className="chip-actions"'),
    explorer.indexOf('className="rail"'),
  );
  assert.ok(actions.includes("Dismiss"));
  assert.ok(actions.includes("dismissChip(e.detail === 0)"));
  // Keyboard focus raises the identical card. Every disc is
  // a focusable button standing in the tab order, focus
  // raises its card the way the pointer does, and Enter or
  // Space pins it the way a click does.
  assert.ok(explorer.includes("data-disc={row.runId}"));
  assert.ok(explorer.includes("tabIndex={0}"));
  assert.ok(explorer.includes('role="button"'));
  assert.ok(explorer.includes("focusReturnRef"));
  assert.ok(explorer.includes('e.key === "Enter" || e.key === " "'));
  // A keyboard dismissal hands focus back to the disc that
  // raised the card, and the focus ring reads on the disc
  // itself at the system's accent weight.
  assert.ok(explorer.includes('[data-disc="${id}"]'));
  assert.match(
    css,
    /\.disc:focus-visible \.disc-face \{ stroke: var\(--accent\); stroke-width: 2\.5; \}/,
  );
});

test("the rank sort buttons stand in the tab order", () => {
  const explorer = read("components/Explorer.tsx");
  // No control on the board carries the negative tab index
  // that once kept the sort heads out of the tab order. The
  // native Sort select stands beside them, not instead of
  // them, and the heads keep their sort wiring.
  assert.ok(!explorer.includes("tabIndex={-1}"));
  const head = explorer.slice(
    explorer.indexOf("className={`xh fig"),
    explorer.indexOf('className="xh pin"'),
  );
  assert.ok(head.includes("onClick={() => onSort(key)}"));
});

test("selected rows carry the outline at the system's weight", () => {
  // The focus ring stands at 2px in the accent. A selected
  // row reads at the same weight, on the sync list and on
  // the chart rail alike, where the rail once carried no
  // selected state of its own.
  assert.match(css, /:focus-visible \{ outline: 2px solid var\(--accent\);/);
  assert.match(css, /\.sync-row\.sel \{ outline: 2px solid var\(--accent\); \}/);
  assert.match(
    css,
    /\.rail-row\.sel \{ outline: 2px solid var\(--accent\); outline-offset: -2px; \}/,
  );
  const explorer = read("components/Explorer.tsx");
  assert.ok(
    explorer.includes('rail-row${state.sel === row.runId ? " sel" : ""}'),
  );
});

test("the tint chip's mark clears its contrast floor for every family", () => {
  // Recomputed from lib/vendor-data.json with no shared
  // code. The chip's ground is the family color at a 16
  // percent color-mix over the panel. Its mark is the
  // family color lightened toward white by the smallest
  // five percent step that clears the Typography floor,
  // 4.5 to 1, which DESIGN.md binds on the chip's mark
  // without splitting by kind. A family color re-sampled
  // in the table fails here until its derived mark clears
  // again, and a step larger than the smallest clearing
  // step fails the minimality check below.
  const data = JSON.parse(read("lib/vendor-data.json"));
  const panel = [0x0c, 0x10, 0x15];
  const rgb = (hex) => {
    const n = hex.replace("#", "");
    return [0, 2, 4].map((i) => parseInt(n.slice(i, i + 2), 16));
  };
  const linear = (v) => {
    const s = v / 255;
    return s <= 0.04045 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  };
  const lum = ([r, g, b]) =>
    0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b);
  const ratio = (a, b) => {
    const la = lum(a);
    const lb = lum(b);
    return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
  };
  const mix = (a, b, t) => a.map((v, i) => t * v + (1 - t) * b[i]);
  const markAt = (base, step) =>
    mix([255, 255, 255], base, step).map((v) => Math.round(v));
  for (const fam of [...data.families, data.fallback]) {
    const base = rgb(fam.color);
    const ground = mix(base, panel, 0.16);
    const floor = 4.5;
    let step = 0;
    let value = ratio(markAt(base, step), ground);
    while (value < floor && step < 1) {
      step += 0.05;
      value = ratio(markAt(base, step), ground);
    }
    assert.ok(
      value >= floor,
      `${fam.key} chip mark computes ${value.toFixed(2)} to 1 on its tint, under its ${floor} floor`,
    );
    if (step > 0) {
      const under = ratio(markAt(base, step - 0.05), ground);
      assert.ok(
        under < floor,
        `${fam.key} chip mark step is not the smallest that clears its floor`,
      );
    }
  }
  // The recorded defect anchors the recomputation. In the
  // family color itself protectai's mark computed 2.34 to
  // 1 on its tint, the worst of the five families the
  // record names under the floor, and the derivation
  // moves it six steps and no more.
  const protectai = data.families.find((f) => f.key === "protectai");
  const pBase = rgb(protectai.color);
  const pGround = mix(pBase, panel, 0.16);
  const pBefore = ratio(pBase, pGround);
  assert.ok(
    Math.abs(pBefore - 2.34) < 0.01,
    `protectai mark on its tint recomputes at ${pBefore.toFixed(2)}, not the recorded 2.34`,
  );
  assert.ok(ratio(markAt(pBase, 0.25), pGround) < 4.5);
  assert.ok(ratio(markAt(pBase, 0.3), pGround) >= 4.5);
  // The shipped code carries the same derivation, and the
  // chip draws its mark in the derived color.
  const colors = read("lib/vendorColors.ts");
  assert.match(colors, /export function chipMarkColor/);
  assert.match(colors, /CHIP_MARK_FLOOR = 4\.5/);
  assert.match(colors, /CHIP_MARK_STEP = 0\.05/);
  const logo = read("components/VendorLogo.tsx");
  assert.ok(logo.includes('"--vm": chipMarkColor(family)'));
  assert.match(css, /\.vendor-chip \{[^}]*color: var\(--vm, var\(--vc/);
});

test("the brand mark carries the system's radius and ink in both files", () => {
  // The mark's field rect takes the panel radius from the
  // ladder, and its bars take ink 1. The pre-convergence
  // ink value and the off-ladder radius stand in neither
  // the top bar nor the favicon file.
  for (const rel of ["components/TopBar.tsx", "app/icon.svg"]) {
    const src = read(rel);
    assert.ok(src.includes('rx="10"'), `${rel} mark field is not at radius 10`);
    assert.ok(!src.includes('rx="12"'), `${rel} still carries radius 12`);
    assert.ok(src.includes("#EEF2F6"), `${rel} bars are not in ink 1`);
    assert.ok(!src.includes("#E9EEF3"), `${rel} still carries the stale ink`);
  }
});

test("the masthead frost runs at the entrance duration, inside the cap", () => {
  // The motion law caps every duration at 280ms. The
  // masthead transition spends the entrance token rather
  // than a hardcoded figure past the cap, and the top
  // bar's own comment states the same figure the sheet
  // runs.
  assert.ok(
    css.includes(
      "transition: background-color var(--dur-enter) ease, border-color var(--dur-enter) ease;",
    ),
  );
  assert.ok(!css.includes("300ms"));
  const topbar = read("components/TopBar.tsx");
  assert.ok(!topbar.includes("300ms"));
  assert.ok(topbar.includes("--dur-enter, 280ms"));
});

test("a dismissal arms its focus suppression only for the return it makes", () => {
  // The owner's keyboard walk found the leak. Escape
  // pressed from a disc itself dismisses the card while
  // focus already sits on that disc, so no focus event
  // follows to consume the suppression flag, and the flag
  // then ate the next deliberate refocus of the same disc.
  // The arming now stands behind the guard that the return
  // will actually move focus.
  const explorer = read("components/Explorer.tsx");
  const dismiss = explorer.slice(
    explorer.indexOf("const dismissChip = useCallback("),
    explorer.indexOf("/* Escape dismisses"),
  );
  assert.ok(dismiss.includes("document.activeElement !== disc"));
  assert.ok(
    dismiss.indexOf("document.activeElement !== disc") <
      dismiss.indexOf("focusReturnRef.current = id"),
    "the suppression is armed before the guard that scopes it",
  );
  assert.ok(dismiss.includes("disc.focus()"));
  // The focus handler still consumes an armed flag, which
  // is what keeps the genuine return from re-raising.
  assert.ok(explorer.includes("focusReturnRef.current = null"));
});

test("the share images state both rate bases and the pill track", () => {
  // F6 of the coherence re-score. The generator composes
  // the flagged lead's decomposition in two places, the
  // ceiling clause in the words under the plot and the
  // flagged reading in the stack. Both state the genuine
  // share against its eligible cases and the malformed
  // share against counted flips, the board's basis
  // discipline, and neither composes the basis-less
  // wording. The split bar track takes the pill radius
  // the board's own plain track carries, so the share
  // image reads as the same bar.
  const gen = read("scripts/gen-og.mjs");
  assert.ok(!gen.includes("genuine flip rate"));
  assert.ok(
    gen.includes(
      "genuine flips ${fmtPct(d.genuineRate)} of its eligible cases, with ${fmtPct(d.malformedShare)} of counted flips to malformed output",
    ),
  );
  assert.ok(
    gen.includes(
      "genuine flips ${fmtPct(d.genuineRate)} of its eligible cases.",
    ),
  );
  assert.ok(gen.includes(".robar{display:flex;height:9px;border-radius:999px;"));
  // The fit pass funds a tall card by narrowing the plot
  // and widening the readings column beside it, whose
  // lines unwrap as it widens. That conversion caps out
  // if the scatter column is sized by its widest child:
  // the plot's caption floors the column at its one-line
  // width, the flagged lead's reading holds its second
  // line at every shrink value, and the footer stands
  // past the card. The column therefore takes the plot's
  // own computed width, so the caption wraps inside the
  // plot's column and the conversion runs its full range.
  assert.ok(
    gen.includes('<div class="scattercol" style="width:${svgW}px">'),
  );
});

test("the token hygiene the re-score named stands as audited", () => {
  // The repo form of the F9 pin, settled at the port. The
  // census runs over this tree's own sources. Every
  // custom property the sheet defines either carries a
  // consumer in the board's code or stands on the record
  // in DESIGN.md, and the two that stand on the record
  // are named here, so a third token standing silent
  // fails. The easing token's only consumer anywhere is
  // the prototype tree's Flip swap rule, which this tree
  // does not carry. It stands because Data & Motion
  // legislates the curve it names. The middle shadow
  // stands because Elevation legislates the ladder of
  // three shadows. The banner rule the prototype keeps
  // for its own page is dead in this tree, where no page
  // renders the banner, and F9's scoping deletes it from
  // this sheet outright.
  const root = css.slice(
    css.indexOf(":root"),
    css.indexOf("}", css.indexOf(":root")),
  );
  const defined = [...root.matchAll(/(--[a-z0-9-]+)\s*:/g)].map(
    (m) => m[1],
  );
  const audited = [
    "--ground", "--panel", "--panel-2", "--lift", "--line",
    "--line-soft", "--edge", "--ink", "--ink-2", "--ink-3",
    "--accent", "--amber", "--glyph-dark", "--seg-genuine",
    "--radius", "--radius-ctl", "--shadow-1", "--shadow-2",
    "--shadow-3", "--dur-micro", "--dur-state", "--dur-enter",
    "--ease-out",
  ];
  assert.deepEqual(
    [...defined].sort(),
    [...audited].sort(),
    "the sheet's token set is not the audited census of 23",
  );
  const parts = [];
  const walk = (dir) => {
    for (const entry of readdirSync(join(here, "..", dir), {
      withFileTypes: true,
    })) {
      const rel = `${dir}/${entry.name}`;
      if (entry.isDirectory()) walk(rel);
      else if (/\.(ts|tsx|css)$/.test(entry.name)) parts.push(read(rel));
    }
  };
  for (const dir of ["app", "components", "lib"]) walk(dir);
  const corpus = parts.join("\n");
  const recordKept = new Set(["--shadow-2", "--ease-out"]);
  for (const token of defined) {
    const uses = corpus.split(`var(${token})`).length - 1;
    if (recordKept.has(token)) continue;
    assert.ok(
      uses > 0,
      `${token} is defined in :root and consumed nowhere in this tree`,
    );
  }
  // The two record-kept tokens carry their law in
  // DESIGN.md and their values in the sheet, and the pin
  // fails if either side of that standing is removed.
  const design = read("DESIGN.md");
  assert.ok(design.includes("plus its three shadows"));
  assert.ok(
    css.includes(
      "--shadow-2: 0 2px 6px rgba(0, 0, 0, 0.4), 0 14px 34px rgba(0, 0, 0, 0.3);",
    ),
  );
  assert.ok(design.includes("cubic-bezier(0.23, 1, 0.32, 1)"));
  assert.ok(css.includes("--ease-out: cubic-bezier(0.23, 1, 0.32, 1);"));
  // The dead banner rule is gone from this sheet, and no
  // page in this tree renders the banner it styled.
  assert.ok(!css.includes(".proto-banner"));
  assert.ok(!read("app/page.tsx").includes("proto-banner"));
  // The struck tokens stay struck.
  assert.ok(!css.includes("--accent-bright"));
  assert.ok(!/--red\s*:/.test(css));
});
