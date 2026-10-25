import type { BoardRow } from "@/lib/payload";
import { vendorOf, LOGO_PATHS } from "@/lib/vendor";

/**
 * The vendor chip for a row or a card: the maker's brand mark in
 * the board's ink tone, or a monogram letter for the systems that
 * publish no mark. Monochrome on purpose: the board's palette
 * carries the data, and a row of competing brand colors would
 * fight it. The chip is decorative beside the model name, which
 * already names the result; the vendor rides along as the
 * accessible label.
 */
export default function VendorLogo({
  row,
  size = "row",
}: {
  row: BoardRow;
  size?: "row" | "card";
}) {
  const vendor = vendorOf(row);
  return (
    <span
      className={`vendor-chip ${size}${vendor.kind === "mono" ? " mono" : ""}`}
      role="img"
      aria-label={vendor.label}
      title={vendor.label}
    >
      {vendor.kind === "logo" ? (
        <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
          <path d={LOGO_PATHS[vendor.slug]} fill="currentColor" />
        </svg>
      ) : (
        <span className="vendor-letter" aria-hidden="true">
          {vendor.letter}
        </span>
      )}
    </span>
  );
}
