import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: process.env.INTERNAL_API_URL || "http://127.0.0.1:8000/api/:path*",
      },
      {
        source: "/static/:path*",
        destination: process.env.INTERNAL_API_URL
          ? `${process.env.INTERNAL_API_URL.replace(/\/api.*$/, '')}/static/:path*`
          : "http://127.0.0.1:8000/static/:path*",
      },
    ];
  },
};

export default nextConfig;
