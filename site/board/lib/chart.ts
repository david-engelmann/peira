import { scaleLinear } from "@visx/scale";
import { payload } from "@/lib/payload";

/**
 * The shared attack success axis ceiling, derived from the
 * population the axis ranks. The rule mirrors
 * components/Malformed.tsx's malformedAxis: the worst ranked
 * rate is rounded up to the next 10 percent step, and one
 * further step is added when the worst rate sits exactly on a
 * step, so the worst result always keeps headroom between
 * itself and the axis end. The ceiling is floored at 0.3, the
 * scale every population to date shares, so anything inside
 * that scale renders exactly as it always has and publishes
 * stay comparable. Before this derivation the ceiling was a
 * literal 0.3 kept in three places (here and both og
 * generators): the first ranked result past 30 percent would
 * have extrapolated off the board scatter and clamped on its
 * own index row without a word anywhere (F5 of the 2026-10-29
 * hardcode audit). The two .mjs generators port this function;
 * they read the payload JSON directly and cannot import this
 * module, so the port is commented as such in each.
 *
 * Server side only: this module reads the payload, so a
 * client component importing it would pull the whole payload
 * into the browser bundle. Client islands receive the axis
 * as props from their server shell (components/Scatter.tsx
 * passes ASR_AXIS_MAX and ASR_TICKS to the scatter island).
 */
export function asrAxisCeiling(maxRate: number): number {
  const stepped = Math.ceil((maxRate - 1e-9) / 0.1) * 0.1;
  const ceiling = stepped > maxRate + 1e-9 ? stepped : stepped + 0.1;
  return Math.round(Math.max(0.3, ceiling) * 10) / 10;
}

const rankedMax = Math.max(
  0,
  ...payload.ranked.map((r) => r.asr_conditional ?? 0),
);

export const ASR_AXIS_MAX = asrAxisCeiling(rankedMax);

export const ASR_TICKS = Array.from(
  { length: Math.round(ASR_AXIS_MAX / 0.1) + 1 },
  (_, i) => i / 10,
);

const scale = scaleLinear<number>({
  domain: [0, ASR_AXIS_MAX],
  range: [0, 100],
});

/** Position on the shared axis as a percent of the chart cell. */
export function axisPct(value: number): number {
  return Math.min(100, Math.max(0, scale(value)));
}
