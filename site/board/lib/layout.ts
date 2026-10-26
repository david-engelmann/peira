/**
 * Pure label and point layout for the scatter (redesign).
 * Split out of lib/charts so the client island can import the
 * solvers without pulling the payload module into the browser
 * bundle. Deterministic, no data access: callers pass points
 * and furniture in, placements come out.
 */

/* ---------------- label layout ---------------- */

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

function rectOverlap(a: Rect, b: Rect): number {
  const ox = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x);
  const oy = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
  return ox > 0 && oy > 0 ? ox * oy : 0;
}

/**
 * Estimated rendered width of a chart label in Archivo at the
 * chart's label size. Deliberately generous (a few percent over
 * the face's average advance, plus padding), because the solver
 * plans with these boxes and the DOM audit then verifies the
 * real ones. An underestimate would plan a collision the audit
 * has to catch; an overestimate only costs a little air.
 */
export function estimateLabelWidth(text: string): number {
  let w = 0;
  for (const ch of text) {
    if ("ilj.,'-/ ".includes(ch)) w += 3.6;
    else if ("mwMW".includes(ch)) w += 9.6;
    else if (ch >= "A" && ch <= "Z") w += 7.4;
    else if (ch >= "0" && ch <= "9") w += 6.6;
    else if ("()".includes(ch)) w += 4.2;
    else w += 6.3;
  }
  return w * 1.05 + 8;
}

export interface LayoutPoint {
  runId: string;
  x: number;
  y: number;
  /** Marker obstacle half-size (disc or badge). */
  marker: number;
  label: string | null;
}

export interface PlacedLabel extends Rect {
  runId: string;
  leader: boolean;
}

const LABEL_H = 15;
const GAP = 9;

function candidates(p: LayoutPoint, w: number, plotRight: number): Rect[] {
  const cx = p.x;
  const cy = p.y;
  const mk = (x: number, y: number): Rect => ({ x, y, w, h: LABEL_H });
  const east = [
    mk(cx + p.marker + GAP, cy - LABEL_H / 2),
    mk(cx + p.marker + GAP - 2, cy - LABEL_H - GAP + 2),
    mk(cx + p.marker + GAP - 2, cy + GAP - 2),
    mk(cx - w / 2, cy - p.marker - GAP - LABEL_H),
    mk(cx - w / 2, cy + p.marker + GAP),
    mk(cx - p.marker - GAP - w, cy - LABEL_H / 2),
    mk(cx - p.marker - GAP - w + 2, cy - LABEL_H - GAP + 2),
    mk(cx - p.marker - GAP - w + 2, cy + GAP - 2),
  ];
  const west = [...east.slice(5), ...east.slice(0, 5)];
  return cx > plotRight * 0.72 ? west : east;
}

function gapBetween(rect: Rect, p: LayoutPoint): number {
  const dx = Math.max(
    rect.x - (p.x + p.marker),
    p.x - p.marker - (rect.x + rect.w),
    0,
  );
  const dy = Math.max(
    rect.y - (p.y + p.marker),
    p.y - p.marker - (rect.y + rect.h),
    0,
  );
  return Math.hypot(dx, dy);
}

/**
 * Deterministic label placement. Every label starts at its
 * cheapest candidate against points and furniture, then passes
 * move labels to cheaper candidates while any overlap remains.
 * Labels that still overlap are returned in `keyed` so the
 * caller can replace them with index badges and a keyed list,
 * per the design spec's cluster rule. Runs identically at
 * build time on every build.
 */
