import type { BoardRow } from "@/lib/payload";
import { displayCi } from "@/lib/payload";
import { axisPct } from "@/lib/chart";

/**
 * One row's interval strip, drawn with positioned elements on
 * the shared 0 to 30 axis. The whisker line runs from cap to
 * cap and stops 2 px short of each cap center, so a visible gap
 * separates the line from the caps and nothing passes through
 * them (owner ruling, round 8 feedback). Positions are percents
 * of the strip width, so the geometry is exact at any width and
 * code verifiable against the payload interval.
 *
 * Full suite rows draw a solid whisker with a filled estimate
 * mark. Slice rows draw a quieter whisker with a hollow mark, so
 * the population difference survives a greyscale screenshot.
 * Flagged rows draw in amber. A measured zero still draws its
 * whisker; a missing interval draws the not measured mark.
 */
export default function WhiskerStrip({
  row,
  variant,
}: {
  row: BoardRow;
  variant: "full" | "slice" | "flagged";
}) {
  const ci = displayCi(row);
  if (row.asr_conditional === null || ci === null) {
    return (
      <div className={`cell-chart ${variant}`}>
        <div className="not-measured" aria-hidden="true">
          ·
        </div>
      </div>
    );
  }
  const asr = row.asr_conditional;
  const [lo, hi] = ci;
  const x0 = axisPct(lo);
  const x1 = axisPct(hi);
  const xa = axisPct(asr);
  return (
    <div className={`cell-chart ${variant}`} aria-hidden="true">
      <div
        className="whisker"
        style={{
          left: `calc(${x0}% + 2px)`,
          width: `calc(${Math.max(0, x1 - x0)}% - 4px)`,
        }}
      />
      <div className="whisker-cap" style={{ left: `${x0}%` }} />
      <div className="whisker-cap" style={{ left: `${x1}%` }} />
      <div
        className={`estimate-dot${variant === "slice" ? " hollow" : ""}`}
        style={{ left: `${xa}%` }}
      />
    </div>
  );
}
