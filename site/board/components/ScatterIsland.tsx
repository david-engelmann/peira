"use client";

import { useState } from "react";
import { fmtPct, fmtCi, fmtUsdExact } from "@/lib/format";
import { ASR_AXIS_MAX, ASR_TICKS } from "@/lib/chart";
import {
  placeLabels,
  nudgePoints,
  estimateLabelWidth,
  type LayoutPoint,
  type PlacedLabel,
  type Rect,
} from "@/lib/layout";
import { LOGO_PATHS, type LogoSlug } from "@/lib/logoPaths";
import type { ScatterDatum } from "@/lib/scatterData";

/**
 * The cost scatter island (redesign). Receives the shaped
 * point set from lib/scatterData, so no payload module enters
 * the client bundle. Every point is a disc in its maker's
 * family color carrying the maker's mark, and every point is
 * named in place by the deterministic label solver. Nothing
 * is keyed out to numbers: labels the solver cannot place
 * beside their point move to a labelled overflow stack
 * inside the plot, tied back with a leader line. Hover, tap
 * and keyboard focus enlarge the point, bold its label, and
 * open a small card with the model's figures. Flagged
 * results keep the amber ring. The corners carry the two
 * readings the data supports, in display type.
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
  h: 700,
  railW: 50,
  railCx: 25,
  dividerX: 58,
  plot: { x0: 66, x1: 354, y0: 34, y1: 420 },
  labelBounds: { x: 0, y: 26, w: 358, h: 392 },
};

/* Corner annotation furniture. The solver keeps labels out
 * of these boxes, and the audit keeps the annotation text
 * clear of every other text node in the section. The
 * top-right reading is the payload's own extremes: the
 * priciest run is also the easiest to flip. The bottom-left
 * names jev-1.14.0 at its recorded twenty cents a run. */
const WIDE_ANNOT_TR: Rect = { x: 580, y: 38, w: 258, h: 62 };
const WIDE_ANNOT_BL: Rect = { x: 134, y: 428, w: 300, h: 72 };
const PHONE_ANNOT_TR: Rect = { x: 138, y: 2, w: 216, h: 40 };

const r2 = (v: number) => Math.round(v * 100) / 100;

interface Pt {
  d: ScatterDatum;
  x: number;
  y: number;
  nudged: boolean;
}

function decadeTicks(domain: [number, number]): number[] {
  const out: number[] = [];
  const start = Math.ceil(Math.log10(domain[0]));
  const end = Math.floor(Math.log10(domain[1]));
  for (let d = start; d <= end; d++) out.push(10 ** d);
  return out;
}

function buildPoints(
  plotted: ScatterDatum[],
  rail: ScatterDatum[],
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
  const plottedPts: Pt[] = plotted.map((d) => ({
    d,
    x: xOf(d.cost!),
    y: yOf(d.asr),
    nudged: false,
  }));
  const railPts: Pt[] = rail.map((d) => ({
    d,
    x: g.railCx,
    y: yOf(d.asr),
    nudged: false,
  }));
  const wide = g === WIDE;
  const spread = (pts: Pt[], minSep: number, maxShift: number) => {
    const wrappers = pts.map((p) => ({ runId: p.d.runId, x: p.x, y: p.y, p }));
    const moved = nudgePoints(wrappers, minSep, maxShift);
    for (const wpt of wrappers) {
      wpt.p.x = wpt.x;
      wpt.p.y = wpt.y;
      wpt.p.nudged = moved.has(wpt.runId);
    }
  };
  spread(plottedPts, wide ? 24 : 22, wide ? 12 : 18.5);
  /* The rail chain sits inside a few pixels on the true axis,
   * tighter than one disc diameter, so it spreads as a stack:
   * sorted passes hold the separation while every point stays
   * within the audit's nudged slack of its true position. The
   * separation target is what the monogram letters need to
   * stay clear of each other. */
  {
    const sorted = [...railPts].sort((a, b) => a.y - b.y);
    const orig = new Map(sorted.map((p) => [p.d.runId, p.y]));
    const minSep = wide ? 15 : 17;
    const maxShift = wide ? 12 : 18;
    for (let pass = 0; pass < 8; pass++) {
      for (let i = 1; i < sorted.length; i++) {
        const lo = Math.max(
          sorted[i - 1].y + minSep,
          orig.get(sorted[i].d.runId)! - maxShift,
        );
        sorted[i].y = Math.min(
          Math.max(sorted[i].y, lo),
          orig.get(sorted[i].d.runId)! + maxShift,
        );
      }
      for (let i = sorted.length - 2; i >= 0; i--) {
        const hi = Math.min(
          sorted[i + 1].y - minSep,
          orig.get(sorted[i].d.runId)! + maxShift,
        );
        sorted[i].y = Math.max(
          Math.min(sorted[i].y, hi),
          orig.get(sorted[i].d.runId)! - maxShift,
        );
      }
    }
    for (const p of sorted) {
      if (Math.abs(p.y - orig.get(p.d.runId)!) > 0.01) p.nudged = true;
    }
  }
  return [...plottedPts, ...railPts];
}

