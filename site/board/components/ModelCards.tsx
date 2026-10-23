import {
  boardGroups,
  boardDateWords,
  boardVersions,
  taxBenchmarks,
  shortName,
  wireWords,
  displayCi,
  duplicateShortNames,
  modelSlug,
  type BoardRow,
  type RankedRow,
} from "@/lib/payload";
import {
  fmtInt,
  fmtPct,
  fmtCiCompact,
  fmtUsd,
} from "@/lib/format";
import { familyOrder } from "@/lib/charts";
import { costStateOf } from "@/lib/cards";
import ModelCard, { type CardKind } from "./ModelCard";
import CardControls from "./CardControls";

/**
 * Model detail, design system sections 2.2 and 4.5. The 36
 * full cards leave the page flow: in their place an index of
 * collapsed rows in the ranking's three groups, each showing
 * the five numbers a scanning reader compares, and each opening
 * its full card in place. The card is a native details element,
 * so its text is in the static page and it opens with no
 * JavaScript. Index rows anchor to the top of the index and
 * card anchors land on the card header (the summary), never on
 * the first field row (foundation items 8 and 9); the details
 * element carries the anchor and the scroll margin.
 */

function IndexSummary({
  row,
  rank,
  kind,
  dupes,
}: {
  row: BoardRow;
  rank: number | null;
  kind: CardKind;
  dupes: Set<string>;
}) {
  const name = shortName(row);
  const ci = displayCi(row);
  const cost = costStateOf(row);
  const label = [
    name,
    dupes.has(name) ? wireWords(row.wire) : null,
    kind === "flagged" ? "flagged" : `rank ${rank}`,
    row.asr_conditional !== null
      ? `attack success ${fmtPct(row.asr_conditional)}`
      : null,
    row.benign_accuracy !== null
      ? `benign accuracy ${fmtPct(row.benign_accuracy)}`
      : null,
    row.malformed_rate !== null
      ? `malformed ${fmtPct(row.malformed_rate)}`
      : null,
  ]
    .filter(Boolean)
    .join(", ");
  return (
    <summary
      className="index-row"
      data-index-for={row.run_id}
      aria-label={`${label}. Show the full card`}
    >
      <span className="idx-line1">
        {kind === "flagged" ? (
          <span className="flag-tag">Flagged</span>
        ) : (
          <span className="cell-rank num">{rank}</span>
        )}
        <span className="idx-name">
          {name}
          {dupes.has(name) && (
            <span className="wire-line"> {wireWords(row.wire)}</span>
          )}
        </span>
        <span className="idx-toggle" aria-hidden="true">
          Details
        </span>
      </span>
      <span className="idx-line2 mono" aria-hidden="true">
        <span className="dl-seg">
          <span className="dl-k">ASR</span>{" "}
          <span className="dl-v num">
            {row.asr_conditional !== null
              ? `${fmtPct(row.asr_conditional)}${ci ? ` ${fmtCiCompact(ci)}` : ""}`
              : "·"}
          </span>
        </span>
        <span className="dl-seg">
          <span className="dl-sep">|</span>
          <span className="dl-k">BENIGN</span>{" "}
          <span className="dl-v num">
            {row.benign_accuracy !== null ? fmtPct(row.benign_accuracy) : "·"}
          </span>
        </span>
        <span className="dl-seg">
          <span className="dl-sep">|</span>
          <span className="dl-k">MALFORMED</span>{" "}
          <span className="dl-v num">
            {row.malformed_rate !== null ? fmtPct(row.malformed_rate) : "·"}
          </span>
        </span>
        <span className="dl-seg">
          <span className="dl-sep">|</span>
          <span className="dl-k">COST</span>{" "}
          <span className="dl-v num">
            {cost.kind === "amount" && fmtUsd(cost.value)}
            {cost.kind === "lower-bound" && `≥ ${fmtUsd(cost.value)}`}
            {cost.kind === "local" && "served locally"}
            {cost.kind === "unrecorded" && "no cost recorded"}
          </span>
        </span>
      </span>
    </summary>
  );
}

export default function ModelCards() {
  const groups = boardGroups();
  const benchmarks = taxBenchmarks(groups);
  const allRows: BoardRow[] = [
    ...groups.full,
    ...groups.slices,
    ...groups.flagged,
  ];
  const dupes = duplicateShortNames(allRows);
  const familyKeys = familyOrder(allRows);
  const sliceCases = groups.slices[0]?.n_cases ?? 0;
  const versions = boardVersions();

  const renderItem = (row: BoardRow, rank: number | null, kind: CardKind) => (
    <details
      className="model-item"
      key={row.run_id}
      id={`model-${modelSlug(row, allRows)}`}
      data-card-for={row.run_id}
    >
      <IndexSummary row={row} rank={rank} kind={kind} dupes={dupes} />
      <ModelCard
        row={row}
        rank={rank}
        kind={kind}
        groupSize={
          kind === "full"
            ? groups.full.length
            : kind === "slice"
              ? groups.slices.length
              : 0
        }
        sliceCases={sliceCases}
        benchmarks={benchmarks}
        familyKeys={familyKeys}
        allRows={allRows}
        standalone={false}
      />
    </details>
  );

  return (
    <section
      className="section"
      aria-labelledby="models-title"
      data-section="models"
      id="models"
    >
      <p className="section-label">Model detail</p>
      <h2 className="section-title" id="models-title">
        Every result in full
      </h2>
      <p className="section-lede">
        One card per result, in the ranking's groups and order. Each
        index row carries the headline figures. Open a row for the
        full card, its family bars, its severity flips, and the
        provenance of its run. Every result also stands on its own
        page, linked from its card.
      </p>
      <CardControls />

      <div className="model-group" data-mgroup="full">
        <div className="group-head">
          <h3 className="group-label">Full suite</h3>
          <p className="group-caption">
            Every result in this group ran the full{" "}
            {fmtInt(groups.fullCases)} case suite.
          </p>
        </div>
        {groups.full.map((row: RankedRow) => renderItem(row, row.rank, "full"))}
      </div>

      <div className="model-group" data-mgroup="flagged">
        <div className="group-head">
          <h3 className="group-label">Flagged</h3>
        </div>
        {groups.flagged.map((row) => renderItem(row, null, "flagged"))}
      </div>

      <div className="model-group" data-mgroup="slices">
        <div className="group-head">
          <h3 className="group-label">Guardrail slices</h3>
          <p className="group-caption">
            Guardrail slices, measured on the {fmtInt(sliceCases)} case
            abstain subset.
          </p>
        </div>
        {groups.slices.map((row: RankedRow) =>
          renderItem(row, row.rank, "slice"),
        )}
      </div>

      <p className="chart-id">
        Peira decision robustness board, model detail. {fmtInt(allRows.length)}{" "}
        results, one card each. Dataset {versions.dataset}, updated{" "}
        {boardDateWords()}.
      </p>
    </section>
  );
}
