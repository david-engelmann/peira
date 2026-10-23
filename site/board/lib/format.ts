/**
 * Display formatting for payload numbers.
 *
 * Formatting only, but the exact formatting matters. The board
 * has always printed percentages as the payload value's decimal
 * string scaled by 100 and rounded half up at one decimal (the
 * previous renderer's _pct). Naive binary float formatting
 * breaks that contract on boundary values: the stored 0.0055
 * prints as 0.6 percent on the published board, while the float
 * product 0.5499999999999999 formats to 0.5. Every formatter
 * here therefore works on the value's decimal string, never on
 * a float product, so the printed figure is the published one.
 */

/** Expand a JS number string, including exponent forms. */
function expandDecimalString(value: number): string {
  const s = String(value);
  if (!/[eE]/.test(s)) return s;
  const [mantissa, expStr] = s.split(/[eE]/);
  const exp = parseInt(expStr, 10);
  const negative = mantissa.startsWith("-");
  const body = negative ? mantissa.slice(1) : mantissa;
  const [intPart, fracPart = ""] = body.split(".");
  const digits = intPart + fracPart;
  const point = intPart.length + exp;
  let out: string;
  if (point <= 0) {
    out = "0." + "0".repeat(-point) + digits;
  } else if (point >= digits.length) {
    out = digits + "0".repeat(point - digits.length);
  } else {
    out = digits.slice(0, point) + "." + digits.slice(point);
  }
  return (negative ? "-" : "") + out;
}

/** Shift the decimal point of a plain decimal string by places. */
function shiftPoint(decStr: string, places: number): string {
  const negative = decStr.startsWith("-");
  const body = negative ? decStr.slice(1) : decStr;
  const [intPart, fracPart = ""] = body.split(".");
  let digits = intPart + fracPart;
  let point = intPart.length + places;
  // Leading zeros are not significant; dropping them moves the
  // point with them. Without this, 0.0055 shifted by two places
  // comes out as 000.55 instead of 0.55.
  let lead = 0;
  while (lead < digits.length - 1 && digits[lead] === "0") lead += 1;
  digits = digits.slice(lead);
  point -= lead;
  let out: string;
  if (point <= 0) {
    out = "0." + "0".repeat(-point) + digits;
  } else if (point >= digits.length) {
    out = digits + "0".repeat(point - digits.length);
  } else {
    out = digits.slice(0, point) + "." + digits.slice(point);
  }
  return (negative ? "-" : "") + out;
}

/**
 * Round a plain decimal string half up at the given number of
 * decimals, returning a string with exactly that many decimals.
 * Half up on the decimal string: the first dropped digit at or
 * above 5 rounds up, which covers the exact-half case too.
 */
export function quantizeHalfUp(decStr: string, decimals: number): string {
  const negative = decStr.startsWith("-");
  const body = negative ? decStr.slice(1) : decStr;
  const [rawInt, fracPart = ""] = body.split(".");
  const intPart = rawInt.replace(/^0+(?=\d)/, "");
  const kept = fracPart.slice(0, decimals).padEnd(decimals, "0");
  const dropped = fracPart.slice(decimals);
  const digits = (intPart + kept).split("").map(Number);
  if (dropped.length > 0 && dropped[0] >= "5") {
    let i = digits.length - 1;
    while (i >= 0 && digits[i] === 9) {
      digits[i] = 0;
      i -= 1;
    }
    if (i < 0) digits.unshift(1);
    else digits[i] += 1;
  }
  const joined = digits.join("");
  const intOut = joined.slice(0, joined.length - decimals) || "0";
  const fracOut = decimals > 0 ? joined.slice(joined.length - decimals) : "";
  return (
    (negative ? "-" : "") + intOut + (decimals > 0 ? `.${fracOut}` : "")
  );
}

/** A proportion as a percent at one decimal, as in 10.7%. */
export function fmtPct(value: number): string {
  return `${quantizeHalfUp(shiftPoint(expandDecimalString(value), 2), 1)}%`;
}

/** A proportion's percent figure without the sign, as in 10.7. */
export function fmtPctFigure(value: number): string {
  return quantizeHalfUp(shiftPoint(expandDecimalString(value), 2), 1);
}

export function fmtCi(ci: [number, number]): string {
  return `${fmtPct(ci[0])} to ${fmtPct(ci[1])}`;
}

/** Compact interval for tight contexts, as in 10.7% [9.8, 11.6]. */
export function fmtCiCompact(ci: [number, number]): string {
  return `[${fmtPctFigure(ci[0])}, ${fmtPctFigure(ci[1])}]`;
}

export function fmtInt(value: number): string {
  return value.toLocaleString("en-US");
}

/** ECE and Brier print at three decimals. */
/** Signed tax figure at three decimals, for example +0.055. */
export function fmtTax(value: number): string {
  const sign = value < 0 ? "-" : "+";
  return sign + quantizeHalfUp(expandDecimalString(Math.abs(value)), 3);
}

/** Whole milliseconds with no grouping, for example 4475ms. */
export function fmtMs(value: number): string {
  return `${quantizeHalfUp(expandDecimalString(value), 0)}ms`;
}

export function fmtEce(value: number): string {
  return quantizeHalfUp(expandDecimalString(value), 3);
}

export function fmtUsd(value: number): string {
  return `$${quantizeHalfUp(expandDecimalString(value), 2)}`;
}

/**
 * Cost with up to four decimals, trailing zeros trimmed but
 * never below two. Chart tooltips and the keyed list use it so
 * a $0.0582 run does not print as $0.06.
 */
export function fmtUsdExact(value: number): string {
  const q = quantizeHalfUp(expandDecimalString(value), 4);
  const [whole, fracRaw = ""] = q.split(".");
  let frac = fracRaw.replace(/0+$/, "");
  if (frac.length < 2) frac = frac.padEnd(2, "0");
  return `$${whole}.${frac}`;
}
