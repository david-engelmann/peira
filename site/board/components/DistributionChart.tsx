"use client";

import { useId, useRef, useState, type ComponentProps, type CSSProperties, type KeyboardEvent } from "react";
import { fmtCi, fmtPct } from "@/lib/format";
import Mark from "./Mark";
import "./distribution-chart.css";

interface DistributionResult {
  name: string;
  mark: ComponentProps<typeof Mark>["mark"];
  href: string;
  rate: number;
  interval: [number, number] | null;
  malformedShare: string | null;
}

export default function DistributionChart({ results, featuredCount, summary }: {
  results: DistributionResult[];
  featuredCount: number;
  summary: string;
}) {
  const [active, setActive] = useState(0);
  const bars = useRef<Array<HTMLButtonElement | null>>([]);
  const instructionsId = useId();
  const result = results[active];
  const maxPercent = 100 * Math.max(...results.map(({ rate }) => rate));
  const step = maxPercent > 40 ? 20 : maxPercent > 10 ? 10 : 2.5;
  const ceiling = Math.max(10, step * Math.ceil(maxPercent / step));
  const ticks = Array.from({ length: ceiling / step + 1 }, (_, index) => index * step);

  function adjacent(index: number, direction: number) {
    return (index + direction + results.length) % results.length;
  }

  function moveFocus(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    let next: number;
    switch (event.key) {
      case "ArrowLeft": next = adjacent(index, -1); break;
      case "ArrowRight": next = adjacent(index, 1); break;
      case "Home": next = 0; break;
      case "End": next = results.length - 1; break;
      default: return;
    }
    event.preventDefault();
    setActive(next);
    bars.current[next]?.focus({ preventScroll: true });
  }

  return (
    <div className="distribution-chart">
      <div className="distribution-plot" role="group" aria-label={summary} aria-describedby={instructionsId}>
        <span className="distribution-instructions" id={instructionsId}>
          Use the left and right arrow keys to inspect results, or Home and End to jump to the first and last bars.
        </span>
        <div className="distribution-scale" aria-hidden="true">
          {ticks.map(tick => (
            <div className="distribution-tick" key={tick} style={{ bottom: `${100 * tick / ceiling}%` }}>
              <span>{tick}%</span>
            </div>
          ))}
        </div>
        <div className="distribution-bars" style={{ "--bar-count": results.length } as CSSProperties}>
          {results.map(({ href, interval, malformedShare, name, rate }, index) => (
            <button
              className="distribution-bar"
              data-featured={index < featuredCount}
              key={href}
              ref={node => { bars.current[index] = node; }}
              type="button"
              tabIndex={active === index ? 0 : -1}
              aria-pressed={active === index}
              aria-label={`${name}, ${fmtPct(rate)}${malformedShare ? `, ${malformedShare}` : ""}${interval ? `, 95% interval ${fmtCi(interval)}` : ""}`}
              onPointerEnter={event => { if (event.pointerType === "mouse") setActive(index); }}
              onFocus={() => setActive(index)}
              onClick={() => setActive(index)}
              onKeyDown={event => moveFocus(event, index)}
            >
              <span aria-hidden="true" style={{ height: `${10000 * rate / ceiling}%` }} />
            </button>
          ))}
        </div>
      </div>
      <div className="distribution-direction" aria-hidden="true">
        <span>Lower rates</span><span>Higher rates</span>
      </div>
      <div className="distribution-readout">
        <div className="distribution-identity">
          <Mark mark={result.mark} size={28} />
          <div className="distribution-selection">
            <div className="distribution-result" role="status" aria-atomic="true">
              <span className="distribution-name">{result.name}</span>
              <span className="distribution-measure">
                <b>{fmtPct(result.rate)}</b>
                {result.malformedShare && <span> · {result.malformedShare}</span>}
                {result.interval && <span> · 95% CI {fmtCi(result.interval)}</span>}
              </span>
            </div>
            <a className="distribution-link" href={result.href} aria-label={`Open result for ${result.name}`}>
              Open result <span aria-hidden="true">↗</span>
            </a>
          </div>
        </div>
        {results.length > 1 && (
          <div className="distribution-actions">
            <button type="button" aria-label="Previous result" onClick={() => setActive(adjacent(active, -1))}>‹</button>
            <button type="button" aria-label="Next result" onClick={() => setActive(adjacent(active, 1))}>›</button>
          </div>
        )}
      </div>
    </div>
  );
}
