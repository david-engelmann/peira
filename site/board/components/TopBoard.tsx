"use client";

import { useState } from "react";
import type { RailRow, RailSegment, TopData } from "@/lib/topData";
import Inspector from "./Inspector";
import Mark from "./Mark";
import ScatterPanel, { WordsLine } from "./ScatterPanel";

/**
 * The instrument panel's top: the cost scatter (01) and the
 * ranking rail with its inspector (02), one island because
 * the two share a selection. Selecting a rail row, a scatter
 * disc, a rail band row, or a phone mini-row loads that
 * result into the inspector, and the scatter marks it with
 * the green ring. The rail's groups and tie segments come
 * shaped from the server (lib/topData); rows past the fold
 * stay in the page and are hidden until the fold opens, so
 * the fold is a reading device, never a data cut.
 */

function RowButton({
  row,
  selected,
  hidden,
  onSelect,
}: {
  row: RailRow;
  selected: boolean;
  hidden: boolean;
  onSelect: (runId: string) => void;
}) {
  return (
    <button
      type="button"
      className={`rrow${selected ? " sel" : ""}`}
      data-run-id={row.runId}
      aria-pressed={selected}
      aria-label={row.ariaLabel}
      hidden={hidden}
      onClick={() => onSelect(row.runId)}
    >
      <span className="rk num">{row.rank}</span>
      <Mark mark={row.mark} size="row" />
      <span className="nm">
        {row.name}
        {row.wire !== null && <span className="sub">{row.wire}</span>}
        {row.note !== null && <span className="note">{row.note}</span>}
        {row.singleNote !== null && (
          <span className="note">{row.singleNote}</span>
        )}
      </span>
      <span className="atk num">{row.asrText}</span>
      <span className="wtrack" aria-hidden="true">
        {row.whisker !== null && (
          <>
            <span
              className="wci"
              style={{
                left: `${row.whisker.lo}%`,
                width: `${Math.max(0, row.whisker.hi - row.whisker.lo)}%`,
              }}
            />
            <span className="wpt" style={{ left: `${row.whisker.pt}%` }} />
          </>
        )}
      </span>
      <span className="c num">{row.benignText ?? "·"}</span>
      <span className="c num">{row.eceText ?? "·"}</span>
      <span className="c num">{row.taxText ?? "·"}</span>
      <span className="c num cost">{row.costText}</span>
      <span className="rstats mono" aria-hidden="true">
        {row.asrText} atk · {row.benignText ?? "·"} ben ·{" "}
        {row.eceText ?? "·"} ece · {row.taxText ?? "·"} tax · {row.costText}
      </span>
    </button>
  );
}

function SegmentList({
  segments,
  foldAfter,
  expanded,
  selectedRunId,
  onSelect,
  counter,
}: {
  segments: RailSegment[];
  foldAfter: number;
  expanded: boolean;
  selectedRunId: string;
  onSelect: (runId: string) => void;
  counter: { n: number };
}) {
  return (
    <>
      {segments.map((seg, i) => {
        const rows = seg.kind === "band" ? seg.rows : [seg.row];
        const start = counter.n;
        counter.n += rows.length;
        const hidden = !expanded && start >= foldAfter;
        const body = rows.map((row) => (
          <RowButton
            key={row.runId}
            row={row}
            selected={row.runId === selectedRunId}
            hidden={hidden}
            onSelect={onSelect}
          />
        ));
        return seg.kind === "band" ? (
          <div className="band-block" key={`band-${i}`}>
            <div className="rail-gutter" aria-hidden="true">
              <div className="rail-rule" />
              <div className="rail-label">tied</div>
            </div>
            <div className="rows">{body}</div>
          </div>
        ) : (
          <div className="band-block" key={`single-${rows[0].runId}`}>
            <div className="rail-gutter" aria-hidden="true" />
            <div className="rows">{body}</div>
          </div>
        );
      })}
    </>
  );
}

