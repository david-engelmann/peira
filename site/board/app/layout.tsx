import type { Metadata } from "next";
import {
  payload,
  boardDateIso,
  boardVersions,
  modelCounts,
} from "@/lib/payload";
import { fmtInt } from "@/lib/format";
import "./globals.css";

/**
 * The social and search head (criteria SO-01 to SO-04). Every
 * figure in it derives from the payload at build time, and the
 * preview image is generated from the same payload by
 * scripts/gen-og.mjs, so the representations cannot drift apart
 * (SF-04). The canonical address is the production board.
 */
const SITE = "https://peiratrial.dev";
const versions = boardVersions();
const modelTotal = modelCounts().tested;
const fullCases = Math.max(...payload.ranked.map((r) => r.n_cases));

const description = `Attack success rates for ${modelTotal} decision models on ${fmtInt(fullCases)} paired cases, with 95 percent intervals, tie brackets, and flagged results.`;

export const metadata: Metadata = {
  metadataBase: new URL(SITE),
  title: `Peira decision robustness board, attack success on the ${versions.suite} suite`,
  description,
  alternates: { canonical: "/" },
  openGraph: {
    type: "website",
    siteName: "Peira",
    title: "Peira decision robustness board",
    description,
    url: "/",
    images: [
      {
        url: "/og.png",
        width: 1200,
        height: 630,
        alt: "The top of the Peira ranking, attack success rates with 95 percent intervals",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "Peira decision robustness board",
    description,
    images: ["/og.png"],
  },
};

const jsonLd = {
  "@context": "https://schema.org",
  "@type": "Dataset",
  name: "Peira decision robustness board",
  description,
  url: `${SITE}/`,
  version: versions.dataset,
  dateModified: boardDateIso(),
  measurementTechnique: "Paired benign and attacked decision cases",
  variableMeasured: "Attack success rate",
  distribution: [
    {
      "@type": "DataDownload",
      encodingFormat: "application/json",
      contentUrl: `${SITE}/payload.json`,
    },
  ],
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <a className="skip" href="#main">
          Skip to content
        </a>
        {children}
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
        />
      </body>
    </html>
  );
}
