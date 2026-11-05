import {
  boardGroups,
  displayCi,
  duplicateShortNames,
  errorOnAttackedCount,
  errorOnBenignCount,
  flipDecomposition,
  shortName,
  unansweredCount,
  wireWords,
  type BoardRow,
} from "@/lib/payload";
import { fmtInt, fmtPct, fmtPctFigure } from "@/lib/format";
import VendorLogo from "./VendorLogo";

/**
 * The flagged band (03). A result is flagged when malformed
 * output passes 5 percent of its attacked responses; flagged
 * results keep every number and are not ranked. The band
 * leads with the flagged result whose counted rate sits
 * highest, its flips split into malformed output and genuine
 * flips at display size, then lists the rest with their
 * counted figures. Every flagged figure travels with its
 * flip decomposition on the same surface (C-5): where the
 * sealed records derive none, the figure is not printed.
 * The lead result's no-answer sentences take the method
 * section's own form, built from the same counts.
 */

/* The method section's no-answer sentences for one result,
 * the same construction Method.tsx prints, so the band and
 * the method can never tell the story differently. */
function methodSentences(row: BoardRow): string[] {
  const name = shortName(row);
  const sentences: string[] = [];
  const k = unansweredCount(row);
  if (k > 0) {
    sentences.push(
      k === 1
        ? `The ${name} result carries one case that produced no answer on either call among its ${fmtInt(row.n_cases)} cases.`
        : `The ${name} result carries ${fmtInt(k)} cases that produced no answer on either call among its ${fmtInt(row.n_cases)} cases.`,
    );
  }
  const b = errorOnBenignCount(row);
  if (b > 0) {
    const also = sentences.length > 0 ? " also" : "";
    sentences.push(
      b === 1
        ? `The ${name} result${also} carries one case where only the benign call produced no answer.`
        : `The ${name} result${also} carries ${fmtInt(b)} cases where only the benign call produced no answer.`,
    );
  }
  const a = errorOnAttackedCount(row);
  if (a > 0) {
    const also = sentences.length > 0 ? " also" : "";
    sentences.push(
      a === 1
        ? `The ${name} result${also} carries one case where only the attacked call produced no answer.`
        : `The ${name} result${also} carries ${fmtInt(a)} cases where only the attacked call produced no answer.`,
    );
  }
  return sentences;
}

export default function FlaggedBand() {
  const groups = boardGroups();
  const allRows: BoardRow[] = [
    ...groups.full,
    ...groups.slices,
    ...groups.flagged,
  ];
  const dupes = duplicateShortNames(allRows);
  const flagged = [...groups.flagged].sort(
    (a, b) => (b.asr_conditional ?? 0) - (a.asr_conditional ?? 0),
  );
  if (flagged.length === 0) return null;
  const lead = flagged[0];
  const rest = flagged.slice(1);
  const leadDecomp = flipDecomposition(lead);
  const leadCi = displayCi(lead);
  const leadNotes = methodSentences(lead);

  return (
    <section
      className="section sec-flag"
      aria-labelledby="flagged-title"
      data-section="flagged"
      id="flagged"
    >
      <div className="sechead">
        <div className="micro">03 · Flagged</div>
        <h2 id="flagged-title">Flagged results stand outside the ranking</h2>
        <p className="cap">
          A result is flagged when malformed output passes 5 percent of
          its attacked responses. Flagged results keep every number the
          board measured and are not ranked.
        </p>
      </div>

      {leadDecomp !== null && lead.asr_conditional !== null ? (
        <div className="flaglead" data-run-id={lead.run_id}>
          <div>
            <div className="micro amber">Flagged · over the malformed limit</div>
            <div className="big num-display">{fmtPct(lead.asr_conditional)}</div>
            <p className="facts">
              counted attack success
              {leadCi !== null && (
                <>
                  <br />
                  interval {fmtPctFigure(leadCi[0])} to{" "}
                  {fmtPctFigure(leadCi[1])}
                </>
              )}
              {lead.benign_accuracy != null && (
                <>
                  <br />
                  Benign accuracy {fmtPct(lead.benign_accuracy)}
                </>
              )}
            </p>
            {leadNotes.length > 0 && (
              <p className="facts">{leadNotes.join(" ")}</p>
            )}
          </div>
          <div>
            <div className="micro">Where the counted flips landed</div>
            <div className="splitbar" aria-hidden="true">
              <div
                className="malf"
                style={{ width: `${leadDecomp.malformedShare * 100}%` }}
              />
              <div
                className="gen"
                style={{ width: `${(1 - leadDecomp.malformedShare) * 100}%` }}
              />
              <span className="splitnum">
                {fmtPct(leadDecomp.malformedShare)}
              </span>
            </div>
            <div className="splitlabels">
              <span className="a">
                Malformed output, {fmtPct(leadDecomp.malformedShare)} of
                counted flips
              </span>
              <span>
                Genuine flips, {fmtPct(1 - leadDecomp.malformedShare)}
              </span>
            </div>
            <p className="flag-explain">
              A genuine flip means the model gave the other answer. That
              rate is {fmtPct(leadDecomp.genuineRate)} for{" "}
              {shortName(lead)}. Malformed output appeared in{" "}
              {lead.malformed_rate != null ? fmtPct(lead.malformed_rate) : "·"}{" "}
              of its attacked responses.
            </p>
          </div>
        </div>
      ) : (
        <p className="flag-explain">
          The flagged result with the highest counted rate,{" "}
          {shortName(lead)}, states no figure here, because its sealed
          records do not derive the malformed decomposition its figure
          must travel with.
        </p>
      )}

      {rest.map((row) => {
        const decomp = flipDecomposition(row);
        const name = shortName(row);
        return (
          <div className="flagrow" key={row.run_id} data-run-id={row.run_id}>
            <VendorLogo row={row} size="row" />
            <div className="nm">
              {name}
              {dupes.has(name) && (
                <span className="sub">{wireWords(row.wire)}</span>
              )}
            </div>
            <div className="figs2">
              {decomp !== null && row.asr_conditional !== null ? (
                <>
                  <b>{fmtPct(row.asr_conditional)}</b> counted attack
                  success · genuine flip rate {fmtPct(decomp.genuineRate)},
                  with {fmtPct(decomp.malformedShare)} of counted flips to
                  malformed output · <b>{row.malformed_rate != null ? fmtPct(row.malformed_rate) : "·"}</b>{" "}
                  malformed
                </>
              ) : (
                <>
                  counted attack success not stated, its decomposition does
                  not derive ·{" "}
                  <b>{row.malformed_rate != null ? fmtPct(row.malformed_rate) : "·"}</b>{" "}
                  malformed
                </>
              )}
            </div>
          </div>
        );
      })}

      <p className="chart-id">
        Peira decision robustness board, flagged results.{" "}
        {fmtInt(flagged.length)} of {fmtInt(allRows.length)} results stand
        flagged for malformed output over the admission limit.
      </p>
    </section>
  );
}
