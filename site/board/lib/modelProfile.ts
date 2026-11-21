import type { BoardRow } from "./payload";

export interface ModelProfile {
  readonly kind: "specialist" | "general" | "guard" | "unknown";
  readonly interface: "typed" | "structured" | "option-scoring" | "classification" | "safety" | "unknown";
  readonly serving: "local" | "hosted" | "unknown";
  readonly weights: "open" | "gated" | "unreleased" | "unknown";
  readonly frontier: boolean;
}

const unknownProfile: ModelProfile = {
  kind: "unknown",
  interface: "unknown",
  serving: "unknown",
  weights: "unknown",
  frontier: false,
};

// Exact adapter and version pairs. See MODEL-PROFILES.md for the evidence
// and the scope of the frontier baseline cohort.
const groups: [ModelProfile, string[]][] = [
  [{ kind: "guard", interface: "safety", serving: "local", weights: "open", frontier: false }, [
    "granite-guardian-hap|125m",
    "shieldstral|1.0",
    "qwen3guard-gen|1.0",
    "protectai-prompt-injection|2.0",
    "granite-guardian|1.0",
  ]],
  [{ kind: "guard", interface: "safety", serving: "local", weights: "gated", frontier: false }, [
    "llama-prompt-guard-2|2.0",
  ]],
  [{ kind: "specialist", interface: "classification", serving: "local", weights: "open", frontier: false }, [
    "gliner-decide|fastino/GLiNER2.5-Decide@9d1bfb848cd16d93ee56ccbc59cd92bf0f284d90",
  ]],
  [{ kind: "specialist", interface: "typed", serving: "local", weights: "open", frontier: false }, [
    "decider|Mapika/decider-0.8b@a0a01d6f8135298f400a8c856b355793012ae971",
    "kev|jaredpalmer/kev-4b",
    "kev|jaredpalmer/kev-0.8b",
    "strands-decider|StrandsAgents/strands-decider-2B-hobson-v21",
    "laya|convaiinnovations/laya-multilingual",
    "laya|convaiinnovations/laya-typed-decisions",
    "von|von-1.3.0",
  ]],
  [{ kind: "specialist", interface: "typed", serving: "hosted", weights: "open", frontier: false }, [
    "clef|@cf/cloudflare/clef",
    "clef|@cf/cloudflare/clef-flash",
    "clef|@cf/cloudflare/clef-omni",
    "pplx-decider|pplx-decider-v1.1-27b",
    "pplx-decider|pplx-decider-v1.2",
    "pplx-decider|pplx-decider-flash-v1.2",
  ]],
  [{ kind: "specialist", interface: "typed", serving: "hosted", weights: "unknown", frontier: false }, [
    "jev|jev-1.13.0",
    "jev|jev-1.14.0",
    "mercury-decide|mercury-decide",
    "celeris|celeris-1-decision",
    "google-decisions|gemini-decision-1",
  ]],
  [{ kind: "specialist", interface: "typed", serving: "hosted", weights: "unreleased", frontier: false }, [
    "openrouter-decisions|microsoft/microsoft-decision-1",
  ]],
  [{ kind: "general", interface: "option-scoring", serving: "local", weights: "open", frontier: false }, [
    "semif|Qwen/Qwen3.5-4B@851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a",
  ]],
  [{ kind: "general", interface: "structured", serving: "hosted", weights: "open", frontier: true }, [
    "moonshot-structured|kimi-k3",
    "deepseek-structured|deepseek-flash",
    "minimax-structured|MiniMax-M3",
    "minimax-structured|MiniMax-M3.1-Flash",
  ]],
  [{ kind: "general", interface: "typed", serving: "hosted", weights: "unknown", frontier: true }, [
    "openai-decisions|gpt-6-luna",
  ]],
  [{ kind: "general", interface: "structured", serving: "hosted", weights: "unknown", frontier: true }, [
    "google-structured|gemini-4-argon",
    "google-structured|gemini-3.8-flash",
    "openai-structured|gpt-5.6-terra",
    "openai-structured|gpt-6.1-sol",
    "openai-structured|gpt-6-luna",
    "openai-structured|gpt-6-astra",
    "openai-structured|gpt-5.6-sol",
    "openai-structured|gpt-5.6-luna",
    "anthropic-structured|claude-haiku-5-5",
    "anthropic-structured|claude-sonnet-5-5",
    "anthropic-structured|claude-opus-5-5",
    "anthropic-structured|claude-fable-5-1",
    "xai-structured|grok-4",
    "zai-structured|glm-4-plus",
  ]],
  [{ kind: "general", interface: "structured", serving: "hosted", weights: "open", frontier: false }, [
    "openrouter-structured|qwen/qwen3-235b-a22b-2507",
    "openrouter-tool|inclusionai/ling-3.0-flash",
    "openrouter-tool|inclusionai/ling-3.0-flash-vl",
    "openrouter-tool|inclusionai/ling-3.1-flash",
  ]],
  [{ kind: "general", interface: "structured", serving: "hosted", weights: "unknown", frontier: false }, [
    "openrouter-structured|upstage/solar-pro4",
    "mercury-structured|mercury-3",
  ]],
];

const profiles = new Map(
  groups.flatMap(([profile, identities]) =>
    identities.map((identity) => [identity, profile] as const),
  ),
);

export function modelProfile(row: BoardRow): ModelProfile {
  return profiles.get(`${row.adapter_name}|${row.adapter_version}`) ?? unknownProfile;
}
