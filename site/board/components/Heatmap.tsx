import type { CSSProperties } from "react";
import {
  boardGroups,
  boardDateWords,
  boardVersions,
  shortName,
  wireWords,
  duplicateShortNames,
  type BoardRow,
  type RankedRow,
} from "@/lib/payload";
import { fmtInt, fmtPct, fmtCi } from "@/lib/format";
import {
  familiesOf,
  familyOrder,
  familyFullName,
  FAMILY_SHORT,
  rampCss,
  rampTextIsGround,
  fmtCellPct,
} from "@/lib/charts";

/**
 * Attack success by family, design system section 4.3. Every
 * result is a row in the ranking's three groups and order, and
 * every family is a column ordered by its mean attack success
 * across the field, highest first. Cells print their exact
 * whole percent value on the power 0.65 heat ramp; a family a
 * row never faced prints a middot on a ground tone cell, with
 * the reason stated in its group header and at the legend.
 */

function cellTitle(row: BoardRow, key: string): string {
  const fam = familiesOf(row).get(key);
  const name = familyFullName(key);
  if (!fam || fam.asr === null) {
    return `${name} was not measured for ${shortName(row)}`;
  }
  const ci = fam.asrCi95 ? `, 95 percent interval ${fmtCi(fam.asrCi95)}` : "";
  const base =
    fam.nEligible !== null ? `, ${fmtInt(fam.nEligible)} eligible cases` : "";
  return `${name} attack success ${fmtPct(fam.asr)}${ci}${base}`;
}

function HeatRow({
  row,
  order,
  flagged,
  dupes,
}: {
  row: BoardRow;
  order: string[];
  flagged: boolean;
  dupes: Set<string>;
}) {
  const fams = familiesOf(row);
  const name = shortName(row);
  const label = dupes.has(name)
    ? `${name} (${wireWords(row.wire)})`
    : name;
  return (
    <>
      <div className="heat-name" data-run-id={row.run_id}>
        {flagged && <span className="flag-tag">Flagged</span>}
        <span className="heat-name-text">{label}</span>
      </div>
      {order.map((key) => {
        const fam = fams.get(key);
        if (!fam || fam.asr === null) {
          return (
            <div
              key={key}
              className="heat-cell na"
              data-run-id={row.run_id}
              data-family={key}
              data-na="true"
              title={cellTitle(row, key)}
            >
              ·
            </div>
          );
        }
        const style: CSSProperties = {
          background: rampCss(fam.asr),
          color: rampTextIsGround(fam.asr)
            ? "var(--ground)"
            : "var(--ink-1)",
        };
        return (
          <div
            key={key}
            className="heat-cell num"
            style={style}
            data-run-id={row.run_id}
            data-family={key}
            data-asr={fam.asr}
            title={cellTitle(row, key)}
          >
            {fmtCellPct(fam.asr)}
          </div>
        );
      })}
    </>
  );
}

function GroupHead({
  label,
  caption,
}: {
  label: string;
  caption?: string;
}) {
  return (
    <div className="heat-group">
      <span className="heat-group-inner">
        <span className="group-label">{label}</span>
        {caption && <span className="heat-group-caption">{caption}</span>}
      </span>
    </div>
  );
}

export default function Heatmap() {
  const groups = boardGroups();
  const allRows: BoardRow[] = [
    ...groups.full,
    ...groups.slices,
    ...groups.flagged,
  ];
  const order = familyOrder(allRows);
  const dupes = duplicateShortNames(allRows);
  const sliceFamilies = groups.slices[0]
    ? familiesOf(groups.slices[0]).size
    : 0;
  const missing = order.length - sliceFamilies;
  const versions = boardVersions();
  const gridStyle: CSSProperties = {
    gridTemplateColumns: `var(--heat-name-w) repeat(${order.length}, minmax(56px, 1fr))`,
  };

  return (
    <section
      className="section"
      aria-labelledby="heatmap-title"
      data-section="heatmap"
      id="families"
    >
      <p className="section-label">Attack families</p>
      <h2 className="section-title" id="heatmap-title">
        Where the attacks land
      </h2>
      <p className="section-lede">
        Attack success by family for every result. Rows follow the
        ranking's groups and order. Columns run from the family that
        lands most often across the field to the one that lands least,
        and every cell prints its rate, so the shading never carries a
        number alone.
      </p>
      <p className="scroll-hint" aria-hidden="true">
        The families continue to the right
      </p>
      <div className="heat-scroll">
        <div className="heat-grid" style={gridStyle}>
          <div className="heat-corner">Model</div>
          {order.map((key) => (
            <div key={key} className="heat-head" data-family={key}>
              {FAMILY_SHORT[key] ?? familyFullName(key)}
            </div>
          ))}
          <GroupHead label="Full suite" />
          {groups.full.map((row: RankedRow) => (
            <HeatRow key={row.run_id} row={row} order={order} flagged={false} dupes={dupes} />
          ))}
          <GroupHead label="Flagged" />
          {groups.flagged.map((row) => (
            <HeatRow key={row.run_id} row={row} order={order} flagged dupes={dupes} />
          ))}
          <GroupHead
            label="Guardrail slices"
            caption={`The slices ran ${sliceFamilies} of the ${order.length} families. A dotted cell marks a family a slice never faced.`}
          />
          {groups.slices.map((row: RankedRow) => (
            <HeatRow key={row.run_id} row={row} order={order} flagged={false} dupes={dupes} />
          ))}
        </div>
      </div>
      <div className="heat-legend">
        <div className="heat-scale" aria-hidden="true">
          {[0, 0.1, 0.25, 0.5, 1].map((v) => (
            <span key={v} className="heat-swatch-wrap">
              <span
                className="heat-swatch"
                style={{ background: rampCss(v) }}
              />
              <span className="heat-swatch-label num">
                {Math.round(v * 100)}
              </span>
            </span>
          ))}
        </div>
        <p className="heat-legend-note">
          Attack success, percent. Shading rises faster than the value,
          so low rates separate. Judge cells by their printed numbers. A
          dotted cell on a ground tone marks a family that result never
          faced, {fmtInt(missing)} of the {fmtInt(order.length)} families
          for the guardrail slices.
        </p>
      </div>
      <p className="chart-id">
        Peira decision robustness board, attack success by family.{" "}
        {fmtInt(allRows.length)} results across {fmtInt(order.length)}{" "}
        families. Dataset {versions.dataset}, updated {boardDateWords()}.
      </p>
    </section>
  );
}