export default function TopBoard({ data }: { data: TopData }) {
  const [selectedRunId, setSelectedRunId] = useState(data.defaultRunId);
  const [fullOpen, setFullOpen] = useState(false);
  const [sliceOpen, setSliceOpen] = useState(false);
  const datum = data.inspectors[selectedRunId] ?? data.inspectors[data.defaultRunId];
  const select = (runId: string) => {
    if (data.inspectors[runId]) setSelectedRunId(runId);
  };
  const fullCounter = { n: 0 };
  const sliceCounter = { n: 0 };

  return (
    <div className="topboard">
      <section
        className="section sec-scatter"
        aria-labelledby="scatter-title"
        data-section="scatter"
        id="cost"
      >
        <div className="sechead">
          <div className="micro">01 · Scatter</div>
          <h2 id="scatter-title">{data.scatter.titleText}</h2>
          <p className="cap">{data.scatter.caption}</p>
        </div>
        <div className="spanel">
          <div className="scatter-wide">
            <ScatterPanel
              view={data.scatter.wide}
              phone={false}
              selectedRunId={selectedRunId}
              onSelect={select}
            />
            <WordsLine view={data.scatter.wide} />
          </div>
          <div className="scatter-phone">
            <ScatterPanel
              view={data.scatter.phone}
              phone
              selectedRunId={selectedRunId}
              onSelect={select}
            />
            <div className="srail">
              {data.scatter.phoneRail.map((r) => (
                <button
                  type="button"
                  key={r.runId}
                  className={`srow${r.runId === selectedRunId ? " sel" : ""}`}
                  data-rail-for={r.runId}
                  aria-pressed={r.runId === selectedRunId}
                  aria-label={`${r.name}, attack success ${r.asrText}. Select this result.`}
                  onClick={() => select(r.runId)}
                >
                  <span className="sd" aria-hidden="true" />
                  <span className="sn">{r.name}</span>
                  <span className="sr num">{r.asrText}</span>
                </button>
              ))}
            </div>
            <WordsLine view={data.scatter.phone} />
          </div>
        </div>
        <div className="readings">
          {data.scatter.readings.map((s) => (
            <p key={s.slice(0, 24)}>{s}</p>
          ))}
        </div>
        <div className="chart-captions">
          {data.scatter.captions.map((s) => (
            <p key={s.slice(0, 24)}>{s}</p>
          ))}
        </div>
        <p className="chart-id">{data.scatter.chartId}</p>
      </section>

      <section
        className="section sec-zone"
        aria-labelledby="ranking-title"
        data-section="ranking"
        id="ranking"
      >
        <div className="sechead">
          <div className="micro">02 · Ranking</div>
          <h2 id="ranking-title">The ranking, toughest first</h2>
          <p className="cap">
            Attack success with its 95 percent interval, on the ranking's
            shared scale. Rows bracketed together have overlapping
            intervals and should be read as tied.
          </p>
        </div>
        <div className="zgrid">
          <div className="railwrap">
            <div className="colhead" aria-hidden="true">
              <span />
              <span />
              <span>Result</span>
              <span className="r">ATK</span>
              <span />
              <span className="r">BEN</span>
              <span className="r">ECE</span>
              <span className="r">TAX</span>
              <span className="r">Cost</span>
            </div>
            <SegmentList
              segments={data.rail.fullSegments}
              foldAfter={data.rail.foldAfter}
              expanded={fullOpen}
              selectedRunId={selectedRunId}
              onSelect={select}
              counter={fullCounter}
            />
            {data.rail.foldedCount > 0 && (
              <button
                type="button"
                className="foldline"
                aria-expanded={fullOpen}
                onClick={() => setFullOpen(!fullOpen)}
              >
                {fullOpen
                  ? "Show fewer full-suite results."
                  : `${data.rail.foldedCount} further full-suite results follow in the same rail. Show them.`}
              </button>
            )}
            <div className="ghead">
              <div className="micro">Guard models</div>
              <p>{data.rail.guardCaption}</p>
            </div>
            <SegmentList
              segments={data.rail.sliceSegments}
              foldAfter={data.rail.sliceFoldAfter}
              expanded={sliceOpen}
              selectedRunId={selectedRunId}
              onSelect={select}
              counter={sliceCounter}
            />
            {data.rail.sliceFoldedCount > 0 && (
              <button
                type="button"
                className="foldline"
                aria-expanded={sliceOpen}
                onClick={() => setSliceOpen(!sliceOpen)}
              >
                {sliceOpen
                  ? "Show fewer guard results."
                  : `${data.rail.sliceFoldedCount} further guard results follow in the same rail. Show them.`}
              </button>
            )}
          </div>
          <Inspector datum={datum} axisMax={data.axisMax} />
        </div>
      </section>
    </div>
  );
}
