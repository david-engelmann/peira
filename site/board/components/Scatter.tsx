import {
  payload,
  boardGroups,
  boardDateWords,
  boardVersions,
  shortName,
  wireWords,
  duplicateShortNames,
  type BoardRow,
} from "@/lib/payload";
import { fmtInt, fmtPct, fmtUsdExact } from "@/lib/format";
import { ASR_AXIS_MAX, ASR_TICKS } from "@/lib/chart";
import {
  scatterSets,
  costIsLowerBound,
  railCostState,
  costDomain,
  decadeTicks,
  placeLabels,
  nudgePoints,
  estimateLabelWidth,
  type LayoutPoint,
  type Rect,
} from "@/lib/charts";

/**
 * Cost against attack success, design system section 4.2.
 * Ranked results are filled discs and flagged results are
 * amber rings on a log cost axis and the ranking's shared
 * attack success axis. Labels are placed at build time by a
 * deterministic solver over the frozen payload, so no label
 * collides by construction; the cluster that cannot clear is
 * keyed out to index numbers and a list beside the plot, per
 * the spec's cluster rule. Ranked results with no chartable
 * cost sit on the labelled rail at the left at their attack
 * success, with the recorded zero versus no cost distinction
 * stated in words in the caption.
 */

interface Geom {
  w: number;
  h: number;
  railW: number;
  railCx: number;
  dividerX: number;
  plot: { x0: number; x1: number; y0: number; y1: number };
  labelBounds: Rect;
}

const WIDE: Geom = {
  w: 1132,
  h: 612,
  railW: 94,
  railCx: 46,
  dividerX: 106,
  plot: { x0: 128, x1: 1124, y0: 36, y1: 540 },
  labelBounds: { x: 2, y: 30, w: 1128, h: 512 },
};

const PHONE: Geom = {
  w: 358,
  h: 336,
  railW: 50,
  railCx: 25,
  dividerX: 58,
  plot: { x0: 66, x1: 354, y0: 34, y1: 294 },
  labelBounds: { x: 0, y: 0, w: 358, h: 336 },
};

const r2 = (v: number) => Math.round(v * 100) / 100;

interface Pt {
  row: BoardRow;
  x: number;
  y: number;
  rail: boolean;
  lowerBound: boolean;
  nudged: boolean;
}

function buildPoints(
  sets: ReturnType<typeof scatterSets>,
  domain: [number, number],
  g: Geom,
): Pt[] {
  const [lo, hi] = domain;
  const logLo = Math.log10(lo);
  const logSpan = Math.log10(hi) - logLo;
  const yOf = (asr: number) =>
    g.plot.y0 + (1 - asr / ASR_AXIS_MAX) * (g.plot.y1 - g.plot.y0);
  const xOf = (cost: number) =>
    g.plot.x0 + ((Math.log10(cost) - logLo) / logSpan) * (g.plot.x1 - g.plot.x0);
  const plotted: Pt[] = sets.plotted.map((row) => ({
    row,
    x: xOf(row.total_cost_usd!),
    y: yOf(row.asr_conditional!),
    rail: false,
    lowerBound: costIsLowerBound(row),
    nudged: false,
  }));
  const rail: Pt[] = sets.rail.map((row) => ({
    row,
    x: g.railCx,
    y: yOf(row.asr_conditional!),
    rail: true,
    lowerBound: false,
    nudged: false,
  }));
  const wide = g === WIDE;
  /* Plotted points and rail points spread separately. The rail
   * points share one x, so their chains are longer; at phone
   * width every point wears an 18 px badge and the separation
   * target drops to what keeps badge numerals clear. */
  const spread = (pts: Pt[], minSep: number, maxShift: number) => {
    const wrappers = pts.map((p) => ({ runId: p.row.run_id, x: p.x, y: p.y, p }));
    const moved = nudgePoints(wrappers, minSep, maxShift);
    for (const wpt of wrappers) {
      wpt.p.x = wpt.x;
      wpt.p.y = wpt.y;
      wpt.p.nudged = moved.has(wpt.runId);
    }
  };
  spread(plotted, wide ? 13 : 14.5, wide ? 12 : 18.5);
  spread(rail, wide ? 11 : 14.5, wide ? 10 : 18.5);
  return [...plotted, ...rail];
}

function labelFor(row: BoardRow, dupes: Set<string>): string {
  const name = shortName(row);
  return dupes.has(name) ? `${name} (${wireWords(row.wire)})` : name;
}

