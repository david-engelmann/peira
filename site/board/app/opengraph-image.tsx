import { ImageResponse } from "next/og";
import { boardGroups } from "@/lib/payload";
import { fmtInt, fmtPct } from "@/lib/format";

export const dynamic = "force-static";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";
export const alt = "Peira decision robustness benchmark. Ranked full-suite attack success rates in ascending order.";

export default function StudyPreview() {
  const { full, fullCases } = boardGroups();
  const rates = full.flatMap(row => row.asr_conditional === null ? [] : [row.asr_conditional]);
  const ceiling = Math.max(.1, Math.ceil(Math.max(0, ...rates) * 10) / 10);
  return new ImageResponse(
    <div style={{ display: "flex", flexDirection: "column", width: "100%", height: "100%",
      background: "#123a31", color: "#f5f7ec", padding: "50px 60px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: "1px solid #8ba496", paddingBottom: 18 }}>
        <span style={{ fontSize: 36, fontWeight: 700 }}>peira</span>
        <span style={{ fontSize: 22 }}>Decision robustness benchmark</span>
      </div>
      <div style={{ fontSize: 68, letterSpacing: "-3px", marginTop: 30 }}>Which models hold up under attack?</div>
      <div style={{ fontSize: 25, color: "#d1ddd0", marginTop: 12 }}>{`${fmtInt(fullCases)} paired cases · ${rates.length} ranked full-suite results`}</div>
      <div style={{ display: "flex", alignItems: "flex-end", height: 212, marginTop: 28, borderBottom: "1px solid #a1b6a6" }}>
        {rates.map((rate, index) => <div key={index} style={{ flexGrow: 1, height: 212 * rate / ceiling, marginRight: 3, background: index < 3 ? "#d4f290" : "#87ac9b" }} />)}
      </div>
      <div style={{ fontSize: 20, color: "#d1ddd0", marginTop: 14 }}>{rates.length ? `Attack success ranged from ${fmtPct(rates[0])} to ${fmtPct(rates[rates.length - 1])} of eligible cases · One bar per result` : "Attack success per eligible case"}</div>
    </div>, size,
  );
}
