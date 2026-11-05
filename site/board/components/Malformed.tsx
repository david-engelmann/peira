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

/**
 * The malformed rail (04). Every result's malformed share
 * as a bar on one scale, worst first, with the 5 percent
 * flag line drawn through the bars and labelled. The scale
 * derives from the field: the worst printed rate rounded up
 * to the next 5 percent step, with a floor of 15 percent so
 * a quiet field still reads against a frame that leaves the
 * flag line inside the track. Results past the line stand
 * in the flagged band above with their split; their bars
 * here draw in the flagged amber, and every other bar draws
 * in the neutral track ink, so maker identity never rides
 * on bar color. Results whose printed rate is 0.0 percent
 * fold into one summary line rather than draw as empty bars.
 */

function malformedAxis(maxRate: number): { max: number } {
  return { max: Math.max(0.15, Math.ceil(maxRate / 0.05) * 0.05) };
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
  const axis = malformedAxis(
    printed.reduce((m, r) => Math.max(m, r.malformed_rate ?? 0), 0),
  );
  const pct = (value: number): number =>
    Math.max(0, (value / axis.max) * 100);
  const flagFrac = 0.05 / axis.max;

  return (
    <section
      className="section sec-malformed"
      aria-labelledby="malformed-title"
      data-section="malformed"
      id="malformed"
    >
      <div className="sechead">
        <div className="micro">04 · Malformed</div>
        <h2 id="malformed-title">Malformed output across the field</h2>
        <p className="cap">
          Attacked responses that stopped parsing as function calls,
          ranked by share. Bars run on one scale to{" "}
          {Math.round(axis.max * 100)} percent. Results past the flag
          line stand in the flagged band above with their split.
        </p>
      </div>

      <div className="malfrows">
        <div className="malfhead">
          <span className="micro faint">flag line, 5 percent malformed</span>
        </div>
        <div
          className="flagline"
          style={{
            left: `calc(190px + (100% - 254px) * ${flagFrac})`,
          }}
          aria-hidden="true"
        />
        {printed.map((row) => {
          const flagged = flaggedIds.has(row.run_id);
          const rate = row.malformed_rate ?? 0;
          const name = shortName(row);
          return (
            <div
              className="mrow"
              key={row.run_id}
              data-run-id={row.run_id}
              data-malformed={row.malformed_rate ?? ""}
            >
              <div className="nm">
                {name}
                {dupes.has(name) && (
                  <span className="sub">{wireWords(row.wire)}</span>
                )}
              </div>
              <div className="mtrack">
                <div
                  className={`mbar${flagged ? " amber" : ""}`}
                  style={{ width: `${pct(rate)}%` }}
                />
              </div>
              <div className={`mrate num${flagged ? " amber" : ""}`}>
                {fmtPct(rate)}
              </div>
            </div>
          );
        })}
      </div>

      {folded > 0 && (
        <p className="mal-fold">
          {fmtInt(folded)} results printed a malformed rate of 0.0 percent
          and are folded here rather than drawn as empty bars.
        </p>
      )}

      <p className="chart-id">
        Peira decision robustness board, malformed response rates. All{" "}
        {fmtInt(allRows.length)} results, worst first, flag line 5 percent.
        Dataset {versions.dataset}, updated {boardDateWords()}.
      </p>
    </section>
  );
}
