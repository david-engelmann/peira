import {
  boardGroups,
  modelSlug,
  shortName,
  unansweredNote,
  type BoardRow,
} from "@/lib/payload";
import { fmtInt, fmtPct, fmtUsd, fmtUsdExact } from "@/lib/format";
import { asrAxisFor } from "@/lib/chart";
import { costDomain } from "@/lib/charts";
import { findingsData } from "@/lib/findings";
import VendorLogo from "@/components/VendorLogo";

/**
 * The findings opening. Five blocks, each one dominant visual,
 * a short claim, and one action that hands the reader the
 * finding's own population inside the explorer. Every figure
 * derives from the payload through lib/findings, which fails
 * the build where a derivation it needs comes back empty.
 */

function SplitBar({
  label,
  figured,
  malformedShare,
  malformedLabel,
  genuineLabel,
}: {
  label: string;
  figured: string;
  malformedShare: number;
  malformedLabel: string;
  genuineLabel: string;
}) {
  const malformedPct = Math.max(0, Math.min(100, malformedShare * 100));
  return (
    <div className="splitbar">
      <div className="splitbar-head">
        <span className="micro">{label}</span>
        <span className="splitbar-figured">{figured}</span>
      </div>
      <div className="splitbar-track" role="img" aria-label={`${malformedLabel}, ${genuineLabel}`}>
        <span className="seg genuine" style={{ width: `${100 - malformedPct}%` }} />
        <span className="seg malformed" style={{ width: `${malformedPct}%` }} />
      </div>
      <div className="splitbar-labels">
        <span>{genuineLabel}</span>
        <span className="amber-text">{malformedLabel}</span>
      </div>
    </div>
  );
}

