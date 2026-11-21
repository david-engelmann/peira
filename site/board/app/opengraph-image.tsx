import { ImageResponse } from "next/og";
import { cardColors, ShareCard } from "@/components/ShareCard";
import { boardGroups } from "@/lib/payload";
import { fmtInt, fmtPct } from "@/lib/format";
import { shareCardSize } from "@/lib/shareMetadata";

export const dynamic = "force-static";
export const size = shareCardSize;
export const contentType = "image/png";

const plotWidth = 408;
const plotHeight = 142;

function RankedRates({ rates }: { rates: number[] }) {
  const lowest = rates[0];
  const highest = rates[rates.length - 1];
  const ceiling = Math.max(0.1, Math.ceil(highest * 10) / 10);
  const baseline = plotHeight - 7;
  const points = rates.map((rate, index) => ({
    x: rates.length === 1 ? plotWidth / 2 : 7 + (plotWidth - 14) * index / (rates.length - 1),
    y: baseline - (plotHeight - 14) * rate / ceiling,
  }));
  const line = points.map(({ x, y }) => `${x},${y}`).join(" ");
  const first = points[0];
  const last = points[points.length - 1];

  return (
    <div style={{
      display: "flex", flexDirection: "column", width: 478, flexShrink: 0,
      backgroundColor: cardColors.panel, border: `1px solid ${cardColors.rule}`,
      borderRadius: 18, padding: "28px 34px",
    }}>
      <span style={{ fontSize: 40, fontWeight: 700, letterSpacing: "-1px" }}>Attack success</span>
      <span style={{ fontSize: 62, fontWeight: 700, color: cardColors.accent, letterSpacing: "-2px" }}>
        {lowest === highest ? fmtPct(lowest) : `${fmtPct(lowest)}–${fmtPct(highest)}`}
      </span>
      <span style={{ fontSize: 26, color: cardColors.quiet }}>Share of eligible cases</span>
      <svg width={plotWidth} height={plotHeight} viewBox={`0 0 ${plotWidth} ${plotHeight}`} style={{ marginTop: 21 }}>
        <line x1={0} y1={baseline} x2={plotWidth} y2={baseline} stroke={cardColors.rule} strokeWidth={2} />
        {rates.length > 1 && <g>
          <polygon points={`${first.x},${baseline} ${line} ${last.x},${baseline}`} fill={cardColors.accent} fillOpacity={0.14} />
          <polyline points={line} fill="none" stroke={cardColors.accent} strokeWidth={4} strokeLinejoin="round" />
        </g>}
        {points.map(({ x, y }, index) => (
          <circle
            key={index}
            cx={x}
            cy={y}
            r={index === 0 || index === points.length - 1 ? 6 : 2.5}
            fill={cardColors.accent}
          />
        ))}
      </svg>
      <span style={{ fontSize: 24, color: cardColors.quiet, marginTop: 12 }}>
        {`${fmtInt(rates.length)} ranked full-suite ${rates.length === 1 ? "result" : "results"}`}
      </span>
    </div>
  );
}

export default function StudyPreview() {
  const { full, fullCases } = boardGroups();
  const rates = full.flatMap(row => row.asr_conditional === null ? [] : [row.asr_conditional]);
  return new ImageResponse(
    <ShareCard>
      <div style={{ display: "flex", gap: 40, alignItems: "center", flex: 1 }}>
        <div style={{ display: "flex", flexDirection: "column", flex: 1 }}>
          <div style={{
            display: "flex", flexDirection: "column", fontSize: 87,
            lineHeight: 1, fontWeight: 700, letterSpacing: "-4px",
          }}>
            <span>When do AI</span>
            <span style={{ color: cardColors.accent }}>decisions</span>
            <span style={{ color: cardColors.accent }}>change?</span>
          </div>
          {fullCases > 0 && (
            <div style={{ display: "flex", gap: 9, marginTop: 34, fontSize: 32, color: cardColors.quiet }}>
              <span style={{ fontWeight: 700, color: cardColors.ink }}>{fmtInt(fullCases)}</span>
              <span>paired cases</span>
            </div>
          )}
        </div>
        {rates.length > 0 && <RankedRates rates={rates} />}
      </div>
    </ShareCard>,
    size,
  );
}
