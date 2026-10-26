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
}

const LABEL_H = 15;
const GAP = 9;
/* Second candidate ring, one disc further out. A label only
 * reaches it when every near candidate collides, and the
 * association guard in placeLabels then applies: a far label
 * must sit closer to its own point than to any other, so it
 * can never read as a neighbour's name. */
const GAP_FAR = 26;
/* Edge gap beyond which a candidate counts as far. Near
 * candidates sit at most GAP from their point's marker box. */
const FAR_GAP = 12;

function candidates(p: LayoutPoint, w: number, plotRight: number): Rect[] {
  const cx = p.x;
  const cy = p.y;
  const mk = (x: number, y: number): Rect => ({ x, y, w, h: LABEL_H });
  const near = [
    mk(cx + p.marker + GAP, cy - LABEL_H / 2),
    mk(cx + p.marker + GAP - 2, cy - LABEL_H - GAP + 2),
    mk(cx + p.marker + GAP - 2, cy + GAP - 2),
    mk(cx - w / 2, cy - p.marker - GAP - LABEL_H),
    mk(cx - w / 2, cy + p.marker + GAP),
    mk(cx - p.marker - GAP - w, cy - LABEL_H / 2),
    mk(cx - p.marker - GAP - w + 2, cy - LABEL_H - GAP + 2),
    mk(cx - p.marker - GAP - w + 2, cy + GAP - 2),
  ];
  const g = GAP_FAR;
  const far = [
    mk(cx + p.marker + g, cy - LABEL_H / 2),
    mk(cx + p.marker + g, cy - LABEL_H - g),
    mk(cx + p.marker + g, cy + g),
    mk(cx - w / 2, cy - p.marker - g - LABEL_H),
    mk(cx - w / 2, cy + p.marker + g),
    mk(cx - p.marker - g - w, cy - LABEL_H / 2),
    mk(cx - p.marker - g - w, cy - LABEL_H - g),
    mk(cx - p.marker - g - w, cy + g),
  ];
  const east = [...near, ...far];
  const west = [
    ...near.slice(5),
    ...near.slice(3, 5),
    ...near.slice(0, 3),
    ...far.slice(5),
    ...far.slice(3, 5),
    ...far.slice(0, 3),
  ];
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
 * Candidates come in two rings, near and far; a far candidate
 * is valid only while the label stays closer to its own point
 * than to any other. Labels the joint solve leaves overlapped
 * get a retry against the seated set, including displacing a
 * single seated label to another clean candidate. Labels that
 * still overlap are returned in `keyed` so the
 * caller can place them in its overflow stack beside their
 * point's disc glyph. There are no index badges, no keyed
 * lists, and no leader lines anywhere in the design: a label
 * is either adjacent to its point or in the stack, and the
 * stack entry carries the point's own disc so the association
 * needs no drawn line. Runs identically at build time on
 * every build.
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
  /* A far label must stay closer to its own point than to
   * any other point, or it would read as the neighbour's
   * name. Purely geometric, so it holds in every pass. */
  const associationOk = (self: string, rect: Rect, ownGap: number): boolean => {
    for (const q of points) {
      if (q.runId === self) continue;
      if (gapBetween(rect, q) < ownGap) return false;
    }
    return true;
  };
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
    const gap = gapBetween(rect, byId.get(self)!);
    cost += gap * 0.4;
    if (gap > FAR_GAP && !associationOk(self, rect, gap)) cost += 100000;
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
      placed.push({ ...rect, runId: p.runId });
    }
  }
  /* Retry pass for the labels the joint solve could not
   * seat. A keyed label's own tentative rect no longer blocks
   * the field, so first each keyed label retries against the
   * seated set alone, highest on the chart first. If a
   * candidate is blocked by exactly one seated label, that
   * label is displaced to another clean candidate of its own
   * and the keyed label takes the freed spot. Far candidates
   * must pass the association guard in both moves. Whatever
   * still cannot seat stays keyed for the caller's stack. */
  const seated = new Map<string, Rect>(
    placed.map((l) => [l.runId, { x: l.x, y: l.y, w: l.w, h: l.h }]),
  );
  const inBounds = (rect: Rect): boolean =>
    rect.x >= bounds.x - 0.5 &&
    rect.y >= bounds.y - 0.5 &&
    rect.x + rect.w <= bounds.x + bounds.w + 0.5 &&
    rect.y + rect.h <= bounds.y + bounds.h + 0.5;
  const usable = (p: LayoutPoint, rect: Rect): boolean => {
    const gap = gapBetween(rect, p);
    return gap <= FAR_GAP || associationOk(p.runId, rect, gap);
  };
  const cleanAgainst = (
    p: LayoutPoint,
    rect: Rect,
    others: Map<string, Rect>,
    skipId?: string,
  ): boolean => {
    for (const f of furniture) if (rectOverlap(rect, f) > 0.5) return false;
    for (const [id, pr] of pointRects) {
      if (id !== p.runId && rectOverlap(rect, pr) > 0.5) return false;
    }
    for (const [id, other] of others) {
      if (id !== skipId && rectOverlap(rect, other) > 0.5) return false;
    }
    return inBounds(rect);
  };
  const retryOrder = [...keyed].sort(
    (a, b) => byId.get(a)!.y - byId.get(b)!.y,
  );
  const stillKeyed: string[] = [];
  for (const id of retryOrder) {
    const p = byId.get(id)!;
    const w = estimateLabelWidth(p.label!) * widthScale;
    const cands = candidates(p, w, bounds.x + bounds.w);
    let seat: Rect | null = null;
    for (const c of cands) {
      if (usable(p, c) && cleanAgainst(p, c, seated)) {
        seat = c;
        break;
      }
    }
    if (!seat) {
      outer: for (const c of cands) {
        if (!usable(p, c) || !inBounds(c)) continue;
        let blockedBy: string | null = null;
        let dead = false;
        for (const f of furniture) {
          if (rectOverlap(c, f) > 0.5) {
            dead = true;
            break;
          }
        }
        if (dead) continue;
        for (const [pid, pr] of pointRects) {
          if (pid !== id && rectOverlap(c, pr) > 0.5) {
            dead = true;
            break;
          }
        }
        if (dead) continue;
        for (const [oid, other] of seated) {
          if (rectOverlap(c, other) > 0.5) {
            if (blockedBy !== null) {
              dead = true;
              break;
            }
            blockedBy = oid;
          }
        }
        if (dead || blockedBy === null) continue;
        const q = byId.get(blockedBy)!;
        const qw = estimateLabelWidth(q.label!) * widthScale;
        for (const qc of candidates(q, qw, bounds.x + bounds.w)) {
          if (!usable(q, qc)) continue;
          if (rectOverlap(qc, c) > 0.5) continue;
          if (cleanAgainst(q, qc, seated, blockedBy)) {
            seated.set(blockedBy, qc);
            seat = c;
            break outer;
          }
        }
      }
    }
    if (seat) {
      seated.set(id, seat);
    } else {
      stillKeyed.push(id);
    }
  }
  const finalPlaced: PlacedLabel[] = [];
  for (const p of labelled) {
    const rect = seated.get(p.runId);
    if (rect) finalPlaced.push({ ...rect, runId: p.runId });
  }
  return { placed: finalPlaced, keyed: stillKeyed };
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

