import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import ts from "typescript";

const source = readFileSync(new URL("../lib/modelProfile.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
});
const exports = {};
new Function("exports", outputText)(exports);
const { modelProfile } = exports;

test("reviewed adapter and version pairs express independent model profiles", () => {
  const examples = [
    ["granite-guardian", "1.0", "guard", "safety", "local", "open", false],
    ["llama-prompt-guard-2", "2.0", "guard", "safety", "local", "gated", false],
    ["von", "von-1.3.0", "specialist", "typed", "local", "open", false],
    ["clef", "@cf/cloudflare/clef-omni", "specialist", "typed", "hosted", "open", false],
    ["pplx-decider", "pplx-decider-v1.1-27b", "specialist", "typed", "hosted", "open", false],
    ["jev", "jev-1.14.0", "specialist", "typed", "hosted", "unknown", false],
    ["openrouter-decisions", "microsoft/microsoft-decision-1", "specialist", "typed", "hosted", "unreleased", false],
    ["semif", "Qwen/Qwen3.5-4B@851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a", "general", "option-scoring", "local", "open", false],
    ["gliner-decide", "fastino/GLiNER2.5-Decide@9d1bfb848cd16d93ee56ccbc59cd92bf0f284d90", "specialist", "classification", "local", "open", false],
    ["moonshot-structured", "kimi-k3", "general", "structured", "hosted", "open", true],
    ["minimax-structured", "MiniMax-M3.1-Flash", "general", "structured", "hosted", "open", true],
    ["openai-decisions", "gpt-6-luna", "general", "typed", "hosted", "unknown", true],
    ["openai-structured", "gpt-6-luna", "general", "structured", "hosted", "unknown", true],
    ["openrouter-tool", "inclusionai/ling-3.1-flash", "general", "structured", "hosted", "open", false],
    ["mercury-structured", "mercury-3", "general", "structured", "hosted", "unknown", false],
  ];
  for (const [adapter_name, adapter_version, kind, decisionInterface, serving, weights, frontier] of examples) {
    const expected = { kind, interface: decisionInterface, serving, weights, frontier };
    const row = { adapter_name, adapter_version };
    assert.deepEqual(modelProfile(row), expected, `${adapter_name}/${adapter_version}`);
    assert.deepEqual(modelProfile({
      ...row, ranking_eligible: false, total_cost_usd: 12, asr_conditional: 0.1,
    }), expected, `${adapter_name}/${adapter_version} with different measurements`);
  }
});

test("an unreviewed pair stays unknown even for a known adapter", () => {
  assert.deepEqual(modelProfile({
    adapter_name: "openai-structured",
    adapter_version: "future-checkpoint",
    display_name: "gpt-6-luna",
  }), { kind: "unknown", interface: "unknown", serving: "unknown", weights: "unknown", frontier: false });
});
