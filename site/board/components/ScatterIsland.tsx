"use client";

import { useMemo, useRef, useState, type MouseEvent } from "react";
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
 * named: beside its disc where the deterministic label solver
 * finds a collision-free side, on the rail as a list row
 * beside its disc, or in the overflow stack, where each row
 * carries the point's own disc glyph beside its name and
 * figures. No label is ever tied to its point by a drawn
 * line: there are no leader lines anywhere in the chart.
 * Flagged results keep the amber ring. The corners carry the
 * two readings the data supports, in display type.
 *
 * The detail card is one state machine for every pointer.
 * Hover and keyboard focus preview a point; a click or tap
 * pins its card open, and the pinned card carries a close
 * control, because touch has no pointer-leave to dismiss by.
 * Tapping the pinned point again, tapping anywhere in the
 * chart that is not a point, or pressing Escape closes it.
 * A tap resolves to the nearest point within the touch
 * radius, so a fingertip in the packed cluster opens the
 * point it actually landed on, not whichever disc's box
 * happens to paint on top.
 *
 * The phone variant changes the chart's shape rather than
 * shrinking it (doctrine D7). Its plot is drawn at true CSS
 * pixels for a 390 px phone, runs the full width of the well
 * at more than twice the old plot height, and carries no
 * rail column: the rail points' names already live in the
 * list under the plot, each beside its own disc, so the
 * plot spends its whole width on the cost axis. Type stays
 * at the wide chart's sizes; nothing renders under the
 * doctrine's 10 px floor.
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

/* The wide rail is a list column in its own right: each rail
 * disc sits at the column's left with its name directly
 * beside it in the same row, and the plot begins after the
 * divider. Label bounds for plotted points start past the
 * divider, so a plotted label can never stray into the rail
 * list or across the divider line. */
const WIDE: Geom = {
  w: 1132,
  h: 676,
  railW: 260,
  railCx: 46,
  dividerX: 268,
  plot: { x0: 292, x1: 1124, y0: 36, y1: 604 },
  labelBounds: { x: 276, y: 30, w: 854, h: 574 },
};

/* The phone geometry is drawn at true CSS pixels for the
 * audited 390 px width: the page padding leaves 358 px and
 * the well's own padding and border leave 328, so one SVG
 * unit is one CSS pixel and the solver's label estimates
 * (calibrated at the wide chart's 11.5 px label size) hold
 * exactly. There is no rail column: railW is 0 and the rail
 * points render only as list entries under the plot. The
 * divider sits off-canvas and the grid skips it. */
const PHONE: Geom = {
  w: 328,
  h: 700,
  railW: 0,
  railCx: 0,
  dividerX: -10,
  plot: { x0: 10, x1: 320, y0: 52, y1: 566 },
  labelBounds: { x: 4, y: 44, w: 320, h: 526 },
};

/* Phone overflow list geometry: entries begin below the
 * cost axis caption, one column of two-line rows (disc and
 * name, then the figures under the name). One column, never
 * two: at full label size the longest names on the board
 * need the whole width, and a name is never truncated to
 * fit a column. */
const PHONE_LIST_TOP = 640;
const PHONE_ENTRY_PITCH = 34;
const PHONE_ENTRY_X = 6;

/* The two corner readings, single-sourced: the wide and
 * phone renders set the same words. The top-right reading is
 * the payload's own extremes: the priciest run is also the
 * easiest to flip. The bottom-left names jev-1.14.0 at its
 * recorded twenty cents a run. */
const CORNER_TR = {
  title: "Expensive and fragile",
  sub: "The priciest run flipped most of all",
};
const CORNER_BL = {
  title: "Near-free and tough",
  sub: "Jev 1.14 held at twenty cents a run",
};

/* Corner annotation furniture. The solver keeps labels out
 * of these boxes, and the audit keeps the annotation text
 * clear of every other text node in the section. */
const WIDE_ANNOT_TR: Rect = { x: 580, y: 38, w: 258, h: 62 };
const WIDE_ANNOT_BL: Rect = { x: 298, y: 458, w: 300, h: 72 };
/* Phone furniture: the axis caption's box at the top left,
 * the top-right corner reading's box, and the bottom-left
 * corner reading's box. The label bounds begin below the
 * top pair; the boxes exist so the solver also keeps clear
 * of them in the bands it can reach. The bottom-left
 * reading sits inside the plot's empty lower band, where
 * the wide chart puts its own: the shared 0 to 30 scale
 * leaves that band empty of points, and a reading is the
 * honest thing to fill it with. */
