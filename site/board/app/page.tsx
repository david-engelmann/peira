import {
  payload,
  boardGroups,
  boardDateWords,
  boardVersions,
  modelCounts,
  taxBenchmarks,
} from "@/lib/payload";
import { fmtInt, fmtPct, fmtEce } from "@/lib/format";
import Ranking from "@/components/Ranking";

/**
 * Round 8 prototype page. A compact masthead carrying the
 * orientation facts (what was measured, on how many cases, the
 * headline counts) over the ranking section alone. The findings
 * strip, navigation, and remaining sections land in their own
 * build rounds.
 */
export default function Page() {
  const groups = boardGroups();
  const counts = modelCounts();
  const benchmarks = taxBenchmarks(groups);
  const versions = boardVersions();
  const updated = boardDateWords();
  const resultCount = payload.ranked.length + payload.unranked.length;
  const fullFirst = groups.full[0];
  const fullLast = groups.full[groups.full.length - 1];
  const rangeText =
    fullFirst?.asr_conditional !== null &&
    fullFirst?.asr_conditional !== undefined &&
    fullLast?.asr_conditional !== null &&
    fullLast?.asr_conditional !== undefined
      ? ` On the full suite, attack success runs from ${fmtPct(fullFirst.asr_conditional)} to ${fmtPct(fullLast.asr_conditional)}.`
      : "";

  return (
    <main className="page" id="main">
      <header className="masthead">
        <div className="masthead-top">
          <div>
            <h1 className="wordmark">Peira</h1>
            <p className="claim">Decision models under attack</p>
          </div>
          <p className="stamp">
            dataset {versions.dataset}, suite {versions.suite}, updated{" "}
            {updated}
          </p>
        </div>
        <section className="findings">
          <p className="finding">
            Every model decided the same {fmtInt(groups.fullCases)} paired
            cases, each case in a benign form and an attacked form. Attack
            success is the share of eligible attacked cases where the
            attack flipped the decision.{rangeText}
          </p>
          <p className="counts-line">
            The board holds {fmtInt(resultCount)} results from{" "}
            {fmtInt(counts.tested)} models, counted by adapter and
            version. {fmtInt(counts.ranked)} are ranked and{" "}
            {fmtInt(counts.flagged)} are flagged.
          </p>
          <p className="links-line">
            <a href="https://github.com/david-engelmann/peira">
              Code and method on GitHub
            </a>
            <a href="/payload.json">The payload behind this page, JSON</a>
          </p>
        </section>
      </header>

      <Ranking />

      <footer className="proto-note">
        <p>
          Prototype for design review, built from payload publish 26.
          Robustness tax benchmarks derived from this payload are benign
          accuracy set by {benchmarks.benignSetter} at{" "}
          {fmtPct(benchmarks.benignValue)} and attacked ECE set by{" "}
          {benchmarks.eceSetter} at {fmtEce(benchmarks.eceValue)}, over
          the {benchmarks.cohortSize} full suite ranked results.
        </p>
        <p>
          How to cite this board. Engelmann, D. Peira decision robustness
          board. Dataset {versions.dataset}, suite {versions.suite},
          updated {updated}. peiratrial.dev
        </p>
        <p>
          What changed since the previous board. Model counts now key on
          adapter and version together, so the three guard models that
          share version 1.0 count as three models. Tie bands are drawn as
          brackets rather than listed in prose, and flagged results sit
          in their own strip. Corrections are made by republishing the
          payload and recording the change here.
        </p>
      </footer>
    </main>
  );
}
