import {
  boardDateWords, boardGroups, displayCi, duplicateShortNames, flipDecomposition,
  modelCounts, modelSlug, shortName, wireWords,
} from "@/lib/payload";
import { fmtCi, fmtInt, fmtPct } from "@/lib/format";

export default function Headline() {
  const { full, fullCases, slices, flagged } = boardGroups();
  const all = [...full, ...slices, ...flagged];
  const comparisons = full.flatMap(row =>
    row.asr_conditional === null ? [] : [{ row, rate: row.asr_conditional }]
  );
  const best = comparisons[0];
  const flips = best ? flipDecomposition(best.row) : null;
  const featured = comparisons.slice(0, 3);
  const intervals = featured.flatMap(({ row }) => {
    const ci = displayCi(row);
    return ci ? [ci] : [];
  });
  const overlapping = featured.length > 1 && intervals.length === featured.length &&
    Math.max(...intervals.map(ci => ci[0])) <= Math.min(...intervals.map(ci => ci[1]));
  const duplicates = duplicateShortNames(all);
  const ceiling = Math.max(0.1, Math.ceil(Math.max(0, ...comparisons.map(d => d.rate)) * 10) / 10);
  return (
    <section className="study-cover" id="results" aria-labelledby="study-title">
      <div className="cover-copy">
        <p className="study-kicker">Decision robustness benchmark</p>
        <h1 id="study-title">Which models <em>hold up</em> under attack?</h1>
        <p className="study-intro">
          Peira tests each decision twice, first as written and then with adversarial input.
          {best && flips && (
            <> Among ranked full-suite runs, the lowest observed attack success rate was {fmtPct(best.rate)},
              with {fmtInt(flips.flips)} failures in {fmtInt(best.row.n_eligible)} eligible cases.</>
          )}
        </p>
        <div className="cover-links">
          <a href="#explorer">Explore the results <span aria-hidden="true">↗</span></a>
          <a href="#method">How we measure</a>
        </div>
        <dl className="study-facts">
          <div><dt>Paired cases</dt><dd>{fmtInt(fullCases)}</dd></div>
          <div><dt>Models tested</dt><dd>{fmtInt(modelCounts().tested)}</dd></div>
        </dl>
      </div>
      {best && <figure className="field-plate">
        <div className="plate-dateline"><span>Full suite</span><time>{boardDateWords()}</time></div>
        <h2>Attack success across the field</h2>
        <p>Each bar shows one of {comparisons.length} ranked full-suite results. Lower is better.</p>
        <div className="plate-graph" role="img" aria-label={`Attack success across ${comparisons.length} ranked full-suite results ranges from ${fmtPct(best.rate)} to ${fmtPct(comparisons[comparisons.length - 1].rate)} of eligible cases.`}>
          <div className="plate-bars">
            {comparisons.map(({ row, rate }, index) => (
              <i key={row.run_id} className={index < featured.length ? "highlight" : undefined}
                style={{ height: `${100 * rate / ceiling}%` }} />
            ))}
          </div>
          <div className="plate-axis">
            {[ceiling, ceiling / 2, 0].map(tick => (
              <span key={tick}>{Math.round(tick * 100)}%</span>
            ))}
          </div>
        </div>
        <div className="plate-key"><span>Lowest observed rates</span><span>95% interval</span></div>
        <ol>
          {featured.map(({ row, rate }) => {
            const ci = displayCi(row);
            const name = shortName(row);
            return (
              <li key={row.run_id}>
                <a href={`#result=${encodeURIComponent(modelSlug(row, all))}`}>
                  {name}{duplicates.has(name) && ` · ${wireWords(row.wire)}`}
                </a>
                <strong>{fmtPct(rate)}</strong>
                <span>{ci ? fmtCi(ci) : "Unavailable"}</span>
              </li>
            );
          })}
        </ol>
        <figcaption>Rates use each result’s eligible cases.{overlapping && " The intervals for these results overlap."}</figcaption>
      </figure>}
    </section>
  );
}
