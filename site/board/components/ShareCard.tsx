import { readFileSync } from "node:fs";
import path from "node:path";
import PeiraBrand from "./PeiraBrand";
import type { ReactNode } from "react";
import vendorData from "@/lib/vendor-data.json";

export const cardColors = { ...vendorData.design, accent: vendorData.design.subjectFill };

const symbol = `data:image/svg+xml;base64,${readFileSync(path.join(process.cwd(), "app/icon.svg")).toString("base64")}`;

export function ShareCard({ label, children }: { label?: string; children: ReactNode }) {
  return (
    <div style={{
      display: "flex", flexDirection: "column", width: "100%", height: "100%",
      backgroundColor: cardColors.ground, color: cardColors.ink, padding: "30px 54px 29px",
      borderTop: `5px solid ${cardColors.accent}`,
    }}>
      <div style={{
        display: "flex", justifyContent: "space-between", alignItems: "center",
        ...(label && { borderBottom: `1px solid ${cardColors.rule}`, paddingBottom: 17 }),
      }}>
        <PeiraBrand symbol={symbol} ink={cardColors.ink} scale={1.2} />
        {label && <span style={{ fontSize: 19, color: cardColors.quiet }}>{label}</span>}
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
