import { boardGroups, modelSlug, type BoardRow } from "@/lib/payload";

/**
 * A model address in the redesign is the explorer opened with
 * its result selected and its reading open. The address itself
 * still resolves, and hands the reader to that form.
 */

export function generateStaticParams() {
  const groups = boardGroups();
  const allRows: BoardRow[] = [
    ...groups.full,
    ...groups.slices,
    ...groups.flagged,
  ];
  return allRows.map((row) => ({ slug: modelSlug(row, allRows) }));
}

export default async function ModelAddress({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const target = `/#result=${encodeURIComponent(slug)}`;
  return (
    <main className="page model-redirect">
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
