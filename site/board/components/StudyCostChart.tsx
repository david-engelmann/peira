"use client";

import { useId, useRef, useState, type ComponentProps, type KeyboardEvent, type MouseEvent } from "react";
import { fmtCi, fmtInt, fmtPct, fmtUsdExact } from "@/lib/format";
import Mark from "./Mark";
import "./study-cost-chart.css";

const coverageLabels = {
  complete: "Fully priced",
  "lower-bound": "Cost lower bound",
  unknown: "Coverage unknown",
};
type Coverage = keyof typeof coverageLabels;

interface CostPoint {
  id: string;
  name: string;
  mark: ComponentProps<typeof Mark>["mark"];
  slug: string;
  cost: number;
  asr: number;
  ci: [number, number] | null;
  coverage: Coverage;
  highlighted: boolean;
}

const marker = (point: CostPoint) =>
  (point.highlighted ? " study-scatter-highlight" : "") + ` study-scatter-${point.coverage}`;

const HIT_RADIUS = 22;
const REPEAT_RADIUS = 5;

function CostInterval({ left, top, bottom, rate, className }: {
  left: number;
  top: number;
  bottom: number;
  rate: number;
  className: string;
}) {
  const center = 18;
  const stem = center + (left > 82 ? -15 : 15);
  return (
    <svg
      aria-hidden="true"
      className={`study-scatter-whisker${className}`}
      style={{ left: `${left}%` }}
      width={center * 2}
      height="100%"
      stroke="currentColor"
    >
      <line x1={stem} x2={stem} y1={`${top}%`} y2={`${bottom}%`} />
      <line x1={stem - 2} x2={stem + 2} y1={`${top}%`} y2={`${top}%`} />
      <line x1={stem - 2} x2={stem + 2} y1={`${bottom}%`} y2={`${bottom}%`} />
      <line x1={center} x2={stem} y1={`${rate}%`} y2={`${rate}%`} />
    </svg>
  );
}

