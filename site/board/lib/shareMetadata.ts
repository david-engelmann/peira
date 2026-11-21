import type { Metadata } from "next";

export const shareCardSize = { width: 1200, height: 630 };

export function shareMetadata({ title, description, path, imagePath, imageAlt }: {
  title: string;
  description: string;
  path: string;
  imagePath: string;
  imageAlt: string;
}): Metadata {
  const image = { url: imagePath, alt: imageAlt };
  return {
    title,
    description,
    alternates: { canonical: path },
    openGraph: {
      type: "website",
      siteName: "Peira",
      url: path,
      title,
      description,
      images: [{ ...image, ...shareCardSize, type: "image/png" }],
    },
    twitter: {
      card: "summary_large_image",
      title,
      description,
      images: [image],
    },
  };
}
