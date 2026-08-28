import type { NextConfig } from "next";
import path from "node:path";

const backendApiUrl = process.env.BACKEND_API_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  turbopack: {
    root: path.resolve(__dirname),
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${backendApiUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
