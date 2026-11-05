import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  metadataBase: new URL("https://peira-board-proto.pages.dev"),
  title: "peira board redesign prototype",
  description:
    "A live prototype of the redesigned peira board on the published payload. Findings first, one explorer as their evidence.",
  robots: { index: false, follow: false },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