export default function Findings() {
  const f = findingsData();
  const groups = boardGroups();
  const allRows: BoardRow[] = [
    ...groups.full,
    ...groups.slices,
    ...groups.flagged,
  ];
  const mercurySlug = modelSlug(f.split.mercury.row, allRows);
  const leaderSlug = modelSlug(f.leader.row, allRows);
  const worst = Math.max(...groups.full.map((r) => r.asr_conditional ?? 0));
  const axis = asrAxisFor(worst);
  const [costLo, costHi] = costDomain([
    f.price.jev.cost,
    f.price.priciest.cost,
    f.price.cheapest.cost,
  ]);
  const costPos = (v: number) =>
    ((Math.log10(v) - Math.log10(costLo)) /
      (Math.log10(costHi) - Math.log10(costLo))) *
    100;
  const corrText = `${f.price.correlation < 0 ? "−" : ""}${Math.abs(f.price.correlation).toFixed(2)}`;
  const guardTotal = Math.max(1, f.guards.flips);
  const leaderNote = unansweredNote(f.leader.row);
  const wireLo = Math.min(...f.wire.tracks.map((t) => t.asr));
  const wireHi = Math.max(...f.wire.tracks.map((t) => t.asr));

  return (
    <section className="findings" aria-label="Findings">
      <div className="sechead" id="findings">
        <div className="micro">Findings</div>
        <h2>What the numbers mean</h2>
        <p className="cap">
          Each reading below derives from the same payload as every
          number under it.
        </p>
      </div>

      <article className="finding" data-finding="split">
        <p className="micro amber-text">Finding · The split</p>
        <h3>
          The ranked board flips on decisions, the flagged band on
          broken output.
        </h3>
        <SplitBar
          label={`Ranked · ${fmtInt(f.split.ranked.rows)}`}
          figured={`${fmtInt(f.split.ranked.flips)} flips · ${fmtInt(f.split.ranked.malformed)} malformed`}
          malformedShare={f.split.ranked.share}
          malformedLabel={`Malformed ${fmtPct(f.split.ranked.share)}`}
          genuineLabel={`Genuine ${fmtPct(1 - f.split.ranked.share)}`}
        />
        <SplitBar
          label={`Flagged · ${fmtInt(f.split.flagged.rows)}`}
          figured={`${fmtInt(f.split.flagged.flips)} flips · ${fmtInt(f.split.flagged.malformed)} malformed`}
          malformedShare={f.split.flagged.share}
          malformedLabel={`Malformed ${fmtPct(f.split.flagged.share)}`}
          genuineLabel={`Genuine ${fmtPct(1 - f.split.flagged.share)}`}
        />
        <SplitBar
          label={shortName(f.split.mercury.row)}
          figured={`counted ${fmtPct(f.split.mercury.counted)}`}
          malformedShare={f.split.mercury.malformedShare}
          malformedLabel={`Malformed output, ${fmtPct(f.split.mercury.malformedShare)} of counted flips`}
          genuineLabel={`Genuine flips, ${fmtPct(f.split.mercury.genuineShare)}, genuine rate ${fmtPct(f.split.mercury.genuineRate)}`}
        />
        <p className="f-copy">
          No ranked result is majority malformed. Highest malformed
          rate {fmtPct(f.split.rankedMaxMalformedRate)}.
        </p>
        <a
          className="f-action"
          href={`#explorer?pop=all&mode=rank&sort=asr&sel=${mercurySlug}&open=1`}
        >
          Read this in the explorer
        </a>
      </article>

      <article className="finding" data-finding="wire">
        <p className="micro">Finding · Harness</p>
        <h3>One model, two wires, two readings</h3>
        <div className="wiretracks">
          {f.wire.tracks.map((t) => (
            <div className="wiretrack" key={t.row.run_id}>
              <div className="wiretrack-head">
                <span className="micro">
                  {f.wire.name} · {t.wire}
                </span>
                <span className="rn">{fmtPct(t.asr)}</span>
              </div>
              <div className="wiretrack-line">
                <span
                  className="whisker"
                  style={{
                    left: `${(t.ci[0] / axis.max) * 100}%`,
                    width: `${((t.ci[1] - t.ci[0]) / axis.max) * 100}%`,
                  }}
                />
                <span
                  className="point"
                  style={{ left: `${(t.asr / axis.max) * 100}%` }}
                />
                <span
                  className="mtick"
                  style={{ left: `${(t.malformed / axis.max) * 100}%` }}
                  aria-hidden="true"
                />
              </div>
              <p className="wiretrack-sub">
                Interval {fmtPct(t.ci[0])} to {fmtPct(t.ci[1])} ·
                malformed {fmtPct(t.malformed)}
                {t.cost !== null ? ` · ${fmtUsdExact(t.cost)}` : ""}
              </p>
            </div>
          ))}
          <div className="wirebracket" aria-hidden="true">
            <span
              className="wirebracket-line"
              style={{
                left: `${(wireLo / axis.max) * 100}%`,
                width: `${((wireHi - wireLo) / axis.max) * 100}%`,
              }}
            />
            <span
              className="wirebracket-label"
              style={{ left: `${(wireHi / axis.max) * 100}%` }}
            >
              {(f.wire.gap * 100).toFixed(1)} points
            </span>
          </div>
        </div>
        <p className="f-copy">
          The same model ran the same suite through two {f.wire.vendor}{" "}
          wires. The intervals overlap, so the gap is the size of the
          harness effect.
        </p>
        <a
          className="f-action"
          href={`#explorer?pop=full&mode=rank&q=${encodeURIComponent(f.wire.name)}`}
        >
          Read this in the explorer
        </a>
      </article>

      <article className="finding" data-finding="price">
        <p className="micro">Finding · Cost</p>
        <h3>Price shows no useful relationship</h3>
        <div className="costpair">
          {[
            {
              row: f.price.jev.row,
              cost: f.price.jev.cost,
              asr: f.price.jev.asr,
            },
            {
              row: f.price.priciest.row,
              cost: f.price.priciest.cost,
              asr: f.price.priciest.asr,
            },
          ].map((a) => (
            <div className="costrow" key={a.row.run_id}>
              <span className="costrow-name">
                <VendorLogo row={a.row} size="mini" /> {shortName(a.row)}
              </span>
              <span className="costrow-track">
                <span
                  className="costrow-bar"
                  style={{ width: `${Math.max(2, costPos(a.cost))}%` }}
                />
              </span>
              <span className="costrow-fig">
                {fmtUsd(a.cost)} a run · {fmtPct(a.asr)}
              </span>
            </div>
          ))}
          <p className="costrow-multiple">
            {fmtInt(Math.round(f.price.multiple))}× the price
          </p>
          <p className="corr">
            <span className="corr-num">{corrText}</span>
            <span className="micro">
              Rank correlation · no useful relationship ·{" "}
              {fmtInt(f.price.pricedCount)} priced
            </span>
          </p>
        </div>
        <p className="f-copy">
          {shortName(f.price.jev.row)} stands {ordinal(f.price.jev.rank)}{" "}
          of {fmtInt(groups.full.length)} at {fmtUsd(f.price.jev.cost)}.
          {fmtInt(f.price.hundredFold.count)} results cost at least a
          hundred times more. {fmtInt(f.price.hundredFold.flippedMore)}{" "}
          flipped more
          {f.price.hundredFold.flippedLess.length > 0
            ? `, and ${f.price.hundredFold.flippedLess.map((r) => `${r.name} flipped less at ${fmtUsd(r.cost)}`).join(", ")}`
            : ""}
          . The cheapest priced flipped {fmtPct(f.price.cheapest.asr)}.
        </p>
        <a
          className="f-action"
          href="#explorer?pop=full&mode=chart&frontier=1&cost=priced"
        >
          Read this in the explorer
        </a>
      </article>

      <article className="finding" data-finding="guards">
        <p className="micro">Finding · Guard models</p>
        <h3>Guard rows answer a different question</h3>
        <div
          className="anatomy"
          role="img"
          aria-label={`${fmtInt(f.guards.flips)} counted flips, ${fmtInt(f.guards.reversals)} reversals, ${fmtInt(f.guards.toAbstain)} to abstain, ${fmtInt(f.guards.untyped)} untyped`}
        >
          <span className="anat-slot empty">
            Reversals · {fmtInt(f.guards.reversals)}
          </span>
          <span
            className="anat-slot abstain"
            style={{ width: `${(f.guards.toAbstain / guardTotal) * 100}%` }}
          >
            Abstain · {fmtInt(f.guards.toAbstain)}
          </span>
          <span
            className="anat-slot untyped"
            style={{ width: `${(f.guards.untyped / guardTotal) * 100}%` }}
          >
            Untyped · {fmtInt(f.guards.untyped)}
          </span>
        </div>
        <ul className="guardlines">
          {f.guards.rows.map((row) => (
            <li key={row.run_id}>
              <VendorLogo row={row} size="mini" />
              <span>{shortName(row)}</span>
              <span className="rn">
                {row.asr_conditional !== null ? fmtPct(row.asr_conditional) : "·"}
              </span>
            </li>
          ))}
        </ul>
        <p className="f-copy">
          The {fmtInt(f.guards.rows.length)} guard results ran{" "}
          {fmtInt(f.guards.subsetCases)} of the suite's{" "}
          {fmtInt(f.guards.fullCases)} cases, where abstaining is a
          designed answer. None of their {fmtInt(f.guards.flips)}{" "}
          counted flips is a reversal. None has a recorded cost.
        </p>
        <a className="f-action" href="#explorer?pop=guards&mode=rank">
          Read this in the explorer
        </a>
      </article>

      <article className="finding disclosure" data-finding="leader">
        <p className="micro">Disclosed error · One case</p>
        <h3>One case on this board was never decided</h3>
        <p className="f-copy">
          <VendorLogo row={f.leader.row} size="mini" />{" "}
          {shortName(f.leader.row)} stands first of{" "}
          {fmtInt(f.leader.population)} on the full suite, measured
          through the {f.leader.harness}.
        </p>
        <div className="leaderfigs">
          <div>
            <span className="micro">Attack success</span>
            <strong className="rn">
              {fmtPct(f.leader.row.asr_conditional as number)}
            </strong>
            <span className="rsub">
              interval {fmtPct(f.leader.ci[0])} to {fmtPct(f.leader.ci[1])}
            </span>
          </div>
          <div>
            <span className="micro">Flips</span>
            <strong className="rn">{fmtInt(f.leader.flips)}</strong>
            <span className="rsub">
              {fmtInt(f.leader.malformedFlips)} to malformed output
            </span>
          </div>
          <div>
            <span className="micro">Benign accuracy</span>
            <strong className="rn">{fmtPct(f.leader.benign)}</strong>
            <span className="rsub">
              over {fmtInt(f.leader.decidedBenign)} cases
            </span>
          </div>
        </div>
        <div className="f-panel">
          {leaderNote !== null && <p className="f-copy">{leaderNote}</p>}
          {/* Record sourced, per the derivation record's adjudication
              on this finding. The refusal and the prompt class come
              from the seal adjudication record, not from the payload. */}
          <p className="f-copy">
            The provider layer refused that case on both calls, a
            content moderation prompt it blocks outright. No run
            through this harness could have measured it.
          </p>
          <p className="f-copy">
            The blocked case stands in neither the hits nor the
            misses of that benign accuracy.
          </p>
        </div>
        <a
          className="f-action"
          href={`#explorer?pop=full&mode=rank&sel=${leaderSlug}&open=1`}
        >
          Read this in the explorer
        </a>
      </article>
    </section>
  );
}

function ordinal(n: number): string {
  const s = ["th", "st", "nd", "rd"];
  const v = n % 100;
  return n + (s[(v - 20) % 10] || s[v] || s[0]);
}
