import { fmtInt, fmtPct } from "@/lib/format";
import { scatterData } from "@/lib/scatterData";
import ScatterIsland from "./ScatterIsland";

/**
 * Cost against attack success, redesign. The section shell
 * renders on the server; the chart itself is a client island
 * fed by lib/scatterData's shaped point set, the same pattern
 * as the compare island, so the payload stays out of the
 * browser bundle. Every point is named: beside its disc
 * where the label solver seats it, in the plot's overflow
 * rows, or in the fitted list under the chart at widths
 * where the plot has no room left. Naming degrades in
 * tiers and never fails: no width renders a point unnamed
 * and no width throws. Every point carries its maker's mark
 * in its maker's color; flagged results keep the amber ring;
 * the rail holds the results with no chartable cost, with
 * the recorded zero versus no cost distinction stated in
 * words in the caption.
 *
 * The two readings under the lede are computed from the
 * payload by lib/scatterData (hardcode audit F1, F2). No
 * name, price or corner claim is written into this file:
 * when the population changes, the readings change with it
 * or the strip prints the two facts separately.
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
        ranking's shared scale, 0 to {Math.round(data.axis.max * 100)}{" "}
        percent. Every point is named and carries its maker's mark in
        its maker's color, and flagged results carry an amber ring.
      </p>

      <div className="scatter-readings">
        <p>
          {data.readings.priciestIsMostFlipped ? (
            <>
              The priciest run, {data.readings.priciest.label}{" "}
              {data.readings.priciest.costPhrase}, also
              flipped most of any ranked result{" "}
              {data.readings.rankedScope}, at{" "}
              {fmtPct(data.readings.mostFlippedRanked.asr!)}.
            </>
          ) : (
            <>
              The priciest run is {data.readings.priciest.label}{" "}
              {data.readings.priciest.costPhrase}. The
              ranked result that flipped most{" "}
              {data.readings.rankedScope} is{" "}
              {data.readings.mostFlippedRanked.label} at{" "}
              {fmtPct(data.readings.mostFlippedRanked.asr!)}.
            </>
          )}
        </p>
        <p>
          The toughest ranked result {data.readings.rankedScope},{" "}
          {data.readings.toughestRanked.label},
          flipped {fmtPct(data.readings.toughestRanked.asr!)}{" "}
          {data.readings.toughestRanked.costPhrase}. The
          cheapest run on the chart is {data.readings.cheapest.label}{" "}
          {data.readings.cheapest.costPhrase}.
        </p>
      </div>

      <div className="scatter-wide">
        <ScatterIsland
          plotted={data.plotted}
          rail={data.rail}
          domain={data.domain}
          axisMax={data.axis.max}
          ticks={data.axis.ticks}
        />
      </div>

      <div className="scatter-phone">
        <ScatterIsland
          plotted={data.plotted}
          rail={data.rail}
          domain={data.domain}
          axisMax={data.axis.max}
          ticks={data.axis.ticks}
          phone
        />
      </div>

      <div className="chart-captions">
        <p>
          Cost is the recorded total for one full run, plotted on a log
          scale. Where some calls went unpriced, the recorded cost is a
          lower bound and the true cost sits higher than the point. The
          point's own card says when it is a lower bound.
        </p>
        <p>
          {fmtInt(data.railCount)} results hold no place on the cost
          axis, because their recorded cost is $0.00 or no cost was
          recorded at all, so they sit on the rail at the left of the
          wide chart at their attack success, and on a phone they
          join the list under the plot, in attack success order.{" "}
          {joinNames(data.zeroNames)} recorded a cost
          of $0.00, while {joinNames(data.noneNames)} recorded no cost at all.
          A recorded zero and no recorded cost are different facts, and
          the rail keeps them apart in words.
        </p>
        {data.aboveScaleNames.length > 0 && (
          <p>
            {joinNames(data.aboveScaleNames)}{" "}
            {data.aboveScaleNames.length === 1 ? "sits" : "sit"} above
            the chart's 0 to {Math.round(data.axis.max * 100)} percent
            scale, so{" "}
            {data.aboveScaleNames.length === 1
              ? "its disc stands off the top of the plot rather than at a false position, and it is"
              : "their discs stand off the top of the plot rather than at false positions, and they are"}{" "}
            named with the chart's overflow entries instead.
          </p>
        )}
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
