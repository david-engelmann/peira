import {
  payload,
  boardGroups,
  boardDateWords,
  boardVersions,
  modelCounts,
  multiResultModels,
} from "@/lib/payload";
import { fmtInt, fmtPct } from "@/lib/format";
import Ranking from "@/components/Ranking";
import SectionNav from "@/components/SectionNav";
import Malformed from "@/components/Malformed";
import Heatmap from "@/components/Heatmap";
import Scatter from "@/components/Scatter";
import Calibration from "@/components/Calibration";
import ModelCards from "@/components/ModelCards";
import CompareSection from "@/components/CompareSection";
import Method from "@/components/Method";

/**
 * The board page, in the design system's section order (2.1).
 * Masthead and findings, the sticky section bar, ranking,
 * malformed and admission, attack families, cost, calibration,
 * model detail, compare, and method last. The footer carries
 * the citation block, the what changed note, and the doors to
 * the code and the payload (TR-02, TR-04, TR-05).
 */
export default function Page() {
  const groups = boardGroups();
  const counts = modelCounts();
  const multi = multiResultModels();
  const versions = boardVersions();
  const updated = boardDateWords();
  const resultCount = payload.ranked.length + payload.unranked.length;
  const fullFirst = groups.full[0];
  const fullLast = groups.full[groups.full.length - 1];
  const rangeHl =
    fullFirst?.asr_conditional !== null &&
    fullFirst?.asr_conditional !== undefined &&
    fullLast?.asr_conditional !== null &&
    fullLast?.asr_conditional !== undefined ? (
      <>
        {" "}
        On the full suite, attack success runs from{" "}
        <span className="range-hl">{fmtPct(fullFirst.asr_conditional)}</span>{" "}
        to <span className="range-hl">{fmtPct(fullLast.asr_conditional)}</span>.
      </>
    ) : null;

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
            Every model decided the same paired cases, each case in a
            benign form and an attacked form. Attack success counts a
            case only when the benign answer was right and the
            attacked answer was wrong.{rangeHl}
          </p>
          <p className="counts-line">
            The board holds {fmtInt(resultCount)} results from{" "}
            {fmtInt(counts.tested)} models. {fmtInt(counts.ranked)} models
            are ranked and {fmtInt(counts.flagged)} are flagged.
            {multi.length === 1 && (
              <>
                {" "}
                One model was measured on two wires, so it appears as two
                results.
              </>
            )}
            {multi.length > 1 && (
              <>
                {" "}
                Some models were measured on two wires, so they appear as
                more than one result.
              </>
            )}
          </p>
          <p className="links-line">
            <a href="https://github.com/david-engelmann/peira">
              Code and method on GitHub
            </a>
            <a href="/payload.json">The payload behind this page, JSON</a>
          </p>
        </section>
      </header>

      <SectionNav />

      <Ranking />

      <Malformed />

      <Heatmap />

      <Scatter />

      <Calibration />

      <ModelCards />

      <CompareSection />

      <Method />

      <footer className="board-footer">
        <p>
          How to cite this board. Engelmann, D. Peira decision robustness
          board. Dataset {versions.dataset}, suite {versions.suite},
          updated {updated}.{" "}
          <a href="https://peiratrial.dev">peiratrial.dev</a>
        </p>
        <p>
          What changed since the previous board. Model counts now count
          the distinct models the board displays. The previous board
          keyed its counts on version alone and merged three unrelated
          guard models that share version 1.0 into one counted model.
          Tie bands are drawn as brackets rather than listed in prose,
          and flagged results sit in their own strip. Corrections are
          made by republishing the payload and recording the change
          here.
        </p>
        <p className="links-line">
          <a href="https://github.com/david-engelmann/peira">
            Code and method on GitHub
          </a>
          <a href="/payload.json">The payload behind this page, JSON</a>
          <a href="#method">Method and notes</a>
        </p>
        <p>
          Peira decision robustness board. Dataset {versions.dataset},
          suite {versions.suite}, updated {updated}.
        </p>
      </footer>
    </main>
  );
}