function pointTitle(p: Pt): string {
  const name = shortName(p.row);
  const asr = fmtPct(p.row.asr_conditional!);
  if (p.rail) {
    return railCostState(p.row) === "recorded-zero"
      ? `${name}, attack success ${asr}, recorded cost $0.00`
      : `${name}, attack success ${asr}, no cost recorded`;
  }
  const cost = fmtUsdExact(p.row.total_cost_usd!);
  return p.lowerBound
    ? `${name}, attack success ${asr}, recorded cost ${cost} per run, a lower bound`
    : `${name}, attack success ${asr}, recorded cost ${cost} per run`;
}

function Marker({
  p,
  badge,
}: {
  p: Pt;
  badge: number | null;
}) {
  const flagged = !p.row.ranking_eligible;
  const cls = flagged ? "pt-flagged" : "pt-ranked";
  return (
    <g
      className="scatter-point"
      data-scatter={p.rail ? "rail" : "plot"}
      data-run-id={p.row.run_id}
      data-cost={p.row.total_cost_usd ?? ""}
      data-asr={p.row.asr_conditional ?? ""}
      data-nudged={p.nudged ? "true" : undefined}
    >
      <title>{pointTitle(p)}</title>
      {p.lowerBound && (
        <g className="lb-tick" aria-hidden="true">
          <line x1={r2(p.x - 14)} y1={r2(p.y)} x2={r2(p.x - 7.5)} y2={r2(p.y)} />
          <polygon
            points={`${r2(p.x - 14)},${r2(p.y)} ${r2(p.x - 9.5)},${r2(p.y - 2.6)} ${r2(p.x - 9.5)},${r2(p.y + 2.6)}`}
          />
        </g>
      )}
      {badge !== null ? (
        <g className="pt-badge">
          <circle cx={r2(p.x)} cy={r2(p.y)} r={9} className={cls} />
          <text x={r2(p.x)} y={r2(p.y)} className="pt-badge-num num">
            {badge}
          </text>
        </g>
      ) : flagged ? (
        <circle cx={r2(p.x)} cy={r2(p.y)} r={5.5} className={cls} />
      ) : (
        <circle cx={r2(p.x)} cy={r2(p.y)} r={5} className={cls} />
      )}
    </g>
  );
}

function Grid({ g, domain }: { g: Geom; domain: [number, number] }) {
  const yOf = (asr: number) =>
    g.plot.y0 + (1 - asr / ASR_AXIS_MAX) * (g.plot.y1 - g.plot.y0);
  const xOf = (cost: number) =>
    g.plot.x0 +
    ((Math.log10(cost) - Math.log10(domain[0])) /
      (Math.log10(domain[1]) - Math.log10(domain[0]))) *
      (g.plot.x1 - g.plot.x0);
  return (
    <g aria-hidden="true">
      <rect
        x={0}
        y={g.plot.y0}
        width={g.railW}
        height={g.plot.y1 - g.plot.y0}
        className="rail-strip"
      />
      {ASR_TICKS.map((t) => (
        <g key={t}>
          <line
            x1={0}
            y1={r2(yOf(t))}
            x2={g.plot.x1}
            y2={r2(yOf(t))}
            className="grid-line"
          />
          <text
            x={g.plot.x0 + 5}
            y={r2(yOf(t) - 4)}
            className="grid-label num"
          >
            {Math.round(t * 100)}
          </text>
        </g>
      ))}
      <line
        x1={g.dividerX}
        y1={g.plot.y0 - 6}
        x2={g.dividerX}
        y2={g.plot.y1}
        className="rail-divider"
      />
      <line
        x1={g.plot.x0}
        y1={g.plot.y1}
        x2={g.plot.x1}
        y2={g.plot.y1}
        className="axis-line"
      />
      {decadeTicks(domain).map((d) => (
        <g key={d}>
          <line
            x1={r2(xOf(d))}
            y1={g.plot.y1}
            x2={r2(xOf(d))}
            y2={g.plot.y1 + 5}
            className="axis-line"
          />
          <text
            x={r2(xOf(d))}
            y={g.plot.y1 + 20}
            className="tick-label num"
            textAnchor="middle"
          >
            {d < 1 ? `$${d.toFixed(2)}` : `$${d}`}
          </text>
        </g>
      ))}
    </g>
  );
}

interface WideSolution {
  placed: ReturnType<typeof placeLabels>["placed"];
  keyedSet: Set<string>;
}

