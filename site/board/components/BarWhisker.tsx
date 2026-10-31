import type { BoardRow } from "@/lib/payload";
import { displayCi } from "@/lib/payload";
import { axisPct } from "@/lib/chart";

/**
 * One row's interval strip, drawn with positioned elements on
 * the shared axis, whose maximum the parent derives from the
 * ranked population (lib/chart). The whisker line runs from cap to
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
  axisMax,
}: {
  row: BoardRow;
  variant: "full" | "slice" | "flagged";
  axisMax: number;
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
  const x0 = axisPct(lo, axisMax);
  const x1 = axisPct(hi, axisMax);
  const xa = axisPct(asr, axisMax);
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
