import type { CSSProperties } from "react";
import type { BoardRow } from "@/lib/payload";
import { vendorOf } from "@/lib/vendor";
import { vendorFamilyOf } from "@/lib/vendorColors";

/**
 * The vendor chip for a row or a card: the maker's brand mark
 * on a tint of the maker's family color, or a monogram letter
 * for the systems that publish no mark. The family color is
 * the same hue the charts use for the model, so identity
 * reads consistently across the board. The chip is decorative
 * beside the model name, which already names the result; the
 * vendor rides along as the accessible label.
 */
export default function VendorLogo({
  row,
  size = "row",
}: {
  row: BoardRow;
  size?: "row" | "card" | "mini";
}) {
  const vendor = vendorOf(row);
  const family = vendorFamilyOf(row);
  const style = { "--vc": family.color } as CSSProperties;
  return (
    <span
      className={`vendor-chip ${size}${vendor.kind === "mono" ? " mono" : ""}`}
      style={style}
      role="img"
      aria-label={vendor.label}
      title={vendor.label}
    >
      {vendor.kind === "logo" ? (
        <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
          <use href={`#vlogo-${vendor.slug}`} />
        </svg>
      ) : (
        <span className="vendor-letter" aria-hidden="true">
          {vendor.letter}
        </span>
      )}
    </span>
  );
}