function Marker({
  p,
  active,
  onActivate,
  onDeactivate,
}: {
  p: Pt;
  active: boolean;
  onActivate: (id: string) => void;
  onDeactivate: () => void;
}) {
  const d = p.d;
  const cls = d.flagged ? "pt-flagged" : "pt-ranked";
  return (
    <g
      className="scatter-point"
      data-scatter={d.rail ? "rail" : "plot"}
      data-run-id={d.runId}
      data-cost={d.cost ?? ""}
      data-asr={d.asr}
      data-nudged={p.nudged ? "true" : undefined}
      data-active={active ? "true" : undefined}
      tabIndex={0}
      role="button"
      aria-label={d.title}
      onMouseEnter={() => onActivate(d.runId)}
      onMouseLeave={onDeactivate}
      onFocus={() => onActivate(d.runId)}
      onBlur={onDeactivate}
      onClick={() => onActivate(d.runId)}
    >
      <title>{d.title}</title>
      <g className="pt-mark">
        <circle
          cx={r2(p.x)}
          cy={r2(p.y)}
          r={10}
          className={cls}
          style={{
            fill: d.color,
            stroke: d.flagged ? undefined : "rgba(255, 255, 255, 0.28)",
          }}
        />
        {d.logoSlug ? (
          <path
            d={LOGO_PATHS[d.logoSlug as LogoSlug]}
            transform={`translate(${r2(p.x - 6)} ${r2(p.y - 6)}) scale(0.5)`}
            fill={d.glyph}
            aria-hidden="true"
          />
        ) : (
          <text
            x={r2(p.x)}
            y={r2(p.y)}
            className="pt-mono"
            fill={d.glyph}
            aria-hidden="true"
          >
            {d.monoLetter}
          </text>
        )}
      </g>
      {d.lowerBound && (
        <g className="lb-tick" aria-hidden="true">
          <line x1={r2(p.x - 24)} y1={r2(p.y)} x2={r2(p.x - 12.5)} y2={r2(p.y)} />
          <polygon
            points={`${r2(p.x - 24)},${r2(p.y)} ${r2(p.x - 19.5)},${r2(p.y - 2.6)} ${r2(p.x - 19.5)},${r2(p.y + 2.6)}`}
          />
        </g>
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
          <text x={g.plot.x0 + 5} y={r2(yOf(t) - 4)} className="grid-label num">
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

interface Solution {
  placed: PlacedLabel[];
}

function solveWide(points: Pt[]): Solution {
  const g = WIDE;
  const furniture: Rect[] = [
    { x: 0, y: 0, w: 104, h: 30 },
    { x: g.plot.x0, y: 4, w: 210, h: 16 },
    WIDE_ANNOT_TR,
    WIDE_ANNOT_BL,
    ...ASR_TICKS.map((t) => ({
      x: g.plot.x0 + 2,
      y: g.plot.y0 + (1 - t / ASR_AXIS_MAX) * (g.plot.y1 - g.plot.y0) - 17,
      w: 26,
      h: 13,
    })),
  ];
  /* Rail labels take a stacked column just inside the plot's
   * left edge, in attack success order, with leader lines back
   * to their discs, as before the redesign. The plotted labels
   * are then solved against the column as furniture. */
  const railPts = points.filter((p) => p.d.rail).sort((a, b) => a.y - b.y);
  const railPlaced: PlacedLabel[] = [];
  if (railPts.length > 0) {
    const pitch = 19;
    const stackH = (railPts.length - 1) * pitch + 15;
    const meanY = railPts.reduce((s, p) => s + p.y, 0) / railPts.length;
    const colX = g.plot.x0 + 34;
    let top = meanY - stackH / 2;
    const loBound = g.labelBounds.y;
    const hiBound = g.labelBounds.y + g.labelBounds.h - stackH;
    top = Math.min(Math.max(top, loBound), hiBound);
    railPts.forEach((p, i) => {
      railPlaced.push({
        runId: p.d.runId,
        x: colX,
        y: top + i * pitch,
        w: estimateLabelWidth(p.d.label),
        h: 15,
        leader: true,
      });
    });
    furniture.push(...railPlaced);
  }
  const railObstacles: LayoutPoint[] = railPts.map((p) => ({
    runId: p.d.runId,
    x: p.x,
    y: p.y,
    marker: 12,
    label: null,
  }));
  const layoutPts: LayoutPoint[] = [
    ...points
      .filter((p) => !p.d.rail)
      .map((p) => ({
        runId: p.d.runId,
        x: p.x,
        y: p.y,
        marker: 12,
        label: p.d.label,
      })),
    ...railObstacles,
  ];
  const first = placeLabels(layoutPts, furniture, g.labelBounds);
  const placed: PlacedLabel[] = [...railPlaced, ...first.placed];
  if (first.keyed.length > 0) {
    /* No keyed list. Unplaced labels take slots in the plot's
     * empty lower band in attack success order, each slot
     * checked against everything already placed, each with a
     * leader line back to its point. */
    const byId = new Map(points.map((p) => [p.d.runId, p]));
    const unplaced = first.keyed
      .map((id) => byId.get(id)!)
      .sort((a, b) => b.d.asr - a.d.asr);
    const taken: Rect[] = [
      ...placed,
      ...furniture,
      ...points.map((p) => ({ x: p.x - 12, y: p.y - 12, w: 24, h: 24 })),
    ];
    const hits = (r: Rect) =>
      taken.some(
        (b) =>
          r.x < b.x + b.w + 2 &&
          b.x < r.x + r.w + 2 &&
          r.y < b.y + b.h + 2 &&
          b.y < r.y + r.h + 2,
      );
    for (const p of unplaced) {
      const w = estimateLabelWidth(p.d.label);
      let slot: Rect | null = null;
      outer: for (let y = 402; y < 528; y += 19) {
        for (const x of [468, 640, 806]) {
          const r: Rect = { x, y, w, h: 15 };
          if (x + w <= 1128 && !hits(r)) {
            slot = r;
            break outer;
          }
        }
      }
      if (slot) {
        taken.push(slot);
        placed.push({ ...slot, runId: p.d.runId, leader: true });
      }
    }
  }
  return { placed };
}

function solvePhone(points: Pt[]): Solution {
  const g = PHONE;
  const furniture: Rect[] = [
    { x: g.plot.x0, y: 0, w: 170, h: 20 },
    PHONE_ANNOT_TR,
    ...ASR_TICKS.map((t) => ({
      x: g.plot.x0 + 2,
      y: g.plot.y0 + (1 - t / ASR_AXIS_MAX) * (g.plot.y1 - g.plot.y0) - 17,
      w: 26,
      h: 13,
    })),
  ];
  const layoutPts: LayoutPoint[] = points.map((p) => ({
    runId: p.d.runId,
    x: p.x,
    y: p.y,
    marker: 11,
    label: p.d.label,
  }));
  const first = placeLabels(layoutPts, furniture, g.labelBounds, 0.84);
  const placed: PlacedLabel[] = [...first.placed];
  if (first.keyed.length > 0) {
    /* Phone overflow: a labelled stack under the plot, in
     * attack success order across two columns, each label
     * tied to its point with a leader line. The chart grows
     * to fit the stack, so the count is never capped. */
    const byId = new Map(points.map((p) => [p.d.runId, p]));
    const unplaced = first.keyed
      .map((id) => byId.get(id)!)
      .sort((a, b) => b.d.asr - a.d.asr);
    const perCol = Math.ceil(unplaced.length / 2);
    unplaced.forEach((p, i) => {
      const col = i < perCol ? 0 : 1;
      const rowI = i - col * perCol;
      placed.push({
        runId: p.d.runId,
        x: 8 + col * 178,
        y: 480 + rowI * 19,
        w: estimateLabelWidth(p.d.label) * 0.84,
        h: 15,
        leader: true,
      });
    });
  }
  return { placed };
}

function Labels({
  placed,
  points,
  activeId,
  phone,
}: {
  placed: PlacedLabel[];
  points: Pt[];
  activeId: string | null;
  phone?: boolean;
}) {
  const ptById = new Map(points.map((p) => [p.d.runId, p]));
  return (
    <>
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
              className={`scatter-label${phone ? " phone" : ""}`}
              data-label-for={l.runId}
              data-active={activeId === l.runId ? "true" : undefined}
            >
              {p.d.label}
            </text>
          </g>
        );
      })}
    </>
  );
}

