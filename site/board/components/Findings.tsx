import {
  boardGroups,
  modelSlug,
  shortName,
  unansweredNote,
  type BoardRow,
} from "@/lib/payload";
import { fmtInt, fmtPct, fmtUsdExact } from "@/lib/format";
import { asrAxisFor } from "@/lib/chart";
import { findingsData } from "@/lib/findings";
import VendorLogo from "@/components/VendorLogo";
import SplitBar from "@/components/SplitBar";

/**
 * The findings, standing as evidence after the headline
 * results and the explorer. Four blocks, each one dominant
 * visual, a short claim, and one action that hands the reader
 * the finding's own population inside the explorer. Every
 * figure derives from the payload through lib/findings, which
 * fails the build where a derivation it needs comes back empty.
 */

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
  const guardTotal = Math.max(1, f.guards.flips);
  const leaderNote = unansweredNote(f.leader.row);

  return (
    <section className="findings scene" aria-label="Findings" id="findings">
      <div className="sechead">
        <div className="micro eyebrow">
          <span className="eno">03</span> Findings
        </div>
        <h2>The split, the wire, the guards, and the case never decided</h2>
        <p className="cap">
          The evidence behind the headline results. Each reading
          below derives from the same payload as every number on
          this page.
        </p>
      </div>

      <article className="finding" data-finding="split">
        <p className="micro amber-text">Finding · Malformed output</p>
        <h3>
          The ranked board flips on decisions. The flagged band flips
          on broken output.
        </h3>
        <SplitBar
          label={`Ranked · ${fmtInt(f.split.ranked.rows)} results`}
          figured={`${fmtInt(f.split.ranked.flips)} counted flips`}
          malformedShare={f.split.ranked.share}
          malformedLabel={`Malformed output, ${fmtPct(f.split.ranked.share)} of counted flips`}
          genuineLabel={`Genuine flips, ${fmtPct(1 - f.split.ranked.share)} of counted flips`}
        />
        <SplitBar
          label={`Flagged · ${fmtInt(f.split.flagged.rows)} results`}
          figured={`${fmtInt(f.split.flagged.flips)} counted flips`}
          malformedShare={f.split.flagged.share}
          malformedLabel={`Malformed output, ${fmtPct(f.split.flagged.share)} of counted flips`}
          genuineLabel={`Genuine flips, ${fmtPct(1 - f.split.flagged.share)} of counted flips`}
        />
        <SplitBar
          label={`${shortName(f.split.mercury.row)} · the extreme`}
          figured={`${fmtInt(f.split.mercury.flips)} counted flips`}
          figuredInBar
          malformedShare={f.split.mercury.malformedShare}
          malformedLabel={`Malformed output, ${fmtPct(f.split.mercury.malformedShare)} of counted flips`}
          genuineLabel={`Genuine flips, ${fmtPct(f.split.mercury.genuineShare)} of counted flips`}
        />
        <p className="f-copy">
          Mercury alone counted {fmtInt(f.split.mercury.flips)} flips,
          and {fmtInt(f.split.mercury.malformedFlips)} of them went to
          malformed output. Its genuine flips are{" "}
          {fmtPct(f.split.mercury.genuineRate)} of its eligible cases.
          No ranked result has malformed output as
          the majority of its counted flips. The highest malformed
          rate on the ranked board is{" "}
          {fmtPct(f.split.rankedMaxMalformedRate)}.
        </p>
        <a
          className="f-action"
          href={`#explorer?pop=all&mode=rank&sort=asr&sel=${mercurySlug}&open=1`}
        >
          Read this in the explorer
        </a>
      </article>

      <article className="finding" data-finding="wire">
        <p className="micro">Finding · The harness</p>
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
              </div>
              <p className="wiretrack-sub">
                Interval {fmtPct(t.ci[0])} to {fmtPct(t.ci[1])} ·
                malformed {fmtPct(t.malformed)}
                {t.cost !== null ? ` · ${fmtUsdExact(t.cost)} a run` : ""}
              </p>
            </div>
          ))}
          <p className="wiretrack-gap">
            <span className="rn">
              {(f.wire.gap * 100).toFixed(1)} points
            </span>{" "}
            apart, with the intervals overlapping
          </p>
        </div>
        <p className="f-copy">
          The same model ran the same suite through two OpenAI wires.
          Only the wire changed, so take the gap as the size of the
          harness effect.
        </p>
        <a
          className="f-action"
          href={`#explorer?pop=full&mode=rank&q=${encodeURIComponent(f.wire.name)}`}
        >
          Read this in the explorer
        </a>
      </article>

      <article className="finding" data-finding="guards">
        <p className="micro">Finding · Guard models</p>
        <h3>The guard rows answer a different question</h3>
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
            To abstain · {fmtInt(f.guards.toAbstain)}
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
          The six guard results ran the {fmtInt(f.guards.subsetCases)}{" "}
          cases where abstaining is a designed answer,{" "}
          {fmtPct(f.guards.subsetShare)} of the suite. Not one of their{" "}
          {fmtInt(f.guards.flips)} counted flips is a decision reversal,
          and none of the six carries a recorded serving cost.
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
          {shortName(f.leader.row)} stands first on the full suite at{" "}
          {fmtPct(f.leader.row.asr_conditional as number)}, measured
          through the Cursor agent harness.
        </p>
        {leaderNote !== null && <p className="f-copy">{leaderNote}</p>}
        {/* Record sourced, per the derivation record's adjudication
            on this finding. The refusal and the prompt class come
            from the seal adjudication record, not from the payload. */}
        <p className="f-copy">
          The harness's provider layer refused that case on both calls.
          It is a content moderation prompt the layer blocks outright,
          so no run through this harness could have measured it.
        </p>
        <p className="f-copy">
          Its benign accuracy of {fmtPct(f.leader.benign)} reads over
          the {fmtInt(f.leader.decidedBenign)} cases that produced an
          answer. The blocked case is in neither the hits nor the
          misses, and none of its {fmtInt(f.leader.flips)} counted
          flips went to malformed output.
        </p>
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
