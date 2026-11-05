"use client";

import { useState } from "react";
import type { InspectorDatum, InspectorKind, InspectorMark } from "@/lib/inspectorData";
import Inspector from "./Inspector";
import Mark from "./Mark";

/**
 * The models index island: a plain rail of names in rate
 * order beside the inspector. Group heads inside the rail
 * carry the ranking's own words, so the list reads as the
 * ranking read. Selecting a name loads its reading; the
 * reading links on to the result's own page.
 */

export interface IndexEntry {
  runId: string;
  kind: InspectorKind;
  rank: number | null;
  name: string;
  wire: string | null;
  mark: InspectorMark;
  rateText: string;
  ariaLabel: string;
}

const GROUP_HEADS: Array<{ kind: InspectorKind; label: string }> = [
  { kind: "full", label: "Full suite" },
  { kind: "flagged", label: "Flagged" },
  { kind: "slice", label: "Guardrail slices" },
];

export default function ModelsIndex({
  entries,
  inspectors,
  axisMax,
  defaultRunId,
}: {
  entries: IndexEntry[];
  inspectors: Record<string, InspectorDatum>;
  axisMax: number;
  defaultRunId: string;
}) {
  const [selectedRunId, setSelectedRunId] = useState(defaultRunId);
  const datum = inspectors[selectedRunId] ?? inspectors[defaultRunId];
  return (
    <div className="zgrid index-grid">
      <div className="railwrap index-rail">
        {GROUP_HEADS.map((g) => {
          const rows = entries.filter((e) => e.kind === g.kind);
          if (rows.length === 0) return null;
          return (
            <div key={g.kind} className="index-group" data-mgroup={g.kind}>
              <div className="ghead">
                <div className="micro">{g.label}</div>
              </div>
              {rows.map((e) => (
                <button
                  type="button"
                  key={e.runId}
                  className={`irow${e.runId === selectedRunId ? " sel" : ""}`}
                  data-index-for={e.runId}
                  aria-pressed={e.runId === selectedRunId}
                  aria-label={`${e.ariaLabel}. Show its reading.`}
                  onClick={() => setSelectedRunId(e.runId)}
                >
                  {e.kind === "flagged" ? (
                    <span className="flag-tag">Flagged</span>
                  ) : (
                    <span className="rk num">{e.rank}</span>
                  )}
                  <Mark mark={e.mark} size="row" />
                  <span className="nm">
                    {e.name}
                    {e.wire !== null && <span className="sub">{e.wire}</span>}
                  </span>
                  <span className="atk num">{e.rateText}</span>
                </button>
              ))}
            </div>
          );
        })}
      </div>
      <Inspector datum={datum} axisMax={axisMax} />
    </div>
  );
}
