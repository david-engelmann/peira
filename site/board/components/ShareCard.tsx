import type { ReactNode } from "react";

export const cardColors = {
  ground: "#123a31",
  ink: "#f6f7ec",
  accent: "#d4f290",
  quiet: "#bed2c4",
  rule: "#607e6f",
  flagged: "#ffd4a6",
};

export function ShareCard({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div style={{
      display: "flex", flexDirection: "column", width: "100%", height: "100%",
      background: cardColors.ground, color: cardColors.ink, padding: "44px 58px",
    }}>
      <div style={{
        display: "flex", justifyContent: "space-between", alignItems: "center",
        borderBottom: `1px solid ${cardColors.rule}`, paddingBottom: 16,
      }}>
        <span style={{ fontSize: 40, fontWeight: 700, letterSpacing: "-2px" }}>peira</span>
        <span style={{ fontSize: 23, color: cardColors.quiet }}>{label}</span>
      </div>
      {children}
    </div>
  );
}
