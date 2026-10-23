import {
  boardGroups,
  boardDateWords,
  boardVersions,
  shortName,
  wireWords,
  duplicateShortNames,
  type BoardRow,
} from "@/lib/payload";
import { fmtInt, fmtEce } from "@/lib/format";
import { calibrationRows, type CalibRow } from "@/lib/charts";

/**
 * Calibration panels, design system section 4.4. One small
 * panel per result plotting its attacked reliability bins,
 * stated confidence against the share of decisions the model
 * got right, on a 0 to 1 square with the diagonal drawn. A
 * point below the diagonal means the model claimed more
 * confidence than it earned on the attacked cases. Panels and
 * the left rail share one order, attacked ECE ascending, and
 * slice panels carry a tag and their case base so they do not
 * read as broken full suite panels (census C-07).
 */

const PW = 300;
const PH = 166;
const PLOT = { x0: 34, x1: 292, y0: 12, y1: 130 };
const r2 = (v: number) => Math.round(v * 100) / 100;

function Panel({
  entry,
  label,
}: {
  entry: CalibRow;
  label: string;
}) {
  const { row, data, isSlice } = entry;
  const classes = [
    "cal-panel",
    label.length + (isSlice ? 6 : 0) > 27 ? "long" : "",
  ]
    .filter(Boolean)
    .join(" ");
  const maxN = data ? Math.max(1, ...data.bins.map((b) => b.n)) : 1;
  const head = (
    <div className="cal-head">
      <p className="cal-name">
        <span className="cal-name-text">{label}</span>
        {isSlice && <span className="slice-tag">Slice</span>}
      </p>
      {data && data.ece !== null ? (
        <p className="cal-meta num">
          ECE {fmtEce(data.ece)} · Brier{" "}
          {data.brier !== null ? fmtEce(data.brier) : "—"} · n{" "}
          {data.n !== null ? fmtInt(data.n) : "—"}
          {isSlice && <> · base {fmtInt(row.n_cases)}</>}
        </p>
      ) : (
        <p className="cal-meta">Not measured</p>
      )}
    </div>
  );
  if (!data || !data.sufficient || data.bins.length === 0) {
    return (
      <article className={classes} id={`cal-${row.run_id}`} data-run-id={row.run_id}>
        {head}
        <div className="cal-empty">
          <p>
            Calibration was not measured for this result. The panel
            keeps its place in the error order so the gap stays
            visible.
          </p>
        </div>
      </article>
    );
  }
  const px = (f: number) => PLOT.x0 + f * (PLOT.x1 - PLOT.x0);
  const py = (o: number) => PLOT.y1 - o * (PLOT.y1 - PLOT.y0);
  /* Census C-07: a panel whose bins coincide says so on the
   * panel. Two slice panels qualify on this payload, the ones
   * whose 15 stated confidences span a tenth or less (the
   * granite-hap panel's bins all sit between 0.986 and 1.000).
   * The wider slice panels spread visibly and need no note. */
  const forecasts = data.bins.map((b) => b.meanForecast);
  const binsCoincide =
    isSlice &&
    forecasts.length > 0 &&
    Math.max(...forecasts) - Math.min(...forecasts) <= 0.1;
  return (
    <article className={classes} id={`cal-${row.run_id}`} data-run-id={row.run_id}>
      {head}
      {binsCoincide && (
        <p className="cal-note">
          The bins coincide because the model states nearly the
          same confidence on almost every case.
        </p>
      )}
      <svg
        viewBox={`0 0 ${PW} ${PH}`}
        className="cal-svg"
        role="img"
        aria-label={`Reliability bins for ${shortName(row)}, attacked cases`}
      >
        <line
          x1={PLOT.x0}
          y1={PLOT.y1}
          x2={PLOT.x1}
          y2={PLOT.y0}
          className="cal-diag"
          aria-hidden="true"
        />
        <line
          x1={PLOT.x0}
          y1={PLOT.y1}
          x2={PLOT.x1}
          y2={PLOT.y1}
          className="cal-axis"
          aria-hidden="true"
        />
        <line
          x1={PLOT.x0}
          y1={PLOT.y0}
          x2={PLOT.x0}
          y2={PLOT.y1}
          className="cal-axis"
          aria-hidden="true"
        />
        <g className="tk-y num" aria-hidden="true">
          {[0, 0.5, 1].map((v) => (
            <text key={v} x={PLOT.x0 - 5} y={r2(py(v) + 3.5)} textAnchor="end">
              {Math.round(v * 100)}
            </text>
          ))}
        </g>
        <g className="tk-x num" aria-hidden="true">
          {[0, 0.5, 1].map((v) => (
            <text key={v} x={r2(px(v))} y={PLOT.y1 + 16} textAnchor="middle">
              {Math.round(v * 100)}
            </text>
          ))}
        </g>
        {data.bins.map((b, i) => (
          <circle
            key={i}
            cx={r2(px(b.meanForecast))}
            cy={r2(py(b.meanOutcome))}
            r={r2(2 + Math.sqrt(b.n / maxN) * 2.5)}
            className="cal-dot"
            data-f={b.meanForecast}
            data-o={b.meanOutcome}
            data-n={b.n}
          >
            <title>
              {`Stated confidence ${Math.round(b.meanForecast * 100)} percent, right ${Math.round(b.meanOutcome * 100)} percent, ${fmtInt(b.n)} cases`}
            </title>
          </circle>
        ))}
      </svg>
    </article>
  );
}

