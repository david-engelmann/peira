import {
  boardDateWords,
  boardGroups,
  boardVersions,
  modelCounts,
} from "@/lib/payload";
import { fmtInt } from "@/lib/format";
import { asrAxisFor } from "@/lib/chart";
import { inspectorDataAll, type InspectorDatum } from "@/lib/inspectorData";
import ModelsIndex, { type IndexEntry } from "./ModelsIndex";

/**
 * The models index (08). A plain rail of names in rate
 * order, in the ranking's groups; selecting a name loads
 * the same inspector the ranking zone carries, and the
 * inspector links to the result's own page, where the full
 * card stands. The counts the card grid used to carry move
 * here and to the ranking head, derived from the payload.
 * The rail row's accessible label carries the result's
 * figures under the same carrier rules as every other
 * surface: a flagged figure only with its decomposition,
 * and the no-answer disclosures with it.
 */

function entryLabel(d: InspectorDatum): string {
  const parts: Array<string | null> = [
    d.name,
    d.wire,
    d.kind === "flagged" ? "flagged" : `rank ${d.rank}`,
    d.asrText !== null ? `attack success ${d.asrText}` : null,
    d.decompText,
    d.benignText !== null ? `benign accuracy ${d.benignText}` : null,
    d.malformedText !== null ? `malformed ${d.malformedText}` : null,
    d.unanswered !== null ? d.unanswered.replace(/\.$/, "") : null,
    d.singleCall !== null ? d.singleCall.replace(/\.$/, "") : null,
  ];
  return parts.filter(Boolean).join(", ");
}

export default function ModelsSection() {
  const groups0 = boardGroups();
  const rankedRates = [...groups0.full, ...groups0.slices]
    .map((r) => r.asr_conditional)
    .filter((v): v is number => v !== null && v !== undefined);
  const axis = asrAxisFor(rankedRates.length ? Math.max(...rankedRates) : 0);
  const { groups, byRunId } = inspectorDataAll(axis.max);
  const counts = modelCounts();
  const versions = boardVersions();

  const entries: IndexEntry[] = [];
  const push = (runId: string) => {
    const d = byRunId.get(runId)!;
    entries.push({
      runId,
      kind: d.kind,
      rank: d.rank,
      name: d.name,
      wire: d.wire,
      mark: d.mark,
      rateText: d.asrText ?? "·",
      ariaLabel: entryLabel(d),
    });
  };
  for (const row of groups.full) push(row.run_id);
  for (const row of groups.slices) push(row.run_id);
  const flaggedSorted = [...groups.flagged].sort(
    (a, b) => (b.asr_conditional ?? 0) - (a.asr_conditional ?? 0),
  );
  for (const row of flaggedSorted) push(row.run_id);

  const inspectors: Record<string, InspectorDatum> = {};
  for (const [id, d] of byRunId) inspectors[id] = d;

  return (
    <section
      className="section sec-models"
      aria-labelledby="models-title"
      data-section="models"
      id="models"
    >
      <div className="sechead">
        <div className="micro">08 · Models</div>
        <h2 id="models-title">Every result, one reading each</h2>
        <p className="cap">
          {fmtInt(counts.tested)} models tested, {fmtInt(counts.ranked)}{" "}
          ranked and {fmtInt(counts.flagged)} flagged. Names run in the
          ranking's groups and order. Select a name for its reading. The
          full card, its family bars, its severity flips and the
          provenance of its run stand on the result's own page.
        </p>
      </div>
      <ModelsIndex
        entries={entries}
        inspectors={inspectors}
        axisMax={axis.max}
        defaultRunId={entries[0].runId}
      />
      <p className="chart-id">
        Peira decision robustness board, model index.{" "}
        {fmtInt(entries.length)} results, one reading each. Dataset{" "}
        {versions.dataset}, updated {boardDateWords()}.
      </p>
    </section>
  );
}
