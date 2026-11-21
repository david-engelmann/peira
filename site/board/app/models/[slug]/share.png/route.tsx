import { ImageResponse } from "next/og";
import { cardColors, ShareCard, ShareFooter } from "@/components/ShareCard";
import { fmtInt } from "@/lib/format";
import { resultShare, resultStaticParams } from "@/lib/resultShare";
import { shareCardSize } from "@/lib/shareMetadata";

export const dynamic = "force-static";
export const dynamicParams = false;

export function generateStaticParams() {
  return resultStaticParams();
}

function Metric({ number, label, detail, color }: {
  number: string | null; label: string; detail?: string; color: string;
}) {
  return (
    <div style={{
      display: "flex", flexDirection: "column", flex: 1,
      backgroundColor: cardColors.panel, padding: "14px 24px 17px",
      border: `1px solid ${cardColors.rule}`, borderRadius: 10,
    }}>
      <span style={{ fontSize: 21, fontWeight: 700 }}>{label}</span>
      <span style={{
        fontSize: number === null ? 42 : 66, fontWeight: 700, lineHeight: 1.05,
        letterSpacing: "-2.5px", color, marginTop: 4,
      }}>
        {number ?? "Unavailable"}
      </span>
      {detail && <span style={{ fontSize: 19, color: cardColors.quiet, marginTop: 5 }}>{detail}</span>}
    </div>
  );
}

export async function GET(_request: Request, { params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const result = resultShare(slug);
  if (!result) return new Response(null, { status: 404 });

  const { row, scope, standing, interval, decomposition, dataset, suite } = result;
  const statusColor = row.kind === "flagged" ? cardColors.flagged : cardColors.accent;
  const nameSize = row.fullName.length > 36 ? 48 : 64;
  const eligibility = row.asrText === null
    ? undefined
    : `${fmtInt(row.nEligible)} eligible cases${interval ? ` · ${interval}` : ""}`;
  return new ImageResponse(
    <ShareCard label="Decision robustness benchmark">
      <div style={{ display: "flex", flexDirection: "column", flex: 1, justifyContent: "center" }}>
        <div style={{ fontSize: 21, color: statusColor, fontWeight: 700 }}>
          {standing}
        </div>
        <div style={{
          fontSize: nameSize, lineHeight: 1.08, fontWeight: 700, letterSpacing: "-2.8px", marginTop: 6,
          overflowWrap: "anywhere",
        }}>
          {row.fullName}
        </div>
        {row.wire && <div style={{ fontSize: 20, color: cardColors.quiet, marginTop: 5 }}>{row.wire}</div>}
        <div style={{ display: "flex", gap: 16, marginTop: 19 }}>
          <Metric number={row.asrText} label={row.asrLabel} detail={eligibility} color={statusColor} />
          <Metric number={row.benignText} label="Benign accuracy" color={cardColors.field} />
        </div>
        {decomposition && <div style={{ color: cardColors.flagged, fontSize: 18, marginTop: 14 }}>{decomposition}</div>}
        {row.unanswered && <div style={{ color: cardColors.quiet, fontSize: 17, marginTop: 6 }}>{row.unanswered}</div>}
        {row.singleCall && <div style={{ color: cardColors.quiet, fontSize: 17, marginTop: 5 }}>{row.singleCall}</div>}
      </div>
      <ShareFooter>
        <span>{`${fmtInt(row.nCases)} paired cases · ${scope}`}</span>
        <span>{`Dataset ${dataset} · Suite ${suite}`}</span>
      </ShareFooter>
    </ShareCard>,
    shareCardSize,
  );
}