export default function Calibration() {
  const groups = boardGroups();
  const allRows: BoardRow[] = [
    ...groups.full,
    ...groups.slices,
    ...groups.flagged,
  ];
  const dupes = duplicateShortNames(allRows);
  const entries = calibrationRows(allRows);
  const maxEce = Math.max(
    0.0001,
    ...entries.map((e) => e.data?.ece ?? e.row.ece_attacked ?? 0),
  );
  const versions = boardVersions();

  return (
    <section
      className="section"
      aria-labelledby="calibration-title"
      data-section="calibration"
      id="calibration"
    >
      <p className="section-label">Calibration</p>
      <h2 className="section-title" id="calibration-title">
        Whether stated confidence holds up
      </h2>
      <p className="section-lede">
        Each panel plots one result on its attacked cases. Stated
        confidence runs across and the share of decisions the model got
        right runs up, in 15 equal count bins. A point below the
        diagonal means the model claimed more confidence than it
        earned. Panels run from the lowest calibration error to the
        highest.
      </p>
      <div className="cal-layout">
        <nav className="cal-rail" aria-label="Results by calibration error">
          <p className="cal-rail-head">Results by attacked ECE</p>
          <ul className="cal-rail-list">
            {entries.map((e) => {
              const ece = e.data?.ece ?? e.row.ece_attacked;
              const name = shortName(e.row);
              const label = dupes.has(name)
                ? `${name} (${wireWords(e.row.wire)})`
                : name;
              return (
                <li key={e.row.run_id}>
                  <a
                    href={`#cal-${e.row.run_id}`}
                    className="cal-rail-link"
                    data-rail-for={e.row.run_id}
                  >
                    <span className="cal-rail-name">{label}</span>
                    <span className="cal-rail-ece num">
                      {ece !== null && ece !== undefined
                        ? fmtEce(ece)
                        : "—"}
                    </span>
                    <span className="cal-rail-bar" aria-hidden="true">
                      <span
                        style={{
                          width: `${(((ece ?? 0) / maxEce) * 100).toFixed(1)}%`,
                        }}
                      />
                    </span>
                  </a>
                </li>
              );
            })}
          </ul>
        </nav>
        <div className="cal-grid">
          {entries.map((e) => {
            const name = shortName(e.row);
            const label = dupes.has(name)
              ? `${name} (${wireWords(e.row.wire)})`
              : name;
            return (
              <Panel
                key={e.row.run_id}
                entry={e}
                label={label}
              />
            );
          })}
        </div>
      </div>
      <p className="chart-id">
        Peira decision robustness board, calibration. All{" "}
        {fmtInt(entries.length)} results, attacked arm, 15 bins each.
        Dataset {versions.dataset}, updated {boardDateWords()}.
      </p>
    </section>
  );
}
