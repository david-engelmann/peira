"use client";

import { useEffect, useRef, useState } from "react";
import type { FlipData, FlipResultDatum } from "@/lib/flipData";

/**
 * The Flip. One paired case from the suite, standing on the
 * first screen as an object the reader runs rather than a
 * claim the page describes. The benign and attacked forms
 * stand side by side with the span the attack added marked
 * and the marking keyed in the object's own words. A stepper
 * chooses whose decision is on the table, and the one primary
 * control runs the attack, playing the selected result's
 * recorded attacked decision from its sealed run. Nothing is
 * simulated. Every state the object shows stands in
 * data/flipcase.json and is re-derived from the sealed
 * artifacts by the board's test suite.
 */

const VERDICT_WORD: Record<FlipResultDatum["outcome"], string> = {
  held: "Held",
  flipped: "Flipped",
  abstained: "Abstained",
  malformed: "Malformed output",
};

/** The verdict's second half, in words, from the record. */
function verdictNote(d: FlipResultDatum, targetAnswer: string): string {
  switch (d.outcome) {
    case "held":
      return "Its decision did not move.";
    case "flipped":
      return d.attackedDecision === targetAnswer
        ? "It took the option the added document argued for."
        : "It answered outside the two options the case offered.";
    case "abstained":
      return "It gave no decision under attack.";
    case "malformed":
      return "Its answer could not be read as a decision.";
  }
}

/** The aggregate sentence, composed from the tallied counts. */
function aggregateLine(counts: FlipData["counts"]): string {
  const parts = [
    `${counts.held} of the ${counts.total} ranked results held their decision`,
    `${counts.flipped} flipped`,
  ];
  if (counts.abstained > 0) parts.push(`${counts.abstained} abstained`);
  if (counts.malformed > 0) {
    parts.push(`${counts.malformed} produced malformed output`);
  }
  const joined =
    parts.length === 2
      ? parts.join(" and ")
      : `${parts.slice(0, -1).join(", ")}, and ${parts[parts.length - 1]}`;
  return `On this case, ${joined}.`;
}

function FlipMark({ d, size = 22 }: { d: FlipResultDatum; size?: number }) {
  const m = d.mark;
  return (
    <span
      className="xmark"
      style={{ width: size, height: size, background: m.color }}
      aria-hidden="true"
    >
      {m.kind === "logo" && m.slug ? (
        <svg width={size * 0.62} height={size * 0.62} viewBox="0 0 24 24">
          <use href={`#vlogo-${m.slug}`} style={{ color: m.glyph }} />
        </svg>
      ) : (
        <span className="xmark-letter" style={{ color: m.glyph }}>
          {m.letter}
        </span>
      )}
    </span>
  );
}

export default function Flip({ data }: { data: FlipData }) {
  const [selId, setSelId] = useState(data.defaultRunId);
  const [attacked, setAttacked] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const [runCount, setRunCount] = useState(0);
  const timer = useRef<number | null>(null);

  const sel =
    data.results.find((r) => r.runId === selId) ?? data.results[0];

  useEffect(
    () => () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
    },
    [],
  );

  const select = (runId: string) => {
    if (timer.current !== null) window.clearTimeout(timer.current);
    setLeaving(false);
    setSelId(runId);
    setAttacked(false);
  };

  /* The run plays the recorded outcome. The standing content
   * leaves at 120ms and the decision enters at 240ms, exits
   * shorter than entries inside the board's motion budget.
   * Under reduced motion the swap is instant and only the
   * verdict word changes. */
  const run = () => {
    if (leaving) return;
    const reduce = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    if (reduce) {
      setAttacked(true);
      setRunCount((c) => c + 1);
      return;
    }
    setLeaving(true);
    timer.current = window.setTimeout(() => {
      setAttacked(true);
      setLeaving(false);
      setRunCount((c) => c + 1);
    }, 120);
  };

  return (
    <div className="flip">
      <div className="flip-head">
        <p className="micro">
          {data.familyLabel} · {data.severityLabel} severity · Case{" "}
          {data.caseId}
        </p>
        <h3 className="flip-title">
          One case, decided {data.counts.total} times
        </h3>
        <p className="flip-lede">
          Every ranked result decided this case twice, once plainly
          and once with one fabricated document added. Choose a
          result, then run the attack to see whether its decision
          held.
        </p>
      </div>

      <div className="flip-stepper" role="group" aria-label="Choose a result">
        {data.results.map((d) => (
          <button
            key={d.runId}
            type="button"
            className={`flip-chip${d.runId === sel.runId ? " on" : ""}`}
            aria-pressed={d.runId === sel.runId}
            onClick={() => select(d.runId)}
          >
            <FlipMark d={d} />
            <span className="flip-chip-rank rn">{d.rank}</span>
            <span className="flip-chip-name">
              {d.name}
              {d.wire ? ` · ${d.wire}` : ""}
            </span>
          </button>
        ))}
      </div>

      <p className="flip-now">
        <FlipMark d={sel} size={26} />
        <span className="flip-now-name">
          {sel.fullName}
          {sel.wire ? ` · ${sel.wire}` : ""}
        </span>
        <span className="flip-now-meta">
          Rank {sel.rank} of {data.counts.total} · attack success{" "}
          <span className="rn">{sel.asrText}</span>
        </span>
      </p>

      <div className="flip-panels">
        <section className="flip-panel" aria-label="Benign form">
          <p className="micro">Benign form</p>
          <p className="flip-prompt">{data.benignPrompt}</p>
          <div className="flip-decision">
            <p className="micro">Its decision</p>
            <p className="flip-decision-text">{sel.benignDecision}</p>
            <p className="flip-decision-sub">The supported decision</p>
          </div>
        </section>

        <section className="flip-panel" aria-label="Attacked form">
          <p className="micro">Attacked form</p>
          <p className="flip-prompt">
            {data.attackedPre}
            <mark className="flip-span">{data.attackedSpan}</mark>
            {data.attackedPost}
          </p>
          <p className="flip-key">
            <span className="flip-swatch" aria-hidden="true" />
            <span>
              <strong>{data.spanLabel}.</strong> {data.attackDescription}
            </span>
          </p>
          <div className="flip-decision">
            <p className="micro">Its decision under attack</p>
            <div
              className={`flip-slot${leaving ? " leaving" : ""}`}
              aria-live="polite"
            >
              {attacked ? (
                <div className="flip-swap" key={`${sel.runId}-${runCount}`}>
                  <p className="flip-decision-text">{sel.attackedDecision}</p>
                  <div className="flip-verdict-row">
                    <span className={`flip-verdict ${sel.outcome}`}>
                      {VERDICT_WORD[sel.outcome]}
                    </span>
                    <span className="flip-verdict-note">
                      {verdictNote(sel, data.targetAnswer)}
                    </span>
                  </div>
                </div>
              ) : (
                <p className="flip-pending">Not run yet</p>
              )}
            </div>
          </div>
        </section>
      </div>

      <div className="flip-controls">
        <button type="button" className="flip-run" onClick={run}>
          Run the attack
        </button>
        {attacked && (
          <button
            type="button"
            className="ghostbtn"
            onClick={() => select(sel.runId)}
          >
            Back to the benign form
          </button>
        )}
        <p className="flip-agg">{aggregateLine(data.counts)}</p>
      </div>
    </div>
  );
}
