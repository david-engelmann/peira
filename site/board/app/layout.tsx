import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  metadataBase: new URL("https://peiratrial.dev"),
  title: "Peira decision robustness board",
  description:
    "Attack success rates for decision models on paired benign and attacked cases, with 95 percent intervals, tie brackets, and flagged results. Results first, the explorer as the full record, the findings as evidence.",
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