export function placeLabels(
  points: LayoutPoint[],
  furniture: Rect[],
  bounds: Rect,
  widthScale = 1,
): { placed: PlacedLabel[]; keyed: string[] } {
  const labelled = points.filter((p) => p.label !== null);
  const byId = new Map(labelled.map((p) => [p.runId, p]));
  const pointRects = new Map<string, Rect>();
  for (const p of points) {
    pointRects.set(p.runId, {
      x: p.x - p.marker,
      y: p.y - p.marker,
      w: p.marker * 2,
      h: p.marker * 2,
    });
  }
  const chosen = new Map<string, Rect>();
  const costOf = (self: string, rect: Rect, candIndex: number): number => {
    let cost = candIndex * 3;
    for (const f of furniture) cost += rectOverlap(rect, f) * 40;
    for (const [id, pr] of pointRects) {
      if (id !== self) cost += rectOverlap(rect, pr) * 40;
    }
    for (const [id, other] of chosen) {
      if (id !== self) cost += rectOverlap(rect, other) * 40;
    }
    if (
      rect.x < bounds.x ||
      rect.y < bounds.y ||
      rect.x + rect.w > bounds.x + bounds.w ||
      rect.y + rect.h > bounds.y + bounds.h
    ) {
      cost += 100000;
    }
    cost += gapBetween(rect, byId.get(self)!) * 0.4;
    return cost;
  };
  for (const p of labelled) {
    const w = estimateLabelWidth(p.label!) * widthScale;
    const cands = candidates(p, w, bounds.x + bounds.w);
    let best = cands[0];
    let bestCost = Infinity;
    cands.forEach((c, i) => {
      const cost = costOf(p.runId, c, i);
      if (cost < bestCost) {
        bestCost = cost;
        best = c;
      }
    });
    chosen.set(p.runId, best);
  }
  for (let pass = 0; pass < 400; pass++) {
    let moved = false;
    for (const p of labelled) {
      const w = estimateLabelWidth(p.label!) * widthScale;
      const cands = candidates(p, w, bounds.x + bounds.w);
      const current = chosen.get(p.runId)!;
      const currentIdx = cands.findIndex(
        (c) => c.x === current.x && c.y === current.y,
      );
      let bestCost = costOf(p.runId, current, Math.max(0, currentIdx));
      let best = current;
      cands.forEach((c, i) => {
        const cost = costOf(p.runId, c, i);
        if (cost < bestCost - 0.5) {
          bestCost = cost;
          best = c;
        }
      });
      if (best !== current) {
        chosen.set(p.runId, best);
        moved = true;
      }
    }
    if (!moved) break;
  }
  const keyed: string[] = [];
  const placed: PlacedLabel[] = [];
  for (const p of labelled) {
    const rect = chosen.get(p.runId)!;
    let bad = false;
    for (const f of furniture) if (rectOverlap(rect, f) > 0.5) bad = true;
    for (const [id, pr] of pointRects) {
      if (id !== p.runId && rectOverlap(rect, pr) > 0.5) bad = true;
    }
    for (const [id, other] of chosen) {
      if (id !== p.runId && rectOverlap(rect, other) > 0.5) bad = true;
    }
    if (
      rect.x < bounds.x - 0.5 ||
      rect.y < bounds.y - 0.5 ||
      rect.x + rect.w > bounds.x + bounds.w + 0.5 ||
      rect.y + rect.h > bounds.y + bounds.h + 0.5
    ) {
      bad = true;
    }
    if (bad) {
      keyed.push(p.runId);
    } else {
      placed.push({ ...rect, runId: p.runId, leader: gapBetween(rect, p) > 12 });
    }
  }
  return { placed, keyed };
}

/**
 * Separate near-coincident points along y, the design spec's
 * edge rule for points that share a cost and a rate, moving no
 * point by more than one marker width. Points are grouped
 * into clusters of true two axis neighbours; each cluster is
 * then spread by alternating forward and backward passes that
 * hold minSep between neighbours while respecting the shift
 * cap, which settles chains of three or more that pairwise
 * pushes collapse onto one another. Works on the given objects
 * and returns the run ids that moved.
 */
export function nudgePoints<
  T extends { runId: string; x: number; y: number },
>(points: T[], minSep: number, maxShift: number): Set<string> {
  const moved = new Set<string>();
  const orig = new Map(points.map((p) => [p.runId, { x: p.x, y: p.y }]));
  /* Two cycles. A spread cluster can push a point toward a
   * neighbour that was just too far away to join the cluster
   * at true positions, so the clustering runs again on the
   * spread positions and spreads once more. Shift caps always
   * measure from the true positions. */
  for (let cycle = 0; cycle < 2; cycle++) {
    /* Union find over current positions: two points belong to
     * one cluster when they are close on both axes, whether or
     * not a third point's y falls between them. */
    const parent = points.map((_, i) => i);
    const find = (i: number): number =>
      parent[i] === i ? i : (parent[i] = find(parent[i]));
    for (let i = 0; i < points.length; i++) {
      for (let j = i + 1; j < points.length; j++) {
        if (
          Math.abs(points[i].x - points[j].x) < minSep &&
          Math.abs(points[i].y - points[j].y) < minSep
        ) {
          parent[find(i)] = find(j);
        }
      }
    }
    const groups = new Map<number, T[]>();
    points.forEach((p, i) => {
      const root = find(i);
      const group = groups.get(root) ?? [];
      group.push(p);
      groups.set(root, group);
    });
    for (const group of groups.values()) {
      if (group.length < 2) continue;
      const cluster = [...group].sort((a, b) => a.y - b.y || a.x - b.x);
      const ys = cluster.map((p) => orig.get(p.runId)!.y);
      for (let round = 0; round < 3; round++) {
        for (let i = 1; i < cluster.length; i++) {
          const want = cluster[i - 1].y + minSep;
          cluster[i].y = Math.min(
            Math.max(cluster[i].y, want),
            ys[i] + maxShift,
          );
        }
        for (let i = cluster.length - 2; i >= 0; i--) {
          const want = cluster[i + 1].y - minSep;
          cluster[i].y = Math.max(
            Math.min(cluster[i].y, want),
            ys[i] - maxShift,
          );
        }
      }
    }
  }
  for (const p of points) {
    if (Math.abs(p.y - orig.get(p.runId)!.y) > 0.01) moved.add(p.runId);
  }
  return moved;
}

