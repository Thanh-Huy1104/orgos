import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  allowedDevOrigins: ["192.168.5.197"],
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
