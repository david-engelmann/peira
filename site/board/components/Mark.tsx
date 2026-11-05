import type { CSSProperties } from "react";
import type { InspectorMark } from "@/lib/inspectorData";

/**
 * The vendor chip for a shaped mark, the client islands'
 * twin of VendorLogo (which reads a payload row directly).
 * The maker's brand mark on a tint of the maker's family
 * color, or the monogram letter for the systems that publish
 * no mark. Decorative beside the result's name, which already
 * names it; the vendor rides along as the accessible label.
 */
export default function Mark({
  mark,
  size = "row",
}: {
  mark: InspectorMark;
  size?: "row" | "card" | "mini";
}) {
  const style = { "--vc": mark.color } as CSSProperties;
  return (
    <span
      className={`vendor-chip ${size}${mark.kind === "mono" ? " mono" : ""}`}
      style={style}
      role="img"
      aria-label={mark.label}
      title={mark.label}
    >
      {mark.kind === "logo" ? (
        <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
          <use href={`#vlogo-${mark.slug}`} />
        </svg>
      ) : (
        <span className="vendor-letter" aria-hidden="true">
          {mark.letter}
        </span>
      )}
    </span>
  );
}
