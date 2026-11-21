import { ImageResponse } from "next/og";
import { cardColors, ShareCard } from "@/components/ShareCard";
import { boardGroups } from "@/lib/payload";
import { fmtInt, fmtPct } from "@/lib/format";
import { shareCardSize } from "@/lib/shareMetadata";

export const dynamic = "force-static";
export const size = shareCardSize;
export const contentType = "image/png";

export default function StudyPreview() {
  const { full, fullCases } = boardGroups();
  const rates = full.flatMap(row => row.asr_conditional === null ? [] : [row.asr_conditional]);
  const ceiling = Math.max(.1, Math.ceil(Math.max(0, ...rates) * 10) / 10);
  return new ImageResponse(
    <ShareCard label="Decision robustness benchmark">
      <div style={{ display: "flex", gap: 42, alignItems: "center", flexGrow: 1 }}>
        <div style={{ display: "flex", flexDirection: "column", width: 530 }}>
          <div style={{ fontSize: 69, lineHeight: 1.02, fontWeight: 700, letterSpacing: "-4px" }}>
            Which models hold up under attack?
          </div>
          <div style={{ fontSize: 26, lineHeight: 1.4, color: cardColors.quiet, marginTop: 22 }}>
            Peira tests each decision twice, with and without adversarial input.
          </div>
        </div>
        {rates.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", flexGrow: 1 }}>
            <span style={{ fontSize: 29, marginBottom: 16 }}>Attack success across the field</span>
            <div style={{ display: "flex", height: 204, gap: 10 }}>
              <div style={{
                display: "flex", flexGrow: 1, gap: 3, alignItems: "flex-end",
                borderTop: `1px solid ${cardColors.rule}`, borderBottom: `1px solid ${cardColors.rule}`,
              }}>
                {rates.map((rate, index) => (
                  <div key={index} style={{
                    flexGrow: 1, height: (202 * rate) / ceiling,
                    background: index < 3 ? cardColors.accent : "#87ac9b",
                  }} />
                ))}
              </div>
              <div style={{ display: "flex", flexDirection: "column", justifyContent: "space-between", fontSize: 17, color: cardColors.quiet }}>
                <span>{`${Math.round(ceiling * 100)}%`}</span>
                <span>0%</span>
              </div>
            </div>
            <span style={{ color: cardColors.quiet, fontSize: 19, marginTop: 12 }}>Rates use eligible cases</span>
          </div>
        )}
      </div>
      <div style={{
        display: "flex", justifyContent: "space-between", gap: 24, fontSize: 22,
        borderTop: `1px solid ${cardColors.rule}`, paddingTop: 16, color: cardColors.quiet,
      }}>
        <span>{`${fmtInt(fullCases)} paired cases in the full suite`}</span>
        {rates.length > 0 && <span>{`${rates.length} ranked full-suite results · lower attack success is better`}</span>}
      </div>
    </ShareCard>,
    size,
  );
}
