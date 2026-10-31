import { scaleLinear } from "@visx/scale";

/**
 * The ranking axis, shared by the ranking and the cost
 * scatter. The axis maximum is DERIVED from the ranked
 * population, never written into source: it is the worst
 * ranked rate rounded up to the next ten percent step, with
 * a floor of 0.3 so small populations keep the board's
 * standing frame. Deriving it means a ranked result can
 * never saturate its own bar in silence (hardcode audit F5):
 * when a tougher population lands, the axis grows a step
 * and every figure still sits at its true position.
 * Publishes stay comparable within a publish, because one
 * axis serves every chart on the page.
 *
 * Flagged results are not part of the derivation: they are
 * not ranked, their figures are stated in words with their
 * decomposition, and a flagged rate past the axis end says
 * so in its row rather than stretching the ranked frame.
 */
export interface AsrAxis {
  max: number;
  ticks: number[];
}

const AXIS_STEP = 0.1;
const AXIS_FLOOR = 0.3;

export function asrAxisFor(worstRanked: number): AsrAxis {
  const stepped =
    Math.ceil((worstRanked - 1e-9) / AXIS_STEP) * AXIS_STEP;
  const max = Math.max(AXIS_FLOOR, Math.round(stepped * 10) / 10);
  const ticks: number[] = [];
  for (let t = 0; t <= max + 1e-9; t += AXIS_STEP) {
    ticks.push(Math.round(t * 10) / 10);
  }
  return { max, ticks };
}

/* One scale per axis maximum, held at module level the way
 * the base code held its single scale. A render uses one
 * shared axis, so the slot turns over at most once per
 * population instead of once per call. */
let axisScaleMax: number | null = null;
let axisScale: ((value: number) => number) | null = null;

/** Position on the shared axis as a percent of the chart cell. */
export function axisPct(value: number, axisMax: number): number {
  if (axisScale === null || axisScaleMax !== axisMax) {
    axisScale = scaleLinear<number>({
      domain: [0, axisMax],
      range: [0, 100],
    });
    axisScaleMax = axisMax;
  }
  return Math.min(100, Math.max(0, axisScale(value)));
}
