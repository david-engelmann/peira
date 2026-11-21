import { ImageResponse } from "next/og";
import { cardColors, ShareCard } from "@/components/ShareCard";
import { fmtInt } from "@/lib/format";
import { resultShare, resultStaticParams } from "@/lib/resultShare";
import { shareCardSize } from "@/lib/shareMetadata";

export const dynamic = "force-static";
export const dynamicParams = false;

export function generateStaticParams() {
  return resultStaticParams();
}

export async function GET(_request: Request, { params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const result = resultShare(slug);
  if (!result) return new Response(null, { status: 404 });

  const { row, scope, standing, decomposition, dataset, suite } = result;
  const flagged = row.kind === "flagged";
  const nameSize = row.fullName.length > 36 ? 48 : 66;
  return new ImageResponse(
    <ShareCard label="Decision robustness benchmark">
      <div style={{ display: "flex", flexDirection: "column", flexGrow: 1, justifyContent: "center" }}>
        <div style={{ fontSize: 24, color: flagged ? cardColors.flagged : cardColors.accent }}>
          {standing}
        </div>
        <div style={{ fontSize: nameSize, lineHeight: 1.1, fontWeight: 700, letterSpacing: "-2px", marginTop: 12 }}>
          {row.fullName}
        </div>
        {row.wire && <div style={{ fontSize: 24, color: cardColors.quiet, marginTop: 8 }}>{row.wire}</div>}
        <div style={{ display: "flex", gap: 44, marginTop: 29 }}>
          <div style={{ display: "flex", flexDirection: "column", flex: 1 }}>
            <span style={{ fontSize: row.asrText === null ? 44 : 70, fontWeight: 700, lineHeight: 1.02, color: cardColors.accent }}>
              {row.asrText ?? "Unavailable"}
            </span>
            <span style={{ fontSize: 24, marginTop: 8 }}>{row.asrLabel}</span>
            {row.asrText !== null && <span style={{ fontSize: 21, color: cardColors.quiet, marginTop: 5 }}>{`${fmtInt(row.nEligible)} eligible cases`}</span>}
          </div>
          <div style={{ display: "flex", flexDirection: "column", flex: 1, borderLeft: `1px solid ${cardColors.rule}`, paddingLeft: 44 }}>
            <span style={{ fontSize: row.benignText === null ? 44 : 70, fontWeight: 700, lineHeight: 1.02 }}>
              {row.benignText ?? "Unavailable"}
            </span>
            <span style={{ fontSize: 24, marginTop: 8 }}>Benign accuracy</span>
          </div>
        </div>
        {decomposition && <div style={{ color: cardColors.flagged, fontSize: 21, marginTop: 21 }}>{decomposition}</div>}
        {row.unanswered && <div style={{ color: cardColors.quiet, fontSize: 19, marginTop: 7 }}>{row.unanswered}</div>}
        {row.singleCall && <div style={{ color: cardColors.quiet, fontSize: 19, marginTop: 5 }}>{row.singleCall}</div>}
      </div>
      <div style={{
        display: "flex", justifyContent: "space-between", fontSize: 22, gap: 24,
        color: cardColors.quiet, borderTop: `1px solid ${cardColors.rule}`, paddingTop: 16,
      }}>
        <span>{`${fmtInt(row.nCases)} paired cases · ${scope}`}</span>
        <span>{`${dataset} · ${suite}`}</span>
      </div>
    </ShareCard>,
    shareCardSize,
  );
}
