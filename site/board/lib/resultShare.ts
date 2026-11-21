import { explorerData } from "@/lib/explorerData";
import { fmtInt, fmtPct } from "@/lib/format";
import { boardGroups, boardVersions } from "@/lib/payload";

const results = explorerData().rows;
const resultsBySlug = new Map(results.map((row) => [row.slug, row]));
const { fullCases } = boardGroups();
const { dataset, suite } = boardVersions();

export function resultStaticParams() {
  return results.map((row) => ({ slug: row.slug }));
}

export function resultShare(slug: string) {
  const row = resultsBySlug.get(slug);
  if (!row) return null;

  const name = row.wire ? `${row.fullName} · ${row.wire}` : row.fullName;
  const scope = row.nCases === fullCases ? "full suite" : "guardrail subset";
  const standing = row.kind === "flagged" ? "Flagged · not ranked" : row.rankLine;
  const interval = row.asrText !== null && row.ciText !== null ? `95% CI ${row.ciText}` : null;
  const attackDetail = row.asrText === null
    ? "Attack success unavailable."
    : `${row.asrText} ${row.asrLabel.toLowerCase()} across ${fmtInt(row.nEligible)} eligible cases${interval ? ` (${interval})` : ""}.`;
  const decomposition = row.kind === "flagged" && row.decomp
    ? `Genuine flips: ${fmtPct(row.decomp.genuineRate)} of eligible cases. Malformed output: ${fmtPct(row.decomp.malformedShare)} of counted flips.`
    : null;
  return { row, name, scope, standing, attackDetail, interval, decomposition, dataset, suite };
}
