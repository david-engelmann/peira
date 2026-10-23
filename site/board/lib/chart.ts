import { scaleLinear } from "@visx/scale";

/**
 * The ranking axis. A fixed 0 to 30 percent scale, shared by the
 * ranking and the cost scatter, kept from the previous board as
 * a standing decision so publishes stay comparable.
 */
export const ASR_AXIS_MAX = 0.3;
export const ASR_TICKS = [0, 0.1, 0.2, 0.3];

const scale = scaleLinear<number>({
  domain: [0, ASR_AXIS_MAX],
  range: [0, 100],
});

/** Position on the shared axis as a percent of the chart cell. */
export function axisPct(value: number): number {
  return Math.min(100, Math.max(0, scale(value)));
}
