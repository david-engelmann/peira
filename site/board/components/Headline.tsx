import CoverField from "@/components/CoverField";
import {
  boardDateWords, boardGroups, displayCi, duplicateShortNames, flipDecomposition,
  modelCounts, modelSlug, shortName, wireWords,
} from "@/lib/payload";
import { fmtCi, fmtInt, fmtPct } from "@/lib/format";
import DistributionChart from "./DistributionChart";

function malformedShareText(flips: ReturnType<typeof flipDecomposition>): string | null {
  return flips && flips.malformedShare > 0.5
    ? `${fmtPct(flips.malformedShare)} of counted flips went to malformed output`
    : null;
}

export default function Headline() {
  const { full, fullCases, slices, flagged } = boardGroups();
  const all = [...full, ...slices, ...flagged];
  const comparisons = full.flatMap(row =>
    row.asr_conditional === null ? [] : [{ row, rate: row.asr_conditional }]
  );
  const best = comparisons[0];
  const flips = best ? flipDecomposition(best.row) : null;
  const bestMalformedShare = malformedShareText(flips);
  const worst = comparisons.at(-1);
  const worstMalformedShare = worst ? malformedShareText(flipDecomposition(worst.row)) : null;
  const duplicates = duplicateShortNames(all);
  const chartResults = comparisons.map(({ row, rate }) => {
    const name = shortName(row);
    return {
      name: duplicates.has(name) ? `${name} · ${wireWords(row.wire)}` : name,
      href: `#result=${encodeURIComponent(modelSlug(row, all))}`,
      rate,
      interval: displayCi(row),
      malformedShare: malformedShareText(flipDecomposition(row)),
    };
  });
  const featured = chartResults.slice(0, 3);
  const intervals = featured.flatMap(({ interval }) => interval ? [interval] : []);
  const overlapping = featured.length > 1 && intervals.length === featured.length &&
    Math.max(...intervals.map(ci => ci[0])) <= Math.min(...intervals.map(ci => ci[1]));
  return (
    <section className="study-cover" id="results" aria-labelledby="study-title">
      <CoverField />
      <div className="cover-copy">
        <p className="study-kicker">Decision robustness benchmark</p>
        <h1 id="study-title">When do AI <em>decisions change?</em></h1>
        <p className="study-intro">
          Peira gives each model the same case twice. The first version establishes its answer. The second tests whether that decision holds under adversarial input.
        </p>
        <div className="cover-links">
          <a href="#explorer">Explore results <span aria-hidden="true">→</span></a>
          <a href="#method">How scoring works</a>
        </div>
        <dl className="study-facts">
          <div><dt>Paired cases</dt><dd>{fmtInt(fullCases)}</dd></div>
          <div><dt>Models tested</dt><dd>{fmtInt(modelCounts().tested)}</dd></div>
          {best && <div><dt>Lowest attack success</dt><dd><a href={featured[0].href}>{fmtPct(best.rate)}</a></dd></div>}
        </dl>
        {best && flips && bestMalformedShare && (
          <p className="cover-rate-note">The lowest rate was measured with {fmtInt(flips.flips)} counted flips in {fmtInt(best.row.n_eligible)} eligible cases. {bestMalformedShare}.</p>
        )}
      </div>
      {best && worst && <figure className="field-plate" aria-labelledby="distribution-title">
        <div className="plate-dateline"><span>Full suite · {fmtInt(comparisons.length)} ranked results</span><time>{boardDateWords()}</time></div>
        <h2 id="distribution-title">Attack success across the field</h2>
        <p>Share of eligible cases. Lower is better.</p>
        <DistributionChart
          results={chartResults}
          featuredCount={featured.length}
          summary={`Attack success across ${comparisons.length} ranked full-suite results ranges from ${fmtPct(best.rate)}${bestMalformedShare ? ` (${bestMalformedShare})` : ""} to ${fmtPct(worst.rate)}${worstMalformedShare ? ` (${worstMalformedShare})` : ""} of eligible cases.`}
        />
        <div className="plate-key"><span>Lowest observed rates</span><span>95% interval</span></div>
        <ol>
          {featured.map(({ href, name, rate, interval, malformedShare }) => (
            <li key={href}>
              <a href={href}>{name}</a>
              <strong>{fmtPct(rate)}{malformedShare && <span> · {malformedShare}</span>}</strong>
              <span>{interval ? fmtCi(interval) : "Unavailable"}</span>
            </li>
          ))}
        </ol>
        <figcaption>Each rate uses that result’s eligible cases.{overlapping && " The intervals shown overlap."}</figcaption>
      </figure>}
    </section>
  );
}
