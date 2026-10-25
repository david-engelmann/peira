"use client";

import { useEffect, useState } from "react";
import type { CompareData, CompareRow } from "@/lib/compare";
import {
  fmtPct,
  fmtPctCell,
  fmtEce,
  fmtUsd,
  fmtMs,
  fmtTax,
  fmtInt,
  fmtDeltaPct,
  fmtDelta3,
  fmtDeltaUsd,
  fmtDeltaMs,
} from "@/lib/format";

/**
 * Compare (design system section 4.6). Two pickers, a metric
 * table with a centre delta column, and paired family bars.
 * Deltas are A minus B computed at render time from the
 * unrounded values in the row set the server shaped from the
 * payload, printed at the precision of their metric. The
 * better side of a row carries a dot in ink-1 (the owner's
 * round 8 ruling confines green to the wordmark and claim).
 * The pair lives in the page address as #compare=a,b, so a
 * comparison is a shareable link, the behaviour the previous
 * board promised.
 */

type MetricKey =
  | "asr" | "benign" | "malformed"
  | "atkEce" | "atkBrier" | "benEce" | "benBrier"
  | "tax" | "cost" | "latP50" | "latP95";

interface MetricDef {
  key: MetricKey;
  label: string;
  better: "low" | "high";
  raw: (row: CompareRow) => number | null;
  format: (row: CompareRow) => string;
  delta: (d: number) => string;
}

const costFormat = (row: CompareRow): string => {
  if (row.cost === null) return "";
  return `${row.costLowerBound ? "≥ " : ""}${fmtUsd(row.cost)}`;
};

const METRICS: MetricDef[] = [
  { key: "asr", label: "Attack success", better: "low", raw: (r) => r.asr, format: (r) => (r.asr === null ? "" : fmtPct(r.asr)), delta: fmtDeltaPct },
  { key: "benign", label: "Benign accuracy", better: "high", raw: (r) => r.benign, format: (r) => (r.benign === null ? "" : fmtPct(r.benign)), delta: fmtDeltaPct },
  { key: "malformed", label: "Malformed rate", better: "low", raw: (r) => r.malformed, format: (r) => (r.malformed === null ? "" : fmtPct(r.malformed)), delta: fmtDeltaPct },
  { key: "atkEce", label: "Attacked ECE", better: "low", raw: (r) => r.atkEce, format: (r) => (r.atkEce === null ? "" : fmtEce(r.atkEce)), delta: fmtDelta3 },
  { key: "atkBrier", label: "Attacked Brier", better: "low", raw: (r) => r.atkBrier, format: (r) => (r.atkBrier === null ? "" : fmtEce(r.atkBrier)), delta: fmtDelta3 },
  { key: "benEce", label: "Benign ECE", better: "low", raw: (r) => r.benEce, format: (r) => (r.benEce === null ? "" : fmtEce(r.benEce)), delta: fmtDelta3 },
  { key: "benBrier", label: "Benign Brier", better: "low", raw: (r) => r.benBrier, format: (r) => (r.benBrier === null ? "" : fmtEce(r.benBrier)), delta: fmtDelta3 },
  { key: "tax", label: "Robustness tax", better: "low", raw: (r) => r.tax, format: (r) => (r.tax === null ? "" : fmtTax(r.tax)), delta: fmtDelta3 },
  { key: "cost", label: "Cost per run", better: "low", raw: (r) => r.cost, format: costFormat, delta: fmtDeltaUsd },
  { key: "latP50", label: "Latency p50 under attack", better: "low", raw: (r) => r.latP50, format: (r) => (r.latP50 === null ? "" : fmtMs(r.latP50)), delta: fmtDeltaMs },
  { key: "latP95", label: "Latency p95 under attack", better: "low", raw: (r) => r.latP95, format: (r) => (r.latP95 === null ? "" : fmtMs(r.latP95)), delta: fmtDeltaMs },
];

/** Whole percent, the shared cell rule (lib/format fmtPctCell). */
function fmtWholePct(value: number): string {
  return fmtPctCell(value);
}

const GROUPS: Array<{ key: CompareRow["group"]; label: string }> = [
  { key: "full", label: "Full suite" },
  { key: "flagged", label: "Flagged" },
  { key: "slice", label: "Guardrail slices" },
];

function Picker({
  side,
  value,
  rows,
  onChange,
}: {
  side: "a" | "b";
  value: string;
  rows: CompareRow[];
  onChange: (slug: string) => void;
}) {
  const id = `cmp-picker-${side}`;
  return (
    <div className="cmp-picker">
      <label htmlFor={id}>Model {side.toUpperCase()}</label>
      <select
        id={id}
        data-cmp-picker={side}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        {GROUPS.map((g) => (
          <optgroup key={g.key} label={g.label}>
            {rows
              .filter((r) => r.group === g.key)
              .map((r) => (
                <option key={r.slug} value={r.slug}>
                  {r.name}
                  {r.wire ? ` (${r.wire})` : ""}
                </option>
              ))}
          </optgroup>
        ))}
      </select>
    </div>
  );
}

