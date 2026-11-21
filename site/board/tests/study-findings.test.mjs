import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

const board = fileURLToPath(new URL("../", import.meta.url));
const readPayload = () => JSON.parse(readFileSync(join(board, "data/payload.json"), "utf8"));

// Transpile production code with a scoped loader.
// The only substitutions are the payload input and the style-only import.
function loadBoard(payload, entry) {
  const modules = new Map();
  function load(filename) {
    if (modules.has(filename)) return modules.get(filename);
    const require = createRequire(filename);
    const module = { exports: {} };
    const { outputText } = ts.transpileModule(readFileSync(filename, "utf8"), {
      fileName: filename,
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        jsx: ts.JsxEmit.ReactJSX,
        target: ts.ScriptTarget.ES2022,
        esModuleInterop: true,
      },
    });
    const requireSource = (id) => {
      if (id.endsWith(".css")) return {};
      if (id === "@/data/payload.json") return payload;
      if (id.endsWith(".json")) return require(id);
      if (id.startsWith("@/")) return load(join(board, `${id.slice(2)}.ts`));
      if (id.startsWith(".")) return load(join(dirname(filename), `${id}.ts`));
      return require(id);
    };
    new Function("require", "module", "exports", outputText)(requireSource, module, module.exports);
    modules.set(filename, module.exports);
    return module.exports;
  }
  return load(join(board, entry));
}

function renderStudy(payload) {
  const StudyFindings = loadBoard(payload, "components/StudyFindings.tsx").default;
  return renderToStaticMarkup(createElement(StudyFindings));
}

test("the study renders exact pooled family counts and rates from the ranked full suite", () => {
  const html = renderStudy(readPayload());
  assert.match(html, /41 ranked full-suite results, tested on the same 4,701 paired cases per result/);
  assert.match(html, /41\.0%<\/p><p[^>]*>of all counted flips came from retrieval poisoning/);
  assert.match(html, /accounted for 9\.9% of eligible cases across results/);
  assert.match(html, /32,416 counted flips across 183,159 eligible cases/);
  assert.match(html, /Retrieval poisoning<\/span><span[^>]*>73\.7%<\/span><span[^>]*>13,305 \/ 18,059/);
  assert.equal([...html.matchAll(/class="study-family-name"/g)].length, 11);
  assert.match(html, /href="#explorer\?pop=full&amp;mode=families"/);
});

test("the study plots all priced ranked full-suite results and discloses their intervals", () => {
  const html = renderStudy(readPayload());
  assert.match(html, /−0\.41<\/p><p[^>]*>Spearman rank correlation between run cost and attack success across 19 fully priced results/);
  assert.match(html, /Across all 32 recorded costs, the correlation was −0\.16/);
  assert.match(html, /For 13 runs, the recorded cost is a lower bound/);
  assert.match(html, /9 had zero or unrecorded cost/);
  assert.equal([...html.matchAll(/class="study-scatter-point\b/g)].length, 32);
  assert.equal([...html.matchAll(/class="study-scatter-whisker\b/g)].length, 32);
  assert.equal([...html.matchAll(/class="study-scatter-point study-scatter-highlight\b/g)].length, 2);
  assert.match(html, /gpt-6-luna · Decisions API · \$0\.2922 · 10\.7%/);
  assert.match(html, /href="\/models\/gpt-6-luna-openai-decisions\/"/);
  assert.match(html, /10\.7% <span>9\.8% to 11\.6%/);
  assert.match(html, /claude-fable-5-1 · ≥\$130\.31 · 28\.5%/);
  assert.match(html, /at least <strong>\$130\.31<\/strong>/);
  assert.match(html, /href="#explorer\?pop=full&amp;mode=chart"/);
});

test("missing family records suppress the pooled finding while the cost finding remains", () => {
  const payload = readPayload();
  const fullCases = Math.max(...payload.ranked.map((row) => row.n_cases));
  const row = payload.ranked.find((row) => row.n_cases === fullCases);
  delete row.detail.families;
  const html = renderStudy(payload);
  assert.doesNotMatch(html, /id="study-families-heading"/);
  assert.match(html, /id="study-cost-heading"/);
});

test("explorer family and severity rates use sealed counts when they agree with stored rates", () => {
  const { explorerData } = loadBoard(readPayload(), "lib/explorerData.ts");
  const { rows } = explorerData();
  const argon = rows.find(row => row.slug === "gemini-4-argon");
  const family = argon.record.families.find(f => f.key === "cryptographic_payload");
  assert.match(family.countsText, /17 flipped of 420 eligible/);
  assert.equal(family.asrText, "4.0%");
  assert.equal(argon.families.find(f => f.key === family.key).asr, 17 / 420);

  const sol = rows.find(row => row.slug === "gpt-6-1-sol");
  const severity = sol.record.severities.find(s => s.label === "Medium");
  assert.ok(severity.segments.includes("245 flipped of 2,017 eligible"));
  assert.equal(severity.flipText, "12.1%");
});

test("explorer preserves stored rates and intervals when the counts disagree", () => {
  const payload = readPayload();
  const argon = payload.ranked.find(row => row.adapter_version === "gemini-4-argon");
  const rawFamily = argon.detail.families.cryptographic_payload;
  rawFamily.asr = 0.05;
  rawFamily.asr_ci95 = [0.01, 0.09];
  const sol = payload.ranked.find(row => row.adapter_version === "gpt-6.1-sol");
  const rawSeverity = sol.detail.severities.medium;
  rawSeverity.flip_rate_raw = 0.11;
  rawSeverity.flip_rate_ci95 = [0.09, 0.13];

  const { explorerData } = loadBoard(payload, "lib/explorerData.ts");
  const { rows } = explorerData();
  const family = rows.find(row => row.runId === argon.run_id).record.families
    .find(f => f.key === "cryptographic_payload");
  assert.equal(family.asrText, "5.0%");
  assert.equal(family.ciText, "1.0% to 9.0%");
  const severity = rows.find(row => row.runId === sol.run_id).record.severities
    .find(s => s.label === "Medium");
  assert.equal(severity.flipText, "11.0%");
  assert.equal(severity.ciText, "9.0% to 13.0%");
});