function HoverCard({ p, g }: { p: Pt; g: Geom }) {
  const d = p.d;
  const leftPct = (p.x / g.w) * 100;
  const topPct = (p.y / g.h) * 100;
  const cls = leftPct > 74 ? " align-r" : leftPct < 20 ? " align-l" : "";
  const below = p.y < g.plot.y0 + 92;
  return (
    <div
      className={`scatter-card${cls}${below ? " below" : ""}`}
      style={{ left: `${leftPct}%`, top: `${topPct}%` }}
      aria-hidden="true"
    >
      <p className="sc-name">{d.label}</p>
      <div className="sc-rows">
        <div className="sc-row">
          <span className="sc-k">Attack success</span>
          <span className="sc-v num">{fmtPct(d.asr)}</span>
        </div>
        {d.ci !== null && (
          <div className="sc-row">
            <span className="sc-k">95% CI</span>
            <span className="sc-v num">{fmtCi(d.ci)}</span>
          </div>
        )}
        <div className="sc-row">
          <span className="sc-k">Recorded cost</span>
          <span className="sc-v num">
            {d.rail
              ? d.cost !== null
                ? "$0.00"
                : "none recorded"
              : `${fmtUsdExact(d.cost!)} per run${d.lowerBound ? ", a lower bound" : ""}`}
          </span>
        </div>
        {d.benign !== null && (
          <div className="sc-row">
            <span className="sc-k">Benign accuracy</span>
            <span className="sc-v num">{fmtPct(d.benign)}</span>
          </div>
        )}
      </div>
    </div>
  );
}

