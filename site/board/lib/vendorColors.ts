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

/**
 * The chip mixes 16 percent of the family color into the
 * theme's panel token from app/study.css. Move the mark
 * toward black on the light panel or white on the dark
 * panel by the smallest five percent step that clears the
 * 4.5:1 floor for both vendor marks and monograms.
 */
const CHIP_PANELS = { light: "#ffffff", dark: "#141e32" };
const CHIP_TINT_SHARE = 0.16;
export const CHIP_MARK_FLOOR = 4.5;
const CHIP_MARK_STEPS = 20;

type Rgb = [number, number, number];

function rgbOf(hex: string): Rgb {
  const n = hex.replace("#", "");
  return [
    parseInt(n.slice(0, 2), 16),
    parseInt(n.slice(2, 4), 16),
    parseInt(n.slice(4, 6), 16),
  ];
}

function hexOf([r, g, b]: Rgb): string {
  const channel = (v: number) =>
    Math.round(v).toString(16).padStart(2, "0");
  return `#${channel(r)}${channel(g)}${channel(b)}`;
}

/** An sRGB mix, the first color at share t, the same mix
 * the stylesheet draws the chip's tinted ground with. */
function mixSrgb(a: Rgb, b: Rgb, t: number): Rgb {
  return [
    t * a[0] + (1 - t) * b[0],
    t * a[1] + (1 - t) * b[1],
    t * a[2] + (1 - t) * b[2],
  ];
}

function luminanceOf([r, g, b]: Rgb): number {
  const linear = (v: number) => {
    const s = v / 255;
    return s <= 0.04045 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  };
  return 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b);
}

function contrastOf(a: Rgb, b: Rgb): number {
  const la = luminanceOf(a);
  const lb = luminanceOf(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

/** The color the chip's mark or monogram letter is drawn in. */
export function chipMarkColor(family: Pick<VendorFamily, "color">, theme: keyof typeof CHIP_PANELS): string {
  const base = rgbOf(family.color);
  const ground = mixSrgb(base, rgbOf(CHIP_PANELS[theme]), CHIP_TINT_SHARE);
  const endpoint: Rgb = theme === "light" ? [0, 0, 0] : [255, 255, 255];
  for (let step = 0; step < CHIP_MARK_STEPS; step += 1) {
    const mark = hexOf(mixSrgb(endpoint, base, step / CHIP_MARK_STEPS));
    if (contrastOf(rgbOf(mark), ground) >= CHIP_MARK_FLOOR) return mark;
  }
  return hexOf(endpoint);
}
