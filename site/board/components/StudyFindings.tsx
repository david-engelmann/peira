import { costIsLowerBound, familiesOf, familyFullName } from "@/lib/charts";
import { spearman } from "@/lib/findings";
import { fmtCi, fmtInt, fmtPct, fmtUsdExact } from "@/lib/format";
import {
  boardGroups,
  displayCi,
  duplicateShortNames,
  familyFlipDecomposition,
  modelSlug,
  shortName,
  wireWords,
  type BoardRow,
} from "@/lib/payload";
import "./study-findings.css";

interface FamilyTotal {
  key: string;
  eligible: number;
  flips: number;
}

function familyTotals(rows: BoardRow[]) {
  const totals = new Map<string, FamilyTotal>();
  for (const row of rows) {
    const families = familiesOf(row);
    const counts = familyFlipDecomposition(row);
    let eligibleInRow = 0;
    for (const [key, family] of families) {
      const eligible = family.nEligible;
      if (eligible === null) return null;
      if (eligible === 0) continue;
      const count = counts.get(key);
      if (!count || count.flips > eligible) return null;
      eligibleInRow += eligible;
      const total = totals.get(key) ?? { key, eligible: 0, flips: 0 };
      total.eligible += eligible;
      total.flips += count.flips;
      totals.set(key, total);
    }
    if (eligibleInRow !== row.n_eligible) return null;
  }
  return [...totals.values()].sort(
    (a, b) => b.flips / b.eligible - a.flips / a.eligible || a.key.localeCompare(b.key),
  );
}

function FamilyFinding({ rows }: { rows: BoardRow[] }) {
  const families = familyTotals(rows);
  if (!families?.length) return null;

  const totalFlips = families.reduce((sum, family) => sum + family.flips, 0);
  const totalEligible = families.reduce((sum, family) => sum + family.eligible, 0);
  const leading = families.reduce((a, b) => a.flips >= b.flips ? a : b);
  const leadingShare = totalFlips === 0 ? 0 : leading.flips / totalFlips;
  const title = leading.key === "retrieval_poisoning" && totalFlips > 0
    ? "False documents accounted for the most flips"
    : "Where decisions flipped";

  return (
    <article className="study-finding" aria-labelledby="study-families-heading">
      <div className="study-finding-copy">
        <h3 id="study-families-heading">{title}</h3>
        {totalFlips > 0 && (
          <>
            <p className="study-finding-stat">{fmtPct(leadingShare)}</p>
            <p className="study-finding-context">
              of all counted flips came from {familyFullName(leading.key).toLowerCase()}.
            </p>
            <p>
              That family accounted for {fmtPct(leading.eligible / totalEligible)} of
              eligible cases across results.
            </p>
          </>
        )}
        <p className="study-finding-note">
          The same case can contribute once for each model run. Counted flips include attacked
          abstentions and malformed outputs.
        </p>
        <a className="study-finding-link" href="#explorer?pop=full&mode=families">
          Compare families by result <span aria-hidden="true">↗</span>
        </a>
      </div>

      <figure className="study-finding-figure">
        <figcaption className="study-chart-heading">
          <strong>Attack success by family</strong>
          <span>Counted flips / eligible cases</span>
        </figcaption>
        <ul className="study-family-chart" aria-label="Pooled results by attack family">
          {families.map(({ key, flips, eligible }) => (
            <li key={key} className={key === leading.key ? "study-family-leading" : undefined}>
              <span className="study-family-name">{familyFullName(key)}</span>
              <span className="study-family-rate">{fmtPct(flips / eligible)}</span>
              <span className="study-family-count">{fmtInt(flips)} / {fmtInt(eligible)}</span>
              <span className="study-family-track" aria-hidden="true">
                <span style={{ width: `${100 * flips / eligible}%` }} />
              </span>
            </li>
          ))}
        </ul>
        <p className="study-chart-key">
          {fmtInt(totalFlips)} counted flips across {fmtInt(totalEligible)} eligible cases pooled over all results.
        </p>
      </figure>
    </article>
  );
}

