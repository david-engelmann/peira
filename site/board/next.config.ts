import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "export",
  images: { unoptimized: true },
  /* Directory per route, so each per-model page exports as
   * models/<slug>/index.html and the published /models/<slug>/
   * address is the file itself, not a redirect target. */
  trailingSlash: true,
};

export default nextConfig;
