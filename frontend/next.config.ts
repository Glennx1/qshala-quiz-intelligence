import type { NextConfig } from "next";
import { withSentryConfig } from "@sentry/nextjs/config";

const isVercel = Boolean(process.env.VERCEL || process.env.NEXT_PUBLIC_VERCEL_ENV);

const nextConfig: NextConfig = {
  async rewrites() {
    const rewrites = [
      {
        source: "/api/:path*",
        destination: process.env.INTERNAL_API_URL || "http://127.0.0.1:8000/api/:path*",
      },
    ];

    // Only proxy /static in local dev when NOT on Vercel and an explicit internal API URL is provided.
    // In production and on Vercel, static assets are served directly from public/ via Vercel Edge CDN with 0ms cold start.
    if (!isVercel && process.env.NODE_ENV === "development" && process.env.INTERNAL_API_URL) {
      rewrites.push({
        source: "/static/:path*",
        destination: `${process.env.INTERNAL_API_URL.replace(/\/api.*$/, '')}/static/:path*`,
      });
    }

    return rewrites;
  },
};

// QShala priority plan P2-1. withSentryConfig is safe to apply even when Sentry isn't configured
// yet (NEXT_PUBLIC_SENTRY_DSN unset) -- the SDK init files below are themselves no-ops without a
// DSN, so this wrapper just passes the build through unchanged in that case. org/project/authToken
// are only needed for source-map upload (readable stack traces in the Sentry UI); without them the
// wrapper skips that step and logs a notice, it does not fail the build.
export default withSentryConfig(nextConfig, {
  org: process.env.SENTRY_ORG,
  project: process.env.SENTRY_PROJECT,
  authToken: process.env.SENTRY_AUTH_TOKEN,
  silent: !process.env.CI,
  widenClientFileUpload: true,
});
