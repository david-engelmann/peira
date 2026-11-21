import type { ReactNode } from "react";
import vendorData from "@/lib/vendor-data.json";

export const cardColors = { ...vendorData.design, accent: vendorData.design.subjectFill };

export function ShareCard({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div style={{
      display: "flex", flexDirection: "column", width: "100%", height: "100%",
      backgroundColor: cardColors.ground, color: cardColors.ink, padding: "30px 54px 29px",
      borderTop: `5px solid ${cardColors.accent}`,
    }}>
      <div style={{
        display: "flex", justifyContent: "space-between", alignItems: "center",
        borderBottom: `1px solid ${cardColors.rule}`, paddingBottom: 17,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 13 }}>
          <div style={{ display: "flex", alignItems: "flex-end", gap: 4 }}>
            <div style={{ width: 6, height: 9, backgroundColor: cardColors.field }} />
            <div style={{ width: 6, height: 16, backgroundColor: cardColors.field }} />
            <div style={{ width: 6, height: 23, backgroundColor: cardColors.accent }} />
          </div>
          <span style={{ fontSize: 36, fontWeight: 700, letterSpacing: "-1.6px" }}>peira</span>
        </div>
        <span style={{ fontSize: 19, color: cardColors.quiet }}>{label}</span>
      </div>
      {children}
    </div>
  );
}

export function ShareFooter({ children }: { children: ReactNode }) {
  return (
    <div style={{
      display: "flex", flexShrink: 0, justifyContent: "space-between", alignItems: "center",
      borderTop: `1px solid ${cardColors.rule}`, paddingTop: 16, gap: 24,
      fontSize: 19, color: cardColors.quiet,
    }}>
      {children}
    </div>
  );
}
