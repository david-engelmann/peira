import type { CSSProperties } from "react";
import type { InspectorMark } from "@/lib/inspectorData";
import { chipMarkColor } from "@/lib/vendorColors";

/**
 * The vendor mark tile the explorer and the Flip share. The
 * maker's mark stands on its family color, drawn from the
 * sprite when the vendor publishes one and standing as a
 * letter in the glyph color when it does not. The tile is
 * decorative beside the name it rides with, and that name
 * already names the result.
 */
export default function Mark({
  mark,
  size = 26,
  tinted = false,
}: {
  mark: InspectorMark & { glyph: string };
  size?: number;
  tinted?: boolean;
}) {
  const style = {
    width: size,
    height: size,
    ...(tinted
      ? {
          "--vc": mark.color,
          "--vm-light": chipMarkColor(mark, "light"),
          "--vm-dark": chipMarkColor(mark, "dark"),
        }
      : { background: mark.color, color: mark.glyph }),
  } as CSSProperties;
  return (
    <span
      className={tinted ? "xmark vendor-chip" : "xmark"}
      style={style}
      aria-hidden="true"
    >
      {mark.kind === "logo" && mark.slug ? (
        <svg width={size * 0.62} height={size * 0.62} viewBox="0 0 24 24">
          <use href={`#vlogo-${mark.slug}`} />
        </svg>
      ) : (
        <span className="xmark-letter">{mark.letter}</span>
      )}
    </span>
  );
}
