import type { Metadata } from "next";
import { initializeTheme } from "@/lib/theme";
import "./globals.css";
import "./study.css";
import "./explorer-refresh.css";

export const metadata: Metadata = {
  metadataBase: new URL(
    process.env.BOARD_PUBLIC_ORIGIN ?? process.env.CF_PAGES_URL ??
      (process.env.NODE_ENV === "development" ? "http://localhost:3000" : "https://peiratrial.dev"),
  ),
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: initializeTheme }} />
      </head>
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
