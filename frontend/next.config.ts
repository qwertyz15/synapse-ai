import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  devIndicators: { position: "bottom-right" },
  redirects: async () => [{ source: "/documents", destination: "/library", permanent: true }],
};

export default nextConfig;
