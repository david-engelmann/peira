import { costIsLowerBound, familiesOf, familyFullName } from "@/lib/charts";
import { spearman } from "@/lib/findings";
import { fmtInt, fmtPct, fmtUsdExact } from "@/lib/format";
import { markOf } from "@/lib/inspectorData";
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
import { vendorFamilyOf } from "@/lib/vendorColors";
import StudyCostChart from "./StudyCostChart";
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

function hasPositiveCost(row: BoardRow): row is BoardRow & { total_cost_usd: number } {
  const cost = row.total_cost_usd;
  return cost !== null && Number.isFinite(cost) && cost > 0;
}

function costResults(rows: (BoardRow & { total_cost_usd: number })[]) {
  return rows.flatMap((row) => {
    const cost = row.total_cost_usd;
    const asr = row.asr_conditional;
    if (asr === null || !Number.isFinite(asr)) return [];
    const families = [...familiesOf(row).values()];
    const complete = families.length > 0 && families.every(f =>
      f.nLatencyCalls !== null && f.nCostedCalls === f.nLatencyCalls);
    return [{ row, cost, asr, ci: displayCi(row), lowerBound: costIsLowerBound(row), complete }];
  });
}

function CostFinding({ rows, allRows }: { rows: BoardRow[]; allRows: BoardRow[] }) {
  const recordedCosts = rows.filter(hasPositiveCost);
  const results = costResults(recordedCosts);
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
  const excludedCosts = rows.length - recordedCosts.length;
  const excludedRates = recordedCosts.length - results.length;

  return (
    <article className="study-finding study-finding-cost" aria-labelledby="study-cost-heading">
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
          {fmtInt(recordedCosts.length)} ranked full-suite results had positive serving costs
          recorded for the benchmark calls.{excludedCosts > 0 && <> {fmtInt(excludedCosts)} had zero or unrecorded cost.</>}
          {excludedRates > 0 && <> The chart excludes {fmtInt(excludedRates)} without an attack success rate.</>}
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
        <StudyCostChart points={results.map((result) => {
          const { row, cost, asr, ci, lowerBound, complete } = result;
          return {
            id: row.run_id,
            mark: { ...markOf(row), glyph: vendorFamilyOf(row).glyph },
            name: label(row),
            slug: modelSlug(row, allRows),
            cost,
            asr,
            ci,
            coverage: lowerBound ? "lower-bound" : complete ? "complete" : "unknown",
            highlighted: comparison !== null && (result === comparison || result === highestCost),
          };
        })} />
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
