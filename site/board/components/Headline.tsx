import {
  boardGroups,
  displayCi,
  flipDecomposition,
  shortName,
  splitDisplayName,
  type BoardRow,
} from "@/lib/payload";
import { fmtCi, fmtInt, fmtPct } from "@/lib/format";
import { findingsData } from "@/lib/findings";
import VendorLogo from "@/components/VendorLogo";
import SplitBar from "@/components/SplitBar";

/**
 * The headline results, standing immediately under the hero.
 * The share card's numeral stack is the section's visual core:
 * the leader, the flagged lead with its split stated, and the
 * last ranked result, each as one large tabular numeral in the
 * share card's grammar of label, name, figure, and caption,
 * with the flagged lead's malformed share carried large inside
 * its split bar. The leader cards, the spread across every
 * ranked full suite result, and the price result in its
 * restrained form stand under the stack. Every figure derives
 * from the payload through the same data layer the rest of the
 * page reads.
 */

function fullName(row: BoardRow): string {
  return splitDisplayName(row.display_name).name;
}

export default function Headline() {
  const full = boardGroups().full;
  const leaders = full.slice(0, 3);
  const best = full[0];
  const worst = full[full.length - 1];
  const f = findingsData();
  const price = f.price;
  const mercury = f.split.mercury;
  const corrText = `${price.correlation < 0 ? "−" : ""}${Math.abs(price.correlation).toFixed(2)}`;
  const bestCi = displayCi(best);
  const worstCi = displayCi(worst);
  const bestDecomp = flipDecomposition(best);

  return (
    <section className="headline scene" aria-label="Headline results" id="results">
      <div className="sechead">
        <div className="micro eyebrow">
          <span className="eno">01</span> Results
        </div>
        <h2>
          The leader stands at {fmtPct(best.asr_conditional as number)},
          the flagged lead at {fmtPct(mercury.counted)}, the last
          ranked at {fmtPct(worst.asr_conditional as number)}
        </h2>
        <p className="cap">
          Three figures carry the board, in the share card's
          grammar. Lower is better on the ranked board.
        </p>
      </div>

      <div className="sharecard">
        <div className="stack-entry">
          <p className="micro">
            Rank 1 of {fmtInt(full.length)} · the full suite
          </p>
          <p className="stack-name">
            <VendorLogo row={best} size="card" /> {fullName(best)}
          </p>
          <p className="stack-num">{fmtPct(best.asr_conditional as number)}</p>
          <p className="stack-cap">
            Attack success
            {bestCi ? `, interval ${fmtCi(bestCi)}` : ""}.
            {bestDecomp
              ? bestDecomp.malformedFlips === 0
                ? ` None of its ${fmtInt(bestDecomp.flips)} counted flips went to malformed output.`
                : ` ${fmtInt(bestDecomp.malformedFlips)} of its ${fmtInt(bestDecomp.flips)} counted flips went to malformed output.`
              : ""}
          </p>
        </div>

        <div className="stack-entry">
          <p className="micro amber-text">Flagged · off the scale</p>
          <p className="stack-name">
            <VendorLogo row={mercury.row} size="card" />{" "}
            {fullName(mercury.row)}
          </p>
          <p className="stack-num">{fmtPct(mercury.counted)}</p>
          <SplitBar
            bare
            figuredInBar
            label=""
            figured=""
            malformedShare={mercury.malformedShare}
            malformedLabel={`Malformed output, ${fmtPct(mercury.malformedShare)} of counted flips`}
            genuineLabel={`Genuine flips, ${fmtPct(mercury.genuineShare)} of counted flips`}
          />
          <p className="stack-cap">
            Counted attack success. Of its {fmtInt(mercury.flips)}{" "}
            counted flips, {fmtInt(mercury.malformedFlips)} went to
            malformed output, and its genuine flips are{" "}
            {fmtPct(mercury.genuineRate)} of its eligible cases.
          </p>
        </div>

        <div className="stack-entry">
          <p className="micro">
            Rank {fmtInt(full.length)} of {fmtInt(full.length)} · the
            full suite
          </p>
          <p className="stack-name">
            <VendorLogo row={worst} size="card" /> {fullName(worst)}
          </p>
          <p className="stack-num">
            {fmtPct(worst.asr_conditional as number)}
          </p>
          <p className="stack-cap">
            Attack success
            {worstCi ? `, interval ${fmtCi(worstCi)}` : ""}. The
            highest counted rate on the ranked board.
          </p>
        </div>
      </div>

      <div className="leaders">
        {leaders.map((row, i) => {
          const ci = displayCi(row);
          return (
            <article className="leader-card" key={row.run_id}>
              <p className="micro">Rank {i + 1}</p>
              <p className="leader-name">
                <VendorLogo row={row} size="card" /> {shortName(row)}
              </p>
              <p className="leader-rate">
                {fmtPct(row.asr_conditional as number)}
              </p>
              <p className="leader-ci">
                Attack success
                {ci ? `, interval ${fmtCi(ci)}` : ""}
              </p>
            </article>
          );
        })}
      </div>
      <p className="headline-line">
        Across all {fmtInt(full.length)} ranked full suite results,
        attack success runs from {fmtPct(best.asr_conditional as number)}{" "}
        for {shortName(best)} to {fmtPct(worst.asr_conditional as number)}{" "}
        for {shortName(worst)}.
      </p>
      <p className="headline-line">
        Price does not predict robustness. Across the{" "}
        {fmtInt(price.pricedCount)} priced ranked results, the rank
        correlation between price and attack success is {corrText}, no
        useful relationship.
      </p>
    </section>
  );
}
