import type { ModelProfile } from "./modelProfile";

export const profileDimensions = ["kind", "interface", "serving", "weights", "tier"] as const;
export type ProfileDimension = typeof profileDimensions[number];

export const dimensionLabels: Record<ProfileDimension, string> = {
  kind: "Model role",
  interface: "Decision interface",
  serving: "Inference",
  weights: "Weight access",
  tier: "Frontier cohort",
};

export const groupLabels: Record<ProfileDimension, Record<string, string>> = {
  kind: {
    specialist: "Decision specialists",
    general: "General-purpose models",
    guard: "Guard models",
    unknown: "Role unverified",
  },
  interface: {
    typed: "Typed decision questions",
    structured: "Structured generation",
    "option-scoring": "Direct option scoring",
    classification: "Label classification",
    safety: "Safety verdicts",
    unknown: "Interface unverified",
  },
  serving: {
    local: "Local inference",
    hosted: "Hosted inference",
    unknown: "Inference unverified",
  },
  weights: {
    open: "Documented open weights",
    gated: "Gated download",
    unreleased: "Weights not distributed",
    unknown: "Weights unverified",
  },
  tier: {
    frontier: "Frontier baselines",
    other: "Other results",
  },
};

export function profileValue(profile: ModelProfile, dimension: ProfileDimension): string {
  return dimension === "tier" ? (profile.frontier ? "frontier" : "other") : profile[dimension];
}