export default function Compare({ data }: { data: CompareData }) {
  const bySlug = new Map(data.rows.map((r) => [r.slug, r]));
  const [aSlug, setASlug] = useState(data.defaultA);
  const [bSlug, setBSlug] = useState(data.defaultB);

  /* The pair is carried in the address. On load, a shared
   * link's pair wins over the default; on every change the
   * address follows without a reload or a scroll jump. */
  useEffect(() => {
    const m = window.location.hash.match(/^#compare=([^,]+),(.+)$/);
    if (m && bySlug.has(m[1]) && bySlug.has(m[2])) {
      setASlug(m[1]);
      setBSlug(m[2]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const setPair = (a: string, b: string) => {
    setASlug(a);
    setBSlug(b);
    window.history.replaceState(null, "", `#compare=${a},${b}`);
  };

  const a = bySlug.get(aSlug) ?? data.rows[0];
  const b = bySlug.get(bSlug) ?? data.rows[1];
  const same = a.slug === b.slug;
  const crossBase = !same && a.nCases !== b.nCases;

  return (
    <div className="cmp">
      <div className="cmp-pickers">
        <Picker side="a" value={aSlug} rows={data.rows} onChange={(s) => setPair(s, bSlug)} />
        <button type="button" className="cmp-swap" onClick={() => setPair(bSlug, aSlug)}>
          Swap A and B
        </button>
        <Picker side="b" value={bSlug} rows={data.rows} onChange={(s) => setPair(aSlug, s)} />
      </div>

      {same && (
        <p className="cmp-banner" data-cmp-banner="same">
          Both pickers name the same model, so there is nothing to
          compare. Pick a second model to see the differences.
        </p>
      )}
      {crossBase && (
        <p className="cmp-banner" data-cmp-banner="population">
          The two results ran different case bases (the full suite
          against the abstain subset), so their rates are not measured
          on the same base.
        </p>
      )}

      <table className="cmp-table">
        <thead>
          <tr>
            <th scope="col" className="cmp-th-metric">Metric</th>
            <th scope="col" className="cmp-th-model">
              {a.name}
              {a.wire && <span className="cmp-th-wire">{a.wire}</span>}
            </th>
            <th scope="col" className="cmp-th-delta">A minus B</th>
            <th scope="col" className="cmp-th-model">
              {b.name}
              {b.wire && <span className="cmp-th-wire">{b.wire}</span>}
            </th>
          </tr>
        </thead>
        <tbody>
          {METRICS.map((m) => {
            const av = m.raw(a);
            const bv = m.raw(b);
            const both = av !== null && bv !== null;
            const d = both ? av - bv : null;
            const win =
              !same && both && av !== bv
                ? m.better === "low"
                  ? av < bv
                    ? "a"
                    : "b"
                  : av > bv
                    ? "a"
                    : "b"
                : null;
            return (
              <tr key={m.key} data-cmp-row={m.key}>
                <th scope="row" className="cmp-metric">{m.label}</th>
                <td
                  className="cmp-val num"
                  data-cmp-value={m.key}
                  data-cmp-side="a"
                  data-cmp-raw={av === null ? "" : av}
                >
                  {win === "a" && (
                    <span className="win-dot" data-cmp-win="a" role="img" aria-label="stronger side" />
                  )}
                  {av === null ? <span className="not-measured">·</span> : m.format(a)}
                </td>
                <td
                  className="cmp-delta num"
                  data-cmp-delta={m.key}
                  data-cmp-raw={d === null ? "" : d}
                >
                  {same || d === null ? (
                    <span className="not-measured">·</span>
                  ) : (
                    m.delta(d)
                  )}
                </td>
                <td
                  className="cmp-val num"
                  data-cmp-value={m.key}
                  data-cmp-side="b"
                  data-cmp-raw={bv === null ? "" : bv}
                >
                  {win === "b" && (
                    <span className="win-dot" data-cmp-win="b" role="img" aria-label="stronger side" />
                  )}
                  {bv === null ? <span className="not-measured">·</span> : m.format(b)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <div className="cmp-families">
        {data.familyNames.map((fname, i) => (
          <div className="cmp-fam" key={data.familyKeys[i]}>
            <div className="cmp-fam-name">{fname}</div>
            <div className="cmp-fam-lines">
              {(["a", "b"] as const).map((side) => {
                const row = side === "a" ? a : b;
                const v = row.families[i];
                return (
                  <div
                    className="cmp-fam-line"
                    key={side}
                    data-cmpfamily={data.familyKeys[i]}
                    data-cmpside={side}
                    data-cmpasr={v === null ? "" : v}
                    {...(v === null ? { "data-na": "true" } : {})}
                  >
                    <span className="cmp-fam-side mono">{side.toUpperCase()}</span>
                    {v === null ? (
                      <span className="not-measured">·</span>
                    ) : (
                      <>
                        <span className="cmp-fam-track">
                          <span
                            className="cmp-fam-fill"
                            style={{
                              width: `${Math.max(v * 100, v > 0 ? 0.8 : 0)}%`,
                            }}
                          />
                        </span>
                        <span className="cmp-fam-val num">{fmtWholePct(v)}</span>
                      </>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      <p className="cmp-note">
        Deltas are model A minus model B, computed from the unrounded
        payload values and printed at the precision of their row. The
        percent rows read in percentage points. The dot marks the
        stronger side of a row.
      </p>
      <p className="cmp-note">
        A middot marks a figure a result does not carry. Slices and
        flagged results carry no robustness tax. A cost with ≥ is a
        lower bound, a cost of $0.00 is a locally served run, and a
        run with no recorded cost shows the middot. Where a cost is
        a lower bound, its delta is a difference of recorded totals.
      </p>
    </div>
  );
}
