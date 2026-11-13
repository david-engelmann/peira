/**
 * Flip case data shaping, server side. The Flip object on the
 * first screen states what each ranked result did on one
 * paired case. The case record stands in data/flipcase.json,
 * extracted from the sealed artifacts and the dataset, and
 * the board's test suite re-derives every state in it from
 * those sources by a second path, so a drift fails the build
 * rather than printing. This module joins the case record to
 * the payload rows, so the object's names, marks, ranks, and
 * board rates come from the board's own data layer and cannot
 * drift from the rest of the page. The aggregate counts are
 * tallied here from the per-result states, never read from
 * the file's counts block.
 */

import flipcaseData from "@/data/flipcase.json";
import { boardGroups, splitDisplayName } from "@/lib/payload";
import { inspectorDataAll, type InspectorMark } from "@/lib/inspectorData";
import { vendorFamilyOf } from "@/lib/vendorColors";

export type FlipOutcome = "held" | "flipped" | "abstained" | "malformed";

interface FlipcaseResult {
  runId: string;
  rank: number;
  benignDecision: string;
  attackedDecision: string;
  outcome: FlipOutcome;
}

interface FlipcaseFile {
  caseId: string;
  familyLabel: string;
  severity: string;
  benignPrompt: string;
  attackedPrompt: string;
  rightAnswer: string;
  targetAnswer: string;
  attack: {
    spanStart: number;
    spanEnd: number;
    spanLabel: string;
    description: string;
  };
  results: FlipcaseResult[];
}

export interface FlipResultDatum {
  runId: string;
  /** Dense rank on the ranked full suite, from the payload. */
  rank: number;
  /** Short name, the name the stepper prints. */
  name: string;
  /** Wire in words, present only when another result shares the name. */
  wire: string | null;
  /** Full display name, organisation prefix kept, revision split out. */
  fullName: string;
  mark: InspectorMark & { glyph: string };
  /** The result's board attack success rate, formatted. */
  asrText: string;
  /** The recorded decisions, verbatim from the sealed run. */
  benignDecision: string;
  attackedDecision: string;
  outcome: FlipOutcome;
}

export interface FlipData {
  caseId: string;
  familyLabel: string;
  /** Severity in words, first letter raised. */
  severityLabel: string;
  benignPrompt: string;
  /** The attacked prompt in three parts, so the object can
   * mark the span the attack added. */
  attackedPre: string;
  attackedSpan: string;
  attackedPost: string;
  spanLabel: string;
  attackDescription: string;
  rightAnswer: string;
  targetAnswer: string;
  /** Tallied from the per-result states in this module. */
  counts: {
    held: number;
    flipped: number;
    abstained: number;
    malformed: number;
    total: number;
  };
  results: FlipResultDatum[];
  /** The board leader, the object's opening selection. */
  defaultRunId: string;
}

const raw = flipcaseData as unknown as FlipcaseFile;

export function flipData(): FlipData {
  const groups = boardGroups();
  const { byRunId } = inspectorDataAll(1);
  const byId = new Map(groups.full.map((r) => [r.run_id, r]));
  const tally = { held: 0, flipped: 0, abstained: 0, malformed: 0 };
  const results = [...raw.results]
    .sort((a, b) => a.rank - b.rank)
    .map((entry) => {
      const row = byId.get(entry.runId);
      const datum = byRunId.get(entry.runId);
      if (!row || !datum) {
        throw new Error(
          `flip case result ${entry.runId} is not a ranked full suite row`,
        );
      }
      tally[entry.outcome] += 1;
      return {
        runId: entry.runId,
        rank: row.rank,
        name: datum.name,
        wire: datum.wire,
        fullName: splitDisplayName(row.display_name).name,
        mark: { ...datum.mark, glyph: vendorFamilyOf(row).glyph },
        asrText: datum.asrText ?? "",
        benignDecision: entry.benignDecision,
        attackedDecision: entry.attackedDecision,
        outcome: entry.outcome,
      };
    });
  const leader = results.find((r) => r.rank === 1) ?? results[0];
  return {
    caseId: raw.caseId,
    familyLabel: raw.familyLabel,
    severityLabel: raw.severity.charAt(0).toUpperCase() + raw.severity.slice(1),
    benignPrompt: raw.benignPrompt,
    attackedPre: raw.attackedPrompt.slice(0, raw.attack.spanStart),
    attackedSpan: raw.attackedPrompt.slice(
      raw.attack.spanStart,
      raw.attack.spanEnd,
    ),
    attackedPost: raw.attackedPrompt.slice(raw.attack.spanEnd),
    spanLabel: raw.attack.spanLabel,
    attackDescription: raw.attack.description,
    rightAnswer: raw.rightAnswer,
    targetAnswer: raw.targetAnswer,
    counts: { ...tally, total: results.length },
    results,
    defaultRunId: leader.runId,
  };
}
