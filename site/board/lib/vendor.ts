import type { BoardRow } from "./payload";
import { shortName } from "./payload";
import { LOGO_PATHS, type LogoSlug } from "./logoPaths";
import { vendorMatchOf } from "./vendorColors";

/**
 * Vendor identity for a board row: a brand mark where the
 * vendor publishes one, otherwise a monogram chip lettered
 * from the provider's name. Which vendor a row belongs to
 * resolves through lib/vendor-data.json, the one vendor
 * table for the whole board, shared with lib/vendorColors
 * and scripts/gen-og.mjs; resolution reads the display name,
 * the adapter name and the wire together, so a model measured
 * through a gateway still carries its maker's mark (a Qwen
 * model on the OpenRouter wire is a Qwen row), and a row
 * nobody has mapped yet degrades to a monogram lettered from
 * the model's own name rather than to a wrong logo.
 * Providers that publish no usable mark get the monogram
 * letter and label the table records for them, so a row is
 * credited to its maker everywhere the board shows one.
 */
export type VendorMark =
  | { kind: "logo"; slug: LogoSlug; label: string }
  | { kind: "mono"; letter: string; label: string };

export function vendorOf(row: BoardRow): VendorMark {
  const family = vendorMatchOf(row);
  if (family?.logo) {
    return { kind: "logo", slug: family.logo as LogoSlug, label: family.label };
  }
  if (family?.mono) {
    return { kind: "mono", letter: family.mono, label: family.label };
  }
  const name = shortName(row);
  const letter = (name.match(/[a-z0-9]/i)?.[0] ?? "·").toUpperCase();
  return { kind: "mono", letter, label: name };
}

export { LOGO_PATHS };
