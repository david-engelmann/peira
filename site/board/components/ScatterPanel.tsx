import type { ScatterView } from "@/lib/topData";

/**
 * One scatter panel, wide or phone, drawn from the geometry
 * lib/topData seated on the server. Discs are every full
 * suite result with a recorded cost on the shared scale;
 * flagged discs keep the amber ring; the selected result's
 * disc carries the green ring. The wide panel's left band is
 * the no-cost rail at laddered heights, its rows selectable
 * like the phone panel's named mini-rows under the plot.
 * A point the placement pass could not name beside its disc
 * is named in words under the panel, and its point carries
 * no label here.
 */
export default function ScatterPanel({
  view,
  phone,
  selectedRunId,
  onSelect,
}: {
  view: ScatterView;
  phone: boolean;
  selectedRunId: string;
  onSelect: (runId: string) => void;
}) {
  const keyActivate = (runId: string) => (e: React.KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onSelect(runId);
    }
  };
  const offScale = view.offScale;
  return (
    <svg
      viewBox={view.viewBox}
      className={phone ? "scatter-svg phone" : "scatter-svg wide"}
      role="img"
      aria-label="Scatter of attack success against recorded cost per run"
    >
      {view.gridLines.map((g) => (
        <g key={g.label}>
          <line
            x1={phone ? 34 : (view.railDividerX ?? 224)}
            y1={g.y}
            x2={phone ? 350 : 1240}
            y2={g.y}
            stroke="#161d25"
            strokeWidth="1"
          />
          <text
            x={phone ? 26 : 248}
            y={g.y + 4}
            textAnchor="end"
            className="svg-tick"
          >
            {g.label}
          </text>
        </g>
      ))}
      {view.railDividerX !== null && (
        <line
          x1={view.railDividerX}
          y1={8}
          x2={view.railDividerX}
          y2={440}
          stroke="#262f3a"
          strokeWidth="1"
          strokeDasharray="3 5"
        />
      )}
      {view.railRows.map((r) => (
        <g
          key={r.runId}
          className="svg-rail-row"
          data-rail-for={r.runId}
          role="button"
          tabIndex={0}
          aria-label={`${r.name}, attack success ${r.asrText}. Select this result.`}
          onClick={() => onSelect(r.runId)}
          onKeyDown={keyActivate(r.runId)}
        >
          <circle
            cx={18}
            cy={r.cy}
            r={r.runId === selectedRunId ? 7 : 6.5}
            className={
              r.runId === selectedRunId ? "disc sel" : "disc rail-disc"
            }
          />
          <text x={34} y={r.cy + 4} className="svg-rail-name">
            {r.printName}
          </text>
          <text x={212} y={r.cy + 4} textAnchor="end" className="svg-rail-rate">
            {r.asrText}
          </text>
        </g>
      ))}
      {view.points.map((p) => (
        <g
          key={p.runId}
          className="svg-point"
          data-point-for={p.runId}
          role="button"
          tabIndex={0}
          aria-label={`${p.title}. Select this result.`}
          onClick={() => onSelect(p.runId)}
          onKeyDown={keyActivate(p.runId)}
        >
          <title>{p.title}</title>
          {phone && (
            <circle cx={p.x} cy={p.y} r={27} className="hit-disc" />
          )}
          <circle
            cx={p.x}
            cy={p.y}
            r={p.runId === selectedRunId ? 7.5 : phone ? 5 : 6.5}
            className={
              p.runId === selectedRunId
                ? "disc sel"
                : p.flagged
                  ? "disc flagged"
                  : "disc"
            }
          />
        </g>
      ))}
      {view.labels.map((l) => (
        <text
          key={l.runId}
          x={l.x}
          y={l.y}
          className="svg-label"
          data-label-for={l.runId}
        >
          {l.text}
        </text>
      ))}
      {offScale !== null && (
        <g className="svg-offscale">
          <text x={offScale.textX} y={offScale.textY} className="svg-off-title">
            {offScale.line1}
          </text>
          {offScale.entries.map((e, i) => (
            <g key={e.runId} data-offscale-for={e.runId}>
              <text x={offScale.textX} y={offScale.textY + 24 + i * 48} className="svg-off-line">
                {e.line2}
              </text>
              <text x={offScale.textX} y={offScale.textY + 48 + i * 48} className="svg-off-line">
                {e.line3}
              </text>
              <path
                d={`M ${e.caretX - 7} 26 L ${e.caretX} 12 L ${e.caretX + 7} 26`}
                fill="none"
                stroke="#e8a33d"
                strokeWidth="2.5"
              />
            </g>
          ))}
        </g>
      )}
      {view.decades.map((d) => (
        <text
          key={d.label}
          x={d.x}
          y={phone ? 272 : 436}
          textAnchor="middle"
          className="svg-tick"
        >
          {d.label}
        </text>
      ))}
    </svg>
  );
}

/** The named-in-words line under a panel, from its clauses. */
export function WordsLine({ view }: { view: ScatterView }) {
  if (view.words.length === 0) return null;
  return (
    <p className="nameline">
      <b>Named in words</b>
      {" · "}
      {view.words.map((clause, ci) => (
        <span key={clause.lead}>
          {ci > 0 ? ". " : ""}
          {clause.lead},{" "}
          {clause.items.map((item, ii) => (
            <span key={item.runId} data-words-for={item.runId}>
              {ii > 0 ? ", " : ""}
              <b>{item.name}</b> {item.rest}
            </span>
          ))}
          {ci === view.words.length - 1 ? "." : ""}
        </span>
      ))}
    </p>
  );
}
