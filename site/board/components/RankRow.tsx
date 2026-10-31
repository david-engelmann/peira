import type { BoardRow, RankedRow } from "@/lib/payload";
import {
  shortName,
  wireWords,
  displayCi,
  flipDecomposition,
} from "@/lib/payload";
import {
  fmtPct,
  fmtCi,
  fmtCiCompact,
  fmtEce,
  fmtMs,
  fmtTax,
  fmtUsd,
} from "@/lib/format";
import WhiskerStrip from "./BarWhisker";
import VendorLogo from "./VendorLogo";

/**
 * Break opportunities after hyphens, so a long short name wraps
 * between its tokens and never mid-token at narrow widths. The
 * rendered text is unchanged; the checker reads the same string.
 */
function BreakableName({ name }: { name: string }) {
  const parts = name.split("-");
  return (
    <>
      {parts.map((part, i) => (
        <span key={i}>
          {i > 0 && "-"}
          {part}
          {i < parts.length - 1 && <wbr />}
        </span>
      ))}
    </>
  );
}

function rowAriaLabel(
  row: BoardRow,
  name: string,
  wireLine: string | null,
  status: string,
): string {
  const parts = [name];
  if (wireLine) parts.push(wireLine);
  parts.push(status);
  /* A flagged figure travels with its decomposition in the
   * accessible name too, as it does in the scatter titles:
   * the genuine flip rate and the malformed share of
   * counted flips, when the payload derives them. Where it
   * derives none, the label states no figure at all, the
   * suppression the compare section follows, so the name
   * cannot carry a bare flagged figure even if the printed
   * cell regresses. */
  const decomp = status === "flagged" ? flipDecomposition(row) : null;
  const bareFigure = status === "flagged" && decomp === null;
  if (row.asr_conditional !== null && !bareFigure) {
    parts.push(`attack success ${fmtPct(row.asr_conditional)}`);
  }
  const ci = displayCi(row);
  if (ci !== null && !bareFigure) {
    parts.push(`95% CI ${fmtCi(ci)}`);
  }
  if (row.benign_accuracy != null) {
    parts.push(`benign accuracy ${fmtPct(row.benign_accuracy)}`);
  }
  if (row.ece_attacked != null) {
    parts.push(`attacked ECE ${fmtEce(row.ece_attacked)}`);
  }
  if (row.robustness_tax != null) {
    parts.push(`robustness tax ${fmtTax(row.robustness_tax)}`);
  }
  if (row.malformed_rate != null) {
    parts.push(`malformed ${fmtPct(row.malformed_rate)}`);
  }
  if (decomp !== null) {
    parts.push(
      `genuine flip rate ${fmtPct(decomp.genuineRate)}, with ${fmtPct(decomp.malformedShare)} of counted flips to malformed output`,
    );
  }
  return parts.join(", ");
}

/**
 * The data line (owner layout, round 8 feedback). Mono micro
 * segments in a fixed order, each a label and a payload value.
 * A segment whose payload value is null is omitted, never
 * filled in. The row's case count is not one of the segments:
 * the suite's size is stated once, in the method section, and
 * repeating it on every row is noise (owner, 2026-10-25).
 */
function DataLine({ row }: { row: BoardRow }) {
  /* Loose null checks throughout: flagged rows omit some keys
   * entirely rather than carrying them as null. */
  const segs: Array<[string, string]> = [];
  if (row.benign_accuracy != null) {
    segs.push(["BENIGN", fmtPct(row.benign_accuracy)]);
  }
  if (row.ece_attacked != null) {
    segs.push(["ECE", fmtEce(row.ece_attacked)]);
  }
  if (row.robustness_tax != null) {
    segs.push(["TAX", fmtTax(row.robustness_tax)]);
  }
  if (row.latency_ms_p50_attacked != null) {
    segs.push(["LAT", fmtMs(row.latency_ms_p50_attacked)]);
  }
  if (row.total_cost_usd != null) {
    segs.push(["COST", fmtUsd(row.total_cost_usd)]);
  }
  return (
    <div className="data-line mono" aria-hidden="true">
      {segs.map(([k, v], i) => (
        <span key={k} className="dl-seg">
          {i > 0 && <span className="dl-sep">|</span>}
          <span className="dl-k">{k}</span> <span className="dl-v num">{v}</span>
        </span>
      ))}
    </div>
  );
}

/**
 * The right block. The headline rate at display size, and under
 * it the interval and the malformed rate. The precise figure
 * is the headline itself: printing it a second time in the
 * sub-line stated one fact twice (cycle 2, doctrine D11), so
 * the sub-line carries only what the headline does not.
 */
