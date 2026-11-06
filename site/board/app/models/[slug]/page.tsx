import type { Metadata } from "next";
import {
  boardGroups,
  modelSlug,
  shortName,
  type BoardRow,
} from "@/lib/payload";

/**
 * A model address in the redesign is the explorer opened with
 * its result selected and its reading open. The address itself
 * still resolves, and hands the reader to that form. The page
 * carries no figures of its own, so nothing about a result can
 * drift between its address and its reading.
 */

function allRows(): BoardRow[] {
  const groups = boardGroups();
  return [...groups.full, ...groups.slices, ...groups.flagged];
}

export function generateStaticParams() {
  const rows = allRows();
  return rows.map((row) => ({ slug: modelSlug(row, rows) }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const rows = allRows();
  const row = rows.find((r) => modelSlug(r, rows) === slug);
  const name = row ? shortName(row) : slug;
  return {
    title: `${name} on the Peira board`,
    description: `The board address for ${name}. It opens the explorer with this result selected and its reading open.`,
  };
}

export default async function ModelAddress({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const target = `/#result=${encodeURIComponent(slug)}`;
  return (
    <main className="page model-redirect" id="main">
      <p className="micro">peira · Model address</p>
      <h1>This result now opens in the explorer</h1>
      <p className="cap">
        The board's model addresses open the explorer with the result
        selected and its reading open.{" "}
        <a href={target}>Open this result in the explorer</a>
      </p>
      <script
        dangerouslySetInnerHTML={{
          __html: `window.location.replace(${JSON.stringify(target)});`,
        }}
      />
    </main>
  );
}
