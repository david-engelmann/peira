import { fmtInt } from "@/lib/format";
import { scatterData } from "@/lib/scatterData";
import ScatterIsland from "./ScatterIsland";

/**
 * Cost against attack success, redesign. The section shell
 * renders on the server; the chart itself is a client island
 * fed by lib/scatterData's shaped point set, the same pattern
 * as the compare island, so the payload stays out of the
 * browser bundle. Every point is named in place and carries
 * its maker's mark in its maker's color; flagged results
 * keep the amber ring; the rail holds the results with no
 * chartable cost, with the recorded zero versus no cost
 * distinction stated in words in the caption.
 */

function joinNames(names: string[]): string {
  if (names.length <= 1) return names.join("");
  if (names.length === 2) return `${names[0]} and ${names[1]}`;
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

export default function Scatter() {
  const data = scatterData();

  return (
    <section className="section" aria-labelledby="scatter-title" data-section="scatter" id="cost">
      <p className="section-label">Cost</p>
      <h2 className="section-title" id="scatter-title">
        What robustness costs per run
      </h2>
      <p className="section-lede">
        Recorded cost for one full run against attack success, on the
        ranking's shared 0 to 30 percent scale. Every point is named and
        carries its maker's mark in its maker's color, and flagged
        results carry an amber ring.
      </p>

      <div className="scatter-wide">
        <ScatterIsland
          plotted={data.plotted}
          rail={data.rail}
          domain={data.domain}
        />
      </div>

      <div className="scatter-phone">
        <ScatterIsland
          plotted={data.plotted}
          rail={data.rail}
          domain={data.domain}
          phone
        />
      </div>

      <div className="chart-captions">
        <p>
          Cost is the recorded total for one full run, plotted on a log
          scale. A short tick pointing left from a point marks a lower
          bound, where some calls went unpriced and the true cost sits
          higher than the point.
        </p>
        <p>
          {fmtInt(data.railCount)} ranked models ran locally and hold
          no place on the cost axis, so they sit on the rail at the left
          at their attack success. {joinNames(data.zeroNames)} recorded a cost
          of $0.00, while {joinNames(data.noneNames)} recorded no cost at all.
          A recorded zero and no recorded cost are different facts, and
          the rail keeps them apart in words.
        </p>
        <p>
          The chart plots {fmtInt(data.plottedCount)} of the board's{" "}
          {fmtInt(data.populationCount + data.sliceCount)} results, with{" "}
          {fmtInt(data.railCount)} more on the rail. The{" "}
          {fmtInt(data.sliceCount)} guardrail slices are not plotted,
          since they ran on the abstain base and record no serving cost.
        </p>
      </div>
      <p className="chart-id">
        Peira decision robustness board, cost against attack success.{" "}
        {fmtInt(data.populationCount)} full suite results,{" "}
        {fmtInt(data.plottedCount)} plotted and{" "}
        {fmtInt(data.railCount)} on the rail. Dataset {data.dataset},
        updated {data.updated}.
      </p>
    </section>
  );
}
