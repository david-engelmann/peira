import type { Metadata } from "next";
import { notFound } from "next/navigation";
import {
  boardGroups,
  boardDateWords,
  boardVersions,
  flipDecomposition,
  taxBenchmarks,
  shortName,
  wireWords,
  duplicateShortNames,
  modelSlug,
  type BoardRow,
} from "@/lib/payload";
import { fmtPct, fmtInt } from "@/lib/format";
import { familyOrder } from "@/lib/charts";
import ModelCard, { type CardKind } from "@/components/ModelCard";

/**
 * One page per result, generated from the payload at build
 * time (the stack decision's per-model pages). The page renders
 * the same card body the board's index expands, behind the
 * same data derivations, so a shared link to a single result
 * shows exactly the figures the board shows. Each page carries
 * its own head, with the result's headline figures in its
 * description, and points its canonical address at itself.
 */

function allRows(): BoardRow[] {
  const groups = boardGroups();
  return [...groups.full, ...groups.slices, ...groups.flagged];
}

function rowForSlug(slug: string): BoardRow | undefined {
  const rows = allRows();
  return rows.find((r) => modelSlug(r, rows) === slug);
}

function kindAndRank(row: BoardRow): { kind: CardKind; rank: number | null } {
  const groups = boardGroups();
  const full = groups.full.find((r) => r.run_id === row.run_id);
  if (full) return { kind: "full", rank: full.rank };
  const slice = groups.slices.find((r) => r.run_id === row.run_id);
  if (slice) return { kind: "slice", rank: slice.rank };
  return { kind: "flagged", rank: null };
}

export function generateStaticParams() {
  const rows = allRows();
  return rows.map((row) => ({ slug: modelSlug(row, rows) }));
}

/**
 * The guarded sentence a malformed-majority flagged result
 * carries wherever its headline travels (cycle 7, RT-01 and
 * RT-02): the attack success figure with its base stated
 * correctly and its decomposition attached, in one breath.
 * Null unless the sealed family records derive a decomposition
 * in which most counted flips were malformed output. One
 * builder, used by the head description and by the page body,
 * so the two surfaces cannot drift apart.
 */
/** The flag prefix on a flagged result's head and page body. */
const FLAGGED_NOT_RANKED = "Flagged and not ranked.";

function decompositionSentence(row: BoardRow): string | null {
  if (row.asr_conditional === null) return null;
  const d = flipDecomposition(row);
  if (!d || d.malformedShare <= 0.5) return null;
  return `Attack success ${fmtPct(row.asr_conditional)} on the cases where the benign answer was right, most of it malformed output rather than changed decisions. Genuine flip rate ${fmtPct(d.genuineRate)}.`;
}

/**
 * The head description for a result's own page, the text a
 * shared link shows in search results and chat unfurls. A
 * flagged result's attack success never prints here bare
 * (cycle 7, C7-05): with a derivable malformed majority it
 * prints inside its decomposition sentence, and without one
 * it does not print at all. A slice result names the
 * sub-population its figures rest on (cycle 7, C7-R03). The
 * attack success base is stated as what it is, the cases
 * where the benign answer was right, not all paired cases
 * (cycle 7, RT-01).
 */
function pageDescription(row: BoardRow): string {
  const name = shortName(row);
  const head = `${name} on the Peira decision robustness board.`;
  if (row.asr_conditional === null) return head;
  const benign =
    row.benign_accuracy !== null ? fmtPct(row.benign_accuracy) : "not measured";
  const malformed =
    row.malformed_rate !== null ? fmtPct(row.malformed_rate) : "not measured";
  const { kind } = kindAndRank(row);
  if (kind === "flagged") {
    const decomp = decompositionSentence(row);
    if (decomp) {
      return `${head} ${FLAGGED_NOT_RANKED} ${decomp} Benign accuracy ${benign}, malformed rate ${malformed}.`;
    }
    return `${head} ${FLAGGED_NOT_RANKED} Benign accuracy ${benign}, malformed rate ${malformed}.`;
  }
  const base = `${head} Attack success ${fmtPct(row.asr_conditional)} on the cases where the benign answer was right, benign accuracy ${benign}, malformed rate ${malformed}.`;
  if (kind === "slice") {
    return `${base} Measured on the guardrail abstain subset, not the full suite.`;
  }
  return base;
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const row = rowForSlug(slug);
  if (!row) return {};
  const name = shortName(row);
  const description = pageDescription(row);
  const title = `${name} on the Peira board`;
  return {
    title,
    description,
    alternates: { canonical: `/models/${slug}` },
    openGraph: {
      type: "article",
      siteName: "Peira",
      title,
      description,
      url: `/models/${slug}`,
      images: [
        {
          url: "/og.png",
          width: 1200,
          height: 630,
          alt: "The Peira cost scatter: attack success against recorded cost per run, every full-suite model named beside its point",
        },
      ],
    },
    twitter: {
      card: "summary_large_image",
      title,
      description,
      images: ["/og.png"],
    },
  };
}

export default async function ModelPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const row = rowForSlug(slug);
  if (!row) notFound();
  const groups = boardGroups();
  const rows = allRows();
  const { kind, rank } = kindAndRank(row);
  const versions = boardVersions();
  const name = shortName(row);
  const decomp = kind === "flagged" ? decompositionSentence(row) : null;

  return (
    <main className="page model-page" id="main">
      <header className="masthead">
        <div className="masthead-top">
          <div>
            <p className="wordmark">Peira</p>
            <p className="claim">Decision models under attack</p>
          </div>
          <p className="stamp">
            dataset {versions.dataset}, suite {versions.suite}, updated{" "}
            {boardDateWords()}
          </p>
        </div>
        <p className="back-line">
          <a href="/">The full board</a>
          <a href="/#models">The model index</a>
        </p>
        {decomp && (
          <p className="decomp-line">{FLAGGED_NOT_RANKED} {decomp}</p>
        )}
        <h1 className="model-page-title">
          {name}
          {duplicateShortNames(rows).has(name) && (
            <span className="model-page-wire"> {wireWords(row.wire)}</span>
          )}
        </h1>
      </header>

      <article className="model-card standalone" data-card-for={row.run_id}>
        <ModelCard
          row={row}
          rank={rank}
          kind={kind}
          groupSize={
            kind === "full"
              ? groups.full.length
              : kind === "slice"
                ? groups.slices.length
                : 0
          }
          benchmarks={taxBenchmarks(groups)}
          familyKeys={familyOrder(rows)}
          allRows={rows}
          standalone
        />
      </article>

      <p className="chart-id">
        Peira decision robustness board, model detail for {name}. One of{" "}
        {fmtInt(rows.length)} results. Dataset {versions.dataset}, suite{" "}
        {versions.suite}, updated {boardDateWords()}.
      </p>
    </main>
  );
}