/** Solve the wide label layout once, so badges and list agree. */
function solveWide(
  points: Pt[],
  dupes: Set<string>,
): WideSolution {
  const g = WIDE;
  const furniture: Rect[] = [
    { x: 0, y: 0, w: 104, h: 30 },
    { x: g.plot.x0, y: 4, w: 210, h: 16 },
    ...ASR_TICKS.map((t) => ({
      x: g.plot.x0 + 2,
      y: g.plot.y0 + (1 - t / ASR_AXIS_MAX) * (g.plot.y1 - g.plot.y0) - 17,
      w: 26,
      h: 13,
    })),
  ];
  /* Rail labels take a stacked column just inside the plot's
   * left edge, in attack success order, with leader lines back
   * to their discs. The generic solver cannot place them: the
   * rail discs sit within a few pixels of each other, so any
   * anchor beside a disc collides with the next disc's label,
   * and keying them out would bury five of the board's models
   * behind bare numbers. The column is deterministic, clear of
   * the axis labels (which end 34 px into the plot), and the
   * plotted labels are then solved against it as furniture. */
  const railPts = points
    .filter((p) => p.rail)
    .sort((a, b) => a.y - b.y);
  const railPlaced: WideSolution["placed"] = [];
  if (railPts.length > 0) {
    const pitch = 17;
    const stackH = (railPts.length - 1) * pitch + 15;
    const meanY =
      railPts.reduce((s, p) => s + p.y, 0) / railPts.length;
    const colX = g.plot.x0 + 34;
    const pointBoxes: Rect[] = points
      .filter((p) => !p.rail)
      .map((p) => ({ x: p.x - 7, y: p.y - 7, w: 14, h: 14 }));
    const hitsPoint = (top: number) =>
      railPts.some((p, i) => {
        const rect: Rect = {
          x: colX,
          y: top + i * pitch,
          w: estimateLabelWidth(labelFor(p.row, dupes)),
          h: 15,
        };
        return pointBoxes.some(
          (b) =>
            rect.x < b.x + b.w &&
            b.x < rect.x + rect.w &&
            rect.y < b.y + b.h &&
            b.y < rect.y + rect.h,
        );
      });
    let top = meanY - stackH / 2;
    const loBound = g.labelBounds.y;
    const hiBound = g.labelBounds.y + g.labelBounds.h - stackH;
    top = Math.min(Math.max(top, loBound), hiBound);
    for (const shift of [0, -8, 8, -16, 16, -26, 26]) {
      const candidate = Math.min(Math.max(top + shift, loBound), hiBound);
      if (!hitsPoint(candidate)) {
        top = candidate;
        break;
      }
    }
    railPts.forEach((p, i) => {
      railPlaced.push({
        runId: p.row.run_id,
        x: colX,
        y: top + i * pitch,
        w: estimateLabelWidth(labelFor(p.row, dupes)),
        h: 15,
        leader: true,
      });
    });
    furniture.push(...railPlaced);
  }
  const railObstacles: LayoutPoint[] = railPts.map((p) => ({
    runId: p.row.run_id,
    x: p.x,
    y: p.y,
    marker: 7,
    label: null,
  }));
  const layoutPts: LayoutPoint[] = [
    ...points
      .filter((p) => !p.rail)
      .map((p) => ({
        runId: p.row.run_id,
        x: p.x,
        y: p.y,
        marker: 7,
        label: labelFor(p.row, dupes),
      })),
    ...railObstacles,
  ];
  const first = placeLabels(layoutPts, furniture, g.labelBounds);
  const placed = [...railPlaced, ...first.placed];
  if (first.keyed.length === 0) {
    return { placed, keyedSet: new Set() };
  }
  const keyedSet = new Set(first.keyed);
  const retry = layoutPts.map((p) =>
    keyedSet.has(p.runId) ? { ...p, marker: 10, label: null } : p,
  );
  const second = placeLabels(retry, furniture, g.labelBounds);
  for (const id of second.keyed) keyedSet.add(id);
  return { placed: [...railPlaced, ...second.placed], keyedSet };
}

