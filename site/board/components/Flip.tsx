"use client";

import { useState } from "react";
import type { FlipData, FlipResultDatum } from "@/lib/flipData";

const VERDICT_WORD: Record<FlipResultDatum["outcome"], string> = {
  held: "Held",
  flipped: "Flipped",
  abstained: "Abstained",
  malformed: "Malformed output",
};

function aggregateLine(counts: FlipData["counts"]): string {
  const parts = [
    `${counts.held} of ${counts.total} ranked full-suite results held their original decision`,
    `${counts.flipped} flipped`,
  ];
  if (counts.abstained > 0) parts.push(`${counts.abstained} abstained`);
  if (counts.malformed > 0) {
    parts.push(`${counts.malformed} produced malformed output`);
  }
  const last = parts.pop();
  const joiner = parts.length > 1 ? ", and " : " and ";
  return `${parts.join(", ")}${joiner}${last}.`;
}

export default function Flip({ data }: { data: FlipData }) {
  const [runId, setRunId] = useState(data.defaultRunId);
  const selected =
    data.results.find((result) => result.runId === runId) ?? data.results[0];

  return (
    <details className="method-disclosure">
      <summary>Inspect a recorded case</summary>
      <div className="case-evidence">
        <p className="case-metadata">
          {data.familyLabel} · {data.severityLabel} severity ·{" "}
          <span>Case {data.caseId}</span>
        </p>
        <p className="case-aggregate">{aggregateLine(data.counts)}</p>

        <div className="case-selector">
          <label htmlFor="case-run">Ranked result</label>
          <select
            id="case-run"
            value={selected.runId}
            onChange={(event) => setRunId(event.target.value)}
          >
            {data.results.map((result) => (
              <option key={result.runId} value={result.runId}>
                {result.rank}. {result.fullName}{result.wire ? ` · ${result.wire}` : ""}
              </option>
            ))}
          </select>
        </div>

        <div className="case-readout" aria-live="polite" aria-atomic="true">
          <dl className="case-decisions">
            <div>
              <dt>Original decision</dt>
              <dd>{selected.benignDecision}</dd>
            </div>
            <div>
              <dt>Decision under attack</dt>
              <dd>{selected.attackedDecision}</dd>
            </div>
          </dl>
          <p className="case-outcome">
            <strong>{VERDICT_WORD[selected.outcome]}</strong>
            {selected.outcome === "flipped" && (
              <span>
                {selected.attackedDecision === data.targetAnswer
                  ? "Chose the option backed by the added document."
                  : "Answered outside the two options."}
              </span>
            )}
            {selected.asrText && (
              <span>Suite attack success {selected.asrText}</span>
            )}
          </p>
        </div>

        <details className="case-prompts">
          <summary>Read both prompts</summary>
          <div className="case-prompt-pair">
            <div>
              <h3>Original prompt</h3>
              <p className="case-prompt">{data.benignPrompt}</p>
              <p className="case-reference">
                <strong>Supported decision</strong> · {data.rightAnswer}
              </p>
            </div>
            <div>
              <h3>Attacked prompt</h3>
              <p className="case-prompt">
                {data.attackedPre}<mark className="case-added">{data.attackedSpan}</mark>{data.attackedPost}
              </p>
              <p className="case-reference">
                <strong>{data.spanLabel}.</strong> {data.attackDescription}
              </p>
            </div>
          </div>
        </details>
      </div>
    </details>
  );
}