const PHONE_ANNOT_CAPTION: Rect = { x: 8, y: 0, w: 158, h: 18 };
const PHONE_ANNOT_TR: Rect = { x: 104, y: 0, w: 220, h: 42 };
const PHONE_ANNOT_BL: Rect = { x: 4, y: 494, w: 240, h: 48 };

const r2 = (v: number) => Math.round(v * 100) / 100;

interface Pt {
  d: ScatterDatum;
  x: number;
  y: number;
  nudged: boolean;
}

/** One overflow stack row: the point's disc, name and figures. */
interface StackEntry {
  runId: string;
  x: number;
  y: number;
}

/* The island's own copy is the only one: lib/charts carries
 * the same helper's history but importing it here would pull
 * the payload module into the client bundle. */
function decadeTicks(domain: [number, number]): number[] {
  const out: number[] = [];
  const start = Math.ceil(Math.log10(domain[0]));
  const end = Math.floor(Math.log10(domain[1]));
  for (let d = start; d <= end; d++) out.push(10 ** d);
  return out;
}

function entryValues(d: ScatterDatum): string {
  const asr = fmtPct(d.asr);
  if (d.rail) return d.cost !== null ? `${asr} · $0.00` : `${asr} · no cost`;
  return `${asr} · ${fmtUsdExact(d.cost!)} per run`;
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
  /* On the phone there are no rail markers: the rail points
   * stand only in the list under the plot, beside their own
   * discs, so nothing unnamed crowds the plot's left edge
   * and the cost axis takes the full width. */
  const railPts: Pt[] =
    g === PHONE
      ? []
      : rail.map((d) => ({
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
   * within the audit's nudged slack of its true position. On
   * the wide chart the separation is the name row pitch: each
   * rail name sits beside its disc in the same row, so the
   * rows need a full label height between centres. */
  {
    const sorted = [...railPts].sort((a, b) => a.y - b.y);
    const orig = new Map(sorted.map((p) => [p.d.runId, p.y]));
    const minSep = wide ? 15.5 : 17;
    const maxShift = wide ? 13 : 18;
    for (let pass = 0; pass < 60; pass++) {
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

function MarkerGlyph({ d }: { d: ScatterDatum }) {
  const cls = d.flagged ? "pt-flagged" : "pt-ranked";
  return (
    <>
      <circle
        cx={0}
        cy={0}
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
          transform="translate(-6 -6) scale(0.5)"
          fill={d.glyph}
          aria-hidden="true"
        />
      ) : (
        <text x={0} y={0} className="pt-mono" fill={d.glyph} aria-hidden="true">
          {d.monoLetter}
        </text>
      )}
    </>
  );
}

/**
 * The point's accessible name: the same figures the hover
 * card shows sighted users (name, attack success, 95% CI,
 * recorded cost, benign accuracy), so the focusable group
 * says in words everything the card says on screen.
 */
function pointAccessibleName(d: ScatterDatum): string {
  const parts = [`${d.label}, attack success ${fmtPct(d.asr)}`];
  if (d.ci !== null) parts.push(`95% CI ${fmtCi(d.ci)}`);
  parts.push(
    d.rail
      ? d.cost !== null
        ? "recorded cost $0.00"
        : "no recorded cost"
      : `recorded cost ${fmtUsdExact(d.cost!)} per run${
          d.lowerBound ? ", a lower bound" : ""
        }`,
  );
  if (d.benign !== null) parts.push(`benign accuracy ${fmtPct(d.benign)}`);
  return parts.join(", ");
}

function Marker({
  p,
  active,
  onActivate,
  onDeactivate,
  onToggle,
}: {
  p: Pt;
  active: boolean;
  onActivate: (id: string) => void;
  onDeactivate: () => void;
  onToggle: (id: string) => void;
}) {
  const d = p.d;
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
      role="group"
      aria-label={pointAccessibleName(d)}
      onMouseEnter={() => onActivate(d.runId)}
      onMouseLeave={onDeactivate}
      onFocus={() => onActivate(d.runId)}
      onBlur={onDeactivate}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onToggle(d.runId);
        }
      }}
    >
      <title>{d.title}</title>
      {/* The translate lives on the outer group and the CSS
        * grow on the inner one: a CSS transform replaces a
        * transform attribute outright, so carrying both on
        * one element threw the active disc to the chart's
        * origin, scaled, the moment it was hovered or pinned.
        * Nested, the grow scales the mark around its own
        * centre (transform-box fill-box) and the point stays
        * where it was plotted. */}
      <g transform={`translate(${r2(p.x)} ${r2(p.y)})`}>
        <g className="pt-mark">
          <MarkerGlyph d={d} />
          <circle className="pt-focus-ring" r={13.5} aria-hidden="true" />
        </g>
      </g>
      {/* The touch target: a transparent circle well past the
        * disc (r 23 against the disc's 10, a 46 px target at
        * the phone's true-pixel scale), painted last in the
        * group so it takes the tap. Clicks are not handled
        * here: the island's SVG handler resolves any tap in
        * the chart to the nearest point within this radius,
        * so overlapping targets in the packed cluster cannot
        * open the wrong card. */}
      <circle
        className="pt-hit"
        cx={r2(p.x)}
        cy={r2(p.y)}
        r={23}
        aria-hidden="true"
      />
      {/* No lower-bound glyph beside the disc: the short arrow
        * that used to sit here floated in empty space and read
        * as a stray mark pointing at nothing. The lower-bound
        * fact rides in the point's title, its detail card, and
        * the caption under the chart. */}
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
      {g.railW > 0 && (
        <rect
          x={0}
          y={g.plot.y0}
          width={g.railW}
          height={g.plot.y1 - g.plot.y0}
          className="rail-strip"
        />
      )}
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
      {g.railW > 0 && (
        <line
          x1={g.dividerX}
          y1={g.plot.y0 - 6}
          x2={g.dividerX}
          y2={g.plot.y1}
          className="rail-divider"
        />
      )}
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
  stack: StackEntry[];
}

function baseFurniture(g: Geom): Rect[] {
  return [
    { x: 0, y: 0, w: 104, h: 30 },
    { x: g.plot.x0, y: 4, w: 210, h: 16 },
    ...ASR_TICKS.map((t) => ({
      x: g.plot.x0 + 2,
      y: g.plot.y0 + (1 - t / ASR_AXIS_MAX) * (g.plot.y1 - g.plot.y0) - 17,
      w: 26,
      h: 13,
    })),
  ];
}

function solveWide(points: Pt[]): Solution {
  const g = WIDE;
  const furniture: Rect[] = [
    ...baseFurniture(g),
    WIDE_ANNOT_TR,
    WIDE_ANNOT_BL,
  ];
  /* Rail names sit directly beside their discs, one row per
   * point, as a list inside the rail column: disc, then name,
   * on the point's own row. The placed rects join the
   * furniture, so plotted labels solve around the list. */
  const railPts = points.filter((p) => p.d.rail).sort((a, b) => a.y - b.y);
  const railPlaced: PlacedLabel[] = railPts.map((p) => ({
    runId: p.d.runId,
    x: g.railCx + 18,
    y: p.y - 7.5,
    w: estimateLabelWidth(p.d.label),
    h: 15,
  }));
  furniture.push(...railPlaced);
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
  const stack: StackEntry[] = [];
  if (first.keyed.length > 0) {
    /* No keyed list and no drawn lines. A label the solver
     * cannot seat beside its point takes a row in the plot's
     * empty lower band, in attack success order, each row
     * carrying the point's own disc glyph beside its name and
     * figures. Rows are scanned against everything already
     * placed, so the stack never covers a point or a label. */
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
    /* The scan geometry derives from the Geom, so the stack
     * follows the chart when the chart moves: rows are one
     * entry tall on a fixed pitch, the right edge is the
     * label bounds' right edge, the primary band is the
     * plot's empty lower stretch, and the fallback band is
     * the rest of the label bounds above it. Within a row
     * the scan sweeps right from the label bounds' left edge
     * and takes the first seat that hits nothing. A point
     * that finds no seat in either band fails the render
     * loudly rather than shipping unnamed. */
    const STACK_H = 26;
    const STACK_PITCH = 32;
    const lb = g.labelBounds;
    const rightEdge = lb.x + lb.w;
    const bands: Array<{ top: number; bottom: number }> = [
      { top: g.plot.y1 - 164, bottom: g.plot.y1 - STACK_H },
      { top: lb.y, bottom: g.plot.y1 - 164 - STACK_PITCH },
    ];
    for (const p of unplaced) {
      const w =
        26 + estimateLabelWidth(p.d.label) + 10 +
        estimateLabelWidth(entryValues(p.d));
      let slot: Rect | null = null;
      outer: for (const band of bands) {
        for (let y = band.top; y <= band.bottom; y += STACK_PITCH) {
          for (let x = lb.x + 16; x + w <= rightEdge; x += 8) {
            const r: Rect = { x, y, w, h: STACK_H };
            if (!hits(r)) {
              slot = r;
              break outer;
            }
          }
        }
      }
      if (!slot) {
        throw new Error(
          `scatter: no label seat for ${p.d.runId} (${p.d.label}) in either stack band; every point must be named`,
        );
      }
      taken.push(slot);
      stack.push({ runId: p.d.runId, x: slot.x, y: slot.y });
    }
  }
  return { placed, stack };
}

function solvePhone(
  points: Pt[],
  railData: ScatterDatum[],
): Solution & { stackRows: number } {
  const g = PHONE;
  const furniture: Rect[] = [
    PHONE_ANNOT_CAPTION,
    PHONE_ANNOT_TR,
    PHONE_ANNOT_BL,
    ...ASR_TICKS.map((t) => ({
      x: g.plot.x0 + 2,
      y: g.plot.y0 + (1 - t / ASR_AXIS_MAX) * (g.plot.y1 - g.plot.y0) - 17,
      w: 26,
      h: 13,
    })),
  ];
  /* Only plotted points stand in the phone plot (buildPoints
   * returns no rail markers at this geometry), and labels
   * render at the wide chart's size, so the solver plans at
   * full width scale. The rail points and any plotted point
   * the solver cannot seat go to the list under the plot,
   * each entry carrying its own disc beside its name. */
  const layoutPts: LayoutPoint[] = points.map((p) => ({
    runId: p.d.runId,
    x: p.x,
    y: p.y,
    marker: 11,
    label: p.d.label,
  }));
  const first = placeLabels(layoutPts, furniture, g.labelBounds, 1);
  const byId = new Map<string, ScatterDatum>([
    ...points.map((p) => [p.d.runId, p.d] as const),
    ...railData.map((d) => [d.runId, d] as const),
  ]);
  const listed = [...railData.map((d) => d.runId), ...first.keyed]
    .map((id) => byId.get(id)!)
    .sort((a, b) => b.asr - a.asr);
  const stack: StackEntry[] = listed.map((d, i) => ({
    runId: d.runId,
    x: PHONE_ENTRY_X,
    y: PHONE_LIST_TOP + i * PHONE_ENTRY_PITCH,
  }));
  return { placed: first.placed, stack, stackRows: listed.length };
}

function Labels({
  placed,
  dataById,
  activeId,
  phone,
}: {
  placed: PlacedLabel[];
  dataById: Map<string, ScatterDatum>;
  activeId: string | null;
  phone?: boolean;
}) {
  return (
    <>
      {placed.map((l) => {
        const d = dataById.get(l.runId)!;
        return (
          <text
            key={l.runId}
            x={r2(l.x)}
            y={r2(l.y + 11)}
            className={`scatter-label${phone ? " phone" : ""}`}
            data-label-for={l.runId}
            data-active={activeId === l.runId ? "true" : undefined}
          >
            {d.label}
          </text>
        );
      })}
    </>
  );
}

/**
 * Overflow rows: the point's disc at a reduced scale, its
 * name, and its figures. The disc carries the association;
 * nothing is drawn between the row and the point. On the
 * wide chart the figures follow the name on the same line;
 * on the phone they sit under the name. A row is itself a
 * target: tapping or clicking it pins the point's card,
 * anchored at the row's disc, and on the phone a rail
 * point's row is its only marker, so there the row also
 * carries the keyboard stop and the accessible name.
 */
function StackEntries({
  stack,
  dataById,
  activeId,
  phone,
  onActivate,
  onDeactivate,
  onToggle,
}: {
  stack: StackEntry[];
  dataById: Map<string, ScatterDatum>;
  activeId: string | null;
  phone?: boolean;
  onActivate: (id: string) => void;
  onDeactivate: () => void;
  onToggle: (id: string) => void;
}) {
  return (
    <>
      {stack.map((s) => {
        const d = dataById.get(s.runId)!;
        const nameW = estimateLabelWidth(d.label);
        const focusable = phone && d.rail;
        return (
          <g
            key={s.runId}
            className="scatter-entry"
            data-entry-for={s.runId}
            {...(focusable
              ? {
                  tabIndex: 0,
                  role: "group",
                  "aria-label": pointAccessibleName(d),
                }
              : {})}
            onMouseEnter={() => onActivate(s.runId)}
            onMouseLeave={onDeactivate}
            onFocus={focusable ? () => onActivate(s.runId) : undefined}
            onBlur={focusable ? onDeactivate : undefined}
            onClick={(e) => {
              e.stopPropagation();
              onToggle(s.runId);
            }}
            onKeyDown={
              focusable
                ? (e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      onToggle(s.runId);
                    }
                  }
                : undefined
            }
          >
            <rect
              className="entry-hit"
              x={r2(s.x - 4)}
              y={r2(s.y - 2)}
              width={
                phone
                  ? 324
                  : 26 + nameW + 10 + estimateLabelWidth(entryValues(d)) + 8
              }
              height={phone ? 36 : 30}
              aria-hidden="true"
            />
            <g
              transform={`translate(${r2(s.x + 10)} ${r2(s.y + 13)}) scale(${phone ? 0.72 : 0.85})`}
              aria-hidden="true"
            >
              <MarkerGlyph d={d} />
            </g>
            <text
              x={r2(s.x + (phone ? 24 : 26))}
              y={r2(s.y + (phone ? 13 : 17))}
              className={`scatter-label${phone ? " phone" : ""}`}
              data-label-for={s.runId}
              data-active={activeId === s.runId ? "true" : undefined}
            >
              {d.label}
            </text>
            <text
              x={r2(phone ? s.x + 24 : s.x + 26 + nameW + 10)}
              y={r2(phone ? s.y + 27 : s.y + 17)}
              className={`scatter-entry-values${phone ? " phone" : ""} num`}
              aria-hidden="true"
            >
              {entryValues(d)}
            </text>
          </g>
        );
      })}
    </>
  );
}