function WideChart({
  points,
  domain,
  dupes,
  indexOf,
  solution,
}: {
  points: Pt[];
  domain: [number, number];
  dupes: Set<string>;
  indexOf: Map<string, number>;
  solution: WideSolution;
}) {
  const g = WIDE;
  const { placed, keyedSet } = solution;
  const ptById = new Map(points.map((p) => [p.row.run_id, p]));
  return (
    <svg
      viewBox={`0 0 ${g.w} ${g.h}`}
      className="scatter-svg"
      role="img"
      aria-label="Scatter of recorded cost per run against attack success, with a rail for results that carry no cost"
      data-domain-lo={domain[0]}
      data-domain-hi={domain[1]}
      data-plot={`${g.plot.x0},${g.plot.y0},${g.plot.x1},${g.plot.y1}`}
      data-rail-cx={g.railCx}
    >
      <Grid g={g} domain={domain} />
      <text x={2} y={13} className="rail-head">
        No recorded
      </text>
      <text x={2} y={27} className="rail-head">
        API cost
      </text>
      <text x={g.plot.x0} y={16} className="axis-caption">
        Attack success, percent
      </text>
      {points.map((p) => (
        <Marker
          key={p.row.run_id}
          p={p}
          badge={keyedSet.has(p.row.run_id) ? indexOf.get(p.row.run_id)! : null}
        />
      ))}
      {placed.map((l) => {
        const p = ptById.get(l.runId)!;
        const nearX = Math.min(Math.max(p.x, l.x), l.x + l.w);
        const nearY = Math.min(Math.max(p.y, l.y), l.y + l.h);
        return (
          <g key={l.runId}>
            {l.leader && (
              <line
                x1={r2(p.x)}
                y1={r2(p.y)}
                x2={r2(nearX)}
                y2={r2(nearY)}
                className="leader"
                aria-hidden="true"
              />
            )}
            <text
              x={r2(l.x)}
              y={r2(l.y + 11)}
              className="scatter-label"
              data-label-for={l.runId}
            >
              {labelFor(p.row, dupes)}
            </text>
          </g>
        );
      })}
      <text x={g.plot.x0} y={g.h - 8} className="axis-caption">
        Recorded cost per run, US dollars, log scale
      </text>
    </svg>
  );
}

function PhoneChart({
  points,
  domain,
  indexOf,
}: {
  points: Pt[];
  domain: [number, number];
  indexOf: Map<string, number>;
}) {
  const g = PHONE;
  return (
    <svg
      viewBox={`0 0 ${g.w} ${g.h}`}
      className="scatter-svg"
      role="img"
      aria-label="Scatter of recorded cost per run against attack success. Points carry numbers keyed to the list below the chart."
      data-domain-lo={domain[0]}
      data-domain-hi={domain[1]}
      data-plot={`${g.plot.x0},${g.plot.y0},${g.plot.x1},${g.plot.y1}`}
      data-rail-cx={g.railCx}
    >
      <Grid g={g} domain={domain} />
      <text x={g.plot.x0} y={14} className="axis-caption">
        Attack success, percent
      </text>
      {points.map((p) => (
        <Marker key={p.row.run_id} p={p} badge={indexOf.get(p.row.run_id)!} />
      ))}
      <text x={g.plot.x0} y={g.h - 6} className="axis-caption">
        Cost per run, dollars, log scale
      </text>
    </svg>
  );
}