export default function ScatterIsland({
  plotted,
  rail,
  domain,
  phone,
}: {
  plotted: ScatterDatum[];
  rail: ScatterDatum[];
  domain: [number, number];
  phone?: boolean;
}) {
  const g = phone ? PHONE : WIDE;
  const points = buildPoints(plotted, rail, domain, g);
  const solution = phone ? solvePhone(points) : solveWide(points);
  const overflow = phone
    ? solution.placed.filter((l) => l.y >= 480).length
    : 0;
  const height = phone
    ? 480 + Math.ceil(overflow / 2) * 19 + 52
    : WIDE.h;
  const [activeId, setActiveId] = useState<string | null>(null);
  const active = points.find((p) => p.d.runId === activeId) ?? null;
  return (
    <div className="scatter-wrap">
      <svg
        viewBox={`0 0 ${g.w} ${height}`}
        className="scatter-svg"
        role="img"
        aria-label="Scatter of recorded cost per run against attack success, every point named, with a rail for results that carry no cost"
        data-domain-lo={domain[0]}
        data-domain-hi={domain[1]}
        data-plot={`${g.plot.x0},${g.plot.y0},${g.plot.x1},${g.plot.y1}`}
        data-rail-cx={g.railCx}
      >
        <Grid g={g} domain={domain} />
        {!phone && (
          <>
            <text x={2} y={13} className="rail-head">
              No recorded
            </text>
            <text x={2} y={27} className="rail-head">
              API cost
            </text>
          </>
        )}
        <text x={g.plot.x0} y={phone ? 14 : 16} className="axis-caption">
          Attack success, percent
        </text>
        {phone ? (
          <g className="corner-note">
            <text x={354} y={22} textAnchor="end" className="corner-title phone">
              Expensive and fragile
            </text>
            <text x={354} y={38} textAnchor="end" className="corner-sub phone">
              The priciest run flipped most of all
            </text>
          </g>
        ) : (
          <>
            <g className="corner-note">
              <text x={838} y={66} textAnchor="end" className="corner-title">
                Expensive and fragile
              </text>
              <text x={838} y={90} textAnchor="end" className="corner-sub">
                The priciest run flipped most of all
              </text>
            </g>
            <g className="corner-note">
              <text x={140} y={470} className="corner-title">
                Near-free and tough
              </text>
              <text x={140} y={494} className="corner-sub">
                Jev 1.14 held at twenty cents a run
              </text>
            </g>
          </>
        )}
        {points.map((p) => (
          <Marker
            key={p.d.runId}
            p={p}
            active={activeId === p.d.runId}
            onActivate={setActiveId}
            onDeactivate={() => setActiveId(null)}
          />
        ))}
        <Labels
          placed={solution.placed}
          points={points}
          activeId={activeId}
          phone={phone}
        />
        <text x={g.plot.x0} y={g.plot.y1 + 40} className="axis-caption">
          {phone
            ? "Cost per run, dollars, log scale"
            : "Recorded cost per run, US dollars, log scale"}
        </text>
        {phone && (
          <g className="corner-note">
            <text x={8} y={height - 26} className="corner-title phone">
              Near-free and tough
            </text>
            <text x={8} y={height - 10} className="corner-sub phone">
              Jev 1.14 held at twenty cents a run
            </text>
          </g>
        )}
      </svg>
      {active && <HoverCard p={active} g={{ ...g, h: height }} />}
    </div>
  );
}
