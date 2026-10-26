/**
 * Vendor color system for the redesign. One hue per vendor
 * family, used by every chip and chart on the board, so a
 * model carries the same color in the ranking, the scatter,
 * the heatmap labels, the calibration panels, the detail
 * cards and the compare bars. Resolution reads the display
 * name, the adapter name and the wire together, the same
 * haystack as lib/vendor, so a model measured through a
 * gateway still takes its maker's color.
 *
 * No family color equals the flagged amber (#e8a33d), which
 * stays reserved for the flagged encoding everywhere.
 * `glyph` is the ink that stays legible on the family color
 * when the color fills a disc or a chip.
 */
export interface VendorFamily {
  key: string;
  label: string;
  color: string;
  glyph: string;
}

const DARK = "#0b0e12";
const LIGHT = "#f4f7fa";

export const VENDOR_FAMILIES: VendorFamily[] = [
  { key: "openai", label: "OpenAI", color: "#d7e0e8", glyph: DARK },
  { key: "anthropic", label: "Anthropic", color: "#d97757", glyph: LIGHT },
  { key: "google", label: "Google", color: "#8ab8ff", glyph: DARK },
  { key: "meta", label: "Meta", color: "#4a7dff", glyph: LIGHT },
  { key: "microsoft", label: "Microsoft", color: "#7bc950", glyph: DARK },
  { key: "ibm", label: "IBM", color: "#4fb3e3", glyph: DARK },
  { key: "mistral", label: "Mistral AI", color: "#ff8a3d", glyph: DARK },
  { key: "cloudflare", label: "Cloudflare", color: "#f0b429", glyph: DARK },
  { key: "deepseek", label: "DeepSeek", color: "#6e7bff", glyph: LIGHT },
  { key: "qwen", label: "Qwen", color: "#a78bfa", glyph: DARK },
  { key: "perplexity", label: "Perplexity", color: "#2ec4b6", glyph: DARK },
  { key: "minimax", label: "MiniMax", color: "#f24e7e", glyph: LIGHT },
  { key: "moonshot", label: "Moonshot AI", color: "#9fb4c7", glyph: DARK },
  { key: "cursor", label: "Cursor", color: "#b8bdc7", glyph: DARK },
  { key: "xai", label: "xAI", color: "#ffffff", glyph: DARK },
  { key: "zhipu", label: "Zhipu AI", color: "#6e8cff", glyph: DARK },
  { key: "jev", label: "Jev", color: "#a3d635", glyph: DARK },
  { key: "kev", label: "Kev", color: "#e879f9", glyph: DARK },
  { key: "laya", label: "Laya", color: "#5eead4", glyph: DARK },
  { key: "decider", label: "Decider", color: "#e5c15c", glyph: DARK },
  { key: "strands", label: "Strands", color: "#2aa198", glyph: DARK },
  { key: "celeris", label: "Celeris", color: "#7dd3fc", glyph: DARK },
  { key: "inception", label: "Inception", color: "#fca5a5", glyph: DARK },
  { key: "upstage", label: "Upstage", color: "#ffe066", glyph: DARK },
  { key: "inclusionai", label: "InclusionAI", color: "#c4b5fd", glyph: DARK },
  { key: "protectai", label: "Protect AI", color: "#f0abfc", glyph: DARK },
];

const RULES: Array<{ test: RegExp; key: string }> = [
  { test: /gpt-|openai/, key: "openai" },
  { test: /claude|anthropic/, key: "anthropic" },
  { test: /gemini|google/, key: "google" },
  { test: /llama|prompt-guard|meta/, key: "meta" },
  { test: /granite|ibm/, key: "ibm" },
  { test: /mistral|shieldstral/, key: "mistral" },
  { test: /clef|cloudflare/, key: "cloudflare" },
  { test: /deepseek/, key: "deepseek" },
  { test: /qwen/, key: "qwen" },
  { test: /pplx|perplexity/, key: "perplexity" },
  { test: /minimax/, key: "minimax" },
  { test: /kimi|moonshot/, key: "moonshot" },
  { test: /microsoft/, key: "microsoft" },
  { test: /cursor/, key: "cursor" },
  { test: /grok|xai/, key: "xai" },
  { test: /glm|zai/, key: "zhipu" },
  { test: /jev/, key: "jev" },
  { test: /kev/, key: "kev" },
  { test: /laya/, key: "laya" },
  { test: /decider-0|mapika/, key: "decider" },
  { test: /strands/, key: "strands" },
  { test: /celeris/, key: "celeris" },
  { test: /mercury|inception/, key: "inception" },
  { test: /solar|upstage/, key: "upstage" },
  { test: /ling|inclusionai/, key: "inclusionai" },
  { test: /protectai|deberta/, key: "protectai" },
];

const BY_KEY = new Map(VENDOR_FAMILIES.map((f) => [f.key, f]));
const FALLBACK: VendorFamily = {
  key: "other",
  label: "Other",
  color: "#8b98a5",
  glyph: DARK,
};

/** The vendor family for anything carrying the three identity fields. */
export function vendorFamilyOf(row: {
  display_name: string;
  adapter_name: string;
  wire: string;
}): VendorFamily {
  const hay = `${row.display_name} ${row.adapter_name} ${row.wire}`.toLowerCase();
  for (const rule of RULES) {
    if (rule.test.test(hay)) {
      return BY_KEY.get(rule.key) ?? FALLBACK;
    }
  }
  return FALLBACK;
}

export function vendorColorOf(row: {
  display_name: string;
  adapter_name: string;
  wire: string;
}): string {
  return vendorFamilyOf(row).color;
}
