import { compareData } from "@/lib/compare";
import { boardDateWords, boardVersions } from "@/lib/payload";
import { fmtInt } from "@/lib/format";
import Compare from "./Compare";

/**
 * The compare section shell (design system sections 2.1 and
 * 4.6). Server component: it shapes the compact row set from
 * the payload once and hands it to the client island as
 * props. The same row set is printed beside the section as a
 * JSON script element, a machine readable copy that lets
 * integrity check 11 prove the island's dataset equals the
 * payload on every row, since the island's own arithmetic
 * cannot be read from static HTML.
 */
export default function CompareSection() {
  const data = compareData();
  const versions = boardVersions();
  return (
    <>
      <section
        className="section"
        aria-labelledby="compare-title"
        data-section="compare"
        id="compare"
      >
        <p className="section-label">Compare</p>
        <h2 className="section-title" id="compare-title">
          Two models head to head
        </h2>
        <p className="section-lede">
          Pick any two of the {fmtInt(data.rows.length)} results and
          read them side by side. The middle column gives the
          difference of the unrounded values, and the bars below set
          the two against each other family by family on the shared
          0 to 100 percent scale.
        </p>
        <Compare data={data} />
        <p className="chart-id">
          Peira decision robustness board, compare. Full suite base{" "}
          {fmtInt(data.fullCases)} cases, abstain slices{" "}
          {fmtInt(data.sliceCases)} cases. Dataset {versions.dataset},
          updated {boardDateWords()}.
        </p>
      </section>
      <script
        type="application/json"
        data-compare-rows={data.rows.length}
        dangerouslySetInnerHTML={{ __html: JSON.stringify(data.rows) }}
      />
    </>
  );
}
