import {
  boardGroups,
  boardVersions,
  modelCounts,
  multiResultModels,
} from "@/lib/payload";
import { fmtInt } from "@/lib/format";
import { explorerData } from "@/lib/explorerData";
import VendorSprite from "@/components/VendorSprite";
import TopBar from "@/components/TopBar";
import Headline from "@/components/Headline";
import Findings from "@/components/Findings";
import Explorer from "@/components/Explorer";
import MethodStub from "@/components/MethodStub";

/**
 * The board. Numbered scenes in the Maidan landing's design
 * language, the money shot compositions carried as each
 * scene's object. The hero states what Peira is, the headline
 * results follow at once, the explorer stands as the full
 * record, and the findings stand after it as evidence.
 * Method stands in its diet form. This source is what
 * publishes to peiratrial.dev.
 */

const MONTHS = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

function dateWords(iso: string): string {
  const [y, m, d] = iso
    .slice(0, 10)
    .split("-")
    .map((part) => Number(part));
  if (!y || !m || !d || m < 1 || m > 12) return iso.slice(0, 10);
  return `${d} ${MONTHS[m - 1]} ${y}`;
}

export default function Home() {
  const groups = boardGroups();
  const versions = boardVersions();
  const counts = modelCounts();
  const multi = multiResultModels();
  /* The re-measurement note the Method scene promises at the
   * foot of the page, derived from the payload's own re-run
   * records. A re-run record proves a later recording exists,
   * chained to an earlier run on a stated date, and nothing
   * more, so the note claims exactly that. Where a result was
   * recorded again, the publish prints the later recording's
   * figures in place of the earlier run's, and the result's
   * reading in the explorer says it was recorded again. The
   * note exists only while the payload carries re-run records
   * to stand on. */
  const rerunDates = [
    ...groups.full,
    ...groups.slices,
    ...groups.flagged,
  ]
    .map((r) => r.rerun?.date)
    .filter((d): d is string => typeof d === "string")
    .sort();
  const rerunNote =
    rerunDates.length === 0
      ? null
      : rerunDates[0] === rerunDates[rerunDates.length - 1]
        ? `Re-measurement note. ${fmtInt(rerunDates.length)} results on this board were recorded again after an earlier run, on ${dateWords(rerunDates[0])}. This publish prints the later recording's figures in place of the earlier run's, and each result's reading says it was recorded again.`
        : `Re-measurement note. ${fmtInt(rerunDates.length)} results on this board were recorded again after an earlier run, between ${dateWords(rerunDates[0])} and ${dateWords(rerunDates[rerunDates.length - 1])}. This publish prints the later recording's figures in place of the earlier run's, and each result's reading says it was recorded again.`;
  const total =
    groups.full.length + groups.slices.length + groups.flagged.length;
  const countsLine =
    `The board holds ${fmtInt(total)} results from ${fmtInt(counts.tested)} models. ` +
    `${fmtInt(counts.ranked)} models are ranked and ${fmtInt(counts.flagged)} are flagged.` +
    (multi.length === 1
      ? " One model was measured on two wires, so it appears as two results."
      : multi.length > 1
        ? ` ${fmtInt(multi.length)} models were measured on two wires, so each appears as two results.`
        : "");
  const data = explorerData();

  return (
    <main className="page">
      <VendorSprite />
      <TopBar />

      <section className="hero" id="top" aria-label="The board">
        <p className="micro">Paired measurement · Benign and attacked</p>
        <h1>Decision models, measured under attack</h1>
        <p className="hero-lede">
          Peira is an adversarial robustness benchmark for AI decision
          models. Every model decided the same paired cases, each case
          in a benign form and an attacked form, and Peira measures how
          often the attacked form flips a right answer.
        </p>
        <p className="hero-counts">{countsLine}</p>
      </section>

      <Headline />
      <Explorer data={data} />
      <Findings />
      <MethodStub />

      <footer className="colophon">
        <p>
          Dataset {versions.dataset} · Suite {versions.suite} ·{" "}
          {countsLine} The figures derive from the sealed runs in the
          payload this page links.
        </p>
        {rerunNote !== null && <p>{rerunNote}</p>}
        <p>
          The board is rebuilt from the sealed payload on every
          publish.
        </p>
      </footer>
    </main>
  );
}