function ValueBlock({ row, flagged }: { row: BoardRow; flagged: boolean }) {
  const ci = displayCi(row);
  /* A flagged figure whose sealed records derive no
   * decomposition is not printed (C-5), the suppression the
   * compare section and the scatter follow. The cell reads
   * as not measured and the row's meta line states the
   * flagged standing, so no component on this row can print
   * the figure bare even if the render law regresses. */
  const suppressed =
    flagged && flipDecomposition(row) === null;
  if (row.asr_conditional === null || suppressed) {
    return (
      <div className={`cell-value${flagged ? " flagged" : ""}`}>
        <div className="not-measured">·</div>
      </div>
    );
  }
  return (
    <div className={`cell-value${flagged ? " flagged" : ""}`}>
      <div className="value-main num">{fmtPct(row.asr_conditional)}</div>
      {ci !== null && (
        <div className="value-sub mono" aria-hidden="true">
          {fmtCiCompact(ci)}
          {row.malformed_rate != null && (
            <> · MALFORMED {fmtPct(row.malformed_rate)}</>
          )}
        </div>
      )}
    </div>
  );
}

/** The flagged reason line. Ranked rows carry no meta line. */
function flaggedMeta(row: BoardRow): string {
  const base = `malformed ${row.malformed_rate !== null ? fmtPct(row.malformed_rate) : ""}, over the 5% admission limit`;
  /* The figure in the value cell is a flagged headline, so
   * its decomposition stands in the row with it (C-5): the
   * genuine flip rate and the malformed share of counted
   * flips, when the payload derives them. Where it does
   * not, no decomposition is stated at all. */
  const decomp = flipDecomposition(row);
  if (decomp === null) return base;
  return `${base}. Genuine flip rate ${fmtPct(decomp.genuineRate)}, with ${fmtPct(decomp.malformedShare)} of counted flips to malformed output`;
}

function NameBlock({
  row,
  showWire,
  flagged,
  href,
  aboveScale,
}: {
  row: BoardRow;
  showWire: boolean;
  flagged: boolean;
  href: string;
  /** A flagged rate past the shared axis end, stated in words. */
  aboveScale?: boolean;
}) {
  const name = shortName(row);
  return (
    <div className="cell-name">
      <div className="name-line">
        {flagged && <span className="flag-tag">FLAGGED</span>}
        <a className="name-link" href={href}>
          <BreakableName name={name} />
        </a>
      </div>
      {showWire && <div className="wire-line">{wireWords(row.wire)}</div>}
      {flagged && (
        <div className="meta-line flagged">
          {flaggedMeta(row)}
          {aboveScale &&
            ". Its rate sits above the chart's scale, so its whisker stops at the edge"}
        </div>
      )}
    </div>
  );
}

export function RankedRowView({
  row,
  variant,
  showWire,
  href,
  axisMax,
}: {
  row: RankedRow;
  variant: "full" | "slice";
  showWire: boolean;
  href: string;
  axisMax: number;
}) {
  const name = shortName(row);
  const wireLine = showWire ? wireWords(row.wire) : null;
  return (
    <div
      className="rank-row"
      data-run-id={row.run_id}
      role="group"
      aria-label={rowAriaLabel(row, name, wireLine, `rank ${row.rank}`)}
    >
      <div className="row-main">
        <div className="row-line1">
          <span className="cell-rank num">{row.rank}</span>
          <VendorLogo row={row} />
          <NameBlock row={row} showWire={showWire} flagged={false} href={href} />
        </div>
        <DataLine row={row} />
      </div>
      <ValueBlock row={row} flagged={false} />
      <WhiskerStrip row={row} variant={variant} axisMax={axisMax} />
    </div>
  );
}

export function FlaggedRowView({
  row,
  showWire,
  href,
  axisMax,
}: {
  row: BoardRow;
  showWire: boolean;
  href: string;
  axisMax: number;
}) {
  const name = shortName(row);
  const wireLine = showWire ? wireWords(row.wire) : null;
  const aboveScale =
    row.asr_conditional !== null && row.asr_conditional > axisMax;
  return (
    <div
      className="rank-row flagged"
      data-run-id={row.run_id}
      role="group"
      aria-label={rowAriaLabel(row, name, wireLine, "flagged")}
    >
      <div className="row-main">
        <div className="row-line1">
          <span className="cell-rank" />
          <VendorLogo row={row} />
          <NameBlock
            row={row}
            showWire={showWire}
            flagged={true}
            href={href}
            aboveScale={aboveScale}
          />
        </div>
        <DataLine row={row} />
      </div>
      <ValueBlock row={row} flagged={true} />
      <WhiskerStrip row={row} variant="flagged" axisMax={axisMax} />
    </div>
  );
}