function HoverCard({
  p,
  g,
  phone,
  pinned,
  onClose,
}: {
  p: Pt;
  g: Geom;
  phone?: boolean;
  pinned: boolean;
  onClose: () => void;
}) {
  const d = p.d;
  const rawLeftPct = (p.x / g.w) * 100;
  /* On the phone the well is nearly viewport-wide, so a card
   * centred on an edge point would bleed out of the panel;
   * the anchor clamps into the middle band and the align
   * classes do the rest. The association survives the clamp:
   * the point itself stays enlarged and bold beneath. */
  const leftPct = phone
    ? Math.min(64, Math.max(36, rawLeftPct))
    : rawLeftPct;
  const topPct = (p.y / g.h) * 100;
  const cls = leftPct > 74 ? " align-r" : leftPct < 20 ? " align-l" : "";
  /* The card stands below the point through the whole top
   * band; on the phone's taller plot the band is deeper, so
   * a card opening upward there would leave the panel. */
  const below = p.y < g.plot.y0 + (phone ? 178 : 92);
  return (
    <div
      className={`scatter-card${cls}${below ? " below" : ""}${pinned ? " pinned" : ""}`}
      style={{ left: `${leftPct}%`, top: `${topPct}%` }}
      aria-hidden={pinned ? undefined : true}
      onClick={pinned ? (e) => e.stopPropagation() : undefined}
    >
      <p className="sc-name">{d.label}</p>
      {pinned && (
        <button
          type="button"
          className="sc-close"
          aria-label={`Close details for ${d.label}`}
          onClick={onClose}
        >
          ×
        </button>
      )}
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
  /* Geometry and label placement are pure in the props:
   * memoize them so hover and focus state changes re-render
   * without re-running the point builder or the solver. */
  const { points, solution } = useMemo(() => {
    const pts = buildPoints(plotted, rail, domain, g);
    return {
      points: pts,
      solution: phone ? solvePhone(pts, rail) : solveWide(pts),
    };
  }, [plotted, rail, domain, g, phone]);
  const dataById = useMemo(
    () =>
      new Map<string, ScatterDatum>(
        [...plotted, ...rail].map((d) => [d.runId, d]),
      ),
    [plotted, rail],
  );
  const height = phone
    ? PHONE_LIST_TOP +
      (solution as { stackRows?: number }).stackRows! * PHONE_ENTRY_PITCH +
      28
    : WIDE.h;
  /* The card's state machine. Hover and focus preview;
   * a click or tap pins. The pinned card is the touch
   * user's card: it stays until the same point is tapped
   * again, a tap lands anywhere else in the chart, the
   * close control is used, or Escape is pressed, because
   * touch has no pointer-leave to dismiss by. */
  const [hoverId, setHoverId] = useState<string | null>(null);
  const [pinnedId, setPinnedId] = useState<string | null>(null);
  const activeId = pinnedId ?? hoverId;
  const togglePin = (id: string) => {
    if (pinnedId === id) {
      setPinnedId(null);
      setHoverId(null);
    } else {
      setPinnedId(id);
      setHoverId(id);
    }
  };
  const dismiss = () => {
    setPinnedId(null);
    setHoverId(null);
  };
  const svgRef = useRef<SVGSVGElement | null>(null);
  /* A tap or click anywhere in the chart resolves to the
   * nearest point inside the touch radius and toggles its
   * pin; landing outside every point dismisses. Resolving
   * by distance, not by which element painted on top, is
   * what makes the packed cluster honest under a fingertip.
   * Taps on the well's own padding land outside the SVG and
   * reach the wrap's handler, which dismisses the same way. */
  const handleChartClick = (e: MouseEvent) => {
    const svg = svgRef.current;
    if (!svg) return;
    const ctm = svg.getScreenCTM();
    if (!ctm) return;
    const pt = new DOMPoint(e.clientX, e.clientY).matrixTransform(
      ctm.inverse(),
    );
    let best: Pt | null = null;
    let bestD = 24;
    for (const p of points) {
      const dist = Math.hypot(p.x - pt.x, p.y - pt.y);
      if (dist < bestD) {
        bestD = dist;
        best = p;
      }
    }
    if (best) togglePin(best.d.runId);
    else dismiss();
  };
  /* The active point's card anchor: its marker position, or
   * for a list entry the position of the entry's own disc. */
  const active: Pt | null = (() => {
    if (!activeId) return null;
    const mp = points.find((p) => p.d.runId === activeId);
    if (mp) return mp;
    const entry = solution.stack.find((s) => s.runId === activeId);
    const d = dataById.get(activeId);
    if (entry && d) {
      return { d, x: entry.x + 10, y: entry.y + 13, nudged: false };
    }
    return null;
  })();
  return (
    <div
      className="scatter-wrap"
      onKeyDown={(e) => {
        if (e.key === "Escape") dismiss();
      }}
      onClick={(e) => {
        if (!(e.target as HTMLElement).closest("svg, .scatter-card")) {
          dismiss();
        }
      }}
    >
      <svg
        ref={svgRef}
        onClick={handleChartClick}
        viewBox={`0 0 ${g.w} ${height}`}
        className="scatter-svg"
        role="group"
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
            <text x={324} y={22} textAnchor="end" className="corner-title phone">
              {CORNER_TR.title}
            </text>
            <text x={324} y={38} textAnchor="end" className="corner-sub phone">
              {CORNER_TR.sub}
            </text>
          </g>
        ) : (
          <>
            <g className="corner-note">
              <text x={838} y={66} textAnchor="end" className="corner-title">
                {CORNER_TR.title}
              </text>
              <text x={838} y={90} textAnchor="end" className="corner-sub">
                {CORNER_TR.sub}
              </text>
            </g>
            <g className="corner-note">
              <text x={304} y={500} className="corner-title">
                {CORNER_BL.title}
              </text>
              <text x={304} y={524} className="corner-sub">
                {CORNER_BL.sub}
              </text>
            </g>
          </>
        )}
        {points.map((p) => (
          <Marker
            key={p.d.runId}
            p={p}
            active={activeId === p.d.runId}
            onActivate={setHoverId}
            onDeactivate={() => setHoverId(null)}
            onToggle={togglePin}
          />
        ))}
        <Labels
          placed={solution.placed}
          dataById={dataById}
          activeId={activeId}
          phone={phone}
        />
        <StackEntries
          stack={solution.stack}
          dataById={dataById}
          activeId={activeId}
          phone={phone}
          onActivate={setHoverId}
          onDeactivate={() => setHoverId(null)}
          onToggle={togglePin}
        />
        <text x={g.plot.x0} y={g.plot.y1 + 40} className="axis-caption">
          {phone
            ? "Cost per run, dollars, log scale"
            : "Recorded cost per run, US dollars, log scale"}
        </text>
        {phone && (
          <g className="corner-note">
            <text x={8} y={520} className="corner-title phone">
              {CORNER_BL.title}
            </text>
            <text x={8} y={538} className="corner-sub phone">
              {CORNER_BL.sub}
            </text>
          </g>
        )}
      </svg>
      {active && (
        <HoverCard
          p={active}
          g={{ ...g, h: height }}
          phone={phone}
          pinned={pinnedId !== null && pinnedId === activeId}
          onClose={dismiss}
        />
      )}
    </div>
  );
}
