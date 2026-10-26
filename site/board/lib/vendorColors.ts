/**
 * Vendor color system for the redesign. One hue per vendor
 * family, used by every chip and chart on the board, so a
 * model carries the same color in the ranking, the scatter,
 * the heatmap labels, the calibration panels, the detail
 * cards and the compare bars.
 *
 * The families, their colors, their marks and the rules that
 * resolve a row to a family live in lib/vendor-data.json,
 * the one vendor table for the whole board: lib/vendor
 * (marks and monograms) and scripts/gen-og.mjs (the share
 * image) read the same file, and
 * scripts/check-vendor-agreement.mjs proves the three
 * resolvers agree on every payload row. Resolution reads the
 * display name, the adapter name and the wire together, so a
 * model measured through a gateway still takes its maker's
 * color.
 */
import vendorData from "./vendor-data.json";

export interface VendorFamily {
  key: string;
  label: string;
  color: string;
  /** The ink that stays legible on the family color when the
   * color fills a disc or a chip. */
  glyph: string;
  /** Brand mark key into lib/logoPaths, or null when the
   * vendor publishes no usable mark. */
  logo: string | null;
  /** Monogram letter for a vendor with no mark, or null. */
  mono: string | null;
}

interface VendorData {
  families: VendorFamily[];
  rules: Array<{ pattern: string; family: string }>;
  fallback: VendorFamily;
}

const DATA = vendorData as VendorData;

export const VENDOR_FAMILIES: VendorFamily[] = DATA.families;

const BY_KEY = new Map(DATA.families.map((f) => [f.key, f]));
const RULES = DATA.rules.map((r) => ({
  test: new RegExp(r.pattern),
  key: r.family,
}));
const FALLBACK: VendorFamily = DATA.fallback;

/**
 * The vendor family a row resolves to, or null when no rule
 * matches its display name, adapter name or wire.
 */
export function vendorMatchOf(row: {
  display_name: string;
  adapter_name: string;
  wire: string;
}): VendorFamily | null {
  const hay = `${row.display_name} ${row.adapter_name} ${row.wire}`.toLowerCase();
  for (const rule of RULES) {
    if (rule.test.test(hay)) {
      return BY_KEY.get(rule.key) ?? null;
    }
  }
  return null;
}

/** The vendor family for anything carrying the three identity fields. */
export function vendorFamilyOf(row: {
  display_name: string;
  adapter_name: string;
  wire: string;
}): VendorFamily {
  return vendorMatchOf(row) ?? FALLBACK;
}

export function vendorColorOf(row: {
  display_name: string;
  adapter_name: string;
  wire: string;
}): string {
  return vendorFamilyOf(row).color;
}
