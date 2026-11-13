import type { InspectorMark } from "@/lib/inspectorData";

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
}: {
  mark: InspectorMark & { glyph: string };
  size?: number;
}) {
  const m = mark;
  return (
    <span
      className="xmark"
      style={{ width: size, height: size, background: m.color }}
      aria-hidden="true"
    >
      {m.kind === "logo" && m.slug ? (
        <svg width={size * 0.62} height={size * 0.62} viewBox="0 0 24 24">
          <use href={`#vlogo-${m.slug}`} style={{ color: m.glyph }} />
        </svg>
      ) : (
        <span className="xmark-letter" style={{ color: m.glyph }}>
          {m.letter}
        </span>
      )}
    </span>
  );
}
