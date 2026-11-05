import {
  payload,
  boardGroups,
  boardDateWords,
  boardVersions,
  modelCounts,
  multiResultModels,
} from "@/lib/payload";
import { fmtInt, fmtPct } from "@/lib/format";
import { topData } from "@/lib/topData";
import TopBoard from "@/components/TopBoard";
import SectionNav from "@/components/SectionNav";
import FlaggedBand from "@/components/FlaggedBand";
import Malformed from "@/components/Malformed";
import Heatmap from "@/components/Heatmap";
import Calibration from "@/components/Calibration";
import ModelsSection from "@/components/ModelsSection";
import CompareSection from "@/components/CompareSection";
import Method from "@/components/Method";

/**
 * The board page, instrument panel order. Masthead and
 * hero, the sticky section bar, the scatter (01) and the
 * ranking with its inspector (02) as one island, the
 * flagged band (03), the malformed rail (04), attack
 * families (05), calibration (06), compare (07), the
 * models index (08), and method (09) last. The footer
 * carries the citation block, the corrections note, and
 * the doors to the code and the payload (TR-02, TR-04,
 * TR-05). The hero's first sentence is the frozen
 * definition, verbatim; the range that follows it and the
 * counts under it derive from the payload at build time.
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
  const rangeLines =
    fullFirst?.asr_conditional !== null &&
    fullFirst?.asr_conditional !== undefined &&
    fullLast?.asr_conditional !== null &&
    fullLast?.asr_conditional !== undefined ? (
      <>
        <span className="hl">On the full suite, attack success</span>{" "}
        <span className="hl">
          runs from{" "}
          <span className="rn">{fmtPct(fullFirst.asr_conditional)}</span> to{" "}
          <span className="rn">{fmtPct(fullLast.asr_conditional)}</span>.
        </span>
      </>
    ) : null;

  return (
    <main className="page" id="main">
      <header className="masthead">
        <div className="masthead-top">
          <div>
            <p className="wordmark">Peira</p>
            <p className="claim">Decision models under attack</p>
          </div>
          <nav className="mastnav" aria-label="Board highlights">
            <a href="#method">Method</a>
            <a href="#models">Models</a>
            <a href="#compare">Compare</a>
          </nav>
          <p className="stamp">
            dataset {versions.dataset}, suite {versions.suite}, updated{" "}
            {updated}
          </p>
        </div>
        <section className="hero">
          <p className="micro hero-eyebrow">
            Paired benign and attacked cases · One suite · Sealed runs
          </p>
          <h1 className="hero-title">
            <span className="hl">Attack success counts a case only when</span>{" "}
            <span className="hl">the benign answer was right and</span>{" "}
            <span className="hl">the attacked side answered wrong,</span>{" "}
            <span className="hl">
              abstained, or produced malformed output.
            </span>{" "}
            {rangeLines}
          </h1>
          <p className="counts-line">
            The board holds <b>{fmtInt(resultCount)}</b> results from{" "}
            <b>{fmtInt(counts.tested)}</b> models.{" "}
            <b>{fmtInt(counts.ranked)}</b> models are ranked and{" "}
            <b>{fmtInt(counts.flagged)}</b> are flagged.
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
                Some models were measured on more than one wire, so they
                appear as more than one result.
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

      <TopBoard data={topData()} />

      <FlaggedBand />

      <Malformed />

      <Heatmap />

      <Calibration />

      <CompareSection />

      <ModelsSection />

      <Method />

      <footer className="board-footer">
        <p>
          How to cite this board. Engelmann, D. Peira decision robustness
          board. Dataset {versions.dataset}, suite {versions.suite},
          updated {updated}.{" "}
          <a href="https://peiratrial.dev">peiratrial.dev</a>
        </p>
        <p>
          Corrections are made by republishing the payload and recording
          the change in this note, under the publish date above.
        </p>
        <p className="links-line">
          <a href="https://github.com/david-engelmann/peira">
            Code and method on GitHub
          </a>
          <a href="/payload.json">The payload behind this page, JSON</a>
          <a href="#method">Method and notes</a>
        </p>
      </footer>
    </main>
  );
}