function costResults(rows: BoardRow[]) {
  return rows.flatMap((row) => {
    const cost = row.total_cost_usd;
    const asr = row.asr_conditional;
    if (cost === null || !Number.isFinite(cost) || cost <= 0 || asr === null) return [];
    const families = [...familiesOf(row).values()];
    const complete = families.length > 0 && families.every(f =>
      f.nLatencyCalls !== null && f.nCostedCalls === f.nLatencyCalls);
    return [{ row, cost, asr, ci: displayCi(row), lowerBound: costIsLowerBound(row), complete }];
  });
}

function CostFinding({ rows, allRows }: { rows: BoardRow[]; allRows: BoardRow[] }) {
  const results = costResults(rows);
  if (results.length < 2) return null;

  const complete = results.filter(result => result.complete);
  const lowerCost = complete.filter(({ cost }) => cost < 1);
  const bestBelowDollar = lowerCost.length
    ? lowerCost.reduce((a, b) => a.asr <= b.asr ? a : b)
    : null;
  const highestCost = results.reduce((a, b) => a.cost >= b.cost ? a : b);
  const comparison = bestBelowDollar !== highestCost ? bestBelowDollar : null;
  const duplicateNames = duplicateShortNames(allRows);
  const label = (row: BoardRow) => {
    const name = shortName(row);
    return duplicateNames.has(name) ? `${name} · ${wireWords(row.wire)}` : name;
  };
  const rho = spearman(results.map(({ cost }) => cost), results.map(({ asr }) => asr));
  const completeRho = complete.length < 2 ? NaN : spearman(complete.map(r => r.cost), complete.map(r => r.asr));
  const correlation = (value: number) => value.toFixed(2).replace("-", "−");
  const partialCount = results.filter(result => result.lowerBound).length;
  const hasLowerBounds = results.some(({ lowerBound }) => lowerBound);

  const lowestCost = Math.min(...results.map(({ cost }) => cost));
  const xMin = Math.log10(lowestCost) - 0.14;
  const xMax = Math.log10(highestCost.cost) + 0.14;
  const x = (cost: number) => `${100 * (Math.log10(cost) - xMin) / (xMax - xMin)}%`;
  const decadeStart = Math.ceil(xMin);
  const decadeStep = Math.max(1, Math.ceil((xMax - decadeStart) / 5));
  const decades = Array.from(
    { length: Math.floor((xMax - decadeStart) / decadeStep) + 1 },
    (_, i) => 10 ** (decadeStart + i * decadeStep),
  );
  const xTicks = decades.length >= 2 ? decades : [...new Set([lowestCost, highestCost.cost])];
  const maxAsr = Math.max(...results.map(({ asr, ci }) => ci?.[1] ?? asr));
  const yMax = Math.min(1, Math.max(0.2, Math.ceil((maxAsr + 0.025) * 10) / 10));
  const y = (rate: number) => `${100 * rate / yMax}%`;
  const yStep = yMax > 0.5 ? 0.2 : 0.1;
  const yTicks = Array.from(
    { length: Math.round(yMax / yStep) + 1 },
    (_, i) => i * yStep,
  ).map((tick) => Number(tick.toFixed(1))).filter((tick) => tick <= yMax);
  const excluded = rows.length - results.length;

  return (
    <article className="study-finding" aria-labelledby="study-cost-heading">
      <div className="study-finding-copy">
        <h3 id="study-cost-heading">What did robustness cost?</h3>
        {Number.isFinite(completeRho) && (
          <>
            <p className="study-finding-stat">{correlation(completeRho)}</p>
            <p className="study-finding-context">
              Spearman rank correlation between run cost and attack success across {fmtInt(complete.length)} fully priced results.
            </p>
          </>
        )}
        {Number.isFinite(rho) && complete.length !== results.length && (
          <p>Across all {fmtInt(results.length)} recorded costs, the correlation was {correlation(rho)}.
            {partialCount > 0 && <> For {fmtInt(partialCount)} runs, the recorded cost is a lower bound.</>}
          </p>
        )}
        {comparison && (
          <p className="study-finding-note">
            Among fully priced runs under $1, the lowest attack success rate was <strong>{fmtPct(comparison.asr)}</strong> at <strong>{fmtUsdExact(comparison.cost)}</strong>. At the highest recorded spend, attack success was <strong>{fmtPct(highestCost.asr)}</strong> with{" "}
            {highestCost.lowerBound && "at least "}<strong>{fmtUsdExact(highestCost.cost)}</strong> in cost.
          </p>
        )}
        <p className="study-finding-note">
          {fmtInt(results.length)} ranked full-suite results had positive serving costs
          recorded for the benchmark calls.{excluded > 0 && <> {fmtInt(excluded)} had zero or unrecorded cost.</>}
        </p>
        <a className="study-finding-link" href="#explorer?pop=full&mode=chart">
          Explore the cost chart <span aria-hidden="true">↗</span>
        </a>
      </div>

      <figure className="study-finding-figure">
        <figcaption className="study-chart-heading">
          <strong>Attack success vs. serving cost</strong>
          <span>Lower attack success is better</span>
        </figcaption>
        <div className="study-scatter" aria-hidden="true">
          <div className="study-scatter-plot">
            {yTicks.map((tick) => (
              <div className="study-scatter-horizontal" key={tick} style={{ bottom: y(tick) }}>
                <span>{Math.round(tick * 100)}%</span>
              </div>
            ))}
            {xTicks.map((tick) => (
              <div className="study-scatter-vertical" key={tick} style={{ left: x(tick) }}>
                <span>{decades.length >= 2 ? `$${tick}` : fmtUsdExact(tick)}</span>
              </div>
            ))}
            {results.map((result) => {
              const { row, cost, asr, ci, lowerBound } = result;
              const highlighted = comparison !== null && (result === comparison || result === highestCost);
              return (
                <div key={row.run_id}>
                  {ci && (
                    <div
                      className={`study-scatter-whisker${highlighted ? " study-scatter-highlight" : ""}`}
                      style={{ left: x(cost), bottom: y(ci[0]), height: y(ci[1] - ci[0]) }}
                    />
                  )}
                  <div
                    className={`study-scatter-point${highlighted ? " study-scatter-highlight" : ""}${lowerBound ? " study-scatter-lower-bound" : ""}`}
                    style={{ left: x(cost), bottom: y(asr) }}
                    title={`${label(row)} · ${lowerBound ? "≥" : ""}${fmtUsdExact(cost)} · ${fmtPct(asr)}`}
                  />
                </div>
              );
            })}
          </div>
          <p className="study-scatter-axis">Recorded serving cost (USD, log scale)</p>
        </div>
        <p className="study-chart-key">
          Vertical lines show per-result 95% Wilson intervals.
          {hasLowerBounds && <> Open circles mark cost lower bounds from unpriced calls.</>}
          {comparison && <> Larger turquoise points mark the two results discussed.</>}
        </p>
        <details className="study-cost-data">
          <summary>View {fmtInt(results.length)} results</summary>
          <table>
            <thead>
              <tr>
                <th scope="col">Result</th>
                <th scope="col">Cost</th>
                <th scope="col">Attack success <span>(95% CI)</span></th>
              </tr>
            </thead>
            <tbody>
              {results.map(({ row, cost, asr, ci, lowerBound }) => (
                <tr key={row.run_id}>
                  <th scope="row"><a href={`/models/${modelSlug(row, allRows)}/`}>{label(row)}</a></th>
                  <td>{lowerBound && "≥ "}{fmtUsdExact(cost)}</td>
                  <td>{fmtPct(asr)} {ci && <span>{fmtCi(ci)}</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      </figure>
    </article>
  );
}

export default function StudyFindings() {
  const { full, slices, flagged, fullCases } = boardGroups();
  if (!full.length) return null;

  return (
    <section className="study-findings" id="findings" aria-labelledby="study-findings-heading">
      <header className="study-findings-header">
        <h2 id="study-findings-heading">Study findings</h2>
        <p>
          {fmtInt(full.length)} ranked full-suite results, tested on the same{" "}
          {fmtInt(fullCases)} paired cases per result.
        </p>
      </header>
      <FamilyFinding rows={full} />
      <CostFinding rows={full} allRows={[...full, ...slices, ...flagged]} />
    </section>
  );
}
