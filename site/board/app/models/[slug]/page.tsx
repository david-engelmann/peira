import type { Metadata } from "next";
import PeiraBrand from "@/components/PeiraBrand";
import {
  boardGroups,
  duplicateShortNames,
  modelSlug,
  shortName,
  splitDisplayName,
  wireWords,
  type BoardRow,
} from "@/lib/payload";
import { resultShare, resultStaticParams } from "@/lib/resultShare";
import { shareMetadata } from "@/lib/shareMetadata";

/**
 * A model address in the redesign is the explorer opened with
 * its result selected and its reading open. The address itself
 * still resolves, and hands the reader to that form. The page
 * names its own result, as every other surface names what it
 * shows, so a reader who lands without JavaScript, or who
 * meets the address as a tab or a shared link, can tell one
 * result's page from another's.
 */

function allRows(): BoardRow[] {
  const groups = boardGroups();
  return [...groups.full, ...groups.slices, ...groups.flagged];
}

function rowForSlug(slug: string): BoardRow | undefined {
  const rows = allRows();
  return rows.find((row) => modelSlug(row, rows) === slug);
}

export const dynamicParams = false;

export function generateStaticParams() {
  return resultStaticParams();
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const result = resultShare(slug);
  if (!result) return {};
  const { row, name, standing, attackDetail, decomposition } = result;
  const description = [`${standing}.`, attackDetail, decomposition, row.unanswered, row.singleCall]
    .filter(Boolean).join(" ");
  const benign = row.benignText ? ` Benign accuracy: ${row.benignText}.` : "";
  return shareMetadata({
    title: `${name} · Peira decision robustness board`,
    description,
    path: row.href,
    imagePath: `${row.href}share.png`,
    imageAlt: `${name}. ${description}${benign}`,
  });
}

export default async function ModelAddress({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const target = `/#result=${encodeURIComponent(slug)}`;
  const rows = allRows();
  const row = rowForSlug(slug);
  const name = row ? splitDisplayName(row.display_name).name : null;
  const shared =
    row !== undefined && duplicateShortNames(rows).has(shortName(row));
  return (
    <main className="page model-redirect">
      <a className="route-brand" href="/" aria-label="Peira home"><PeiraBrand /></a>
      <h1>{name ?? "This result now opens in the explorer"}</h1>
      {row && shared && <p className="micro">{wireWords(row.wire)}</p>}
      <p className="cap">
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
