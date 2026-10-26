import {
  boardGroups,
  boardDateWords,
  boardVersions,
  shortName,
  wireWords,
  duplicateShortNames,
  type BoardRow,
} from "@/lib/payload";
import { fmtInt, fmtPct } from "@/lib/format";
import { vendorColorOf } from "@/lib/vendorColors";

/**
 * Malformed rates and the admission rule, design system
 * sections 1.9 and 2.1 (position 4, directly after the ranking,
 * because the ranking raises the question this section answers).
 *
 * One list, worst first, the order the previous board's strip
 * was verified in. The axis runs 0 to 15 percent on round ticks
 * (census F-15, which also bans the old per-row admission
 * ticks): the 5 percent admission line is a single continuous
 * rule drawn once across every bar. Flagged results draw an
 * amber outline bar with an amber value and a flagged tag, the
 * same encoding as the ranking's flagged strip, and amber
 * appears on no other row. A ranked bar past the line would
 * draw in red, the design's over-threshold mark; none exists
 * on this payload. Results whose printed rate is 0.0 percent
 * fold into one summary line (the standing Round 21 S6 rule,
 * confirmed by the census).
 */

const MALFORMED_AXIS_MAX = 0.15;
const MAL_TICKS = [0, 0.05, 0.1, 0.15];

/** Position on the malformed axis as a percent of the strip. */
function malPct(value: number): number {
  return Math.min(100, Math.max(0, (value / MALFORMED_AXIS_MAX) * 100));
}

export default function Malformed() {
  const groups = boardGroups();
  const allRows: BoardRow[] = [
    ...groups.full,
    ...groups.slices,
    ...groups.flagged,
  ];
  const dupes = duplicateShortNames(allRows);
  const flaggedIds = new Set(groups.flagged.map((r) => r.run_id));
  const sorted = [...allRows].sort((a, b) => {
    const d = (b.malformed_rate ?? 0) - (a.malformed_rate ?? 0);
    if (d !== 0) return d;
    return a.display_name < b.display_name ? -1 : 1;
  });
  const printed = sorted.filter(
    (r) => r.malformed_rate !== null && fmtPct(r.malformed_rate) !== "0.0%",
  );
  const folded = sorted.length - printed.length;
  const versions = boardVersions();

  return (
    <section
      className="section"
      aria-labelledby="malformed-title"
      data-section="malformed"
      id="malformed"
    >
      <p className="section-label">Malformed and admission</p>
      <h2 className="section-title" id="malformed-title">
        Why flagged results are not ranked
      </h2>
      <p className="section-lede">
        A result earns a rank only when its malformed response rate is
        at or under 5 percent on its complete sealed run.{" "}
        {fmtInt(groups.flagged.length)} results sit over that line.
        They keep every number the board measured, are not ranked, and
        their bars below draw in the flagged outline.
      </p>

      <div className="mal-axis" aria-hidden="true">
        <div className="mal-limit-label" style={{ left: `${malPct(0.05)}%` }}>
          5% admission limit
        </div>
        {MAL_TICKS.map((tick, i) => (
          <span
            key={tick}
            className={`mal-tick num${
              i === 0 ? " first" : i === MAL_TICKS.length - 1 ? " last" : ""
            }`}
            style={{ left: `${malPct(tick)}%` }}
          >
            {Math.round(tick * 100)}
          </span>
        ))}
      </div>

      <div className="mal-rows">
        <div
          className="mal-line"
          style={{ left: `${malPct(0.05)}%` }}
          aria-hidden="true"
        />
        {printed.map((row) => {
          const flagged = flaggedIds.has(row.run_id);
          const rate = row.malformed_rate ?? 0;
          const over = !flagged && rate > 0.05;
          const name = shortName(row);
          return (
            <div
              className="mal-row"
              key={row.run_id}
              data-run-id={row.run_id}
              data-malformed={row.malformed_rate ?? ""}
            >
              <div className="mal-line1">
                <div className="cell-name">
                  <div className="name-line">
                    {flagged && <span className="flag-tag">Flagged</span>}
                    {name}
                  </div>
                  {dupes.has(name) && (
                    <div className="wire-line">{wireWords(row.wire)}</div>
                  )}
                </div>
                <div
                  className={`mal-value num${flagged ? " flagged" : ""}`}
                >
                  {fmtPct(rate)}
                </div>
              </div>
              <div className="mal-track">
                <div
                  className={`mal-fill${flagged ? " flagged" : ""}${over ? " over" : ""}`}
                  style={{
                    width: `${malPct(rate)}%`,
                    background:
                      flagged || over ? undefined : vendorColorOf(row),
                  }}
                />
              </div>
            </div>
          );
        })}
      </div>

      {folded > 0 && (
        <p className="mal-fold">
          {fmtInt(folded)} results printed a malformed rate of 0.0
          percent and are folded here rather than drawn as empty bars.
        </p>
      )}

      <p className="chart-id">
        Peira decision robustness board, malformed response rates. All{" "}
        {fmtInt(allRows.length)} results, worst first, admission limit 5
        percent. Dataset {versions.dataset}, updated {boardDateWords()}.
      </p>
    </section>
  );
}
