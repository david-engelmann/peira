import { ImageResponse } from "next/og";
import { cardColors, ShareCard, ShareFooter } from "@/components/ShareCard";
import { boardGroups } from "@/lib/payload";
import { fmtInt } from "@/lib/format";
import { shareCardSize } from "@/lib/shareMetadata";

export const dynamic = "force-static";
export const size = shareCardSize;
export const contentType = "image/png";

export default function StudyPreview() {
  const { full, fullCases } = boardGroups();
  const rates = full.flatMap(row => row.asr_conditional === null ? [] : [row.asr_conditional]);
  const ceiling = Math.max(.1, Math.ceil(Math.max(0, ...rates) * 10) / 10);
  const plotHeight = 213;
  const barGap = rates.length > 40 ? 120 / rates.length : 3;
  return new ImageResponse(
    <ShareCard label="Decision robustness benchmark">
      <div style={{ display: "flex", gap: 40, alignItems: "center", flex: 1 }}>
        <div style={{ display: "flex", flexDirection: "column", width: rates.length ? 532 : 680 }}>
          <div style={{
            display: "flex", flexDirection: "column", fontSize: 64,
            lineHeight: 1.03, fontWeight: 700, letterSpacing: "-3.8px",
          }}>
            <span>When do AI</span>
            <span style={{ color: cardColors.accent }}>decisions change?</span>
          </div>
          <div style={{
            fontSize: 26, lineHeight: 1.4, color: cardColors.quiet, marginTop: 22, maxWidth: 475,
          }}>
            Peira tests each decision twice, with and without adversarial input.
          </div>
        </div>
        {rates.length > 0 && (
          <div style={{
            display: "flex", flexDirection: "column", flex: 1, backgroundColor: cardColors.panel,
            border: `1px solid ${cardColors.rule}`, borderRadius: 12, padding: "23px 26px 19px",
          }}>
            <span style={{ fontSize: 25, fontWeight: 700 }}>Attack success by rank</span>
            <span style={{ color: cardColors.quiet, fontSize: 18, marginTop: 4 }}>
              Ranked full-suite results
            </span>
            <div style={{ display: "flex", height: plotHeight, gap: 12, marginTop: 24 }}>
              <div style={{
                display: "flex", flex: 1, gap: barGap, alignItems: "flex-end", position: "relative",
                borderTop: `1px solid ${cardColors.rule}`, borderBottom: `1px solid ${cardColors.rule}`,
              }}>
                <div style={{
                  position: "absolute", top: "50%", left: 0, right: 0, height: 1,
                  backgroundColor: cardColors.rule,
                }} />
                {rates.map((rate, index) => (
                  <div key={index} style={{
                    flex: 1, height: ((plotHeight - 2) * rate) / ceiling,
                    backgroundColor: cardColors.field, borderRadius: "2px 2px 0 0",
                  }} />
                ))}
              </div>
              <div style={{
                display: "flex", flexDirection: "column", justifyContent: "space-between",
                alignItems: "flex-end", fontSize: 16, color: cardColors.quiet, margin: "-8px 0",
              }}>
                <span>{`${Math.round(ceiling * 100)}%`}</span>
                <span>{`${Math.round(ceiling * 50)}%`}</span>
                <span>0%</span>
              </div>
            </div>
            <span style={{ color: cardColors.accent, fontSize: 18, marginTop: 15 }}>
              Lower is better · rates use eligible cases
            </span>
          </div>
        )}
      </div>
      <ShareFooter>
        <div style={{ display: "flex", gap: 10 }}>
          <span style={{ color: cardColors.accent, fontWeight: 700 }}>{fmtInt(fullCases)}</span>
          <span>paired cases in the full suite</span>
        </div>
        {rates.length > 0 && <span>{`${rates.length} ranked results`}</span>}
      </ShareFooter>
    </ShareCard>,
    size,
  );
}
