import type { Metadata } from "next";
import "./globals.css";
import "./study.css";
import "./explorer-refresh.css";

export const metadata: Metadata = {
  metadataBase: new URL(process.env.BOARD_PUBLIC_ORIGIN ?? "https://peiratrial.dev"),
  title: "Peira | Decision robustness benchmark",
  description:
    "Compare AI decisions before and after an attack. Explore model rankings, attack families, run costs and the evidence behind each result.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <link
          rel="preload"
          href="/fonts/archivo.woff2"
          as="font"
          type="font/woff2"
          crossOrigin="anonymous"
        />
        <link
          rel="preload"
          href="/fonts/jetbrains-mono.woff2"
          as="font"
          type="font/woff2"
          crossOrigin="anonymous"
        />
        {children}
      </body>
    </html>
  );
}
