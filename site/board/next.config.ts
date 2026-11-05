import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "export",
  images: { unoptimized: true },
  /* Prototype build constraint on this small box. One worker
   * keeps the build's write pressure serial while the overlay
   * write fault is active. */
  experimental: { cpus: 1, workerThreads: false },
  /* Directory per route, so each per-model page exports as
   * models/<slug>/index.html and the published /models/<slug>/
   * address is the file itself, not a redirect target. */
  trailingSlash: true,
};

export default nextConfig;