function joinNames(names: string[]): string {
  if (names.length <= 1) return names.join("");
  if (names.length === 2) return `${names[0]} and ${names[1]}`;
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

function KeyedItem({
  row,
  index,
  sets,
  dupes,
}: {
  row: BoardRow;
  index: number;
  sets: ReturnType<typeof scatterSets>;
  dupes: Set<string>;
}) {
  const rail = sets.rail.some((r) => r.run_id === row.run_id);
  /* The meta line is built from whole phrases, each rendered as
   * an unbreakable span, so the line wraps only at phrase
   * boundaries and never inside a phrase like a cost with its
   * lower bound note (round 9 deviation carried here). */
  const phrases: string[] = [fmtPct(row.asr_conditional!)];
  if (rail) {
    phrases.push(
      railCostState(row) === "recorded-zero"
        ? "recorded cost $0.00"
        : "no recorded cost",
    );
  } else {
    phrases.push(`${fmtUsdExact(row.total_cost_usd!)} per run`);
    if (costIsLowerBound(row)) phrases.push("a lower bound");
  }
  return (
    <li className="keyed-item">
      <span className="keyed-num num">{index}</span>
      <span className="keyed-name">{labelFor(row, dupes)}</span>
      <span className="keyed-meta num">
        {phrases.map((p, i) => (
          <span key={i} className="keyed-phrase">
            {p}
            {i < phrases.length - 1 && (
              <span className="keyed-sep"> · </span>
            )}
          </span>
        ))}
      </span>
    </li>
  );
}

export default function Scatter() {
  const groups = boardGroups();
  const allRows = [...groups.full, ...groups.slices, ...groups.flagged];
  const dupes = duplicateShortNames(allRows);
  const sets = scatterSets(allRows);
  const domain = costDomain(sets.plotted.map((r) => r.total_cost_usd!));
  const byAsr = [...sets.population].sort(
    (a, b) => (a.asr_conditional ?? 0) - (b.asr_conditional ?? 0),
  );
  const indexOf = new Map(byAsr.map((r, i) => [r.run_id, i + 1]));
  const widePoints = buildPoints(sets, domain, WIDE);
  const phonePoints = buildPoints(sets, domain, PHONE);
  const versions = boardVersions();
  const zeroNames = sets.rail
    .filter((r) => railCostState(r) === "recorded-zero")
    .map((r) => shortName(r));
  const noneNames = sets.rail
    .filter((r) => railCostState(r) === "unrecorded")
    .map((r) => shortName(r));
  const solution = solveWide(widePoints, dupes);
  const keyedRows = byAsr.filter((r) => solution.keyedSet.has(r.run_id));

  return (
    <section className="section" aria-labelledby="scatter-title" data-section="scatter">
      <p className="section-label">Cost</p>
      <h2 className="section-title" id="scatter-title">
        What robustness costs per run
      </h2>
      <p className="section-lede">
        Recorded cost for one full run against attack success, on the
        ranking's shared 0 to 30 percent scale. Ranked results are filled
        discs and flagged results are amber rings.
      </p>

      <div className="scatter-wide">
        <WideChart
          points={widePoints}
          domain={domain}
          dupes={dupes}
          indexOf={indexOf}
          solution={solution}
        />
        {keyedRows.length > 0 && (
          <div className="keyed-box">
            <p className="keyed-head">
              Points too close to label in place, keyed by number
            </p>
            <ul className="keyed-list">
              {keyedRows.map((row) => (
                <KeyedItem
                  key={row.run_id}
                  row={row}
                  index={indexOf.get(row.run_id)!}
                  sets={sets}
                  dupes={dupes}
                />
              ))}
            </ul>
          </div>
        )}
      </div>

      <div className="scatter-phone">
        <p className="keyed-head">
          The band at the left holds the results with no recorded API
          cost, each numbered into the key below.
        </p>
        <PhoneChart points={phonePoints} domain={domain} indexOf={indexOf} />
        <ul className="keyed-list phone-key">
          {byAsr.map((row) => (
            <KeyedItem
              key={row.run_id}
              row={row}
              index={indexOf.get(row.run_id)!}
              sets={sets}
              dupes={dupes}
            />
          ))}
        </ul>
      </div>

      <div className="chart-captions">
        <p>
          Cost is the recorded total for one full run, plotted on a log
          scale. A short tick pointing left from a point marks a lower
          bound. Some of that run's calls went unpriced, so the true cost
          sits higher than the point.
        </p>
        <p>
          {fmtInt(sets.rail.length)} ranked models ran locally and hold
          no place on the cost axis, so they sit on the rail at the left
          at their attack success. {joinNames(zeroNames)} recorded a cost
          of $0.00, while {joinNames(noneNames)} recorded no cost at all.
          A recorded zero and no recorded cost are different facts, and
          the rail keeps them apart in words.
        </p>
        <p>
          The chart plots {fmtInt(sets.plotted.length)} of the board's{" "}
          {fmtInt(payload.ranked.length + payload.unranked.length)}{" "}
          results, with {fmtInt(sets.rail.length)} more on the rail. The{" "}
          {fmtInt(sets.slices.length)} guardrail slices are not plotted,
          since they ran on the {fmtInt(sets.slices[0]?.n_cases ?? 0)} case
          abstain base and record no serving cost.
        </p>
      </div>
      <p className="chart-id">
        Peira decision robustness board, cost against attack success.{" "}
        {fmtInt(sets.population.length)} full suite results on{" "}
        {fmtInt(groups.fullCases)} cases each, {fmtInt(sets.plotted.length)}{" "}
        plotted and {fmtInt(sets.rail.length)} on the rail. Dataset{" "}
        {versions.dataset}, updated {boardDateWords()}.
      </p>
    </section>
  );
}

