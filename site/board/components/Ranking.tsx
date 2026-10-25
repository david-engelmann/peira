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
import { ASR_TICKS, axisPct } from "@/lib/chart";
import { RankedRowView, FlaggedRowView } from "./RankRow";

/**
 * The ranking, design system section 4.1. One chart in three
 * stacked groups on a shared axis. The full suite group leads,
 * the flagged strip follows, and the abstain slices close under
 * a header that states their case base. Ties are drawn as
 * brackets in the left rail and stated once, in the sentence
 * under the heading.
 */

function AxisStrip({ titled }: { titled: boolean }) {
  return (
    <div className="axis-row" aria-hidden="true">
      <div className="rail" />
      <div className="axis-grid">
        {titled && <div className="axis-title">Attack success, percent</div>}
        <div className="axis-cell">
          {ASR_TICKS.map((tick, i) => (
            <span
              key={tick}
              className={`axis-tick num${
                i === 0 ? " first" : i === ASR_TICKS.length - 1 ? " last" : ""
              }`}
              style={{ left: `${axisPct(tick)}%` }}
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
  axisTitled,
  allRows,
}: {
  id: string;
  label: string;
  caption: string | null;
  rows: RankedRow[];
  variant: "full" | "slice";
  dupes: Set<string>;
  axisTitled: boolean;
  allRows: BoardRow[];
}) {
  const bands = tieBands(rows);
  const segs = segments(rows, bands);
  return (
    <div className="rank-group" data-group={id}>
      <div className="group-head">
        <h3 className="group-label">{label}</h3>
        {caption && <p className="group-caption">{caption}</p>}
      </div>
      <AxisStrip titled={axisTitled} />
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
}: {
  rows: BoardRow[];
  dupes: Set<string>;
  allRows: BoardRow[];
}) {
  return (
    <div className="rank-group" data-group="flagged">
      <div className="group-head">
        <h3 className="group-label">Flagged</h3>
      </div>
      <AxisStrip titled={false} />
      {rows.map((row) => (
        <div className="band-block" key={row.run_id}>
          <div className="rail" aria-hidden="true" />
          <div className="rows">
            <FlaggedRowView
              row={row}
              showWire={dupes.has(shortName(row))}
              href={`/models/${modelSlug(row, allRows)}/`}
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
  const sliceCases = groups.slices[0]?.n_cases ?? 0;

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
        axisTitled={true}
        allRows={allRows}
      />
      <FlaggedGroup rows={groups.flagged} dupes={dupesByShort} allRows={allRows} />
      <RankedGroup
        id="slices"
        label="Guardrail slices"
        caption="Guardrail slices, measured on the abstain subset. Their rates sit apart from the full suite and the two groups are never interleaved."
        rows={groups.slices}
        variant="slice"
        dupes={dupesByShort}
        axisTitled={false}
        allRows={allRows}
      />
      <p className="chart-id">
        Peira decision robustness board, ranking. Dataset{" "}
        {boardVersions().dataset}, updated {boardDateWords()}.
      </p>
    </section>
  );
}
