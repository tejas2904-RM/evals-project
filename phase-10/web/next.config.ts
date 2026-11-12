import type { NextConfig } from "next";

const config: NextConfig = {
  // Static export: Vercel serves files from its CDN; no serverless functions, no server-side data, no secrets.
  output: "export",
  trailingSlash: true,
  reactStrictMode: true,
  poweredByHeader: false,
  images: { unoptimized: true },
  agentRules: false,
};

export default config;
