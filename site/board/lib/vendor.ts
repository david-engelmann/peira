import type { BoardRow } from "./payload";
import { shortName } from "./payload";
import { LOGO_PATHS, type LogoSlug } from "./logoPaths";

/**
 * Vendor identity for a board row: a brand mark where the vendor
 * publishes one, otherwise a monogram chip lettered from the
 * model's own name. Resolution reads the display name, the
 * adapter name and the wire together, so a model measured through
 * a gateway still carries its maker's mark (a Qwen model on the
 * OpenRouter wire is a Qwen row), and a row nobody has mapped yet
 * degrades to the monogram rather than to a wrong logo.
 */
export type VendorMark =
  | { kind: "logo"; slug: LogoSlug; label: string }
  | { kind: "mono"; letter: string; label: string };

const RULES: Array<{
  test: RegExp;
  slug: LogoSlug;
  label: string;
}> = [
  { test: /gpt-|openai/, slug: "openai", label: "OpenAI" },
  { test: /claude|anthropic/, slug: "anthropic", label: "Anthropic" },
  { test: /gemini|google/, slug: "googlegemini", label: "Google" },
  { test: /llama|meta/, slug: "meta", label: "Meta" },
  { test: /granite|ibm/, slug: "ibm", label: "IBM" },
  { test: /mistral|shieldstral/, slug: "mistralai", label: "Mistral AI" },
  { test: /clef|cloudflare/, slug: "cloudflare", label: "Cloudflare" },
  { test: /deepseek/, slug: "deepseek", label: "DeepSeek" },
  { test: /qwen/, slug: "qwen", label: "Qwen" },
  { test: /pplx|perplexity/, slug: "perplexity", label: "Perplexity" },
  { test: /minimax/, slug: "minimax", label: "MiniMax" },
  { test: /kimi|moonshot/, slug: "moonshotai", label: "Moonshot AI" },
  { test: /microsoft/, slug: "microsoft", label: "Microsoft" },
  { test: /cursor/, slug: "cursor", label: "Cursor" },
];

export function vendorOf(row: BoardRow): VendorMark {
  const hay = `${row.display_name} ${row.adapter_name} ${row.wire}`.toLowerCase();
  for (const rule of RULES) {
    if (rule.test.test(hay)) {
      return { kind: "logo", slug: rule.slug, label: rule.label };
    }
  }
  if (/grok|xai/.test(hay)) {
    /* xAI publishes no mark in the icon set; its own wordmark is
     * an X, so the monogram carries that letter. */
    return { kind: "mono", letter: "X", label: "xAI" };
  }
  const name = shortName(row);
  const letter = (name.match(/[a-z0-9]/i)?.[0] ?? "·").toUpperCase();
  return { kind: "mono", letter, label: name };
}

export { LOGO_PATHS };