export default function StudyCostChart({ points }: { points: CostPoint[] }) {
  const [coverage, setCoverage] = useState<"all" | Coverage>("all");
  const [zoomed, setZoomed] = useState(false);
  const [intervals, setIntervals] = useState(true);
  const [selectedId, setSelectedId] = useState(points.find(point => point.highlighted && point.coverage === "complete")?.id);
  const pointButtons = useRef(new Map<string, HTMLButtonElement>());
  const lastClick = useRef<{ left: number; top: number; id: string } | null>(null);
  const instructionsId = useId();

  const sorted = [...points].sort((a, b) => a.cost - b.cost);
  const underDollar = sorted.filter(point => point.cost < 1);
  const canZoom = underDollar.length > 0 && underDollar.length < sorted.length;
  const domain = zoomed ? underDollar : sorted;
  const visible = domain.filter(point => coverage === "all" || point.coverage === coverage);
  const current = visible.find(point => point.id === selectedId) ?? visible[0];
  const hasIntervals = points.some(point => point.ci !== null);
  const coverageOptions = (Object.keys(coverageLabels) as Coverage[])
    .filter(option => points.some(point => point.coverage === option));
  const showHighlights = visible.some(point => point.highlighted);

  const lowest = domain[0].cost;
  const highest = domain.at(-1)!.cost;
  const xMin = Math.log10(lowest) - 0.22;
  const xMax = zoomed ? 0.08 : Math.log10(highest) + 0.22;
  const x = (cost: number) => 100 * (Math.log10(cost) - xMin) / (xMax - xMin);
  const decadeStart = Math.ceil(xMin);
  const decadeStep = Math.max(1, Math.ceil((Math.floor(xMax) - decadeStart) / 4));
  const decades = Array.from(
    { length: Math.floor((xMax - decadeStart) / decadeStep) + 1 },
    (_, i) => 10 ** (decadeStart + i * decadeStep),
  );
  const xTicks = decades.length >= 2 ? decades : [...new Set([lowest, zoomed ? 1 : highest])];
  const maxAsr = Math.max(...points.map(({ asr, ci }) => Math.max(asr, ci?.[1] ?? asr)));
  const yStep = maxAsr > 0.5 ? 0.2 : 0.1;
  const yMax = Math.min(1, Math.max(0.2, Math.ceil((maxAsr + 0.025) / yStep) * yStep));
  const y = (rate: number) => 100 * rate / yMax;
  const yTicks = Array.from({ length: Math.round(yMax / yStep) + 1 }, (_, i) => i * yStep);
  const positioned = visible.map(point => ({ point, left: x(point.cost), bottom: y(point.asr) }));

  function adjacentPoint(id: string, direction: number) {
    const index = visible.findIndex(point => point.id === id);
    return visible[(index + direction + visible.length) % visible.length];
  }

  function moveFocus(event: KeyboardEvent<HTMLButtonElement>, id: string) {
    let next: CostPoint | undefined;
    switch (event.key) {
      case "ArrowLeft":
      case "ArrowUp": next = adjacentPoint(id, -1); break;
      case "ArrowRight":
      case "ArrowDown": next = adjacentPoint(id, 1); break;
      case "Home": next = visible[0]; break;
      case "End": next = visible.at(-1); break;
      default: return;
    }
    event.preventDefault();
    if (next) {
      lastClick.current = null;
      setSelectedId(next.id);
      pointButtons.current.get(next.id)?.focus({ preventScroll: true });
    }
  }

  function inspectAtPointer(event: MouseEvent<HTMLDivElement>, clicked = false) {
    const plot = event.currentTarget.getBoundingClientRect();
    const left = event.clientX - plot.left;
    const top = event.clientY - plot.top;
    const previous = lastClick.current;
    const repeated = previous && Math.hypot(left - previous.left, top - previous.top) <= REPEAT_RADIUS;
    if (!clicked && repeated) return;
    if (!repeated) lastClick.current = null;
    const hits = positioned.map(item => ({
      point: item.point,
      distance: Math.hypot(left - plot.width * item.left / 100, top - plot.height * (1 - item.bottom / 100)),
    })).filter(hit => hit.distance <= HIT_RADIUS).sort((a, b) => a.distance - b.distance);
    if (!hits.length) return;
    const index = repeated ? hits.findIndex(({ point }) => point.id === previous.id) : -1;
    const { point } = hits[(index + 1) % hits.length];
    setSelectedId(point.id);
    if (clicked) {
      lastClick.current = { left, top, id: point.id };
      pointButtons.current.get(point.id)?.focus({ preventScroll: true });
    }
  }

  return (
    <div className="study-scatter">
      <div className="study-scatter-controls">
        <label className="study-scatter-coverage">
          Cost coverage
          <select value={coverage} onChange={event => {
            lastClick.current = null;
            setCoverage(event.target.value as "all" | Coverage);
          }}>
            <option value="all">All recorded costs</option>
            {coverageOptions.map(option => <option key={option} value={option}>{coverageLabels[option]}</option>)}
          </select>
        </label>
        {canZoom && (
          <button type="button" aria-pressed={zoomed} onClick={() => {
            lastClick.current = null;
            setZoomed(!zoomed);
          }}>
            Zoom below $1
          </button>
        )}
        {hasIntervals && (
          <label className="study-scatter-toggle">
            <input type="checkbox" checked={intervals} onChange={event => setIntervals(event.target.checked)} />
            95% intervals
          </label>
        )}
      </div>

      <p className="study-scatter-count" role="status">
        {fmtInt(visible.length)} of {fmtInt(points.length)} results shown
      </p>
      <div className="study-scatter-axes">
        <div
          className="study-scatter-plot"
          role="group"
          aria-label="Attack success by recorded serving cost on a logarithmic scale"
          aria-describedby={instructionsId}
          onPointerMove={event => {
            if (event.pointerType === "mouse" && !event.currentTarget.querySelector("button:focus-visible")) {
              inspectAtPointer(event);
            }
          }}
          onClick={event => { if (event.detail > 0) inspectAtPointer(event, true); }}
        >
          <span className="study-scatter-instructions" id={instructionsId}>
            Use the arrow keys to inspect results in cost order, or Home and End to jump to the lowest and highest costs.
            Click or tap the same spot again to cycle through overlapping results.
          </span>
          <div className="study-scatter-grid" aria-hidden="true">
            {yTicks.map((tick) => (
              <div className="study-scatter-horizontal" key={tick} style={{ bottom: `${y(tick)}%` }}>
                <span>{Math.round(tick * 100)}%</span>
              </div>
            ))}
            {xTicks.map((tick) => (
              <div className="study-scatter-vertical" key={tick} style={{ left: `${x(tick)}%` }}>
                <span>{decades.length >= 2 ? `$${tick}` : fmtUsdExact(tick)}</span>
              </div>
            ))}
          </div>
          {!current && <p className="study-scatter-empty">No results match these settings.</p>}
          {positioned.map(({ point, left, bottom }) => (
            <div key={point.id}>
              {intervals && point.ci && (
                <CostInterval
                  left={left}
                  top={100 - y(point.ci[1])}
                  bottom={100 - y(point.ci[0])}
                  rate={100 - bottom}
                  className={marker(point)}
                />
              )}
              <button
                className={`study-scatter-point${marker(point)}`}
                type="button"
                ref={node => {
                  if (node) pointButtons.current.set(point.id, node);
                  else pointButtons.current.delete(point.id);
                }}
                style={{ left: `${left}%`, bottom: `${bottom}%` }}
                tabIndex={point === current ? 0 : -1}
                aria-pressed={point === current}
                aria-label={`${point.name}, ${point.mark.label} · ${point.coverage === "lower-bound" ? "≥" : ""}${fmtUsdExact(point.cost)} · ${fmtPct(point.asr)} · ${coverageLabels[point.coverage]}${point.ci ? ` · 95% interval ${fmtCi(point.ci)}` : ""}`}
                onFocus={() => setSelectedId(point.id)}
                onClick={event => { if (event.detail === 0) setSelectedId(point.id); }}
                onKeyDown={event => moveFocus(event, point.id)}
              >
                <span className="study-scatter-badge" aria-hidden="true">
                  <Mark mark={point.mark} size={18} tinted />
                </span>
              </button>
            </div>
          ))}
        </div>
        <p className="study-scatter-axis">Recorded serving cost (USD, log scale)</p>
      </div>

      <ul className="study-scatter-key" aria-label="Chart legend">
        {coverageOptions.map(option => (
          <li key={option}><span className={`study-scatter-swatch study-scatter-${option}`} aria-hidden="true" />{coverageLabels[option]}</li>
        ))}
        {showHighlights && <li><span className="study-scatter-swatch study-scatter-highlight" aria-hidden="true" />Discussed results</li>}
        {intervals && hasIntervals && (
          <li>
            <svg className="study-scatter-interval" width="16" height="14" aria-hidden="true">
              <path d="M12 1v12M10 1h4M10 13h4M2 7h10" fill="none" stroke="currentColor" />
            </svg>
            95% Wilson interval
          </li>
        )}
      </ul>

      {current && (
        <div className="study-scatter-readout">
          <div>
            <div className="study-scatter-selection" role="status" aria-atomic="true">
              <strong><Mark mark={current.mark} size={20} />{current.name}<span className="provider-description">, {current.mark.label}</span></strong>
              <span className="study-scatter-measures">
                <span><b>{fmtPct(current.asr)}</b> attack success</span>
                {current.ci && <span>95% CI {fmtCi(current.ci)}</span>}
                <span>
                  <b>{current.coverage === "lower-bound" && "≥ "}{fmtUsdExact(current.cost)}</b>{" "}
                  {current.coverage === "lower-bound" ? "cost lower bound" : "recorded cost"}
                  {current.coverage === "unknown" && " · coverage unknown"}
                </span>
              </span>
            </div>
            <a href={`#result=${encodeURIComponent(current.slug)}`} aria-label={`Open result for ${current.name}, ${current.mark.label}`}>
              Open result <span aria-hidden="true">↗</span>
            </a>
          </div>
          {visible.length > 1 && (
            <div className="study-scatter-navigation">
              <button type="button" aria-label="Previous result by cost" onClick={() => setSelectedId(adjacentPoint(current.id, -1).id)}>‹</button>
              <button type="button" aria-label="Next result by cost" onClick={() => setSelectedId(adjacentPoint(current.id, 1).id)}>›</button>
            </div>
          )}
        </div>
      )}

      {visible.length > 0 && (
        <details className="study-cost-data">
          <summary>View data for {fmtInt(visible.length)} results</summary>
          <table>
            <thead>
              <tr>
                <th scope="col">Result</th>
                <th scope="col">Recorded cost</th>
                <th scope="col">Attack success (95% CI)</th>
              </tr>
            </thead>
            <tbody>
              {visible.map(({ id, name, slug, cost, asr, ci, coverage }) => (
                <tr key={id}>
                  <th scope="row"><a href={`/models/${slug}/`}>{name}</a></th>
                  <td>{coverage === "lower-bound" && "≥ "}{fmtUsdExact(cost)}<span>{coverageLabels[coverage]}</span></td>
                  <td>{fmtPct(asr)} {ci && <span>{fmtCi(ci)}</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
    </div>
  );
}
