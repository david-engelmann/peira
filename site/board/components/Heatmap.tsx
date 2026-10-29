import type { CSSProperties } from "react";
import {
  boardGroups,
  boardDateWords,
  boardVersions,
  shortName,
  wireWords,
  duplicateShortNames,
  flipDecomposition,
  familyFlipDecomposition,
  type BoardRow,
  type RankedRow,
  type FlipDecomposition,
} from "@/lib/payload";
import { fmtInt, fmtPct, fmtCi } from "@/lib/format";
import VendorLogo from "./VendorLogo";
import {
  familiesOf,
  familyOrder,
  familyFullName,
  FAMILY_CHIP,
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
 * row never faced prints the not measured mark (--) on a
 * ground tone cell, with the reason stated in its group header
 * and at the legend (doctrine D13). Under the phone
 * breakpoint the matrix restacks: each row's cells wrap under
 * its name as chips labeled with the family short name (held
 * in data-fam-short for the stylesheet's generated label), so
 * every family stays present and named with nothing off
 * canvas (D7, D8).
 *
 * A flagged row's figures carry their malformed decomposition
 * on this surface (C-5): every flagged cell title states the
 * family's genuine flip rate and the malformed share of its
 * counted flips, the flagged group header points at the notes
 * under the grid, and the notes state each flagged result's
 * whole-row decomposition. A flagged family whose records do
 * not derive a decomposition prints no figure here at all:
 * its cell is suppressed to the not measured mark, and its
 * title says the figure is not stated and why.
 */

function cellTitle(
  row: BoardRow,
  key: string,
  flagged: boolean,
  famDecomp: Map<string, FlipDecomposition | null>,
): string {
  const fam = familiesOf(row).get(key);
  const name = familyFullName(key);
  if (!fam || fam.asr === null) {
    return `${name} was not measured for ${shortName(row)}`;
  }
  const ci = fam.asrCi95 ? `, 95 percent interval ${fmtCi(fam.asrCi95)}` : "";
  const base =
    fam.nEligible !== null ? `, ${fmtInt(fam.nEligible)} eligible cases` : "";
  const figure = `${name} attack success ${fmtPct(fam.asr)}${ci}${base}`;
  if (!flagged) return figure;
  const d = famDecomp.get(key);
  if (d === undefined || d === null) {
    return `${name} attack success not stated for ${shortName(row)}, because the figure's malformed decomposition does not derive from the sealed records`;
  }
  if (d.flips === 0) return `${figure}, no counted flips`;
  return `${figure}, genuine flip rate ${fmtPct(d.genuineRate)}, with ${fmtPct(d.malformedShare)} of counted flips to malformed output`;
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
  const famDecomp = flagged
    ? familyFlipDecomposition(row)
    : new Map<string, FlipDecomposition | null>();
  const name = shortName(row);
  const label = dupes.has(name)
    ? `${name} (${wireWords(row.wire)})`
    : name;
  return (
    <>
      <div className="heat-name" data-run-id={row.run_id}>
        {flagged && <span className="flag-tag">Flagged</span>}
        <VendorLogo row={row} size="mini" />
        <span className="heat-name-text">{label}</span>
      </div>
      {order.map((key) => {
        const fam = fams.get(key);
        const famShort =
          FAMILY_CHIP[key] ?? FAMILY_SHORT[key] ?? familyFullName(key);
        if (!fam || fam.asr === null) {
          return (
            <div
              key={key}
              className="heat-cell na"
              data-run-id={row.run_id}
              data-family={key}
              data-fam-short={famShort}
              data-na="true"
              title={cellTitle(row, key, flagged, famDecomp)}
            >
              --
            </div>
          );
        }
        if (flagged && (famDecomp.get(key) ?? null) === null) {
          return (
            <div
              key={key}
              className="heat-cell na"
              data-run-id={row.run_id}
              data-family={key}
              data-fam-short={famShort}
              data-suppressed="true"
              title={cellTitle(row, key, flagged, famDecomp)}
            >
              --
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
            data-fam-short={famShort}
            data-asr={fam.asr}
            title={cellTitle(row, key, flagged, famDecomp)}
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
  /* Column floors are the content's own (design cycle 3):
   * a column never narrows below its header's longest word,
   * so a header can wrap between words but never clips
   * mid-word, and any space above the floors divides
   * equally. The old flat 56 px floor let the two longest
   * headers (Crosslingual, Sycophancy) overflow their slots
   * wherever the equal share fell under their word width,
   * and priced the grid's minimum content above what the
   * tablet band's section can hold. */
  const gridStyle: CSSProperties = {
    gridTemplateColumns: `var(--heat-name-w) repeat(${order.length}, minmax(min-content, 1fr))`,
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
        ranking's groups and order, with {fmtInt(groups.full.length)} full suite results, {fmtInt(groups.flagged.length)} flagged results, and {fmtInt(groups.slices.length)} guardrail slices.
        Columns run from the family that lands most often across the
        field to the one that lands least, and every cell prints its
        rate, so the shading never carries a number alone.
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
          <GroupHead
            label="Flagged"
            caption="Not ranked. Each flagged result's decomposition is stated under the grid."
          />
          {groups.flagged.map((row) => (
            <HeatRow key={row.run_id} row={row} order={order} flagged dupes={dupes} />
          ))}
          <GroupHead
            label="Guardrail slices"
            caption={`The slices ran ${sliceFamilies} of the ${order.length} families. A cell marked "--" is a family a slice never faced.`}
          />
          {groups.slices.map((row: RankedRow) => (
            <HeatRow key={row.run_id} row={row} order={order} flagged={false} dupes={dupes} />
          ))}
        </div>
      </div>
      {groups.flagged.length > 0 && (
        <div className="chart-captions">
          {groups.flagged.map((row) => {
            const d = flipDecomposition(row);
            const name = dupes.has(shortName(row))
              ? `${shortName(row)} (${wireWords(row.wire)})`
              : shortName(row);
            return (
              <p key={row.run_id}>
                {d
                  ? `${name}, flagged and not ranked, attack success ${fmtPct(row.asr_conditional!)}, genuine flip rate ${fmtPct(d.genuineRate)}, with ${fmtPct(d.malformedShare)} of counted flips to malformed output.`
                  : `${name}, flagged and not ranked. Its attack success figures are not stated, because the sealed records do not derive their malformed decomposition.`}
              </p>
            );
          })}
        </div>
      )}
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
          cell marked "--" on a ground tone is a family that result
          never faced, {fmtInt(missing)} of the {fmtInt(order.length)}
          families for the guardrail slices.
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
