import type { InspectorDatum } from "@/lib/inspectorData";
import { fmtPctFigure } from "@/lib/format";
import Mark from "./Mark";

/**
 * The inspector, the one reading every surface gives a
 * selected result: identity and rank line, the figure grid
 * on the shared scales, the disclosure blocks verbatim from
 * the payload's note builders, the weakest family, and the
 * link to the result's own page. One anatomy for every
 * result, so a reader learns the order once. Presentational:
 * the islands that own selection render it with the datum
 * lib/inspectorData shaped on the server.
 */
export default function Inspector({
  datum,
  axisMax,
  variant = "panel",
}: {
  datum: InspectorDatum;
  axisMax: number;
  /**
   * The panel variant is a selection reading inside the
   * board page. The page variant heads a result's own page,
   * where nothing is selected and the own page link would
   * point at the page itself.
   */
  variant?: "panel" | "page";
}) {
  const d = datum;
  return (
    <aside className="insp" aria-label={`Selected result, ${d.name}`} data-inspector-for={d.runId}>
      {variant === "panel" && (
        <div className="micro sel">
          <span className="tick" aria-hidden="true" />
          Selected result
        </div>
      )}
      <div className="ihead">
        <Mark mark={d.mark} size="card" />
        <div>
          <h3 className="iname">{d.name}</h3>
          <div className="isub">{d.subLine}</div>
        </div>
      </div>
      <div className={`rankline mono${d.kind === "flagged" ? " amber" : ""}`}>
        {d.rankLine}
      </div>
      <div className="figs">
        <div className="fig wide">
          <span className="fl">{d.asrLabel}</span>
          {d.whisker !== null && d.asrText !== null ? (
            <>
              <span className="track" aria-hidden="true">
                <span
                  className="ci"
                  style={{
                    left: `${d.whisker.lo}%`,
                    width: `${Math.max(0, d.whisker.hi - d.whisker.lo)}%`,
                  }}
                />
                <span className="pt" style={{ left: `${d.whisker.pt}%` }} />
              </span>
              <span className="vrow">
                <span className="v">{d.asrText}</span>
                {d.ci !== null && (
                  <span className="iv">
                    interval {fmtPctFigure(d.ci[0])} to {fmtPctFigure(d.ci[1])}
                  </span>
                )}
                <span className="axmax">{Math.round(axisMax * 100)}</span>
              </span>
            </>
          ) : (
            <span className="vrow">
              <span className="v not-measured">·</span>
              <span className="iv">not stated, its decomposition does not derive</span>
            </span>
          )}
        </div>
        <div className="fig wide">
          <span className="fl">Benign accuracy</span>
          {d.benignPct !== null && d.benignText !== null ? (
            <>
              <span className="track" aria-hidden="true">
                <span className="bar" style={{ width: `${d.benignPct}%` }} />
                {d.benignBest !== null && (
                  <span className="best" style={{ left: `${d.benignBest.pct}%` }} />
                )}
              </span>
              <span className="vrow">
                <span className="v">{d.benignText}</span>
                {d.benignBest !== null && (
                  <span className="iv">
                    {d.benignBest.name} marks the best at {d.benignBest.text}
                  </span>
                )}
                <span className="axmax">100</span>
              </span>
            </>
          ) : (
            <span className="vrow">
              <span className="v not-measured">·</span>
            </span>
          )}
        </div>
        <div className="fig">
          <span className="fl">Malformed</span>
          <span className="v">{d.malformedText ?? "·"}</span>
        </div>
        <div className="fig">
          <span className="fl">Attacked ECE</span>
          <span className="v">{d.eceText ?? "·"}</span>
        </div>
        <div className="fig">
          <span className="fl">Robustness tax</span>
          <span className="v">{d.taxText ?? "·"}</span>
          {d.tax === null && (
            <span className="iv">
              {d.kind === "full" ? "not carried" : "slices and flagged results carry none"}
            </span>
          )}
        </div>
        <div className="fig">
          <span className="fl">Median latency, attacked</span>
          <span className="v">{d.latencyText ?? "·"}</span>
        </div>
        <div className="fig">
          <span className="fl">Cost per run</span>
          <span className="v">{d.costText}</span>
          {d.costSub !== null && <span className="iv">{d.costSub}</span>}
        </div>
      </div>
      {d.flaggedReason !== null && (
        <p className="disc flagged">{d.flaggedReason}</p>
      )}
      {d.sliceNote !== null && <p className="disc">{d.sliceNote}</p>}
      {d.unanswered !== null && <p className="disc">{d.unanswered}</p>}
      {d.singleCall !== null && <p className="disc">{d.singleCall}</p>}
      {d.weakestFamily !== null && (
        <p className="weakest">
          Weakest family, {d.weakestFamily.name}, at {d.weakestFamily.text}.
        </p>
      )}
      {variant === "panel" && (
        <p className="ownpage-line">
          <a className="ownpage" href={d.href}>
            This result on its own page
          </a>
        </p>
      )}
    </aside>
  );
}
