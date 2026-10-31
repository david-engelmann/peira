import type { BoardRow, RankedRow } from "@/lib/payload";
import {
  boardGroups,
  boardDateWords,
  boardVersions,
  tieBands,
  duplicateShortNames,
  modelSlug,
  shortName,
} from "@/lib/payload";
import { fmtInt } from "@/lib/format";
import { asrAxisFor, axisPct, type AsrAxis } from "@/lib/chart";
import { RankedRowView, FlaggedRowView } from "./RankRow";

/**
 * The ranking, design system section 4.1. One chart in three
 * stacked groups on a shared axis. The full suite group leads,
 * the flagged strip follows, and the abstain slices close under
 * a header that states their case base. Ties are drawn as
 * brackets in the left rail and stated once, in the sentence
 * under the heading.
 */

function AxisStrip({
  title,
  axis,
}: {
  title: string | null;
  axis: AsrAxis;
}) {
  return (
    <div className="axis-row" aria-hidden="true">
      <div className="rail" />
      <div className="axis-grid">
        {title && <div className="axis-title">{title}</div>}
        <div className="axis-cell">
          {axis.ticks.map((tick, i) => (
            <span
              key={tick}
              className={`axis-tick num${
                i === 0 ? " first" : i === axis.ticks.length - 1 ? " last" : ""
              }`}
              style={{ left: `${axisPct(tick, axis.max)}%` }}
            >
              {Math.round(tick * 100)}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

type Segment =
  | { kind: "band"; rows: RankedRow[] }
  | { kind: "single"; row: RankedRow };

function segments(
  rows: RankedRow[],
  bands: Map<number, [number, number]>,
): Segment[] {
  const out: Segment[] = [];
  let i = 0;
  while (i < rows.length) {
    const band = bands.get(rows[i].rank);
    if (band && band[0] === rows[i].rank) {
      const members = rows.filter(
        (r) => r.rank >= band[0] && r.rank <= band[1],
      );
      out.push({ kind: "band", rows: members });
      i += members.length;
    } else {
      out.push({ kind: "single", row: rows[i] });
      i += 1;
    }
  }
  return out;
}

function RankedGroup({
  id,
  label,
  caption,
  rows,
  variant,
  dupes,
  axisTitle,
  allRows,
  axis,
}: {
  id: string;
  label: string;
  caption: string | null;
  rows: RankedRow[];
  variant: "full" | "slice";
  dupes: Set<string>;
  axisTitle: string | null;
  allRows: BoardRow[];
  axis: AsrAxis;
}) {
  const bands = tieBands(rows);
  const segs = segments(rows, bands);
  return (
    <div className="rank-group" data-group={id}>
      <div className="group-head">
        <h3 className="group-label">{label}</h3>
        {caption && <p className="group-caption">{caption}</p>}
      </div>
      <AxisStrip title={axisTitle} axis={axis} />
      {segs.map((seg, i) =>
        seg.kind === "band" ? (
          <div className="band-block" key={`band-${i}`}>
            <div className="rail" aria-hidden="true">
              <div className="rail-rule" />
              <div className="rail-label">tied</div>
            </div>
            <div className="rows">
              {seg.rows.map((row) => (
                <RankedRowView
                  key={row.run_id}
                  row={row}
                  variant={variant}
                  showWire={dupes.has(shortName(row))}
                  href={`/models/${modelSlug(row, allRows)}/`}
                  axisMax={axis.max}
                />
              ))}
            </div>
          </div>
        ) : (
          <div className="band-block" key={`single-${seg.row.run_id}`}>
            <div className="rail" aria-hidden="true" />
            <div className="rows">
              <RankedRowView
                row={seg.row}
                variant={variant}
                showWire={dupes.has(shortName(seg.row))}
                href={`/models/${modelSlug(seg.row, allRows)}/`}
                axisMax={axis.max}
              />
            </div>
          </div>
        ),
      )}
    </div>
  );
}

function FlaggedGroup({
  rows,
  dupes,
  allRows,
  axis,
}: {
  rows: BoardRow[];
  dupes: Set<string>;
  allRows: BoardRow[];
  axis: AsrAxis;
}) {
  return (
    <div className="rank-group" data-group="flagged">
      <div className="group-head">
        <h3 className="group-label">Flagged</h3>
      </div>
      <AxisStrip title={null} axis={axis} />
      {rows.map((row) => (
        <div className="band-block" key={row.run_id}>
          <div className="rail" aria-hidden="true" />
          <div className="rows">
            <FlaggedRowView
              row={row}
              showWire={dupes.has(shortName(row))}
              href={`/models/${modelSlug(row, allRows)}/`}
              axisMax={axis.max}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

export default function Ranking() {
  const groups = boardGroups();
  const allRows = [...groups.full, ...groups.slices, ...groups.flagged];
  const dupesByShort = duplicateShortNames(allRows);
  // duplicateShortNames keys by short name already.
  /* One axis for the whole page, derived from the ranked
   * population (lib/chart): the worst ranked rate across
   * the full suite and the slices, rounded up a step. The
   * cost scatter reads the same derivation from
   * lib/scatterData, so the two surfaces cannot drift. */
  const rankedRates = [...groups.full, ...groups.slices]
    .map((r) => r.asr_conditional)
    .filter((v): v is number => v !== null && v !== undefined);
  const axis = asrAxisFor(rankedRates.length ? Math.max(...rankedRates) : 0);
  return (
    <section className="section" aria-labelledby="ranking-title" id="ranking">
      <p className="section-label">Ranking</p>
      <h2 className="section-title" id="ranking-title">
        Which models are hardest to attack
      </h2>
      <p className="section-lede">
        Ranks follow point estimates, and rows joined by a bracket have
        overlapping 95 percent intervals and should be read as tied.
      </p>
      <p className="section-lede lede-pointer">
        Why {fmtInt(groups.flagged.length)} results are flagged stands
        with the <a href="#malformed">malformed chart</a> directly below.
      </p>

      <RankedGroup
        id="full"
        label="Full suite"
        caption="Every result in this group ran the full suite."
        rows={groups.full}
        variant="full"
        dupes={dupesByShort}
        axisTitle="Attack success, percent"
        allRows={allRows}
        axis={axis}
      />
      <FlaggedGroup
        rows={groups.flagged}
        dupes={dupesByShort}
        allRows={allRows}
        axis={axis}
      />
      <RankedGroup
        id="slices"
        label="Guardrail slices"
        caption="Guardrail slices, measured on the abstain subset. Their rates sit apart from the full suite and the two groups are never interleaved."
        rows={groups.slices}
        variant="slice"
        dupes={dupesByShort}
        axisTitle="Attack success, percent, abstain subset"
        allRows={allRows}
        axis={axis}
      />
      <p className="chart-id">
        Peira decision robustness board, ranking. Dataset{" "}
        {boardVersions().dataset}, updated {boardDateWords()}.
      </p>
    </section>
  );
}
