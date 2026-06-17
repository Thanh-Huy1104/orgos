import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  allowedDevOrigins: ["192.168.5.197", "100.85.103.107", "icarus"],
  experimental: {
    serverActions: {
      allowedOrigins: ["100.85.103.107", "icarus"],
    },
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://localhost:8420/api/:path*",
      },
    ];
  },
};

export default nextConfig;
